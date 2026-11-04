"""Durable full refresh after an interruption; never grants an EFP login attempt."""
from contextlib import closing
import datetime as dt
import sqlite3
import time

from cpf_provider import ProviderStore, provider_operation
from edof_day_session import PARIS, POLL_SECONDS, working_hours
from edof_gmail import Vault
import edof_directory as directory

RETRY_SECONDS = 900
READY = {"directory_ready", "requests_ready"}


def install(db):
    db.execute("""CREATE TABLE IF NOT EXISTS directory_recovery (
        owner TEXT PRIMARY KEY, since REAL NOT NULL, reason TEXT NOT NULL,
        retry_after REAL NOT NULL DEFAULT 0, job_id TEXT, revision INTEGER,
        completed REAL, message TEXT NOT NULL DEFAULT '')""")


def mark(db, owner, reason, now=None):
    """Keep the first interruption until its complete refresh has been analysed."""
    db.execute("""INSERT INTO directory_recovery(owner,since,reason) VALUES(?,?,?)
        ON CONFLICT(owner) DO UPDATE SET since=excluded.since,reason=excluded.reason,
        retry_after=0,job_id=NULL,revision=NULL,completed=NULL,message=''
        WHERE directory_recovery.completed IS NOT NULL""", (owner, time.time() if now is None else now, reason))


def claim(db, owner, job_id, since, revision):
    changed = db.execute("""UPDATE directory_recovery SET job_id=?,revision=?,message=''
        WHERE owner=? AND since=? AND completed IS NULL AND job_id IS NULL AND retry_after<=?""",
        (job_id, revision, owner, since, time.time())).rowcount
    if not changed:
        raise ValueError("Reprise déjà prise en charge.")


def finished(db, job, result):
    if not job or job["mode"] != "directory":
        return
    code = result.get("code")
    if code not in READY and code != "day_closed":
        mark(db, job["owner"], code or "interrupted")
        # A new outage after the full read invalidates that read for this recovery.
        db.execute("""UPDATE directory_recovery SET job_id=NULL,revision=NULL,retry_after=?
            WHERE owner=? AND completed IS NULL AND job_id IS NOT NULL AND job_id<>?""",
            (time.time()+RETRY_SECONDS,job["owner"],job["id"]))
    if code != "directory_ready":
        db.execute("""UPDATE directory_recovery SET job_id=NULL,revision=NULL,retry_after=?,message=?
            WHERE job_id=? AND completed IS NULL""",
            (time.time()+RETRY_SECONDS, "La lecture complète n’a pas abouti. Une nouvelle tentative est prévue après le délai de reprise et le retour de la connexion.", job["id"]))


