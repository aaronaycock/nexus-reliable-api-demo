"""Stand-in for Task Center: the system of record for human tasks.

This is a normal web service, not a Temporal worker. It uses Temporal in two
ways, both plain client calls:

1. Notifications (scenario 1). When a task is created or reassigned, it starts
   a Standalone Nexus Operation on the notifications endpoint and moves on.
   Temporal owns delivery from there. No Lambda timeout, no lost notifications.
2. Answers (scenario 2). When a person responds, it signals the
   HumanInputWorkflow waiting in Task Center's own namespace.

Run: uvicorn services.task_center.app:app --port 8002
"""

import dataclasses
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from temporalio.client import Client
from temporalio.common import NexusOperationIDReusePolicy
from temporalio.exceptions import NexusOperationAlreadyStartedError

from common import config
from contracts.gen.notifications import NotificationRequest, Notifications
from handlers.task_center.models import NewTask, TaskResponse

log = logging.getLogger("task-center")
clients: dict[str, Client] = {}
tasks: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    clients["caller"] = await config.connect(config.CALLER_NAMESPACE)  # starts standalone operations
    clients["tasks"] = await config.connect(config.TASKS_NAMESPACE)  # signals its own workflows
    yield


app = FastAPI(title="Task Center", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Reassign(BaseModel):
    assignee: str


class Respond(BaseModel):
    outcome: str  # approved | rejected | provided
    value: str | None = None
    responded_by: str


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def notify(task: dict, recipient: str, template: str) -> str:
    """Fire-and-forget: start the operation, record its ID, return."""
    task["seq"] += 1
    op_id = f"notify-{task['task_id']}-{task['seq']}"  # business key: one notification per task event
    notifications = clients["caller"].create_nexus_client(service=Notifications, endpoint=config.NOTIFY_ENDPOINT)
    try:
        await notifications.start_operation(
            Notifications.send,
            NotificationRequest(recipient=recipient, channel="email", template=template,
                                subject=task["title"], reference=task["task_id"]),
            id=op_id,
            id_reuse_policy=NexusOperationIDReusePolicy.REJECT_DUPLICATE,
            schedule_to_close_timeout=timedelta(hours=1),
        )
    except NexusOperationAlreadyStartedError:
        pass  # this event was already handed to Temporal
    task["notifications"].append(op_id)
    log.info("handed notification %s to Temporal", op_id)
    return op_id


@app.post("/v1/tasks", status_code=201)
async def create(t: NewTask) -> dict:
    existing = next((x for x in tasks.values() if x["reference"] == t.reference), None)
    if existing:
        if not existing["notifications"]:  # an earlier attempt saved the task but failed to hand off
            await notify(existing, existing["assignee"], "task_assigned")
        return existing
    task = {**dataclasses.asdict(t), "task_id": f"T-{uuid.uuid4().hex[:6]}", "status": "open", "created_at": now(),
            "seq": 0, "notifications": [], "outcome": None, "value": None, "responded_by": None}
    tasks[task["task_id"]] = task
    await notify(task, task["assignee"], "task_assigned")
    return task


@app.post("/v1/tasks/{task_id}/reassign")
async def reassign(task_id: str, r: Reassign) -> dict:
    task = _open(task_id)
    task["assignee"] = r.assignee
    await notify(task, r.assignee, "task_reassigned")
    return task


@app.post("/v1/tasks/{task_id}/respond")
async def respond(task_id: str, r: Respond) -> dict:
    task = _open(task_id)
    answer = TaskResponse(outcome=r.outcome, value=r.value, responded_by=r.responded_by, responded_at=now())
    await clients["tasks"].get_workflow_handle(task["workflow_id"]).signal("respond", answer)
    task.update(status="done", outcome=r.outcome, value=r.value, responded_by=r.responded_by)
    return task


@app.post("/v1/tasks/{task_id}/expire")
async def expire(task_id: str) -> dict:
    task = tasks[task_id]
    task["status"] = "expired"
    return task


@app.get("/v1/tasks")
async def list_tasks(status: str | None = None) -> list[dict]:
    rows = [t for t in tasks.values() if status is None or t["status"] == status]
    return sorted(rows, key=lambda t: t["created_at"], reverse=True)


@app.post("/admin/reset")
async def reset() -> dict:
    tasks.clear()
    return {"tasks": 0}


def _open(task_id: str) -> dict:
    task = tasks.get(task_id)
    if task is None:
        raise HTTPException(404, f"task {task_id} not found")
    if task["status"] != "open":
        raise HTTPException(409, f"task {task_id} is {task['status']}")
    return task
