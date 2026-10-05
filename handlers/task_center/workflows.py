import asyncio
from datetime import datetime, timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from contracts.gen.task_center import HumanInputRequest, HumanInputResult
    from handlers.task_center.activities import create_task, expire_task
    from handlers.task_center.models import NewTask, TaskResponse

ONE_DAY = 24 * 60 * 60


@workflow.defn
class HumanInputWorkflow:
    """Owns one human step: create the task, wait for the answer, return it.

    Runs in Task Center's namespace. Task Center signals it here when the person
    responds, so Task Center never needs access to the caller's namespace.
    """

    def __init__(self) -> None:
        self._response: TaskResponse | None = None
        self._task_id: str | None = None

    @workflow.signal
    def respond(self, response: TaskResponse) -> None:
        self._response = response

    @workflow.query
    def task_id(self) -> str | None:
        return self._task_id

    @workflow.run
    async def run(self, req: HumanInputRequest) -> HumanInputResult:
        self._task_id = await workflow.execute_activity(
            create_task,
            NewTask(
                reference=req.reference,
                requested_by=req.requested_by,
                assignee=req.assignee,
                kind=req.kind,
                title=req.title,
                details=req.details,
                workflow_id=workflow.info().workflow_id,
            ),
            start_to_close_timeout=timedelta(seconds=10),
        )
        try:
            await workflow.wait_condition(
                lambda: self._response is not None,
                timeout=timedelta(seconds=req.due_in_seconds or ONE_DAY),
            )
        except asyncio.TimeoutError:
            await workflow.execute_activity(expire_task, self._task_id, start_to_close_timeout=timedelta(seconds=10))
            return HumanInputResult(reference=req.reference, task_id=self._task_id, outcome="expired")

        r = self._response
        return HumanInputResult(
            reference=req.reference,
            task_id=self._task_id,
            outcome=r.outcome,
            value=r.value,
            responded_by=r.responded_by,
            responded_at=datetime.fromisoformat(r.responded_at),
        )
