"""Ask a person for a decision from any Python service, and get the answer back.

    python -m examples.request_input --reference vendor-77 --assignee dana

Approve or reject the task in the web UI (http://localhost:8000). The result
arrives here, even if it takes days and this process restarts in between:
reconnect with get_nexus_operation_handle(operation_id).
"""

import argparse
import asyncio
from datetime import timedelta

from common import config
from contracts.gen.task_center import HumanInputRequest, TaskCenter


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reference", default="vendor-77")
    p.add_argument("--assignee", default="dana")
    p.add_argument("--title", default="Approve new vendor: Northwind Data")
    a = p.parse_args()

    client = await config.connect(config.CALLER_NAMESPACE)
    task_center = client.create_nexus_client(service=TaskCenter, endpoint=config.TASKS_ENDPOINT)
    handle = await task_center.start_operation(
        TaskCenter.request_input,
        HumanInputRequest(reference=a.reference, requested_by="examples", assignee=a.assignee,
                          kind="approve_reject", title=a.title),
        id=f"input-{a.reference}",
        schedule_to_close_timeout=timedelta(days=7),
    )
    print(f"waiting for {a.assignee} on {handle.operation_id}...")
    answer = await handle.result()
    print(f"{answer.outcome} by {answer.responded_by}")


if __name__ == "__main__":
    asyncio.run(main())
