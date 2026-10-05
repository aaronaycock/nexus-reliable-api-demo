"""A product team's workflow that uses two shared capabilities through Nexus.

The billing team needs an approval before changing a client's fee. It calls
Task Center's human-in-the-loop operation (internal to internal), applies the
change, then notifies the requester through the Notification team's operation
(internal to external). It knows only endpoint, service and operation names.
"""

import logging
from datetime import timedelta

from dataclasses import dataclass

from temporalio import activity, workflow

with workflow.unsafe.imports_passed_through():
    from common import config
    from contracts.gen.notifications import NotificationRequest, Notifications
    from contracts.gen.task_center import HumanInputRequest, TaskCenter


@dataclass
class FeeChange:
    change_id: str
    account: str
    new_fee_bps: int
    requested_by: str
    approver: str
    due_in_seconds: int = 24 * 60 * 60


@dataclass
class FeeChangeResult:
    change_id: str
    outcome: str
    applied: bool
    decided_by: str | None = None


@activity.defn
async def apply_fee_change(change: FeeChange) -> None:
    logging.getLogger("billing").info("applied fee change %s: %s -> %d bps", change.change_id, change.account, change.new_fee_bps)


@workflow.defn
class FeeChangeWorkflow:
    @workflow.run
    async def run(self, change: FeeChange) -> FeeChangeResult:
        task_center = workflow.create_nexus_client(service=TaskCenter, endpoint=config.TASKS_ENDPOINT)
        answer = await task_center.execute_operation(
            TaskCenter.request_input,
            HumanInputRequest(
                reference=f"fee-change-{change.change_id}",
                requested_by="billing",
                assignee=change.approver,
                kind="approve_reject",
                title=f"Approve fee change for {change.account}: {change.new_fee_bps} bps",
                due_in_seconds=change.due_in_seconds,
            ),
            schedule_to_close_timeout=timedelta(seconds=change.due_in_seconds) + timedelta(minutes=5),
        )

        approved = answer.outcome == "approved"
        if approved:
            await workflow.execute_activity(apply_fee_change, change, start_to_close_timeout=timedelta(seconds=10))

        notifications = workflow.create_nexus_client(service=Notifications, endpoint=config.NOTIFY_ENDPOINT)
        await notifications.execute_operation(
            Notifications.send,
            NotificationRequest(
                recipient=change.requested_by,
                channel="email",
                template=f"change_{answer.outcome}",
                subject=f"Fee change {change.change_id}: {answer.outcome}",
                reference=f"fee-change-{change.change_id}",
            ),
            schedule_to_close_timeout=timedelta(hours=1),
        )
        return FeeChangeResult(change_id=change.change_id, outcome=answer.outcome,
                               applied=approved, decided_by=answer.responded_by)
