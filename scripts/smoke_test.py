"""End-to-end checks for every scenario. Run against a live `make up`:  make smoke

Each check prints PASS or FAIL. The script exits non-zero if any check fails.
"""

import asyncio
import sys
import time
import uuid

import httpx

from common import config
from teams.billing.workflows import FeeChange, FeeChangeWorkflow

GW, API, TC = config.GATEWAY_URL, config.NOTIFICATION_API_URL, config.TASK_CENTER_URL
RUN = uuid.uuid4().hex[:4]  # keeps IDs unique across runs against the same dev server
failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))


def wait_for(fn, timeout=30.0, every=0.5):
    end = time.time() + timeout
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(every)
    return None


def call(endpoint, service, operation, body, key, wait_s=5):
    r = httpx.post(f"{GW}/{endpoint}/{service}/{operation}", params={"wait_s": wait_s},
                   headers={"Idempotency-Key": key}, json=body, timeout=40)
    return r.status_code, r.json()


def op(op_id):
    return httpx.get(f"{GW}/operations/{op_id}", timeout=10).json()


def sent():
    return httpx.get(f"{API}/v1/notifications", timeout=10).json()


def mode(m):
    httpx.post(f"{API}/admin/mode", json={"mode": m}, timeout=10)


def task_for(reference):
    return next((t for t in httpx.get(f"{TC}/v1/tasks", timeout=10).json() if t["reference"] == reference), None)


NOTIFY = (config.NOTIFY_ENDPOINT, "notifications.v1", "send")
INPUT = (config.TASKS_ENDPOINT, "task-center.v1", "request_input")


def scenario_1() -> None:
    print("\nScenario 1: reliable API delivery")
    httpx.post(f"{API}/admin/reset", timeout=10)
    body = {"recipient": "dana", "channel": "email", "template": "task_assigned", "reference": f"s1-{RUN}"}

    code, r = call(*NOTIFY, body, f"s1-happy-{RUN}")
    check("healthy API: result returned inline (200)", code == 200 and r["status"] == "COMPLETED", f"{code} {r.get('status')}")
    mine = lambda: [n for n in sent() if n["reference"] == f"s1-{RUN}"]
    check("exactly one email sent", len(mine()) == 1)

    code, r = call(*NOTIFY, body, f"s1-happy-{RUN}")
    check("same Idempotency-Key again: same operation, no second email", r.get("replayed") and len(mine()) == 1)

    code, r = call(*NOTIFY, {**body, "template": "task_asigned"}, f"s1-typo-{RUN}")
    check("API rejects a bad template: fails on the first attempt",
          r["status"] == "FAILED" and "unknown template" in (r.get("error") or ""), str(r.get("error")))

    code, r = call(*NOTIFY, {**body, "channel": "sms"}, f"s1-contract-{RUN}")
    check("contract violation (channel 'sms'): rejected before the API is called",
          r["status"] == "FAILED" and "channel" in (r.get("error") or "") and len(mine()) == 1, str(r.get("error")))

    mode("maintenance")
    code, r = call(*NOTIFY, {**body, "recipient": "lee"}, f"s1-outage-{RUN}", wait_s=1)
    check("API down: caller gets 202 and a status URL", code == 202 and r["status_url"].endswith(f"s1-outage-{RUN}"))
    retrying = wait_for(lambda: (op(f"s1-outage-{RUN}").get("owner_view") or {}).get("pending_activities", [{}])[0].get("attempt", 0) >= 3)
    check("owner's view shows the handler retrying", bool(retrying))
    mode("ok")
    done = wait_for(lambda: op(f"s1-outage-{RUN}")["status"] == "COMPLETED", timeout=40)
    lee = [n for n in sent() if n["recipient"] == "lee" and n["reference"] == f"s1-{RUN}"]
    check("API back: delivered exactly once", bool(done) and len(lee) == 1, f"{len(lee)} emails to lee")


