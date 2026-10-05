"""Stand-in for an existing Notification API. Nothing here knows about Temporal.

It behaves like a real internal service:
- requires an API key (only the Nexus handler worker has it)
- honors an Idempotency-Key header, so retries never send twice
- can be put into maintenance (503) or bug (500) mode from the demo UI

Routes marked with `x-nexus` in the OpenAPI spec become Nexus operations.
`make codegen` reads that spec and generates the Nexus contract.

Run: uvicorn services.notification_api.app:app --port 8001
"""

import uuid
from datetime import datetime, timezone
from enum import Enum

from fastapi import FastAPI, Header, HTTPException, Response, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from common import config

app = FastAPI(title="Notification API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)  # declared in the OpenAPI spec

TEMPLATES = {"task_assigned", "task_reassigned", "change_approved", "change_rejected", "change_expired"}


class Channel(str, Enum):
    email = "email"
    in_app = "in_app"


class NotificationRequest(BaseModel):
    recipient: str = Field(description="User the notification is for.")
    channel: Channel
    template: str = Field(description="One of: " + ", ".join(sorted(TEMPLATES)))
    subject: str | None = Field(default=None, description="Optional subject line.")
    reference: str | None = Field(default=None, description="Business reference, e.g. a task ID.")


class NotificationReceipt(BaseModel):
    notification_id: str
    status: str
    recipient: str
    channel: Channel
    replayed: bool = Field(default=False, description="True when the Idempotency-Key matched an earlier send.")


class Mode(BaseModel):
    mode: str = Field(description="ok | maintenance | bug")


state = {"mode": "ok", "requests": 0, "rejected": 0, "replays": 0}
outbox: list[dict] = []
by_idempotency_key: dict[str, dict] = {}


@app.post(
    "/v1/notifications",
    status_code=201,
    response_model=NotificationReceipt,
    operation_id="send",
    openapi_extra={"x-nexus": {"service": "notifications.v1", "operation": "send"}},
)
def send(
    req: NotificationRequest,
    response: Response,
    x_api_key: str | None = Security(api_key_scheme),
    idempotency_key: str | None = Header(default=None),
) -> dict:
    """Send one notification."""
    state["requests"] += 1
    if x_api_key != config.NOTIFICATION_API_KEY:
        raise HTTPException(401, "missing or invalid X-API-Key")
    if state["mode"] == "maintenance":
        state["rejected"] += 1
        raise HTTPException(503, "Notification API is down for maintenance")
    if state["mode"] == "bug":
        state["rejected"] += 1
        raise HTTPException(500, "NullPointerException in TemplateRenderer (simulated bug)")
    if req.template not in TEMPLATES:
        raise HTTPException(400, f"unknown template '{req.template}'")

    if idempotency_key and idempotency_key in by_idempotency_key:
        state["replays"] += 1
        response.status_code = 200
        return {**by_idempotency_key[idempotency_key], "replayed": True}

    sent = {
        "notification_id": f"N-{uuid.uuid4().hex[:8]}",
        "status": "SENT",
        "recipient": req.recipient,
        "channel": req.channel,
        "replayed": False,
    }
    outbox.insert(0, {**sent, "template": req.template, "reference": req.reference,
                      "sent_at": datetime.now(timezone.utc).isoformat(), "idempotency_key": idempotency_key})
    if idempotency_key:
        by_idempotency_key[idempotency_key] = sent
    return sent


@app.get("/v1/notifications")
def list_sent(limit: int = 50) -> list[dict]:
    """The outbox: every notification actually sent, newest first."""
    return outbox[:limit]


@app.get("/admin/status")
def status() -> dict:
    return {**state, "sent": len(outbox)}


@app.post("/admin/mode")
def set_mode(m: Mode) -> dict:
    if m.mode not in {"ok", "maintenance", "bug"}:
        raise HTTPException(400, "mode must be ok, maintenance or bug")
    state["mode"] = m.mode
    return status()


@app.post("/admin/reset")
def reset() -> dict:
    state.update(mode="ok", requests=0, rejected=0, replays=0)
    outbox.clear()
    by_idempotency_key.clear()
    return status()
