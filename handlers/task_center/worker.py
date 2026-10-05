"""Task Center team's worker. Publishes task-center.v1 behind the task-center-dev endpoint."""

import asyncio
import logging

import nexusrpc.handler
from temporalio import nexus
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.worker import Worker

from common import config
from contracts.gen.task_center import HumanInputRequest, HumanInputResult, TaskCenter
from handlers.task_center.activities import create_task, expire_task
from handlers.task_center.workflows import HumanInputWorkflow


@nexusrpc.handler.service_handler(service=TaskCenter)
class TaskCenterHandler:
    @nexus.workflow_run_operation
    async def request_input(
        self, ctx: nexus.WorkflowRunOperationContext, req: HumanInputRequest
    ) -> nexus.WorkflowHandle[HumanInputResult]:
        # One human step per business reference. A second request for the same
        # reference attaches to the workflow already waiting, instead of
        # creating a second task.
        return await ctx.start_workflow(
            HumanInputWorkflow.run,
            req,
            id=f"hitl-{req.reference}",
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("temporalio.activity").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # no traceback per retry; activities log one line
    client = await config.connect(config.TASKS_NAMESPACE)
    worker = Worker(
        client,
        task_queue=config.TASKS_TASK_QUEUE,
        workflows=[HumanInputWorkflow],
        activities=[create_task, expire_task],
        nexus_service_handlers=[TaskCenterHandler()],
    )
    logging.info("task-center worker: %s / %s", config.TASKS_NAMESPACE, config.TASKS_TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
