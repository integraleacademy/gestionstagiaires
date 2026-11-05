"""One persistent cadence for portal traffic, not an assumed EDOF quota.

The existing browser/provider locks serialize jobs. SQLite also serializes slots
across processes and restarts. Static assets do not consume business slots.
"""
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import time
from urllib.parse import parse_qs, urlsplit

from edof_throttle import PortalThrottled, status

MIN_GAP = 1.5
MAX_GAP = 6.0


def operation(url, method, params=None):
    parsed = urlsplit(url)
    if parsed.netloc == "efpconnect.emploi.gouv.fr" and parsed.path.startswith("/auth/"):
        return "efp_auth" if method == "POST" else None
    if parsed.netloc != "of.moncompteformation.gouv.fr":
        return None
    if parsed.path.startswith("/idp/edof/api/"):
        return "edof_identity"
    if not parsed.path.startswith("/edof-api/"):
        return None
    tail = parsed.path.partition("/registration-folders/")[2]
    if tail == "pad":
        state = (params or {}).get("state") or parse_qs(parsed.query).get("state", [""])[0]
        return {"notProcessed":"pending", "accepted":"accepted", "all":"full"}.get(state, "list")
    if tail:
        return "proposal_validate" if tail.endswith("/status") else "folder_update" if method != "GET" else "folder_read"
    return "workspace"


class Traffic:
    def __init__(self, vault, *, clock=time.time, sleep=time.sleep):
        self.vault, self.clock, self.sleep = vault, clock, sleep
        self.path = Path(vault.path).with_name("edof_traffic.sqlite3")
        self.counts, self.waited, self.last_limit = {}, 0.0, None
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        with closing(self.connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS cadence (id INTEGER PRIMARY KEY, next_at REAL, gap REAL, limited_at REAL)")
            db.execute("INSERT OR IGNORE INTO cadence VALUES (1,0,?,0)", (MIN_GAP,))

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def check(self):
        if status(self.vault):
            pause = PortalThrottled(None)
            pause.recorded = True  # A local guard must not create/extend a 429.
            raise pause

    def before(self, url, method, params=None):
        kind = operation(url, method, params)
        self.check()
        if not kind:
            return
        while True:
            self.check()
            with closing(self.connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                next_at, gap, limited_at = db.execute("SELECT next_at,gap,limited_at FROM cadence WHERE id=1").fetchone()
                now = self.clock()
                if now - limited_at > 3600:
                    gap = MIN_GAP
                delay = max(0, next_at - now)
                if not delay:
                    db.execute("UPDATE cadence SET next_at=?,gap=? WHERE id=1", (now+gap, gap))
                    key = method + ":" + kind
                    self.counts[key] = self.counts.get(key, 0) + 1
                    return
            wait = min(delay, 0.2)
            self.sleep(wait)
            self.waited += wait

    def after(self, response, method, params=None):
        kind = operation(response.url, method, params)
        if response.status != 429 or urlsplit(response.url).netloc not in {
                "of.moncompteformation.gouv.fr", "efpconnect.emploi.gouv.fr"}:
            return
        pause = PortalThrottled((response.headers or {}).get("retry-after"))
        pause.remember(self.vault)
        with closing(self.connect()) as db, db:
            db.execute("UPDATE cadence SET gap=min(?,gap*2),limited_at=? WHERE id=1", (MAX_GAP,self.clock()))
        deadline = status(self.vault) or {}
        self.last_limit = {"operation":kind or "portal", "method":method,
                           "source":deadline.get("source"), "until":deadline.get("until"),
                           "retry_seconds":pause.delay if pause.explicit else None}
        return pause

    def report(self):
        return {"requests":self.counts, "wait_seconds":round(self.waited,2), "limit":self.last_limit}


class PacedRequest:
    def __init__(self, request, traffic):
        self.raw, self.traffic = request, traffic

    def __getattr__(self, method):
        original = getattr(self.raw, method)
        if method not in {"get","post","put","patch","delete","head","fetch"}:
            return original
        def call(url, **kwargs):
            verb = kwargs.get("method", "GET") if method == "fetch" else method.upper()
            self.traffic.before(url, verb, kwargs.get("params"))
            reply = original(url, **kwargs)
            pause = self.traffic.after(reply, verb, kwargs.get("params"))
            if pause:
                reply.dispose()
                raise pause
            return reply
        return call


class PacedContext:
    def __init__(self, context, traffic):
        self.raw = context
        self.request = PacedRequest(context.request, traffic)

    def __getattr__(self, name):
        return getattr(self.raw, name)
