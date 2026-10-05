"""Task Center's internal types. Not part of the published contract."""

from dataclasses import dataclass


@dataclass
class NewTask:
    reference: str
    requested_by: str
    assignee: str
    kind: str
    title: str
    workflow_id: str  # the HumanInputWorkflow waiting on this task
    details: str | None = None


@dataclass
class TaskResponse:
    """What Task Center sends the waiting workflow when a person answers."""

    outcome: str  # approved | rejected | provided
    responded_by: str
    responded_at: str
    value: str | None = None
