"""Private, read-only EDOF browser for the Paris working day."""
from contextlib import suppress
from datetime import datetime
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import threading
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
POLL_SECONDS = 120


def working_hours(now=None):
    now = (now or datetime.now(PARIS)).astimezone(PARIS)
    return now.weekday() < 5 and 8 <= now.hour < 19


def allow_login(vault, *, automatic, verified_tab=False, owner=None, now=None):
    """Called under the shared job lock before the password POST can issue a code."""
    now = (now or datetime.now(PARIS)).astimezone(PARIS)
    today = now.date().isoformat()
    previous = vault.get("efp-login-day")
    count = int(previous == today)  # Compatible with the original date-only entry.
    if isinstance(previous, dict) and previous.get("date") == today:
        count = previous["count"]
    if automatic:
        if not working_hours(now):
            return False
        override = bool(owner) and vault.get("day-login-override:" + owner, consume=True) == today
        if count and not (verified_tab and count == 1) and not override:
            return False
    vault.put("efp-login-day", {"date": today, "count": count + 1}, ttl=2 * 86400)
    return True


class DayWorker:
    """One isolated child controlled through anonymous pipes, with no network listener."""
    def __init__(self):
        self.process = self.temp = self.owner = None
        self.mutex = threading.RLock()

    def close(self):
        with self.mutex:
            if self.process is not None:
                with suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
                self.process.stdin.close()
                self.process.stdout.close()
                self.process = self.owner = None
            if self.temp is not None:
                self.temp.cleanup()
                self.temp = None

    def read(self, spec, env, timeout):
        with self.mutex:
            if not working_hours():
                return {"code": "day_closed"}
            if self.process is None or self.owner != spec["owner"] or self.process.poll() is not None:
                self.close()
                self.temp = tempfile.TemporaryDirectory(prefix="edof-working-day-")
                self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve())],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    env={**env, "TMPDIR": self.temp.name}, text=True, start_new_session=True)
                self.owner = spec["owner"]
            try:
                self.process.stdin.write(json.dumps({"owner": self.owner}) + "\n")
                self.process.stdin.flush()
                now = datetime.now(PARIS)
                remaining = (now.replace(hour=19, minute=0, second=0, microsecond=0) - now).total_seconds()
                if not select.select([self.process.stdout], [], [], min(timeout, max(0, remaining)))[0]:
                    self.close()
                    return {"code": "timeout" if working_hours() else "day_closed"}
                result = json.loads(self.process.stdout.readline(32768))
                if result.get("code") not in {"directory_ready", "directory_incomplete", "directory_unavailable"}:
                    self.close()
                return result
            except (OSError, ValueError):
                self.close()
                return {"code": "browser_error"}


def serve():
    from playwright.sync_api import sync_playwright
    from edof_server_browser import run_browser
    with sync_playwright() as pw:
        live = {"pw": pw, "browser": pw.chromium.launch(headless=True)}
        try:
            for line in sys.stdin:
                if not working_hours():
                    break
                owner = json.loads(line)["owner"]
                result = run_browser({"mode": "directory", "owner": owner, "day_session": True}, live=live)
                if result["code"] == "directory_ready":
                    live["verified"] = True
                print(json.dumps(result), flush=True)
        finally:
            live["browser"].close()


if __name__ == "__main__":
    serve()
