"""Wake the single EDOF scheduler across Gunicorn processes without job payloads."""
from contextlib import contextmanager, suppress
from pathlib import Path
import os
import time


def wake(directory):
    # The durable queue is authoritative; a missed notification is retried by the watch.
    with suppress(OSError):
        fd = os.open(Path(directory) / 'edof_dispatch.wake', os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.utime(fd, None)
        finally:
            os.close(fd)


@contextmanager
def listen(directory):
    # Only used by the elected scheduler. Never delete the marker: another process
    # could be notifying us while a job starts or finishes.
    yield {'path':Path(directory) / 'edof_dispatch.wake', 'seen':None}


def wait(inbox, timeout=20):
    deadline = time.monotonic() + timeout
    while True:
        try:
            stamp = inbox['path'].stat().st_mtime_ns
        except OSError:
            stamp = 0
        if stamp != inbox['seen'] or time.monotonic() >= deadline:
            inbox['seen'] = stamp
            return
        # Only stat the notification marker, not the databases or the EDOF portal.
        time.sleep(min(.2, max(0, deadline-time.monotonic())))
