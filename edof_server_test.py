"""Test V2-only autonomous access experiment, separate from business data."""

import datetime as dt
import fcntl
import hashlib
import hmac
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, jsonify, redirect, request, send_file, session, url_for

from edof_readonly_test import TEST_SERVICE_ID, ID_RE, STATE_LABELS
from edof_gmail import Vault, GmailError, connector_key, oauth_configured, authorization_url, finish_authorization

JOB_TIMEOUT = 210
RETENTION = 86400
MESSAGES = {
    "running": "Essai en cours sur Render. Vous pouvez fermer votre Chrome : l’essai continue sur le serveur.",
    "login_reachable": "Render atteint le formulaire EFP Connect. La connexion à votre compte et la lecture d’un dossier restent à tester.",
    "credentials_missing": "Le formulaire EFP est accessible. Configurez EDOF_EFP_USERNAME et EDOF_EFP_PASSWORD dans les variables du service Render Test V2.",
    "read_success": "Dossier lu depuis Render, sans utiliser votre Chrome. Le détail de cet essai indique si une connexion a été réutilisée.",
    "human_verification": "Le site demande une vérification humaine. L’essai s’est arrêté : l’accès entièrement autonome n’est pas validé.",
    "verification_code": "EFP demande un code de vérification. L’essai s’est arrêté : l’accès entièrement autonome n’est pas validé.",
    "credentials_rejected": "EFP refuse les identifiants configurés. Aucun nouvel essai automatique n’a été lancé.",
    "account_unavailable": "EFP indique que le compte est bloqué ou désactivé. Aucun nouvel essai automatique n’a été lancé.",
    "account_action_required": "EFP demande une étape supplémentaire sur le compte. L’essai s’est arrêté sans valider cette étape.",
    "sign_in_error": "EFP affiche une erreur de connexion. Aucun dossier n’a été lu et aucun nouvel essai automatique n’a été lancé.",
    "login_form_not_allowed": "La destination du formulaire EFP diffère du parcours prévu. L’essai doit être adapté ; aucun identifiant n’a été saisi.",
    "authentication_unconfirmed": "La connexion n’a pas pu être confirmée. Aucun dossier n’a été lu.",
    "organism_selection_required": "La sélection automatique de l’établissement n’a pas abouti. Le parcours doit être adapté.",
    "workspace_dialog_required": "EDOF affiche une fenêtre devant le choix de l’établissement. Consultez le titre et les actions observés dans le diagnostic.",
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
    "gmail_not_configured": "La connexion Google du module doit être configurée avant de recevoir les codes automatiquement.",
    "gmail_not_connected": "Connectez le compte Gmail associé à EFP pour permettre la réception automatique des codes.",
    "gmail_reconnect_required": "Google a refusé ou révoqué l’autorisation. Reconnectez Gmail ; aucun nouvel essai EFP n’a été lancé.",
    "gmail_account_mismatch": "Le compte Google doit avoir exactement la même adresse que le compte EFP configuré dans Render.",
    "gmail_permission_missing": "L’autorisation Google de lecture hors connexion est incomplète. Reconnectez Gmail.",
    "gmail_unavailable": "Gmail n’a pas répondu correctement. L’essai s’est arrêté sans relancer la connexion EFP.",
    "gmail_response_invalid": "La réponse Gmail n’a pas pu être vérifiée. Aucun code n’a été utilisé.",
    "gmail_messages_ambiguous": "Plusieurs messages peuvent correspondre à la connexion EFP. Aucun code n’a été choisi.",
    "gmail_code_missing": "Aucun nouveau code EFP suffisamment vérifié n’a été trouvé dans Gmail pendant cet essai.",
    "otp_form_unrecognized": "Le formulaire du code EFP n’est pas reconnu. Aucun code n’a été transmis.",
    "otp_rejected": "La validation du code EFP n’a pas abouti. Aucun autre code n’a été essayé.",
    "private_storage_unavailable": "La protection de la connexion serveur n’est pas configurée. Aucun accès Gmail n’a été utilisé.",
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


class JobCooldown(ValueError):
    def __init__(self, remaining):
        self.remaining = remaining
        super().__init__(f"Le délai entre deux essais est commun au serveur. Nouvel essai possible dans {remaining} s.")


class ServerTestStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "edof_server_test.sqlite3"
        self.connector_key = None

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
                remaining = math.ceil(recent["created"] + delay - time.time()) if recent else 0
                if remaining > 0:
                    raise JobCooldown(remaining)
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

    def migrate_history(self, previous_owner, account_owner):
        db = self.connect()
        try:
            with db:
                db.execute("UPDATE jobs SET owner = ? WHERE owner = ?", (account_owner, previous_owner))
        finally:
            db.close()

    def successful_read(self, owner, *, spec=None, job_id=None):
        """Return a prior verified read, never an inferred match between homonyms."""
        db = self.connect()
        try:
            rows = db.execute(
                "SELECT id, finished, result FROM jobs WHERE owner = ? AND mode = 'read' "
                "AND finished IS NOT NULL AND json_extract(result, '$.code') = 'read_success' "
                "AND (? IS NULL OR id = ?) ORDER BY finished DESC, id DESC", (owner, job_id, job_id))
            found = None
            for row in rows:
                fields = json.loads(row["result"]).get("fields") or {}
                folder = fields.get("folder_id")
                if not folder:
                    continue
                if spec:
                    if spec["folder_id"] and str(folder) != spec["folder_id"]:
                        continue
                    if spec["first_name"] and any(
                        (fields.get(key) or "").strip().casefold() != spec[key].casefold()
                        for key in ("first_name", "last_name")
                    ):
                        continue
                    if found:
                        if str(found["fields"]["folder_id"]) != str(folder):
                            return None
                        continue
                checked = dt.datetime.fromtimestamp(row["finished"], ZoneInfo("Europe/Paris"))
                found = {"id": row["id"], "checked_at": checked.strftime("%d/%m/%Y à %H h %M"), "fields": fields}
                if not spec or spec["folder_id"]:
                    break
            return found
        finally:
            db.close()


def execute_job(store, job_id, spec, lock_fd):
    process = None
    temporary = tempfile.TemporaryDirectory(prefix="edof-server-test-")
    result = {"code": "browser_error"}
    try:
        # Do not pass unrelated app/CRM/database credentials to the child browser.
        permitted_env = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH", "RENDER_SERVICE_ID", "EDOF_EFP_USERNAME", "EDOF_EFP_PASSWORD"}
        child_env = {key: value for key, value in os.environ.items() if key in permitted_env}
        child_env["PYTHONUNBUFFERED"] = "1"
        # Chromium uses temporary profile files while running. Remove its whole
        # private working directory even after timeout/SIGKILL, not only when
        # Playwright manages to close the browser cleanly.
        child_env["TMPDIR"] = temporary.name
        if store.connector_key and spec["mode"] == "read":
            child_env["EDOF_CONNECTOR_KEY"] = store.connector_key
            child_env["EDOF_CONNECTOR_DIRECTORY"] = str(store.directory)
            for key in ("EDOF_GOOGLE_CLIENT_ID", "EDOF_GOOGLE_CLIENT_SECRET"):
                if key in os.environ:
                    child_env[key] = os.environ[key]
        process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("edof_server_browser.py"))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, env=child_env, start_new_session=True, pass_fds=(lock_fd,))
        output, _ = process.communicate(json.dumps(spec), timeout=JOB_TIMEOUT)
        if process.returncode == 0 and len(output) < 32768:
            parsed = json.loads(output)
            if isinstance(parsed, dict) and parsed.get("code") in MESSAGES:
                # The runner emits only the explicitly normalized dossier schema.
                result = {key: parsed[key] for key in ("code", "stage", "fields", "fresh_session", "gmail_code_used", "session_saved", "candidate_count", "blocked_writes", "diagnostics") if key in parsed}
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
            temporary.cleanup()
            store.finish(job_id, result)
        finally:
            os.close(lock_fd)


