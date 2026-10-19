from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker

from app.config import load_settings
from app.temporal.activities import (
    mark_run_running,
    ping,
    record_agent_error,
    record_order_event,
    record_wake,
    run_agent,
)
from app.temporal.workflow import NoopWorkflow, OrderSupervisorWorkflow

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = load_settings()
    logger.info(
        "Connecting Temporal worker address=%s namespace=%s queue=%s",
        settings.temporal_address,
        settings.temporal_namespace,
        settings.temporal_task_queue,
    )
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    with ThreadPoolExecutor(max_workers=4) as activity_executor:
        worker = Worker(
            client,
            task_queue=settings.temporal_task_queue,
            workflows=[NoopWorkflow, OrderSupervisorWorkflow],
            activities=[
                ping,
                mark_run_running,
                record_order_event,
                record_wake,
                run_agent,
                record_agent_error,
            ],
            activity_executor=activity_executor,
        )
        logger.info("Worker polling task queue %s", settings.temporal_task_queue)
        await worker.run()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
