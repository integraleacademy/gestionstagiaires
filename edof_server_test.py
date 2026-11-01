"""Test V2-only autonomous access experiment, separate from business data."""

import datetime as dt
import fcntl
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time

from flask import Blueprint, abort, jsonify, request, send_file, session

from edof_readonly_test import TEST_SERVICE_ID, ID_RE, STATE_LABELS

JOB_TIMEOUT = 150
RETENTION = 86400
MESSAGES = {
    "running": "Essai en cours sur Render. Vous pouvez fermer votre Chrome : l’essai continue sur le serveur.",
    "login_reachable": "Render atteint le formulaire EFP Connect. La connexion à votre compte et la lecture d’un dossier restent à tester.",
    "credentials_missing": "Le formulaire EFP est accessible. Configurez EDOF_EFP_USERNAME et EDOF_EFP_PASSWORD dans les variables du service Render Test V2.",
    "read_success": "Dossier lu depuis Render après une connexion EFP neuve, sans utiliser votre Chrome.",
    "human_verification": "Le site demande une vérification humaine. L’essai s’est arrêté : l’accès entièrement autonome n’est pas validé.",
    "verification_code": "EFP demande un code de vérification. L’essai s’est arrêté : l’accès entièrement autonome n’est pas validé.",
    "credentials_rejected": "EFP refuse les identifiants configurés. Aucun nouvel essai automatique n’a été lancé.",
    "authentication_unconfirmed": "La connexion n’a pas pu être confirmée. Aucun dossier n’a été lu.",
    "organism_selection_required": "La sélection automatique de l’établissement n’a pas abouti. Le parcours doit être adapté.",
    "search_unconfirmed": "La recherche par nom n’a pas produit de réponse exploitable. Le parcours doit être adapté.",
    "search_incomplete": "La recherche comporte plusieurs pages ou son total est inconnu. Aucune correspondance unique n’a été affirmée.",
    "no_match": "Aucun dossier ne correspond exactement au nom et au prénom dans le résultat de cette recherche.",
    "ambiguous": "Plusieurs dossiers portent ce nom et ce prénom. Un numéro CPF ou des critères supplémentaires sont nécessaires.",
    "identity_mismatch": "Le dossier lu ne correspond pas au nom et au prénom demandés. Il n’a pas été retenu.",
    "read_unconfirmed": "La réponse du dossier n’a pas été reçue. La lecture autonome reste à valider.",
    "response_unrecognized": "EDOF a retourné une réponse dont le format n’est pas reconnu par cet essai.",
    "unexpected_page": "La page de connexion n’est pas celle attendue. Aucun identifiant n’a été transmis.",
    "timeout": "Le délai de l’essai est dépassé. Le navigateur du serveur a été arrêté.",
    "interrupted": "L’essai a été interrompu, par exemple par un redémarrage. Aucun succès n’est supposé.",
    "browser_missing": "Le navigateur serveur n’est pas installé dans cette version du déploiement.",
    "browser_error": "Le navigateur serveur n’a pas terminé l’essai. Aucun succès n’est supposé.",
    "wrong_environment": "Cet essai est réservé au service Test V2.",
}


def validate_spec(payload):
    if not isinstance(payload, dict) or set(payload) - {"mode", "folder_id", "first_name", "last_name"}:
        raise ValueError("Paramètres d’essai invalides.")
    if payload.get("mode") not in {"access", "read"}:
        raise ValueError("Choisissez un essai d’accès ou de lecture.")
    result = {"mode": payload["mode"]}
    if result["mode"] == "access":
        return result
    for key in ("folder_id", "first_name", "last_name"):
        value = payload.get(key, "")
        if not isinstance(value, str) or len(value) > 120 or any(ord(c) < 32 for c in value):
            raise ValueError("Un critère de recherche est invalide.")
        result[key] = value.strip()
    if result["folder_id"] and not ID_RE.fullmatch(result["folder_id"]):
        raise ValueError("Le numéro CPF doit contenir uniquement des chiffres.")
    if bool(result["first_name"]) != bool(result["last_name"]):
        raise ValueError("Renseignez le nom et le prénom ensemble.")
    if not result["folder_id"] and not result["first_name"]:
        raise ValueError("Renseignez un numéro CPF ou le nom et le prénom.")
    return result


def configuration():
    return {
        "credentials_configured": bool(os.environ.get("EDOF_EFP_USERNAME", "").strip() and os.environ.get("EDOF_EFP_PASSWORD")),
        "browser_installed": importlib.util.find_spec("playwright") is not None,
    }


class ServerTestStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "edof_server_test.sqlite3"

    def connect(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA secure_delete = ON")
        db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, created REAL NOT NULL, finished REAL, mode TEXT NOT NULL, result TEXT NOT NULL)")
        db.execute("DELETE FROM jobs WHERE created < ?", (time.time() - RETENTION,))
        db.execute("UPDATE jobs SET finished = ?, result = ? WHERE finished IS NULL AND created < ?",
                   (time.time(), json.dumps({"code": "interrupted"}), time.time() - JOB_TIMEOUT - 30))
        db.commit()
        return db

    def reserve(self, owner, mode):
        db = self.connect()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT 1 FROM jobs WHERE finished IS NULL").fetchone():
                    raise ValueError("Un essai est déjà en cours sur ce serveur.")
                # Prevent repeated password attempts; no automatic retry loop.
                recent = db.execute("SELECT created FROM jobs WHERE mode = ? ORDER BY created DESC LIMIT 1", (mode,)).fetchone()
                delay = 300 if mode == "read" else 30
                if recent and time.time() - recent["created"] < delay:
                    raise ValueError(f"Attendez {delay} secondes entre deux essais de ce type.")
                job_id = secrets.token_hex(16)
                db.execute("INSERT INTO jobs (id, owner, created, mode, result) VALUES (?, ?, ?, ?, ?)",
                           (job_id, owner, time.time(), mode, json.dumps({"code": "running"})))
            return job_id
        finally:
            db.close()

    def finish(self, job_id, result):
        db = self.connect()
        try:
            with db:
                db.execute("UPDATE jobs SET result = ?, finished = ? WHERE id = ?",
                           (json.dumps(result, ensure_ascii=False), time.time(), job_id))
        finally:
            db.close()

    def latest(self, owner):
        db = self.connect()
        try:
            rows = db.execute("SELECT * FROM jobs WHERE owner = ? ORDER BY created DESC LIMIT 3", (owner,)).fetchall()
            result = []
            for row in rows:
                detail = json.loads(row["result"])
                code = detail.get("code", "browser_error")
                result.append({"id": row["id"], "mode": row["mode"],
                    "created_at": dt.datetime.fromtimestamp(row["created"], dt.timezone.utc).isoformat(),
                    "finished": row["finished"] is not None, "message": MESSAGES.get(code, MESSAGES["browser_error"]), **detail})
            return result
        finally:
            db.close()


def execute_job(store, job_id, spec, lock_fd):
    process = None
    result = {"code": "browser_error"}
    try:
        # Do not pass unrelated app/CRM/database credentials to the child browser.
        permitted_env = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH", "RENDER_SERVICE_ID", "EDOF_EFP_USERNAME", "EDOF_EFP_PASSWORD"}
        child_env = {key: value for key, value in os.environ.items() if key in permitted_env}
        child_env["PYTHONUNBUFFERED"] = "1"
        process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("edof_server_browser.py"))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, env=child_env, start_new_session=True, pass_fds=(lock_fd,))
        output, _ = process.communicate(json.dumps(spec), timeout=JOB_TIMEOUT)
        if process.returncode == 0 and len(output) < 32768:
            parsed = json.loads(output)
            if isinstance(parsed, dict) and parsed.get("code") in MESSAGES:
                # The runner emits only the explicitly normalized dossier schema.
                result = {key: parsed[key] for key in ("code", "stage", "fields", "fresh_session", "candidate_count", "blocked_writes") if key in parsed}
    except subprocess.TimeoutExpired:
        result = {"code": "timeout"}
    except Exception:
        pass  # Never expose subprocess diagnostics, page URLs or auth material.
    finally:
        if process is not None:
            # Clean up the entire Chromium process tree, even if the runner died.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        try:
            store.finish(job_id, result)
        finally:
            os.close(lock_fd)


def start_job(store, owner, spec):
    store.directory.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(store.directory / "edof_server_test.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Un navigateur d’essai fonctionne déjà sur ce serveur.") from None
        job_id = store.reserve(owner, spec["mode"])
        thread = threading.Thread(target=execute_job, args=(store, job_id, spec, lock_fd), daemon=True)
        thread.start()
        return job_id
    except Exception:
        os.close(lock_fd)
        raise


def register_edof_server_test(legacy):
    if os.environ.get("RENDER_SERVICE_ID") != TEST_SERVICE_ID:
        return
    register_routes(legacy.app, ServerTestStore("/var/data"),
        admin_required=legacy.admin_login_required,
        can_access=lambda: legacy._is_super_admin_session() and not session.get("assist_partner_id"))


def register_routes(app, store, *, admin_required, can_access):
    bp = Blueprint("edof_server_test", __name__)

    def owner():
        if not can_access():
            abort(403)
        token = session.setdefault("edof_server_owner", secrets.token_urlsafe(32))
        return hashlib.sha256(token.encode()).hexdigest()

    @bp.after_request
    def private(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @bp.get("/admin/edof-test/server")
    @admin_required
    def index():
        user = owner()
        csrf = session.setdefault("edof_server_csrf", secrets.token_urlsafe(32))
        return app.jinja_env.get_template("edof_server_test.html").render(
            csrf=csrf, config=configuration(), jobs=store.latest(user), state_labels=STATE_LABELS)

    @bp.get("/admin/edof-test/server/status")
    @admin_required
    def status():
        user = owner()
        return jsonify(ok=True, config=configuration(), jobs=store.latest(user))

    @bp.get("/admin/edof-test/server/script.js")
    @admin_required
    def script():
        owner()
        return send_file(Path(__file__).parent / "edof_test_assets" / "server.js")

    @bp.post("/admin/edof-test/server/run")
    @admin_required
    def run():
        user = owner()
        expected = session.get("edof_server_csrf", "")
        if not expected or not hmac.compare_digest(expected, request.headers.get("X-CSRF-Token", "")):
            abort(403)
        if request.content_length is None or request.content_length > 2048:
            return jsonify(ok=False, error="Paramètres trop volumineux."), 413
        try:
            spec = validate_spec(request.get_json(silent=True))
            if spec["mode"] == "read" and not configuration()["credentials_configured"]:
                return jsonify(ok=False, error=MESSAGES["credentials_missing"]), 409
            job_id = start_job(store, user, spec)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        return jsonify(ok=True, job_id=job_id), 202

    app.register_blueprint(bp)
