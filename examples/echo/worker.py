"""Echo worker entry point.

Connects to Temporal and processes workflows and activities on the
``echo`` task queue.

Run with: python -m examples.echo.worker
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from temporalio.client import Client
from temporalio.worker import Worker

from examples.echo.activities import create_activities
from examples.echo.config import EchoConfig
from examples.echo.workflows import ChatWorkflow, ProposalWorkflow
from sdk.lifecycle import shutdown_event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("echo")


async def run() -> None:
    with shutdown_event() as stop:
        await run_until_stopped(stop)


async def run_until_stopped(stop: asyncio.Event) -> None:
    config = EchoConfig()  # type: ignore[call-arg]

    logger.info(
        "Connecting to Temporal at %s namespace=%s",
        config.temporal_address,
        config.temporal_namespace,
    )
    client = await Client.connect(
        config.temporal_address,
        namespace=config.temporal_namespace,
    )

    activities = create_activities(config)

    async with Worker(
        client,
        task_queue=config.task_queue,
        workflows=[ChatWorkflow, ProposalWorkflow],
        activities=activities,
        graceful_shutdown_timeout=timedelta(seconds=40),
    ):
        logger.info("Echo worker started on queue=%s", config.task_queue)
        logger.info("Model endpoint: %s model: %s", config.llm_base_url, config.llm_model)
        await stop.wait()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
