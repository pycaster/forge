"""Process shutdown shared by the Gateway and example worker."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def shutdown_event() -> Iterator[asyncio.Event]:
    """Let SIGINT and SIGTERM stop workers through their normal cleanup path."""
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    signals = (signal.SIGINT, signal.SIGTERM)
    for sig in signals:
        loop.add_signal_handler(sig, stop.set)
    try:
        yield stop
    finally:
        for sig in signals:
            loop.remove_signal_handler(sig)
