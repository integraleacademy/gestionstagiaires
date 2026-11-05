"""One private EDOF session for the Paris working day."""
from contextlib import suppress
from datetime import datetime
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import tempfile
import threading
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
POLL_SECONDS = 120
OPEN_HOUR = 7
CLOSE_HOUR = 19
MAX_DAILY_LOGINS = 4
LOGIN_RETRY_SECONDS = 15 * 60
SHARED_JOB_MODES = frozenset({"declare","reconcile","proposal_read","proposal_check","proposal_send"})


def working_hours(now=None, *, daily=True):
    now = (now or datetime.now(PARIS)).astimezone(PARIS)
    return (daily or now.weekday() < 5) and OPEN_HOUR <= now.hour < CLOSE_HOUR


def session_deadline(now, manual_until=0, *, daily=True):
    scheduled = now.astimezone(PARIS).replace(hour=CLOSE_HOUR, minute=0, second=0, microsecond=0).timestamp() if working_hours(now, daily=daily) else 0
    return max(scheduled, manual_until)


def awaiting_edof_return(result):
    diag = result.get("diagnostics") or {}
    return (result.get("code") == "timeout" and result.get("stage") == "authentication"
            and result.get("gmail_code_used") is True and diag.get("callback_status") == 200
            and diag.get("location") == "edof_initialisation" and not diag.get("workspace_denied"))


def login_count(vault, today):
    prior = vault.get("efp-login-day")
    if isinstance(prior, dict):
        return prior.get("count", 0) if prior.get("date") == today else 0
    return int(prior == today)


def login_policy(vault, *, owner=None, now=None, manual_until=0):
    now = (now or datetime.now(PARIS)).astimezone(PARIS)
    today = now.date().isoformat()
    count = login_count(vault, today)
    prior = vault.get("efp-login-day")
    last = prior.get("at", 0) if isinstance(prior, dict) and prior.get("date") == today else 0
    override = bool(owner) and vault.get("day-login-override:" + owner) == today
    # Outside the daily watch, retain the existing explicit one-hour activation.
    limit = MAX_DAILY_LOGINS if working_hours(now) else 1
    code = None
    if session_deadline(now, manual_until) <= now.timestamp():
        code = "day_closed"
    elif vault.get("edof-throttled"):
        code = "portal_throttled"
    elif count >= limit and not override:
        code = "day_login_used"
    elif count and last and now.timestamp() < last + LOGIN_RETRY_SECONDS and not override:
        code = "day_login_wait"
    return {"allowed":code is None, "code":code, "used":count, "limit":MAX_DAILY_LOGINS,
            "remaining":max(0,MAX_DAILY_LOGINS-count), "retry_at":last+LOGIN_RETRY_SECONDS if code == "day_login_wait" else None,
            "override":override}


def allow_login(vault, *, owner=None, now=None, manual_until=0):
    """Reserve the account's attempt before submitting credentials, under the job lock."""
    now = (now or datetime.now(PARIS)).astimezone(PARIS)
    today = now.date().isoformat()
    policy = login_policy(vault, owner=owner, now=now, manual_until=manual_until)
    if not policy["allowed"]:
        if policy["code"] == "day_login_used":
            vault.put("efp-paused-day", today, ttl=86400)
        return False
    if policy["override"]:
        vault.get("day-login-override:" + owner, consume=True)
    vault.put("efp-login-day", {"date":today, "count":policy["used"]+1, "at":now.timestamp()}, ttl=2*86400)
    vault.delete("efp-paused-day")
    return True