def prepare(store, selection, now=None):
    """Detect missed polling and finish local analysis of verified full reads."""
    if selection["provider"] != "integrale" or selection["pending"] or not store.connector_key:
        return
    now = now or dt.datetime.now(PARIS)
    with closing(store.connect()) as db, db:
        if working_hours(now):
            owners = db.execute("""SELECT a.owner,j.finished FROM directory_activity a LEFT JOIN jobs j
                ON j.id=(SELECT id FROM jobs WHERE owner=a.owner AND mode='directory' ORDER BY created DESC LIMIT 1)""").fetchall()
            for row in owners:
                if row["finished"] and row["finished"] < now.timestamp()-POLL_SECONDS*3:
                    mark(db, row["owner"], "missed_poll", now.timestamp())
        # A retained request survives restarts and expiry of the technical jobs table.
        db.execute("""UPDATE directory_recovery SET job_id=NULL,revision=NULL
            WHERE completed IS NULL AND job_id IS NOT NULL AND
            (revision<>? OR NOT EXISTS(SELECT 1 FROM jobs WHERE id=directory_recovery.job_id))""", (selection["revision"],))
        runs = db.execute("""SELECT r.*,j.created,j.finished,json_extract(j.result,'$.code') AS code
            FROM directory_recovery r JOIN jobs j ON j.id=r.job_id
            WHERE r.completed IS NULL AND j.finished IS NOT NULL AND r.retry_after<=?""", (now.timestamp(),)).fetchall()
    for run in runs:
        if not (working_hours(now) and store.directory_enabled(run["owner"]) or store.manual_until(run["owner"])):
            continue
        if run["code"] != "directory_ready":
            with closing(store.connect()) as db, db:
                db.execute("""UPDATE directory_recovery SET job_id=NULL,revision=NULL,retry_after=?
                    WHERE owner=? AND since=? AND job_id=?""", (now.timestamp()+RETRY_SECONDS,run["owner"],run["since"],run["job_id"]))
            continue
        try:
            with provider_operation("integrale"):
                if ProviderStore(store.directory).state()["revision"] != run["revision"]:
                    continue
                snap = Vault(store.directory, store.connector_key).get(directory.record_key(run["owner"]), keep=True)
                if not snap or snap.get("scope") != "all" or (snap.get("checked") or 0) < max(run["since"],run["created"]):
                    # A partial or stale list cannot fulfil a recovery.
                    with closing(store.connect()) as db, db:
                        db.execute("UPDATE directory_recovery SET job_id=NULL,revision=NULL,retry_after=? WHERE owner=? AND since=?",
                                   (now.timestamp()+RETRY_SECONDS,run["owner"],run["since"]))
                    continue
                from integrale_edof_sync import process_directory
                from integrale_edof_dashboard import apply_confirmed_entries
                from edof_declarations import discover
                process_directory(store, directory.dated_snapshot(snap), owner=run["owner"])
                report = discover(store, run["owner"], apply_confirmed_entries(snap,store.directory,run["owner"]))
                if report is None:
                    continue
            queued = report["entry_training"] + report["service_done"]
            issues = report["blocked"] + report["missing"] + report["review"]
            message = (f"Reprise automatique · liste complète vérifiée le {now.strftime('%d/%m/%Y à %Hh%M')}. "
                       f"Automatisations préparées : {queued}. À vérifier : {issues}.")
            with closing(store.connect()) as db, db:
                db.execute("""UPDATE directory_recovery SET completed=?,message=?
                    WHERE owner=? AND since=? AND job_id=? AND completed IS NULL""",
                    (now.timestamp(),message,run["owner"],run["since"],run["job_id"]))
        except (OSError, ValueError, sqlite3.Error):
            # Retain the source read and retry local analysis without another EDOF write.
            with closing(store.connect()) as db, db:
                db.execute("UPDATE directory_recovery SET retry_after=?,message=? WHERE owner=? AND since=? AND completed IS NULL",
                           (now.timestamp()+RETRY_SECONDS,"Liste complète reçue. L’analyse sera reprise automatiquement.",run["owner"],run["since"]))


def next_job(store, selection, now=None):
    if selection["provider"] != "integrale" or selection["pending"] or not store.connector_key:
        return None
    now = now or dt.datetime.now(PARIS)
    vault = Vault(store.directory, store.connector_key)
    if not vault.get("gmail") or vault.get("edof-throttled"):
        return None
    with closing(store.connect()) as db:
        rows = db.execute("""SELECT r.*,j.finished,json_extract(j.result,'$.code') AS code
            FROM directory_recovery r JOIN jobs j ON j.id=(SELECT id FROM jobs WHERE owner=r.owner
                AND mode='directory' ORDER BY created DESC LIMIT 1)
            WHERE r.completed IS NULL AND r.job_id IS NULL AND r.retry_after<=? ORDER BY r.since""", (now.timestamp(),)).fetchall()
    for row in rows:
        if not (working_hours(now) and store.directory_enabled(row["owner"]) or store.manual_until(row["owner"])):
            continue
        # Only a fresh successful private read unlocks a full catch-up. No code override.
        if row["code"] in READY and row["finished"] >= row["since"] and 0 <= now.timestamp()-row["finished"] < POLL_SECONDS*3:
            return {"mode":"directory", "owner":row["owner"], "provider":"integrale",
                    "recovery_since":row["since"], "revision":selection["revision"]}
    return None


def status(store, owner):
    with closing(store.connect()) as db:
        row = db.execute("SELECT * FROM directory_recovery WHERE owner=?", (owner,)).fetchone()
    if not row:
        return None
    message = row["message"] or ("Reprise automatique · synchronisation complète et rattrapage en cours." if row["job_id"] else
                                "Reprise automatique prévue · la synchronisation complète et le rattrapage démarreront dès le retour de la connexion EDOF.")
    return {"pending":row["completed"] is None, "message":message}


def pending(store, owner):
    with closing(store.connect()) as db:
        return bool(db.execute("SELECT 1 FROM directory_recovery WHERE owner=? AND completed IS NULL", (owner,)).fetchone())
