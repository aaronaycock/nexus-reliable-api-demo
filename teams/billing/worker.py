"""Billing team's worker: an ordinary Temporal worker with no Nexus handlers."""

import asyncio
import logging

from temporalio.worker import Worker

from common import config
from teams.billing.workflows import FeeChangeWorkflow, apply_fee_change


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("temporalio.activity").setLevel(logging.ERROR)  # no traceback per retry; activities log one line
    client = await config.connect(config.BILLING_NAMESPACE)
    worker = Worker(client, task_queue=config.BILLING_TASK_QUEUE,
                    workflows=[FeeChangeWorkflow], activities=[apply_fee_change])
    logging.info("billing worker: %s / %s", config.BILLING_NAMESPACE, config.BILLING_TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
