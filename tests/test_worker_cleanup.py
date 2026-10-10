import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from examples.echo import worker as echo
from gateway import __main__ as gateway
from gateway.config import Channel


def test_gateway_telegram_stops_poller_and_application_before_worker_exit(monkeypatch):
    config = SimpleNamespace(
        channel=Channel.telegram,
        temporal_address='test:7233', temporal_namespace='agent',
        gateway_task_queue='gateway', telegram_bot_token='123:TEST',
    )
    monkeypatch.setattr(gateway, 'GatewayConfig', lambda: config)

    # Patch the imports that _run_telegram does lazily.
    import gateway.activities as gw_activities
    import gateway.telegram as gw_telegram

    monkeypatch.setattr(gateway.Client, 'connect', AsyncMock())
    monkeypatch.setattr(gw_activities, 'create_activities', lambda bot: [])

    events = []
    async def record(name):
        events.append(name)
    app = SimpleNamespace(initialize=AsyncMock(), start=AsyncMock(),
        updater=SimpleNamespace(start_polling=AsyncMock(), stop=AsyncMock(side_effect=lambda: None)),
        stop=AsyncMock(), shutdown=AsyncMock())
    async def stop_polling(): await record('poller')
    async def stop_app(): await record('app')
    async def shutdown_app(): await record('shutdown')
    app.updater.stop.side_effect = stop_polling
    app.stop.side_effect = stop_app
    app.shutdown.side_effect = shutdown_app
    monkeypatch.setattr(gw_telegram, 'create_telegram_app', lambda **kwargs: app)
    worker = MagicMock()
    worker.__aenter__ = AsyncMock()
    async def exit_worker(*args): await record('worker')
    worker.__aexit__ = AsyncMock(side_effect=exit_worker)
    monkeypatch.setattr(gateway, 'Worker', MagicMock(return_value=worker))
    async def run():
        stop = asyncio.Event()
        stop.set()
        await gateway.run_until_stopped(stop)
    asyncio.run(run())
    assert events == ['poller', 'app', 'shutdown', 'worker']


def test_echo_exits_worker_context_on_shutdown(monkeypatch):
    monkeypatch.setattr(echo, 'EchoConfig', lambda: SimpleNamespace(
        temporal_address='test:7233', temporal_namespace='agent', task_queue='echo',
        llm_base_url='http://model', llm_model='test'))
    monkeypatch.setattr(echo.Client, 'connect', AsyncMock())
    monkeypatch.setattr(echo, 'create_activities', lambda config: [])
    worker = MagicMock()
    worker.__aenter__ = AsyncMock()
    worker.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(echo, 'Worker', MagicMock(return_value=worker))
    async def run():
        stop = asyncio.Event()
        stop.set()
        await echo.run_until_stopped(stop)
    asyncio.run(run())
    worker.__aexit__.assert_awaited_once()
