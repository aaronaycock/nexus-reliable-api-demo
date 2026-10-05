# How it works

This demo puts Temporal Nexus in front of two existing capabilities, a Notification API and a human-in-the-loop step, so that any team can call them reliably. This page covers the design decisions behind it, in the order you would make them for your own services.

- [The shape](#the-shape)
- [Nexus terms in Temporal terms](#nexus-terms-in-temporal-terms)
- [Naming](#naming)
- [Environments and regions](#environments-and-regions)
- [Sync or async](#sync-or-async)
- [Retries and errors](#retries-and-errors)
- [Never doing the work twice](#never-doing-the-work-twice)
- [Security](#security)
- [Watching the lifecycle](#watching-the-lifecycle)
- [Contract first, and what you still write](#contract-first-and-what-you-still-write)
- [Cancel and terminate](#cancel-and-terminate)
- [Pre-release limits](#pre-release-limits)

## The shape

![How the demo's parts talk](architecture.svg)

Blue arrows start a Standalone Nexus Operation, black arrows are routing, activity calls and signals, and green dashed arrows carry results back to the operation that asked. ([PNG version](architecture.png) for slides and chat.)

Three kinds of code, owned by three kinds of team:

| Piece | Owner | Lives in | What it does |
|---|---|---|---|
| **Contract** (`contracts/`) | The capability's team, reviewed by a platform team | Shared repo or package | Names the service and operations, and types their inputs and outputs |
| **Handler** (`handlers/`) | The capability's team | Its own namespace | Does the work. For a facade over an existing API it is **generated** from the API's OpenAPI spec. For anything with real logic (like waiting for a person) the team writes it |
| **Caller** (`services/task_center`, `teams/billing`, `gateway/`, `examples/`) | Anyone allowed | Its own namespace | Names an endpoint, a service, an operation and a business key. Nothing else |

A caller never learns which namespace, task queue or workflow serves it. A team can move or rewrite its handler without telling its callers.

## Nexus terms in Temporal terms

| Nexus | Think of it as |
|---|---|
| **Endpoint** | A named, access-controlled route to one namespace and task queue |
| **Service** | An interface: a named set of operations with typed inputs and outputs |
| **Operation (async)** | Starting a workflow and getting its result back, delivered to the caller by Nexus |
| **Operation (sync)** | A short call the handler's worker answers inline, within a 10-second limit |
| **Handler** | Worker code registered on the endpoint's task queue, like registering workflows and activities |
| **Standalone Nexus Operation** | Starting one operation from a client. Like starting a workflow, but the record lives in the caller's namespace and there is no caller workflow to write |
| **Operation ID** | The workflow ID: the business key Temporal deduplicates on |
| **ID reuse and conflict policies** | The same as the workflow ID reuse and conflict policies |
| **Schedule-to-close timeout** | A workflow execution timeout: how long Temporal keeps trying |
| **Caller namespace allowlist** | Namespace permissions, applied per endpoint |

## Naming

| Name | Example | Rule |
|---|---|---|
| Caller namespace | `api-callers` | One per trust boundary. The endpoint allowlist works per caller namespace, so callers in the same namespace get the same access |
| Endpoint | `notifications-prod-ch` | Name the **capability and the stamp** (environment, plus region), never the namespace. Endpoint names are unique per account, so the stamp keeps environments and regions apart. Letters, digits and hyphens only |
| Service | `notifications.v1` | Put the **major version** in the name. A breaking change ships as `notifications.v2` next to v1, on the same endpoint, and callers move when ready |
| Operation | `send`, `request_input` | A stable verb |
| Operation ID | `notify-T-42-3`, `release-2026-10-05` | A **business key** for the event, never a random UUID. It is what makes a retried request harmless |

**One endpoint can carry several services.** An endpoint routes to one namespace and task queue, and every service the workers on that queue register is reachable through it. That is how `v1` and `v2` coexist, and how a team can publish several capabilities behind one endpoint per environment.

## Environments and regions

A **stamp** is one environment in one region: `dev`, `staging-us`, `staging-ch`, `prod-us`, `prod-ch`. Each team runs one namespace per stamp, and everything in this demo is named per stamp:

| | Pattern | `prod-ch` example |
|---|---|---|
| Team namespace | `<team>-<stamp>` | `notifications-prod-ch` |
| Endpoint | `<capability or team>-<stamp>` | `notifications-prod-ch` |
| Endpoint allowlist | only caller namespaces **in the same stamp** | `api-callers-prod-ch`, `billing-prod-ch` |
| Caller configuration | one setting | `NEXUS_ENV=prod-ch` |

**The allowlist keeps stamps apart.** A `dev` caller cannot reach a `prod` endpoint, and a US caller cannot reach a Swiss one, because neither is on that endpoint's allowlist. Data residency holds by construction, not by convention.

**Callers change one setting.** `NEXUS_ENV` decides every endpoint name the demo's callers use (`common/config.py`). `NEXUS_ENV=prod-ch make up` brings the whole demo up against `notifications-prod-ch` and `task-center-prod-ch`, and `NEXUS_ENV=prod-ch make smoke` passes. No caller code mentions an environment or a region. (Locally the demo stamps only endpoint names and keeps one set of namespaces; in a real account the namespaces are per stamp too, as `make plan-endpoints` shows.)

**How many endpoints?** Run `make plan-endpoints`. It reads [`deploy/endpoints.yaml`](../deploy/endpoints.yaml), the teams, what they publish and who calls it, and prints every endpoint, target and allowlist for two strategies. Add `--terraform OUT.tf` to write them as Terraform.

| Strategy | Endpoint per | Count | Choose it when |
|---|---|---|---|
| **Per capability** | service × stamp | capabilities × stamps | Few capabilities, or each needs its own allowlist |
| **Per team** | publishing team × stamp | teams × stamps | Many capabilities. The team's worker registers all its services on one task queue, so one endpoint reaches them all |
| Router worker | stamp, or team × stamp | lowest | Only if one endpoint must reach work on several task queues. It adds a hop and a component everyone shares |

With 5 stamps, one endpoint per capability reaches the default limit of 100 endpoints per account (see [Cloud limits](https://docs.temporal.io/cloud/limits); it can be raised) at 20 capabilities. One endpoint per team stays at teams × 5.

> **Our recommendation** (pending Temporal's official guidance):
> - **Start with one endpoint per capability per stamp.** It's the simplest to reason about, and each capability gets its own allowlist.
> - **Move to one endpoint per team per stamp as capabilities grow.** Callers don't change, because the service name, not the endpoint, selects the contract, so only the endpoint setting moves.
> - **Avoid router workers.** They concentrate every team's traffic in one shared component for little gain.
> - **Ask for a higher endpoint limit** before you need it, not when you hit it.

## Sync or async

A sync operation answers inside the request, and the handler has under 10 seconds to do it. An async operation starts something durable, usually a workflow, and Nexus delivers the result to the caller when it finishes.

| Use sync when | Use async when |
|---|---|
| One call, reliably fast, safe to repeat | The downstream can be slow or down for a while |
| | The work has several steps |
| | A person is involved |
| | You want your own retry policy |

Both operations in this demo are async:
- **`notifications.v1 / send`** starts a generated workflow whose activity calls the Notification API. A maintenance window can last longer than any request.
- **`task-center.v1 / request_input`** starts `HumanInputWorkflow`, which waits for a person.

Keeping slow or unreliable work out of sync handlers also protects the endpoint. Nexus has a [circuit breaker](https://docs.temporal.io/nexus/operations) per caller namespace and endpoint pair: by default, 5 consecutive retryable errors open it, and requests stop for a while. In an async handler, the API's errors stay inside the handler's workflow and never reach the breaker.

## Retries and errors

Retries happen in two places:

1. **Starting the operation.** Temporal retries delivery of the start request to the handler on retryable errors until it succeeds or the operation's schedule-to-start or schedule-to-close timeout passes. You see these as the operation's *attempts*.
2. **Inside the handler.** Once the handler's workflow is running, its activity retry policy governs calls to the real API (the `retry` and `deadline_s` settings in `contracts/facades.yaml`). You see these in the owning team's workflow, and in the web UI's owner's view.

Every generated facade makes the same decision about what is worth retrying, in one shared place (`common/http_facade.py`):

| Downstream says | Meaning | The handler raises | Result |
|---|---|---|---|
| `2xx` | Done | (returns the receipt) | Operation completes |
| `400`, `401`, `403`, `404`, `409`, `422` | The request is wrong; retrying cannot help | Non-retryable `ApplicationError` | Operation fails at once, with the API's message |
| `429`, `5xx`, connection refused | The API is unhealthy | Retryable `ApplicationError` | Backoff until it recovers or the deadline passes |
| Input breaks the contract | The caller sent the wrong shape | (the generated validator does it) | Fails at once with `BAD_REQUEST`, one entry per bad field. The API is never called |

If a permanent error is left retryable, the operation retries until its deadline and then reports a timeout instead of the real cause. That is the most common mistake when wrapping an API.

Set **schedule-to-close to the business deadline.** An email about a task assignment is worth an hour of retries, not sixty days.

## Never doing the work twice

Nexus delivery is at least once, so every layer needs a key that stays the same across retries.

| Layer | Key | Where |
|---|---|---|
| Caller → Temporal | Operation ID (a business key) | `services/task_center/app.py`, `gateway/app.py` |
| Temporal → handler | The handler workflow's ID | `handlers/*/worker.py` |
| Handler → API | `Idempotency-Key` header, set to the handler workflow's ID | `common/http_facade.py` |

The policies on the operation ID matter:

- **Conflict policy, `USE_EXISTING`:** a second start with the same ID while the first is **still running** attaches to it.
- **Reuse policy, `REJECT_DUPLICATE`:** a second start with the same ID after the first has **closed** is refused. The default, `ALLOW_DUPLICATE`, would start a new run and send a second email.

The gateway sets both, and treats a refused duplicate as "already done, here is the status URL". `make smoke` checks that three identical POSTs produce one email.

The human-in-the-loop handler adds one more rule: one workflow per business reference (`id=f"hitl-{reference}"` with `USE_EXISTING`). Two callers asking about the same reference share one task, and both get the same answer.

## Security

- **The endpoint allowlist decides who can call.** On Temporal Cloud, each endpoint lists the caller namespaces allowed to reach it, including namespaces whose workflows call it. See [Nexus security](https://docs.temporal.io/nexus/security). (The local dev server does not enforce allowlists.)
- **Credentials stay with the handler.** Only the Notification team's worker has the Notification API key (`NOTIFICATION_API_KEY`). Callers never see it, and it is not in any operation's input. Anything in an operation's input is stored in event history, so secrets never belong there.
- **The gateway is not an open proxy.** It only routes to operations listed in its catalog (`gateway/catalog.py`), which is built from the contracts. Put your own authentication in front of it.
- **Split caller namespaces by trust boundary.** Access is per caller namespace today, and handlers do not see a verified caller identity. Callers that need different access belong in different caller namespaces.
- **Each team signals only its own workflows.** Task Center signals the waiting `HumanInputWorkflow` in its own namespace, so it needs no access to the namespaces of the teams that ask it for input.

## Watching the lifecycle

**What the caller sees, in its own namespace:**
- List, count and describe operations by endpoint, service, operation and status. The gateway's `/operations` and the CLI's `temporal nexus operation list|describe|count` both use this.
- On Temporal Cloud, standalone operations appear in the Nexus operation metrics with `temporal_workflow_type="__temporal_standalone_nexus_operation__"` ([metrics reference](https://docs.temporal.io/cloud/metrics/openmetrics/metrics-reference)).
- Each operation records a **link to the workflow handling it**. The gateway returns it as `handler`, and the web UI shows it as a link into the Temporal UI.

**What the owning team sees:** its own workflow, including activity attempts and the API's last error. The web UI's *owner's view* reads it through the link. That needs read access to the handler's namespace, which a caller team would not normally have, so set `GATEWAY_OWNER_VIEW=false` to show only what a caller can see.

**For a caller's own UI:** poll `GET /operations/{id}` and show status, result or error. The caller doesn't need to track state of its own.

> **Our recommendation** (pending Temporal's official guidance):
> - **Callers watch their own operations,** in their own caller namespace: list, describe, metrics, or a gateway like this one. Give caller teams read access to their caller namespace, not to the namespaces of the teams they call.
> - **Owners watch their own workflows,** in their own namespace.
> - **The link joins the two views** when someone with access to both needs to follow a call end to end.

## Contract first, and what you still write

```
Notification API (FastAPI) ──> openapi.json ──┬─> notifications.nexusrpc.yaml ──> nexgen ──> contracts/gen/notifications/  (contract)
                                              └─> + contracts/facades.yaml ───> gen_facade ──> handlers/notifications/   (handler)
task-center.nexusrpc.yaml (hand-written) ───────────────────────────> nexgen ──> contracts/gen/task_center/    (contract)
```

`make codegen` runs the whole chain:

1. **The API's owner marks which routes to publish** with an `x-nexus` extension in its OpenAPI spec. The spec already says the rest, in standard OpenAPI: method, path, request and response types, the API-key header (an `apiKey` security scheme), and the `Idempotency-Key` header.
2. **`scripts/openapi_to_nexus.py` writes the Nexus contract.** Request bodies become inputs, and responses become outputs. Headers stay out, because the handler owns credentials and idempotency.
3. **[nexgen](https://github.com/temporalio/nexgen), Temporal's contract generator, turns each `.nexusrpc.yaml` into code:** typed dataclasses, a service definition, and validators that run on both sides of the wire. The same file also generates Go, Java and TypeScript.
4. **`scripts/gen_facade.py` writes the complete handler** (worker, workflow and activity) from the spec and the facade's settings in [`contracts/facades.yaml`](../contracts/facades.yaml). The settings cover the namespace, task queue, base URL, credential, retry policy and deadline. The generated code calls [`common/http_facade.py`](../common/http_facade.py), the one hand-written runtime every facade shares, which holds the retry rules, the credential handling and the idempotency key.

**So, does anyone still write worker code?**

| You are publishing | You write | Generated |
|---|---|---|
| **An existing API, as is** (`notifications.v1`) | An `x-nexus` tag on each route, and one entry in `facades.yaml` | The contract, and the whole handler and worker |
| **A capability with its own logic** (`task-center.v1`: create a task, wait for a person, handle a deadline) | The contract (`.nexusrpc.yaml`) and the workflow | The contract's types and service definition |
| **Calling either** | Nothing new: one SDK call, or one HTTP request | The types callers use |

Every facade gets the same behavior because the shared runtime is written once: a 4xx fails fast, a 5xx retries, the API key never leaves the worker, and the Idempotency-Key is stable across retries.

> nexgen is pre-release. Its accepted schema subset and generated code may change, so the version is pinned in `scripts/codegen.sh`. The facade generator handles JSON request and response bodies and `{param}` path segments filled from the request.

## Cancel and terminate

- **Cancel** reaches the handler only after the operation has **started**. A cancel requested while the start is still being retried waits, and the retries continue.
- **Terminate** ends a standalone operation immediately, whatever its state. Use it as the escape hatch.
- **A deadline that fits the business** (schedule-to-close) ends the operation without anyone stepping in.

## Pre-release limits

Standalone Nexus Operations are pre-release. At the time of writing the [documentation](https://docs.temporal.io/standalone-nexus-operation) lists these as not yet supported:
- Delete and reset.
- Batch `--query` support for cancel, terminate and delete.
- Operator actions from the UI's list page.
- High-availability (multi-region) namespaces.

Check the documentation for the current state before building on it.
