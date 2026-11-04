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

from cpf_provider import ProviderStore, acquire_provider, provider_operation
from edof_readonly_test import TEST_SERVICE_ID, ID_RE, STATE_LABELS
from edof_day_session import DayWorker, OPEN_HOUR, POLL_SECONDS, PARIS, working_hours, awaiting_edof_return, login_policy
import edof_recovery as recovery
import edof_directory as directory
import edof_session_clock as session_clock
import edof_proposal_jobs as proposals
import edof_declarations as declarations
import edof_automation_audit as automation_audit
from edof_gmail import Vault, GmailError, connector_key, oauth_configured, authorization_url, finish_authorization

JOB_TIMEOUT = 210
DIRECTORY_TIMEOUT = 420
DECLARATION_TIMEOUT = 360
RETENTION = 86400
PROPOSAL_MODES = {"proposal_read", "proposal_send", "proposal_check"}
AUTH_MODES = PROPOSAL_MODES | {"read", "directory", "declare", "reconcile", "inspect_forms"}
MESSAGES = {
    **declarations.REASONS,
    "day_login_used": "Le quota de codes EFP autorisé est atteint. La reconnexion automatique est en pause. Un administrateur peut autoriser une tentative supplémentaire.",
    "day_login_wait": "Une authentification EFP a été tentée récemment. La reconnexion reprendra automatiquement après le délai de 15 minutes.",
    "portal_throttled": "EDOF ou EFP limite les requêtes. La veille respecte le délai du portail, avec une pause minimale d’une heure.",
    "day_closed": "La veille est ouverte tous les jours de 7 h à 19 h, heure de Paris.",
    "declaration_confirmed": "Le statut et les valeurs de la déclaration ont été relus sur EDOF.",
    "declaration_inspected": "Contrôle des commandes disponibles sur EDOF terminé en lecture seule.",
    "pending_unavailable": "EDOF n’a pas renvoyé la liste des nouveaux dossiers à traiter. La dernière lecture vérifiée est conservée.",
    "requests_ready": "Les dossiers À traiter ont été relus dans l’onglet officiel EDOF.",
    "declaration_exit_confirmed": "Sortie confirmée dans EDOF. Le service fait reste à transmettre.",
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


MESSAGES.update(proposals.MESSAGES)


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
        db.execute("""CREATE TABLE IF NOT EXISTS directory_sync_requests (owner TEXT NOT NULL,
                    scope TEXT NOT NULL CHECK(scope IN ('new','all')), requested REAL NOT NULL, job_id TEXT,
                    PRIMARY KEY(owner,scope))""")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='manual_directory'").fetchone():
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='manual_directory'").fetchone():
                db.execute("INSERT OR IGNORE INTO directory_sync_requests SELECT owner,'all',requested,job_id FROM manual_directory")
                db.execute("DROP TABLE manual_directory")
        db.execute("""CREATE TABLE IF NOT EXISTS automation_catchups (owner TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                   requested REAL NOT NULL, message TEXT NOT NULL DEFAULT '')""")
        automation_audit.install_jobs(db)
        recovery.install(db)
        db.execute("UPDATE jobs SET finished = ?, result = ? WHERE finished IS NULL "
                   "AND created < ? - CASE WHEN mode = 'directory' THEN ? WHEN mode IN ('declare','reconcile','proposal_read','proposal_send','proposal_check') THEN ? ELSE ? END",
                   (time.time(), json.dumps({"code": "interrupted"}), time.time() - 30, DIRECTORY_TIMEOUT, DECLARATION_TIMEOUT, JOB_TIMEOUT))
        db.execute("DELETE FROM jobs WHERE created < ?", (time.time() - RETENTION,))
        db.commit()
        return db

    def reserve(self, owner, mode, *, day_session=False, sync_scope=None, recovery_since=None, revision=None):
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
                reuse = mode in PROPOSAL_MODES and self.connector_key and db.execute(
                    """SELECT 1 FROM jobs WHERE owner=? AND finished>=? AND json_extract(result,'$.code')='proposal_loaded'
                       AND NOT EXISTS(SELECT 1 FROM jobs j2 WHERE j2.created>jobs.created AND j2.owner=jobs.owner
                       AND json_extract(j2.result,'$.code') NOT IN ('proposal_loaded','directory_ready','requests_ready','read_success'))
                       LIMIT 1""", (owner, time.time()-300)).fetchone() and Vault(self.directory,self.connector_key).get("browser")
                if remaining > 0 and not (day_session or reuse):
                    raise JobCooldown(remaining)
                if mode == "directory":
                    db.execute("DELETE FROM directory_requested WHERE owner=?", (owner,))
                job_id = secrets.token_hex(16)
                db.execute("INSERT INTO jobs (id, owner, created, mode, result) VALUES (?, ?, ?, ?, ?)",
                           (job_id, owner, time.time(), mode, json.dumps({"code": "running", "day_session": day_session})))
                if recovery_since is not None:
                    recovery.claim(db, owner, job_id, recovery_since, revision)
                if sync_scope:
                    claimed = db.execute("""UPDATE directory_sync_requests SET job_id=? WHERE owner=? AND scope=? AND requested>=?
                        AND (job_id IS NULL OR job_id IN (SELECT id FROM jobs WHERE json_extract(result,'$.code')='interrupted'))""",
                        (job_id, owner, sync_scope, time.time()-3600)).rowcount
                    if not claimed:
                        raise ValueError("Synchronisation déjà prise en charge.")
            return job_id
        finally:
            db.close()

    def finish(self, job_id, result):
        db = self.connect()
        try:
            with db:
                job = db.execute("SELECT id,owner,mode FROM jobs WHERE id=?", (job_id,)).fetchone()
                db.execute("UPDATE jobs SET result = ?, finished = ? WHERE id = ?",
                           (json.dumps(result, ensure_ascii=False), time.time(), job_id))
                recovery.finished(db, job, result)
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
                "json_extract(result, '$.diagnostics.edof_screen') AS screen, json_extract(result,'$.session_saved') AS session_saved "
                "FROM jobs WHERE owner = ? AND (mode IN ('read', 'directory') OR json_extract(result,'$.session_saved')=1) AND finished IS NOT NULL "
                "ORDER BY finished DESC, id DESC LIMIT 1", (owner,),
            ).fetchone()
        finally:
            db.close()

        checked_at = None
        if row:
            checked_at = dt.datetime.fromtimestamp(row["finished"], ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H h %M")
        if row and row["screen"] == "session_expired":
            state, label = "expired", "Session expirée au dernier contrôle"
        elif row and row["code"] in {"day_login_used","day_login_wait"}:
            budget = login_policy(Vault(self.directory,self.connector_key), owner=owner, manual_until=self.manual_until(owner)) if self.connector_key else None
            if budget and budget["allowed"]:
                state, label = "reconnect", "Reconnexion automatique programmée"
            elif budget and budget["code"] == "day_login_wait":
                state, label = "day_wait", "Reconnexion automatique après le délai de 15 minutes"
            elif budget and budget["code"] in {"portal_throttled","day_closed"}:
                state, label = "day_wait", MESSAGES[budget["code"]]
            else:
                state, label = "day_paused", "Veille en pause · quota de codes EFP atteint"
        elif row and row["code"] in {"credentials_rejected", "account_unavailable", "verification_code",
                                    "otp_rejected", "account_action_required", "sign_in_error"}:
            state, label = "reconnect", "Reconnexion nécessaire"
        elif not saved_session:
            state, label = "missing", "Aucune session réutilisable"
        elif row and (row["code"] in {"directory_ready", "requests_ready", "read_success"} or row["session_saved"]):
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

    def recover_directory_reads(self):
        """Only the scheduler leader can reclaim reads whose browser lock is free."""
        with open(self.directory / "edof_server_test.lock", "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            with closing(self.connect()) as db, db:
                for item in db.execute("SELECT owner FROM directory_activity UNION SELECT owner FROM manual_sessions WHERE until>?", (time.time(),)).fetchall():
                    recovery.mark(db, item["owner"], "server_restart")
                if self.connector_key:
                    vault = Vault(self.directory, self.connector_key)
                    owners = db.execute("SELECT owner FROM directory_activity UNION SELECT owner FROM manual_sessions UNION SELECT DISTINCT owner FROM jobs")
                    for item in owners:
                        session_clock.record(vault, item["owner"], "interrupted")
                db.execute("""UPDATE jobs SET finished=?, result=?
                    WHERE mode='directory' AND finished IS NULL""",
                    (time.time(), json.dumps({"code":"interrupted", "restart":True, "day_session":True})))

    def queue_sync(self, owner, scope, *, catchup_revision=None):
        now = time.time()
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if catchup_revision is not None and db.execute("""SELECT 1 FROM automation_catchups WHERE owner=?
                    AND revision=? AND message='' AND requested>=?""", (owner,catchup_revision,now-3600)).fetchone():
                return
            db.execute("""INSERT INTO directory_sync_requests (owner,scope,requested,job_id) VALUES (?,?,?,NULL)
                ON CONFLICT(owner,scope) DO UPDATE SET requested=excluded.requested, job_id=NULL
                WHERE directory_sync_requests.requested < ? OR job_id IN
                      (SELECT id FROM jobs WHERE finished IS NOT NULL)""", (owner,scope,now,now-3600))
            if catchup_revision is not None:
                db.execute("INSERT OR REPLACE INTO automation_catchups VALUES (?,?,?,'')", (owner,catchup_revision,now))

    def catchup_status(self, owner, *, include_outcomes=False):
        with closing(self.connect()) as db:
            row = db.execute("SELECT requested,revision,message FROM automation_catchups WHERE owner=?", (owner,)).fetchone()
        if not row:
            return None
        message = row["message"]
        outcomes = {}
        valid_report = False
        # Older runs stored just the summary. New reports also retain each decision.
        if message.startswith("{"):
            result = json.loads(message)
            message, outcomes = result["summary"], result["outcomes"]
            valid_report = True
        active_run = row["requested"] >= time.time() - 3600
        if not message and not active_run:
            message = "Le délai de rattrapage a expiré. Relancez-le pour actualiser la liste."
        phase = "done" if message else "scan"
        targets = {f:action for f,(action,status) in outcomes.items() if status in {"queued","sending"}}
        waiting = review = 0
        if targets:
            with closing(declarations.database(self.directory)) as db:
                states = db.execute("""SELECT d.status, COUNT(*) FROM cpf_declarations d
                    JOIN json_each(?) t ON d.folder=t.key AND d.action=t.value
                    WHERE d.revision=? GROUP BY d.status""", (json.dumps(targets),row["revision"])).fetchall()
            counts = dict(states)
            waiting = counts.get("queued",0) + counts.get("sending",0)
            verified = counts.get("confirmed",0)
            review = sum(counts.get(k,0) for k in ("uncertain","review","paused"))
            message += f" Suivi des envois de ce passage · en attente : {waiting}, confirmés par EDOF : {verified}, à vérifier : {review}."
            if waiting and active_run:
                selected = ProviderStore(self.directory).state()
                if selected["provider"] == "integrale" and not selected["pending"] and selected["revision"] == row["revision"]:
                    phase = "send"
        state = {"busy":phase != "done", "phase":phase, "requested":row["requested"],
                 "message":message or "Lecture des dossiers dans EDOF, puis préparation des déclarations arrivées à échéance."}
        if phase == "done":
            unresolved = waiting or review or any(status not in {"queued","sending","confirmed"} for _,status in outcomes.values())
            state["result"] = "error" if not valid_report else "warning" if unresolved else "success"
        if include_outcomes:
            state["outcomes"] = outcomes
        return state

    def process_catchups(self, selection):
        from integrale_edof_dashboard import apply_confirmed_entries
        with closing(self.connect()) as db:
            runs = db.execute("""SELECT c.*,m.requested AS sync_start,j.created,j.finished,json_extract(j.result,'$.code') code
                FROM automation_catchups c LEFT JOIN directory_sync_requests m ON m.owner=c.owner AND m.scope='all'
                LEFT JOIN jobs j ON j.id=m.job_id WHERE c.message=''""").fetchall()
        for run in runs:
            if selection["provider"] != "integrale" or selection["pending"] or run["revision"] != selection["revision"]:
                message = "Rattrapage arrêté. Le système de traitement CPF a changé."
            elif not run["sync_start"] or run["requested"] < time.time()-3600:
                message = "Rattrapage interrompu. Relancez-le pour actualiser la liste."
            elif not run["finished"] or run["code"] == "interrupted":
                continue
            elif run["code"] != "directory_ready":
                message = "La liste générale EDOF n’a pas été actualisée. Relancez le rattrapage après la reprise de la connexion."
            else:
                try:
                    with provider_operation("integrale"):
                        snap = Vault(self.directory,self.connector_key).get(directory.record_key(run["owner"]))
                        if not snap or (snap.get("checked") or 0) < max(run["created"],run["requested"]) or snap.get("scope") != "all":
                            raise ValueError("La liste complète est indisponible.")
                        if ProviderStore(self.directory).state()["revision"] != run["revision"]:
                            raise ValueError("Le choix du système CPF a changé.")
                        outcomes = {}
                        report = declarations.discover(self, run["owner"], apply_confirmed_entries(snap,self.directory,run["owner"]), outcomes=outcomes)
                        if report is None:
                            raise ValueError("Intégrale EDOF doit être actif.")
                    when = dt.datetime.now(PARIS).strftime("%d/%m à %H h %M")
                    message = (f"Liste vérifiée le {when}. En file de transmission : entrées en formation · {report['entry_training']}, "
                               f"sorties avec service fait · {report['service_done']}. Déjà traitées ou en cours : {report['existing']}. "
                               f"Bloquées : {report['blocked']}. Date effective ou réalisation à préciser : {report['missing']}. "
                               f"À vérifier : {report['review']}.")
                    if not any(report.values()):
                        message = f"Liste vérifiée le {when}. Aucune automatisation en retard."
                    message = json.dumps({"summary":message, "outcomes":outcomes}, ensure_ascii=False)
                except (OSError, ValueError) as exc:
                    message = ("Analyse interrompue. " + str(exc) if isinstance(exc, ValueError) else
                               "Analyse interrompue. Les données sont momentanément indisponibles.")
            with closing(self.connect()) as db, db:
                db.execute("""UPDATE automation_catchups SET message=? WHERE owner=? AND requested=? AND message=''""",
                           (message,run["owner"],run["requested"]))

    def next_manual_sync(self):
        with closing(self.connect()) as db:
            return db.execute("""SELECT m.owner,m.scope,m.requested,(c.owner IS NOT NULL) AS catchup
                FROM directory_sync_requests m LEFT JOIN jobs j ON j.id=m.job_id
                LEFT JOIN automation_catchups c ON c.owner=m.owner AND m.scope='all' AND c.message=''
                WHERE m.requested>=? AND (m.job_id IS NULL OR json_extract(j.result,'$.code')='interrupted')
                ORDER BY catchup DESC,m.requested LIMIT 1""", (time.time()-3600,)).fetchone()

    def manual_sync_status(self, owner, scope):
        with closing(self.connect()) as db:
            item = db.execute("""SELECT m.requested,j.finished,json_extract(j.result,'$.code') code
                FROM directory_sync_requests m LEFT JOIN jobs j ON j.id=m.job_id WHERE m.owner=? AND m.scope=? AND m.requested>=?""",
                (owner,scope,time.time()-RETENTION)).fetchone()
        if not item:
            return None
        timing = {"requested": item["requested"], "finished": item["finished"]}
        if not item["finished"] or item["code"] == "interrupted":
            if item["requested"] < time.time()-3600:
                return {**timing, "busy":False, "message":"La demande de synchronisation a expiré. Relancez-la."}
            return {**timing, "busy":True, "message":"Synchronisation en cours en arrière-plan. Vous pouvez quitter la page."}
        when = dt.datetime.fromtimestamp(item["finished"], PARIS).strftime("%H h %M")
        if scope == "new" and item["code"] == "requests_ready":
            message = "Nouveaux dossiers à traiter synchronisés à " + when + "."
        elif item["code"] == "directory_ready":
            message = "Liste des dossiers synchronisée à " + when + "."
        elif item["code"] == "requests_ready":
            message = "Demandes à traiter actualisées à " + when + ". La liste générale n’a pas pu être actualisée."
        else:
            message = "Synchronisation non terminée à " + when + ". " + MESSAGES.get(item["code"], "")
        return {**timing, "busy":False, "code":item["code"],
                "updated":item["code"] in {"requests_ready","directory_ready"},
                "complete":item["code"] == ("directory_ready" if scope == "all" else "requests_ready"), "message":message}

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
                    db.execute("DELETE FROM directory_sync_requests")
                else:
                    db.execute("DELETE FROM directory_requested WHERE owner = ?", (owner,))
                    db.execute("DELETE FROM directory_activity WHERE owner = ?", (owner,))
                    db.execute("DELETE FROM manual_sessions WHERE owner=?", (owner,))
                    db.execute("DELETE FROM directory_sync_requests WHERE owner=?", (owner,))
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

    def live_connection(self, owner, saved_session, *, snapshot=None):
        now = dt.datetime.now(PARIS)
        manual = self.manual_until(owner)
        watch_enabled = self.directory_enabled(owner)
        watch_open = working_hours(now, daily=True)
        open_now = bool(manual or watch_open and watch_enabled)
        timing = session_clock.read_clock(Vault(self.directory,self.connector_key), owner) if self.connector_key else {}
        budget = login_policy(Vault(self.directory,self.connector_key), owner=owner, now=now, manual_until=manual) if self.connector_key else None
        with closing(self.connect()) as db:
            if not timing:
                timing = session_clock.legacy_observation(db, owner)
            queued = bool(db.execute("SELECT 1 FROM directory_requested WHERE owner=?", (owner,)).fetchone())
            row = db.execute("""SELECT finished,created,json_extract(result,'$.code') code
                FROM jobs WHERE owner=? AND mode='directory' ORDER BY created DESC LIMIT 1""", (owner,)).fetchone()
            last = db.execute("""SELECT finished,json_extract(result,'$.code') code FROM jobs
                WHERE owner=? AND mode='directory' AND finished IS NOT NULL ORDER BY finished DESC LIMIT 1""", (owner,)).fetchone()
            last_private = db.execute("""SELECT MAX(finished) FROM jobs WHERE owner=? AND json_extract(result,'$.session_saved')=1""",
                                      (owner,)).fetchone()[0] or 0
            successes = dict(db.execute("""SELECT json_extract(result,'$.code') code, MAX(finished)
                FROM jobs WHERE owner=? AND mode='directory' AND finished IS NOT NULL
                AND json_extract(result,'$.code') IN ('directory_ready','requests_ready') GROUP BY code""", (owner,)))
        snapshot = snapshot or {}
        full = max(snapshot.get("checked") or 0, successes.get("directory_ready", 0))
        pending_sync = max(snapshot.get("pending_checked") or 0, successes.get("requests_ready", 0))
        synced = max(full, pending_sync)
        sync = {"stamp":synced, "label":directory.stamp({"checked":synced}) if synced else "",
                "scope":"Demandes à traiter" if pending_sync > full else "Liste générale",
                "full_stamp":full, "full_label":directory.stamp({"checked":full}) if full else ""}
        stamp = last["finished"] if last else 0
        earliest = now.astimezone(PARIS).replace(hour=OPEN_HOUR, minute=0, second=0, microsecond=0).timestamp()
        if manual:
            earliest = min(earliest, manual - 3600) if watch_open and watch_enabled else manual - 3600
        verified = bool(stamp >= earliest and open_now and saved_session and last and last["code"] in {"directory_ready","requests_ready"} and
                        0 <= now.timestamp() - stamp < POLL_SECONDS * 3)
        phase = {}
        if open_now and self.connector_key:
            phase = Vault(self.directory,self.connector_key).get("edof-phase:"+owner) or {}
        private_at = phase.get("at", 0)
        if (open_now and private_at >= earliest and now.timestamp()-private_at < POLL_SECONDS*3
                and phase.get("private_status") == 200 and (private_at >= stamp or last and last["code"] in {"requests_ready","directory_ready"})):
            verified = True
        pending = bool(open_now and (queued or row and row["finished"] is None))
        if open_now and last_private >= earliest and last_private >= stamp and 0 <= now.timestamp()-last_private < POLL_SECONDS*3:
            verified = True
        latest_check = max(stamp,last_private)
        checked = dt.datetime.fromtimestamp(latest_check, PARIS).strftime("%d/%m à %H h %M") if latest_check else ""
        if private_at >= earliest and private_at > latest_check and phase.get("private_status") == 200:
            checked = dt.datetime.fromtimestamp(private_at, PARIS).strftime("%d/%m à %H h %M")
        labels = {"opening_workspace":"Ouverture du portail EDOF", "efp_form":"Connexion à EFP",
                  "otp_submitted":"Retour d’EFP vers EDOF", "selecting_organisation":"Ouverture de l’établissement",
                  "reading_directory":"Lecture de la liste", "reading_pending_tab":"Lecture des dossiers À traiter",
                  "reading_all_folders":"Synchronisation de tous les dossiers", "pending_verified":"Demandes vérifiées"}
        blocked = open_now and not verified and stamp >= earliest and last and last["code"] in {"day_login_used","day_login_wait"} and (not budget or budget["code"] == "day_login_used")
        error = MESSAGES.get(last["code"], "") if open_now and not verified and stamp >= earliest and last and last["code"] not in {"directory_ready","requests_ready"} else ""
        if error and last["code"] in {"day_login_used","day_login_wait"} and budget:
            error = MESSAGES.get(budget["code"], "Reconnexion automatique programmée dans la limite des quatre codes quotidiens.")
        schedule = ("Veille programmée de 7 h à 19 h (Paris)" if watch_open else "Hors plage de veille (7 h à 19 h, Paris)") if watch_enabled else "Veille automatique suspendue"
        clock = session_clock.clock_view(timing, now.timestamp(), open_now=open_now, verified=verified)
        return {"clock":clock, "active": verified, "pending": pending, "checked": checked, "sync": sync, "schedule": schedule, "manual_sync": self.manual_sync_status(owner, "all"),
                "recovery": recovery.status(self, owner),
                "login_budget": {k:budget[k] for k in ("used","limit","remaining","retry_at")} if budget else None,
                "last_read": dict(row) if row else None,
                "new_sync": self.manual_sync_status(owner, "new"),
                "phase": labels.get(phase.get("phase"), "") if private_at >= earliest and pending else "",
                "stamp": stamp, "manual": bool(manual),
                "until": dt.datetime.fromtimestamp(manual, PARIS).strftime("%H h %M") if manual else "",
                "paused": bool(blocked), "error": error}

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
                last = db.execute("SELECT finished,json_extract(result,'$.code') AS code FROM jobs WHERE owner=? AND mode='directory' ORDER BY created DESC LIMIT 1", (owner,)).fetchone()
                if last and last["finished"] and last["finished"]+60 <= now and last["code"] in {"browser_error","timeout","directory_incomplete","directory_unavailable","authentication_unconfirmed"}:
                    db.execute("INSERT OR IGNORE INTO directory_requested VALUES (?)", (owner,))
                return False
            db.execute("INSERT OR REPLACE INTO manual_sessions VALUES (?,?,?)", (owner, now, now + 3600))
            db.execute("INSERT OR IGNORE INTO directory_requested VALUES (?)", (owner,))
            return True

    def day_owners(self, now, *, daily=True):
        """A new workday restarts enabled accounts, including after a weekend or failed login."""
        start = now.astimezone(PARIS).replace(hour=OPEN_HOUR, minute=0, second=0, microsecond=0).timestamp()
        db = self.connect()
        try:
            rows = db.execute("""
                SELECT a.owner,m.started AS manual_start,j.created,j.finished,j.result,json_extract(j.result,'$.code') AS code,
                       (EXISTS(SELECT 1 FROM directory_requested r WHERE r.owner=a.owner)
                        OR (json_extract(j.result,'$.code') IN ('day_login_used','day_login_wait') AND EXISTS
                            (SELECT 1 FROM jobs newer WHERE newer.owner=a.owner AND newer.finished>j.finished
                             AND json_extract(newer.result,'$.session_saved')=1))) AS requested
                FROM (SELECT owner,max(seen) AS seen FROM (SELECT owner,seen FROM directory_activity WHERE ?
                      UNION ALL SELECT owner,started AS seen FROM manual_sessions WHERE until>?) GROUP BY owner) a
                LEFT JOIN manual_sessions m ON m.owner=a.owner AND m.until>?
                LEFT JOIN jobs j ON j.id = (
                    SELECT id FROM jobs WHERE owner=a.owner AND mode='directory' AND created>=CASE WHEN m.started IS NOT NULL THEN m.started ELSE ? END
                    ORDER BY created DESC LIMIT 1)
                ORDER BY coalesce(j.created,0),a.seen DESC
            """, (int(working_hours(now, daily=daily)), now.timestamp(), now.timestamp(), start)).fetchall()
            due = []
            for row in rows:
                if row["created"] is None:
                    due.append(row["owner"])
                elif row["finished"] and row["requested"] and row["code"] in {"day_login_used", "directory_ready","requests_ready","browser_error","timeout","directory_unavailable","directory_incomplete","pending_unavailable","authentication_unconfirmed"}:
                    due.append(row["owner"])
                elif row["finished"] and row["code"] == "portal_throttled":
                    if self.connector_key and not Vault(self.directory,self.connector_key).get("edof-throttled"):
                        due.append(row["owner"])
                elif row["finished"] and row["code"] in {"day_login_used","day_login_wait"} and self.connector_key:
                    budget = login_policy(Vault(self.directory,self.connector_key), owner=row["owner"], now=now,
                                          manual_until=self.manual_until(row["owner"]))
                    if budget["allowed"] and row["finished"] + 20 <= now.timestamp():
                        due.append(row["owner"])
                elif row["finished"] and row["code"] in ("directory_ready","requests_ready","directory_incomplete","directory_unavailable","pending_unavailable","timeout","browser_error","interrupted","authentication_unconfirmed"):
                    result = json.loads(row["result"])
                    if row["code"] == "interrupted" and result.get("restart"):
                        due.append(row["owner"])
                        continue
                    delay = POLL_SECONDS if row["code"] in {"directory_ready","requests_ready","pending_unavailable"} or awaiting_edof_return(result) else 900
                    if (delay == 900 and row["manual_start"] and row["code"] == "browser_error"
                            and result.get("stage") == "login_page" and not result.get("gmail_code_used")
                            and not (result.get("diagnostics") or {}).get("login_post_status")):
                        attempts = db.execute("SELECT count(*) FROM jobs WHERE owner=? AND mode='directory' AND created>=?",
                                              (row["owner"], row["manual_start"])).fetchone()[0]
                        if attempts < 4:
                            delay = POLL_SECONDS
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
                found = {"id": row["id"], "checked_at": checked.strftime("%d/%m/%Y à %H h %M"), "fields": fields,
                         "import_error": json.loads(row["result"]).get("import_error")}
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
            timeout = DIRECTORY_TIMEOUT if spec["mode"] == "directory" else DECLARATION_TIMEOUT
            parsed = day_worker.read(spec, child_env, timeout, lock_fds=(lock_fd, provider_fd))
        else:
            process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("edof_server_browser.py"))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, env=child_env, start_new_session=True, pass_fds=(lock_fd,) if provider_fd is None else (lock_fd, provider_fd))
            timeout = {"directory": DIRECTORY_TIMEOUT, **dict.fromkeys({"declare","reconcile"} | PROPOSAL_MODES, DECLARATION_TIMEOUT)}
            output, _ = process.communicate(json.dumps(spec), timeout=timeout.get(spec["mode"], JOB_TIMEOUT))
            parsed = json.loads(output) if process.returncode == 0 and len(output) < 32768 else {}
        if isinstance(parsed, dict) and parsed.get("code") in MESSAGES:
            # The runner emits only the explicitly normalized dossier schema.
            result = {key: parsed[key] for key in ("code", "stage", "fields", "confirmed_state", "fresh_session", "gmail_code_used", "session_saved", "candidate_count", "blocked_writes", "diagnostics", "proposal_receipt", "proposal_message") if key in parsed}
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
            if spec.get("import_session") and result.get("code") == "read_success":
                from integrale_edof_registration import create_registration
                try:
                    with store.legacy.app.app_context():
                        create_registration(store.legacy, spec["folder_id"], spec["import_session"], result["fields"])
                except ValueError as exc:
                    result["import_error"] = str(exc)
                except (OSError, sqlite3.Error):
                    result["import_error"] = "Enregistrement local indisponible. Réessayez depuis le dossier."
            if result.get("code") == "directory_ready" and store.data_file and spec.get("owner"):
                try:
                    from integrale_edof_sync import process_directory
                    snapshot = Vault(store.directory, store.connector_key).get(directory.record_key(spec["owner"]))
                    if snapshot:
                        snapshot = directory.dated_snapshot(snapshot)
                        process_directory(store, snapshot, owner=spec["owner"])

                except (OSError, ValueError, sqlite3.Error):
                    # Keep the verified source snapshot. The next full sync
                    # can retry local analysis without replaying external work.
                    result.setdefault("diagnostics", {})["local_analysis_pending"] = True
            if spec["mode"] == "proposal_read":
                proposals.finish_read(store.directory,spec,MESSAGES.get(result["code"],"Vérifiez la connexion EDOF."))
            if spec["mode"] in {"proposal_send","proposal_check"}:
                proposals.complete(store.directory, spec, result, result.get("proposal_message") or MESSAGES.get(result["code"],"Vérifiez la connexion EDOF."))
                if result["code"] == "proposal_confirmed":
                    store.request_directory(spec["owner"])
            if spec["mode"] in {"declare", "reconcile"}:
                declarations.complete(store.directory, spec, result["code"], result.get("confirmed_state"))
                if result["code"] == "declaration_confirmed":
                    store.request_directory(spec["owner"])
            if day_worker is not None and spec["mode"] == "directory":
                result["day_session"] = True
            store.finish(job_id, result)
            if day_worker is not None and spec["mode"] == "directory":
                # Operational proof without account, dossier, cookie or code values.
                report = (result.get("diagnostics") or {}).get("directory") or {}
                print(f"EDOF_DAY status={result['code']} fresh={result.get('fresh_session')} "
                      f"mail_used={result.get('gmail_code_used')} stage={result.get('stage')} "
                      f"fault={(result.get('diagnostics') or {}).get('fault')} "
                      f"operation={(result.get('diagnostics') or {}).get('operation')} "
                      f"phase={(result.get('diagnostics') or {}).get('initial_phase')} "
                      f"full_http={report.get('http')} page={report.get('page')} total={report.get('total')} "
                      f"seen={report.get('seen')} reason={report.get('failure')}", flush=True)
        finally:
            os.close(lock_fd)
            if provider_fd is not None:
                os.close(provider_fd)


