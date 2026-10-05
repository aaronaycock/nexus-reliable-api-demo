"""Start a fee change the way the billing team would: an ordinary workflow start.

python -m teams.billing.start --change-id 42 --approver dana --wait
"""

import argparse
import asyncio

from common import config
from teams.billing.workflows import FeeChange, FeeChangeWorkflow


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--change-id", default="42")
    p.add_argument("--account", default="ACME-001")
    p.add_argument("--new-fee-bps", type=int, default=85)
    p.add_argument("--requested-by", default="sam")
    p.add_argument("--approver", default="dana")
    p.add_argument("--due-in-seconds", type=int, default=24 * 60 * 60)
    p.add_argument("--wait", action="store_true")
    a = p.parse_args()

    client = await config.connect(config.BILLING_NAMESPACE)
    change = FeeChange(change_id=a.change_id, account=a.account, new_fee_bps=a.new_fee_bps,
                       requested_by=a.requested_by, approver=a.approver, due_in_seconds=a.due_in_seconds)
    handle = await client.start_workflow(FeeChangeWorkflow.run, change, id=f"fee-change-{a.change_id}",
                                         task_queue=config.BILLING_TASK_QUEUE)
    print(f"started {handle.id} in {config.BILLING_NAMESPACE}; approve it in Task Center")
    if a.wait:
        print("result:", await handle.result())


if __name__ == "__main__":
    asyncio.run(main())
