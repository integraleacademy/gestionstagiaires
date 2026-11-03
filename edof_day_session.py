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
RENEWAL_INTERVAL = 10 * 60


def working_hours(now=None, *, daily=False):
    now = (now or datetime.now(PARIS)).astimezone(PARIS)
    return (daily or now.weekday() < 5) and 8 <= now.hour < 19


def session_deadline(now, manual_until=0, *, daily=False):
    scheduled = now.replace(hour=19, minute=0, second=0, microsecond=0).timestamp() if working_hours(now, daily=daily) else 0
    return max(scheduled, manual_until)


def awaiting_edof_return(result):
    diag = result.get("diagnostics") or {}
    return (result.get("code") == "timeout" and result.get("stage") == "authentication"
            and result.get("gmail_code_used") is True and diag.get("callback_status") == 200
            and diag.get("location") == "edof_initialisation" and not diag.get("workspace_denied"))


def renewal_time(previous, verified_at, now):
    """A verified directory read permits one more sign-in, including after a restart."""
    if not verified_at or not (now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                               <= verified_at <= now.timestamp()):
        return None
    attempted_at = previous.get("at", 0) if isinstance(previous, dict) else 0
    if verified_at <= attempted_at:
        return None
    return max(verified_at, attempted_at + RENEWAL_INTERVAL)


def allow_login(vault, *, automatic, verified_tab=False, owner=None, now=None, manual_until=0, recover_return=False, daily=False, verified_at=None):
    """Called under the shared job lock before the password POST can issue a code."""
    now = (now or datetime.now(PARIS)).astimezone(PARIS)
    today = now.date().isoformat()
    previous = vault.get("efp-login-day")
    count = int(previous == today)  # Compatible with the original date-only entry.
    if isinstance(previous, dict) and previous.get("date") == today:
        count = previous["count"]
    if automatic:
        if session_deadline(now, manual_until, daily=daily) <= now.timestamp():
            return False
        override = bool(owner) and vault.get("day-login-override:" + owner, consume=True) == today
        renewal = renewal_time(previous, verified_at, now)
        may_renew = renewal is not None and renewal <= now.timestamp()
        initial_recovery = count == 1 and ((verified_tab and not verified_at)
                                           or (manual_until > now.timestamp() and recover_return))
        if count and not (may_renew or initial_recovery or override):
            return False
    vault.put("efp-login-day", {"date": today, "count": count + 1, "at": now.timestamp()}, ttl=2 * 86400)
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
            now = datetime.now(PARIS)
            deadline = session_deadline(now, spec.get("manual_until", 0), daily=True)
            if deadline <= now.timestamp():
                return {"code": "day_closed"}
            if self.process is None or self.owner != spec["owner"] or self.process.poll() is not None:
                self.close()
                from edof_gmail import Vault
                vault = Vault(env["EDOF_CONNECTOR_DIRECTORY"], env["EDOF_CONNECTOR_KEY"])
                today = now.date().isoformat()
                budget = vault.get("efp-login-day")
                count = budget.get("count",0) if isinstance(budget,dict) and budget.get("date")==today else int(budget==today)
                # Without a reusable session or an authorised sign-in there is
                # no work for a fresh Chromium process to do on this instance.
                renewal = renewal_time(budget, spec.get("verified_at"), now)
                if (count and not (renewal is not None and renewal <= now.timestamp()) and not (vault.get("browser") or {}).get("cookies")
                        and vault.get("day-login-override:"+spec["owner"]) != today
                        and not (count==1 and spec.get("recover_return") and spec.get("manual_until",0)>now.timestamp())):
                    return {"code":"day_login_used", "gmail_code_used":False}
                self.temp = tempfile.TemporaryDirectory(prefix="edof-working-day-")
                self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve())],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    env={**env, "TMPDIR": self.temp.name}, text=True, start_new_session=True)
                self.owner = spec["owner"]
            try:
                started = datetime.now(PARIS).timestamp()
                command = {key:spec.get(key) for key in ("provider", "verified_at", "recover_return")}
                command.update(owner=self.owner, manual_until=spec.get("manual_until", 0), full_sync=bool(spec.get("full_sync_until")))
                self.process.stdin.write(json.dumps(command) + "\n")
                self.process.stdin.flush()
                now = datetime.now(PARIS)
                remaining = deadline - now.timestamp()
                if not select.select([self.process.stdout], [], [], min(timeout, max(0, remaining)))[0]:
                    self.close()
                    from edof_gmail import Vault
                    checkpoint = Vault(env["EDOF_CONNECTOR_DIRECTORY"], env["EDOF_CONNECTOR_KEY"]).get("edof-phase:"+spec["owner"]) or {}
                    if checkpoint.get("at", 0) < started:
                        checkpoint = {"phase": "browser_start"}
                    return {"code": "timeout" if datetime.now(PARIS).timestamp() < deadline else "day_closed",
                            "stage": checkpoint.get("phase"), "gmail_code_used": checkpoint.get("mail_used"),
                            "diagnostics":{"callback_status":checkpoint.get("callback"), "workspace_status":checkpoint.get("private_status")}}
                result = json.loads(self.process.stdout.readline(32768))
                if result.get("code") not in {"directory_ready", "requests_ready", "directory_incomplete", "directory_unavailable"} and not awaiting_edof_return(result):
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
                command = json.loads(line)
                now = datetime.now(PARIS)
                manual_until = command.get("manual_until", 0)
                if session_deadline(now, manual_until, daily=True) <= now.timestamp():
                    break
                owner = command["owner"]
                result = run_browser({"mode": "directory", "owner": owner, "day_session": True,
                                      "provider":command.get("provider"), "manual_until": manual_until, "recover_return": command.get("recover_return", False),
                                      "verified_at": command.get("verified_at"), "full_sync": command.get("full_sync", False)}, live=live)
                live["return_pending"] = awaiting_edof_return(result)
                if result["code"] in {"directory_ready", "requests_ready"}:
                    live["verified"] = True
                print(json.dumps(result), flush=True)
        finally:
            live["browser"].close()


if __name__ == "__main__":
    serve()