class DayWorker:
    """One isolated child controlled by a private socket pair, with no network listener."""
    def __init__(self):
        self.process = self.temp = self.owner = self.provider = self.channel = self.vault = None
        self.mutex = threading.RLock()

    def close(self):
        with self.mutex:
            if self.process is not None:
                with suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
                self.process.stdout.close()
                if self.vault and self.owner:
                    from edof_session_clock import record
                    record(self.vault, self.owner, "interrupted")
                self.process = self.owner = self.provider = self.vault = None
            if self.channel is not None:
                self.channel.close()
                self.channel = None
            if self.temp is not None:
                self.temp.cleanup()
                self.temp = None

    def read(self, spec, env, timeout, *, lock_fds=()):
        with self.mutex:
            now = datetime.now(PARIS)
            deadline = session_deadline(now, spec.get("manual_until", 0), daily=True)
            if deadline <= now.timestamp():
                return {"code": "day_closed"}
            if spec["mode"] not in SHARED_JOB_MODES | {"directory"}:
                raise ValueError("Opération hors veille EDOF.")
            if (self.process is None or self.owner != spec["owner"] or self.provider != spec.get("provider")
                    or self.process.poll() is not None):
                self.close()
                from edof_gmail import Vault
                vault = Vault(env["EDOF_CONNECTOR_DIRECTORY"], env["EDOF_CONNECTOR_KEY"])
                if vault.get("edof-throttled"):
                    return {"code":"portal_throttled"}
                today = now.date().isoformat()
                policy = login_policy(vault, owner=spec["owner"], now=now, manual_until=spec.get("manual_until",0))
                if (not policy["allowed"]
                        and (vault.get("efp-paused-day") == today or not (vault.get("browser") or {}).get("cookies"))):
                    return {"code":policy["code"], "gmail_code_used":False}
                self.temp = tempfile.TemporaryDirectory(prefix="edof-working-day-")
                self.channel, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                with child:
                    self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(child.fileno())],
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, pass_fds=(child.fileno(),),
                        env={**env, "TMPDIR":self.temp.name}, text=True, start_new_session=True)
                self.owner, self.provider, self.vault = spec["owner"], spec.get("provider"), vault
            try:
                started = datetime.now(PARIS).timestamp()
                command = {**spec, "full_sync":spec.get("sync_scope") == "all" or spec.get("recovery_since") is not None}
                # Both locks must cover the child's work even if the scheduler is killed.
                socket.send_fds(self.channel, [json.dumps(command).encode()], list(lock_fds))
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
                if ((spec["mode"] == "directory" and result.get("code") not in
                     {"directory_ready","directory_progress","requests_ready","directory_incomplete","directory_unavailable","pending_unavailable","portal_throttled"} and not awaiting_edof_return(result))
                    or result.get("code") in {"browser_error","day_login_used","otp_rejected","human_verification","account_unavailable"}):
                    self.close()
                return result
            except (OSError, ValueError):
                self.close()
                return {"code": "browser_error"}


def serve(channel):
    from playwright.sync_api import sync_playwright
    from edof_server_browser import run_browser
    with sync_playwright() as pw:
        live = {"pw":pw, "browser":pw.chromium.launch(headless=True)}
        try:
            while True:
                data, locks, flags, _ = socket.recv_fds(channel, 131072, 2)
                try:
                    if not data:
                        break
                    if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or len(locks) != 2:
                        raise ValueError("Commande EDOF incomplète.")
                    cmd = json.loads(data)
                    if cmd["mode"] not in SHARED_JOB_MODES | {"directory"}:
                        raise ValueError("Opération inconnue.")
                    now = datetime.now(PARIS)
                    if session_deadline(now, cmd.get("manual_until",0)) <= now.timestamp():
                        result = {"code":"day_closed"}
                    else:
                        result = run_browser({**cmd, "day_session":cmd["mode"] == "directory", "shared_job":True}, live=live)
                        live["return_pending"] = awaiting_edof_return(result)
                        if result["code"] in {"directory_ready","directory_progress","requests_ready"}:
                            live["verified"] = True
                finally:
                    for fd in locks:
                        os.close(fd)
                print(json.dumps(result),flush=True)
        finally:
            live["browser"].close()


if __name__ == "__main__":
    with socket.socket(fileno=int(sys.argv[1])) as channel:
        serve(channel)
