import dataclasses

import httpx
from temporalio import activity

from common import config
from handlers.task_center.models import NewTask


@activity.defn
async def create_task(task: NewTask) -> str:
    """Create the task in Task Center. Idempotent: one task per reference."""
    async with httpx.AsyncClient(base_url=config.TASK_CENTER_URL, timeout=5) as http:
        resp = await http.post("/v1/tasks", json=dataclasses.asdict(task))
        resp.raise_for_status()
        return resp.json()["task_id"]


@activity.defn
async def expire_task(task_id: str) -> None:
    async with httpx.AsyncClient(base_url=config.TASK_CENTER_URL, timeout=5) as http:
        (await http.post(f"/v1/tasks/{task_id}/expire")).raise_for_status()
