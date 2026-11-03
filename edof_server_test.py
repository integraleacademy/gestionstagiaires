"""Test V2-only autonomous access experiment, separate from business data."""

import datetime as dt
import fcntl
import hashlib
import hmac
import importlib.util
import itertools
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

from contextlib import closing
from flask import flash, Blueprint, abort, jsonify, redirect, request, send_file, session, url_for

from cpf_provider import acquire_provider
from edof_readonly_test import TEST_SERVICE_ID, ID_RE, STATE_LABELS
from edof_server_browser import stalled_before_login
from edof_day_session import DayWorker, POLL_SECONDS, PARIS, working_hours
import edof_directory as directory
import edof_declarations as declarations
from edof_gmail import Vault, GmailError, connector_key, oauth_configured, authorization_url, finish_authorization

JOB_TIMEOUT = 210
DIRECTORY_TIMEOUT = 420
DECLARATION_TIMEOUT = 360
RETENTION = 86400
AUTH_MODES = {"read", "directory", "declare", "reconcile", "inspect_forms"}
MESSAGES = {
    **declarations.REASONS,
    "day_login_used": "EFP demande encore une authentification. La veille est en pause. Autorisez une reprise dans les paramètres ou attendez le prochain jour ouvré.",
    "day_closed": "La veille est ouverte du lundi au vendredi, de 8 h à 19 h, heure de Paris.",
    "declaration_confirmed": "Le statut et les valeurs de la déclaration ont été relus sur EDOF.",
    "declaration_inspected": "Contrôle des commandes disponibles sur EDOF terminé en lecture seule.",
    "directory_ready": "La liste EDOF de l’établissement est disponible pour la recherche.",
    "directory_unavailable": "EDOF n’a pas renvoyé la liste de l’établissement. Vous pouvez reprendre la synchronisation.",
    "directory_incomplete": "La liste renvoyée par EDOF est incomplète. La dernière liste vérifiée reste consultable.",
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
        self.data_file = None

    def connect(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA secure_delete = ON")
        db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, created REAL NOT NULL, finished REAL, mode TEXT NOT NULL, result TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS directory_activity (owner TEXT PRIMARY KEY, seen REAL NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS manual_sessions (owner TEXT PRIMARY KEY, started REAL NOT NULL, until REAL NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS directory_requested (owner TEXT PRIMARY KEY)")
        db.execute("DELETE FROM jobs WHERE created < ?", (time.time() - RETENTION,))
        db.execute("UPDATE jobs SET finished = ?, result = ? WHERE finished IS NULL "
                   "AND created < ? - CASE WHEN mode = 'directory' THEN ? WHEN mode IN ('declare','reconcile') THEN ? ELSE ? END",
                   (time.time(), json.dumps({"code": "interrupted"}), time.time() - 30, DIRECTORY_TIMEOUT, DECLARATION_TIMEOUT, JOB_TIMEOUT))
        db.commit()
        return db

    def reserve(self, owner, mode, *, day_session=False):
        db = self.connect()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT 1 FROM jobs WHERE finished IS NULL").fetchone():
                    raise ValueError("Un essai est déjà en cours sur ce serveur.")
                # Prevent repeated password attempts; no automatic retry loop.
                auth = mode in AUTH_MODES
                group = sorted(AUTH_MODES) if auth else [mode]
                recent = db.execute("SELECT MAX(created) AS created FROM jobs WHERE coalesce(json_extract(result,'$.day_session'),0)=0 AND mode IN (" +
                                    ",".join("?" for _ in group)+")", group).fetchone()
                delay = 300 if auth else 30
                remaining = math.ceil(recent["created"] + delay - time.time()) if recent["created"] is not None else 0
                if remaining > 0 and not day_session:
                    raise JobCooldown(remaining)
                if mode == "directory":
                    db.execute("DELETE FROM directory_requested WHERE owner=?", (owner,))
                job_id = secrets.token_hex(16)
                db.execute("INSERT INTO jobs (id, owner, created, mode, result) VALUES (?, ?, ?, ?, ?)",
                           (job_id, owner, time.time(), mode, json.dumps({"code": "running", "day_session": day_session})))
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

    def connection_status(self, owner, saved_session):
        # Only a completed read of the private portal can confirm access.
        # Cached lookups and the public EFP form do not check a session.
        db = self.connect()
        try:
            row = db.execute(
                "SELECT finished, json_extract(result, '$.code') AS code, "
                "json_extract(result, '$.diagnostics.edof_screen') AS screen "
                "FROM jobs WHERE owner = ? AND mode IN ('read', 'directory') AND finished IS NOT NULL "
                "ORDER BY finished DESC, id DESC LIMIT 1", (owner,),
            ).fetchone()
        finally:
            db.close()

        checked_at = None
        if row:
            checked_at = dt.datetime.fromtimestamp(row["finished"], ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H h %M")
        if row and row["screen"] == "session_expired":
            state, label = "expired", "Session expirée au dernier contrôle"
        elif row and row["code"] == "day_login_used":
            state, label = "day_paused", "Veille en pause · EFP redemande un code"
        elif row and row["code"] in {"credentials_rejected", "account_unavailable", "verification_code",
                                    "otp_rejected", "account_action_required", "sign_in_error"}:
            state, label = "reconnect", "Reconnexion nécessaire"
        elif not saved_session:
            state, label = "missing", "Aucune session réutilisable"
        elif row and row["code"] in {"directory_ready", "read_success"}:
            state, label = "confirmed", "Active au dernier contrôle"
        else:
            state, label = "unknown", "État à confirmer"
        return {"state": state, "label": label, "checked_at": checked_at}

    def use_directory(self, owner, *, enable=False):
        db = self.connect()
        try:
            with db:
                if enable:
                    db.execute("INSERT OR REPLACE INTO directory_activity VALUES (?, ?)", (owner, time.time()))
                else:
                    db.execute("UPDATE directory_activity SET seen = ? WHERE owner = ?", (time.time(), owner))
        finally:
            db.close()

    def request_directory(self, owner):
        db = self.connect()
        try:
            with db:
                db.execute("INSERT OR REPLACE INTO directory_activity VALUES (?, ?)", (owner, time.time()))
                db.execute("INSERT OR IGNORE INTO directory_requested VALUES (?)", (owner,))
        finally:
            db.close()

    def directory_enabled(self, owner):
        db = self.connect()
        try:
            return db.execute("SELECT 1 FROM directory_activity WHERE owner = ?", (owner,)).fetchone() is not None
        finally:
            db.close()

    def pause_directory(self, owner=None):
        db = self.connect()
        try:
            with db:
                if owner is None:
                    db.execute("DELETE FROM directory_requested")
                    db.execute("DELETE FROM directory_activity")
                    db.execute("DELETE FROM manual_sessions")
                else:
                    db.execute("DELETE FROM directory_requested WHERE owner = ?", (owner,))
                    db.execute("DELETE FROM directory_activity WHERE owner = ?", (owner,))
                    db.execute("DELETE FROM manual_sessions WHERE owner=?", (owner,))
        finally:
            db.close()

    def due_directories(self, *, operating=False):
        # Refresh active accounts in the background. A failed run pauses automatic sign-in.
        db = self.connect()
        try:
            return [row["owner"] for row in db.execute(
                "SELECT r.owner FROM directory_requested r UNION ALL SELECT a.owner FROM directory_activity a JOIN jobs j ON j.id = "
                "(SELECT id FROM jobs WHERE owner = a.owner AND mode = 'directory' ORDER BY created DESC LIMIT 1) "
                "WHERE j.finished < ? - CASE WHEN a.seen > ? THEN ? ELSE ? END "
                "AND json_extract(j.result, '$.code') = 'directory_ready'",
                (time.time(), time.time() - 3600, directory.REFRESH_INTERVAL, directory.REFRESH_INTERVAL if operating else directory.IDLE_REFRESH_INTERVAL))]
        finally:
            db.close()

    def live_connection(self, owner, saved_session):
        now = dt.datetime.now(PARIS)
        manual = self.manual_until(owner)
        open_now = bool(manual or working_hours(now) and self.directory_enabled(owner))
        with closing(self.connect()) as db:
            row = db.execute("""SELECT finished,created,json_extract(result,'$.code') code
                FROM jobs WHERE owner=? AND mode='directory' ORDER BY created DESC LIMIT 1""", (owner,)).fetchone()
            last = db.execute("""SELECT finished,json_extract(result,'$.code') code FROM jobs
                WHERE owner=? AND mode='directory' AND finished IS NOT NULL ORDER BY finished DESC LIMIT 1""", (owner,)).fetchone()
        stamp = last["finished"] if last else 0
        earliest = now.astimezone(PARIS).replace(hour=8, minute=0, second=0, microsecond=0).timestamp()
        if manual:
            earliest = min(earliest, manual - 3600) if working_hours(now) and self.directory_enabled(owner) else manual - 3600
        verified = bool(stamp >= earliest and open_now and saved_session and last and last["code"] == "directory_ready" and
                        0 <= now.timestamp() - stamp < POLL_SECONDS * 3)
        pending = bool(open_now and row and row["finished"] is None)
        checked = dt.datetime.fromtimestamp(stamp, PARIS).strftime("%d/%m à %H h %M") if stamp else ""
        return {"active": verified, "pending": pending, "checked": checked,
                "stamp": stamp, "manual": bool(manual),
                "until": dt.datetime.fromtimestamp(manual, PARIS).strftime("%H h %M") if manual else "",
                "paused": bool(open_now and last and last["code"] == "day_login_used"),
                "error": MESSAGES.get(last["code"], "") if open_now and last and last["code"] != "directory_ready" else ""}

    def manual_until(self, owner):
        with closing(self.connect()) as db:
            row = db.execute("SELECT until FROM manual_sessions WHERE owner=? AND until>?", (owner, time.time())).fetchone()
            return row["until"] if row else 0

    def activate_manual(self, owner):
        now = time.time()
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT until FROM manual_sessions WHERE owner=?", (owner,)).fetchone()
            if previous and previous["until"] > now:
                return False
            db.execute("INSERT OR REPLACE INTO manual_sessions VALUES (?,?,?)", (owner, now, now + 3600))
            db.execute("INSERT OR IGNORE INTO directory_requested VALUES (?)", (owner,))
            return True

    def day_owners(self, now):
        """A new workday restarts enabled accounts, including after a weekend or failed login."""
        start = now.astimezone(PARIS).replace(hour=8, minute=0, second=0, microsecond=0).timestamp()
        db = self.connect()
        try:
            rows = db.execute("""
                SELECT a.owner,j.created,j.finished,json_extract(j.result,'$.code') AS code,
                       EXISTS(SELECT 1 FROM directory_requested r WHERE r.owner=a.owner) AS requested
                FROM (SELECT owner,max(seen) AS seen FROM (SELECT owner,seen FROM directory_activity WHERE ?
                      UNION ALL SELECT owner,started AS seen FROM manual_sessions WHERE until>?) GROUP BY owner) a
                LEFT JOIN manual_sessions m ON m.owner=a.owner AND m.until>?
                LEFT JOIN jobs j ON j.id = (
                    SELECT id FROM jobs WHERE owner=a.owner AND mode='directory' AND created>=CASE WHEN m.started IS NOT NULL THEN m.started ELSE ? END
                    ORDER BY created DESC LIMIT 1)
                ORDER BY coalesce(j.created,0),a.seen DESC
            """, (int(working_hours(now)), now.timestamp(), now.timestamp(), start))
            due = []
            for row in rows:
                if row["created"] is None:
                    due.append(row["owner"])
                elif row["finished"] and row["requested"] and row["code"] in {"day_login_used", "directory_ready"}:
                    due.append(row["owner"])
                elif row["finished"] and row["code"] in ("directory_ready","directory_incomplete","directory_unavailable","timeout","browser_error","interrupted"):
                    delay = POLL_SECONDS if row["code"] == "directory_ready" else 900
                    if row["created"] + delay <= now.timestamp() and row["finished"] + 20 <= now.timestamp():
                        due.append(row["owner"])
            return due
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


def execute_job(store, job_id, spec, lock_fd, provider_fd=None, day_worker=None):
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
        if store.connector_key and spec["mode"] in AUTH_MODES:
            child_env["EDOF_CONNECTOR_KEY"] = store.connector_key
            child_env["EDOF_CONNECTOR_DIRECTORY"] = str(store.directory)
            for key in ("EDOF_GOOGLE_CLIENT_ID", "EDOF_GOOGLE_CLIENT_SECRET"):
                if key in os.environ:
                    child_env[key] = os.environ[key]
        if day_worker is not None:
            parsed = day_worker.read(spec, child_env, DIRECTORY_TIMEOUT)
        else:
            process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("edof_server_browser.py"))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, env=child_env, start_new_session=True, pass_fds=(lock_fd,) if provider_fd is None else (lock_fd, provider_fd))
            timeout = {"directory": DIRECTORY_TIMEOUT, "declare": DECLARATION_TIMEOUT, "reconcile": DECLARATION_TIMEOUT}
            output, _ = process.communicate(json.dumps(spec), timeout=timeout.get(spec["mode"], JOB_TIMEOUT))
            parsed = json.loads(output) if process.returncode == 0 and len(output) < 32768 else {}
        if isinstance(parsed, dict) and parsed.get("code") in MESSAGES:
            # The runner emits only the explicitly normalized dossier schema.
            result = {key: parsed[key] for key in ("code", "stage", "fields", "confirmed_state", "fresh_session", "gmail_code_used", "session_saved", "candidate_count", "blocked_writes", "diagnostics") if key in parsed}
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
            if result.get("code") == "directory_ready" and store.data_file and spec.get("owner"):
                try:
                    from integrale_edof_sync import process_directory
                    snapshot = Vault(store.directory, store.connector_key).get(directory.record_key(spec["owner"]))
                    if snapshot:
                        snapshot = directory.dated_snapshot(snapshot)
                        process_directory(store, snapshot, store.data_file)
                        if not day_worker or (spec["provider"] == "integrale" and working_hours()):
                            declarations.discover(store, spec["owner"], snapshot)
                except (OSError, ValueError, sqlite3.Error):
                    # Keep the verified source snapshot. The next full sync
                    # can retry local analysis without replaying external work.
                    result.setdefault("diagnostics", {})["local_analysis_pending"] = True
            if spec["mode"] in {"declare", "reconcile"}:
                declarations.complete(store.directory, spec, result["code"], result.get("confirmed_state"))
                if result["code"] == "declaration_confirmed":
                    store.request_directory(spec["owner"])
            if day_worker is not None:
                result["day_session"] = True
            store.finish(job_id, result)
            if day_worker is not None:
                # Operational proof without account, dossier, cookie or code values.
                print(f"EDOF_DAY status={result['code']} fresh={result.get('fresh_session')} "
                      f"mail_used={result.get('gmail_code_used')}", flush=True)
        finally:
            os.close(lock_fd)
            if provider_fd is not None:
                os.close(provider_fd)


def last_read_stalled_at_login(jobs):
    # A failed lookup after a successful fresh login has not saved a new
    # browser, so it must not hide the preceding failed cookie restore.
    last = next((job for job in jobs if not (
        job.get("code") in {"timeout", "search_unconfirmed"} and job.get("stage") in {"search", "dossier"}
        and job.get("fresh_session") is True and job.get("gmail_code_used") is True and not job.get("session_saved")
    )), {})
    return (last.get("finished") is True and last.get("mode") == "read"
            and last.get("stage") == "login_page" and last.get("code") == "authentication_unconfirmed"
            and last.get("gmail_code_used") is False
            and stalled_before_login(last.get("diagnostics") or {}))


def start_job(store, owner, spec, *, day_worker=None):
    store.directory.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(store.directory / "edof_server_test.lock", os.O_CREAT | os.O_RDWR, 0o600)
    provider_fd = None
    try:
        # A form inspection is a read-only job; it cannot construct a business-write gate.
        if day_worker is not None:
            now = dt.datetime.now(PARIS)
            until = store.manual_until(owner)
            if spec["mode"] != "directory" or not (until or working_hours(now) and store.directory_enabled(owner)):
                raise ValueError("Veille indisponible.")
            spec = {**spec, "manual_until": until}
            provider_fd = acquire_provider(spec["provider"])
        elif spec["mode"] != "inspect_forms":
            ticket = (spec.get("intent") or {}).get("pilot_ticket")
            if ticket and spec["mode"] in {"declare", "reconcile"}:
                from cpf_provider import ProviderStore
                active = ProviderStore(store.directory).state()["provider"] if spec["mode"] == "reconcile" else "wedof"
                provider_fd = acquire_provider(active)
            else:
                provider_fd = acquire_provider("integrale")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Un navigateur d’essai fonctionne déjà sur ce serveur.") from None
        # A new, explicitly started read can use standard sign-in if the last
        # run never reached an EFP form or the private workspace.
        if spec["mode"] in {"read", "directory"} and last_read_stalled_at_login(store.latest(owner)):
            spec = {**spec, "fresh_login": True}
        if spec["mode"] in {"declare", "reconcile"}:
            from cpf_provider import ProviderStore
            if spec["mode"] == "declare" and ProviderStore(store.directory).state()["revision"] != spec["revision"]:
                raise ValueError("Le choix de système a changé.")
            if not declarations.check_before_job(store, spec):
                raise ValueError("Cette déclaration est à vérifier dans la fiche.")
        job_id = store.reserve(owner, spec["mode"], day_session=day_worker is not None)
        thread = threading.Thread(target=execute_job, args=(store, job_id, spec, lock_fd, provider_fd, day_worker), daemon=True)
        thread.start()
        return job_id
    except Exception:
        os.close(lock_fd)
        if provider_fd is not None:
            os.close(provider_fd)
        raise


def register_edof_server_test(legacy):
    if os.environ.get("RENDER_SERVICE_ID") != TEST_SERVICE_ID:
        return
    store = ServerTestStore("/var/data")
    store.data_file = legacy.DATA_FILE
    register_routes(legacy.app, store, legacy=legacy,
        admin_required=legacy.admin_login_required,
        can_access=lambda: legacy._is_super_admin_session() and not session.get("assist_partner_id"))

    def refresh_active_directories():
        worker = DayWorker()
        # Gunicorn can have several schedulers. Only one owns the in-memory tab.
        store.directory.mkdir(parents=True, exist_ok=True)
        with open(store.directory / "edof_day_leader.lock", "a") as leader:
            try:
                fcntl.flock(leader, fcntl.LOCK_EX)
                while True:
                    time.sleep(20)
                    try:
                        now = dt.datetime.now(PARIS)
                        if worker.owner and not (store.manual_until(worker.owner) or working_hours(now) and store.directory_enabled(worker.owner)):
                            worker.close()
                        from cpf_provider import ProviderStore
                        active = ProviderStore(store.directory).state()
                        if active["pending"]:
                            continue
                        pending = declarations.next_job(store, active["revision"], provider=active["provider"])
                        if pending:
                            start_job(store, pending["owner"], pending)
                            continue
                        for user in store.day_owners(now):
                            if not store.connector_key or not Vault(store.directory, store.connector_key).get("gmail"):
                                worker.close()
                                break
                            start_job(store, user, {"mode": "directory", "owner": user, "provider": active["provider"]}, day_worker=worker)
                            break
                    except (OSError, sqlite3.Error, ValueError):
                        continue
            finally:
                worker.close()

    threading.Thread(target=refresh_active_directories, name="edof-directory", daemon=True).start()


def register_routes(app, store, *, admin_required, can_access, legacy=None):
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
            result["saved_session"] = bool((vault().get("browser") or {}).get("cookies"))
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
        snapshot = vault().get(directory.record_key(user)) if store.connector_key else None
        if snapshot:
            store.use_directory(user)
        selected_folder = request.args.get("fiche")
        if selected_folder is not None and not re.fullmatch(r"[0-9a-f]{32}", selected_folder):
            abort(404)
        selected_id = request.args.get("result")
        if selected_id is not None and not re.fullmatch(r"[0-9a-f]{32}", selected_id):
            abort(404)
        if selected_folder is not None:
            fields = next((row for key, row in snapshot["rows"].items()
                           if hmac.compare_digest(directory.link_key(user, key), selected_folder)), None) if snapshot else None
            last_read = {"id": selected_folder, "fields": fields, "checked_at": directory.stamp(snapshot), "listed": True} if fields else None
        else:
            last_read = store.successful_read(user, job_id=selected_id)
        gmail = gmail_status()
        return app.jinja_env.get_template("edof_server_test.html").render(
            csrf=csrf, config=configuration(), gmail=gmail,
            efp=store.connection_status(user, gmail["saved_session"]), gmail_notice={
                "connected": "Gmail est connecté. Vous pouvez lancer un essai serveur.",
                "disconnected": "La connexion Gmail et la session EFP enregistrées sur Render ont été effacées. Vous pouvez aussi retirer l’autorisation dans votre compte Google.",
                "canceled": "La connexion Google n’a pas été autorisée.",
                "invalid": "Cette demande de connexion a expiré. Recommencez depuis cette page.",
                "busy": "Un essai serveur est en cours. Attendez sa fin avant de modifier la connexion.",
                **MESSAGES}.get(request.args.get("gmail"), ""),
            jobs=store.latest(user), last_read=last_read, selected_result=selected_folder is not None or selected_id is not None,
            directory_checked=directory.stamp(snapshot) if snapshot else None,
            directory_count=len(snapshot["rows"]) if snapshot else 0, directory_enabled=store.directory_enabled(user),
            directory_examples=[{"fields":row, "key":directory.link_key(user, row["folder_id"])}
                                for row in itertools.islice(snapshot["rows"].values(), 3)] if snapshot else [],
            state_labels=STATE_LABELS)

    @bp.get("/admin/edof-test/server/status")
    @admin_required
    def status():
        user = results_owner()
        return jsonify(ok=True, config=configuration(), gmail=gmail_status(), jobs=store.latest(user))

    @bp.get("/admin/edof-test/server/connection-status")
    @admin_required
    def connection_status():
        user = results_owner()
        return jsonify(store.connection_status(user, gmail_status()["saved_session"]))

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
        def disconnect():
            vault().clear()
            store.pause_directory()

        response = edit_connection(disconnect)
        if response.location.endswith("gmail=connected"):
            response.location = "/admin/edof-test/server?gmail=disconnected"
        return response

    @bp.get("/admin/edof-test/server/script.js")
    @admin_required
    def script():
        owner()
        return send_file(Path(__file__).parent / "edof_test_assets" / "server.js")

    @bp.post("/admin/edof-test/server/directory/refresh")
    @admin_required
    def refresh_directory():
        user = results_owner()
        check_csrf()
        if not configuration()["credentials_configured"] or not gmail_status()["connected"]:
            return jsonify(ok=False, error="Connectez le compte EFP et Gmail pour synchroniser la liste."), 409
        try:
            active = next((job for job in store.latest(user) if job["mode"] == "directory" and not job["finished"]), None)
            job = active["id"] if active else start_job(store, user, {"mode": "directory", "owner": user})
            store.use_directory(user, enable=True)
            return jsonify(ok=True, job_id=job), 202
        except JobCooldown as exc:
            return jsonify(ok=False, error=str(exc), retry_after=exc.remaining), 429
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 409

    @bp.post("/admin/edof-test/server/directory/schedule")
    @admin_required
    def schedule_directory():
        user = results_owner()
        check_csrf()
        if not configuration()["credentials_configured"] or not gmail_status()["connected"]:
            return jsonify(ok=False, error="Connectez le compte EFP et Gmail pour activer la veille."), 409
        store.use_directory(user, enable=True)
        return redirect(url_for("integrale_edof.index", section="technical"), code=303)

    @bp.post("/admin/edof-test/server/directory/manual")
    @admin_required
    def activate_manual():
        user = results_owner()
        check_csrf()
        if session.get("admin_role") == "viewer":
            abort(403)
        target = url_for("integrale_edof.index", section="state", tab="request")
        if not configuration()["credentials_configured"] or not gmail_status()["connected"]:
            flash("Connectez EFP et Gmail dans les paramètres pour activer la connexion.", "error")
            return redirect(target, code=303)
        def activate():
            if store.activate_manual(user):
                vault().put("day-login-override:" + user, dt.datetime.now(PARIS).date().isoformat(), ttl=600)
        response = edit_connection(activate)
        if response.location.endswith("gmail=busy"):
            flash("Une lecture EDOF est déjà en cours. Réessayez après sa fin.", "warning")
        return redirect(target, code=303)

    @bp.post("/admin/edof-test/server/directory/resume")
    @admin_required
    def resume_day():
        user = results_owner()
        check_csrf()
        if not store.manual_until(user) and (not working_hours() or not store.directory_enabled(user)):
            return jsonify(ok=False, error="La veille doit être ouverte."), 409
        def permit():
            if store.connection_status(user, True)["state"] != "day_paused":
                raise ValueError("La veille ne demande pas de nouveau code.")
            vault().put("day-login-override:" + user, dt.datetime.now(PARIS).date().isoformat(), ttl=600)
            with closing(store.connect()) as db, db:
                db.execute("INSERT OR IGNORE INTO directory_requested VALUES (?)", (user,))
        try:
            response = edit_connection(permit)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 409
        if response.location.endswith("gmail=busy"):
            return jsonify(ok=False, error="Une lecture est en cours. Réessayez après sa fin."), 409
        return redirect(url_for("integrale_edof.index", section="technical"), code=303)

    @bp.post("/admin/edof-test/server/directory/pause")
    @admin_required
    def pause_directory():
        user = results_owner()
        check_csrf()
        store.pause_directory(user)
        return redirect(url_for("edof_server_test.index", _anchor="directory-status"), code=303)

    @bp.post("/admin/edof-test/server/directory/lookup")
    @admin_required
    def lookup():
        user = results_owner()
        check_csrf()
        if not request.content_length or request.content_length > 2048:
            return jsonify(ok=False, error="Critères de recherche invalides."), 400
        try:
            spec = validate_spec(request.get_json(silent=True))
            if spec["mode"] != "read":
                raise ValueError("Renseignez un numéro CPF ou le nom et le prénom.")
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        snapshot = vault().get(directory.record_key(user)) if store.connector_key else None
        hits = []
        if snapshot:
            store.use_directory(user)
            for row in directory.matches(snapshot, spec):
                if len(hits) >= 20:
                    return jsonify(ok=True, message="Plus de vingt dossiers correspondent. Précisez le numéro CPF.")
                hits.append({"fields": row, "url": url_for("edof_server_test.index",
                            fiche=directory.link_key(user, row["folder_id"]), _anchor="dossier-lu")})
        saved = store.successful_read(user, spec=spec)
        if saved and all(hit["fields"]["folder_id"] != saved["fields"]["folder_id"] for hit in hits):
            hits.append({"fields": {k: saved["fields"].get(k) for k in ("folder_id", "first_name", "last_name", "title", "state")},
                         "url": url_for("edof_server_test.index", result=saved["id"], _anchor="dossier-lu")})
        if hits:
            return jsonify(ok=True, matches=hits)
        if snapshot:
            return jsonify(ok=True, message=f"Aucun dossier correspondant dans la liste EDOF du {directory.stamp(snapshot)}. "
                           "Utilisez « Relire sur EDOF » pour vérifier en direct.")
        return jsonify(ok=True, needs_sync=True, message="La première synchronisation de la liste EDOF reste à terminer. "
                       "Cliquez sur « Synchroniser la liste EDOF » pour la préparer.")

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
    if legacy is not None:
        from integrale_edof_dashboard import register_dashboard
        register_dashboard(app, legacy, store, results_owner=results_owner, vault=vault,
                           gmail_status=gmail_status, admin_required=admin_required, check_csrf=check_csrf)
