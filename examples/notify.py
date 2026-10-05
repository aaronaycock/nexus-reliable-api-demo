"""Fire-and-forget a notification from any Python service. No workflow, no worker.

    python -m examples.notify --to dana --template task_assigned

The call returns as soon as Temporal has durably recorded the operation.
Delivery, retries and deduplication are Temporal's job from then on.
"""

import argparse
import asyncio
from datetime import timedelta

from temporalio.common import NexusOperationIDReusePolicy

from common import config
from contracts.gen.notifications import NotificationRequest, Notifications


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--to", default="dana")
    p.add_argument("--template", default="task_assigned")
    p.add_argument("--reference", default="example-1")
    p.add_argument("--wait", action="store_true", help="wait for delivery instead of returning at once")
    a = p.parse_args()

    client = await config.connect(config.CALLER_NAMESPACE)  # your own caller namespace
    notifications = client.create_nexus_client(
        service=Notifications,             # the contract: notifications.v1
        endpoint=config.NOTIFY_ENDPOINT,   # where to route it: notifications-dev
    )
    handle = await notifications.start_operation(
        Notifications.send,                # the operation
        NotificationRequest(recipient=a.to, channel="email", template=a.template, reference=a.reference),
        id=f"notify-{a.reference}-{a.to}",  # business key: Temporal dedupes on it
        id_reuse_policy=NexusOperationIDReusePolicy.REJECT_DUPLICATE,  # never send this one twice
        schedule_to_close_timeout=timedelta(hours=1),  # how long Temporal keeps trying
    )
    print(f"handed off {handle.operation_id}")
    if a.wait:
        print("delivered:", await handle.result())


if __name__ == "__main__":
    asyncio.run(main())