def start_job(store, owner, spec, *, day_worker=None):
    store.directory.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(store.directory / "edof_server_test.lock", os.O_CREAT | os.O_RDWR, 0o600)
    provider_fd = None
    try:
        # Only the scheduler can dispatch a state-changing job to the shared session.
        spec = {**spec, "owner":owner}
        if day_worker is not None:
            until = max(store.manual_until(owner), spec.get("sync_until", 0))
            if not (until or working_hours()):
                raise ValueError("Veille indisponible.")
            spec = {**spec, "manual_until":until}
        if day_worker is not None and spec["mode"] in {"directory","proposal_read","proposal_check"}:
            provider_fd = acquire_provider(spec["provider"])
        elif spec["mode"] == "read" and spec.get("import_session"):
            provider_fd = acquire_provider(ProviderStore(store.directory).state()["provider"])
        elif spec["mode"] not in {"inspect_forms","proposal_read","proposal_check"}:
            ticket = (spec.get("intent") or {}).get("pilot_ticket")
            if ticket and spec["mode"] in {"declare", "reconcile"}:
                active = ProviderStore(store.directory).state()["provider"] if spec["mode"] == "reconcile" else "wedof"
                provider_fd = acquire_provider(active)
            else:
                provider_fd = acquire_provider("integrale")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Un navigateur d’essai fonctionne déjà sur ce serveur.") from None
        if spec["mode"] in {"declare", "reconcile"}:
            if spec["mode"] == "declare" and ProviderStore(store.directory).state()["revision"] != spec["revision"]:
                raise ValueError("Le choix de système a changé.")
            if not declarations.check_before_job(store, spec):
                raise ValueError("Cette déclaration est à vérifier dans la fiche.")
        job_id = store.reserve(owner, spec["mode"], day_session=day_worker is not None and spec["mode"]=="directory", sync_scope=spec.get("sync_scope"),
                               recovery_since=spec.get("recovery_since"), revision=spec.get("revision"))
        if spec["mode"] == "proposal_read" and not proposals.reading(store.directory,spec):
            store.finish(job_id,{"code":"interrupted"})
            raise ValueError("Une autre lecture est déjà programmée.")
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
    store.legacy = legacy
    register_routes(legacy.app, store, legacy=legacy,
        admin_required=legacy.admin_login_required,
        can_access=lambda: legacy._is_super_admin_session() and not session.get("assist_partner_id"))

    def refresh_active_directories():
        worker = DayWorker()
        inspected = None
        # Gunicorn can have several schedulers. Only one owns the in-memory tab.
        store.directory.mkdir(parents=True, exist_ok=True)
        with open(store.directory / "edof_day_leader.lock", "a") as leader:
            try:
                fcntl.flock(leader, fcntl.LOCK_EX)
                store.recover_directory_reads()
                while True:
                    time.sleep(20)
                    try:
                        now = dt.datetime.now(PARIS)
                        active = ProviderStore(store.directory).state()
                        daily = active["provider"] == "integrale"
                        if worker.owner and not (store.manual_until(worker.owner) or working_hours(now, daily=True) and store.directory_enabled(worker.owner)):
                            worker.close()
                        store.process_catchups(active)
                        if active["pending"]:
                            continue
                        recovery.prepare(store, active, now)
                        manual_sync = store.next_manual_sync()
                        if not manual_sync:
                            restart = recovery.next_job(store, active, now)
                            if restart:
                                start_job(store, restart["owner"], restart, day_worker=worker)
                                continue
                            pending = proposals.next_job(store.directory,active) or declarations.next_job(store, active["revision"], provider=active["provider"])
                            # Re-evaluate deadlines even when no new export was needed this minute.
                            tick = (active["revision"], int(now.timestamp()) // 300)
                            if not pending and daily and working_hours(now) and inspected != tick and store.connector_key:
                                inspected = tick
                                with closing(store.connect()) as db:
                                    owners = [r[0] for r in db.execute("SELECT owner FROM directory_activity")]
                                vault = Vault(store.directory, store.connector_key)
                                for owner in owners:
                                    if recovery.pending(store, owner):
                                        continue
                                    snap = directory.dated_snapshot(vault.get(directory.record_key(owner), keep=True))
                                    if snap:
                                        from integrale_edof_dashboard import apply_confirmed_entries
                                        declarations.discover(store, owner, apply_confirmed_entries(snap, store.directory, owner))
                                pending = declarations.next_job(store, active["revision"])
                            if pending and pending["mode"] == "declare" and recovery.pending(store, pending["owner"]):
                                pending = None
                            if pending:
                                open_now = working_hours(now) or store.manual_until(pending["owner"])
                                if open_now or pending["mode"] in PROPOSAL_MODES:
                                    try:
                                        start_job(store,pending["owner"],{**pending,"provider":active["provider"]},
                                                  day_worker=worker if open_now else None)
                                        continue
                                    except JobCooldown:
                                        pass  # Keep the watch running between dossier jobs.
                        if manual_sync:
                            user = manual_sync["owner"]
                            start_job(store, user, {"mode":"directory", "owner":user, "provider":active["provider"],
                                      "sync_scope":manual_sync["scope"], "sync_until":manual_sync["requested"] + 3600}, day_worker=worker)
                            continue
                        for user in store.day_owners(now, daily=True):
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
        snapshot = directory.dated_snapshot(vault().get(directory.record_key(user))) if store.connector_key else None
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

    @bp.post("/admin/edof-test/synchroniser")
    @admin_required
    def sync_now():
        user = results_owner()
        check_csrf()
        if session.get("admin_role") == "viewer":
            abort(403)
        ready = configuration()["credentials_configured"] and gmail_status()["connected"] and store.connector_key
        scope = request.form.get("scope", "all")
        if scope not in {"new", "all"}:
            abort(400)
        if ready:
            store.queue_sync(user, scope)
            target = "des nouveaux dossiers à traiter" if scope == "new" else "de tous les dossiers"
            message = f"Synchronisation {target} demandée. Vous pouvez quitter la page."
        else:
            message = "Connectez EFP et Gmail dans les paramètres pour synchroniser les dossiers."
        if request.accept_mimetypes.best == "application/json":
            state = store.manual_sync_status(user, scope) if ready else None
            return jsonify(message=message, requested=(state or {}).get("requested")), 202 if ready else 409
        flash(message, "success" if ready else "error")
        return redirect(url_for("integrale_edof.index", section=request.form.get("section") or "requests",
                                tab=request.form.get("tab"), folder=request.form.get("folder") or None), code=303)

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
            if request.accept_mimetypes.best == "application/json":
                return jsonify(message="Connectez EFP et Gmail dans les paramètres pour activer la connexion."), 409
            flash("Connectez EFP et Gmail dans les paramètres pour activer la connexion.", "error")
            return redirect(target, code=303)
        def activate():
            store.activate_manual(user)
        requested = time.time()
        response = edit_connection(activate)
        if response.location.endswith("gmail=busy"):
            if request.accept_mimetypes.best == "application/json":
                return jsonify(message="Une lecture EDOF est déjà en cours. Attendez sa fin avant de relancer la connexion."), 409
            flash("Une lecture EDOF est déjà en cours. Réessayez après sa fin.", "warning")
        if request.accept_mimetypes.best == "application/json":
            live = store.live_connection(user, gmail_status()["saved_session"])
            return jsonify(requested=requested, active=live["active"],
                           message="Connexion EDOF déjà active." if live["active"] else "Connexion demandée. Le serveur vérifie l’accès à EDOF."), 202
        return redirect(target, code=303)

    @bp.post("/admin/edof-test/server/directory/resume")
    @admin_required
    def resume_day():
        user = results_owner()
        check_csrf()
        if session.get("admin_role") == "viewer":
            abort(403)
        if not store.manual_until(user) and (not working_hours(daily=True) or not store.directory_enabled(user)):
            return jsonify(ok=False, error="La veille doit être ouverte."), 409
        def permit():
            if store.connection_status(user, True)["state"] != "day_paused":
                raise ValueError("La veille ne demande pas de nouveau code.")
            vault().put("day-login-override:" + user, dt.datetime.now(PARIS).date().isoformat(), ttl=600)
            with closing(store.connect()) as db, db:
                db.execute("INSERT OR IGNORE INTO directory_requested VALUES (?)", (user,))
        requested = time.time()
        try:
            response = edit_connection(permit)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 409
        if response.location.endswith("gmail=busy"):
            return jsonify(ok=False, error="Une lecture est en cours. Réessayez après sa fin."), 409
        if request.accept_mimetypes.best == "application/json":
            return jsonify(requested=requested, message="Reconnexion demandée. Un nouveau code EFP est autorisé pour cette tentative."), 202
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
        snapshot = directory.dated_snapshot(vault().get(directory.record_key(user))) if store.connector_key else None
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
                       "Cliquez sur « Synchro manuelle tous les dossiers » pour la préparer.")

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
