"""Bounded, durable queue for interactive training convocations.

Only the worker runs the requested POST. It replays the original access checks
and does not repeat an email whose delivery may already have begun.
"""
from contextlib import closing, contextmanager
import copy
import fcntl
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from flask import g, jsonify, request, session, url_for

_START_LOCK = threading.Lock()
SESSION_FIELDS = (
    "admin_logged_in", "admin_role", "admin_username", "admin_email", "admin_user_id",
    "platform_role", "user_id", "partner_id", "assist_partner_id", "manuals_only", "session_issued_at",
)
UNCERTAIN = {
    "ok": False, "uncertain": True,
    "error": "L’envoi a été lancé mais sa réception reste à vérifier dans l’historique des e-mails avant tout nouvel envoi.",
}


def _database_path(host):
    return Path(host.PERSIST_DIR) / "convocation-jobs.sqlite3"


@contextmanager
def _database(path):
    with closing(sqlite3.connect(path, timeout=4)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        with db:
            yield db


def _install(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with _database(path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, tenant TEXT NOT NULL, operation TEXT NOT NULL,
                session_id TEXT NOT NULL, trainee_id TEXT NOT NULL, mode INTEGER NOT NULL,
                path TEXT NOT NULL, origin TEXT NOT NULL, auth TEXT NOT NULL,
                state TEXT NOT NULL, created REAL NOT NULL, result TEXT, http_code INTEGER
            );
            CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(state, created);
            CREATE TABLE IF NOT EXISTS requests (
                tenant TEXT NOT NULL, operation TEXT NOT NULL, session_id TEXT NOT NULL,
                trainee_id TEXT NOT NULL, request_key TEXT NOT NULL,
                job TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                PRIMARY KEY(tenant,operation,session_id,trainee_id,request_key)
            );
        """)


def start_worker(host, *, create=False):
    path = _database_path(host)
    if not create and not path.exists():
        return
    with _START_LOCK:
        state = host.app.extensions.get("convocation_jobs")
        if state and state["path"] == path and state["thread"].is_alive():
            return state
        _install(path)
        state = {"path": path, "wake": threading.Event(), "stop": threading.Event()}
        thread = threading.Thread(target=_run, args=(host, state), name="convocations", daemon=True)
        state["thread"] = thread
        host.app.extensions["convocation_jobs"] = state
        thread.start()
        return state


def _finish(db, job_id, result, code):
    db.execute("UPDATE jobs SET state='finished',result=?,http_code=?,auth='{}' WHERE id=?",
               (json.dumps(result, ensure_ascii=False), code, job_id))


def _response(row):
    if row["state"] == "finished":
        return jsonify(json.loads(row["result"])), row["http_code"], {"X-Convocation-Job-State": "finished"}
    public_state = "queued" if row["state"] == "queued" else "running"
    return jsonify(ok=True, job_id=row["id"], status=public_state,
                   status_url=url_for("admin_convocation_job_status", job_id=row["id"])), 202, {"Retry-After":"2"}


def _tenant(host):
    return host._current_partner_id() or getattr(host, "INTEGRALE_PARTNER_ID", "")


def defer(host, action, session_id, trainee_id):
    name = request.headers.get("Idempotency-Key") or uuid.uuid4().hex
    if len(name) > 128 or not name.isascii() or not name.isprintable():
        return jsonify(ok=False, error="Identifiant de demande invalide."), 400
    body = request.get_json(silent=True) or {}
    skip_sent = bool(isinstance(body, dict) and body.get("skip_if_already_sent"))
    scope = (_tenant(host), action, session_id, trainee_id)
    auth = {key:session[key] for key in SESSION_FIELDS if key in session}
    runner = start_worker(host, create=True)
    with _database(runner["path"]) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM jobs WHERE state='finished' AND created<?", (time.time()-30*86400,))
        row = db.execute("""SELECT jobs.* FROM requests r JOIN jobs ON jobs.id=r.job
            WHERE r.tenant=? AND r.operation=? AND r.session_id=? AND r.trainee_id=? AND r.request_key=?""",
                         (*scope, name)).fetchone()
        if row:
            return _response(row)
        row = db.execute("""SELECT * FROM jobs WHERE tenant=? AND operation=? AND session_id=? AND trainee_id=?
                            AND state!='finished'""", scope).fetchone()
        if not row:
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state!='finished'").fetchone()[0] >= 64:
                return jsonify(ok=False, error="La file des convocations est pleine. Réessayez dans un instant."), 429
            job_id = uuid.uuid4().hex
            db.execute("""INSERT INTO jobs(id,tenant,operation,session_id,trainee_id,mode,path,origin,auth,state,created)
                          VALUES(?,?,?,?,?,?,?,?,?,'queued',?)""",
                       (job_id, *scope, int(skip_sent), request.path, getattr(host, "PUBLIC_BASE_URL", None) or "http://localhost", json.dumps(auth), time.time()))
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        db.execute("INSERT INTO requests VALUES(?,?,?,?,?,?)", (*scope, name, row["id"]))
    runner["wake"].set()
    return _response(row)


def status(host, job_id):
    path = _database_path(host)
    row = None
    if path.exists():
        with _database(path) as db:
            row = db.execute("SELECT * FROM jobs WHERE id=? AND tenant=?", (job_id, _tenant(host))).fetchone()
    if row is None:
        return jsonify(ok=False, error="Traitement de convocation introuvable."), 404
    return _response(row)


def begin_delivery():
    job = g.get("convocation_job")
    if not job:
        return {}
    path, job_id = job
    with _database(path) as db:
        changed = db.execute("UPDATE jobs SET state='sending' WHERE id=? AND state='running'", (job_id,)).rowcount
        if not changed:
            raise RuntimeError("L’envoi a déjà été pris en charge.")
    return {"metadata": {"idempotency_key": job_id}}


def _execute(host, path, row):
    with host.app.test_request_context(row["path"], base_url=row["origin"], method="POST",
                                       headers={"Accept":"application/json"}, json={"skip_if_already_sent":bool(row["mode"])}):
        session.update(json.loads(row["auth"]))
        g.convocation_job = (path, row["id"])
        reply = host.app.full_dispatch_request()
        payload = reply.get_json(silent=True)
        if not isinstance(payload, dict):
            return {"ok":False, "error":"Le traitement n’a pas abouti. Vérifiez vos droits sur ce dossier."}, 403
        return payload, reply.status_code


def _run(host, state):
    while not state["stop"].is_set():
        try:
            _drain(host, state)
        except (sqlite3.Error, OSError):
            host.app.logger.exception("convocation_queue_storage_unavailable")
            state["stop"].wait(5)


def _drain(host, state):
    path = state["path"]
    # Render may overlap workers during a shutdown. Only the lock owner can
    # recover unfinished work or deliver queued messages.
    with open(str(path)+".worker.lock", "a+") as lock:
        while not state["stop"].is_set():
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                state["stop"].wait(1)
        else:
            return
        with _database(path) as db:
            db.execute("UPDATE jobs SET state='queued' WHERE state='running'")
            for row in db.execute("SELECT id FROM jobs WHERE state='sending'").fetchall():
                _finish(db, row["id"], UNCERTAIN, 409)
        while not state["stop"].is_set():
            state["wake"].clear()
            with _database(path) as db:
                row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
                if row:
                    db.execute("UPDATE jobs SET state='running' WHERE id=?", (row["id"],))
            if not row:
                state["wake"].wait(5)
                continue
            try:
                payload, code = _execute(host, path, row)
            except Exception:
                host.app.logger.exception("convocation_job_failed job=%s", row["id"])
                payload, code = {"ok":False, "error":"Le traitement de la convocation a échoué."}, 500
            with _database(path) as db:
                current = db.execute("SELECT state FROM jobs WHERE id=?", (row["id"],)).fetchone()
                if current["state"] == "sending" and not payload.get("ok") and not payload.get("delivery_refused"):
                    payload, code = UNCERTAIN, 409
                _finish(db, row["id"], payload, code)


def _document_fields(trainee):
    return {key:value for key, value in trainee.items()
            if key.startswith(("convocation_aps_", "convocation_auto_"))
            or key in ("updated_at", "vtc_practice_convocation_sent_at", "sent_email_history")}


def remember_fields(trainee):
    if g.get("convocation_job"):
        g.convocation_before = copy.deepcopy(_document_fields(trainee))


def save_result(host, data, training, trainee):
    if not g.get("convocation_job"):
        host.save_data(data)
        return

    before = g.convocation_before
    changes = {key:value for key, value in _document_fields(trainee).items() if before.get(key) != value}

    def apply(latest):
        session_id = str(training["id"])
        trainee_id = str(trainee["id"])
        _, _, current = host._find_session_trainee(latest, session_id, trainee_id)
        if not current:
            raise ValueError("Ce dossier n’est plus disponible.")
        for key, value in changes.items():
            if key == "sent_email_history":
                new_entries = [item for item in value if item not in (before.get(key) or [])]
                current[key] = (new_entries + (current.get(key) or []))[:200]
            elif key == "convocation_aps_previous_pdf_tokens":
                current[key] = list(dict.fromkeys((current.get(key) or []) + value))
            elif key == "updated_at":
                current[key] = max(str(current.get(key) or ""), value)
            elif current.get(key) == before.get(key):
                current[key] = value
        return {}

    host._atomic_update_data(apply)
