"""Thin HTTP gateway: any HTTP client can call a Nexus operation.

    POST /{endpoint}/{service}/{operation}?wait_s=5   (header: Idempotency-Key)
    GET  /operations/{operation_id}
    GET  /operations

The gateway is a normal Temporal client in the caller namespace. Each POST
starts a Standalone Nexus Operation, then waits up to `wait_s` seconds:
- finished in time: 200 with the result, like a normal API call
- still running:    202 with a status URL, so the caller polls instead of timing out

Only operations in the catalog are reachable, so the gateway is not an open
proxy. It also serves the demo web UI at /.

Run: uvicorn gateway.app:app --port 8000
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse
from temporalio.client import Client, NexusOperationFailureError, NexusOperationHandle
from temporalio.common import (
    NexusOperationExecutionStatus as Status,
    NexusOperationIDConflictPolicy,
    NexusOperationIDReusePolicy,
)
from temporalio.exceptions import NexusOperationAlreadyStartedError

from common import config
from gateway.catalog import CATALOG, find

STATIC = Path(__file__).parent / "static"
MAX_WAIT_S = 25
OWNER_VIEW = os.environ.get("GATEWAY_OWNER_VIEW", "true").lower() != "false"
clients: dict[str, Client] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    clients["caller"] = await config.connect(config.CALLER_NAMESPACE)
    yield


app = FastAPI(title="Nexus HTTP gateway", lifespan=lifespan)


def caller() -> Client:
    return clients["caller"]


def error_message(err: BaseException | None) -> str | None:
    """The innermost distinct message, which is the one a person needs to read.

    Contract violations caught by the generated validators carry one entry per
    bad field in their details; those are spelled out.
    """
    messages: list[str] = []
    while err is not None:
        msg = str(err)
        details = getattr(err, "details", None) or ()
        violations = details[0] if details and isinstance(details[0], list) else []
        if violations and all(isinstance(v, dict) and "path" in v for v in violations):
            msg = "contract violation: " + "; ".join(f"{v['path']}: {v['reason']}" for v in violations)
        if msg and msg not in messages:
            messages.append(msg)
        err = err.__cause__
    return messages[-1] if messages else None


def handler_link(d) -> dict | None:
    """The workflow that is doing the work, from the link Nexus records on the operation."""
    for link in d.raw_description.links:
        if link.HasField("workflow_event"):
            w = link.workflow_event
            return {
                "namespace": w.namespace,
                "workflow_id": w.workflow_id,
                "run_id": w.run_id,
                "ui_url": f"{config.TEMPORAL_UI_URL}/namespaces/{w.namespace}/workflows/{w.workflow_id}/{w.run_id}/history",
            }
    return None


async def owner_view(link: dict) -> dict | None:
    """What the owning team sees: retries inside its workflow.

    Needs read access to the handler's namespace, which a caller team would
    not normally have. On by default for the local demo; set
    GATEWAY_OWNER_VIEW=false to show only what the caller's namespace offers.
    """
    if not OWNER_VIEW:
        return None
    ns = link["namespace"]
    if ns not in clients:
        clients[ns] = await config.connect(ns)
    desc = await clients[ns].get_workflow_handle(link["workflow_id"], run_id=link["run_id"]).describe()
    pending = [
        {
            "activity": p.activity_type.name,
            "attempt": p.attempt,
            "last_error": p.last_failure.message or None,
            "next_attempt_at": p.next_attempt_schedule_time.ToDatetime().isoformat() + "Z"
            if p.HasField("next_attempt_schedule_time") else None,
        }
        for p in desc.raw_description.pending_activities
    ]
    return {"workflow_status": desc.status.name if desc.status else None, "pending_activities": pending}


async def summarize(handle: NexusOperationHandle) -> dict:
    d = await handle.describe()
    running = d.status == Status.RUNNING
    out = {
        "operation_id": d.operation_id,
        "run_id": d.run_id,
        "endpoint": d.endpoint,
        "service": d.service,
        "operation": d.operation,
        "status": d.status.name,
        "state": d.state.name if running else None,
        "attempt": d.attempt,
        "scheduled_at": d.schedule_time.isoformat() if d.schedule_time else None,
        "closed_at": d.close_time.isoformat() if d.close_time else None,
        "expires_at": d.expiration_time.isoformat() if d.expiration_time else None,
        "next_attempt_at": d.next_attempt_schedule_time.isoformat() if running and d.next_attempt_schedule_time else None,
        "last_error": error_message(d.last_attempt_failure),
        "status_url": f"/operations/{d.operation_id}",
        "handler": handler_link(d),
    }
    if out["handler"] and running:
        out["owner_view"] = await owner_view(out["handler"])
    if d.status == Status.COMPLETED:
        out["result"] = await handle.result()
    elif not running:
        try:
            await handle.result()
        except NexusOperationFailureError as e:
            out["error"] = error_message(e.cause)
    return out


@app.post("/{endpoint}/{service}/{operation}")
async def start(
    endpoint: str,
    service: str,
    operation: str,
    body: dict,
    response: Response,
    idempotency_key: str | None = Header(default=None),
    wait_s: float = 5,
) -> dict:
    entry = find(endpoint, service, operation)
    if entry is None:
        raise HTTPException(404, f"{endpoint}/{service}/{operation} is not in the catalog")
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required; it becomes the operation ID")

    nexus = caller().create_nexus_client(service=service, endpoint=endpoint)
    try:
        handle = await nexus.start_operation(
            operation,
            body,
            id=idempotency_key,
            result_type=dict,
            id_conflict_policy=NexusOperationIDConflictPolicy.USE_EXISTING,  # retry while running: attach
            id_reuse_policy=NexusOperationIDReusePolicy.REJECT_DUPLICATE,  # retry after it closed: no new run
            schedule_to_close_timeout=timedelta(seconds=entry["timeout_s"]),
            summary=f"via gateway: {operation}",
        )
        replayed = False
    except NexusOperationAlreadyStartedError:
        handle = caller().get_nexus_operation_handle(idempotency_key, result_type=dict)
        replayed = True

    try:
        await asyncio.wait_for(handle.result(), timeout=min(max(wait_s, 0), MAX_WAIT_S))
    except (asyncio.TimeoutError, NexusOperationFailureError):
        pass
    out = await summarize(handle)
    out["replayed"] = replayed
    response.status_code = 202 if out["status"] == "RUNNING" else 200
    return out


@app.get("/operations/{operation_id}")
async def get_operation(operation_id: str) -> dict:
    return await summarize(caller().get_nexus_operation_handle(operation_id, result_type=dict))


@app.get("/operations")
async def list_operations(limit: int = 25) -> list[dict]:
    endpoints = sorted({e["endpoint"] for e in CATALOG})
    query = " OR ".join(f"Endpoint = '{e}'" for e in endpoints)
    rows = []
    async for op in caller().list_nexus_operations(query, limit=limit):
        rows.append({
            "operation_id": op.operation_id,
            "endpoint": op.endpoint,
            "service": op.service,
            "operation": op.operation,
            "status": op.status.name,
            "scheduled_at": op.schedule_time.isoformat() if op.schedule_time else None,
            "duration_s": op.execution_duration.total_seconds() if op.execution_duration else None,
        })
    return rows


@app.get("/catalog")
async def catalog() -> list[dict]:
    return CATALOG


@app.get("/config")
async def ui_config() -> dict:
    return {
        "caller_namespace": config.CALLER_NAMESPACE,
        "notification_api_url": config.NOTIFICATION_API_URL,
        "task_center_url": config.TASK_CENTER_URL,
        "temporal_ui_url": config.TEMPORAL_UI_URL,
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
