import os
import signal
import subprocess
import sys

import pytest


@pytest.mark.parametrize('sig', [signal.SIGTERM, signal.SIGINT])
def test_signal_exits_through_cleanup(tmp_path, sig):
    ready = tmp_path / 'ready'
    cleaned = tmp_path / 'cleaned'
    script = '''
import asyncio, pathlib, sys
from sdk.lifecycle import shutdown_event
async def main():
    with shutdown_event() as stop:
        pathlib.Path(sys.argv[1]).touch()
        try:
            await stop.wait()
        finally:
            pathlib.Path(sys.argv[2]).touch()
asyncio.run(main())
'''
    proc = subprocess.Popen([sys.executable, '-c', script, str(ready), str(cleaned)])
    try:
        import time
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            assert proc.poll() is None
            time.sleep(.02)
        assert ready.exists()
        os.kill(proc.pid, sig)
        assert proc.wait(timeout=5) == 0
        assert cleaned.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
