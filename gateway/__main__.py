"""Gateway entry point.

Starts the Temporal activity worker and the configured channel adapter.
Run with: python -m gateway

Set CHANNEL=http for the HTTP/REST adapter (default).
Set CHANNEL=telegram for the Telegram long-poll adapter.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from temporalio.client import Client
from temporalio.worker import Worker

from gateway.config import Channel, GatewayConfig
from gateway.router import Router
from sdk.lifecycle import shutdown_event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("gateway")
# Telegram request URLs contain the bot token. Do not log HTTPX request URLs.
logging.getLogger("httpx").setLevel(logging.WARNING)


async def run() -> None:
    with shutdown_event() as stop:
        await run_until_stopped(stop)


async def run_until_stopped(stop: asyncio.Event) -> None:
    config = GatewayConfig()  # type: ignore[call-arg]

    if config.channel == Channel.http:
        await _run_http(config, stop)
    else:
        await _run_telegram(config, stop)


async def _run_http(config: GatewayConfig, stop: asyncio.Event) -> None:
    """Start the HTTP channel adapter."""
    from gateway.http_adapter import run_http_gateway

    logger.info("Starting gateway with HTTP adapter on port %d", config.gateway_port)
    await run_http_gateway(config, stop)


async def _run_telegram(config: GatewayConfig, stop: asyncio.Event) -> None:
    """Start the Telegram channel adapter."""
    from telegram import Bot

    from gateway.activities import create_activities
    from gateway.telegram import create_telegram_app

    logger.info(
        "Connecting to Temporal at %s namespace=%s",
        config.temporal_address,
        config.temporal_namespace,
    )
    temporal_client = await Client.connect(
        config.temporal_address,
        namespace=config.temporal_namespace,
    )

    bot = Bot(token=config.telegram_bot_token)
    activities = create_activities(bot)
    router = Router(client=temporal_client, config=config)
    telegram_app = create_telegram_app(config=config, router=router)

    async with Worker(
        temporal_client,
        task_queue=config.gateway_task_queue,
        activities=activities,
        graceful_shutdown_timeout=timedelta(seconds=40),
    ):
        logger.info("Temporal worker started on queue=%s", config.gateway_task_queue)
        logger.info("Starting Telegram poller...")

        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.updater.start_polling(drop_pending_updates=True)  # type: ignore[union-attr]

        logger.info("Gateway is running. Press Ctrl+C to stop.")

        try:
            await stop.wait()
        finally:
            logger.info("Shutting down...")
            await telegram_app.updater.stop()  # type: ignore[union-attr]
            await telegram_app.stop()
            await telegram_app.shutdown()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