def scenario_2() -> None:
    print("\nScenario 2: workflow as a service")
    httpx.post(f"{TC}/admin/reset", timeout=10)
    ref = f"release-{RUN}"
    req = {"reference": ref, "requested_by": "ci", "assignee": "dana", "kind": "approve_reject",
           "title": "Approve production release", "due_in_seconds": 600}

    code, r = call(*INPUT, req, f"ci-{ref}", wait_s=1)
    check("CI asks for approval over HTTP: 202 while waiting for a person", code == 202)
    code2, _ = call(*INPUT, req, f"ci-{ref}-retry", wait_s=1)
    task = wait_for(lambda: task_for(ref))
    check("second request for the same reference: still one task", code2 == 202 and task is not None
          and sum(1 for t in httpx.get(f"{TC}/v1/tasks").json() if t["reference"] == ref) == 1)
    check("Task Center notified the assignee", wait_for(lambda: any(
        n["reference"] == task["task_id"] and n["template"] == "task_assigned" for n in sent())))

    httpx.post(f"{TC}/v1/tasks/{task['task_id']}/reassign", json={"assignee": "lee"}, timeout=10)
    check("reassigned: new assignee notified", wait_for(lambda: any(
        n["reference"] == task["task_id"] and n["recipient"] == "lee" and n["template"] == "task_reassigned" for n in sent())))

    httpx.post(f"{TC}/v1/tasks/{task['task_id']}/respond", json={"outcome": "approved", "responded_by": "lee"}, timeout=10)
    first = wait_for(lambda: (lambda o: o if o["status"] == "COMPLETED" else None)(op(f"ci-{ref}")))
    second = wait_for(lambda: (lambda o: o if o["status"] == "COMPLETED" else None)(op(f"ci-{ref}-retry")))
    check("person approves: the answer comes back as the result",
          bool(first) and first["result"]["outcome"] == "approved" and first["result"]["responded_by"] == "lee")
    check("both requests for the reference got the same answer",
          bool(second) and second["result"]["task_id"] == first["result"]["task_id"])

    code, r = call(*INPUT, {**req, "reference": f"expiring-{RUN}", "due_in_seconds": 2}, f"ci-expiring-{RUN}", wait_s=1)
    expired = wait_for(lambda: (lambda o: o if o["status"] == "COMPLETED" else None)(op(f"ci-expiring-{RUN}")), timeout=20)
    check("nobody answers before the deadline: outcome 'expired'", bool(expired) and expired["result"]["outcome"] == "expired")


async def team_workflow() -> None:
    print("\nA team's workflow using both capabilities")
    client = await config.connect(config.BILLING_NAMESPACE)
    change = FeeChange(change_id=f"smoke-{RUN}", account="ACME-001", new_fee_bps=85, requested_by="sam", approver="dana")
    handle = await client.start_workflow(FeeChangeWorkflow.run, change, id=f"fee-change-smoke-{RUN}",
                                         task_queue=config.BILLING_TASK_QUEUE)
    task = await asyncio.to_thread(wait_for, lambda: task_for(f"fee-change-smoke-{RUN}"))
    check("billing workflow asked Task Center for approval", task is not None)
    httpx.post(f"{TC}/v1/tasks/{task['task_id']}/respond", json={"outcome": "approved", "responded_by": "dana"}, timeout=10)
    result = await asyncio.wait_for(handle.result(), timeout=30)
    check("approval came back and the change was applied", result.applied and result.decided_by == "dana")
    check("requester notified through the notifications endpoint", any(
        n["recipient"] == "sam" and n["template"] == "change_approved" and n["reference"] == f"fee-change-smoke-{RUN}" for n in sent()))


if __name__ == "__main__":
    scenario_1()
    scenario_2()
    asyncio.run(team_workflow())
    print(f"\n{'all checks passed' if not failures else f'{failures} check(s) failed'}")
    sys.exit(1 if failures else 0)