def last_read_stalled_at_login(jobs):
    # A failed lookup after a successful fresh login has not saved a new
    # browser, so it must not hide the preceding failed cookie restore.
    last = next((job for job in jobs if not (
        job.get("code") in {"timeout", "search_unconfirmed"} and job.get("stage") in {"search", "dossier"}
        and job.get("fresh_session") is True and job.get("gmail_code_used") is True and not job.get("session_saved")
    )), {})
    diag = last.get("diagnostics") or {}
    return (last.get("finished") is True and last.get("mode") == "read"
            and last.get("stage") == "login_page" and last.get("code") == "authentication_unconfirmed"
            and last.get("gmail_code_used") is False
            and diag.get("location") in {"edof_initialisation", "edof_folder_list", "edof_login_redirect"}
            and diag.get("edof_screen") in {"empty", "loading", "other", "session_expired"}
            and diag.get("error_banner_visible") is False and diag.get("password_form_visible") is False
            and not any(diag.get(key) for key in ("workspace_status", "workspace_denied", "login_post_status",
                                                  "blocked_edof_posts", "blocked_efp_posts", "blocked_other_posts")))


def start_job(store, owner, spec):
    store.directory.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(store.directory / "edof_server_test.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Un navigateur d’essai fonctionne déjà sur ce serveur.") from None
        # A new, explicitly started read can use standard sign-in if the last
        # run never reached an EFP form or the private workspace.
        if spec["mode"] == "read" and last_read_stalled_at_login(store.latest(owner)):
            spec = {**spec, "fresh_login": True}
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
    store.connector_key = connector_key(app.secret_key)

    def vault():
        if not store.connector_key:
            raise GmailError("private_storage_unavailable")
        return Vault(store.directory, store.connector_key)

    def gmail_status():
        result = {"configured": oauth_configured(), "protected": bool(store.connector_key), "connected": False, "saved_session": False}
        if store.connector_key:
            result["connected"] = bool(vault().get("gmail"))
            result["saved_session"] = bool(vault().get("browser"))
        return result

    def check_csrf():
        expected = session.get("edof_server_csrf", "")
        supplied = request.headers.get("X-CSRF-Token", "") or request.form.get("csrf", "")
        if not expected or not hmac.compare_digest(expected, supplied):
            abort(403)

    def edit_connection(action):
        # Do not disconnect/replace credentials while a browser uses them.
        fd = os.open(store.directory / "edof_server_test.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return redirect("/admin/edof-test/server?gmail=busy", code=303)
            action()
        finally:
            os.close(fd)
        return redirect("/admin/edof-test/server?gmail=connected", code=303)

    def owner():
        if not can_access():
            abort(403)
        token = session.setdefault("edof_server_owner", secrets.token_urlsafe(32))
        return hashlib.sha256(token.encode()).hexdigest()

    def results_owner():
        # OAuth state and CSRF stay tied to this browser. Verified reads follow
        # the authenticated admin account across its own browser sessions.
        previous = owner()
        username = session.get("admin_username")
        if not isinstance(username, str) or not username.strip():
            return previous
        key = app.secret_key.encode() if isinstance(app.secret_key, str) else app.secret_key
        account = hmac.digest(key, b"edof-test-results-v1\0" + username.strip().lower().encode(), "sha256").hex()
        if session.get("edof_history_account") != account:
            store.migrate_history(previous, account)
            session["edof_history_account"] = account
        return account

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
        user = results_owner()
        csrf = session.setdefault("edof_server_csrf", secrets.token_urlsafe(32))
        selected_id = request.args.get("result")
        if selected_id is not None and not re.fullmatch(r"[0-9a-f]{32}", selected_id):
            abort(404)
        last_read = store.successful_read(user, job_id=selected_id)
        return app.jinja_env.get_template("edof_server_test.html").render(
            csrf=csrf, config=configuration(), gmail=gmail_status(), gmail_notice={
                "connected": "Gmail est connecté. Vous pouvez lancer un essai serveur.",
                "disconnected": "La connexion Gmail et la session EFP enregistrées sur Render ont été effacées. Vous pouvez aussi retirer l’autorisation dans votre compte Google.",
                "canceled": "La connexion Google n’a pas été autorisée.",
                "invalid": "Cette demande de connexion a expiré. Recommencez depuis cette page.",
                "busy": "Un essai serveur est en cours. Attendez sa fin avant de modifier la connexion.",
                **MESSAGES}.get(request.args.get("gmail"), ""),
            jobs=store.latest(user), last_read=last_read, selected_result=selected_id is not None, state_labels=STATE_LABELS)

    @bp.get("/admin/edof-test/server/status")
    @admin_required
    def status():
        user = results_owner()
        return jsonify(ok=True, config=configuration(), gmail=gmail_status(), jobs=store.latest(user))

    @bp.post("/admin/edof-test/server/gmail/connect")
    @admin_required
    def gmail_connect():
        user = owner()
        check_csrf()
        if not oauth_configured() or not configuration()["credentials_configured"] or not store.connector_key:
            return redirect("/admin/edof-test/server?gmail=gmail_not_configured", code=303)
        if request.form.get("consent") != "yes":
            abort(400)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        vault().put("oauth:" + user, {"state": state, "verifier": verifier}, ttl=600)
        session["edof_gmail_state"] = state
        return redirect(authorization_url(state, verifier), code=303)

    @bp.get("/admin/edof-test/server/gmail/callback")
    @admin_required
    def gmail_callback():
        user = owner()
        state = request.args.get("state", "")
        expected = session.pop("edof_gmail_state", "")
        if not state or not expected or not hmac.compare_digest(state, expected) or not store.connector_key:
            return redirect("/admin/edof-test/server?gmail=invalid", code=303)
        pending = vault().get("oauth:" + user, consume=True)
        if not pending or not hmac.compare_digest(state, pending["state"]):
            return redirect("/admin/edof-test/server?gmail=invalid", code=303)
        code = request.args.get("code", "")
        if request.args.get("error") or not code or len(code) > 4096:
            return redirect("/admin/edof-test/server?gmail=canceled", code=303)
        try:
            return edit_connection(lambda: finish_authorization(vault(), code, pending["verifier"]))
        except GmailError as exc:
            return redirect("/admin/edof-test/server?gmail=" + exc.code, code=303)

    @bp.post("/admin/edof-test/server/gmail/disconnect")
    @admin_required
    def gmail_disconnect():
        owner()
        check_csrf()
        response = edit_connection(lambda: vault().clear())
        if response.location.endswith("gmail=connected"):
            response.location = "/admin/edof-test/server?gmail=disconnected"
        return response

    @bp.get("/admin/edof-test/server/script.js")
    @admin_required
    def script():
        owner()
        return send_file(Path(__file__).parent / "edof_test_assets" / "server.js")

    @bp.post("/admin/edof-test/server/run")
    @admin_required
    def run():
        user = results_owner()
        check_csrf()
        if request.content_length is None or request.content_length > 2048:
            return jsonify(ok=False, error="Paramètres trop volumineux."), 413
        try:
            spec = validate_spec(request.get_json(silent=True))
            if spec["mode"] == "read" and request.args.get("prefer_saved") == "1":
                saved = store.successful_read(user, spec=spec)
                if saved:
                    return jsonify(ok=True, saved=True, job_id=saved["id"],
                                   result_url=url_for("edof_server_test.index", result=saved["id"], _anchor="dossier-lu"))
            if spec["mode"] == "read" and not configuration()["credentials_configured"]:
                return jsonify(ok=False, error=MESSAGES["credentials_missing"]), 409
            job_id = start_job(store, user, spec)
        except JobCooldown as exc:
            return jsonify(ok=False, error=str(exc), retry_after=exc.remaining), 429, {"Retry-After": str(exc.remaining)}
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        return jsonify(ok=True, job_id=job_id), 202

    app.register_blueprint(bp)
