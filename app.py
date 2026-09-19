import os
import json
import uuid
import re
import zlib
import hashlib
import hmac
import datetime
import calendar
import math
import html
import unicodedata
import threading
import shutil
import copy
import importlib.util
import time
import subprocess
import secrets
import random
import base64
import logging
import signal
import atexit
import sys
from backup_chronology import backup_chronology_key
from wedof_requests import (
    entry_kind as wedof_entry_kind,
    grouped_requests as group_wedof_requests,
    merge_folder as merge_wedof_folder,
    notification_kind as wedof_notification_kind,
    registration_id as wedof_registration_id,
    registration_payload as wedof_registration_payload,
    related_entries as related_wedof_entries,
)
from digiforma_duration import aps_elearning_completion, journal_attendance
from manual_document_reminders import document_actions, build_content as build_manual_docs_content, content_fingerprint
from automatic_document_reminders import run as run_automatic_document_reminders, schedule as automatic_document_schedule
from automatic_training_attestations import run as run_automatic_training_attestations
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
try:
    import resource
except ImportError:
    resource = None
from typing import Dict, Any, Optional, List, Iterable, Tuple, Set, Callable
from functools import lru_cache, wraps
from zoneinfo import ZoneInfo
from flask import session
import werkzeug.security as werkzeug_security
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from PIL import Image, ImageOps
import tempfile
import fcntl
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

try:
    from docxtpl import DocxTemplate
except ImportError:
    DocxTemplate = None

import requests
from flask import Flask, request, redirect, url_for, jsonify, render_template, abort, send_file, flash, has_request_context, make_response, g, Response

import zipfile
from io import BytesIO
from docx import Document
from pypdf import PdfReader, PdfWriter
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from urllib.parse import urlparse, urljoin, quote, urlencode
from cryptography.fernet import Fernet
import afc_import
from akto_bts import (
    AktoApiError,
    AktoBtsStore,
    AktoClient,
    AktoConfig,
    AktoConfigurationError,
    new_sync_run_id,
    sync_akto_bts,
)
from wedof_service import WedofApiError, WedofClient, WedofConfigurationError, read_env_bool
from wedof_governor import (
    WedofGovernorError,
    WedofQuotaExceeded,
    acquire_lease as acquire_wedof_governor_lease,
    quota_snapshot as wedof_quota_snapshot,
    release_lease as release_wedof_governor_lease,
    reserve_request as reserve_central_wedof_request,
    valid_governor_token,
)
from wedof_matching import (build_matching_preview, extract_folder, find_trainee_cpf_candidates,
                            normalize_date, normalize_email, normalize_name, normalize_phone)
from wedof_links import (ALLOWED_STATES, evaluate_wedof_link_date_consistency, local_association_status,
                         save_manual_wedof_link, sync_exact_wedof_links)
from wedof_automation import (automation_dashboard_state, build_automation_dashboard, is_wedof_maintenance_window,
                              next_automatic_attempt,
                              record_maintenance_skip, run_dry_run, run_live_automation,
                              sync_folder_automation_status)
from cpf_tracking import build_cpf_view, has_cpf_financing, has_generated_cpf_invoice
from vtc_cpf_guidance import build_confirmation_content
from partner_postgres import (
    PartnerPostgresDuplicateEmail,
    PartnerPostgresError,
    PartnerPostgresNotFound,
    PartnerPostgresStore,
    PartnerPostgresUnavailable,
    PartnerPostgresValidationError,
    PartnerPostgresWriteConflict,
    canonical_json as _partner_canonical_json,
)


_APP_IMPORT_STARTED_AT = time.monotonic()
_REQUEST_STARTED_AT_KEY = "_memory_request_started_at"
_BACKGROUND_TASKS_LOCK = threading.Lock()
_BACKGROUND_TASKS_LAST_RUN_AT = 0.0
_BACKGROUND_TASKS_MIN_INTERVAL_SECONDS = int(os.environ.get("BACKGROUND_TASKS_MIN_INTERVAL_SECONDS", "300"))
MEMORY_DIAGNOSTICS_ENABLED = (os.environ.get("MEMORY_DIAGNOSTICS_ENABLED", "0") or "").strip().lower() in {
    "1", "true", "yes", "on",
}

def _current_rss_mb() -> float:
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024
    except Exception:
        pass
    try:
        with open("/proc/self/statm", "r", encoding="utf-8") as f:
            pages = int((f.read().split() or ["0", "0"])[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except Exception:
        return -1.0

def _peak_rss_mb() -> float:
    if resource is not None:
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if sys.platform == "darwin":
                return usage / (1024 * 1024)
            return usage / 1024
        except Exception:
            pass
    return _current_rss_mb()

def _rss_mb() -> float:
    return _current_rss_mb()

def _current_route_for_log() -> str:
    if has_request_context():
        return request.path or ""
    return "-"

def _log_memory_stage(stage: str, started_at: Optional[float] = None, route: Optional[str] = None, baseline_mb: Optional[float] = None) -> float:
    if not MEMORY_DIAGNOSTICS_ENABLED:
        return baseline_mb if baseline_mb is not None else -1.0
    current_rss_mb = _current_rss_mb()
    peak_rss_mb = _peak_rss_mb()
    duration_ms = 0.0 if started_at is None else (time.monotonic() - started_at) * 1000
    delta_mb = 0.0 if baseline_mb is None else current_rss_mb - baseline_mb
    message = (
        f"MEMORY stage={stage} current_rss_mb={current_rss_mb:.1f} "
        f"peak_rss_mb={peak_rss_mb:.1f} delta_mb={delta_mb:.1f} "
        f"duration_ms={duration_ms:.1f}"
    )
    print(message, file=sys.stderr, flush=True)
    logging.getLogger(__name__).info(
        "%s pid=%s route=%s",
        message,
        os.getpid(),
        route if route is not None else _current_route_for_log(),
    )
    return current_rss_mb

_log_memory_stage("IMPORT_BEGIN", _APP_IMPORT_STARTED_AT, "-")
_log_memory_stage("AFTER_IMPORTS", _APP_IMPORT_STARTED_AT, "-")

def _install_shutdown_diagnostics() -> None:
    def _signal_handler(signum, frame):
        name = signal.Signals(signum).name if signum in signal.Signals.__members__.values() else str(signum)
        logging.getLogger(__name__).warning("WORKER_SIGNAL signal=%s pid=%s rss_mb=%.1f", name, os.getpid(), _rss_mb())
        raise SystemExit(128 + signum)

    def _normal_exit():
        logging.getLogger(__name__).info("WORKER_EXIT_NORMAL pid=%s rss_mb=%.1f", os.getpid(), _rss_mb())

    def _unhandled(exc_type, exc, tb):
        logging.getLogger(__name__).critical("WORKER_UNHANDLED_EXCEPTION pid=%s rss_mb=%.1f", os.getpid(), _rss_mb(), exc_info=(exc_type, exc, tb))
        if exc_type is SystemExit:
            return
        sys.__excepthook__(exc_type, exc, tb)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _signal_handler)
        except Exception:
            logging.getLogger(__name__).exception("WORKER_SIGNAL_HANDLER_INSTALL_FAILED signal=%s", sig)
    atexit.register(_normal_exit)
    sys.excepthook = _unhandled

_install_shutdown_diagnostics()


app = Flask(__name__)
DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES)))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
_log_memory_stage("AFTER_FLASK_CREATION", _APP_IMPORT_STARTED_AT, "-")


@app.before_request
def _log_request_begin_memory():
    if request.path == "/healthz":
        return None
    setattr(request, _REQUEST_STARTED_AT_KEY, time.monotonic())
    g.load_data_call_count = 0
    _log_memory_stage("REQUEST_BEGIN")
    return None


@app.get("/templates/cpf.jpg")
def cpf_logo_asset():
    return send_file(os.path.join(app.root_path, "templates", "cpf.jpg"), mimetype="image/jpeg")


@app.after_request
def add_no_store_headers(response):
    """Avoid serving stale admin/API data after autosaved changes."""
    if request.path.startswith(("/admin", "/api/")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/api/qonto/oauth/ping")
def api_qonto_oauth_ping():
    app.logger.warning("[QONTO OAUTH PING] ROUTE CALLED")
    return jsonify({"ok": True, "route": "qonto_oauth_ping"})


@app.before_request
def debug_qonto_routes_once():
    if request.path == "/healthz":
        return None
    if request.path == "/api/qonto/oauth/ping":
        app.logger.warning("[QONTO DEBUG] url_map=%s", app.url_map)


@app.get("/api/qonto/oauth/callback")
def api_qonto_oauth_callback():
    app.logger.info("[QONTO OAUTH CALLBACK] route called")
    error = request.args.get("error")
    error_description = request.args.get("error_description") or request.args.get("error_message") or ""
    code = request.args.get("code") or ""
    app.logger.info("[QONTO OAUTH CALLBACK] has_code=%s", str(bool(code)).lower())
    if error:
        message = error_description or error
        app.logger.warning("[QONTO OAUTH CALLBACK] provider error status=%s message=%s", error, _sanitize_qonto_error(message))
        return redirect(_qonto_oauth_settings_redirect("error"))

    if not code:
        app.logger.warning("[QONTO OAUTH CALLBACK] missing authorization code")
        return redirect(_qonto_oauth_settings_redirect("error"))

    state = request.args.get("state") or ""
    expected_state = session.pop("qonto_oauth_state", "")
    if expected_state and (not state or not hmac.compare_digest(state, expected_state)):
        app.logger.warning("[QONTO OAUTH CALLBACK] state mismatch has_state=%s", bool(state))
        return redirect(_qonto_oauth_settings_redirect("error"))

    try:
        payload = _exchange_qonto_oauth_token({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _qonto_oauth_redirect_uri(),
            "client_id": _qonto_oauth_client_id(),
            "client_secret": _qonto_oauth_client_secret(),
        })
        app.logger.info("[QONTO OAUTH CALLBACK] token exchange status=success")
        data = load_data()
        app.logger.info(
            "[QONTO OAUTH CALLBACK] token payload received has_access_token=%s has_refresh_token=%s expires_in=%s scope=%s",
            bool(payload.get("access_token")),
            bool(payload.get("refresh_token")),
            payload.get("expires_in"),
            payload.get("scope") or payload.get("scopes") or "",
        )
        _store_qonto_oauth_tokens(data, payload)
        return redirect(_qonto_oauth_settings_redirect("success"))
    except QontoApiError as exc:
        app.logger.warning("[QONTO OAUTH CALLBACK] token exchange status=%s message=%s", getattr(exc, "status_code", "unknown"), _sanitize_qonto_error(str(exc)))
    except Exception as exc:
        app.logger.warning("[QONTO OAUTH CALLBACK] token exchange status=unknown message=%s", _sanitize_qonto_error(str(exc)))
    return redirect(_qonto_oauth_settings_redirect("error"))


@app.errorhandler(404)
def page_not_found(error):
    if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
        return jsonify({"ok": False, "error": "not_found"}), 404

    trainee_login_url = None
    path_parts = [part for part in request.path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] == "espace":
        token = path_parts[1]
        data = load_data()
        _, trainee = find_session_and_trainee_by_token(data, token)
        trainee_login_url = (
            url_for("public_trainee_login", token=token)
            if trainee
            else url_for("public_trainee_global_login")
        )

    return render_template("404.html", trainee_login_url=trainee_login_url), 404


@app.errorhandler(PartnerPostgresWriteConflict)
def partner_postgres_write_conflict(_error):
    app.logger.warning(
        "partner_postgres write_conflict partner_id=%s path=%s",
        _current_partner_id() if has_request_context() else "",
        request.path if has_request_context() else "",
    )
    if has_request_context() and _request_expects_json():
        return jsonify({
            "ok": False,
            "error": "partner_data_changed",
            "message": "Ces donnÃ©es viennent dâ€™Ãªtre modifiÃ©es. Rechargez la page avant de recommencer.",
        }), 409
    return make_response(
        "Ces donnÃ©es viennent dâ€™Ãªtre modifiÃ©es. Rechargez la page avant de recommencer.",
        409,
    )


@app.errorhandler(PartnerPostgresError)
def partner_postgres_unavailable(_error):
    # Never fall back to the global JSON store for an authenticated external
    # tenant: stale data is preferable to neither cross-tenant exposure nor a
    # partially persisted write.
    app.logger.exception(
        "partner_postgres request_failed partner_id=%s path=%s",
        _current_partner_id() if has_request_context() else "",
        request.path if has_request_context() else "",
    )
    if has_request_context() and _request_expects_json():
        return jsonify({
            "ok": False,
            "error": "partner_database_unavailable",
            "message": "Lâ€™espace partenaire est temporairement indisponible. RÃ©essayez dans quelques instants.",
        }), 503
    return make_response(
        "Lâ€™espace partenaire est temporairement indisponible. RÃ©essayez dans quelques instants.",
        503,
    )

# =========================
# Auth (admin)
# =========================
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

ADMIN_USER = os.environ.get("ADMIN_USER", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
SECRETARY_USER = os.environ.get("SECRETARY_USER", "").strip()
SECRETARY_PASSWORD = os.environ.get("SECRETARY_PASSWORD", "").strip()
SCOTIA_USER = os.environ.get("SCOTIA_USER", "").strip()
SCOTIA_PASSWORD = os.environ.get("SCOTIA_PASSWORD", "").strip()
INTEGRALE_SCOTIA_AUTO_LOGIN_EMAIL = "clement@integraleacademy.com"
SCOTIA_COMMENT_AUTHOR_LABELS = {
    INTEGRALE_SCOTIA_AUTO_LOGIN_EMAIL: "IntÃ©grale Connect",
    "scotiaformation@gmail.com": "Scotia",
}
SCOTIA_NOTIFICATION_EMAIL = os.environ.get("SCOTIA_NOTIFICATION_EMAIL", "scotiaformation@gmail.com").strip()
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "30"))

SESSION_INVALIDATION_CUTOFF = os.environ.get("SESSION_INVALIDATION_CUTOFF", "2026-07-10T00:00:00Z").strip()
SESSION_ISSUED_AT_KEY = "session_issued_at"

def _parse_session_cutoff(raw_value: str) -> Optional[datetime.datetime]:
    value = str(raw_value or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        app.logger.warning("SESSION_INVALIDATION_CUTOFF invalide: %r", raw_value)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)

def _session_issue_datetime() -> Optional[datetime.datetime]:
    issued_at = str(session.get(SESSION_ISSUED_AT_KEY) or "").strip()
    if not issued_at:
        return None
    if issued_at.endswith("Z"):
        issued_at = issued_at[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(issued_at)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)

def _stamp_authenticated_session() -> None:
    session[SESSION_ISSUED_AT_KEY] = (
        datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    )

def _session_has_authentication_marker() -> bool:
    return any(
        key in session or any(str(existing_key).startswith(key) for existing_key in session.keys())
        for key in ("admin_logged_in", "scotia_logged_in", "public_auth_")
    )

def _current_session_is_still_valid() -> bool:
    cutoff = _parse_session_cutoff(SESSION_INVALIDATION_CUTOFF)
    if cutoff is None:
        return True
    issued_at = _session_issue_datetime()
    return issued_at is None or issued_at >= cutoff
ADMIN_PUSH_TITLE = os.environ.get("ADMIN_PUSH_TITLE", "IntÃ©grale Connect")
WEB_PUSH_VAPID_PUBLIC_KEY = os.environ.get("WEB_PUSH_VAPID_PUBLIC_KEY", "").strip()
WEB_PUSH_VAPID_PRIVATE_KEY = os.environ.get("WEB_PUSH_VAPID_PRIVATE_KEY", "").strip()
WEB_PUSH_VAPID_CLAIMS_SUB = os.environ.get("WEB_PUSH_VAPID_CLAIMS_SUB", "mailto:admin@example.com").strip()
WEB_PUSH_LIBRARY_AVAILABLE = importlib.util.find_spec("pywebpush") is not None
PYPDF_LIBRARY_AVAILABLE = importlib.util.find_spec("pypdf") is not None
REPORTLAB_LIBRARY_AVAILABLE = importlib.util.find_spec("reportlab") is not None

YPAREO_API_URL_DEFAULT = "https://api.ypareo-neo.com"
YPAREO_AUTH_ENDPOINT = "/authenticate"
YPAREO_APPRENANTS_ENDPOINT = "/personne"
YPAREO_CURSUS_ENDPOINT = "/personne/{IdPersonne}/cursus"
YPAREO_REQUEST_TIMEOUT_SECONDS = 15
YPAREO_ACCESS_TOKEN_DEFAULT_TTL_SECONDS = 30 * 60
YPAREO_AUTH_ERROR_MESSAGE = (
    "Authentification YPAREO impossible : vÃ©rifier le token initial YPAREO_AUTH_TOKEN."
)
YPAREO_CREATION_ERROR_MESSAGE = (
    "CrÃ©ation YPAREO impossible : vÃ©rifier les donnÃ©es envoyÃ©es ou les droits API."
)
YPAREO_CURSUS_ERROR_MESSAGE = (
    "CrÃ©ation du cursus YPAREO impossible : vÃ©rifier les donnÃ©es envoyÃ©es ou les droits API."
)
YPAREO_FORMATION_NOT_LINKED_ERROR = "Formation non liÃ©e Ã  un idFormation YPAREO"
YPAREO_DSSP_NOT_CONFIGURED_ERROR = "Formation DSSP / Dirigeant non configurÃ©e dans Render"

# =========================
# Qonto integration (server-side only)
# =========================
QONTO_API_BASE_URL_DEFAULT = "https://thirdparty.qonto.com"
QONTO_STATUS_OK_MESSAGE = "Qonto connectÃ©"
QONTO_STATUS_NOT_CONFIGURED_MESSAGE = "Qonto non configurÃ©"
QONTO_STATUS_FORBIDDEN_MESSAGE = "Identifiants Qonto invalides ou droits insuffisants"
QONTO_WEBHOOK_SIGNATURE_HEADERS = (
    "X-Qonto-Signature",
    "Qonto-Signature",
    "X-Hub-Signature-256",
    "X-Signature",
)

QONTO_OAUTH_SCOPE = "offline_access client.read client.write client_invoice.write client_invoices.read sepa_direct_debit.read sepa_direct_debit.write webhook"
QONTO_OAUTH_ENVIRONMENT = "production"
QONTO_OAUTH_PRODUCTION_BASE_URL = "https://oauth.qonto.com"
QONTO_OAUTH_REQUIRED_MESSAGE = "Connexion Qonto OAuth requise pour programmer les prÃ©lÃ¨vements SEPA."
QONTO_OAUTH_PRODUCTION_REDIRECT_URI = "https://gestionstagiaires-r5no.onrender.com/api/qonto/oauth/callback"
QONTO_OAUTH_LEGACY_HOSTS = {"gestionstagiaires-test-v2.onrender.com"}
_qonto_oauth_refresh_lock = threading.RLock()
APP_BASE_URL = (
    os.environ.get("APP_BASE_URL")
    or os.environ.get("PUBLIC_BASE_URL")
    or "https://gestionstagiaires-r5no.onrender.com"
).strip().rstrip("/")


def _normalize_qonto_oauth_redirect_uri(value: str) -> str:
    """Keep Qonto OAuth callbacks on the production application host.

    The previous Render hostname must never be sent to Qonto: it would make
    the provider return the administrator to the retired application.
    """
    raw = (value or "").strip().rstrip("/")
    if not raw:
        return QONTO_OAUTH_PRODUCTION_REDIRECT_URI
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.hostname in QONTO_OAUTH_LEGACY_HOSTS:
        return QONTO_OAUTH_PRODUCTION_REDIRECT_URI
    return raw


QONTO_OAUTH_REDIRECT_URI = (
    _normalize_qonto_oauth_redirect_uri(
        os.environ.get("QONTO_OAUTH_REDIRECT_URI")
        or f"{APP_BASE_URL}/api/qonto/oauth/callback"
    )
)



class QontoConfigurationError(RuntimeError):
    """Raised when Qonto credentials are missing from server environment variables."""


def _qonto_secret(value: str) -> str:
    return _normalize_render_secret(value or "")


def _qonto_login() -> str:
    return _qonto_secret(os.environ.get("QONTO_LOGIN") or "")


def _qonto_secret_key() -> str:
    return _qonto_secret(os.environ.get("QONTO_SECRET_KEY") or "")


def _qonto_base_url() -> str:
    configured = (os.environ.get("QONTO_API_BASE_URL") or QONTO_API_BASE_URL_DEFAULT).strip().rstrip("/")
    if "sandbox" in configured and "staging.qonto.co" in configured:
        return QONTO_API_BASE_URL_DEFAULT
    return configured


def _qonto_oauth_environment() -> str:
    return QONTO_OAUTH_ENVIRONMENT


def _qonto_oauth_base_url() -> str:
    configured = (os.environ.get("QONTO_OAUTH_BASE_URL") or "").strip().rstrip("/")
    if configured and not ("sandbox" in configured and "staging.qonto.co" in configured):
        return configured
    return QONTO_OAUTH_PRODUCTION_BASE_URL


def _qonto_oauth_client_id() -> str:
    return _qonto_secret(os.environ.get("QONTO_OAUTH_CLIENT_ID") or os.environ.get("QONTO_CLIENT_ID") or "")


def _qonto_oauth_client_secret() -> str:
    return _qonto_secret(os.environ.get("QONTO_OAUTH_CLIENT_SECRET") or os.environ.get("QONTO_CLIENT_SECRET") or "")


def _qonto_staging_token() -> str:
    return _qonto_secret(os.environ.get("QONTO_STAGING_TOKEN") or os.environ.get("QONTO_OAUTH_STAGING_TOKEN") or "")


def _qonto_oauth_redirect_uri() -> str:
    # Qonto requires a byte-for-byte match with the redirect URI configured in
    # the Developer Portal and reused during the token exchange.
    return QONTO_OAUTH_REDIRECT_URI


def _qonto_oauth_settings_redirect(outcome: str):
    """Return administrators to the canonical host after an OAuth callback."""
    callback = urlparse(_qonto_oauth_redirect_uri())
    return f"{callback.scheme}://{callback.netloc}/admin/qonto?oauth={quote(outcome)}"


def _qonto_oauth_is_configured() -> bool:
    return bool(_qonto_oauth_client_id() and _qonto_oauth_client_secret())


def mask_qonto_iban(iban: Any) -> str:
    normalized = re.sub(r"\s+", "", str(iban or "")).upper()
    if not normalized:
        return ""
    if len(normalized) <= 8:
        return "*" * len(normalized)
    return f"{normalized[:4]}********{normalized[-4:]}"


def _qonto_bank_account_summary(account: Any) -> Dict[str, Any]:
    account = account if isinstance(account, dict) else {}
    return {
        "id": account.get("id") or "",
        "iban": mask_qonto_iban(account.get("iban") or account.get("IBAN")),
        "name": account.get("name") or "",
        "status": account.get("status") or "",
        "main": bool(account.get("main") or account.get("is_main")),
    }


def get_qonto_organization_bank_accounts() -> Dict[str, Any]:
    data = _qonto_request("GET", "/v2/organization")
    organization = data.get("organization") if isinstance(data.get("organization"), dict) else data
    bank_accounts = organization.get("bank_accounts") if isinstance(organization, dict) else []
    if not isinstance(bank_accounts, list):
        bank_accounts = []
    return {
        "organization": {
            "id": organization.get("id") or "",
            "name": organization.get("name") or "",
        },
        "bank_accounts": [_qonto_bank_account_summary(account) for account in bank_accounts],
    }


def get_qonto_bank_account_id() -> str:
    bank_account_id = _qonto_secret(os.environ.get("QONTO_BANK_ACCOUNT_ID") or os.environ.get("QONTO_SEPA_BANK_ACCOUNT_ID") or "")
    if not bank_account_id:
        raise QontoConfigurationError("QONTO_BANK_ACCOUNT_ID manquant : renseignez le compte bancaire Qonto Ã  utiliser pour programmer les prÃ©lÃ¨vements SEPA.")
    return bank_account_id


def _qonto_oauth_missing_scopes(data: Optional[Dict[str, Any]] = None) -> List[str]:
    data = data or load_data()
    settings = _qonto_oauth_settings(data)
    raw = settings.get("scopes") or settings.get("scope") or []
    if isinstance(raw, str):
        granted = {item.strip() for item in raw.replace(",", " ").split() if item.strip()}
    elif isinstance(raw, list):
        granted = {str(item).strip() for item in raw if str(item).strip()}
    else:
        granted = set()
    required = {item for item in QONTO_OAUTH_SCOPE.split() if item != "offline_access"}
    return sorted(required - granted)


def _qonto_oauth_has_scope(scope: str, data: Optional[Dict[str, Any]] = None) -> bool:
    """Never infer a granted scope from the presence of an old OAuth token."""
    data = data or load_data()
    settings = _qonto_oauth_settings(data)
    raw = settings.get("scopes") or settings.get("scope") or []
    granted = ({item.strip() for item in raw.replace(",", " ").split() if item.strip()}
               if isinstance(raw, str) else {str(item).strip() for item in raw if str(item).strip()})
    return scope in granted


def _ensure_qonto_oauth_ready(data: Optional[Dict[str, Any]] = None) -> None:
    data = data or load_data()
    if not _qonto_oauth_connected(data):
        raise QontoConfigurationError(QONTO_OAUTH_REQUIRED_MESSAGE)
    missing = _qonto_oauth_missing_scopes(data)
    if missing:
        raise QontoConfigurationError("Connexion Qonto OAuth incomplÃ¨te : reconnectez Qonto depuis RÃ©glages > Qonto pour autoriser les scopes manquants : " + ", ".join(missing))

def get_qonto_invoice_iban():
    iban = os.getenv("QONTO_IBAN", "").strip().replace(" ", "").upper()
    if not iban:
        raise ValueError("QONTO_IBAN manquant")
    return iban


def format_qonto_vat_rate(vat_rate):
    try:
        rate = float(vat_rate)
    except Exception:
        rate = 20.0

    if rate > 1:
        rate = rate / 100

    return str(rate).rstrip("0").rstrip(".") if "." in str(rate) else str(rate)


def _is_qonto_missing_iban_error(message: str) -> bool:
    normalized = str(message or "").lower()
    return "invalid_iban" in normalized or "iban is empty" in normalized or "qonto_iban manquant" in normalized


def get_qonto_headers() -> Dict[str, str]:
    """Build Qonto API key headers without Bearer, Basic or Base64 encoding."""
    return {
        "Authorization": f"{_qonto_login()}:{_qonto_secret_key()}",
        "Accept": "application/json",
    }


def _qonto_is_configured() -> bool:
    return bool(_qonto_login() and _qonto_secret_key())


def _sanitize_qonto_error(message: str) -> str:
    sanitized = str(message or "")
    secrets_to_mask = [_qonto_login(), _qonto_secret_key(), _qonto_oauth_client_secret(), _qonto_webhook_secret() if "_qonto_webhook_secret" in globals() else ""]
    if "load_data" in globals():
        try:
            data = load_data()
            secrets_to_mask.extend([_qonto_oauth_access_token(data), _qonto_oauth_refresh_token(data)])
        except Exception:
            pass
    for secret in secrets_to_mask:
        if secret:
            sanitized = sanitized.replace(secret, "[masquÃ©]")
    return sanitized


def _qonto_oauth_settings(data: Dict[str, Any]) -> Dict[str, Any]:
    settings = data.setdefault("qonto_oauth", {})
    if not isinstance(settings, dict):
        data["qonto_oauth"] = {}
        settings = data["qonto_oauth"]
    return settings


def _qonto_oauth_access_token(data: Dict[str, Any]) -> str:
    return _qonto_secret((_qonto_oauth_settings(data).get("access_token") or ""))


def _qonto_oauth_refresh_token(data: Dict[str, Any]) -> str:
    return _qonto_secret((_qonto_oauth_settings(data).get("refresh_token") or ""))


def _qonto_oauth_token_environment(data: Dict[str, Any]) -> str:
    return str(_qonto_oauth_settings(data).get("environment") or "").strip().lower()


def _qonto_oauth_connected(data: Optional[Dict[str, Any]] = None) -> bool:
    data = data or load_data()
    settings = _qonto_oauth_settings(data)
    return bool(settings.get("refresh_token")) and _qonto_oauth_token_environment(data) == _qonto_oauth_environment()


def _qonto_oauth_has_incompatible_token(data: Optional[Dict[str, Any]] = None) -> bool:
    data = data or load_data()
    settings = _qonto_oauth_settings(data)
    return bool(settings.get("refresh_token")) and _qonto_oauth_token_environment(data) not in ("", _qonto_oauth_environment())


def _reset_qonto_oauth_tokens(data: Dict[str, Any]) -> None:
    settings = _qonto_oauth_settings(data)
    for key in ("access_token", "refresh_token", "expires_at", "scope", "scopes", "environment"):
        settings.pop(key, None)
    settings["connected"] = False
    settings["updated_at"] = _now_iso()


def _qonto_oauth_status_message(data: Optional[Dict[str, Any]] = None) -> str:
    data = data or load_data()
    if _qonto_oauth_connected(data):
        return "OAuth Qonto : connectÃ© production"
    if _qonto_oauth_has_incompatible_token(data):
        return "OAuth Qonto : connectÃ© sandbox, incompatible avec production"
    return "OAuth Qonto : non connectÃ©"


def _store_qonto_oauth_tokens(data: Dict[str, Any], token_payload: Dict[str, Any]) -> None:
    settings = _qonto_oauth_settings(data)
    now = int(time.time())
    expires_in = int(token_payload.get("expires_in") or 3600)
    refresh_token = token_payload.get("refresh_token") or settings.get("refresh_token") or ""
    access_token = token_payload.get("access_token") or settings.get("access_token") or ""
    settings.update({
        "connected": bool(refresh_token),
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": token_payload.get("token_type") or "bearer",
        "scope": token_payload.get("scope") or settings.get("scope") or "",
        "scopes": token_payload.get("scopes") or (str(token_payload.get("scope") or settings.get("scope") or "").split()),
        "expires_at": now + max(expires_in - 60, 60),
        "created_at": settings.get("created_at") or _now_iso(),
        "updated_at": _now_iso(),
        "environment": _qonto_oauth_environment(),
    })
    # OAuth is one of the few callers allowed to replace the canonical token
    # set. Ordinary business-data saves preserve the latest tokens already on
    # disk so a request that started before this rotation cannot erase it.
    save_data(data, preserve_qonto_oauth=False)


def _exchange_qonto_oauth_token(form_data: Dict[str, str]) -> Dict[str, Any]:
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    response = requests.post(f"{QONTO_OAUTH_PRODUCTION_BASE_URL}/oauth2/token", headers=headers, data=form_data, timeout=20)
    raw_body = response.text or ""
    if not response.ok:
        raise QontoApiError(response.status_code, _sanitize_qonto_error(raw_body), _qonto_response_trace_id(response, raw_body))
    return response.json()


def _qonto_oauth_bearer_token(data: Optional[Dict[str, Any]] = None, *, force_refresh: bool = False) -> str:
    """Return a usable OAuth token, optionally proving the refresh grant is valid.

    Merely having a refresh token in ``data.json`` does not mean that Qonto still
    accepts it (the user can revoke the authorization from Qonto).  The forced
    refresh is used by the settings health check so that the UI never labels a
    revoked credential as an active connection.
    """
    data = data or load_data()
    settings = _qonto_oauth_settings(data)
    if not _qonto_oauth_connected(data):
        raise QontoConfigurationError(QONTO_OAUTH_REQUIRED_MESSAGE)
    if force_refresh or int(settings.get("expires_at") or 0) <= int(time.time()) + 60:
        # Qonto rotates refresh tokens. Serialize refreshes so two simultaneous
        # SEPA requests cannot both consume the same one and make the second
        # request erase the newly rotated credentials with ``invalid_grant``.
        with _qonto_oauth_refresh_lock:
            latest_data = load_data()
            latest_settings = _qonto_oauth_settings(latest_data)
            latest_token = _qonto_oauth_refresh_token(latest_data)
            original_token = _qonto_oauth_refresh_token(data)
            latest_is_fresh = int(latest_settings.get("expires_at") or 0) > int(time.time()) + 60
            if latest_token and latest_token != original_token and latest_is_fresh:
                return _qonto_oauth_access_token(latest_data)
            refresh_data = latest_data if latest_token else data
            try:
                payload = _exchange_qonto_oauth_token({
                    "client_id": _qonto_oauth_client_id(),
                    "client_secret": _qonto_oauth_client_secret(),
                    "grant_type": "refresh_token",
                    "refresh_token": _qonto_oauth_refresh_token(refresh_data),
                })
            except QontoApiError as exc:
                error_text = f"{exc.body} {exc}".lower()
                if exc.status_code == 400 and "invalid_grant" in error_text:
                    # Never clear a newer token saved while this request was in
                    # flight. Only the token actually rejected by Qonto may be
                    # marked disconnected.
                    canonical_data = load_data()
                    if _qonto_oauth_refresh_token(canonical_data) != _qonto_oauth_refresh_token(refresh_data):
                        return _qonto_oauth_bearer_token(canonical_data)
                    _reset_qonto_oauth_tokens(canonical_data)
                    save_data(canonical_data, preserve_qonto_oauth=False)
                    raise QontoConfigurationError(
                        "Connexion Qonto OAuth expirÃ©e ou rÃ©voquÃ©e : reconnectez Qonto depuis RÃ©glages > Qonto avant de programmer un prÃ©lÃ¨vement SEPA."
                    ) from exc
                raise
            _store_qonto_oauth_tokens(refresh_data, payload)
            return _qonto_oauth_access_token(refresh_data)
    return _qonto_oauth_access_token(data)


def test_qonto_connection() -> Tuple[bool, int]:
    if not _qonto_is_configured():
        raise QontoConfigurationError(QONTO_STATUS_NOT_CONFIGURED_MESSAGE)
    response = requests.get(
        f"{_qonto_base_url()}/v2/organization",
        headers=get_qonto_headers(),
        timeout=12,
    )
    return response.ok, response.status_code


class QontoApiError(RuntimeError):
    def __init__(self, status_code: int, body: str = "", trace_id: str = "", message: Optional[str] = None):
        self.status_code = status_code
        self.body = body or ""
        self.trace_id = trace_id or ""
        precise = message or _extract_qonto_error_message(self.body) or self.body or "Erreur Qonto"
        super().__init__(f"Qonto HTTP {status_code}: {precise}" + (f" trace_id={self.trace_id}" if self.trace_id else ""))


class QontoNotFoundError(QontoApiError):
    pass


def cleanQontoPayload(obj: Any) -> Any:
    """Remove values Qonto rejects: undefined-equivalents, nulls, empty strings and empty objects."""
    if isinstance(obj, dict):
        cleaned: Dict[str, Any] = {}
        for key, value in obj.items():
            cleaned_value = cleanQontoPayload(value)
            if cleaned_value is None or cleaned_value == "":
                continue
            if isinstance(cleaned_value, dict) and not cleaned_value:
                continue
            if isinstance(cleaned_value, list) and not cleaned_value:
                continue
            cleaned[key] = cleaned_value
        return cleaned
    if isinstance(obj, list):
        cleaned_list = []
        for value in obj:
            cleaned_value = cleanQontoPayload(value)
            if cleaned_value is None or cleaned_value == "":
                continue
            if isinstance(cleaned_value, dict) and not cleaned_value:
                continue
            if isinstance(cleaned_value, list) and not cleaned_value:
                continue
            cleaned_list.append(cleaned_value)
        return cleaned_list
    if obj is None:
        return None
    if isinstance(obj, str) and obj == "":
        return ""
    return obj


def _extract_qonto_error_message(raw_body: str) -> str:
    if not raw_body:
        return ""
    try:
        data = json.loads(raw_body)
    except Exception:
        return raw_body[:500]
    if isinstance(data, dict):
        for key in ("message", "error", "detail", "description"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        errors = data.get("errors")
        if isinstance(errors, list) and errors:
            parts = []
            for error in errors[:5]:
                if isinstance(error, dict):
                    parts.append(str(error.get("message") or error.get("detail") or error.get("code") or error))
                else:
                    parts.append(str(error))
            return "; ".join(part for part in parts if part)
    return raw_body[:500]


def _qonto_response_trace_id(response: requests.Response, raw_body: str) -> str:
    for key in ("x-qonto-trace-id", "x-request-id", "trace-id", "trace_id"):
        value = response.headers.get(key)
        if value:
            return value
    try:
        data = json.loads(raw_body or "{}")
        if isinstance(data, dict):
            return str(data.get("trace_id") or data.get("traceId") or data.get("request_id") or "")
    except Exception:
        pass
    return ""


INVALID_QONTO_CLIENT_SEARCH_MESSAGE = "Recherche client Qonto invalide : utiliser uniquement filter[name], filter[email], filter[tax_identification_number] ou filter[vat_number]."
INVALID_QONTO_SEARCH_MARKERS = ("queryfields", "query_fields", "QueryFields", "first_name last_name name email")


def _contains_invalid_qonto_search_marker(value: Any) -> bool:
    try:
        serialized = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    except Exception:
        serialized = str(value)
    lowered = serialized.lower()
    return any(marker.lower() in lowered for marker in INVALID_QONTO_SEARCH_MARKERS)


def _qonto_request(method: str, path: str, payload: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if has_request_context() and (
        _is_external_partner_session()
        or (session.get("assist_partner_id") and _is_super_admin_session())
    ):
        raise QontoConfigurationError(
            "Qonto nâ€™est pas disponible tant que ce partenaire ne possÃ¨de pas sa propre connexion OAuth."
        )
    endpoint = path if path.startswith("/") else f"/{path}"
    is_webhook_endpoint = endpoint.startswith("/v2/webhook_subscriptions")
    is_sepa_endpoint = endpoint.startswith("/v2/sepa/direct_debit")
    # Qonto explicitly requires OAuth2 for webhook subscriptions.  Do not let
    # the API-key fallback leak onto these endpoints (it returns HTTP 401).
    if is_webhook_endpoint:
        if not _qonto_oauth_connected():
            raise QontoConfigurationError(QONTO_OAUTH_REQUIRED_MESSAGE)
        if not _qonto_oauth_has_scope("webhook"):
            raise QontoConfigurationError("La connexion OAuth actuelle ne possÃ¨de pas lâ€™autorisation webhook. RÃ©initialisez puis reconnectez Qonto.")
        _ensure_qonto_oauth_ready()
    elif not is_sepa_endpoint and not _qonto_is_configured():
        raise QontoConfigurationError("Qonto nâ€™est pas connectÃ©")
    cleaned_payload = cleanQontoPayload(payload) if payload is not None else None
    if _contains_invalid_qonto_search_marker(endpoint) or _contains_invalid_qonto_search_marker(params) or _contains_invalid_qonto_search_marker(cleaned_payload):
        app.logger.error("[QONTO] invalid client search blocked method=%s path=%s params=%s", method.upper(), endpoint, params)
        raise RuntimeError(INVALID_QONTO_CLIENT_SEARCH_MESSAGE)
    url = f"{_qonto_base_url()}{endpoint}"
    prepared = requests.Request(method.upper(), url, params=params).prepare()
    called_url = prepared.url or url
    try:
        headers = get_qonto_headers()
        if cleaned_payload is not None:
            headers = {**headers, "Content-Type": "application/json"}
        if is_sepa_endpoint or is_webhook_endpoint:
            headers = {"Authorization": f"Bearer {_qonto_oauth_bearer_token()}", "Content-Type": "application/json", "Accept": "application/json"}
        # Webhook creation must use a JSON request body.  Keep this explicit so
        # a generic-client argument mismatch cannot silently turn it into query
        # parameters or an empty form body.
        if is_webhook_endpoint and method.upper() == "POST":
            app.logger.info(
                "[QONTO] webhook_subscription_request method=%s url=%s payload_keys=%s callback_url=%s types=%s secret_present=%s content_type=%s",
                method.upper(), called_url, sorted((cleaned_payload or {}).keys()),
                (cleaned_payload or {}).get("callback_url"), (cleaned_payload or {}).get("types"),
                bool((cleaned_payload or {}).get("secret")), headers.get("Content-Type"),
            )
            response = requests.post(url, json=cleaned_payload, headers=headers, timeout=20)
        else:
            response = requests.request(method.upper(), url, headers=headers, json=cleaned_payload if cleaned_payload is not None else None, params=params, timeout=20)
        raw_body = response.text or ""
        trace_id = _qonto_response_trace_id(response, raw_body)
        log_payload = cleaned_payload
        if is_webhook_endpoint and isinstance(cleaned_payload, dict) and "secret" in cleaned_payload:
            log_payload = {**cleaned_payload, "secret": "***"}
        safe_payload = _sanitize_qonto_error(json.dumps(log_payload, ensure_ascii=False)) if log_payload is not None else None
        app.logger.info("[QONTO] api_call method=%s url=%s payload=%s status=%s trace_id=%s body=%s", method.upper(), called_url, safe_payload, response.status_code, trace_id or "", _sanitize_qonto_error(raw_body[:4000]))
        if not response.ok:
            if response.status_code == 404:
                raise QontoNotFoundError(response.status_code, raw_body, trace_id)
            raise QontoApiError(response.status_code, raw_body, trace_id)
        if not raw_body.strip():
            return {}
        return response.json()
    except (QontoConfigurationError, QontoApiError):
        raise
    except Exception as exc:
        raise RuntimeError(_sanitize_qonto_error(str(exc))) from exc


QONTO_FIELD_LABELS = {
    "street_address": "adresse de facturation",
    "address_line_1": "adresse de facturation",
    "address": "adresse de facturation",
    "city": "ville",
    "zip_code": "code postal",
    "postal_code": "code postal",
    "country_code": "pays",
    "name": "nom du client",
    "first_name": "prÃ©nom",
    "last_name": "nom",
    "email": "e-mail",
    "tax_identification_number": "SIRET",
    "tin_number": "SIRET",
    "tin number": "SIRET",
}


def _format_qonto_missing_fields_message(message: str) -> str:
    """Turn Qonto's technical required-field errors into an actionable French message."""
    if not message:
        return ""
    missing_fields = re.findall(r"`([^`]+)`\s+must have a value", message, flags=re.IGNORECASE)
    if not missing_fields:
        return ""
    labels: List[str] = []
    seen = set()
    for field in missing_fields:
        label = QONTO_FIELD_LABELS.get(field, field.replace("_", " "))
        if label not in seen:
            labels.append(label)
            seen.add(label)
    if not labels:
        return ""
    if len(labels) == 1:
        fields_text = labels[0]
    else:
        fields_text = ", ".join(labels[:-1]) + f" et {labels[-1]}"
    return (
        "Impossible de crÃ©er la facture Qonto : informations client incomplÃ¨tes. "
        f"Il manque : {fields_text}. "
        "ComplÃ©tez ces champs dans la fiche du stagiaire / financeur, puis relancez la crÃ©ation de facture."
    )


def _format_qonto_validation_errors(errors: List[Dict[str, str]]) -> str:
    labels = []
    seen = set()
    for error in errors or []:
        label = (error.get("label") or QONTO_FIELD_LABELS.get(error.get("field", "")) or error.get("field") or "champ").strip()
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
    if not labels:
        return "Qonto refuse la facture car les informations client sont incomplÃ¨tes."
    fields_text = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + f" et {labels[-1]}"
    return (
        "Impossible de crÃ©er la facture Qonto : informations client incomplÃ¨tes. "
        f"Il manque : {fields_text}. "
        "ComplÃ©tez ces champs dans la fiche du stagiaire / financeur, puis relancez la crÃ©ation de facture."
    )


def format_qonto_error_for_front(exc: Exception) -> str:
    if isinstance(exc, QontoApiError):
        extracted = _extract_qonto_error_message(exc.body)
        friendly = _format_qonto_missing_fields_message(extracted or str(exc))
        if friendly:
            return friendly
        return f"Erreur Qonto : {exc.status_code} {extracted or str(exc)}"
    sanitized = _sanitize_qonto_error(str(exc))
    friendly = _format_qonto_missing_fields_message(sanitized)
    if friendly:
        return friendly
    return f"Erreur Qonto : {sanitized}"

def _first_qonto_client(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    clients = data.get("clients") or data.get("client_list") or data.get("items") or []
    return clients[0] if isinstance(clients, list) and clients else None


def normalize_french_company_tax_id(value: Any) -> str:
    """Convert a French SIRET into the SIREN/TIN expected by Qonto."""
    compact = re.sub(r"[\s.\-]", "", str(value or "").strip()).upper()
    return compact[:9] if compact.isdigit() and len(compact) == 14 else compact


def find_qonto_client_by_name(name: str) -> Optional[Dict[str, Any]]:
    normalized_name = (name or "").strip()
    if not normalized_name:
        return None
    data = _qonto_request("GET", "/v2/clients", params={"filter[name]": normalized_name})
    return _first_qonto_client(data)


def find_qonto_client_by_tax_identification_number(tax_identification_number: str) -> Optional[Dict[str, Any]]:
    normalized_tax_id = normalize_french_company_tax_id(tax_identification_number)
    if not normalized_tax_id:
        return None
    data = _qonto_request("GET", "/v2/clients", params={"filter[tax_identification_number]": normalized_tax_id})
    return _first_qonto_client(data)


def search_qonto_client(criteria: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    email = (criteria.get("email") or "").strip()
    name = (criteria.get("name") or criteria.get("client_name") or "").strip()
    params = {"filter[email]": email} if email else ({"filter[name]": name} if name else {})
    data = _qonto_request("GET", "/v2/clients", params=params)
    clients = data.get("clients") or data.get("client_list") or data.get("items") or []
    for client in clients if isinstance(clients, list) else []:
        if email and (client.get("email") or "").strip().lower() == email.lower():
            return client
        if name and (client.get("name") or "").strip().lower() == name.lower():
            return client
    return _first_qonto_client(data)


def find_existing_qonto_client(client_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Prefer the company's stable SIRET before mutable name/email fields."""
    tax_id = normalize_french_company_tax_id(client_payload.get("tax_identification_number"))
    if tax_id:
        existing = find_qonto_client_by_tax_identification_number(tax_id)
        if existing:
            return existing
    return search_qonto_client({
        "email": client_payload.get("email"),
        "name": client_payload.get("name")
        or f"{client_payload.get('first_name', '')} {client_payload.get('last_name', '')}".strip(),
    })


def create_qonto_client(payload: Dict[str, Any]) -> Dict[str, Any]:
    client = dict(payload or {})
    # Qonto /v2/clients expects client fields at the JSON root: never wrap in
    # {client: ...}, {data: ...} or JSON:API attributes envelopes.
    if isinstance(client.get("client"), dict):
        client = dict(client["client"])
    elif isinstance(client.get("data"), dict):
        data = client["data"]
        client = dict(data.get("attributes") if isinstance(data.get("attributes"), dict) else data)

    kind = _qonto_client_kind(client)
    if kind == "company":
        if not (client.get("name") or "").strip():
            raise ValueError("Nom sociÃ©tÃ© obligatoire pour crÃ©er un client Qonto company")
        client.setdefault("currency", "EUR")
        client.setdefault("locale", "FR")
        billing = client.get("billing_address") if isinstance(client.get("billing_address"), dict) else {}
        for key in ("street_address", "city", "zip_code", "country_code"):
            if not (billing.get(key) or "").strip():
                raise ValueError(f"Adresse de facturation Qonto incomplÃ¨te : {key}")
        for forbidden in ("first_name", "last_name", "displayType", "address_line_2", "SociÃ©tÃ©"):
            client.pop(forbidden, None)
        if isinstance(client.get("billing_address"), dict):
            client["billing_address"].pop("address_line_2", None)
    else:
        for key in ("first_name", "last_name"):
            if not (client.get(key) or "").strip():
                raise ValueError(f"{key} obligatoire pour crÃ©er un client Qonto individual")

    cleaned_payload = cleanQontoPayload(client)
    app.logger.info("[QONTO CREATE CLIENT URL] %s", f"{_qonto_base_url()}/v2/clients")
    app.logger.info("[QONTO CREATE CLIENT PAYLOAD] %s", json.dumps(cleaned_payload, ensure_ascii=False, indent=2))
    return _qonto_request("POST", "/v2/clients", cleaned_payload)


def create_qonto_client_with_optional_tax_id(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a client without discarding its required company tax ID.

    Retrying without this value only postpones the failure until Qonto creates
    the invoice, where the French company TIN is mandatory.
    """
    return create_qonto_client(payload)


def update_qonto_client(client_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return _qonto_request("PATCH", f"/v2/clients/{client_id}", payload)


def get_or_create_qonto_billing_client(client_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a Qonto client that is usable for invoice creation.

    The invoice form is the source of truth for billing details.  When the
    client already exists in Qonto, patch it with the complete canonical
    payload instead of reusing an incomplete record (or creating a duplicate).
    """
    existing = find_existing_qonto_client(client_payload)
    if not existing:
        return create_qonto_client_with_optional_tax_id({
            "client": remove_invalid_qonto_phone(client_payload),
        })

    existing_client = existing.get("client") if isinstance(existing.get("client"), dict) else existing
    existing_client_id = existing_client.get("id")
    existing_tax_id = existing_client.get("tax_identification_number") or existing_client.get("tin_number")
    company_tax_missing = (
        _qonto_client_kind(client_payload) == "company"
        and bool(client_payload.get("tax_identification_number"))
        and not existing_tax_id
    )
    billing_address_missing = not qonto_client_has_complete_billing_address(existing)
    if existing_client_id and (company_tax_missing or billing_address_missing):
        update_payload = remove_invalid_qonto_phone(dict(client_payload))
        app.logger.info(
            "[QONTO] Completing existing billing client client_id=%s missing_tax_id=%s missing_billing_address=%s payload_keys=%s",
            existing_client_id,
            company_tax_missing,
            billing_address_missing,
            list(update_payload.keys()),
        )
        updated = update_qonto_client(existing_client_id, update_payload)
        if updated:
            return updated
    return existing


def create_qonto_invoice(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _qonto_request("POST", "/v2/client_invoices", payload)


def finalize_qonto_invoice(invoice_id: str) -> Dict[str, Any]:
    return _qonto_request("POST", f"/v2/client_invoices/{quote(str(invoice_id), safe='')}/finalize")


def send_qonto_invoice(invoice_id: str, email_payload: Dict[str, Any]) -> Dict[str, Any]:
    return _qonto_request("POST", f"/v2/client_invoices/{quote(str(invoice_id), safe='')}/send", email_payload)


def get_qonto_invoice(invoice_id: str) -> Dict[str, Any]:
    return _qonto_request("GET", f"/v2/client_invoices/{quote(str(invoice_id), safe='')}")


def list_qonto_invoices(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _qonto_request("GET", "/v2/client_invoices", params=params or {})


def _iter_qonto_invoice_payloads(payload: Any):
    if isinstance(payload, dict):
        invoice = _qonto_invoice_payload(payload)
        if isinstance(invoice, dict) and invoice is not payload:
            yield invoice
        for key in ("client_invoices", "invoices", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        yield _qonto_invoice_payload(item)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield _qonto_invoice_payload(item)


def find_qonto_invoice_by_number(invoice_number: str) -> Optional[Dict[str, Any]]:
    needle = str(invoice_number or "").strip()
    if not needle:
        return None
    param_attempts = (
        {"filter[number]": needle},
        {"number": needle},
        {"query": needle},
        {"search": needle},
    )
    for params in param_attempts:
        try:
            payload = list_qonto_invoices(params)
        except Exception as exc:
            app.logger.info("[QONTO] invoice number lookup failed number=%s params=%s error=%s", needle, params, exc)
            continue
        for invoice in _iter_qonto_invoice_payloads(payload):
            current_number = str(invoice.get("number") or invoice.get("invoice_number") or "").strip()
            if current_number == needle:
                return invoice
    return None


def _first_non_empty(mapping: Any, *keys: str) -> str:
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if value:
            return str(value)
    return ""


def _find_qonto_pdf_url(payload: Any) -> str:
    """Find the first PDF/public invoice URL exposed by a Qonto invoice payload."""
    url_keys = {"public_url", "url", "file_url", "pdf_url", "download_url"}
    if isinstance(payload, dict):
        for key in ("public_url", "pdf_url", "download_url", "file_url", "url"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key, value in payload.items():
            if key in url_keys and value:
                return str(value).strip()
            nested = _find_qonto_pdf_url(value)
            if nested:
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = _find_qonto_pdf_url(item)
            if nested:
                return nested
    return ""


def _find_qonto_attachment_id(payload: Any) -> str:
    """Find the first Qonto attachment id exposed by an invoice payload."""
    if isinstance(payload, dict):
        for key in ("attachment_id", "attachmentId", "pdf_attachment_id", "pdfAttachmentId"):
            value = payload.get(key)
            if value:
                return str(value).strip()
        attachment = payload.get("attachment")
        if isinstance(attachment, dict):
            value = attachment.get("id")
            if value:
                return str(value).strip()
        attachments = payload.get("attachments")
        if isinstance(attachments, list):
            for item in attachments:
                value = _find_qonto_attachment_id(item)
                if value:
                    return value
        for value in payload.values():
            nested = _find_qonto_attachment_id(value)
            if nested:
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = _find_qonto_attachment_id(item)
            if nested:
                return nested
    return ""


def get_qonto_attachment(attachment_id: str) -> Dict[str, Any]:
    return _qonto_request("GET", f"/v2/attachments/{quote(str(attachment_id), safe='')}")


class QontoPdfUnavailableError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        self.status_code = status_code
        super().__init__(message)


def _qonto_json_response(response: requests.Response, context: str) -> Dict[str, Any]:
    content_type = response.headers.get("Content-Type", "")
    raw_body = response.text or ""
    if not response.ok:
        app.logger.warning("QONTO PDF: %s status=%s", context, response.status_code)
        if response.status_code == 404:
            raise QontoNotFoundError(response.status_code, "Not found", _qonto_response_trace_id(response, raw_body))
        if response.status_code in (401, 403):
            raise QontoPdfUnavailableError("Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto.", 502)
        if response.status_code == 429:
            raise QontoPdfUnavailableError("Qonto limite temporairement les demandes. RÃ©essayez dans quelques secondes.", 429)
        raise QontoPdfUnavailableError("Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto.", 502)
    if "json" not in content_type.lower():
        app.logger.warning("QONTO PDF: %s rÃ©ponse non JSON content_type=%s", context, content_type[:80])
        raise QontoPdfUnavailableError("Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto.", 502)
    try:
        payload = response.json()
    except ValueError as exc:
        app.logger.warning("QONTO PDF: %s JSON invalide", context)
        raise QontoPdfUnavailableError("Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto.", 502) from exc
    if not isinstance(payload, dict):
        raise QontoPdfUnavailableError("Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto.", 502)
    return payload


def _qonto_get_json(path: str, context: str) -> Dict[str, Any]:
    if not _qonto_is_configured():
        raise QontoConfigurationError("Qonto nâ€™est pas connectÃ©")
    url = f"{_qonto_base_url()}{path if path.startswith('/') else '/' + path}"
    try:
        response = requests.get(url, headers=get_qonto_headers(), timeout=20)
    except requests.Timeout as exc:
        app.logger.warning("QONTO PDF: timeout %s", context)
        raise QontoPdfUnavailableError("Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto.", 504) from exc
    return _qonto_json_response(response, context)


def _qonto_attachment_payload(attachment_payload: Dict[str, Any]) -> Dict[str, Any]:
    attachment = attachment_payload.get("attachment") if isinstance(attachment_payload, dict) else None
    if not isinstance(attachment, dict):
        app.logger.warning("QONTO PDF: champ attachment absent")
        raise QontoPdfUnavailableError("Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto.", 502)
    return attachment


def fetch_qonto_client_invoice_pdf(invoice_id: str, max_attempts: int = 3, retry_delay: float = 0.35) -> Tuple[bytes, str]:
    invoice_id = str(invoice_id or "").strip()
    if not invoice_id or not re.match(r"^[A-Za-z0-9_-]+$", invoice_id):
        raise QontoPdfUnavailableError("Facture Qonto invalide ou absente.", 400)
    if not _qonto_is_configured():
        raise QontoConfigurationError("Qonto nâ€™est pas connectÃ©")

    attachment_id = ""
    invoice_payload: Dict[str, Any] = {}
    attempts = max(1, min(int(max_attempts or 1), 3))
    for attempt in range(attempts):
        invoice_payload = _qonto_get_json(f"/v2/client_invoices/{quote(invoice_id, safe='')}", "invoice")
        client_invoice = invoice_payload.get("client_invoice")
        if not isinstance(client_invoice, dict):
            app.logger.warning("QONTO PDF: champ client_invoice absent invoice_id=%s", invoice_id)
            raise QontoPdfUnavailableError("Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto.", 502)
        attachment_id = str(client_invoice.get("attachment_id") or "").strip()
        if attachment_id:
            break
        app.logger.info("QONTO PDF: attachment_id absent invoice_id=%s attempt=%s", invoice_id, attempt + 1)
        if attempt < attempts - 1:
            time.sleep(max(0.0, retry_delay))
    if not attachment_id:
        raise QontoPdfUnavailableError("Le PDF de cette facture est encore en cours de gÃ©nÃ©ration. RÃ©essayez dans quelques secondes.", 409)

    attachment_payload = _qonto_get_json(f"/v2/attachments/{quote(attachment_id, safe='')}", "attachment")
    attachment = _qonto_attachment_payload(attachment_payload)
    declared_type = str(attachment.get("file_content_type") or "").lower()
    if declared_type and declared_type != "application/pdf":
        app.logger.warning("QONTO PDF: attachment non PDF invoice_id=%s attachment_id=%s", invoice_id, attachment_id)
        raise QontoPdfUnavailableError("Le document retournÃ© par Qonto nâ€™est pas un PDF valide.", 502)
    pdf_url = str(attachment.get("url") or "").strip()
    if not pdf_url:
        app.logger.warning("QONTO PDF: attachment.url absent invoice_id=%s attachment_id=%s", invoice_id, attachment_id)
        raise QontoPdfUnavailableError("Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto.", 502)
    try:
        pdf_response = requests.get(pdf_url, timeout=30)
    except requests.Timeout as exc:
        app.logger.warning("QONTO PDF: timeout lors du tÃ©lÃ©chargement invoice_id=%s", invoice_id)
        raise QontoPdfUnavailableError("Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto.", 504) from exc
    if not pdf_response.ok:
        app.logger.warning("QONTO PDF: tÃ©lÃ©chargement status=%s invoice_id=%s", pdf_response.status_code, invoice_id)
        msg = "Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto."
        if pdf_response.status_code in (401, 403, 404):
            msg = "Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto."
        raise QontoPdfUnavailableError(msg, 502)
    pdf_content = pdf_response.content or b""
    if not pdf_content:
        app.logger.warning("QONTO PDF: tÃ©lÃ©chargement vide invoice_id=%s", invoice_id)
        raise QontoPdfUnavailableError("Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto.", 502)
    if not pdf_content.startswith(b"%PDF"):
        app.logger.warning("QONTO PDF: contenu non PDF invoice_id=%s", invoice_id)
        raise QontoPdfUnavailableError("Le document retournÃ© par Qonto nâ€™est pas un PDF valide.", 502)
    filename = secure_filename(str(attachment.get("file_name") or attachment.get("filename") or f"facture-qonto-{invoice_id}.pdf")) or f"facture-qonto-{invoice_id}.pdf"
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf"
    return pdf_content, filename


def _download_qonto_attachment_pdf(attachment_id: str) -> Tuple[bytes, str]:
    attachment_id = str(attachment_id or "").strip()
    if not attachment_id:
        raise QontoPdfUnavailableError("Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto.", 400)
    attachment_payload = _qonto_get_json(f"/v2/attachments/{quote(attachment_id, safe='')}", "attachment")
    attachment = _qonto_attachment_payload(attachment_payload)
    pdf_url = str(attachment.get("url") or "").strip()
    if not pdf_url:
        raise QontoPdfUnavailableError("Impossible de rÃ©cupÃ©rer le PDF auprÃ¨s de Qonto.", 502)
    pdf_content, content_type = _download_pdf_from_url(pdf_url)
    return pdf_content, content_type


def _download_pdf_from_url(pdf_url: str) -> Tuple[bytes, str]:
    pdf_response = requests.get(str(pdf_url), timeout=30)
    if not pdf_response.ok:
        raise RuntimeError(f"TÃ©lÃ©chargement PDF Qonto impossible ({pdf_response.status_code})")
    if not (pdf_response.content or b"").startswith(b"%PDF"):
        raise RuntimeError("Le document retournÃ© par Qonto nâ€™est pas un PDF valide.")
    return pdf_response.content, "application/pdf"


def download_qonto_invoice_pdf(invoice_id: str, invoice_number: str = "") -> Tuple[bytes, str]:
    pdf_content, _filename = fetch_qonto_client_invoice_pdf(invoice_id)
    return pdf_content, "application/pdf"


def list_qonto_direct_debit_mandates(
    client_id: str = "", page: int = 1, per_page: int = 100
) -> Dict[str, Any]:
    """List Qonto mandates, optionally restricted to a client."""
    params: Dict[str, Any] = {"page": page, "per_page": per_page}
    if client_id:
        params["client_id"] = client_id
    return _qonto_request("GET", "/v2/sepa/direct_debit_mandates", params=params)


def _qonto_direct_debit_mandate_items(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("direct_debit_mandates", "mandates", "items"):
        if isinstance(response.get(key), list):
            return [item for item in response[key] if isinstance(item, dict)]
    return []


def _qonto_mandate_rum(mandate: Dict[str, Any]) -> str:
    """Return the RUM exposed by the different Qonto API response versions."""
    for key in ("rum", "unique_mandate_reference", "mandate_reference", "reference"):
        value = mandate.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def find_qonto_direct_debit_mandate_by_rum(rum: str) -> Optional[Dict[str, Any]]:
    """Walk every Qonto result page and find a mandate by its exact RUM."""
    page, per_page = 1, 100
    while True:
        response = list_qonto_direct_debit_mandates(page=page, per_page=per_page)
        items = _qonto_direct_debit_mandate_items(response)
        match = next((mandate for mandate in items if _qonto_mandate_rum(mandate) == rum), None)
        if match is not None:
            return match

        meta = response.get("meta") if isinstance(response.get("meta"), dict) else {}
        next_page = meta.get("next_page") or meta.get("nextPage")
        total_pages = meta.get("total_pages") or meta.get("totalPages")
        if next_page:
            try:
                next_page_number = int(next_page)
            except (TypeError, ValueError):
                next_page_number = page + 1
        elif total_pages:
            try:
                next_page_number = page + 1 if page < int(total_pages) else 0
            except (TypeError, ValueError):
                next_page_number = 0
        else:
            next_page_number = page + 1 if len(items) >= per_page else 0
        if not next_page_number or next_page_number <= page:
            return None
        page = next_page_number


def get_qonto_direct_debit_mandate(mandate_id: str) -> Dict[str, Any]:
    """Fetch one mandate by its Qonto identifier."""
    return _qonto_request("GET", f"/v2/sepa/direct_debit_mandates/{quote(str(mandate_id), safe='')}")


def _qonto_direct_debit_mandate_payload(response: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    mandate = response.get("direct_debit_mandate") or response.get("mandate") or response
    return mandate if isinstance(mandate, dict) else {}


def _qonto_identifier_is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value or "").strip())
        return True
    except (TypeError, ValueError, AttributeError):
        return False


def _all_qonto_direct_debit_mandates_for_client(client_id: str) -> List[Dict[str, Any]]:
    """Return every mandate for one exact Qonto client, across all pages."""
    if not str(client_id or "").strip():
        return []
    mandates: List[Dict[str, Any]] = []
    page, per_page = 1, 100
    while True:
        response = list_qonto_direct_debit_mandates(str(client_id), page=page, per_page=per_page)
        items = _qonto_direct_debit_mandate_items(response)
        mandates.extend(items)
        meta = response.get("meta") if isinstance(response.get("meta"), dict) else {}
        next_page = meta.get("next_page") or meta.get("nextPage")
        total_pages = meta.get("total_pages") or meta.get("totalPages")
        if next_page:
            try:
                next_number = int(next_page)
            except (TypeError, ValueError):
                next_number = page + 1
        elif total_pages:
            try:
                next_number = page + 1 if page < int(total_pages) else 0
            except (TypeError, ValueError):
                next_number = 0
        else:
            next_number = page + 1 if len(items) >= per_page else 0
        if not next_number or next_number <= page:
            return mandates
        page = next_number


def _resolve_qonto_direct_debit_mandate_for_line(line: Dict[str, Any]) -> Dict[str, Any]:
    """Repair a legacy mandate link before reconciling its subscriptions.

    Older billing rows could persist the human-readable RUM in the technical
    mandate-id field.  Qonto subscriptions contain the UUID, so the comparison
    then returned zero matches while the UI continued to show "Mandat OK".
    Resolve the mandate only through the line's exact Qonto client or exact RUM
    and persist the UUID back onto the row.
    """
    stored_id = str(line.get("qonto_direct_debit_mandate_id") or "").strip()
    stored_rum = str(line.get("qonto_mandate_rum") or "").strip()
    client_id = str(
        line.get("qontoClientId") or line.get("qontoCustomerId")
        or line.get("qonto_mandate_client_id") or ""
    ).strip()
    rum_candidates = {value for value in (stored_rum, stored_id) if value and not _qonto_identifier_is_uuid(value)}
    mandate: Dict[str, Any] = {}

    if client_id:
        mandates = _all_qonto_direct_debit_mandates_for_client(client_id)
        mandate = next(
            (item for item in mandates if stored_id and str(item.get("id") or "") == stored_id),
            {},
        )
        if not mandate and rum_candidates:
            mandate = next(
                (item for item in mandates if _qonto_mandate_rum(item) in rum_candidates),
                {},
            )
        if not mandate:
            usable = [
                item for item in mandates
                if _map_mandate_status(item.get("status")) in {"pending", "active", "signed"}
            ]
            # A single mandate for this exact Qonto client is unambiguous.  Do
            # not guess when the client has several mandates.
            if len(usable) == 1:
                mandate = usable[0]

    if not mandate and stored_id and _qonto_identifier_is_uuid(stored_id):
        try:
            mandate = _qonto_direct_debit_mandate_payload(get_qonto_direct_debit_mandate(stored_id))
        except QontoNotFoundError:
            mandate = {}
    if not mandate and rum_candidates:
        for rum in rum_candidates:
            mandate = find_qonto_direct_debit_mandate_by_rum(rum) or {}
            if mandate:
                break
    if not mandate or not str(mandate.get("id") or "").strip():
        return {}

    resolved_id = str(mandate.get("id"))
    resolved_rum = _qonto_mandate_rum(mandate) or stored_rum
    previous_id = stored_id
    line["qonto_direct_debit_mandate_id"] = resolved_id
    if resolved_rum:
        line["qonto_mandate_rum"] = resolved_rum
    if mandate.get("client_id"):
        line["qonto_mandate_client_id"] = str(mandate.get("client_id"))
        line["qontoClientId"] = line.get("qontoClientId") or str(mandate.get("client_id"))
        line["qontoCustomerId"] = line.get("qontoCustomerId") or str(mandate.get("client_id"))
    status = _map_mandate_status(mandate.get("status"))
    line["qonto_mandate_status"] = status
    line["mandateStatus"] = status
    if previous_id and previous_id != resolved_id:
        _billing_log(
            line, "Identifiant technique du mandat Qonto rÃ©parÃ©", "success",
            f"{previous_id} -> {resolved_id}", resolved_id,
        )
    return mandate

def create_qonto_direct_debit_mandate(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _qonto_request("POST", "/v2/sepa/direct_debit_mandates", {"direct_debit_mandate": payload})

def create_qonto_direct_debit_subscription(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _qonto_request("POST", "/v2/sepa/direct_debit_subscriptions", {"direct_debit_subscription": payload})


def get_qonto_direct_debit_subscription(subscription_id: str) -> Dict[str, Any]:
    """Fetch one subscription, including historical completed/canceled rows."""
    return _qonto_request(
        "GET",
        f"/v2/sepa/direct_debit_subscriptions/{quote(str(subscription_id), safe='')}",
    )

def list_qonto_direct_debit_subscriptions(
    mandate_id: str = "", page: int = 1, per_page: int = 100
) -> Dict[str, Any]:
    """List subscriptions; callers restrict them to ``mandate_id`` locally.

    Qonto's list endpoint does not accept ``direct_debit_mandate_id`` as a
    query parameter.  Sending that unsupported filter can reject the entire
    reconciliation request, leaving the old local schedule unchanged.
    """
    params: Dict[str, Any] = {"page": page, "per_page": per_page}
    return _qonto_request("GET", "/v2/sepa/direct_debit_subscriptions", params=params)

def _qonto_direct_debit_subscription_items(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("direct_debit_subscriptions", "subscriptions", "items"):
        if isinstance(response.get(key), list):
            return [item for item in response[key] if isinstance(item, dict)]
    return []


def _qonto_direct_debit_subscription_payload(response: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    subscription = response.get("direct_debit_subscription") or response.get("subscription") or response
    return subscription if isinstance(subscription, dict) else {}


def _qonto_subscription_mandate_id(subscription: Dict[str, Any]) -> str:
    """Return a subscription mandate UUID without accepting an implicit match."""
    nested = subscription.get("direct_debit_mandate")
    nested_id = nested.get("id") if isinstance(nested, dict) else ""
    return str(
        subscription.get("direct_debit_mandate_id")
        or subscription.get("mandate_id") or nested_id or ""
    ).strip()

def list_qonto_direct_debit_collections(
    subscription_id: str = "", page: int = 1, per_page: int = 100,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"page": page, "per_page": per_page}
    if subscription_id:
        params["direct_debit_subscription_id"] = subscription_id
    return _qonto_request("GET", "/v2/sepa/direct_debit_collections", params=params)

def _qonto_collection_items(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("direct_debit_collections", "collections", "items"):
        if isinstance(response.get(key), list):
            return response.get(key)
    return []


def _qonto_collection_date(collection: Dict[str, Any]) -> str:
    return str(
        collection.get("collection_date") or collection.get("scheduled_at")
        or collection.get("due_date") or collection.get("date")
        or collection.get("completed_at") or collection.get("paid_at") or ""
    )[:10]


def _qonto_collection_amount_cents(collection: Dict[str, Any]) -> int:
    amount = collection.get("amount")
    if isinstance(amount, dict):
        amount = amount.get("value") if amount.get("value") is not None else amount.get("amount")
    return money_value_to_cents(amount or 0)


def _all_qonto_direct_debit_collections_for_rum(rum: str) -> List[Dict[str, Any]]:
    """List collections for one exact RUM when local subscription ids are stale."""
    rum = str(rum or "").strip()
    if not rum:
        return []
    collections: List[Dict[str, Any]] = []
    page, per_page = 1, 100
    while True:
        response = list_qonto_direct_debit_collections(page=page, per_page=per_page)
        items = _qonto_collection_items(response)
        collections.extend(
            item for item in items
            if str(
                item.get("unique_mandate_reference") or item.get("rum")
                or item.get("mandate_reference") or ""
            ).strip() == rum
        )
        meta = response.get("meta") if isinstance(response.get("meta"), dict) else {}
        next_page = meta.get("next_page") or meta.get("nextPage")
        total_pages = meta.get("total_pages") or meta.get("totalPages")
        if next_page:
            try:
                next_number = int(next_page)
            except (TypeError, ValueError):
                next_number = page + 1
        elif total_pages:
            try:
                next_number = page + 1 if page < int(total_pages) else 0
            except (TypeError, ValueError):
                next_number = 0
        else:
            next_number = page + 1 if len(items) >= per_page else 0
        if not next_number or next_number <= page:
            return collections
        page = next_number

def _qonto_webhook_secret() -> str:
    return _qonto_secret(os.environ.get("QONTO_WEBHOOK_SECRET") or "")


def _require_qonto_webhook_secret() -> str:
    secret = _qonto_webhook_secret()
    if not secret:
        raise QontoConfigurationError("QONTO_WEBHOOK_SECRET est requis avant dâ€™activer le webhook Qonto.")
    if not 32 <= len(secret) <= 128:
        raise QontoConfigurationError("QONTO_WEBHOOK_SECRET doit comporter entre 32 et 128 caractÃ¨res.")
    return secret


def money_value_to_cents(value: Any) -> int:
    if isinstance(value, dict):
        value = value.get("value") if value.get("value") is not None else value.get("amount")
    if value is None or value == "":
        return 0
    try:
        decimal_value = Decimal(str(value).replace(",", ".").strip())
        if not decimal_value.is_finite():
            raise ValueError("Montant non fini")
        return int(
            (decimal_value * Decimal("100")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    except (InvalidOperation, OverflowError, TypeError, ValueError) as exc:
        raise ValueError("Montant Qonto invalide") from exc


def cents_to_money(cents: Any) -> float:
    try:
        return float((Decimal(int(cents or 0)) / Decimal("100")).quantize(Decimal("0.01")))
    except Exception:
        return 0.0



def _cents_first_non_null(*values: Any) -> int:
    for value in values:
        if value is None or value == "":
            continue
        if isinstance(value, dict):
            value = value.get("value") if value.get("value") is not None else value.get("amount")
        try:
            return int(Decimal(str(value).replace(",", ".").strip()).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Montant Qonto invalide") from exc
    return 0


def _validate_qonto_paid_cents(total_amount_cents: int, paid_amount_cents: int, invoice_reference: str = "") -> Tuple[int, bool]:
    """Reject impossible Qonto paid amounts instead of treating them as cash.

    A client invoice cannot have more money paid than its own total.  When a
    stale amount from another invoice survives locally, counting it would mark
    the trainee as overpaid and would also be added to any cash installments.
    Treat that value as unverified until the invoice is synchronized again.
    """
    total_cents = max(int(total_amount_cents or 0), 0)
    paid_cents = int(paid_amount_cents or 0)
    is_consistent = paid_cents >= 0 and not (total_cents > 0 and paid_cents > total_cents)
    if is_consistent:
        return paid_cents, True
    app.logger.warning(
        "QONTO_PAYMENT_AMOUNT_IGNORED invoice=%s total_amount_cents=%s paid_amount_cents=%s",
        invoice_reference or "unknown",
        total_cents,
        paid_cents,
    )
    return 0, False


def serialize_qonto_invoice_for_frontend(invoice: Dict[str, Any]) -> Dict[str, Any]:
    """Return the single canonical Qonto invoice shape sent to the frontend."""
    total_amount_cents = _cents_first_non_null(
        invoice.get("qonto_total_amount_cents"),
        invoice.get("total_amount_cents"),
        invoice.get("qontoTotalAmountCents"),
        invoice.get("totalAmountCents"),
        money_value_to_cents(invoice.get("amountTTC") or invoice.get("amount") or 0) if invoice.get("amountTTC") is not None or invoice.get("amount") is not None else None,
    )
    raw_paid_amount_cents = _cents_first_non_null(
        invoice.get("qonto_amount_paid_cents"),
        invoice.get("paid_amount_cents"),
        invoice.get("qontoAmountPaidCents"),
        invoice.get("paidAmountCents"),
    )
    # A SEPA collection may have been completed before the client invoice was
    # created. In that case Qonto legitimately returns ``amount_paid = 0`` on
    # the new invoice even though money has already been collected for this
    # billing line. Reconcile the invoice snapshot with the collection
    # history before exposing it to the finance widget.
    raw_paid_amount_cents = _reconciled_qonto_paid_cents(invoice, raw_paid_amount_cents)
    paid_amount_cents, _ = _validate_qonto_paid_cents(
        total_amount_cents,
        raw_paid_amount_cents,
        str(invoice.get("qontoInvoiceNumber") or invoice.get("invoice_number") or invoice.get("invoiceNumber") or invoice.get("number") or ""),
    )
    remaining_amount_cents = max(total_amount_cents - paid_amount_cents, 0)
    payment_percentage = 0 if total_amount_cents == 0 else float(min((Decimal(paid_amount_cents) / Decimal(total_amount_cents) * Decimal('100')), Decimal('100')).quantize(Decimal('0.01')))
    raw_payment_status = invoice.get("qonto_payment_status") or invoice.get("payment_status") or invoice.get("qontoPaymentStatus") or invoice.get("paymentStatus")
    if total_amount_cents > 0 and paid_amount_cents >= total_amount_cents:
        payment_status = "paid"
    elif paid_amount_cents > 0:
        payment_status = "partially_paid"
    else:
        payment_status = str(raw_payment_status or "unpaid").lower()
        if payment_status not in {"draft", "canceled", "cancelled"}:
            payment_status = "unpaid"
    out = {
        "invoice_number": invoice.get("qontoInvoiceNumber") or invoice.get("invoice_number") or invoice.get("invoiceNumber") or invoice.get("number") or "",
        "total_amount_cents": total_amount_cents,
        "paid_amount_cents": paid_amount_cents,
        "remaining_amount_cents": remaining_amount_cents,
        "payment_percentage": payment_percentage,
        "payment_status": payment_status,
        "qonto_status": invoice.get("qonto_status") or invoice.get("qontoStatus") or invoice.get("invoiceStatus") or "",
        "last_synced_at": invoice.get("qontoLastSyncedAt") or invoice.get("qonto_last_synced_at") or invoice.get("updatedAt") or "",
    }
    if invoice.get("qontoInvoiceId") or invoice.get("qontoDraftId"):
        out["invoice_id"] = invoice.get("qontoInvoiceId") or invoice.get("qontoDraftId")
    app.logger.info(
        "QONTO_INVOICE_FRONTEND_SERIALIZED invoice_number=%s payment_status=%s qonto_amount_paid_cents=%s paid_amount_cents=%s qonto_total_amount_cents=%s total_amount_cents=%s qonto_remaining_amount_cents=%s remaining_amount_cents=%s",
        out["invoice_number"], out["payment_status"], invoice.get("qonto_amount_paid_cents"), out["paid_amount_cents"], invoice.get("qonto_total_amount_cents"), out["total_amount_cents"], invoice.get("qonto_remaining_amount_cents"), out["remaining_amount_cents"]
    )
    return out


def _reconciled_qonto_paid_cents(invoice: Dict[str, Any], fallback_cents: int) -> int:
    """Return the net amount actually kept for a SEPA invoice.

    Qonto's client-invoice ``amount_paid`` is cumulative and can keep counting a
    direct debit after the bank has returned it.  Collection statuses are the
    source of truth for SEPA: only completed, non-returned collections are cash
    that is still held.  We deliberately retain the invoice value until at
    least one collection has reached a terminal state so pending legacy plans
    do not erase a valid non-SEPA payment.
    """
    all_installments = _sepa_installments(invoice)
    # Historical mandate-only lines did not always persist ``paymentMode``.
    # The presence of a real SEPA schedule is sufficient proof that these are
    # direct-debit collections and prevents a later-created invoice from
    # hiding them.
    if not all_installments:
        return fallback_cents
    terminal = {"completed", "paid", "succeeded", "success", "failed", "returned", "rejected", "refunded"}
    if not any(str(item.get("status") or "").lower() in terminal for item in all_installments):
        return fallback_cents
    # Keep rejected/reprogrammed history for the authority decision above, but
    # count only one current attempt per contractual installment below.
    installments = _effective_sepa_installments(invoice)
    paid = sum(
        money_value_to_cents(item.get("amount") or 0)
        for item in installments
        if str(item.get("status") or "").lower() in {"completed", "paid", "succeeded", "success"}
    )
    return max(paid, 0)


def normalize_qonto_invoice_storage_fields(invoice: Dict[str, Any]) -> None:
    serialized = serialize_qonto_invoice_for_frontend(invoice)
    # ``control`` is a deliberate local safety state (for a missing or
    # unverifiable remote invoice), not a Qonto payment state.  Do not erase it
    # merely because the normalizer has no fresh remote payment amount.
    if invoice.get("invoiceStatus") == "control" or invoice.get("paymentStatus") == "control":
        serialized["payment_status"] = "control"
    invoice["qonto_total_amount_cents"] = serialized["total_amount_cents"]
    invoice["qonto_amount_paid_cents"] = serialized["paid_amount_cents"]
    invoice["qonto_remaining_amount_cents"] = serialized["remaining_amount_cents"]
    invoice["payment_percentage"] = serialized["payment_percentage"]
    invoice["qonto_payment_status"] = serialized["payment_status"]
    invoice["paymentStatus"] = serialized["payment_status"]

def _qonto_money_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("value") if value.get("value") is not None else value.get("amount")
    return value


def normalize_qonto_invoice_payment_data(client_invoice: Dict[str, Any], local_invoice: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not isinstance(client_invoice, dict):
        raise ValueError("RÃ©ponse Qonto invalide")
    local_invoice = local_invoice or {}
    total_source = _qonto_money_value(client_invoice.get("total_amount"))
    if total_source is None and client_invoice.get("total_amount_cents") is not None:
        total_cents = int(client_invoice.get("total_amount_cents") or 0)
    elif total_source is not None:
        total_cents = money_value_to_cents(total_source)
    elif local_invoice.get("qonto_total_amount_cents") is not None:
        total_cents = int(local_invoice.get("qonto_total_amount_cents") or 0)
    elif local_invoice.get("qontoTotalAmountCents") is not None:
        total_cents = int(local_invoice.get("qontoTotalAmountCents") or 0)
    else:
        total_cents = money_value_to_cents(local_invoice.get("amountTTC") or local_invoice.get("amount_ttc") or local_invoice.get("amount") or 0)
    remote_paid_amount_is_explicit = any(
        client_invoice.get(key) not in (None, '')
        for key in (
            'amount_paid', 'paid_amount', 'amount_paid_cents', 'paid_amount_cents',
            'remaining_amount', 'amount_due', 'remaining_amount_cents',
        )
    )
    amount_paid = _qonto_money_value(client_invoice.get("amount_paid"))
    if amount_paid is None:
        amount_paid = _qonto_money_value(client_invoice.get("paid_amount"))
    remaining_amount = _qonto_money_value(client_invoice.get("remaining_amount"))
    if remaining_amount is None:
        remaining_amount = _qonto_money_value(client_invoice.get("amount_due"))
    if amount_paid is None and client_invoice.get("amount_paid_cents") is not None:
        amount_paid_cents = int(client_invoice.get("amount_paid_cents") or 0)
    elif amount_paid is None and client_invoice.get("paid_amount_cents") is not None:
        amount_paid_cents = int(client_invoice.get("paid_amount_cents") or 0)
    elif amount_paid is None and remaining_amount is not None:
        amount_paid_cents = max(total_cents - money_value_to_cents(remaining_amount), 0)
    elif amount_paid is None and client_invoice.get("remaining_amount_cents") is not None:
        amount_paid_cents = max(total_cents - int(client_invoice.get("remaining_amount_cents") or 0), 0)
    elif amount_paid is None and local_invoice.get("qonto_amount_paid_cents") is not None:
        amount_paid_cents = int(local_invoice.get("qonto_amount_paid_cents") or 0)
    elif amount_paid is None and local_invoice.get("qontoAmountPaidCents") is not None:
        amount_paid_cents = int(local_invoice.get("qontoAmountPaidCents") or 0)
    elif amount_paid is None and local_invoice.get("qontoInvoiceAmountPaid") is not None:
        amount_paid_cents = money_value_to_cents(local_invoice.get("qontoInvoiceAmountPaid") or 0)
    elif amount_paid is None and local_invoice.get("qonto_invoice_amount_paid") is not None:
        # Trainee-level invoices created by the historical WEDOF/Qonto flow use
        # snake_case fields.  Keep accepting that shape so an already-paid CPF
        # invoice does not reappear as unpaid in the admin trainee dashboard.
        amount_paid_cents = money_value_to_cents(local_invoice.get("qonto_invoice_amount_paid") or 0)
    else:
        amount_paid_cents = 0 if amount_paid is None else money_value_to_cents(amount_paid)
    qonto_status = (client_invoice.get("status") or local_invoice.get("qonto_status") or local_invoice.get("qontoStatus") or local_invoice.get("qonto_invoice_status") or "").strip() or "unpaid"
    if qonto_status == 'paid' and not remote_paid_amount_is_explicit and total_cents > 0:
        # Qonto's paid status is itself authoritative.  Some list/webhook
        # payloads omit amount_paid even though the full invoice is settled.
        amount_paid_cents = total_cents
    amount_paid_cents, paid_amount_is_consistent = _validate_qonto_paid_cents(
        total_cents,
        amount_paid_cents,
        str(client_invoice.get("number") or client_invoice.get("invoice_number") or local_invoice.get("qontoInvoiceNumber") or ""),
    )
    if not paid_amount_is_consistent:
        remaining_cents = total_cents
    elif remaining_amount is not None:
        remaining_cents = max(money_value_to_cents(remaining_amount), 0)
    elif client_invoice.get("remaining_amount_cents") is not None:
        remaining_cents = max(int(client_invoice.get("remaining_amount_cents") or 0), 0)
    else:
        remaining_cents = max(total_cents - amount_paid_cents, 0)
    if qonto_status == "canceled":
        payment_status = "canceled"
    elif qonto_status == "draft":
        payment_status = "draft"
    elif total_cents > 0 and amount_paid_cents >= total_cents:
        payment_status = "paid"
    elif amount_paid_cents > 0:
        payment_status = "partially_paid"
    else:
        payment_status = "unpaid"
    return {
        "qonto_status": qonto_status,
        "qonto_total_amount_cents": total_cents,
        "qonto_amount_paid_cents": amount_paid_cents,
        "qonto_remaining_amount_cents": remaining_cents,
        "qonto_payment_status": payment_status,
        "qonto_paid_at": client_invoice.get("paid_at"),
    }


def _normalize_qonto_amount(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("value") or value.get("amount") or 0
    return _money(value)


def _qonto_invoice_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    return data.get("client_invoice") if isinstance(data.get("client_invoice"), dict) else (data.get("invoice") if isinstance(data.get("invoice"), dict) else data)


def _apply_qonto_invoice_status(inv: Dict[str, Any], invoice: Dict[str, Any]) -> None:
    normalized = normalize_qonto_invoice_payment_data(invoice, inv)
    status = normalized["qonto_status"]
    paid_at = normalized.get("qonto_paid_at") or inv.get("qonto_invoice_paid_at") or ""
    if status:
        inv["qonto_invoice_status"] = status
    inv["qonto_invoice_paid_at"] = paid_at or ""
    inv["qonto_invoice_amount_paid"] = cents_to_money(normalized["qonto_amount_paid_cents"])
    inv.update(normalized)
    if invoice.get("id"):
        inv["qonto_invoice_id"] = invoice.get("id")
    if invoice.get("number") or invoice.get("invoice_number"):
        inv["qonto_invoice_number"] = invoice.get("number") or invoice.get("invoice_number") or ""
    if invoice.get("public_url") or invoice.get("url"):
        inv["qonto_invoice_url"] = invoice.get("public_url") or invoice.get("url") or inv.get("qonto_invoice_url")
    inv["qonto_invoice_synced_at"] = _now_iso()
    inv["qonto_last_synced_at"] = inv["qonto_invoice_synced_at"]
    inv["qonto_sync_error"] = None
    inv["last_error"] = ""


def _find_trainee_by_qonto_invoice_id(data: Dict[str, Any], invoice_id: str):
    needle = str(invoice_id or "").strip()
    if not needle:
        return None, None, None
    for sess in data.get("sessions", []):
        trainees = _session_trainees_list(sess)
        for trainee in trainees:
            inv = trainee.get("qonto_invoice") if isinstance(trainee.get("qonto_invoice"), dict) else {}
            if str(inv.get("qonto_invoice_id") or "").strip() == needle:
                return sess, trainees, trainee
    return None, None, None


def syncQontoInvoiceStatus(invoiceId: str) -> Optional[Dict[str, Any]]:
    data = load_data()
    sess, trainees, trainee = _find_trainee_by_qonto_invoice_id(data, invoiceId)
    if not trainee:
        return None
    remote = get_qonto_invoice(invoiceId)
    invoice = _qonto_invoice_payload(remote)
    inv = _qonto_invoice_state(trainee)
    _apply_qonto_invoice_status(inv, invoice)
    sess["trainees"] = trainees
    save_data(data)
    return inv

def _qonto_webhook_callback_url() -> str:
    # Keep a single stable public target.  Qonto must be configured with this
    # exact URL (the legacy /api/qonto/webhooks route remains an inbound alias).
    return os.environ.get("QONTO_WEBHOOK_CALLBACK_URL", "https://gestionstagiaires-r5no.onrender.com/api/webhooks/qonto").strip()


QONTO_WEBHOOK_EVENT_TYPES = [
    "v1/client-invoices",
    "v1/sepa-direct-debit-mandates",
    "v1/sepa-direct-debit-collections",
]


def ensure_qonto_webhook_subscription() -> Dict[str, Any]:
    """Create or repair the Qonto invoice and SEPA webhook subscription on demand.

    This function is intentionally not called at startup so Render restarts never
    create duplicate subscriptions.
    """
    callback_url = _qonto_webhook_callback_url()
    webhook_secret = _require_qonto_webhook_secret()
    configured_id = os.environ.get("QONTO_WEBHOOK_SUBSCRIPTION_ID", "").strip()
    subscriptions_payload = _qonto_request("GET", "/v2/webhook_subscriptions")
    subscriptions = subscriptions_payload.get("webhook_subscriptions") or subscriptions_payload.get("subscriptions") or []
    subscriptions = subscriptions if isinstance(subscriptions, list) else []
    configured = next((sub for sub in subscriptions if configured_id and str(sub.get("id")) == configured_id), None)
    canonical = next((sub for sub in subscriptions if (sub.get("url") or sub.get("callback_url") or sub.get("target_url")) == callback_url), None)
    reusable = canonical or configured or next(
        (sub for sub in subscriptions if set(QONTO_WEBHOOK_EVENT_TYPES).issubset({str(t) for t in (sub.get("event_types") or sub.get("types") or [])})),
        None,
    )
    if reusable:
        types = {str(t) for t in (reusable.get("event_types") or reusable.get("types") or [])}
        missing_events = [event for event in QONTO_WEBHOOK_EVENT_TYPES if event not in types]
        current_url = reusable.get("url") or reusable.get("callback_url") or reusable.get("target_url")
        if not missing_events and current_url == callback_url:
            data = load_data(); _store_qonto_webhook_subscription(data, reusable); save_data(data)
            return {"ok": True, "created": False, "updated": False, "subscription": reusable, "callback_url": callback_url}
        # Repair the existing subscription instead of creating a second one.
        subscription_id = str(reusable.get("id") or "").strip()
        if not subscription_id:
            raise RuntimeError("Souscription Qonto existante sans identifiant, mise Ã  jour impossible")
        payload = {
            "callback_url": callback_url,
            "types": list(dict.fromkeys([*(reusable.get("event_types") or reusable.get("types") or []), *QONTO_WEBHOOK_EVENT_TYPES])),
            "description": "Synchronisation Qonto - Gestion stagiaires",
        }
        updated = _qonto_request("PUT", f"/v2/webhook_subscriptions/{quote(subscription_id, safe='')}", payload)
        subscription = updated.get("webhook_subscription") or updated
        data = load_data(); _store_qonto_webhook_subscription(data, subscription); save_data(data)
        return {"ok": True, "created": False, "updated": True, "subscription": subscription, "callback_url": callback_url}
    payload = {
        "callback_url": callback_url,
        "types": list(QONTO_WEBHOOK_EVENT_TYPES),
        "secret": webhook_secret,
        "description": "Synchronisation Qonto - Gestion stagiaires",
    }
    created = _qonto_request("POST", "/v2/webhook_subscriptions", payload)
    subscription = created.get("webhook_subscription") or created
    data = load_data(); _store_qonto_webhook_subscription(data, subscription); save_data(data)
    return {"ok": True, "created": True, "updated": False, "subscription": subscription, "callback_url": callback_url}


QONTO_WEBHOOK_HISTORY_LIMIT = 50


def _qonto_webhook_resource_id(item: Dict[str, Any]) -> str:
    return str(item.get("id") or item.get("qonto_invoice_id") or item.get("direct_debit_mandate_id") or item.get("direct_debit_collection_id") or "")


def _record_qonto_webhook(data: Dict[str, Any], event: str, item: Dict[str, Any], result: str, error: str = "") -> None:
    """Persist a small, secret-free delivery history for the admin diagnostics."""
    entries = data.setdefault("qonto_webhook_history", [])
    if not isinstance(entries, list):
        entries = []
        data["qonto_webhook_history"] = entries
    entries.insert(0, {"received_at": _now_iso(), "event": str(event or "unknown"), "resource_id": _qonto_webhook_resource_id(item), "result": result, "error": _sanitize_qonto_error(error)[:500] if error else ""})
    del entries[QONTO_WEBHOOK_HISTORY_LIMIT:]


def _store_qonto_webhook_subscription(data: Dict[str, Any], subscription: Dict[str, Any]) -> None:
    """Keep a non-sensitive local snapshot for status polling."""
    if not isinstance(subscription, dict):
        return
    data["qonto_webhook_subscription"] = {
        "id": str(subscription.get("id") or ""),
        "event_types": [str(value) for value in (subscription.get("event_types") or subscription.get("types") or [])],
        "callback_url": str(subscription.get("url") or subscription.get("callback_url") or subscription.get("target_url") or ""),
        "updated_at": _now_iso(),
    }


def qonto_webhook_status() -> Dict[str, Any]:
    """Return the locally persisted webhook state; never contacts Qonto."""
    data = load_data()
    history = data.get("qonto_webhook_history") if isinstance(data.get("qonto_webhook_history"), list) else []
    snapshot = data.get("qonto_webhook_subscription") if isinstance(data.get("qonto_webhook_subscription"), dict) else {}
    last = history[0] if history else {}
    subscribed_events = [str(value) for value in snapshot.get("event_types", [])]
    missing_events = [event for event in QONTO_WEBHOOK_EVENT_TYPES if event not in subscribed_events]
    connection_api_key_ok = bool(_qonto_is_configured())
    oauth_ok = _qonto_oauth_connected(data)
    webhook_scope_ok = oauth_ok and _qonto_oauth_has_scope("webhook", data)
    return {
        # Explicit public names used by the polling client.
        "connection_api_key_ok": connection_api_key_ok,
        "oauth_ok": oauth_ok,
        "webhook_scope_ok": webhook_scope_ok,
        "webhook_secret_configured": bool(_qonto_webhook_secret()),
        "subscription_found": bool(snapshot.get("id")),
        "subscription_id": str(snapshot.get("id") or ""),
        "subscribed_events": subscribed_events,
        "missing_events": missing_events,
        "last_webhook_received_at": last.get("received_at") or "",
        "last_event_type": last.get("event") or "",
        "last_processing_result": last.get("result") or "",
        "last_error": last.get("error") or "",
        "callback_url": snapshot.get("callback_url") or _qonto_webhook_callback_url(),
        # Compatibility names for the existing settings view.
        "configuration_present": connection_api_key_ok, "api_connected": connection_api_key_ok,
        "oauth_connected": oauth_ok, "webhook_scope_authorized": webhook_scope_ok,
        "event_types": subscribed_events, "last_received_at": last.get("received_at") or "",
        "last_event": last.get("event") or "", "last_result": last.get("result") or "",
    }


def _verify_qonto_webhook_signature(raw_body: bytes) -> bool:
    secret = _qonto_webhook_secret()
    if not secret:
        return False
    signatures = []
    for header in QONTO_WEBHOOK_SIGNATURE_HEADERS:
        value = (request.headers.get(header) or "").strip()
        if value:
            signatures.append(value)
    if not signatures:
        return False
    candidates = set()
    now = int(time.time())
    for sig in signatures:
        match = re.search(r"(?:^|,)t=(\d+),v1=([0-9a-fA-F]+)", sig)
        if match:
            timestamp = int(match.group(1))
            if abs(now - timestamp) > 300:
                continue
            signed = f"{timestamp}.".encode("utf-8") + raw_body
            candidates.add(hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest())
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    candidates.update({digest, f"sha256={digest}"})
    provided = []
    for sig in signatures:
        clean = sig.strip().strip('"').strip("'")
        provided.append(clean)
        match = re.search(r"(?:^|,)t=\d+,v1=([0-9a-fA-F]+)", clean)
        if match:
            provided.append(match.group(1))
    return any(hmac.compare_digest(sig, candidate) for sig in provided for candidate in candidates)


def mark_qonto_invoice_as_paid(invoice_id: str):
    return syncQontoInvoiceStatus(invoice_id)


def build_qonto_phone(raw_phone):
    raw = (raw_phone or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())

    if not digits:
        return None

    # France : 06 65 24 52 71 => +33 / 665245271
    if digits.startswith("0") and len(digits) == 10:
        return {
            "country_code": "+33",
            "number": digits[1:],
        }

    if digits.startswith("33") and len(digits) >= 11:
        return {
            "country_code": "+33",
            "number": digits[2:],
        }

    return None


_ypareo_access_token_cache: Dict[str, Any] = {
    "token": "",
    "expires_at": 0.0,
    "configuration_key": "",
}
_ypareo_access_token_lock = threading.Lock()


class YpareoAuthenticationError(RuntimeError):
    """Raised when the initial YPAREO token cannot produce an access token."""


def _normalize_render_secret(value: str) -> str:
    """Normalize a secret pasted in Render without exposing it in logs."""
    secret = (value or "").strip()
    for _ in range(2):
        if len(secret) >= 2 and secret[0] == secret[-1] and secret[0] in {"'", '"'}:
            secret = secret[1:-1].strip()
            continue
        break
    return "".join(secret.splitlines()).strip()


def _ypareo_auth_token() -> str:
    return _normalize_render_secret(os.environ.get("YPAREO_AUTH_TOKEN") or "")


def _ypareo_base_url() -> str:
    return (os.environ.get("YPAREO_API_URL") or YPAREO_API_URL_DEFAULT).strip().rstrip("/")


def _ypareo_endpoint(environment_name: str, default: str) -> str:
    endpoint = (os.environ.get(environment_name) or default).strip()
    return endpoint if endpoint.startswith("/") else f"/{endpoint}"


def ypareo_headers(access_token: str) -> Dict[str, str]:
    """Build headers for an authenticated API request."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _ypareo_response_structure(value: Any) -> Any:
    """Describe a response shape without logging any response values."""
    if isinstance(value, dict):
        return {str(key): _ypareo_response_structure(item) for key, item in value.items()}
    if isinstance(value, list):
        return ["<items>"] if value else []
    if value is None:
        return "<null>"
    return f"<{type(value).__name__}>"


def _extract_ypareo_access_token(response_data: Any) -> str:
    if not isinstance(response_data, dict):
        return ""
    candidates = [response_data.get("token"), response_data.get("access_token")]
    nested_data = response_data.get("data")
    if isinstance(nested_data, dict):
        candidates.extend([nested_data.get("token"), nested_data.get("access_token")])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _ypareo_access_token_ttl(response_data: Any) -> float:
    """Read a supplied lifetime when available, otherwise cache for 30 minutes."""
    containers = [response_data]
    if isinstance(response_data, dict) and isinstance(response_data.get("data"), dict):
        containers.append(response_data["data"])

    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in ("expires_in", "expiresIn"):
            try:
                lifetime = float(container.get(key))
            except (TypeError, ValueError):
                continue
            if lifetime > 0:
                return lifetime
        for key in ("expires_at", "expiresAt"):
            value = container.get(key)
            try:
                expires_at = float(value)
            except (TypeError, ValueError):
                if not isinstance(value, str):
                    continue
                try:
                    expires_at = datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
            lifetime = expires_at - time.time()
            if lifetime > 0:
                return lifetime

    return YPAREO_ACCESS_TOKEN_DEFAULT_TTL_SECONDS


def _clear_ypareo_access_token_cache() -> None:
    with _ypareo_access_token_lock:
        _ypareo_access_token_cache.update(token="", expires_at=0.0, configuration_key="")


def get_ypareo_access_token() -> str:
    """Exchange the initial YPAREO token for a cached API access token."""
    initial_token = _ypareo_auth_token()
    if not initial_token:
        app.logger.error("[YPAREO] YPAREO_AUTH_TOKEN non configurÃ©")
        raise YpareoAuthenticationError(YPAREO_AUTH_ERROR_MESSAGE)

    auth_url = f"{_ypareo_base_url()}{_ypareo_endpoint('YPAREO_AUTH_ENDPOINT', YPAREO_AUTH_ENDPOINT)}"
    configuration_key = hashlib.sha256(f"{auth_url}\0{initial_token}".encode("utf-8")).hexdigest()

    with _ypareo_access_token_lock:
        now = time.monotonic()
        if (
            _ypareo_access_token_cache["token"]
            and _ypareo_access_token_cache["configuration_key"] == configuration_key
            and now < _ypareo_access_token_cache["expires_at"]
        ):
            return str(_ypareo_access_token_cache["token"])

        try:
            response = requests.post(
                auth_url,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json={"token": initial_token},
                timeout=YPAREO_REQUEST_TIMEOUT_SECONDS,
            )
            if not response.ok:
                app.logger.warning(
                    "[YPAREO] authentification refusÃ©e url=%s status=%s",
                    auth_url,
                    response.status_code,
                )
                raise YpareoAuthenticationError(YPAREO_AUTH_ERROR_MESSAGE)
            try:
                response_data = response.json()
            except (ValueError, requests.JSONDecodeError) as exc:
                app.logger.error("[YPAREO] rÃ©ponse d'authentification invalide (JSON attendu)")
                raise YpareoAuthenticationError(YPAREO_AUTH_ERROR_MESSAGE) from exc

            access_token = _extract_ypareo_access_token(response_data)
            if not access_token:
                app.logger.error(
                    "[YPAREO] rÃ©ponse d'authentification sans token structure=%s",
                    json.dumps(_ypareo_response_structure(response_data), ensure_ascii=False),
                )
                raise YpareoAuthenticationError(YPAREO_AUTH_ERROR_MESSAGE)

            ttl = _ypareo_access_token_ttl(response_data)
            _ypareo_access_token_cache.update(
                token=access_token,
                expires_at=time.monotonic() + ttl,
                configuration_key=configuration_key,
            )
            return access_token
        except YpareoAuthenticationError:
            raise
        except requests.RequestException as exc:
            app.logger.error("[YPAREO] appel d'authentification impossible erreur=%s", type(exc).__name__)
            raise YpareoAuthenticationError(YPAREO_AUTH_ERROR_MESSAGE) from exc


def nettoyer_payload(data: Any) -> Any:
    """Recursively remove values that must not be sent to YPAREO."""
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            cleaned_value = nettoyer_payload(value)
            if cleaned_value is None or cleaned_value == "" or cleaned_value == {} or cleaned_value == []:
                continue
            cleaned[key] = cleaned_value
        return cleaned
    if isinstance(data, (list, tuple)):
        cleaned = []
        for value in data:
            cleaned_value = nettoyer_payload(value)
            if cleaned_value is None or cleaned_value == "" or cleaned_value == {} or cleaned_value == []:
                continue
            cleaned.append(cleaned_value)
        return cleaned
    if isinstance(data, str):
        return data.strip()
    return data


def _ypareo_existing_value(stagiaire: Dict[str, Any], *keys: str) -> Any:
    """Return the first non-empty value already present under one of ``keys``."""
    for key in keys:
        if key not in stagiaire:
            continue
        value = stagiaire.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value.strip() if isinstance(value, str) else value
    return None


def _normaliser_telephone_ypareo(value: Any) -> str:
    """Return the 10-digit French national number expected by YPAREO."""
    if value is None:
        return ""

    telephone = re.sub(r"[\s.\-()]", "", str(value))
    if telephone.startswith("+33"):
        telephone = telephone[3:]
    elif telephone.startswith("0033"):
        telephone = telephone[4:]

    telephone = re.sub(r"\D", "", telephone)
    if len(telephone) == 9 and not telephone.startswith("0"):
        telephone = f"0{telephone}"

    return telephone if re.fullmatch(r"0[1-9]\d{8}", telephone) else ""


def construire_payload_apprenant(stagiaire: Dict[str, Any]) -> Dict[str, Any]:
    """Map only locally available trainee data to the YPAREO learner schema."""
    nom = _ypareo_existing_value(stagiaire, "nom", "last_name")
    prenom = _ypareo_existing_value(stagiaire, "prenom", "first_name")
    email = _ypareo_existing_value(stagiaire, "email")
    telephone = _normaliser_telephone_ypareo(
        _ypareo_existing_value(stagiaire, "telephone", "phone")
    )

    adresse_source = stagiaire.get("adresse")
    adresse_ligne1 = None
    adresse_ligne2 = None
    adresse_ligne3 = None
    adresse_ligne4 = None
    adresse_code_postal = None
    adresse_ville = None
    if isinstance(adresse_source, dict):
        adresse_ligne1 = _ypareo_existing_value(adresse_source, "ligne1")
        adresse_ligne2 = _ypareo_existing_value(adresse_source, "ligne2")
        adresse_ligne3 = _ypareo_existing_value(adresse_source, "ligne3")
        adresse_ligne4 = _ypareo_existing_value(adresse_source, "ligne4")
        adresse_code_postal = _ypareo_existing_value(adresse_source, "codePostal", "code_postal")
        adresse_ville = _ypareo_existing_value(adresse_source, "ville")
    else:
        adresse_ligne1 = _ypareo_existing_value(stagiaire, "adresse", "address")

    adresse_ligne1 = adresse_ligne1 or _ypareo_existing_value(stagiaire, "address")
    adresse_ligne2 = adresse_ligne2 or _ypareo_existing_value(stagiaire, "address_line2", "adresse_ligne2")
    adresse_ligne3 = adresse_ligne3 or _ypareo_existing_value(stagiaire, "address_line3", "adresse_ligne3")
    adresse_ligne4 = adresse_ligne4 or _ypareo_existing_value(stagiaire, "address_line4", "adresse_ligne4")
    adresse_code_postal = adresse_code_postal or _ypareo_existing_value(stagiaire, "code_postal", "zip_code")
    adresse_ville = adresse_ville or _ypareo_existing_value(stagiaire, "ville", "city")

    adresse = nettoyer_payload({
        "ligne1": adresse_ligne1,
        "ligne2": adresse_ligne2,
        "ligne3": adresse_ligne3,
        "ligne4": adresse_ligne4,
        "codePostal": adresse_code_postal,
        "ville": adresse_ville,
    })
    if adresse:
        adresse["paysAlpha"] = "FR"

    payload = {
        "adresse": adresse,
        "dateNaissance": _ypareo_existing_value(stagiaire, "date_naissance", "birth_date"),
        "emails": [{"adresse": email, "isDefault": True}] if email else [],
        "nom": nom,
        "nomNaissance": _ypareo_existing_value(stagiaire, "nom_naissance", "birth_name") or nom,
        "prenom": prenom,
        "telephones": [{
            "indicatif": "+33",
            "isDefaultAppel": True,
            "isDefaultSms": True,
            "numero": telephone,
        }] if telephone else [],
        "villeNaissance": _ypareo_existing_value(stagiaire, "ville_naissance", "birth_city"),
        "codePostalNaissance": _ypareo_existing_value(stagiaire, "code_postal_naissance", "birth_zip_code"),
        "departementNaissance": _ypareo_existing_value(stagiaire, "departement_naissance", "birth_department"),
        "inseeCommuneNaissance": _ypareo_existing_value(stagiaire, "insee_commune_naissance"),
        "numeroFranceTravail": _ypareo_existing_value(stagiaire, "numero_france_travail"),
        "numeroINE": _ypareo_existing_value(stagiaire, "numero_ine"),
        "idCivilite": _ypareo_existing_value(stagiaire, "id_civilite"),
        "idNationalite": _ypareo_existing_value(stagiaire, "id_nationalite"),
        "isRqth": _ypareo_existing_value(stagiaire, "is_rqth"),
    }
    return nettoyer_payload(payload)


def _normaliser_formation_ypareo(value: Any) -> str:
    """Normalize a local training label for tolerant YPAREO UUID matching."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.upper().replace("â€™", "'")
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def _ypareo_formation_environment_name(session_obj: Dict[str, Any]) -> Optional[str]:
    """Resolve the Render variable associated with the session's local training name."""
    candidates = [
        _session_get(session_obj, "training_type", ""),
        _session_get(session_obj, "formation", ""),
        _session_get(session_obj, "title", ""),
        _session_get(session_obj, "nom", ""),
        _session_get(session_obj, "name", ""),
    ]
    normalized_candidates = [_normaliser_formation_ypareo(value) for value in candidates if value]

    for formation in normalized_candidates:
        if any(marker in formation for marker in ("DIRIGEANT", "DSSP", "DO ESP", "DOESP")):
            return "YPAREO_ID_FORMATION_DSSP"
        if "BTS NDRC" in formation:
            return "YPAREO_ID_FORMATION_BTS_NDRC"
        if "BTS MOS" in formation:
            return "YPAREO_ID_FORMATION_BTS_MOS"
        if "BTS MCO" in formation:
            return "YPAREO_ID_FORMATION_BTS_MCO"
        if "BTS PI" in formation:
            return "YPAREO_ID_FORMATION_BTS_PI"
        if "BTS CI" in formation:
            return "YPAREO_ID_FORMATION_BTS_CI"
        if "SSIAP 1" in formation or "SSIAP1" in formation or formation == "SSIAP":
            return "YPAREO_ID_FORMATION_SSIAP1"
        if re.search(r"(^| )A3P($| )", formation):
            return "YPAREO_ID_FORMATION_A3P"
        if re.search(r"(^| )APS($| )", formation):
            return "YPAREO_ID_FORMATION_APS"
        if re.search(r"(^| )VTC($| )", formation):
            return "YPAREO_ID_FORMATION_VTC"
    return None


def id_formation_ypareo(session_obj: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Return the configured YPAREO formation UUID and a precise mapping error."""
    environment_name = _ypareo_formation_environment_name(session_obj)
    if not environment_name:
        return None, YPAREO_FORMATION_NOT_LINKED_ERROR

    formation_id = _normalize_render_secret(os.environ.get(environment_name) or "")
    if formation_id:
        return formation_id, None
    if environment_name == "YPAREO_ID_FORMATION_DSSP":
        return None, YPAREO_DSSP_NOT_CONFIGURED_ERROR
    return None, YPAREO_FORMATION_NOT_LINKED_ERROR


def _ypareo_optional_integer_setting(name: str) -> Optional[int]:
    raw_value = _normalize_render_secret(os.environ.get(name) or "")
    return int(raw_value) if raw_value else None


def construire_payload_cursus(session_obj: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Build the minimal initial cursus payload accepted by YPAREO."""
    formation_id, mapping_error = id_formation_ypareo(session_obj)
    if not formation_id:
        return None, mapping_error

    nom = _ypareo_existing_value(session_obj, "nom", "name", "title")
    formation = _ypareo_existing_value(session_obj, "formation", "training_type")
    payload = {
        "idFormation": formation_id,
        "idOrganisme": _normalize_render_secret(os.environ.get("YPAREO_ID_ORGANISME") or ""),
        "nom": nom or formation,
        "idSituationAvantApprentissage": _ypareo_optional_integer_setting(
            "YPAREO_ID_SITUATION_AVANT_APPRENTISSAGE"
        ),
    }
    return nettoyer_payload(payload), None


_YPAREO_SECRET_KEYS = {"token", "access_token", "ypareo_auth_token", "authorization"}
_YPAREO_REDACTED_VALUE = "<masquÃ©>"


def _redact_ypareo_secrets(value: Any) -> Any:
    """Return loggable YPAREO data with authentication secrets removed."""
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
            redacted[str(key)] = (
                _YPAREO_REDACTED_VALUE
                if normalized_key in _YPAREO_SECRET_KEYS
                else _redact_ypareo_secrets(item)
            )
        return redacted
    if isinstance(value, list):
        return [_redact_ypareo_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_ypareo_secrets(item) for item in value)
    return value


def _ypareo_safe_response_text(response: Any, *secrets: str) -> str:
    """Return the complete API body while masking token-like fields and known secrets."""
    raw_text = str(getattr(response, "text", "") or "")
    if not raw_text:
        try:
            response_data = response.json()
            raw_text = "" if response_data is None else json.dumps(response_data, ensure_ascii=False)
        except (ValueError, TypeError, requests.JSONDecodeError, AttributeError):
            raw_text = ""

    try:
        parsed_body = json.loads(raw_text)
    except (TypeError, ValueError, json.JSONDecodeError):
        safe_text = raw_text
        secret_names = "|".join(re.escape(name) for name in sorted(_YPAREO_SECRET_KEYS, key=len, reverse=True))
        safe_text = re.sub(
            rf'(?i)((?:{secret_names})\s*[=:]\s*(?:Bearer\s+)?)[^\s,;]+',
            rf"\1{_YPAREO_REDACTED_VALUE}",
            safe_text,
        )
    else:
        safe_text = json.dumps(_redact_ypareo_secrets(parsed_body), ensure_ascii=False)

    known_secrets = {_ypareo_auth_token(), *[str(secret or "") for secret in secrets]}
    for secret in sorted((item for item in known_secrets if item), key=len, reverse=True):
        safe_text = safe_text.replace(secret, _YPAREO_REDACTED_VALUE)
    return safe_text


def _ypareo_log_api_response(
    operation: str,
    response: Any,
    *,
    url: str,
    payload: Dict[str, Any],
    trainee_id: Any,
    access_token: str,
    **context: Any,
) -> None:
    """Log a YPAREO response and request context without authentication material."""
    details = {
        "operation": operation,
        "url": url,
        "status_code": getattr(response, "status_code", None),
        "response_text": _ypareo_safe_response_text(response, access_token),
        "payload": _redact_ypareo_secrets(payload),
        "trainee_id": trainee_id or "",
        **_redact_ypareo_secrets(context),
    }
    log_method = app.logger.info if getattr(response, "ok", False) else app.logger.error
    log_method("[YPAREO] rÃ©ponse API %s", json.dumps(details, ensure_ascii=False, default=str))


def _ypareo_api_error_message(response: Any, fallback: str, access_token: str = "") -> str:
    """Extract a useful and secret-free API error for persistence and the admin UI."""
    if response is None:
        return fallback
    try:
        response_data = response.json()
    except (ValueError, requests.JSONDecodeError, AttributeError):
        response_data = None
    if isinstance(response_data, dict):
        for container in (response_data, response_data.get("data")):
            if not isinstance(container, dict):
                continue
            for key in ("message", "error", "detail", "title"):
                value = container.get(key)
                if isinstance(value, str) and value.strip():
                    safe_value = _ypareo_safe_response_text(
                        type("YpareoErrorBody", (), {"text": value.strip()})(), access_token
                    )
                    return safe_value[:1000]

    status_code = getattr(response, "status_code", "inconnu")
    response_text = _ypareo_safe_response_text(response, access_token).strip() or "(rÃ©ponse vide)"
    return f"Erreur YPAREO HTTP {status_code} : rÃ©ponse API {response_text}"[:1000]


def _ypareo_detected_formation_name(session_obj: Dict[str, Any]) -> str:
    """Return the local formation label used to resolve the YPAREO formation ID."""
    return str(_ypareo_existing_value(
        session_obj, "formation", "training_type", "title", "nom", "name"
    ) or "")


def creer_cursus_ypareo(
    id_personne: Any, stagiaire: Dict[str, Any], session_obj: Dict[str, Any]
) -> bool:
    """Create only the cursus for an existing YPAREO person."""
    try:
        payload, mapping_error = construire_payload_cursus(session_obj)
    except (TypeError, ValueError) as exc:
        stagiaire["ypareo_cursus_statut"] = "Erreur"
        stagiaire["ypareo_cursus_erreur"] = f"Configuration cursus YPAREO invalide : {exc}"[:1000]
        stagiaire["ypareo_cursus_id"] = ""
        return False
    if not payload:
        stagiaire["ypareo_cursus_statut"] = "Erreur"
        stagiaire["ypareo_cursus_erreur"] = mapping_error or YPAREO_FORMATION_NOT_LINKED_ERROR
        stagiaire["ypareo_cursus_id"] = ""
        return False

    quoted_id_personne = quote(str(id_personne), safe="")
    cursus_path = _ypareo_endpoint("YPAREO_CURSUS_ENDPOINT", YPAREO_CURSUS_ENDPOINT).format(
        id_personne=quoted_id_personne, IdPersonne=quoted_id_personne
    )
    cursus_url = f"{_ypareo_base_url()}{cursus_path}"
    try:
        access_token = get_ypareo_access_token()
        response = None
        for attempt in range(2):
            response = requests.post(
                cursus_url,
                headers=ypareo_headers(access_token),
                json=payload,
                timeout=YPAREO_REQUEST_TIMEOUT_SECONDS,
            )
            _ypareo_log_api_response(
                "POST /personne/{IdPersonne}/cursus",
                response,
                url=cursus_url,
                payload=payload,
                trainee_id=stagiaire.get("id"),
                access_token=access_token,
                idPersonne=id_personne,
                nom_formation=_ypareo_detected_formation_name(session_obj),
                idFormation=payload.get("idFormation", ""),
            )
            if response.status_code != 401 or attempt == 1:
                break
            _clear_ypareo_access_token_cache()
            access_token = get_ypareo_access_token()

        if response is None or not response.ok:
            raise RuntimeError(
                _ypareo_api_error_message(response, YPAREO_CURSUS_ERROR_MESSAGE, access_token)
            )
        try:
            response_data = response.json()
        except (ValueError, requests.JSONDecodeError) as exc:
            raise RuntimeError(
                _ypareo_api_error_message(response, YPAREO_CURSUS_ERROR_MESSAGE, access_token)
            ) from exc
        response_body = response_data.get("data") if isinstance(response_data, dict) else None
        cursus_id = response_body.get("id") if isinstance(response_body, dict) else None
        if cursus_id is None or str(cursus_id).strip() == "":
            raise RuntimeError(
                _ypareo_api_error_message(response, YPAREO_CURSUS_ERROR_MESSAGE, access_token)
            )

        stagiaire["ypareo_cursus_statut"] = "CrÃ©Ã©"
        stagiaire["ypareo_cursus_id"] = cursus_id
        stagiaire["ypareo_cursus_erreur"] = ""
        app.logger.info(
            "[YPAREO] cursus crÃ©Ã© trainee_id=%s ypareo_id=%s cursus_id=%s",
            stagiaire.get("id") or "", id_personne, cursus_id,
        )
        return True
    except YpareoAuthenticationError as exc:
        message = str(exc)
    except requests.RequestException as exc:
        app.logger.error(
            "[YPAREO] appel cursus impossible url=%s trainee_id=%s idPersonne=%s "
            "nom_formation=%s idFormation=%s payload=%s erreur=%s",
            cursus_url,
            stagiaire.get("id") or "",
            id_personne,
            _ypareo_detected_formation_name(session_obj),
            payload.get("idFormation", ""),
            json.dumps(_redact_ypareo_secrets(payload), ensure_ascii=False, default=str),
            type(exc).__name__,
        )
        message = YPAREO_CURSUS_ERROR_MESSAGE
    except (TypeError, ValueError) as exc:
        message = f"Configuration cursus YPAREO invalide : {exc}"
    except Exception as exc:
        message = str(exc).strip() or YPAREO_CURSUS_ERROR_MESSAGE

    stagiaire["ypareo_cursus_statut"] = "Erreur"
    stagiaire["ypareo_cursus_erreur"] = message[:1000]
    stagiaire["ypareo_cursus_id"] = ""
    app.logger.error(
        "[YPAREO] Ã©chec crÃ©ation cursus trainee_id=%s erreur=%s",
        stagiaire.get("id") or "", message,
    )
    return False


def creer_apprenant_ypareo(
    stagiaire: Dict[str, Any], session_obj: Optional[Dict[str, Any]] = None
) -> bool:
    """Create a learner, then its cursus, without blocking local creation on failure."""
    payload = construire_payload_apprenant(stagiaire)
    personne_url = (
        f"{_ypareo_base_url()}"
        f"{_ypareo_endpoint('YPAREO_APPRENANTS_ENDPOINT', YPAREO_APPRENANTS_ENDPOINT)}"
    )

    try:
        access_token = get_ypareo_access_token()
        response = None
        for attempt in range(2):
            response = requests.post(
                personne_url, headers=ypareo_headers(access_token), json=payload,
                timeout=YPAREO_REQUEST_TIMEOUT_SECONDS,
            )
            _ypareo_log_api_response(
                "POST /personne",
                response,
                url=personne_url,
                payload=payload,
                trainee_id=stagiaire.get("id"),
                access_token=access_token,
            )
            if response.status_code != 401 or attempt == 1:
                break
            app.logger.warning(
                "[YPAREO] accÃ¨s /personne refusÃ©, renouvellement du token trainee_id=%s",
                stagiaire.get("id") or "",
            )
            _clear_ypareo_access_token_cache()
            access_token = get_ypareo_access_token()

        if response is None or not response.ok:
            raise RuntimeError(
                _ypareo_api_error_message(response, YPAREO_CREATION_ERROR_MESSAGE, access_token)
            )
        try:
            response_data = response.json()
        except (ValueError, requests.JSONDecodeError) as exc:
            raise RuntimeError(
                _ypareo_api_error_message(response, YPAREO_CREATION_ERROR_MESSAGE, access_token)
            ) from exc
        response_body = response_data.get("data") if isinstance(response_data, dict) else None
        ypareo_id = response_body.get("id") if isinstance(response_body, dict) else None
        if ypareo_id is None or str(ypareo_id).strip() == "":
            raise RuntimeError(
                _ypareo_api_error_message(response, YPAREO_CREATION_ERROR_MESSAGE, access_token)
            )

        stagiaire["ypareo_statut"] = "CrÃ©Ã©"
        stagiaire["ypareo_id"] = ypareo_id
        stagiaire["ypareo_erreur"] = ""
        app.logger.info(
            "[YPAREO] apprenant crÃ©Ã© trainee_id=%s ypareo_id=%s",
            stagiaire.get("id") or "", ypareo_id,
        )
        if session_obj is not None:
            creer_cursus_ypareo(ypareo_id, stagiaire, session_obj)
        return True
    except YpareoAuthenticationError as exc:
        message = str(exc)
    except requests.RequestException as exc:
        app.logger.error(
            "[YPAREO] appel de crÃ©ation impossible url=%s trainee_id=%s payload=%s erreur=%s",
            personne_url,
            stagiaire.get("id") or "",
            json.dumps(_redact_ypareo_secrets(payload), ensure_ascii=False, default=str),
            type(exc).__name__,
        )
        message = YPAREO_CREATION_ERROR_MESSAGE
    except Exception as exc:
        message = str(exc).strip() or YPAREO_CREATION_ERROR_MESSAGE

    stagiaire["ypareo_statut"] = "Erreur"
    stagiaire["ypareo_erreur"] = message[:1000]
    if session_obj is not None:
        stagiaire["ypareo_cursus_statut"] = "Non envoyÃ©"
        stagiaire["ypareo_cursus_erreur"] = ""
    app.logger.error(
        "[YPAREO] Ã©chec crÃ©ation apprenant trainee_id=%s erreur=%s",
        stagiaire.get("id") or "", message,
    )
    return False


@app.get("/service-worker.js")
def service_worker():
    sw_path = os.path.join(app.static_folder or "static", "sw.js")
    response = send_file(sw_path, mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response

@app.get("/espace/modeles/attestation-honneur-examen-desp.pdf")
def public_dirigeant_initial_attestation_template():
    template_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "templates",
        "static",
        "attestation.pdf",
    )
    if not os.path.exists(template_path):
        abort(404)
    return send_file(
        template_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="attestation-honneur-examen-desp.pdf",
    )


@app.get("/espace/modeles/certificat-medical-ssiap.pdf")
def public_ssiap_medical_certificate_template():
    app_root = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(app_root, "templates_word", "certificat.pdf")
    if not os.path.exists(template_path):
        # Fallback vers le modÃ¨le dÃ©jÃ  versionnÃ© pour Ã©viter d'ajouter un PDF
        # binaire supplÃ©mentaire aux demandes d'extraction de code.
        template_path = os.path.join(app_root, "static", "certificat.pdf")
    if not os.path.exists(template_path):
        abort(404)
    return send_file(
        template_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="certificat-medical-ssiap.pdf",
    )

app.config.update(
    SESSION_COOKIE_NAME="integrale_admin",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,  # Render = https
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=SESSION_DAYS),
)

def _request_expects_json() -> bool:
    return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"


def _static_credentials_match(username: str, password: str, expected_username: str, expected_password: str) -> bool:
    """Validate Render/static credentials while tolerating common copy/paste issues.

    Partner accounts are stored in the JSON data file as password hashes and
    intentionally keep password spaces significant.  This helper is only for
    environment-configured admin/secretary/SCOTIA credentials, where accidental
    leading/trailing spaces in Render variables should not block login.
    """
    expected_username = (expected_username or "").strip()
    expected_password = (expected_password or "").strip()
    if not expected_username or not expected_password:
        return False
    return (username or "").strip().lower() == expected_username.lower() and (password or "").strip() == expected_password

def admin_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            if _request_expects_json():
                return jsonify({"ok": False, "error": "Session administrateur expirÃ©e. Reconnectez-vous."}), 401
            # Keep the query string: CRM prefill links must survive authentication.
            next_url = request.full_path.rstrip("?")
            return redirect(url_for("admin_login", next=next_url))
        return view(*args, **kwargs)
    return wrapped

def admin_write_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("admin_role") == "viewer":
            if _request_expects_json():
                return jsonify({"ok": False, "error": "Droits insuffisants pour modifier ces donnÃ©es."}), 403
            abort(403)
        return view(*args, **kwargs)
    return wrapped

def _is_integrale_scotia_admin_session() -> bool:
    """Return True when the active admin session belongs to ClÃ©ment.

    Older persistent admin sessions did not store the username, so we also trust
    the configured admin account when it is ClÃ©ment's account.
    """
    if not session.get("admin_logged_in") or session.get("admin_role") not in {"admin", "super_admin"}:
        return False

    admin_username = (session.get("admin_username") or "").strip().lower()
    if admin_username:
        return admin_username == INTEGRALE_SCOTIA_AUTO_LOGIN_EMAIL

    return (ADMIN_USER or "").strip().lower() == INTEGRALE_SCOTIA_AUTO_LOGIN_EMAIL


def _enable_scotia_session_for_integrale_admin() -> None:
    session["scotia_logged_in"] = True
    session["scotia_username"] = INTEGRALE_SCOTIA_AUTO_LOGIN_EMAIL
    session.permanent = True


def scotia_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("scotia_logged_in"):
            return redirect(url_for("scotia_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

@app.before_request
def protect_sensitive_routes():
    if request.path == "/healthz":
        return None
    """Central safety net for sensitive admin/API routes.

    Some legacy endpoints were missing explicit decorators.  This hook protects
    whole sensitive namespaces without changing public candidate/VAE flows.
    """
    path = request.path or ""
    if _session_has_authentication_marker() and not _current_session_is_still_valid():
        app.logger.info("[SECURITY] session invalidÃ©e par cutoff path=%s", path)
        session.clear()
        if path.startswith("/api/"):
            return jsonify({"ok": False, "error": "session_expired"}), 401

    # Never trust a role stored on a partner user as a platform role.  This
    # also invalidates legacy cookies created before partner roles were
    # constrained at login time.
    if _is_external_partner_session() and _current_session_role() not in PARTNER_ACCOUNT_ROLES:
        app.logger.warning("[SECURITY] invalid_partner_role_session path=%s role=%s", path, _current_session_role())
        session.clear()
        if path.startswith("/api/"):
            return jsonify({"ok": False, "error": "invalid_partner_session"}), 401
        return redirect(url_for("admin_login", error="invalid"))

    if path.startswith("/admin/") and path != "/admin/login":
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login", next=request.full_path if request.query_string else path))

    protected_api_prefixes = (
        "/api/admin/",
        "/api/secretariat/",
        "/api/cnaps",
    )
    if path.startswith(protected_api_prefixes):
        if not session.get("admin_logged_in"):
            app.logger.warning("[SECURITY] blocked_by_global_guard path=%s", path)
            return jsonify({"ok": False, "error": "auth_required"}), 401
        if request.method not in {"GET", "HEAD", "OPTIONS"} and session.get("admin_role") == "viewer":
            return jsonify({"ok": False, "error": "read_only"}), 403

    partner_context = bool(
        session.get("admin_logged_in")
        and (_is_external_partner_session() or (session.get("assist_partner_id") and _is_super_admin_session()))
    )
    if partner_context:
        endpoint = request.endpoint or ""
        endpoint_lower = endpoint.lower()
        global_integration_path = (
            path.startswith(("/admin/qonto", "/admin/reglages/qonto", "/admin/wedof", "/api/send-to-"))
            or "qonto" in endpoint_lower
            or "wedof" in endpoint_lower
            or (
                "/cpf/" in path
                and path.rsplit("/", 1)[-1] in {"live-match", "associate-match", "refresh", "search", "associate"}
            )
        )
        if global_integration_path:
            app.logger.warning(
                "[SECURITY] partner_global_integration_blocked partner_id=%s endpoint=%s path=%s",
                _current_partner_id(), endpoint, path,
            )
            if path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
                return jsonify({"ok": False, "error": "tenant_integration_not_configured"}), 403
            flash("Cette intÃ©gration nÃ©cessite des identifiants propres Ã  votre organisme.", "error")
            return redirect(url_for("admin_sessions"))
        if endpoint in PARTNER_SPACE_FORBIDDEN_ENDPOINTS:
            if path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
                return jsonify({"ok": False, "error": "partner_space_forbidden"}), 403
            flash("Cette fonctionnalitÃ© nâ€™est pas disponible dans lâ€™espace partenaire.", "error")
            return redirect(url_for("admin_sessions"))
        for module_key, endpoints in PARTNER_MODULE_ROUTE_ENDPOINTS.items():
            if endpoint in endpoints and not partner_has_module(module_key):
                if path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
                    return jsonify({"ok": False, "error": "module_locked", "module": module_key}), 403
                flash("Ce module est verrouillÃ© pour ce partenaire. Activez-le dans la fiche partenaire.", "error")
                return redirect(url_for("admin_sessions"))

@app.context_processor
def inject_read_only():
    admin_notifications = {"notifications": [], "unresolved_total": 0}
    wedof_new_requests_count = 0
    sales_today_notification_count = 0
    admin_logged_in = bool(session.get("admin_logged_in"))
    can_view_notifications = admin_logged_in and _admin_can_view_notifications()
    ctx_data: Optional[Dict[str, Any]] = None
    # The BTS area is intentionally independent from the historical data.json
    # payload. Its navigation badges stay neutral instead of loading that file.
    if admin_logged_in and request.endpoint != "admin_bts":
        try:
            ctx_data = load_data()
        except Exception:
            ctx_data = None
        if ctx_data is not None:
            try:
                sales_metrics = _build_sales_tracking_metrics(ctx_data, datetime.date.today().year)
                sales_today_notification_count = max(int(sales_metrics.get("today_inscriptions") or 0), 0)
            except Exception:
                sales_today_notification_count = 0
            if can_view_notifications:
                try:
                    admin_notifications = _admin_notifications_payload(ctx_data)
                except Exception:
                    admin_notifications = {"notifications": [], "unresolved_total": 0}
    mail_sent_notice = bool(session.pop("_mail_sent_notice", False))
    current_partner_name = ""
    assisted_partner_name = ""
    partner = None
    partner_sidebar = {}
    if admin_logged_in and ctx_data is not None:
        try:
            active_partner_id = _current_partner_id()
            partner = next((p for p in ctx_data.get("partners", []) if isinstance(p, dict) and p.get("id") == active_partner_id), None)
            current_partner_name = (partner or {}).get("name") or ""
            if partner:
                normalize_partner_subscription(ctx_data, partner)
                sub = partner.get("subscription") or {}
                notification_total = admin_notifications.get("unresolved_total", 0) if can_view_notifications else 0
                enabled_modules = _partner_enabled_modules(partner)
                partner_sidebar = {
                    "partner": partner,
                    "logo_url": _partner_logo_url(partner),
                    "user_name": session.get("admin_username") or session.get("admin_email") or "",
                    "subscription": sub,
                    "enabled_modules": enabled_modules,
                    "notification_total": notification_total,
                    "is_active": (partner.get("status") or "active") == "active",
                    "show_users": bool(partner.get("max_users") or ctx_data.get("users")),
                }
            if session.get("assist_partner_id"):
                assisted_partner_name = current_partner_name
        except Exception:
            pass
    return {
        "is_admin_logged_in": bool(session.get("admin_logged_in")),
        "is_super_admin": _is_super_admin_session(),
        "current_partner_name": current_partner_name,
        "assisted_partner_name": assisted_partner_name,
        "is_partner_space": _is_external_partner_session() or bool(session.get("assist_partner_id")),
        "is_read_only": session.get("admin_role") == "viewer",
        "admin_notifications": admin_notifications["notifications"],
        "admin_unresolved_total": admin_notifications["unresolved_total"],
        "wedof_new_requests_count": wedof_new_requests_count,
        "sales_today_notification_count": sales_today_notification_count,
        "admin_can_access_notifications": _admin_can_view_notifications(),
        "admin_can_manage_notifications": _admin_can_manage_notifications(),
        "global_mail_sent_notice": mail_sent_notice,
        "current_partner_logo_url": _partner_logo_url(partner) if current_partner_name else "",
        "public_base_url": PUBLIC_BASE_URL.rstrip("/"),
        "partner_modules": PARTNER_MODULES,
        "partner_has_module": partner_has_module,
        "partner_allowed_formation_types": _partner_allowed_formation_types(),
        "partner_sidebar": partner_sidebar,
    }

@app.get("/admin/login")
def admin_login():
    next_url = _safe_local_redirect_target(
        request.args.get("next") or "", url_for("admin_sessions")
    )
    error_code = (request.args.get("error") or "").strip()
    messages = {
        "invalid": "Identifiant ou mot de passe incorrect.",
        "inactive": "Ce compte partenaire est dÃ©sactivÃ©.",
        "not_activated": "Ce compte partenaire nâ€™est pas encore activÃ©. Utilisez le lien dâ€™invitation pour dÃ©finir le mot de passe.",
        "partner_status": "Lâ€™espace partenaire est suspendu ou archivÃ©. Contactez lâ€™administrateur.",
        "partner_suspended": "Lâ€™espace partenaire est suspendu. Contactez lâ€™administrateur.",
        "partner_archived": "Lâ€™espace partenaire est archivÃ©. Contactez lâ€™administrateur.",
        "rate_limited": "Trop de tentatives de connexion. Patientez quelques minutes avant de rÃ©essayer.",
    }
    activated_message = "Votre compte est activÃ©. Vous pouvez maintenant vous connecter." if request.args.get("activated") == "1" else ""
    return render_template(
        "admin_login.html",
        next_url=next_url,
        error_message=messages.get(error_code, ""),
        activated_message=activated_message,
    )

@app.post("/admin/login")
def admin_login_post():
    username = (request.form.get("username") or "").strip()
    username_normalized = username.lower()
    password = request.form.get("password") or ""
    next_url = _safe_local_redirect_target(
        request.form.get("next") or "", url_for("admin_sessions")
    )
    # A login attempt always starts a new authentication transaction.  This
    # prevents an existing tenant cookie from influencing the data scope used
    # to authenticate another account.
    session.clear()
    if len(username) > 320 or len(password) > 4096:
        return redirect(url_for("admin_login", next=next_url, error="invalid"))

    # Les accÃ¨s plateforme (admin / consultation) sont prioritaires sur les
    # comptes partenaires. Un administrateur peut partager la mÃªme adresse
    # e-mail qu'un utilisateur partenaire ; dans ce cas ses identifiants
    # statiques doivent toujours ouvrir l'espace d'administration complet.
    if _static_credentials_match(username_normalized, password, ADMIN_USER, ADMIN_PASSWORD):
        def record_platform_login(data: Dict[str, Any]) -> Dict[str, Any]:
            _append_activity_log(data, "login", "user", username_normalized, INTEGRALE_PARTNER_ID)
            return {"ok": True}

        _atomic_update_data(record_platform_login)
        session.clear()
        session["admin_logged_in"] = True
        session["admin_role"] = "admin"
        session["platform_role"] = "super_admin"
        session["admin_username"] = username_normalized
        session["partner_id"] = INTEGRALE_PARTNER_ID
        _stamp_authenticated_session()
        session.permanent = True
        return redirect(_post_login_redirect_target(next_url, url_for("admin_sessions")))

    if SECRETARY_USER and SECRETARY_PASSWORD and _static_credentials_match(username_normalized, password, SECRETARY_USER, SECRETARY_PASSWORD):
        session.clear()
        session["admin_logged_in"] = True
        session["admin_role"] = "viewer"
        session["platform_role"] = "viewer"
        session["admin_username"] = username_normalized
        session["partner_id"] = INTEGRALE_PARTNER_ID
        _stamp_authenticated_session()
        session.permanent = True
        return redirect(_post_login_redirect_target(next_url, url_for("admin_sessions")))

    # Reject repeated unauthenticated work before parsing the potentially
    # large tenant store or evaluating a password hash.
    if _partner_login_is_rate_limited(username_normalized):
        app.logger.warning("partner_auth reason=rate_limited username_hash=%s", hashlib.sha256(username_normalized.encode()).hexdigest()[:16])
        return redirect(url_for("admin_login", next=next_url, error="rate_limited"))

    data = _load_partner_auth_data()
    _log_partner_auth_event("login_attempt", data, username_normalized)

    # sÃ©curitÃ© minimale : si aucun accÃ¨s plateforme ni partenaire nâ€™est configurÃ©, on refuse.
    if not (ADMIN_USER and ADMIN_PASSWORD) and not (SECRETARY_USER and SECRETARY_PASSWORD) and not data.get("users"):
        _log_partner_auth_event("data_file_inaccessible_or_no_auth_config", data, username_normalized)
        abort(500, "ADMIN_USER/ADMIN_PASSWORD non configurÃ©s")

    user = _find_user_by_email(data, username_normalized)
    if user:
        partner = next((p for p in data.get("partners", []) if isinstance(p, dict) and p.get("id") == user.get("partner_id")), None)
        if not user.get("active", True):
            _log_partner_auth_event("utilisateur dÃ©sactivÃ©", data, username_normalized, user, partner)
            return redirect(url_for("admin_login", next=next_url, error="inactive"))
        if not user.get("password_hash"):
            _log_partner_auth_event("aucun mot de passe dÃ©fini", data, username_normalized, user, partner)
            return redirect(url_for("admin_login", next=next_url, error="not_activated"))
        password_ok = _verify_password(password, user.get("password_hash") or "")
        if not password_ok:
            _log_partner_auth_event("mauvais mot de passe", data, username_normalized, user, partner, password_ok=False)
            return redirect(url_for("admin_login", next=next_url, error="invalid"))
        if not partner:
            _log_partner_auth_event("partenaire introuvable", data, username_normalized, user, None, password_ok=True)
            return redirect(url_for("admin_login", next=next_url, error="invalid"))
        if partner.get("status") == "suspended":
            _log_partner_auth_event("partenaire suspendu", data, username_normalized, user, partner, password_ok=True)
            return redirect(url_for("admin_login", next=next_url, error="partner_suspended"))
        if partner.get("status") == "archived":
            _log_partner_auth_event("partenaire archivÃ©", data, username_normalized, user, partner, password_ok=True)
            return redirect(url_for("admin_login", next=next_url, error="partner_archived"))
        if partner.get("status") not in {"active", "trial"}:
            _log_partner_auth_event("statut partenaire refusÃ©", data, username_normalized, user, partner, password_ok=True)
            return redirect(url_for("admin_login", next=next_url, error="invalid"))

        partner_role = str(user.get("role") or "partner_admin").strip()
        if partner_role not in PARTNER_ACCOUNT_ROLES:
            _log_partner_auth_event("rÃ´le partenaire refusÃ©", data, username_normalized, user, partner, password_ok=True)
            app.logger.warning(
                "[SECURITY] partner_login_invalid_role user_id=%s partner_id=%s role=%s",
                user.get("id"), user.get("partner_id"), partner_role,
            )
            return redirect(url_for("admin_login", next=next_url, error="invalid"))

        _log_partner_auth_event("connexion partenaire rÃ©ussie", data, username_normalized, user, partner, password_ok=True)
        def record_partner_login(canonical: Dict[str, Any]) -> Dict[str, Any]:
            current_user = next((
                item for item in canonical.get("users", [])
                if isinstance(item, dict) and str(item.get("id") or "") == str(user.get("id") or "")
            ), None)
            current_partner = next((
                item for item in canonical.get("partners", [])
                if isinstance(item, dict) and str(item.get("id") or "") == str(partner.get("id") or "")
            ), None)
            if (
                not current_user
                or not current_partner
                or not current_user.get("active", True)
                or str(current_user.get("role") or "partner_admin").strip() != partner_role
                or current_partner.get("status") not in {"active", "trial"}
            ):
                return {"ok": False}
            current_user["last_login_at"] = _now_iso()
            _append_activity_log(
                canonical, "login", "user", current_user.get("id"), current_partner.get("id"),
            )
            return {"ok": True}

        if not _atomic_update_data(
            record_partner_login,
            partner_id=str(user.get("partner_id") or ""),
        ).get("ok"):
            return redirect(url_for("admin_login", next=next_url, error="invalid"))
        session.clear()
        session["admin_logged_in"] = True
        session["admin_username"] = user.get("email") or username_normalized
        session["user_id"] = user.get("id")
        session["admin_user_id"] = user.get("id")
        session["admin_role"] = partner_role
        session["partner_id"] = user.get("partner_id")
        _stamp_authenticated_session()
        session.permanent = True
        _clear_partner_login_account_limit(username_normalized)
        return redirect(_post_login_redirect_target(next_url, url_for("admin_sessions")))

    _log_partner_auth_event("utilisateur partenaire introuvable", data, username_normalized)

    return redirect(url_for("admin_login", next=next_url, error="invalid"))


@app.get("/scotia/login")
def scotia_login():
    next_url = request.args.get("next") or url_for("scotia_dashboard")
    if session.get("scotia_logged_in"):
        return redirect(next_url)
    return f"""
    <!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Connexion SCOTIA</title></head>
    <body style="font-family:Arial,sans-serif;max-width:420px;margin:60px auto;padding:20px">
      <h2>Connexion SCOTIA</h2>
      <form method="post" action="/scotia/login" autocomplete="off">
        <input type="hidden" name="next" value="{next_url}">
        <div style="margin:10px 0"><label>Identifiant</label><br><input name="username" autocomplete="off" style="width:100%;padding:10px"></div>
        <div style="margin:10px 0"><label>Mot de passe</label><br><input name="password" type="password" autocomplete="new-password" style="width:100%;padding:10px"></div>
        <button style="padding:10px 14px">Se connecter</button>
      </form>
    </body></html>
    """

@app.post("/scotia/login")
def scotia_login_post():
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    next_url = request.form.get("next") or url_for("scotia_dashboard")

    admin_ok = _static_credentials_match(username, password, ADMIN_USER, ADMIN_PASSWORD)
    scotia_ok = _static_credentials_match(username, password, SCOTIA_USER, SCOTIA_PASSWORD)

    if not (SCOTIA_USER and SCOTIA_PASSWORD) and not (ADMIN_USER and ADMIN_PASSWORD):
        abort(500, "SCOTIA_USER/SCOTIA_PASSWORD ou ADMIN_USER/ADMIN_PASSWORD non configurÃ©s")

    if scotia_ok or admin_ok:
        session.clear()
        session["scotia_logged_in"] = True
        session["scotia_username"] = username.lower()
        _stamp_authenticated_session()
        if admin_ok:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"
            session["admin_username"] = username.lower()
        session.permanent = False
        return redirect(next_url)

    return redirect(url_for("scotia_login", next=next_url))

@app.get("/scotia/logout")
def scotia_logout():
    session.clear()
    return redirect(url_for("scotia_login"))

@app.get("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

def fr_date(value: str) -> str:
    s = (value or "").strip()
    if not s:
        return ""
    try:
        dt = datetime.datetime.strptime(s[:10], "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return value

def format_date_fr(value: Any) -> str:
    """Affiche une date ISO en franÃ§ais, sans jamais exposer une valeur invalide."""
    try:
        raw = str(value or "").strip()
        if not raw:
            return "â€”"
        return datetime.date.fromisoformat(raw[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return "â€”"

def _fr_date_offset(value: str, *, months: int = 0, days: int = 0) -> str:
    """Format an ISO date after applying calendar-month and day offsets."""
    s = str(value or "").strip()
    if not s:
        return ""
    try:
        result = datetime.datetime.strptime(s[:10], "%Y-%m-%d").date()
        if months:
            month_index = result.year * 12 + result.month - 1 + months
            year, zero_based_month = divmod(month_index, 12)
            month = zero_based_month + 1
            day = min(result.day, calendar.monthrange(year, month)[1])
            result = result.replace(year=year, month=month, day=day)
        result += datetime.timedelta(days=days)
        return result.strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return ""

def fr_datetime(value: str) -> str:
    s = (value or "").strip()
    if not s:
        return ""
    normalized = s.replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        dt = dt.astimezone(ZoneInfo("Europe/Paris"))
        return dt.strftime("%d/%m/%Y Ã  %Hh%M")
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            dt = datetime.datetime.strptime(s[:26], fmt)
            dt = dt.replace(tzinfo=datetime.timezone.utc).astimezone(ZoneInfo("Europe/Paris"))
            return dt.strftime("%d/%m/%Y Ã  %Hh%M")
        except Exception:
            pass
    return fr_date(s)


def history_datetime(value: str) -> str:
    s = (value or "").strip()
    if not s:
        return ""
    normalized = s.replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        dt = dt.astimezone(ZoneInfo("Europe/Paris"))
        return dt.strftime("%d/%m/%Y %Hh%M")
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            dt = datetime.datetime.strptime(s[:26], fmt)
            dt = dt.replace(tzinfo=datetime.timezone.utc).astimezone(ZoneInfo("Europe/Paris"))
            return dt.strftime("%d/%m/%Y %Hh%M")
        except Exception:
            pass
    return fr_date(s)


# âœ… Filtres utilisables dans tous tes templates
app.add_template_filter(fr_date, "frdate")
app.add_template_filter(fr_datetime, "frdatetime")
app.add_template_filter(format_date_fr, "format_date_fr")


# =========================
# Persistent disk (Render)
# =========================
def _storage_probe_json(path: str, required_list_key: Optional[str] = None) -> Tuple[bool, int]:
    """Return whether a JSON storage file is structurally usable and its list size."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
    except Exception:
        return False, 0

    if not isinstance(loaded, dict):
        return False, 0
    if not required_list_key:
        return True, 0
    bucket = loaded.get(required_list_key)
    if not isinstance(bucket, list):
        return False, 0
    return True, len(bucket)


def _persist_dir_data_score(path: str) -> int:
    """Score an existing candidate by the production data it already contains.

    Render services may have both /var/data and /data writable.  Choosing the
    first writable path can hide the mounted disk and make the app look empty.
    Prefer the candidate that already contains stagiaire/VAE data or backups.
    """
    if not path or not os.path.isdir(path):
        return 0

    score = 0
    data_path = os.path.join(path, "data.json")
    vae_path = os.path.join(path, "data_vae.json")
    wedof_path = os.path.join(path, "wedof_webhooks.json")

    if os.path.exists(data_path):
        score += 20
        valid, count = _storage_probe_json(data_path, "sessions")
        if valid:
            score += 1000 + min(count, 500)

    if os.path.exists(vae_path):
        score += 15
        valid, count = _storage_probe_json(vae_path, "dossiers")
        if valid:
            score += 900 + min(count, 500)

    if os.path.exists(wedof_path):
        valid, count = _storage_probe_json(wedof_path)
        if valid:
            score += 50
        else:
            try:
                with open(wedof_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    score += 50 + min(len(loaded), 200)
            except Exception:
                pass

    backup_dir = os.path.join(path, "backups")
    if os.path.isdir(backup_dir):
        try:
            names = os.listdir(backup_dir)
        except Exception:
            names = []
        data_backups = [n for n in names if n.startswith("data_json.") and n.endswith(".json")]
        vae_backups = [n for n in names if n.startswith("data_vae_json.") and n.endswith(".json")]
        score += min(len(data_backups), 120) * 3
        score += min(len(vae_backups), 120) * 2

    uploads_dir = os.path.join(path, "uploads")
    if os.path.isdir(uploads_dir):
        try:
            if any(os.scandir(uploads_dir)):
                score += 25
        except Exception:
            pass

    return score


def _is_writable_directory(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        test_path = os.path.join(path, ".write-test")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test_path)
        return True
    except Exception:
        return False


def _resolve_persist_dir() -> str:
    """Return the directory used for all mutable production data.

    On Render this must point to the mounted persistent disk.  The value can be
    forced with PERSIST_DIR.  Without PERSIST_DIR, both common Render mount
    paths are probed and the one that already contains the business data wins.
    """
    configured = (os.environ.get("PERSIST_DIR") or "").strip()
    if configured:
        if _is_writable_directory(configured):
            return configured
        raise RuntimeError(f"PERSIST_DIR configurÃ© mais non accessible en Ã©criture: {configured}")

    candidates = ["/var/data", "/data"]
    writable_candidates: List[Tuple[str, int]] = []
    last_error = None
    for candidate in candidates:
        try:
            if _is_writable_directory(candidate):
                writable_candidates.append((candidate, _persist_dir_data_score(candidate)))
        except Exception as exc:
            last_error = exc
            continue

    if not writable_candidates:
        raise RuntimeError(f"Aucun dossier persistant accessible parmi {candidates}: {last_error}")

    best_candidate, best_score = max(writable_candidates, key=lambda item: item[1])
    if best_score > 0:
        return best_candidate

    return writable_candidates[0][0]

PERSIST_DIR = _resolve_persist_dir()
DATA_FILE = os.path.join(PERSIST_DIR, "data.json")
WEDOF_WEBHOOK_FILE = os.path.join(PERSIST_DIR, "wedof_webhooks.json")
VTC_CPF_TRAINING_ID = "84089988400026_vtc2022"
VTC_CPF_TRAINING_ACTION_ID = "84089988400026_vtc2022mixte"
VTC_CPF_ACCOUNT_URL = "https://www.moncompteformation.gouv.fr/espace-prive/html/#/"
AKTO_BTS_DB_FILE = os.path.join(PERSIST_DIR, "akto_bts.sqlite3")
AKTO_BTS_SYNC_LOCK_FILE = os.path.join(PERSIST_DIR, "akto_bts_sync.lock")
os.environ.setdefault(
    "WEDOF_GOVERNOR_DB_PATH",
    os.path.join(PERSIST_DIR, "wedof_governor.sqlite3"),
)

BACKUP_DIR = os.path.join(PERSIST_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)
TRASH_DIR = os.path.join(PERSIST_DIR, "trash")
os.makedirs(TRASH_DIR, exist_ok=True)
BACKUP_RETENTION = int(os.environ.get("BACKUP_RETENTION", "120"))
BACKUP_MIN_INTERVAL_SECONDS = int(os.environ.get("BACKUP_MIN_INTERVAL_SECONDS", "300"))
AUTO_RESTORE_FROM_BACKUP = (os.environ.get("AUTO_RESTORE_FROM_BACKUP", "1") or "").strip().lower() in {"1", "true", "yes", "on"}
BACKUP_SNAPSHOT_BEFORE_SAVE = (os.environ.get("BACKUP_SNAPSHOT_BEFORE_SAVE", "1") or "").strip().lower() in {"1", "true", "yes", "on"}
DOCS_TO_CONTROL_PUBLIC_TOKEN = (os.environ.get("DOCS_TO_CONTROL_PUBLIC_TOKEN") or "").strip()
DOCS_TO_CONTROL_TRUSTED_USER_AGENT = (
    os.environ.get("DOCS_TO_CONTROL_TRUSTED_USER_AGENT")
    or "plateformegestion/1.0 (+https://plateformegestion.onrender.com)"
).strip()

def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        app.logger.warning("Invalid integer for %s; using default %s", name, default)
        return default


MAX_JSON_BACKUP_BYTES = _int_env("MAX_JSON_BACKUP_BYTES", 52428800)
QONTO_TRAINEE_AUTO_SYNC_TTL_SECONDS = max(30, _int_env("QONTO_TRAINEE_AUTO_SYNC_TTL_SECONDS", 300))
QONTO_BACKGROUND_SYNC_MAX_LINES = max(1, min(200, _int_env("QONTO_BACKGROUND_SYNC_MAX_LINES", 40)))
QONTO_BACKGROUND_SYNC_MAX_SECONDS = max(10, min(180, _int_env("QONTO_BACKGROUND_SYNC_MAX_SECONDS", 120)))
_qonto_background_sync_lock = threading.Lock()

_data_lock = threading.RLock()
_partner_login_rate_limit_lock = threading.Lock()
_partner_login_attempts: Dict[str, List[float]] = {}
_partner_auth_index_lock = threading.RLock()
_partner_auth_index_cache: Dict[str, Any] = {
    "path": "", "fingerprint": None, "users": [], "partners": [], "invitations": [],
}
_partner_postgres_store_lock = threading.RLock()
_partner_postgres_bootstrap_lock = threading.RLock()
_partner_postgres_store_instance: Optional[PartnerPostgresStore] = None
_partner_postgres_store_config: Tuple[str, int, float] = ("", 0, 0.0)
# Tests can inject a deterministic in-memory repository without installing a
# PostgreSQL driver.  Production never sets this value.
_partner_postgres_store_override: Any = None
_partner_postgres_bootstrap_done = False
_cnaps_public_annuaire_monitor_lock = threading.Lock()
_afc_documents_reminders_lock = threading.Lock()
_convention_signature_reminders_lock = threading.Lock()
_wedof_webhook_lock = threading.RLock()
_wedof_webhook_processing_lock = threading.RLock()
_last_backup_times: Dict[str, float] = {}
_storage_startup_logged = False

UPLOADS_DIR = os.path.join(PERSIST_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)
_log_memory_stage("AFTER_STORAGE_CONFIGURATION", _APP_IMPORT_STARTED_AT, "-")

PARTNER_STORAGE_CATEGORIES = {"stagiaires", "contrats", "conventions", "signatures", "factures", "logos", "documents"}
INTEGRALE_PARTNER_ID = "11111111-1111-4111-8111-111111111111"
PARTNER_STATUSES = {"active", "trial", "suspended", "archived"}
PLATFORM_ROLES = {"super_admin", "partner_admin", "admin", "viewer"}
PARTNER_ACCOUNT_ROLES = {"partner_admin", "viewer"}
PARTNER_LOGIN_WINDOW_SECONDS = max(60, _int_env("PARTNER_LOGIN_WINDOW_SECONDS", 300))
PARTNER_LOGIN_MAX_ATTEMPTS = max(3, _int_env("PARTNER_LOGIN_MAX_ATTEMPTS", 8))
PARTNER_LOGIN_MAX_ATTEMPTS_PER_IP = max(
    PARTNER_LOGIN_MAX_ATTEMPTS,
    _int_env("PARTNER_LOGIN_MAX_ATTEMPTS_PER_IP", 40),
)

PARTNER_POSTGRES_MODES = {"off", "shadow", "active"}


def _partner_postgres_mode() -> str:
    """Return the safe runtime mode for the external-partner store.

    ``off`` keeps the historical JSON behaviour. ``shadow`` copies and checks
    external tenants while JSON remains authoritative. ``active`` makes
    PostgreSQL authoritative only for external partner contexts.
    """
    value = str(os.environ.get("PARTNER_POSTGRES_MODE") or "off").strip().lower()
    return value if value in PARTNER_POSTGRES_MODES else "off"


def _partner_postgres_active() -> bool:
    return _partner_postgres_mode() == "active"


def _partner_postgres_shadow() -> bool:
    return _partner_postgres_mode() == "shadow"


def _partner_postgres_configured() -> bool:
    return bool(str(os.environ.get("PARTNER_DATABASE_URL") or "").strip())


def _get_partner_postgres_store() -> PartnerPostgresStore:
    global _partner_postgres_store_instance, _partner_postgres_store_config
    if _partner_postgres_store_override is not None:
        return _partner_postgres_store_override
    database_url = str(os.environ.get("PARTNER_DATABASE_URL") or "").strip()
    if not database_url:
        raise PartnerPostgresUnavailable("PARTNER_DATABASE_URL absent")
    max_pool_size = max(1, min(_int_env("PARTNER_POSTGRES_POOL_MAX_SIZE", 4), 10))
    try:
        timeout_seconds = max(
            1.0,
            min(float(os.environ.get("PARTNER_POSTGRES_TIMEOUT_SECONDS") or "5"), 30.0),
        )
    except (TypeError, ValueError):
        timeout_seconds = 5.0
    config = (database_url, max_pool_size, timeout_seconds)
    with _partner_postgres_store_lock:
        if _partner_postgres_store_instance is not None and _partner_postgres_store_config != config:
            _partner_postgres_store_instance.close()
            _partner_postgres_store_instance = None
        if _partner_postgres_store_instance is None:
            _partner_postgres_store_instance = PartnerPostgresStore(
                database_url,
                min_pool_size=0,
                max_pool_size=max_pool_size,
                timeout_seconds=timeout_seconds,
            )
            _partner_postgres_store_config = config
        return _partner_postgres_store_instance


def _close_partner_postgres_store() -> None:
    global _partner_postgres_store_instance
    with _partner_postgres_store_lock:
        store, _partner_postgres_store_instance = _partner_postgres_store_instance, None
    if store is not None:
        store.close()


atexit.register(_close_partner_postgres_store)


def get_partner_storage_path(partner_id: str, category: str) -> str:
    """Return a safe partner-scoped storage path on the persistent disk."""
    partner_id = str(partner_id or "").strip()
    category = str(category or "").strip().lower()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", partner_id):
        raise ValueError("partner_id invalide")
    if category not in PARTNER_STORAGE_CATEGORIES:
        raise ValueError("catÃ©gorie de stockage invalide")
    root = os.path.realpath(os.path.join(PERSIST_DIR, "partners", partner_id))
    target = os.path.realpath(os.path.join(root, category))
    if not target.startswith(root + os.sep):
        raise ValueError("chemin partenaire invalide")
    os.makedirs(target, exist_ok=True)
    return target


def _current_session_role() -> str:
    return (session.get("admin_role") or "").strip() if has_request_context() else ""


def _is_super_admin_session() -> bool:
    """Only an internal platform session may ever be a super administrator.

    Partner roles live in the same historical ``admin_role`` cookie field.  A
    corrupted partner record must therefore not become a platform admin merely
    by containing ``admin`` or ``super_admin``.
    """
    if not has_request_context() or not session.get("admin_logged_in"):
        return False
    partner_id = str(session.get("partner_id") or "")
    if partner_id and partner_id != INTEGRALE_PARTNER_ID:
        return False
    return bool(
        session.get("platform_role") == "super_admin"
        or _current_session_role() in {"super_admin", "admin"}
    )


def _is_external_partner_session() -> bool:
    if not has_request_context() or not session.get("admin_logged_in"):
        return False
    partner_id = str(session.get("partner_id") or "")
    return bool(partner_id and partner_id != INTEGRALE_PARTNER_ID and not _is_super_admin_session())


def _current_partner_id() -> str:
    if not has_request_context():
        return ""
    if session.get("assist_partner_id") and _is_super_admin_session():
        return str(session.get("assist_partner_id") or "")
    return str(session.get("partner_id") or "")


def _is_partner_scoped_session() -> bool:
    if not has_request_context() or not session.get("admin_logged_in"):
        return False
    return bool(_current_partner_id()) and not _is_super_admin_session()


def _is_partner_data_scope_session() -> bool:
    """Whether this request must read exactly one external tenant's data.

    Super-admin assistance is deliberately included even though it remains a
    privileged session.  This prevents assistance pages from materialising the
    global JSON document and makes the PostgreSQL row-level policy apply to the
    same tenant the administrator is viewing.
    """
    if not has_request_context() or not session.get("admin_logged_in"):
        return False
    partner_id = _current_partner_id()
    if not partner_id or partner_id == INTEGRALE_PARTNER_ID:
        return False
    return bool(
        _is_external_partner_session()
        or (
            _partner_postgres_active()
            and session.get("assist_partner_id")
            and _is_super_admin_session()
        )
    )


def _safe_local_redirect_target(value: str, default: str, *, prefixes: Tuple[str, ...] = ("/admin",)) -> str:
    """Return a same-origin application path or a known-safe default."""
    raw = str(value or "").strip()
    if not raw or any(ord(char) < 32 for char in raw):
        return default
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return default
    if prefixes and not any(parsed.path == prefix or parsed.path.startswith(prefix + "/") for prefix in prefixes):
        return default
    return raw


def _post_login_redirect_target(value: str, default: str) -> str:
    """Keep a signed-in user away from routes reserved to super admins.

    ``next`` is captured before authentication, when the application does not
    yet know which role will sign in. A partner who was given an internal
    ``/admin/partners/...`` URL would otherwise authenticate successfully and
    immediately land on a 403 page.
    """
    target = _safe_local_redirect_target(value, default)
    if _is_super_admin_session():
        return target
    try:
        endpoint, _route_values = app.url_map.bind_to_environ(request.environ).match(
            urlparse(target).path,
            method="GET",
        )
    except HTTPException:
        return default
    view = app.view_functions.get(endpoint)
    if view is not None and getattr(view, "_requires_super_admin", False):
        app.logger.info(
            "auth_redirect_sanitized role=%s endpoint=%s",
            _current_session_role() or "unknown",
            endpoint,
        )
        return default
    return target


def _partner_login_rate_limit_keys(username: str) -> Tuple[str, str]:
    forwarded = request.headers.get("X-Forwarded-For", "") if has_request_context() else ""
    ip = (forwarded.split(",", 1)[0].strip() or (request.remote_addr or "unknown")) if has_request_context() else "unknown"
    email_digest = hashlib.sha256(str(username or "").strip().lower().encode("utf-8")).hexdigest()[:24]
    ip_digest = hashlib.sha256(ip.encode("utf-8")).hexdigest()[:24]
    return f"account:{ip_digest}:{email_digest}", f"ip:{ip_digest}"


def _partner_login_is_rate_limited(username: str) -> bool:
    """Bound unauthenticated JSON/password work without persisting attempts."""
    now = time.monotonic()
    cutoff = now - PARTNER_LOGIN_WINDOW_SECONDS
    account_key, ip_key = _partner_login_rate_limit_keys(username)
    with _partner_login_rate_limit_lock:
        for key in list(_partner_login_attempts):
            kept = [stamp for stamp in _partner_login_attempts[key] if stamp >= cutoff]
            if kept:
                _partner_login_attempts[key] = kept
            else:
                _partner_login_attempts.pop(key, None)
        account_attempts = _partner_login_attempts.setdefault(account_key, [])
        ip_attempts = _partner_login_attempts.setdefault(ip_key, [])
        if len(account_attempts) >= PARTNER_LOGIN_MAX_ATTEMPTS or len(ip_attempts) >= PARTNER_LOGIN_MAX_ATTEMPTS_PER_IP:
            return True
        account_attempts.append(now)
        ip_attempts.append(now)
        # The dictionary is process-local and deliberately bounded.
        if len(_partner_login_attempts) > 4096:
            for key in list(_partner_login_attempts)[:1024]:
                _partner_login_attempts.pop(key, None)
        return False


def _clear_partner_login_account_limit(username: str) -> None:
    account_key, _ip_key = _partner_login_rate_limit_keys(username)
    with _partner_login_rate_limit_lock:
        _partner_login_attempts.pop(account_key, None)


def _partner_auth_file_fingerprint(path: str) -> Optional[Tuple[int, int]]:
    try:
        stat_result = os.stat(path)
        return stat_result.st_mtime_ns, stat_result.st_size
    except OSError:
        return None


def _store_partner_auth_index(
    payload: Dict[str, Any],
    path: Optional[str] = None,
    fingerprint: Optional[Tuple[int, int]] = None,
) -> None:
    """Keep only the fields required for authentication in process memory."""
    auth_path = os.path.abspath(path or DATA_FILE)
    user_fields = {
        "id", "partner_id", "email", "role", "active", "password_hash",
        "invitation_activated_at", "last_login_at",
    }
    partner_fields = {"id", "name", "status"}
    invitation_fields = {
        "id", "user_id", "partner_id", "token_hash", "token_encrypted",
        "expires_at", "used_at", "cancelled_at",
    }
    users = [
        {key: value for key, value in item.items() if key in user_fields}
        for item in payload.get("users", [])
        if isinstance(item, dict)
    ]
    partners = [
        {key: value for key, value in item.items() if key in partner_fields}
        for item in payload.get("partners", [])
        if isinstance(item, dict)
    ]
    invitations = [
        {key: value for key, value in item.items() if key in invitation_fields}
        for item in payload.get("invitations", [])
        if isinstance(item, dict)
    ]
    with _partner_auth_index_lock:
        _partner_auth_index_cache.update({
            "path": auth_path,
            "fingerprint": fingerprint if fingerprint is not None else _partner_auth_file_fingerprint(auth_path),
            "users": users,
            "partners": partners,
            "invitations": invitations,
        })


def _load_partner_auth_data() -> Dict[str, List[Dict[str, Any]]]:
    """Load a small cached auth index without running business normalizers."""
    if _partner_postgres_active():
        if not _partner_postgres_configured():
            raise PartnerPostgresUnavailable(
                "PARTNER_DATABASE_URL absent en mode active"
            )
        # PostgreSQL exposes only the indexed partner/authentication tables;
        # no session, trainee, invoice or document payload is materialised.
        return _get_partner_postgres_store().load_auth_data()
    auth_path = os.path.abspath(DATA_FILE)
    fingerprint = _partner_auth_file_fingerprint(auth_path)
    with _partner_auth_index_lock:
        if (
            _partner_auth_index_cache.get("path") == auth_path
            and _partner_auth_index_cache.get("fingerprint") == fingerprint
        ):
            return {
                "users": [dict(item) for item in _partner_auth_index_cache.get("users", [])],
                "partners": [dict(item) for item in _partner_auth_index_cache.get("partners", [])],
                "invitations": [dict(item) for item in _partner_auth_index_cache.get("invitations", [])],
            }
        # Keep the lock across the cold load so concurrent first logins do not
        # materialize several copies of the full JSON document at once.
        payload: Optional[Dict[str, Any]] = None
        stable_fingerprint: Optional[Tuple[int, int]] = None
        for _attempt in range(3):
            before_read = _partner_auth_file_fingerprint(auth_path)
            candidate = _load_valid_json_payload(DATA_FILE)
            after_read = _partner_auth_file_fingerprint(auth_path)
            if isinstance(candidate, dict) and before_read == after_read:
                payload = candidate
                stable_fingerprint = after_read
                break
        if payload is None:
            return {"users": [], "partners": []}
        _store_partner_auth_index(payload, auth_path, fingerprint=stable_fingerprint)
        return {
            "users": [dict(item) for item in _partner_auth_index_cache.get("users", [])],
            "partners": [dict(item) for item in _partner_auth_index_cache.get("partners", [])],
            "invitations": [dict(item) for item in _partner_auth_index_cache.get("invitations", [])],
        }


def _integrale_partner() -> Dict[str, Any]:
    now = _now_iso() if "_now_iso" in globals() else datetime.datetime.utcnow().isoformat() + "Z"
    return {
        "id": INTEGRALE_PARTNER_ID,
        "name": "IntÃ©grale Connect",
        "legal_name": "IntÃ©grale SÃ©curitÃ© Formations",
        "siret": "",
        "address": "54 chemin du Carreou",
        "postal_code": "83480",
        "city": "Puget-sur-Argens",
        "phone": "04 22 47 07 68",
        "email": "integralesecuriteformations@gmail.com",
        "contact_first_name": "",
        "contact_last_name": "",
        "logo_path": "",
        "status": "active",
        "subscription_plan": "legacy",
        "max_users": 10,
        "storage_limit": 0,
        "trial_ends_at": "",
        "subscription_started_at": now,
        "subscription_ends_at": "",
        "internal_notes": "Partenaire crÃ©Ã© automatiquement pour rattacher les donnÃ©es historiques.",
        "created_at": now,
        "updated_at": now,
    }


def _append_activity_log(data: Dict[str, Any], action: str, resource_type: str = "", resource_id: str = "", partner_id: str = "", details: Optional[Dict[str, Any]] = None) -> None:
    logs = data.setdefault("activity_logs", [])
    safe_details = dict(details or {})
    for secret_key in ("token", "password", "secret"):
        safe_details.pop(secret_key, None)
    logs.append({
        "id": str(uuid.uuid4()),
        "user": (session.get("admin_username") if has_request_context() else "system") or "system",
        "partner_id": partner_id or _current_partner_id() or "",
        "action": action,
        "resource_type": resource_type,
        "resource_id": str(resource_id or ""),
        "created_at": _now_iso() if "_now_iso" in globals() else datetime.datetime.utcnow().isoformat() + "Z",
        "ip": (request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip() if has_request_context() else ""),
        "details": safe_details,
    })
    del logs[:-1000]


def _ensure_multi_partner_payload(data: Dict[str, Any]) -> bool:
    changed = False
    if not isinstance(data.get("partners"), list):
        data["partners"] = []
        changed = True
    if not any(p.get("id") == INTEGRALE_PARTNER_ID for p in data["partners"] if isinstance(p, dict)):
        data["partners"].append(_integrale_partner())
        changed = True
    if not isinstance(data.get("users"), list):
        data["users"] = []
        changed = True
    if not isinstance(data.get("invitations"), list):
        data["invitations"] = []
        changed = True
    if not isinstance(data.get("activity_logs"), list):
        data["activity_logs"] = []
        changed = True
    for s in data.get("sessions") or []:
        if isinstance(s, dict) and not s.get("partner_id"):
            s["partner_id"] = INTEGRALE_PARTNER_ID; changed = True
        for t in _session_trainees_list(s) if isinstance(s, dict) else []:
            if isinstance(t, dict) and not t.get("partner_id"):
                t["partner_id"] = s.get("partner_id") or INTEGRALE_PARTNER_ID; changed = True
    tenant_collection_keys = {
        "positioning_tests", "notifications_edof", "notifications_financement_refuse",
        "notifications_prelevements", "notifications_prelevement_non_valides",
        "notifications_phone_relances", "notifications_vae_relances",
        "notifications_cnaps_pre_relances", "notifications_test_fr",
        "notifications_convention_unsigned", "notifications_vtc_books",
        "notifications_admin",
    }
    tenant_collection_keys.update(globals().get("PARTNER_SCOPED_COLLECTION_KEYS", set()))
    for key in tenant_collection_keys:
        for item in data.get(key) or []:
            if isinstance(item, dict) and not item.get("partner_id"):
                item["partner_id"] = INTEGRALE_PARTNER_ID; changed = True
    return changed


PARTNER_SCOPED_COLLECTION_KEYS = {
    "sessions",
    "activity_logs",
    "admin_push_subscriptions",
    "billing_lines",
    "subscription_requests",
    "positioning_tests",
    "notifications_edof",
    "notifications_financement_refuse",
    "notifications_prelevements",
    "notifications_prelevement_non_valides",
    "notifications_phone_relances",
    "notifications_vae_relances",
    "notifications_cnaps_pre_relances",
    "notifications_test_fr",
    "notifications_convention_unsigned",
    "notifications_vtc_books",
    "notifications_admin",
    "cnaps_pending_imports",
    "cnaps_public_annuaire_statuses",
    "cnaps_status_change_notifications",
    "cnaps_tracking_manual_nubs",
    "wedof_links",
    "wedof_folder_cache",
}
PARTNER_SCOPED_VALUE_KEYS = {
    "sales_tracking",
    "ssiap_diploma_sequences",
    "daily_recap_sent_dates",
    "cnaps_tracking_deleted_keys",
}
PARTNER_VISIBLE_FIELDS = {
    "id", "name", "legal_name", "siret", "activity_declaration_number",
    "address", "address_extra", "postal_code", "city", "country",
    "contact_first_name", "contact_last_name", "contact_role", "email",
    "phone", "website", "logo_url", "logo_path", "logo_filename",
    "status", "subscription_plan", "max_users", "storage_limit",
    "trial_ends_at", "subscription_started_at", "subscription_ends_at",
    "enabled_modules", "subscription", "created_at", "updated_at",
}
PARTNER_VISIBLE_USER_FIELDS = {
    "id", "partner_id", "email", "first_name", "last_name", "role", "active",
    "invitation_activated_at", "created_at", "updated_at", "last_login_at",
}
PARTNER_SELF_EDITABLE_FIELDS = {
    "name", "legal_name", "siret", "activity_declaration_number", "address",
    "address_extra", "postal_code", "city", "country", "contact_first_name",
    "contact_last_name", "contact_role", "email", "phone", "website",
    "logo_url", "logo_path", "logo_filename", "updated_at",
}
PARTNER_SUBSCRIPTION_USAGE_FIELDS = {
    "trainee_usage_count", "trainee_usage_migrated_at",
}


def _partner_tenant_values(data: Dict[str, Any], partner_id: str) -> Dict[str, Any]:
    container = data.get("partner_scoped_data")
    if not isinstance(container, dict):
        return {}
    values = container.get(partner_id)
    return values if isinstance(values, dict) else {}


def _filter_data_for_partner(data: Dict[str, Any], partner_id: str) -> Dict[str, Any]:
    """Build a deny-by-default tenant view of the canonical JSON payload.

    Never start from ``dict(data)`` here: doing so made every newly introduced
    top-level key visible to every partner until somebody remembered to add a
    filter.  Only explicitly tenant-aware collections and values cross this
    boundary.
    """
    partner_id = str(partner_id or "")
    scoped: Dict[str, Any] = {}
    own_partner = next((
        item for item in data.get("partners", [])
        if isinstance(item, dict) and str(item.get("id") or "") == partner_id
    ), None)
    scoped["partners"] = [
        {key: value for key, value in own_partner.items() if key in PARTNER_VISIBLE_FIELDS}
    ] if own_partner else []
    scoped["users"] = [
        {key: value for key, value in user.items() if key in PARTNER_VISIBLE_USER_FIELDS}
        for user in data.get("users", [])
        if isinstance(user, dict) and str(user.get("partner_id") or "") == partner_id
    ]
    # Invitations contain reusable encrypted activation tokens and are managed
    # only from the platform administration area.
    scoped["invitations"] = []
    for key in PARTNER_SCOPED_COLLECTION_KEYS:
        values = data.get(key)
        if not isinstance(values, list):
            scoped[key] = []
            continue
        scoped_values = [
            item for item in values
            if isinstance(item, dict) and str(item.get("partner_id") or "") == partner_id
        ]
        if key == "sessions":
            safe_sessions = []
            for item in scoped_values:
                safe_session = dict(item)
                for trainee_key in ("trainees", "stagiaires"):
                    trainees = item.get(trainee_key)
                    if isinstance(trainees, list):
                        safe_session[trainee_key] = [
                            trainee for trainee in trainees
                            if isinstance(trainee, dict)
                            and str(trainee.get("partner_id") or partner_id) == partner_id
                        ]
                safe_sessions.append(safe_session)
            scoped_values = safe_sessions
        scoped[key] = scoped_values
    # Tenant routes may append audit events, but they do not need the existing
    # log history (which can contain IP addresses and other operational data).
    scoped["activity_logs"] = []

    tenant_values = _partner_tenant_values(data, partner_id)
    for key in PARTNER_SCOPED_VALUE_KEYS:
        if partner_id == INTEGRALE_PARTNER_ID and key in data:
            scoped[key] = data[key]
        elif key in tenant_values:
            scoped[key] = tenant_values[key]
        else:
            scoped[key] = [] if key.endswith("_dates") or key.endswith("_keys") else {}

    legacy_dismissed = data.get("notifications_admin_dismissed_schedule_keys")
    scoped["notifications_admin_dismissed_schedule_keys"] = [
        value for value in legacy_dismissed or []
        if isinstance(value, str) and value.startswith(f"{partner_id}:")
    ]
    return scoped


def _merge_partner_scoped_payload(
    scoped: Dict[str, Any], partner_id: str, current: Optional[Dict[str, Any]] = None,
    *, global_payload: bool = True,
) -> Dict[str, Any]:
    """Merge one tenant view while preserving every other tenant atomically."""
    current = current if isinstance(current, dict) else (_load_valid_json_payload(DATA_FILE) or _empty_data_payload())
    if global_payload:
        _ensure_multi_partner_payload(current)
    else:
        for key in ("partners", "users", "invitations", "activity_logs"):
            if not isinstance(current.get(key), list):
                current[key] = []
    partner_id = str(partner_id or "")

    _preserve_aps_elearning_report_state(scoped, current)
    for key in PARTNER_SCOPED_COLLECTION_KEYS - {"activity_logs"}:
        if not isinstance(scoped.get(key), list):
            continue
        replacements = []
        for item in scoped[key]:
            if not isinstance(item, dict):
                continue
            item["partner_id"] = partner_id
            if key == "sessions":
                for trainee in _session_trainees_list(item):
                    if isinstance(trainee, dict):
                        trainee["partner_id"] = partner_id
            replacements.append(item)
        canonical_values = current.get(key) if isinstance(current.get(key), list) else []
        current[key] = [
            item for item in canonical_values
            if not (isinstance(item, dict) and str(item.get("partner_id") or "") == partner_id)
        ] + replacements

    # Audit history is append-only from a tenant request.  A stale form or a
    # malicious payload cannot delete or rewrite prior events.
    canonical_logs = current.get("activity_logs") if isinstance(current.get("activity_logs"), list) else []
    known_log_ids = {str(item.get("id") or "") for item in canonical_logs if isinstance(item, dict)}
    for item in scoped.get("activity_logs", []) if isinstance(scoped.get("activity_logs"), list) else []:
        if not isinstance(item, dict) or str(item.get("id") or "") in known_log_ids:
            continue
        item["partner_id"] = partner_id
        canonical_logs.append(item)
        known_log_ids.add(str(item.get("id") or ""))
    current["activity_logs"] = canonical_logs[-1000:]

    if isinstance(scoped.get("partners"), list):
        scoped_partner = next((p for p in scoped.get("partners", []) if isinstance(p, dict) and p.get("id") == partner_id), None)
        if scoped_partner:
            canonical_partner = next((
                p for p in current.get("partners", [])
                if isinstance(p, dict) and str(p.get("id") or "") == partner_id
            ), None)
            if canonical_partner:
                for key in PARTNER_SELF_EDITABLE_FIELDS:
                    if key in scoped_partner:
                        canonical_partner[key] = scoped_partner[key]
                scoped_subscription = scoped_partner.get("subscription")
                canonical_subscription = canonical_partner.get("subscription")
                if isinstance(scoped_subscription, dict) and isinstance(canonical_subscription, dict):
                    for key in PARTNER_SUBSCRIPTION_USAGE_FIELDS:
                        if key in scoped_subscription:
                            canonical_subscription[key] = scoped_subscription[key]

    if partner_id == INTEGRALE_PARTNER_ID:
        for key in PARTNER_SCOPED_VALUE_KEYS:
            if key in scoped:
                current[key] = scoped[key]
    else:
        container = current.setdefault("partner_scoped_data", {})
        if not isinstance(container, dict):
            container = {}
            current["partner_scoped_data"] = container
        tenant_values = container.setdefault(partner_id, {})
        if not isinstance(tenant_values, dict):
            tenant_values = {}
            container[partner_id] = tenant_values
        for key in PARTNER_SCOPED_VALUE_KEYS:
            if key in scoped:
                tenant_values[key] = scoped[key]

    dismissed = current.get("notifications_admin_dismissed_schedule_keys")
    dismissed = dismissed if isinstance(dismissed, list) else []
    current["notifications_admin_dismissed_schedule_keys"] = [
        value for value in dismissed
        if not (isinstance(value, str) and value.startswith(f"{partner_id}:"))
    ] + [
        value for value in scoped.get("notifications_admin_dismissed_schedule_keys", [])
        if isinstance(value, str) and value.startswith(f"{partner_id}:")
    ]
    return current


def _partner_bundle_from_canonical(data: Dict[str, Any], partner_id: str) -> Dict[str, Any]:
    """Extract one complete external tenant without any other tenant data."""
    partner_id = str(partner_id or "").strip()
    partner = next((
        copy.deepcopy(item) for item in data.get("partners", [])
        if isinstance(item, dict) and str(item.get("id") or "") == partner_id
    ), None)
    if not partner or partner_id == INTEGRALE_PARTNER_ID:
        raise PartnerPostgresValidationError("partenaire externe introuvable")
    bundle = _filter_data_for_partner(data, partner_id)
    # PostgreSQL keeps the complete protected records. Tenant-facing reads are
    # filtered again before leaving load_data(), so hashes, tokens and internal
    # notes never cross the application boundary.
    bundle["partners"] = [partner]
    bundle["users"] = [
        copy.deepcopy(item) for item in data.get("users", [])
        if isinstance(item, dict) and str(item.get("partner_id") or "") == partner_id
    ]
    bundle["invitations"] = [
        copy.deepcopy(item) for item in data.get("invitations", [])
        if isinstance(item, dict) and str(item.get("partner_id") or "") == partner_id
    ]
    return bundle


def _partner_bundle_checksum(bundle: Dict[str, Any]) -> str:
    normalized = copy.deepcopy(bundle)
    for key in ("partners", "users", "invitations"):
        if isinstance(normalized.get(key), list):
            normalized[key] = sorted(
                normalized[key],
                key=lambda item: str(item.get("id") or "") if isinstance(item, dict) else "",
            )
    return hashlib.sha256(_partner_canonical_json(normalized).encode("utf-8")).hexdigest()


def _partner_duplicate_email_diagnostics(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Describe legacy duplicate logins without exposing e-mail addresses.

    A duplicate account must stop the migration because authentication by
    e-mail would otherwise be ambiguous.  The private Render log still needs
    enough non-secret metadata to select the correct record for a backed-up,
    explicit repair.
    """
    invitations_by_user: Dict[str, int] = {}
    for invitation in bundle.get("invitations", []) or []:
        if not isinstance(invitation, dict):
            continue
        user_id = str(invitation.get("user_id") or "").strip()
        if user_id:
            invitations_by_user[user_id] = invitations_by_user.get(user_id, 0) + 1

    groups: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    for position, user in enumerate(bundle.get("users", []) or []):
        if not isinstance(user, dict):
            continue
        normalized = str(user.get("email") or "").strip().lower()
        if normalized:
            groups.setdefault(normalized, []).append((position, user))

    diagnostics: List[Dict[str, Any]] = []
    for normalized, records in groups.items():
        if len(records) < 2:
            continue
        all_keys = sorted({str(key) for _position, user in records for key in user})
        differing_fields = [
            key for key in all_keys
            if len({_partner_canonical_json(user.get(key)) for _position, user in records}) > 1
        ]
        diagnostics.append({
            "email_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16],
            "differing_fields": differing_fields,
            "records": [
                {
                    "position": position,
                    "id": str(user.get("id") or ""),
                    "role": str(user.get("role") or ""),
                    "active": bool(user.get("active", True)),
                    "has_password_hash": bool(str(user.get("password_hash") or "")),
                    "created_at": str(user.get("created_at") or ""),
                    "updated_at": str(user.get("updated_at") or ""),
                    "last_login_at": str(user.get("last_login_at") or ""),
                    "invitation_count": invitations_by_user.get(str(user.get("id") or ""), 0),
                }
                for position, user in records
            ],
        })
    return diagnostics


def _partner_exact_duplicate_repair_spec() -> Optional[Tuple[str, str, str, int]]:
    """Parse the deliberately narrow one-shot legacy repair selector.

    Format: ``partner_id:user_id:email_sha256_prefix:expected_occurrences``.
    Requiring every observed value prevents an accidentally retained flag from
    modifying another account in a later deployment.
    """
    raw = str(
        os.environ.get("PARTNER_POSTGRES_REPAIR_EXACT_USER_DUPLICATES") or ""
    ).strip()
    if not raw:
        return None
    parts = [part.strip() for part in raw.split(":")]
    if len(parts) != 4 or not all(parts):
        raise PartnerPostgresValidationError(
            "sÃ©lecteur de rÃ©paration des doublons partenaire invalide"
        )
    partner_id, user_id, email_hash, expected_raw = parts
    if partner_id == INTEGRALE_PARTNER_ID:
        raise PartnerPostgresValidationError(
            "la rÃ©paration ne peut pas cibler le partenaire IntÃ©grale"
        )
    if not re.fullmatch(r"[0-9a-f]{16}", email_hash.lower()):
        raise PartnerPostgresValidationError(
            "empreinte e-mail de rÃ©paration invalide"
        )
    try:
        expected_occurrences = int(expected_raw)
    except ValueError as exc:
        raise PartnerPostgresValidationError(
            "nombre attendu de doublons partenaire invalide"
        ) from exc
    if expected_occurrences < 2 or expected_occurrences > 100:
        raise PartnerPostgresValidationError(
            "nombre attendu de doublons partenaire hors limites"
        )
    return partner_id, user_id, email_hash.lower(), expected_occurrences


def _repair_exact_partner_user_duplicates(
    data: Dict[str, Any], repair_spec: Tuple[str, str, str, int],
) -> Dict[str, Any]:
    """Keep one of several byte-for-byte equivalent legacy user records.

    No fuzzy merge is permitted: partner, user ID, anonymised e-mail hash and
    occurrence count must match the operator-provided selector, and every
    selected record must contain exactly the same JSON fields and values.
    Invitations are left untouched because they already reference the shared
    user ID.
    """
    partner_id, user_id, expected_email_hash, expected_occurrences = repair_spec
    users = data.get("users")
    if not isinstance(users, list):
        raise PartnerPostgresValidationError(
            "collection utilisateurs absente avant rÃ©paration"
        )
    if not any(
        isinstance(partner, dict)
        and str(partner.get("id") or "") == partner_id
        for partner in data.get("partners", []) or []
    ):
        raise PartnerPostgresValidationError(
            "partenaire ciblÃ© absent avant rÃ©paration"
        )

    matching_positions = [
        position
        for position, user in enumerate(users)
        if isinstance(user, dict)
        and str(user.get("partner_id") or "") == partner_id
        and str(user.get("id") or "") == user_id
    ]
    if len(matching_positions) != expected_occurrences:
        raise PartnerPostgresValidationError(
            "nombre de doublons partenaire diffÃ©rent de la valeur attendue"
        )
    selected = [users[position] for position in matching_positions]
    canonical_record = _partner_canonical_json(selected[0])
    if any(_partner_canonical_json(user) != canonical_record for user in selected[1:]):
        raise PartnerPostgresValidationError(
            "les comptes partenaire ciblÃ©s ne sont pas strictement identiques"
        )
    normalized_email = str(selected[0].get("email") or "").strip().lower()
    actual_email_hash = hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()[:16]
    if not normalized_email or not hmac.compare_digest(actual_email_hash, expected_email_hash):
        raise PartnerPostgresValidationError(
            "empreinte e-mail diffÃ©rente de la valeur attendue"
        )

    first_position = matching_positions[0]
    duplicate_positions = set(matching_positions[1:])
    data["users"] = [
        user for position, user in enumerate(users) if position not in duplicate_positions
    ]
    remaining = [
        user for user in data["users"]
        if isinstance(user, dict)
        and str(user.get("partner_id") or "") == partner_id
        and str(user.get("id") or "") == user_id
    ]
    if len(remaining) != 1 or _partner_canonical_json(remaining[0]) != canonical_record:
        raise PartnerPostgresValidationError(
            "vÃ©rification en mÃ©moire de la rÃ©paration partenaire Ã©chouÃ©e"
        )
    return {
        "partner_id": partner_id,
        "user_id": user_id,
        "email_hash": actual_email_hash,
        "expected_occurrences": expected_occurrences,
        "kept_position": first_position,
        "removed": len(duplicate_positions),
    }


def _repair_exact_partner_user_duplicates_on_disk(
    repair_spec: Tuple[str, str, str, int],
) -> Dict[str, Any]:
    """Apply and verify the guarded repair while holding the JSON file lock."""
    result: Dict[str, Any] = {}

    def repair_current_payload(_payload: Dict[str, Any]) -> Dict[str, Any]:
        current = _load_valid_json_payload(DATA_FILE)
        if not isinstance(current, dict):
            raise PartnerPostgresValidationError(
                "data.json illisible pendant la rÃ©paration partenaire"
            )
        _ensure_multi_partner_payload(current)
        result.update(_repair_exact_partner_user_duplicates(current, repair_spec))
        return current

    _write_json_with_backups(
        DATA_FILE,
        {},
        _data_lock,
        payload_transform=repair_current_payload,
    )
    verified = _load_valid_json_payload(DATA_FILE)
    if not isinstance(verified, dict):
        raise PartnerPostgresValidationError(
            "data.json illisible aprÃ¨s rÃ©paration partenaire"
        )
    partner_id, user_id, _email_hash, _expected_occurrences = repair_spec
    matching = [
        user for user in verified.get("users", []) or []
        if isinstance(user, dict)
        and str(user.get("partner_id") or "") == partner_id
        and str(user.get("id") or "") == user_id
    ]
    if len(matching) != 1:
        raise PartnerPostgresValidationError(
            "vÃ©rification sur disque de la rÃ©paration partenaire Ã©chouÃ©e"
        )
    return result


def _overlay_partner_bundle(
    canonical: Dict[str, Any], bundle: Dict[str, Any], partner_id: str,
) -> Dict[str, Any]:
    """Replace exactly one external tenant in a platform/admin data view."""
    partner_id = str(partner_id or "").strip()
    partner = next((
        copy.deepcopy(item) for item in bundle.get("partners", [])
        if isinstance(item, dict) and str(item.get("id") or "") == partner_id
    ), None)
    if not partner:
        raise PartnerPostgresValidationError("bundle PostgreSQL sans partenaire")

    for key in ("partners", "users", "invitations"):
        values = canonical.get(key) if isinstance(canonical.get(key), list) else []
        canonical[key] = [
            item for item in values
            if not (
                isinstance(item, dict)
                and str(item.get("id") if key == "partners" else item.get("partner_id") or "") == partner_id
            )
        ]
    canonical["partners"].append(partner)
    canonical["users"].extend([
        copy.deepcopy(item) for item in bundle.get("users", [])
        if isinstance(item, dict) and str(item.get("partner_id") or "") == partner_id
    ])
    canonical["invitations"].extend([
        copy.deepcopy(item) for item in bundle.get("invitations", [])
        if isinstance(item, dict) and str(item.get("partner_id") or "") == partner_id
    ])

    for key in PARTNER_SCOPED_COLLECTION_KEYS:
        canonical_values = canonical.get(key) if isinstance(canonical.get(key), list) else []
        canonical[key] = [
            item for item in canonical_values
            if not (isinstance(item, dict) and str(item.get("partner_id") or "") == partner_id)
        ]
        canonical[key].extend([
            copy.deepcopy(item) for item in bundle.get(key, [])
            if isinstance(item, dict) and str(item.get("partner_id") or "") == partner_id
        ])

    container = canonical.setdefault("partner_scoped_data", {})
    if not isinstance(container, dict):
        container = {}
        canonical["partner_scoped_data"] = container
    container[partner_id] = {
        key: copy.deepcopy(bundle[key])
        for key in PARTNER_SCOPED_VALUE_KEYS if key in bundle
    }

    dismissed = canonical.get("notifications_admin_dismissed_schedule_keys")
    dismissed = dismissed if isinstance(dismissed, list) else []
    canonical["notifications_admin_dismissed_schedule_keys"] = [
        value for value in dismissed
        if not (isinstance(value, str) and value.startswith(f"{partner_id}:"))
    ] + [
        value for value in bundle.get("notifications_admin_dismissed_schedule_keys", [])
        if isinstance(value, str) and value.startswith(f"{partner_id}:")
    ]
    return canonical


def _overlay_partner_postgres_for_platform(data: Dict[str, Any]) -> Dict[str, Any]:
    """Merge authoritative external tenants into a privileged platform view."""
    if not _partner_postgres_active():
        return data
    try:
        baselines: Dict[str, Dict[str, Any]] = {}
        for bundle, version in _get_partner_postgres_store().load_all_bundles():
            partner = next((
                item for item in bundle.get("partners", []) if isinstance(item, dict)
            ), None)
            partner_id = str((partner or {}).get("id") or "")
            if partner_id and partner_id != INTEGRALE_PARTNER_ID:
                _overlay_partner_bundle(data, bundle, partner_id)
                baselines[partner_id] = {
                    "version": int(version),
                    "checksum": _partner_bundle_checksum(bundle),
                }
        if has_request_context():
            g.partner_postgres_platform_baselines = baselines
    except PartnerPostgresError:
        # Internal IntÃ©grale work must remain available during a partner DB
        # outage. External logins and tenant routes still fail closed.
        app.logger.exception("partner_postgres platform_overlay_unavailable")
    return data


def _persist_changed_partner_postgres_from_platform(data: Dict[str, Any]) -> None:
    """Persist only DB tenant bundles changed by a global/public request.

    Public trainee links do not carry an admin partner cookie. Their handlers
    historically load the global document, update one trainee and save it. A
    per-request baseline lets those existing routes keep working while an
    optimistic version check prevents a stale global request from overwriting
    a newer partner write.
    """
    if not _partner_postgres_active() or not has_request_context():
        return
    baselines = getattr(g, "partner_postgres_platform_baselines", None)
    if not isinstance(baselines, dict):
        return
    store = _get_partner_postgres_store()
    for partner_id, baseline in list(baselines.items()):
        if not isinstance(baseline, dict):
            continue
        try:
            candidate = _partner_bundle_from_canonical(data, partner_id)
        except PartnerPostgresValidationError:
            # Deletion is always explicit through the protected admin route;
            # a generic save can never erase a whole PostgreSQL tenant.
            continue
        checksum = _partner_bundle_checksum(candidate)
        if checksum == str(baseline.get("checksum") or ""):
            continue

        def replace_bundle(_current: Dict[str, Any]) -> Dict[str, Any]:
            return copy.deepcopy(candidate)

        _updated, version = store.mutate_bundle(
            partner_id,
            replace_bundle,
            expected_version=int(baseline.get("version") or 0),
        )
        baselines[partner_id] = {"version": version, "checksum": checksum}


def _load_partner_postgres_bundle(partner_id: str) -> Tuple[Dict[str, Any], int]:
    if not _partner_postgres_configured():
        raise PartnerPostgresUnavailable("PARTNER_DATABASE_URL absent en mode active")
    bundle, version = _get_partner_postgres_store().load_bundle(partner_id)
    if has_request_context():
        versions = getattr(g, "partner_postgres_versions", None)
        if not isinstance(versions, dict):
            versions = {}
            g.partner_postgres_versions = versions
        versions[partner_id] = version
    return bundle, version


def _sync_partner_postgres_from_canonical(
    canonical: Dict[str, Any], *, strict: bool = False,
) -> Dict[str, Any]:
    """Idempotently copy every external JSON tenant into PostgreSQL."""
    report: Dict[str, Any] = {"ok": True, "imported": [], "unchanged": [], "errors": []}
    if not _partner_postgres_configured():
        error = "PARTNER_DATABASE_URL absent"
        if strict:
            raise PartnerPostgresUnavailable(error)
        report.update({"ok": False, "errors": [error]})
        return report
    existing_checksums: Dict[str, str] = {}
    try:
        store = _get_partner_postgres_store()
        existing_checksums = {
            str(item.get("partner_id") or ""): str(item.get("source_checksum") or "")
            for item in store.stats().get("tenants", [])
            if isinstance(item, dict)
        }
        expected_checksums: Dict[str, str] = {}
        expected_users = 0
        expected_invitations = 0
        for partner in canonical.get("partners", []):
            if not isinstance(partner, dict):
                continue
            partner_id = str(partner.get("id") or "")
            if not partner_id or partner_id == INTEGRALE_PARTNER_ID:
                continue
            try:
                bundle = _partner_bundle_from_canonical(canonical, partner_id)
                checksum = _partner_bundle_checksum(bundle)
                expected_checksums[partner_id] = checksum
                expected_users += len(bundle.get("users", []))
                expected_invitations += len(bundle.get("invitations", []))
                if existing_checksums.get(partner_id) == checksum:
                    report["unchanged"].append(partner_id)
                    continue
                duplicate_diagnostics = _partner_duplicate_email_diagnostics(bundle)
                if duplicate_diagnostics:
                    partner_name = re.sub(
                        r"[\r\n\t]+", " ", str(partner.get("name") or "")
                    ).strip()[:120]
                    app.logger.error(
                        "partner_postgres duplicate_auth_email partner_id=%s "
                        "partner_name=%s details=%s",
                        partner_id,
                        partner_name,
                        json.dumps(
                            duplicate_diagnostics,
                            ensure_ascii=True,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    )
                store.import_bundle(
                    partner_id, bundle, source_checksum=checksum,
                )
                reloaded, _version = store.load_bundle(partner_id)
                if _partner_bundle_checksum(reloaded) != checksum:
                    raise PartnerPostgresValidationError(
                        "la vÃ©rification aprÃ¨s import ne correspond pas"
                    )
                report["imported"].append(partner_id)
            except PartnerPostgresError as exc:
                report["ok"] = False
                report["errors"].append({
                    "partner_id": partner_id,
                    "error": type(exc).__name__,
                })
                if strict:
                    raise
        if strict:
            # Re-read every tenant, including rows skipped as unchanged, then
            # compare aggregate indexed-table counts. This is the final gate
            # before an operator may switch the source to active mode.
            for partner_id, checksum in expected_checksums.items():
                reloaded, _version = store.load_bundle(partner_id)
                if _partner_bundle_checksum(reloaded) != checksum:
                    raise PartnerPostgresValidationError(
                        "la vÃ©rification complÃ¨te aprÃ¨s import ne correspond pas"
                    )
            stats = store.stats()
            actual_partner_ids = {
                str(item.get("partner_id") or "")
                for item in stats.get("tenants", [])
                if isinstance(item, dict)
            }
            if (
                actual_partner_ids != set(expected_checksums)
                or int(stats.get("partners") or 0) != len(expected_checksums)
                or int(stats.get("users") or 0) != expected_users
                or int(stats.get("invitations") or 0) != expected_invitations
            ):
                raise PartnerPostgresValidationError(
                    "les totaux PostgreSQL ne correspondent pas au miroir partenaire"
                )
            report["stats"] = {
                "partners": len(expected_checksums),
                "users": expected_users,
                "invitations": expected_invitations,
                "checksums_verified": len(expected_checksums),
            }
    except PartnerPostgresError:
        if strict:
            raise
        report["ok"] = False
        if not report["errors"]:
            report["errors"].append("postgres_unavailable")
    return report


def _bootstrap_partner_postgres_shadow() -> Dict[str, Any]:
    """Back up JSON then perform an idempotent shadow import at startup."""
    global _partner_postgres_bootstrap_done
    if not _partner_postgres_shadow():
        return {"ok": True, "skipped": "mode_not_shadow"}
    enabled = str(os.environ.get("PARTNER_POSTGRES_AUTO_MIGRATE") or "0").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return {"ok": True, "skipped": "auto_migrate_disabled"}
    with _partner_postgres_bootstrap_lock:
        if _partner_postgres_bootstrap_done:
            return {"ok": True, "skipped": "already_done"}
        canonical = _load_valid_json_payload(DATA_FILE)
        if not isinstance(canonical, dict):
            raise PartnerPostgresValidationError("data.json illisible avant migration")
        _ensure_multi_partner_payload(canonical)
        snapshot = _force_backup_snapshot(DATA_FILE, reason="pre-partner-postgres")
        if not snapshot:
            raise PartnerPostgresValidationError(
                "sauvegarde data.json impossible avant migration"
            )
        repair_report: Optional[Dict[str, Any]] = None
        repair_spec = _partner_exact_duplicate_repair_spec()
        if repair_spec:
            repair_report = _repair_exact_partner_user_duplicates_on_disk(repair_spec)
            canonical = _load_valid_json_payload(DATA_FILE)
            if not isinstance(canonical, dict):
                raise PartnerPostgresValidationError(
                    "data.json illisible aprÃ¨s rÃ©paration partenaire"
                )
            _ensure_multi_partner_payload(canonical)
            app.logger.warning(
                "partner_postgres exact_duplicate_user_repaired "
                "partner_id=%s user_id=%s email_hash=%s removed=%s backup=%s",
                repair_report["partner_id"],
                repair_report["user_id"],
                repair_report["email_hash"],
                repair_report["removed"],
                os.path.basename(snapshot),
            )
        report = _sync_partner_postgres_from_canonical(canonical, strict=True)
        _partner_postgres_bootstrap_done = True
        app.logger.warning(
            "partner_postgres shadow_bootstrap ok=%s imported=%s unchanged=%s "
            "repaired_duplicates=%s db_partners=%s db_users=%s "
            "db_invitations=%s checksums_verified=%s backup=%s",
            bool(report.get("ok")),
            len(report.get("imported", [])),
            len(report.get("unchanged", [])),
            int((repair_report or {}).get("removed") or 0),
            int((report.get("stats") or {}).get("partners") or 0),
            int((report.get("stats") or {}).get("users") or 0),
            int((report.get("stats") or {}).get("invitations") or 0),
            int((report.get("stats") or {}).get("checksums_verified") or 0),
            os.path.basename(snapshot),
        )
        return {
            **report,
            "repair": repair_report,
            "backup": os.path.basename(snapshot),
        }




def _verify_partner_postgres_initial_cutover() -> Dict[str, Any]:
    """Read-only gate for the first active deployment, before serving traffic.

    Disable the one-deploy flag immediately after success: once active writes
    start, JSON is deliberately no longer the authoritative partner source.
    """
    enabled = str(os.environ.get("PARTNER_POSTGRES_VERIFY_INITIAL_CUTOVER") or "").lower()
    if not _partner_postgres_active() or enabled not in {"1", "true", "yes", "on"}:
        return {"ok": True, "skipped": "initial_cutover_check_disabled"}
    before = _partner_auth_file_fingerprint(DATA_FILE)
    canonical = _load_valid_json_payload(DATA_FILE)
    if before is None or not isinstance(canonical, dict):
        raise PartnerPostgresValidationError("source JSON illisible avant bascule")
    _ensure_multi_partner_payload(canonical)
    store = _get_partner_postgres_store()
    expected_ids = set()
    for partner in canonical.get("partners", []):
        if not isinstance(partner, dict):
            continue
        partner_id = str(partner.get("id") or "")
        if not partner_id or partner_id == INTEGRALE_PARTNER_ID:
            continue
        source = _partner_bundle_from_canonical(canonical, partner_id)
        target, _version = store.load_bundle(partner_id)
        if _partner_bundle_checksum(source) != _partner_bundle_checksum(target):
            raise PartnerPostgresValidationError("donnÃ©es partenaire modifiÃ©es depuis le miroir")
        expected_ids.add(partner_id)
    stats = store.stats()
    actual_ids = {str(row.get("partner_id") or "") for row in stats.get("tenants", [])}
    if actual_ids != expected_ids or _partner_auth_file_fingerprint(DATA_FILE) != before:
        raise PartnerPostgresValidationError("source partenaire modifiÃ©e pendant la vÃ©rification")
    app.logger.warning(
        "partner_postgres initial_cutover_verified mode=active partners=%s users=%s invitations=%s",
        len(expected_ids), int(stats.get("users") or 0), int(stats.get("invitations") or 0),
    )
    return {"ok": True, "partners_verified": len(expected_ids)}


def _data_file_diagnostics() -> Dict[str, Any]:
    path = os.path.abspath(DATA_FILE)
    return {
        "data_file": path,
        "persist_dir": os.path.abspath(PERSIST_DIR),
        "exists": os.path.exists(DATA_FILE),
    }


def _log_partner_auth_event(reason: str, data: Optional[Dict[str, Any]] = None, username: str = "", user: Optional[Dict[str, Any]] = None, partner: Optional[Dict[str, Any]] = None, password_ok: Optional[bool] = None) -> None:
    users = data.get("users", []) if isinstance(data, dict) else []
    wanted = (username or "").strip().lower()
    found = bool(user)
    app.logger.info(
        "partner_auth reason=%s data_file=%s persist_dir=%s exists=%s partner_users=%s searched_user_present=%s role=%s user_active=%s password_hash_present=%s password_check=%s partner_id_present=%s partner_status=%s",
        reason,
        os.path.abspath(DATA_FILE),
        os.path.abspath(PERSIST_DIR),
        os.path.exists(DATA_FILE),
        sum(1 for u in users if isinstance(u, dict) and u.get("role") == "partner_admin"),
        found if wanted else False,
        (user or {}).get("role") or "",
        bool((user or {}).get("active", True)) if user else "",
        bool((user or {}).get("password_hash")) if user else False,
        "success" if password_ok is True else ("failure" if password_ok is False else "not_checked"),
        bool((user or {}).get("partner_id")) if user else False,
        (partner or {}).get("status") or "",
    )

def _find_user_by_email(data: Dict[str, Any], email: str) -> Optional[Dict[str, Any]]:
    wanted = (email or "").strip().lower()
    return next((u for u in data.get("users", []) if isinstance(u, dict) and (u.get("email") or "").strip().lower() == wanted), None)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256((raw_token or "").encode("utf-8")).hexdigest()


def _password_is_valid(password: str) -> bool:
    return bool(password) and len(password) >= 10 and any(c.isalpha() for c in password) and any(c.isdigit() for c in password)


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000).hex()
    return f"pbkdf2_sha256$260000${salt}${digest}"


def _describe_password_hash(stored: str) -> Tuple[bool, str, str]:
    """Inspect a stored hash string without running a KDF."""
    stored = stored or ""
    if not stored:
        return False, "empty", "empty_hash"

    if stored.startswith("pbkdf2_sha256$"):
        parts = stored.split("$", 3)
        if len(parts) != 4 or not all(parts):
            return False, "pbkdf2_sha256", "incomplete_hash"
        _, rounds, salt, digest = parts
        try:
            rounds_int = int(rounds)
        except ValueError:
            return False, "pbkdf2_sha256", "non_numeric_iterations"
        if rounds_int < 1 or rounds_int > 600000:
            return False, "pbkdf2_sha256", "iterations_out_of_range"
        return True, "pbkdf2_sha256", "ok"

    method = stored.split("$", 1)[0]
    if method.startswith("pbkdf2:"):
        parts = method.split(":")
        if len(parts) != 3 or not all(parts):
            return False, "werkzeug_pbkdf2", "incomplete_hash"
        try:
            iterations = int(parts[2])
        except ValueError:
            return False, "werkzeug_pbkdf2", "non_numeric_iterations"
        if iterations < 1 or iterations > 600000:
            return False, "werkzeug_pbkdf2", "iterations_out_of_range"
        if len(stored.split("$")) != 3:
            return False, "werkzeug_pbkdf2", "incomplete_hash"
        return True, "werkzeug_pbkdf2", "ok"

    if method.startswith("scrypt"):
        parts = method.split(":")
        if len(parts) != 4 or not all(parts):
            return False, "werkzeug_scrypt", "incomplete_hash"
        try:
            n, r, p = (int(value) for value in parts[1:])
        except ValueError:
            return False, "werkzeug_scrypt", "non_numeric_parameters"
        if n < 2 or n & (n - 1):
            return False, "werkzeug_scrypt", "n_not_power_of_two"
        if r < 1 or p < 1:
            return False, "werkzeug_scrypt", "r_or_p_below_one"
        if 128 * n * r > 64 * 1024 * 1024:
            return False, "werkzeug_scrypt", "memory_above_64mb"
        if len(stored.split("$")) != 3:
            return False, "werkzeug_scrypt", "incomplete_hash"
        return True, "werkzeug_scrypt", "ok"

    return False, method or "unknown", "unknown_hash_format"


def _log_refused_user_password_hashes(data: Dict[str, Any]) -> None:
    for user in data.get("users", []) if isinstance(data, dict) else []:
        if not isinstance(user, dict) or not user.get("password_hash"):
            continue
        ok, hash_type, reason = _describe_password_hash(str(user.get("password_hash") or ""))
        if not ok:
            app.logger.warning(
                "PASSWORD_HASH_REFUSED user_id=%s partner_id=%s hash_type=%s reason=%s",
                user.get("id") or "",
                user.get("partner_id") or "",
                hash_type,
                reason,
            )


def _verify_password(password: str, stored: str) -> bool:
    started_at = time.monotonic()
    _log_memory_stage("BEFORE_PASSWORD_VERIFY", route=_current_route_for_log())
    stored = stored or ""
    ok, hash_type, reason = _describe_password_hash(stored)
    if not ok:
        app.logger.warning("PASSWORD_HASH_REFUSED hash_type=%s reason=%s", hash_type, reason)
        _log_memory_stage("AFTER_PASSWORD_VERIFY", started_at, _current_route_for_log())
        return False

    try:
        if hash_type == "pbkdf2_sha256":
            _, rounds, salt, digest = stored.split("$", 3)
            candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds)).hex()
            result = hmac.compare_digest(candidate, digest)
        else:
            result = werkzeug_security.check_password_hash(stored, password)
        return result
    except Exception:
        app.logger.exception("PASSWORD_VERIFY_FAILED hash_type=%s", hash_type)
        return False
    finally:
        _log_memory_stage("AFTER_PASSWORD_VERIFY", started_at, _current_route_for_log())


def _werkzeug_hash_uses_unsafe_memory(stored: str) -> bool:
    ok, hash_type, _reason = _describe_password_hash(stored or "")
    return hash_type == "werkzeug_scrypt" and not ok




def _invitation_fernet() -> Fernet:
    digest = hashlib.sha256((app.secret_key or "dev-secret-change-me").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_invitation_token(raw_token: str) -> str:
    return _invitation_fernet().encrypt((raw_token or "").encode()).decode()


def _decrypt_invitation_token(value: str) -> str:
    if not value:
        return ""
    try:
        return _invitation_fernet().decrypt(value.encode()).decode()
    except Exception:
        return ""

def _create_invitation(data: Dict[str, Any], user_id: str, partner_id: str, hours: int = 48) -> str:
    raw = secrets.token_urlsafe(48)
    data.setdefault("invitations", []).append({
        "id": str(uuid.uuid4()), "user_id": user_id, "partner_id": partner_id,
        "token_hash": _hash_token(raw), "token_encrypted": _encrypt_invitation_token(raw), "created_at": _now_iso(),
        "expires_at": (datetime.datetime.utcnow() + datetime.timedelta(hours=hours)).isoformat() + "Z",
        "used_at": "", "cancelled_at": "", "last_send_status": "", "last_send_error": "", "last_sent_at": "", "brevo_message_id": "",
        "delivery_state": "pending", "send_attempt_id": "", "send_started_at": "", "send_attempt_count": 0,
    })
    return raw


def _normalize_public_base_url(value: str) -> str:
    raw = (value or "").strip().rstrip("/")
    if not raw:
        return raw

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.netloc in PUBLIC_STUDENT_PORTAL_LEGACY_HOSTS:
        return PUBLIC_STUDENT_PORTAL_BASE_DEFAULT
    return raw


def _public_base_url() -> str:
    raw = os.environ.get("APP_BASE_URL") or os.environ.get("PUBLIC_BASE_URL") or APP_BASE_URL or ""
    return _normalize_public_base_url(raw)


def _activation_url(raw_token: str) -> str:
    return f"{_public_base_url()}/activate-account?token={quote(raw_token or '')}"


def _brevo_config_diagnostics() -> Dict[str, Any]:
    base = _public_base_url()
    return {
        "api_key_present": bool((BREVO_API_KEY or "").strip()),
        "sender_email_present": bool((BREVO_SENDER_EMAIL or "").strip()),
        "sender_name_present": bool((BREVO_SENDER_NAME or "").strip()),
        "base_url_present": bool(base),
        "sender_email": "adresse configurÃ©e" if (BREVO_SENDER_EMAIL or "").strip() else "absente",
        "sender_name": "nom configurÃ©" if (BREVO_SENDER_NAME or "").strip() else "absent",
        "base_url": "URL configurÃ©e" if base else "absente",
    }


def _missing_brevo_config() -> List[str]:
    missing = []
    if not (BREVO_API_KEY or "").strip():
        missing.append("BREVO_API_KEY")
    if not (BREVO_SENDER_EMAIL or "").strip():
        missing.append("BREVO_SENDER_EMAIL")
    if not (BREVO_SENDER_NAME or "").strip():
        missing.append("BREVO_SENDER_NAME")
    if not _public_base_url():
        missing.append("APP_BASE_URL ou PUBLIC_BASE_URL")
    return missing


def _safe_brevo_log(action: str, **details: Any) -> None:
    redacted = {k: v for k, v in details.items() if k not in {"api_key", "token", "raw_token", "activation_url"}}
    app.logger.info("[BREVO_INVITATION] %s %s", action, json.dumps(redacted, ensure_ascii=False, default=str))


def _partner_invitation_mail_html(user: Dict[str, Any], partner: Dict[str, Any], activation_url: str) -> str:
    logo_src = f"{PUBLIC_BASE_URL.rstrip('/')}/static/iaconnectpartenaires.png"
    escaped_url = html.escape(activation_url, quote=True)
    first_name = html.escape(user.get('first_name') or '')
    partner_name = html.escape(partner.get('name') or '')
    return mail_layout(f"""
      <div style="text-align:center;margin-bottom:22px">
        <img src="{logo_src}" alt="IntÃ©grale Connect Partenaires" style="max-height:144px;width:auto;display:block;margin:0 auto;border:0;outline:none;text-decoration:none">
      </div>
      <div style="background:linear-gradient(135deg,#0f172a,#1d4ed8);color:#fff;border-radius:20px;padding:24px 22px;margin-bottom:22px;text-align:center">
        <p style="margin:0 0 8px;text-transform:uppercase;letter-spacing:.14em;font-size:12px;color:#bfdbfe;font-weight:700">Espace partenaire</p>
        <h1 style="margin:0;font-size:28px;line-height:1.15">Activation de votre espace partenaire</h1>
      </div>
      <p style="font-size:16px;color:#334155;line-height:1.55;margin:0 0 14px">Bonjour {first_name},</p>
      <p style="font-size:16px;color:#334155;line-height:1.55;margin:0 0 22px">Votre espace <strong style="color:#0f172a">{partner_name}</strong> est prÃªt.</p>
      <div style="text-align:center;margin:28px 0">
        <a href="{escaped_url}" style="display:inline-block;background:#f97316;color:#fff;text-decoration:none;font-weight:800;border-radius:999px;padding:14px 24px;box-shadow:0 12px 24px rgba(249,115,22,.22)">DÃ©finir mon mot de passe</a>
      </div>
      <p style="font-size:14px;color:#64748b;line-height:1.55;margin:0;background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:14px 16px">Ce lien est personnel, utilisable une seule fois et expire sous 48 heures.</p>
    """, show_default_logo=False, footer_text="IntÃ©grale Connect Partenaires")


def _send_partner_invitation_email(user: Dict[str, Any], partner: Dict[str, Any], raw_token: str) -> Dict[str, Any]:
    activation_url = _activation_url(raw_token)
    html_body = _partner_invitation_mail_html(user, partner, activation_url)
    text_body = f"Activez votre espace partenaire : {activation_url}"
    result = brevo_send_email(user.get("email") or "", "Activation de votre espace partenaire", html_body, text_content=text_body, metadata={"partner_id": partner.get("id"), "partner_name": partner.get("name"), "user_id": user.get("id"), "purpose": "partner_invitation"})
    return result


def _partner_counts(data: Dict[str, Any], partner_id: str) -> Dict[str, int]:
    sessions_for_partner = [s for s in data.get("sessions", []) if isinstance(s, dict) and s.get("partner_id") == partner_id]
    return {"users": sum(1 for u in data.get("users", []) if isinstance(u, dict) and u.get("partner_id") == partner_id), "sessions": len(sessions_for_partner), "trainees": sum(len(_registered_trainees(s)) for s in sessions_for_partner)}




def _delete_partner_everywhere(data: Dict[str, Any], partner_id: str) -> Dict[str, int]:
    """Remove a partner and every partner-scoped record from the JSON payload."""
    removed: Dict[str, int] = {}

    def prune_list(key: str, predicate) -> None:
        items = data.get(key)
        if not isinstance(items, list):
            return
        kept = [item for item in items if not predicate(item)]
        count = len(items) - len(kept)
        if count:
            data[key] = kept
            removed[key] = count

    prune_list("partners", lambda item: isinstance(item, dict) and item.get("id") == partner_id)
    for key, items in list(data.items()):
        if isinstance(items, list):
            prune_list(key, lambda item, pid=partner_id: isinstance(item, dict) and item.get("partner_id") == pid)

    dismissed_keys = data.get("notifications_admin_dismissed_schedule_keys")
    if isinstance(dismissed_keys, list):
        kept_keys = [key for key in dismissed_keys if not str(key).startswith(f"{partner_id}:")]
        count = len(dismissed_keys) - len(kept_keys)
        if count:
            data["notifications_admin_dismissed_schedule_keys"] = kept_keys
            removed["notifications_admin_dismissed_schedule_keys"] = count

    return removed


def _remove_partner_storage(partner_id: str) -> bool:
    root = os.path.realpath(os.path.join(PERSIST_DIR, "partners"))
    target = os.path.realpath(os.path.join(root, str(partner_id or "")))
    if not target.startswith(root + os.sep):
        raise ValueError("chemin partenaire invalide")
    if os.path.isdir(target):
        shutil.rmtree(target)
        return True
    return False

def _partner_or_404(data: Dict[str, Any], partner_id: str) -> Dict[str, Any]:
    partner = next((p for p in data.get("partners", []) if isinstance(p, dict) and p.get("id") == partner_id), None)
    if not partner:
        abort(404)
    return partner


def require_super_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _is_super_admin_session():
            abort(403)
        return view(*args, **kwargs)
    wrapped._requires_super_admin = True
    return wrapped


def _safe_upload_identifier(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", normalized):
        raise ValueError(f"{label} invalide")
    return normalized


def _partner_id_for_upload(session_id: str, trainee_id: str) -> str:
    current_partner_id = _current_partner_id()
    if current_partner_id and (
        _is_external_partner_session()
        or (session.get("assist_partner_id") and _is_super_admin_session())
    ):
        return current_partner_id
    # Public trainee uploads do not carry an admin cookie. Resolve the tenant
    # from the server-side session record so those files are isolated too.
    if has_request_context():
        try:
            data = load_data(run_background_tasks=False)
            session_obj = next((
                item for item in data.get("sessions", [])
                if isinstance(item, dict) and str(item.get("id") or "") == str(session_id)
            ), None)
            if session_obj and any(
                str(item.get("id") or "") == str(trainee_id)
                for item in _session_trainees_list(session_obj) if isinstance(item, dict)
            ):
                return str(session_obj.get("partner_id") or INTEGRALE_PARTNER_ID)
        except Exception:
            app.logger.exception("Unable to resolve upload tenant session_id=%s", session_id)
    return current_partner_id or INTEGRALE_PARTNER_ID


def trainee_upload_dir(session_id: str, trainee_id: str) -> str:
    safe_session_id = _safe_upload_identifier(session_id, "session_id")
    safe_trainee_id = _safe_upload_identifier(trainee_id, "trainee_id")
    partner_id = _partner_id_for_upload(safe_session_id, safe_trainee_id)
    d = os.path.join(
        get_partner_storage_path(partner_id, "stagiaires"),
        safe_session_id,
        safe_trainee_id,
    )
    os.makedirs(d, exist_ok=True)
    return d


def _cleanup_backups_for(prefix: str) -> None:
    try:
        names = sorted(
            [name for name in os.listdir(BACKUP_DIR) if name.startswith(prefix + ".")],
            key=lambda name: backup_chronology_key(os.path.join(BACKUP_DIR, name)),
            reverse=True,
        )
        for old_name in names[BACKUP_RETENTION:]:
            old_path = os.path.join(BACKUP_DIR, old_name)
            if os.path.isfile(old_path):
                os.remove(old_path)
    except Exception:
        pass


def _json_backup_path(prefix: str, reason: str = "auto") -> str:
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S.%fZ")
    suffix = uuid.uuid4().hex[:8]
    safe_reason = re.sub(r"[^a-zA-Z0-9_-]+", "-", reason or "auto")[:32]
    return os.path.join(BACKUP_DIR, f"{prefix}.{stamp}.{safe_reason}.{suffix}.json")


def _copy_file_durable(src_path: str, dst_path: str) -> None:
    with open(src_path, "rb") as src, open(dst_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
        dst.flush()
        os.fsync(dst.fileno())


def _snapshot_file_durable(src_path: str, dst_path: str) -> None:
    """Create a durable point-in-time snapshot without copying large JSON files when possible."""
    try:
        os.link(src_path, dst_path)
        _fsync_parent_dir(dst_path)
        return
    except OSError:
        pass

    if os.path.getsize(src_path) > MAX_JSON_BACKUP_BYTES:
        raise ValueError("file larger than MAX_JSON_BACKUP_BYTES")

    _copy_file_durable(src_path, dst_path)
    _fsync_parent_dir(dst_path)


def _force_backup_snapshot(path: str, reason: str = "manual") -> Optional[str]:
    base_name = os.path.basename(path)
    prefix = base_name.replace(".", "_")
    if not os.path.exists(path):
        return None
    backup_path = _json_backup_path(prefix, reason)
    try:
        _snapshot_file_durable(path, backup_path)
        _cleanup_backups_for(prefix)
        if not os.path.isfile(backup_path):
            app.logger.warning("New backup was not retained for %s", path)
            return None
        return backup_path
    except ValueError:
        app.logger.warning("Backup skipped for %s: file larger than MAX_JSON_BACKUP_BYTES and hard-link snapshot unavailable", path)
        return None
    except Exception:
        app.logger.exception("Unable to create JSON backup for %s", path)
        return None


def _fsync_parent_dir(path: str) -> None:
    try:
        dir_fd = os.open(os.path.dirname(path) or ".", os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        pass


def _write_json_with_backups(
    path: str,
    payload: Any,
    lock: threading.RLock,
    payload_transform: Optional[Callable[[Any], Any]] = None,
) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lock_path = path + ".lock"
    with lock:
        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                # Run read/merge transforms only after taking the inter-process
                # lock. This closes the race between reading the canonical
                # value and replacing the JSON file.
                if payload_transform is not None:
                    payload = payload_transform(payload)
                now_ts = datetime.datetime.utcnow().timestamp()
                base_name = os.path.basename(path)
                prefix = base_name.replace(".", "_")

                # Snapshot systÃ©matique avant Ã©criture pour Ã©viter toute fenÃªtre de perte
                # de donnÃ©es entre deux backups pÃ©riodiques.
                if BACKUP_SNAPSHOT_BEFORE_SAVE:
                    if _force_backup_snapshot(path, reason="before-save"):
                        _last_backup_times[path] = now_ts

                if os.path.exists(path):
                    last = _last_backup_times.get(path, 0)
                    if now_ts - last >= BACKUP_MIN_INTERVAL_SECONDS:
                        if _force_backup_snapshot(path, reason="interval"):
                            _last_backup_times[path] = now_ts

                tmp = f"{path}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
                try:
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(payload, f, ensure_ascii=False, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp, path)
                    _fsync_parent_dir(path)
                    if os.path.abspath(path) == os.path.abspath(DATA_FILE) and isinstance(payload, dict):
                        _store_partner_auth_index(payload, path)
                finally:
                    if os.path.exists(tmp):
                        try:
                            os.remove(tmp)
                        except Exception:
                            pass
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

def _safe_remove_file(path: str) -> None:
    """DÃ©place le fichier vers la corbeille interne avant suppression logique."""
    if not path:
        return
    if not os.path.exists(path) or not os.path.isfile(path):
        return

    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    parent_hint = os.path.basename(os.path.dirname(path) or "root")
    base_name = os.path.basename(path)
    target_name = f"{stamp}_{parent_hint}_{base_name}"
    target_path = os.path.join(TRASH_DIR, target_name)

    if os.path.exists(target_path):
        unique = uuid.uuid4().hex[:8]
        target_path = os.path.join(TRASH_DIR, f"{stamp}_{parent_hint}_{unique}_{base_name}")

    try:
        os.replace(path, target_path)
    except Exception:
        # Dernier recours : suppression classique si le move Ã©choue.
        try:
            os.remove(path)
        except Exception:
            pass


def _iter_corrupt_candidates(path: str) -> Iterable[str]:
    parent = os.path.dirname(path) or "."
    base_name = os.path.basename(path)
    prefix = base_name + ".corrupt."
    try:
        names = sorted(
            [name for name in os.listdir(parent) if name.startswith(prefix)],
            reverse=True,
        )
    except Exception:
        return []
    return [os.path.join(parent, name) for name in names]


def _load_valid_json_payload(path: str) -> Optional[Dict[str, Any]]:
    lock = _data_lock if "_data_lock" in globals() and path == globals().get("DATA_FILE") else None

    def _read() -> Optional[Dict[str, Any]]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            return None
        return None

    if lock is not None:
        with lock:
            return _read()
    return _read()


def _recover_data_file(path: str) -> Optional[str]:
    recovery_sources: List[str] = []
    base_name = os.path.basename(path)
    backup_prefix = base_name.replace(".", "_") + "."
    try:
        backup_names = sorted(
            [
                name
                for name in os.listdir(BACKUP_DIR)
                if name.startswith(backup_prefix) and name.endswith(".json")
            ],
            key=lambda name: backup_chronology_key(os.path.join(BACKUP_DIR, name)),
            reverse=True,
        )
        recovery_sources.extend(os.path.join(BACKUP_DIR, name) for name in backup_names)
    except Exception:
        pass

    recovery_sources.extend(_iter_corrupt_candidates(path))

    for source in recovery_sources:
        if not os.path.isfile(source):
            continue
        loaded = _load_valid_json_payload(source)
        if loaded is None:
            continue
        try:
            shutil.copyfile(source, path)
            app.logger.warning("Recovered data.json from %s", source)
            return source
        except Exception:
            continue
    return None


def _count_loaded_objects(data: Dict[str, Any]) -> Tuple[int, int]:
    sessions = data.get("sessions")
    sessions_count = len(sessions) if isinstance(sessions, list) else 0
    trainees_count = 0
    if isinstance(sessions, list):
        for session_item in sessions:
            if isinstance(session_item, dict):
                trainees = session_item.get("trainees")
                if isinstance(trainees, list):
                    trainees_count += len(trainees)
    return trainees_count, sessions_count


def _log_storage_state(data: Optional[Dict[str, Any]] = None) -> None:
    global _storage_startup_logged
    if _storage_startup_logged:
        return
    exists = os.path.exists(DATA_FILE)
    size = os.path.getsize(DATA_FILE) if exists else 0
    trainees_count, sessions_count = _count_loaded_objects(data or {})
    app.logger.info(
        "Storage startup path=%s exists=%s size=%sB stagiaires=%s sessions=%s",
        DATA_FILE,
        exists,
        size,
        trainees_count,
        sessions_count,
    )
    _storage_startup_logged = True


def _restore_latest_backup(path: str) -> bool:
    base_name = os.path.basename(path)
    prefix = base_name.replace(".", "_")

    try:
        names = sorted(
            [
                name
                for name in os.listdir(BACKUP_DIR)
                if name.startswith(prefix + ".") and name.endswith(".json")
            ],
            key=lambda name: backup_chronology_key(os.path.join(BACKUP_DIR, name)),
            reverse=True,
        )
    except Exception:
        return False

    for name in names:
        backup_path = os.path.join(BACKUP_DIR, name)
        if not os.path.isfile(backup_path):
            continue
        try:
            with open(backup_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                continue
            shutil.copyfile(backup_path, path)
            return True
        except Exception:
            continue
    return False


def _restore_data_from_backups_if_possible() -> Optional[Dict[str, Any]]:
    if not _restore_latest_backup(DATA_FILE):
        return None
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        return None
    return None


# =========================
# Brevo (Sendinblue) config
# =========================
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "ecole@integraleacademy.com")
BREVO_SENDER_NAME = os.environ.get("BREVO_SENDER_NAME", "IntÃ©grale Academy")
CNAPS_LOOKUP_ENDPOINT = os.environ.get("CNAPS_LOOKUP_ENDPOINT", "")
CNAPS_PUBLIC_ANNUAIRE_LEGACY_ENDPOINT = "https://espace-consultation.cnaps.interieur.gouv.fr/annuaire/api/annuaire-public"
CNAPS_PUBLIC_ANNUAIRE_PAGE_URL = "https://espace-consultation.cnaps.interieur.gouv.fr/annuaire/app/annuaire-public"
CNAPS_PUBLIC_ANNUAIRE_ENDPOINT = os.environ.get("CNAPS_PUBLIC_ANNUAIRE_ENDPOINT", "https://espace-consultation.cnaps.interieur.gouv.fr/annuaire/api/back/public/annuaire/search/personne-physique").strip()
CNAPSV3_NOTIFICATIONS_ENDPOINT = os.environ.get("CNAPSV3_NOTIFICATIONS_ENDPOINT", "")
CNAPSV3_BASE_URL = os.environ.get("CNAPSV3_BASE_URL", "https://cnapsv3.onrender.com").strip().rstrip("/")
GESTIONSTAGIAIRE_SYNC_TOKEN = os.environ.get("GESTIONSTAGIAIRE_SYNC_TOKEN", "").strip()

PUBLIC_STUDENT_PORTAL_BASE_DEFAULT = "https://gestionstagiaires-r5no.onrender.com"
PUBLIC_STUDENT_PORTAL_LEGACY_HOSTS = {"gestionstagiaires-test-v2.onrender.com"}


def _normalize_public_student_portal_base(value: str) -> str:
    raw = (value or "").strip().rstrip("/")
    if not raw:
        return PUBLIC_STUDENT_PORTAL_BASE_DEFAULT

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.netloc in PUBLIC_STUDENT_PORTAL_LEGACY_HOSTS:
        return PUBLIC_STUDENT_PORTAL_BASE_DEFAULT
    return raw


PUBLIC_STUDENT_PORTAL_BASE = _normalize_public_student_portal_base(
    os.environ.get("PUBLIC_STUDENT_PORTAL_BASE") or APP_BASE_URL
)

PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    APP_BASE_URL
).strip().rstrip("/")


CNAPS_STATUS_ENDPOINT = os.environ.get("CNAPS_STATUS_ENDPOINT", "")
HEBERGEMENT_STATUS_ENDPOINT = os.environ.get("HEBERGEMENT_STATUS_ENDPOINT", "")


def _cnapsv3_notifications_endpoint() -> str:
    endpoint = (CNAPSV3_NOTIFICATIONS_ENDPOINT or "").strip()
    if endpoint:
        return endpoint

    lookup = (CNAPS_LOOKUP_ENDPOINT or "").strip()
    if not lookup:
        return ""

    try:
        parsed = urlparse(lookup)
        if not parsed.scheme or not parsed.netloc:
            return ""
        return urljoin(f"{parsed.scheme}://{parsed.netloc}", "/notifications_espace_cnaps_a_valider.json")
    except Exception:
        return ""


def _cnapsv3_accept_endpoint() -> str:
    base_url = (CNAPSV3_BASE_URL or "").strip().rstrip("/")
    if not base_url:
        return ""
    return f"{base_url}/integrations/gestionstagiaire/cnaps/accept"


def _cnapsv3_lookup_endpoint() -> str:
    base_url = (CNAPSV3_BASE_URL or "").strip().rstrip("/")
    if not base_url:
        return ""
    return f"{base_url}/integrations/gestionstagiaire/cnaps/lookup"


def _cnapsv3_tracking_endpoint() -> str:
    base_url = (CNAPSV3_BASE_URL or "").strip().rstrip("/")
    if not base_url:
        return ""
    return f"{base_url}/api/a-traiter"


def _extract_cnapsv3_tracking_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("demandes", "requests", "items", "data", "a_traiter", "to_process"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _extract_cnapsv3_tracking_items(value)
            if nested:
                return nested
    return []


def _cnapsv3_tracking_value(item: Dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""




CNAPSV3_TRACKING_MIN_CREATED_DATE = datetime.date(2026, 6, 1)


def _parse_cnapsv3_tracking_date(value: Any) -> Optional[datetime.date]:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(normalized).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(raw[:10], fmt).date()
        except ValueError:
            continue
    return None


def _cnapsv3_tracking_request_matches_scope(item: Dict[str, Any]) -> bool:
    """Keep every CNAPSV3 dossier created on or after the tracking cutoff."""
    created_raw = _cnapsv3_tracking_value(item, (
        "created_at",
        "createdAt",
        "date_creation",
        "dateCreation",
        "created_date",
        "date_depot",
        "dateDepot",
        "submitted_at",
        "submittedAt",
        "transmitted_at",
        "transmittedAt",
    ))
    created_date = _parse_cnapsv3_tracking_date(created_raw)
    return bool(created_date and created_date >= CNAPSV3_TRACKING_MIN_CREATED_DATE)


CNAPSV3_TRACKING_CACHE_TTL_SECONDS = 15
_cnapsv3_tracking_cache: Dict[str, Any] = {"expires_at": 0.0, "rows": [], "error": None}


def _cnapsv3_tracking_response_metadata(response: Any) -> Tuple[int, str, str]:
    status_code = int(getattr(response, "status_code", 0) or 0)
    headers = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("Content-Type") or headers.get("content-type") or "")
    final_url = str(getattr(response, "url", "") or "")
    return status_code, content_type, final_url


def _cnapsv3_tracking_error(message: str, response: Any = None) -> Tuple[List[Dict[str, str]], str]:
    if response is not None:
        status_code, content_type, final_url = _cnapsv3_tracking_response_metadata(response)
        app.logger.warning(
            "Suivi CNAPSV3 indisponible: %s (HTTP %s, Content-Type: %s, URL finale: %s)",
            message,
            status_code or "inconnu",
            content_type or "inconnu",
            final_url or "inconnue",
        )
    else:
        app.logger.warning("Suivi CNAPSV3 indisponible: %s", message)
    return [], message


def fetch_cnapsv3_tracking_requests(get_func=None) -> Tuple[List[Dict[str, str]], Optional[str]]:
    use_cache = get_func is None
    if get_func is None:
        get_func = requests.get
    now = time.time()
    if use_cache and now < float(_cnapsv3_tracking_cache.get("expires_at") or 0):
        return list(_cnapsv3_tracking_cache.get("rows") or []), _cnapsv3_tracking_cache.get("error")

    endpoint = _cnapsv3_tracking_endpoint()
    if not endpoint:
        return [], "CNAPSV3_BASE_URL non configurÃ©"

    token = os.environ.get("CNAPSV3_API_TOKEN", "").strip()
    if not token:
        rows, error = _cnapsv3_tracking_error("CNAPSV3_API_TOKEN absent")
        if use_cache:
            _cnapsv3_tracking_cache.update({"expires_at": now + CNAPSV3_TRACKING_CACHE_TTL_SECONDS, "rows": rows, "error": error})
        return rows, error

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }

    try:
        response = get_func(endpoint, headers=headers, timeout=(3, 10))
    except requests.ConnectTimeout:
        rows, error = _cnapsv3_tracking_error("timeout connexion")
        if use_cache:
            _cnapsv3_tracking_cache.update({"expires_at": now + CNAPSV3_TRACKING_CACHE_TTL_SECONDS, "rows": rows, "error": error})
        return rows, error
    except requests.ReadTimeout:
        rows, error = _cnapsv3_tracking_error("timeout lecture")
        if use_cache:
            _cnapsv3_tracking_cache.update({"expires_at": now + CNAPSV3_TRACKING_CACHE_TTL_SECONDS, "rows": rows, "error": error})
        return rows, error
    except requests.ConnectionError:
        rows, error = _cnapsv3_tracking_error("erreur connexion")
        if use_cache:
            _cnapsv3_tracking_cache.update({"expires_at": now + CNAPSV3_TRACKING_CACHE_TTL_SECONDS, "rows": rows, "error": error})
        return rows, error
    except requests.Timeout:
        rows, error = _cnapsv3_tracking_error("timeout rÃ©seau")
        if use_cache:
            _cnapsv3_tracking_cache.update({"expires_at": now + CNAPSV3_TRACKING_CACHE_TTL_SECONDS, "rows": rows, "error": error})
        return rows, error
    except requests.RequestException:
        rows, error = _cnapsv3_tracking_error("erreur rÃ©seau")
        if use_cache:
            _cnapsv3_tracking_cache.update({"expires_at": now + CNAPSV3_TRACKING_CACHE_TTL_SECONDS, "rows": rows, "error": error})
        return rows, error
    except Exception:
        rows, error = _cnapsv3_tracking_error("erreur inattendue")
        if use_cache:
            _cnapsv3_tracking_cache.update({"expires_at": now + CNAPSV3_TRACKING_CACHE_TTL_SECONDS, "rows": rows, "error": error})
        return rows, error

    status_code, content_type, final_url = _cnapsv3_tracking_response_metadata(response)
    if status_code != 200:
        if status_code in (401, 403):
            rows, error = _cnapsv3_tracking_error("authentification CNAPSV3 refusÃ©e", response)
        elif status_code >= 500:
            rows, error = _cnapsv3_tracking_error("erreur serveur CNAPSV3", response)
        else:
            rows, error = _cnapsv3_tracking_error(f"HTTP {status_code}", response)
        if use_cache:
            _cnapsv3_tracking_cache.update({"expires_at": now + CNAPSV3_TRACKING_CACHE_TTL_SECONDS, "rows": rows, "error": error})
        return rows, error
    if "/login" in final_url:
        rows, error = _cnapsv3_tracking_error("redirection vers la page de connexion", response)
        if use_cache:
            _cnapsv3_tracking_cache.update({"expires_at": now + CNAPSV3_TRACKING_CACHE_TTL_SECONDS, "rows": rows, "error": error})
        return rows, error
    if "application/json" not in content_type.lower():
        rows, error = _cnapsv3_tracking_error("rÃ©ponse non JSON", response)
        if use_cache:
            _cnapsv3_tracking_cache.update({"expires_at": now + CNAPSV3_TRACKING_CACHE_TTL_SECONDS, "rows": rows, "error": error})
        return rows, error

    try:
        payload = response.json() or {}
    except ValueError:
        rows, error = _cnapsv3_tracking_error("JSON invalide", response)
        if use_cache:
            _cnapsv3_tracking_cache.update({"expires_at": now + CNAPSV3_TRACKING_CACHE_TTL_SECONDS, "rows": rows, "error": error})
        return rows, error
    except Exception:
        rows, error = _cnapsv3_tracking_error("lecture JSON impossible", response)
        if use_cache:
            _cnapsv3_tracking_cache.update({"expires_at": now + CNAPSV3_TRACKING_CACHE_TTL_SECONDS, "rows": rows, "error": error})
        return rows, error

    rows: List[Dict[str, str]] = []
    for item in _extract_cnapsv3_tracking_items(payload):
        tracking_id = _cnapsv3_tracking_value(item, ("id", "request_id", "dossier_id"))
        last_name = _cnapsv3_tracking_value(item, ("nom", "last_name", "lastname", "name"))
        first_name = normalize_first_name(_cnapsv3_tracking_value(item, ("prenom", "first_name", "firstname")))
        nub = _cnapsv3_tracking_value(item, ("nub", "NUB", "numero_nub", "nub_number", "num_nub"))
        status = _cnapsv3_tracking_value(item, ("statut_cnaps", "cnaps_status", "status", "statut"))
        if not any((last_name, first_name, nub, status)):
            continue
        if not _cnapsv3_tracking_request_matches_scope(item):
            continue
        normalized_row = {
            "last_name": last_name,
            "first_name": first_name,
            "nub": nub,
            "cnaps_status": status or "INCONNU",
        }
        if tracking_id:
            normalized_row["tracking_id"] = tracking_id
        rows.append(normalized_row)
    if use_cache:
        _cnapsv3_tracking_cache.update({"expires_at": now + CNAPSV3_TRACKING_CACHE_TTL_SECONDS, "rows": rows, "error": None})
    return rows, None


def sync_cnapsv3_lookup_identifier(
    first_name: str,
    last_name: str,
    email: Optional[str] = None,
    *,
    post_func=requests.post,
    sleep_func=time.sleep,
) -> Optional[Dict[str, str]]:
    first_name_value = str(first_name or "").strip()
    last_name_value = str(last_name or "").strip()
    if not first_name_value or not last_name_value:
        app.logger.warning("[CNAPSV3_LOOKUP] first_name/last_name manquants")
        return None

    endpoint = _cnapsv3_lookup_endpoint()
    if not endpoint:
        app.logger.error("[CNAPSV3_LOOKUP] CNAPSV3_BASE_URL non configurÃ©")
        return None

    if not GESTIONSTAGIAIRE_SYNC_TOKEN:
        app.logger.error("[CNAPSV3_LOOKUP] GESTIONSTAGIAIRE_SYNC_TOKEN manquant")
        return None

    payload: Dict[str, Any] = {
        "first_name": first_name_value,
        "last_name": last_name_value,
    }
    email_value = str(email or "").strip()
    if email_value:
        payload["email"] = email_value

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GESTIONSTAGIAIRE_SYNC_TOKEN}",
    }

    backoff_seconds = [1, 2, 4]
    for attempt, delay in enumerate(backoff_seconds, start=1):
        try:
            response = post_func(endpoint, headers=headers, json=payload, timeout=(3, 10))
        except requests.RequestException as exc:
            app.logger.warning(
                "[CNAPSV3_LOOKUP] Erreur rÃ©seau tentative=%s/%s payload=%s error=%s",
                attempt,
                len(backoff_seconds),
                payload,
                exc,
            )
            if attempt < len(backoff_seconds):
                sleep_func(delay)
                continue
            return None

        if response.status_code == 200:
            body = response.json() if hasattr(response, "json") else {}
            if not isinstance(body, dict):
                body = {}
            identifiers = {
                "request_id": str(body.get("request_id") or "").strip(),
                "dossier_id": str(body.get("dossier_id") or "").strip(),
                "email": str(body.get("email") or "").strip(),
            }
            if not identifiers["request_id"] and not identifiers["dossier_id"]:
                app.logger.warning("[CNAPSV3_LOOKUP] succÃ¨s sans identifiant payload=%s", payload)
                return None
            app.logger.info("[CNAPSV3_LOOKUP] succÃ¨s payload=%s", payload)
            return identifiers
        if response.status_code == 401:
            app.logger.error("[CNAPSV3_LOOKUP] 401 payload=%s", payload)
            return None
        if response.status_code == 404:
            app.logger.info("[CNAPSV3_LOOKUP] notfound payload=%s", payload)
            return None
        if response.status_code == 409:
            app.logger.info("[CNAPSV3_LOOKUP] ambiguous payload=%s", payload)
            return None

        app.logger.warning(
            "[CNAPSV3_LOOKUP] RÃ©ponse inattendue status=%s payload=%s",
            response.status_code,
            payload,
        )
        return None

    return None


def sync_cnapsv3_accept_status(
    request_id: Optional[str] = None,
    dossier_id: Optional[str] = None,
    *,
    post_func=requests.post,
    sleep_func=time.sleep,
) -> bool:
    request_id_value = str(request_id or "").strip()
    dossier_id_value = str(dossier_id or "").strip()

    if not request_id_value and not dossier_id_value:
        app.logger.warning("[CNAPSV3_SYNC] Aucun identifiant fourni (request_id/dossier_id)")
        return False

    endpoint = _cnapsv3_accept_endpoint()
    if not endpoint:
        app.logger.error("[CNAPSV3_SYNC] CNAPSV3_BASE_URL non configurÃ©")
        return False

    if not GESTIONSTAGIAIRE_SYNC_TOKEN:
        app.logger.error("[CNAPSV3_SYNC] GESTIONSTAGIAIRE_SYNC_TOKEN manquant")
        return False

    payload: Dict[str, Any]
    if request_id_value:
        payload = {"request_id": request_id_value}
    else:
        payload = {"dossier_id": dossier_id_value}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GESTIONSTAGIAIRE_SYNC_TOKEN}",
    }

    backoff_seconds = [1, 2, 4]
    for attempt, delay in enumerate(backoff_seconds, start=1):
        try:
            response = post_func(endpoint, headers=headers, json=payload, timeout=8)
        except requests.RequestException as exc:
            app.logger.warning(
                "[CNAPSV3_SYNC] Erreur rÃ©seau tentative=%s/%s payload=%s error=%s",
                attempt,
                len(backoff_seconds),
                payload,
                exc,
            )
            if attempt < len(backoff_seconds):
                sleep_func(delay)
                continue
            return False

        if response.status_code == 200:
            app.logger.info("[CNAPSV3_SYNC] SuccÃ¨s synchronisation payload=%s", payload)
            return True
        if response.status_code == 401:
            app.logger.error("[CNAPSV3_SYNC] Token invalide (401) payload=%s", payload)
            return False
        if response.status_code == 404:
            app.logger.error("[CNAPSV3_SYNC] Dossier/requÃªte introuvable (404) payload=%s", payload)
            return False
        if response.status_code == 400:
            app.logger.error("[CNAPSV3_SYNC] Payload invalide (400) payload=%s", payload)
            return False

        app.logger.warning(
            "[CNAPSV3_SYNC] RÃ©ponse inattendue status=%s payload=%s",
            response.status_code,
            payload,
        )
        return False

    return False


def _sync_cnapsv3_notifications_to_secretariat(data: Dict[str, Any]) -> bool:
    def _is_cnaps_space_validated(value: Any) -> bool:
        normalized = _normalize_status(str(value or ""))
        return normalized.startswith("VALIDE")

    endpoint = _cnapsv3_notifications_endpoint()
    if not endpoint:
        return False

    try:
        response = requests.get(endpoint, timeout=(3, 10))
        response.raise_for_status()
        payload = response.json() or {}
    except Exception:
        app.logger.exception("Impossible de rÃ©cupÃ©rer les notifications CNAPSV3 (%s)", endpoint)
        return False

    if not payload.get("ok"):
        return False

    incoming = payload.get("notifications") or []
    if not isinstance(incoming, list):
        return False

    bucket = data.setdefault("notifications_cnaps_pre_relances", [])

    incoming_by_id = {}
    for item in incoming:
        if not isinstance(item, dict):
            continue
        request_id = str(item.get("request_id") or "").strip()
        if not request_id:
            continue
        incoming_by_id[request_id] = item

    incoming_ids = set(incoming_by_id.keys())

    # Le endpoint CNAPSV3 reprÃ©sente la source de vÃ©ritÃ© des dossiers Ã  afficher.
    # On purge les notifications CNAPSV3 locales qui ne sont plus remontÃ©es (ex: dossier validÃ©).
    filtered_bucket = []
    for item in bucket:
        if not isinstance(item, dict):
            continue
        meta = item.get("meta") or {}
        request_id = str((meta.get("cnapsv3_request_id") if isinstance(meta, dict) else "") or "").strip()
        if request_id:
            if request_id not in incoming_ids:
                continue
            if _is_cnaps_space_validated(incoming_by_id.get(request_id, {}).get("espace_cnaps")):
                continue
        filtered_bucket.append(item)

    changed = len(filtered_bucket) != len(bucket)
    bucket[:] = filtered_bucket

    known_ids = {
        str((item.get("meta") or {}).get("cnapsv3_request_id") or "").strip()
        for item in bucket
        if isinstance(item, dict)
    }

    for request_id, item in incoming_by_id.items():
        if _is_cnaps_space_validated(item.get("espace_cnaps")):
            continue

        if request_id in known_ids:
            continue

        first_name = str(item.get("prenom") or "").strip()
        last_name = str(item.get("nom") or "").strip()
        label_name = _format_trainee_name(first_name, last_name)
        label = f"{label_name} â€¢ Notification Compte CNAPS Ã  valider" if label_name else "Notification Compte CNAPS Ã  valider"
        created_at = str(item.get("updated_at") or "").strip() or _now_iso()

        phone = str(
            item.get("phone")
            or item.get("telephone")
            or item.get("tel")
            or item.get("mobile")
            or ""
        ).strip()

        bucket.insert(0, {
            "id": _notification_id("CPV3"),
            "label": label,
            "created_at": created_at,
            "done": False,
            "meta": {
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone,
                "call_status": "Ã€ appeler",
                "no_answer_count": 0,
                "cnapsv3_request_id": request_id,
                "cnapsv3_espace_cnaps": str(item.get("espace_cnaps") or "").strip(),
                "cnapsv3_title": str(item.get("title") or "").strip(),
                "cnapsv3_message": str(item.get("message") or "").strip(),
                "cnapsv3_updated_at": str(item.get("updated_at") or "").strip(),
            },
        })
        known_ids.add(request_id)
        changed = True

    return changed

BREVO_NO_CREDIT_MARKERS = (
    "not enough credits",
    "insufficient credits",
    "out of credits",
    "insufficient balance",
)


def _brevo_no_credit_detected(response_text: str) -> bool:
    text = (response_text or "").lower()
    return any(marker in text for marker in BREVO_NO_CREDIT_MARKERS)


def _notify_brevo_credit_alert_once(channel: str, recipient: str, response_text: str) -> None:
    if not has_request_context():
        return
    if session.get("_brevo_credit_alert_sending"):
        return

    subject = "[ALERTE] CrÃ©dits Brevo insuffisants"
    html_body = mail_layout(f"""
      <h2 style=\"text-align:center\">âš ï¸ CrÃ©dits Brevo insuffisants</h2>
      <p>Un envoi automatique a Ã©chouÃ© car les crÃ©dits Brevo semblent Ã©puisÃ©s.</p>
      <p><strong>Canal :</strong> {html.escape(channel)}</p>
      <p><strong>Destinataire :</strong> {html.escape(recipient or 'â€”')}</p>
      <p><strong>RÃ©ponse Brevo :</strong><br>{html.escape((response_text or 'â€”')[:1200])}</p>
    """)

    session["_brevo_credit_alert_sending"] = True
    try:
        brevo_send_email("clement@integraleacademy.com", subject, html_body)
    except Exception:
        pass
    finally:
        session.pop("_brevo_credit_alert_sending", None)


def _register_brevo_no_credit(channel: str, recipient: str, response_text: str) -> None:
    if not has_request_context():
        return
    session["brevo_no_credit_notice"] = {
        "channel": channel,
        "recipient": recipient,
        "at": _now_iso(),
    }
    _notify_brevo_credit_alert_once(channel, recipient, response_text)


def normalize_phone_fr(phone: str) -> str:
    p = (phone or "").strip().replace(" ", "").replace(".", "").replace("-", "")
    if not p:
        return ""
    if p.startswith("+"):
        return p
    if p.startswith("00"):
        return "+" + p[2:]
    if p.startswith("0") and len(p) == 10 and p[1:].isdigit():
        return "+33" + p[1:]
    return p


def format_phone_fr_for_display(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) == 10 and digits.startswith("0"):
        return " ".join(digits[i:i + 2] for i in range(0, 10, 2))
    if len(digits) == 11 and digits.startswith("33"):
        local = "0" + digits[2:]
        return " ".join(local[i:i + 2] for i in range(0, 10, 2))
    return _collapse_spaces(phone)


def _collapse_spaces(value: str) -> str:
    return " ".join((value or "").strip().split())


def _parse_no_answer_count(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(3, count))


def normalize_last_name(value: str) -> str:
    collapsed = _collapse_spaces(value)
    return collapsed.upper()

def normalize_first_name(value: str) -> str:
    collapsed = _collapse_spaces(value)
    lowered = collapsed.lower()
    return lowered.title()


def _trainee_alpha_sort_key(trainee: Dict[str, Any]) -> Tuple[str, str]:
    last_name = _normalized_token(trainee.get("last_name") or "")
    first_name = _normalized_token(trainee.get("first_name") or "")
    return last_name, first_name


def _ocr_extract_text_from_image(file_bytes: bytes, filename: str, content_type: str = "") -> Tuple[str, str]:
    api_key = (os.environ.get("OCR_SPACE_API_KEY") or "helloworld").strip()
    if not file_bytes:
        return "", "empty_file"

    def _build_ocr_variants(original_bytes: bytes) -> List[Tuple[bytes, str, str]]:
        variants: List[Tuple[bytes, str, str]] = [
            (original_bytes, filename or "upload.png", content_type or "application/octet-stream")
        ]
        try:
            with Image.open(BytesIO(original_bytes)) as img:
                prepared = ImageOps.exif_transpose(img)

                processed_variants: List[Tuple[Image.Image, str]] = []

                # Variante "fidÃ¨le" : niveaux de gris + autocontraste.
                grayscale = ImageOps.grayscale(prepared)
                boosted = ImageOps.autocontrast(grayscale)
                processed_variants.append((boosted, "upload-preprocessed.png"))

                # Variante "compressÃ©e" : rÃ©duit la taille des captures trÃ¨s grandes
                # qui Ã©chouent parfois cÃ´tÃ© API OCR (timeouts / no text parsed).
                max_edge = 1800
                resized = boosted.copy()
                longest_edge = max(resized.size) if resized.size else 0
                if longest_edge > max_edge:
                    ratio = max_edge / float(longest_edge)
                    new_size = (
                        max(1, int(resized.size[0] * ratio)),
                        max(1, int(resized.size[1] * ratio)),
                    )
                    resized = resized.resize(new_size, Image.Resampling.LANCZOS)
                processed_variants.append((resized, "upload-preprocessed-small.png"))

                # Variante "binaire" : utile sur captures UI trÃ¨s contrastÃ©es.
                thresholded = boosted.point(lambda p: 255 if p > 175 else 0)
                processed_variants.append((thresholded, "upload-preprocessed-bw.png"))

                for variant_img, variant_name in processed_variants:
                    out = BytesIO()
                    variant_img.save(out, format="PNG", optimize=True)
                    variants.append((out.getvalue(), variant_name, "image/png"))
        except Exception:
            pass
        return variants

    # Render/Gunicorn tue le worker aprÃ¨s ~30s. On borne strictement la durÃ©e
    # de cette fonction pour Ã©viter un redÃ©marrage du process en pleine requÃªte.
    started_at = time.monotonic()
    max_total_seconds = 20.0
    last_error = "ocr_failed"
    for file_variant, file_name_variant, content_type_variant in _build_ocr_variants(file_bytes):
        if (time.monotonic() - started_at) >= max_total_seconds:
            return "", "ocr_timeout"

        files = {
            "file": (file_name_variant, file_variant, content_type_variant)
        }
        for engine in ("2", "1"):
            for language in ("fre", "eng"):
                remaining = max_total_seconds - (time.monotonic() - started_at)
                if remaining <= 0:
                    return "", "ocr_timeout"

                payload = {
                    "language": language,
                    "isOverlayRequired": "false",
                    "OCREngine": engine,
                    "scale": "true",
                    "detectOrientation": "true",
                }
                try:
                    response = requests.post(
                        "https://api.ocr.space/parse/image",
                        data=payload,
                        files=files,
                        headers={"apikey": api_key},
                        timeout=min(8.0, max(2.0, remaining)),
                    )
                    data = response.json()
                except requests.Timeout:
                    last_error = "ocr_timeout"
                    continue
                except Exception:
                    last_error = "ocr_unreachable"
                    continue

                error_message = data.get("ErrorMessage")
                if isinstance(error_message, list):
                    error_message = " ".join(str(x) for x in error_message if x)
                error_details = data.get("ErrorDetails")
                if isinstance(error_details, list):
                    error_details = " ".join(str(x) for x in error_details if x)
                if error_message or error_details:
                    raw_error = " ".join(
                        part for part in [str(error_message or "").strip(), str(error_details or "").strip()] if part
                    ).strip()
                    last_error = raw_error or "ocr_failed"

                parsed_results = data.get("ParsedResults") or []
                if not isinstance(parsed_results, list):
                    continue

                chunks: List[str] = []
                for item in parsed_results:
                    if not isinstance(item, dict):
                        continue
                    text = (item.get("ParsedText") or "").strip()
                    if text:
                        chunks.append(text)

                parsed_text = "\n".join(chunks).strip()
                if parsed_text:
                    return parsed_text, ""

    return "", last_error


def _normalized_token(value: str) -> str:
    lowered = (value or "").strip().lower()
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _is_likely_section_header(value: str) -> bool:
    token = _normalized_token(value)
    blocked_contains = (
        "informations biographiques",
        "coordonnees",
        "coordoonnees",
        "civilite",
        "niveau de formation",
        "niveau d'etudes",
        "date de naissance",
        "lieu de naissance",
        "adresse",
        "courriel",
        "telephone",
    )
    return any(part in token for part in blocked_contains)


def _extract_name_from_ocr_lines(lines: List[str]) -> Tuple[str, str]:
    for idx, line in enumerate(lines):
        clean = re.sub(r"\s+", " ", line).strip(" :\t")
        if not clean:
            continue
        if _is_likely_section_header(clean):
            continue
        if idx > 0 and _is_likely_section_header(lines[idx - 1]):
            continue

        parts = [p for p in clean.split(" ") if p]
        if len(parts) != 2:
            continue
        if not all(re.search(r"[A-Za-zÃ€-Ã¿]", p) for p in parts):
            continue
        if any(any(ch.isdigit() for ch in p) for p in parts):
            continue

        return normalize_first_name(parts[0]), normalize_last_name(parts[1])

    return "", ""


def _extract_trainee_fields_from_ocr_text(raw_text: str) -> Dict[str, str]:
    text = (raw_text or "").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    non_renseigne_tokens = {"non renseigne", "non renseignÃ©", "non renseignÃ©e"}

    def _is_non_renseigne(value: str) -> bool:
        token = _normalized_token(value)
        if token in non_renseigne_tokens:
            return True
        return "non renseigne" in token

    def _clean_ocr_value(value: str) -> str:
        cleaned = (value or "").strip()
        cleaned = re.sub(r"^[#â€¢Â·â—â–ªâ—¦\-\â€“â€”\.,:;|/\\()\[\]{}_*+~`'\"â€œâ€â€˜â€™]+", "", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    known_labels = (
        "civilite",
        "nom de famille",
        "nom",
        "prenom",
        "date de naissance",
        "lieu de naissance",
        "adresse",
        "adresse postale",
        "email",
        "courriel",
        "telephone",
        "telephone portable",
        "telephone mobile",
    )

    def _looks_like_label(value: str) -> bool:
        token = _normalized_token(value)
        if token in known_labels:
            return True
        if re.match(r"^(deuxieme|troisieme|quatrieme)\s+prenom$", token):
            return True
        if token.startswith("prenom "):
            return True
        if token.endswith(" prenom"):
            return True
        return False

    def _first_value_after_labels(
        label_tokens: Tuple[str, ...],
        max_lookahead: int = 4,
        forbidden_tokens: Optional[set] = None,
    ) -> str:
        forbidden_tokens = forbidden_tokens or set()
        for idx, line in enumerate(lines):
            token = _normalized_token(line)
            if token not in label_tokens:
                continue
            for offset in range(1, max_lookahead + 1):
                if idx + offset >= len(lines):
                    break
                candidate = _clean_ocr_value(lines[idx + offset].strip())
                if not candidate:
                    continue
                if _is_non_renseigne(candidate) or _looks_like_label(candidate):
                    continue
                if _normalized_token(candidate) in forbidden_tokens:
                    continue
                return candidate
        return ""

    def _value_after_label(label_regex: str) -> str:
        pattern = re.compile(label_regex, flags=re.IGNORECASE)
        for idx, line in enumerate(lines):
            if pattern.search(line):
                suffix = _clean_ocr_value(pattern.sub("", line).strip(" :\t"))
                if suffix and not _is_non_renseigne(suffix) and not _looks_like_label(suffix):
                    return suffix
                for offset in (1, 2, 3):
                    if idx + offset >= len(lines):
                        break
                    candidate = _clean_ocr_value(lines[idx + offset].strip())
                    if not _is_non_renseigne(candidate) and not _looks_like_label(candidate):
                        return candidate
        return ""

    def _find_phone() -> str:
        labeled_phone = _value_after_label(r"telephone\s+portable|telephone\s+mobile|telephone")
        if labeled_phone:
            m_labeled = re.search(r"(?:\+33|0)\s*[1-9](?:[\s\.-]*\d{2}){4}", labeled_phone)
            if m_labeled:
                return normalize_phone_fr(m_labeled.group(0))
        m = re.search(r"(?:\+33|0)\s*[1-9](?:[\s\.-]*\d{2}){4}", text)
        if not m:
            return ""
        return normalize_phone_fr(m.group(0))

    def _parse_birth_date_to_iso(value: str) -> str:
        v = (value or "").strip()
        if not v:
            return ""
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(v, fmt).strftime("%Y-%m-%d")
            except Exception:
                pass
        return ""

    birth_date_raw = _first_value_after_labels(("date de naissance",), max_lookahead=8) or _value_after_label(r"^\s*date\s+de\s+naissance\b")
    address_raw = _value_after_label(r"adresse\s+postale|adresse")
    first_name_raw = _first_value_after_labels(("prenom",), max_lookahead=8) or _value_after_label(r"^\s*pr[eÃ©]nom\b")
    last_name_raw = _first_value_after_labels(("nom de famille", "nom"), max_lookahead=8) or _value_after_label(r"^\s*nom\s+de\s+famille\b|^\s*nom\b")
    if any(ch.isdigit() for ch in first_name_raw):
        first_name_raw = ""
    if any(ch.isdigit() for ch in last_name_raw):
        last_name_raw = ""
    first_name = normalize_first_name(first_name_raw)
    last_name = normalize_last_name(last_name_raw)

    if _normalized_token(last_name) in {"prenom", "prenom :"}:
        last_name = ""
    if _normalized_token(first_name) in {"nom", "nom de famille"}:
        first_name = ""
    if first_name and last_name and _normalized_token(first_name) == _normalized_token(last_name):
        alt_first_name = _first_value_after_labels(
            ("prenom",),
            max_lookahead=6,
            forbidden_tokens={_normalized_token(last_name)},
        )
        if any(ch.isdigit() for ch in alt_first_name):
            alt_first_name = ""
        alt_first_name = normalize_first_name(alt_first_name)
        if alt_first_name and _normalized_token(alt_first_name) != _normalized_token(last_name):
            first_name = alt_first_name

    if not first_name or not last_name:
        extracted_first_name, extracted_last_name = _extract_name_from_ocr_lines(lines)
        if not first_name:
            first_name = extracted_first_name
        if not last_name:
            last_name = extracted_last_name

    zip_code = ""
    city = ""
    if address_raw:
        compact = re.sub(r"\s+", " ", address_raw).strip()
        compact = re.sub(r"^[A-Za-z]{1,2}\s+(?=\d)", "", compact)
        m_zip_city = re.search(r"\b(\d{5})\b\s+([A-Za-zÃ€-Ã¿\- ]+)$", compact)
        if m_zip_city:
            zip_code = m_zip_city.group(1)
            city = normalize_first_name(m_zip_city.group(2).strip())
        address_raw = compact

    birth_city = _first_value_after_labels(("lieu de naissance",), max_lookahead=8) or _value_after_label(r"^\s*lieu\s+de\s+naissance\b")
    if birth_city and ("@" in birth_city or _looks_like_label(birth_city)):
        birth_city = ""
    if birth_city and re.match(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$", birth_city):
        if not _parse_birth_date_to_iso(birth_date_raw):
            birth_date_raw = birth_city
        alternative_birth_city = _first_value_after_labels(
            ("lieu de naissance",),
            max_lookahead=12,
            forbidden_tokens={_normalized_token(birth_city)},
        )
        if (
            re.match(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$", alternative_birth_city or "")
            or "@" in (alternative_birth_city or "")
            or _looks_like_label(alternative_birth_city or "")
        ):
            birth_city = ""
        else:
            birth_city = alternative_birth_city

    email_from_label = _value_after_label(r"courriel|email|e-?mail")
    email_match = re.search(
        r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}",
        email_from_label or text,
        flags=re.IGNORECASE,
    )
    return {
        "last_name": last_name,
        "first_name": first_name,
        "birth_date": _parse_birth_date_to_iso(birth_date_raw),
        "birth_city": birth_city,
        "email": (email_match.group(0).strip() if email_match else ""),
        "phone": _find_phone(),
        "address": address_raw,
        "zip_code": zip_code,
        "city": city,
    }


def _extract_afc_candidates_from_ocr_text(raw_text: str) -> List[Dict[str, str]]:
    text = (raw_text or "").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    lines = [re.sub(r"^[^\w@+]*", "", line).strip(" :\t") for line in text.split("\n")]
    lines = [line for line in lines if line]

    if not lines:
        return []

    ident_re = re.compile(r"\b\d{5,8}[A-Z]\s*-\s*\d{3}\b", flags=re.IGNORECASE)
    email_re = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", flags=re.IGNORECASE)
    phone_re = re.compile(r"(?:\+33|0)\s*[1-9](?:[\s\.-]*\d{2}){4}")

    start_indices: List[int] = []
    for idx, line in enumerate(lines):
        if ident_re.search(line):
            start_indices.append(idx)

    if not start_indices:
        for idx, line in enumerate(lines):
            if email_re.search(line):
                start_indices.append(max(0, idx - 2))

    if not start_indices:
        return []

    start_indices = sorted(set(start_indices))
    candidates: List[Dict[str, str]] = []

    for block_idx, start in enumerate(start_indices):
        end = start_indices[block_idx + 1] if block_idx + 1 < len(start_indices) else len(lines)
        block = lines[start:end]
        if not block:
            continue

        block_text = "\n".join(block)
        ident_match = ident_re.search(block_text)
        email_match = email_re.search(block_text)
        phone_match = phone_re.search(block_text)

        identifiant_ft = ""
        if ident_match:
            identifiant_ft = re.sub(r"\s+", " ", ident_match.group(0).upper()).replace(" -", " -").replace("- ", "- ").strip()

        ignored_tokens = (
            "candidats",
            "details de la candidature",
            "dÃ©tails de la candidature",
            "var (",
            "@",
        )
        name_line = ""
        for line in block:
            lowered = _normalized_token(line)
            if any(token in lowered for token in ignored_tokens):
                continue
            if ident_re.search(line) or email_re.search(line) or phone_re.search(line):
                continue
            if sum(ch.isalpha() for ch in line) < 4:
                continue
            if len(line.split()) < 2:
                continue
            name_line = re.sub(r"\s+", " ", line).strip()
            break

        if not name_line and not (email_match or phone_match or ident_match):
            continue

        nom = ""
        prenom = ""
        if name_line:
            parts = [p for p in name_line.split(" ") if p]
            if len(parts) >= 2:
                last_parts: List[str] = []
                first_parts: List[str] = []
                switched = False
                for part in parts:
                    alpha_chars = [c for c in part if c.isalpha()]
                    is_upper_word = bool(alpha_chars) and all(c.isupper() for c in alpha_chars)
                    if not switched and is_upper_word:
                        last_parts.append(part)
                        continue
                    switched = True
                    first_parts.append(part)

                if not first_parts:
                    nom = normalize_last_name(parts[-1])
                    prenom = normalize_first_name(" ".join(parts[:-1]))
                else:
                    nom = normalize_last_name(" ".join(last_parts)) if last_parts else normalize_last_name(parts[-1])
                    prenom = normalize_first_name(" ".join(first_parts)) if first_parts else normalize_first_name(parts[0])

        if not nom and not prenom:
            continue

        candidates.append({
            "identifiant_ft": identifiant_ft,
            "nom": nom,
            "prenom": prenom,
            "email": (_normalize_afc_email(email_match.group(0)) if email_match else ""),
            "telephone": (format_phone_fr_for_display(phone_match.group(0)) if phone_match else ""),
        })

    return candidates


def _afc_candidate_dedup_key(candidate: Dict[str, Any]) -> str:
    identifiant_ft = re.sub(r"\s+", "", str(candidate.get("identifiant_ft") or "").upper())
    if identifiant_ft:
        return "identifiant_ft:" + identifiant_ft

    email = _normalize_afc_email(candidate.get("email")).lower()
    if email:
        return "email:" + email

    nom = normalize_last_name(str(candidate.get("nom") or ""))
    prenom = normalize_first_name(str(candidate.get("prenom") or ""))
    telephone = "".join(ch for ch in str(candidate.get("telephone") or "") if ch.isdigit())
    return f"name_phone:{nom}|{prenom}|{telephone}"


def _normalize_afc_email(raw_email: Any) -> str:
    value = str(raw_email or "").strip()
    if "@" not in value:
        return value

    local, domain = value.split("@", 1)
    local = local.lstrip(" _.-")
    domain = domain.lstrip(" _.-")
    normalized = f"{local}@{domain}".strip()
    return normalized


def _create_afc_candidate(payload: Dict[str, Any], *, import_source: str = "") -> Dict[str, Any]:
    """Unique factory shared by manual creation and confirmed image imports."""
    nom = str(payload.get("nom") or "").strip()
    prenom = str(payload.get("prenom") or "").strip()
    cnaps_lookup = fetch_cnaps_lookup_by_name(nom, prenom) or {}
    created_at = _now_iso()
    candidate = {
        "id": "AFC-" + uuid.uuid4().hex[:8].upper(),
        "identifiant_ft": str(payload.get("identifiant_ft") or "").strip(),
        "nom": nom, "prenom": prenom,
        "email": str(payload.get("email") or "").strip(),
        "telephone": str(payload.get("telephone") or "").strip(),
        "decision": "", "notification_status": "",
        "cnaps_status": cnaps_lookup.get("status") or "INCONNU",
        "cnaps_status_history": cnaps_lookup.get("statut_cnaps_history") or [],
        "cnaps_status_changed_at": created_at,
        "motif_refus": "", "complement_refus": "", "complement_refus_autre": "",
        "modules": {"formation_technique": 0, "remise_niveau": 0, "soutien_personnalise": 0, "paf": 0},
        "dates_formation": "", "test_francais_reussi": None, "cnaps_priority": False,
        "presence_afc": False, "presence_afc_status": "A_CONVOQUER",
        "test_results_comment": "", "created_at": created_at,
    }
    if import_source:
        candidate["source"] = import_source
    return candidate



import base64

def _parse_email_recipient_blocklist(raw_value: str) -> Set[str]:
    return {
        item.strip().lower()
        for item in re.split(r"[,;\s]+", raw_value or "")
        if item.strip()
    }


EMAIL_RECIPIENT_BLOCKLIST = _parse_email_recipient_blocklist(os.environ.get("EMAIL_RECIPIENT_BLOCKLIST", ""))


def _is_blocked_email_recipient(email: str) -> bool:
    return (email or "").strip().lower() in EMAIL_RECIPIENT_BLOCKLIST


CNAPS_STATUS_CHANGE_NOTIFICATION_TO = "cassandre@integraleacademy.com"
CNAPS_STATUS_CHANGE_NOTIFICATION_CC = ["elsa@integraleacademy.com", "clement@integraleacademy.com"]
CNAPS_MONITOR_TOKEN = os.environ.get("CNAPS_MONITOR_TOKEN", "").strip()
CNAPS_MONITOR_REQUEST_DELAY_SECONDS = max(0.0, float(os.environ.get("CNAPS_MONITOR_REQUEST_DELAY_SECONDS", "1")))
AFC_CNAPS_REFRESH_INTERVAL_SECONDS = max(60, int(os.environ.get("AFC_CNAPS_REFRESH_INTERVAL_SECONDS", "900")))
AFC_CNAPS_REFRESH_REQUEST_DELAY_SECONDS = max(
    0.0,
    float(os.environ.get("AFC_CNAPS_REFRESH_REQUEST_DELAY_SECONDS", "0.25")),
)

def _cnaps_status_change_key(last_name: str, nub: str) -> str:
    normalized_name = unicodedata.normalize("NFD", str(last_name or ""))
    normalized_name = "".join(ch for ch in normalized_name if unicodedata.category(ch) != "Mn")
    normalized_name = re.sub(r"\s+", " ", normalized_name).strip().upper()
    normalized_nub = re.sub(r"\D+", "", str(nub or ""))[-7:]
    return f"{normalized_name}|{normalized_nub}"

def _cnaps_result_signature(result: Dict[str, Any]) -> str:
    active_titles = result.get("active_titles")
    if isinstance(active_titles, list):
        rows = active_titles
    else:
        rows = result.get("results") if isinstance(result.get("results"), list) else [result]
    parts = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        values = [
            str(row.get(key) or "").strip()
            for key in (
                "display_status", "label", "activity", "activite", "typeActivite",
                "status", "validity", "validite_titre", "agrementStatutEs",
                "date_fin_validite", "valid_until", "date_validite_titre", "dateFinValidite",
            )
        ]
        parts.append(" â€¢ ".join(value for value in values if value))
    return " || ".join(part for part in parts if part).strip()

def _cnaps_result_has_known_status(result: Dict[str, Any]) -> bool:
    signature = _cnaps_result_signature(result).upper()
    return bool(signature and "INCONNU" not in signature)

def _cnaps_pending_status_change_count(data: Dict[str, Any]) -> int:
    notifications = data.get("cnaps_status_change_notifications") or {}
    if not isinstance(notifications, dict):
        return 0
    return sum(
        1
        for item in notifications.values()
        if isinstance(item, dict) and not item.get("reviewed_at")
    )


def _annotate_cnaps_tracking_status_changes(rows: List[Dict[str, Any]], data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flag tracking rows that have generated a CNAPS status-change notification.

    Only outstanding notifications are kept at the top of the tracking screen.
    A notification marked as seen remains visible on its dossier for context,
    but is no longer a status change to be handled.
    """
    notifications = data.get("cnaps_status_change_notifications") or {}
    if not isinstance(notifications, dict):
        notifications = {}
    for row in rows:
        notification = notifications.get(_cnaps_status_change_key(row.get("last_name"), row.get("nub")))
        tracking_id = str(row.get("tracking_id") or "").strip()
        if not isinstance(notification, dict) and tracking_id:
            notification = next(
                (
                    item for item in notifications.values()
                    if isinstance(item, dict)
                    and str(item.get("tracking_id") or "").strip() == tracking_id
                ),
                None,
            )
        row["status_change_notified"] = isinstance(notification, dict)
        row["status_change_reviewed"] = bool(notification.get("reviewed_at")) if isinstance(notification, dict) else False
    return sorted(rows, key=lambda row: not (row["status_change_notified"] and not row["status_change_reviewed"]))


def _mark_cnaps_status_change_imported(data: Dict[str, Any], *, last_name: str, nub: str) -> bool:
    key = _cnaps_status_change_key(last_name, nub)
    notifications = data.get("cnaps_status_change_notifications")
    if not key or key == "|" or not isinstance(notifications, dict):
        return False
    item = notifications.get(key)
    if not isinstance(item, dict) or item.get("reviewed_at"):
        return False
    item["reviewed_at"] = _now_iso()
    item["reviewed_reason"] = "import_pre_cnaps"
    return True

def _cnaps_trainee_enrollments(data: Dict[str, Any], *, first_name: str, last_name: str, nub: str) -> List[Dict[str, str]]:
    """Return the sessions in which the CNAPS dossier holder is enrolled."""
    normalized_nub = re.sub(r"\D+", "", str(nub or ""))[-7:]
    normalized_first_name = _normalized_token(first_name)
    normalized_last_name = _normalized_token(last_name)
    enrollments: List[Dict[str, str]] = []

    for session_obj in data.get("sessions", []) or []:
        if not isinstance(session_obj, dict) or bool(session_obj.get("archived")) or _is_wedof_leads_session(session_obj):
            continue
        for trainee in _registered_trainees(session_obj):
            trainee_nub = re.sub(
                r"\D+", "", str(
                    trainee.get("nub")
                    or trainee.get("cnaps_nub")
                    or trainee.get("cnaps_tracking_nub")
                    or extract_nub_from_pre_car(str(trainee.get("pre_number") or ""))
                    or ""
                ),
            )[-7:]
            matches_nub = bool(normalized_nub and trainee_nub == normalized_nub)
            matches_name = (
                bool(normalized_first_name and normalized_last_name)
                and _normalized_token(trainee.get("first_name")) == normalized_first_name
                and _normalized_token(trainee.get("last_name")) == normalized_last_name
            )
            if not (matches_nub or matches_name):
                continue
            enrollments.append({
                "formation": formation_label(_session_get(session_obj, "training_type", "")) or "Formation non renseignÃ©e",
                "date_start": fr_date(_session_get(session_obj, "date_start", "")),
                "date_end": fr_date(_session_get(session_obj, "date_end", "")),
            })
            break
    return enrollments


def _cnaps_trainee_first_name(data: Dict[str, Any], *, last_name: str, nub: str) -> str:
    """Find a missing first name from an active trainee record when possible."""
    normalized_nub = re.sub(r"\D+", "", str(nub or ""))[-7:]
    normalized_last_name = _normalized_token(last_name)
    if not normalized_nub and not normalized_last_name:
        return ""

    for session_obj in data.get("sessions", []) or []:
        if not isinstance(session_obj, dict) or bool(session_obj.get("archived")) or _is_wedof_leads_session(session_obj):
            continue
        for trainee in _registered_trainees(session_obj):
            trainee_nub = re.sub(
                r"\D+", "", str(
                    trainee.get("nub")
                    or trainee.get("cnaps_nub")
                    or trainee.get("cnaps_tracking_nub")
                    or extract_nub_from_pre_car(str(trainee.get("pre_number") or ""))
                    or ""
                ),
            )[-7:]
            matches_nub = bool(normalized_nub and trainee_nub == normalized_nub)
            matches_last_name = bool(
                normalized_last_name
                and _normalized_token(trainee.get("last_name")) == normalized_last_name
            )
            if matches_nub or matches_last_name:
                return str(trainee.get("first_name") or "").strip()
    return ""


def build_cnaps_status_change_email(
    first_name: str,
    last_name: str,
    nub: str,
    new_status: str,
    enrollments: Optional[List[Dict[str, str]]] = None,
    previous_status: str = "",
) -> Tuple[str, str]:
    full_name = " ".join(part for part in [str(first_name or "").strip(), str(last_name or "").strip()] if part) or "Stagiaire"
    safe_name = html.escape(full_name)
    safe_nub = html.escape(str(nub or "â€”"))
    safe_status = html.escape(new_status or "Statut Ã  vÃ©rifier")
    safe_previous_status = html.escape(previous_status or "Ã‰tat prÃ©cÃ©dent non renseignÃ©")
    safe_logo_url = html.escape(f"{PUBLIC_BASE_URL.rstrip('/')}/static/logo-integrale.png", quote=True)
    enrollment_rows = []
    for enrollment in enrollments or []:
        formation = html.escape(str(enrollment.get("formation") or "Formation non renseignÃ©e"))
        date_start = html.escape(str(enrollment.get("date_start") or "Ã€ confirmer"))
        date_end = html.escape(str(enrollment.get("date_end") or "Ã€ confirmer"))
        enrollment_rows.append(
            f'<li style="margin:8px 0;"><strong>{formation}</strong><br><span style="color:#475569;">Du {date_start} au {date_end}</span></li>'
        )
    enrollment_html = (
        '<div style="margin-top:18px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:18px;padding:18px;">'
        '<div style="font-size:12px;font-weight:800;color:#1d4ed8;text-transform:uppercase;letter-spacing:.12em;">Inscrit(e) en formation : OUI</div>'
        f'<ul style="margin:10px 0 0;padding-left:20px;font-size:15px;line-height:1.5;color:#0f172a;">{"".join(enrollment_rows)}</ul>'
        '</div>'
        if enrollment_rows else
        '<div style="margin-top:18px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:18px;padding:18px;font-size:15px;font-weight:800;color:#475569;">Inscrit(e) en formation : NON</div>'
    )
    subject = f"Changement de statut CNAPS â€” {full_name}"
    html_body = f"""
    <div style="margin:0;padding:0;background:#f4f7fb;font-family:Inter,Arial,sans-serif;color:#0f172a;">
      <div style="max-width:680px;margin:0 auto;padding:32px 18px;">
        <div style="background:linear-gradient(135deg,#111827,#2563eb);border-radius:28px;padding:28px;color:#fff;box-shadow:0 24px 70px rgba(15,23,42,.22);text-align:center;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr><td align="center">
            <img src="{safe_logo_url}" alt="IntÃ©grale Academy" width="176" style="display:block;width:176px;max-width:100%;height:auto;margin:0 auto 24px;">
          </td></tr></table>
          <div style="font-size:12px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;opacity:.82;">IntÃ©grale Academy Â· CNAPS</div>
          <h1 style="margin:16px 0 8px;font-size:30px;line-height:1.1;">Changement de statut</h1>
        </div>
        <div style="margin-top:-18px;background:#fff;border:1px solid #e5e7eb;border-radius:24px;padding:26px;box-shadow:0 18px 55px rgba(15,23,42,.10);">
          <div style="display:inline-block;background:#dcfce7;color:#166534;border-radius:999px;padding:8px 12px;font-size:12px;font-weight:900;text-transform:uppercase;letter-spacing:.08em;">Nouveau statut dÃ©tectÃ©</div>
          <div style="margin:18px 0 4px;font-size:12px;font-weight:800;color:#64748b;text-transform:uppercase;letter-spacing:.12em;">Stagiaire</div>
          <h2 style="margin:0 0 6px;font-size:24px;color:#111827;">{safe_name}</h2>
          <p style="margin:0 0 18px;color:#64748b;font-size:14px;">NUB : <strong style="color:#111827;">{safe_nub}</strong></p>
          <div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:18px;padding:18px;margin-bottom:12px;">
            <div style="font-size:12px;font-weight:800;color:#9a3412;text-transform:uppercase;letter-spacing:.12em;">Ancien statut</div>
            <div style="margin-top:8px;font-size:16px;font-weight:800;color:#7c2d12;line-height:1.45;">{safe_previous_status}</div>
          </div>
          <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:18px;padding:18px;">
            <div style="font-size:12px;font-weight:800;color:#64748b;text-transform:uppercase;letter-spacing:.12em;">Nouveau statut</div>
            <div style="margin-top:8px;font-size:18px;font-weight:900;color:#0f172a;line-height:1.45;">{safe_status}</div>
          </div>
          {enrollment_html}
          <p style="margin:20px 0 0;color:#475569;font-size:14px;line-height:1.6;">Merci de vÃ©rifier le dossier dans le suivi CNAPS et de rÃ©aliser les actions nÃ©cessaires.</p>
        </div>
      </div>
    </div>
    """
    return subject, html_body

def _create_cnaps_status_change_notification(
    data: Dict[str, Any],
    *,
    first_name: str,
    last_name: str,
    nub: str,
    previous_status: str,
    new_status: str,
    tracking_id: str = "",
) -> bool:
    """Create the in-app alert and attempt its email delivery.

    The in-app notification is deliberately persisted even when Brevo is
    temporarily unavailable.  Email delivery must not be able to erase a real
    CNAPS state change from the dashboard.
    """
    key = _cnaps_status_change_key(last_name, nub)
    if not key or key == "|":
        return False
    signature = str(new_status or "").strip()
    if not signature:
        return False
    sent = data.setdefault("cnaps_status_change_notifications", {})
    if not isinstance(sent, dict):
        sent = {}
        data["cnaps_status_change_notifications"] = sent
    # Do not resend an alert for the exact same CNAPS status.  A later,
    # genuinely different status is nevertheless a new change to notify.
    if isinstance(sent.get(key), dict) and sent[key].get("signature") == signature:
        return False
    first_name = str(first_name or "").strip() or _cnaps_trainee_first_name(data, last_name=last_name, nub=nub)
    enrollments = _cnaps_trainee_enrollments(data, first_name=first_name, last_name=last_name, nub=nub)
    created_at = _now_iso()
    notification = {
        "signature": signature,
        "previous_status": str(previous_status or "").strip(),
        "created_at": created_at,
        "sent_at": "",
        "email_status": "pending",
        "first_name": first_name,
        "last_name": last_name,
        "nub": nub,
        "tracking_id": str(tracking_id or "").strip(),
    }
    # Persist the dashboard alert before attempting the external email call.
    sent[key] = notification
    subject, html_body = build_cnaps_status_change_email(
        first_name,
        last_name,
        nub,
        signature,
        enrollments,
        previous_status=str(previous_status or "").strip(),
    )
    try:
        response = brevo_send_email(
            CNAPS_STATUS_CHANGE_NOTIFICATION_TO,
            subject,
            html_body,
            cc_emails=CNAPS_STATUS_CHANGE_NOTIFICATION_CC,
            metadata={"purpose": "cnaps_status_change", "cnaps_key": key},
        )
    except Exception as exc:
        app.logger.exception("[CNAPS_STATUS_CHANGE] erreur inattendue pendant l'envoi key=%s", key)
        response = {"ok": False, "error": str(exc) or "Erreur inattendue Brevo"}
    if not isinstance(response, dict):
        response = {"ok": bool(response), "error": "RÃ©ponse Brevo invalide" if not response else ""}
    if response.get("ok"):
        notification["sent_at"] = _now_iso()
        notification["email_sent_at"] = notification["sent_at"]
        notification["email_status"] = "sent"
        notification["email_message_id"] = str(response.get("message_id") or "")
    else:
        notification["email_status"] = "failed"
        notification["email_error"] = str(response.get("error") or "Envoi Brevo impossible")[:500]
        notification["email_last_attempt_at"] = _now_iso()
        app.logger.warning("[CNAPS_STATUS_CHANGE] email non envoyÃ© key=%s error=%s", key, response.get("error"))
    return True


def _notify_cnaps_status_change(
    data: Dict[str, Any],
    *,
    first_name: str,
    last_name: str,
    nub: str,
    result: Dict[str, Any],
    previous_status: str = "",
    tracking_id: str = "",
) -> bool:
    if not _cnaps_result_has_known_status(result):
        return False
    return _create_cnaps_status_change_notification(
        data,
        first_name=first_name,
        last_name=last_name,
        nub=nub,
        previous_status=previous_status,
        new_status=_cnaps_result_signature(result),
        tracking_id=tracking_id,
    )


def _cnaps_public_annuaire_status_key(last_name: str, nub: str) -> str:
    return _cnaps_status_change_key(last_name, nub)


def _cnaps_tracking_monitor_key(*, tracking_id: str, first_name: str, last_name: str) -> str:
    """Return an identity that survives a missing or newly assigned NUB."""
    normalized_tracking_id = re.sub(r"[^A-Za-z0-9._:-]+", "", str(tracking_id or "").strip())
    if normalized_tracking_id:
        return f"TRACKING|{normalized_tracking_id}"
    normalized_last_name = _cnaps_tracking_normalize_key_part(last_name)
    normalized_first_name = _cnaps_tracking_normalize_key_part(first_name)
    if not normalized_last_name and not normalized_first_name:
        return ""
    return f"PERSON|{normalized_last_name}|{normalized_first_name}"


def _cnaps_tracking_state_details(nub: str, result: Optional[Dict[str, Any]]) -> Tuple[str, str, str, bool]:
    normalized_nub = re.sub(r"\D+", "", str(nub or ""))[-7:]
    if len(normalized_nub) != 7:
        return "nub_missing", "NUB absent", "", False
    signature = _cnaps_result_signature(result or {})
    if _cnaps_result_has_known_status(result or {}):
        return "titles", signature, signature, True
    return "no_title", "Aucun titre CNAPS trouvÃ©", "", False


def _cnaps_tracking_state_code(entry: Dict[str, Any]) -> str:
    explicit = str(entry.get("state_code") or "").strip()
    if explicit:
        return explicit
    display_status = str(entry.get("display_status") or "").strip().upper()
    if display_status == "NUB ABSENT":
        return "nub_missing"
    signature = str(entry.get("signature") or "").strip()
    if bool(entry.get("known")) or (signature and "INCONNU" not in signature.upper()):
        return "titles"
    return "no_title"


def _cnaps_tracking_state_display(entry: Dict[str, Any]) -> str:
    display_status = str(entry.get("display_status") or "").strip()
    if display_status:
        return display_status
    if _cnaps_tracking_state_code(entry) == "titles":
        return str(entry.get("signature") or "Statut CNAPS dÃ©tectÃ©").strip()
    if _cnaps_tracking_state_code(entry) == "nub_missing":
        return "NUB absent"
    return "Aucun titre CNAPS trouvÃ©"


def _record_cnaps_tracking_state(
    data: Dict[str, Any],
    *,
    first_name: str,
    last_name: str,
    nub: str,
    tracking_id: str = "",
    result: Optional[Dict[str, Any]] = None,
) -> bool:
    """Persist every visible tracking state and notify on a real transition.

    In particular, ``NUB absent`` is retained under the CNAPSV3 request ID so
    the later first annuaire result is a change, not a fresh baseline.
    """
    monitor_key = _cnaps_tracking_monitor_key(
        tracking_id=tracking_id,
        first_name=first_name,
        last_name=last_name,
    )
    if not monitor_key:
        return False
    statuses = data.setdefault("cnaps_public_annuaire_statuses", {})
    if not isinstance(statuses, dict):
        statuses = {}
        data["cnaps_public_annuaire_statuses"] = statuses

    normalized_nub = re.sub(r"\D+", "", str(nub or ""))[-7:]
    legacy_key = (
        _cnaps_public_annuaire_status_key(last_name, normalized_nub)
        if len(normalized_nub) == 7
        else ""
    )
    state_code, display_status, signature, known = _cnaps_tracking_state_details(normalized_nub, result)
    previous = statuses.get(monitor_key) if isinstance(statuses.get(monitor_key), dict) else None
    # Migrate the status map that predates stable CNAPSV3 request identities.
    if previous is None and legacy_key and isinstance(statuses.get(legacy_key), dict):
        previous = dict(statuses[legacy_key])

    checked_at = _now_iso()
    base_entry = {
        "state_code": state_code,
        "display_status": display_status,
        "known": known,
        "signature": signature,
        "checked_at": checked_at,
        "tracking_id": str(tracking_id or "").strip(),
        "first_name": str(first_name or "").strip(),
        "last_name": str(last_name or "").strip(),
        "nub": normalized_nub,
    }
    if previous is None:
        current_entry = {**base_entry, "status_since": checked_at}
        statuses[monitor_key] = current_entry
        if legacy_key:
            statuses[legacy_key] = dict(current_entry)
        return False

    # A successful HTTP response with no title is not evidence that a title
    # previously found by the directory disappeared.  Keeping the last known
    # state avoids false alerts on a transient/partial annuaire response.
    previous_state_code = _cnaps_tracking_state_code(previous)
    if previous_state_code == "titles" and state_code == "no_title":
        preserved_entry = {
            **previous,
            "checked_at": checked_at,
            "last_empty_result_at": checked_at,
        }
        statuses[monitor_key] = preserved_entry
        if legacy_key:
            statuses[legacy_key] = dict(preserved_entry)
        return False

    previous_signature = str(previous.get("signature") or "")
    changed = previous_state_code != state_code or (
        state_code == "titles" and previous_signature != signature
    )
    current_entry = {
        **base_entry,
        "status_since": checked_at if changed else (
            previous.get("status_since") or previous.get("checked_at") or checked_at
        ),
        **({"last_empty_result_at": previous["last_empty_result_at"]} if previous.get("last_empty_result_at") else {}),
    }
    statuses[monitor_key] = current_entry
    if legacy_key:
        statuses[legacy_key] = dict(current_entry)

    if not changed or state_code == "nub_missing":
        return False
    return _create_cnaps_status_change_notification(
        data,
        first_name=first_name,
        last_name=last_name,
        nub=normalized_nub,
        previous_status=_cnaps_tracking_state_display(previous),
        new_status=display_status,
        tracking_id=tracking_id,
    )


def _record_cnaps_public_annuaire_status(
    data: Dict[str, Any],
    *,
    first_name: str,
    last_name: str,
    nub: str,
    result: Dict[str, Any],
    tracking_id: str = "",
) -> bool:
    """Record a successful public-annuaire result and notify on a change."""
    return _record_cnaps_tracking_state(
        data,
        first_name=first_name,
        last_name=last_name,
        nub=nub,
        tracking_id=tracking_id,
        result=result,
    )


def run_cnaps_public_annuaire_monitor() -> Dict[str, Any]:
    """Check tracked CNAPS files without requiring an administrator page visit."""
    job_started_at = time.monotonic()
    app.logger.info("[CNAPS_MONITOR] JOB_BEGIN")
    rows: List[Dict[str, Any]] = []
    checked = notified = errors = 0
    try:
        step_started_at = time.monotonic()
        app.logger.info("[CNAPS_MONITOR] CANDIDATE_SELECTION_BEGIN")
        rows, fetch_error = fetch_cnapsv3_tracking_requests()
        if fetch_error:
            app.logger.warning("[CNAPS_MONITOR] CANDIDATE_SELECTION_ERROR duration_ms=%s error=%s", int((time.monotonic() - step_started_at) * 1000), fetch_error)
            return {"checked": 0, "notified": 0, "errors": 1, "status": "fetch_error", "error": str(fetch_error)[:160]}
        app.logger.info("[CNAPS_MONITOR] CANDIDATE_SELECTION_END duration_ms=%s candidates=%s", int((time.monotonic() - step_started_at) * 1000), len(rows))

        seen: Set[str] = set()
        observations: List[Tuple[str, str, str, str, Optional[Dict[str, Any]]]] = []
        for index, row in enumerate(rows, start=1):
            candidate_started_at = time.monotonic()
            last_name = str(row.get("last_name") or "").strip()
            first_name = str(row.get("first_name") or "").strip()
            tracking_id = str(row.get("tracking_id") or "").strip()
            nub = re.sub(r"\D+", "", str(row.get("nub") or ""))[-7:]
            key = _cnaps_tracking_monitor_key(
                tracking_id=tracking_id,
                first_name=first_name,
                last_name=last_name,
            )
            app.logger.info("[CNAPS_MONITOR] CANDIDATE_BEGIN index=%s key=%s nub_masked=%s", index, key, _mask_cnaps_nub(nub))
            if not last_name or not key or key in seen:
                app.logger.info("[CNAPS_MONITOR] CANDIDATE_END index=%s skipped=true duration_ms=%s", index, int((time.monotonic() - candidate_started_at) * 1000))
                continue
            seen.add(key)
            if len(nub) != 7:
                # Missing NUB is a real visible state.  Persist it so a later
                # NUB/title appearance is detected as a transition.
                observations.append((first_name, last_name, nub, tracking_id, None))
                app.logger.info("[CNAPS_MONITOR] CANDIDATE_END index=%s state=nub_missing duration_ms=%s", index, int((time.monotonic() - candidate_started_at) * 1000))
                continue
            call_started_at = time.monotonic()
            app.logger.info("[CNAPS_MONITOR] CNAPS_CALL_BEGIN index=%s key=%s", index, key)
            result = fetch_cnaps_public_annuaire(last_name, nub)
            app.logger.info("[CNAPS_MONITOR] CNAPS_CALL_END index=%s key=%s status=%s duration_ms=%s", index, key, result.get("check_status"), int((time.monotonic() - call_started_at) * 1000))
            if result.get("check_status") != "success":
                errors += 1
                app.logger.info("[CNAPS_MONITOR] CANDIDATE_END index=%s error=true duration_ms=%s", index, int((time.monotonic() - candidate_started_at) * 1000))
                continue
            checked += 1
            observations.append((first_name, last_name, nub, tracking_id, result))
            if CNAPS_MONITOR_REQUEST_DELAY_SECONDS:
                time.sleep(CNAPS_MONITOR_REQUEST_DELAY_SECONDS)
            app.logger.info("[CNAPS_MONITOR] CANDIDATE_END index=%s duration_ms=%s", index, int((time.monotonic() - candidate_started_at) * 1000))
        if observations:
            save_started_at = time.monotonic()
            app.logger.info("[CNAPS_MONITOR] SAVE_BEGIN")

            def merge_cnaps_results(latest_data: Dict[str, Any]) -> int:
                merged_notified = 0
                for first_name, last_name, nub, tracking_id, result in observations:
                    if _record_cnaps_tracking_state(
                        latest_data,
                        first_name=first_name,
                        last_name=last_name,
                        nub=nub,
                        tracking_id=tracking_id,
                        result=result,
                    ):
                        merged_notified += 1
                return merged_notified

            notified = update_data(merge_cnaps_results, run_background_tasks=False)
            app.logger.info("[CNAPS_MONITOR] SAVE_END duration_ms=%s", int((time.monotonic() - save_started_at) * 1000))
        return {"checked": checked, "notified": notified, "errors": errors, "status": "done"}
    finally:
        app.logger.info("[CNAPS_MONITOR] JOB_END duration_ms=%s candidates=%s checked=%s notified=%s errors=%s", int((time.monotonic() - job_started_at) * 1000), len(rows), checked, notified, errors)

def brevo_send_email(
    to_email: str,
    subject: str,
    html: str,
    cc_emails: Optional[List[str]] = None,
    trainee: Optional[Dict[str, Any]] = None,
    attachments: Optional[List[Dict[str, str]]] = None,
    text_content: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    to_email = (to_email or "").strip()
    missing = _missing_brevo_config()
    if not to_email:
        missing.append("destinataire")
    if missing:
        result = {"ok": False, "status_code": None, "message_id": "", "error": "Configuration Brevo incomplÃ¨te : " + ", ".join(missing)}
        return result if metadata is not None else False
    if _is_blocked_email_recipient(to_email):
        print(f"[EMAIL] blocked recipient skipped: {to_email}")
        result = {"ok": False, "status_code": None, "message_id": "", "error": "Destinataire bloquÃ©"}
        return result if metadata is not None else False

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }

    email_attachments = [item for item in (attachments or []) if isinstance(item, dict) and item.get("content") and item.get("name")]

    payload = {
        "sender": {"name": BREVO_SENDER_NAME, "email": BREVO_SENDER_EMAIL},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
    }

    if text_content:
        payload["textContent"] = text_content

    cc_list = [
        email.strip()
        for email in (cc_emails or [])
        if email and not _is_blocked_email_recipient(email)
    ]
    if cc_list:
        payload["cc"] = [{"email": email} for email in cc_list]

    if email_attachments:
        payload["attachment"] = email_attachments

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=12)
        ok = r.status_code in (200, 201, 202)
        try:
            response_json = r.json()
        except Exception:
            response_json = {}
        message_id = str(response_json.get("messageId") or response_json.get("message_id") or "")
        error_message = str(response_json.get("message") or response_json.get("error") or (r.text or ""))[:500]
        _safe_brevo_log("send", timestamp=_now_iso(), partner_id=(metadata or {}).get("partner_id"), partner_name=(metadata or {}).get("partner_name"), user_id=(metadata or {}).get("user_id"), to_email=to_email, status_code=r.status_code, error="" if ok else error_message, message_id=message_id)
        if ok and has_request_context():
            session["_mail_sent_notice"] = True
        if ok and isinstance(trainee, dict):
            sent_history = trainee.get("sent_email_history")
            if not isinstance(sent_history, list):
                sent_history = []
            sent_history.insert(0, {
                "to_email": (to_email or "").strip(),
                "subject": (subject or "").strip(),
                "html": html or "",
                "sent_at": _now_iso(),
            })
            trainee["sent_email_history"] = sent_history[:200]
        if (not ok) and _brevo_no_credit_detected(r.text):
            _register_brevo_no_credit("email", to_email, r.text)
        result = {"ok": ok, "status_code": r.status_code, "message_id": message_id, "error": "" if ok else error_message}
        return result if metadata is not None else ok
    except Exception as exc:
        _safe_brevo_log("exception", timestamp=_now_iso(), partner_id=(metadata or {}).get("partner_id"), partner_name=(metadata or {}).get("partner_name"), user_id=(metadata or {}).get("user_id"), to_email=to_email, status_code=None, error=str(exc)[:500], message_id="")
        result = {"ok": False, "status_code": None, "message_id": "", "error": str(exc)}
        return result if metadata is not None else False


def brevo_send_sms(phone: str, message: str) -> bool:
    phone = normalize_phone_fr(phone)
    if not BREVO_API_KEY or not phone:
        print("[SMS] Missing BREVO_API_KEY or phone")
        return False

    url = "https://api.brevo.com/v3/transactionalSMS/sms"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }

    # (souvent requis selon config Brevo) : nom dâ€™expÃ©diteur SMS
    sms_sender = os.environ.get("BREVO_SMS_SENDER", "").strip()

    payload = {
        "recipient": phone,
        "content": message,
        "type": "transactional",
        "unicodeEnabled": True,
    }
    if sms_sender:
        payload["sender"] = sms_sender  # ex: "INTEGRALE"

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=12)

        # âœ… logs indispensables (status + rÃ©ponse Brevo)
        print("[SMS] status=", r.status_code)
        print("[SMS] response=", r.text)

        ok = r.status_code in (200, 201, 202)
        if (not ok) and _brevo_no_credit_detected(r.text):
            _register_brevo_no_credit("sms", phone, r.text)
        return ok
    except Exception as e:
        print("[SMS] exception=", repr(e))
        return False


def notify_elearning_access_available(trainee: Dict[str, Any], session_obj: Dict[str, Any], link: str) -> Dict[str, bool]:
    first_name = (trainee.get("first_name") or "").strip() or "Madame, Monsieur"
    training_name = formation_label(_session_get(session_obj, "training_type", ""))
    date_start = fr_date(_session_get(session_obj, "date_start", ""))
    date_end = fr_date(_session_get(session_obj, "date_end", ""))
    student_space_link = f"{PUBLIC_STUDENT_PORTAL_BASE.rstrip('/')}/espace/{(trainee.get('public_token') or '').strip()}"
    access_link = student_space_link if (trainee.get("public_token") or "").strip() else link

    subject = "Votre accÃ¨s e-learning est disponible â€“ IntÃ©grale Academy"
    html = mail_layout(f"""
      <h2 style="text-align:center">ðŸš€ AccÃ¨s e-learning activÃ©</h2>
      <p>Bonjour <strong>{first_name}</strong>,</p>
      <p>
        Bonne nouvelle : votre accÃ¨s Ã  la <strong>Formation thÃ©orique en e-learning</strong>
        est maintenant disponible.
      </p>
      <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;padding:14px;margin:16px 0;">
        <p style="margin:0 0 10px 0;">
          <strong>ðŸ“Œ Formation :</strong> {training_name}
          {" â€” <strong>Dates :</strong> " + date_start + " au " + date_end if (date_start or date_end) else ""}
        </p>
        <p style="margin:0;">
          <strong>ðŸ”— AccÃ©der Ã  votre Espace Stagiaire :</strong><br>
          <a href="{access_link}" style="display:inline-block;margin-top:8px;background:#2563eb;color:#ffffff;text-decoration:none;font-weight:700;padding:10px 16px;border-radius:8px;">
            AccÃ©der Ã  mon Espace Stagiaire
          </a>
        </p>
      </div>
      <p>
        Vous pouvez dÃ¨s maintenant retrouver vos accÃ¨s Ã  la formation thÃ©orique e-learning
        directement dans votre Espace Stagiaire.
      </p>
    """)

    sms_name = (trainee.get("first_name") or "").strip()
    sms = (
        f"IntÃ©grale Academy âœ… {sms_name + ', ' if sms_name else ''}"
        "Votre accÃ¨s e-learning Formation VTC est disponible. "
        f"Connectez vous Ã  votre Espace Stagiaire pour suivre votre formation : {access_link}"
    )

    email_ok = brevo_send_email((trainee.get("email") or "").strip(), subject, html, trainee=trainee)
    sms_ok = brevo_send_sms((trainee.get("phone") or "").strip(), sms)
    return {"email_ok": bool(email_ok), "sms_ok": bool(sms_ok)}




def build_vtc_practice_convocation_email(first_name: str, practice_training_date: str) -> Tuple[str, str]:
    trainee_first_name = (first_name or "").strip() or "PrÃ©nom"
    practice_date_fr = fr_date(practice_training_date) or "DATE FORMATION PRATIQUE"

    subject = "Formation pratique Chauffeur VTC ðŸš˜"
    html = mail_layout(f"""
      <div style="background:linear-gradient(135deg,#eff6ff,#f0fdf4);border:1px solid #dbeafe;border-radius:14px;padding:18px;">
        <h2 style="margin:0 0 12px 0;color:#0f172a;">Convocation formation pratique</h2>
        <p style="margin:0 0 10px 0;">Bonjour {trainee_first_name},</p>

        <p style="margin:0 0 10px 0;">Je reviens vers vous concernant votre parcours Chauffeur VTC.</p>

        <p style="margin:0 0 10px 0;">Tout dâ€™abord, fÃ©licitations pour votre rÃ©ussite Ã  lâ€™examen thÃ©orique ðŸ‘ Câ€™est une Ã©tape importante vers lâ€™obtention de votre carte professionnelle !</p>

        <p style="margin:0 0 10px 0;">Vous avez normalement reÃ§u un message de la Chambre de MÃ©tiers et de l'Artisanat vous demandant de prÃ©ciser le centre de formation ainsi que lâ€™Ã©tablissement mettant Ã  disposition le vÃ©hicule Ã  doubles commandes pour lâ€™Ã©preuve pratique. Merci dâ€™indiquer : IntÃ©grale SÃ©curitÃ© Formations.</p>

        <div style="background:#ffffff;border:1px solid #bbf7d0;border-radius:12px;padding:12px 14px;margin:12px 0;">
          <p style="margin:0;">Votre formation pratique est prÃ©vue le {practice_date_fr}, de 08h30 Ã  12h00, dans nos locaux :<br>
          IntÃ©grale Academy<br>
          54 chemin du Carreou<br>
          83480 PUGET-SUR-ARGENS</p>
        </div>

        <p style="margin:0 0 8px 0;">Au cours de cette matinÃ©e, nous vous prÃ©parerons concrÃ¨tement Ã  lâ€™examen pratique :</p>
        <ul style="margin:0 0 12px 18px;padding:0;">
          <li>dÃ©roulement dÃ©taillÃ© de lâ€™Ã©preuve,</li>
          <li>mise en situation professionnelle,</li>
          <li>examen blanc,</li>
          <li>prise en main du vÃ©hicule Ã  doubles commandes,</li>
          <li>conseils mÃ©thodologiques pour optimiser votre passage devant le jury.</li>
        </ul>

        <p style="margin:0 0 10px 0;">Vous trouverez en piÃ¨ce-jointe votre convocation Ã  la formation pratique, ainsi que le document officiel de prÃªt du vÃ©hicule Ã  doubles commandes.<br>
        âš ï¸ Il est impÃ©ratif de prÃ©senter ce document le jour de lâ€™examen : en son absence, le jury peut prononcer un ajournement.</p>

        <p style="margin:0 0 10px 0;">Nous restons Ã  votre disposition si vous avez la moindre question.<br>
        Ã€ trÃ¨s bientÃ´t pour la prÃ©paration finale ! ðŸš—</p>
      </div>
    """)
    return subject, html


def build_vtc_practice_convocation_sms(first_name: str, practice_training_date: str) -> str:
    trainee_first_name = (first_name or "").strip()
    practice_date_fr = fr_date(practice_training_date) or "DATE FORMATION PRATIQUE"
    greeting = f"Bonjour {trainee_first_name}, " if trainee_first_name else "Bonjour, "
    return (
        "IntÃ©grale Academy ðŸš— "
        f"{greeting}FÃ©licitations pour votre rÃ©ussite Ã  l'examen thÃ©orique Chauffeur VTC. "
        f"Votre formation pratique VTC est prÃ©vue le {practice_date_fr} de 08h30 Ã  12h00 "
        "dans nos locaux IntÃ©grale Academy, 54 chemin du Carreou 83480 Puget-sur-Argens. Pour plus d'informations, consultez vos mails."
    )


def build_vtc_practice_exam_success_email(first_name: str, practice_exam_date: str) -> Tuple[str, str]:
    first_name = (first_name or "").strip()
    greeting = f"Bonjour <strong>{first_name}</strong>," if first_name else "Bonjour,"
    practice_exam_date_fr = fr_date(practice_exam_date)
    subject = "FÃ©licitations ðŸŽ‰ RÃ©ussite Ã  l'examen pratique VTC"

    html = mail_layout(f"""
      <p style="margin:0 0 10px 0;">{greeting}</p>
      <p style="margin:0 0 10px 0;">FÃ©licitations pour votre rÃ©ussite Ã  l'examen pratique VTC ðŸ‘</p>
      <p style="margin:0 0 10px 0;">Votre examen pratique du <strong>{practice_exam_date_fr}</strong> est validÃ©.</p>
      <p style="margin:0;">Nous restons Ã  votre disposition pour la suite de vos dÃ©marches.</p>
    """)
    return subject, html


def build_vtc_practice_exam_success_sms(first_name: str, practice_exam_date: str) -> str:
    first_name = (first_name or "").strip()
    greeting = f"Bonjour {first_name}, " if first_name else "Bonjour, "
    practice_exam_date_fr = fr_date(practice_exam_date)
    return (
        f"{greeting}fÃ©licitations pour votre rÃ©ussite Ã  l'examen pratique VTC du {practice_exam_date_fr}. "
        "IntÃ©grale Academy reste disponible pour la suite de votre dossier."
    )


CMAR_MIN_IDENTIFIER_DIGITS = 3

def _normalize_cmar_identifier(value: str) -> str:
    raw = (value or "").strip().upper()
    if not raw:
        return ""
    return "".join(ch for ch in raw if ch.isalnum())


def _canonical_cmar_identifier(value: str) -> str:
    normalized = _normalize_cmar_identifier(value)
    if normalized.startswith("CMAR"):
        return normalized[4:]
    return normalized


def _cmar_identifier_match_keys(value: str) -> Set[str]:
    """
    Construit des clÃ©s de comparaison robustes pour un identifiant CMAR.
    Permet notamment de rapprocher "00000088" et "88".
    """
    canonical = _canonical_cmar_identifier(value)
    if not canonical:
        return set()

    keys = {canonical}
    digits = re.sub(r"\D", "", canonical)
    if digits:
        keys.add(digits)
        keys.add(digits.lstrip("0") or "0")
    return {k for k in keys if k}


def _extract_cmar_identifiers_from_pdf(file_bytes: bytes) -> List[str]:
    if not file_bytes:
        return []

    def _decode_pdf_text(raw: bytes) -> str:
        if not raw:
            return ""
        if raw.startswith(b"\xfe\xff"):
            try:
                return raw[2:].decode("utf-16-be", errors="ignore")
            except Exception:
                pass
        if raw.startswith(b"\xff\xfe"):
            try:
                return raw[2:].decode("utf-16-le", errors="ignore")
            except Exception:
                pass

        nul_even = sum(1 for i in range(0, len(raw), 2) if raw[i] == 0)
        nul_odd = sum(1 for i in range(1, len(raw), 2) if raw[i] == 0)
        pairs = max(1, len(raw) // 2)

        if nul_even / pairs > 0.30:
            try:
                return raw.decode("utf-16-be", errors="ignore")
            except Exception:
                pass
        if nul_odd / pairs > 0.30:
            try:
                return raw.decode("utf-16-le", errors="ignore")
            except Exception:
                pass

        return raw.decode("latin-1", errors="ignore")

    def _decode_pdf_literal_strings(blob: bytes) -> List[str]:
        out: List[str] = []
        i = 0
        n = len(blob)
        while i < n:
            if blob[i] != 0x28:  # (
                i += 1
                continue

            i += 1
            depth = 1
            buf = bytearray()
            while i < n and depth > 0:
                ch = blob[i]

                if ch == 0x5C:  # backslash
                    i += 1
                    if i >= n:
                        break
                    esc = blob[i]
                    simple = {
                        0x6E: 0x0A,  # \n
                        0x72: 0x0D,  # \r
                        0x74: 0x09,  # \t
                        0x62: 0x08,  # \b
                        0x66: 0x0C,  # \f
                        0x28: 0x28,  # \(
                        0x29: 0x29,  # \)
                        0x5C: 0x5C,  # \\
                    }
                    if esc in simple:
                        buf.append(simple[esc])
                        i += 1
                        continue

                    if 0x30 <= esc <= 0x37:
                        oct_digits = bytes([esc])
                        i += 1
                        for _ in range(2):
                            if i < n and 0x30 <= blob[i] <= 0x37:
                                oct_digits += bytes([blob[i]])
                                i += 1
                            else:
                                break
                        buf.append(int(oct_digits, 8) & 0xFF)
                        continue

                    buf.append(esc)
                    i += 1
                    continue

                if ch == 0x28:  # (
                    depth += 1
                    buf.append(ch)
                    i += 1
                    continue

                if ch == 0x29:  # )
                    depth -= 1
                    if depth > 0:
                        buf.append(ch)
                    i += 1
                    continue

                buf.append(ch)
                i += 1

            if buf:
                out.append(_decode_pdf_text(bytes(buf)))

        return out

    def _decode_pdf_hex_strings(blob: bytes) -> List[str]:
        out: List[str] = []
        for m in re.finditer(rb"<([0-9A-Fa-f\s]{4,})>", blob):
            raw = re.sub(rb"\s+", b"", m.group(1))
            if len(raw) % 2 == 1:
                raw += b"0"
            try:
                decoded = bytes.fromhex(raw.decode("ascii", errors="ignore"))
                out.append(_decode_pdf_text(decoded))
            except Exception:
                continue
        return out

    chunks: List[bytes] = [file_bytes]
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", file_bytes, flags=re.S):
        stream_data = m.group(1)
        chunks.append(stream_data)

        if b"/FlateDecode" in file_bytes[max(0, m.start() - 250):m.start()]:
            try:
                inflated = zlib.decompress(stream_data)
                chunks.append(inflated)
            except Exception:
                pass

    text_sources: List[str] = []
    for chunk in chunks:
        text_sources.append(_decode_pdf_text(chunk))
        text_sources.extend(_decode_pdf_literal_strings(chunk))
        text_sources.extend(_decode_pdf_hex_strings(chunk))

    content = "\n".join(text_sources).upper()
    candidates = set()

    for token in re.findall(r"\b(?:CMAR\s*[:\-]?)?([A-Z0-9\-]{4,})\b", content):
        normalized = _normalize_cmar_identifier(token)
        if not normalized:
            continue
        if normalized.startswith("CMAR"):
            normalized = normalized[4:]
        if normalized.isdigit() and len(normalized) < CMAR_MIN_IDENTIFIER_DIGITS:
            continue
        if normalized.isdigit() and len(normalized) > 20:
            continue
        if any(ch.isdigit() for ch in normalized) and len(normalized) >= CMAR_MIN_IDENTIFIER_DIGITS:
            candidates.add(normalized)

    # fallback : capture les suites numÃ©riques mÃªme si le PDF met des sÃ©parateurs/NULL
    compact_digits = re.sub(r"[^0-9]", " ", content)
    for token in compact_digits.split():
        if CMAR_MIN_IDENTIFIER_DIGITS <= len(token) <= 20:
            candidates.add(token)

    return sorted(candidates)


def _build_pdf_search_haystacks(file_bytes: bytes) -> Tuple[str, str]:
    """
    Retourne 2 haystacks tokenisÃ©s (avec sÃ©parateurs espaces):
    - alnum_only: tokens A-Z0-9 sÃ©parÃ©s par espaces
    - digits_only: tokens 0-9 sÃ©parÃ©s par espaces
    Permet un matching robuste sans faux positifs par concatÃ©nation.
    """
    if not file_bytes:
        return "", ""

    chunks: List[bytes] = [file_bytes]
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", file_bytes, flags=re.S):
        stream_data = m.group(1)
        chunks.append(stream_data)
        if b"/FlateDecode" in file_bytes[max(0, m.start() - 250):m.start()]:
            try:
                chunks.append(zlib.decompress(stream_data))
            except Exception:
                pass

    merged = "\n".join(chunk.decode("latin-1", errors="ignore") for chunk in chunks).upper()
    alnum_only = " " + " ".join(t for t in re.split(r"[^A-Z0-9]+", merged) if t) + " "
    digits_only = " " + " ".join(t for t in re.split(r"[^0-9]+", merged) if t) + " "
    return alnum_only, digits_only


def _send_vtc_theory_exam_notification(session_obj: Dict[str, Any], trainee: Dict[str, Any], send_notifications: bool = True) -> Dict[str, Any]:
    if _trainee_registration_is_cancelled(trainee):
        raise RuntimeError(AUTOMATION_DISABLED_REGISTRATION_CANCELLED_MESSAGE)
    practice_training_date = (
        _session_get(session_obj, "practice_training_date", "")
        or _session_get(session_obj, "exam_practice_date", "")
        or _session_get(session_obj, "exam_date", "")
    )


def _normalize_cmar_identifier(value: str) -> str:
    raw = (value or "").strip().upper()
    if not raw:
        return ""
    return "".join(ch for ch in raw if ch.isalnum())


def _extract_cmar_identifiers_from_pdf(file_bytes: bytes) -> List[str]:
    if not file_bytes:
        return []

    def _decode_pdf_text(raw: bytes) -> str:
        if not raw:
            return ""
        if raw.startswith(b"\xfe\xff"):
            try:
                return raw[2:].decode("utf-16-be", errors="ignore")
            except Exception:
                pass
        if raw.startswith(b"\xff\xfe"):
            try:
                return raw[2:].decode("utf-16-le", errors="ignore")
            except Exception:
                pass

        nul_even = sum(1 for i in range(0, len(raw), 2) if raw[i] == 0)
        nul_odd = sum(1 for i in range(1, len(raw), 2) if raw[i] == 0)
        pairs = max(1, len(raw) // 2)

        if nul_even / pairs > 0.30:
            try:
                return raw.decode("utf-16-be", errors="ignore")
            except Exception:
                pass
        if nul_odd / pairs > 0.30:
            try:
                return raw.decode("utf-16-le", errors="ignore")
            except Exception:
                pass

        return raw.decode("latin-1", errors="ignore")

    def _decode_pdf_literal_strings(blob: bytes) -> List[str]:
        out: List[str] = []
        i = 0
        n = len(blob)
        while i < n:
            if blob[i] != 0x28:  # (
                i += 1
                continue

            i += 1
            depth = 1
            buf = bytearray()
            while i < n and depth > 0:
                ch = blob[i]

                if ch == 0x5C:  # backslash
                    i += 1
                    if i >= n:
                        break
                    esc = blob[i]
                    simple = {
                        0x6E: 0x0A,  # \n
                        0x72: 0x0D,  # \r
                        0x74: 0x09,  # \t
                        0x62: 0x08,  # \b
                        0x66: 0x0C,  # \f
                        0x28: 0x28,  # \(
                        0x29: 0x29,  # \)
                        0x5C: 0x5C,  # \\
                    }
                    if esc in simple:
                        buf.append(simple[esc])
                        i += 1
                        continue

                    if 0x30 <= esc <= 0x37:
                        oct_digits = bytes([esc])
                        i += 1
                        for _ in range(2):
                            if i < n and 0x30 <= blob[i] <= 0x37:
                                oct_digits += bytes([blob[i]])
                                i += 1
                            else:
                                break
                        buf.append(int(oct_digits, 8) & 0xFF)
                        continue

                    buf.append(esc)
                    i += 1
                    continue

                if ch == 0x28:  # (
                    depth += 1
                    buf.append(ch)
                    i += 1
                    continue

                if ch == 0x29:  # )
                    depth -= 1
                    if depth > 0:
                        buf.append(ch)
                    i += 1
                    continue

                buf.append(ch)
                i += 1

            if buf:
                out.append(_decode_pdf_text(bytes(buf)))

        return out

    def _decode_pdf_hex_strings(blob: bytes) -> List[str]:
        out: List[str] = []
        for m in re.finditer(rb"<([0-9A-Fa-f\s]{4,})>", blob):
            raw = re.sub(rb"\s+", b"", m.group(1))
            if len(raw) % 2 == 1:
                raw += b"0"
            try:
                decoded = bytes.fromhex(raw.decode("ascii", errors="ignore"))
                out.append(_decode_pdf_text(decoded))
            except Exception:
                continue
        return out

    chunks: List[bytes] = [file_bytes]
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", file_bytes, flags=re.S):
        stream_data = m.group(1)
        chunks.append(stream_data)

        if b"/FlateDecode" in file_bytes[max(0, m.start() - 250):m.start()]:
            try:
                inflated = zlib.decompress(stream_data)
                chunks.append(inflated)
            except Exception:
                pass

    text_sources: List[str] = []
    for chunk in chunks:
        text_sources.append(_decode_pdf_text(chunk))
        text_sources.extend(_decode_pdf_literal_strings(chunk))
        text_sources.extend(_decode_pdf_hex_strings(chunk))

    content = "\n".join(text_sources).upper()
    candidates = set()

    for token in re.findall(r"\b(?:CMAR\s*[:\-]?)?([A-Z0-9\-]{4,})\b", content):
        normalized = _normalize_cmar_identifier(token)
        if not normalized:
            continue
        if normalized.startswith("CMAR"):
            normalized = normalized[4:]
        if normalized.isdigit() and len(normalized) < CMAR_MIN_IDENTIFIER_DIGITS:
            continue
        if normalized.isdigit() and len(normalized) > 20:
            continue
        if any(ch.isdigit() for ch in normalized) and len(normalized) >= CMAR_MIN_IDENTIFIER_DIGITS:
            candidates.add(normalized)

    # fallback : capture les suites numÃ©riques mÃªme si le PDF met des sÃ©parateurs/NULL
    compact_digits = re.sub(r"[^0-9]", " ", content)
    for token in compact_digits.split():
        if CMAR_MIN_IDENTIFIER_DIGITS <= len(token) <= 20:
            candidates.add(token)

    return sorted(candidates)


def _build_pdf_search_haystacks(file_bytes: bytes) -> Tuple[str, str]:
    """
    Retourne 2 haystacks tokenisÃ©s (avec sÃ©parateurs espaces):
    - alnum_only: tokens A-Z0-9 sÃ©parÃ©s par espaces
    - digits_only: tokens 0-9 sÃ©parÃ©s par espaces
    Permet un matching robuste sans faux positifs par concatÃ©nation.
    """
    if not file_bytes:
        return "", ""

    chunks: List[bytes] = [file_bytes]
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", file_bytes, flags=re.S):
        stream_data = m.group(1)
        chunks.append(stream_data)
        if b"/FlateDecode" in file_bytes[max(0, m.start() - 250):m.start()]:
            try:
                chunks.append(zlib.decompress(stream_data))
            except Exception:
                pass

    merged = "\n".join(chunk.decode("latin-1", errors="ignore") for chunk in chunks).upper()
    alnum_only = " " + " ".join(t for t in re.split(r"[^A-Z0-9]+", merged) if t) + " "
    digits_only = " " + " ".join(t for t in re.split(r"[^0-9]+", merged) if t) + " "
    return alnum_only, digits_only




def _build_excel_search_haystacks(file_name: str, file_bytes: bytes) -> Tuple[str, str]:
    """
    Retourne 2 haystacks tokenisÃ©s pour CSV/XLSX:
    - alnum_only: tokens A-Z0-9 sÃ©parÃ©s par espaces
    - digits_only: tokens 0-9 sÃ©parÃ©s par espaces
    """
    name = (file_name or "").lower().strip()
    if not file_bytes:
        return "", ""

    texts: List[str] = []

    if name.endswith(".csv"):
        texts.append(file_bytes.decode("utf-8", errors="ignore"))
    elif name.endswith(".xlsx"):
        try:
            with zipfile.ZipFile(BytesIO(file_bytes), "r") as zf:
                shared_strings: List[str] = []
                if "xl/sharedStrings.xml" in zf.namelist():
                    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                    for si in root.findall("{*}si"):
                        parts = [t.text or "" for t in si.findall(".//{*}t")]
                        shared_strings.append("".join(parts))

                sheet_files = [n for n in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n)]
                for sheet in sheet_files:
                    root = ET.fromstring(zf.read(sheet))
                    for c in root.findall(".//{*}c"):
                        cell_type = c.attrib.get("t") or ""

                        if cell_type == "inlineStr":
                            inline_parts = [t.text or "" for t in c.findall(".//{*}is//{*}t")]
                            inline_raw = "".join(inline_parts).strip()
                            if inline_raw:
                                texts.append(inline_raw)
                            continue

                        v = c.find("{*}v")
                        if v is None or v.text is None:
                            continue
                        raw = v.text.strip()
                        if not raw:
                            continue
                        if cell_type == "s":
                            try:
                                idx = int(raw)
                                if 0 <= idx < len(shared_strings):
                                    texts.append(shared_strings[idx])
                            except Exception:
                                continue
                        else:
                            texts.append(raw)
        except Exception:
            return "", ""

    merged = "\n".join(texts).upper()
    alnum_only = " " + " ".join(t for t in re.split(r"[^A-Z0-9]+", merged) if t) + " "
    digits_only = " " + " ".join(t for t in re.split(r"[^0-9]+", merged) if t) + " "
    return alnum_only, digits_only


def _extract_cmar_identifiers_from_excel(file_name: str, file_bytes: bytes) -> List[str]:
    name = (file_name or "").lower().strip()
    if not file_bytes:
        return []

    def _ids_from_text(raw_text: str) -> List[str]:
        out = set()
        txt = (raw_text or "").upper()
        for token in re.findall(r"\b(?:CMAR\s*[:\-]?)?([A-Z0-9\-]{4,})\b", txt):
            normalized = _normalize_cmar_identifier(token)
            if normalized.startswith("CMAR"):
                normalized = normalized[4:]
            if any(ch.isdigit() for ch in normalized) and len(normalized) >= CMAR_MIN_IDENTIFIER_DIGITS:
                out.add(normalized)
        digits = re.sub(r"[^0-9]", " ", txt)
        for token in digits.split():
            if CMAR_MIN_IDENTIFIER_DIGITS <= len(token) <= 20:
                out.add(token)
        return sorted(out)

    if name.endswith(".csv"):
        csv_text = file_bytes.decode("utf-8", errors="ignore")
        return _ids_from_text(csv_text)

    if not name.endswith(".xlsx"):
        return []

    texts: List[str] = []
    try:
        with zipfile.ZipFile(BytesIO(file_bytes), "r") as zf:
            shared_strings: List[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in root.findall("{*}si"):
                    parts = [t.text or "" for t in si.findall(".//{*}t")]
                    shared_strings.append("".join(parts))

            sheet_files = [n for n in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n)]
            for sheet in sheet_files:
                root = ET.fromstring(zf.read(sheet))
                for c in root.findall(".//{*}c"):
                    cell_type = c.attrib.get("t") or ""

                    if cell_type == "inlineStr":
                        inline_parts = [t.text or "" for t in c.findall(".//{*}is//{*}t")]
                        inline_raw = "".join(inline_parts).strip()
                        if inline_raw:
                            texts.append(inline_raw)
                        continue

                    v = c.find("{*}v")
                    if v is None or v.text is None:
                        continue
                    raw = v.text.strip()
                    if not raw:
                        continue
                    if cell_type == "s":
                        try:
                            idx = int(raw)
                            if 0 <= idx < len(shared_strings):
                                texts.append(shared_strings[idx])
                        except Exception:
                            continue
                    else:
                        texts.append(raw)
    except Exception:
        return []

    return _ids_from_text("\n".join(texts))


def _extract_vtc_exam_results(file_name: str, file_bytes: bytes) -> Dict[str, Any]:
    name = (file_name or "").lower().strip()
    ids = _extract_cmar_identifiers_from_pdf(file_bytes) if name.endswith(".pdf") else _extract_cmar_identifiers_from_excel(file_name, file_bytes)
    admissible_ids = set()
    non_admissible_ids = set()

    def _status_from_text(text: str) -> str:
        txt = (text or "").upper()
        if "NON ADMIS" in txt:
            return "non_admissible"
        if "ADMIS" in txt:
            return "admissible"
        if "NON ADMISSIBLE" in txt:
            return "non_admissible"
        if "ADMISSIBLE" in txt:
            return "admissible"
        return ""

    row_texts: List[str] = []

    if name.endswith(".csv"):
        csv_text = file_bytes.decode("utf-8", errors="ignore")
        row_texts = [line for line in csv_text.splitlines() if line.strip()]
    elif name.endswith(".xlsx"):
        try:
            with zipfile.ZipFile(BytesIO(file_bytes), "r") as zf:
                shared_strings: List[str] = []
                if "xl/sharedStrings.xml" in zf.namelist():
                    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                    for si in root.findall("{*}si"):
                        parts = [t.text or "" for t in si.findall(".//{*}t")]
                        shared_strings.append("".join(parts))

                sheet_files = [n for n in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n)]
                for sheet in sheet_files:
                    root = ET.fromstring(zf.read(sheet))
                    for row in root.findall(".//{*}row"):
                        row_values = []
                        for c in row.findall("{*}c"):
                            cell_type = c.attrib.get("t") or ""

                            if cell_type == "inlineStr":
                                inline_parts = [t.text or "" for t in c.findall(".//{*}is//{*}t")]
                                inline_raw = "".join(inline_parts).strip()
                                if inline_raw:
                                    row_values.append(inline_raw)
                                continue

                            v = c.find("{*}v")
                            if v is None or v.text is None:
                                continue
                            raw = v.text.strip()
                            if not raw:
                                continue
                            if cell_type == "s":
                                try:
                                    idx = int(raw)
                                    if 0 <= idx < len(shared_strings):
                                        row_values.append(shared_strings[idx])
                                except Exception:
                                    continue
                            else:
                                row_values.append(raw)
                        if row_values:
                            row_texts.append(" ".join(row_values))
        except Exception:
            row_texts = []
    elif name.endswith(".pdf"):
        content = file_bytes.decode("latin-1", errors="ignore")
        row_texts = [line for line in content.splitlines() if line.strip()]

    for line in row_texts:
        status = _status_from_text(line)
        if not status:
            continue
        tokens = re.findall(r"\b(?:CMAR\s*[:\-]?)?([A-Z0-9\-]{4,})\b", line.upper())
        for token in tokens:
            normalized = _normalize_cmar_identifier(token)
            if normalized.startswith("CMAR"):
                normalized = normalized[4:]
            if not normalized:
                continue
            if status == "non_admissible":
                non_admissible_ids.add(normalized)
                admissible_ids.discard(normalized)
            elif normalized not in non_admissible_ids:
                admissible_ids.add(normalized)

    return {
        "all_ids": sorted(set(ids)),
        "admissible_ids": sorted(admissible_ids),
        "non_admissible_ids": sorted(non_admissible_ids),
    }


def _send_vtc_theory_exam_notification(session_obj: Dict[str, Any], trainee: Dict[str, Any], send_notifications: bool = True) -> Dict[str, Any]:
    if _trainee_registration_is_cancelled(trainee):
        raise RuntimeError(AUTOMATION_DISABLED_REGISTRATION_CANCELLED_MESSAGE)
    practice_training_date = (
        _session_get(session_obj, "practice_training_date", "")
        or _session_get(session_obj, "exam_practice_date", "")
        or _session_get(session_obj, "exam_date", "")
    )

    first_name = (trainee.get("first_name") or "").strip()
    email = (trainee.get("email") or "").strip()
    phone = (trainee.get("phone") or "").strip()

    subject, html = build_vtc_practice_convocation_email(first_name, practice_training_date)
    sms = build_vtc_practice_convocation_sms(first_name, practice_training_date)

    docx_path, pdf_path = _generate_aps_convocation_files(
        session_obj, trainee, str(session_obj.get("id") or ""), str(trainee.get("id") or "")
    )
    with open(pdf_path, "rb") as fh:
        attachment = {"name": os.path.basename(pdf_path), "content": base64.b64encode(fh.read()).decode("ascii")}
    email_ok = brevo_send_email(email, subject, html, trainee=trainee, attachments=[attachment]) if (send_notifications and email) else False
    sms_ok = brevo_send_sms(phone, sms) if (send_notifications and phone) else False

    trainee["vtc_theory_exam_sent_at"] = _now_iso()
    trainee["vtc_theory_exam_email_ok"] = bool(email_ok)
    trainee["vtc_theory_exam_sms_ok"] = bool(sms_ok)
    trainee["convocation_aps_status"] = "sent" if email_ok else "generated"
    trainee["convocation_aps_generated_at"] = trainee["vtc_theory_exam_sent_at"]
    trainee["convocation_aps_sent_at"] = trainee["vtc_theory_exam_sent_at"] if email_ok else ""
    trainee["convocation_aps_pdf_path"] = pdf_path
    trainee["convocation_aps_docx_path"] = docx_path
    trainee["convocation_aps_pdf_token"] = _store_public_file_token(pdf_path)
    trainee["convocation_aps_last_error"] = ""
    trainee["updated_at"] = _now_iso()

    return {
        "email_ok": bool(email_ok),
        "sms_ok": bool(sms_ok),
        "sent_at": trainee.get("vtc_theory_exam_sent_at") or "",
    }


def _send_vtc_practice_exam_success_notification(session_obj: Dict[str, Any], trainee: Dict[str, Any]) -> Dict[str, Any]:
    if _trainee_registration_is_cancelled(trainee):
        raise RuntimeError(AUTOMATION_DISABLED_REGISTRATION_CANCELLED_MESSAGE)
    practice_exam_date = (
        _session_get(session_obj, "exam_practice_date", "")
        or _session_get(session_obj, "exam_date", "")
    )

    first_name = (trainee.get("first_name") or "").strip()
    email = (trainee.get("email") or "").strip()
    phone = (trainee.get("phone") or "").strip()

    subject, html = build_vtc_practice_exam_success_email(first_name, practice_exam_date)
    sms = build_vtc_practice_exam_success_sms(first_name, practice_exam_date)

    email_ok = brevo_send_email(email, subject, html, trainee=trainee) if email else False
    sms_ok = brevo_send_sms(phone, sms) if phone else False

    trainee["vtc_practice_result"] = "success"
    trainee["vtc_practice_result_label"] = "rÃ©ussite examen pratique"
    trainee["vtc_practice_exam_sent_at"] = _now_iso()
    trainee["vtc_practice_exam_email_ok"] = bool(email_ok)
    trainee["vtc_practice_exam_sms_ok"] = bool(sms_ok)
    trainee["updated_at"] = _now_iso()

    return {
        "email_ok": bool(email_ok),
        "sms_ok": bool(sms_ok),
        "sent_at": trainee.get("vtc_practice_exam_sent_at") or "",
    }


def mail_layout(inner_html: str, show_default_logo: bool = True, footer_text: str = "IntÃ©grale Academy") -> str:
    # âœ… logo en URL HTTPS (fiable dans Gmail)
    logo_src = f"{PUBLIC_BASE_URL.rstrip('/')}/static/logo-integrale.png"
    logo_html = ""
    if show_default_logo:
        logo_html = f"""
        <div style="text-align:center;margin-bottom:18px">
          <img src="{logo_src}" alt="IntÃ©grale Academy"
               style="height:60px;width:auto;display:block;margin:0 auto;border:0;outline:none;text-decoration:none">
        </div>
        """
    footer_html = ""
    if footer_text:
        footer_html = f"""
        <p style="margin-top:30px;color:#666;font-size:13px;text-align:center">
          {html.escape(footer_text)}
        </p>
        """

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;background:#f7f7f7;padding:18px;border-radius:12px">
      <div style="background:white;padding:18px;border-radius:12px">
        {logo_html}

        {inner_html}

        {footer_html}
      </div>
    </div>
    """


VAE_ADMIN_NOTIFICATION_EMAIL = os.environ.get("VAE_ADMIN_NOTIFICATION_EMAIL", "cassandre@integraleacademy.com").strip()


def _vae_admin_notification_name(trainee: Optional[Dict[str, Any]] = None, dossier: Optional[Dict[str, Any]] = None) -> str:
    trainee = trainee if isinstance(trainee, dict) else {}
    dossier = dossier if isinstance(dossier, dict) else {}
    candidat = dossier.get("candidat") if isinstance(dossier.get("candidat"), dict) else {}

    trainee_name = _format_trainee_name(trainee.get("first_name", ""), trainee.get("last_name", "")) if trainee else ""
    if trainee_name:
        return trainee_name

    dossier_name = " ".join(
        part.strip()
        for part in [
            str(candidat.get("prenoms") or ""),
            str(candidat.get("nom_usage") or candidat.get("nom_naissance") or ""),
        ]
        if str(part or "").strip()
    ).strip()
    return dossier_name


def _send_vae_admin_notification(
    action: str,
    *,
    trainee: Optional[Dict[str, Any]] = None,
    dossier: Optional[Dict[str, Any]] = None,
    session_obj: Optional[Dict[str, Any]] = None,
    details: Optional[Dict[str, Any]] = None,
) -> bool:
    """Envoie un email interne Ã  Cassandre pour les Ã©vÃ©nements importants VAE."""
    if not VAE_ADMIN_NOTIFICATION_EMAIL:
        return False

    trainee = trainee if isinstance(trainee, dict) else {}
    dossier = dossier if isinstance(dossier, dict) else {}
    session_obj = session_obj if isinstance(session_obj, dict) else {}
    details = details if isinstance(details, dict) else {}
    candidat = dossier.get("candidat") if isinstance(dossier.get("candidat"), dict) else {}
    meta = dossier.get("meta") if isinstance(dossier.get("meta"), dict) else {}

    candidate_name = _vae_admin_notification_name(trainee, dossier) or "Candidat non renseignÃ©"
    candidate_email = (trainee.get("email") or candidat.get("email") or "").strip()
    candidate_phone = (trainee.get("phone") or candidat.get("telephone") or "").strip()
    subject = f"Notification VAE â€“ {action}"

    rows = [
        ("Action", action),
        ("Candidat", candidate_name),
        ("Email candidat", candidate_email),
        ("TÃ©lÃ©phone candidat", candidate_phone),
        ("Session", session_obj.get("name") or session_obj.get("session_name") or details.get("session_name") or ""),
        ("ID session", session_obj.get("id") or meta.get("session_id") or details.get("session_id") or ""),
        ("ID stagiaire", trainee.get("id") or meta.get("trainee_id") or details.get("trainee_id") or ""),
        ("ID dossier VAE", dossier.get("id") or details.get("dossier_id") or ""),
        ("Statut dossier", dossier.get("statut_dossier") or details.get("statut_dossier") or ""),
    ]
    for key, value in details.items():
        if key in {"session_name", "session_id", "trainee_id", "dossier_id", "statut_dossier"}:
            continue
        label = str(key).replace("_", " ").strip().capitalize()
        rows.append((label, value))

    rendered_rows = "".join(
        f"<tr><th style='text-align:left;padding:8px;border-bottom:1px solid #e5e7eb;width:180px'>{html.escape(str(label))}</th>"
        f"<td style='padding:8px;border-bottom:1px solid #e5e7eb'>{html.escape(str(value or 'â€”'))}</td></tr>"
        for label, value in rows
    )
    html_body = mail_layout(f"""
      <h2 style="margin:0 0 12px 0;color:#0f172a;text-align:center;">ðŸ”” Notification VAE</h2>
      <p>Une action concernant la VAE vient d'Ãªtre effectuÃ©e.</p>
      <table style="border-collapse:collapse;width:100%;background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden">
        {rendered_rows}
      </table>
    """)
    return brevo_send_email(VAE_ADMIN_NOTIFICATION_EMAIL, subject, html_body)


def build_vtc_onboarding_email(first_name: str, form_link: str) -> Tuple[str, str]:
    first_name = (first_name or "").strip()
    greeting = f"Bonjour <strong>{first_name}</strong>," if first_name else "Bonjour,"
    subject = "Votre inscription Chauffeur VTC â€“ IntÃ©grale Academy"

    html = mail_layout(f"""
      <p>{greeting}</p>
      <p>
        Je fais suite Ã  votre inscription en formation <strong>Chauffeur VTC</strong>.
      </p>
      <p>Je vous remercie pour votre confiance !</p>
      <p>
        Vous pouvez Ã  prÃ©sent accÃ©der Ã  votre Espace Stagiaire en cliquant ici :
      </p>
      <p style="text-align:center;margin:18px 0;">
        <a href="{form_link}"
           style="display:inline-block;background:#1f8f4a;color:white;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:bold">
          ðŸ‘‰ AccÃ©der Ã  mon Espace Stagiaire
        </a>
      </p>

      <p>Dans votre Espace Stagiaire vous allez retrouver :</p>

      <p>
        1ï¸âƒ£ Les indications pour crÃ©er votre compte Chambre des mÃ©tiers (exament3p) :
        ce compte vous permettra de dÃ©poser vos documents officiels nÃ©cessaires pour
        l'inscription Ã  l'examen thÃ©orique et l'examen pratique
      </p>
      <p>
        2ï¸âƒ£ DÃ¨s que votre compte Chambre des mÃ©tiers sera crÃ©Ã©, vous devrez nous indiquer,
        dans votre Espace Stagiaire, votre identifiant et votre mot de passe Chambre des mÃ©tiers,
        afin que nous puissions nous connecter et procÃ©der au paiement des frais d'examen
        (âš ï¸ Veillez Ã  ne pas rÃ©gler les frais d'inscriptions, ils sont inclus dans votre formation)
      </p>
      <p>
        3ï¸âƒ£ Les accÃ¨s Ã  votre formation thÃ©orique en e-learning
      </p>

      <p>
        Nous restons Ã  votre disposition pour tout renseignement complÃ©mentaire.<br>
        Excellente journÃ©e Ã  vous.
      </p>

      <p style="margin-top:18px;">
        Bien cordialement,<br>
        <strong>ClÃ©ment VAILLANT</strong><br>
        Directeur GÃ©nÃ©ral â€“ IntÃ©grale SÃ©curitÃ© Formations<br>
        04 22 47 07 68<br>
        <a href="https://www.integraleacademy.com" target="_blank" rel="noopener">www.integraleacademy.com</a>
      </p>
    """)
    return subject, html


def build_vtc_onboarding_sms(first_name: str, form_link: str) -> str:
    first_name = (first_name or "").strip()
    greeting = f"Bonjour {first_name}, " if first_name else "Bonjour, "
    return (
        "IntÃ©grale Academy ðŸš– "
        f"{greeting}"
        "votre inscription en formation Chauffeur VTC est confirmÃ©e. "
        f"AccÃ©dez Ã  votre Espace Stagiaire : {form_link} "
        "Vous y retrouverez les Ã©tapes Chambre des mÃ©tiers et vos accÃ¨s e-learning. "
        "Besoin d'aide ? 04 22 47 07 68."
    )


def build_dirigeant_vae_onboarding_email_sms(first_name: str, link: str) -> Tuple[str, str, str]:
    first_name = (first_name or "").strip()
    subject = "Votre VAE Dirigeant d'entreprise de sÃ©curitÃ© privÃ©e (DESP)"
    html = mail_layout(f"""
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse;color:#0f172a;font-size:16px;line-height:1.6;">
        <tr>
          <td style="text-align:center;font-size:26px;font-weight:700;padding:0 0 16px 0;">ðŸš€ En route vers la VAE</td>
        </tr>
        <tr>
          <td style="padding:0 0 12px 0;">Bonjour {first_name},</td>
        </tr>
        <tr>
          <td style="padding:0 0 12px 0;">
            Votre VAE (Validation des acquis de l'expÃ©rience) Dirigeant d'entreprise de sÃ©curitÃ© privÃ©e (DESP)
            commence aujourd'hui.
          </td>
        </tr>
        <tr>
          <td style="padding:0 0 12px 0;"><strong>Les Ã©tapes :</strong></td>
        </tr>

        <tr><td style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px;"><strong>1ï¸âƒ£ RÃ©daction du Livret 1 (dossier de faisabilitÃ©)</strong><br>Vous allez complÃ©ter en ligne votre dossier de faisabilitÃ© depuis votre Espace candidat.<br>Ce document permet de prÃ©senter votre parcours professionnel, vos fonctions exercÃ©es et vos responsabilitÃ©s, afin de vÃ©rifier que votre expÃ©rience correspond bien aux compÃ©tences attendues pour le DESP. Câ€™est en quelque sorte la Â« photographie Â» de votre expÃ©rience.<br>â³ DurÃ©e estimÃ©e : environ 30 minutes.</td></tr>
        <tr><td style="height:10px;font-size:0;line-height:0;">&nbsp;</td></tr>
        <tr><td style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px;"><strong>2ï¸âƒ£ Ã‰tude du Livret 1 et attestation de recevabilitÃ©</strong><br>Votre dossier est Ã©tudiÃ© par la commission.<br>Si les Ã©lÃ©ments fournis sont conformes et suffisants, une attestation de recevabilitÃ© vous est dÃ©livrÃ©e.<br>Ã€ partir de ce moment, nous prendrons contact avec vous pour mettre en place la convention de VAE et procÃ©der au rÃ¨glement de lâ€™acompte (1 140 â‚¬).</td></tr>
        <tr><td style="height:10px;font-size:0;line-height:0;">&nbsp;</td></tr>
        <tr><td style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px;"><strong>3ï¸âƒ£ RÃ©daction du Livret 2</strong><br>Vous devrez ensuite complÃ©ter le Livret 2.<br>Ce document est le cÅ“ur de votre dÃ©marche : vous y dÃ©taillez prÃ©cisÃ©ment vos activitÃ©s, vos missions, les situations professionnelles rencontrÃ©es, ainsi que les compÃ©tences mobilisÃ©es.<br>Câ€™est ce dossier qui sera prÃ©sentÃ© au jury de certification.</td></tr>
        <tr><td style="height:10px;font-size:0;line-height:0;">&nbsp;</td></tr>
        <tr><td style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px;"><strong>4ï¸âƒ£ Ã‰tude du Livret 2</strong><br>La commission analyse votre dossier.<br>Si lâ€™ensemble est conforme et complet, une date de passage devant le jury de certification est programmÃ©e.</td></tr>
        <tr><td style="height:10px;font-size:0;line-height:0;">&nbsp;</td></tr>
        <tr><td style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px;"><strong>5ï¸âƒ£ Passage devant le jury de certification</strong><br>Vous serez convoquÃ© Ã  un entretien professionnel dâ€™environ une heure.<br>Lors de cet Ã©change, le jury reviendra sur votre parcours et sur les Ã©lÃ©ments prÃ©sentÃ©s dans le Livret 2.<br>Lâ€™objectif est de vÃ©rifier la maÃ®trise des compÃ©tences attendues, Ã  travers des questions concrÃ¨tes sur votre expÃ©rience et vos pratiques professionnelles.</td></tr>
        <tr><td style="height:10px;font-size:0;line-height:0;">&nbsp;</td></tr>
        <tr><td style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:14px;"><strong>6ï¸âƒ£ Obtention de votre certification</strong></td></tr>

        <tr>
          <td style="text-align:center;padding:22px 0;">
            <a href="{link}" style="display:inline-block;background:#1f8f4a;color:#ffffff;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:700;">DÃ©marrer ma VAE</a>
          </td>
        </tr>
        <tr>
          <td>
            Je reste Ã  votre disposition pour tous renseignements complÃ©mentaires,<br>
            <strong>ClÃ©ment VAILLANT</strong><br>
            Directeur IntÃ©grale Academy
          </td>
        </tr>
      </table>
    """)

    sms = (
        f"IntÃ©grale Academy Bonjour {first_name}, votre VAE Dirigeant d'entreprise de sÃ©curitÃ© (DESP) commence aujourd'hui ðŸš€. "
        f"Pour dÃ©marrer votre VAE cliquez ici : {link} "
        "Je reste Ã  votre disposition. ClÃ©ment VAILLANT - IntÃ©grale Academy"
    )
    return subject, html, sms


def _parse_iso_datetime(value: str) -> Optional[datetime.datetime]:
    raw = (value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(normalized)
    except Exception:
        return None


def build_vtc_credentials_reminder_email(first_name: str, form_link: str) -> Tuple[str, str]:
    first_name = (first_name or "").strip()
    greeting = f"Bonjour <strong>{first_name}</strong>," if first_name else "Bonjour,"
    subject = "Relance â€“ Identifiants Chambre des mÃ©tiers manquants"

    html = mail_layout(f"""
      <h2 style="text-align:center;color:#b91c1c">â° Relance â€“ Formation Chauffeur VTC</h2>
      <p>{greeting}</p>
      <p>
        Je me permets de revenir vers vous concernant votre formation <strong>Chauffeur VTC</strong>.
      </p>
      <p>
        Ã€ ce jour, nous n'avons toujours pas reÃ§u vos identifiants Chambre des mÃ©tiers
        (<strong>exament3p</strong>) afin que nous puissions procÃ©der au paiement de vos frais d'examen.
      </p>
      <p>
        Nous vous rappelons que vous devez nous faire parvenir vos identifiants via votre
        <strong>Espace Stagiaire</strong> (les envois par mail et tout autre moyen de communication
        ne sont pas pris en compte).
      </p>
      <p style="text-align:center;margin:18px 0;">
        <a href="{form_link}"
           style="display:inline-block;background:#1f8f4a;color:white;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:bold">
          ðŸ‘‰ AccÃ©der Ã  mon Espace Stagiaire
        </a>
      </p>

      <p>
        Je vous remercie par avance.
      </p>

      <p style="margin-top:18px;">
        Bien cordialement,<br>
        <strong>ClÃ©ment VAILLANT</strong><br>
        Directeur IntÃ©grale Academy
      </p>
    """)
    return subject, html


def build_vtc_credentials_reminder_sms(first_name: str, form_link: str) -> str:
    first_name = (first_name or "").strip()
    greeting = f"Bonjour {first_name}, " if first_name else "Bonjour, "
    return (
        "IntÃ©grale Academy â° "
        f"{greeting}nous n'avons pas reÃ§u vos identifiants Chambre des mÃ©tiers (exament3p). "
        "Merci de les transmettre uniquement via votre Espace Stagiaire : "
        f"{form_link}"
    )


def build_vtc_credentials_invalid_email(first_name: str, form_link: str) -> Tuple[str, str]:
    first_name = (first_name or "").strip()
    greeting = f"Bonjour <strong>{first_name}</strong>," if first_name else "Bonjour,"
    subject = "Connexion ExamenT3P impossible"

    html = mail_layout(f"""
      <h2 style="text-align:center;color:#1d4ed8">Connexion ExamenT3P impossible</h2>
      <p>{greeting}</p>
      <p>
        Je me permets de revenir vers vous concernant votre formation Chauffeur VTC. Nous ne pouvons pas nous connecter Ã  votre compte
        <strong>ExamenT3P (Chambre des mÃ©tiers)</strong>.
      </p>
      <p>
        Cela peut Ãªtre dÃ» Ã  l'une des deux raisons suivantes :
      </p>
      <ul style="margin:0 0 16px 18px;padding:0;">
        <li>Le login ou le mot de passe transmis n'est pas correct.</li>
        <li>Votre compte n'a pas encore Ã©tÃ© activÃ© (activation via le lien reÃ§u par email de la Chambre des mÃ©tiers).</li>
      </ul>
      <p>
        Merci de vÃ©rifier ces deux points puis de saisir Ã  nouveau vos identifiants dans votre
        <strong>Espace Stagiaire</strong> :
      </p>
      <p style="text-align:center;margin:18px 0;">
        <a href="{form_link}"
           style="display:inline-block;background:#1f8f4a;color:white;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:bold">
          ðŸ‘‰ AccÃ©der Ã  mon Espace Stagiaire
        </a>
      </p>
      <p>
        Ã€ rÃ©ception, nous pourrons procÃ©der au paiement des frais d'examen. Si vous avez besoin d'aide, vous pouvez nous contacter au 04 22 47 07 68.
      </p>
      <p>
        Merci pour votre comprÃ©hension.
      </p>
      <p style="margin-top:18px;">
        <strong>ClÃ©ment VAILLANT</strong><br>
        Directeur IntÃ©grale Academy
      </p>
    """)
    return subject, html


def build_vtc_credentials_invalid_sms(first_name: str, form_link: str) -> str:
    first_name = (first_name or "").strip()
    greeting = f"Bonjour {first_name}, " if first_name else "Bonjour, "
    return (
        "IntÃ©grale Academy - Formation Chauffeur VTC "
        f"{greeting}Nous ne pouvons pas nous connecter Ã  votre compte ExamenT3P (Chambre des mÃ©tiers). "
        "Cause possible: identifiants incorrects ou compte non activÃ© (lien reÃ§u par email de la Chambre des mÃ©tiers). "
        "Merci de vÃ©rifier puis ressaisir vos identifiants dans votre Espace Stagiaire : "
        f"{form_link} "
        "A rÃ©ception, nous pourrons procÃ©der au paiement des frais d'examen. "
        "ClÃ©ment VAILLANT - Directeur IntÃ©grale Academy"
    )


def _send_vtc_credentials_invalid_notification(data: Dict[str, Any], session_obj: Dict[str, Any], trainee: Dict[str, Any]) -> bool:
    if _trainee_registration_is_cancelled(trainee):
        return False
    link = f"{PUBLIC_STUDENT_PORTAL_BASE.rstrip('/')}/espace/{(trainee.get('public_token') or '').strip()}"
    first_name = (trainee.get("first_name") or "").strip()
    subject, html_content = build_vtc_credentials_invalid_email(first_name, link)

    trainee_email = (trainee.get("email") or "").strip()
    trainee_phone = (trainee.get("phone") or "").strip()

    email_ok = brevo_send_email(
        trainee_email,
        subject,
        html_content,
        cc_emails=["clement@integraleacademy.com"],
        trainee=trainee,
    ) if trainee_email else False
    sms_ok = brevo_send_sms(trainee_phone, build_vtc_credentials_invalid_sms(first_name, link)) if trainee_phone else False

    trainee["vtc_cm_login"] = ""
    trainee["vtc_cm_password"] = ""
    trainee["vtc_cm_submitted_at"] = ""
    trainee["updated_at"] = _now_iso()

    phone_followups = trainee.get("phone_followups")
    if not isinstance(phone_followups, list):
        phone_followups = []
    phone_followups.insert(0, {
        "type": "VTC IDENTIFIANTS ERRONÃ‰S",
        "details": "Demande de ressaisie envoyÃ©e (identifiants ExamenT3P erronÃ©s).",
        "at": _now_iso(),
        "status": "ENVOYÃ‰E",
        "comment": "Mail + SMS envoyÃ©s et identifiants ExamenT3P rÃ©initialisÃ©s.",
    })
    trainee["phone_followups"] = phone_followups

    trainee_display_name = _format_trainee_name(trainee.get("first_name", ""), trainee.get("last_name", ""))
    add_admin_notification(
        data,
        f"ðŸ”µ Demande de nouveaux identifiants ExamenT3P envoyÃ©e Ã  {trainee_display_name}",
        meta={
            "type": "vtc_credentials_invalid",
            "session_id": session_obj.get("id"),
            "trainee_id": trainee.get("id"),
        },
    )

    return bool(email_ok or sms_ok)


def _send_vtc_credentials_reminder(data: Dict[str, Any], session_obj: Dict[str, Any], trainee: Dict[str, Any], details: str) -> bool:
    if _trainee_registration_is_cancelled(trainee):
        return False
    link = f"{PUBLIC_STUDENT_PORTAL_BASE.rstrip('/')}/espace/{(trainee.get('public_token') or '').strip()}"
    first_name = (trainee.get("first_name") or "").strip()
    subject, html_content = build_vtc_credentials_reminder_email(first_name, link)

    trainee_email = (trainee.get("email") or "").strip()
    trainee_phone = (trainee.get("phone") or "").strip()

    email_ok = brevo_send_email(
        trainee_email,
        subject,
        html_content,
        cc_emails=["clement@integraleacademy.com"],
        trainee=trainee,
    ) if trainee_email else False
    sms_ok = brevo_send_sms(trainee_phone, build_vtc_credentials_reminder_sms(first_name, link)) if trainee_phone else False

    copy_subject = f"Copie relance VTC identifiants envoyÃ©e â€“ {first_name} {(trainee.get('last_name') or '').strip()}".strip()
    copy_html = mail_layout(f"""
      <h2>Copie relance VTC</h2>
      <p><strong>Stagiaire :</strong> {_format_trainee_name(trainee.get('first_name', ''), trainee.get('last_name', ''))}</p>
      <p><strong>Session :</strong> {_session_get(session_obj, 'name', '') or 'â€”'}</p>
      <p><strong>Email stagiaire :</strong> {trainee_email or 'Non renseignÃ©'}</p>
      <p><strong>TÃ©lÃ©phone stagiaire :</strong> {trainee_phone or 'Non renseignÃ©'}</p>
      <p><strong>Email stagiaire envoyÃ© :</strong> {'Oui' if email_ok else 'Non'}</p>
      <p><strong>SMS envoyÃ© :</strong> {'Oui' if sms_ok else 'Non'}</p>
      <p><strong>Contexte :</strong> {details}</p>
    """)
    copy_email_ok = brevo_send_email("clement@integraleacademy.com", copy_subject, copy_html)

    trainee["vtc_cm_reminder_sent_at"] = _now_iso()
    trainee["vtc_cm_reminder_email_ok"] = bool(email_ok)
    trainee["vtc_cm_reminder_sms_ok"] = bool(sms_ok)
    trainee["vtc_cm_reminder_copy_email_ok"] = bool(copy_email_ok)
    trainee["updated_at"] = _now_iso()

    phone_followups = trainee.get("phone_followups")
    if not isinstance(phone_followups, list):
        phone_followups = []
    phone_followups.insert(0, {
        "type": "RELANCE VTC IDENTIFIANTS",
        "details": details,
        "at": _now_iso(),
        "status": "ENVOYÃ‰E",
        "comment": "Relance envoyÃ©e (mail + SMS) pour identifiants Chambre des mÃ©tiers manquants.",
    })
    trainee["phone_followups"] = phone_followups

    trainee_display_name = _format_trainee_name(trainee.get("first_name", ""), trainee.get("last_name", ""))
    add_admin_notification(
        data,
        f"â° Relance VTC identifiants envoyÃ©e Ã  {trainee_display_name}",
        meta={
            "type": "vtc_credentials_reminder",
            "session_id": session_obj.get("id"),
            "trainee_id": trainee.get("id"),
        },
    )
    return bool(email_ok or sms_ok or copy_email_ok)


def _is_vtc_cm_reminder_auto_disabled(trainee: Dict[str, Any]) -> bool:
    return bool(
        trainee.get("vtc_cm_reminder_auto_disabled")
        or (trainee.get("vtc_cm_reminder_auto_disabled_at") or "").strip()
    )


def _compute_vtc_cm_reminder_schedule(trainee: Dict[str, Any]) -> Optional[datetime.datetime]:
    if _trainee_registration_is_cancelled(trainee):
        return None
    if _is_vtc_cm_reminder_auto_disabled(trainee):
        return None
    if bool(trainee.get("exam_fees_paid")):
        return None
    if (trainee.get("vtc_cm_login") or "").strip() and (trainee.get("vtc_cm_password") or "").strip():
        return None
    if (trainee.get("vtc_cm_submitted_at") or "").strip():
        return None
    if (trainee.get("vtc_cm_reminder_sent_at") or "").strip():
        return None

    created_at = _parse_iso_datetime(trainee.get("created_at") or "")
    if not created_at:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=datetime.timezone.utc)

    return created_at + datetime.timedelta(days=7)


def _refresh_vtc_cm_reminder_schedule(trainee: Dict[str, Any]) -> None:
    due_at = _compute_vtc_cm_reminder_schedule(trainee)
    if due_at is None:
        trainee.pop("vtc_cm_reminder_scheduled_for", None)
        return
    trainee["vtc_cm_reminder_scheduled_for"] = due_at.astimezone(datetime.timezone.utc).isoformat()


def _send_vtc_credentials_missing_reminders(data: Dict[str, Any]) -> bool:
    changed = False
    now_utc = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    session_list = data.get("sessions") or []

    for session_obj in session_list:
        if session_obj.get("archived"):
            continue

        training_type = (_session_get(session_obj, "training_type", "") or "").upper()
        if "VTC" not in training_type:
            continue

        trainees = _session_trainees_list(session_obj)
        for trainee in trainees:
            if _trainee_registration_is_cancelled(trainee):
                _refresh_vtc_cm_reminder_schedule(trainee)
                continue
            _refresh_vtc_cm_reminder_schedule(trainee)

            if _is_vtc_cm_reminder_auto_disabled(trainee):
                continue
            if (trainee.get("vtc_cm_login") or "").strip() and (trainee.get("vtc_cm_password") or "").strip():
                continue
            if (trainee.get("vtc_cm_submitted_at") or "").strip():
                continue
            if (trainee.get("vtc_cm_reminder_sent_at") or "").strip():
                continue

            created_at = _parse_iso_datetime(trainee.get("created_at") or "")
            if not created_at:
                continue
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=datetime.timezone.utc)

            days_since_creation = (now_utc - created_at).days
            if days_since_creation < 7:
                continue

            _send_vtc_credentials_reminder(data, session_obj, trainee, "Relance automatique J+7")
            _refresh_vtc_cm_reminder_schedule(trainee)
            changed = True

        session_obj["trainees"] = trainees
        session_obj.pop("stagiaires", None)

    return changed


def _session_start_date(session_obj: Dict[str, Any]) -> Optional[datetime.date]:
    raw = (_session_get(session_obj, "date_start", "") or "").strip()
    if not raw:
        return None
    try:
        return datetime.datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _docs_relance_auto_enabled(session_obj: Dict[str, Any]) -> bool:
    training_type = (_session_get(session_obj, "training_type", "") or "").strip().upper()
    partner_id = str(session_obj.get("partner_id") or INTEGRALE_PARTNER_ID)
    return partner_id == INTEGRALE_PARTNER_ID and training_type != "DIRIGEANT VAE" and "VTC" not in training_type


def _docs_relance_schedule(session_obj, trainee, *, activated_on=None, today=None):
    start = _session_start_date(session_obj)
    if not start or not _docs_relance_auto_enabled(session_obj):
        return []
    today = today or datetime.datetime.now(ZoneInfo("Europe/Paris")).date()
    return automatic_document_schedule(trainee, start, today, activated_on=activated_on)


def _docs_relance_planned_date(session_obj, trainee=None, *, activated_on=None):
    if session_obj.get("archived"):
        return None
    trainee = trainee or {}
    if _trainee_registration_is_cancelled(trainee) or trainee.get("force_dossier_complete"):
        return None
    for row in _docs_relance_schedule(session_obj, trainee, activated_on=activated_on):
        if row["state"] in {"PrÃ©vue", "Ã€ envoyer"}:
            return datetime.date.fromisoformat(row["date"])
    return None


def _send_docs_relance_reminders(data: Dict[str, Any]) -> bool:
    """Legacy background hook only refreshes dates; delivery belongs to the cron.

    Loading a page must never send document reminders or save a stale snapshot
    over a delivery recorded by the protected scheduler.
    """
    changed = False
    activation = (data.get("document_reminders_scheduler") or {}).get("activated_on")
    for training in data.get("sessions", []):
        for trainee in _session_trainees_list(training):
            planned = _docs_relance_planned_date(training, trainee, activated_on=activation)
            value = planned.isoformat() if planned else ""
            if trainee.get("docs_relance_auto_planned_date") != value:
                trainee["docs_relance_auto_planned_date"] = value
                changed = True
    return changed


# =========================
# Helpers
# =========================

# =========================
# Public trainee "mini-login" (nom + date naissance)
# =========================
import unicodedata
import threading
import re

def _norm_lastname(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")  # remove accents
    s = re.sub(r"[^a-z0-9]+", "", s)  # keep only alnum, no spaces
    return s

def _birth_to_ddmmyyyy(value: str) -> str:
    """
    Normalise une date de naissance en DDMMYYYY.

    Formats acceptÃ©s :
    - DD/MM/YYYY, D/M/YYYY
    - DD-MM-YYYY, D-M-YYYY
    - YYYY-MM-DD, YYYY-M-D
    - DDMMYYYY (saisie publique compacte)
    - YYYYMMDD (stockage/import compact)

    Les zÃ©ros de tÃªte du jour et du mois sont toujours conservÃ©s.
    Si la date est absente ou invalide, renvoie une chaÃ®ne vide.
    """
    v = str(value or "").strip()
    if not v:
        return ""

    def _format_if_valid(day: str, month: str, year: str) -> str:
        if not (day and month and year) or len(year) != 4:
            return ""
        try:
            dt = datetime.datetime(int(year), int(month), int(day))
        except (TypeError, ValueError):
            return ""
        return dt.strftime("%d%m%Y")

    # Formats sÃ©parÃ©s explicites : pas de suppression des zÃ©ros, on reconstruit via datetime.
    match = re.fullmatch(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", v)
    if match:
        year, month, day = match.groups()
        return _format_if_valid(day, month, year)

    match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", v)
    if match:
        first, second, year = match.groups()
        french = _format_if_valid(first, second, year)
        if french:
            return french
        # CompatibilitÃ© avec d'anciens imports MM/DD/YYYY lorsque le format
        # franÃ§ais est impossible (ex : 10/29/1979).
        return _format_if_valid(second, first, year)

    digits = re.fullmatch(r"\d{8}", v)
    if digits:
        # Le formulaire public utilise DDMMYYYY. On le privilÃ©gie pour Ã©viter
        # qu'un jour comme 19 soit interprÃ©tÃ© comme le dÃ©but d'une annÃ©e.
        ddmmyyyy = _format_if_valid(v[0:2], v[2:4], v[4:8])
        if ddmmyyyy:
            return ddmmyyyy
        # SÛ}µëÊ×¬¢h­µç[Û×Ù\™XÝÙXš]ÛX[™]WÚY	ÊHÜˆ	ÉÂˆ[™VÉÜ[Û×ÛX[™]WÜ[I×HH™]šY]Ë™Ù]
	ÛX[™]WÜ[IÊHÜˆ[™K™Ù]
	Ü[Û×ÛX[™]WÜ[IÊHÜˆ	ÉÂˆYˆ™]šY]Ë™Ù]
	Ü[Û×ØÛY[ÚY	ÊN‚ˆ[™VÉÜ[Û×ÛX[™]WØÛY[ÚY	×HH™]šY]ÖÉÜ[Û×ØÛY[ÚY	×Bˆ[™VÉÜ[ÛÐÛY[Y	×HH[™K™Ù]
	Ü[ÛÐÛY[Y	ÊHÜˆ™]šY]ÖÉÜ[Û×ØÛY[ÚY	×Bˆ[™VÉÜ[ÛÐÝ\ÝÛY\’Y	×HH[™K™Ù]
	Ü[ÛÐÝ\ÝÛY\’Y	ÊHÜˆ™]šY]ÖÉÜ[Û×ØÛY[ÚY	×Bˆ[™VÉÜ[Û×Ù\™XÝÙXš]ÜÝXœØÜš\[Û—ÚY	×HH™^
ˆ
ˆÝŠ›ÝË™Ù]
	Ü[Û×Ù\™XÝÙXš]ÜÝXœØÜš\[Û—ÚY	ÊHÜˆ	ÉÊBˆ›Üˆ›ÝÈ[ˆ›ÝÜÈYˆ›ÝË™Ù]
	Ü[Û×Ù\™XÝÙXš]ÜÝXœØÜš\[Û—ÚY	ÊBˆ
Kˆ	ÉËˆ
Bˆ[™VÉÜ[ÛÑ\™XÝXš]Þ[˜ÕØ\›š[™É×HH	ÉÂˆ[™VÉÜÞ[˜ÕØ\›š[™É×HH	ÉÂˆ[™VÉÜ[ÛÑ\™XÝXš]\ÝÞ[˜ÙY]	×HH›ÝÂˆ[™VÉÜ[ÛÓ\ÝÞ[˜ÙY]	×HH›ÝÂˆYˆ™]šY]Ë™Ù]
	Û[ÙIÊHOH	ÛX[X[	Î‚ˆ[™VÉÙš[˜[˜ÚX[Ý˜XÚÚ[™×ÛÝ™\œšYI×HHÂˆ	Ù[˜X›Y	ÎˆYKˆ	ÜÛÝ\˜ÙIÎˆ	ØYZ[—Ü™]šY]ÙYÜØÚY[IËˆ	Ùš[™Ù\œš[	Îˆ™]šY]Ë™Ù]
	Ùš[™Ù\œš[	ÊHÜˆ	ÉËˆ	Ý\]YØ]	Îˆ›ÝËˆ	Ý\]YØžIÎˆ
ˆÙ\ÜÚ[Û‹™Ù]
	ØYZ[—Ý\Ù\›˜[YIÊHÜˆÙ\ÜÚ[Û‹™Ù]
	ØYZ[—Ù[XZ[	ÊHÜˆ	ØYZ[‰ÂˆYˆ\×Ü™\]Y\ÝØÛÛ^

H[ÙH	ÜÞ\Ý[IÂˆ
KˆBˆ[ÙN‚ˆ[™KœÜ
	Ùš[˜[˜ÚX[Ý˜XÚÚ[™×ÛÝ™\œšYIË›Û™JBˆÜÞ[˜×ÜÙ\WØ[X\Ù\Ê[™JBˆYˆ[™K™Ù]
	Ü[ÛÔ^[Y[ÛØ˜[Ý]\ÉÊHOH	Ô^pêIÎ‚ˆ[™VÉÜ^[Y[Ý]\É×HH	ÜZY	Âˆ[Yˆ[™K™Ù]
	Ü[ÛÔ^[Y[ÛØ˜[Ý]\ÉÊHOH	ÔZY[Y[\Y[	Î‚ˆ[™VÉÜ^[Y[Ý]\É×HH	Ü\X[	Âˆ[Yˆ[™K™Ù]
	Ü[ÛÔ^[Y[ÛØ˜[Ý]\ÉÊHOH	Ô™Z™]0êIÎ‚ˆ[™VÉÜ^[Y[Ý]\É×HH	Ù˜Z[Y	Âˆ[ÙN‚ˆ[™VÉÜ^[Y[Ý]\É×HH	Ý[œZY	ÂˆØš[[™×ÛÙÊˆ[™Kˆ
ˆ	ÔÝZ]šHš[˜[˜ÚY\ˆÛÜœšYðêHX[Y[[Y[	ÂˆYˆ™]šY]Ë™Ù]
	Û[ÙIÊHOH	ÛX[X[	Âˆ[ÙH	ÔÝZ]šHš[˜[˜ÚY\ˆ™XÛÛœÝZ]\Z\È[ÛÉÂˆ
Kˆ	ÜÝXØÙ\ÜÉËˆ‰ÞÛ[Š›ÝÜÊ_H0êXÚ0êX[˜ÙJÊKÛÛ[™K™Ù]
œÙ\WÜ^[Y[Ü[ˆ‹ßJK™Ù]
œZYÚ[œÝ[Y[È‹
_H^pêYJÊIËˆ™]šY]Ë™Ù]
	Ùš[™Ù\œš[	ÊHÜˆ	ÉËˆ
B‚‚™YˆØ\WÜ[Û×ØÛÛXÝ[Û—ÝÙXšÛÚÊ]NˆXÝÜÝ‹[žWK][NˆXÝÜÝ‹[žWJHOˆ›ÛÛ‚ˆÛÛXÝ[Û—ÚYHÝŠ][K™Ù]
	ÚY	ÊHÜˆ	ÉÊBˆÝXœØÜš\[Û—ÚYHÝŠ][K™Ù]
	Ù\™XÝÙXš]ÜÝXœØÜš\[Û—ÚY	ÊHÜˆ	ÉÊBˆYˆ›Ý
ÛÛXÝ[Û—ÚYÜˆÝXœØÜš\[Û—ÚY
N‚ˆ™]\›ˆ˜[ÙBˆ\]YH˜[ÙBˆ›Üˆ[™H[ˆØš[[™×Û[™\Ê]JN‚ˆ[œÝ[Y[ÈH[™K™Ù]
	Ù\™XÝXš][œÝ[Y[ÉÊHYˆ\Ú[œÝ[˜ÙJ[™K™Ù]
	Ù\™XÝXš][œÝ[Y[ÉÊK\Ý
H[ÙH×BˆX]Ú[™ÈHÂˆ[œÝ›Üˆ[œÝ[ˆ[œÝ[Y[ÂˆYˆ
ÝXœØÜš\[Û—ÚY[™ÝŠ[œÝ™Ù]
	Ü[Û×Ù\™XÝÙXš]ÜÝXœØÜš\[Û—ÚY	ÊHÜˆ	ÉÊHOHÝXœØÜš\[Û—ÚY
BˆÜˆ
ÛÛXÝ[Û—ÚY[™ÝŠ[œÝ™Ù]
	Ü[Û×Ù\™XÝÙXš]ØÛÛXÝ[Û—ÚY	ÊHÜˆ	ÉÊHOHÛÛXÝ[Û—ÚY
BˆBˆ]™[Ù]HHÝŠˆ][K™Ù]
	ØÛÛXÝ[Û—Ù]IÊHÜˆ][K™Ù]
	ÜØÚY[YØ]	ÊHÜˆ][K™Ù]
	ÙYWÙ]IÊBˆÜˆ][K™Ù]
	Ù]IÊHÜˆ][K™Ù]
	ØÛÛ\]YØ]	ÊHÜˆ][K™Ù]
	ÜZYØ]	ÊHÜˆ	ÉÂˆ
VÎŒLBˆYˆ[ŠX]Ú[™ÊHˆN‚ˆ]YHÂˆ[œÝ›Üˆ[œÝ[ˆX]Ú[™ÂˆYˆÝŠ[œÝ™Ù]
	Ü[Û×ÛÜšYÚ[˜[ÙYWÙ]IÊHÜˆ[œÝ™Ù]
	ÙYWÙ]IÊHÜˆ[œÝ™Ù]
	Ù]IÊHÜˆ	ÉÊVÎŒLHOH]™[Ù]BˆBˆÈ™]™\ˆ›ÜYØ]HÛ™H™XÝ\œš[™ÈÛÛXÝ[Û‰ÜÈ™Z™XÝ[ÛˆÈ]™\žBˆÈ]\™H[œÝ[Y[Ú[ˆ[ÛÈ\È›ÝÝ\YYH\ØX›H]K‚ˆX]Ú[™ÈH]YÜˆÂˆ[œÝ›Üˆ[œÝ[ˆX]Ú[™ÂˆYˆÝŠ[œÝ™Ù]
	Ü[Û×Ù\™XÝÙXš]ØÛÛXÝ[Û—ÚY	ÊHÜˆ	ÉÊHOHÛÛXÝ[Û—ÚYˆBˆ›Üˆ[œÝ[ˆX]Ú[™Î‚ˆ™]š[Ý\×ÜÝ]\ÈH[œÝ™Ù]
	ÜÝ]\ÉÊBˆ[œÝÉÜ[Û×Ù\™XÝÙXš]ØÛÛXÝ[Û—ÚY	×HHÛÛXÝ[Û—ÚYÜˆ[œÝ™Ù]
	Ü[Û×Ù\™XÝÙXš]ØÛÛXÝ[Û—ÚY	ÊHÜˆ	ÉÂˆ[œÝÉÜÝ]\É×HHÛX\ØÛÛXÝ[Û—ÜÝ]\Ê][K™Ù]
	ÜÝ]\ÉÊHÜˆ][K™Ù]
	Ù]™[	ÊJBˆÜ™XÛÛ˜Ú[WÝ˜XÚÙYÚ[œÝ[Y[ÝÚ]Ü[ÛÊ[œÝ][JBˆYˆ[œÝÉÜÝ]\É×HOH	ØÛÛ\]Y	Î‚ˆ[œÝÉÜZY]	×HH][K™Ù]
	ÜZYØ]	ÊHÜˆ][K™Ù]
	ØÛÛ\]YØ]	ÊHÜˆÛ›Ý×Ú\ÛÊ
BˆÜ™\ÝÜ™WÜ™[[Ý™YÚ[œÝ[Y[ÚY—ÜZY
[™K[œÝ
BˆYˆ][K™Ù]
	ÜÝ]\×Ü™X\ÛÛ‰ÊN‚ˆ[œÝÉÙ˜Z[\™T™X\ÛÛ‰×HH][K™Ù]
	ÜÝ]\×Ü™X\ÛÛ‰ÊBˆ[œÝÉÜÝ]\×Ü™X\ÛÛ‰×HH][K™Ù]
	ÜÝ]\×Ü™X\ÛÛ‰ÊBˆ[œÝÉÝ\]YØ]	×HHÛ›Ý×Ú\ÛÊ
Bˆ\›ÙÙÙ\‹š[™›Ê	ÖÔSÓ•×HÛÛXÝ[Ûˆ	\ÈÝXœØÜš\[Û—ÚYI\ÈÛÛXÝ[Û—ÚYI\ÉË[œÝÉÜÝ]\É×KÝXœØÜš\[Û—ÚYÛÛXÝ[Û—ÚY
BˆØš[[™×ÛÙÊ[™KˆÛÛXÝ[ÛˆÑTH[ÛÈÚ[œÝÉÜÝ]\É×_H‹	ÜÝXØÙ\ÜÉÈYˆ[œÝÉÜÝ]\É×HOH	ØÛÛ\]Y	È[ÙH	Ù\œ›Ü‰Ë[œÝ™Ù]
	ÜÝ]\×Ü™X\ÛÛ‰ÊHÜˆ	ÉËÛÛXÝ[Û—ÚY
Bˆ[™VÉÜ[ÛÔ^[Y[ÛØ˜[Ý]\É×HHÜ[Û×Ü^[Y[ÙÛØ˜[ÜÝ]\Ê[™JBˆYˆ[™VÉÜ[ÛÔ^[Y[ÛØ˜[Ý]\É×HOH	Ô^pêIÎˆ[™VÉÜ^[Y[Ý]\É×HH	ÜZY	Âˆ[Yˆ[™VÉÜ[ÛÔ^[Y[ÛØ˜[Ý]\É×HOH	ÔZY[Y[\Y[	Îˆ[™VÉÜ^[Y[Ý]\É×HH	Ü\X[	Âˆ[Yˆ[™VÉÜ[ÛÔ^[Y[ÛØ˜[Ý]\É×HOH	Ô™Z™]0êIÎˆ[™VÉÜ^[Y[Ý]\É×HH	Ù˜Z[Y	Âˆ[Yˆ[™VÉÜ[ÛÔ^[Y[ÛØ˜[Ý]\É×H[ˆÉÔ™Z™]˜Z]0êIË	Ô°ê[0ê™[Y[È›ÙÜ˜[[pê\ÉßNˆ[™VÉÜ^[Y[Ý]\É×HH	Ý[œZY	ÂˆYˆ[œÝÉÜÝ]\É×H[ˆÉÙ˜Z[Y	Ë	Ü™]\›™Y	Ë	Ü™Y[™Y	ßH[™™]š[Ý\×ÜÝ]\È›Ý[ˆÉÙ˜Z[Y	Ë	Ü™]\›™Y	Ë	Ü™Y[™Y	ßN‚ˆÛ›ÝYžWÜ™Z™XÝYÜ[Û×ÙXš]
]K[™K[œÝÛÛXÝ[Û—ÚY
BˆÜÞ[˜×ÜÙ\WØ[X\Ù\Ê[™JBˆÜØ]™WØš[[™×Û[™J]K[™JBˆ\]YHYBˆ™]\›ˆ\]Y‚‚™YˆØ\WÜ[Û×ÛX[™]WÝÙXšÛÚÊ]NˆXÝÜÝ‹[žWK][NˆXÝÜÝ‹[žWJHOˆ›ÛÛ‚ˆX[™]WÚYHÝŠ][K™Ù]
	ÚY	ÊHÜˆ][K™Ù]
	Ù\™XÝÙXš]ÛX[™]WÚY	ÊHÜˆ	ÉÊBˆYˆ›ÝX[™]WÚY‚ˆ™]\›ˆ˜[ÙBˆ\]YH˜[ÙBˆÝ]\ÈHÛX\ÛX[™]WÜÝ]\Ê][K™Ù]
	ÜÝ]\ÉÊHÜˆ][K™Ù]
	Ù]™[	ÊJBˆ›Üˆ[™H[ˆØš[[™×Û[™\Ê]JN‚ˆYˆÝŠ[™K™Ù]
	Ü[Û×Ù\™XÝÙXš]ÛX[™]WÚY	ÊHÜˆ	ÉÊHOHX[™]WÚY‚ˆÛÛ[YBˆ[™VÉÜ[Û×ÛX[™]WÜÝ]\É×HHÝ]\Âˆ[™VÉÛX[™]TÝ]\É×HHÝ]\ÂˆYˆÝ]\È[ˆÉØXÝ]™IË	ÜÚYÛ™Y	ßN‚ˆ[™VÉÜ[Û×ÛX[™]WÜÚYÛ™YØ]	×HH][K™Ù]
	ØXØÙ\YØ]	ÊHÜˆ][K™Ù]
	ÜÚYÛ™YØ]	ÊHÜˆ][K™Ù]
	Ø\›Ý™YØ]	ÊHÜˆ[™K™Ù]
	Ü[Û×ÛX[™]WÜÚYÛ™YØ]	ÊHÜˆÛ›Ý×Ú\ÛÊ
Bˆ\›ÙÙÙ\‹š[™›Ê	ÖÔSÓ•×HÙXšÛÚÈX[™]ÚYÛ°êH™péÝHX[™]WÚYI\ÉËX[™]WÚY
BˆØš[[™×ÛÙÊ[™K	ÕÙXšÛÚÈX[™]ÑTHÚYÛ°êH™péÝIË	ÜÝXØÙ\ÜÉËÝ]\ËX[™]WÚY
BˆžN‚ˆ[œÝ\™WÜ[Û×ÜÙ\WÚ[œÝ[Y[×Ù›Ü—Û[™J[™JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆØš[[™×ÛÙÊ[™K	Ñ\œ™]\ˆÜ°êX][ÛˆÝXœØÜš\[ÛœÈ\°êÈÚYÛ˜]\™HX[™]	Ë	Ù\œ›Ü‰ËÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJKX[™]WÚY
BˆÜÞ[˜×ÜÙ\WØ[X\Ù\Ê[™JBˆÜØ]™WØš[[™×Û[™J]K[™JBˆ\]YHYBˆ™]\›ˆ\]Y‚‚™Yˆ[œÝ\™T[ÛÔÙ\R[œÝ[Y[Ê˜Z[™YRYˆÝŠHOˆXÝÜÝ‹[žWN‚ˆ]HHØYÙ]J
BˆÜ™X]YHˆX]ÚYHˆ›Üˆ[™H[ˆØš[[™×Û[™\Ê]JN‚ˆYˆÝŠ[™K™Ù]
	Ý˜Z[™YRY	ÊHÜˆ	ÉÊHOHÝŠ˜Z[™YRY
N‚ˆÛÛ[YBˆYˆ[™K™Ù]
	Ü^[Y[[ÙIÊHOH	ÜÙ\WÙ\™XÝÙXš]	Î‚ˆÛÛ[YBˆX]ÚY
ÏHBˆ™\Ý[H[œÝ\™WÜ[Û×ÜÙ\WÚ[œÝ[Y[×Ù›Ü—Û[™J[™JBˆÜ™X]Y
ÏH[
™\Ý[™Ù]
	ØÜ™X]Y	ÊHÜˆ
BˆÜØ]™WØš[[™×Û[™J]K[™JBˆØ]™WÙ]J]JBˆ™]\›ˆÉÛX]ÚY	ÎˆX]ÚY	ØÜ™X]Y	ÎˆÜ™X]YB‚‚\œÜÝ
	ËØ\KØš[[™ËÜ™\Ù[™[X[™]IÊBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØš[[™×Ü™\Ù[™ÛX[™]J
N‚ˆ]HHØYÙ]J
NÈ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßNÈ[™HHÛ[™WÙœ›ÛWÜ^[ØY
]K^[ØY
BˆYˆ[™H[™[™K™Ù]
	Ü™YÚ\Ý˜][ÛØ[˜Ù[Y	ÊN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ô™[[˜ÙH›Ü]pêYHˆÙ]H[œØÜš\[Ûˆ\Ý[›[0êYK‰ßJKBˆYˆ›Ý[™HÜˆ›Ý[™K™Ù]
	ÜÚYÛ—Ý\›	ÊN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ð]XÝ[ˆY[ˆHX[™]0è™[›ÞY\‰ßJKˆÙ[HÜÙ[™Ü[Û×ÛX[™]WÛ[šÊ[™JBˆØš[[™×ÛÙÊ[™K	ÓY[ˆX[™]ÑTH™[›ÞpêIË	ÜÝXØÙ\ÜÉÈYˆÙ[[ÙH	Ù\œ›Ü‰Ë	Ñ[XZ[[›ÞpêIÈYˆÙ[[ÙH	Ñ[XZ[›Ûˆ[›ÞpêIÊBˆÜØ]™WØš[[™×Û[™J]K[™JNÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ›ÛÛ
Ù[
K	ÛY\ÜØYÙIÎˆ	ÓY[ˆHX[™]™[›ÞpêIÈYˆÙ[[ÙH	Ñ[XZ[›Ûˆ[›ÞpêIßJK
ŒYˆÙ[[ÙH
B‚‚\œÜÝ
	ËØ\KØš[[™ËØÜ™X]K[X[™]IÊBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØš[[™×ØÜ™X]WÛX[™]J
N‚ˆˆˆÜ™X]H
Üˆ™]žJHHÑTHX[™]HÚ]Ý]Ü™X][™È[›Ý\ˆ[›ÚXÙKˆˆˆ‚ˆ]HHØYÙ]J
NÈ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßNÈ[™HHÛ[™WÙœ›ÛWÜ^[ØY
]K^[ØY
BˆYˆ›Ý[™N‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÓYÛ™HH˜XÝ\˜][Ûˆ[›Ý]˜X›IßJKˆYˆ[™K™Ù]
	Ü™YÚ\Ý˜][ÛØ[˜Ù[Y	ÊN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ô°ê[0ê™[Y[›Ü]pêHˆÙ]H[œØÜš\[Ûˆ\Ý[›[0êYK‰ßJKBˆØ\WÚ[›ÚXÙWÜ™XÚ\Y[Ü^[ØY
[™K^[ØY
BˆžN‚ˆÙ[œÝ\™WÜ[Û×ÛØ]]Ü™XYJ
BˆYˆ›Ý
[™K™Ù]
	Ü[ÛÐÛY[Y	ÊHÜˆ[™K™Ù]
	Ü[ÛÐÝ\ÝÛY\’Y	ÊJN‚ˆÛY[Ü^[ØYHZ[Ü[Û×ØÛY[Ü^[ØY
ˆ[™K[™KÉÚY	Îˆ[™K™Ù]
	ÜÙ\ÜÚ[Û’Y	Ê_Kˆ[™K™Ù]
	Ùš[˜[˜Ú[™Õ\IÊHÜˆ[™K™Ù]
	Ùš[˜[˜Ú[™ÓX™[	ÊKˆ
Bˆ˜[Y][Û—Ù\œ›ÜœÈH˜[Y]WÜ[Û×ØÛY[Ü^[ØY
ÛY[Ü^[ØY[™K™Ù]
	Ùš[˜[˜Ú[™Õ\IÊJBˆYˆ˜[Y][Û—Ù\œ›ÜœÎ‚ˆ˜Z\ÙH[[YQ\œ›ÜŠÙ›Ü›X]Ü[Û×Ý˜[Y][Û—Ù\œ›ÜœÊ˜[Y][Û—Ù\œ›ÜœÊJBˆWØÛY[HÙ]ÛÜ—ØÜ™X]WÜ[Û×Øš[[™×ØÛY[
ÛY[Ü^[ØY
BˆÛY[ÚYH
WØÛY[™Ù]
	ØÛY[	ÊHÜˆWØÛY[
K™Ù]
	ÚY	ÊBˆYˆ›ÝÛY[ÚY‚ˆ˜Z\ÙH[[YQ\œ›ÜŠ	ÐÛY[[ÛÈ[›Ý]˜X›IÊBˆ[™VÉÜ[ÛÐÛY[Y	×HH[™VÉÜ[ÛÐÝ\ÝÛY\’Y	×HHÛY[ÚYˆ^[Y[Ü[ˆHÛ›Ü›X[^™WÜ^[Y[Ü[Š^[ØY™Ù]
	Ü^[Y[[‰ÊHÜˆ^[ØYÛ[Û™^J[™K™Ù]
	Ø[[Ý[ÉÊHÜˆ[™K™Ù]
	Ø[[Ý[	ÊJJBˆYˆ^[Y[Ü[‹™Ù]
	Û[ÙIÊHOH	ÜÙ\WÙ\™XÝÙXš]	ÈÜˆ›Ý^[Y[Ü[‹™Ù]
	ÜØÚY[IÊN‚ˆ˜Z\ÙH[[YQ\œ›ÜŠ	Õ™]Z[^ˆ0êYš[š\ˆ]H[Ú[œÈ[™H0êXÚ0êX[˜ÙHH°ê[0ê™[Y[	ÊBˆÜÙ]\Ü[Û×Ù\™XÝÙXš]Ù›Ü—Û[™J[™K^[Y[Ü[ŠBˆ[™VÉÜ[ÛÔ^[Y[ÛØ˜[Ý]\É×HHÜ[Û×Ü^[Y[ÙÛØ˜[ÜÝ]\Ê[™JBˆÜ\œÚ\ÝÜ[Û×ÛX[™]WÛÛ—Ý˜Z[™YJ]K[™JBˆÜØ]™WØš[[™×Û[™J]K[™JNÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆYK	ÛY\ÜØYÙIÎˆ	ÓX[™]H°ê[0ê™[Y[Ü°êpêIË	Û[™IÎˆÙš[™Øš[[™×Û[™J]K[™VÉÚY	×J_JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆØš[[™×ÛÙÊ[™K	Ñ\œ™]\ˆÜ°êX][ÛˆX[™]ÑTIË	Ù\œ›Ü‰ËÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJJBˆÜØ]™WØš[[™×Û[™J]K[™JNÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ›Ü›X]Ü[Û×Ù\œ›Ü—Ù›Ü—Ùœ›Û
^Ê_JK‚‚™YˆÚ[œÝ[Y[ÙY]ÜÛ˜\ÚÝ
[™NˆXÝÜÝ‹[žWJHOˆ\ÝÓ\ÝÐ[žWWN‚ˆˆˆÛÛ\\™HH^XÝ\Ü^YYØÚY[K[˜ÛY[™ÈÙXšÛÚËÜÝ]\ÈÚ[™Ù\Ëˆˆˆ‚ˆ™]\›ˆÂˆÜÝŠ›ÝË™Ù]
	ÙYWÙ]IÊHÜˆ›ÝË™Ù]
	Ù]IÊHÜˆ	ÉÊVÎŒLKˆ[Û™^WÝ˜[YWÝ×ØÙ[Ê›ÝË™Ù]
	Ø[[Ý[	ÊHÜˆ
KÝŠ›ÝË™Ù]
	ÜÝ]\ÉÊHÜˆ	ÉÊKˆÝŠ›ÝË™Ù]
	Ü[Û×Ù\™XÝÙXš]ÜÝXœØÜš\[Û—ÚY	ÊHÜˆ	ÉÊKˆÝŠ›ÝË™Ù]
	Ü[Û×Ù\™XÝÙXš]ØÛÛXÝ[Û—ÚY	ÊHÜˆ	ÉÊKˆÚ[œÝ[Y[ÜØÚY[WÜÜÚ][ÛŠ›ÝË[™^
ÈJKˆ›ÛÛ
›ÝË™Ù]
	Ù^ÛYYÙœ›ÛWÜØÚY[WÝÝ[ÉÊJKˆÚ[œÝ[Y[Ü™Z™XÝ[Û—Ú\×Ý™X]Y
›ÝÊKÝŠ›ÝË™Ù]
	Ý˜XÚÚ[™×Ü™[[Ý™YØ]	ÊHÜˆ	ÉÊWBˆ›Üˆ[™^›ÝÈ[ˆ[[Y\˜]JÜÙ\WÚ[œÝ[Y[Ê[™JJBˆB‚‚™YˆÜ™Yœ™\ÚÙY]YÚ[œÝ[Y[Ü[Š[™NˆXÝÜÝ‹[žWJHOˆ›Û™N‚ˆ›ÝÜÈHÜÙ\WÚ[œÝ[Y[Ê[™JBˆY™™XÝ]™HHÛÜY
ÙY™™XÝ]™WÜÙ\WÚ[œÝ[Y[Ê[™JKÙ^O[[X™H›ÝÎˆÝŠ›ÝË™Ù]
	Ù]IÊHÜˆ	ÉÊJBˆÜÚ][ÛœÈH×Ú[œÝ[Y[ÜØÚY[WÜÜÚ][ÛŠ›ÝË›ÝÜËš[™^
›ÝÊH
ÈJNˆ[™^ˆ›Üˆ[™^›ÝÈ[ˆ[[Y\˜]JY™™XÝ]™KÝ\LJ_Bˆ›ÜˆÜ™\‹›ÝÈ[ˆ[[Y\˜]J›ÝÜËÝ\LJN‚ˆÛÜÜÚ][ÛˆHÚ[œÝ[Y[ÜØÚY[WÜÜÚ][ÛŠ›ÝËÜ™\ŠBˆÈ[]YÛÝÈ™[XZ[ˆ\Ý[˜Ýœ›ÛH[]™HÜÚ][ÛœËˆH]\ˆ™X[ˆÈ˜[šÈ^[Y[]\Ý›ÝÛÛ\ÙH[È[›Ý\ˆ[œÝ[Y[	ÜÈÛÝ‚ˆÜÚ][ÛˆHÜÚ][ÛœË™Ù]
ÛÜÜÚ][Û‹[ŠY™™XÝ]™JH
ÈÛÜÜÚ][ÛŠBˆ›ÝÖÉÚ[™^	×HH›ÝÖÉÜØÚY[WÚ[™^	×HHÜÚ][Û‚ˆ›ÝÖÉÜØÚY[WÝÝ[	×HH[ŠY™™XÝ]™JBˆ[™VÉÜ^[Y[[‰×HHÂˆ
ŠŠ[™K™Ù]
	Ü^[Y[[‰ÊHÜˆßJK	Û[ÙIÎˆ	ÜÙ\WÙ\™XÝÙXš]	Ëˆ	Ú[œÝ[Y[ÉÎˆ[ŠY™™XÝ]™JK	ÛX™[	Îˆ‰ðâXÚ0êX[˜ÚY\ˆÛ[ŠY™™XÝ]™J_H0êXÚ0êX[˜ÙJÊIËˆ	Ùš\œÝXš]]IÎˆY™™XÝ]™VÌK™Ù]
	Ù]IÊHYˆY™™XÝ]™H[ÙH	ÉËˆ	ÜØÚY[IÎˆÞÉÙ]IÎˆ›ÝË™Ù]
	Ù]IÊK	Ø[[Ý[	Îˆ›ÝË™Ù]
	Ø[[Ý[	Ê_H›Üˆ›ÝÈ[ˆY™™XÝ]™WKˆBˆÜÞ[˜×ÜÙ\WØ[X\Ù\Ê[™JB‚‚™YˆÜ™XÛÛ˜Ú[WÝ˜XÚÙYÚ[œÝ[Y[ÝÚ]Ü[ÛÊ›ÝÎˆXÝÜÝ‹[žWKÛÛXÝ[ÛŽˆXÝÜÝ‹[žWJHOˆ›Û™N‚ˆˆˆ’ÙY\[™[™ÈØØ[Y]Ë]ÛÝ[H˜[šÉÜÈ[[Ý[Û˜ÙH]\ÈZYˆˆˆ‚ˆYˆ›Ý›ÝË™Ù]
	Ý˜XÚÚ[™×Ü[™[™×Ü[ÛÉÊN‚ˆ™]\›‚ˆ˜[š×Ù]HHÜ[Û×ØÛÛXÝ[Û—Ù]JÛÛXÝ[ÛŠBˆ˜[š×Ø[[Ý[ØÙ[ÈHÜ[Û×ØÛÛXÝ[Û—Ø[[Ý[ØÙ[ÊÛÛXÝ[ÛŠBˆYˆ˜[š×Ø[[Ý[ØÙ[Èˆ‚ˆ›ÝÖÉÜ[Û×ÛÜšYÚ[˜[Ø[[Ý[	×HH˜[š×Ø[[Ý[ØÙ[ÈÈLˆYˆ˜[š×Ù]N‚ˆ›ÝÖÉÜ[Û×ÛÜšYÚ[˜[ÙYWÙ]I×HH˜[š×Ù]BˆZYHÝŠ›ÝË™Ù]
	ÜÝ]\ÉÊHÜˆ	ÉÊK›ÝÙ\Š
H[ˆSÓ•×ÔRQÐÓÓPÕSÓ—ÔÕUTÑTÂˆYˆZY‚ˆÈÛÛYHÙXšÛÚÈ^[ØYÈÛZ]H[[Ý[ˆ\ÙHH\Ý˜[šÈ[[Ý[ˆÈ[š]X[HH[[Ý[™Y›Ü™HHØØ[Y][ˆ]Ø\ÙK‚ˆZYØ[[Ý[ØÙ[ÈH˜[š×Ø[[Ý[ØÙ[ÈÜˆ[Û™^WÝ˜[YWÝ×ØÙ[Ê›ÝË™Ù]
	Ü[Û×ÛÜšYÚ[˜[Ø[[Ý[	ÊHÜˆ
BˆYˆZYØ[[Ý[ØÙ[Èˆ‚ˆ›ÝÖÉØ[[Ý[	×HHZYØ[[Ý[ØÙ[ÈÈLˆZYÙ]HH˜[š×Ù]HÜˆ›ÝË™Ù]
	Ü[Û×ÛÜšYÚ[˜[ÙYWÙ]IÊBˆYˆZYÙ]N‚ˆ›ÝÖÉÙ]I×HH›ÝÖÉÙYWÙ]I×HHZYÙ]Bˆ]\×ÛX]ÚH˜[š×Ù]HOHÝŠ›ÝË™Ù]
	ÙYWÙ]IÊHÜˆ›ÝË™Ù]
	Ù]IÊHÜˆ	ÉÊVÎŒLBˆ[[Ý[×ÛX]ÚH
ˆ˜[š×Ø[[Ý[ØÙ[ÈOH[Û™^WÝ˜[YWÝ×ØÙ[Ê›ÝË™Ù]
	Ø[[Ý[	ÊHÜˆ
BˆYˆ˜[š×Ø[[Ý[ØÙ[Èˆ[ÙH	Ü[Û×ÛÜšYÚ[˜[Ø[[Ý[	È›Ý[ˆ›ÝÂˆ
BˆYˆZYÜˆ
]\×ÛX]Ú[™[[Ý[×ÛX]Ú
N‚ˆ›ÜˆÙ^H[ˆ
	Ý˜XÚÚ[™×Ü[™[™×Ü[ÛÉË	Ü[Û×ÛÜšYÚ[˜[ÙYWÙ]IË	Ü[Û×ÛÜšYÚ[˜[Ø[[Ý[	ÊN‚ˆ›ÝËœÜ
Ù^K›Û™JB‚‚™YˆÜ™\ÝÜ™WÜ™[[Ý™YÚ[œÝ[Y[ÚY—ÜZY
[™NˆXÝÜÝ‹[žWK›ÝÎˆXÝÜÝ‹[žWJHOˆ›Û™N‚ˆˆˆHØØ[™[[Ý˜[™]™\ˆ\˜\Ù\ÈH^[Y[ÝXœÙ\]Y[HÛÛ™š\›YYžH[ÛËˆˆˆ‚ˆYˆ›ÝË™Ù]
	Ý˜XÚÚ[™×Ü™[[Ý™YØ]	ÊH[™ÝŠ›ÝË™Ù]
	ÜÝ]\ÉÊHÜˆ	ÉÊK›ÝÙ\Š
H[ˆSÓ•×ÔRQÐÓÓPÕSÓ—ÔÕUTÑTÎ‚ˆ›ÝÖÉÝ˜XÚÚ[™×Ü™\ÝÜ™YØY\—Ü^[Y[Ø]	×HHÛ›Ý×Ú\ÛÊ
Bˆ›ÝËœÜ
	Ý˜XÚÚ[™×Ü™[[Ý™YØ]	Ë›Û™JBˆ›ÝËœÜ
	Ù^ÛYYÙœ›ÛWÜØÚY[WÝÝ[ÉË›Û™JBˆ›ÝÖÉÜØÚY[WÚ[™^	×HH›ÝÖÉÚ[™^	×HHH
ÈX^
ˆ
Ú[œÝ[Y[ÜØÚY[WÜÜÚ][ÛŠ][K[™^
ÈJBˆ›Üˆ[™^][H[ˆ[[Y\˜]JÜÙ\WÚ[œÝ[Y[Ê[™JJHYˆ][H\È›Ý›ÝÊKY˜][Lˆ
B‚‚\œÜÝ
	ËØ\KØš[[™ËÚ[œÝ[Y[ÉÊBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØš[[™×ÙY]Ú[œÝ[Y[

N‚ˆˆˆ‘Y]ØØ[˜XÚÚ[™ÈÛ›NÈ\È[™Ú[™]™\ˆÜš]\ÈÈ[ÛËˆˆˆ‚ˆYˆ›ÝÙš[˜[˜Ú[™×Ü\™\—Û[Ù[WÙ[˜X›Y

N‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÓH[Ù[Hš[˜[˜Ù[Y[\Ý™\œ›ÝZ[0êK‰ßJKÂˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJBˆYˆ›Ý\Ú[œÝ[˜ÙJ^[ØYXÝ
HÜˆ^[ØY™Ù]
	ÜØÛÜIÊHOH	Ý˜XÚÚ[™ÉÎ‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ô°êXÚ\Ù^ˆ]YHH[ÙYšXØ][ÛˆÛÛ˜Ù\›™HHÝZ]šH[š\]Y[Y[‰ßJKˆXÝ[ÛˆH^[ØY™Ù]
	ØXÝ[Û‰ÊBˆYˆXÝ[Ûˆ›Ý[ˆÉØY	Ë	Ý\]IË	Ù[]IßN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÐXÝ[Ûˆ[˜ÛÛ›YK‰ßJKˆYˆ]]]J]JN‚ˆ[™\ÈHØš[[™×Û[™\×Ù›Ü—Ý˜Z[™YWÜÙ\ÜÚ[ÛŠ]KÝŠ^[ØY™Ù]
	Ý˜Z[™YRY	ÊHÜˆ	ÉÊKÝŠ^[ØY™Ù]
	ÜÙ\ÜÚ[Û’Y	ÊHÜˆ	ÉÊJBˆ[™HH™^

][H›Üˆ][H[ˆ[™\ÈYˆÝŠ][K™Ù]
	ÚY	ÊJHOHÝŠ^[ØY™Ù]
	Û[™RY	ÊHÜˆ	ÉÊJK›Û™JBˆYˆ›Ý[™N‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ðâXÚ0êX[˜ÚY\ˆ[›Ý]˜X›HÝ\ˆÙ]HšXÚK‰ßJKˆYˆ[™K™Ù]
	Ü™YÚ\Ý˜][ÛØ[˜Ù[Y	ÊHÜˆ\×ØÜ—Øš[[™×ØÛÛ^
[™JN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÐÙ]0êXÚ0êX[˜ÚY\ˆ™H]]\È0ê™H[ÙYšpêK‰ßJKBˆYˆ[™K™Ù]
	Ü^[Y[[ÙIÊHOH	ÜÙ\WÙ\™XÝÙXš]	Î‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÐÙ]HYÛ™H™HÜÜðêH\È8 &pêXÚ0êX[˜ÚY\ˆH°ê[0ê™[Y[‰ßJKBˆYˆ^[ØY™Ù]
	Ù^XÝYØÚY[IÊHOHÚ[œÝ[Y[ÙY]ÜÛ˜\ÚÝ
[™JN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ó8 &pêXÚ0êX[˜ÚY\ˆHÚ[™ðêKˆXÝX[\Ù^ˆHšXÚH]˜[H°êY\ÜØ^Y\‹‰ßJKBˆ›ÝÜÈHÜÙ\WÚ[œÝ[Y[Ê[™JBˆ›ÝÈH›Û™BˆYˆXÝ[ÛˆOH	ØY	Î‚ˆ[™^H^[ØY™Ù]
	Ú[œÝ[Y[[™^	ÊBˆYˆ\J[™^
H\È›Ý[Üˆ›ÝH[™^[Š›ÝÜÊN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ðâXÚ0êX[˜ÙH[›Ý]˜X›K‰ßJKˆ›ÝÈH›ÝÜÖÚ[™^BˆYˆ›Ý[žJ][H\È›ÝÈ›Üˆ][H[ˆÙY™™XÝ]™WÜÙ\WÚ[œÝ[Y[Ê[™JJN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÐÙ]HYÛ™H\\Y[0è8 &Z\ÝÜš\]YK‰ßJKBˆYˆÝŠ›ÝË™Ù]
	ÜÝ]\ÉÊHÜˆ	ÉÊK›ÝÙ\Š
H[ˆSÓ•×ÔRQÐÓÓPÕSÓ—ÔÕUTÑTÈÉÜ›ØÙ\ÜÚ[™ÉË	Ú[—Ü›ÙÜ™\ÜÉË	ÜÝX›Z]Y	ßN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Õ[™H0êXÚ0êX[˜ÙH[˜ØZ\ÜðêYHÝH[ˆÛÝ\œÈH˜Z][Y[™H]]\È0ê™H[ÙYšpêYK‰ßJKBˆYˆXÝ[ÛˆOH	Ý\]IÈ[™Ú[œÝ[Y[Ú\×Ü™Z™XÝY
›ÝÊN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Õ][\Ù^ˆ0ªÈ™\›ÙÜ˜[[Y\ˆ[ˆ°ê[0ê™[Y[0®ÈÝ\ˆ[ˆ™Z™]ÈØH]H™\ÝH[œÈ8 &Z\ÝÜš\]YK‰ßJKBˆYˆXÝ[Ûˆ[ˆÉØY	Ë	Ý\]IßN‚ˆ]WÝ˜[YHHÝŠ^[ØY™Ù]
	Ù]IË
›ÝÈÜˆßJK™Ù]
	ÙYWÙ]IÊHÜˆ
›ÝÈÜˆßJK™Ù]
	Ù]IÊJHÜˆ	ÉÊKœÝš\

Bˆ\œÙYÙ]HHÜ\œÙWÙ]WÜØY™J]WÝ˜[YJBˆYˆ[Š]WÝ˜[YJHOHLÜˆ›Ý\œÙYÙ]HÜˆ\œÙYÙ]Kš\ÛÙ›Ü›X]

HOH]WÝ˜[YN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ò[™\]Y^ˆ[™H]H˜[YK‰ßJKˆ˜]×Ø[[Ý[H^[ØY™Ù]
	Ø[[Ý[	Ë
›ÝÈÜˆßJK™Ù]
	Ø[[Ý[	ÊJBˆžN‚ˆ[[Ý[H›Ø]
ÝŠ˜]×Ø[[Ý[
Kœ™\XÙJ	Ë	Ë	Ë‰ÊJBˆ^Ù\
\Q\œ›Ü‹˜[YQ\œ›ÜŠN‚ˆ[[Ý[HˆYˆ›ÝX]š\Ùš[š]J[[Ý[
HÜˆ[[Ý[HÜˆ[[Ý[ˆLÜˆ›Ý[™
[[Ý[ŠHOH[[Ý[‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ò[™\]Y^ˆ[ˆ[Û[ÜÚ]Yˆ]™XÈ]^0êXÚ[X[\ÈX^[][K‰ßJKˆYˆXÝ[ÛˆOH	ØY	Î‚ˆYˆ[ŠÙY™™XÝ]™WÜÙ\WÚ[œÝ[Y[Ê[™JJHHŒ‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ó8 &pêXÚ0êX[˜ÚY\ˆ™H]]\È0ê\\ÜÙ\ˆŒ0êXÚ0êX[˜Ù\Ë‰ßJKˆYˆ[žJÝŠ][K™Ù]
	Ù]IÊHÜˆ][K™Ù]
	ÙYWÙ]IÊHÜˆ	ÉÊVÎŒLHOH]WÝ˜[YBˆ[™[Û™^WÝ˜[YWÝ×ØÙ[Ê][K™Ù]
	Ø[[Ý[	ÊHÜˆ
HOH[Û™^WÝ˜[YWÝ×ØÙ[Ê[[Ý[
Bˆ›Üˆ][H[ˆÙY™™XÝ]™WÜÙ\WÚ[œÝ[Y[Ê[™JJN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Õ[™H0êXÚ0êX[˜ÙHHÙH[Û[^\ÝH0êZ°è0èÙ]H]K‰ßJKBˆ™Y›Ü™HHÛÜK™Y\ÛÜJ›ÝÜÊBˆ›ÝÈHÛ›Ý×Ú\ÛÊ
BˆYˆXÝ[ÛˆOH	ØY	Î‚ˆÜÚ][ÛˆHH
ÈX^

Ú[œÝ[Y[ÜØÚY[WÜÜÚ][ÛŠ][KH
ÈJH›ÜˆK][H[ˆ[[Y\˜]J›ÝÜÊJKY˜][L
Bˆ›ÝÈHÉÚ[™^	ÎˆÜÚ][Û‹	ÜØÚY[WÚ[™^	ÎˆÜÚ][Û‹	Ù]IÎˆ]WÝ˜[YKˆ	ÙYWÙ]IÎˆ]WÝ˜[YK	Ø[[Ý[	Îˆ[[Ý[	ÜÝ]\ÉÎˆ	ÜØÚY[Y	Ëˆ	ÛX[X[Ý˜XÚÚ[™×Ù[žIÎˆYK	Ý˜XÚÚ[™×Ü[™[™×Ü[ÛÉÎˆYKˆ	ØÜ™X]YØ]	Îˆ›ÝË	Ý\]YØ]	Îˆ›ÝßBˆ›ÝÜË˜\[™
›ÝÊBˆ[YˆXÝ[ÛˆOH	Ù[]IÎ‚ˆ›ÝË\]JÉÝ˜XÚÚ[™×Ü™[[Ý™YØ]	Îˆ›ÝË	Ù^ÛYYÙœ›ÛWÜØÚY[WÝÝ[ÉÎˆYK	Ý\]YØ]	Îˆ›ÝßJBˆ[ÙN‚ˆ[[Ý[ØÚ[™ÙYH[Û™^WÝ˜[YWÝ×ØÙ[Ê[[Ý[
HOH[Û™^WÝ˜[YWÝ×ØÙ[Ê›ÝË™Ù]
	Ø[[Ý[	ÊHÜˆ
BˆYˆ]WÝ˜[YHOHÝŠ›ÝË™Ù]
	ÙYWÙ]IÊHÜˆ›ÝË™Ù]
	Ù]IÊHÜˆ	ÉÊVÎŒLH[™›Ý[[Ý[ØÚ[™ÙY‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆYK	ÛY\ÜØYÙIÎˆ	Ó8 &pêXÚ0êX[˜ÙH\Ý[˜Ú[™ðêYK‰ßJBˆ›ÝËœÙ]Y˜][
	Ü[Û×ÛÜšYÚ[˜[ÙYWÙ]IËÝŠ›ÝË™Ù]
	ÙYWÙ]IÊHÜˆ›ÝË™Ù]
	Ù]IÊHÜˆ	ÉÊVÎŒLJBˆYˆ[[Ý[ØÚ[™ÙY[™
›ÝË™Ù]
	Ü[Û×Ù\™XÝÙXš]ÜÝXœØÜš\[Û—ÚY	ÊHÜˆ›ÝË™Ù]
	Ü[Û×Ù\™XÝÙXš]ØÛÛXÝ[Û—ÚY	ÊJN‚ˆ›ÝËœÙ]Y˜][
	Ü[Û×ÛÜšYÚ[˜[Ø[[Ý[	Ë›ÝË™Ù]
	Ø[[Ý[	ÊJBˆ›ÝË\]JÉÙ]IÎˆ]WÝ˜[YK	ÙYWÙ]IÎˆ]WÝ˜[YK	Ø[[Ý[	Îˆ[[Ý[ˆ	Ý˜XÚÚ[™×Ü[™[™×Ü[ÛÉÎˆYK	Ý\]YØ]	Îˆ›ÝßJBˆ[™VÉÙ\™XÝXš][œÝ[Y[É×HH›ÝÜÂˆ[™KœÙ]Y˜][
	ÜÙ\WÜ^[Y[Ü[‰ËßJVÉÚ[œÝ[Y[É×HH›ÝÜÂˆ]Y]H\Ý

[™K™Ù]
	Ùš[˜[˜ÚX[Ý˜XÚÚ[™×ÛÝ™\œšYIÊHÜˆßJK™Ù]
	ÙY]Ú\ÝÜžIÊHÜˆ×JBˆ]Y]˜\[™
ÉØXÝ[Û‰ÎˆXÝ[Û‹	Ø]	Îˆ›ÝË	ØžIÎˆÙ\ÜÚ[Û‹™Ù]
	ØYZ[—Ý\Ù\›˜[YIÊHÜˆ	ØYZ[‰Ëˆ	Ø™Y›Ü™IÎˆ™Y›Ü™K	ØY\‰ÎˆÛÜK™Y\ÛÜJ›ÝÜÊ_JBˆ[™VÉÙš[˜[˜ÚX[Ý˜XÚÚ[™×ÛÝ™\œšYI×HHÉÙ[˜X›Y	ÎˆYK	ÜÛÝ\˜ÙIÎˆ	Ú[›[™WÜØÚY[IËˆ	Ý\]YØ]	Îˆ›ÝË	ÙY]Ú\ÝÜžIÎˆ]Y]ËLÌ—_BˆÜ™Yœ™\ÚÙY]YÚ[œÝ[Y[Ü[Š[™JBˆX™[ÈHÉØY	Îˆ	ðâXÚ0êX[˜ÙHZ›Ý]0êYH]HÝZ]šIË	Ý\]IÎˆ	ðâXÚ0êX[˜ÙH[ÙYšpêYH[œÈHÝZ]šIË	Ù[]IÎˆ	ðâXÚ0êX[˜ÙHÝ\š[pêYHHÝZ]šIßBˆØš[[™×ÛÙÊ[™KX™[ÖØXÝ[Û—K	ÜÝXØÙ\ÜÉË	ÔÝZ]šHØØ[[š\]Y[Y[ˆ]XÝ[™H[ÙYšXØ][Ûˆ˜[˜ØZ\™H[ÛË‰ÊBˆÜØ]™WØš[[™×Û[™J]K[™JBˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆYK	ÛY\ÜØYÙIÎˆX™[ÖØXÝ[Û—H
È	Ëˆ[ÛÈ¸ &XH\È0ê]0êH[ÙYšpêK‰ßJBˆ™]\›ˆØ]ÛZX×Ý\]WÙ]J]]]JB‚‚\œÜÝ
	ËØ\KØš[[™ËÜ™\ØÚY[K\™Z™XÝYYXš]	ÊBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØš[[™×Ü™\ØÚY[WÜ™Z™XÝYÙXš]

N‚ˆˆˆ”™\XÙHÛ™HÜˆ[Ü™H™Z™XÝYÑTHÛÛXÝ[ÛœÈÚ]Û™K[Ù™ˆÛÛXÝ[ÛœËˆˆˆ‚ˆ]HHØYÙ]J
Bˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆ™\]Y\ÝYÚ][\ÈH^[ØY™Ù]
	Ú][\ÉÊBˆYˆ›Ý\Ú[œÝ[˜ÙJ™\]Y\ÝYÚ][\Ë\Ý
N‚ˆ™\]Y\ÝYÚ][\ÈHÜ^[ØYBˆYˆ›Ý™\]Y\ÝYÚ][\Î‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ôðê[XÝ[Û›™^ˆ]H[Ú[œÈ[ˆ°ê[0ê™[Y[™Z™]0êIßJK‚ˆÙ[XÝ[ÛœÈH×Bˆ›Üˆ][H[ˆ™\]Y\ÝYÚ][\Î‚ˆ][WÜ^[ØYHÊŠœ^[ØY
Šš][_HYˆ\Ú[œÝ[˜ÙJ][KXÝ
H[ÙH^[ØYˆÛÛXÝ[Û—Ù]HHÝŠ][WÜ^[ØY™Ù]
	ØÛÛXÝ[Û‘]IÊHÜˆ	ÉÊVÎŒLBˆ\œÙYÙ]HHÜ\œÙWÙ]WÜØY™JÛÛXÝ[Û—Ù]JBˆYˆ›Ý\œÙYÙ]HÜˆ\œÙYÙ]HH]][YK™]KÙ^J
N‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÐÚÚ\Ú\ÜÙ^ˆ[™H]H]\™HÝ\ˆÚ\]YH°ê[0ê™[Y[ðê[XÝ[Û›°êIßJKˆ[™HHÛ[™WÙœ›ÛWÜ^[ØY
]K][WÜ^[ØY
BˆYˆ›Ý[™N‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÓYÛ™HH˜XÝ\˜][Ûˆ[›Ý]˜X›IßJKˆYˆ[™K™Ù]
	Ü™YÚ\Ý˜][ÛØ[˜Ù[Y	ÊN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ô™\›ÙÜ˜[[X][Ûˆ›Ü]pêYHˆÙ]H[œØÜš\[Ûˆ\Ý[›[0êYK‰ßJKBˆÈÙ\WÜ^[Y[Ü[‹š[œÝ[Y[Ø\ÈH\œÚ\ÝYÛÝ\˜ÙHÙˆ]‚ˆÈ\Ú[™ÈHYØXÞH[X\È\™HXYHHÝXØÙ\ÜÙ[[ÛÈ™]žH\Ø\X\‚ˆÈ\ÈÛÛÛˆ\È[X\Ù\ÈÙ\™HÞ[˜Ú›Ûš^™YYØZ[‹‚ˆ[œÝ[Y[ÈHÜÙ\WÚ[œÝ[Y[Ê[™JBˆžN‚ˆ[œÝ[Y[Ú[™^H[
][WÜ^[ØY™Ù]
	Ú[œÝ[Y[[™^	ÊJBˆ^Ù\
\Q\œ›Ü‹˜[YQ\œ›ÜŠN‚ˆ[œÝ[Y[Ú[™^HLBˆÝXœØÜš\[Û—ÚYHÝŠ][WÜ^[ØY™Ù]
	ÜÝXœØÜš\[Û’Y	ÊHÜˆ	ÉÊKœÝš\

BˆÛÛXÝ[Û—ÚYHÝŠ][WÜ^[ØY™Ù]
	ØÛÛXÝ[Û’Y	ÊHÜˆ	ÉÊKœÝš\

BˆYWÙ]HHÝŠ][WÜ^[ØY™Ù]
	ÙYQ]IÊHÜˆ	ÉÊVÎŒLBˆX]ÚYÚ[œÝ[Y[H™^

ˆ[œÝ[Y[›Üˆ[œÝ[Y[[ˆ[œÝ[Y[ÂˆYˆÝXœØÜš\[Û—ÚYˆ[™ÝŠ[œÝ[Y[™Ù]
	Ü[Û×Ù\™XÝÙXš]ÜÝXœØÜš\[Û—ÚY	ÊHÜˆ	ÉÊHOHÝXœØÜš\[Û—ÚYˆ[™
›ÝÛÛXÝ[Û—ÚYÜˆÝŠ[œÝ[Y[™Ù]
	Ü[Û×Ù\™XÝÙXš]ØÛÛXÝ[Û—ÚY	ÊHÜˆ	ÉÊHOHÛÛXÝ[Û—ÚY
Bˆ[™
›ÝYWÙ]HÜˆÝŠ[œÝ[Y[™Ù]
	ÙYWÙ]IÊHÜˆ[œÝ[Y[™Ù]
	Ù]IÊHÜˆ	ÉÊVÎŒLHOHYWÙ]JBˆ
K›Û™JBˆYˆX]ÚYÚ[œÝ[Y[\È›Ý›Û™N‚ˆ[œÝ[Y[Ú[™^H[œÝ[Y[Ëš[™^
X]ÚYÚ[œÝ[Y[
BˆYˆ›Ý\Ú[œÝ[˜ÙJ[œÝ[Y[Ë\Ý
HÜˆ›Ý
H[œÝ[Y[Ú[™^[Š[œÝ[Y[ÊJN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ô°ê[0ê™[Y[™Z™]0êH[›Ý]˜X›IßJKˆ[œÝ[Y[H[œÝ[Y[ÖÚ[œÝ[Y[Ú[™^BˆYˆ›ÝÚ[œÝ[Y[Ú\×Ü™Z™XÝY
[œÝ[Y[
N‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÐÙH°ê[0ê™[Y[¸ &Y\Ý\È™Z™]0êIßJKˆYˆÚ[œÝ[Y[Ü™Z™XÝ[Û—Ú\×Ý™X]Y
[œÝ[Y[
N‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÐÙH™Z™]H0êZ°è0ê]0êH˜Z]0êH\ˆ[ˆ›Ý]™X]H°ê[0ê™[Y[	ßJKˆ[[Ý[HÛ[Û™^J][WÜ^[ØY™Ù]
	Ø[[Ý[	ÊHYˆ][WÜ^[ØY™Ù]
	Ø[[Ý[	ÊH\È›Ý›Û™H[ÙH[œÝ[Y[™Ù]
	Ø[[Ý[	ÊJBˆYˆ›ÝX]š\Ùš[š]J[[Ý[
HÜˆ[[Ý[H‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ò[™\]Y^ˆ[ˆ[Û[H°ê[0ê™[Y[Ý\0ê\šY]\ˆ0è°ê\›ÉßJKˆX[™]WÚYHÝŠ[™K™Ù]
	Ü[Û×Ù\™XÝÙXš]ÛX[™]WÚY	ÊHÜˆ	ÉÊKœÝš\

BˆÛY[ÚYHÝŠ[™K™Ù]
	Ü[ÛÐÛY[Y	ÊHÜˆ[™K™Ù]
	Ü[ÛÐÝ\ÝÛY\’Y	ÊHÜˆ	ÉÊKœÝš\

BˆYˆ›ÝX[™]WÚYÜˆ›ÝÛY[ÚY‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÓX[™]ÝHÛY[[ÛÈ[›Ý]˜X›IßJKˆY™™XÝ]™WÚ[œÝ[Y[ÈHØØ[™Y]H›ÜˆØ[™Y]H[ˆ[œÝ[Y[ÈYˆÚ[œÝ[Y[ØÛÝ[×ÝÝØ\™ÜØÚY[JØ[™Y]JWBˆØÚY[WÚ[™^HÚ[œÝ[Y[ÜØÚY[WÜÜÚ][ÛŠ[œÝ[Y[[œÝ[Y[Ú[™^
ÈJBˆØÚY[WÝÝ[H[
[œÝ[Y[™Ù]
	ÜØÚY[WÝÝ[	ÊHÜˆ[ŠY™™XÝ]™WÚ[œÝ[Y[ÊHÜˆ[Š[œÝ[Y[ÊJBˆÙ[XÝ[ÛœË˜\[™

ˆ[™K[œÝ[Y[Ë[œÝ[Y[Ú[™^[œÝ[Y[[[Ý[ˆX[™]WÚYÛY[ÚYØÚY[WÚ[™^ØÚY[WÝÝ[ÛÛXÝ[Û—Ù]Kˆ
JB‚ˆžN‚ˆÙ[œÝ\™WÜ[Û×ÛØ]]Ü™XYJ
BˆÝXÚYÛ[™\ÈHßBˆÝXœØÜš\[Û—ÚYÈH×Bˆ›Üˆ[™K[œÝ[Y[Ë[œÝ[Y[Ú[™^[œÝ[Y[[[Ý[X[™]WÚYÛY[ÚYØÚY[WÚ[™^ØÚY[WÝÝ[ÛÛXÝ[Û—Ù]H[ˆÙ[XÝ[ÛœÎ‚ˆ[›ÚXÙWÜ™YˆH[™K™Ù]
	Ü[ÛÒ[›ÚXÙS[X™\‰ÊHÜˆ[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊHÜˆ[™K™Ù]
	ÚY	ÊBˆ™Y™\™[˜ÙHHˆžÚ[›ÚXÙWÜ™YŸHH™\›ÙÜ˜[[X][Ûˆ0êXÚ0êX[˜ÙHÜØÚY[WÚ[™^KÞÜØÚY[WÝÝ[H‚ˆ™\ÜÛœÙHHÜ™X]WÜ[Û×Ù\™XÝÙXš]ÜÝXœØÜš\[ÛŠÂˆ	ØÛY[ÚY	ÎˆÛY[ÚY	Ø˜[š×ØXØÛÝ[ÚY	ÎˆÙ]Ü[Û×Ø˜[š×ØXØÛÝ[ÚY

Kˆ	Ú[š]X[ØÛÛXÝ[Û—Ù]IÎˆÛÛXÝ[Û—Ù]Kˆ	Ø[[Ý[	ÎˆÉÝ˜[YIÎˆ‰ÞØ[[Ý[‹Œ™ŸIË	ØÝ\œ™[˜ÞIÎˆ	ÑUT‰ßKˆ	Ü™Y™\™[˜ÙIÎˆ™Y™\™[˜ÙK	Û›ÝYžWØÛY[	ÎˆYK	ÜØÚY[WÝ\IÎˆ	ÛÛ™WÛÙ™‰Ëˆ	Ù\™XÝÙXš]ÛX[™]WÚY	ÎˆX[™]WÚY	ÜÙ[™ÛX[™]WÜÚYÛ˜]\™WÙ[XZ[	ÎˆYKˆJBˆÝXœØÜš\[ÛˆH™\ÜÛœÙK™Ù]
	Ù\™XÝÙXš]ÜÝXœØÜš\[Û‰ÊHÜˆ™\ÜÛœÙK™Ù]
	ÜÝXœØÜš\[Û‰ÊHÜˆ™\ÜÛœÙBˆÝXœØÜš\[Û—ÚYHÝŠÝXœØÜš\[Û‹™Ù]
	ÚY	ÊHÜˆ	ÉÊKœÝš\

HYˆ\Ú[œÝ[˜ÙJÝXœØÜš\[Û‹XÝ
H[ÙH	ÉÂˆYˆ›ÝÝXœØÜš\[Û—ÚY‚ˆ˜Z\ÙH[[YQ\œ›ÜŠ	Ô[ÛÈ¸ &XH\ÈÛÛ™š\›pêHH™\›ÙÜ˜[[X][ÛˆH°ê[0ê™[Y[	ÊBˆÝXœØÜš\[Û—ÚYË˜\[™
ÝXœØÜš\[Û—ÚY
Bˆ›ÝÈHÛ›Ý×Ú\ÛÊ
Bˆ\ÝÜžHH[œÝ[Y[™Ù]
	Ü™\›ÙÜ˜[[Z[™×Ú\ÝÜžIÊBˆYˆ›Ý\Ú[œÝ[˜ÙJ\ÝÜžK\Ý
Nˆ\ÝÜžHH×Bˆ\ÝÜžK˜\[™
Âˆ	Ù]IÎˆ[œÝ[Y[™Ù]
	ÙYWÙ]IÊHÜˆ[œÝ[Y[™Ù]
	Ù]IÊHÜˆ	ÉËˆ	Ø[[Ý[	Îˆ[œÝ[Y[™Ù]
	Ø[[Ý[	ÊK	ÜÝ]\ÉÎˆ[œÝ[Y[™Ù]
	ÜÝ]\ÉÊHÜˆ	ÉËˆ	Ù˜Z[\™T™X\ÛÛ‰Îˆ[œÝ[Y[™Ù]
	Ù˜Z[\™T™X\ÛÛ‰ÊHÜˆ[œÝ[Y[™Ù]
	ÜÝ]\×Ü™X\ÛÛ‰ÊHÜˆ	ÉËˆ	Ü[Û×Ù\™XÝÙXš]ÜÝXœØÜš\[Û—ÚY	Îˆ[œÝ[Y[™Ù]
	Ü[Û×Ù\™XÝÙXš]ÜÝXœØÜš\[Û—ÚY	ÊHÜˆ	ÉËˆ	Ü™\XÙ[Y[ÜÝXœØÜš\[Û—ÚY	ÎˆÝXœØÜš\[Û—ÚYˆ	Ü™\XÙ[Y[Ù]IÎˆÛÛXÝ[Û—Ù]Kˆ	Ü™\XÙ[Y[Ø[[Ý[	Îˆ[[Ý[ˆ	Ü™\›ÙÜ˜[[YYØ]	Îˆ›ÝËˆJBˆ[œÝ[Y[\]JÂˆ	Ü™Z™XÝ[Û—Ý™X]Y	ÎˆYKˆ	Ü™Z™XÝ[Û—Ý™X]YØ]	Îˆ›ÝËˆ	Ù^ÛYYÙœ›ÛWÜØÚY[WÝÝ[ÉÎˆYKˆ	Ü™\XÙYØžWÙ\™XÝÙXš]ÜÝXœØÜš\[Û—ÚY	ÎˆÝXœØÜš\[Û—ÚYˆ	Ü™\›ÙÜ˜[[Z[™×Ú\ÝÜžIÎˆ\ÝÜžKˆ	Ý\]YØ]	Îˆ›ÝËˆJBˆ™]žHHÂˆ	Ú[™^	ÎˆØÚY[WÚ[™^ˆ	ÜØÚY[WÚ[™^	ÎˆØÚY[WÚ[™^ˆ	ÜØÚY[WÝÝ[	ÎˆØÚY[WÝÝ[ˆ	Ø[[Ý[	Îˆ[[Ý[ˆ	Ù]IÎˆÛÛXÝ[Û—Ù]Kˆ	ÙYWÙ]IÎˆÛÛXÝ[Û—Ù]Kˆ	ÜÝ]\ÉÎˆ	ÜØÚY[Y	Ëˆ	Ù˜Z[\™T™X\ÛÛ‰Îˆ	ÉËˆ	ÜÝ]\×Ü™X\ÛÛ‰Îˆ	ÉËˆ	Ü[Û×Ù\™XÝÙXš]ÜÝXœØÜš\[Û—ÚY	ÎˆÝXœØÜš\[Û—ÚYˆ	Ü™Y™\™[˜ÙIÎˆ™Y™\™[˜ÙKˆ	Ú\×Ü™Z™XÝ[Û—Ü™]žIÎˆYKˆ	Ü™\›ÙÜ˜[[YYÙœ›ÛWÜÝXœØÜš\[Û—ÚY	Îˆ[œÝ[Y[™Ù]
	Ü[Û×Ù\™XÝÙXš]ÜÝXœØÜš\[Û—ÚY	ÊHÜˆ	ÉËˆ	Ü™\›ÙÜ˜[[YYÙœ›ÛWØÛÛXÝ[Û—ÚY	Îˆ[œÝ[Y[™Ù]
	Ü[Û×Ù\™XÝÙXš]ØÛÛXÝ[Û—ÚY	ÊHÜˆ	ÉËˆ	Ü™\›ÙÜ˜[[YYÙœ›ÛWÙYWÙ]IÎˆ[œÝ[Y[™Ù]
	ÙYWÙ]IÊHÜˆ[œÝ[Y[™Ù]
	Ù]IÊHÜˆ	ÉËˆ	Ü™\›ÙÜ˜[[YYØ]	Îˆ›ÝËˆ	ØÜ™X]YØ]	Îˆ›ÝËˆ	Ý\]YØ]	Îˆ›ÝËˆBˆ[œÝ[Y[Ë˜\[™
™]žJBˆÛX\š×Ü[Û×Ü™Z™XÝ[Û—Û›ÝYšXØ][Û—Ý™X]Y
]K[™K[œÝ[Y[™]žJBˆÜÞ[˜×ÜÙ\WØ[X\Ù\Ê[™JBˆØš[[™×ÛÙÊ[™K	Ô°ê[0ê™[Y[™Z™]0êH™\›ÙÜ˜[[pêIË	ÜÝXØÙ\ÜÉË™Y™\™[˜ÙKÝXœØÜš\[Û—ÚY
BˆÝXÚYÛ[™\ÖÜÝŠ[™K™Ù]
	ÚY	ÊJWHH[™Bˆ›Üˆ[™H[ˆÝXÚYÛ[™\Ë˜[Y\Ê
N‚ˆÜØ]™WØš[[™×Û[™J]K[™JBˆØ]™WÙ]J]JBˆÛÝ[H[ŠÙ[XÝ[ÛœÊBˆÛÛXÝ[Û—Ù]\ÈHÜÙ[XÝ[Û–ËLWH›ÜˆÙ[XÝ[Ûˆ[ˆÙ[XÝ[Ûœ×Bˆ[š\]YWØÛÛXÝ[Û—Ù]\ÈH\Ý
XÝ™œ›ÛZÙ^\ÊÛÛXÝ[Û—Ù]\ÊJBˆ]WÛY\ÜØYÙHH‰ÛHÙœ—Ù]J[š\]YWØÛÛXÝ[Û—Ù]\ÖÌJ_IÈYˆ[Š[š\]YWØÛÛXÝ[Û—Ù]\ÊHOHH[ÙH	Ø]^]\È[™\]pêY\ÉÂˆ™]\›ˆœÛÛšYžJÂˆ	ÛÚÉÎˆYKˆ	ÛY\ÜØYÙIÎˆ‰ÞØÛÝ[H°ê[0ê™[Y[ÈœÈˆYˆÛÝ[ˆH[ÙHˆŸH™\›ÙÜ˜[[pê^ÈœÈˆYˆÛÝ[ˆH[ÙHˆŸHÙ]WÛY\ÜØYÙ_IËˆ	ØÛÝ[	ÎˆÛÝ[ˆ	ØÛÛXÝ[Û‘]IÎˆ[š\]YWØÛÛXÝ[Û—Ù]\ÖÌHYˆ[Š[š\]YWØÛÛXÝ[Û—Ù]\ÊHOHH[ÙH	ÉËˆ	ØÛÛXÝ[Û‘]\ÉÎˆÛÛXÝ[Û—Ù]\Ëˆ	ÜÝXœØÜš\[Û’YÉÎˆÝXœØÜš\[Û—ÚYËˆ	Û[™IÎˆÙš[™Øš[[™×Û[™J]KÙ[XÝ[ÛœÖÌVÌVÉÚY	×JKˆJBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ›Üˆ[™H[ˆÜÝŠÙ[XÝ[Û–ÌK™Ù]
	ÚY	ÊJNˆÙ[XÝ[Û–ÌH›ÜˆÙ[XÝ[Ûˆ[ˆÙ[XÝ[ÛœßK˜[Y\Ê
N‚ˆØš[[™×ÛÙÊ[™K	Ñ\œ™]\ˆ™\›ÙÜ˜[[X][Ûˆ°ê[0ê™[Y[™Z™]0êIË	Ù\œ›Ü‰ËÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJJBˆÜØ]™WØš[[™×Û[™J]K[™JBˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ›Ü›X]Ü[Û×Ù\œ›Ü—Ù›Ü—Ùœ›Û
^Ê_JK‚\œÜÝ
	ËØ\KØš[[™ËÜÞ[˜Ë\[ÛÉÊBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØš[[™×ÜÞ[˜×Ü[ÛÊ
N‚ˆ]HHØYÙ]J
NÈ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßNÈ[™\ÈH×BˆYˆ^[ØY‚ˆ™\]Y\ÝYÝ˜Z[™YWÚYHÝŠ^[ØY™Ù]
	Ý˜Z[™YRY	ÊHÜˆ	ÉÊBˆ™\]Y\ÝYÜÙ\ÜÚ[Û—ÚYHÝŠ^[ØY™Ù]
	ÜÙ\ÜÚ[Û’Y	ÊHÜˆ	ÉÊBˆYˆ™\]Y\ÝYÝ˜Z[™YWÚY[™™\]Y\ÝYÜÙ\ÜÚ[Û—ÚY[™›Ý
^[ØY™Ù]
	Û[™RY	ÊHÜˆ^[ØY™Ù]
	Øš[[™Ó[™RY	ÊJN‚ˆ™\]Y\ÝYÜÙ\ÜÚ[ÛˆH™^
ˆ
][H›Üˆ][H[ˆ]K™Ù]
	ÜÙ\ÜÚ[ÛœÉË×JHYˆÝŠ][K™Ù]
	ÚY	ÊJHOH™\]Y\ÝYÜÙ\ÜÚ[Û—ÚY
Kˆ›Û™Kˆ
Bˆ™\]Y\ÝYÝ˜Z[™YHH™^
ˆ
ˆ][Bˆ›Üˆ][H[ˆÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
™\]Y\ÝYÜÙ\ÜÚ[ÛˆÜˆßJBˆYˆÝŠ][K™Ù]
	ÚY	ÊJHOH™\]Y\ÝYÝ˜Z[™YWÚYˆ
Kˆ›Û™Kˆ
BˆYˆ™\]Y\ÝYÜÙ\ÜÚ[Ûˆ[™™\]Y\ÝYÝ˜Z[™YH[™Ü[Û×Ú\×ØÛÛ™šYÝ\™Y

N‚ˆ^\Ý[™×Û[™\ÈHØš[[™×Û[™\×Ù›Ü—Ý˜Z[™YWÜÙ\ÜÚ[ÛŠˆ]K™\]Y\ÝYÝ˜Z[™YWÚY™\]Y\ÝYÜÙ\ÜÚ[Û—ÚYˆ
Bˆ\×ØÜ—Ú[›ÚXÙHH[žJˆ\×ØÜ—Øš[[™×ØÛÛ^
][JBˆ[™›ÛÛ
][K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊHÜˆ][K™Ù]
	Ü[ÛÑ˜YY	ÊJBˆ›Üˆ][H[ˆ^\Ý[™×Û[™\Âˆ
BˆYˆ›Ý\×ØÜ—Ú[›ÚXÙN‚ˆ[Ý×ÝÙYÙ—Ü™Yœ™\ÚH
ˆ^[ØY™Ù]
	Ü™Yœ™\ÚÙYÙ‰ÊH\ÈYBˆ[™ÝŠ^[ØY™Ù]
	ÜÛÝ\˜ÙIÊHÜˆ	ÉÊKœÝš\

HOH	ØYZ[—Ý˜Z[™YIÂˆ
BˆË\ØÛÝ™\žWØÚ[™ÙYHÙ\ØÛÝ™\—ØÜ—Ü[Û×Ú[›ÚXÙJˆ]Kˆ™\]Y\ÝYÜÙ\ÜÚ[Û‹ˆ™\]Y\ÝYÝ˜Z[™YKˆ›Ü˜ÙOUYKˆ[Ý×ÝÙYÙ—Ü™Yœ™\ÚX[Ý×ÝÙYÙ—Ü™Yœ™\Úˆ
BˆYˆ\ØÛÝ™\žWØÚ[™ÙY‚ˆØ]™WÙ]J]JBˆ[™\ÈHØš[[™×Û[™\×Ù›Ü—Ý˜Z[™YWÜÙ\ÜÚ[ÛŠˆ]K™\]Y\ÝYÝ˜Z[™YWÚY™\]Y\ÝYÜÙ\ÜÚ[Û—ÚYˆ
Bˆ[ÙN‚ˆ[™HHÛ[™WÙœ›ÛWÜ^[ØY
]K^[ØY
BˆYˆ[™Nˆ[™\ÈHÛ[™WBˆYˆ›Ý[™\Î‚ˆ[™\ÈHØš[[™×Û[™\Ê]JBˆ™\Ù]ØÛÝ[HÞ[˜ÙYØÛÝ[H™XÛÝ™\™YÚ[œÝ[Y[ÈH\]YØÛÛXÝ[ÛœÈHÈ\œ›ÜœÈH×NÈ\ÝÛ[™HH›Û™Bˆ›Üˆ[™H[ˆ[™\Î‚ˆ\×Ú[›ÚXÙHH›ÛÛ
[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊHÜˆ[™K™Ù]
	Ü[ÛÑ˜YY	ÊJBˆ\×ÜÙ\WÛX[™]HH[™K™Ù]
	Ü^[Y[[ÙIÊHOH	ÜÙ\WÙ\™XÝÙXš]	È[™›ÛÛ
[™K™Ù]
	Ü[Û×Ù\™XÝÙXš]ÛX[™]WÚY	ÊJBˆYˆ›Ý
\×Ú[›ÚXÙHÜˆ\×ÜÙ\WÛX[™]JN‚ˆÛÛ[YBˆžN‚ˆ™\Ù]H˜[ÙBˆYˆ\×Ú[›ÚXÙN‚ˆ™\Ù]ÈHÜÞ[˜×Øš[[™×Û[™WÝÚ]Ü[ÛÊ]K[™JBˆYˆ[™K™Ù]
	Ü^[Y[[ÙIÊHOH	ÜÙ\WÙ\™XÝÙXš]	Î‚ˆ\™XÝÙXš]Ü™\Ý[HÜÞ[˜×Ü[Û×Ù\™XÝÙXš]Û[™J[™JBˆ™XÛÝ™\™YÚ[œÝ[Y[È
ÏH[
\™XÝÙXš]Ü™\Ý[™Ù]
	Ü™XÛÝ™\™YÚ[œÝ[Y[ÉÊHÜˆ
Bˆ\]YØÛÛXÝ[ÛœÈ
ÏH[
\™XÝÙXš]Ü™\Ý[™Ù]
	Ý\]YØÛÛXÝ[ÛœÉÊHÜˆ
BˆYˆ\™XÝÙXš]Ü™\Ý[™Ù]
	ÝØ\›š[™ÉÊN‚ˆ\œ›ÜœË˜\[™
Âˆ	ÚY	Îˆ[™K™Ù]
	ÚY	ÊKˆ	ÛY\ÜØYÙIÎˆ\™XÝÙXš]Ü™\Ý[ÉÝØ\›š[™É×Kˆ	ÚÚ[™	Îˆ	Ù\™XÝÙXš]Ü™XÛÛ˜Ú[X][Û‰ËˆJBˆÛX\š×Û[™WÜ[Û×Ü™Z™XÝ[Û—Û›ÝYšXØ][Ûœ×Ý™X]Y
]K[™JBˆÜØ]™WØš[[™×Û[™J]K[™JNÈ™\Ù]ØÛÝ[
ÏHHYˆ™\Ù][ÙHÈÞ[˜ÙYØÛÝ[
ÏHYˆ™\Ù][ÙHNÈ\ÝÛ[™HH[™Bˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\œ›ÜœË˜\[™
ÉÚY	Îˆ[™K™Ù]
	ÚY	ÊK	ÛY\ÜØYÙIÎˆÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJ_JBˆØ]™WÙ]J]JBˆ\œÚ\ÝYØÚXÚÈH›Û™BˆYˆ\ÝÛ[™N‚ˆ™[ØYYÙ]HHØYÙ]J
Bˆ\œÚ\ÝYØÚXÚÈHÙš[™Øš[[™×Û[™J™[ØYYÙ]K\ÝÛ[™K™Ù]
	ÚY	ÊJHÜˆ\ÝÛ[™Bˆ[Û[™\ÈHØš[[™×Û[™\Ê]JBˆ˜Z[™YHH›Û™BˆYˆ\ÝÛ[™N‚ˆ›ÜˆÙ\ÜÈ[ˆ]K™Ù]
	ÜÙ\ÜÚ[ÛœÉË×JN‚ˆ›Üˆ[ˆÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
Ù\ÜÊN‚ˆYˆÝŠ™Ù]
	ÚY	ÊJHOHÝŠ\ÝÛ[™K™Ù]
	Ý˜Z[™YRY	ÊJN‚ˆ˜Z[™YHHÈœ™XZÂˆYˆ˜Z[™YNˆœ™XZÂˆÝ[[X\žHHØ[Ý[]WÝ˜Z[™YWÙš[˜[˜ÚX[ÜÝ[[X\žJˆ˜Z[™YK[Û[™\Ë[˜ÛYWØØ[˜Ù[YUYKˆ
HYˆ˜Z[™YH[ÙHßBˆ[›ÚXÙHH›Û™BˆYˆ\ÝÛ[™N‚ˆ[›ÚXÙHHÙ\šX[^™WÜ[Û×Ú[›ÚXÙWÙ›Ü—Ùœ›Û[™
\ÝÛ[™JBˆ[›ÚXÙVÉÛ[X™\‰×HH[›ÚXÙVÉÚ[›ÚXÙWÛ[X™\‰×Bˆ[›ÚXÙVÉØ[[Ý[ÜZYØÙ[É×HH[›ÚXÙVÉÜZYØ[[Ý[ØÙ[É×Bˆ\›ÙÙÙ\‹š[™›Ê	ÔSÓ•×ÔVSQS•ÔTSS‘H[›ÚXÙWÛ[X™\I\È˜]×ÜZYØ[[Ý[IKŒ™ˆ›Ü›X[^™YÜZYØÙ[ÏI\ÈÝÜ™YÜZYØÙ[ÏI\ÈÝÜ™YÝÝ[ØÙ[ÏI\ÈØ[Ý[]YÜ™[XZ[š[™×ØÙ[ÏI\ÈÝ[[X\žWÜZYÝÝ[ØÙ[ÏI\Èœ›Û[™ÜZYØ[[Ý[ØÙ[ÏI\ÉË[›ÚXÙVÉÛ[X™\‰×KÙ[×Ý×Û[Û™^J[›ÚXÙVÉÜZYØ[[Ý[ØÙ[É×JK[›ÚXÙVÉÜZYØ[[Ý[ØÙ[É×K
\œÚ\ÝYØÚXÚÈÜˆßJK™Ù]
	Ü[Û×Ø[[Ý[ÜZYØÙ[ÉÊK
\œÚ\ÝYØÚXÚÈÜˆßJK™Ù]
	Ü[Û×ÝÝ[Ø[[Ý[ØÙ[ÉÊK[›ÚXÙVÉÜ™[XZ[š[™×Ø[[Ý[ØÙ[É×KÝ[[X\žK™Ù]
	ÜZYÝÝ[ØÙ[ÉÊK[›ÚXÙVÉÜZYØ[[Ý[ØÙ[É×JBˆ™]\›ˆœÛÛšYžJÂˆ	ÛÚÉÎˆYK	ÜÝXØÙ\ÜÉÎˆYK	ÜÞ[˜ÙYØÛÝ[	ÎˆÞ[˜ÙYØÛÝ[ˆ	Ü™XÛÝ™\™YÚ[œÝ[Y[ÉÎˆ™XÛÝ™\™YÚ[œÝ[Y[Ëˆ	Ý\]YØÛÛXÝ[ÛœÉÎˆ\]YØÛÛXÝ[ÛœËˆ	Ù˜Z[YØÛÝ[	Îˆ[Š\œ›ÜœÊKˆ	ÛY\ÜØYÙIÎˆ
ˆ‰ÔÞ[˜Ú›Ûš\Ø][Ûˆ\›Z[°êYHˆÜÞ[˜ÙYØÛÝ[H˜XÝ\™JÊH°ê\šYšpêYJÊK	Âˆ‰ÞÜ™XÛÝ™\™YÚ[œÝ[Y[ßH0êXÚ0êX[˜ÙJÊH[ÛÈ™]›Ý]°êYJÊK	Âˆ‰ÞÝ\]YØÛÛXÝ[ÛœßHÝ]]
ÊHH°ê[0ê™[Y[Z\È0è›Ý\‹‰Âˆ
Kˆ	Û[™\ÉÎˆ[Û[™\Ë	Ù\œ›ÜœÉÎˆ\œ›ÜœË	Ú[›ÚXÙIÎˆ[›ÚXÙKˆ	Ùš[˜[˜ÚX[ÜÝ[[X\žIÎˆÝ[[X\žKˆJB‚‚\œÜÝ
	ËØ\KØš[[™ËÜ™\Ù]Yš[˜[˜ÚX[]˜XÚÚ[™ÉÊBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØš[[™×Ü™\Ù]Ùš[˜[˜ÚX[Ý˜XÚÚ[™Ê
N‚ˆˆˆ”™]šY]ÈÜˆ]ÛZXØ[H™XZ[Û™H˜Z[™YIÜÈØØ[ÑTH˜XÚÚ[™Ë‚‚ˆH[™Ú[\È[X™\˜][H™XY[Û›HÝØ\™[ÛËˆ]™]™\ˆØ[˜Ù[ËˆÜ™X]\ËY]ËÜˆ™]šY\ÈH™[[ÝHXš]ˆHØØ[š[[™È›ÝÈ\ÈØ]™YˆÛ›HY\ˆHÙXÛÛ™™\]Y\ÝÛÛ™š\›\ÈH^XÝ™]šY]Èš[™Ù\œš[‚ˆˆˆ‚ˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆ˜Z[™YWÚYHÝŠ^[ØY™Ù]
	Ý˜Z[™YRY	ÊHÜˆ	ÉÊKœÝš\

BˆÙ\ÜÚ[Û—ÚYHÝŠ^[ØY™Ù]
	ÜÙ\ÜÚ[Û’Y	ÊHÜˆ	ÉÊKœÝš\

Bˆ™]šY]×ÛÛ›HH›ÛÛ
^[ØY™Ù]
	Ü™]šY]ÉÊJBˆÛÛ™š\›YYH^[ØY™Ù]
	ØÛÛ™š\›IÊH\ÈYBˆ\×ÛX[X[Ú[œÝ[Y[ÈH	ÛX[X[[œÝ[Y[ÉÈ[ˆ^[ØYˆX[X[Ú[œÝ[Y[ÈH^[ØY™Ù]
	ÛX[X[[œÝ[Y[ÉÊBˆYˆ›Ý˜Z[™YWÚYÜˆ›ÝÙ\ÜÚ[Û—ÚY‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÑšXÚHÝYÚXZ\™HÝHÙ\ÜÚ[ÛˆX[œ]X[K‰ßJKˆYˆ›Ý™]šY]×ÛÛ›H[™›ÝÛÛ™š\›YY‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÓHÛÛ™š\›X][ÛˆH°êZ[š]X[\Ø][Ûˆ\ÝØ›YØ]Ú\™K‰ßJK‚ˆ]HHØYÙ]J
BˆÙ\ÜÚ[Û—ÛØšˆH™^
ˆ
][H›Üˆ][H[ˆ]K™Ù]
	ÜÙ\ÜÚ[ÛœÉË×JHYˆÝŠ][K™Ù]
	ÚY	ÊHÜˆ	ÉÊHOHÙ\ÜÚ[Û—ÚY
Kˆ›Û™Kˆ
Bˆ˜Z[™YHH™^
ˆ
ˆ][H›Üˆ][H[ˆÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
Ù\ÜÚ[Û—ÛØšˆÜˆßJBˆYˆÝŠ][K™Ù]
	ÚY	ÊHÜˆ	ÉÊHOH˜Z[™YWÚYˆ
Kˆ›Û™Kˆ
BˆYˆ›ÝÙ\ÜÚ[Û—ÛØšˆÜˆ›Ý˜Z[™YN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÐÙ]HšXÚHÝYÚXZ\™H\Ý[›Ý]˜X›H[œÈÙ]HÙ\ÜÚ[Û‹‰ßJK‚ˆ[™\ÈHØš[[™×Û[™\×Ù›Ü—Ý˜Z[™YWÜÙ\ÜÚ[ÛŠ]K˜Z[™YWÚYÙ\ÜÚ[Û—ÚY
Bˆ™\Ù]ØØ[™Y]\ÈHÙš[˜[˜ÚX[Ü™\Ù]Û[™WØØ[™Y]\Ê[™\ÊBˆYˆ[Š™\Ù]ØØ[™Y]\ÊHOHN‚ˆ™]\›ˆœÛÛšYžJÂˆ	ÛÚÉÎˆ˜[ÙKˆ	Ù\œ›Ü‰Îˆ
ˆ	Ð]XÝ[ˆ0êXÚ0êX[˜ÚY\ˆ\œÛÛ›™[[š\]YH¸ &XH0ê]0êH›Ý]°êHÝ\ˆÙ]HšXÚK‰ÂˆYˆ›Ý™\Ù]ØØ[™Y]\Âˆ[ÙH	Ô\ÚY]\œÈ0êXÚ0êX[˜ÚY\œÈ\œÛÛ›™[È^\Ý[Ý\ˆÙ]HšXÚHÈ]XÝ[™H°êZ[š]X[\Ø][Ûˆ]]ÛX]\]YH¸ &Y\ÝÜÜÚX›K‰Âˆ
KˆJKBˆ[™HH™\Ù]ØØ[™Y]\ÖÌB‚ˆžN‚ˆ™\Ù]Ü™]šY]ÈH
ˆØZ[ÛX[X[Ùš[˜[˜ÚX[Ý˜XÚÚ[™×Ü™\Ù]Ü™]šY]Ê[™KX[X[Ú[œÝ[Y[ÊBˆYˆ\×ÛX[X[Ú[œÝ[Y[Âˆ[ÙHØZ[Ùš[˜[˜ÚX[Ý˜XÚÚ[™×Ü™\Ù]Ü™]šY]Ê[™JBˆ
Bˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰ÎˆÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJ_JKB‚ˆX›X×Ú[œÝ[Y[ÈHÂˆÂˆ	Ú[™^	Îˆ[
›ÝË™Ù]
	Ú[™^	ÊHÜˆ[™^
Kˆ	Ù]IÎˆÝŠ›ÝË™Ù]
	ÙYWÙ]IÊHÜˆ›ÝË™Ù]
	Ù]IÊHÜˆ	ÉÊVÎŒLKˆ	Ø[[Ý[ØÙ[ÉÎˆ[Û™^WÝ˜[YWÝ×ØÙ[Ê›ÝË™Ù]
	Ø[[Ý[	ÊHÜˆ
Kˆ	ÜÝ]\ÉÎˆÝŠ›ÝË™Ù]
	ÜÝ]\ÉÊHÜˆ	ÜØÚY[Y	ÊKˆBˆ›Üˆ[™^›ÝÈ[ˆ[[Y\˜]J™\Ù]Ü™]šY]ÖÉÚ[œÝ[Y[É×KÝ\LJBˆBˆ™\ÜÛœÙWÜ™]šY]ÈHÂˆ	Û[ÙIÎˆ™\Ù]Ü™]šY]Ë™Ù]
	Û[ÙIÊHÜˆ	Ü[ÛÉËˆ	Ùš[™Ù\œš[	Îˆ™\Ù]Ü™]šY]ÖÉÙš[™Ù\œš[	×Kˆ	Û[™WÚY	Îˆ™\Ù]Ü™]šY]ÖÉÛ[™WÚY	×Kˆ	ÛX[™]WÜ[IÎˆ™\Ù]Ü™]šY]ÖÉÛX[™]WÜ[I×Kˆ	Ù^XÝYØ[[Ý[ØÙ[ÉÎˆ™\Ù]Ü™]šY]ÖÉÙ^XÝYØ[[Ý[ØÙ[É×Kˆ	Ù]XÝYØ[[Ý[ØÙ[ÉÎˆ™\Ù]Ü™]šY]ÖÉÙ]XÝYØ[[Ý[ØÙ[É×Kˆ	ÜZYØ[[Ý[ØÙ[ÉÎˆ™\Ù]Ü™]šY]ÖÉÜZYØ[[Ý[ØÙ[É×Kˆ	Ü™[XZ[š[™×Ø[[Ý[ØÙ[ÉÎˆ™\Ù]Ü™]šY]ÖÉÜ™[XZ[š[™×Ø[[Ý[ØÙ[É×Kˆ	Ú[œÝ[Y[ÉÎˆX›X×Ú[œÝ[Y[ËˆBˆYˆ™]šY]×ÛÛ›N‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆYK	Ü™]šY]ÉÎˆ™\ÜÛœÙWÜ™]šY]ßJB‚ˆÝ\YYÙš[™Ù\œš[HÝŠ^[ØY™Ù]
	Ü™]šY]Ñš[™Ù\œš[	ÊHÜˆ	ÉÊKœÝš\

BˆYˆ›ÝÝ\YYÙš[™Ù\œš[Üˆ›ÝXXË˜ÛÛ\\™WÙYÙ\Ý
ˆÝ\YYÙš[™Ù\œš[™\Ù]Ü™]šY]ÖÉÙš[™Ù\œš[	×Kˆ
N‚ˆ™]\›ˆœÛÛšYžJÂˆ	ÛÚÉÎˆ˜[ÙKˆ	Ù\œ›Ü‰Îˆ
ˆ	Ó8 &pêXÚ0êX[˜ÚY\ˆHÚ[™ðêH\Z\È8 &X\\°éÝKˆ°ê\šYšY^‹[HH›Ý]™X]H]˜[H8 &X\\]Y\‹‰ÂˆYˆ™\Ù]Ü™]šY]Ë™Ù]
	Û[ÙIÊHOH	ÛX[X[	Âˆ[ÙH	Ó\ÈÛ›°êY\È[ÛÈÛÚ[™ðêH\Z\È8 &X\\°éÝKˆ™[[˜Ù^ˆH°êZ[š]X[\Ø][ÛˆÝ\ˆ\È°ê\šYšY\‹‰Âˆ
KˆJKB‚ˆ^\Ý[™×ÛX\HØš[[™×Ù^\Ý[™×ÛX\
]JBˆ˜XÚÝ\HÂˆ	ÚY	Îˆ‰Ùš[˜[˜ÙK\™\Ù]^Ý]ZY]ZY

Kš^ÎŒL—_IËˆ	ØÜ™X]YØ]	ÎˆÛ›Ý×Ú\ÛÊ
Kˆ	ØÜ™X]YØžIÎˆÙ\ÜÚ[Û‹™Ù]
	ØYZ[—Ý\Ù\›˜[YIÊHÜˆÙ\ÜÚ[Û‹™Ù]
	ØYZ[—Ù[XZ[	ÊHÜˆ	ØYZ[‰Ëˆ	ÜÙ\ÜÚ[Û—ÚY	ÎˆÙ\ÜÚ[Û—ÚYˆ	Ý˜Z[™YWÚY	Îˆ˜Z[™YWÚYˆ	Û[™WÚY	ÎˆÝŠ[™K™Ù]
	ÚY	ÊHÜˆ	ÉÊKˆ	Ü™]šY]×Ùš[™Ù\œš[	Îˆ™\Ù]Ü™]šY]ÖÉÙš[™Ù\œš[	×Kˆ	Ý˜Z[™YWÙš[˜[˜Ú[™ÉÎˆÂˆÙ^NˆÛÜK™Y\ÛÜJ˜Z[™YK™Ù]
Ù^JJBˆ›ÜˆÙ^H[ˆ
ˆ	Ý˜Z[š[™×ÜšXÙIË	ØÜ—Ø[[Ý[	Ë	Ü\œÛÛ˜[Ø[[Ý[	Ë	ÛÝ\—Ø[[Ý[	Ëˆ	ÛÝ\—Ùš[˜[˜Ú[™×Ø[[Ý[	Ë	Ùš[˜[˜Ú[™ÜÉË	ØÜ—Ý˜[Y]Y	Ëˆ
BˆKˆ	Øš[[™×Û[™IÎˆÛÜK™Y\ÛÜJ^\Ý[™×ÛX\™Ù]
ÝŠ[™K™Ù]
	ÚY	ÊHÜˆ	ÉÊJHÜˆ[™JKˆBˆØ\WÙš[˜[˜ÚX[Ý˜XÚÚ[™×Ü™\Ù]
[™K™\Ù]Ü™]šY]ÊBˆÜØ]™WØš[[™×Û[™J]K[™JBˆ˜XÚÝ\ÈH]K™Ù]
	Ùš[˜[˜ÚX[Ý˜XÚÚ[™×Ü™\Ù]Ø˜XÚÝ\ÉÊBˆYˆ›Ý\Ú[œÝ[˜ÙJ˜XÚÝ\Ë\Ý
N‚ˆ˜XÚÝ\ÈH×Bˆ˜XÚÝ\Ë˜\[™
˜XÚÝ\
Bˆ]VÉÙš[˜[˜ÚX[Ý˜XÚÚ[™×Ü™\Ù]Ø˜XÚÝ\É×HH˜XÚÝ\ÖËML—BˆØ]™WÙ]J]JB‚ˆœ™\ÚÛ[™\ÈHØš[[™×Û[™\×Ù›Ü—Ý˜Z[™YWÜÙ\ÜÚ[ÛŠ]K˜Z[™YWÚYÙ\ÜÚ[Û—ÚY
BˆÝ[[X\žHHØ[Ý[]WÝ˜Z[™YWÙš[˜[˜ÚX[ÜÝ[[X\žJˆ˜Z[™YKœ™\ÚÛ[™\Ë[˜ÛYWØØ[˜Ù[YUYKˆ
Bˆ™]\›ˆœÛÛšYžJÂˆ	ÛÚÉÎˆYKˆ	ÛY\ÜØYÙIÎˆ
ˆ	ÓHÝZ]šHš[˜[˜ÚY\ˆHÙ]HšXÚHH0ê]0êHÛÜœšYðêHØ[œÈ[ÙYšY\ˆ[ÛË‰ÂˆYˆ™\Ù]Ü™]šY]Ë™Ù]
	Û[ÙIÊHOH	ÛX[X[	Âˆ[ÙH	ÓHÝZ]šHš[˜[˜ÚY\ˆH0ê]0êH™XÛÛœÝZ]\Z\È[ÛÈØ[œÈ[ÙYšY\ˆ[ÛË‰Âˆ
Kˆ	Ø˜XÚÝ\ÚY	Îˆ˜XÚÝ\ÉÚY	×Kˆ	Ü™]šY]ÉÎˆ™\ÜÛœÙWÜ™]šY]Ëˆ	Û[™\ÉÎˆœ™\ÚÛ[™\Ëˆ	Ùš[˜[˜ÚX[ÜÝ[[X\žIÎˆÝ[[X\žKˆJB‚‚\œÜÝ
	ËØ\KØYZ[‹Øš[[™Ë[[™\ËØ[ËYÙ[™\˜]IÊBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØYZ[—Øš[[™×Ø[×ÙÙ[™\˜]J
N‚ˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆYÈH^[ØY™Ù]
	ÚYÉÊHÜˆ×Bˆš[˜[^™WØY\—ØÜ™X]HH›ÛÛ
^[ØY™Ù]
	Ùš[˜[^™IÊHÜˆ^[ØY™Ù]
	Ùš[˜[^™PY\Ü™X]IÊJBˆ]HHØYÙ]J
NÈÝ[[X\žHHÉØÜ™X]Y	Îˆ×K	ÚYÛ›Ü™Y	Îˆ×K	Ù˜Z[Y	Îˆ×_Bˆ›Üˆ[™WÚY[ˆYÎ‚ˆ[™HHÙš[™Øš[[™×Û[™J]KÝŠ[™WÚY
JBˆYˆ›Ý[™NˆÝ[[X\žVÉÙ˜Z[Y	×K˜\[™
ÉÚY	Îˆ[™WÚY	Ù\œ›Ü‰Îˆ	Ú[›Ý]˜X›IßJNÈÛÛ[YBˆYˆ[™K™Ù]
	Ü™YÚ\Ý˜][ÛØ[˜Ù[Y	ÊNˆÝ[[X\žVÉÚYÛ›Ü™Y	×K˜\[™
[™JNÈÛÛ[YBˆYˆ[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊHÜˆÛ›Ü›X[^™WØš[[™×Ú[›ÚXÙWÜÝ]\Ê[™K™Ù]
	Ú[›ÚXÙTÝ]\ÉÊJH[ˆÉÙ˜Y	Ë	Ùš[˜[^™Y	Ë	ÜÙ[	Ë	ÜZY	Ë	Ù^\›˜[ÙÙ[™\˜]Y	ßNˆÝ[[X\žVÉÚYÛ›Ü™Y	×K˜\[™
[™JNÈÛÛ[YBˆÚË™\ÈHØÜ™X]WÚ[›ÚXÙWÙ›Ü—Øš[[™×Û[™J]K[™JBˆÜ™X]YÛ[™HH™\Ë™Ù]
	Û[™IÊBˆYˆÚÈ[™š[˜[^™WØY\—ØÜ™X]H[™Ü™X]YÛ[™H[™Ü™X]YÛ[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊN‚ˆžN‚ˆZHHÜ[Û×Ú[›ÚXÙWÜ^[ØY
š[˜[^™WÜ[Û×Ú[›ÚXÙJÜ™X]YÛ[™VÉÜ[ÛÒ[›ÚXÙRY	×JJBˆÜ™X]YÛ[™VÉÚ[›ÚXÙTÝ]\É×HHÛ›Ü›X[^™WØš[[™×Ú[›ÚXÙWÜÝ]\ÊZK™Ù]
	ÜÝ]\ÉÊHÜˆ	Ùš[˜[^™Y	ÊBˆÜ™X]YÛ[™VÉÙš[˜[^™Y]	×HHÛ›Ý×Ú\ÛÊ
BˆÜ™Yœ™\ÚØš[[™×Û[™WÚ[›ÚXÙWÙœ›ÛWÜ[ÛÊÜ™X]YÛ[™KZJBˆØš[[™×ÛÙÊÜ™X]YÛ[™K	Ñ˜XÝ\™Hš[˜[\ðêYH\°êÈðê[°ê\˜][Ûˆ[ˆX\ÜÙIË	ÜÝXØÙ\ÜÉË	ÉËÜ™X]YÛ[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊHÜˆ	ÉÊBˆÜØ]™WØš[[™×Û[™J]KÜ™X]YÛ[™JNÈØ]™WÙ]J]JBˆÜ™X]YÛ[™HHÙš[™Øš[[™×Û[™J]KÝŠÜ™X]YÛ[™K™Ù]
	ÚY	ÊJJHÜˆÜ™X]YÛ[™Bˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆÝ[[X\žVÉÙ˜Z[Y	×K˜\[™
ÉÚY	Îˆ[™WÚY	Ù\œ›Ü‰ÎˆÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJK	Û[™IÎˆÜ™X]YÛ[™_JBˆ]HHØYÙ]J
BˆÛÛ[YBˆÝ[[X\žVÉØÜ™X]Y	ÈYˆÚÈ[ÙH	Ù˜Z[Y	×K˜\[™
Ü™X]YÛ[™HÜˆÉÚY	Îˆ[™WÚY	Ù\œ›Ü‰Îˆ™\Ë™Ù]
	Ù\œ›Ü‰Ê_JBˆ]HHØYÙ]J
Bˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆYK
ŠœÝ[[X\ž_JB‚‚\œÜÝ
	ËØ\KØYZ[‹Øš[[™Ë[[™\ËÏ[™WÚY‹ÜÞ[˜Ë\^[Y[	ÊBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØYZ[—Øš[[™×ÜÞ[˜×Ü^[Y[
[™WÚYˆÝŠN‚ˆ]HHØYÙ]J
NÈ[™HHÙš[™Øš[[™×Û[™J]K[™WÚY
BˆYˆ›Ý[™Nˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÓYÛ™H[›Ý]˜X›IßJKˆYˆ›Ý[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊNˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ð]XÝ[™H˜XÝ\™H[ÛÈpêYIßJKˆžN‚ˆYÜ™\Ù]Y\ÜØYÙHHÜÞ[˜×Øš[[™×Û[™WÝÚ]Ü[ÛÊ]K[™JBˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆYK	Û[™IÎˆÙš[™Øš[[™×Û[™J]K[™WÚY
HÜˆ[™K	Ü™\Ù]	ÎˆYÜ™\Ù]	ÛY\ÜØYÙIÎˆY\ÜØYÙ_JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆØ]™WÙ]J]JNÈ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	ÔÞ[˜Ú›Ûš\Ø][Ûˆ[\ÜÜÚX›Hˆ˜XÝ\™HÛÛœÙ\°êYHØØ[[Y[	ßJK‚‚\™Ù]
‹ØYZ[‹Ü[ÛËÚ[›ÚXÙ\ËÏ[›ÚXÙWÚY‹ÜˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ü[Û×Ú[›ÚXÙWÜŠ[›ÚXÙWÚYˆÝŠN‚ˆžN‚ˆ—ØÛÛ[š[[˜[YHH™]ÚÜ[Û×ØÛY[Ú[›ÚXÙWÜŠ[›ÚXÙWÚY
BˆØY™WÙš[[˜[YHHÙXÝ\™WÙš[[˜[YJš[[˜[YJHÜˆˆ™˜XÝ\™K\[ÛË^ÜÙXÝ\™WÙš[[˜[YJÝŠ[›ÚXÙWÚY
JHÜˆ	Ù˜XÝ\™IßKœˆ‚ˆ™\ÜÛœÙHH™\ÜÛœÙJˆ—ØÛÛ[ˆZ[Y]\OH˜\XØ][Û‹Üˆ‹ˆXY\œÏ^ÂˆÛÛ[Q\ÜÜÚ][ÛˆŽˆ‰Ú[›[™NÈš[[˜[YOHžÜØY™WÙš[[˜[Y_H‰ËˆØXÚKPÛÛ›ÛŽˆœš]˜]K›Ë\ÝÜ™H‹ˆKˆ
Bˆ™]\›ˆ™\ÜÛœÙBˆ^Ù\[ÛÐÛÛ™šYÝ\˜][Û‘\œ›ÜŽ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”[ÛÈ¸ &Y\Ý\ÈÛÛ›™XÝ0êHŸJKLÂˆ^Ù\[ÛÓ›Ý›Ý[™\œ›ÜŽ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ‘˜XÝ\™H[ÛÈ[›Ý]˜X›HŸJKˆ^Ù\[ÛÔ•[˜]˜Z[X›Q\œ›Üˆ\È^Î‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆÝŠ^Ê_JKÙ]]Š^ËœÝ]\×ØÛÙH‹LŠBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹Ø\›š[™Ê”SÓ•ÈŽˆ\œ™]\ˆ[˜][™YH[›ÚXÙWÚYI\È\œ›ÜI\È‹[›ÚXÙWÚYÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJJBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ’[\ÜÜÚX›HH°êXÝ\0ê\™\ˆHˆ]\°êÈH[ÛËˆŸJKL‚‚‚\™Ù]
	ËØ\KØYZ[‹Øš[[™Ë[[™\ËÏ[™WÚY‹ÙÝÛ›ØYZ[›ÚXÙIÊBYZ[—ÛÙÚ[—Ü™\]Z\™Y™Yˆ\WØYZ[—Øš[[™×ÙÝÛ›ØY
[™WÚYˆÝŠN‚ˆ]HHØYÙ]J
NÈ[™HHÙš[™Øš[[™×Û[™J]K[™WÚY
BˆYˆ›Ý[™HÜˆ›Ý[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊN‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ð[˜ÚY[›™H˜XÝ\™HØ[œÈY[YšX[[ÛÈ°êXÝ\0ê\˜X›IßJKˆžN‚ˆ—Øž]\ËÛÛ[Ý\HHÝÛ›ØYÜ[Û×Ú[›ÚXÙWÜŠ[™VÉÜ[ÛÒ[›ÚXÙRY	×K[™K™Ù]
	Ü[ÛÒ[›ÚXÙS[X™\‰ÊHÜˆ	ÉÊBˆ[™VÉÚ[›ÚXÙQÝÛ›ØYY]	×HHÛ›Ý×Ú\ÛÊ
NÈØš[[™×ÛÙÊ[™K	Ôˆ0ê[0êXÚ\™ðêIË	ÜÝXØÙ\ÜÉÊNÈÜØ]™WØš[[™×Û[™J]K[™JNÈØ]™WÙ]J]JBˆØY™WÙš[[˜[YHHÙXÝ\™WÙš[[˜[YJˆ‘PÕT‘WÞÛ[™K™Ù]
	Ü[ÛÒ[›ÚXÙS[X™\‰ÊHÜˆ[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	Ê_KœˆŠHÜˆˆ™˜XÝ\™K\[ÛË^Û[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	Ê_Kœˆ‚ˆ™]\›ˆ™\ÜÛœÙJ—Øž]\ËZ[Y]\OIØ\XØ][Û‹Ü‰ËXY\œÏ^ÉÐÛÛ[Q\ÜÜÚ][Û‰Îˆ‰Ú[›[™NÈš[[˜[YOHžÜØY™WÙš[[˜[Y_H‰Ë	ÐØXÚKPÛÛ›Û	Îˆ	Üš]˜]K›Ë\ÝÜ™IßJBˆ^Ù\[ÛÐÛÛ™šYÝ\˜][Û‘\œ›ÜŽ‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ô[ÛÈ¸ &Y\Ý\ÈÛÛ›™XÝ0êIßJKLÂˆ^Ù\[ÛÓ›Ý›Ý[™\œ›ÜŽ‚ˆØš[[™×ÛÙÊ[™K	Ôˆ[ÛÈ[™\ÜÛšX›IË	Ù\œ›Ü‰Ë	Ñ˜XÝ\™H[ÛÈ[›Ý]˜X›IË[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊHÜˆ	ÉÊBˆÜØ]™WØš[[™×Û[™J]K[™JNÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ñ˜XÝ\™H[ÛÈ[›Ý]˜X›IßJKˆ^Ù\[ÛÔ•[˜]˜Z[X›Q\œ›Üˆ\È^Î‚ˆØš[[™×ÛÙÊ[™K	Ôˆ[ÛÈ[™\ÜÛšX›IË	Ù\œ›Ü‰ËÝŠ^ÊK[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊHÜˆ	ÉÊBˆÜØ]™WØš[[™×Û[™J]K[™JNÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰ÎˆÝŠ^ÊK	Ü[ÛÒ[›ÚXÙRY	Îˆ[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	Ê_JKÙ]]Š^Ë	ÜÝ]\×ØÛÙIËLŠBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹Ø\›š[™Ê”SÓ•ÈŽˆ[›ÚXÙHÝÛ›ØY˜Z[Y[™WÚYI\È[›ÚXÙWÚYI\È\œ›ÜI\È‹[™WÚY[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊHÜˆ	ÉËÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJJBˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Ò[\ÜÜÚX›HH°êXÝ\0ê\™\ˆHˆ]\°êÈH[ÛË‰ßJKL‚‚‚\œÜÝ
	ËØ\KØYZ[‹Øš[[™Ë[[™\ËØ[ËYÝÛ›ØY	ÊBYZ[—ÛÙÚ[—Ü™\]Z\™Y™Yˆ\WØYZ[—Øš[[™×Ø[×ÙÝÛ›ØY

N‚ˆYÈH
™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßJK™Ù]
	ÚYÉÊHÜˆ×Bˆ]HHØYÙ]J
NÈY[HHž]\ÒSÊ
NÈÛÝ[HˆÚ]š\š[K–š\š[JY[K	ÝÉËš\š[K–’TÑQ“UQ
H\È™Ž‚ˆ›Üˆ[™WÚY[ˆYÎ‚ˆ[™HHÙš[™Øš[[™×Û[™J]KÝŠ[™WÚY
JBˆYˆ[™H[™[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊN‚ˆ˜[YHH™KœÝXŠ‰Ö×KV˜K^ŒNWË‹WJÉË	×ÉËˆ‘PÕT‘WÞÛ[™K™Ù]
	Ü[ÛÒ[›ÚXÙS[X™\‰ÊHÜˆ[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	Ê_WÞÛ[™K™Ù]
	Ý˜Z[™YS\Ý˜[YIÊ_WÞÛ[™K™Ù]
	Ý˜Z[™YQš\œÝ˜[YIÊ_WÞÛ[™K™Ù]
	Ù›Ü›X][Û“˜[YIÊ_KŠBˆ™‹Üš]\ÝŠ˜[YK[™K™Ù]
	Ú[›ÚXÙT•\›	ÊHÜˆˆ‘˜XÝ\™H[ÛÎˆÛ[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	Ê_HŠBˆØš[[™×ÛÙÊ[™K	Ôˆ0ê[0êXÚ\™ðêH[ˆX\ÜÙIË	ÜÝXØÙ\ÜÉÊNÈÜØ]™WØš[[™×Û[™J]K[™JNÈÛÝ[
ÏHBˆØ]™WÙ]J]JNÈY[KœÙYZÊ
Bˆ™]\›ˆÙ[™Ùš[JY[KZ[Y]\OIØ\XØ][Û‹Þš\	Ë\×Ø]XÚY[UYKÝÛ›ØYÛ˜[YOY‰Ù˜XÝ\™\×Ü[Û×ÞØÛÝ[Kžš\	ÊB‚‚\œÜÝ
	ËØ\KØYZ[‹Øš[[™Ë[[™\ËÏ[™WÚY‹ØÜ™X]KXÜ™Y][›ÝIÊBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØYZ[—Øš[[™×ØÜ™Y]Û›ÝJ[™WÚYˆÝŠN‚ˆ]HHØYÙ]J
NÈ[™HHÙš[™Øš[[™×Û[™J]K[™WÚY
BˆYˆ›Ý[™HÜˆ›Ý[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊNˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰Îˆ	Õ[ˆ]›Ú\ˆ°êXÙ\ÜÚ]H[™H˜XÝ\™H^\Ý[IßJKˆ[™VÉØÜ™Y]›ÝTÝ]\É×HH	Ü™\]Y\ÝY	ÎÈØš[[™×ÛÙÊ[™K	Ð]›Ú\ˆðê[°ê\°êIË	ÜÝXØÙ\ÜÉË	Ñ[X[™H[œ™YÚ\Ý°êYHØØ[[Y[ÈÜ°êX][Ûˆ[ÛÈ0èÛÛ›™XÝ\ˆÙ[ÛˆTH\ÜÛšX›K‰Ë[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊHÜˆ	ÉÊBˆÜØ]™WØš[[™×Û[™J]K[™JNÈØ]™WÙ]J]JNÈ™]\›ˆœÛÛšYžJÉÛÚÉÎˆYK	Û[™IÎˆ[™_JB‚‚\™Ù]
‹Ø\KØYZ[‹Ý˜Z[™Y\ËÏ˜Z[™YWÚY‹Ü[ÛËZ[›ÚXÙKÜ™]šY]ÈŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™Yˆ\WÜ[Û×Ú[›ÚXÙWÜ™]šY]Ê˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
NÈÙ\ÜËË˜Z[™YHHÙš[™Ý˜Z[™YWØ[žWÜÙ\ÜÚ[ÛŠ]K˜Z[™YWÚY
BˆYˆ›Ý˜Z[™YNˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”ÝYÚXZ\™H[›Ý]˜X›HŸJKˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK
Š—ØZ[Ü[Û×Ú[›ÚXÙWÜ™]šY]ÊÙ\ÜË˜Z[™YJ_JB‚‚\™Ù]
‹Ø\KØYZ[‹Ý˜Z[™Y\ËÏ˜Z[™YWÚY‹Ü[ÛËZ[›ÚXÙKÜÝ]\ÈŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™Yˆ\WÜ[Û×Ú[›ÚXÙWÜÝ]\Ê˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
NÈÙ\ÜË˜Z[™Y\Ë˜Z[™YHHÙš[™Ý˜Z[™YWØ[žWÜÙ\ÜÚ[ÛŠ]K˜Z[™YWÚY
BˆYˆ›Ý˜Z[™YNˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”ÝYÚXZ\™H[›Ý]˜X›HŸJKˆ[ˆHÜ[Û×Ú[›ÚXÙWÜÝ]J˜Z[™YJBˆYˆ[‹™Ù]
œ[Û×Ú[›ÚXÙWÚYŠH[™Ü[Û×Ú\×ØÛÛ™šYÝ\™Y

N‚ˆžN‚ˆ™[[ÝHHÙ]Ü[Û×Ú[›ÚXÙJ[–Èœ[Û×Ú[›ÚXÙWÚY—JBˆ[›ÚXÙHH™[[ÝK™Ù]
˜ÛY[Ú[›ÚXÙHŠHÜˆ™[[ÝK™Ù]
š[›ÚXÙHŠHÜˆ™[[ÝBˆØ\WÜ[Û×Ú[›ÚXÙWÜÝ]\Ê[‹[›ÚXÙJBˆÙ\ÜÖÈ˜Z[™Y\È—HH˜Z[™Y\ÎÈØ]™WÙ]J]JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹Ø\›š[™Ê–ÔSÓ•×HÝ]\ÈÞ[˜È˜Z[Yˆ	\È‹ÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJJBˆ™]\›ˆœÛÛšYžJÜ[Û×ÜÝ]\×Ü^[ØY
˜Z[™YJJB‚‚\œÜÝ
‹Ø\KØYZ[‹Ý˜Z[™Y\ËÏ˜Z[™YWÚY‹Ü[ÛËZ[›ÚXÙKØÜ™X]HŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WÜ[Û×Ú[›ÚXÙWØÜ™X]J˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
NÈÙ\ÜË˜Z[™Y\Ë˜Z[™YHHÙš[™Ý˜Z[™YWØ[žWÜÙ\ÜÚ[ÛŠ]K˜Z[™YWÚY
BˆYˆ›Ý˜Z[™YNˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”ÝYÚXZ\™H[›Ý]˜X›HŸJKˆ[ˆHÜ[Û×Ú[›ÚXÙWÜÝ]J˜Z[™YJBˆYˆ[‹™Ù]
œ[Û×Ú[›ÚXÙWÚYŠNˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ‘˜XÝ\™H0êZ°èÜ°êpêYHÝ\ˆÙHÝYÚXZ\™H‹
Š—Ü[Û×ÜÝ]\×Ü^[ØY
˜Z[™YJ_JKBˆYˆ›ÝÜ[Û×Ú\×ØÛÛ™šYÝ\™Y

Nˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”[ÛÈ¸ &Y\Ý\ÈÛÛ›™XÝ0êHŸJKˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆÛY[H^[ØY™Ù]
˜ÛY[ŠHÜˆßNÈ[›ÚXÙHH^[ØY™Ù]
š[›ÚXÙHŠHÜˆßBˆ\×ØÜ—Ú[›ÚXÙHH\×ØÜ—Øš[[™×ØÛÛ^
^[ØY
HÜˆ\×ØÜ—Øš[[™×ØÛÛ^
˜Z[™YJHÜˆÚ\×ØÜ—Ùš[˜[˜Ù]\ŠÛY[™Ù]
›˜[YHŠJHÜˆ
ÛY[™Ù]
›˜[YHŠHOHÔ—ÔSÓ•×ÐÓQS•ÓSQJBˆYˆ\×ØÜ—Ú[›ÚXÙN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ“H˜XÝ\˜][ÛˆÔˆ\Ýðê\°êYH[œÈ[ˆÙÚXÚY[^\›™KˆŸJKˆZ\ÜÚ[™ÈH×BˆYˆ›Ý\×ØÜ—Ú[›ÚXÙH[™›Ý
ÛY[™Ù]
™[XZ[ŠHÜˆˆŠKœÝš\

NˆZ\ÜÚ[™Ë˜\[™
™[XZ[ŠBˆžN‚ˆš[[™×ØY™\ÜÈHZ[Ü[Û×Øš[[™×ØY™\Ü×Ùœ›ÛWÛ[Ù[
ÛY[
Bˆ^Ù\˜[YQ\œ›Üˆ\È^Î‚ˆš[[™×ÛY\ÜØYÙHHÝŠ^ÊBˆZ\ÜÚ[™Ë™^[™
Ü[Û×Øš[[™×ØY™\Ü×ÛZ\ÜÚ[™×ÙšY[ÊÛY[
JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK›Y\ÜØYÙHŽˆš[[™×ÛY\ÜØYÙK™\œ›ÜˆŽˆš[[™×ÛY\ÜØYÙK›Z\ÜÚ[™×ÙšY[ÈŽˆZ\ÜÚ[™ßJKˆYˆÛ[Û™^J[›ÚXÙK™Ù]
[š]ÜšXÙWÚŠHÜˆ[›ÚXÙK™Ù]
˜[[Ý[ÚŠJHHˆZ\ÜÚ[™Ë˜\[™
›[Û[ŠBˆYˆZ\ÜÚ[™Î‚ˆY\ÜØYÙHHÚ[\ÈØ›YØ]Ú\™\ÈX[œ]X[Èˆˆ
È‹‹š›Ú[ŠZ\ÜÚ[™ÊBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK›Y\ÜØYÙHŽˆY\ÜØYÙK™\œ›ÜˆŽˆY\ÜØYÙK›Z\ÜÚ[™×ÙšY[ÈŽˆZ\ÜÚ[™ßJKˆžN‚ˆ[›ÚXÙWÚX˜[ˆHÙ]Ü[Û×Ú[›ÚXÙWÚX˜[Š
Bˆ^Ù\˜[YQ\œ›ÜŽ‚ˆ\›ÙÙÙ\‹Ø\›š[™Ê–ÔSÓ•×HÜ™X]H[›ÚXÙHÚÚ\Y˜Z[™YWÚYI\ÈZ\ÜÚ[™×ÚX˜[]YH‹˜Z[™YWÚY
Bˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ’PSˆ[ÛÈX[œ]X[ˆZ›Ý]^ˆSÓ•×ÒPSˆ[œÈ\È˜\šXX›\È™[™\‹ˆŸJKˆžN‚ˆ\›ÙÙÙ\‹š[™›Êˆ–ÔSÓ•×H[Ù[ÛY[Y™\ÜÈÝ™Y]I\Èš\I\ÈÚ]OI\ÈÛÝ[žOI\È‹ˆÛY[™Ù]
˜Y™\ÜÈŠHÜˆÛY[™Ù]
œÝ™Y]ØY™\ÜÈŠKˆÛY[™Ù]
žš\ØÛÙHŠHÜˆÛY[™Ù]
œÜÝ[ØÛÙHŠKˆÛY[™Ù]
˜Ú]HŠKˆÛY[™Ù]
˜ÛÝ[žWØÛÙHŠHÜˆÛY[™Ù]
˜ÛÝ[žHŠKˆ
BˆYˆ\×ØÜ—Ú[›ÚXÙN‚ˆWØÛY[HÙ]ÛÜ—ØÜ™X]WØÜ—Ü[Û×ØÛY[

Bˆ[ÙN‚ˆ[Û×ØÛY[Ü^[ØYH™[[Ý™WÚ[˜[YÜ[Û×ÜÛ™JZ[Ü[Û×ØÛY[Ü^[ØY
ÛY[š[[™×ØY™\ÜÊJBˆWØÛY[HÙ]ÛÜ—ØÜ™X]WÜ[Û×Øš[[™×ØÛY[
[Û×ØÛY[Ü^[ØY
BˆWØÛY[ÚYH
WØÛY[™Ù]
˜ÛY[ŠHÜˆWØÛY[
K™Ù]
šYŠBˆYˆ›ÝWØÛY[ÚYˆ˜Z\ÙH[[YQ\œ›ÜŠ’[\ÜÜÚX›HHÜ°êY\ˆHÛY[[ÛÈŠBˆÝ\H
^[ØY™Ù]
œÙ\ÜÚ[ÛˆŠHÜˆßJK™Ù]
™]WÜÝ\ŠHÜˆÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜË™]WÜÝ\‹ˆŠVÎŒLBˆ[™H
^[ØY™Ù]
œÙ\ÜÚ[ÛˆŠHÜˆßJK™Ù]
™]WÙ[™ŠHÜˆÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜË™]WÙ[™‹ˆŠVÎŒLBˆ[[Ý[ÚH[›ÚXÙK™Ù]
[š]ÜšXÙWÚŠHÜˆ[›ÚXÙK™Ù]
˜[[Ý[ÚŠBˆ\›ÙÙÙ\‹š[™›Êˆ–ÔSÓ•×HÜ™X]H[›ÚXÙH^[ØYÚXÚÈÛY[ÚYI\È\×ÚX˜[I\ÈX˜[—Û\ÝI\È[[Ý[I\È‹ˆWØÛY[ÚYˆ›ÛÛ
[›ÚXÙWÚX˜[ŠKˆ[›ÚXÙWÚX˜[–ËM—Kˆ[›ÚXÙK™Ù]
˜[[Ý[ÚŠKˆ
Bˆ[Û×Ú[›ÚXÙWÜ^[ØYHÂˆ˜ÛY[ÚYŽˆWØÛY[ÚYˆš\ÜÝYWÙ]HŽˆ[›ÚXÙK™Ù]
š\ÜÝYWÙ]HŠKˆ™YWÙ]HŽˆ[›ÚXÙK™Ù]
™YWÙ]HŠKˆ˜Ý\œ™[˜ÞHŽˆ‘UTˆ‹ˆœ^[Y[ÛY]ÙÈŽˆÈšX˜[ˆŽˆ[›ÚXÙWÚX˜[ŸKˆœ\™›Ü›X[˜ÙWÜÝ\Ù]HŽˆÝ\ˆœ\™›Ü›X[˜ÙWÙ[™Ù]HŽˆ[™ˆœÝ]\ÈŽˆ™˜Y‹ˆ\›\×Ø[™ØÛÛ™][ÛœÈŽˆ[›ÚXÙK™Ù]
˜ÛÛ™][ÛœÈŠKˆš][\ÈŽˆÞÂˆ]HŽˆ[›ÚXÙK™Ù]
›X™[ŠKˆ™\ØÜš\[ÛˆŽˆ[›ÚXÙK™Ù]
›X™[ŠKˆœ]X[]HŽˆŒH‹ˆ[š]ÜšXÙHŽˆÂˆ˜[YHŽˆÝŠ[[Ý[Ú
Kˆ˜Ý\œ™[˜ÞHŽˆ‘UTˆ‹ˆKˆ˜]Ü˜]HŽˆ›Ü›X]Ü[Û×Ý˜]Ü˜]JYˆ\×ØÜ—Ú[›ÚXÙH[ÙH
[›ÚXÙK™Ù]
˜]Ü˜]HŠHÜˆŒ
JKˆWKˆBˆØY™WÜ^[ØYHXÝ
[Û×Ú[›ÚXÙWÜ^[ØY
BˆØY™WÜ^[ØYÈœ^[Y[ÛY]ÙÈ—HHÈšX˜[ˆŽˆŠŠŠˆˆ
È[›ÚXÙWÚX˜[–ËM—_Bˆ\›ÙÙÙ\‹š[™›Ê–ÔSÓ•×H[›ÚXÙH^[ØYI\È‹ØY™WÜ^[ØY
BˆWÚ[ˆHÜ™X]WÜ[Û×Ú[›ÚXÙJ[Û×Ú[›ÚXÙWÜ^[ØY
BˆZHHWÚ[‹™Ù]
˜ÛY[Ú[›ÚXÙHŠHÜˆWÚ[‹™Ù]
š[›ÚXÙHŠHÜˆWÚ[‚ˆ›ÝÈHÛ›Ý×Ú\ÛÊ
NÈ[‹\]JÈšYŽˆ[‹™Ù]
šYŠHÜˆÝŠ]ZY]ZY

JK˜Z[™YWÚYŽˆ˜Z[™YWÚYœ[Û×ØÛY[ÚYŽˆWØÛY[ÚYœ[Û×Ú[›ÚXÙWÚYŽˆZK™Ù]
šYŠKœ[Û×Ú[›ÚXÙWÛ[X™\ˆŽˆZK™Ù]
›[X™\ˆŠHÜˆZK™Ù]
š[›ÚXÙWÛ[X™\ˆŠHÜˆˆ‹œ[Û×Ú[›ÚXÙWÜÝ]\ÈŽˆZK™Ù]
œÝ]\ÈŠHÜˆ™˜Y‹œ[Û×Ú[›ÚXÙWÜZYØ]ŽˆZK™Ù]
œZYØ]ŠHÜˆˆ‹œ[Û×Ú[›ÚXÙWØ[[Ý[ÜZYŽˆÛ›Ü›X[^™WÜ[Û×Ø[[Ý[
ZK™Ù]
˜[[Ý[ÜZYŠJKœ[Û×Ú[›ÚXÙWÝ\›ŽˆZK™Ù]
œX›X×Ý\›ŠHÜˆZK™Ù]
\›ŠHÜˆˆ‹˜ÛY[Û˜[YHŽˆÛY[™Ù]
›˜[YHŠK˜ÛY[Ù[XZ[ŽˆÛY[™Ù]
™[XZ[ŠK˜š[[™×ØY™\ÜÈŽˆXÝ
š[[™×ØY™\ÜÊK˜[[Ý[ÚŽˆÛ[Û™^J[›ÚXÙK™Ù]
˜[[Ý[ÚŠHÜˆ[›ÚXÙK™Ù]
[š]ÜšXÙWÚŠJK˜[[Ý[Ý˜HŽˆÛ[Û™^J[›ÚXÙK™Ù]
˜[[Ý[Ý˜HŠJK˜[[Ý[ÝÈŽˆÛ[Û™^J[›ÚXÙK™Ù]
˜[[Ý[ÝÈŠJK˜Ý\œ™[˜ÞHŽˆ‘UTˆ‹š\ÜÝYWÙ]HŽˆ[›ÚXÙK™Ù]
š\ÜÝYWÙ]HŠK™YWÙ]HŽˆ[›ÚXÙK™Ù]
™YWÙ]HŠK˜Ü™X]YØ]Žˆ›ÝË›\ÝÙ\œ›ÜˆŽˆˆŸJBˆYˆ^[ØY™Ù]
œØ]™WØš[[™×ØY™\ÜÈŠN‚ˆ˜Z[™YVÈ˜Y™\ÜÈ—HHš[[™×ØY™\ÜÖÈœÝ™Y]ØY™\ÜÈ—Bˆ˜Z[™YVÈžš\ØÛÙH—HHš[[™×ØY™\ÜÖÈžš\ØÛÙH—Bˆ˜Z[™YVÈ˜Ú]H—HHš[[™×ØY™\ÜÖÈ˜Ú]H—Bˆ˜Z[™YVÈœ[Û×Øš[[™×ØÛÝ[žWØÛÙH—HHš[[™×ØY™\ÜÖÈ˜ÛÝ[žWØÛÙH—BˆYˆ›Ý[‹™Ù]
œ[Û×Ú[›ÚXÙWÚYŠNˆ˜Z\ÙH[[YQ\œ›ÜŠ’[\ÜÜÚX›HHÜ°êY\ˆH˜XÝ\™H[ÛÈŠBˆÙ\ÜÖÈ˜Z[™Y\È—HH˜Z[™Y\ÎÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK›Y\ÜØYÙHŽˆ‘˜XÝ\™Hœ›ÝZ[Ûˆ[ÛÈÜ°êpêYH‹
Š—Ü[Û×ÜÝ]\×Ü^[ØY
˜Z[™YJ_JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆØ[š]^™YÙ\œ›ÜˆHÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJBˆ\›ÙÙÙ\‹™^Ù\[ÛŠ–ÔSÓ•×HÜ™X]H[›ÚXÙH˜Z[Yˆ	\È‹Ø[š]^™YÙ\œ›ÜŠBˆ[–Èœ[Û×Ú[›ÚXÙWÜÝ]\È—HH™\œ›ÜˆŽÈ[–È›\ÝÙ\œ›Üˆ—HHØ[š]^™YÙ\œ›ÜŽÈÙ\ÜÖÈ˜Z[™Y\È—HH˜Z[™Y\ÎÈØ]™WÙ]J]JBˆYˆÚ\×Ü[Û×ÛZ\ÜÚ[™×ÚX˜[—Ù\œ›ÜŠØ[š]^™YÙ\œ›ÜŠN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ’[\ÜÜÚX›HHÜ°êY\ˆH˜XÝ\™H[ÛÈˆ8 &RPSˆHZY[Y[[ÛÈ\ÝX[œ]X[ˆZ›Ý]^ˆSÓ•×ÒPSˆ[œÈ™[™\‹ˆŸJKˆYˆœÛ™Hˆ[ˆØ[š]^™YÙ\œ›Ü‹›ÝÙ\Š
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ“H0ê[0ê\Û™HÛY[¸ &XH\È0ê]0êH[›ÞpêH0è[ÛÈØ\ˆ[¸ &Y\Ý\ÈØ›YØ]Ú\™KˆŸJKˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›Ü›X]Ü[Û×Ù\œ›Ü—Ù›Ü—Ùœ›Û
^Ê_JK‚‚\œÜÝ
‹Ø\KØYZ[‹Ý˜Z[™Y\ËÏ˜Z[™YWÚY‹Ü[ÛËZ[›ÚXÙKÙš[˜[^™HŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WÜ[Û×Ú[›ÚXÙWÙš[˜[^™J˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
NÈÙ\ÜË˜Z[™Y\Ë˜Z[™YHHÙš[™Ý˜Z[™YWØ[žWÜÙ\ÜÚ[ÛŠ]K˜Z[™YWÚY
BˆYˆ›Ý˜Z[™YNˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”ÝYÚXZ\™H[›Ý]˜X›HŸJKˆ[ˆHÜ[Û×Ú[›ÚXÙWÜÝ]J˜Z[™YJNÈ[›ÚXÙWÚYH[‹™Ù]
œ[Û×Ú[›ÚXÙWÚYŠBˆYˆ›Ý[›ÚXÙWÚYˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ]XÝ[™H˜XÝ\™H[ÛÈpêYHŸJKˆžN‚ˆš[˜[^™YHš[˜[^™WÜ[Û×Ú[›ÚXÙJ[›ÚXÙWÚY
NÈZHHš[˜[^™Y™Ù]
˜ÛY[Ú[›ÚXÙHŠHÜˆš[˜[^™Y™Ù]
š[›ÚXÙHŠHÜˆš[˜[^™Yˆ[–Èœ[Û×Ú[›ÚXÙWÜÝ]\È—HHZK™Ù]
œÝ]\ÈŠHÜˆ™š[˜[^™YŽÈ[–È™š[˜[^™YØ]—HHÛ›Ý×Ú\ÛÊ
NÈ[–È›\ÝÙ\œ›Üˆ—HHˆŽÈÙ\ÜÖÈ˜Z[™Y\È—HH˜Z[™Y\ÎÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK›Y\ÜØYÙHŽˆ‘˜XÝ\™Hš[˜[\ðêYH‹
Š—Ü[Û×ÜÝ]\×Ü^[ØY
˜Z[™YJ_JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠ–ÔSÓ•×Hš[˜[^™H˜Z[Yˆ	\È‹ÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJJNÈ[–È›\ÝÙ\œ›Üˆ—HHÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJNÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ’[\ÜÜÚX›HHš[˜[\Ù\ˆH˜XÝ\™HŸJK‚‚\œÜÝ
‹Ø\KØYZ[‹Ý˜Z[™Y\ËÏ˜Z[™YWÚY‹Ü[ÛËZ[›ÚXÙKÜÙ[™ŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WÜ[Û×Ú[›ÚXÙWÜÙ[™
˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
NÈÙ\ÜË˜Z[™Y\Ë˜Z[™YHHÙš[™Ý˜Z[™YWØ[žWÜÙ\ÜÚ[ÛŠ]K˜Z[™YWÚY
BˆYˆ›Ý˜Z[™YNˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”ÝYÚXZ\™H[›Ý]˜X›HŸJKˆ[ˆHÜ[Û×Ú[›ÚXÙWÜÝ]J˜Z[™YJNÈ[XZ[H
[‹™Ù]
˜ÛY[Ù[XZ[ŠHÜˆ˜Z[™YK™Ù]
™[XZ[ŠHÜˆˆŠKœÝš\

BˆYˆ
[‹™Ù]
œ[Û×Ú[›ÚXÙWÜÝ]\ÈŠHÜˆˆŠH›Ý[ˆÈ™š[˜[^™Y‹œÙ[ŸNˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ“H˜XÝ\™HÚ]0ê™Hš[˜[\ðêYH]˜[[›ÚHŸJKˆYˆ›Ý[XZ[ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ‘[XZ[ÛY[X[œ]X[ŸJKˆ˜Z[š[™ÈH
ÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜË›˜[YH‹ˆŠHÜˆÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜË˜Z[š[™×Ý\H‹ˆŠHÜˆ‘›Ü›X][ÛˆŠKœÝš\

Bˆ[HˆžÝ˜Z[™YK™Ù]
	Ùš\œÝÛ˜[YIË	ÉÊ_HÝ˜Z[™YK™Ù]
	Û\ÝÛ˜[YIË	ÉÊ_H‹œÝš\

BˆžN‚ˆÙ[™Ü[Û×Ú[›ÚXÙJ[‹™Ù]
œ[Û×Ú[›ÚXÙWÚYŠKÈ™[XZ[Žˆ[XZ[˜ÛÜWÝ×ÜÙ[ˆŽˆYKœÝXš™XÝŽˆˆ•›Ý™H˜XÝ\™HH›Ü›X][ÛˆÝ˜Z[š[™ßH‹˜›ÙHŽˆˆ›Ûš›Ý\‹—•™]Z[^ˆ›Ý]™\ˆ›Ý™H˜XÝ\™HÛÛ˜Ù\›˜[H›Ü›X][ÛˆÝ˜Z[š[™ßHHÙ[K——ÛÜ™X[[Y[’[0êYÜ˜[HXØY[^HŸJBˆ[–Èœ[Û×Ú[›ÚXÙWÜÝ]\È—HHœÙ[ŽÈ[–ÈœÙ[Ø]—HHÛ›Ý×Ú\ÛÊ
NÈ[–È›\ÝÙ\œ›Üˆ—HHˆŽÈÙ\ÜÖÈ˜Z[™Y\È—HH˜Z[™Y\ÎÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK›Y\ÜØYÙHŽˆ‘˜XÝ\™H[›ÞpêYH‹
Š—Ü[Û×ÜÝ]\×Ü^[ØY
˜Z[™YJ_JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠ–ÔSÓ•×HÙ[™˜Z[Yˆ	\È‹ÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJJNÈ[–È›\ÝÙ\œ›Üˆ—HHÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJNÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ’[\ÜÜÚX›H8 &Y[›ÞY\ˆH˜XÝ\™HŸJK‚‚\œÜÝ
‹Ø\KØYZ[‹Ý˜Z[™Y\ËÏ˜Z[™YWÚY‹Ü[ÛË\Ù\KÙ[œÝ\™HŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØYZ[—Ý˜Z[™YWÜ[Û×ÜÙ\WÙ[œÝ\™J˜Z[™YWÚYˆÝŠN‚ˆžN‚ˆ™\Ý[H[œÝ\™T[ÛÔÙ\R[œÝ[Y[Ê˜Z[™YWÚY
Bˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆYK
Šœ™\Ý[JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ™]\›ˆœÛÛšYžJÉÛÚÉÎˆ˜[ÙK	Ù\œ›Ü‰ÎˆÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJK	ÛY\ÜØYÙIÎˆ›Ü›X]Ü[Û×Ù\œ›Ü—Ù›Ü—Ùœ›Û
^Ê_JK‚‚\œÜÝ
‹Ø\KØYZ[‹Ý˜Z[™Y\ËÏ˜Z[™YWÚY‹Ü[ÛË[X[™]KÜÙX\˜ÚŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØYZ[—Ý˜Z[™YWÜ[Û×ÛX[™]WÜÙX\˜Ú
˜Z[™YWÚYˆÝŠN‚ˆˆˆ‘š[™H[ÛÈX[™]HžH•SH[™\ÜÛØÚX]H]ÈXÚšXØ[URQÚ]H˜Z[™YKˆˆˆ‚ˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆ[HHÝŠ^[ØY™Ù]
œ[HŠHÜˆˆŠKœÝš\

BˆYˆ›Ý[N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”ØZ\Ú\ÜÙ^ˆ[ˆ[pê\›È•SHHX[™]ˆŸJKˆYˆ[Š[JHˆMŒÜˆ[žJÜ™
Ú\˜XÝ\ŠHÌˆ›ÜˆÚ\˜XÝ\ˆ[ˆ[JN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ“H[pê\›È•SHHX[™]¸ &Y\Ý\È˜[YKˆŸJK‚ˆ]HHØYÙ]J
BˆÙ\ÜË˜Z[™Y\Ë˜Z[™YHHÙš[™Ý˜Z[™YWØ[žWÜÙ\ÜÚ[ÛŠ]K˜Z[™YWÚY
BˆYˆ›Ý˜Z[™YN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”ÝYÚXZ\™H[›Ý]˜X›KˆŸJKˆžN‚ˆX[™]HHš[™Ü[Û×Ù\™XÝÙXš]ÛX[™]WØžWÜ[J[JBˆYˆ›ÝX[™]HÜˆ›ÝX[™]K™Ù]
šYŠN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ]XÝ[ˆX[™][ÛÈ›Ý]°êH]™XÈÙH•SHŸJK‚ˆÝ]\ÈHÛX\ÛX[™]WÜÝ]\ÊX[™]K™Ù]
œÝ]\ÈŠJBˆ˜Z[™YVÈœ[Û×Ù\™XÝÙXš]ÛX[™]WÚY—HHÝŠX[™]K™Ù]
šYŠJBˆ˜Z[™YVÈœ[Û×ÛX[™]WÜ[H—HH[Bˆ˜Z[™YVÈœ[Û×ÛX[™]WÜÝ]\È—HHÝ]\Âˆ˜Z[™YVÈœ[Û×ÛX[™]WÜÙX\˜ÚYØ]—HHÛ›Ý×Ú\ÛÊ
Bˆ˜Z[™YVÈœ[Û×ÛX[™]WØÛY[ÚY—HHÝŠX[™]K™Ù]
˜ÛY[ÚYŠHÜˆˆŠBˆØ[™Y]WÛ[™\ÈHÛ[™H›Üˆ[™H[ˆØš[[™×Û[™\Ê]JHYˆÝŠ[™K™Ù]
˜Z[™YRYŠHÜˆˆŠHOHÝŠ˜Z[™YWÚY
WBˆ[™HH™^

][H›Üˆ][H[ˆØ[™Y]WÛ[™\ÈYˆ][K™Ù]
œ^[Y[[ÙHŠHOHœÙ\WÙ\™XÝÙXš]ŠK›Û™JBˆYˆ[™H\È›Û™N‚ˆ[™HH™^

][H›Üˆ][H[ˆØ[™Y]WÛ[™\ÈYˆÝŠ][K™Ù]
™š[˜[˜Ú[™Õ\HŠHÜˆˆŠK›ÝÙ\Š
H[ˆÈœ\œÛÛ˜[‹œ\œÛÛ›™[ŸJK›Û™JBˆYˆ[™H\È›Ý›Û™N‚ˆ[™VÈœ[Û×Ù\™XÝÙXš]ÛX[™]WÚY—HHÝŠX[™]K™Ù]
šYŠJBˆ[™VÈœ[Û×ÛX[™]WÜ[H—HH[Bˆ[™VÈœ[Û×ÛX[™]WÜÝ]\È—HHÝ]\Âˆ[™VÈ›X[™]TÝ]\È—HHÝ]\Âˆ[™VÈœ[Û×ÛX[™]WÜÚYÛ—Ý\›—HHX[™]K™Ù]
œÚYÛ—Ý\›ŠHÜˆ[™K™Ù]
œ[Û×ÛX[™]WÜÚYÛ—Ý\›ŠHÜˆˆ‚ˆ[™VÈœÚYÛ—Ý\›—HH[™VÈœ[Û×ÛX[™]WÜÚYÛ—Ý\›—BˆYˆX[™]K™Ù]
˜ÛY[ÚYŠN‚ˆ[™VÈœ[ÛÐÛY[Y—HHX[™]K™Ù]
˜ÛY[ÚYŠBˆØš[[™×ÛÙÊ[™K“X[™][ÛÈ™]›Ý]°êHX[Y[[Y[‹œÝXØÙ\ÜÈ‹Ý]\ËÝŠX[™]K™Ù]
šYŠJJBˆ™XÛÝ™\™YÚ[œÝ[Y[ÈHˆžN‚ˆ™XÛÝ™\™YÚ[œÝ[Y[ÈHÜ™XÛÝ™\—Ü[Û×Ú[œÝ[Y[×Ù›Ü—ÛX[™]J[™KÝŠX[™]K™Ù]
šYŠJJBˆYˆ™XÛÝ™\™YÚ[œÝ[Y[Î‚ˆØš[[™×ÛÙÊ[™K°âXÚ0êX[˜ÚY\ˆ[ÛÈ™]›Ý]°êHX[Y[[Y[‹œÝXØÙ\ÜÈ‹ˆžÜ™XÛÝ™\™YÚ[œÝ[Y[ßH0êXÚ0êX[˜ÙJÊH‹ÝŠX[™]K™Ù]
šYŠJJBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹Ø\›š[™Ê–ÔSÓ•×H°êXÝ\0ê\˜][Ûˆ0êXÚ0êX[˜ÚY\ˆ[\ÜÜÚX›HX[™]WÚYI\È\œ›ÜI\È‹X[™]K™Ù]
šYŠKÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJJBˆÜØ]™WØš[[™×Û[™J]K[™JBˆÙ\ÜÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÂˆ›ÚÈŽˆYKˆ›Y\ÜØYÙHŽˆ“X[™]™]›Ý]°êHÝ\ˆ[ÛÈ]\ÜÛØÚpêH]HÝYÚXZ\™Kˆ‹ˆœ™XÛÝ™\™YÚ[œÝ[Y[ÈŽˆ™XÛÝ™\™YÚ[œÝ[Y[ÈYˆ[™H\È›Ý›Û™H[ÙHˆ›X[™]HŽˆÂˆšYŽˆÝŠX[™]K™Ù]
šYŠJKˆœ[HŽˆ[KˆœÝ]\ÈŽˆÝ]\Ëˆ˜ÛY[ÚYŽˆÝŠX[™]K™Ù]
˜ÛY[ÚYŠHÜˆˆŠKˆ˜Ü™X]YØ]ŽˆX[™]K™Ù]
˜Ü™X]YØ]ŠHÜˆˆ‹ˆKˆJBˆ^Ù\[ÛÐ\Q\œ›Üˆ\È^Î‚ˆÝ]\×ØÛÙHHYˆÙ]]Š^ËœÝ]\×ØÛÙH‹
HOH[ÙHL‚ˆY\ÜØYÙHH]XÝ[ˆX[™][ÛÈ›Ý]°êH]™XÈÙH•SHˆYˆÝ]\×ØÛÙHOH[ÙH›Ü›X]Ü[Û×Ù\œ›Ü—Ù›Ü—Ùœ›Û
^ÊBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆY\ÜØYÙ_JKÝ]\×ØÛÙBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹Ø\›š[™Ê–ÔSÓ•×H™XÚ\˜ÚHX[™][\ÜÜÚX›H˜Z[™YWÚYI\È\œ›ÜI\È‹˜Z[™YWÚYÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJJBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›Ü›X]Ü[Û×Ù\œ›Ü—Ù›Ü—Ùœ›Û
^Ê_JKL‚‚‚‚‚\œÜÝ
‹Ø\KØYZ[‹Ü[ÛËÝÙXšÛÚË\ÝXœØÜš\[Û‹Ù[œÝ\™HŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØYZ[—Ü[Û×ÝÙXšÛÚ×ÜÝXœØÜš\[Û—Ù[œÝ\™J
N‚ˆžN‚ˆ™]\›ˆœÛÛšYžJ[œÝ\™WÜ[Û×ÝÙXšÛÚ×ÜÝXœØÜš\[ÛŠ
JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹Ø\›š[™Ê–ÔSÓ•×HÙXšÛÚÈÝXœØÜš\[Ûˆ[œÝ\™H˜Z[Yˆ	\È‹ÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJJBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJK˜Ø[˜XÚ×Ý\›ŽˆÜ[Û×ÝÙXšÛÚ×ØØ[˜XÚ×Ý\›

_JKL‚‚\œÜÝ
‹Ø\KÜ[ÛËÝÙXšÛÚÜÈŠB\œÜÝ
‹Ø\KÝÙXšÛÚÜËÜ[ÛÈŠB™Yˆ\WÜ[Û×ÝÙXšÛÚÜÊ
N‚ˆ˜]×Ø›ÙHH™\]Y\Ý™Ù]Ù]JØXÚOUYJBˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆ]™[H
^[ØY™Ù]
™]™[ŠHÜˆ^[ØY™Ù]
\HŠHÜˆˆŠKœÝš\

Bˆ][HH^[ØY™Ù]
™]HŠHYˆ\Ú[œÝ[˜ÙJ^[ØY™Ù]
™]HŠKXÝ
H[ÙHßBˆYˆ›ÝÝ™\šYžWÜ[Û×ÝÙXšÛÚ×ÜÚYÛ˜]\™J˜]×Ø›ÙJN‚ˆ]HHØYÙ]J
NÈÜ™XÛÜ™Ü[Û×ÝÙXšÛÚÊ]K]™[][Kœ™Z™XÝY‹š[˜[YÜÚYÛ˜]\™HŠNÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆš[˜[YÜÚYÛ˜]\™HŸJKBˆ›Ü›X[^™YÙ]™[H]™[›ÝÙ\Š
Kœ™\XÙJ—È‹‹HŠBˆYˆœÙ\KY\™XÝYXš][X[™]Hˆ[ˆ›Ü›X[^™YÙ]™[‚ˆ]HHØYÙ]J
NÈ\]YHØ\WÜ[Û×ÛX[™]WÝÙXšÛÚÊ]K][JNÈÜ™XÛÜ™Ü[Û×ÝÙXšÛÚÊ]K]™[][K\]YˆYˆ\]Y[ÙHšYÛ›Ü™YŠNÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK\]YŽˆ\]YJBˆYˆœÙ\KY\™XÝYXš]XÛÛXÝ[Ûˆˆ[ˆ›Ü›X[^™YÙ]™[‚ˆ]HHØYÙ]J
NÈ\]YHØ\WÜ[Û×ØÛÛXÝ[Û—ÝÙXšÛÚÊ]K][JNÈÜ™XÛÜ™Ü[Û×ÝÙXšÛÚÊ]K]™[][K\]YˆYˆ\]Y[ÙHšYÛ›Ü™YŠNÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK\]YŽˆ\]YJBˆYˆ]™[[™˜ÛY[Z[›ÚXÙ\Èˆ›Ý[ˆ]™[[™˜ÛY[Ú[›ÚXÙHˆ›Ý[ˆ]™[‚ˆ]HHØYÙ]J
NÈÜ™XÛÜ™Ü[Û×ÝÙXšÛÚÊ]K]™[][KšYÛ›Ü™YŠNÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKšYÛ›Ü™YŽˆY_JBˆ[›ÚXÙWÚYH][K™Ù]
šYŠHÜˆ][K™Ù]
œ[Û×Ú[›ÚXÙWÚYŠBˆYˆ›Ý[›ÚXÙWÚY‚ˆ]HHØYÙ]J
NÈÜ™XÛÜ™Ü[Û×ÝÙXšÛÚÊ]K]™[][K™\œ›Üˆ‹›Z\ÜÚ[™×Ú[›ÚXÙWÚYŠNÈØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›Z\ÜÚ[™×Ú[›ÚXÙWÚYŸJKˆžN‚ˆ[›ÚXÙWÜ^[ØYHÜ[Û×Ú[›ÚXÙWÜ^[ØY
Ù]Ü[Û×Ú[›ÚXÙJ[›ÚXÙWÚY
JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹Ø\›š[™Ê–ÔSÓ•×HÙXšÛÚÈ[›ÚXÙH™Yœ™\Ú˜Z[Y[›ÚXÙWÚYI\È\œ›ÜI\È‹[›ÚXÙWÚYÜØ[š]^™WÜ[Û×Ù\œ›ÜŠÝŠ^ÊJJBˆ[›ÚXÙWÜ^[ØYHÈšYŽˆ[›ÚXÙWÚYœÝ]\ÈŽˆ][K™Ù]
œÝ]\ÈŠKœZYØ]Žˆ][K™Ù]
œZYØ]ŠK˜[[Ý[ÜZYŽˆ][K™Ù]
˜[[Ý[ÜZYŠ_B‚ˆYˆ\œÚ\ÝÚ[›ÚXÙWÙ]™[
]NˆXÝÜÝ‹[žWJHOˆXÝÜÝ‹[žWN‚ˆÈ[ÛÈØ[ˆ›ÝYžH\È™Y›Ü™HÜ™X]KY˜Y\ÈØ]™Y]È™\ÜÛœÙKˆ™XYˆÈHØ[›ÛšXØ[]HÛ›HY\ˆ™[[ÝHKÓË[™\ˆHØ[YHš[HØÚÈ\ÂˆÈHÜš]KˆØ]š[™ÈHÛ˜\ÚÝZÙ[ˆ™Y›Ü™HHÑU\ÙYÈ\˜\ÙHBˆÈ™]ÛHÜ™X]Y[›ÚXÙH
]™[ˆÚ[ˆ\ÈÙXšÛÚÈX]ÚY›ÈØØ[›ÝÊK‚ˆ\]YH˜[ÙBˆ›Üˆ[™H[ˆØš[[™×Û[™\Ê]JN‚ˆYˆÝŠ[™K™Ù]
	Ü[ÛÒ[›ÚXÙRY	ÊHÜˆ[™K™Ù]
	Ü[ÛÑ˜YY	ÊHÜˆ	ÉÊHOHÝŠ[›ÚXÙWÚY
N‚ˆØ\WÜ[Û×Ú[›ÚXÙWÜ^[Y[Ý×Øš[[™×Û[™J[™K[›ÚXÙWÜ^[ØY
BˆØš[[™×ÛÙÊ[™K	ÔZY[Y[˜XÝ\™H[ÛÈÞ[˜Ú›Ûš\ðêIË	ÜÝXØÙ\ÜÉË[™K™Ù]
	Ü^[Y[Ý]\ÉÊHÜˆ	ÉËÝŠ[›ÚXÙWÚY
JBˆÜØ]™WØš[[™×Û[™J]K[™JBˆ\]YHYBˆÙ\ÜË˜Z[™Y\Ë˜Z[™YHHÙš[™Ý˜Z[™YWØžWÜ[Û×Ú[›ÚXÙWÚY
]K[›ÚXÙWÚY
BˆYˆ˜Z[™YN‚ˆ[ˆHÜ[Û×Ú[›ÚXÙWÜÝ]J˜Z[™YJBˆØ\WÜ[Û×Ú[›ÚXÙWÜÝ]\Ê[‹[›ÚXÙWÜ^[ØY
BˆÙ\ÜÖÈ˜Z[™Y\È—HH˜Z[™Y\Âˆ\]YHYBˆÜ™XÛÜ™Ü[Û×ÝÙXšÛÚÊ]K]™[][K\]YˆYˆ\]Y[ÙHšYÛ›Ü™YŠBˆ™]\›ˆÈ\]YŽˆ\]YB‚ˆ™\Ý[HØ]ÛZX×Ý\]WÙ]J\œÚ\ÝÚ[›ÚXÙWÙ]™[
Bˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK
Šœ™\Ý[JB‚‚\™Ù]
‹ØYZ[‹Ý˜Z[™YKÏ˜Z[™YWÚY‹ØÛÛ›ØØ][Û‹X\ËÜ™]šY]ÈŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ü™]šY]×Ø\×ØÛÛ›ØØ][Û—ØžWÝ˜Z[™YJ˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆËËHÙš[™Ý˜Z[™YWØ[žWÜÙ\ÜÚ[ÛŠ]K˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›ÝÜˆ›ÝÚ\×Ø\×ÜÙ\ÜÚ[ÛŠÊN‚ˆX›Ü

BˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ™]\›ˆXZÙWÜ™\ÜÛœÙJUUÓPUSÓ—ÑTÐP“QÔ‘QÒTÕUSÓ—ÐÐSÑSQÓQTÔÐQÑKJBˆžN‚ˆË—Ü]HÙÙ[™\˜]WØ\×ØÛÛ›ØØ][Û—Ùš[\ÊËˆ‹˜Z[™YWÚY
Bˆ™]\›ˆÙ[™Ùš[J—Ü]Z[Y]\OH˜\XØ][Û‹Üˆ‹\×Ø]XÚY[Q˜[ÙKÝÛ›ØYÛ˜[YO[ÜËœ]˜˜\Ù[˜[YJ—Ü]
JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠ–ÐÓÓ•“ÐÐUSÓˆT×H\\°éÝH[\ÜÜÚX›HŠBˆ™]\›ˆXZÙWÜ™\ÜÛœÙJˆ\\°éÝHÛÛ›ØØ][ÛˆTÈ[\ÜÜÚX›HˆÚ[™\ØØ\JÝŠ^ÊJ_H‹
B‚‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ›ØØ][Û‹X\ËÜ™]šY]ÈŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ü™]šY]×Ø\×ØÛÛ›ØØ][ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆËËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›ÝÜˆ›ÝÚ\×Ø\×ÜÙ\ÜÚ[ÛŠÊN‚ˆX›Ü

BˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ™]\›ˆXZÙWÜ™\ÜÛœÙJUUÓPUSÓ—ÑTÐP“QÔ‘QÒTÕUSÓ—ÐÐSÑSQÓQTÔÐQÑKJBˆžN‚ˆË—Ü]HÙÙ[™\˜]WØ\×ØÛÛ›ØØ][Û—Ùš[\ÊËÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
Bˆ™]\›ˆÙ[™Ùš[J—Ü]Z[Y]\OH˜\XØ][Û‹Üˆ‹\×Ø]XÚY[Q˜[ÙKÝÛ›ØYÛ˜[YO[ÜËœ]˜˜\Ù[˜[YJ—Ü]
JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠ–ÐÓÓ•“ÐÐUSÓˆT×H\\°éÝH[\ÜÜÚX›HŠBˆ™]\›ˆXZÙWÜ™\ÜÛœÙJˆ\\°éÝHÛÛ›ØØ][ÛˆTÈ[\ÜÜÚX›HˆÚ[™\ØØ\JÝŠ^ÊJ_H‹
B‚‚‚‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹Ø]\Ý][Û‹Y[™YKX\ËÜ™]šY]ÈŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ü™]šY]×Ø\×Ù[žWØ]\Ý][ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆËËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›ÝÜˆ›ÝØ]]ÛX][Û—Ú\×Ù[žWØ]\Ý][ÛŠÊN‚ˆX›Ü

BˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ™]\›ˆXZÙWÜ™\ÜÛœÙJUUÓPUSÓ—ÑTÐP“QÔ‘QÒTÕUSÓ—ÐÐSÑSQÓQTÔÐQÑKJBˆžN‚ˆË—Ü]HÙÙ[™\˜]WØ\×Ù[žWØ]\Ý][Û—Ùš[\ÊËÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
Bˆ™]\›ˆÙ[™Ùš[J—Ü]Z[Y]\OH˜\XØ][Û‹Üˆ‹\×Ø]XÚY[Q˜[ÙKÝÛ›ØYÛ˜[YO[ÜËœ]˜˜\Ù[˜[YJ—Ü]
JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠ–ÐUTÕUSÓˆS•‘QHT×H\\°éÝH[\ÜÜÚX›HŠBˆ™]\›ˆXZÙWÜ™\ÜÛœÙJˆ\\°éÝH]\Ý][Ûˆ8 &Y[°êYHTÈ[\ÜÜÚX›HˆÚ[™\ØØ\JÝŠ^ÊJ_H‹
B‚‚\œ›Ý]J‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÙ\YšXØ]\™X[\Ø][Ûˆ‹Y]ÙÏVÈ‘ÑU‹”ÔÕ—JBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ý˜Z[™YWØÙ\YšXØ]WÜ™X[^˜][ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆÙ\ÜÚ[Û—ÛØš‹Ë˜Z[™YHHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÙ\ÜÚ[Û—ÛØšˆÜˆ›Ý˜Z[™YN‚ˆX›Ü

Bˆš[[™×Û[™\ÈHØš[[™×Û[™\×Ù›Ü—Ý˜Z[™YWÜÙ\ÜÚ[ÛŠ]K˜Z[™YWÚYÙ\ÜÚ[Û—ÚY
BˆÝÜ™YÙ[\ÞY\ˆHØÙ\YšXØ]WÜ™X[^˜][Û—Ù[\ÞY\Š˜Z[™YKš[[™×Û[™\ÊBˆÝX›Z]YÙ[\ÞY\ˆHØÙ\YšXØ]WÜ™X[^˜][Û—Ù[\ÞY\ŠÈ˜ÛÛ\[žWÛ˜[YHŽˆ™\]Y\Ý™›Ü›K™Ù]
˜ÛÛ\[žWÛ˜[YHŠ_JVÎŒNBˆYˆ›ÝÝÜ™YÙ[\ÞY\ˆ[™›ÝÝX›Z]YÙ[\ÞY\Ž‚ˆ™]\›ˆ™[™\—Ý[\]Jˆ˜YZ[—ØÙ\YšXØ]WÜ™X[^˜][Û—ØÛÛ\[žKš[‹ˆ]OH‘[™\š\ÙHHÝYÚXZ\™H‹ˆ˜Z[™YO]˜Z[™YKˆÙ\ÜÚ[Û—ÛØš\Ù\ÜÚ[Û—ÛØš‹ˆ›Ü›WÙ\œ›ÜJ•™]Z[^ˆ™[œÙZYÛ™\ˆH›ÛHH8 &Y[™\š\ÙKˆˆYˆ™\]Y\Ý›Y]ÙOH”ÔÕˆ[ÙHˆŠKˆ
K
Yˆ™\]Y\Ý›Y]ÙOH”ÔÕˆ[ÙHŒ
BˆžN‚ˆÛÛ^HØZ[ØÙ\YšXØ]WÜ™X[^˜][Û—ØÛÛ^
ˆÙ\ÜÚ[Û—ÛØš‹ˆ˜Z[™YKˆš[[™×Û[™\Ëˆ[\ÞY\—ÛÝ™\œšYO\ÝX›Z]YÙ[\ÞY\‹ˆ
BˆÙ\YšXØ]HHØZ[ØÙ\YšXØ]WÜ™X[^˜][Û—ÜŠÛÛ^
Bˆ^Ù\
š[S›Ý›Ý[™\œ›Ü‹[[YQ\œ›ÜŠH\È^Î‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠ–ÐÑT•Q’PÐU‘PSTÐUSÓ—Hðê[°ê\˜][Ûˆ[\ÜÜÚX›HŠBˆ™]\›ˆXZÙWÜ™\ÜÛœÙJˆÙ\YšXØ]H°êX[\Ø][Ûˆ[™\ÜÛšX›HˆÚ[™\ØØ\JÝŠ^ÊJ_H‹LÊBˆ^Ù\˜[YQ\œ›Üˆ\È^Î‚ˆ™]\›ˆXZÙWÜ™\ÜÛœÙJ[™\ØØ\JÝŠ^ÊJK
B‚ˆ˜[YHH‹H‹š›Ú[Šš[\Š›Û™K
ˆÜØY™WÙš[[˜[YWÜ\
˜Z[™YK™Ù]
›\ÝÛ˜[YHŠHÜˆ˜Z[™YK™Ù]
››ÛHŠJKˆÜØY™WÙš[[˜[YWÜ\
˜Z[™YK™Ù]
™š\œÝÛ˜[YHŠHÜˆ˜Z[™YK™Ù]
œ™[›ÛHŠJKˆ
JJBˆ™]\›ˆÙ[™Ùš[JˆÙ\YšXØ]KˆZ[Y]\OH˜\XØ][Û‹Üˆ‹ˆ\×Ø]XÚY[Q˜[ÙKˆÝÛ›ØYÛ˜[YOYˆ˜Ù\YšXØ]\™X[\Ø][Û‹^Û˜[YHÜˆ˜Z[™YWÚYKœˆ‹ˆ
B‚‚\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹Ø]\Ý][Û‹Y[™YKX\ËÜÙ[™ŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™YˆYZ[—ÜÙ[™Ø\×Ù[žWØ]\Ý][ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆË˜Z[™Y\ËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”ÝYÚXZ\™H[›Ý]˜X›HŸJKˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ™]\›ˆØØ[˜Ù[YÜ™YÚ\Ý˜][Û—Ø]]ÛX][Û—Ü™\ÜÛœÙJ
BˆYˆ›ÝØ]]ÛX][Û—Ú\×Ù[žWØ]\Ý][ÛŠÊN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ]\Ý][Ûˆ8 &Y[°êYH›ÛˆÛÛ™šYÝ\°êYHÝ\ˆÙ]H›Ü›X][ÛˆŸJKˆžN‚ˆØÞÜ]—Ü]HÙÙ[™\˜]WØ\×Ù[žWØ]\Ý][Û—Ùš[\ÊËÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆÚ]Ü[Š—Ü]œ˜ˆŠH\Èš‚ˆ[˜ÛÙYÜˆH˜\ÙM˜[˜ÛÙJšœ™XY

JK™XÛÙJ˜\ØÚZHŠBˆÝXš™XÝ[ØÛÛ[HØZ[Ø\×Ù[žWØ]\Ý][Û—Ù[XZ[
ÝŠ™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠKÊBˆ[XZ[ÛÚÈHœ™]›×ÜÙ[™Ù[XZ[
ÝŠ™Ù]
™[XZ[ŠHÜˆˆŠKœÝš\

KÝXš™XÝ[ØÛÛ[˜Z[™YO]]XÚY[ÏVÞÈ›˜[YHŽˆÜËœ]˜˜\Ù[˜[YJ—Ü]
K˜ÛÛ[Žˆ[˜ÛÙYÜŸWJBˆYˆ›Ý[XZ[ÛÚÎ‚ˆ˜Z\ÙH[[YQ\œ›ÜŠ’[\ÜÜÚX›H8 &Y[›ÞY\ˆ8 &X]\Ý][Ûˆ8 &Y[°êYHˆ0êXÚXÈ8 &Y[›ÚH[XZ[ŠBˆÙ[Ø]HÛ›Ý×Ú\ÛÊ
BˆÈ˜]\Ý][Û—Ù[™YWØ\×ÜÝ]\È—HHœÙ[‚ˆÈ˜]\Ý][Û—Ù[™YWØ\×ÙÙ[™\˜]YØ]—HH™Ù]
˜]\Ý][Û—Ù[™YWØ\×ÙÙ[™\˜]YØ]ŠHÜˆÙ[Ø]ˆÈ˜]\Ý][Û—Ù[™YWØ\×ÜÙ[Ø]—HHÙ[Ø]ˆÈ˜]\Ý][Û—Ù[™YWØ\×Ü—Ü]—HH—Ü]ˆÈ˜]\Ý][Û—Ù[™YWØ\×ÙØÞÜ]—HHØÞÜ]ˆÈ˜]\Ý][Û—Ù[™YWØ\×Ü—ÝÚÙ[ˆ—HHÜÝÜ™WÜX›X×Ùš[WÝÚÙ[Š—Ü]
BˆÈ˜]\Ý][Û—Ù[™YWØ\×Û\ÝÙ\œ›Üˆ—HHˆ‚ˆÈ\]YØ]—HHÙ[Ø]ˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKœÝ]\ÈŽˆœÙ[‹œÙ[Ø]ŽˆÙ[Ø]œÙ[Ø]ÛX™[Žˆœ—Ù]][YJÙ[Ø]
_JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠ–ÐUTÕUSÓˆS•‘QHT×H[›ÚH[\ÜÜÚX›HŠBˆY\ÜØYÙHHÝŠ^ÊHÜˆ‘\œ™]\ˆ[˜ÛÛ›YH[™[8 &Y[›ÚHH8 &X]\Ý][Ûˆ8 &Y[°êYHTËˆ‚ˆÈ˜]\Ý][Û—Ù[™YWØ\×ÜÝ]\È—HH™Ù]
˜]\Ý][Û—Ù[™YWØ\×ÜÝ]\ÈŠHÜˆœ[™[™È‚ˆÈ˜]\Ý][Û—Ù[™YWØ\×Û\ÝÙ\œ›Üˆ—HHY\ÜØYÙBˆÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
BˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆY\ÜØYÙ_JK‚‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹Ø]\Ý][Û‹Yš[‹X\ËÜ™]šY]ÈŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ü™]šY]×Ø\×Ù[™Ø]\Ý][ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆËËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›ÝÜˆ›ÝØ]]ÛX][Û—Ú\×Ù[™Ø]\Ý][ÛŠÊN‚ˆX›Ü

BˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ™]\›ˆXZÙWÜ™\ÜÛœÙJUUÓPUSÓ—ÑTÐP“QÔ‘QÒTÕUSÓ—ÐÐSÑSQÓQTÔÐQÑKJBˆžN‚ˆË—Ü]HÙÙ[™\˜]WØ\×Ù[™Ø]\Ý][Û—Ùš[\ÊËÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
Bˆ™]\›ˆÙ[™Ùš[J—Ü]Z[Y]\OH˜\XØ][Û‹Üˆ‹\×Ø]XÚY[Q˜[ÙKÝÛ›ØYÛ˜[YO[ÜËœ]˜˜\Ù[˜[YJ—Ü]
JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠ–ÐUTÕUSÓˆ’SˆT×H\\°éÝH[\ÜÜÚX›HŠBˆ™]\›ˆXZÙWÜ™\ÜÛœÙJˆ\\°éÝH]\Ý][ÛˆHš[ˆTÈ[\ÜÜÚX›HˆÚ[™\ØØ\JÝŠ^ÊJ_H‹
B‚‚\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹Ø]\Ý][Û‹Yš[‹X\ËÜÙ[™ŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™YˆYZ[—ÜÙ[™Ø\×Ù[™Ø]\Ý][ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆË˜Z[™Y\ËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”ÝYÚXZ\™H[›Ý]˜X›HŸJKˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ™]\›ˆØØ[˜Ù[YÜ™YÚ\Ý˜][Û—Ø]]ÛX][Û—Ü™\ÜÛœÙJ
BˆYˆ›ÝØ]]ÛX][Û—Ú\×Ù[™Ø]\Ý][ÛŠÊN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ]\Ý][ÛˆHš[ˆ›ÛˆÛÛ™šYÝ\°êYHÝ\ˆÙ]H›Ü›X][ÛˆŸJKˆžN‚ˆØÞÜ]—Ü]HÙÙ[™\˜]WØ\×Ù[™Ø]\Ý][Û—Ùš[\ÊËÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆÚ]Ü[Š—Ü]œ˜ˆŠH\Èš‚ˆ[˜ÛÙYÜˆH˜\ÙM˜[˜ÛÙJšœ™XY

JK™XÛÙJ˜\ØÚZHŠBˆÝXš™XÝ[ØÛÛ[HØZ[Ø\×Ù[™Ø]\Ý][Û—Ù[XZ[
ÝŠ™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÙ[™‹ˆŠKÊBˆ[XZ[ÛÚÈHœ™]›×ÜÙ[™Ù[XZ[
ÝŠ™Ù]
™[XZ[ŠHÜˆˆŠKœÝš\

KÝXš™XÝ[ØÛÛ[˜Z[™YO]]XÚY[ÏVÞÈ›˜[YHŽˆÜËœ]˜˜\Ù[˜[YJ—Ü]
K˜ÛÛ[Žˆ[˜ÛÙYÜŸWJBˆYˆ›Ý[XZ[ÛÚÎ‚ˆ˜Z\ÙH[[YQ\œ›ÜŠ’[\ÜÜÚX›H8 &Y[›ÞY\ˆ8 &X]\Ý][ÛˆHš[ˆˆ0êXÚXÈ8 &Y[›ÚH[XZ[ŠBˆÙ[Ø]HÛ›Ý×Ú\ÛÊ
BˆÈ˜]\Ý][Û—Ùš[—Ø\×ÜÝ]\È—HHœÙ[‚ˆÈ˜]\Ý][Û—Ùš[—Ø\×ÙÙ[™\˜]YØ]—HH™Ù]
˜]\Ý][Û—Ùš[—Ø\×ÙÙ[™\˜]YØ]ŠHÜˆÙ[Ø]ˆÈ˜]\Ý][Û—Ùš[—Ø\×ÜÙ[Ø]—HHÙ[Ø]ˆÈ˜]\Ý][Û—Ùš[—Ø\×Ü—Ü]—HH—Ü]ˆÈ˜]\Ý][Û—Ùš[—Ø\×ÙØÞÜ]—HHØÞÜ]ˆÈ˜]\Ý][Û—Ùš[—Ø\×Ü—ÝÚÙ[ˆ—HHÜÝÜ™WÜX›X×Ùš[WÝÚÙ[Š—Ü]
BˆÈ˜]\Ý][Û—Ùš[—Ø\×Û\ÝÙ\œ›Üˆ—HHˆ‚ˆÈ\]YØ]—HHÙ[Ø]ˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKœÝ]\ÈŽˆœÙ[‹œÙ[Ø]ŽˆÙ[Ø]œÙ[Ø]ÛX™[Žˆœ—Ù]][YJÙ[Ø]
_JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠ–ÐUTÕUSÓˆ’SˆT×H[›ÚH[\ÜÜÚX›HŠBˆY\ÜØYÙHHÝŠ^ÊHÜˆ‘\œ™]\ˆ[˜ÛÛ›YH[™[8 &Y[›ÚHH8 &X]\Ý][ÛˆHš[ˆTËˆ‚ˆÈ˜]\Ý][Û—Ùš[—Ø\×ÜÝ]\È—HH™Ù]
˜]\Ý][Û—Ùš[—Ø\×ÜÝ]\ÈŠHÜˆœ[™[™È‚ˆÈ˜]\Ý][Û—Ùš[—Ø\×Û\ÝÙ\œ›Üˆ—HHY\ÜØYÙBˆÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
BˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆY\ÜØYÙ_JK‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹Ø]]ÛX][Û‹ÜÝ]\ÈŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ý˜Z[™YWØ]]ÛX][Û—ÜÝ]\ÊÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆË˜Z[™Y\ËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”ÝYÚXZ\™H[›Ý]˜X›HŸJKˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ™]\›ˆØØ[˜Ù[YÜ™YÚ\Ý˜][Û—Ø]]ÛX][Û—Ü™\ÜÛœÙJ
BˆYˆ›ÝØ]]ÛX][Û—Ú\×Ù[˜X›Y
Ë
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›[Ù[WÛØÚÙY‹›[Ù[HŽˆ˜]]ÛX][ÛœÈŸJKÂˆÜ™Yœ™\ÚÞ[Ý\ÚYÛ—ØÛÛ™[[Û—ÜÝ]\×ÚY—Ü[™[™Ê]KË˜Z[™Y\Ë
Bˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK˜]]ÛX][Û—ÜÝ]\ÈŽˆØZ[Ý˜Z[™YWØ]]ÛX][Û—ÜÝ]\ÊËÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
_JB‚‚\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹Ø]]ÛX][Û‹ØÛÛ›ØØ][Û‹ÙÙ[™\˜]HŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™YˆYZ[—ÙÙ[™\˜]WØ\×ØÛÛ›ØØ][Û—Ø]]ÛX][ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆË˜Z[™Y\ËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”ÝYÚXZ\™H[›Ý]˜X›HŸJKˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ™]\›ˆØØ[˜Ù[YÜ™YÚ\Ý˜][Û—Ø]]ÛX][Û—Ü™\ÜÛœÙJ
BˆYˆ›ÝØ]]ÛX][Û—Ú\×Ù[˜X›Y
Ë
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›[Ù[WÛØÚÙY‹›[Ù[HŽˆ˜]]ÛX][ÛœÈŸJKÂˆYˆ›ÝÚ\×Ø\×ÜÙ\ÜÚ[ÛŠÊN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆÛÛ›ØØ][ÛˆTÈ°ê\Ù\°êYH]^›Ü›X][ÛœÈTÈŸJKˆžN‚ˆØÞÜ]—Ü]HÙÙ[™\˜]WØ\×ØÛÛ›ØØ][Û—Ùš[\ÊËÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
Bˆ›ÝÈHÛ›Ý×Ú\ÛÊ
BˆÈ˜ÛÛ›ØØ][Û—Ø\×ÜÝ]\È—HH™Ù]
˜ÛÛ›ØØ][Û—Ø\×ÜÝ]\ÈŠHÜˆ™Ù[™\˜]Y‚ˆÈ˜ÛÛ›ØØ][Û—Ø\×ÙÙ[™\˜]YØ]—HH›ÝÂˆÈ˜ÛÛ›ØØ][Û—Ø\×Ü—Ü]—HH—Ü]ˆÈ˜ÛÛ›ØØ][Û—Ø\×ÙØÞÜ]—HHØÞÜ]ˆÈ˜ÛÛ›ØØ][Û—Ø\×Û\ÝÙ\œ›Üˆ—HHˆ‚ˆÈ\]YØ]—HH›ÝÂˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKœÝ]\ÈŽˆ™Ù[™\˜]Y‹šY]×Ý\›Žˆ\›Ù›ÜŠ˜YZ[—ÝšY]×Ø\×ØÛÛ›ØØ][Ûˆ‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
_JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆY\ÜØYÙHHÝŠ^ÊHÜˆ‘\œ™]\ˆ[˜ÛÛ›YH[™[Hðê[°ê\˜][ÛˆHHÛÛ›ØØ][ÛˆTËˆ‚ˆÈ˜ÛÛ›ØØ][Û—Ø\×Û\ÝÙ\œ›Üˆ—HHY\ÜØYÙBˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆY\ÜØYÙ_JK‚\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ›ØØ][Û‹X\ËÜÙ[™ŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™YˆYZ[—ÜÙ[™Ø\×ØÛÛ›ØØ][ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆË˜Z[™Y\ËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”ÝYÚXZ\™H[›Ý]˜X›HŸJKˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ™]\›ˆØØ[˜Ù[YÜ™YÚ\Ý˜][Û—Ø]]ÛX][Û—Ü™\ÜÛœÙJ
BˆYˆ›ÝØ]]ÛX][Û—Ú\×Ù[˜X›Y
Ë
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›[Ù[WÛØÚÙY‹›[Ù[HŽˆ˜]]ÛX][ÛœÈŸJKÂˆYˆ›ÝÚ\×Ø\×ÜÙ\ÜÚ[ÛŠÊN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆÛÛ›ØØ][ÛˆTÈ°ê\Ù\°êYH]^›Ü›X][ÛœÈTÈŸJKˆ\×ÝÈHÝŠØ]]ÛX][Û—ÙØÝ[Y[ØÛÛ™šYÊÊK™Ù]
œÛYÈŠHÜˆˆŠHOHÈ‚ˆYˆ\×ÝÈ[™›Ý™Ù]
×Ý[ÜžWÙ^[WÜÙ[Ø]ŠN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ‘[ˆ][HH°ê]\ÜÚ]H0è8 &Y^[Y[ˆ0ê[Üš\]YHŸJKˆØ[—ÜÙ[™ÝÚ]Ý]ÜÚYÛ™YØÛÛ™[[ÛˆHØØ[—ÜÙ[™ØÛÛ›ØØ][Û—ÝÚ]Ý]ÜÚYÛ™YØÛÛ™[[ÛŠÊBˆYˆ›Ý\×ÝÈ[™›ÝØ[—ÜÙ[™ÝÚ]Ý]ÜÚYÛ™YØÛÛ™[[Ûˆ[™›ÝÚ\×Þ[Ý\ÚYÛ—ÜÚYÛ˜]\™WÙÛ™JÞ[Ý\ÚYÛ—ÜÝ]J
JN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ‘[ˆ][HHÚYÛ˜]\™HHHÛÛ™[[ÛˆŸJKˆžN‚ˆØÞÜ]—Ü]HÙÙ[™\˜]WØ\×ØÛÛ›ØØ][Û—Ùš[\ÊËÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÜËœ]™^\ÝÊ—Ü]
N‚ˆ˜Z\ÙH^Ù\[ÛŠ“HˆHÛÛ›ØØ][ÛˆTÈ¸ &XH\È0ê]0êHðê[°ê\°êKˆŠBˆÚ]Ü[Š—Ü]œ˜ˆŠH\Èš‚ˆ[˜ÛÙYÜˆH˜\ÙM˜[˜ÛÙJšœ™XY

JK™XÛÙJ˜\ØÚZHŠBˆYˆ\×ÝÎ‚ˆÝXš™XÝ[ØÛÛ[HZ[Ý×Ü˜XÝXÙWØÛÛ›ØØ][Û—Ù[XZ[
ÝŠ™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKÜÙ\ÜÚ[Û—ÙÙ]
Ëœ˜XÝXÙWÝ˜Z[š[™×Ù]H‹ˆŠHÜˆÜÙ\ÜÚ[Û—ÙÙ]
Ë™^[WÜ˜XÝXÙWÙ]H‹ˆŠJBˆ[ÙN‚ˆÝXš™XÝ[ØÛÛ[HØZ[Ø\×ØÛÛ›ØØ][Û—Ù[XZ[
ÝŠ™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠKÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÙ[™‹ˆŠKÊBˆ[XZ[ÛÚÈHœ™]›×ÜÙ[™Ù[XZ[
ˆÝŠ™Ù]
™[XZ[ŠHÜˆˆŠKœÝš\

KˆÝXš™XÝˆ[ØÛÛ[ˆ˜Z[™YO]ˆ]XÚY[ÏVÞÈ›˜[YHŽˆÜËœ]˜˜\Ù[˜[YJ—Ü]
K˜ÛÛ[Žˆ[˜ÛÙYÜŸWKˆ
BˆYˆ›Ý[XZ[ÛÚÎ‚ˆ˜Z\ÙH[[YQ\œ›ÜŠ’[\ÜÜÚX›H8 &Y[›ÞY\ˆHÛÛ›ØØ][Ûˆˆ0êXÚXÈ8 &Y[›ÚH[XZ[ŠBˆXœ×Ü—Ü]HÜËœ]˜XœÜ]
—Ü]
BˆYˆ›ÝØ\×ØÛÛ›ØØ][Û—Ü—Ú\×Ø[ÝÙY
Xœ×Ü—Ü]
HÜˆ›ÝÜËœ]™^\ÝÊXœ×Ü—Ü]
HÜˆÜËœ]™Ù]Ú^™JXœ×Ü—Ü]
HH‚ˆ˜Z\ÙH[[YQ\œ›ÜŠ“HˆHÛÛ›ØØ][ÛˆTÈ¸ &Y\Ý\ÈÛÛœÝ[X›H\Z\È8 &XYZ[š\Ý˜][Û‹ˆŠBˆÙ[Ø]HÛ›Ý×Ú\ÛÊ
BˆÈ˜ÛÛ›ØØ][Û—Ø\×ÜÝ]\È—HHœÙ[‚ˆÈ˜ÛÛ›ØØ][Û—Ø\×ÙÙ[™\˜]YØ]—HH™Ù]
˜ÛÛ›ØØ][Û—Ø\×ÙÙ[™\˜]YØ]ŠHÜˆÙ[Ø]ˆÈ˜ÛÛ›ØØ][Û—Ø\×ÜÙ[Ø]—HHÙ[Ø]ˆÈ˜ÛÛ›ØØ][Û—Ø\×Ü—Ü]—HH—Ü]ˆÈ˜ÛÛ›ØØ][Û—Ø\×ÙØÞÜ]—HHØÞÜ]ˆÈ˜ÛÛ›ØØ][Û—Ø\×Ü—ÝÚÙ[ˆ—HHÜÝÜ™WÜX›X×Ùš[WÝÚÙ[Š—Ü]
BˆÈ˜ÛÛ›ØØ][Û—Ø\×ÙÙ[™\˜]YÙœ›ÛH—HHÛÜ™‚ˆÈ˜ÛÛ›ØØ][Û—Ø\×ÝšY]×Ý\›—HH\›Ù›ÜŠ˜YZ[—ÝšY]×Ø\×ØÛÛ›ØØ][Ûˆ‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
BˆÈ˜ÛÛ›ØØ][Û—Ø\×Û\ÝÙ\œ›Üˆ—HHˆ‚ˆÈ˜ÛÛ›ØØ][Û—Ø]]×Û\ÝÙ\œ›Üˆ—HHˆ‚ˆÈ˜ÛÛ›ØØ][Û—Ø]]×ÜØÚY[YØ]—HHˆ‚ˆÈ\]YØ]—HHÙ[Ø]ˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKœÝ]\ÈŽˆœÙ[‹œÙ[Ø]ŽˆÙ[Ø]œÙ[Ø]ÛX™[Žˆœ—Ù]][YJÙ[Ø]
KšY]×Ý\›Žˆ\›Ù›ÜŠ˜YZ[—ÝšY]×Ø\×ØÛÛ›ØØ][Ûˆ‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
_JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠ–ÐÓÓ•“ÐÐUSÓˆT×H[›ÚH[\ÜÜÚX›HŠBˆY\ÜØYÙHHÝŠ^ÊHÜˆ‘\œ™]\ˆ[˜ÛÛ›YH[™[8 &Y[›ÚHHHÛÛ›ØØ][ÛˆTËˆ‚ˆÈ˜ÛÛ›ØØ][Û—Ø\×ÜÝ]\È—HH™Ù]
˜ÛÛ›ØØ][Û—Ø\×ÜÝ]\ÈŠHÜˆœ[™[™È‚ˆÈ˜ÛÛ›ØØ][Û—Ø\×Û\ÝÙ\œ›Üˆ—HHY\ÜØYÙBˆÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
BˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆY\ÜØYÙ_JK‚‚‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ™[[Û‹Ü™]šY]ÈŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ü™]šY]×ØÛÛ™[[ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆËËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆX›Ü

BˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ™]\›ˆXZÙWÜ™\ÜÛœÙJUUÓPUSÓ—ÑTÐP“QÔ‘QÒTÕUSÓ—ÐÐSÑSQÓQTÔÐQÑKJBˆYˆ›ÝØ]]ÛX][Û—Ú\×Ù[˜X›Y
Ë
N‚ˆX›Ü
ÊBˆžN‚ˆË—Ü]HÙÙ[™\˜]WØ\×ØÛÛ™[[Û—Ùš[\ÊËÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
Bˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ›\Ú
ˆ\\°éÝHÛÛ™[[Ûˆˆ×ÜØ[š]^™WÞ[Ý\ÚYÛ—Ù\œ›ÜŠÝŠ^ÊJ_H‹™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
JBˆXœ×Ü]HÜËœ]˜XœÜ]
—Ü]
HYˆ—Ü][ÙHˆ‚ˆ›ÛÝHÜËœ]˜XœÜ]
SÕTÒQÓ—ÐÓÓ•‘S•SÓ—ÑTŠBˆYˆ›ÝXœ×Ü]Üˆ›ÝXœ×Ü]œÝ\ÝÚ]
›ÛÝ
ÈÜËœÙ\
HÜˆ›ÝÜËœ]™^\ÝÊXœ×Ü]
N‚ˆX›Ü

Bˆ™]\›ˆÙ[™Ùš[JXœ×Ü]Z[Y]\OH˜\XØ][Û‹Üˆ‹\×Ø]XÚY[Q˜[ÙKÝÛ›ØYÛ˜[YO[ÜËœ]˜˜\Ù[˜[YJXœ×Ü]
JB‚‚ÓÓ•‘S•SÓ—Ñ’SSÒS‘×Ñ’QSÈH
˜Z[š[™×ÜšXÙH‹˜Ü—Ø[[Ý[‹œ\œÛÛ˜[Ø[[Ý[‹›Ý\—Ø[[Ý[ŠB‚‚™YˆØ\WØÛÛ™[[Û—Ùš[˜[˜Ú[™×Ü^[ØY
˜Z[™YNˆXÝÜÝ‹[žWK^[ØYˆXÝÜÝ‹[žWJHOˆ›Û™N‚ˆ›ÜˆÙ^H[ˆÓÓ•‘S•SÓ—Ñ’SSÒS‘×Ñ’QSÎ‚ˆYˆÙ^H[ˆ^[ØY‚ˆ˜Z[™YVÚÙ^WHHÝŠ^[ØY™Ù]
Ù^JHÜˆˆŠKœÝš\

B‚‚\œÜÝ
‹Ø\KÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ™[[Û‹Ùš[˜[˜Ú[™ÈŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WÝ\]WØÛÛ™[[Û—Ùš[˜[˜Ú[™ÊÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆË˜Z[™Y\ËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”ÝYÚXZ\™H[›Ý]˜X›HŸJKˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ™]\›ˆØØ[˜Ù[YÜ™YÚ\Ý˜][Û—Ø]]ÛX][Û—Ü™\ÜÛœÙJ
BˆYˆ›ÝØ]]ÛX][Û—Ú\×Ù[˜X›Y
Ë
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›[Ù[WÛØÚÙY‹›[Ù[HŽˆ˜]]ÛX][ÛœÈŸJKÂˆYˆ›ÝÙš[˜[˜Ú[™×Ü\™\—Û[Ù[WÙ[˜X›Y

N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›[Ù[WÛØÚÙY‹›[Ù[HŽˆ™š[˜[˜Ú[™ÈŸJKÂˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆØ\WØÛÛ™[[Û—Ùš[˜[˜Ú[™×Ü^[ØY
^[ØY
BˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆY_JB‚‚\œÜÝ
‹Ø\KÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ™[[Û‹ÜÚYÛ˜]\™KØÜ™X]HŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØÜ™X]WØÛÛ™[[Û—ÜÚYÛ˜]\™JÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆË˜Z[™Y\ËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”ÝYÚXZ\™H[›Ý]˜X›HŸJKˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ™]\›ˆØØ[˜Ù[YÜ™YÚ\Ý˜][Û—Ø]]ÛX][Û—Ü™\ÜÛœÙJ
BˆYˆ›ÝØ]]ÛX][Û—Ú\×Ù[˜X›Y
Ë
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›[Ù[WÛØÚÙY‹›[Ù[HŽˆ˜]]ÛX][ÛœÈŸJKÂˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆØ\WØÛÛ™[[Û—Ùš[˜[˜Ú[™×Ü^[ØY
^[ØY
BˆžN‚ˆ›Ü˜ÙWÛ™]ÈHÝŠ^[ØY™Ù]
™›Ü˜ÙWÛ™]ÈŠHÜˆˆŠK›ÝÙ\Š
H[ˆÈŒH‹YH‹žY\È‹›ÛˆŸBˆÝ]HHÜ™X]WÞ[Ý\ÚYÛ—ØÛÛ™[[Û—ÜÚYÛ˜]\™JËÙ\ÜÚ[Û—ÚY˜Z[™YWÚY›Ü˜ÙWÛ™]ÏY›Ü˜ÙWÛ™]ÊBˆÚYÛ˜]\™WÛ[šÈHÝŠÝ]K™Ù]
œÚYÛ˜]\™WÛ[šÈŠHÜˆˆŠKœÝš\

Bˆ[XZ[ÛÚÈHÙ[™Þ[Ý\ÚYÛ—ÜÚYÛ˜]\™WÛ[š×Ù[XZ[
ËÚYÛ˜]\™WÛ[šÊBˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK™[XZ[ÛÚÈŽˆ›ÛÛ
[XZ[ÛÚÊKœÝ]\ÈŽˆÝ]K™Ù]
œÝ]\ÈŠ_JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆY\ÜØYÙHHÜØ[š]^™WÞ[Ý\ÚYÛ—Ù\œ›ÜŠÝŠ^ÊJBˆÝ]HHÞ[Ý\ÚYÛ—ÜÝ]J
BˆÝ]VÈœÝ]\È—HH™\œ›Üˆ‚ˆÝ]VÈ›\ÝÙ\œ›Üˆ—HHY\ÜØYÙBˆÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
BˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆY\ÜØYÙ_JK‚‚‚\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ™[[Û‹ÛYØXÞK\ÚYÛ™YŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™YˆYZ[—ÝÙÙÛWÛYØXÞWØÛÛ™[[Û—ÜÚYÛ™Y
Ù\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆË˜Z[™Y\ËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ›\Ú
”ÝYÚXZ\™H[›Ý]˜X›Kˆ‹™\œ›ÜˆŠBˆX›Ü

BˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ›\Ú
UUÓPUSÓ—ÑTÐP“QÔ‘QÒTÕUSÓ—ÐÐSÑSQÓQTÔÐQÑK™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
™\]Y\Ýœ™Y™\œ™\ˆÜˆ\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
JBˆÚXÚÙYHÝŠ™\]Y\Ý™›Ü›K™Ù]
›YØXÞWÜÚYÛ™YŠHÜˆˆŠK›ÝÙ\Š
H[ˆÈŒH‹YH‹žY\È‹›ÛˆŸBˆ›ÝÈHÛ›Ý×Ú\ÛÊ
BˆÝ]HHÞ[Ý\ÚYÛ—ÜÝ]J
BˆYˆÚXÚÙY‚ˆÈ˜ÛÛ™[[Û—ÛYØXÞWÜÚYÛ™Y—HHYBˆÈ˜ÛÛ™[[Û—ÛYØXÞWÜÚYÛ™YØ]—HH™Ù]
˜ÛÛ™[[Û—ÛYØXÞWÜÚYÛ™YØ]ŠHÜˆ›ÝÂˆÈ˜ÛÛ™[[Û—ÜÝ]\È—HHœÚYÛ™Y‚ˆÈ˜ÛÛ™[[Û—Ø\×ÜÝ]\È—HHœÚYÛ™Y‚ˆÈ˜ÛÛ™[[Û—Ø\×ÜÚYÛ™YØ]—HH™Ù]
˜ÛÛ™[[Û—Ø\×ÜÚYÛ™YØ]ŠHÜˆÈ˜ÛÛ™[[Û—ÛYØXÞWÜÚYÛ™YØ]—BˆÝ]K\]JÂˆœÝ]\ÈŽˆ™Û™H‹ˆœÚYÛ™YØ]ŽˆÝ]K™Ù]
œÚYÛ™YØ]ŠHÜˆÈ˜ÛÛ™[[Û—ÛYØXÞWÜÚYÛ™YØ]—Kˆ›™^Ü™[Z[™\—Ø]Žˆˆ‹ˆ›\ÝÙ\œ›ÜˆŽˆˆ‹ˆ›YØXÞWÜÚYÛ™YŽˆYKˆ›YØXÞWÜÚYÛ™YØ]ŽˆÈ˜ÛÛ™[[Û—ÛYØXÞWÜÚYÛ™YØ]—KˆJBˆÜØÚY[WØÛÛ›ØØ][Û—ØY\—ØÛÛ™[[Û—ÜÚYÛ™Y
ËÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
Bˆ›\Ú
ÛÛ™[[ÛˆX\œ]pêYHÛÛ[YHðê[°ê\°êYH]ÚYÛ°êYHšXH8 &X[˜ÚY[ˆÙÚXÚY[ˆ‹œÝXØÙ\ÜÈŠBˆ[ÙN‚ˆÈ˜ÛÛ™[[Û—ÛYØXÞWÜÚYÛ™Y—HH˜[ÙBˆÈ›YØXÞWØÛÛ™[[Û—ÜÚYÛ™Y—HH˜[ÙBˆÈ˜ÛÛ™[[Û—ÛYØXÞWÜÚYÛ™YØ]—HHˆ‚ˆYˆÝ]K™Ù]
›YØXÞWÜÚYÛ™YŠH[™›ÝÝ]K™Ù]
œÚYÛ˜]\™WÜ™\]Y\ÝÚYŠH[™›ÝÝ]K™Ù]
œÚYÛ™YÜ—Ü]ŠN‚ˆÝ]K˜ÛX\Š
Bˆ[ÙN‚ˆÝ]VÈ›YØXÞWÜÚYÛ™Y—HH˜[ÙBˆYˆ™Ù]
˜ÛÛ™[[Û—Ø\×ÜÝ]\ÈŠHOHœÚYÛ™Yˆ[™›ÝÝ]K™Ù]
œÚYÛ™YÜ—Ü]ŠN‚ˆÈ˜ÛÛ™[[Û—Ø\×ÜÝ]\È—HHˆ‚ˆÈ˜ÛÛ™[[Û—Ø\×ÜÚYÛ™YØ]—HHˆ‚ˆYˆ
™Ù]
˜ÛÛ™[[Û—ÜÝ]\ÈŠHÜˆˆŠKœÝš\

K›ÝÙ\Š
HOHœÚYÛ™Yˆ[™›ÝÝ]K™Ù]
œÚYÛ™YÜ—Ü]ŠN‚ˆÈ˜ÛÛ™[[Û—ÜÝ]\È—HHœÛÛÛˆ‚ˆÈ˜ÛÛ›ØØ][Û—Ø]]×ÜØÚY[YØ]—HHˆ‚ˆ›\Ú
“X\œ]XYÙH[˜ÚY[ˆÙÚXÚY[[›[0êKˆ‹œÝXØÙ\ÜÈŠBˆÈ\]YØ]—HH›ÝÂˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ™]\›ˆ™Y\™XÝ
™\]Y\Ýœ™Y™\œ™\ˆÜˆ\›Ù›ÜŠ˜YZ[—ÜÙ\ÜÚ[Ûœ×ØÛÛ™[[ÛœÈŠJB‚\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ›ØØ][Û‹\ÚYÛ˜]\™KØÜ™X]HŠB\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ™[[Û‹Þ[Ý\ÚYÛˆŠB\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ™[[Û‹ÜÚYÛ˜]\™KØÜ™X]HŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™YˆYZ[—ØÜ™X]WØÛÛ™[[Û—ÜÚYÛ˜]\™JÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆË˜Z[™Y\ËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ›\Ú
”ÝYÚXZ\™H[›Ý]˜X›Kˆ‹™\œ›ÜˆŠBˆX›Ü

BˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ›\Ú
UUÓPUSÓ—ÑTÐP“QÔ‘QÒTÕUSÓ—ÐÐSÑSQÓQTÔÐQÑK™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
JBˆYˆ›ÝØ]]ÛX][Û—Ú\×Ù[˜X›Y
Ë
N‚ˆ›\Ú
ÙH[Ù[H\Ý™\œ›ÝZ[0êHÝ\ˆÙH\[˜Z\™KˆXÝ]™^‹[H[œÈHšXÚH\[˜Z\™Kˆ‹™\œ›ÜˆŠBˆX›Ü
ÊBˆžN‚ˆÝ]HHÜ™X]WÞ[Ý\ÚYÛ—ØÛÛ™[[Û—ÜÚYÛ˜]\™JËÙ\ÜÚ[Û—ÚY˜Z[™YWÚY›Ü˜ÙWÛ™]ÏX›ÛÛ
™\]Y\Ý™›Ü›K™Ù]
™›Ü˜ÙWÛ™]ÈŠJJBˆÚYÛ˜]\™WÛ[šÈHÝŠÝ]K™Ù]
œÚYÛ˜]\™WÛ[šÈŠHÜˆˆŠKœÝš\

BˆYˆÙ[™Þ[Ý\ÚYÛ—ÜÚYÛ˜]\™WÛ[š×Ù[XZ[
ËÚYÛ˜]\™WÛ[šÊN‚ˆ›\Ú
‘[X[™H[Ý\ÚYÛˆÜ°êpêYH]K[XZ[[›ÞpêH]HÝYÚXZ\™Kˆ‹œÝXØÙ\ÜÈŠBˆ[ÙN‚ˆ›\Ú
‘[X[™H[Ý\ÚYÛˆÜ°êpêYKXZ\È8 &YK[XZ[¸ &XH\ÈH0ê™H[›ÞpêKˆ‹™\œ›ÜˆŠBˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆY\ÜØYÙHHÜØ[š]^™WÞ[Ý\ÚYÛ—Ù\œ›ÜŠÝŠ^ÊJBˆ\›ÙÙÙ\‹™^Ù\[ÛŠ–ÖSÕTÒQÓ—HÜ™X]HÛÛ™[[ÛˆÚYÛ˜]\™H˜Z[Y˜Z[™YWÚYI\È\œ›ÜI\È‹˜Z[™YWÚYY\ÜØYÙJBˆÝ]HHÞ[Ý\ÚYÛ—ÜÝ]J
BˆÝ]VÈœÝ]\È—HH™\œ›Üˆ‚ˆÝ]VÈ›\ÝÙ\œ›Üˆ—HHY\ÜØYÙBˆÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
BˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ›\Ú
ˆ”ÚYÛ˜]\™HÛÛ™[[ÛˆˆÛY\ÜØYÙ_H‹™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
JB‚‚\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹Ø]]ÛX][ÛœËÜ™\Ù]ŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™YˆYZ[—Ü™\Ù]Ý˜Z[™YWØ]]ÛX][ÛœÊÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆË˜Z[™Y\ËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ›\Ú
”ÝYÚXZ\™H[›Ý]˜X›Kˆ‹™\œ›ÜˆŠBˆX›Ü

BˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ›\Ú
UUÓPUSÓ—ÑTÐP“QÔ‘QÒTÕUSÓ—ÐÐSÑSQÓQTÔÐQÑK™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
JBˆYˆ›ÝØ]]ÛX][Û—Ú\×Ù[˜X›Y
Ë
N‚ˆ›\Ú
ÙH[Ù[H\Ý™\œ›ÝZ[0êHÝ\ˆÙH\[˜Z\™KˆXÝ]™^‹[H[œÈHšXÚH\[˜Z\™Kˆ‹™\œ›ÜˆŠBˆX›Ü
ÊBˆžN‚ˆÜ™\Ù]Ý˜Z[™YWØ]]ÛX][ÛœÊ
BˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ›\Ú
“\È]]ÛX]\Ø][ÛœÈÛ0ê]0êH™[Z\Ù\È0è°ê\›Ëˆ›Ý\ÈÝ]™^ˆ™\™[™™HHðê[°ê\˜][Ûˆ\ÈØÝ[Y[Ëˆ‹œÝXØÙ\ÜÈŠBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆY\ÜØYÙHHÜØ[š]^™WÞ[Ý\ÚYÛ—Ù\œ›ÜŠÝŠ^ÊJBˆ\›ÙÙÙ\‹™^Ù\[ÛŠ–ÐUUÓPUSÓ”×H™[Z\ÙH0è°ê\›È[\ÜÜÚX›H˜Z[™YWÚYI\È\œ›ÜI\È‹˜Z[™YWÚYY\ÜØYÙJBˆ›\Ú
ˆ”™[Z\ÙH0è°ê\›È\È]]ÛX]\Ø][ÛœÈˆÛY\ÜØYÙ_H‹™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
JB‚‚\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ›ØØ][Û‹\ÚYÛ˜]\™KÜ™\Ù[™Y[XZ[ŠB\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ™[[Û‹ÜÚYÛ˜]\™KÜ™\Ù[™Y[XZ[ŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™YˆYZ[—Ü™\Ù[™ØÛÛ™[[Û—ÜÚYÛ˜]\™WÙ[XZ[
Ù\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆË˜Z[™Y\ËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ›\Ú
”ÝYÚXZ\™H[›Ý]˜X›Kˆ‹™\œ›ÜˆŠBˆX›Ü

BˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ›\Ú
UUÓPUSÓ—ÑTÐP“QÔ‘QÒTÕUSÓ—ÐÐSÑSQÓQTÔÐQÑK™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
JBˆÝ]HHÞ[Ý\ÚYÛ—ÜÝ]J
BˆÚYÛ˜]\™WÛ[šÈHÝŠÝ]K™Ù]
œÚYÛ˜]\™WÛ[šÈŠHÜˆˆŠKœÝš\

BˆžN‚ˆYˆÙ[™Þ[Ý\ÚYÛ—ÜÚYÛ˜]\™WÛ[š×Ù[XZ[
ËÚYÛ˜]\™WÛ[šÊN‚ˆ›\Ú
‘K[XZ[HÚYÛ˜]\™H™[›ÞpêH]HÝYÚXZ\™Kˆ‹œÝXØÙ\ÜÈŠBˆ[ÙN‚ˆ›\Ú
‘[X[™H[Ý\ÚYÛˆÜ°êpêYKXZ\È8 &YK[XZ[¸ &XH\ÈH0ê™H[›ÞpêKˆ‹™\œ›ÜˆŠBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆY\ÜØYÙHHÜØ[š]^™WÞ[Ý\ÚYÛ—Ù\œ›ÜŠÝŠ^ÊJBˆÝ]VÈœÚYÛ˜]\™WÙ[XZ[Û\ÝÙ\œ›Üˆ—HHY\ÜØYÙBˆÝ]VÈ›\ÝÙ\œ›Üˆ—HHY\ÜØYÙBˆÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
Bˆ›\Ú
Y\ÜØYÙK™\œ›ÜˆŠBˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
JB‚‚\œÜÝ
‹ØYZ[‹Ý˜Z[™Y\ËÏ˜Z[™YWÚY‹ØÛÛ›ØØ][Û‹\ÚYÛ˜]\™KÜÙ[™\™[Z[™\ˆŠB\œÜÝ
‹ØYZ[‹Ý˜Z[™Y\ËÏ˜Z[™YWÚY‹ØÛÛ™[[Û‹ÜÚYÛ˜]\™KÜÙ[™\™[Z[™\ˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™YˆYZ[—ÜÙ[™ØÛÛ™[[Û—ÜÚYÛ˜]\™WÜ™[Z[™\Š˜Z[™YWÚYˆÝŠN‚ˆÚËY\ÜØYÙHHÙ[™ØÛÛ›ØØ][Û—ÜÚYÛ˜]\™WÜ™[Z[™\Š˜Z[™YWÚY
Bˆ›\Ú
Y\ÜØYÙKœÝXØÙ\ÜÈˆYˆÚÈ[ÙH™\œ›ÜˆŠBˆ]HHØYÙ]J
BˆÙ\ÜËË˜Z[™YKÈHÙš[™Ý˜Z[™YWØžWØÛÛ›ØØ][Û—ÜÚYÛ˜]\™WÚY
]K˜Z[™YWÚY
BˆYˆÙ\ÜÈ[™˜Z[™YN‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜË™Ù]
šYŠK˜Z[™YWÚY]˜Z[™YK™Ù]
šYŠJJBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—ÜÙ\ÜÚ[ÛœÈŠJB‚‚\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ›ØØ][Û‹\ÚYÛ˜]\™KÜÙ[™\™[Z[™\ˆŠB\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ™[[Û‹ÜÚYÛ˜]\™KÜÙ[™\™[Z[™\ˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™YˆYZ[—ÜÙ[™ØÛÛ™[[Û—ÜÚYÛ˜]\™WÜ™[Z[™\—Ù›Ü—ÜÙ\ÜÚ[ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆÚËY\ÜØYÙHHÙ[™ØÛÛ›ØØ][Û—ÜÚYÛ˜]\™WÜ™[Z[™\Š˜Z[™YWÚY
Bˆ›\Ú
Y\ÜØYÙKœÝXØÙ\ÜÈˆYˆÚÈ[ÙH™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
JB‚‚\œÜÝ
‹Ú[\›˜[ØÜ›Û‹ØÛÛ›ØØ][Û‹\ÚYÛ˜]\™K\™[Z[™\œÈŠB™Yˆ[\›˜[ØÜ›Û—ØÛÛ›ØØ][Û—ÜÚYÛ˜]\™WÜ™[Z[™\œÊ
N‚ˆ^XÝYHÜË™[š\›Û‹™Ù]
Ô“Ó—ÔÑPÔ‘U‹ˆŠKœÝš\

Bˆ›ÝšYYH
™\]Y\ÝšXY\œË™Ù]
–PÜ›Û‹TÙXÜ™]ŠHÜˆ™\]Y\Ý˜\™ÜË™Ù]
ÚÙ[ˆŠHÜˆˆŠKœÝš\

BˆYˆ^XÝY[™›ÝXXË˜ÛÛ\\™WÙYÙ\Ý
^XÝY›ÝšYY
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™›Ü˜šY[ˆŸJKÂˆ™\Ý[H[—ØÛÛ›ØØ][Û—ÜÚYÛ˜]\™WÜ™[Z[™\œÊ
BˆÛÛ›ØØ][Û—Ü™[Z[™\œÈH[—Ý˜Z[š[™×ØÛÛ›ØØ][Û—Ü™[Z[™\œÊ
Bˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK
Šœ™\Ý[˜Z[š[™×ØÛÛ›ØØ][ÛœÈŽˆÛÛ›ØØ][Û—Ü™[Z[™\œßJB‚‚™YˆÝÙYÙ—ÙÛÝ™\››Ü—Ø]]Üš^™Y

HOˆ›ÛÛ‚ˆ›ÝšYYH
™\]Y\ÝšXY\œË™Ù]
–UÙYÙ‹QÛÝ™\››Ü‹UÚÙ[ˆŠHÜˆˆŠKœÝš\

Bˆ™]\›ˆ˜[YÙÛÝ™\››Ü—ÝÚÙ[Š›ÝšYY
B‚‚\œÜÝ
‹Ú[\›˜[ÝÙYÙ‹ÙÛÝ™\››Ü‹Ü™\Ù\™HŠB™Yˆ[\›˜[ÝÙYÙ—ÙÛÝ™\››Ü—Ü™\Ù\™J
N‚ˆˆˆ”°ê\Ù\™H]ÛZ\]Y[Y[[™H[š]0êH]˜[[ˆ\[ÑQÑˆHÔ“Kˆˆˆ‚ˆYˆ›ÝÝÙYÙ—ÙÛÝ™\››Ü—Ø]]Üš^™Y

N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™›Ü˜šY[ˆŸJKÂˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆÜšYÚ[ˆHÝŠ^[ØY™Ù]
›ÜšYÚ[ˆŠHÜˆˆŠKœÝš\

K˜Ø\ÙY›Û

BˆYˆÜšYÚ[ˆ›Ý[ˆÈ˜Ü›H‹™Ù\Ý[ÛœÝYÚXZ\™\È‹™Ù\Ý[ÛœÝYÚXZ\™\Ë]ÙXšÛÚÈŸN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆš[˜[YÛÜšYÚ[ˆŸJKˆžN‚ˆ™\Ý[H™\Ù\™WØÙ[˜[ÝÙYÙ—Ü™\]Y\Ý
ˆÜšYÚ[[ÜšYÚ[‹ˆÜ\˜][Û\ÝŠ^[ØY™Ù]
›Ü\˜][ÛˆŠHÜˆÙYÙ—Ü™\]Y\ÝŠKˆY]Ù\ÝŠ^[ØY™Ù]
›Y]ÙŠHÜˆ‘ÑUŠKˆ]\ÝŠ^[ØY™Ù]
œ]ŠHÜˆˆŠKˆ
Bˆ^Ù\ÙYÙ”][ÝQ^ÙYYY\È^Î‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆœ][ÝWÙ^ÙYYY‹
Š™^ËœÛ˜\ÚÝJKŽBˆ^Ù\ÙYÙ‘ÛÝ™\››Ü‘\œ›ÜŽ‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠÛÛ\]\ˆÑQÑˆÙ[˜[[™\ÜÛšX›HŠBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™ÛÝ™\››Ü—Ý[˜]˜Z[X›HŸJKLÂˆ™]\›ˆœÛÛšYžJ™\Ý[
KŒ‚‚\™Ù]
‹Ú[\›˜[ÝÙYÙ‹ÙÛÝ™\››Ü‹ÜÝ]\ÈŠB™Yˆ[\›˜[ÝÙYÙ—ÙÛÝ™\››Ü—ÜÝ]\Ê
N‚ˆYˆ›ÝÝÙYÙ—ÙÛÝ™\››Ü—Ø]]Üš^™Y

N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™›Ü˜šY[ˆŸJKÂˆžN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK
ŠÙYÙ—Ü][ÝWÜÛ˜\ÚÝ

_JKŒˆ^Ù\ÙYÙ‘ÛÝ™\››Ü‘\œ›ÜŽ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™ÛÝ™\››Ü—Ý[˜]˜Z[X›HŸJKLÂ‚‚\œÜÝ
‹Ú[\›˜[ÝÙYÙ‹ÙÛÝ™\››Ü‹ÛØÚÜËØXÜ]Z\™HŠB™Yˆ[\›˜[ÝÙYÙ—ÙÛÝ™\››Ü—ÛØÚ×ØXÜ]Z\™J
N‚ˆYˆ›ÝÝÙYÙ—ÙÛÝ™\››Ü—Ø]]Üš^™Y

N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™›Ü˜šY[ˆŸJKÂˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆ˜[YHHÝŠ^[ØY™Ù]
›˜[YHŠHÜˆˆŠKœÝš\

BˆYˆ˜[YH›Ý[ˆÂˆÙYÙ‹YÛØ˜[\™XÛÛ˜Ú[X][Ûˆ‹ÙYÙ‹[]™KX]]ÛX][Ûˆ‹ˆÙYÙ‹XÜ›K\™XÛÛ˜Ú[X][Û‹\ØÚY[H‹ˆN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆš[˜[YÛØÚÈŸJKˆžN‚ˆÜÙXÛÛ™ÈH[
^[ØY™Ù]
ÜÙXÛÛ™ÈŠHÜˆÍŒ
Bˆ^Ù\
\Q\œ›Ü‹˜[YQ\œ›ÜŠN‚ˆÜÙXÛÛ™ÈHÍŒˆžN‚ˆ™\Ý[HXÜ]Z\™WÝÙYÙ—ÙÛÝ™\››Ü—ÛX\ÙJˆ˜[YKˆÝÛ™\\ÝŠ^[ØY™Ù]
›ÝÛ™\ˆŠHÜˆ[šÛ›ÝÛˆŠKˆÜÙXÛÛ™Ï]ÜÙXÛÛ™Ëˆ
Bˆ^Ù\ÙYÙ‘ÛÝ™\››Ü‘\œ›ÜŽ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™ÛÝ™\››Ü—Ý[˜]˜Z[X›HŸJKLÂˆ™]\›ˆœÛÛšYžJ™\Ý[
KŒ‚‚\œÜÝ
‹Ú[\›˜[ÝÙYÙ‹ÙÛÝ™\››Ü‹ÛØÚÜËÜ™[X\ÙHŠB™Yˆ[\›˜[ÝÙYÙ—ÙÛÝ™\››Ü—ÛØÚ×Ü™[X\ÙJ
N‚ˆYˆ›ÝÝÙYÙ—ÙÛÝ™\››Ü—Ø]]Üš^™Y

N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™›Ü˜šY[ˆŸJKÂˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆ˜[YHHÝŠ^[ØY™Ù]
›˜[YHŠHÜˆˆŠKœÝš\

BˆYˆ˜[YH›Ý[ˆÂˆÙYÙ‹YÛØ˜[\™XÛÛ˜Ú[X][Ûˆ‹ÙYÙ‹[]™KX]]ÛX][Ûˆ‹ˆÙYÙ‹XÜ›K\™XÛÛ˜Ú[X][Û‹\ØÚY[H‹ˆN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆš[˜[YÛØÚÈŸJKˆžN‚ˆ™[X\ÙYH™[X\ÙWÝÙYÙ—ÙÛÝ™\››Ü—ÛX\ÙJˆ˜[YKÝŠ^[ØY™Ù]
ÚÙ[ˆŠHÜˆˆŠKˆ
Bˆ^Ù\ÙYÙ‘ÛÝ™\››Ü‘\œ›ÜŽ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™ÛÝ™\››Ü—Ý[˜]˜Z[X›HŸJKLÂˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKœ™[X\ÙYŽˆ™[X\ÙYJKŒ‚‚\œÜÝ
‹Ú[\›˜[ØÜ›Û‹ÝÙYÙ‹X]]ÛX][ÛˆŠB™Yˆ[\›˜[ØÜ›Û—ÝÙYÙ—Ø]]ÛX][ÛŠ
N‚ˆ^XÝYHÜË™[š\›Û‹™Ù]
Ô“Ó—ÔÑPÔ‘U‹ˆŠKœÝš\

Bˆ›ÝšYYH
™\]Y\ÝšXY\œË™Ù]
–PÜ›Û‹TÙXÜ™]ŠHÜˆ™\]Y\Ý˜\™ÜË™Ù]
ÚÙ[ˆŠHÜˆˆŠKœÝš\

BˆYˆ›Ý^XÝYÜˆ›Ý›ÝšYYÜˆ›ÝXXË˜ÛÛ\\™WÙYÙ\Ý
^XÝY›ÝšYY
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™›Ü˜šY[ˆŸJKÂˆYˆ›ÝÝÙYÙ—Û]™WÛ[ÙWÙ[˜X›Y

N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKœÝ]\ÈŽˆœÝ\Ü[™Y‹›[ÙHŽˆ™\ØX›YŸJKŒˆžN‚ˆ™\Ý[H[—ÝÙYÙ—Ø]]ÛX][Û—Û]™J
Bˆ^Ù\
ÙYÙÛÛ™šYÝ\˜][Û‘\œ›Ü‹ÙYÙ\Q\œ›Ü‹ÙYÙ‘ÛÝ™\››Ü‘\œ›ÜŠH\È^Î‚ˆ\›ÙÙÙ\‹Ø\›š[™ÊÜ›ÛˆÑQÑˆ[™\ÜÛšX›H\œ™]\I\È‹Ù]]Š^Ë˜ÛÙH‹ÙYÙ—ØÛÛ™šYÝ\˜][Û—Ù\œ›ÜˆŠJBˆ™\Ý[HÈ›ÚÈŽˆ˜[ÙKœ\X[Žˆ˜[ÙKœÝ]\ÈŽˆ™˜Z[Y‹™\œ›ÜˆŽˆÙYÙ—Ý[˜]˜Z[X›HŸBˆ^Ù\^Ù\[ÛŽ‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠ‘\œ™]\ˆXÚš\]YH™]ÞpêYHHÜ›ÛˆÑQÑˆŠBˆ™\Ý[HÈ›ÚÈŽˆ˜[ÙKœ\X[Žˆ˜[ÙKœÝ]\ÈŽˆ™˜Z[Y‹™\œ›ÜˆŽˆÙYÙ—Ý[˜]˜Z[X›HŸBˆYˆ™\Ý[™Ù]
œÝ]\ÈŠHOHœÚÚ\YÛXZ[[˜[˜ÙWÝÚ[™ÝÈŽ‚ˆ™\Ý[HÈ›ÚÈŽˆYKœÝ]\ÈŽˆœÚÚ\YÛXZ[[˜[˜ÙWÝÚ[™ÝÈ‹›[ÙHŽˆ™\Ý[™Ù]
›[ÙH‹™žWÜ[ˆŠKˆ›™^ØXÝ[ÛˆŽˆ˜]]ÛX]X×Ü™]žWÛÛ—Û™^ØÜ›ÛˆŸBˆÝ]\×ØÛÙHHHYˆ™\Ý[™Ù]
œÝ]\ÈŠHOH˜[™XYWÜ[›š[™Èˆ[ÙHLÈYˆ™\Ý[™Ù]
œÝ]\ÈŠHOH™˜Z[Yˆ[ÙHŒˆ™]\›ˆœÛÛšYžJ™\Ý[
KÝ]\×ØÛÙB‚‚\œÜÝ
‹Ú[\›˜[ØÜ›Û‹ÝÙYÙ‹\™XÛÛ˜Ú[X][ÛˆŠB™Yˆ[\›˜[ØÜ›Û—ÝÙYÙ—Ü™XÛÛ˜Ú[X][ÛŠ
N‚ˆˆˆ“[˜ÙH]H\È]Y[]Y\ÈØØ[œÈÛØ˜]^ÑU[Û›H^XÚ][Y[]]Üš\ðê\Ëˆˆˆ‚ˆ^XÝYHÜË™[š\›Û‹™Ù]
Ô“Ó—ÔÑPÔ‘U‹ˆŠKœÝš\

Bˆ›ÝšYYH
™\]Y\ÝšXY\œË™Ù]
–PÜ›Û‹TÙXÜ™]ŠHÜˆ™\]Y\Ý˜\™ÜË™Ù]
ÚÙ[ˆŠHÜˆˆŠKœÝš\

BˆYˆ›Ý^XÝYÜˆ›Ý›ÝšYYÜˆ›ÝXXË˜ÛÛ\\™WÙYÙ\Ý
^XÝY›ÝšYY
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™›Ü˜šY[ˆŸJKÂˆYˆ›Ý™XYÙ[—Ø›ÛÛ
•ÑQÑ—Ô‘PÓÓÒSPUSÓ—ÑSP“Q‹Y˜][Q˜[ÙJN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKœÝ]\ÈŽˆœÝ\Ü[™Y‹›[ÙHŽˆ™\ØX›YŸJKŒˆžN‚ˆ™\Ý[H[—ÝÙYÙ—Ø]]ÛX][Û—ÙžWÜ[Š
Bˆ^Ù\
ÙYÙÛÛ™šYÝ\˜][Û‘\œ›Ü‹ÙYÙ\Q\œ›Ü‹ÙYÙ‘ÛÝ™\››Ü‘\œ›ÜŠH\È^Î‚ˆ\›ÙÙÙ\‹Ø\›š[™Êˆ”°êXÛÛ˜Ú[X][ÛˆÑQÑˆ[™\ÜÛšX›H\œ™]\I\È‹ˆÙ]]Š^Ë˜ÛÙH‹ÙYÙ—ØÛÛ™šYÝ\˜][Û—Ù\œ›ÜˆŠKˆ
Bˆ™\Ý[HÈ›ÚÈŽˆ˜[ÙKœ\X[Žˆ˜[ÙKœÝ]\ÈŽˆ™˜Z[Y‹™\œ›ÜˆŽˆÙYÙ—Ý[˜]˜Z[X›HŸBˆ^Ù\^Ù\[ÛŽ‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠ‘\œ™]\ˆXÚš\]YH™]ÞpêYHHH°êXÛÛ˜Ú[X][ÛˆÑQÑˆŠBˆ™\Ý[HÈ›ÚÈŽˆ˜[ÙKœ\X[Žˆ˜[ÙKœÝ]\ÈŽˆ™˜Z[Y‹™\œ›ÜˆŽˆÙYÙ—Ý[˜]˜Z[X›HŸBˆYˆ™\Ý[™Ù]
œÝ]\ÈŠHOHœÚÚ\YÛXZ[[˜[˜ÙWÝÚ[™ÝÈŽ‚ˆ™\Ý[HÂˆ›ÚÈŽˆYKˆœÝ]\ÈŽˆœÚÚ\YÛXZ[[˜[˜ÙWÝÚ[™ÝÈ‹ˆ›[ÙHŽˆ™\Ý[™Ù]
›[ÙH‹™žWÜ[ˆŠKˆ›™^ØXÝ[ÛˆŽˆ˜]]ÛX]X×Ü™]žWÛÛ—Û™^Ü™XÛÛ˜Ú[X][Ûˆ‹ˆBˆÝ]\×ØÛÙHHHYˆ™\Ý[™Ù]
œÝ]\ÈŠHOH˜[™XYWÜ[›š[™Èˆ[ÙHLÈYˆ™\Ý[™Ù]
œÝ]\ÈŠHOH™˜Z[Yˆ[ÙHŒˆ™]\›ˆœÛÛšYžJ™\Ý[
KÝ]\×ØÛÙB‚‚\œÜÝ
‹Ú[\›˜[ØÜ›Û‹ØØ\Ú\^[Y[\™[Z[™\œÈŠB™Yˆ[\›˜[ØÜ›Û—ØØ\ÚÜ^[Y[Ü™[Z[™\œÊ
N‚ˆ^XÝYHÜË™[š\›Û‹™Ù]
Ô“Ó—ÔÑPÔ‘U‹ˆŠKœÝš\

Bˆ›ÝšYYH
™\]Y\ÝšXY\œË™Ù]
–PÜ›Û‹TÙXÜ™]ŠHÜˆ™\]Y\Ý˜\™ÜË™Ù]
ÚÙ[ˆŠHÜˆˆŠKœÝš\

BˆYˆ^XÝY[™›ÝXXË˜ÛÛ\\™WÙYÙ\Ý
^XÝY›ÝšYY
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™›Ü˜šY[ˆŸJKÂˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK
Šœ[—ØØ\ÚÜ^[Y[Ü™[Z[™\œÊ
_JB‚‚\œÜÝ
‹Ú[\›˜[ØÜ›Û‹ØLÜZÜÝ[™Ë\™[Z[™\œÈŠB™Yˆ[\›˜[ØÜ›Û—ØLÜÚÜÝ[™×Ü™[Z[™\œÊ
N‚ˆ^XÝYHÜË™[š\›Û‹™Ù]
Ô“Ó—ÔÑPÔ‘U‹ˆŠKœÝš\

Bˆ›ÝšYYH
™\]Y\ÝšXY\œË™Ù]
–PÜ›Û‹TÙXÜ™]ŠHÜˆ™\]Y\Ý˜\™ÜË™Ù]
ÚÙ[ˆŠHÜˆˆŠKœÝš\

BˆYˆ^XÝY[™›ÝXXË˜ÛÛ\\™WÙYÙ\Ý
^XÝY›ÝšYY
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™›Ü˜šY[ˆŸJKÂˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK
Šœ[—ØLÜÚÜÝ[™×Ü™[Z[™\œÊ
_JB‚‚\œÜÝ
‹Ú[\›˜[ØÜ›Û‹ÙØÝ[Y[\™[Z[™\œÈŠB™Yˆ[\›˜[ØÜ›Û—ÙØÝ[Y[Ü™[Z[™\œÊ
N‚ˆ^XÝYHÜË™[š\›Û‹™Ù]
Ô“Ó—ÔÑPÔ‘U‹ˆŠKœÝš\

Bˆ›ÝšYYH
™\]Y\ÝšXY\œË™Ù]
–PÜ›Û‹TÙXÜ™]ŠHÜˆˆŠKœÝš\

BˆYˆ›Ý^XÝYÜˆ›Ý›ÝšYYÜˆ›ÝXXË˜ÛÛ\\™WÙYÙ\Ý
^XÝY›ÝšYY
N‚ˆ™]\›ˆœÛÛšYžJÚÏQ˜[ÙK\œ›ÜH™›Ü˜šY[ˆŠKÂˆžWÜ[ˆH
™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßJK™Ù]
™žWÜ[ˆŠH\ÈYBˆØÝ[Y[Ü™[Z[™\œÈH[—Ø]]ÛX]X×ÙØÝ[Y[Ü™[Z[™\œÊÞ\Ë›[Ù[\Ö××Û˜[YW××KžWÜ[YžWÜ[ŠBˆ˜Z[š[™×Ø]\Ý][ÛœÈH[—Ø]]ÛX]X×Ý˜Z[š[™×Ø]\Ý][ÛœÊÞ\Ë›[Ù[\Ö××Û˜[YW××KžWÜ[YžWÜ[ŠBˆ™\Ý[HÂˆ›ÚÈŽˆ›ÛÛ
ØÝ[Y[Ü™[Z[™\œË™Ù]
›ÚÈŠJH[™›ÛÛ
˜Z[š[™×Ø]\Ý][ÛœË™Ù]
›ÚÈŠJKˆœÝ]\ÈŽˆ™žWÜ[ˆˆYˆžWÜ[ˆ[ÙH
ˆ˜ÛÛ\]YˆYˆØÝ[Y[Ü™[Z[™\œË™Ù]
›ÚÈŠH[™˜Z[š[™×Ø]\Ý][ÛœË™Ù]
›ÚÈŠH[ÙH˜ÛÛ\]YÝÚ]Ú\ÜÝY\È‚ˆ
Kˆ˜ÚXÚÙYŽˆ[
ØÝ[Y[Ü™[Z[™\œË™Ù]
˜ÚXÚÙYŠHÜˆ
H
È[
˜Z[š[™×Ø]\Ý][ÛœË™Ù]
˜ÚXÚÙYŠHÜˆ
Kˆ™YHŽˆ[
ØÝ[Y[Ü™[Z[™\œË™Ù]
™YHŠHÜˆ
H
È[
˜Z[š[™×Ø]\Ý][ÛœË™Ù]
™YHŠHÜˆ
Kˆœ›ØÙ\ÜÙYŽˆ[
ØÝ[Y[Ü™[Z[™\œË™Ù]
œ›ØÙ\ÜÙYŠHÜˆ
H
È[
˜Z[š[™×Ø]\Ý][ÛœË™Ù]
œ›ØÙ\ÜÙYŠHÜˆ
Kˆ™[XZ[×ØXØÙ\YŽˆ[
ØÝ[Y[Ü™[Z[™\œË™Ù]
™[XZ[×ØXØÙ\YŠHÜˆ
H
È[
˜Z[š[™×Ø]\Ý][ÛœË™Ù]
™[XZ[×ØXØÙ\YŠHÜˆ
KˆœÛ\×ØXØÙ\YŽˆ[
ØÝ[Y[Ü™[Z[™\œË™Ù]
œÛ\×ØXØÙ\YŠHÜˆ
Kˆ™[žWÜÙ[Žˆ[
˜Z[š[™×Ø]\Ý][ÛœË™Ù]
™[žWÜÙ[ŠHÜˆ
Kˆ™[™ÜÙ[Žˆ[
˜Z[š[™×Ø]\Ý][ÛœË™Ù]
™[™ÜÙ[ŠHÜˆ
KˆœÚÚ\YØØ[˜Ù[YŽˆ[
˜Z[š[™×Ø]\Ý][ÛœË™Ù]
œÚÚ\YØØ[˜Ù[YŠHÜˆ
Kˆ™˜Z[YŽˆ[
ØÝ[Y[Ü™[Z[™\œË™Ù]
™˜Z[YŠHÜˆ
H
È[
˜Z[š[™×Ø]\Ý][ÛœË™Ù]
™˜Z[YŠHÜˆ
Kˆ˜XÝ]˜]YÛÛˆŽˆØÝ[Y[Ü™[Z[™\œË™Ù]
˜XÝ]˜]YÛÛˆŠHÜˆ˜Z[š[™×Ø]\Ý][ÛœË™Ù]
˜XÝ]˜]YÛÛˆŠHÜˆˆ‹ˆ™ØÝ[Y[Ü™[Z[™\œÈŽˆØÝ[Y[Ü™[Z[™\œËˆ˜Z[š[™×Ø]\Ý][ÛœÈŽˆ˜Z[š[™×Ø]\Ý][ÛœËˆBˆ™]\›ˆœÛÛšYžJ™\Ý[
KŒYˆ™\Ý[È›ÚÈ—H[ÙHL‚‚‚\œÜÝ
‹Ú[\›˜[ØÜ›Û‹ØY˜ËYØÝ[Y[Ë\™[Z[™\œÈŠB™Yˆ[\›˜[ØÜ›Û—ØY˜×ÙØÝ[Y[×Ü™[Z[™\œÊ
N‚ˆ^XÝYHÜË™[š\›Û‹™Ù]
Ô“Ó—ÔÑPÔ‘U‹ˆŠKœÝš\

Bˆ›ÝšYYH
™\]Y\ÝšXY\œË™Ù]
–PÜ›Û‹TÙXÜ™]ŠHÜˆ™\]Y\Ý˜\™ÜË™Ù]
ÚÙ[ˆŠHÜˆˆŠKœÝš\

BˆYˆ›Ý^XÝYÜˆ›Ý›ÝšYYÜˆ›ÝXXË˜ÛÛ\\™WÙYÙ\Ý
^XÝY›ÝšYY
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™›Ü˜šY[ˆŸJKÂˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK
Šœ[—ØY˜×ÙØÝ[Y[×Ü™[Z[™\œÊ
_JB‚‚‘RSWÔ‘PÐTÔ‘PÒTQS•ÈH
ˆ™[ØP[YÜ˜[XXØY[^K˜ÛÛH‹ˆ˜]\™[YP[YÜ˜[XXØY[^K˜ÛÛH‹ˆ˜Û[Y[[YÜ˜[XXØY[^K˜ÛÛH‹ˆ˜Ø\ÜØ[™™P[YÜ˜[XXØY[^K˜ÛÛH‹ŠB‚‘RSWÔ‘PÐTÑ’T”ÕÓSQTÈHÂˆ˜Ø\ÜØ[™™P[YÜ˜[XXØY[^K˜ÛÛHŽˆØ\ÜØ[™™H‹ˆ˜]\™[YP[YÜ˜[XXØY[^K˜ÛÛHŽˆ]\°ê[YH‹ˆ™[ØP[YÜ˜[XXØY[^K˜ÛÛHŽˆ‘[ØH‹ˆ˜Û[Y[[YÜ˜[XXØY[^K˜ÛÛHŽˆÛ0ê[Y[‹ŸB‘RSWÔ‘PÐTÕÑPUT—ÓÐÐUSÓ”ÈHÂˆœYÙ]ŽˆÈ›X™[Žˆ”YÙ]Ý\ˆ\™Ù[œÈ‹›]]YHŽˆËMK›Û™Ú]YHŽˆ‹Ž_Kˆ˜]\š[XÈŽˆÈ›X™[Žˆ]\š[XÈ‹›]]YHŽˆŽL‹›Û™Ú]YHŽˆ‹_KŸB—ÑRSWÔ‘PÐTÔUSÕWÔÕP’‘PÕÈH
ˆÚ\]YH›ÙÜ°êÈ‹•[ˆØš™XÝYˆÛZ\ˆ‹“H\œðê]°ê\˜[˜ÙH‹•[ˆ]]\È‹“8 &Y[šYH8 &X\™[™™H‹ˆ“H˜]˜Z[8 &pê\]Z\H‹•[™HY0êYH\YðêYH‹“HÛÛ™šX[˜ÙH‹“HÛÝ\˜YÙH8 &Y\ÜØ^Y\ˆ‹•[™HXÝ[Ûˆ][H‹ˆ“HÛÛœÝ[˜ÙH‹•[ˆ™YØ\™™]Yˆ‹“8 &pêXÛÝ]H‹“HÝ\š[ÜÚ]0êH‹•[™H0êXÚ\Ú[Ûˆ\ÜÝ[pêYH‹ˆ“8 &Y[Ý\ÚX\ÛYH‹“H]Y[˜ÙH‹•[ˆ0êYšH™[]°êH‹“HÜ°êX]]š]0êH‹“8 &X][[Ûˆ]^]]™\È‹ŠB—ÑRSWÔ‘PÐTÔUSÕWÔ‘QPÐUTÈH
ˆ›Ý]œ™HH›ÚYH]^°ê]\ÜÚ]\ÈH[XZ[ˆ‹˜[œÙ›Ü›YH\ÈØœÝXÛ\È[ˆÜÜÚXš[]0ê\È‹ˆ™Û›™HHÙ[œÈ]^Y™›ÜÈH›Ý\ˆ‹™˜Z]Ü˜[™\ˆ\È[Xš][ÛœÈÛÛXÝ]™\È‹ˆœ˜\›ØÚH[ˆ]H\ÈH8 &Y^Ù[[˜ÙH‹œ\›Y]8 &X[\ˆ\ÈÚ[ˆ[œÙ[X›H‹ˆ˜ÛÛœÝZ][™H°ê]\ÜÚ]H\˜X›H‹œ°ê]°êH\È™\ÜÛÝ\˜Ù\È[œÛÝ\0éÛÛ›°êY\È‹ˆœ™[™\ÈÜ˜[™È›Ú™]ÈXØÙ\ÜÚX›\È‹™˜Z]˜pë™HH›Ý]™[\ÈÜÜ[š]0ê\È‹ˆ˜Ú[™ÙH[™H[[[Ûˆ[ˆ°ê\Ý[]‹°êXÛZ\™HH›ØÚZ[ˆ\È0èXØÛÛ\\ˆ‹ˆœ™[™›Ü˜ÙHÙH]YH›Ý\È°è\ÜÛÛœÈ[œÙ[X›H‹œ°ê\\™H\È™[\ÈšXÝÚ\™\È‹ˆ™˜Z]]˜[˜Ù\ˆpê›YH\È›Ú™]È\È\È^YÙX[È‹š[š]H0è0ê\\ÜÙ\ˆ\ÈXš]Y\È‹ˆ˜Ü°êYH8 &pê[[ˆ°êXÙ\ÜØZ\™HÝ\ˆ°ê]\ÜÚ\ˆ‹™Û›™HHH˜[]\ˆ0èÚ\]YH^0ê\šY[˜ÙH‹ˆ››Ý\È˜\›ØÚHH]]™XÈÛÛ™šX[˜ÙH‹ŠBˆÈŒNH›Ü›][][ÛœÈÛ›™[[ˆ°ê\Ù\›Ú\ˆHÎ[œðêY\ÈÜšYÚ[˜[\Ëˆ\ÂˆÈÍH™[Zpê™\ÈØ\˜[\ÜÙ[[™HÚ]][Ûˆ\Ý[˜ÝHÚ\]YH›Ý\ˆH	Ø[›°êYK‚‘RSWÔ‘PÐTÔUSÕTÈH\Jˆ
ˆžÜÝXš™XÝHÜ™YXØ]_Kˆ‹’[0êYÜ˜[HXØY[^HŠBˆ›ÜˆÝXš™XÝ[ˆÑRSWÔ‘PÐTÔUSÕWÔÕP’‘PÕÂˆ›Üˆ™YXØ]H[ˆÑRSWÔ‘PÐTÔUSÕWÔ‘QPÐUTÂŠVÎŒÍWB‚ˆÈ\ÈØ[[™\ˆ\È[X™\˜][HÙ\[ˆH\XØ][Ûˆ[œÝXYÙˆ\[™[™ÈÛ‚ˆÈ›ÛZ[š\ÎˆHŒÜ›Ûˆ]\ÝÝ[\Ü^HHÙ[Xœ˜][ÛˆÚ[ˆ[ˆ^\›˜[ˆÈÙ\šXÙH\ÈÛÝÈÜˆ[˜]˜Z[X›Kˆ™XœX\žHŽH[[[Û˜[H\Ù\È™XœX\žHŽ‚‘RSWÔ‘PÐTÓSQQVTÈHÂˆNˆ“X\šYKpê™HHY]_˜\Ú[HHðê\Ø\°êYH]Ü°êYÛÚ\™HH˜^šX[ž™_Ù[™]špê™_Ù[ÛŸ0âYÝX\™pê[Z[™_˜^[[Û™XÚY[Ÿ[^ÝZ[][Y_][[Ÿ]X[˜_]™]_š[˜_°ê[Z_X\˜Ù[›ÜÙ[[™_š\ØØ_X\š]\ßðêX˜\ÝY[ŸYÛ°êßš[˜Ù[˜\›˜\™œ˜[°éÛÚ\ß[˜[šYKÛÛ™\œÚ[ÛˆH][][_[™ðê_ÛX\ßÚ[\ßX\[™_X\˜Ù[H‹œÜ]
ŸŠKˆŽˆ‘[_0ê[Ü[™_›Z\Ù_°ê\›Ûš\]Y_YØ]_Ø\ÝÛŸ]Yðê[šY_˜XÜ]Y[[™_\Û[™_\›˜]Y0ê[ðëÜÙK›Ý™KQ[YHHÝ\™\ß°ê[^°êX]šXÙ_˜[[[ŸÛ]Y_[Y[›™_[^\ß™\›˜Y]_ØXš[ŸZ[pêY_Y\œ™KQ[ZY[Ÿ\ØX™[_^˜\™_[Ù\Ý_›Ûpê[ß™\ÝÜŸÛ›Üš[™_›ÛXZ[ˆ‹œÜ]
ŸŠKˆÎˆ]Xš[ŸÚ\›\ßÝpê[›Û0ê_Ø\Ú[Z\ŸÛ]™_ÛÛ]_°ê[XÚ]0ê_™X[Ÿœ˜[°éÛÚ\Ù_š]šY[Ÿ›ÜÚ[™_\Ý[™_›ÙšYÝY_X][_ÝZ\Ù_°ê[°êYXÝ_]šXÙ_Þ\š[_›ÜÙ\\˜™\Û0ê[Y[˜Ù_0êX_šXÝÜšY[ŸØ]\š[™_[X™\\š\ÜØ_XšXŸÛÛ˜[ŸÝÛY\ß[pêY0êY_™[š˜[Z[ˆ‹œÜ]
ŸŠKˆˆ’YÝY\ßØ[™š[™K[^[™š[™_šXÚ\™\ÚYÜ™_\°ê™_X\˜Ù[[Ÿ™X[‹P˜\\Ý_[Y_Ø]]Y\Ÿ[™\Ý[š\Û\ß[\ßY_X^[Y_]\›™_™[›ðëR›ÜÙ\[šXÙ]\™˜Z][[X_Ù]_[œÙ[Y_[^[™™_Ù[Ü™Ù\ßšY0ê_X\˜ß[Y_š]_˜[0ê\šY_Ø]\š[™_›Ø™\‹œÜ]
ŸŠKˆNˆ’°ê\°ê[ZY_›Üš\ß[\H]˜XÜ]Y\ßÞ[˜Z[ŸY]Y[˜Ù_Ú\ðê_0ê\Ú\°ê_XðíY_ÛÛ[™Ù_\Ý[_XÚ[_›Û[™_X]X\ß[š\Ù_Û›Ü°ê_\ØØ[0â\šXß]™\ß™\›˜\™[ŸÛÛœÝ[[Ÿ0â[Z[_YY\ŸÛ˜]Y[ŸÛÜY_°ê\™[™Ù\Ÿ]YÝ\Ý[ŸÙ\›XZ[Ÿ^[X\™™\™[˜[™\œš[™Kš\Ú]][ÛˆHHšY\™ÙHX\šYH‹œÜ]
ŸŠKˆŽˆ’\Ý[Ÿ›[™[™_ðê]š[ŸÛÝ[_YÛÜŸ›Ü˜™\Ú[™\pêY\™X[™_[™ž_˜\›˜X°ê_Ý^_[Ú[™_0â[\ðêY_Ù\›XZ[™_™X[‹Qœ˜[°éÛÚ\ß\°ê_0ê[Û˜Ù_›Û]X[Ú[°ê™_›ÙÛ_[˜[Ÿ]Y™^_™X[‹P˜\\Ý_›ÜÜ\Ÿ[[Y_™\›˜[™\°ê[°êY_Y\œ™H]][X\X[‹œÜ]
ŸŠKˆÎˆ•Y\œž_X\[šY[ŸÛX\ß›Ü™[[Ú[™_X\šY]_˜[Ý[X˜]][X[™[™_[šXÚ™[›ðëÛ]šY\Ÿ[œšK›ðêÛØ[Z[_Û˜[Ø\›Y[‹›Ý™KQ[YHH[ÛPØ\›Y[Ú\›Ý_œ°êY0ê\šXß\œðê™_X\š[˜_šXÝÜŸX\šYKSXY[Z[™_œšYÚ]_Úš\Ý[™_˜XÜ]Y\ß[›™H]›ØXÚ[_˜][Y_Ø[\ÛÛŸØZ[HX\_[Y]_YÛ˜XÙH‹œÜ]
ŸŠKˆˆ[ÛœÙ_[Y[ŸYY_™X[‹SX\šY_X™[ØÝ]šY[‹˜[œÙšYÝ\˜][ÛŸØpê][ŸÛZ[š\]Y_[[Ý\Ÿ]\™[ÛZ\™_Û\š\ÜÙK™X[›™_\Û]_0â]œ˜\™X\šYK\ÜÛÛ\[ÛŸ\›Y[XXÚ[_0ê[0ê™_™X[‹Q]Y\ß™\›˜\™Úš\ÝÜ_˜XœšXÙ_›ÜÙ_˜\0ê[0ê[^_ÝZ\ß˜]XÚH]YšY[Ÿ[Ûš\]Y_]YÝ\Ý[ŸØXš[™_šXXÜ™_\š\ÝYH‹œÜ]
ŸŠKˆNˆ‘Ú[\ß[™ÜšYÜ°êYÛÚ\™_›ÜØ[Y_˜pëÜÜØ_™\˜[™™Z[™K°êYÚ[™K°êZ˜[™_YšY[‹˜]]š]0êHHX\šY_[Z[Ÿ[°êßY[_\Û[˜Z\™_Z[pê_Þ\šY[‹°êHHHÜ›Ú^›Û[™0âY]™[˜]Y˜Y0êÙ_0â[Z[Y_]ž_X]Y]_X]\šXÙ_ÛÛœÝ[0êÛ_\›X[›ŸðíYH][ZY[Ÿš[˜Ù[™[˜Ù\Û\ßZXÚ[°ê\°íYH‹œÜ]
ŸŠKˆLˆ•0ê\°êÙ_0êYÙ\Ÿðê\˜\™œ˜[°éÛÚ\ß›]\Ÿœ[›ßÙ\™Ù_0ê[YÚY_[š\ßÚ\ÛZ[Ÿš\›Z[ŸÚ[œšYYðê\˜]Y\Ý_]\°ê[YK0ê\°êÙ_YÚYÙ_˜]YÝZ[ŸXß™[°ê_Y[[™_ðê[[™_0â[ÙY_™X[Ÿ›Ü™[[ŸÜ°ê\[‹[™ÝY\œ˜[™[Z]š_[Y[[™_Ú[[Ûˆ]Y_˜\˜Ú\ÜÙ_šY[™[Y_]Y[[ˆ‹œÜ]
ŸŠKˆLNˆ’\›ÛÝ\ÜØZ[ØðêX[™K0êY[ßX™\Ú\›\ßÞ[šY_™\[_Ø\š[™_Ù[Ù™œ›Þ_0ê[ÙÜ™_0ê[ÛŸX\[ŸÚš\ÝX[ŸœšXÙ_ÚYÚ[™_[™\X\™ÝY\š]_0â[\ØX™]]Y_[™Ý^_Y[Û™Y\ËX\šY_ðêXÚ[_Û0ê[Y[Úš\ÝT›Ú_›Ü˜_Ø]\š[™_[[™_ðê]™\š[‹X\šY_˜XÜ]Y\ßØ]\›š[Ÿ[™°êH‹œÜ]
ŸŠKˆLŽˆ‘›Ü™[˜Ù_š]šX[™_]šY\Ÿ˜\˜˜\˜_ðê\˜[šXÛÛ\ß[Xœ›Ú\Ù_[œšYYY\œ™_›ÛX\šXß[šY[ÛÜ™[[ŸXÚY_Ù[_š[›ÛŸ[XÙ_ØpêÛØ]Y[Ÿ\˜˜Z[Ÿ0ê[Ü[KYÛ˜XÙ_Y\œ™_œ˜[°éÛÚ\ÙKV]špê™_\›X[™Y0ê_[[X[Y[0â]Y[›™_™X[ŸØ\Ü\™ØZ[È[››ØÙ[ß]šYØZ[H˜[Z[_›ÙÙ\ŸÞ[™\Ý™H‹œÜ]
ŸŠKŸB‚‚™YˆÙZ[WÜ™XØ\Û˜[YY^J˜[YNˆ]][YK™]JHOˆÝŽ‚ˆˆˆ”™]\›ˆHÛÛ™šYÝ\™YÙ[Xœ˜][Ûˆ›Üˆ]™\žH^HÙˆHYX\‹ˆˆˆ‚ˆ^HHZ[Š˜[YK™^K[ŠRSWÔ‘PÐTÓSQQVTÖÝ˜[YK›[ÛJJBˆ™]\›ˆRSWÔ‘PÐTÓSQQVTÖÝ˜[YK›[ÛVÙ^HHWB‚‚™YˆÙZ[WÜ™XØ\Ü][ÝJ˜[YNˆ]][YK™]JHOˆXÝÜÝ‹Ý—N‚ˆˆˆ”™]\›ˆHÝX›H][ÝH›ÜˆH[]™\žH]KÚ\™YžH™]šY]È[™[XZ[ˆˆˆ‚ˆÈ[˜ÚÜˆÛˆH›Û‹[X\YX\ˆÛÈHÚ]™[ˆØ[[™\ˆ^HÙY\ÈHØ[YH][ÝBˆÈœ›ÛHÛ™HYX\ˆÈ[›Ý\‹ˆ™XœX\žHŽH[X™\˜][HÚ\™\È™XœX\žHŽ	ÜË‚ˆØ[[™\—Ù^HH]][YK™]JŒK˜[YK›[ÛZ[Š˜[YK™^KŽ
HYˆ˜[YK›[ÛOHˆ[ÙH˜[YK™^JBˆ][ÝK]]ÜˆHRSWÔ‘PÐTÔUSÕTÖÊØ[[™\—Ù^HH]][YK™]JŒKKJJK™^\×Bˆ™]\›ˆÈ^Žˆ][ÝK˜]]ÜˆŽˆ]]ÜŸB‚‚™YˆÙZ[WÜ™XØ\ÛÛ™×Ù]J˜[YNˆ]][YK™]JHOˆÝŽ‚ˆÙYZÙ^\ÈH
›[™H‹›X\™H‹›Y\˜Ü™YH‹š™]YH‹™[™™YH‹œØ[YYH‹™[X[˜ÚHŠBˆ[ÛÈH
ˆ‹š˜[šY\ˆ‹™°ê]œšY\ˆ‹›X\œÈ‹˜]œš[‹›XZH‹šZ[ˆ‹šZ[]‹˜[ðîÝ‹œÙ\[Xœ™H‹›ØÝØœ™H‹››Ý™[Xœ™H‹™0êXÙ[Xœ™HŠBˆ™]\›ˆˆžÝÙYZÙ^\ÖÝ˜[YKÙYZÙ^J
W_HÝ˜[YK™^_HÛ[ÛÖÝ˜[YK›[Û_HÝ˜[YKžYX\ŸH‚‚‚™YˆÙZ[WÜ™XØ\Ù\Ü^WÙ]J˜[YNˆ]][YK™]JHOˆÝŽ‚ˆˆˆ”™]\›ˆHÚÜ\ˆ]H\ÙY[ˆHÜ™Y][™ÈØ\™ˆˆˆ‚ˆ™]\›ˆÙZ[WÜ™XØ\ÛÛ™×Ù]J˜[YJKœœÜ]
ˆ‹JVÌB‚‚™YˆÙZ[WÜ™XØ\ÝÙX]\—Ù\ØÜš\[ÛŠÛÙNˆ[žJHOˆÝŽ‚ˆžN‚ˆÛÙHH[
ÛÙJBˆ^Ù\
\Q\œ›Ü‹˜[YQ\œ›ÜŠN‚ˆ™]\›ˆ›\ÈÛÛ™][ÛœÈpê]0ê[È™HÛÛ\È\ÜÛšX›\È‚ˆYˆÛÙHOH‚ˆ™]\›ˆ›H›Ý\›°êYHÙ\˜H[œÛÛZ[0êYH‚ˆYˆÛÙH[ˆÌKŸN‚ˆ™]\›ˆ›H›Ý\›°êYHÙ\˜H\ÜÙ^ˆ[œÛÛZ[0êYH‚ˆYˆÛÙHOHÎ‚ˆ™]\›ˆ›H›Ý\›°êYHÙ\˜HXYÙ]\ÙH‚ˆYˆÛÙH[ˆÍKN‚ˆ™]\›ˆ›H›Ý\›°êYHÙ\˜Hœ[Y]\ÙH‚ˆYˆÛÙH[ˆÍLKLËMKM‹MßN‚ˆ™]\›ˆ[ˆš\Ü]YHHœZ[™H\Ý°ê]H‚ˆYˆÛÙH[ˆÍŒKŒËK‹ßN‚ˆ™]\›ˆ™\È\ÜØYÙ\È]šY]^ÛÛ°ê]\È‚ˆYˆÛÙH[ˆÎKŸN‚ˆ™]\›ˆ[ˆš\Ü]YH8 &X]™\œÙ\È\Ý°ê]H‚ˆYˆÛÙH[ˆÍÌKÌËÍKÍËKŸN‚ˆ™]\›ˆ›H›Ý\›°êYHÙ\˜H™ZYÙ]\ÙH‚ˆYˆÛÙH[ˆÎMKM‹N_N‚ˆ™]\›ˆ›H›Ý\›°êYHÙ\˜HÜ˜YÙ]\ÙH‚ˆ™]\›ˆ›Hpê]0ê[ÈÙ\˜H˜\šXX›H‚‚‚™YˆÙZ[WÜ™XØ\ÝÙX]\—ÚXÛÛŠÛÙNˆ[žJHOˆÝŽ‚ˆˆˆ”™]\›ˆHÚ[\K[XZ[XÛY[\ØY™HÙX]\ˆXÝÙÜ˜[H›ÜˆHÓSÈÛÙKˆˆˆ‚ˆžN‚ˆÛÙHH[
ÛÙJBˆ^Ù\
\Q\œ›Ü‹˜[YQ\œ›ÜŠN‚ˆ™]\›ˆ¼'ã({î#È‚ˆYˆÛÙHOH‚ˆ™]\›ˆ¸¦ ;î#È‚ˆYˆÛÙH[ˆÌKŸN‚ˆ™]\›ˆ¼'ã);î#È‚ˆYˆÛÙHOHÎ‚ˆ™]\›ˆ¸¦ {î#È‚ˆYˆÛÙH[ˆÍKN‚ˆ™]\›ˆ¼'ã*ûî#È‚ˆYˆÛÙH[ˆÍLKLËMKM‹MËŒKŒËK‹ËKŸN‚ˆ™]\›ˆ¼'ã)ûî#È‚ˆYˆÛÙH[ˆÍÌKÌËÍKÍËKŸN‚ˆ™]\›ˆ¼'ã*;î#È‚ˆYˆÛÙH[ˆÎMKM‹N_N‚ˆ™]\›ˆ¸¦â;î#È‚ˆ™]\›ˆ¼'ã)»î#È‚‚‚™YˆÙZ[WÜ™XØ\Û˜[YY^WÛX™[
˜[YY^Nˆ[žJHOˆÝŽ‚ˆˆˆ‘›Ü›X]›ÛZ[š\ÉÈ˜[YH\ÈHœšY[™Hœ™[˜ÚÙ[Xœ˜][ÛˆX™[ˆˆˆ‚ˆ˜[YHHÝŠ˜[YY^HÜˆˆŠKœÝš\

KœÝš\
‹ˆHŠBˆYˆ›Ý˜[YHÜˆ˜[YK˜Ø\ÙY›Û

HOH›H°êHH›Ý\ˆŽ‚ˆ™]\›ˆˆ‚ˆÝÙ\™YH˜[YK˜Ø\ÙY›Û

BˆYˆÝÙ\™YœÝ\ÝÚ]
œØZ[HŠN‚ˆ™]\›ˆˆ›HØZ[K^Ý˜[YVÍÎ—KœÝš\

_H‚ˆYˆÝÙ\™YœÝ\ÝÚ]
œØZ[ŠN‚ˆ™]\›ˆˆ›HØZ[^Ý˜[YVÍŽ—KœÝš\

_H‚ˆYˆÝÙ\™YœÝ\ÝÚ]
›HØZ[HŠN‚ˆ™]\›ˆˆ›HØZ[K^Ý˜[YVÌL—KœÝš\

_H‚ˆYˆÝÙ\™YœÝ\ÝÚ]
›HØZ[ŠN‚ˆ™]\›ˆˆ›HØZ[^Ý˜[YVÎN—KœÝš\

_H‚ˆ™]\›ˆ˜[YHYˆÝÙ\™YœÝ\ÝÚ]

›HØZ[H‹›HØZ[KHŠJH[ÙHˆ›HØZ[^Ý˜[Y_H‚‚‚™Yˆ™]ÚÙZ[WÜ™XØ\ÙÜ™Y][™×ØÛÛ^
[]™\žWÙ]Nˆ]][YK™]JHOˆXÝÜÝ‹[žWN‚ˆˆˆ‘™]ÚH˜[YY^H[™Ù^IÜÈ›Ü™XØ\ÝÈ\ÙYžHHŒÜ™Y][™Ëˆˆˆ‚ˆÛÛ^ˆXÝÜÝ‹[žWHHÂˆ™]HŽˆ[]™\žWÙ]Kˆ›˜[YY^HŽˆÙZ[WÜ™XØ\Û˜[YY^J[]™\žWÙ]JKˆÙX]\ˆŽˆßKˆœ][ÝHŽˆÙZ[WÜ™XØ\Ü][ÝJ[]™\žWÙ]JKˆBˆ›ÜˆÙ^KØØ][Ûˆ[ˆRSWÔ‘PÐTÕÑPUT—ÓÐÐUSÓ”Ëš][\Ê
N‚ˆžN‚ˆ™\ÜÛœÙHH™\]Y\ÝË™Ù]
šÎ‹ËØ\K›Ü[‹[Y][Ë˜ÛÛKÝŒKÙ›Ü™XØ\Ý‹\˜[\Ï^Âˆ›]]YHŽˆØØ][Û–È›]]YH—K›Û™Ú]YHŽˆØØ][Û–È›Û™Ú]YH—Kˆ™Z[HŽˆÙX]\—ØÛÙK[\\˜]\™WÌ›WÛX^™XÚ\]][Û—Ü›Ø˜Xš[]WÛX^‹[Y^›Û™HŽˆ‘]\›ÜKÔ\š\È‹ˆœÝ\Ù]HŽˆ[]™\žWÙ]Kš\ÛÙ›Ü›X]

K™[™Ù]HŽˆ[]™\žWÙ]Kš\ÛÙ›Ü›X]

KˆK[Y[Ý]LL
Bˆ™\ÜÛœÙKœ˜Z\ÙWÙ›Ü—ÜÝ]\Ê
BˆZ[HH™\ÜÛœÙKšœÛÛŠ
K™Ù]
™Z[HŠHÜˆßBˆ™XÚ\]][Û—Ý˜[Y\ÈHZ[K™Ù]
œ™XÚ\]][Û—Ü›Ø˜Xš[]WÛX^ŠHÜˆ×Bˆ™XÚ\]][Û—Ü›Ø˜Xš[]HH
ˆ›Ý[™
›Ø]
™XÚ\]][Û—Ý˜[Y\ÖÌJJBˆYˆ™XÚ\]][Û—Ý˜[Y\È[™™XÚ\]][Û—Ý˜[Y\ÖÌH\È›Ý›Û™H[ÙH›Û™Bˆ
BˆÛÛ^ÈÙX]\ˆ—VÚÙ^WHHÂˆ[\\˜]\™HŽˆ›Ý[™
›Ø]

Z[K™Ù]
[\\˜]\™WÌ›WÛX^ŠHÜˆ×JVÌJJKˆ™\ØÜš\[ÛˆŽˆÙZ[WÜ™XØ\ÝÙX]\—Ù\ØÜš\[ÛŠ
Z[K™Ù]
ÙX]\—ØÛÙHŠHÜˆ×JVÌJKˆšXÛÛˆŽˆÙZ[WÜ™XØ\ÝÙX]\—ÚXÛÛŠ
Z[K™Ù]
ÙX]\—ØÛÙHŠHÜˆ×JVÌJKˆœ™XÚ\]][Û—Ü›Ø˜Xš[]HŽˆ™XÚ\]][Û—Ü›Ø˜Xš[]KˆBˆ^Ù\
™\]Y\ÝË”™\]Y\Ý^Ù\[Û‹˜[YQ\œ›Ü‹\Q\œ›Ü‹[™^\œ›ÜŠN‚ˆÙÙÚ[™Ë™Ù]ÙÙÙ\Š×Û˜[YW×ÊKØ\›š[™Ê’[\ÜÜÚX›HH°êXÝ\0ê\™\ˆHpê]0ê[ÈH	\È‹ØØ][Û–È›X™[—K^×Ú[™›ÏUYJBˆ™]\›ˆÛÛ^‚‚™YˆÙZ[WÜ™XØ\ÙÜ™Y][™Ê™XÚ\Y[ˆÝ‹ÛÛ^ˆXÝÜÝ‹[žWJHOˆÝŽ‚ˆš\œÝÛ˜[YHHRSWÔ‘PÐTÑ’T”ÕÓSQTË™Ù]
™XÚ\Y[›ÝÙ\Š
KˆŠBˆ\ÈHÙˆ›Ûš›Ý\ˆÙš\œÝÛ˜[Y_K›Ý\ÈÛÛ[Y\ÈH×ÙZ[WÜ™XØ\ÛÛ™×Ù]JÛÛ^ÉÙ]I×J_H—Bˆ˜[YY^HHÙZ[WÜ™XØ\Û˜[YY^WÛX™[
ÛÛ^™Ù]
›˜[YY^HŠJBˆYˆ˜[YY^N‚ˆ\Ë˜\[™
ˆ]Z›Ý\™	ÚZKÉÙ\ÝÛ˜[YY^_HHŠBˆÙ^\ÈHÈœYÙ]‹˜]\š[XÈ—Bˆ›ÜˆÙ^H[ˆÙ^\Î‚ˆØØ][Û‹›Ü™XØ\ÝHRSWÔ‘PÐTÕÑPUT—ÓÐÐUSÓ”ÖÚÙ^WK
ÛÛ^™Ù]
ÙX]\ˆŠHÜˆßJK™Ù]
Ù^JBˆYˆ›Ü™XØ\Ý‚ˆ˜Z[—Ü›Ø˜Xš[]HH›Ü™XØ\Ý™Ù]
œ™XÚ\]][Û—Ü›Ø˜Xš[]HŠBˆ›Ø˜Xš[]WÝ^Hˆˆ
›Ø˜Xš[]0êHX^[X[HH°êXÚ\]][ÛœÈˆÜ˜Z[—Ü›Ø˜Xš[]_H	JHˆYˆ˜Z[—Ü›Ø˜Xš[]H\È›Ý›Û™H[ÙHˆ‚ˆ\Ë˜\[™
ˆ›H[\0ê\˜]\™H°ê]YH0èÛØØ][Û–ÉÛX™[	×_H]Z›Ý\™	ÚZH\ÝHÙ›Ü™XØ\ÝÉÝ[\\˜]\™I×_p¬È]Ù›Ü™XØ\ÝÉÙ\ØÜš\[Û‰×_^Ü›Ø˜Xš[]WÝ^HŠBˆ[ÙN‚ˆ\Ë˜\[™
ˆ›\È°ê]š\Ú[ÛœÈpê]0ê[ÈHÛØØ][Û–ÉÛX™[	×_H™HÛÛ\È\ÜÛšX›\ÈŠBˆ™]\›ˆ‹ˆ‹š›Ú[Š\ÊKœ™\XÙJˆKˆ‹ˆHŠH
È
ˆˆYˆ\ÖËLWK™[™ÝÚ]
ˆHŠH[ÙH‹ˆŠB‚‚™YˆÙZ[WÜ™XØ\ÙÜ™Y][™×Ú[
™XÚ\Y[ˆÝ‹ÛÛ^ˆXÝÜÝ‹[žWJHOˆÝŽ‚ˆˆˆ”™[™\ˆHÜ™Y][™È\ÈHÛÛ\XÝ\›È[™[™]šYX[ÙX]\ˆØ\™Ëˆˆˆ‚ˆš\œÝÛ˜[YHHRSWÔ‘PÐTÑ’T”ÕÓSQTË™Ù]
™XÚ\Y[›ÝÙ\Š
KˆŠBˆ˜[YY^HHÙZ[WÜ™XØ\Û˜[YY^WÛX™[
ÛÛ^™Ù]
›˜[YY^HŠJBˆÙ[Xœ˜][ÛˆH
ˆ‰Ï]ˆÝ[OH›X\™Ú[‹]Ü\ØÛÛÜŽˆÍÍŽÙ›Û\Ú^™NŒM“›Ý\ÈÛÛ[Y\ÈHÚ[™\ØØ\JÙZ[WÜ™XØ\Ù\Ü^WÙ]JÛÛ^È™]H—JJ_H]]Z›Ý\™	ÚZH×	Ù\ÝÚ[™\ØØ\J˜[YY^J_HOÙ]‰ÂˆYˆ˜[YY^H[ÙHˆ‚ˆ
Bˆ][ÝHHÛÛ^™Ù]
œ][ÝHŠHÜˆÙZ[WÜ™XØ\Ü][ÝJÛÛ^È™]H—JBˆ][ÝWØØ\™H
ˆ‰Ï]ˆÝ[OH›X\™Ú[‹]ÜŒMœÙ›Û\Ú^™NŒMÙ›Û]ÙZYÚŽØÛÛÜŽˆÌMÌMMÚ]][ÛˆH›Ý\Ù]‰Âˆ‰Ï]ˆÝ[OH›X\™Ú[‹]ÜœÜY[™ÎŒM\NØ˜XÚÙÜ›Ý[™ˆÙYŒÙ™ŽØ›Ü™\‹[YÛÛYÍØÌØYYØ›Ü™\‹\˜Y]\ÎŒLØÛÛÜŽˆÌÌL™NH‰Âˆ‰Ï]ˆÝ[OH™›Û\Ú^™NŒMœÙ›Û\Ý[Nš][XÎÛ[™KZZYÚŒKH°ªÈÚ[™\ØØ\JÝŠ][ÝK™Ù]
^ŠHÜˆˆŠJ_H0®ÏÙ]‰Âˆ‰Ï]ˆÝ[OH›X\™Ú[‹]ÜœÙ›Û\Ú^™NŒLœÙ›Û]ÙZYÚŽØÛÛÜŽˆÍ™ŽH¸ %Ú[™\ØØ\JÝŠ][ÝK™Ù]
˜]]ÜˆŠHÜˆˆŠJ_OÙ]Ù]‰Âˆ
BˆÙ^\ÈHÈœYÙ]‹˜]\š[XÈ—BˆÙX]\—ØØ\™ÈH×Bˆ›ÜˆÙ^H[ˆÙ^\Î‚ˆØØ][ÛˆHRSWÔ‘PÐTÕÑPUT—ÓÐÐUSÓ”ÖÚÙ^WBˆ›Ü™XØ\ÝH
ÛÛ^™Ù]
ÙX]\ˆŠHÜˆßJK™Ù]
Ù^JBˆYˆ›Ü™XØ\Ý‚ˆXÛÛˆH[™\ØØ\JÝŠ›Ü™XØ\Ý™Ù]
šXÛÛˆŠHÜˆ¼'ã({î#ÈŠJBˆ\ØÜš\[ÛˆHÝŠ›Ü™XØ\Ý™Ù]
™\ØÜš\[ÛˆŠHÜˆ›pê]0ê[ÈH›Ý\ˆŠKœ™[[Ý™\™Yš^
›H›Ý\›°êYHÙ\˜HŠBˆ˜Z[—Ü›Ø˜Xš[]HH›Ü™XØ\Ý™Ù]
œ™XÚ\]][Û—Ü›Ø˜Xš[]HŠBˆ›Ø˜Xš[]WÚ[H
ˆ‰Ï]ˆÝ[OH›X\™Ú[‹]ÜŒÜÙ›Û\Ú^™NŒLœÙ›Û]ÙZYÚÌØÛÛÜŽˆÌÍŽXLH”š\Ü]YHH°êXÚ\]][ÛœÈˆÚ[™\ØØ\JÝŠ˜Z[—Ü›Ø˜Xš[]JJ_H	OÙ]‰ÂˆYˆ˜Z[—Ü›Ø˜Xš[]H\È›Ý›Û™H[ÙHˆ‚ˆ
BˆÙX]\—ØØ\™Ë˜\[™
ˆ‰ÏÝ[OHœY[™ÎœÝ™\XØ[X[YÛŽÜ]ˆÝ[OH›Z[‹]ÚYŒŒLÜY[™ÎŒMœNØ˜XÚÙÜ›Ý[™›[™X\‹YÜ˜YY[
LÍYYËÙY™™™‹ÙXÙ™Y™ŠNØ›Ü™\ŽŒ\ÛÛYØ˜YM™™Ø›Ü™\‹\˜Y]\ÎŒMœ‰Âˆ‰ÏX›H›ÛOHœ™\Ù[][ÛˆˆÚYHŒL	HÝ[OH™›Û\Ú^™NŒÌœÝÚYžÚXÛÛŸOÝ]ˆÝ[OH™›Û\Ú^™NŒLœÙ›Û]ÙZYÚŽÛ]\‹\ÜXÚ[™Î‹Œ™[NÝ^]˜[œÙ›Ü›N\\˜Ø\ÙNØÛÛÜŽˆÌÍŽXLHžÚ[™\ØØ\JØØ][Û–È›X™[—J_OÙ]‰Âˆ‰Ï]ˆÝ[OH›X\™Ú[‹]ÜŒœÙ›Û\Ú^™NŒŒœÙ›Û]ÙZYÚŽLØÛÛÜŽˆÌMÌMMžÚ[™\ØØ\JÝŠ›Ü™XØ\ÝÈ[\\˜]\™H—JJ_p¬ÏÙ]]ˆÝ[OH™›Û\Ú^™NŒLÜØÛÛÜŽˆÍÍMMŽHžÚ[™\ØØ\J\ØÜš\[Û‹˜Ø\][^™J
J_OÙ]žÜ›Ø˜Xš[]WÚ[OÝÝÝX›OÙ]Ý‰Âˆ
Bˆ[ÙN‚ˆÙX]\—ØØ\™Ë˜\[™
‰ÏÝ[OHœY[™Îœ]ˆÝ[OHœY[™ÎŒMœØ˜XÚÙÜ›Ý[™ˆÙŽ˜Y˜ÎØ›Ü™\‹\˜Y]\ÎŒMœØÛÛÜŽˆÍÍˆ¼'ã({î#È°ê]š\Ú[ÛœÈ[™\ÜÛšX›\È0­ÈÚ[™\ØØ\JØØ][Û–È›X™[—J_OÙ]Ý‰ÊBˆ™]\›ˆ
ˆ	ÏÝ[OHœY[™Ë]ÜŒLœ]ˆÝ[OHœY[™ÎŒŒœØ˜XÚÙÜ›Ý[™ˆÙ™™ŽØ›Ü™\ŽŒ\ÛÛYÙLMÙ™ŽØ›Ü™\‹\˜Y]\ÎŒŒØ›Þ\ÚYÝÎŒ™Ø˜JÌKNKŒŠH‰Âˆ‰Ï]ˆÝ[OH™›Û\Ú^™NŒŒÜÙ›Û]ÙZYÚŽLØÛÛÜŽˆÌMÌMM›Ûš›Ý\ˆÚ[™\ØØ\Jš\œÝÛ˜[YJ_H<'äbÏÙ]‰Âˆ‰ÞØÙ[Xœ˜][ÛŸIÂˆ‰ÏX›H›ÛOHœ™\Ù[][ÛˆˆÚYHŒL	HˆÝ[OH›X\™Ú[‹]ÜŒMžÈˆ‹š›Ú[ŠÙX]\—ØØ\™Ê_OÝÝX›OžÜ][ÝWØØ\™OÙ]ÝÝ‰Âˆ
B‚‚™YˆÙZ[WÜ™XØ\Ù]J˜[YNˆ[žJHOˆÜ[Û˜[Ù]][YK™]WN‚ˆˆˆ‘^˜XÝHØ[[™\ˆ]Hœ›ÛHH]\›ÙÙ[™[Ý\È[Y\Ý[\ÈÙH\œÚ\Ýˆˆˆ‚ˆYˆ\Ú[œÝ[˜ÙJ˜[YK]][YK™]][YJN‚ˆ™]\›ˆ˜[YK™]J
BˆYˆ\Ú[œÝ[˜ÙJ˜[YK]][YK™]JN‚ˆ™]\›ˆ˜[YBˆ™]\›ˆÜ\œÙWÙ›^X›WÙ]JÝŠ˜[YHÜˆˆŠJB‚‚™YˆÙZ[WÜ™XØ\Û˜[YJ˜Z[™YNˆXÝÜÝ‹[žWJHOˆÝŽ‚ˆ™]\›ˆÜØ[\×Ý˜Z[™YWÙ\Ü^WÛ˜[YJ˜Z[™YJB‚‚™YˆÙZ[WÜ™XØ\Ü™]š[Ý\×Û[Û
˜[YNˆ]][YK™]JHOˆ]][YK™]N‚ˆˆˆ”™]\›ˆHÛÛ\\˜X›HØ[[™\ˆ^H[ˆH™]š[Ý\È[Ûˆˆˆ‚ˆYX\‹[ÛH
˜[YKžYX\ˆHKLŠHYˆ˜[YK›[ÛOHH[ÙH
˜[YKžYX\‹˜[YK›[ÛHJBˆ™]\›ˆ˜[YKœ™\XÙJYX\^YX\‹[Û[[Û^O[Z[Š˜[YK™^KØ[[™\‹›[Û˜[™ÙJYX\‹[Û
VÌWJJB‚‚™YˆÙZ[WÜ™XØ\Ü™\ÜÙ]J[]™\žWÙ]Nˆ]][YK™]JHOˆ]][YK™]N‚ˆˆˆ”™]\›ˆH\Ý\Ú[™\ÜÈ^HÛÝ™\™YžHH[Ü›š[™È™XØ\ˆˆˆ‚ˆ™\ÜÙ]HH[]™\žWÙ]HH]][YK[YY[J^\ÏLJBˆÚ[H™\ÜÙ]KÙYZÙ^J
HHN‚ˆ™\ÜÙ]HOH]][YK[YY[J^\ÏLJBˆ™]\›ˆ™\ÜÙ]B‚‚™YˆÙZ[WÜ™XØ\Û™^Ù[]™\žWÙ]J˜[YNˆ]][YK™]JHOˆ]][YK™]N‚ˆˆˆ”™]\›ˆH™^ÙYZÙ^HÛˆÚXÚH]]ÛX]XÈ™XØ\Ø[ˆ™HÙ[ˆˆˆ‚ˆ[]™\žWÙ]HH˜[YH
È]][YK[YY[J^\ÏLJBˆÚ[H[]™\žWÙ]KÙYZÙ^J
HHN‚ˆ[]™\žWÙ]H
ÏH]][YK[YY[J^\ÏLJBˆ™]\›ˆ[]™\žWÙ]B‚‚™YˆÙZ[WÜ™XØ\Ü™Z™XÝ[Û—Ü™X\ÛÛŠ˜[YNˆ[žJHOˆÝŽ‚ˆˆˆ•˜[œÛ]H[ÛÉÜÈXXÚ[™K\™XYX›H™Z™XÝ[Ûˆ™X\ÛÛœÈ›ÜˆHX[Kˆˆˆ‚ˆ˜]ÈHÝŠ˜[YHÜˆˆŠKœÝš\

Bˆ›Ü›X[^™YH˜]Ë›ÝÙ\Š
Kœ™\XÙJ‹H‹—ÈŠKœ™\XÙJˆ‹—ÈŠBˆX™[ÈHÂˆ˜›ØÚÙYØXØÛÝ[ŽˆÛÛ\H˜[˜ØZ\™H›Ü]pêH‹ˆš[œÝY™šXÚY[Ù[™ÈŽˆ”ÛÛH[œÝY™š\Ø[‹ˆ˜ÛÜÙYØXØÛÝ[ŽˆÛÛ\H˜[˜ØZ\™HÛ0í\°êH‹ˆ˜˜[š×ØXØÛÝ[ØÛÜÙYŽˆÛÛ\H˜[˜ØZ\™HÛ0í\°êH‹ˆš[˜[YØXØÛÝ[ŽˆÛÛÜ™Û›°êY\È˜[˜ØZ\™\È[˜[Y\È‹ˆœ™]›ÚÙYÛX[™]HŽˆ“X[™]H°ê[0ê™[Y[°ê]›Ü]pêH‹ˆ››×ÛX[™]HŽˆ“X[™]H°ê[0ê™[Y[XœÙ[‹ˆ›X[™]WÛ›ÝÙ›Ý[™Žˆ“X[™]H°ê[0ê™[Y[[›Ý]˜X›H‹ˆœ™Y\ÙYØžWØ˜[šÈŽˆ”°ê[0ê™[Y[™Y\ðêH\ˆH˜[œ]YH‹ˆ™XÜ—Ù\Ü]HŽˆ”°ê[0ê™[Y[ÛÛ\Ý0êH\ˆH][Z\™H‹ˆ\Ù\—Ü™\]Y\ÝYŽˆ”™Z™][X[™0êH\ˆH][Z\™H‹ˆœ™\]Y\ÝYØžWÝ\Ù\ˆŽˆ”™Z™][X[™0êH\ˆH][Z\™H‹ˆ™\XØ]HŽˆ”°ê[0ê™[Y[[ˆÝX›H‹ˆœ™YÝ[]ÜžWÜ™X\ÛÛˆŽˆ”™Z™]Ý\ˆ˜Z\ÛÛˆ°êYÛ[Y[Z\™H‹ˆXÚšXØ[Ù\œ›ÜˆŽˆ‘\œ™]\ˆXÚš\]YH˜[˜ØZ\™H‹ˆBˆYˆ›Ü›X[^™Y[ˆX™[Î‚ˆ™]\›ˆX™[ÖÛ›Ü›X[^™YBˆ™]\›ˆ“[ÝYˆ˜[˜ØZ\™H›Ûˆ˜YZ]ˆYˆ›Ü›X[^™Y[ÙH“[ÝYˆ›ÛˆÛÛ[][š\]pêH\ˆH˜[œ]YH‚‚‚™YˆÙZ[WÜ™XØ\ØÛÛ™[[Û—Ú\×Ü[™[™ÊÙ\ÜÚ[Û—ÛØšŽˆXÝÜÝ‹[žWK˜Z[™YNˆXÝÜÝ‹[žWJHOˆ›ÛÛ‚ˆˆˆ•\ÙHHØ[YH[YÚXš[]H[™Ý]\È[\È\ÈHÛÛ™[[ÛœÈ\Ú›Ø\™ˆˆˆ‚ˆYˆÜX›X×Ý˜Z[™YWØÛÛ™[[Û—Ú\×ÜÚYÛ™Y
˜Z[™YJH[™›ÝØÛÛ™[[Û—ØÜ™X]YÛÛ—ÛÜ—ØY\—Ý˜XÚÚ[™×ÜÝ\
˜Z[™YJN‚ˆ™]\›ˆ˜[ÙBˆ˜Z[š[™×Ý\HHÝŠÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠBˆYˆ•QHˆ[ˆ˜Z[š[™×Ý\K\\Š
N‚ˆ˜YWÚÙ^HH˜YWÜÝ]\×ÝšY]Ê˜Z[™YK™Ù]
˜YWÜÝ]\ÈŠHÜˆ˜Z[™YK™Ù]
˜YWÜÝ]\×ÛX™[ŠJVÈšÙ^H—Bˆ[™™\œ™YÚÙ^HHÚ[™™\—Ý˜YWÜÝ]\×Ùœ›ÛWØXÝ[Û—Ù]\Ê˜Z[™YK™Ù]
˜YWØXÝ[Û—Ù]\ÈŠJBˆYˆ[™™\œ™YÚÙ^H[™QWÔÕUT×ÔS’Ë™Ù]
[™™\œ™YÚÙ^KLJHˆQWÔÕUT×ÔS’Ë™Ù]
˜YWÚÙ^KLJN‚ˆ˜YWÚÙ^HH[™™\œ™YÚÙ^BˆYˆQWÔÕUT×ÔS’Ë™Ù]
˜YWÚÙ^KLJHQWÔÕUT×ÔS’Ë™Ù]
™š[˜[˜Ù[Y[Ý˜[Y]Y‹
N‚ˆ™]\›ˆ˜[ÙBˆÝ]HHÞ[Ý\ÚYÛ—ÜÝ]J˜Z[™YJBˆ˜]×ÜÝ]\ÈHÛ›Ü›X[^™WÞ[Ý\ÚYÛ—ÜÝ]\ÊÝ]K™Ù]
œÝ]\ÈŠJBˆÚYÛ™YØ]HÝ]K™Ù]
œÚYÛ™YØ]ŠHÜˆ˜Z[™YK™Ù]
˜ÛÛ™[[Û—Ø\×ÜÚYÛ™YØ]ŠHÜˆ˜Z[™YK™Ù]
˜ÛÛ™[[Û—ÛYØXÞWÜÚYÛ™YØ]ŠBˆ\×Ü™\]Y\ÝH›ÛÛ
Ý]K™Ù]
œÚYÛ˜]\™WÜ™\]Y\ÝÚYŠJBˆYˆ˜]×ÜÝ]\È[ˆÈ™\œ›Üˆ‹™ÝÛ›ØYÙ\œ›Üˆ‹™XÛ[™Y‹œ™Y\ÙY‹™^\™Y‹˜Ø[˜Ù[Y‹˜Ø[˜Ù[YŸN‚ˆ™]\›ˆ˜[ÙBˆYˆÞ[Ý\ÚYÛ—ÜÚYÛ˜]\™WÛ[š×Ú\×Ù^\™Y
Ý]JHÜˆÚ\×Þ[Ý\ÚYÛ—ÜÚYÛ˜]\™WÙÛ™JÝ]JHÜˆÚYÛ™YØ]ÜˆÚ\×ÛYØXÞWÜÚYÛ™YØÛÛ™[[ÛŠ˜Z[™YJN‚ˆ™]\›ˆ˜[ÙBˆYˆ\×Ü™\]Y\Ý‚ˆ™]\›ˆÚ\×Þ[Ý\ÚYÛ—ÜÚYÛ˜]\™WÜ[™[™ÊÝ]JBˆÈØ[YHYØXÞHÝ™\œšYH\ÈH\Ú›Ø\™›ÜˆHÛÛ™[[ÛˆÚ]›ÈÙ[™\˜]Yš[K‚ˆ™]\›ˆ›ÝÝ]K™Ù]
[œÚYÛ™YÜ—Ü]ŠH[™›Ý˜Z[™YK™Ù]
˜ÛÛ™[[Û—Ø\×Ü—Ü]ŠH[™ÝŠ˜Z[™YK™Ù]
˜ÛÛ™[[Û—ÜÝ]\ÈŠHÜˆˆŠKœÝš\

K›ÝÙ\Š
HOHœÚYÛš[™È‚‚‚™YˆÙZ[WÜ™XØ\ÛX[™]WÚ\×Ü[™[™Ê][NˆXÝÜÝ‹[žWJHOˆ›ÛÛ‚ˆˆˆ”™]\›ˆÚ]\ˆHX[™]HÝ[™YYÈÚYÛš[™ËÛ›Üš[™È›ÛÙˆÙˆÚYÛ˜]\™Kˆˆˆ‚ˆÝ]\ÈHÛX\ÛX[™]WÜÝ]\Ê][K™Ù]
œ[Û×ÛX[™]WÜÝ]\ÈŠHÜˆ][K™Ù]
›X[™]TÝ]\ÈŠJBˆ\×ÛX[™]WÝ×ÜÚYÛˆH›ÛÛ
ˆ][K™Ù]
œ[Û×Ù\™XÝÙXš]ÛX[™]WÚYŠBˆÜˆ][K™Ù]
œ[Û×ÛX[™]WÜÚYÛ—Ý\›ŠBˆÜˆ][K™Ù]
œÚYÛ—Ý\›ŠBˆ
BˆÚYÛ™YØ]H›ÛÛ
ˆ][K™Ù]
œ[Û×ÛX[™]WÜÚYÛ™YØ]ŠBˆÜˆ][K™Ù]
›X[™]TÚYÛ™Y]ŠBˆÜˆ][K™Ù]
›X[™]WÜÚYÛ™YØ]ŠBˆ
Bˆ™]\›ˆÝ]\ÈOHœ[™[™Èˆ[™\×ÛX[™]WÝ×ÜÚYÛˆ[™›ÝÚYÛ™YØ]‚‚™YˆZ[ÙZ[WÜ™XØ\Ù]J]NˆXÝÜÝ‹[žWK™\ÜÙ]Nˆ]][YK™]JHOˆXÝÜÝ‹[žWN‚ˆˆˆZ[H™]š[Ý\ËY^HÜ\˜][Û˜[Û˜\ÚÝÚ]Ý]]]][™ÈÝÜ™Y]Kˆˆˆ‚ˆžN‚ˆš[Ü—ÞYX\—Ù]HH™\ÜÙ]Kœ™\XÙJYX\\™\ÜÙ]KžYX\ˆHJBˆ^Ù\˜[YQ\œ›ÜŽˆÈŽH™XœX\žNˆÛÛ\\™HÚ]H\Ý^HÙˆ™XœX\žH‹LK‚ˆš[Ü—ÞYX\—Ù]HH™\ÜÙ]Kœ™\XÙJYX\\™\ÜÙ]KžYX\ˆHK^OLŽ
BˆØ[\ÈHÈœ™]™[YHŽˆ˜ÛÝ[Žˆ™›Ü›X][ÛœÈŽˆß_Bˆ[ÛÜ™]™[YHHˆÛÛ\\š\ÛÛ—Ù]\ÈHÂˆœ™]š[Ý\×Ù^HŽˆ™\ÜÙ]HH]][YK[YY[J^\ÏLJKˆœ™]š[Ý\×ÝÙYZÈŽˆ™\ÜÙ]HH]][YK[YY[J^\ÏMÊKˆœ™]š[Ý\×Û[ÛŽˆÙZ[WÜ™XØ\Ü™]š[Ý\×Û[Û
™\ÜÙ]JKˆœ™]š[Ý\×ÞYX\ˆŽˆš[Ü—ÞYX\—Ù]KˆBˆÛÛ\\š\ÛÛ—ÜØ[\ÈHÚÙ^NˆÈ™]HŽˆ]Kœ™]™[YHŽˆ˜ÛÝ[ŽˆH›ÜˆÙ^K]H[ˆÛÛ\\š\ÛÛ—Ù]\Ëš][\Ê
_Bˆ[™[™×ÜÚYÛ˜]\™\Îˆ\ÝÑXÝÜÝ‹Ý—WHH×Bˆ[™[™×ÛX[™]\×ØžWÝ˜Z[™YNˆXÝÜÝ‹XÝÜÝ‹Ý—WHHßBˆ[˜ÛÛ\]WÝ\ÛÛZ[™Îˆ\ÝÑXÝÜÝ‹Ý—WHH×BˆÛ˜\×Ü[™[™Îˆ\ÝÑXÝÜÝ‹Ý—WHH×BˆÙ^WÙ]\Îˆ\ÝÑXÝÜÝ‹Ý—WHH×Bˆ˜YWÙ›ÛÝ×Ý\HÂˆ›™]×Ü™\]Y\ÝÈŽˆˆ›]œ™]ÌWÝ˜[Y]YŽˆˆ›]œ™]Ì—Ý˜[Y]YŽˆˆ˜Ù\YšXØ][Û—ÛØZ[™YŽˆˆBˆ˜YWÙ›ÛÝ×Ý\Û˜[Y\ÈHÚÙ^Nˆ×H›ÜˆÙ^H[ˆ˜YWÙ›ÛÝ×Ý\BˆÙ^HH™\ÜÙ]H
È]][YK[YY[J^\ÏLJB‚ˆ˜[Y]YØÛ˜\ÈHÈ˜[YH‹˜[Y0êH‹˜[YYH‹˜[Y0êYH‹˜XØÙ\Y‹˜XØÙ\H‹˜XØÙ\0êH‹˜XÝ]™H‹˜XÝYˆ‹™˜]›Ü˜X›H‹™Û™HŸBˆ›ÜˆÙ\ÜÚ[Û—ÛØšˆ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JHÜˆ×N‚ˆYˆ›Ý\Ú[œÝ[˜ÙJÙ\ÜÚ[Û—ÛØš‹XÝ
HÜˆÙ\ÜÚ[Û—ÛØš‹™Ù]
˜\˜Ú]™YŠHÜˆÚ\×ÝÙYÙ—ÛXY×ÜÙ\ÜÚ[ÛŠÙ\ÜÚ[Û—ÛØšŠN‚ˆÛÛ[YBˆ˜Z[š[™×Ý\HHÝŠÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹˜Z[š[™×Ý\H‹ˆŠHÜˆÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹›˜[YH‹ˆŠHÜˆ‘›Ü›X][ÛˆŠKœÝš\

Bˆ˜Z[š[™×ÛX™[HÜØ[\×Ý˜Z[š[™×ÛX™[
˜Z[š[™×Ý\JBˆÝ\Ù]HHÜÙ\ÜÚ[Û—ÜÝ\Ù]JÙ\ÜÚ[Û—ÛØšŠBˆ[™Ù]HHÙZ[WÜ™XØ\Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹™]WÙ[™‹ˆŠJHÜˆÝ\Ù]BˆÙ\ÜÚ[Û—ÛX™[HˆžÙ›Ü›X][Û—ÛX™[
˜Z[š[™×Ý\JHÜˆ˜Z[š[™×Ý\_H0­ÈÙœ—Ù]JÝ\Ù]Kš\ÛÙ›Ü›X]

JHYˆÝ\Ù]H[ÙH	Ù]H0èÛÛ™š\›Y\‰ßH‚ˆÙ\ÜÚ[Û—Û˜[YHHÝŠÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹›˜[YH‹ˆŠHÜˆˆŠKœÝš\

Bˆ›Ü›X][Û—Û˜[YHHˆ0­È‹š›Ú[ŠXÝ™œ›ÛZÙ^\Ê\›Üˆ\[ˆ
Ù\ÜÚ[Û—Û˜[YK›Ü›X][Û—ÛX™[
˜Z[š[™×Ý\JHÜˆ˜Z[š[™×Ý\JHYˆ\
JBˆ]WÜ˜[™ÙHHˆ™HÙœ—Ù]JÝ\Ù]Kš\ÛÙ›Ü›X]

JHYˆÝ\Ù]H[ÙH	Ù]H0èÛÛ™š\›Y\‰ßH]HÙœ—Ù]J[™Ù]Kš\ÛÙ›Ü›X]

JHYˆ[™Ù]H[ÙH	Ù]H0èÛÛ™š\›Y\‰ßH‚ˆYˆÝ\Ù]HOHÙ^H
È]][YK[YY[J^\ÏLJN‚ˆÙ^WÙ]\Ë˜\[™
È›˜[YHŽˆ‘0êX]H›Ü›X][Ûˆ[XZ[ˆ‹™]Z[ŽˆˆžÙ›Ü›X][Û—Û˜[Y_H0­ÈÙ]WÜ˜[™Ù_HŸJB‚ˆ^[WÙ]\ÈH×Bˆ›Üˆ^[WÚÙ^K^[WÛX™[[ˆ
ˆ
™^[WÙ]H‹‘^[Y[ˆŠK
™^[WÝ[ÜžWÙ]H‹‘^[Y[ˆ0ê[Üš\]YHŠKˆ
™^[WÜ˜XÝXÙWÙ]H‹‘^[Y[ˆ˜]\]YHŠK
œÜÚX\Ù^[WÙ]H‹‘^[Y[ˆÔÒPTŠKˆ
N‚ˆ^[WÙ]HHÙZ[WÜ™XØ\Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹^[WÚÙ^KˆŠJBˆYˆ^[WÙ]H[™
^[WÙ]K^[WÛX™[
H›Ý[ˆ^[WÙ]\Î‚ˆ^[WÙ]\Ë˜\[™

^[WÙ]K^[WÛX™[
JBˆ›Üˆ^[WÙ]K^[WÛX™[[ˆ^[WÙ]\Î‚ˆ^\×Ý[[Ù^[HH
^[WÙ]HHÙ^JK™^\ÂˆYˆ^\×Ý[[Ù^[H›Ý[ˆÌKßN‚ˆÛÛ[YBˆ]HHˆžÙ^[WÛX™[H[XZ[ˆˆYˆ^\×Ý[[Ù^[HOHH[ÙHˆžÙ^[WÛX™[H[œÈÈ›Ý\œÈ‚ˆ™[Z[™\ˆHˆ0­È[œÙ^ˆ0èðê[°ê\™\ˆ\ÈÜÜÚY\œÈ8 &Y^[Y[ˆˆYˆ^\×Ý[[Ù^[HOHÈ[™˜Z[š[™×Ý\K\\Š
KœÝ\ÝÚ]

TÈ‹LÔŠJH[ÙHˆ‚ˆÙ^WÙ]\Ë˜\[™
È›˜[YHŽˆ]K™]Z[ŽˆˆžÙ›Ü›X][Û—Û˜[Y_H0­ÈHÙœ—Ù]J^[WÙ]Kš\ÛÙ›Ü›X]

J_H0­ÈÙ]WÜ˜[™Ù_^Ü™[Z[™\ŸHŸJB‚ˆ›Üˆ˜Z[™YH[ˆÜ™YÚ\Ý\™YÝ˜Z[™Y\ÊÙ\ÜÚ[Û—ÛØšŠN‚ˆ˜[YHHÙZ[WÜ™XØ\Û˜[YJ˜Z[™YJBˆ˜Z[™YWÚÙ^HHÝŠ˜Z[™YK™Ù]
šYŠHÜˆˆŠKœÝš\

HÜˆÛ›Ü›X[^™YÝÚÙ[Š˜[YJBˆØ[WÙ]HHÜØ[\×Ý˜Z[™YWØ[˜ÚÜ—Ù]J˜Z[™YK˜Z[š[™×ÛX™[
BˆšXÙHHÜØ[\×Ý˜Z[™YWÜšXÙJ˜Z[™YK˜Z[š[™×Ý\K˜Z[š[™×ÛX™[
Bˆ^ÛYYÙœ›ÛWÜØ[\ÈH›ÛÛ
˜Z[™YK™Ù]
™^ÛYWÙœ›ÛWÜØ[\×Ý˜XÚÚ[™ÈŠHÜˆÙ\ÜÚ[Û—ÛØš‹™Ù]
™^ÛYWÙœ›ÛWÜØ[\×Ý˜XÚÚ[™ÈŠJBˆYˆ•QHˆ[ˆ˜Z[š[™×Ý\K\\Š
N‚ˆYˆÙZ[WÜ™XØ\Ù]J˜Z[™YK™Ù]
˜Ü™X]YØ]ŠJHOH™\ÜÙ]N‚ˆ˜YWÙ›ÛÝ×Ý\È›™]×Ü™\]Y\ÝÈ—H
ÏHBˆ˜YWÙ›ÛÝ×Ý\Û˜[Y\ÖÈ›™]×Ü™\]Y\ÝÈ—K˜\[™
˜[YJBˆXÝ[Û—Ù]\ÈH˜Z[™YK™Ù]
˜YWØXÝ[Û—Ù]\ÈŠHÜˆßBˆYˆ\Ú[œÝ[˜ÙJXÝ[Û—Ù]\ËXÝ
N‚ˆ›ÜˆXÝ[Û—ÚÙ^KY]šX×ÚÙ^H[ˆ
ˆ
›]œ™]ÌWÝ˜[Y]Y‹›]œ™]ÌWÝ˜[Y]YŠKˆ
›]œ™]Ì—Ý˜[Y]Y‹›]œ™]Ì—Ý˜[Y]YŠKˆ
™\ÛYWÛØ[H‹˜Ù\YšXØ][Û—ÛØZ[™YŠKˆ
N‚ˆYˆÙZ[WÜ™XØ\Ù]JXÝ[Û—Ù]\Ë™Ù]
XÝ[Û—ÚÙ^JJHOH™\ÜÙ]N‚ˆ˜YWÙ›ÛÝ×Ý\ÛY]šX×ÚÙ^WH
ÏHBˆ˜YWÙ›ÛÝ×Ý\Û˜[Y\ÖÛY]šX×ÚÙ^WK˜\[™
˜[YJBˆYˆ›Ý^ÛYYÙœ›ÛWÜØ[\È[™Ø[WÙ]H[™Ø[WÙ]KžYX\ˆOH™\ÜÙ]KžYX\ˆ[™Ø[WÙ]K›[ÛOH™\ÜÙ]K›[Û[™Ø[WÙ]HH™\ÜÙ]N‚ˆ[ÛÜ™]™[YH
ÏHšXÙBˆYˆ›Ý^ÛYYÙœ›ÛWÜØ[\È[™Ø[WÙ]HOH™\ÜÙ]N‚ˆØ[\ÖÈœ™]™[YH—H
ÏHšXÙBˆØ[\ÖÈ˜ÛÝ[—H
ÏHBˆX™[H˜Z[š[™×ÛX™[ˆØ[\ÖÈ™›Ü›X][ÛœÈ—VÛX™[HHØ[\ÖÈ™›Ü›X][ÛœÈ—K™Ù]
X™[
H
ÈBˆYˆ›Ý^ÛYYÙœ›ÛWÜØ[\Î‚ˆ›ÜˆÙ^KÛÛ\\š\ÛÛ—Ù]H[ˆÛÛ\\š\ÛÛ—Ù]\Ëš][\Ê
N‚ˆYˆØ[WÙ]HOHÛÛ\\š\ÛÛ—Ù]N‚ˆÛÛ\\š\ÛÛ—ÜØ[\ÖÚÙ^WVÈœ™]™[YH—H
ÏHšXÙBˆÛÛ\\š\ÛÛ—ÜØ[\ÖÚÙ^WVÈ˜ÛÝ[—H
ÏHB‚ˆYˆÙZ[WÜ™XØ\ØÛÛ™[[Û—Ú\×Ü[™[™ÊÙ\ÜÚ[Û—ÛØš‹˜Z[™YJN‚ˆ[™[™×ÜÚYÛ˜]\™\Ë˜\[™
È›˜[YHŽˆ˜[YK™]Z[ŽˆÙ\ÜÚ[Û—ÛX™[JB‚ˆYˆÙZ[WÜ™XØ\ÛX[™]WÚ\×Ü[™[™Ê˜Z[™YJN‚ˆ[™[™×ÛX[™]\×ØžWÝ˜Z[™YVÝ˜Z[™YWÚÙ^WHHÂˆ›˜[YHŽˆ˜[YKˆ™]Z[ŽˆˆžÙ›Ü›X][Û—Û˜[YHÜˆ	Ñ›Ü›X][Û‰ßH0­ÈÙ]WÜ˜[™Ù_H0­ÈÚYÛ˜]\™HHX[™][ˆ][H‹ˆB‚ˆYˆÝ\Ù]H[™H
Ý\Ù]HHÙ^JK™^\ÈÈ[™›ÝÜÜÚY\—Ú\×ØÛÛ\]WÝÝ[
˜Z[™YK˜Z[š[™×Ý\KÝ\Ù]JN‚ˆ[˜ÛÛ\]WÝ\ÛÛZ[™Ë˜\[™
È›˜[YHŽˆ˜[YK™]Z[ŽˆÙ\ÜÚ[Û—ÛX™[JB‚ˆÛ˜\×Ü˜]ÈHÝŠ˜Z[™YK™Ù]
˜Û˜\×ÜÝ]\ÈŠHÜˆ˜Z[™YK™Ù]
œÝ]]ØÛ˜\ÈŠHÜˆ˜Z[™YK™Ù]
œ™WÜÝ]\ÈŠHÜˆˆŠKœÝš\

Bˆ›Ü›X[^™YØÛ˜\ÈH[šXÛÙY]K››Ü›X[^™J“‘‘‹Û˜\×Ü˜]Ë›ÝÙ\Š
JBˆ›Ü›X[^™YØÛ˜\ÈHˆ‹š›Ú[ŠÚ›ÜˆÚ[ˆ›Ü›X[^™YØÛ˜\ÈYˆ[šXÛÙY]K˜Ø]YÛÜžJÚ
HOH“[ˆŠBˆ›Ü›X[^™YÝ˜[Y]YHÝ[šXÛÙY]K››Ü›X[^™J	Ó‘‘	Ë˜[YJK™[˜ÛÙJ	Ø\ØÚZIË	ÚYÛ›Ü™IÊK™XÛÙJ
H›Üˆ˜[YH[ˆ˜[Y]YØÛ˜\ßBˆÛ˜\×Ú\×Ý˜[Y]YH›Ü›X[^™YØÛ˜\È[ˆ›Ü›X[^™YÝ˜[Y]YÜˆ›Ü›X[^™YØÛ˜\È[ˆÙˆ˜Û˜\ÈÝ˜[Y_Hˆ›Üˆ˜[YH[ˆ›Ü›X[^™YÝ˜[Y]YBˆÛ˜\×Ú\×Ú[—Ü›ÙÜ™\ÜÈH›Ü›X[^™YØÛ˜\È[ˆÈ™[ˆÛÝ\œÈ‹™[—ØÛÝ\œÈ‹š[ˆ›ÙÜ™\ÜÈ‹š[—Ü›ÙÜ™\ÜÈ‹›Û™ÛÚ[™ÈŸBˆÈ]™\žH˜Z[™YH]\˜]Y\™H™[Û™ÜÈÈH™X[›Û‹X\˜Ú]™YˆÈ˜Z[š[™ÈÙ\ÜÚ[Û‹ˆÛ›HH^XÚ]8 '[ˆÛÝ\œø 'HÓTÈ]Y]YH\ÂˆÈXÝ[Û˜X›NÈ›[šË˜[œÛZ]YÜˆÝ\ˆÝ]\Ù\È]\ÝÝ^HÝ]‚ˆYˆ[™Ù]H[™[™Ù]HHÙ^H[™Û˜\×Ú\×Ú[—Ü›ÙÜ™\ÜÈ[™›ÝÛ˜\×Ú\×Ý˜[Y]Y‚ˆÙ\ÜÚ[Û—Û˜[YHHÝŠÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹›˜[YH‹ˆŠHÜˆˆŠKœÝš\

BˆÛ˜\×ÜÙ\ÜÚ[ÛˆHˆ0­È‹š›Ú[ŠXÝ™œ›ÛZÙ^\Ê\›Üˆ\[ˆ
Ù\ÜÚ[Û—Û˜[YK›Ü›X][Û—ÛX™[
˜Z[š[™×Ý\JHÜˆ˜Z[š[™×Ý\JHYˆ\
JBˆÝ\ÛX™[Hœ—Ù]JÝ\Ù]Kš\ÛÙ›Ü›X]

JHYˆÝ\Ù]H[ÙH™]H0èÛÛ™š\›Y\ˆ‚ˆ[™ÛX™[Hœ—Ù]J[™Ù]Kš\ÛÙ›Ü›X]

JHYˆ[™Ù]H[ÙHÝ\ÛX™[ˆÛ˜\×Ü[™[™Ë˜\[™
Âˆ›˜[YHŽˆ˜[YKˆ™]Z[ŽˆˆžØÛ˜\×ÜÙ\ÜÚ[ÛˆÜˆ	Ñ›Ü›X][Û‰ßH0­ÈHÜÝ\ÛX™[H]HÙ[™ÛX™[H0­ÈØÛ˜\×Ü˜]ÈÜˆ	ÜÝ]]›Ûˆ™[œÙZYÛ°êIßH‹ˆJB‚ˆÈHÓTÈ˜XÚÚ[™ÈYÙH\È]]Üš]]]™Nˆ]ÛÛZ[œÈÝ]\Ù\È™]\›™YžBˆÈÓTÕŒÈ[™[œ›ÛY[X]Ú[™Ëˆ˜[˜XÚÈÈØØ[HÝÜ™Y˜Z[™YBˆÈÝ]\Ù\ÈÛ›HÚ[H]Ù\šXÙH\È[˜]˜Z[X›K‚ˆÛ˜\×Ü›ÝÜËÛ˜\×Ù\œ›ÜˆH™]ÚØÛ˜\ÝŒ×Ý˜XÚÚ[™×Ü™\]Y\ÝÊ
BˆYˆ›ÝÛ˜\×Ù\œ›ÜŽ‚ˆÛ˜\×Ü[™[™ÈH×Bˆ[›XZ\™WÜÝ]\Ù\ÈH]K™Ù]
˜Û˜\×ÜX›X×Ø[›XZ\™WÜÝ]\Ù\ÈŠHÜˆßBˆ›Üˆ›ÝÈ[ˆ[œšXÚØÛ˜\×Ý˜XÚÚ[™×Ü›ÝÜ×ÝÚ]Ù[œ›ÛY[
Û˜\×Ü›ÝÜË]JN‚ˆYˆ›Ý›ÝË™Ù]
š\×Ù[œ›ÛYŠN‚ˆÛÛ[YBˆXˆH™KœÝXŠˆ—
È‹ˆ‹ÝŠ›ÝË™Ù]
›XˆŠHÜˆˆŠJVËMÎ—Bˆ[›XZ\™WÚÙ^HHØÛ˜\×ÜX›X×Ø[›XZ\™WÜÝ]\×ÚÙ^JÝŠ›ÝË™Ù]
›\ÝÛ˜[YHŠHÜˆˆŠKXŠBˆ[›XZ\™WÜÝ]\ÈH[›XZ\™WÜÝ]\Ù\Ë™Ù]
[›XZ\™WÚÙ^JHYˆ\Ú[œÝ[˜ÙJ[›XZ\™WÜÝ]\Ù\ËXÝ
H[ÙH›Û™BˆÈ\È\È^XÝHHYÙIÜÈ8 '[ˆÛÝ\œø 'HYX[š[™ÎˆHX›XÈÓTÂˆÈ[›XZ\™HÚXÚÈÝXØÙYYY]™]\›™Y›ÈXÝ]™H]KˆÛ\ˆ]BˆÈÚ]Ý][ˆ[›XZ\™H˜\Ù[[™HÙY\ÈHYØXÞH^XÚ]Ý]\Ë‚ˆ›×Ý]WÙ›Ý[™H\Ú[œÝ[˜ÙJ[›XZ\™WÜÝ]\ËXÝ
H[™›Ý›ÛÛ
[›XZ\™WÜÝ]\Ë™Ù]
šÛ›ÝÛˆŠJBˆ›Ü›X[^™YÜÝ]\ÈHÛ›Ü›X[^™WØÛ˜\×ÜÝ]\Ê›ÝË™Ù]
˜Û˜\×ÜÝ]\ÈŠJKœ™\XÙJ—È‹ˆŠBˆYˆ›Ý›×Ý]WÙ›Ý[™[™
[›XZ\™WÜÝ]\È\È›Ý›Û™HÜˆ›Ü›X[^™YÜÝ]\ÈOH‘SˆÓÕT”ÈŠN‚ˆÛÛ[YBˆ[œ›ÛY[H›ÝË™Ù]
™[œ›ÛY[ŠHÜˆßBˆÙ\ÜÚ[Û—Û˜[YHHÝŠ[œ›ÛY[™Ù]
œÙ\ÜÚ[Û—Û˜[YHŠHÜˆˆŠKœÝš\

Bˆ˜Z[š[™×Ý\HHÝŠ[œ›ÛY[™Ù]
˜Z[š[™×Ý\HŠHÜˆˆŠKœÝš\

BˆÙ\ÜÚ[Û—Ù]Z[Hˆ0­È‹š›Ú[ŠXÝ™œ›ÛZÙ^\Ê\›Üˆ\[ˆ
Ù\ÜÚ[Û—Û˜[YK˜Z[š[™×Ý\JHYˆ\
JHÜˆ‘›Ü›X][Ûˆ‚ˆÝ\ÛX™[Hœ—Ù]JÝŠ[œ›ÛY[™Ù]
™]WÜÝ\ŠHÜˆˆŠJHÜˆ™]H0èÛÛ™š\›Y\ˆ‚ˆ[™ÛX™[Hœ—Ù]JÝŠ[œ›ÛY[™Ù]
™]WÙ[™ŠHÜˆˆŠJHÜˆÝ\ÛX™[ˆÙ\ÜÚ[Û—Ù]Z[HˆžÜÙ\ÜÚ[Û—Ù]Z[H0­ÈHÜÝ\ÛX™[H]HÙ[™ÛX™[H‚ˆÝ]\×ÜÚ[˜ÙHHÙZ[WÜ™XØ\Ù]J[›XZ\™WÜÝ]\Ë™Ù]
œÝ]\×ÜÚ[˜ÙHŠHÜˆ[›XZ\™WÜÝ]\Ë™Ù]
˜ÚXÚÙYØ]ŠJHYˆ\Ú[œÝ[˜ÙJ[›XZ\™WÜÝ]\ËXÝ
H[ÙH›Û™BˆÛ˜\×Ü[™[™Ë˜\[™
Âˆ›˜[YHŽˆÙ›Ü›X]Ý˜Z[™YWÛ˜[YJ›ÝË™Ù]
™š\œÝÛ˜[YH‹ˆŠK›ÝË™Ù]
›\ÝÛ˜[YH‹ˆŠJHÜˆ”ÝYÚXZ\™H‹ˆ™]Z[ŽˆˆžÜÙ\ÜÚ[Û—Ù]Z[H0­È]XÝ[ˆ]™HÓTÈ›Ý]°êH‹ˆZ—ÜÝ\ÜXÝYŽˆ›ÛÛ
›×Ý]WÙ›Ý[™[™Ý]\×ÜÚ[˜ÙH[™
Ù^HHÝ]\×ÜÚ[˜ÙJK™^\ÈHL
KˆJB‚ˆÚ[™Ù\ÈH×Bˆ›Üˆ›ÝYšXØ][Ûˆ[ˆ
]K™Ù]
˜Û˜\×ÜÝ]\×ØÚ[™ÙWÛ›ÝYšXØ][ÛœÈŠHÜˆßJK˜[Y\Ê
N‚ˆYˆ\Ú[œÝ[˜ÙJ›ÝYšXØ][Û‹XÝ
H[™ÙZ[WÜ™XØ\Ù]J›ÝYšXØ][Û‹™Ù]
œÙ[Ø]ŠJHOH™\ÜÙ]N‚ˆÚ[™Ù\Ë˜\[™
Âˆ›˜[YHŽˆˆ‹š›Ú[Šš[\Š›Û™KÜÝŠ›ÝYšXØ][Û‹™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

KÝŠ›ÝYšXØ][Û‹™Ù]
›\ÝÛ˜[YHŠHÜˆˆŠKœÝš\

WJJHÜˆ”ÝYÚXZ\™H‹ˆ™]Z[ŽˆÝŠ›ÝYšXØ][Û‹™Ù]
œÚYÛ˜]\™HŠHÜˆ“›Ý]™X]HÝ]]0ê]XÝ0êHŠKˆJB‚ˆ™Z™XÝYØžWÝ˜Z[™YNˆXÝÜÝ‹XÝÜÝ‹[žWWHHßBˆš[[™×ÛX[™]\×ØžWÝ˜Z[™YNˆXÝÜÝ‹Ü[Û˜[ÑXÝÜÝ‹Ý—WWHHßBˆ›Üˆ[™H[ˆØš[[™×Û[™\Ê]JN‚ˆ˜Z[™YWÚYHÝŠ[™K™Ù]
˜Z[™YRYŠHÜˆˆŠKœÝš\

BˆYˆ[™K™Ù]
œ^[Y[[ÙHŠHOHœÙ\WÙ\™XÝÙXš]Ž‚ˆ˜[YHHˆžÛ[™K™Ù]
	Ý˜Z[™YQš\œÝ˜[YIË	ÉÊ_HÛ[™K™Ù]
	Ý˜Z[™YS\Ý˜[YIË	ÉÊ_H‹œÝš\

HÜˆ”ÝYÚXZ\™H‚ˆÙ^HH˜Z[™YWÚYÜˆÛ›Ü›X[^™YÝÚÙ[Š˜[YJBˆš[[™×ÛX[™]\×ØžWÝ˜Z[™YKœÙ]Y˜][
Ù^K›Û™JBˆYˆÙZ[WÜ™XØ\ÛX[™]WÚ\×Ü[™[™Ê[™JN‚ˆ›Ü›X][ÛˆHÝŠ[™K™Ù]
™›Ü›X][Û“˜[YHŠHÜˆ[™K™Ù]
œÙ\ÜÚ[Û“˜[YHŠHÜˆ‘›Ü›X][Ûˆ›Ûˆ™[œÙZYÛ°êYHŠKœÝš\

BˆÝ\ÛX™[Hœ—Ù]JÝŠ[™K™Ù]
™]TÝ\ŠHÜˆˆŠJHÜˆ™]H0èÛÛ™š\›Y\ˆ‚ˆ[™ÛX™[Hœ—Ù]JÝŠ[™K™Ù]
™]Q[™ŠHÜˆ[™K™Ù]
™]TÝ\ŠHÜˆˆŠJHÜˆ™]H0èÛÛ™š\›Y\ˆ‚ˆš[[™×ÛX[™]\×ØžWÝ˜Z[™YVÚÙ^WHHÂˆ›˜[YHŽˆ˜[YKˆ™]Z[ŽˆˆžÙ›Ü›X][ÛŸH0­ÈHÜÝ\ÛX™[H]HÙ[™ÛX™[H0­ÈÚYÛ˜]\™HHX[™][ˆ][H‹ˆBˆ›Üˆ[œÝ[Y[[ˆÜÙ\WÚ[œÝ[Y[Ê[™JN‚ˆYˆÝŠ[œÝ[Y[™Ù]
œÝ]\ÈŠHÜˆˆŠK›ÝÙ\Š
H›Ý[ˆÈ™˜Z[Y‹œ™Z™XÝY‹œ™]\›™Y‹œ™Y[™Y‹™XÛ[™YŸN‚ˆÛÛ[YBˆYˆÚ[œÝ[Y[Ü™Z™XÝ[Û—Ú\×Ý™X]Y
[œÝ[Y[
N‚ˆÛÛ[YBˆ]™[Ù]HHÙZ[WÜ™XØ\Ù]J[œÝ[Y[™Ù]
œ™Z™XÝYØ]ŠHÜˆ[œÝ[Y[™Ù]
™˜Z[YØ]ŠHÜˆ[œÝ[Y[™Ù]
\]YØ]ŠHÜˆ[œÝ[Y[™Ù]
\]Y]ŠHÜˆ[œÝ[Y[™Ù]
™]HŠHÜˆ[œÝ[Y[™Ù]
™YWÙ]HŠJBˆYˆ]™[Ù]HOH™\ÜÙ]N‚ˆ˜[YHHˆžÛ[™K™Ù]
	Ý˜Z[™YQš\œÝ˜[YIË	ÉÊ_HÛ[™K™Ù]
	Ý˜Z[™YS\Ý˜[YIË	ÉÊ_H‹œÝš\

HÜˆ”ÝYÚXZ\™H‚ˆÙ^HHÝŠ[™K™Ù]
˜Z[™YRYŠHÜˆˆŠKœÝš\

HÜˆÛ›Ü›X[^™YÝÚÙ[Š˜[YJBˆ][HH™Z™XÝYØžWÝ˜Z[™YKœÙ]Y˜][
Ù^KÈ›˜[YHŽˆ˜[YK™]Z[ÈŽˆ×_JBˆ›Ü›X][ÛˆHÝŠ[™K™Ù]
™›Ü›X][Û“˜[YHŠHÜˆ[™K™Ù]
œÙ\ÜÚ[Û“˜[YHŠHÜˆ‘›Ü›X][Ûˆ›Ûˆ™[œÙZYÛ°êYHŠKœÝš\

BˆYWÙ]HHœ—Ù]JÝŠ[œÝ[Y[™Ù]
™YWÙ]HŠHÜˆ[œÝ[Y[™Ù]
™]HŠHÜˆˆŠJHÜˆ™]H›Ûˆ™[œÙZYÛ°êYH‚ˆ™X\ÛÛˆHÙZ[WÜ™XØ\Ü™Z™XÝ[Û—Ü™X\ÛÛŠ[œÝ[Y[™Ù]
œÝ]\×Ü™X\ÛÛˆŠHÜˆ[œÝ[Y[™Ù]
™˜Z[\™T™X\ÛÛˆŠJBˆ][VÈ™]Z[È—K˜\[™
ˆžÙ›Ü›X][ÛŸH0­È0êXÚ0êX[˜ÙHHÙYWÙ]_H0­È×Ù›Ü›X]Ù]\›Ê[œÝ[Y[™Ù]
	Ø[[Ý[	ÊJ_H0­ÈÜ™X\ÛÛŸHŠB‚ˆÈš[[™È[™\È\™HÞ[˜Ú›Ûš^™YÚ][ÛÈ[™\™Y›Ü™HÝ\\œÙYHHÝ[BˆÈX[™]HÝ]\ÈÛÜYYÛÈHÙ\ÜÚ[Ûˆ˜Z[™YH™XÛÜ™‚ˆ›ÜˆÙ^K[™[™×Ú][H[ˆš[[™×ÛX[™]\×ØžWÝ˜Z[™YKš][\Ê
N‚ˆ[™[™×ÛX[™]\×ØžWÝ˜Z[™YKœÜ
Ù^K›Û™JBˆYˆ[™[™×Ú][N‚ˆ[™[™×ÛX[™]\×ØžWÝ˜Z[™YVÚÙ^WHH[™[™×Ú][B‚ˆ™Z™XÝYHÂˆÈ›˜[YHŽˆ][VÈ›˜[YH—K™]Z[Žˆˆ‹š›Ú[ŠXÝ™œ›ÛZÙ^\Ê][VÈ™]Z[È—JJ_Bˆ›Üˆ][H[ˆ™Z™XÝYØžWÝ˜Z[™YK˜[Y\Ê
BˆB‚ˆØš™XÝ]™\ÈH]K™Ù]
œØ[\×Ý˜XÚÚ[™È‹ßJK™Ù]
›Øš™XÝ]™\È‹ßJBˆYX\—ÛØš™XÝ]™\ÈHØš™XÝ]™\Ë™Ù]
ÝŠ™\ÜÙ]KžYX\ŠKßJHYˆ\Ú[œÝ[˜ÙJØš™XÝ]™\ËXÝ
H[ÙHßBˆ[ÛWÛØš™XÝ]™\ÈHYX\—ÛØš™XÝ]™\Ë™Ù]
›[ÛÈ‹ßJHYˆ\Ú[œÝ[˜ÙJYX\—ÛØš™XÝ]™\ËXÝ
H[ÙHßBˆ[ÛÛØš™XÝ]™HHÜ\œÙWÜÜÚ]]™WÚ[
[ÛWÛØš™XÝ]™\Ë™Ù]
ÝŠ™\ÜÙ]K›[Û
K
HYˆ\Ú[œÝ[˜ÙJ[ÛWÛØš™XÝ]™\ËXÝ
H[ÙH
Bˆ[ÛÜ›ÙÜ™\Ü×Ü˜][ÈH
[ÛÜ™]™[YHÈ[ÛÛØš™XÝ]™JHYˆ[ÛÛØš™XÝ]™Hˆ[ÙHˆ[ÛÜ™[XZ[š[™ÈHX^
[ÛÛØš™XÝ]™HH[ÛÜ™]™[YK
HYˆ[ÛÛØš™XÝ]™Hˆ[ÙHˆ™]\›ˆÈ™]HŽˆ™\ÜÙ]KœØ[\ÈŽˆØ[\Ë˜ÛÛ\\š\ÛÛ—ÜØ[\ÈŽˆÛÛ\\š\ÛÛ—ÜØ[\Ëœš[Ü—ÜØ[\ÈŽˆÛÛ\\š\ÛÛ—ÜØ[\ÖÈœ™]š[Ý\×ÞYX\ˆ—K›[ÛÚÜHŽˆÈœ™]™[YHŽˆ[ÛÜ™]™[YK›Øš™XÝ]™HŽˆ[ÛÛØš™XÝ]™Kœ›ÙÜ™\Ü×Ü˜][ÈŽˆ[ÛÜ›ÙÜ™\Ü×Ü˜][Ëœ™[XZ[š[™ÈŽˆ[ÛÜ™[XZ[š[™ßKšÙ^WÙ]\ÈŽˆÙ^WÙ]\Ë˜YWÙ›ÛÝ×Ý\Žˆ˜YWÙ›ÛÝ×Ý\˜YWÙ›ÛÝ×Ý\Û˜[Y\ÈŽˆ˜YWÙ›ÛÝ×Ý\Û˜[Y\Ë˜Û˜\×ØÚ[™Ù\ÈŽˆÚ[™Ù\Ëœ™Z™XÝYŽˆ™Z™XÝYœ[™[™×ÛX[™]\ÈŽˆ\Ý
[™[™×ÛX[™]\×ØžWÝ˜Z[™YK˜[Y\Ê
JKœ[™[™×ÜÚYÛ˜]\™\ÈŽˆ[™[™×ÜÚYÛ˜]\™\Ëš[˜ÛÛ\]WÝ\ÛÛZ[™ÈŽˆ[˜ÛÛ\]WÝ\ÛÛZ[™Ë˜Û˜\×Ü[™[™ÈŽˆÛ˜\×Ü[™[™ßB‚‚™YˆZ[ÙZ[WÜ™XØ\Ù[XZ[
™\ÜˆXÝÜÝ‹[žWK
‹™XÚ\Y[ˆÝˆHˆ‹Ü™Y][™×ØÛÛ^ˆÜ[Û˜[ÑXÝÜÝ‹[žWWHH›Û™JHOˆ\VÜÝ‹Ý—N‚ˆˆˆ”™[™\ˆ[ˆ[XZ[XÛY[\ØY™KÛÛÝ\™[ØXTË\Ý[HZ[H\Ú›Ø\™ˆˆˆ‚ˆ\Ü^WÙ]HH
Ü™Y][™×ØÛÛ^ÜˆßJK™Ù]
™]HŠHÜˆ
™\ÜÈ™]H—H
È]][YK[YY[J^\ÏLJJBˆYˆÙXÝ[Û—ØÛÝ[Ø˜YÙJÛÝ[ˆ[
HOˆÝŽ‚ˆˆˆ”™[™\ˆHØ[YH›ÛZ[™[ÛÝ[\ˆÛˆ]™\žHÜ\˜][Û˜[ÙXÝ[Û‹ˆˆˆ‚ˆ™]\›ˆ‰ÏÜ[ˆÝ[OH™\Ü^Nš[›[™KX›ØÚÎÛZ[‹]ÚYŒŒœÜY[™ÎÜ\Ø˜XÚÙÜ›Ý[™ˆÍ™MNØÛÛÜŽˆÙ™™ŽØ›Ü™\‹\˜Y]\ÎŒLœÝ^X[YÛŽ˜Ù[\ŽÙ›Û\Ú^™NŒLœÙ›Û]ÙZYÚŽLžØÛÝ[OÜÜ[‰Â‚ˆYˆ›ÝÜÊ][\Îˆ\ÝÑXÝÜÝ‹Ý—WK[\NˆÝŠHOˆÝŽ‚ˆYˆ›Ý][\Î‚ˆ™]\›ˆ‰Ï]ˆÝ[OHœY[™ÎŒNØÛÛÜŽˆÍÍŽÝ^X[YÛŽ˜Ù[\ˆ¸§$ÈÚ[™\ØØ\J[\J_OÙ]‰Âˆ™[™\™YH×Bˆ›Üˆ][H[ˆ][\Î‚ˆZ—ÛX™[H	ÏÜ[ˆÝ[OH™\Ü^Nš[›[™KX›ØÚÎÛX\™Ú[‹[YÜÜY[™ÎØ›Ü™\‹\˜Y]\ÎŽN\Ø˜XÚÙÜ›Ý[™ˆÙÌŒŽØÛÛÜŽˆÙ™™ŽÙ›Û\Ú^™NŒLÙ›Û]ÙZYÚŽLÝ^]˜[œÙ›Ü›N\\˜Ø\ÙH”Ý\ÜXÚ[ÛˆHRÜÜ[‰ÈYˆ][K™Ù]
Z—ÜÝ\ÜXÝYŠH[ÙHˆ‚ˆ™[™\™Y˜\[™
‰Ï]ˆÝ[OHœY[™ÎŒLÜØ›Ü™\‹X›ÝÛNŒ\ÛÛYÙL™NŒÝ›Û™ÈÝ[OH˜ÛÛÜŽˆÌMÌŒÌÈžÚ[™\ØØ\J][VÈ›˜[YH—J_OÜÝ›Û™ÏžÝZ—ÛX™[O]ˆÝ[OH›X\™Ú[‹]ÜØÛÛÜŽˆÍÍŽÙ›Û\Ú^™NŒLÜžÚ[™\ØØ\J][VÈ™]Z[—J_OÙ]Ù]‰ÊBˆ™]\›ˆˆ‹š›Ú[Š™[™\™Y
B‚ˆYˆÙ^WÙ]\×ØØ\™
][\Îˆ\ÝÑXÝÜÝ‹Ý—WJHOˆÝŽ‚ˆˆˆ”™[™\ˆÙ^H]\È\ÈHÛÛ\XÝYÙ[™H˜]\ˆ[ˆHÙ[™\šXÈ\Ýˆˆˆ‚ˆYˆ›Ý][\Î‚ˆ™]\›ˆˆ‚ˆYÙ[™WÜ›ÝÜÈH×Bˆ›Üˆ][H[ˆ][\Î‚ˆ]HHÝŠ][K™Ù]
›˜[YHŠHÜˆ°âXÚ0êX[˜ÙHŠBˆ\×Ý\™Ù[H™[XZ[ˆˆ[ˆ]K›ÝÙ\Š
BˆXØÙ[HˆÙXMNÈˆYˆ\×Ý\™Ù[[ÙHˆÍ™MH‚ˆÛÙHˆÙ™™ÙYˆYˆ\×Ý\™Ù[[ÙHˆÙYYŒ™™ˆ‚ˆ[Z[™ÈH°à°ê\\™\ˆ]Z›Ý\™8 &ZZHˆYˆ\×Ý\™Ù[[ÙH°à[XÚ\\ˆ‚ˆYÙ[™WÜ›ÝÜË˜\[™
ˆ‰ÏÝ[OHœY[™ÎœX›H›ÛOHœ™\Ù[][ÛˆˆÚYHŒL	HˆÙ[ÜXÚ[™ÏHŒˆÙ[Y[™ÏHŒˆ	Âˆ‰ÜÝ[OH˜˜XÚÙÜ›Ý[™žÜÛÙNØ›Ü™\ŽŒ\ÛÛYØXØÙ[LŒŽØ›Ü™\‹\˜Y]\ÎŒM‰Âˆ‰ÏÚYHˆˆÝ[OHÚYœØ˜XÚÙÜ›Ý[™žØXØÙ[NØ›Ü™\‹\˜Y]\ÎŒMMÝ‰Âˆ‰ÏÚYHˆ[YÛH˜Ù[\ˆˆÝ[OHœY[™ÎŒMMM]ˆÝ[OHÚYŒÍœÚZYÚŒÍœÛ[™KZZYÚŒÍœØ›Ü™\‹\˜Y]\ÎŒL\Ø˜XÚÙÜ›Ý[™ˆÙ™™ŽØÛÛÜŽžØXØÙ[NÙ›Û\Ú^™NŒNÝ^X[YÛŽ˜Ù[\ŽØ›Þ\ÚYÝÎŒLœ™Ø˜JMKŒË‹Œ
H¸¥áÙ]Ý‰Âˆ‰ÏÝ[OHœY[™ÎŒLÜMLÜœ]ˆÝ[OH˜ÛÛÜŽžØXØÙ[NÙ›Û\Ú^™NŒLÙ›Û]ÙZYÚŽLÛ]\‹\ÜXÚ[™Î‹Œ[NÝ^]˜[œÙ›Ü›N\\˜Ø\ÙHžÝ[Z[™ßOÙ]‰Âˆ‰Ï]ˆÝ[OH›X\™Ú[‹]ÜŒÜØÛÛÜŽˆÌŒMÌ˜NÙ›Û\Ú^™NŒM\Ù›Û]ÙZYÚŽLÛ[™KZZYÚŒKŒÈžÚ[™\ØØ\J]J_OÙ]‰Âˆ‰Ï]ˆÝ[OH›X\™Ú[‹]Ü\ØÛÛÜŽˆÍÍŽÙ›Û\Ú^™NŒLœÛ[™KZZYÚŒKHžÚ[™\ØØ\JÝŠ][K™Ù]
™]Z[ŠHÜˆˆŠJ_OÙ]Ý‰Âˆ‰ÏÝÝX›OÝÝ‰Âˆ
Bˆ™]\›ˆ
ˆ	ÏÝ[OHœY[™ÎŽ]ˆÝ[OH›Ý™\™›ÝÎšY[ŽØ˜XÚÙÜ›Ý[™›[™X\‹YÜ˜YY[
MYYËÙ™™™™™‹ÙŽ˜Y˜ÊNØ›Ü™\ŽŒ\ÛÛYÙ™XY™NØ›Ü™\‹\˜Y]\ÎŒŒÜY[™ÎŒŒØ›Þ\ÚYÝÎŒLŽ™Ø˜JÍËNKŒÍKŒ
H‰Âˆ	ÏX›H›ÛOHœ™\Ù[][ÛˆˆÚYHŒL	HˆÙ[ÜXÚ[™ÏHŒˆÙ[Y[™ÏHŒ]ˆÝ[OH˜ÛÛÜŽˆÍ™MNÙ›Û\Ú^™NŒLÙ›Û]ÙZYÚŽLÛ]\‹\ÜXÚ[™Î‹ŒY[NÝ^]˜[œÙ›Ü›N\\˜Ø\ÙHYÙ[™HÜ0ê\˜][Û›™[Ù]ˆÝ[OH›X\™Ú[ŽœØÛÛÜŽˆÌŒMÌ˜NÙ›Û\Ú^™NŒN\‘]\ÈÛ0ê\ÏÚ]ˆÝ[OH˜ÛÛÜŽˆÍÍŽÙ›Û\Ú^™NŒLœ“\È›ØÚZ[™\È0êXÚ0êX[˜Ù\È0è™H\ÈX[œ]Y\Ù]Ý‰Âˆ‰ÏÚYHˆˆ[YÛHœšYÚˆ˜[YÛHÜžÜÙXÝ[Û—ØÛÝ[Ø˜YÙJ[Š][\ÊJ_OÝÝÝX›O‰Âˆ‰ÏX›H›ÛOHœ™\Ù[][ÛˆˆÚYHŒL	HˆÙ[ÜXÚ[™ÏHŒˆÙ[Y[™ÏHŒˆÝ[OH›X\™Ú[‹]ÜŒLžÈˆ‹š›Ú[ŠYÙ[™WÜ›ÝÜÊ_OÝX›OÙ]ÝÝ‰Âˆ
B‚ˆØ[\ÈH™\ÜÈœØ[\È—Bˆ™]™[YWÛX™[HÚY™œ™\È	ØY™˜Z\™\È™[™™YHˆYˆ\Ü^WÙ]KÙYZÙ^J
HOH[ÙHÚY™œ™H8 &XY™˜Z\™\ÈHH™Z[H‚ˆÛÛ\\š\ÛÛœÈH™\Ü™Ù]
˜ÛÛ\\š\ÛÛ—ÜØ[\ÈŠHÜˆÈœ™]š[Ý\×ÞYX\ˆŽˆ™\ÜÈœš[Ü—ÜØ[\È—_BˆÛÛ\\š\ÛÛ—ÛX™[ÈHÈœ™]š[Ý\×Ù^HŽˆš›Ý\ˆ°êXðêY[‹œ™]š[Ý\×ÝÙYZÈŽˆœÙ[XZ[™H°êXðêY[H‹œ™]š[Ý\×Û[ÛŽˆ›[Ú\È°êXðêY[‹œ™]š[Ý\×ÞYX\ˆŽˆ˜[›°êYH°êXðêY[HŸBˆÛÛ\\š\ÛÛ—ØØ\™ÈH×Bˆ›ÜˆÙ^K][H[ˆÛÛ\\š\ÛÛœËš][\Ê
N‚ˆÛÛ\\š\ÛÛ—Ü™]™[YHH›Ø]
][K™Ù]
œ™]™[YHŠHÜˆ
BˆYˆÙ^H›Ý[ˆÛÛ\\š\ÛÛ—ÛX™[ÈÜˆÛÛ\\š\ÛÛ—Ü™]™[YHH‚ˆÛÛ[YBˆ[HH›Ø]
Ø[\ÖÈœ™]™[YH—HÜˆ
HHÛÛ\\š\ÛÛ—Ü™]™[YBˆ˜][ÈH
[HÈÛÛ\\š\ÛÛ—Ü™]™[YJH
ˆLˆÜÚ]]™HH[HHˆÛÛ\\š\ÛÛ—ØØ\™Ë˜\[™
ˆ‰ÏÚYHŒIHˆÝ[OHœY[™ÎÝ™\XØ[X[YÛŽÜ]ˆÝ[OH›Z[‹ZZYÚNÜY[™ÎŒL\Ø›Ü™\ŽŒ\ÛÛYÙ™XY™NØ›Ü™\‹\˜Y]\ÎŒLœØ˜XÚÙÜ›Ý[™ˆÙ™™ˆ‰Âˆ‰Ï]ˆÝ[OH˜ÛÛÜŽˆÍÍŽÙ›Û\Ú^™NŒLÙ›Û]ÙZYÚŽÝ^]˜[œÙ›Ü›N\\˜Ø\ÙHžØÛÛ\\š\ÛÛ—ÛX™[ÖÚÙ^W_OÙ]‰Âˆ‰Ï]ˆÝ[OH›X\™Ú[‹]Ü\ØÛÛÜŽžÈˆÌMNÙˆYˆÜÚ]]™H[ÙHˆÙÌŒˆŸNÙ›Û\Ú^™NŒLÜÙ›Û]ÙZYÚŽLžÈ¸¥¬ˆˆYˆÜÚ]]™H[ÙH¸¥¯ŸHØXœÊ˜][ÊN‹ŒŸIOÙ]‰Âˆ‰Ï]ˆÝ[OH›X\™Ú[‹]ÜŒœØÛÛÜŽˆÍÍMMŽNÙ›Û\Ú^™NŒL\žÚ[™\ØØ\JÙ›Ü›X]Ù]\›ÊÛÛ\\š\ÛÛ—Ü™]™[YJJ_OÙ]Ù]Ý‰Âˆ
BˆÛÛ\\š\ÛÛˆH
‰ÏX›H›ÛOHœ™\Ù[][ÛˆˆÚYHŒL	HˆÝ[OH›X\™Ú[‹]ÜŒLœžÈˆ‹š›Ú[ŠÛÛ\\š\ÛÛ—ØØ\™Ê_OÝÝX›O‰ÊHYˆÛÛ\\š\ÛÛ—ØØ\™È[ÙH	Ï]ˆÝ[OH›X\™Ú[‹]ÜŒLœØÛÛÜŽˆÍÍŽÙ›Û\Ú^™NŒLœ”\È[˜ÛÜ™HH0ê\š[ÙHÛÛ\\˜X›KÙ]‰Âˆ[ÛÚÜHH™\Ü™Ù]
›[ÛÚÜHŠHÜˆßBˆØš™XÝ]™HH›Ø]
[ÛÚÜK™Ù]
›Øš™XÝ]™HŠHÜˆ
Bˆ›ÙÜ™\Ü×Ü˜][ÈH›Ø]
[ÛÚÜK™Ù]
œ›ÙÜ™\Ü×Ü˜][ÈŠHÜˆ
Bˆ›ÙÜ™\Ü×Ü\˜Ù[HZ[ŠX^
›ÙÜ™\Ü×Ü˜][È
ˆL
KL
BˆYˆØš™XÝ]™Hˆ‚ˆØš™XÝ]™WÝš\ÝX[H
ˆ‰Ï]ˆÝ[OH›X\™Ú[‹]ÜŒNÜY[™ÎŒMØ˜XÚÙÜ›Ý[™ˆÙY™™™ŽØ›Ü™\‹\˜Y]\ÎŒM‰Âˆ‰Ï]ˆÝ[OH™›Û\Ú^™NŒL\ØÛÛÜŽˆÍÍMMŽNÙ›Û]ÙZYÚŽÝ^]˜[œÙ›Ü›N\\˜Ø\ÙH“Øš™XÝYˆH[Ú\ÏÙ]‰Âˆ‰Ï]ˆÝ[OH›X\™Ú[‹]ÜÜÚZYÚŒLØ˜XÚÙÜ›Ý[™ˆÙ™XY™NØ›Ü™\‹\˜Y]\ÎŽN\ÛÝ™\™›ÝÎšY[ˆ]ˆÝ[OHšZYÚŒLÝÚYžÜ›ÙÜ™\Ü×Ü\˜Ù[‹ŒYŸINØ˜XÚÙÜ›Ý[™›[™X\‹YÜ˜YY[
LYËÌMŒÙX‹Ì˜™
NØ›Ü™\‹\˜Y]\ÎŽN\Ù]Ù]‰Âˆ‰ÏX›H›ÛOHœ™\Ù[][ÛˆˆÚYHŒL	HˆÝ[OH›X\™Ú[‹]ÜŽÝ[OH™›Û\Ú^™NŒLœØÛÛÜŽˆÌYMYŽÙ›Û]ÙZYÚŽLžÜ›ÙÜ™\Ü×Ü˜][È
ˆL‹ŒŸIH]Z[Ý[YÛHœšYÚˆÝ[OH™›Û\Ú^™NŒLœØÛÛÜŽˆÍÍMMŽHžÚ[™\ØØ\JÙ›Ü›X]Ù]\›Ê[ÛÚÜK™Ù]
œ™]™[YHŠJJ_HÈÚ[™\ØØ\JÙ›Ü›X]Ù]\›ÊØš™XÝ]™JJ_OÝÝÝX›O‰Âˆ‰Ï]ˆÝ[OH›X\™Ú[‹]Ü\ØÛÛÜŽˆÍÍŽÙ›Û\Ú^™NŒL\”™\ÝHÚ[™\ØØ\JÙ›Ü›X]Ù]\›Ê[ÛÚÜK™Ù]
œ™[XZ[š[™ÈŠJJ_H0è°êX[\Ù\Ù]Ù]‰Âˆ
Bˆ[ÙN‚ˆØš™XÝ]™WÝš\ÝX[H	Ï]ˆÝ[OH›X\™Ú[‹]ÜŒMÜY[™ÎŒL\Ø˜XÚÙÜ›Ý[™ˆÙŽ˜Y˜ÎØ›Ü™\‹\˜Y]\ÎŒLœØÛÛÜŽˆÍÍŽÙ›Û\Ú^™NŒLœ“Øš™XÝYˆY[œÝY[›Ûˆ™[œÙZYÛ°êOÙ]‰Âˆ[]HHÊˆÙ™XY™H‹ˆÌYYŠK
ˆÙ˜ÙMÙŒÈ‹ˆØ™LNYŠK
ˆÙYNY™H‹ˆÍ™ŽHŠK
ˆÙ™™YH‹ˆØÌLÈŠK
ˆØØÙ˜™ŒH‹ˆÌÍ™HŠWBˆ›Ü›X][Û—ÛZ^Hˆ‹š›Ú[Šˆ‰ÏÜ[ˆÝ[OH™\Ü^Nš[›[™KX›ØÚÎÛX\™Ú[Ž\\ÜY[™Î\L\\Ø›Ü™\‹\˜Y]\ÎŽN\Ø˜XÚÙÜ›Ý[™žÜ[]VÚ[™^	H[Š[]JWVÌ_NØÛÛÜŽžÜ[]VÚ[™^	H[Š[]JWVÌW_NÙ›Û\Ú^™NŒLÜÙ›Û]ÙZYÚŽÜ[ˆÝ[OH™\Ü^Nš[›[™KX›ØÚÎÛZ[‹]ÚYŒŒ\ÜY[™ÎŒÜ\ÛX\™Ú[‹\šYÚœØ›Ü™\‹\˜Y]\ÎŽN\Ø˜XÚÙÜ›Ý[™žÜ[]VÚ[™^	H[Š[]JWVÌW_NØÛÛÜŽˆÙ™™ŽÝ^X[YÛŽ˜Ù[\ŽÙ›Û\Ú^™NŒLœžØÛÝ[OÜÜ[žÚ[™\ØØ\JX™[
_OÜÜ[‰Âˆ›Üˆ[™^
X™[ÛÝ[
H[ˆ[[Y\˜]JÛÜY
Ø[\ÖÈ™›Ü›X][ÛœÈ—Kš][\Ê
JJBˆ
HÜˆ	ÏÜ[ˆÝ[OH˜ÛÛÜŽˆÎLNÙ›Û\Ú^™NŒLÜ]XÝ[™H™[OÜÜ[‰ÂˆÙÛÈH[™\ØØ\JˆžÔP“P×ÐTÑWÕT“œœÝš\
	ËÉÊ_KÜÝ]XËÛÙÛËZ[YÜ˜[Kœ™È‹][ÝOUYJBˆÙXÝ[ÛœÈHÂˆ
¼'äáH‹‘]\ÈÛ0ê\È‹™\Ü™Ù]
šÙ^WÙ]\ÈŠHÜˆ×KˆŠKˆ
¸¦¨H‹Ú[™Ù[Y[ÈÓTÈ‹™\ÜÈ˜Û˜\×ØÚ[™Ù\È—K]XÝ[ˆÚ[™Ù[Y[0ê]XÝ0êHŠKˆ
¸¡ªH‹”°ê[0ê™[Y[È™Z™]0ê\È‹™\ÜÈœ™Z™XÝY—K]XÝ[ˆ™Z™]ŠKˆ
¼'ãéˆ‹“X[™]ÈH°ê[0ê™[Y[0è˜[Y\ˆ‹™\Ü™Ù]
œ[™[™×ÛX[™]\ÈŠHÜˆ×K•Ý\È\ÈX[™]ÈÛÛ˜[Y0ê\ÈŠKˆ
¸§#H‹ÛÛ™[[ÛœÈ[ˆ][HHÚYÛ˜]\™H‹™\ÜÈœ[™[™×ÜÚYÛ˜]\™\È—K]XÝ[™HÚYÛ˜]\™H[ˆ][HŠKˆ
¼'äàH‹‘ÜÜÚY\œÈ[˜ÛÛ\]È0­È‹MÈ‹™\ÜÈš[˜ÛÛ\]WÝ\ÛÛZ[™È—K•Ý\È\ÈÜÜÚY\œÈÛÛÛÛ\]ÈŠKˆ
¼'äkˆ‹ÓTÈ0è˜[Y\ˆ‹™\ÜÈ˜Û˜\×Ü[™[™È—K]XÝ[™H˜[Y][Ûˆ[ˆ][HŠKˆBˆY[—ÝÚ[—Ù[\HHÈ‘]\ÈÛ0ê\È‹Ú[™Ù[Y[ÈÓTÈ‹”°ê[0ê™[Y[È™Z™]0ê\È‹“X[™]ÈH°ê[0ê™[Y[0è˜[Y\ˆ‹‘ÜÜÚY\œÈ[˜ÛÛ\]È0­È‹MÈŸBˆØ\™ÈHÙ^WÙ]\×ØØ\™
™\Ü™Ù]
šÙ^WÙ]\ÈŠHÜˆ×JBˆØ\™È
ÏHˆ‹š›Ú[Š‰ÏÝ[OHœY[™ÎŽ]ˆÝ[OH˜˜XÚÙÜ›Ý[™ˆÙ™™ŽØ›Ü™\ŽŒ\ÛÛYÙL™NŒØ›Ü™\‹\˜Y]\ÎŒNÜY[™ÎŒŒˆÝ[OH›X\™Ú[ŽŒØÛÛÜŽˆÌMÌŒÌÎÙ›Û\Ú^™NŒNžÚXÛÛŸI›˜œÜÈÝ]_HÜ[ˆÝ[OH™›Ø]œšYÚžÜÙXÝ[Û—ØÛÝ[Ø˜YÙJ[Š][\ÊJ_OÜÜ[ÚžÜ›ÝÜÊ][\Ë[\J_OÙ]ÝÝ‰È›ÜˆXÛÛ‹]K][\Ë[\H[ˆÙXÝ[ÛœÈYˆ]HOH‘]\ÈÛ0ê\Èˆ[™
][\ÈÜˆ]H›Ý[ˆY[—ÝÚ[—Ù[\JJBˆ˜YWÙ›ÛÝ×Ý\H™\Ü™Ù]
˜YWÙ›ÛÝ×Ý\ŠHÜˆßBˆ˜YWÛY]šXÜÈHÂˆ
“›Ý]™[\È[X[™\ÈQH‹˜YWÙ›ÛÝ×Ý\™Ù]
›™]×Ü™\]Y\ÝÈ‹
JKˆ
“]œ™]ÈH˜[Y0ê\È‹˜YWÙ›ÛÝ×Ý\™Ù]
›]œ™]ÌWÝ˜[Y]Y‹
JKˆ
“]œ™]Èˆ˜[Y0ê\È‹˜YWÙ›ÛÝ×Ý\™Ù]
›]œ™]Ì—Ý˜[Y]Y‹
JKˆ
Ù\YšXØ][ÛœÈØ[Y\È‹˜YWÙ›ÛÝ×Ý\™Ù]
˜Ù\YšXØ][Û—ÛØZ[™Y‹
JKˆBˆš\ÚX›WÝ˜YWÛY]šXÜÈHÊX™[[
ÛÝ[Üˆ
JH›ÜˆX™[ÛÝ[[ˆ˜YWÛY]šXÜÈYˆ[
ÛÝ[Üˆ
HˆBˆYˆš\ÚX›WÝ˜YWÛY]šXÜÎ‚ˆ˜YWÛY]šX×ÚÙ^\ÈHXÝ
š\

X™[›ÜˆX™[ØÛÝ[[ˆ˜YWÛY]šXÜÊK˜YWÙ›ÛÝ×Ý\
JBˆ˜YWÛ˜[Y\ÈH™\Ü™Ù]
˜YWÙ›ÛÝ×Ý\Û˜[Y\ÈŠHÜˆßBˆ˜YWÜ›ÝÜÈHˆ‹š›Ú[Šˆ‰Ï]ˆÝ[OHœY[™ÎŒLÜØ›Ü™\‹X›ÝÛNŒ\ÛÛYÙL™NŒÝ›Û™ÈÝ[OH˜ÛÛÜŽˆÌMÌŒÌÈžÚ[™\ØØ\JX™[
_OÜÝ›Û™ÏÜ[ˆÝ[OH™›Ø]œšYÚžÜÙXÝ[Û—ØÛÝ[Ø˜YÙJÛÝ[
_OÜÜ[‰Âˆ‰Ï]ˆÝ[OH›X\™Ú[‹]ÜœØÛÛÜŽˆÍÍŽÙ›Û\Ú^™NŒLÜžÚ[™\ØØ\J‹‹š›Ú[Š˜YWÛ˜[Y\Ë™Ù]
˜YWÛY]šX×ÚÙ^\ÖÛX™[K×JJJ_OÙ]Ù]‰Âˆ›ÜˆX™[ÛÝ[[ˆš\ÚX›WÝ˜YWÛY]šXÜÂˆ
BˆØ\™ÈH‰ÏÝ[OHœY[™ÎŽ]ˆÝ[OH˜˜XÚÙÜ›Ý[™ˆÙ™™ŽØ›Ü™\ŽŒ\ÛÛYÙL™NŒØ›Ü™\‹\˜Y]\ÎŒNÜY[™ÎŒŒˆÝ[OH›X\™Ú[ŽŒØÛÛÜŽˆÌMÌŒÌÎÙ›Û\Ú^™NŒN¼'ã¤É›˜œÜÈÝZ]šH\ÈQOÚžÝ˜YWÜ›ÝÜßOÙ]ÝÝ‰È
ÈØ\™ÂˆÜ™Y][™ÈHˆ‚ˆYˆ™XÚ\Y[[™Ü™Y][™×ØÛÛ^‚ˆÜ™Y][™ÈHÙZ[WÜ™XØ\ÙÜ™Y][™×Ú[
™XÚ\Y[Ü™Y][™×ØÛÛ^
Bˆ›ÙHH‰ÉÉÏYØÝ\H[[[™ÏH™œˆ›ÙHÝ[OH›X\™Ú[ŽŒØ˜XÚÙÜ›Ý[™ˆÙŒÙ™˜ŽÙ›ÛY˜[Z[N\šX[[™]XØKØ[œË\Ù\šYŽØÛÛÜŽˆÌMÌŒÌÈX›H›ÛOHœ™\Ù[][ÛˆˆÚYHŒL	HˆÙ[ÜXÚ[™ÏHŒˆÙ[Y[™ÏHŒˆÝ[OH˜˜XÚÙÜ›Ý[™ˆÙŒÙ™˜ŽÜY[™ÎŒŽLœ[YÛH˜Ù[\ˆX›H›ÛOHœ™\Ù[][ÛˆˆÚYHŒL	HˆÙ[ÜXÚ[™ÏHŒˆÙ[Y[™ÏHŒˆÝ[OH›X^]ÚYÌÝ[OHœY[™ÎŒÌØ˜XÚÙÜ›Ý[™›[™X\‹YÜ˜YY[
LÍYYËÌMÌMMÍ™MHMIKÌ˜™
NØ›Ü™\‹\˜Y]\ÎŒØÛÛÜŽˆÙ™™ˆ[YÈÜ˜ÏHžÛÙÛßHˆÚYHŒMLˆ[H’[0êYÜ˜[HXØY[^HˆÝ[OH™\Ü^N˜›ØÚÎØ˜XÚÙÜ›Ý[™ˆÙ™™ŽØ›Ü™\‹\˜Y]\ÎŒLœÜY[™ÎÜHÝ[OH›X\™Ú[ŽŒÙ›Û\Ú^™NŒÌ‘RSHÔTUSÓ”ÏÚO]ˆÝ[OH›ÜXÚ]N‹ŽˆžÚ[™\ØØ\Jœ—Ù]J\Ü^WÙ]Kš\ÛÙ›Ü›X]

JJ_OÙ]ÝÝžÙÜ™Y][™ßOÝ[OHœY[™ÎŒL]ˆÝ[OH˜˜XÚÙÜ›Ý[™›[™X\‹YÜ˜YY[
MYYËÙ™™™™™‹ÙY™™™ŠNØ›Ü™\ŽŒ\ÛÛYØ™™™™NØ›Ü™\‹\˜Y]\ÎŒŒœÜY[™ÎŒŒœØ›Þ\ÚYÝÎŒLœÌ™Ø˜JÍËNKŒÍKŒ
H]ˆÝ[OH™›Û\Ú^™NŒLœØÛÛÜŽˆÌYMYŽÙ›Û]ÙZYÚŽLÝ^]˜[œÙ›Ü›N\\˜Ø\ÙNÛ]\‹\ÜXÚ[™Î‹Œ™[H¼'äâ\™›Ü›X[˜ÙHÛÛ[Y\˜ÚX[OÙ]X›H›ÛOHœ™\Ù[][ÛˆˆÚYHŒL	HˆÝ[OH›X\™Ú[‹]ÜŒLÚYHM	HˆÝ[OH™\XØ[X[YÛŽÜÜY[™Ë\šYÚŒMœØ›Ü™\‹\šYÚŒ\ÛÛYÙ™XY™H]ˆÝ[OH˜ÛÛÜŽˆÍÍŽÙ›Û\Ú^™NŒL\Ù›Û]ÙZYÚŽÝ^]˜[œÙ›Ü›N\\˜Ø\ÙHžÚ[™\ØØ\J™]™[YWÛX™[
_OÙ]]ˆÝ[OH™›Û\Ú^™NŒÍÙ›Û]ÙZYÚŽMLØÛÛÜŽˆÌŒMÌ˜NÛX\™Ú[‹]ÜŒÜžÚ[™\ØØ\JÙ›Ü›X]Ù]\›ÊØ[\ÖÉÜ™]™[YI×JJ_OÙ]]ˆÝ[OH›X\™Ú[‹]Ü\ØÛÛÜŽˆÍÍMMŽNÙ›Û\Ú^™NŒLœžÜØ[\ÖÉØÛÝ[	×_H™[^ÉÜÉÈYˆØ[\ÖÉØÛÝ[	×HOHH[ÙH	ÉßH[œ™YÚ\Ý°êY^ÉÜÉÈYˆØ[\ÖÉØÛÝ[	×HOHH[ÙH	ÉßOÙ]žÛØš™XÝ]™WÝš\ÝX[OÝÚYH‰HˆÝ[OH™\XØ[X[YÛŽÜÜY[™Ë[YŒMœ]ˆÝ[OH˜ÛÛÜŽˆÎLNÙ›Û\Ú^™NŒL\Ù›Û]ÙZYÚŽÝ^]˜[œÙ›Ü›N\\˜Ø\ÙH‘›Ü›X][ÛœÈ™[™Y\ÏÙ]]ˆÝ[OH›X\™Ú[‹]ÜŽžÙ›Ü›X][Û—ÛZ^OÙ]ÝÝÝX›OžØÛÛ\\š\ÛÛŸOÙ]ÝÝžØØ\™ßOÝ[OHœY[™ÎŒŒœÝ^X[YÛŽ˜Ù[\ŽØÛÛÜŽˆÎMLØŽÙ›Û\Ú^™NŒLœ’[0êYÜ˜[HXØY[^H0­È˜\Ü]]ÛX]\]YH[›ÞpêH\È›Ý\œÈÝ]œ°ê\È0èÝÝÝX›OÝÝÝX›OØ›ÙOÚ[‰ÉÉÂˆ™]\›ˆ‘RSHÔTUSÓ”È‹›ÙB‚‚™Yˆ[—ÙZ[WÜ™XØ\
ˆ
‹ˆ›ÝÎˆÜ[Û˜[Ù]][YK™]][YWHH›Û™Kˆ›Ü˜ÙNˆ›ÛÛH˜[ÙKˆ[]™\žWÙ]NˆÜ[Û˜[Ù]][YK™]WHH›Û™Kˆ™\]Y\ÝÚYˆÝˆHˆ‹ŠHOˆXÝÜÝ‹[žWN‚ˆ\š\×Û›ÝÈH›ÝÈÜˆ]][YK™]][YK››ÝÊ›Û™R[™›Ê‘]\›ÜKÔ\š\ÈŠJBˆYˆ\š\×Û›ÝËš[™›È\È›Û™N‚ˆ\š\×Û›ÝÈH\š\×Û›ÝËœ™\XÙJš[™›ÏV›Û™R[™›Ê‘]\›ÜKÔ\š\ÈŠJBˆ\š\×Û›ÝÈH\š\×Û›ÝË˜\Ý[Y^›Û™J›Û™R[™›Ê‘]\›ÜKÔ\š\ÈŠJBˆÈH™[™\ˆ›Øˆ[œÈÝ\›KˆÈ›Ý™\]Z\™H]ÈÝ\\š[™ÈH^XÝˆÈŒÝ\ŽˆH[^YY\Þ[Y[ÛÛÝ\Üˆ[\Ü˜\žH›ÝšY\ˆ\œ›Ü‚ˆÈ]\Ý™H™XÛÝ™\˜X›HžHH™^Ý\›H[‹ˆH\œÚ\ÝY\ÝÜžH™[ÝÂˆÈÝ[ÝX\˜[Y\È][ÜÝÛ™HÝXØÙ\ÜÙ[]]ÛX]XÈ[]™\žH\ˆ^K‚ˆYˆ›Ý›Ü˜ÙH[™\š\×Û›ÝËšÝ\ˆ‚ˆ™]\›ˆÈœÙ[Žˆ˜[ÙKœ™X\ÛÛˆŽˆ˜™Y›Ü™WÙ[]™\žWÚÝ\ˆŸBˆY™™XÝ]™WÙ[]™\žWÙ]HH[]™\žWÙ]HÜˆ\š\×Û›ÝË™]J
BˆÈHÛÛ\[žH\ÈÛÜÙY]ÙYZÙ[™Îˆ]]ÛX]XÈ™XØ\È™\Ý[YHÛˆ[Û™^KˆÈ\Ú[™ÈœšY^H\ÈH™\Ü[™È^H›ÜˆØ[\È[™[]YXÝ]š]K‚ˆYˆ›Ý›Ü˜ÙH[™Y™™XÝ]™WÙ[]™\žWÙ]KÙYZÙ^J
HHN‚ˆ™]\›ˆÈœÙ[Žˆ˜[ÙKœ™X\ÛÛˆŽˆÙYZÙ[™ŸBˆ™\ÜÙ]HHÙZ[WÜ™XØ\Ü™\ÜÙ]JY™™XÝ]™WÙ[]™\žWÙ]JBˆ™\]Y\ÝÚYH™\]Y\ÝÚYÜˆ]ZY]ZY

Kš^ÎŒL—Bˆ\›ÙÙÙ\‹Ø\›š[™Êˆ–ÑRSWÔ‘PÐTHÙ[™ÜÝ\™\]Y\ÝÚYI\È›Ü˜ÙOI\È™\ÜÙ]OI\È™XÚ\Y[ÏI\È‹ˆ™\]Y\ÝÚYˆ›Ü˜ÙKˆ™\ÜÙ]Kš\ÛÙ›Ü›X]

Kˆ[ŠRSWÔ‘PÐTÔ‘PÒTQS•ÊKˆ
Bˆ]HHØYÙ]J[—Ø˜XÚÙÜ›Ý[™Ý\ÚÜÏQ˜[ÙJBˆ\ÝÜžHH]KœÙ]Y˜][
™Z[WÜ™XØ\ÜÙ[Ù]\È‹×JBˆYˆ›Ý›Ü˜ÙH[™™\ÜÙ]Kš\ÛÙ›Ü›X]

H[ˆ\ÝÜžN‚ˆ™]\›ˆÈœÙ[Žˆ˜[ÙKœ™X\ÛÛˆŽˆ˜[™XYWÜÙ[‹™]HŽˆ™\ÜÙ]Kš\ÛÙ›Ü›X]

_Bˆ™\ÜHZ[ÙZ[WÜ™XØ\Ù]J]K™\ÜÙ]JBˆÜ™Y][™×ØÛÛ^H™]ÚÙZ[WÜ™XØ\ÙÜ™Y][™×ØÛÛ^
Y™™XÝ]™WÙ[]™\žWÙ]JBˆ[]™\šY\ÈH×Bˆ›Üˆ™XÚ\Y[[ˆRSWÔ‘PÐTÔ‘PÒTQS•Î‚ˆÝXš™XÝ[Ø›ÙHHZ[ÙZ[WÜ™XØ\Ù[XZ[
™\Ü™XÚ\Y[\™XÚ\Y[Ü™Y][™×ØÛÛ^YÜ™Y][™×ØÛÛ^
Bˆ™\Ý[Hœ™]›×ÜÙ[™Ù[XZ[
™XÚ\Y[ÝXš™XÝ[Ø›ÙKY]Y]O^Èœ\œÜÙHŽˆ™Z[WÜ™XØ\‹œ™\ÜÙ]HŽˆ™\ÜÙ]Kš\ÛÙ›Ü›X]

_JBˆ[]™\žHHÂˆœ™XÚ\Y[Žˆ™XÚ\Y[ˆ˜XØÙ\YŽˆ›ÛÛ
™\Ý[™Ù]
›ÚÈŠJKˆ›Y\ÜØYÙWÚYŽˆÝŠ™\Ý[™Ù]
›Y\ÜØYÙWÚYŠHÜˆˆŠKˆBˆ[]™\šY\Ë˜\[™
[]™\žJBˆ\›ÙÙÙ\‹Ø\›š[™Êˆ–ÑRSWÔ‘PÐTH›ÝšY\—Ü™\ÜÛœÙH™\]Y\ÝÚYI\È™XÚ\Y[I\ÈXØÙ\YI\ÈÝ]\×ØÛÙOI\ÈY\ÜØYÙWÚYI\È\œ›ÜI\È‹ˆ™\]Y\ÝÚYˆ™XÚ\Y[ˆ[]™\žVÈ˜XØÙ\Y—Kˆ™\Ý[™Ù]
œÝ]\×ØÛÙHŠKˆ[]™\žVÈ›Y\ÜØYÙWÚY—KˆÝŠ™\Ý[™Ù]
™\œ›ÜˆŠHÜˆˆŠVÎŒŒKˆ
BˆYˆ›Ý™\Ý[™Ù]
›ÚÈŠN‚ˆ™]\›ˆÂˆœÙ[Žˆ˜[ÙKˆœ™X\ÛÛˆŽˆ™[XZ[Ù\œ›Üˆ‹ˆœ™XÚ\Y[Žˆ™XÚ\Y[ˆ™\œ›ÜˆŽˆ™\Ý[™Ù]
™\œ›Üˆ‹ˆŠKˆ˜XØÙ\YÜ™XÚ\Y[ÈŽˆÝ[J][VÈ˜XØÙ\Y—H›Üˆ][H[ˆ[]™\šY\ÊKˆ™[]™\šY\ÈŽˆ[]™\šY\Ëˆœ™\]Y\ÝÚYŽˆ™\]Y\ÝÚYˆBˆYˆ™\ÜÙ]Kš\ÛÙ›Ü›X]

H›Ý[ˆ\ÝÜžN‚ˆ\ÝÜžK˜\[™
™\ÜÙ]Kš\ÛÙ›Ü›X]

JBˆ]VÈ™Z[WÜ™XØ\ÜÙ[Ù]\È—HH\ÝÜžVËM—BˆØ]™WÙ]J]JBˆ\›ÙÙÙ\‹Ø\›š[™Êˆ–ÑRSWÔ‘PÐTHÙ[™ØÛÛ\]H™\]Y\ÝÚYI\È™\ÜÙ]OI\ÈXØÙ\YÜ™XÚ\Y[ÏI\È‹ˆ™\]Y\ÝÚYˆ™\ÜÙ]Kš\ÛÙ›Ü›X]

Kˆ[Š[]™\šY\ÊKˆ
Bˆ™]\›ˆÂˆœÙ[ŽˆYKˆ™[]™\žWÜÝ]\ÈŽˆ˜XØÙ\YØžWÜ›ÝšY\ˆ‹ˆ™]HŽˆ™\ÜÙ]Kš\ÛÙ›Ü›X]

Kˆœ™XÚ\Y[ÈŽˆ[ŠRSWÔ‘PÐTÔ‘PÒTQS•ÊKˆ™[]™\šY\ÈŽˆ[]™\šY\Ëˆœ™\]Y\ÝÚYŽˆ™\]Y\ÝÚYˆB‚‚\œÜÝ
‹Ú[\›˜[ØÜ›Û‹ÙZ[K\™XØ\ŠB™Yˆ[\›˜[ØÜ›Û—ÙZ[WÜ™XØ\

N‚ˆ^XÝYHÜË™[š\›Û‹™Ù]
Ô“Ó—ÔÑPÔ‘U‹ˆŠKœÝš\

Bˆ›ÝšYYH
™\]Y\ÝšXY\œË™Ù]
–PÜ›Û‹TÙXÜ™]ŠHÜˆ™\]Y\Ý˜\™ÜË™Ù]
ÚÙ[ˆŠHÜˆˆŠKœÝš\

BˆYˆ^XÝY[™›ÝXXË˜ÛÛ\\™WÙYÙ\Ý
^XÝY›ÝšYY
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™›Ü˜šY[ˆŸJKÂˆ™\Ý[H[—ÙZ[WÜ™XØ\

BˆÈXZÙH[]™\žH˜Z[\™\Èš\ÚX›H\È˜Z[Y™[™\ˆ›ØœËˆ™]š[Ý\ÛHBˆÈ[™Ú[™]\›™YŒ]™[ˆÚ[ˆœ™]›È™Z™XÝYHY\ÜØYÙKÛÈBˆÈØÚY[\ˆZ\ÛXY[™ÛH™\ÜYHÝXØÙ\ÜÙ[^XÝ][Û‹‚ˆÝ]\×ØÛÙHHLˆYˆ™\Ý[™Ù]
œ™X\ÛÛˆŠHOH™[XZ[Ù\œ›Üˆˆ[ÙHŒˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆÝ]\×ØÛÙHOHŒ
Šœ™\Ý[JKÝ]\×ØÛÙB‚‚\˜ÛK˜ÛÛ[X[™
œÙ[™XÛÛ›ØØ][Û‹\ÚYÛ˜]\™K\™[Z[™\œÈŠB™YˆÛWÜÙ[™ØÛÛ›ØØ][Û—ÜÚYÛ˜]\™WÜ™[Z[™\œÊ
N‚ˆ™\Ý[HÂˆœÚYÛ˜]\™WÜ™[Z[™\œÈŽˆ[—ØÛÛ›ØØ][Û—ÜÚYÛ˜]\™WÜ™[Z[™\œÊ
Kˆ˜Z[š[™×ØÛÛ›ØØ][ÛœÈŽˆ[—Ý˜Z[š[™×ØÛÛ›ØØ][Û—Ü™[Z[™\œÊ
KˆBˆš[
œÛÛ‹™[\Ê™\Ý[[œÝ\™WØ\ØÚZOQ˜[ÙJJB‚‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ›ØØ][Û‹\ÚYÛ™YKœˆŠB\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ™[[Û‹\ÚYÛ™YKœˆŠB\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ™[[Û‹ÜÚYÛ™Y\ˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—ÝšY]×ÜÚYÛ™YØÛÛ™[[ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆË˜Z[™Y\ËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆX›Ü

BˆÝ]HHÞ[Ý\ÚYÛ—ÜÝ]J
BˆXœ×Ü]HÙ^\Ý[™×Þ[Ý\ÚYÛ—ÜÚYÛ™YØÛÛ™[[Û—ÜŠÝ]K˜Z[™YWÚY
BˆYˆ›ÝXœ×Ü]‚ˆYˆ›ÝÞ[Ý\ÚYÛ—Ú\×ØÛÛ™šYÝ\™Y

N‚ˆ\›ÙÙÙ\‹™\œ›ÜŠˆ–ÖSÕTÒQÓ—HÚYÛ™YÛÛ™[[Ûˆ™XÛÝ™\žH[˜]˜Z[X›H˜Z[™YWÚYI\È™X\ÛÛ[›ÝØÛÛ™šYÝ\™Y‹ˆ˜Z[™YWÚYˆ
Bˆ›\Ú
’[\ÜÜÚX›HH°êXÝ\0ê\™\ˆHÛÛ™[[ÛˆÚYÛ°êYHˆ[Ý\ÚYÛˆ¸ &Y\Ý\ÈÛÛ™šYÝ\°êKˆ‹™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚYØ[˜ÚÜH˜]]ÛX][Û’XˆŠJBˆ™\]Y\ÝÚYHˆ‚ˆžN‚ˆ™XÛÝ™\™YÜ™\]Y\ÝHÙš[™ÜÝÜ™YØÛÛ\]YÞ[Ý\ÚYÛ—ØÛÛ™[[Û—Ü™\]Y\Ý

BˆYˆ›Ý™XÛÝ™\™YÜ™\]Y\Ý‚ˆ™XÛÝ™\™YÜ™\]Y\ÝHÙš[™ØÛÛ\]YÞ[Ý\ÚYÛ—ØÛÛ™[[Û—Ü™\]Y\Ý
Ù\ÜÚ[Û—ÚY˜Z[™YWÚY
Bˆ™\]Y\ÝÚYHÝŠ™XÛÝ™\™YÜ™\]Y\Ý™Ù]
šYŠHÜˆˆŠKœÝš\

BˆYˆ›Ý™\]Y\ÝÚY‚ˆ™XÛÝ™\žWÛY\ÜØYÙHHÜÚYÛ™YØÛÛ™[[Û—Ü™XÛÝ™\žWÛY\ÜØYÙJ
Bˆ\›ÙÙÙ\‹Ø\›š[™Êˆ–ÖSÕTÒQÓ—HÚYÛ™YÛÛ™[[Ûˆ[˜]˜Z[X›H˜Z[™YWÚYI\È™X\ÛÛ\™\]Y\ÝÛ›ÝÙ›Ý[™‹ˆ˜Z[™YWÚYˆ
BˆÝ]VÈœÚYÛ™YÜ—Ü™XÛÝ™\žWÙ\œ›Üˆ—HH™XÛÝ™\žWÛY\ÜØYÙBˆÝ]VÈœÚYÛ™YÜ—Ü™XÛÝ™\žWØÚXÚÙYØ]—HHÛ›Ý×Ú\ÛÊ
BˆÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
BˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ›\Ú
™XÛÝ™\žWÛY\ÜØYÙK™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚYØ[˜ÚÜH˜]]ÛX][Û’XˆŠJBˆÈH™XYÜ™XÛÝ™\žH]\Ý›ÝØÚY[HH™]ÈÛÛ›ØØ][ÛˆÜˆÝ™\Üš]BˆÈH™]Ù\ˆÚYÛ˜]\™H™\]Y\ÝÚ][ˆÛ\‹ÛÛ\]Y™\]Y\Ý‚ˆXœ×Ü]HÙÝÛ›ØYÞ[Ý\ÚYÛ—ÜÚYÛ™YÜŠ™\]Y\ÝÚY˜Z[™YWÚY
BˆÚYÛ™YØ]H
ˆ™XÛÝ™\™YÜ™\]Y\Ý™Ù]
˜ÛÛ\]YØ]ŠHÜˆÝ]K™Ù]
œÚYÛ™YØ]ŠBˆÜˆ™Ù]
˜ÛÛ™[[Û—Ø\×ÜÚYÛ™YØ]ŠHÜˆ™Ù]
˜ÛÛ™[[Û—ÛYØXÞWÜÚYÛ™YØ]ŠHÜˆˆ‚ˆ
BˆYˆ›ÝÝ]K™Ù]
œÚYÛ˜]\™WÜ™\]Y\ÝÚYŠHÜˆÝ]K™Ù]
œÚYÛ˜]\™WÜ™\]Y\ÝÚYŠHOH™\]Y\ÝÚY‚ˆÝ]K\]JÂˆœÚYÛ˜]\™WÜ™\]Y\ÝÚYŽˆ™\]Y\ÝÚYˆ™^\›˜[ÚYŽˆ™XÛÝ™\™YÜ™\]Y\Ý™Ù]
™^\›˜[ÚYŠHÜˆÝ]K™Ù]
™^\›˜[ÚYŠHÜˆˆ‹ˆœÝ]\ÈŽˆ™Û™H‹ˆœÚYÛ™YØ]ŽˆÚYÛ™YØ]ˆ›™^Ü™[Z[™\—Ø]Žˆˆ‹ˆ›\ÝÙ\œ›ÜˆŽˆˆ‹ˆJBˆÝ]K\]JÂˆœÚYÛ™YÜ—Ü]ŽˆXœ×Ü]ˆœÚYÛ™YÜ—ÝÚÙ[ˆŽˆÜÝÜ™WÜX›X×Ùš[WÝÚÙ[ŠXœ×Ü]
KˆœÚYÛ™YÜ—Ü™\]Y\ÝÚYŽˆ™\]Y\ÝÚYˆœÚYÛ™YÜ—ØÛÛ\]YØ]ŽˆÚYÛ™YØ]ˆœÚYÛ™YÜ—ÜÛÝ\˜ÙHŽˆž[Ý\ÚYÛˆ‹ˆJBˆÝ]KœÜ
œÚYÛ™YÜ—Ü™XÛÝ™\žWÙ\œ›Üˆ‹›Û™JBˆÝ]KœÜ
œÚYÛ™YÜ—Ü™XÛÝ™\žWØÚXÚÙYØ]‹›Û™JBˆÈ˜ÛÛ™[[Û—ÜÝ]\È—HHœÚYÛ™Y‚ˆÈ˜ÛÛ™[[Û—Ø\×ÜÝ]\È—HHœÚYÛ™Y‚ˆÈ˜ÛÛ™[[Û—Ø\×ÜÚYÛ™YØ]—HHÚYÛ™YØ]ˆÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
BˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ\›ÙÙÙ\‹š[™›Êˆ–ÖSÕTÒQÓ—HÚYÛ™YÛÛ™[[Ûˆ™XÛÝ™\™YÛˆÝÛ›ØY˜Z[™YWÚYI\È™\]Y\ÝÚYI\È‹ˆ˜Z[™YWÚYˆ™\]Y\ÝÚYˆ
Bˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆ™XÛÝ™\žWÛY\ÜØYÙHH
ˆ“HÛÛ›™^[Ûˆ[Ý\ÚYÛˆXÝY[H™H\›Y]\È8 &XXØðêY\ˆ0èÙ]H[X[™Kˆ°ê\šYšY^ˆ\ÈXØðêÈ]HÛÛ\H[Ý\ÚYÛ‹Z\È°êY\ÜØ^Y^‹ˆ‚ˆYˆ\Ú[œÝ[˜ÙJ^Ë[Ý\ÚYÛTQ\œ›ÜŠH[™^ËœÝ]\×ØÛÙH[ˆÍKßBˆ[ÙH“H°êXÝ\0ê\˜][Ûˆ]]ÛX]\]YH\Z\È[Ý\ÚYÛˆH0êXÚÝpêKˆ°êY\ÜØ^Y^ˆÝH[\Ü^ˆHˆÚYÛ°êHÚH›Ý\ÈHÜÜðêY^‹ˆ‚ˆ
Bˆ\›ÙÙÙ\‹™^Ù\[ÛŠˆ–ÖSÕTÒQÓ—HÚYÛ™YÛÛ™[[Ûˆ™XÛÝ™\žH˜Z[Y˜Z[™YWÚYI\È™\]Y\ÝÚYI\È\œ›ÜI\È‹ˆ˜Z[™YWÚYˆ™\]Y\ÝÚYˆÜØ[š]^™WÞ[Ý\ÚYÛ—Ù\œ›ÜŠÝŠ^ÊJKˆ
BˆÝ]VÈœÚYÛ™YÜ—Ü™XÛÝ™\žWÙ\œ›Üˆ—HH™XÛÝ™\žWÛY\ÜØYÙBˆÝ]VÈœÚYÛ™YÜ—Ü™XÛÝ™\žWØÚXÚÙYØ]—HHÛ›Ý×Ú\ÛÊ
BˆÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
BˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆžN‚ˆØ]™WÙ]J]JBˆ^Ù\^Ù\[ÛŽ‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠˆ–ÖSÕTÒQÓ—H[˜X›HÈ\œÚ\ÝÛÛ™[[Ûˆ™XÛÝ™\žH\œ›Üˆ˜Z[™YWÚYI\È‹ˆ˜Z[™YWÚYˆ
Bˆ›\Ú
™XÛÝ™\žWÛY\ÜØYÙK™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚYØ[˜ÚÜH˜]]ÛX][Û’XˆŠJBˆYˆ›ÝXœ×Ü]‚ˆ›\Ú
“HˆÚYÛ°êH\Ý[›Ý]˜X›Kˆ[\Ü^‹[H\Z\ÈH›ØÈÛÛ™[[Û‹ˆ‹™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚYØ[˜ÚÜH˜]]ÛX][Û’XˆŠJBˆ\×Ø]XÚY[HÝŠ™\]Y\Ý˜\™ÜË™Ù]
™ÝÛ›ØYŠHÜˆˆŠKœÝš\

K›ÝÙ\Š
H[ˆÈŒH‹YH‹žY\È‹›ÛˆŸBˆ™]\›ˆÙ[™Ùš[JXœ×Ü]Z[Y]\OH˜\XØ][Û‹Üˆ‹\×Ø]XÚY[X\×Ø]XÚY[ÝÛ›ØYÛ˜[YO[ÜËœ]˜˜\Ù[˜[YJXœ×Ü]
JB‚‚\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ™[[Û‹ÜÚYÛ™Y\‹Ý\ØYŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™YˆYZ[—Ý\ØYÜÚYÛ™YØÛÛ™[[ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆË˜Z[™Y\ËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆX›Ü

Bˆ™Y\™XÝÝ\›H\›Ù›ÜŠˆ˜YZ[—Ý˜Z[™YWÜYÙH‹ˆÙ\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚYˆ˜Z[™YWÚY]˜Z[™YWÚYˆØ[˜ÚÜH˜]]ÛX][Û’Xˆ‹ˆ
BˆYˆ›ÝÝ˜Z[™YWØÛÛ™[[Û—Ú\×ÜÚYÛ™Y

N‚ˆ›\Ú
“HÛÛ™[[ÛˆÚ]0ê™HX\œ]pêYHÛÛ[YHÚYÛ°êYH]˜[8 &Z[\Ü\ˆÛÛˆ‹ˆ‹™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
™Y\™XÝÝ\›
Bˆ[˜ÛÛZ[™×Ùš[HH™\]Y\Ý™š[\Ë™Ù]
œÚYÛ™YÜˆŠBˆYˆ›Ý[˜ÛÛZ[™×Ùš[HÜˆ›Ý[˜ÛÛZ[™×Ùš[K™š[[˜[YN‚ˆ›\Ú
ÚÚ\Ú\ÜÙ^ˆHÛÛ™[[ÛˆÚYÛ°êYH]H›Ü›X]‹ˆ‹™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
™Y\™XÝÝ\›
BˆYˆÜØY™WÙ^
[˜ÛÛZ[™×Ùš[K™š[[˜[YJHOH‹œˆŽ‚ˆ›\Ú
”Ù][[ˆšXÚY\ˆˆ]]0ê™H[\Ü0êHÛÛ[YHÛÛ™[[ÛˆÚYÛ°êYKˆ‹™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
™Y\™XÝÝ\›
Bˆ—Øž]\ÈH[˜ÛÛZ[™×Ùš[Kœ™XY

Ì
ˆL
ˆL
H
ÈJBˆYˆ[Š—Øž]\ÊHˆÌ
ˆL
ˆL‚ˆ›\Ú
“HˆÚYÛ°êH0ê\\ÜÙHHZ[HX^[X[HHÌ[Ëˆ‹™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
™Y\™XÝÝ\›
BˆžN‚ˆÚYÛ™YÜ]HÜÝÜ™WÜÚYÛ™YØÛÛ™[[Û—Ü—Øž]\Ê—Øž]\Ë˜Z[™YWÚY
Bˆ^Ù\[[YQ\œ›Üˆ\È^Î‚ˆ›\Ú
ÝŠ^ÊK™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
™Y\™XÝÝ\›
B‚ˆ›ÝÈHÛ›Ý×Ú\ÛÊ
BˆÝ]HHÞ[Ý\ÚYÛ—ÜÝ]J
BˆÝ]K\]JÂˆœÝ]\ÈŽˆ™Û™H‹ˆœÚYÛ™YØ]ŽˆÝ]K™Ù]
œÚYÛ™YØ]ŠHÜˆ™Ù]
˜ÛÛ™[[Û—Ø\×ÜÚYÛ™YØ]ŠHÜˆ™Ù]
˜ÛÛ™[[Û—ÛYØXÞWÜÚYÛ™YØ]ŠHÜˆ›ÝËˆœÚYÛ™YÜ—Ü]ŽˆÚYÛ™YÜ]ˆœÚYÛ™YÜ—ÝÚÙ[ˆŽˆÜÝÜ™WÜX›X×Ùš[WÝÚÙ[ŠÚYÛ™YÜ]
KˆœÚYÛ™YÜ—ÜÛÝ\˜ÙHŽˆ›X[X[Ý\ØY‹ˆœÚYÛ™YÜ—ÛÜšYÚ[˜[Û˜[YHŽˆÙXÝ\™WÙš[[˜[YJ[˜ÛÛZ[™×Ùš[K™š[[˜[YHÜˆ˜ÛÛ™[[Û‹\ÚYÛ™YKœˆŠVÎŒNKˆœÚYÛ™YÜ—Ý\ØYYØ]Žˆ›ÝËˆ›\ÝÙ\œ›ÜˆŽˆˆ‹ˆJBˆÝ]KœÜ
œÚYÛ™YÜ—Ü™XÛÝ™\žWÙ\œ›Üˆ‹›Û™JBˆÝ]KœÜ
œÚYÛ™YÜ—Ü™XÛÝ™\žWØÚXÚÙYØ]‹›Û™JBˆÈ˜ÛÛ™[[Û—ÜÝ]\È—HHœÚYÛ™Y‚ˆÈ˜ÛÛ™[[Û—Ø\×ÜÝ]\È—HHœÚYÛ™Y‚ˆÈ˜ÛÛ™[[Û—Ø\×ÜÚYÛ™YØ]—HHÝ]K™Ù]
œÚYÛ™YØ]ŠHÜˆ›ÝÂˆÈ\]YØ]—HH›ÝÂˆ\[™Ý˜Z[™YWÚ\ÝÜžWÙ]™[
ˆˆÛÛ™[[ÛˆÚYÛ°êYH[\Ü0êYH‹ˆÝ]K™Ù]
œÚYÛ™YÜ—ÛÜšYÚ[˜[Û˜[YHŠHÜˆ”ˆÚYÛ°êH‹ˆ˜XÝ[Ûˆ‹ˆ›ÝËˆ
BˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JBˆ›\Ú
“HÛÛ™[[ÛˆÚYÛ°êYHH0ê]0êH[\Ü0êYKˆ\È›Ý]ÛœÈ›Ú\ˆ]0ê[0êXÚ\™Ù\ˆÛÛXZ[[˜[XÝYœËˆ‹œÝXØÙ\ÜÈŠBˆ™]\›ˆ™Y\™XÝ
™Y\™XÝÝ\›
B‚‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ™[[Û‹ÛÜšYÚ[˜[\ˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—ÝšY]×ÛÜšYÚ[˜[ØÛÛ™[[ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆËËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆX›Ü

BˆÝ]HHÞ[Ý\ÚYÛ—ÜÝ]J
Bˆ—Ü]HÝŠÝ]K™Ù]
[œÚYÛ™YÜ—Ü]ŠHÜˆ™Ù]
˜ÛÛ™[[Û—Ø\×Ü—Ü]ŠHÜˆˆŠBˆXœ×Ü]HÜËœ]˜XœÜ]
—Ü]
HYˆ—Ü][ÙHˆ‚ˆ›ÛÝHÜËœ]˜XœÜ]
SÕTÒQÓ—ÐÓÓ•‘S•SÓ—ÑTŠBˆYˆ›ÝXœ×Ü]Üˆ›ÝXœ×Ü]œÝ\ÝÚ]
›ÛÝ
ÈÜËœÙ\
HÜˆ›ÝÜËœ]™^\ÝÊXœ×Ü]
N‚ˆX›Ü

Bˆ\×Ø]XÚY[HÝŠ™\]Y\Ý˜\™ÜË™Ù]
™ÝÛ›ØYŠHÜˆˆŠKœÝš\

K›ÝÙ\Š
H[ˆÈŒH‹YH‹žY\È‹›ÛˆŸBˆ™]\›ˆÙ[™Ùš[JXœ×Ü]Z[Y]\OH˜\XØ][Û‹Üˆ‹\×Ø]XÚY[X\×Ø]XÚY[ÝÛ›ØYÛ˜[YO[ÜËœ]˜˜\Ù[˜[YJXœ×Ü]
JB‚‚\™Ù]
‹Ù\ÜXÙKÏÚÙ[‹ØÛÛ›ØØ][Û‹ÜÚYÛ˜]\™HŠB\™Ù]
‹Ù\ÜXÙKÏÚÙ[‹ØÛÛ™[[Û‹ÜÚYÛ˜]\™HŠB™YˆX›X×ØÛÛ™[[Û—ÜÚYÛ˜]\™WÜ™Y\™XÝ
ÚÙ[ŽˆÝŠN‚ˆ]HHØYÙ]J
BˆËHš[™ÜÙ\ÜÚ[Û—Ø[™Ý˜Z[™YWØžWÝÚÙ[Š]KÚÙ[ŠBˆYˆ›ÝÈÜˆ›Ý‚ˆX›Ü

BˆYˆ›ÝÜX›X×Ú\×Ø]]Y
ÚÙ[ŠN‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠœX›X×Ý˜Z[™YWÛÙÚ[ˆ‹ÚÙ[]ÚÙ[ŠJBˆÝ]HHÞ[Ý\ÚYÛ—ÜÝ]J
Bˆ[šÈHÝŠÝ]K™Ù]
œÚYÛ˜]\™WÛ[šÈŠHÜˆˆŠKœÝš\

BˆYˆ›Ý[šÈÜˆÚ\×Þ[Ý\ÚYÛ—ÜÚYÛ˜]\™WÙÛ™JÝ]JN‚ˆ›\Ú
]XÝ[™HÛÛ™[[Ûˆ¸ &Y\Ý[ˆ][HHÚYÛ˜]\™Kˆ‹™\œ›ÜˆŠBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠœX›X×Ý˜Z[™YWÜÜXÙH‹ÚÙ[]ÚÙ[ŠJBˆ\›ÙÙÙ\‹š[™›Ê–ÖSÕTÒQÓ—HX›XÈÚYÛ˜]\™H™Y\™XÝ˜Z[™YWÚYI\È‹™Ù]
šYŠJBˆ™]\›ˆ™Y\™XÝ
[šÊB‚‚\œÜÝ
‹ÝÙXšÛÚÜËÞ[Ý\ÚYÛˆŠB™YˆÙXšÛÚÜ×Þ[Ý\ÚYÛŠ
N‚ˆ˜]×Ø›ÙHH™\]Y\Ý™Ù]Ù]JØXÚOUYJBˆYˆ›ÝÝ™\šYžWÞ[Ý\ÚYÛ—ÝÙXšÛÚ×ÜÚYÛ˜]\™J˜]×Ø›ÙJN‚ˆ\›ÙÙÙ\‹Ø\›š[™Ê–ÖSÕTÒQÓ—HÙXšÛÚÈ[˜[YÚYÛ˜]\™HŠBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆš[˜[YÜÚYÛ˜]\™HŸJKBˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆ]™[Û˜[YHHÝŠ^[ØY™Ù]
™]™[Û˜[YHŠHÜˆ^[ØY™Ù]
™]™[ŠHÜˆˆŠKœÝš\

BˆÚYÛ˜]\™WÜ™\]Y\ÝÜ^[ØYHÞ[Ý\ÚYÛ—Ü^[ØYÜÚYÛ˜]\™WÜ™\]Y\Ý
^[ØY
Bˆ™\]Y\ÝÚYHÞ[Ý\ÚYÛ—ÝÙXšÛÚ×ÜÚYÛ˜]\™WÜ™\]Y\ÝÚY
^[ØY
BˆYˆ›Ý™\]Y\ÝÚY‚ˆ]WÚÙ^\ÈHÛÜY

^[ØY™Ù]
™]HŠHÜˆßJKšÙ^\Ê
JHYˆ\Ú[œÝ[˜ÙJ^[ØY™Ù]
™]HŠKXÝ
H[ÙH×Bˆ\›ÙÙÙ\‹Ø\›š[™Êˆ–ÖSÕTÒQÓ—HÙXšÛÚÈZ\ÜÚ[™ÈÚYÛ˜]\™H™\]Y\ÝY]™[I\È]WÚÙ^\ÏI\È‹ˆ]™[Û˜[YKˆ]WÚÙ^\Ëˆ
Bˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›Z\ÜÚ[™×ÜÚYÛ˜]\™WÜ™\]Y\ÝÚYŸJKŒ‚ˆ\›ÙÙÙ\‹š[™›Ê–ÖSÕTÒQÓ—HÙXšÛÚÈ™XÙZ]™Y]™[I\È™\]Y\ÝÚYI\È‹]™[Û˜[YK™\]Y\ÝÚY
Bˆ^[ØYÜÝ]\ÈHÞ[Ý\ÚYÛ—ÜÚYÛ˜]\™WÜ™\]Y\ÝÜÝ]\Ê^[ØY
BˆÛ™WÙ]™[ÈHÈœÚYÛ˜]\™WÜ™\]Y\Ý™Û™H‹œÚYÛ˜]\™WÜ™\]Y\Ý˜ÛÛ\]Y‹œÚYÛ™\‹™Û™H‹œÚYÛ™\‹˜ÛÛ\]YŸBˆYˆ]™[Û˜[YH›Ý[ˆÛ™WÙ]™[È[™^[ØYÜÝ]\È›Ý[ˆSÕTÒQÓ—Ñ’SSÔÕUTÑTÎ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKšYÛ›Ü™YŽˆY_JBˆ]HHØYÙ]J
Bˆ\ÜÜÙ\ÜÚ[ÛˆHÙš[™ÜÙ\ÜÚ[Û—ØžWÙ\ÜÚÚXÚÛÙ™—Þ[Ý\ÚYÛ—Ü™\]Y\ÝÚY
]K™\]Y\ÝÚY
BˆYˆ\ÜÜÙ\ÜÚ[ÛŽ‚ˆ]™[ÚYHÝŠ^[ØY™Ù]
™]™[ÚYŠHÜˆˆŠBˆ\×Ü™\]Y\ÝÙÛ™WÙ]™[H]™[Û˜[YH[ˆÂˆœÚYÛ˜]\™WÜ™\]Y\Ý™Û™H‹ˆœÚYÛ˜]\™WÜ™\]Y\Ý˜ÛÛ\]Y‹ˆBˆYˆ\×Ü™\]Y\ÝÙÛ™WÙ]™[Üˆ^[ØYÜÝ]\È[ˆSÕTÒQÓ—Ñ’SSÔÕUTÑTÎ‚ˆžN‚ˆÛX\š×Þ[Ý\ÚYÛ—Ù\ÜÚÚXÚÛÙ™—ÜÚYÛ™Y
\ÜÜÙ\ÜÚ[Û‹™\]Y\ÝÚY]™[ÚY
BˆØ]™WÙ]J]JBˆ\›ÙÙÙ\‹š[™›Êˆ–ÖSÕTÒQÓ—HÚYÛ™YØÝ[Y[ÝÜ™Y\OY\ÜÚÚXÚÛÙ™ˆÙ\ÜÚ[Û—ÚYI\È™\]Y\ÝÚYI\È‹ˆ\ÜÜÙ\ÜÚ[Û‹™Ù]
šYŠKˆ™\]Y\ÝÚYˆ
Bˆ™]\›ˆœÛÛšYžJÂˆ›ÚÈŽˆYKˆ\]YŽˆYKˆœÝ]\ÈŽˆœÚYÛ™Y‹ˆ™ØÝ[Y[Ý\HŽˆ™\ÜÚÚXÚÛÙ™ˆ‹ˆJBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆY\ÜØYÙHHÜØ[š]^™WÞ[Ý\ÚYÛ—Ù\œ›ÜŠÝŠ^ÊJBˆÝ]HHÙ\ÜÚÚXÚÛÙ™—Ø][™[˜ÙWÜÝ]J\ÜÜÙ\ÜÚ[Û‹Ü™X]OUYJBˆÝ]VÈœÝ]\È—HH™ÝÛ›ØYÙ\œ›Üˆ‚ˆÝ]VÈ›\ÝÙ\œ›Üˆ—HHY\ÜØYÙBˆÝ]VÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
BˆØ]™WÙ]J]JBˆ\›ÙÙÙ\‹™^Ù\[ÛŠˆ–ÖSÕTÒQÓ—HTÔÚYÛ™YˆÝÛ›ØY˜Z[Y™\]Y\ÝÚYI\È\œ›ÜI\È‹ˆ™\]Y\ÝÚYˆY\ÜØYÙKˆ
Bˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆœÚYÛ™YÜ—ÙÝÛ›ØYÙ˜Z[YŸJKL‚ˆ^[ØYÙ]HH^[ØY™Ù]
™]HŠHYˆ\Ú[œÝ[˜ÙJ^[ØY™Ù]
™]HŠKXÝ
H[ÙHßBˆÚYÛ™\—Ü^[ØYH^[ØYÙ]K™Ù]
œÚYÛ™\ˆŠHYˆ\Ú[œÝ[˜ÙJ^[ØYÙ]K™Ù]
œÚYÛ™\ˆŠKXÝ
H[ÙHßBˆÚYÛ™\—ÚYHÝŠÚYÛ™\—Ü^[ØY™Ù]
šYŠHÜˆ^[ØYÙ]K™Ù]
œÚYÛ™\—ÚYŠHÜˆˆŠKœÝš\

Bˆ\]YH›ÛÛ
ˆÚYÛ™\—ÚYˆ[™ÛX\š×Þ[Ý\ÚYÛ—Ù\ÜÚÚXÚÛÙ™—ÜÚYÛ™\—ÜÚYÛ™Y
ˆ\ÜÜÙ\ÜÚ[Û‹ˆÚYÛ™\—ÚYˆ]™[ÚYˆ
Bˆ
BˆYˆ\]Y‚ˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÂˆ›ÚÈŽˆYKˆ\]YŽˆ\]YˆœÝ]\ÈŽˆœ\X[WÜÚYÛ™Y‹ˆ™ØÝ[Y[Ý\HŽˆ™\ÜÚÚXÚÛÙ™ˆ‹ˆJB‚ˆ\™Ù]Ý\HH˜\×Ù[X\›š[™È‚ˆÙ\ÜË˜Z[™Y\Ë˜Z[™YHHÙš[™Ý˜Z[™YWØžWØ\×Ù[X\›š[™×Þ[Ý\ÚYÛ—Ü™\]Y\ÝÚY
]K™\]Y\ÝÚY
BˆYˆ›Ý˜Z[™YN‚ˆ™\]Y\ÝÚ][HHXÝ
ÚYÛ˜]\™WÜ™\]Y\ÝÜ^[ØY
HYˆ\Ú[œÝ[˜ÙJÚYÛ˜]\™WÜ™\]Y\ÝÜ^[ØYXÝ
H[ÙHßBˆ™\]Y\ÝÚ][KœÙ]Y˜][
šY‹™\]Y\ÝÚY
Bˆ^\›˜[ÚYHÝŠ™\]Y\ÝÚ][K™Ù]
™^\›˜[ÚYŠHÜˆˆŠKœÝš\

BˆYˆ›Ý^\›˜[ÚY‚ˆžN‚ˆ™\]Y\ÝÚ][HHÞ[Ý\ÚYÛ—ÚœÛÛŠ‘ÑU‹ˆ‹ÜÚYÛ˜]\™WÜ™\]Y\ÝËÞÜ™\]Y\ÝÚYHŠBˆ^Ù\^Ù\[ÛŽ‚ˆ\›ÙÙÙ\‹Ø\›š[™Êˆ–ÖSÕTÒQÓ—H[˜X›HÈ™\ÛÛ™H[›X]ÚYÙXšÛÚÈ™\]Y\ÝÚYI\È‹ˆ™\]Y\ÝÚYˆ^×Ú[™›ÏUYKˆ
Bˆ^\›˜[ÚYHÝŠ™\]Y\ÝÚ][K™Ù]
™^\›˜[ÚYŠHÜˆˆŠKœÝš\

BˆÙ\ÜË˜Z[™Y\Ë˜Z[™YHHÙš[™Ý˜Z[™YWØžWØ\×Ù[X\›š[™×Þ[Ý\ÚYÛ—Ù^\›˜[ÚY
ˆ]Kˆ^\›˜[ÚYˆ™\]Y\ÝÚ][Kˆ
BˆYˆ˜Z[™YN‚ˆØYÜØÛÛ\]YÞ[Ý\ÚYÛ—Ø\×Ù[X\›š[™×Ü™\]Y\Ý
˜Z[™YK™\]Y\ÝÚ][JBˆYˆ›Ý˜Z[™YN‚ˆ\™Ù]Ý\HH˜ÛÛ™[[Ûˆ‚ˆÙ\ÜË˜Z[™Y\Ë˜Z[™YHHÙš[™Ý˜Z[™YWØžWÞ[Ý\ÚYÛ—Ü™\]Y\ÝÚY
]K™\]Y\ÝÚY
BˆYˆ›Ý˜Z[™YN‚ˆ\›ÙÙÙ\‹Ø\›š[™Êˆ–ÖSÕTÒQÓ—HÛÛ\]Y™\]Y\Ý›Ý›Ý[™ØØ[H]™[I\È™\]Y\ÝÚYI\È‹ˆ]™[Û˜[YKˆ™\]Y\ÝÚYˆ
Bˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆœÚYÛ˜]\™WÜ™\]Y\ÝÛ›ÝÙ›Ý[™ŸJKBˆÝ]HHØ\×Ù[X\›š[™×ÜÚYÛ˜]\™WÜÝ]J˜Z[™YJHYˆ\™Ù]Ý\HOH˜\×Ù[X\›š[™Èˆ[ÙHÞ[Ý\ÚYÛ—ÜÝ]J˜Z[™YJBˆžN‚ˆYˆ\™Ù]Ý\HOH˜\×Ù[X\›š[™ÈŽ‚ˆÛX\š×Þ[Ý\ÚYÛ—Ø\×Ù[X\›š[™×Ý˜XÚÚ[™×ÜÚYÛ™Y
ˆ]KˆÙ\ÜËˆ˜Z[™Y\Ëˆ˜Z[™YKˆ™\]Y\ÝÚYˆÝŠ^[ØY™Ù]
™]™[ÚYŠHÜˆˆŠKˆ
Bˆ[ÙN‚ˆÛX\š×Þ[Ý\ÚYÛ—ØÛÛ™[[Û—ÜÚYÛ™Y
]KÙ\ÜË˜Z[™Y\Ë˜Z[™YK™\]Y\ÝÚYÝŠ^[ØY™Ù]
™]™[ÚYŠHÜˆˆŠJBˆØ]™WÙ]J]JBˆ\›ÙÙÙ\‹š[™›Êˆ–ÖSÕTÒQÓ—HÚYÛ™YØÝ[Y[ÝÜ™Y\OI\È˜Z[™YWÚYI\È™\]Y\ÝÚYI\È‹ˆ\™Ù]Ý\Kˆ˜Z[™YK™Ù]
šYŠKˆ™\]Y\ÝÚYˆ
Bˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK\]YŽˆYKœÝ]\ÈŽˆœÚYÛ™Y‹™ØÝ[Y[Ý\HŽˆ\™Ù]Ý\_JBˆ^Ù\^Ù\[Ûˆ\È^Î‚ˆY\ÜØYÙHHÜØ[š]^™WÞ[Ý\ÚYÛ—Ù\œ›ÜŠÝŠ^ÊJBˆ\›ÙÙÙ\‹™^Ù\[ÛŠ–ÖSÕTÒQÓ—HÚYÛ™YˆÝÛ›ØY˜Z[Y™\]Y\ÝÚYI\È\œ›ÜI\È‹™\]Y\ÝÚYY\ÜØYÙJBˆYˆ\™Ù]Ý\HOH˜\×Ù[X\›š[™ÈŽ‚ˆÜ™XÛÜ™Þ[Ý\ÚYÛ—Ø\×Ù[X\›š[™×Ü—Ü™XÛÝ™\žWÙ\œ›ÜŠÙ\ÜË˜Z[™Y\Ë˜Z[™YKY\ÜØYÙJBˆ[ÙN‚ˆÝ]VÈœÝ]\È—HH™ÝÛ›ØYÙ\œ›Üˆ‚ˆÝ]VÈ›\ÝÙ\œ›Üˆ—HHY\ÜØYÙBˆÙ\ÜÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆœÚYÛ™YÜ—ÙÝÛ›ØYÙ˜Z[YŸJKL‚‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ØÛÛ›ØØ][Û‹X\ËœˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—ÝšY]×Ø\×ØÛÛ›ØØ][ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆËËHÙš[™ÜÙ\ÜÚ[Û—Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›ÝÜˆ›ÝÚ\×Ø\×ÜÙ\ÜÚ[ÛŠÊN‚ˆX›Ü

Bˆ—Ü]HÝŠ™Ù]
˜ÛÛ›ØØ][Û—Ø\×Ü—Ü]ŠHÜˆˆŠBˆXœ×Ü]HÜËœ]˜XœÜ]
—Ü]
HYˆ—Ü][ÙHˆ‚ˆYˆ›ÝXœ×Ü]Üˆ›ÝØ\×ØÛÛ›ØØ][Û—Ü—Ú\×Ø[ÝÙY
Xœ×Ü]
HÜˆ›ÝÜËœ]™^\ÝÊXœ×Ü]
N‚ˆX›Ü

Bˆ™]\›ˆÙ[™Ùš[JXœ×Ü]Z[Y]\OH˜\XØ][Û‹Üˆ‹\×Ø]XÚY[Q˜[ÙKÝÛ›ØYÛ˜[YO[ÜËœ]˜˜\Ù[˜[YJXœ×Ü]
JB‚‚‚‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ÝËXÛKX]]ÛÙÚ[ˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ý×ØÛWØ]]ÛÙÚ[ŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆX›Ü

B‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆH™^

›Üˆ[ˆ˜Z[™Y\ÈYˆ™Ù]
šYŠHOH˜Z[™YWÚY
K›Û™JBˆYˆ›Ý‚ˆX›Ü

B‚ˆÙÚ[ˆH
™Ù]
×ØÛWÛÙÚ[ˆŠHÜˆˆŠKœÝš\

Bˆ\ÜÝÛÜ™H
™Ù]
×ØÛWÜ\ÜÝÛÜ™ŠHÜˆˆŠKœÝš\

Bˆ˜Z[™YWÛ˜[YHHˆžÊ™Ù]
	Ùš\œÝÛ˜[YIÊHÜˆ	ÉÊKœÝš\

_HÊ™Ù]
	Û\ÝÛ˜[YIÊHÜˆ	ÉÊKœÝš\

_H‹œÝš\

HÜˆœÝYÚXZ\™H‚‚ˆYˆ›ÝÙÚ[ˆÜˆ›Ý\ÜÝÛÜ™‚ˆ™]\›ˆˆˆˆ‚YØÝ\H[‚[[™ÏH™œˆ‚XY‚ˆY]HÚ\œÙ]H]‹N‚ˆY]H˜[YOHšY]ÜÜˆÛÛ[HÚYY]šXÙK]ÚY[š]X[\ØØ[OLH‚ˆ]OÛÛ›™^[Ûˆ]]È^[Y[ÔÝ]O‚ˆÝ[O‚ˆ›ÙHÞÈ›ÛY˜[Z[Nˆ\šX[Ø[œË\Ù\šYŽÈX^]ÚYˆÍŒÈX\™Ú[Žˆ]]ÎÈY[™ÎˆMœÈ[™KZZYÚˆKNÈ_Bˆ˜Ø\™ÞÈ›Ü™\ŽŒ\ÛÛYÙMYMÙXŽÈ›Ü™\‹\˜Y]\ÎŒMÈY[™ÎŒNÈ˜XÚÙÜ›Ý[™ˆÙ™™ŽÈ_BˆØ\›ˆÞÈÛÛÜŽˆØLÌNÈ›Û]ÙZYÚÌÈX\™Ú[‹X›ÝÛNŒLÈ_BˆHÞÈÛÛÜŽˆÌYYÈ_BˆÜÝ[O‚ÚXY‚›ÙO‚ˆ]ˆÛ\ÜÏH˜Ø\™‚ˆ]ˆÛ\ÜÏHØ\›ˆ¸¦¨;î#ÈÛÛ›™^[Ûˆ]]ÛX]\]YH[\ÜÜÚX›OÙ]‚ˆ“\ÈY[YšX[È^[Y[ÔHÝ›Û™ÏžÚ[™\ØØ\J˜Z[™YWÛ˜[YJ_OÜÝ›Û™ÏˆÛÛ[˜ÛÛ\]ËÜ‚ˆ”™[œÙZYÛ™^ˆHÙÚ[ˆ]H[ÝH\ÜÙH[œÈ8 &Y\ÜXÙHÝYÚXZ\™KZ\È°êY\ÜØ^Y^‹Ü‚ˆH™YHžÝ\›Ù›ÜŠ	ØYZ[—Ý˜Z[™YWÜYÙIËÙ\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
_H¸¡¤™]Ý\ˆ0èHšXÚHÝYÚXZ\™OØOÜ‚ˆÙ]‚Ø›ÙO‚Ú[‚ˆˆˆ‹‚ˆÙÚ[—Ù\ØÈH[™\ØØ\JÙÚ[ŠBˆ\ÜÝÛÜ™Ù\ØÈH[™\ØØ\J\ÜÝÛÜ™
Bˆ\™Ù]Ý\›HšÎ‹ËÝÝÝË™^[Y[Ü™œ‹ÚYÌM‚‚ˆ™]\›ˆˆˆˆ‚YØÝ\H[‚[[™ÏH™œˆ‚XY‚ˆY]HÚ\œÙ]H]‹N‚ˆY]H˜[YOHšY]ÜÜˆÛÛ[HÚYY]šXÙK]ÚY[š]X[\ØØ[OLH‚ˆ]OÛÛ›™^[Ûˆ]]È^[Y[ÔÝ]O‚ˆÝ[O‚ˆ›ÙHÞÈ›ÛY˜[Z[Nˆ\šX[Ø[œË\Ù\šYŽÈX^]ÚYˆŒÈX\™Ú[Žˆ]]ÎÈY[™ÎˆMœÈ[™KZZYÚˆKNÈ_Bˆ˜Ø\™ÞÈ›Ü™\ŽŒ\ÛÛYÙMYMÙXŽÈ›Ü™\‹\˜Y]\ÎŒMÈY[™ÎŒNÈ˜XÚÙÜ›Ý[™ˆÙ™™ŽÈ_Bˆ›ÚÈÞÈÛÛÜŽˆÌMLÍÈ›Û]ÙZYÚÌÈ_Bˆš[ÞÈÛÛÜŽˆÍ˜ÌŽÈ_Bˆ˜ˆÞÈ\Ü^Nš[›[™KX›ØÚÎÈX\™Ú[‹]ÜŒLœÈ›Ü™\ŽŒ\ÛÛYÙYYŽÈ›Ü™\‹\˜Y]\ÎŽÈY[™ÎŽLœÈ^YXÛÜ˜][ÛŽ››Û™NÈÛÛÜŽˆÌLLNÎÈ˜XÚÙÜ›Ý[™ˆÙ™™ŽÈÝ\œÛÜŽœÚ[\ŽÈ_Bˆ˜ˆ
È˜ˆÞÈX\™Ú[‹[YŽÈ_BˆÜÝ[O‚ÚXY‚›ÙO‚ˆ]ˆÛ\ÜÏH˜Ø\™‚ˆ]ˆÛ\ÜÏH›ÚÈ¸§!H[]]™HHÛÛ›™^[Ûˆ]]ÛX]\]YH0è^[Y[Ô[ˆÛÝ\œø )Ù]‚ˆ“›Ý\È[›Þ[ÛœÈ]]ÛX]\]Y[Y[\ÈY[YšX[È[œ™YÚ\Ý°ê\ÈÝ\ˆÝ›Û™ÏžÚ[™\ØØ\J˜Z[™YWÛ˜[YJ_OÜÝ›Û™Ï‹Ü‚ˆÛ\ÜÏHš[“HÚ]H^[Y[Ô][\ÙH[™H[Ù[H˜]˜TØÜš\ˆÚHHÛÛ›™^[Ûˆ¸ &XX›Ý]]\ËÛ\]Y^ˆÝ\ˆ0ªÈ™[[˜Ù\ˆ0®ÈZ\È0ªÈÙHÛÛ›™XÝ\ˆ0®ÈÝ\ˆ]\ˆ™[°ê™KÜ‚‚ˆ]ÛˆÛ\ÜÏH˜ˆˆ\OH˜]ÛˆˆÛ˜ÛXÚÏHœ[]]ÓÙÚ[Š
H”™[[˜Ù\ˆHÛÛ›™^[Ûˆ]]ÏØ]Û‚ˆHÛ\ÜÏH˜ˆˆ™YHžÝ\™Ù]Ý\›Hˆ\™Ù]H—Ø›[šÈˆ™[H››ÛÜ[™\ˆ“Ý]œš\ˆ^[Y[ÔX[Y[[Y[ØO‚ˆÙ]‚‚ˆ›Ü›HYH˜]]ÓÙÚ[ˆˆY]ÙHœÜÝˆXÝ[ÛHžÝ\™Ù]Ý\›HˆÝ[OH™\Ü^N››Û™NÈ‚ˆ[œ]˜[YOH™[XZ[ˆ˜[YOHžÛÙÚ[—Ù\ØßH‚ˆ[œ]˜[YOH›ÙÚ[‘[XZ[ˆ˜[YOHžÛÙÚ[—Ù\ØßH‚ˆ[œ]˜[YOHXX×Ù[XZ[ˆ˜[YOHžÛÙÚ[—Ù\ØßH‚ˆ[œ]˜[YOH›ÙÚ[ˆˆ˜[YOHžÛÙÚ[—Ù\ØßH‚ˆ[œ]˜[YOH\Ù\›˜[YHˆ˜[YOHžÛÙÚ[—Ù\ØßH‚ˆ[œ]˜[YOHšY[YšX[ˆ˜[YOHžÛÙÚ[—Ù\ØßH‚‚ˆ[œ]˜[YOHœ\ÜÝÛÜ™ˆ\OHœ\ÜÝÛÜ™ˆ˜[YOHžÜ\ÜÝÛÜ™Ù\ØßH‚ˆ[œ]˜[YOH›ÙÚ[”\ÜÝÛÜ™ˆ\OHœ\ÜÝÛÜ™ˆ˜[YOHžÜ\ÜÝÛÜ™Ù\ØßH‚ˆ[œ]˜[YOHXX×Ü\ÜÝÛÜ™ˆ\OHœ\ÜÝÛÜ™ˆ˜[YOHžÜ\ÜÝÛÜ™Ù\ØßH‚ˆ[œ]˜[YOHœ\ÜÝÙˆ\OHœ\ÜÝÛÜ™ˆ˜[YOHžÜ\ÜÝÛÜ™Ù\ØßH‚ˆ[œ]˜[YOH›[ÝÙWÜ\ÜÙHˆ\OHœ\ÜÝÛÜ™ˆ˜[YOHžÜ\ÜÝÛÜ™Ù\ØßH‚‚ˆ[œ]˜[YOHšYYÙHˆ˜[YOHŒM‚ˆ[œ]˜[YOHœYÙZYˆ˜[YOHŒM‚ˆ[œ]˜[YOH—Ü™[Y[X™\—ÛYHˆ˜[YOHŒH‚ˆ[œ]˜[YOHœ™[Y[X™\ˆˆ˜[YOHŒH‚ˆÙ›Ü›O‚‚ˆØÜš\‚ˆ[˜Ý[Ûˆ[]]ÓÙÚ[Š
HÞÂˆÛÛœÝ›Ü›HHØÝ[Y[™Ù][[Y[žRY
	Ø]]ÓÙÚ[‰ÊNÂˆYˆ
Y›Ü›JHÞÂˆÚ[™ÝË›ØØ][Û‹š™YˆH	ÞÝ\™Ù]Ý\›IÎÂˆ™]\›ŽÂˆ_Bˆ›Ü›KœÝX›Z]

NÂˆ_B‚ˆÙ][Y[Ý]
[]]ÓÙÚ[‹LŒ
NÂˆÜØÜš\‚Ø›ÙO‚Ú[‚ˆˆˆ‚‚‚‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ÜÝ[[X\žHŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ý˜Z[™YWÜÝ[[X\žJÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆX›Ü

B‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆH™^

›Üˆ[ˆ˜Z[™Y\ÈYˆ™Ù]
šYŠHOH˜Z[™YWÚY
K›Û™JBˆYˆ›Ý‚ˆX›Ü

Bˆ\›ÙÙÙ\‹š[™›Êˆ”ÕSSPT–HÐQ˜Z[™YWÚYI\ÈÛÝ\˜ÙWÙš[OI\Èš[YI\Èš[YØ]I\È‹ˆ˜Z[™YWÚYˆUWÑ’SKˆ™Ù]
œš[YŠKˆ™Ù]
œš[YØ]ŠKˆ
B‚ˆ˜Z[š[™×Û˜[YHH
Ë™Ù]
›˜[YHŠHÜˆˆŠKœÝš\

HÜˆ›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠJBˆ˜Z[š[™×Ý\HHÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠBˆY˜][ÜšXÙHHY˜][Ý˜Z[š[™×ÜšXÙJ˜Z[š[™×Ý\JBˆÝ\Hœ—Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠJBˆ[™Hœ—Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÙ[™‹ˆŠJBˆ›Ü›X][Û—Ù]\ÈHˆ‘HÙÝ\H]HÙ[™HˆYˆÝ\[™[™[ÙH‘]\È0èÛÛ™š\›Y\ˆ‚‚ˆÙ\ÜÚ[Û—ÝšY]ÈHÂˆšYŽˆË™Ù]
šYŠKˆ›˜[YHŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë›˜[YH‹ˆŠKˆ˜Z[š[™×Ý\HŽˆ˜Z[š[™×Ý\Kˆ™]WÜÝ\ŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠKˆ™]WÙ[™ŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÙ[™‹ˆŠKˆB‚ˆ˜Z[š[™×Ý\WÚÙ^HH
˜Z[š[™×Ý\HÜˆˆŠKœÝš\

K\\Š
BˆÝ[[X\žWÝ˜Z[š[™×Ø˜YÙHHÈ›X™[Žˆ‘“Ô“PUSÓˆ‹˜ÛÛÜˆŽˆ™Ü˜^HŸBˆYˆ˜Z[š[™×Ý\WÚÙ^KœÝ\ÝÚ]
”ÔÒPTŠN‚ˆÝ[[X\žWÝ˜Z[š[™×Ø˜YÙHHÈ›X™[Žˆ˜Z[š[™×Ý\WÚÙ^K˜ÛÛÜˆŽˆœ™YŸBˆ[Yˆ•QHˆ[ˆ˜Z[š[™×Ý\WÚÙ^N‚ˆÝ[[X\žWÝ˜Z[š[™×Ø˜YÙHHÈ›X™[Žˆ•QH‹˜ÛÛÜˆŽˆ›Ü˜[™ÙHŸBˆ[Yˆ‘T’QÑPS•ˆ[ˆ˜Z[š[™×Ý\WÚÙ^N‚ˆÝ[[X\žWÝ˜Z[š[™×Ø˜YÙHHÈ›X™[Žˆ‘T’QÑPS•‹˜ÛÛÜˆŽˆ›Ü˜[™ÙHŸBˆ[YˆTÈˆ[ˆ˜Z[š[™×Ý\WÚÙ^N‚ˆÝ[[X\žWÝ˜Z[š[™×Ø˜YÙHHÈ›X™[ŽˆTÈ‹˜ÛÛÜˆŽˆ˜›YHŸBˆ[Yˆ••Èˆ[ˆ˜Z[š[™×Ý\WÚÙ^N‚ˆÝ[[X\žWÝ˜Z[š[™×Ø˜YÙHHÈ›X™[Žˆ••È‹˜ÛÛÜˆŽˆœ\œHŸBˆ[YˆLÔˆ[ˆ˜Z[š[™×Ý\WÚÙ^N‚ˆÝ[[X\žWÝ˜Z[š[™×Ø˜YÙHHÈ›X™[ŽˆLÔ‹˜ÛÛÜˆŽˆ™Ü™Y[ˆŸB‚ˆ™]\›ˆ™[™\—Ý[\]Jˆ˜YZ[—Ý˜Z[™YWÜÝ[[X\žKš[‹ˆÙ\ÜÚ[Û\Ù\ÜÚ[Û—ÝšY]Ëˆ˜Z[™YO]ˆ˜Z[š[™×Û˜[YO]˜Z[š[™×Û˜[YHÜˆ‘›Ü›X][Ûˆ‹ˆ›Ü›X][Û—Ù]\ÏY›Ü›X][Û—Ù]\Ëˆ\×ÝÏJ••Èˆ[ˆ
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠK\\Š
JKˆÝ[[X\žWÝ˜Z[š[™×Ø˜YÙO\Ý[[X\žWÝ˜Z[š[™×Ø˜YÙKˆÝ[[X\žWÝ˜Z[š[™×ÜšXÙO]™Ù]
˜Z[š[™×ÜšXÙHŠHÜˆY˜][ÜšXÙKˆ
B‚‚\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ÜÝ[[X\žKÜš[ŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ý˜Z[™YWÜÝ[[X\žWÜš[
Ù\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ˜Z[™YWÛ›ÝÙ›Ý[™ŸJK‚ˆH›Û™BˆYˆ\Ú[œÝ[˜ÙJË™Ù]
˜Z[™Y\ÈŠK\Ý
N‚ˆH™^

›Üˆ[ˆË™Ù]
˜Z[™Y\È‹×JHYˆÝŠ™Ù]
šYŠHÜˆˆŠHOHÝŠ˜Z[™YWÚY
JK›Û™JBˆYˆ›Ý[™\Ú[œÝ[˜ÙJË™Ù]
œÝYÚXZ\™\ÈŠK\Ý
N‚ˆH™^

›Üˆ[ˆË™Ù]
œÝYÚXZ\™\È‹×JHYˆÝŠ™Ù]
šYŠHÜˆˆŠHOHÝŠ˜Z[™YWÚY
JK›Û™JBˆYˆ›Ý‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ˜Z[™YWÛ›ÝÙ›Ý[™ŸJK‚ˆš[YÙ]HH]][YK››ÝÊ[Y^›Û™K]ÊKœÝ™[YJ‰VKI[KIYŠBˆÈœÝ[[X\žWÜš[YØ]—HHš[YÙ]BˆÈœš[Y—HHYBˆÈœš[YØ]—HHÛ›Ý×Ú\ÛÊ
BˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKœš[YØ]Žˆš[YÙ]_JB‚‚\œÜÝ
‹Ø\KÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ÛX\šË\š[YŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™Yˆ\WÛX\š×Ý˜Z[™YWÜš[Y
˜Z[™YWÚYˆÝŠN‚ˆžN‚ˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆš[YH^[ØY™Ù]
œš[Y‹YJBˆš[YHš[YYˆ\Ú[œÝ[˜ÙJš[Y›ÛÛ
H[ÙHÝŠš[Y
KœÝš\

K›ÝÙ\Š
H[ˆÈŒH‹YH‹žY\È‹›ÝZHŸBˆ\›ÙÙÙ\‹š[™›Ê“PT’È’S•QÕT•˜Z[™YWÚYI\Èš[YI\È‹˜Z[™YWÚYš[Y
B‚ˆ]HHØYÙ]J
Bˆ›Ý[™H˜[ÙBˆš[YØ]HÛ›Ý×Ú\ÛÊ
HYˆš[Y[ÙHˆ‚‚ˆ›ÜˆÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JN‚ˆYˆ\Ú[œÝ[˜ÙJË™Ù]
˜Z[™Y\ÈŠK\Ý
N‚ˆ›Üˆ[ˆÖÈ˜Z[™Y\È—N‚ˆYˆÝŠ™Ù]
šYŠJHOHÝŠ˜Z[™YWÚY
N‚ˆ\›ÙÙÙ\‹š[™›Ê‘“ÕS‘[ˆ˜Z[™Y\Ö×HŠBˆÈœš[Y—HHš[YˆÈœš[YØ]—HHš[YØ]ˆYˆ›Ýš[Y‚ˆÈœÝ[[X\žWÜš[YØ]—HHˆ‚ˆ›Ý[™HYB‚ˆYˆ\Ú[œÝ[˜ÙJË™Ù]
œÝYÚXZ\™\ÈŠK\Ý
N‚ˆ›Üˆ[ˆÖÈœÝYÚXZ\™\È—N‚ˆYˆÝŠ™Ù]
šYŠJHOHÝŠ˜Z[™YWÚY
N‚ˆ\›ÙÙÙ\‹š[™›Ê‘“ÕS‘[ˆÝYÚXZ\™\Ö×HŠBˆÈœš[Y—HHš[YˆÈœš[YØ]—HHš[YØ]ˆYˆ›Ýš[Y‚ˆÈœÝ[[X\žWÜš[YØ]—HHˆ‚ˆ›Ý[™HYB‚ˆYˆ›Ý›Ý[™‚ˆ\›ÙÙÙ\‹™\œ›ÜŠ•RS‘QH“Õ“ÕS‘	\È‹˜Z[™YWÚY
Bˆ™]\›ˆœÛÛšYžJÈœÝXØÙ\ÜÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››Ý›Ý[™ŸJK‚ˆØ]™WÙ]J]JBˆ\›ÙÙÙ\‹š[™›Ê”ÐU‘HÒÈ˜Z[™YWÚYI\Èš[YI\È‹˜Z[™YWÚYš[Y
B‚ˆ™]\›ˆœÛÛšYžJÈœÝXØÙ\ÜÈŽˆYKœš[YŽˆš[Yœš[YØ]Žˆš[YØ]JB‚ˆ^Ù\^Ù\[Ûˆ\ÈN‚ˆ[\Ü˜XÙX˜XÚÂˆ˜XÙX˜XÚËœš[Ù^Ê
Bˆ\›ÙÙÙ\‹™\œ›ÜŠ‘T”“ÔˆPT’È’S•Qˆ	\È‹ÝŠJJBˆ™]\›ˆœÛÛšYžJÈœÝXØÙ\ÜÈŽˆ˜[ÙK™\œ›ÜˆŽˆÝŠJ_JKL‚‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ÙšXÚKXYYˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ý˜Z[™YWØYY—ÜÚY]
Ù\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆX›Ü

B‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆH™^

›Üˆ[ˆ˜Z[™Y\ÈYˆ™Ù]
šYŠHOH˜Z[™YWÚY
K›Û™JBˆYˆ›Ý‚ˆX›Ü

B‚ˆ˜Z[š[™×Ý\HHÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠBˆYˆ›ÝÚ\×ØYY—Ý˜Z[š[™Ê˜Z[š[™×Ý\JN‚ˆX›Ü

B‚ˆYˆ
™Ù]
™ÜÜÚY\—ÜÝ]\ÈŠHÜˆˆŠKœÝš\

K›ÝÙ\Š
HOH˜ÛÛ\]HŽ‚ˆX›Ü

B‚ˆYˆXÚÊ
˜[Y\Îˆ[žJHOˆÝŽ‚ˆ›Üˆ˜[YH[ˆ˜[Y\Î‚ˆHÝŠ˜[YHÜˆˆŠKœÝš\

BˆYˆ‚ˆ™]\›ˆˆ™]\›ˆˆ‚‚ˆš\Ù]WÝ˜[YHHXÚÊ™Ù]
˜š\Ù]HŠJBˆš\ÞYX\ˆHˆ‚ˆš\Û[ÛHˆ‚ˆYˆš\Ù]WÝ˜[YN‚ˆžN‚ˆH]][YKœÝœ[YJš\Ù]WÝ˜[YK‰VKI[KIYŠBˆš\ÞYX\ˆHÝŠžYX\ŠBˆš\Û[ÛHˆžÙ›[ÛŒ™H‚ˆ^Ù\^Ù\[ÛŽ‚ˆ\ÜÂ‚ˆYY—Ù]HHÂˆœÛØÚX[ÜÙXÝ\š]WÛ[X™\ˆŽˆXÚÊ™Ù]
˜Ø\WÝš][HŠK™Ù]
œÛØÚX[ÜÙXÝ\š]WÛ[X™\ˆŠK™Ù]
œÜÛˆŠK™Ù]
›[WÜÙXÝHŠJKˆ›˜][Û˜[]WØš\ØÛÝ[žHŽˆˆH‹š›Ú[ŠÝˆ›Üˆˆ[ˆÜXÚÊ™Ù]
›˜][Û˜[]HŠJKXÚÊ™Ù]
˜š\ØÛÝ[žHŠJWHYˆ—JKˆœÙ^ŽˆXÚÊ™Ù]
œÙ^ŠK™Ù]
™Ù[™\ˆŠJKˆ˜š\ÞYX\ˆŽˆš\ÞYX\‹ˆ˜š\Û[ÛŽˆš\Û[Ûˆ˜Ú]š[]HŽˆXÚÊ™Ù]
˜Ú]š[]HŠK™Ù]
˜Ú]š[]HŠK™Ù]
]HŠJKˆ›\ÝÛ˜[YHŽˆXÚÊ™Ù]
›\ÝÛ˜[YHŠJKˆ™š\œÝÛ˜[YHŽˆXÚÊ™Ù]
™š\œÝÛ˜[YHŠJKˆ˜š\Ù]HŽˆœ—Ù]Jš\Ù]WÝ˜[YJHÜˆš\Ù]WÝ˜[YKˆ˜š\ØÚ]WØÛÝ[žHŽˆˆH‹š›Ú[ŠÝˆ›Üˆˆ[ˆÜXÚÊ™Ù]
˜š\ØÚ]HŠJKXÚÊ™Ù]
˜š\ØÛÝ[žHŠJWHYˆ—JKˆ›˜][Û˜[]HŽˆXÚÊ™Ù]
›˜][Û˜[]HŠJKˆ˜Y™\ÜÈŽˆXÚÊ™Ù]
˜Y™\ÜÈŠJKˆžš\ØÛÙHŽˆXÚÊ™Ù]
žš\ØÛÙHŠJKˆ˜Ú]HŽˆXÚÊ™Ù]
˜Ú]HŠJKˆœ™WÛÜ—ØØ\ˆŽˆXÚÊ™Ù]
œ™WÛ[X™\ˆŠJKˆB‚ˆ™]\›ˆ™[™\—Ý[\]Jˆ˜YZ[—Ý˜Z[™YWØYY—ÜÚY]š[‹ˆÙ\ÜÚ[Û\Ëˆ˜Z[™YO]ˆYYXYY—Ù]Kˆ
B‚‚™YˆØZ[ØØ[™Y]WÜÚY]Ù]JÙ\ÜÚ[Û—Ù]NˆXÝÜÝ‹[žWK˜Z[™YWÙ]NˆXÝÜÝ‹[žWJHOˆXÝÜÝ‹[žWN‚ˆÜÜÚY\ˆHÝ˜YWÙš[™Û]\ÝÙ›Ü—Ý˜Z[™YJÝŠ˜Z[™YWÙ]K™Ù]
šYŠHÜˆˆŠJBˆØ[™Y]H
ÜÜÚY\ˆÜˆßJK™Ù]
˜Ø[™Y]ŠHÜˆßB‚ˆYˆXÚÊ
˜[Y\Îˆ[žJHOˆÝŽ‚ˆ›Üˆ˜[YH[ˆ˜[Y\Î‚ˆHÝŠ˜[YHÜˆˆŠKœÝš\

BˆYˆ‚ˆ™]\›ˆˆ™]\›ˆˆ‚‚ˆYˆÛX[—ÜÛ™J˜[YNˆ[žJHOˆÝŽ‚ˆ˜]ÈH™KœÝXŠˆ—‹ˆ‹ÝŠ˜[YHÜˆˆŠJBˆYˆ[Š˜]ÊHOHL‚ˆ™]\›ˆˆ‹š›Ú[Š˜]ÖÚNšH
È—H›ÜˆH[ˆ˜[™ÙJ[Š˜]ÊKŠJBˆ™]\›ˆÝŠ˜[YHÜˆˆŠKœÝš\

B‚ˆ˜Z[š[™×Ý\HH
ÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—Ù]K˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠKœÝš\

K\\Š
BˆY˜][Ù›Ü›X][Û—Ý\HH‘“Ô“PUSÓˆS’UPSHˆYˆ˜Z[š[™×Ý\HOH‘T’QÑPS•S’UPSˆ[ÙH•˜[Y][Ûˆ\ÈXÜ]Z\ÈH	Ù^0ê\šY[˜ÙH
QJH‚‚ˆ^[ØYHÂˆ™›Ü›X][Û—Ý\HŽˆY˜][Ù›Ü›X][Û—Ý\Kˆ™]WÙ[™YWÜÝYÙHŽˆœ—Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—Ù]K™]WÜÝ\‹ˆŠJHÜˆˆ‹ˆœÚ]X][ÛˆŽˆXÚÊØ[™Y]™Ù]
œÝ]]ŠJKˆ˜ÛÛ\[žHŽˆXÚÊ˜Z[™YWÙ]K™Ù]
˜ÛÛ\[žWÛ˜[YHŠK˜Z[™YWÙ]K™Ù]
™[\ÞY\ˆŠK˜Z[™YWÙ]K™Ù]
™[™\š\ÙHŠJKˆ™š[˜[˜Ú[™ÈŽˆˆ‹ˆš[\šY]Ù\ˆŽˆÛ0ê[Y[RSS•‹ˆ›\ÝÛ˜[YHŽˆXÚÊ˜Z[™YWÙ]K™Ù]
›\ÝÛ˜[YHŠKØ[™Y]™Ù]
››ÛWÛ˜Z\ÜØ[˜ÙHŠJKˆ\ØYÙWÛ˜[YHŽˆXÚÊØ[™Y]™Ù]
››ÛWÝ\ØYÙHŠJKˆ™š\œÝÛ˜[Y\ÈŽˆXÚÊ˜Z[™YWÙ]K™Ù]
™š\œÝÛ˜[YHŠKØ[™Y]™Ù]
œ™[›Û\ÈŠJKˆ˜Y™\ÜÈŽˆXÚÊ˜Z[™YWÙ]K™Ù]
˜Y™\ÜÈŠKØ[™Y]™Ù]
˜Y™\ÜÙHŠJKˆœÜÝ[ØÛÙHŽˆXÚÊ˜Z[™YWÙ]K™Ù]
žš\ØÛÙHŠK˜Z[™YWÙ]K™Ù]
œÜÝ[ØÛÙHŠJKˆ˜Ú]HŽˆXÚÊ˜Z[™YWÙ]K™Ù]
˜Ú]HŠK˜Z[™YWÙ]K™Ù]
˜š\ØÚ]HŠJKˆœÛ™HŽˆÛX[—ÜÛ™JXÚÊ˜Z[™YWÙ]K™Ù]
œÛ™HŠKØ[™Y]™Ù]
[\Û™HŠJJKˆ™[XZ[ŽˆXÚÊ˜Z[™YWÙ]K™Ù]
™[XZ[ŠKØ[™Y]™Ù]
™[XZ[ŠJKˆ˜š\Ù]HŽˆœ—Ù]JXÚÊ˜Z[™YWÙ]K™Ù]
˜š\Ù]HŠKØ[™Y]™Ù]
™]WÛ˜Z\ÜØ[˜ÙHŠJJHÜˆXÚÊ˜Z[™YWÙ]K™Ù]
˜š\Ù]HŠKØ[™Y]™Ù]
™]WÛ˜Z\ÜØ[˜ÙHŠJKˆ˜š\ØÚ]HŽˆXÚÊ˜Z[™YWÙ]K™Ù]
˜š\ØÚ]HŠK˜Z[™YWÙ]K™Ù]
˜š\ÜXÙHŠJKˆ™\\Y[ŽˆXÚÊ˜Z[™YWÙ]K™Ù]
™\\Y[ŠJKˆ˜ÛÝ[žHŽˆXÚÊ˜Z[™YWÙ]K™Ù]
˜ÛÝ[žHŠK‘œ˜[˜ÙHŠKˆ›˜][Û˜[]HŽˆXÚÊ˜Z[™YWÙ]K™Ù]
›˜][Û˜[]HŠKØ[™Y]™Ù]
›˜][Û˜[]HŠJKˆ™[Y\™Ù[˜ÞWØÛÛXÝŽˆXÚÊ˜Z[™YWÙ]K™Ù]
™[Y\™Ù[˜ÞWØÛÛXÝŠK˜Z[™YWÙ]K™Ù]
™[Y\™Ù[˜ÞWÜÛ™HŠJKˆ˜Û˜\×Û[X™\ˆŽˆˆ‹ˆœÝYWÛ]™[ŽˆXÚÊØ[™Y]™Ù]
›š]™X]WÙ›Ü›X][ÛˆŠJKˆœÝYWÙÛXZ[ˆŽˆXÚÊ˜Z[™YWÙ]K™Ù]
œÝYWÙÛXZ[ˆŠJKˆ›\ÝØÙ\YšXØ][Û—Û]™[ŽˆXÚÊØ[™Y]™Ù]
›š]™X]WØÙ\YšXØ][ÛˆŠJKˆ›\ÝØÙ\YšXØ][Û—ÙÛXZ[ˆŽˆXÚÊ˜Z[™YWÙ]K™Ù]
›\ÝØÙ\YšXØ][Û—ÙÛXZ[ˆŠJKˆ›\ÝÚ›ØˆŽˆXÚÊ˜Z[™YWÙ]K™Ù]
›\ÝÚ›ØˆŠJKˆžYX\œ×Ù^\šY[˜ÙHŽˆXÚÊ˜Z[™YWÙ]K™Ù]
žYX\œ×Ù^\šY[˜ÙHŠJKˆ˜ÛÛ\[žWÛ˜[YHŽˆXÚÊ˜Z[™YWÙ]K™Ù]
˜ÛÛ\[žWÛ˜[YHŠK˜Z[™YWÙ]K™Ù]
™[\ÞY\ˆŠJKˆ™Ü›ÜÜ×ÜØ[\žHŽˆXÚÊ˜Z[™YWÙ]K™Ù]
™Ü›ÜÜ×ÜØ[\žHŠJKˆB‚ˆØ]™YÜÚY]H˜Z[™YWÙ]K™Ù]
˜Ø[™Y]WÜÚY]ŠBˆYˆ\Ú[œÝ[˜ÙJØ]™YÜÚY]XÝ
N‚ˆ›ÜˆÙ^H[ˆ^[ØYšÙ^\Ê
N‚ˆYˆÙ^H[ˆØ]™YÜÚY]‚ˆ^[ØYÚÙ^WHHÝŠØ]™YÜÚY]™Ù]
Ù^JHÜˆˆŠKœÝš\

B‚ˆ™]\›ˆ^[ØY‚‚\œÜÝ
‹Ù\ÜXÙKÏÚÙ[‹ÙšXÚKXØ[™Y]Ù[œ™YÚ\Ý™\ˆŠB™YˆX›X×Ý˜Z[™YWØØ[™Y]WÜÚY]ÜØ]™JÚÙ[ŽˆÝŠN‚ˆ]HHØYÙ]J
BˆËHš[™ÜÙ\ÜÚ[Û—Ø[™Ý˜Z[™YWØžWÝÚÙ[Š]KÚÙ[ŠBˆYˆ›ÝÈÜˆ›Ý‚ˆX›Ü

B‚ˆYˆ›ÝÜX›X×Ú\×Ø]]Y
ÚÙ[ŠN‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠœX›X×Ý˜Z[™YWÛÙÚ[ˆ‹ÚÙ[]ÚÙ[ŠJB‚ˆ˜Z[š[™×Ý\HH
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠKœÝš\

K\\Š
BˆYˆ›ÝÚ\×Ù\šYÙX[ØØ[™Y]WÜÚY]Ý˜Z[š[™Ê˜Z[š[™×Ý\JN‚ˆX›Ü

B‚ˆ˜\ÙWÜÚY]HØZ[ØØ[™Y]WÜÚY]Ù]JË
BˆØ]™YÜÚY]ˆXÝÜÝ‹Ý—HHßBˆ›ÜˆÙ^H[ˆ˜\ÙWÜÚY]šÙ^\Ê
N‚ˆØ]™YÜÚY]ÚÙ^WHHÝŠ™\]Y\Ý™›Ü›K™Ù]
Ù^KˆŠHÜˆˆŠKœÝš\

BˆÈ˜Ø[™Y]WÜÚY]—HHØ]™YÜÚY]ˆÈ˜Ø[™Y]WÜÚY]ÜØ]™YØ]—HHÛ›Ý×Ú\ÛÊ
B‚ˆ[œÝ\™WÙØÝ[Y[×ÜØÚ[XWÙ›Ü—Ý˜Z[™YJ˜Z[š[™×Ý\JB‚ˆÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
BˆÈ™ÜÜÚY\—ÜÝ]\È—HH˜ÛÛ\]HˆYˆÜÜÚY\—Ú\×ØÛÛ\]WÝÝ[
˜Z[š[™×Ý\KÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠJH[ÙHš[˜ÛÛ\]H‚‚ˆÖÈ˜Z[™Y\È—HHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JB‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠœX›X×Ý˜Z[™YWÜÜXÙH‹ÚÙ[]ÚÙ[ŠH
ÈˆÙØ×ØØ[™Y]WÚ[™›×ÜÚY]ŠB‚‚\™Ù]
‹Ù\ÜXÙKÏÚÙ[‹ÙšXÚKXØ[™Y]ŠB™YˆX›X×Ý˜Z[™YWØØ[™Y]WÜÚY]
ÚÙ[ŽˆÝŠN‚ˆ]HHØYÙ]J
BˆËHš[™ÜÙ\ÜÚ[Û—Ø[™Ý˜Z[™YWØžWÝÚÙ[Š]KÚÙ[ŠBˆYˆ›ÝÈÜˆ›Ý‚ˆX›Ü

B‚ˆYˆ›ÝÜX›X×Ú\×Ø]]Y
ÚÙ[ŠN‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠœX›X×Ý˜Z[™YWÛÙÚ[ˆ‹ÚÙ[]ÚÙ[ŠJB‚ˆ˜Z[š[™×Ý\HH
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠKœÝš\

K\\Š
BˆYˆ›ÝÚ\×Ù\šYÙX[ØØ[™Y]WÜÚY]Ý˜Z[š[™Ê˜Z[š[™×Ý\JN‚ˆX›Ü

B‚ˆÝ×Ý\›Hˆ‚ˆÝ×ÝÚÙ[ˆH
™Ù]
šY[]WÜÝÈŠHÜˆˆŠKœÝš\

BˆYˆÝ×ÝÚÙ[Ž‚ˆÝ×Ý\›H\›Ù›ÜŠœX›X×ÙÝÛ›ØYÙš[H‹ÚÙ[]ÚÙ[‹š[WÝÚÙ[\Ý×ÝÚÙ[ŠB‚ˆ™]\›ˆ™[™\—Ý[\]JˆœX›X×ØØ[™Y]WÜÚY]Ù›Ü›Kš[‹ˆØ[™Y]OWØZ[ØØ[™Y]WÜÚY]Ù]JË
KˆÝ×Ý\›\Ý×Ý\›ˆØ]™WÝ\›]\›Ù›ÜŠœX›X×Ý˜Z[™YWØØ[™Y]WÜÚY]ÜØ]™H‹ÚÙ[]ÚÙ[ŠKˆ
B‚‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ÙšXÚKXØ[™Y]XÛÛ\]YHŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ý˜Z[™YWØØ[™Y]WÜÚY]
Ù\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆX›Ü

B‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆH™^

›Üˆ[ˆ˜Z[™Y\ÈYˆ™Ù]
šYŠHOH˜Z[™YWÚY
K›Û™JBˆYˆ›Ý‚ˆX›Ü

B‚ˆ˜Z[š[™×Ý\HH
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠKœÝš\

K\\Š
BˆYˆ›ÝÚ\×Ù\šYÙX[ØØ[™Y]WÜÚY]Ý˜Z[š[™Ê˜Z[š[™×Ý\JN‚ˆX›Ü

B‚ˆÝ×Ý\›Hˆ‚ˆÝ×ÝÚÙ[ˆH
™Ù]
šY[]WÜÝÈŠHÜˆˆŠKœÝš\

BˆYˆÝ×ÝÚÙ[Ž‚ˆÝ×Ý\›H\›Ù›ÜŠ˜YZ[—ÝšY]×Ý\ØY‹]\Ý×ÝÚÙ[ŠB‚ˆØ[™Y]WÙ]HHØZ[ØØ[™Y]WÜÚY]Ù]JË
B‚ˆš\œÝÛ˜[YHHÝŠ™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

BˆYˆ›Ýš\œÝÛ˜[YN‚ˆš\œÝÛ˜[YHHÝŠ
Ø[™Y]WÙ]K™Ù]
™š\œÝÛ˜[Y\ÈŠHÜˆˆŠKœÝš\

KœÜ]
ˆŠVÌJBˆ\ÝÛ˜[YHHÝŠ™Ù]
›\ÝÛ˜[YHŠHÜˆˆŠKœÝš\

K\\Š
Bˆ—Ý]HH‘šXÚHØ[™Y]QHTÔ‚ˆYˆš\œÝÛ˜[YHÜˆ\ÝÛ˜[YN‚ˆ—Ý]HHˆžÜ—Ý]_HÙš\œÝÛ˜[Y_HÛ\ÝÛ˜[Y_H‹œÝš\

B‚ˆ™]\›ˆ™[™\—Ý[\]Jˆ˜YZ[—Ý˜Z[™YWØØ[™Y]WÜÚY]š[‹ˆØ[™Y]OXØ[™Y]WÙ]KˆÝ×Ý\›\Ý×Ý\›ˆ—Ý]O\—Ý]Kˆ
B‚‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ÙšXÚKXØ[™Y]ŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ý˜Z[™YWØØ[™Y]WÜÚY]ÙY]
Ù\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆX›Ü

B‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆH™^

›Üˆ[ˆ˜Z[™Y\ÈYˆ™Ù]
šYŠHOH˜Z[™YWÚY
K›Û™JBˆYˆ›Ý‚ˆX›Ü

B‚ˆ˜Z[š[™×Ý\HH
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠKœÝš\

K\\Š
BˆYˆ›ÝÚ\×Ù\šYÙX[ØØ[™Y]WÜÚY]Ý˜Z[š[™Ê˜Z[š[™×Ý\JN‚ˆX›Ü

B‚ˆÝ×Ý\›Hˆ‚ˆÝ×ÝÚÙ[ˆH
™Ù]
šY[]WÜÝÈŠHÜˆˆŠKœÝš\

BˆYˆÝ×ÝÚÙ[Ž‚ˆÝ×Ý\›H\›Ù›ÜŠ˜YZ[—ÝšY]×Ý\ØY‹]\Ý×ÝÚÙ[ŠB‚ˆ™]\›ˆ™[™\—Ý[\]JˆœX›X×ØØ[™Y]WÜÚY]Ù›Ü›Kš[‹ˆØ[™Y]OWØZ[ØØ[™Y]WÜÚY]Ù]JË
KˆÝ×Ý\›\Ý×Ý\›ˆØ]™WÝ\›]\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWØØ[™Y]WÜÚY]ÜØ]™H‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
KˆYZ[—Û[ÙOUYKˆ
B‚‚\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ÙšXÚKXØ[™Y]Ù[œ™YÚ\Ý™\ˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ý˜Z[™YWØØ[™Y]WÜÚY]ÜØ]™JÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆX›Ü

B‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆH™^

›Üˆ[ˆ˜Z[™Y\ÈYˆ™Ù]
šYŠHOH˜Z[™YWÚY
K›Û™JBˆYˆ›Ý‚ˆX›Ü

B‚ˆ˜Z[š[™×Ý\HH
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠKœÝš\

K\\Š
BˆYˆ›ÝÚ\×Ù\šYÙX[ØØ[™Y]WÜÚY]Ý˜Z[š[™Ê˜Z[š[™×Ý\JN‚ˆX›Ü

B‚ˆ˜\ÙWÜÚY]HØZ[ØØ[™Y]WÜÚY]Ù]JË
BˆØ]™YÜÚY]ˆXÝÜÝ‹Ý—HHßBˆ›ÜˆÙ^H[ˆ˜\ÙWÜÚY]šÙ^\Ê
N‚ˆØ]™YÜÚY]ÚÙ^WHHÝŠ™\]Y\Ý™›Ü›K™Ù]
Ù^KˆŠHÜˆˆŠKœÝš\

B‚ˆÈ˜Ø[™Y]WÜÚY]—HHØ]™YÜÚY]ˆÈ˜Ø[™Y]WÜÚY]ÜØ]™YØ]—HHÛ›Ý×Ú\ÛÊ
B‚ˆ[œÝ\™WÙØÝ[Y[×ÜØÚ[XWÙ›Ü—Ý˜Z[™YJ˜Z[š[™×Ý\JB‚ˆÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
BˆÈ™ÜÜÚY\—ÜÝ]\È—HH˜ÛÛ\]HˆYˆÜÜÚY\—Ú\×ØÛÛ\]WÝÝ[
˜Z[š[™×Ý\KÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠJH[ÙHš[˜ÛÛ\]H‚‚ˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JB‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
H
ÈˆÙØ×ØØ[™Y]WÚ[™›×ÜÚY]ŠB‚\™Ù]
‹Ø\KØÛÛ™[[Ûœ×ÜÚYÛ™YÝ[œÙY[ˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™Yˆ\WØÛÛ™[[Ûœ×ÜÚYÛ™YÝ[œÙY[Š
N‚ˆ][\ÈHÜÚYÛ™YØÛÛ™[[Ûœ×Ý[œÙY[—Ú][\ÊØYÙ]J
JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKš][\ÈŽˆ][\Ë˜ÛÝ[Žˆ[Š][\Ê_JB‚\™Ù]
‹Ø\KÙØÜ×Ý×ØÛÛ›ÛŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™Yˆ\WÙØÜ×Ý×ØÛÛ›Û

N‚ˆ]HHØYÙ]J
BˆÝ]H×B‚ˆ›ÜˆÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JN‚ˆYˆÚ\×ÝÙYÙ—ÛXY×ÜÙ\ÜÚ[ÛŠÊN‚ˆÛÛ[YBˆÙ\ÜÚ[Û—ÚYHË™Ù]
šYŠBˆÙ\ÜÚ[Û—Û˜[YHHÜÙ\ÜÚ[Û—ÙÙ]
Ë›˜[YH‹ˆŠBˆ˜Z[š[™×Ý\HHÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠB‚ˆ˜Z[™Y\ÈHÜ™YÚ\Ý\™YÝ˜Z[™Y\ÊÊB‚ˆ›Üˆ[ˆ˜Z[™Y\Î‚ˆÈÉØ\ÜÝ\™H]YH\ÈØÜÈ™\]Z\È^\Ý[
Ú[›Ûˆ\ÝHšYHOˆ\È0ê]XÝ0êJBˆ[œÝ\™WÙØÝ[Y[×ÜØÚ[XWÙ›Ü—Ý˜Z[™YJ˜Z[š[™×Ý\JB‚ˆØÜÈH™Ù]
™ØÝ[Y[ÈŠHÜˆ×Bˆ[™[™ÈHˆ›Üˆ[ˆØÜÎ‚ˆÝH
™Ù]
œÝ]\ÈŠHÜˆˆŠKœÝš\

K\\Š
BˆYˆÝ[ˆ
HÓÓ•°åTˆ‹HÓÓ•“ÓTˆŠN‚ˆ[™[™È
ÏHB‚ˆYˆ[™[™Èˆ‚ˆÝ]˜\[™
ÂˆœÙ\ÜÚ[Û—ÚYŽˆÙ\ÜÚ[Û—ÚYˆœÙ\ÜÚ[Û—Û˜[YHŽˆÙ\ÜÚ[Û—Û˜[YKˆ˜Z[š[™×Ý\HŽˆ˜Z[š[™×Ý\Kˆ˜Z[™YWÚYŽˆ™Ù]
šYŠKˆ›\ÝÛ˜[YHŽˆ™Ù]
›\ÝÛ˜[YH‹ˆŠKˆ™š\œÝÛ˜[YHŽˆ™Ù]
™š\œÝÛ˜[YH‹ˆŠKˆœ[™[™×ØÛÝ[Žˆ[™[™Ëˆ˜YZ[—Ý\›Žˆˆ‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÞÜÙ\ÜÚ[Û—ÚYKÜÝYÚXZ\™\ËÞÝ™Ù]
	ÚY	Ê_H‹ˆJB‚ˆÈšNˆ\È\™Ù[	ØX›Ü™
\ÈHØÜÈ0èÛÛ°í\ŠBˆÝ]œÛÜ
Ù^O[[X™Hˆ™Ù]
œ[™[™×ØÛÝ[‹
K™]™\œÙOUYJB‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKš][\ÈŽˆÝ]˜ÛÝ[Žˆ[ŠÝ]
_JB‚‚™œ›ÛH›\ÚÈ[\ÜXZÙWÜ™\ÜÛœÙB‚\œ›Ý]J‹ÙØÜ×Ý×ØÛÛ›ÛšœÛÛˆ‹Y]ÙÏVÈ‘ÑU‹“ÔSÓ”È—JB™YˆX›X×ÙØÜ×Ý×ØÛÛ›Û

N‚ˆÝ\YYÝÚÙ[ˆH
™\]Y\Ý˜\™ÜË™Ù]
ÚÙ[ˆŠHÜˆ™\]Y\ÝšXY\œË™Ù]
–QØÜËUËPÛÛ›ÛUÚÙ[ˆŠHÜˆˆŠKœÝš\

BˆX›X×ÝÚÙ[—ÛÚÈH›ÛÛ
ÐÔ×Õ×ÐÓÓ•“ÓÔP“P×ÕÒÑSˆ[™XXË˜ÛÛ\\™WÙYÙ\Ý
Ý\YYÝÚÙ[‹ÐÔ×Õ×ÐÓÓ•“ÓÔP“P×ÕÒÑSŠJBˆ\ÝYÝ\Ù\—ØYÙ[ÛÚÈH
ˆ›ÝÐÔ×Õ×ÐÓÓ•“ÓÔP“P×ÕÒÑS‚ˆ[™›ÛÛ
ÐÔ×Õ×ÐÓÓ•“ÓÕ•TÕQÕTÑT—ÐQÑS•
Bˆ[™XXË˜ÛÛ\\™WÙYÙ\Ý

™\]Y\ÝšXY\œË™Ù]
•\Ù\‹PYÙ[ŠHÜˆˆŠKœÝš\

KÐÔ×Õ×ÐÓÓ•“ÓÕ•TÕQÕTÑT—ÐQÑS•
Bˆ
BˆYˆ›ÝÙ\ÜÚ[Û‹™Ù]
˜YZ[—ÛÙÙÙYÚ[ˆŠH[™›ÝX›X×ÝÚÙ[—ÛÚÈ[™›Ý\ÝYÝ\Ù\—ØYÙ[ÛÚÎ‚ˆX›Ü
ÊB‚ˆYˆ™\]Y\Ý›Y]ÙOH“ÔSÓ”ÈŽ‚ˆ™\ÜHXZÙWÜ™\ÜÛœÙJˆ‹Œ
BˆYˆX›X×ÝÚÙ[—ÛÚÈÜˆ\ÝYÝ\Ù\—ØYÙ[ÛÚÎ‚ˆ™\ÜšXY\œÖÈXØÙ\ÜËPÛÛ›ÛP[ÝËSÜšYÚ[ˆ—HHŠˆ‚ˆ™\ÜšXY\œÖÈXØÙ\ÜËPÛÛ›ÛP[ÝËSY]ÙÈ—HH‘ÑUÔSÓ”È‚ˆ™\ÜšXY\œÖÈXØÙ\ÜËPÛÛ›ÛP[ÝËRXY\œÈ—HHÛÛ[U\KQØÜËUËPÛÛ›ÛUÚÙ[ˆ‚ˆ™]\›ˆ™\Ü‚ˆ]HHØYÙ]J
BˆÝ]H×B‚ˆ›ÜˆÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JN‚ˆYˆÚ\×ÝÙYÙ—ÛXY×ÜÙ\ÜÚ[ÛŠÊN‚ˆÛÛ[YBˆÙ\ÜÚ[Û—ÚYHË™Ù]
šYŠBˆÙ\ÜÚ[Û—Û˜[YHHÜÙ\ÜÚ[Û—ÙÙ]
Ë›˜[YH‹ˆŠBˆ˜Z[š[™×Ý\HHÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠB‚ˆ˜Z[™Y\ÈHÜ™YÚ\Ý\™YÝ˜Z[™Y\ÊÊB‚ˆ›Üˆ[ˆ˜Z[™Y\Î‚ˆ[œÝ\™WÙØÝ[Y[×ÜØÚ[XWÙ›Ü—Ý˜Z[™YJ˜Z[š[™×Ý\JB‚ˆØÜÈH™Ù]
™ØÝ[Y[ÈŠHÜˆ×Bˆ[™[™ÈHˆ›Üˆ[ˆØÜÎ‚ˆÝH
™Ù]
œÝ]\ÈŠHÜˆˆŠKœÝš\

K\\Š
BˆYˆÝ[ˆ
HÓÓ•°åTˆ‹HÓÓ•“ÓTˆŠN‚ˆ[™[™È
ÏHB‚ˆYˆ[™[™Èˆ‚ˆÝ]˜\[™
ÂˆœÙ\ÜÚ[Û—ÚYŽˆÙ\ÜÚ[Û—ÚYˆœÙ\ÜÚ[Û—Û˜[YHŽˆÙ\ÜÚ[Û—Û˜[YKˆ˜Z[š[™×Ý\HŽˆ˜Z[š[™×Ý\Kˆ˜Z[™YWÚYŽˆ™Ù]
šYŠKˆ›\ÝÛ˜[YHŽˆ™Ù]
›\ÝÛ˜[YH‹ˆŠKˆ™š\œÝÛ˜[YHŽˆ™Ù]
™š\œÝÛ˜[YH‹ˆŠKˆœ[™[™×ØÛÝ[Žˆ[™[™Ëˆ˜YZ[—Ý\›Žˆˆ‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÞÜÙ\ÜÚ[Û—ÚYKÜÝYÚXZ\™\ËÞÝ™Ù]
	ÚY	Ê_H‹ˆJB‚ˆÝ]œÛÜ
Ù^O[[X™Hˆ™Ù]
œ[™[™×ØÛÝ[‹
K™]™\œÙOUYJB‚ˆ™\ÜHXZÙWÜ™\ÜÛœÙJœÛÛšYžJÈ›ÚÈŽˆYKš][\ÈŽˆÝ]˜ÛÝ[Žˆ[ŠÝ]
_JJB‚ˆÈÓÔ”È[š\]Y[Y[ÜœÜ]YH	ØXØðêÈX›XÈ\Ý›ÛÛZ\™[Y[XÝ]°êK‚ˆYˆX›X×ÝÚÙ[—ÛÚÈÜˆ\ÝYÝ\Ù\—ØYÙ[ÛÚÎ‚ˆ™\ÜšXY\œÖÈXØÙ\ÜËPÛÛ›ÛP[ÝËSÜšYÚ[ˆ—HHŠˆ‚ˆ™\ÜšXY\œÖÈXØÙ\ÜËPÛÛ›ÛP[ÝËSY]ÙÈ—HH‘ÑUÔSÓ”È‚ˆ™\ÜšXY\œÖÈXØÙ\ÜËPÛÛ›ÛP[ÝËRXY\œÈ—HHÛÛ[U\KQØÜËUËPÛÛ›ÛUÚÙ[ˆ‚ˆ™]\›ˆ™\Ü‚ˆ™]\›ˆ™\Ü‚‚QRS—Ô‘PÑS•ÕRS‘QT×ÔÑTÔÒSÓ—ÒÑVHH˜YZ[—Ü™XÙ[Ý˜Z[™Y\È‚QRS—Ô‘PÑS•ÔÑTÔÒSÓ”×ÔÑTÔÒSÓ—ÒÑVHH˜YZ[—Ü™XÙ[ÜÙ\ÜÚ[ÛœÈ‚QRS—Ô‘PÑS•ÕÓÓ×ÔÑTÔÒSÓ—ÒÑVHH˜YZ[—Ü™XÙ[ÝÛÛÈ‚•RS‘QWÔÑPTÒÔ‘PÑS•ÓSRUH‚‚QRS—ÔÑPTÒÕÓÓÈHÂˆ˜YZ[—ÜÜÚ][Ûš[™×Ý\ÝÈŽˆ
•\ÝÈHÜÚ][Û›™[Y[‹ÛÛœÝ[\ˆ\È\ÝÈ‹¸§$ÈŠKˆ˜YZ[—ÝÙYÙ—Ü™\]Y\ÝÈŽˆ
Ôˆ0­ÈQÑˆ‹‘[X[™\ÈHš[˜[˜Ù[Y[‹¸ «ŠKˆ˜YZ[—ØÛ˜\×Ý˜XÚÚ[™ÈŽˆ
”ÝZ]šHÓTÈ‹”ÝZ]œ™H\ÈÜÜÚY\œÈÓTÈ‹¸¥áÈŠKˆ˜YZ[—ØÛ˜\×Ý[šÛ›ÝÛˆŽˆ
ÓTÈ[˜ÛÛ›\È‹‘ÜÜÚY\œÈ0è˜\›ØÚ\ˆ‹ÈŠKˆ˜YZ[—ÜÙ\ÜÚ[Ûœ×ØÛÛ™[[ÛœÈŽˆ
ÛÛ™[[ÛœÈ‹‘ðê\™\ˆ\ÈÛÛ™[[ÛœÈ‹¸¥©ŠKˆ˜YZ[—ÜÙ\ÜÚ[Ûœ×Ø]]ÛX][ÛœÈŽˆ
]]ÛX]\Ø][ÛœÈ‹ÛÛ™šYÝ\™\ˆ\È[›Ú\È‹¸¦¨HŠKˆ˜YZ[—ÜØ[\×Ý˜XÚÚ[™ÈŽˆ
”ÝZ]šH\È™[\È‹”[Ý\ˆ8 &XXÝ]š]0êHÛÛ[Y\˜ÚX[H‹¸¡¥ÈŠKˆ˜YZ[—Ú[YÜ˜[WÝØ]ÚŽˆ
\HØ]Ú‹Y™šXÚ\ˆ\ÈÔH]HÚYÛ™]‹¸£&ˆŠKˆ˜YZ[—ÜÙ\ÜÚ[Ûœ×Øš[[™ÈŽˆ
‘˜XÝ\˜][Ûˆ‹‘˜XÝ\™\È]°êÛ[Y[È‹¸ «ŠKˆ˜YZ[—Ù\™XÝÙXš]ÈŽˆ
”°ê[0ê™[Y[È‹‘ðê\™\ˆ\È°ê[0ê™[Y[È\™XÝÈ‹¸¡®ÈŠKˆ˜YZ[—Ü[Û×ÜÙ][™ÜÈŽˆ
”°êYÛYÙ\È[ÛÈ‹”\˜[pê™\ÈH˜XÝ\˜][Ûˆ‹¸¦¦HŠKˆ˜YZ[—ÜÙ\ÜÚ[Ûœ×Ø\˜Ú]™YŽˆ
”Ù\ÜÚ[ÛœÈ\˜Ú]°êY\È‹”™]›Ý]™\ˆ\È[˜ÚY[›™\ÈÙ\ÜÚ[ÛœÈ‹¸¥¨HŠKˆ˜YZ[—ØY˜ÈŽˆ
QÈ‹”ÝZ]šH\ÈØ[™Y]ÈQÈ‹HŠKˆ˜YZ[—ØØ\ÚÜ^[Y[ÈŽˆ
”ZY[Y[È\Ü0êÙ\È‹”ÝZ]šH\È[˜ØZ\ÜÙ[Y[È‹¸ «ŠKŸB‚‚™YˆÜ™[Y[X™\—ØYZ[—Ü™XÙ[
Ù^NˆÝ‹˜[YNˆÝŠHOˆ›Û™N‚ˆ™XÙ[HÜÝŠ][JH›Üˆ][H[ˆ
Ù\ÜÚ[Û‹™Ù]
Ù^JHÜˆ×JHYˆÝŠ][JHOHÝŠ˜[YJWBˆÙ\ÜÚ[Û–ÚÙ^WHHÜÝŠ˜[YJK
œ™XÙ[VÎ•RS‘QWÔÑPTÒÔ‘PÑS•ÓSRUBˆÙ\ÜÚ[Û‹›[ÙYšYYHYB‚‚\˜™Y›Ü™WÜ™\]Y\Ý™Yˆ™[Y[X™\—ØYZ[—ÜÙX\˜ÚØÛÛœÝ[][ÛœÊ
HOˆ›Û™N‚ˆˆˆ[[Y[H\ÈÝYÙÙ\Ý[ÛœÈ]™XÈ\ÈYÙ\È°êY[[Y[Ý]™\\È\ˆ	ØYZ[‹ˆˆˆ‚ˆYˆ™\]Y\Ý›Y]ÙOH‘ÑUˆÜˆ›ÝÙ\ÜÚ[Û‹™Ù]
˜YZ[—ÛÙÙÙYÚ[ˆŠN‚ˆ™]\›‚ˆYˆ™\]Y\Ý™[™Ú[OH˜YZ[—Ý˜Z[™Y\Èˆ[™™\]Y\ÝšY]×Ø\™ÜÈ[™™\]Y\ÝšY]×Ø\™ÜË™Ù]
œÙ\ÜÚ[Û—ÚYŠN‚ˆÜ™[Y[X™\—ØYZ[—Ü™XÙ[
QRS—Ô‘PÑS•ÔÑTÔÒSÓ”×ÔÑTÔÒSÓ—ÒÑVK™\]Y\ÝšY]×Ø\™ÜÖÈœÙ\ÜÚ[Û—ÚY—JBˆ[Yˆ™\]Y\Ý™[™Ú[[ˆQRS—ÔÑPTÒÕÓÓÎ‚ˆÜ™[Y[X™\—ØYZ[—Ü™XÙ[
QRS—Ô‘PÑS•ÕÓÓ×ÔÑTÔÒSÓ—ÒÑVK™\]Y\Ý™[™Ú[
B‚‚™YˆÜ™[Y[X™\—ØYZ[—Ý˜Z[™YWØÛÛœÝ[][ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠHOˆ›Û™N‚ˆˆˆÛÛœÙ\™H\È\›špê™\ÈšXÚ\ÈÝ]™\\ÈÝ\ˆ	ØYZ[š\Ý˜]]\ˆÛÝ\˜[ˆˆˆ‚ˆ][HHÈœÙ\ÜÚ[Û—ÚYŽˆÝŠÙ\ÜÚ[Û—ÚY
K˜Z[™YWÚYŽˆÝŠ˜Z[™YWÚY
_Bˆ™XÙ[HÙ\ÜÚ[Û‹™Ù]
QRS—Ô‘PÑS•ÕRS‘QT×ÔÑTÔÒSÓ—ÒÑVJHÜˆ×Bˆ™XÙ[HÂˆ[žH›Üˆ[žH[ˆ™XÙ[ˆYˆ\Ú[œÝ[˜ÙJ[žKXÝ
Bˆ[™
ˆÝŠ[žK™Ù]
œÙ\ÜÚ[Û—ÚYŠJHOH][VÈœÙ\ÜÚ[Û—ÚY—BˆÜˆÝŠ[žK™Ù]
˜Z[™YWÚYŠJHOH][VÈ˜Z[™YWÚY—Bˆ
BˆBˆÙ\ÜÚ[Û–ÐQRS—Ô‘PÑS•ÕRS‘QT×ÔÑTÔÒSÓ—ÒÑVWHHÚ][K
œ™XÙ[VÎ•RS‘QWÔÑPTÒÔ‘PÑS•ÓSRUBˆÙ\ÜÚ[Û‹›[ÙYšYYHYB‚‚™YˆÚ\×Ý˜YWÝ˜Z[š[™×Ý\J˜[YNˆÝŠHOˆ›ÛÛ‚ˆ™]\›ˆ•QHˆ[ˆ
˜[YHÜˆˆŠKœÝš\

K\\Š
B‚‚™YˆÝ˜Z[™YWÜÙX\˜ÚÚ][JÎˆXÝˆXÝ
HOˆXÝ‚ˆÙ\ÜÚ[Û—ÚYHË™Ù]
šYŠBˆ˜Z[™YWÚYH™Ù]
šYŠBˆ™]\›ˆÂˆœÙ\ÜÚ[Û—ÚYŽˆÙ\ÜÚ[Û—ÚYˆœÙ\ÜÚ[Û—Û˜[YHŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë›˜[YH‹ˆŠKˆ˜Z[š[™×Ý\HŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠKˆ˜Z[™YWÚYŽˆ˜Z[™YWÚYˆ™š\œÝÛ˜[YHŽˆ
™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

Kˆ›\ÝÛ˜[YHŽˆ
™Ù]
›\ÝÛ˜[YHŠHÜˆˆŠKœÝš\

Kˆ˜Ü™X]YØ]Žˆ™Ù]
˜Ü™X]YØ]ŠHÜˆˆ‹ˆœ™YÚ\Ý˜][Û—ØØ[˜Ù[YŽˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

Kˆ˜ÛÛ™[[Û—ÜÝ]\ÈŽˆ™Ù]
˜ÛÛ™[[Û—ÜÝ]\ÈŠHÜˆœÛÛÛˆ‹ˆ˜ÛÛ™[[Û—ÜØZ\ÚYWÙÛ™HŽˆ›ÛÛ
™Ù]
˜ÛÛ™[[Û—ÜØZ\ÚYWÙÛ™HŠJKˆ˜ÛÛ™[[Û—ÜÚYÛ™YÙÛ™HŽˆ›ÛÛ
™Ù]
˜ÛÛ™[[Û—ÜÚYÛ™YÙÛ™HŠJKˆ\ÝÙœ—ÜÝ]\ÈŽˆ™Ù]
\ÝÙœ—ÜÝ]\ÈŠHÜˆœÛÛÛˆ‹ˆ˜YZ[—Ý\›Žˆˆ‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÞÜÙ\ÜÚ[Û—ÚYKÜÝYÚXZ\™\ËÞÝ˜Z[™YWÚYH‹ˆœÝ[[X\žWØ\WÝ\›Žˆˆ‹Ø\KØYZ[‹ÜÙ\ÜÚ[ÛœËÞÜÙ\ÜÚ[Û—ÚYKÝ˜Z[™Y\ËÞÝ˜Z[™YWÚYKÜÝ[[X\žH‹ˆœX›X×ÝÚÙ[ˆŽˆ
™Ù]
œX›X×ÝÚÙ[ˆŠHÜˆˆŠKœÝš\

KˆœX›X×Ý\›ŽˆˆžÔP“P×ÔÕQS•ÔÔ•SÐTÑKœœÝš\
	ËÉÊ_KÙ\ÜXÙKÞÊ™Ù]
	ÜX›X×ÝÚÙ[‰ÊHÜˆ	ÉÊKœÝš\

_H‹ˆB‚‚—ÔURPÒ×ÔÕSSPT–WÑ”‘SÒÓSÓ•ÈH
ˆ‹š˜[šY\ˆ‹™°ê]œšY\ˆ‹›X\œÈ‹˜]œš[‹›XZH‹šZ[ˆ‹šZ[]‹˜[ðîÝ‹œÙ\[Xœ™H‹›ØÝØœ™H‹››Ý™[Xœ™H‹™0êXÙ[Xœ™HŠB‚‚™YˆÜ]ZXÚ×ÜÝ[[X\žWÙ]J˜[YNˆ[žJHOˆÝŽ‚ˆ\œÙYHÜ\œÙWÚ\Û×Ù]JÝŠ˜[YHÜˆˆŠKœÝš\

JBˆYˆ›Ý\œÙY‚ˆ™]\›ˆˆ‚ˆ™]\›ˆˆžÜ\œÙY™^_^ÉÙ\‰ÈYˆ\œÙY™^HOHH[ÙH	ÉßH×ÔURPÒ×ÔÕSSPT–WÑ”‘SÒÓSÓ•ÖÜ\œÙY›[Û_HÜ\œÙYžYX\ŸH‚‚‚™YˆÜ]ZXÚ×ÜÝ[[X\žWÜ\š[Ù
Ý\Ý˜[YNˆ[žK[™Ý˜[YNˆ[žJHOˆÝŽ‚ˆÝ\HÜ\œÙWÚ\Û×Ù]JÝŠÝ\Ý˜[YHÜˆˆŠKœÝš\

JBˆ[™HÜ\œÙWÚ\Û×Ù]JÝŠ[™Ý˜[YHÜˆˆŠKœÝš\

JBˆYˆ›ÝÝ\[™›Ý[™‚ˆ™]\›ˆˆ‚ˆYˆ›ÝÝ\‚ˆ™]\›ˆˆš\Ü]x &X]H×Ü]ZXÚ×ÜÝ[[X\žWÙ]J[™Ý˜[YJ_H‚ˆYˆ›Ý[™‚ˆ™]\›ˆˆ°è\\ˆH×Ü]ZXÚ×ÜÝ[[X\žWÙ]JÝ\Ý˜[YJ_H‚ˆYˆÝ\OH[™‚ˆ™]\›ˆˆ›H×Ü]ZXÚ×ÜÝ[[X\žWÙ]JÝ\Ý˜[YJ_H‚ˆYˆÝ\žYX\ˆOH[™žYX\ˆ[™Ý\›[ÛOH[™›[Û‚ˆš\œÝHˆžÜÝ\™^_^ÉÙ\‰ÈYˆÝ\™^HOHH[ÙH	ÉßH‚ˆ[YˆÝ\žYX\ˆOH[™žYX\Ž‚ˆš\œÝHˆžÜÝ\™^_^ÉÙ\‰ÈYˆÝ\™^HOHH[ÙH	ÉßH×ÔURPÒ×ÔÕSSPT–WÑ”‘SÒÓSÓ•ÖÜÝ\›[Û_H‚ˆ[ÙN‚ˆš\œÝHÜ]ZXÚ×ÜÝ[[X\žWÙ]JÝ\Ý˜[YJBˆ™]\›ˆˆ™HÙš\œÝH]H×Ü]ZXÚ×ÜÝ[[X\žWÙ]J[™Ý˜[YJ_H‚‚‚™YˆÜ]ZXÚ×ÜÝ[[X\žWÜØÚY[JÙ\ÜÚ[Û—ÛØšŽˆXÝ
HOˆXÝ‚ˆˆˆ‘^ÜÙHÛ›H]\È™XYœ›ÛHHÙ\ÜÚ[Ûˆ\ÜÛØÚX]YÚ]H˜Z[™YKˆˆˆ‚ˆ˜Z[š[™×Ý\HHÝŠÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠKœÝš\

K\\Š
Bˆ™Yš^H™\šYÙX[ˆYˆ˜Z[š[™×Ý\KœÝ\ÝÚ]
‘T’QÑPS•ŠH[ÙH˜\È‚ˆ™[[ÝWÜÝ\HÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹ˆžÜ™Yš^WÜ™[[ÝWÜÝ\‹ˆŠBˆ™[[ÝWÙ[™HÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹ˆžÜ™Yš^WÜ™[[ÝWÙ[™‹ˆŠBˆ™\Ù[ÜÝ\HÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹ˆžÜ™Yš^WÚ[—Ü\œÛÛ—ÜÝ\‹ˆŠBˆ™\Ù[Ù[™HÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹ˆžÜ™Yš^WÚ[—Ü\œÛÛ—Ù[™‹ˆŠBˆXœšYH›ÛÛ
™[[ÝWÜÝ\Üˆ™[[ÝWÙ[™Üˆ™\Ù[ÜÝ\Üˆ™\Ù[Ù[™
Bˆ™]\›ˆÂˆšXœšYŽˆXœšYˆ™›Ü›X][ÛˆŽˆÜ]ZXÚ×ÜÝ[[X\žWÜ\š[Ù
ÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹™]WÜÝ\‹ˆŠKÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹™]WÙ[™‹ˆŠJKˆœ™[[ÝHŽˆÜ]ZXÚ×ÜÝ[[X\žWÜ\š[Ù
™[[ÝWÜÝ\™[[ÝWÙ[™
HYˆXœšY[ÙHˆ‹ˆš[—Ü\œÛÛˆŽˆÜ]ZXÚ×ÜÝ[[X\žWÜ\š[Ù
™\Ù[ÜÝ\™\Ù[Ù[™
HYˆXœšY[ÙHˆ‹ˆ™^[HŽˆÜ]ZXÚ×ÜÝ[[X\žWÙ]JÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹™^[WÙ]H‹ˆŠJKˆB‚‚™YˆÝ˜Z[™YWÜ]ZXÚ×ÜÝ[[X\žJ]NˆXÝÙ\ÜÚ[Û—ÛØšŽˆXÝ˜Z[™YNˆXÝ
HOˆXÝ‚ˆˆˆZ[HÛÛ˜Ú\ÙK™XY[Û›HÝ]\È^[ØY\ÙYžHÛØ˜[ÙX\˜Úˆˆˆ‚ˆÙ\ÜÚ[Û—ÚYHÝŠÙ\ÜÚ[Û—ÛØš‹™Ù]
šYŠHÜˆˆŠBˆ˜Z[™YWÚYHÝŠ˜Z[™YK™Ù]
šYŠHÜˆˆŠBˆ˜Z[š[™×Ý\HHÝŠÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠKœÝš\

Bˆ˜Z[š[™×Ý\\ˆH˜Z[š[™×Ý\K\\Š
Bˆ]]ÛX][ÛˆHØZ[Ý˜Z[™YWØ]]ÛX][Û—ÜÝ]\ÊÙ\ÜÚ[Û—ÛØš‹˜Z[™YKÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆÛÛ™[[ÛˆH]]ÛX][Û‹™Ù]
˜ÛÛ™[[ÛˆŠHÜˆßBˆÛÛ›ØØ][ÛˆH]]ÛX][Û‹™Ù]
˜ÛÛ›ØØ][ÛˆŠHÜˆßB‚ˆš[[™×Û[™\ÈHØš[[™×Û[™\×Ù›Ü—Ý˜Z[™YWÜÙ\ÜÚ[ÛŠ]K˜Z[™YWÚYÙ\ÜÚ[Û—ÚY
Bˆ^XX›WÛ[™\ÈHÛ[™H›Üˆ[™H[ˆš[[™×Û[™\ÈYˆ[™K™Ù]
œ^[Y[Ý]\ÈŠHOH››ÝØ\XØX›H—BˆZYÛ[™\ÈHÛ[™H›Üˆ[™H[ˆ^XX›WÛ[™\ÈYˆ[™K™Ù]
œ^[Y[Ý]\ÈŠHOHœZY—BˆYˆ^XX›WÛ[™\È[™[ŠZYÛ[™\ÊHOH[Š^XX›WÛ[™\ÊN‚ˆ^[Y[ÜÝ]K^[Y[ÛX™[H˜ÛÛ\]H‹•Ý]\Ý^pêH‚ˆ[YˆZYÛ[™\Î‚ˆ^[Y[ÜÝ]K^[Y[ÛX™[Hœ[™[™È‹ˆ”ZY[Y[\Y[0­ÈÛ[ŠZYÛ[™\Ê_KÞÛ[Š^XX›WÛ[™\Ê_H°êYÛ0êJÊH‚ˆ[Yˆ^XX›WÛ[™\Î‚ˆ^[Y[ÜÝ]K^[Y[ÛX™[Hœ[™[™È‹”ZY[Y[[ˆ][H‚ˆ[ÙN‚ˆ^[Y[ÜÝ]K^[Y[ÛX™[H›™]]˜[‹]XÝ[™H˜XÝ\™H0è°êYÛ\ˆ‚‚ˆÛ˜\×Ü™[]˜[H˜Z[š[™×Ý\\‹œÝ\ÝÚ]

TÈ‹LÔŠJBˆÛ˜\×ÛÚÈHØÛ˜\×Ú\×ØXØÙ\Y
˜Z[™YK™Ù]
˜Û˜\ÈŠJBˆ\ÝÙœ—Ü™[]˜[H˜Z[š[™×Ý\\‹œÝ\ÝÚ]

TÈ‹LÔŠJBˆÜÜÚY\—ÛÚÈHÜÜÚY\—Ú\×ØÛÛ\]WÝÝ[
˜Z[™YK˜Z[š[™×Ý\KÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹™]WÜÝ\‹ˆŠJB‚ˆYˆÝ]\ÊÙ^NˆÝ‹X™[ˆÝ‹Ý]NˆÝ‹]Z[ˆÝˆHˆŠHOˆXÝ‚ˆ™]\›ˆÈšÙ^HŽˆÙ^K›X™[ŽˆX™[œÝ]HŽˆÝ]K™]Z[Žˆ]Z[B‚ˆÛÛ™[[Û—ÜÝ]HHÝŠÛÛ™[[Û‹™Ù]
œÝ]\ÈŠHÜˆˆŠKœÝš\

K›ÝÙ\Š
BˆYˆÛÛ™[[Û—ÜÝ]HOHœÚYÛ™YŽ‚ˆÛÛ™[[Û—ØØ\™ÜÝ]KÛÛ™[[Û—Ù]Z[H˜ÛÛ\]H‹”ÚYÛ°êYH‚ˆ[YˆÛÛ™[[Û—ÜÝ]H[ˆÈœÙ[‹ØZ][™×ÜÚYÛ˜]\™HŸN‚ˆÛÛ™[[Û—ØØ\™ÜÝ]KÛÛ™[[Û—Ù]Z[H˜ÛÛ\]H‹‘[›ÞpêYH‚ˆ[YˆÛÛ™[[Û—ÜÝ]H[ˆÈ™\œ›Üˆ‹œ™Y\ÙY‹™^\™YŸN‚ˆÛÛ™[[Û—ØØ\™ÜÝ]KÛÛ™[[Û—Ù]Z[H™\œ›Üˆ‹‘\œ™]\ˆ‚ˆ[ÙN‚ˆÛÛ™[[Û—ØØ\™ÜÝ]KÛÛ™[[Û—Ù]Z[Hœ[™[™È‹“›Ûˆ[›ÞpêYH‚ˆÝ]\Ù\ÈHÂˆÝ]\Ê˜ÛÛ™[[Ûˆ‹ÛÛ™[[Ûˆ‹ÛÛ™[[Û—ØØ\™ÜÝ]KÛÛ™[[Û—Ù]Z[
KˆÝ]\Ê˜ÛÛ›ØØ][Ûˆ‹ÛÛ›ØØ][Ûˆ‹˜ÛÛ\]HˆYˆÛÛ›ØØ][Û‹™Ù]
œÝ]\ÈŠHOHœÙ[ˆ[ÙHœ[™[™È‹ÛÛ›ØØ][Û‹™Ù]
›X™[ŠHÜˆ°à[›ÞY\ˆŠKˆÝ]\Ê™š[˜[˜Ú[™È‹‘š[˜[˜Ù[Y[˜[Y0êH‹˜ÛÛ\]HˆYˆ˜Z[™YK™Ù]
™š[˜[˜Ù[Y[ÜÝ]\ÈŠHOH˜[Y]Yˆ[ÙHœ[™[™È‹•˜[Y0êHˆYˆ˜Z[™YK™Ù]
™š[˜[˜Ù[Y[ÜÝ]\ÈŠHOH˜[Y]Yˆ[ÙH°àÛÛ°í\ˆŠKˆÝ]\Êœ^[Y[‹”ZY[Y[‹^[Y[ÜÝ]K^[Y[ÛX™[
KˆÝ]\Ê˜Û˜\È‹ÓTÈ‹˜ÛÛ\]HˆYˆÛ˜\×ÛÚÈ[ÙHœ[™[™È‹ÝŠ˜Z[™YK™Ù]
˜Û˜\ÈŠHÜˆ°àÛÛ°í\ˆŠJHYˆÛ˜\×Ü™[]˜[[ÙHÝ]\Ê˜Û˜\È‹ÓTÈ‹›™]]˜[‹“›ÛˆÛÛ˜Ù\›°êHŠKˆÝ]\Ê\ÝÙœˆ‹•\ÝHœ˜[°éØZ\È‹˜ÛÛ\]HˆYˆ˜Z[™YK™Ù]
\ÝÙœ—ÜÝ]\ÈŠHOH˜[Y]Yˆ[ÙHœ[™[™È‹•˜[Y0êHˆYˆ˜Z[™YK™Ù]
\ÝÙœ—ÜÝ]\ÈŠHOH˜[Y]Yˆ[ÙH°à˜[Y\ˆŠHYˆ\ÝÙœ—Ü™[]˜[[ÙHÝ]\Ê\ÝÙœˆ‹•\ÝHœ˜[°éØZ\È‹›™]]˜[‹“›ÛˆÛÛ˜Ù\›°êHŠKˆÝ]\Ê™ØÝ[Y[È‹‘ØÝ[Y[È‹˜ÛÛ\]HˆYˆÜÜÚY\—ÛÚÈ[ÙHœ[™[™È‹‘ÜÜÚY\ˆÛÛ\]ˆYˆÜÜÚY\—ÛÚÈ[ÙH‘ÜÜÚY\ˆ[˜ÛÛ\]ŠKˆBˆ™[]˜[HÚ][H›Üˆ][H[ˆÝ]\Ù\ÈYˆ][VÈœÝ]H—HOH›™]]˜[—BˆÛÛ\]YHÝ[J][VÈœÝ]H—HOH˜ÛÛ\]Hˆ›Üˆ][H[ˆ™[]˜[
Bˆ™]\›ˆÂˆ›ÚÈŽˆYKˆ˜Z[™YHŽˆÈ™š\œÝÛ˜[YHŽˆ˜Z[™YK™Ù]
™š\œÝÛ˜[YHŠHÜˆˆ‹›\ÝÛ˜[YHŽˆ˜Z[™YK™Ù]
›\ÝÛ˜[YHŠHÜˆˆ‹œÙ\ÜÚ[Û—Û˜[YHŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹›˜[YH‹ˆŠK˜Z[š[™×Ý\HŽˆ˜Z[š[™×Ý\_KˆœØÚY[HŽˆÜ]ZXÚ×ÜÝ[[X\žWÜØÚY[JÙ\ÜÚ[Û—ÛØšŠKˆœ›ÙÜ™\ÜÈŽˆÈ˜ÛÛ\]YŽˆÛÛ\]YÝ[Žˆ[Š™[]˜[
Kœ\˜Ù[Žˆ›Ý[™

ÛÛ\]YÈ[Š™[]˜[
JH
ˆL
HYˆ™[]˜[[ÙHLKˆœÝ]\Ù\ÈŽˆÝ]\Ù\Ëˆ˜YZ[—Ý\›Žˆˆ‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÞÜÙ\ÜÚ[Û—ÚYKÜÝYÚXZ\™\ËÞÝ˜Z[™YWÚYH‹ˆœX›X×Ý\›ŽˆˆžÔP“P×ÔÕQS•ÔÔ•SÐTÑKœœÝš\
	ËÉÊ_KÙ\ÜXÙKÞÊ˜Z[™YK™Ù]
	ÜX›X×ÝÚÙ[‰ÊHÜˆ	ÉÊKœÝš\

_H‹ˆB‚‚‚™YˆÜÙ\ÜÚ[Û—ÜÙX\˜ÚÚ][JÎˆXÝ
HOˆXÝ‚ˆÙ\ÜÚ[Û—ÚYHË™Ù]
šYŠBˆ]WÜÝ\HÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠBˆ]WÙ[™HÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÙ[™‹ˆŠBˆ]WÜ˜[™ÙHHˆ8¡¤ˆ‹š›Ú[Š\›Üˆ\[ˆÙœ—Ù]J]WÜÝ\
Kœ—Ù]J]WÙ[™
WHYˆ\[™\OH¸ %ŠBˆ™]\›ˆÂˆœÙ\ÜÚ[Û—ÚYŽˆÙ\ÜÚ[Û—ÚYˆœÙ\ÜÚ[Û—Û˜[YHŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë›˜[YH‹ˆŠKˆ˜Z[š[™×Ý\HŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠKˆ™]WÜÝ\Žˆ]WÜÝ\ˆ™]WÙ[™Žˆ]WÙ[™ˆ™]WÜ˜[™ÙHŽˆ]WÜ˜[™ÙKˆ™^[WÙ]HŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë™^[WÙ]H‹ˆŠKˆÝ[Žˆ[ŠÜ™YÚ\Ý\™YÝ˜Z[™Y\ÊÊJKˆ˜\˜Ú]™YŽˆ›ÛÛ
Ë™Ù]
˜\˜Ú]™YŠJKˆ˜YZ[—Ý\›Žˆˆ‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÞÜÙ\ÜÚ[Û—ÚYKÝ˜Z[™Y\È‹ˆB‚‚\™Ù]
‹Ø\KÜÙ\ÜÚ[Ûœ×ÜÙX\˜ÚŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™Yˆ\WÜÙ\ÜÚ[Ûœ×ÜÙX\˜Ú

N‚ˆHH
™\]Y\Ý˜\™ÜË™Ù]
œHŠHÜˆˆŠKœÝš\

K›ÝÙ\Š
Bˆ]HHØYÙ]J
Bˆš\ÚX›WÜ\™\—ÚYHØÝ\œ™[Ü\™\—ÚY

HÜˆS•QÔSWÔT•‘T—ÒQˆ[Ú][\ÈH×B‚ˆ›ÜˆÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JN‚ˆYˆ›Ý\Ú[œÝ[˜ÙJËXÝ
N‚ˆÛÛ[YBˆYˆË™Ù]
œ\™\—ÚYŠHOHš\ÚX›WÜ\™\—ÚY‚ˆÛÛ[YBˆYˆÚ\×ÝÙYÙ—ÛXY×ÜÙ\ÜÚ[ÛŠÊN‚ˆÛÛ[YBˆ[Ú][\Ë˜\[™
ÜÙ\ÜÚ[Û—ÜÙX\˜ÚÚ][JÊJB‚ˆYˆ[ŠJHŽ‚ˆ][\ÈHÛÜY
ˆ[Ú][\ËˆÙ^O[[X™H][Nˆ
ÝŠ][K™Ù]
™]WÜÝ\ŠHÜˆˆŠKÝŠ][K™Ù]
œÙ\ÜÚ[Û—Û˜[YHŠHÜˆˆŠJKˆ™]™\œÙOUYKˆ
VÎŒLBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKš][\ÈŽˆ][\Ë˜ÛÝ[Žˆ[Š][\Ê_JB‚ˆÝ]H×Bˆ›Üˆ][H[ˆ[Ú][\Î‚ˆ^\ÝXÚÈHˆ‹š›Ú[ŠÝŠ][K™Ù]
Ù^JHÜˆˆŠH›ÜˆÙ^H[ˆ
ˆœÙ\ÜÚ[Û—Û˜[YH‹˜Z[š[™×Ý\H‹™]WÜÝ\‹™]WÙ[™‹™]WÜ˜[™ÙH‹™^[WÙ]H‚ˆ
JK›ÝÙ\Š
BˆYˆH[ˆ^\ÝXÚÎ‚ˆÝ]˜\[™
][JB‚ˆÝ]œÛÜ
Ù^O[[X™H][Nˆ
›ÛÛ
][K™Ù]
˜\˜Ú]™YŠJKÝŠ][K™Ù]
™]WÜÝ\ŠHÜˆˆŠJK™]™\œÙOQ˜[ÙJBˆÝ]HÝ]ÎŒÌBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKš][\ÈŽˆÝ]˜ÛÝ[Žˆ[ŠÝ]
_JB‚‚\™Ù]
‹Ø\KØYZ[‹ÜÙX\˜ÚÜÝYÙÙ\Ý[ÛœÈŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™Yˆ\WØYZ[—ÜÙX\˜ÚÜÝYÙÙ\Ý[ÛœÊ
N‚ˆˆˆ”™]Ý\›™H\È]X]™HÜ›Ý\\ÈY™šXÚ0ê\È0è	ÛÝ]™\\™HHH™XÚ\˜ÚHÛØ˜[Kˆˆˆ‚ˆ]HHØYÙ]J
Bˆš\ÚX›WÜ\™\—ÚYHØÝ\œ™[Ü\™\—ÚY

HÜˆS•QÔSWÔT•‘T—ÒQˆÙ\ÜÚ[Ûœ×ØžWÚYHÂˆÝŠ][K™Ù]
šYŠJNˆ][H›Üˆ][H[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JBˆYˆ\Ú[œÝ[˜ÙJ][KXÝ
Bˆ[™
][K™Ù]
œ\™\—ÚYŠHÜˆS•QÔSWÔT•‘T—ÒQ
HOHš\ÚX›WÜ\™\—ÚYˆ[™›ÝÚ\×ÝÙYÙ—ÛXY×ÜÙ\ÜÚ[ÛŠ][JBˆBˆ˜Z[™YWÚ][\ÈH×Bˆ˜Z[™Y\×ØžWÚÙ^HHßBˆ›ÜˆÙ\ÜÚ[Û—ÛØšˆ[ˆÙ\ÜÚ[Ûœ×ØžWÚY˜[Y\Ê
N‚ˆ›Üˆ˜Z[™YH[ˆÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
Ù\ÜÚ[Û—ÛØšŠN‚ˆ][HHÝ˜Z[™YWÜÙX\˜ÚÚ][JÙ\ÜÚ[Û—ÛØš‹˜Z[™YJBˆ˜Z[™YWÚ][\Ë˜\[™
][JBˆ˜Z[™Y\×ØžWÚÙ^VÊÝŠ][VÈœÙ\ÜÚ[Û—ÚY—JKÝŠ][VÈ˜Z[™YWÚY—JJWHH][B‚ˆ]\ÝÜ™YÚ\Ý\™YHÛÜY
ˆ
ˆ][H›Üˆ][H[ˆ˜Z[™YWÚ][\ÂˆYˆ›Ý][K™Ù]
œ™YÚ\Ý˜][Û—ØØ[˜Ù[YŠBˆ[™›ÝÚ\×Ý˜YWÝ˜Z[š[™×Ý\J][K™Ù]
˜Z[š[™×Ý\HŠJBˆ
KˆÙ^O[[X™H][NˆÝŠ][K™Ù]
˜Ü™X]YØ]ŠHÜˆˆŠK™]™\œÙOUYKˆ
VÎ•RS‘QWÔÑPTÒÔ‘PÑS•ÓSRUBˆ™XÙ[Ý˜Z[™Y\ÈHÂˆ˜Z[™Y\×ØžWÚÙ^VÚÙ^WH›Üˆ[žH[ˆ
Ù\ÜÚ[Û‹™Ù]
QRS—Ô‘PÑS•ÕRS‘QT×ÔÑTÔÒSÓ—ÒÑVJHÜˆ×JBˆYˆ\Ú[œÝ[˜ÙJ[žKXÝ
Bˆ[™
Ù^HH
ÝŠ[žK™Ù]
œÙ\ÜÚ[Û—ÚYŠJKÝŠ[žK™Ù]
˜Z[™YWÚYŠJJJH[ˆ˜Z[™Y\×ØžWÚÙ^BˆVÎ•RS‘QWÔÑPTÒÔ‘PÑS•ÓSRUBˆ™XÙ[ÜÙ\ÜÚ[ÛœÈHÂˆÜÙ\ÜÚ[Û—ÜÙX\˜ÚÚ][JÙ\ÜÚ[Ûœ×ØžWÚYÜÙ\ÜÚ[Û—ÚYJBˆ›ÜˆÙ\ÜÚ[Û—ÚY[ˆÙ\ÜÚ[Û‹™Ù]
QRS—Ô‘PÑS•ÔÑTÔÒSÓ”×ÔÑTÔÒSÓ—ÒÑVJHÜˆ×BˆYˆÙ\ÜÚ[Û—ÚY[ˆÙ\ÜÚ[Ûœ×ØžWÚYˆVÎ•RS‘QWÔÑPTÒÔ‘PÑS•ÓSRUBˆ™XÙ[ÝÛÛÈHÂˆÈ›X™[ŽˆQRS—ÔÑPTÒÕÓÓÖÙ[™Ú[VÌK™\ØÜš\[ÛˆŽˆQRS—ÔÑPTÒÕÓÓÖÙ[™Ú[VÌWKˆšXÛÛˆŽˆQRS—ÔÑPTÒÕÓÓÖÙ[™Ú[VÌ—Kš™YˆŽˆ\›Ù›ÜŠ[™Ú[
_Bˆ›Üˆ[™Ú[[ˆÙ\ÜÚ[Û‹™Ù]
QRS—Ô‘PÑS•ÕÓÓ×ÔÑTÔÒSÓ—ÒÑVJHÜˆ×BˆYˆ[™Ú[[ˆQRS—ÔÑPTÒÕÓÓÂˆVÎ•RS‘QWÔÑPTÒÔ‘PÑS•ÓSRUBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK›]\ÝÜ™YÚ\Ý\™YŽˆ]\ÝÜ™YÚ\Ý\™Yˆœ™XÙ[Ý˜Z[™Y\ÈŽˆ™XÙ[Ý˜Z[™Y\Ëœ™XÙ[ÜÙ\ÜÚ[ÛœÈŽˆ™XÙ[ÜÙ\ÜÚ[ÛœËˆœ™XÙ[ÝÛÛÈŽˆ™XÙ[ÝÛÛßJB‚‚\™Ù]
‹Ø\KÝ˜Z[™Y\×ÜÙX\˜ÚŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™Yˆ\WÝ˜Z[™Y\×ÜÙX\˜Ú

N‚ˆHH
™\]Y\Ý˜\™ÜË™Ù]
œHŠHÜˆˆŠKœÝš\

K›ÝÙ\Š
Bˆ]HHØYÙ]J
Bˆš\ÚX›WÜ\™\—ÚYHØÝ\œ™[Ü\™\—ÚY

HÜˆS•QÔSWÔT•‘T—ÒQˆ[Ú][\ÈH×Bˆ][\×ØžWÚÙ^HHßB‚ˆ›ÜˆÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JN‚ˆYˆ›Ý\Ú[œÝ[˜ÙJËXÝ
HÜˆ
Ë™Ù]
œ\™\—ÚYŠHÜˆS•QÔSWÔT•‘T—ÒQ
HOHš\ÚX›WÜ\™\—ÚY‚ˆÛÛ[YBˆYˆÚ\×ÝÙYÙ—ÛXY×ÜÙ\ÜÚ[ÛŠÊN‚ˆÛÛ[YBˆ›Üˆ[ˆÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊN‚ˆ][HHÝ˜Z[™YWÜÙX\˜ÚÚ][JË
Bˆ[Ú][\Ë˜\[™
][JBˆ][\×ØžWÚÙ^VÊÝŠ][VÈœÙ\ÜÚ[Û—ÚY—JKÝŠ][VÈ˜Z[™YWÚY—JJWHH][B‚ˆYˆ[ŠJHŽ‚ˆ]\ÝÜ™YÚ\Ý\™YHÛÜY
ˆ
ˆ][H›Üˆ][H[ˆ[Ú][\ÂˆYˆ›Ý][K™Ù]
œ™YÚ\Ý˜][Û—ØØ[˜Ù[YŠBˆ[™›ÝÚ\×Ý˜YWÝ˜Z[š[™×Ý\J][K™Ù]
˜Z[š[™×Ý\HŠJBˆ
KˆÙ^O[[X™H][NˆÝŠ][K™Ù]
˜Ü™X]YØ]ŠHÜˆˆŠKˆ™]™\œÙOUYKˆ
VÎ•RS‘QWÔÑPTÒÔ‘PÑS•ÓSRUBˆ™XÙ[ØÛÛœÝ[YH×Bˆ›Üˆ[žH[ˆÙ\ÜÚ[Û‹™Ù]
QRS—Ô‘PÑS•ÕRS‘QT×ÔÑTÔÒSÓ—ÒÑVJHÜˆ×N‚ˆYˆ›Ý\Ú[œÝ[˜ÙJ[žKXÝ
N‚ˆÛÛ[YBˆ][HH][\×ØžWÚÙ^K™Ù]

ÝŠ[žK™Ù]
œÙ\ÜÚ[Û—ÚYŠJKÝŠ[žK™Ù]
˜Z[™YWÚYŠJJJBˆYˆ][N‚ˆ™XÙ[ØÛÛœÝ[Y˜\[™
][JBˆYˆ[Š™XÙ[ØÛÛœÝ[Y
HOHRS‘QWÔÑPTÒÔ‘PÑS•ÓSRU‚ˆœ™XZÂˆ™]\›ˆœÛÛšYžJÂˆ›ÚÈŽˆYKˆš][\ÈŽˆ×Kˆ›]\ÝÜ™YÚ\Ý\™YŽˆ]\ÝÜ™YÚ\Ý\™Yˆœ™XÙ[ØÛÛœÝ[YŽˆ™XÙ[ØÛÛœÝ[YˆJB‚ˆÝ]H×Bˆ›Üˆ][H[ˆ[Ú][\Î‚ˆš\œÝÛ˜[YHH][VÈ™š\œÝÛ˜[YH—Bˆ\ÝÛ˜[YHH][VÈ›\ÝÛ˜[YH—Bˆ[Û˜[YHHˆžÙš\œÝÛ˜[Y_HÛ\ÝÛ˜[Y_H‹œÝš\

K›ÝÙ\Š
BˆYˆH[ˆ[Û˜[YHÜˆH[ˆš\œÝÛ˜[YK›ÝÙ\Š
HÜˆH[ˆ\ÝÛ˜[YK›ÝÙ\Š
N‚ˆÝ]˜\[™
][JB‚ˆÝ]œÛÜ
Ù^O[[X™H][Nˆ
ˆ
][K™Ù]
›\ÝÛ˜[YHŠHÜˆˆŠK›ÝÙ\Š
Kˆ
][K™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠK›ÝÙ\Š
Kˆ
JBˆÝ]HÝ]ÎŒÌBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKš][\ÈŽˆÝ]˜ÛÝ[Žˆ[ŠÝ]
_JB‚‚\™Ù]
‹Ø\KØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹Ý˜Z[™Y\ËÏ˜Z[™YWÚY‹ÜÝ[[X\žHŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™Yˆ\WØYZ[—Ý˜Z[™YWÜ]ZXÚ×ÜÝ[[X\žJÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆÙ\ÜÚ[Û—ÛØšˆHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÙ\ÜÚ[Û—ÛØšˆÜˆ
Ù\ÜÚ[Û—ÛØš‹™Ù]
œ\™\—ÚYŠHÜˆS•QÔSWÔT•‘T—ÒQ
HOH
ØÝ\œ™[Ü\™\—ÚY

HÜˆS•QÔSWÔT•‘T—ÒQ
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆœÙ\ÜÚ[Û—Û›ÝÙ›Ý[™ŸJKˆ˜Z[™YHHš[™Ý˜Z[™YJÙ\ÜÚ[Û—ÛØš‹˜Z[™YWÚY
BˆYˆ›Ý˜Z[™YN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ˜Z[™YWÛ›ÝÙ›Ý[™ŸJKˆ™]\›ˆœÛÛšYžJÝ˜Z[™YWÜ]ZXÚ×ÜÝ[[X\žJ]KÙ\ÜÚ[Û—ÛØš‹˜Z[™YJJB‚‚\™Ù]
‹Ø\KØÛ˜\ËÝ˜Z[™Y\ÈŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™Yˆ\WØÛ˜\×Ý˜Z[™Y\Ê
N‚ˆ]HHØYÙ]J
BˆÙ\ÜÚ[Ûœ×ÛÝ]H×Bˆ›ÜˆÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JN‚ˆYˆ›ÛÛ
Ë™Ù]
˜\˜Ú]™YŠJN‚ˆÛÛ[YBˆYˆÚ\×ÝÙYÙ—ÛXY×ÜÙ\ÜÚ[ÛŠÊN‚ˆÛÛ[YBˆ˜Z[™Y\ÈHÜ™YÚ\Ý\™YÝ˜Z[™Y\ÊÊBˆÙ\ÜÚ[Ûœ×ÛÝ]˜\[™
ÂˆšYŽˆË™Ù]
šYŠKˆ›˜[YHŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë›˜[YH‹ˆŠKˆ˜Z[š[™×Ý\HŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠKˆ˜Z[™Y\ÈŽˆÂˆÂˆšYŽˆ™Ù]
šYŠKˆ™š\œÝÛ˜[YHŽˆ™Ù]
™š\œÝÛ˜[YH‹ˆŠKˆ›\ÝÛ˜[YHŽˆ™Ù]
›\ÝÛ˜[YH‹ˆŠKˆ˜š\Ù]HŽˆ™Ù]
˜š\Ù]H‹ˆŠKˆBˆ›Üˆ[ˆ˜Z[™Y\ÂˆKˆJB‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKœÙ\ÜÚ[ÛœÈŽˆÙ\ÜÚ[Ûœ×ÛÝ]JB‚‚\œÜÝ
‹Ø\KØÛ˜\ËÜ™WÜ™\]Y\ÝŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØÛ˜\×Ü™WÜ™\]Y\Ý

N‚ˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆ][\ÈH^[ØY™Ù]
š][\ÈŠHYˆ\Ú[œÝ[˜ÙJ^[ØY™Ù]
š][\ÈŠK\Ý
H[ÙH×BˆYˆ›Ý][\Î‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››×Ú][\ÈŸJK‚ˆ]HHØYÙ]J
Bˆ\]YH‚ˆ›Üˆ][H[ˆ][\Î‚ˆÙ\ÜÚ[Û—ÚYHÝŠ][K™Ù]
œÙ\ÜÚ[Û—ÚYŠHÜˆˆŠKœÝš\

Bˆ˜Z[™YWÚYHÝŠ][K™Ù]
˜Z[™YWÚYŠHÜˆˆŠKœÝš\

BˆYˆ›ÝÙ\ÜÚ[Û—ÚYÜˆ›Ý˜Z[™YWÚY‚ˆÛÛ[YBˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆÛÛ[YBˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆH™^

›Üˆ[ˆ˜Z[™Y\ÈYˆ™Ù]
šYŠHOH˜Z[™YWÚY
K›Û™JBˆYˆ›ÝÜˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆÛÛ[YBˆ™XÛÜ™ØÛ˜\×Ü™WÜ™\]Y\Ý

Bˆ\]Y
ÏHBˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JB‚ˆYˆ\]Y‚ˆØ]™WÙ]J]JB‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK\]YŽˆ\]YJB‚‚\œÜÝ
‹Ø\KØÛ˜\ËÚ[\Ü\™HŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™Yˆ\WØÛ˜\×Ú[\ÜÜ™J
N‚ˆš[\ÈH™\]Y\Ý™š[\Ë™Ù]\Ý
™š[\ÈŠBˆYˆ›Ýš[\Î‚ˆÚ[™ÛHH™\]Y\Ý™š[\Ë™Ù]
™š[HŠBˆYˆÚ[™ÛN‚ˆš[\ÈHÜÚ[™ÛWB‚ˆ˜[YÙš[\ÈHÙˆ›Üˆˆ[ˆš[\ÈYˆˆ[™
‹™š[[˜[YHÜˆˆŠK›ÝÙ\Š
K™[™ÝÚ]
‹œˆŠWBˆYˆ›Ý˜[YÙš[\Î‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›Z\ÜÚ[™×ÜˆŸJK‚ˆ]HHØYÙ]J
Bˆ[™[™ÈHØÛ˜\×Ü[™[™×Ú[\ÜÊ]JBˆ[™[™×Ú\Ú\ÈHÂˆ
][K™Ù]
œÚLHŠHÜˆˆŠKœÝš\

K›ÝÙ\Š
Bˆ›Üˆ][H[ˆ[™[™ÂˆYˆ
][K™Ù]
œÚLHŠHÜˆˆŠKœÝš\

BˆBˆ˜Z[™Y\×Ú[™^ˆXÝÕ\VÜÝ‹Ý—K\ÝÑXÝÜÝ‹[žWWWHHßBˆ˜Z[™Y\×ØžWÛ\ÝÛ˜[YNˆXÝÜÝ‹\ÝÑXÝÜÝ‹[žWWWHHßB‚ˆ›ÜˆÙ\ÜÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JN‚ˆYˆ›ÛÛ
Ù\ÜË™Ù]
˜\˜Ú]™YŠJHÜˆ›ÝØÛ˜\×Ü™WÝ˜Z[š[™×Ý\WÚ\×Ø[ÝÙY
ÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜË˜Z[š[™×Ý\H‹ˆŠJN‚ˆÛÛ[YBˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
Ù\ÜÊBˆ›Üˆ˜Z[™YH[ˆ˜Z[™Y\Î‚ˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y
˜Z[™YJN‚ˆÛÛ[YBˆÙ^HH
ˆÛ›Ü›X[^™WÜ\œÛÛ—Û˜[YJ˜Z[™YK™Ù]
›\ÝÛ˜[YH‹ˆŠJKˆÛ›Ü›X[^™WÜ\œÛÛ—Û˜[YJ˜Z[™YK™Ù]
™š\œÝÛ˜[YH‹ˆŠJKˆ
BˆYˆ›ÝÙ^VÌHÜˆ›ÝÙ^VÌWN‚ˆÛÛ[YBˆ[žHHÂˆœÙ\ÜÚ[ÛˆŽˆÙ\ÜËˆ˜Z[™YHŽˆ˜Z[™YKˆBˆ˜Z[™Y\×Ú[™^œÙ]Y˜][
Ù^K×JK˜\[™
[žJBˆ˜Z[™Y\×ØžWÛ\ÝÛ˜[YKœÙ]Y˜][
Ù^VÌK×JK˜\[™
[žJB‚ˆX]Ú\ÈH×Bˆ[›X]ÚYH×B‚ˆ›Üˆš[WÚ[™^š[H[ˆ[[Y\˜]J˜[YÙš[\ÊN‚ˆ˜[YHH
š[K™š[[˜[YHÜˆ™ØÝ[Y[œˆŠKœÝš\

HÜˆ™ØÝ[Y[œˆ‚ˆš[WØž]\ÈHš[Kœ™XY

HÜˆˆˆ‚ˆYÙ\ÝH\ÚX‹œÚLJš[WØž]\ÊKš^YÙ\Ý

HYˆš[WØž]\È[ÙHˆ‚ˆ[™XYWÜØ]™YH›ÛÛ
YÙ\Ý[™YÙ\Ý[ˆ[™[™×Ú\Ú\ÊBˆ^HÙ^˜XÝÜ—Ý^
š[WØž]\ÊBˆ[[WÚ^\ÝXÚËÈHØZ[Ü—ÜÙX\˜ÚÚ^\ÝXÚÜÊš[WØž]\ÊBˆÛÛXš[™YÝ^H
^ÜˆˆŠH
È—ˆˆ
È
[[WÚ^\ÝXÚÈÜˆˆŠB‚ˆYˆ›Ý^[™›Ý[[WÚ^\ÝXÚÎ‚ˆ[›X]ÚY˜\[™
È™š[WÛ˜[YHŽˆ˜[YKœ™X\ÛÛˆŽˆœ—Ý[œ™XYX›HŸJBˆÛÛ[YB‚ˆ™WÛ[X™\ˆHÙ^˜XÝÜ™WÙœ›ÛWÝ^
^
BˆYˆ›Ý™WÛ[X™\Ž‚ˆ™WÛ[X™\ˆHÙ^˜XÝÜ™WÙœ›ÛWØÛÛ\XÝÝ^
[[WÚ^\ÝXÚÊB‚ˆ\ÝÛ˜[YKš\œÝÛ˜[YHHÙ^˜XÝÛ˜[YWÙœ›ÛWØÛ˜\×Ý^
^
BˆYˆ›Ý
\ÝÛ˜[YH[™š\œÝÛ˜[YJN‚ˆ^Ù[žHHÙš[™ØÛ˜\×Ý˜Z[™YWÛX]ÚÚ[—Ý^
˜Z[™Y\×ØžWÛ\ÝÛ˜[YKÛÛXš[™YÝ^š\œÝÛ˜[YJBˆYˆ^Ù[žN‚ˆ˜Z[™YWÙÝY\ÜÈH^Ù[žK™Ù]
˜Z[™YHŠHÜˆßBˆYˆ›Ý\ÝÛ˜[YN‚ˆ\ÝÛ˜[YHHÛ›Ü›X[^™WÜ\œÛÛ—Û˜[YJ˜Z[™YWÙÝY\ÜË™Ù]
›\ÝÛ˜[YH‹ˆŠJBˆYˆ›Ýš\œÝÛ˜[YN‚ˆš\œÝÛ˜[YHHÛ›Ü›X[^™WÜ\œÛÛ—Û˜[YJ˜Z[™YWÙÝY\ÜË™Ù]
™š\œÝÛ˜[YH‹ˆŠJB‚ˆYˆ›Ý™WÛ[X™\Ž‚ˆ[›X]ÚY˜\[™
Âˆ™š[WÛ˜[YHŽˆ˜[YKˆœ™X\ÛÛˆŽˆ›Z\ÜÚ[™×Ü™H‹ˆ™^˜XÝYŽˆÂˆ›\ÝÛ˜[YHŽˆ\ÝÛ˜[YKˆ™š\œÝÛ˜[YHŽˆš\œÝÛ˜[YKˆœ™WÛ[X™\ˆŽˆ™WÛ[X™\‹ˆKˆJBˆÛÛ[YB‚ˆ[žHHÙš[™ØÛ˜\×Ý˜Z[™YWÛX]Ú
˜Z[™Y\×Ú[™^˜Z[™Y\×ØžWÛ\ÝÛ˜[YK\ÝÛ˜[YKš\œÝÛ˜[YJBˆYˆ›Ý[žH[™›Ý
\ÝÛ˜[YH[™š\œÝÛ˜[YJN‚ˆ[žHHÙš[™ØÛ˜\×Ý˜Z[™YWÛX]ÚÚ[—Ý^
˜Z[™Y\×ØžWÛ\ÝÛ˜[YKÛÛXš[™YÝ^š\œÝÛ˜[YJBˆYˆ›Ý[žN‚ˆX]Ú\Ë˜\[™
ÂˆœÛÝ\˜ÙWÚ[™^Žˆš[WÚ[™^ˆ™š[WÛ˜[YHŽˆ˜[YKˆ›\ÝÛ˜[YHŽˆ\ÝÛ˜[YKˆ™š\œÝÛ˜[YHŽˆš\œÝÛ˜[YKˆœ™WÛ[X™\ˆŽˆ™WÛ[X™\‹ˆ™›Ü›X][ÛˆŽˆˆ‹ˆ˜Z[š[™×Ù]\ÈŽˆÂˆœÝ\Žˆˆ‹ˆ™[™Žˆˆ‹ˆKˆœÙ\ÜÚ[Û—ÚYŽˆˆ‹ˆ˜Z[™YWÚYŽˆˆ‹ˆ›X]ÚÙ›Ý[™Žˆ˜[ÙKˆ˜[™XYWÛY\™ÙYŽˆ˜[ÙKˆ˜[™XYWÜØ]™YŽˆ[™XYWÜØ]™YˆJBˆÛÛ[YB‚ˆÙ\ÜÚ[Û—ÛØšˆH[žVÈœÙ\ÜÚ[Ûˆ—Bˆ˜Z[™YHH[žVÈ˜Z[™YH—BˆX]Ú\Ë˜\[™
ÂˆœÛÝ\˜ÙWÚ[™^Žˆš[WÚ[™^ˆ™š[WÛ˜[YHŽˆ˜[YKˆ›\ÝÛ˜[YHŽˆ˜Z[™YK™Ù]
›\ÝÛ˜[YH‹ˆŠKˆ™š\œÝÛ˜[YHŽˆ˜Z[™YK™Ù]
™š\œÝÛ˜[YH‹ˆŠKˆœ™WÛ[X™\ˆŽˆ™WÛ[X™\‹ˆ™›Ü›X][ÛˆŽˆ›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹˜Z[š[™×Ý\H‹ˆŠJKˆ˜Z[š[™×Ù]\ÈŽˆÂˆœÝ\Žˆœ—Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹™]WÜÝ\‹ˆŠJKˆ™[™Žˆœ—Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹™]WÙ[™‹ˆŠJKˆKˆœÙ\ÜÚ[Û—ÚYŽˆÙ\ÜÚ[Û—ÛØš‹™Ù]
šYŠKˆ˜Z[™YWÚYŽˆ˜Z[™YK™Ù]
šYŠKˆ›X]ÚÙ›Ý[™ŽˆYKˆ˜[™XYWÛY\™ÙYŽˆ›ÛÛ
˜Z[™YK™Ù]
˜Û˜\×Ú[\ÜÛY\™ÙYÛÛ˜ÙHŠJKˆ˜[™XYWÜØ]™YŽˆ[™XYWÜØ]™YˆJB‚ˆ™]\›ˆœÛÛšYžJÂˆ›ÚÈŽˆYKˆ›X]Ú\ÈŽˆX]Ú\Ëˆ[›X]ÚYŽˆ[›X]ÚYˆ˜ÛÝ[Žˆ[ŠX]Ú\ÊKˆJB‚‚\œÜÝ
‹Ø\KØÛ˜\ËÚ[\Ü\™KÛY\™ÙHŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØÛ˜\×Ú[\ÜÜ™WÛY\™ÙJ
N‚ˆÙ\ÜÚ[Û—ÚYH
™\]Y\Ý™›Ü›K™Ù]
œÙ\ÜÚ[Û—ÚYŠHÜˆˆŠKœÝš\

Bˆ˜Z[™YWÚYH
™\]Y\Ý™›Ü›K™Ù]
˜Z[™YWÚYŠHÜˆˆŠKœÝš\

Bˆ™WÜ˜]ÈH
™\]Y\Ý™›Ü›K™Ù]
œ™WÛ[X™\ˆŠHÜˆˆŠKœÝš\

BˆXˆH
™\]Y\Ý™›Ü›K™Ù]
›XˆŠHÜˆˆŠKœÝš\

Bˆ\ØYYH™\]Y\Ý™š[\Ë™Ù]
™š[HŠB‚ˆYˆ›ÝÙ\ÜÚ[Û—ÚYÜˆ›Ý˜Z[™YWÚY‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›Z\ÜÚ[™×Ý\™Ù]ŸJKˆYˆ›Ý\ØYYÜˆ›Ý\ØYY™š[[˜[YN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›Z\ÜÚ[™×Ùš[HŸJKˆYˆ›Ý
\ØYY™š[[˜[YHÜˆˆŠK›ÝÙ\Š
K™[™ÝÚ]
‹œˆŠN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆš[˜[YÙš[HŸJK‚ˆ™WÛ[X™\ˆHÛ›Ü›X[^™WÜ™WØØ\Š™WÜ˜]ÊBˆYˆ›ÝÚ\×Ý˜[YÜ™WØØ\Š™WÛ[X™\ŠN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆš[˜[YÜ™HŸJK‚ˆ]HHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆœÙ\ÜÚ[Û—Û›ÝÙ›Ý[™ŸJK‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆH™^

›Üˆ[ˆ˜Z[™Y\ÈYˆ™Ù]
šYŠHOH˜Z[™YWÚY
K›Û™JBˆYˆ›Ý‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ˜Z[™YWÛ›ÝÙ›Ý[™ŸJK‚ˆ˜Z[š[™×Ý\HHÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠBˆYˆ›ÝØÛ˜\×Ü™WÝ˜Z[š[™×Ý\WÚ\×Ø[ÝÙY
˜Z[š[™×Ý\JN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ˜Z[š[™×Û›ÝÙ[YÚX›HŸJK‚ˆÝÜ™YHÜÝÜ™WÙš[JÙ\ÜÚ[Û—ÚY˜Z[™YWÚY™ØÝ[Y[È‹\ØYY
BˆÚÙ[ˆHÝÚÙ[š^™WÜ]
ÝÜ™Y
B‚ˆØ]XÚØÛ˜\×Ý×Ý˜Z[™YJ˜Z[š[™×Ý\K™WÛ[X™\‹ÚÙ[‹’[\Ü‘HÓTÈ\Ú[Û›°êH‹ÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠJBˆÈ˜Û˜\×Ú[\ÜÛY\™ÙYÛÛ˜ÙH—HHYBˆÈ˜Û˜\×Ú[\ÜÛY\™ÙYØ]—HHÛ›Ý×Ú\ÛÊ
BˆÛX\š×ØÛ˜\×ÜÝ]\×ØÚ[™ÙWÚ[\ÜY
]K\ÝÛ˜[YO]™Ù]
›\ÝÛ˜[YH‹ˆŠKX[XŠB‚ˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JB‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKœ™WÛ[X™\ˆŽˆ™WÛ[X™\‹œ[™[™×ÜÝ]\×ØÚ[™Ù\×ØÛÝ[ŽˆØÛ˜\×Ü[™[™×ÜÝ]\×ØÚ[™ÙWØÛÝ[
]J_JB‚‚\œÜÝ
‹Ø\KØÛ˜\ËÚ[\Ü\™KÜØ]™HŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØÛ˜\×Ú[\ÜÜ™WÜØ]™J
N‚ˆ™WÜ˜]ÈH
™\]Y\Ý™›Ü›K™Ù]
œ™WÛ[X™\ˆŠHÜˆˆŠKœÝš\

BˆXˆH
™\]Y\Ý™›Ü›K™Ù]
›XˆŠHÜˆˆŠKœÝš\

Bˆ\ÝÛ˜[YHHÛ›Ü›X[^™WÜ\œÛÛ—Û˜[YJ™\]Y\Ý™›Ü›K™Ù]
›\ÝÛ˜[YHŠHÜˆˆŠBˆš\œÝÛ˜[YHHÛ›Ü›X[^™WÜ\œÛÛ—Û˜[YJ™\]Y\Ý™›Ü›K™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠBˆ\ØYYH™\]Y\Ý™š[\Ë™Ù]
™š[HŠB‚ˆYˆ›Ý\ØYYÜˆ›Ý\ØYY™š[[˜[YN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›Z\ÜÚ[™×Ùš[HŸJKˆYˆ›Ý
\ØYY™š[[˜[YHÜˆˆŠK›ÝÙ\Š
K™[™ÝÚ]
‹œˆŠN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆš[˜[YÙš[HŸJK‚ˆ™WÛ[X™\ˆHÛ›Ü›X[^™WÜ™WØØ\Š™WÜ˜]ÊBˆYˆ›ÝÚ\×Ý˜[YÜ™WØØ\Š™WÛ[X™\ŠN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆš[˜[YÜ™HŸJK‚ˆYˆ›Ý\ÝÛ˜[YHÜˆ›Ýš\œÝÛ˜[YN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›Z\ÜÚ[™×Û˜[YHŸJK‚ˆ]HHØYÙ]J
Bˆ[™[™ÈHØÛ˜\×Ü[™[™×Ú[\ÜÊ]JB‚ˆš[WØž]\ÈH\ØYYœ™XY

HÜˆˆˆ‚ˆYˆ›Ýš[WØž]\Î‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™[\WÙš[HŸJK‚ˆYÙ\ÝH\ÚX‹œÚLJš[WØž]\ÊKš^YÙ\Ý

Bˆ\XØ]HH™^

›Üˆ[ˆ[™[™ÈYˆ
™Ù]
œÚLHŠHÜˆˆŠHOHYÙ\Ý
K›Û™JBˆYˆ\XØ]N‚ˆ›ÝYšXØ][Û—Ü™]šY]ÙYHÛX\š×ØÛ˜\×ÜÝ]\×ØÚ[™ÙWÚ[\ÜY
]K\ÝÛ˜[YO[\ÝÛ˜[YKX[XŠBˆYˆ›ÝYšXØ][Û—Ü™]šY]ÙY‚ˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÂˆ›ÚÈŽˆYKˆœØ]™YŽˆYKˆ˜[™XYWÜØ]™YŽˆYKˆ››ÝYšXØ][Û—Ü™]šY]ÙYŽˆ›ÝYšXØ][Û—Ü™]šY]ÙYˆœ[™[™×ÜÝ]\×ØÚ[™Ù\×ØÛÝ[ŽˆØÛ˜\×Ü[™[™×ÜÝ]\×ØÚ[™ÙWØÛÝ[
]JKˆJB‚ˆÚÙ[ˆHÜÝÜ™WØÛ˜\×Ü[™[™×ÜŠš[WØž]\Ë\ØYY™š[[˜[YHÜˆ™ØÝ[Y[œˆŠBˆY[YšY\œÈHÙš[™ØÛ˜\ÝŒ×ÚY[YšY\—Ù›Ü—Ü[™[™Ê]K\ÝÛ˜[YKš\œÝÛ˜[YJBˆ™\]Y\ÝÚYHY[YšY\œË™Ù]
œ™\]Y\ÝÚYŠHÜˆˆ‚ˆÜÜÚY\—ÚYHY[YšY\œË™Ù]
™ÜÜÚY\—ÚYŠHÜˆˆ‚‚ˆ[™[™×Ú][HHÂˆšYŽˆÔ‹Hˆ
È]ZY]ZY

Kš^ÎŒLK\\Š
Kˆ›\ÝÛ˜[YHŽˆ\ÝÛ˜[YKˆ™š\œÝÛ˜[YHŽˆš\œÝÛ˜[YKˆœ™WÛ[X™\ˆŽˆ™WÛ[X™\‹ˆ™š[WÛ˜[YHŽˆ
\ØYY™š[[˜[YHÜˆ™ØÝ[Y[œˆŠKœÝš\

HÜˆ™ØÝ[Y[œˆ‹ˆ™š[WÝÚÙ[ˆŽˆÚÙ[‹ˆœÚLHŽˆYÙ\Ýˆ˜Ü™X]YØ]ŽˆÛ›Ý×Ú\ÛÊ
Kˆ˜Û˜\ÝŒ×Ü™\]Y\ÝÚYŽˆ™\]Y\ÝÚYˆ˜Û˜\ÝŒ×ÙÜÜÚY\—ÚYŽˆÜÜÚY\—ÚYˆ™[XZ[Žˆˆ‹ˆBˆ[™[™Ë˜\[™
[™[™×Ú][JB‚ˆYˆ›Ý™\]Y\ÝÚY[™›ÝÜÜÚY\—ÚY‚ˆ[XZ[HÙš[™Ü[™[™×Ý˜Z[™YWÙ[XZ[
]K\ÝÛ˜[YKš\œÝÛ˜[YJBˆÛÚÝ\ÚY[YšY\œÈHÞ[˜×ØÛ˜\ÝŒ×ÛÛÚÝ\ÚY[YšY\Šˆš\œÝÛ˜[YOYš\œÝÛ˜[YKˆ\ÝÛ˜[YO[\ÝÛ˜[YKˆ[XZ[Y[XZ[Üˆ›Û™Kˆ
BˆYˆÛÚÝ\ÚY[YšY\œÎ‚ˆ™\]Y\ÝÚYHÝŠÛÚÝ\ÚY[YšY\œË™Ù]
œ™\]Y\ÝÚYŠHÜˆˆŠKœÝš\

BˆÜÜÚY\—ÚYHÝŠÛÚÝ\ÚY[YšY\œË™Ù]
™ÜÜÚY\—ÚYŠHÜˆˆŠKœÝš\

BˆÛ˜\ÝŒ×Ù[XZ[HÝŠÛÚÝ\ÚY[YšY\œË™Ù]
™[XZ[ŠHÜˆˆŠKœÝš\

Bˆ[™[™×Ú][VÈ˜Û˜\ÝŒ×Ü™\]Y\ÝÚY—HH™\]Y\ÝÚYˆ[™[™×Ú][VÈ˜Û˜\ÝŒ×ÙÜÜÚY\—ÚY—HHÜÜÚY\—ÚYˆYˆÛ˜\ÝŒ×Ù[XZ[‚ˆ[™[™×Ú][VÈ™[XZ[—HHÛ˜\ÝŒ×Ù[XZ[ˆ[ÙN‚ˆ\›ÙÙÙ\‹š[™›Êˆ–ÐÓTÕŒ×ÔÖS×HXØÙ\YÛ›Ü°êNˆ]XÝ[ˆY[YšX[›Ý]°êH\°êÈÛÚÝ\š\œÝÛ˜[YOI\È\ÝÛ˜[YOI\È‹ˆš\œÝÛ˜[YKˆ\ÝÛ˜[YKˆ
B‚ˆYˆ›Ý[™[™×Ú][K™Ù]
™[XZ[ŠN‚ˆ[™[™×Ú][VÈ™[XZ[—HHÙš[™Ü[™[™×Ý˜Z[™YWÙ[XZ[
]K\ÝÛ˜[YKš\œÝÛ˜[YJB‚ˆ›ÝYšXØ][Û—Ü™]šY]ÙYHÛX\š×ØÛ˜\×ÜÝ]\×ØÚ[™ÙWÚ[\ÜY
]K\ÝÛ˜[YO[\ÝÛ˜[YKX[XŠBˆØ]™WÙ]J]JB‚ˆÛ˜\ÝŒ×ÛX]ÚÙ›Ý[™H›ÛÛ
™\]Y\ÝÚYÜˆÜÜÚY\—ÚY
B‚ˆÞ[˜×ÛÚÈH˜[ÙBˆYˆÛ˜\ÝŒ×ÛX]ÚÙ›Ý[™‚ˆÞ[˜×ÛÚÈHÞ[˜×ØÛ˜\ÝŒ×ØXØÙ\ÜÝ]\Ê™\]Y\ÝÚY\™\]Y\ÝÚYÜÜÚY\—ÚYYÜÜÚY\—ÚY
B‚ˆ™]\›ˆœÛÛšYžJÂˆ›ÚÈŽˆYKˆœØ]™YŽˆYKˆ˜[™XYWÜØ]™YŽˆ˜[ÙKˆ˜Û˜\ÝŒ×ÜÞ[˜×ÛÚÈŽˆÞ[˜×ÛÚËˆ˜Û˜\ÝŒ×ÛX]ÚÙ›Ý[™ŽˆÛ˜\ÝŒ×ÛX]ÚÙ›Ý[™ˆ››ÝYšXØ][Û—Ü™]šY]ÙYŽˆ›ÝYšXØ][Û—Ü™]šY]ÙYˆœ[™[™×ÜÝ]\×ØÚ[™Ù\×ØÛÝ[ŽˆØÛ˜\×Ü[™[™×ÜÝ]\×ØÚ[™ÙWØÛÝ[
]JKˆJB‚‚\™Ù]
‹ØYZ[‹ØÛ˜\ËÚ[\Ü\™KÜ[™[™ÈŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—ØÛ˜\×Ü[™[™×Ú[\ÜÊ
N‚ˆ]HHØYÙ]J
Bˆ[™[™ÈHØÛ˜\×Ü[™[™×Ú[\ÜÊ]JBˆ[™[™×Ú][\ÈH×B‚ˆ›Üˆ][H[ˆ[™[™Î‚ˆš[WÝÚÙ[ˆH
][K™Ù]
™š[WÝÚÙ[ˆŠHÜˆˆŠKœÝš\

Bˆš[WÙ^\ÝÈH›ÛÛ
š[WÝÚÙ[ˆ[™ÜËœ]™^\ÝÊÙ]ÚÙ[š^™WÜ]
š[WÝÚÙ[ŠJJBˆ[™[™×Ú][\Ë˜\[™
ÂˆšYŽˆ
][K™Ù]
šYŠHÜˆˆŠKœÝš\

Kˆ›\ÝÛ˜[YHŽˆ
][K™Ù]
›\ÝÛ˜[YHŠHÜˆˆŠKœÝš\

Kˆ™š\œÝÛ˜[YHŽˆ
][K™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

Kˆ™[XZ[Žˆ
][K™Ù]
™[XZ[ŠHÜˆˆŠKœÝš\

Kˆœ™WÛ[X™\ˆŽˆ
][K™Ù]
œ™WÛ[X™\ˆŠHÜˆˆŠKœÝš\

Kˆ™š[WÛ˜[YHŽˆ
][K™Ù]
™š[WÛ˜[YHŠHÜˆˆŠKœÝš\

HÜˆ™ØÝ[Y[œˆ‹ˆ™š[WÝÚÙ[ˆŽˆš[WÝÚÙ[‹ˆ™š[WÝ\›Žˆ\›Ù›ÜŠ˜YZ[—ÝšY]×Ý\ØY‹]Yš[WÝÚÙ[ŠHYˆš[WÝÚÙ[ˆ[ÙHˆ‹ˆ˜Ü™X]YØ]Žˆ
][K™Ù]
˜Ü™X]YØ]ŠHÜˆˆŠKœÝš\

Kˆ™š[WÙ^\ÝÈŽˆš[WÙ^\ÝËˆJB‚ˆ[™[™×Ú][\ËœÛÜ
Ù^O[[X™Hˆ™Ù]
˜Ü™X]YØ]ŠHÜˆˆ‹™]™\œÙOUYJB‚ˆ™]\›ˆ™[™\—Ý[\]Jˆ˜YZ[—ØÛ˜\×Ü[™[™×Ú[\ÜËš[‹ˆ[™[™×Ú][\Ï\[™[™×Ú][\Ëˆ
B‚‚\œÜÝ
‹Ø\KØÛ˜\ËÚ[\Ü\™KÜ[™[™ËÏ[™[™×ÚY‹Ù[]HŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØÛ˜\×Ü[™[™×Ú[\ÜÙ[]J[™[™×ÚYˆÝŠN‚ˆ\™Ù]ÚYH
[™[™×ÚYÜˆˆŠKœÝš\

BˆYˆ›Ý\™Ù]ÚY‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›Z\ÜÚ[™×ÚYŸJK‚ˆ]HHØYÙ]J
Bˆ[™[™ÈHØÛ˜\×Ü[™[™×Ú[\ÜÊ]JB‚ˆ™[[Ý™YÚ][HH›Û™Bˆ™[XZ[š[™ÈH×Bˆ›Üˆ][H[ˆ[™[™Î‚ˆYˆ›Ý™[[Ý™YÚ][H[™
][K™Ù]
šYŠHÜˆˆŠKœÝš\

HOH\™Ù]ÚY‚ˆ™[[Ý™YÚ][HH][BˆÛÛ[YBˆ™[XZ[š[™Ë˜\[™
][JB‚ˆYˆ›Ý™[[Ý™YÚ][N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››ÝÙ›Ý[™ŸJK‚ˆ]VÈ˜Û˜\×Ü[™[™×Ú[\ÜÈ—HH™[XZ[š[™Â‚ˆ™[[Ý™YÝÚÙ[ˆH
™[[Ý™YÚ][K™Ù]
™š[WÝÚÙ[ˆŠHÜˆˆŠKœÝš\

BˆYˆ™[[Ý™YÝÚÙ[Ž‚ˆÝ[Ý\ÙYH[žJ
™Ù]
™š[WÝÚÙ[ˆŠHÜˆˆŠKœÝš\

HOH™[[Ý™YÝÚÙ[ˆ›Üˆ[ˆ™[XZ[š[™ÊBˆYˆ›ÝÝ[Ý\ÙY‚ˆžN‚ˆš[WÜ]HÙ]ÚÙ[š^™WÜ]
™[[Ý™YÝÚÙ[ŠBˆYˆÜËœ]™^\ÝÊš[WÜ]
N‚ˆÜØY™WÜ™[[Ý™WÙš[Jš[WÜ]
Bˆ^Ù\^Ù\[ÛŽ‚ˆ\ÜÂ‚ˆØ]™WÙ]J]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK™[]YŽˆY_JB‚‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËØ\˜Ú]™YŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—ÜÙ\ÜÚ[Ûœ×Ø\˜Ú]™Y

N‚ˆ]HHØYÙ]J
BˆÝ]ÜÙ\ÜÚ[ÛœÈH×B‚ˆ›ÜˆÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JN‚ˆYˆ›Ý›ÛÛ
Ë™Ù]
˜\˜Ú]™YŠJN‚ˆÛÛ[YBˆYˆÚ\×ÝÙYÙ—ÛXY×ÜÙ\ÜÚ[ÛŠÊN‚ˆÛÛ[YB‚ˆÝHÛÛ\]WÜÝ]ÊÊBˆ˜Z[™Y\ÈHÜ™YÚ\Ý\™YÝ˜Z[™Y\ÊÊBˆÜÜÚY\—ØÛÛ\]WÝÝ[HÝ[JˆH›Üˆ[ˆ˜Z[™Y\ÈYˆÜÜÚY\—Ú\×ØÛÛ\]WÝÝ[
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠKÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠJBˆ
BˆÙ\ÜÚ[Û—ÙÜÜÚY\—ØÛÛ\]HH
[Š˜Z[™Y\ÊHˆ[™ÜÜÚY\—ØÛÛ\]WÝÝ[OH[Š˜Z[™Y\ÊJBˆÝ]ÜÙ\ÜÚ[ÛœË˜\[™
ÂˆšYŽˆË™Ù]
šYŠKˆ›˜[YHŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë›˜[YH‹ˆŠKˆ˜Z[š[™×Ý\HŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠKˆ™]WÜÝ\ŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠKˆ™]WÙ[™ŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÙ[™‹ˆŠKˆ™^[WÙ]HŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë™^[WÙ]H‹ˆŠKˆ™^[WÝ[ÜžWÙ]HŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë™^[WÝ[ÜžWÙ]H‹ˆŠKˆ™^[WÜ˜XÝXÙWÙ]HŽˆÜÙ\ÜÚ[Û—ÙÙ]
Ë™^[WÜ˜XÝXÙWÙ]H‹ˆŠKˆÝ[ŽˆÝÈÝ[—KˆœÙ\ÜÚ[Û—Ú\×ØÛÛ™›Ü›HŽˆÝÈœÙ\ÜÚ[Û—Ú\×ØÛÛ™›Ü›H—KˆœÙ\ÜÚ[Û—ÙÜÜÚY\—ØÛÛ\]HŽˆÙ\ÜÚ[Û—ÙÜÜÚY\—ØÛÛ\]KˆJB‚ˆ™]\›ˆ™[™\—Ý[\]Jˆ˜YZ[—ÜÙ\ÜÚ[Ûœ×Ø\˜Ú]™Yš[‹ˆÙ\ÜÚ[ÛœÏ[Ý]ÜÙ\ÜÚ[ÛœËˆ›Ü›X][Û—Ý\\ÏWÜ\™\—Ø[ÝÙYÙ›Ü›X][Û—Ý\\Ê
Kˆ
B‚ˆÈOOOOOOOOOOOOOOOOOOOOOOOOBˆÈ‘SSÑHSTÓ’TUQBˆÈOOOOOOOOOOOOOOOOOOOOOOOOB‚™YˆÛ™WÛZ\ÜÚ[™×Ù]Z[×Ý^
ˆXÝÜÝ‹[žWK˜Z[š[™×Ý\NˆÝŠHOˆÝŽ‚ˆÈØÜÈ™\]Z\È[YÛ°ê\Âˆ[œÝ\™WÙØÝ[Y[×ÜØÚ[XWÙ›Ü—Ý˜Z[™YJ˜Z[š[™×Ý\JB‚ˆÈØÝ[Y[È[˜ÛÛ\]ÈHÝ]ÙH]ZH‰Ù\Ý\ÈÓÓ‘“Ô“QH
]H\›Z\ÈÚHLÔ
È›×Ü\›Z\ÊBˆØÜ×Û[™\ÈH×BˆH
˜Z[š[™×Ý\HÜˆˆŠKœÝš\

K\\Š
Bˆ›×Ü\›Z\ÈH›ÛÛ
™Ù]
››×Ü\›Z\ÈŠJB‚ˆ›Üˆ[ˆ
™Ù]
™ØÝ[Y[ÈŠHÜˆ×JN‚ˆÙ^HH
™Ù]
šÙ^HŠHÜˆˆŠKœÝš\

BˆX™[H
™Ù]
›X™[ŠHÜˆ‘ØÝ[Y[ŠKœÝš\

BˆÝH
™Ù]
œÝ]\ÈŠHÜˆˆŠKœÝš\

K\\Š
B‚ˆÈ\›Z\ÈÜ[Û›™[ÚH›×Ü\›Z\ÂˆYˆOHLÔˆ[™Ù^HOHœ\›Z\Èˆ[™›×Ü\›Z\Î‚ˆÛÛ[YB‚ˆYˆÝOHÓÓ‘“Ô“QHŽ‚ˆYˆ›ÝÝ‚ˆÝH““Óˆ0âTÔðâH‚ˆØÜ×Û[™\Ë˜\[™
ˆ‹HÛX™[HˆÜÝHŠB‚ˆØÜ×ÝH—ˆ‹š›Ú[ŠØÜ×Û[™\ÊHYˆØÜ×Û[™\È[ÙH‹H]XÝ[ˆ
Ù[ÛˆÝ]]ÈXÝY[ÊH‚‚ˆ[™›Ü×ÝH[™›Ü×ÛZ\ÜÚ[™×Ý^
˜Z[š[™×Ý\JHÜˆ‹H]XÝ[™H‚‚ˆ™]\›ˆ
ˆ¼'äáØÝ[Y[È[˜ÛÛ\]È—ˆ‚ˆˆžÙØÜ×ÝW—ˆ‚ˆ¼'éïˆ[™›Ü›X][ÛœÈ0èÛÛ\0ê]\ˆ—ˆ‚ˆˆžÚ[™›Ü×ÝWˆ‚ˆ
B‚‚™YˆÙš[™ÜÙ\ÜÚ[Û—Ø[™Ý˜Z[™YJ]NˆXÝÜÝ‹[žWKÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆ™]\›ˆ›Û™K›Û™Bˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆH™^

›Üˆ[ˆ˜Z[™Y\ÈYˆ™Ù]
šYŠHOH˜Z[™YWÚY
K›Û™JBˆ™]\›ˆË‚‚\œÜÝ
‹Ø\KÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹ÜÛ™K\™[[˜ÙKÜÙ[™ŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WÜÛ™WÜ™[[˜ÙWÜÙ[™
Ù\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆYZ[—ØÛÛ[Y[H
^[ØY™Ù]
˜ÛÛ[Y[ŠHÜˆˆŠKœÝš\

B‚ˆ]HHØYÙ]J
BˆËHÙš[™ÜÙ\ÜÚ[Û—Ø[™Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››ÝÙ›Ý[™ŸJK‚ˆ˜Z[š[™×Ý\HHÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠBˆœÙ]Y˜][
œÛ™WÙ›ÛÝÝ\È‹×JB‚ˆÈ0ê]Z[È[˜ÛÛ\]ÂˆZ\ÜÚ[™×Ù]Z[ÈHÛ™WÛZ\ÜÚ[™×Ù]Z[×Ý^
˜Z[š[™×Ý\JB‚ˆÈÚÙ[ˆ[š\]YHÝ\ˆ\ÈXÝ[ÛœÈÙXÜ°ê]Z\™Bˆ›ÛÝÝ\ÝÚÙ[ˆH]ZY]ZY

Kš^ˆ›ÛÝÝ\ÚYH”‹Hˆ
È›ÛÝÝ\ÝÚÙ[–ÎŒLK\\Š
B‚ˆÈ[œ™YÚ\Ý™HH[X[™Bˆ[žHHÂˆšYŽˆ›ÛÝÝ\ÚYˆÚÙ[ˆŽˆ›ÛÝÝ\ÝÚÙ[‹ˆ\HŽˆ‘SPS‘H‘SSÑH‹ˆ˜]ŽˆÛ›Ý×Ú\ÛÊ
Kˆ™]Z[ÈŽˆZ\ÜÚ[™×Ù]Z[Ëˆ˜ÛÛ[Y[ŽˆYZ[—ØÛÛ[Y[ˆœÝ]\ÈŽˆ”S‘S‘È‹ˆBˆÈœÛ™WÙ›ÛÝÝ\È—Kš[œÙ\
[žJB‚ˆÈ[™›ÜÈXZ[ˆš\œÝÛ˜[YHH
™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

Bˆ\ÝÛ˜[YHH
™Ù]
›\ÝÛ˜[YHŠHÜˆˆŠKœÝš\

Bˆ[XZ[H
™Ù]
™[XZ[ŠHÜˆˆŠKœÝš\

BˆÛ™HH
™Ù]
œÛ™HŠHÜˆˆŠKœÝš\

B‚ˆ›Ü›X][Û—Ý\HH›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠJBˆÝ\Hœ—Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠJBˆ[™Hœ—Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÙ[™‹ˆŠJB‚ˆÈY[œÈXÝ[ÛœÈÙXÜ°ê]Z\™H
YÙH]ZHÝ]œ™H[™H[Ù[JBˆ˜\ÙHHP“P×ÐTÑWÕT“œœÝš\
‹ÈŠBˆXÝ[Û—Ý\›HˆžØ˜\Ù_KÜÛ™KY›ÛÝÝ\ÞÙ›ÛÝÝ\ÝÚÙ[ŸH‚‚ˆ\›ØØ[YHXÝ[Û—Ý\›
ÈØXÝ[ÛXØ[Y‚ˆ\›Û›Ø[œÝÙ\ˆHXÝ[Û—Ý\›
ÈØXÝ[Û[›×Ø[œÝÙ\ˆ‚‚ˆÝXš™XÝHˆ¼'äçˆ™[[˜ÙH0ê[0ê\Ûš\]YH8 $ÈÜÜÚY\ˆ[˜ÛÛ\]8 $ÈÙš\œÝÛ˜[Y_HÛ\ÝÛ˜[Y_H‹œÝš\

B‚ˆ[HXZ[Û^[Ý]
ˆˆˆ‚ˆˆÝ[OH^X[YÛŽ˜Ù[\ˆ¼'äçˆ™[[˜ÙH0ê[0ê\Ûš\]YH8 $ÈÜÜÚY\ˆ[˜ÛÛ\]Ú‚‚ˆ]ˆÝ[OH˜˜XÚÙÜ›Ý[™ˆÙŒÙŽØ›Ü™\ŽŒ\ÛÛYÙMYMÙXŽØ›Ü™\‹\˜Y]\ÎŒLœÜY[™ÎŒMÛX\™Ú[ŽŒM‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï”ÝYÚXZ\™HÜÝ›Û™ÏˆÙš\œÝÛ˜[Y_HÛ\ÝÛ˜[Y_OÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï‘›Ü›X][ÛˆÜÝ›Û™ÏˆÙ›Ü›X][Û—Ý\_OÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï‘]\ÈÜÝ›Û™ÏˆÙÝ\H8¡¤ˆÙ[™OÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï•0ê[0ê\Û™HÜÝ›Û™ÏˆÜÛ™HÜˆ¸ %ŸOÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï‘[XZ[ÜÝ›Û™ÏˆÙ[XZ[Üˆ¸ %ŸOÜ‚ˆÙ]‚‚ˆÝ[OH›X\™Ú[ŽŒLœÝ›Û™Ï°â[0ê[Y[È[˜ÛÛ\]ÈÜÝ›Û™ÏÜ‚ˆ™HÝ[OHÚ]K\ÜXÙNœ™K]Ü˜\Ø˜XÚÙÜ›Ý[™ˆÙ™™ŽØ›Ü™\ŽŒ\ÛÛYÙMYMÙXŽÜY[™ÎŒLœØ›Ü™\‹\˜Y]\ÎŒLœÛX\™Ú[ŽŒžÛZ\ÜÚ[™×Ù]Z[ßOÜ™O‚‚ˆÈÝ[OIÛX\™Ú[‹]ÜŒLœ	ÏÝ›Û™ÏÛÛ[Y[Z\™HYZ[ˆÜÝ›Û™Ïœˆˆ
ÈYZ[—ØÛÛ[Y[
ÈÜˆˆYˆYZ[—ØÛÛ[Y[[ÙHˆŸB‚ˆ]ˆÝ[OH^X[YÛŽ˜Ù[\ŽÛX\™Ú[‹]ÜŒNÙ\Ü^N™›^ÙØ\ŒLÚ\ÝYžKXÛÛ[˜Ù[\ŽÙ›^]Ü˜\Ü˜\È‚ˆH™YHžÝ\›ØØ[YH‚ˆÝ[OH™\Ü^Nš[›[™KX›ØÚÎØ˜XÚÙÜ›Ý[™ˆÌM˜LÍNØÛÛÜŽÚ]NÜY[™ÎŒLœMœØ›Ü™\‹\˜Y]\ÎŒLÝ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚŽ‚ˆ8§!H¸ &XZH\[0êHH\œÛÛ›™BˆØO‚‚ˆH™YHžÝ\›Û›Ø[œÝÙ\ŸH‚ˆÝ[OH™\Ü^Nš[›[™KX›ØÚÎØ˜XÚÙÜ›Ý[™ˆÙÌŒŽØÛÛÜŽÚ]NÜY[™ÎŒLœMœØ›Ü™\‹\˜Y]\ÎŒLÝ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚŽ‚ˆ8§c™H¸ &XZH\ÈH›Ú[™™HH\œÛÛ›™BˆØO‚ˆÙ]‚‚ˆÛ\ÜÏHš[ˆÝ[OH›X\™Ú[‹]ÜŒMØÛÛÜŽˆÍ˜ÌŽÙ›Û\Ú^™NŒLÜÝ^X[YÛŽ˜Ù[\ˆ‚ˆÙ\È›Ý]ÛœÈÝ]œ™[[™HYÙH]™XÈ[™H[Ù[HÝ\ˆØZ\Ú\ˆHÛÛ[Y[Z\™K‚ˆÜ‚ˆˆˆŠB‚ˆÈ[›ÚH]HXZ[ÙXÜ°ê]Z\™BˆÚÈHœ™]›×ÜÙ[™Ù[XZ[
ˆž›˜]ÎÐÛXZ[˜ÛÛH‹ˆÝXš™XÝˆ[ˆØ×Ù[XZ[ÏVÈ˜Û[Y[[YÜ˜[XXØY[^K˜ÛÛH—Kˆ
B‚ˆYÛ›ÝYšXØ][ÛŠˆ]Kˆ››ÝYšXØ][Ûœ×ÜÛ™WÜ™[[˜Ù\È‹ˆˆžÙš\œÝÛ˜[Y_HÛ\ÝÛ˜[Y_H8 (ˆÙ›Ü›X][Û—Ý\_H‹ˆY]O^Âˆ™š\œÝÛ˜[YHŽˆš\œÝÛ˜[YKˆ›\ÝÛ˜[YHŽˆ\ÝÛ˜[YKˆ˜Z[š[™ÈŽˆ›Ü›X][Û—Ý\KˆœÛ™HŽˆÛ™Kˆ™[XZ[Žˆ[XZ[ˆœÙ\ÜÚ[Û—ÚYŽˆË™Ù]
šYŠKˆ˜Z[™YWÚYŽˆ™Ù]
šYŠKˆ™›ÛÝÝ\ÚYŽˆ›ÛÝÝ\ÚYˆ›Z\ÜÚ[™×Ù]Z[ÈŽˆZ\ÜÚ[™×Ù]Z[Ëˆ˜YZ[—ØÛÛ[Y[ŽˆYZ[—ØÛÛ[Y[ˆ˜Ø[ÜÝ]\ÈŽˆ°à\[\ˆ‹ˆ››×Ø[œÝÙ\—ØÛÝ[ŽˆˆKˆ
B‚ˆÈ\œÚ\Ý[˜ÙBˆÖÈ˜Z[™Y\È—HHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JB‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK™[XZ[ÛÚÈŽˆ›ÛÛ
ÚÊK™›ÛÝÝ\ÚYŽˆ›ÛÝÝ\ÚYJB‚‚\œÜÝ
‹Ø\KÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹Ý˜YK\™[[˜ÙKÏ™[[˜ÙWÚÙ^O‹ÜÙ[™ŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WÜÙ[™Ý˜YWÜ™[[˜ÙJÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝ‹™[[˜ÙWÚÙ^NˆÝŠN‚ˆ™[[˜ÙWÚÙ^HH
™[[˜ÙWÚÙ^HÜˆˆŠKœÝš\

BˆYˆ™[[˜ÙWÚÙ^H›Ý[ˆQWÔ‘SSÑWÐÓÓ‘’QÔÎ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆš[˜[YÜ™[[˜ÙWÚÙ^HŸJK‚ˆ]HHØYÙ]J
BˆËHÙš[™ÜÙ\ÜÚ[Û—Ø[™Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››ÝÙ›Ý[™ŸJKˆYˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y

N‚ˆ™]\›ˆØØ[˜Ù[YÜ™YÚ\Ý˜][Û—Ø]]ÛX][Û—Ü™\ÜÛœÙJ
B‚ˆ˜Z[š[™×Ý\HH
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠKœÝš\

K\\Š
BˆYˆ˜Z[š[™×Ý\HOH‘T’QÑPS•QHŽ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››ÝÝ˜YHŸJK‚ˆ[œÝ\™WÝ˜YWÜ™[[˜Ù\×ÜÝ]J
Bˆ™Yœ™\ÚÝ˜YWÜ™[[˜ÙWÜØÚY[J
Bˆ™[[˜ÙWÜÝ]HH
™Ù]
˜YWÜ™[[˜Ù\ÈŠHÜˆßJK™Ù]
™[[˜ÙWÚÙ^JHÜˆßBˆYˆ
™[[˜ÙWÜÝ]K™Ù]
œÙ[Ø]ŠHÜˆˆŠKœÝš\

N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ˜[™XYWÜÙ[ŸJKB‚ˆ™\Ý[HÜÙ[™Ý˜YWÜ™[[˜ÙWÛY\ÜØYÙJ]KË™[[˜ÙWÚÙ^K[ÙOH›X[X[ŠB‚ˆÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
BˆÖÈ˜Z[™Y\È—HHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JB‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK
Šœ™\Ý[˜YWÜ™[[˜Ù\ÈŽˆ™Ù]
˜YWÜ™[[˜Ù\È‹ßJ_JB‚‚\œÜÝ
‹Ø\KÜÙXÜ™]\šX]Û›ÝYšXØ][ÛœËÝ˜YWÜ™[[˜Ù\ËÏ›ÝYšXØ][Û—ÚY‹ØØ[\™\Ý[ŠB™Yˆ\WÜÙXÜ™]\šX]Ý˜YWÜ™[[˜ÙWÜ™\Ý[
›ÝYšXØ][Û—ÚYˆÝŠN‚ˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆÝ]ÛÛYHH
^[ØY™Ù]
›Ý]ÛÛYHŠHÜˆˆŠKœÝš\

K\\Š
BˆÛÛ[Y[H
^[ØY™Ù]
˜ÛÛ[Y[ŠHÜˆˆŠKœÝš\

BˆØ[YÜ™\ÛÛ][ÛˆH
^[ØY™Ù]
˜Ø[YÜ™\ÛÛ][ÛˆŠHÜˆˆŠKœÝš\

BˆYˆÝ]ÛÛYH›Ý[ˆ
ÐSQ‹““×ÐS”ÕÑTˆŠN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆš[˜[YÛÝ]ÛÛYHŸJKˆYˆÝ]ÛÛYHOHÐSQˆ[™›ÝÛÛ[Y[‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ˜ÛÛ[Y[Ü™\]Z\™YŸJK‚ˆ]HHØYÙ]J
Bˆ›ÝYšXØ][ÛˆH™^
ˆ
][H›Üˆ][H[ˆ]K™Ù]
››ÝYšXØ][Ûœ×Ý˜YWÜ™[[˜Ù\È‹×JHYˆ][K™Ù]
šYŠHOH›ÝYšXØ][Û—ÚY
Kˆ›Û™Kˆ
BˆYˆ›Ý›ÝYšXØ][ÛŽ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››ÝYšXØ][Û—Û›ÝÙ›Ý[™ŸJK‚ˆ›ÝYšXØ][Û—ÛY]HH›ÝYšXØ][Û‹œÙ]Y˜][
›Y]H‹ßJBˆ™]š[Ý\×Û›×Ø[œÝÙ\ˆHÜ\œÙWÛ›×Ø[œÝÙ\—ØÛÝ[
›ÝYšXØ][Û—ÛY]K™Ù]
››×Ø[œÝÙ\—ØÛÝ[ŠJBˆYˆÝ]ÛÛYHOH““×ÐS”ÕÑTˆŽ‚ˆ›×Ø[œÝÙ\—ØÛÝ[HZ[ŠË™]š[Ý\×Û›×Ø[œÝÙ\ˆ
ÈJBˆ\Ü^HHÂˆNˆŒY\ˆ\[\ÈH°ê\ÛœÙH‹ˆŽˆŒ°êYH\[\ÈH°ê\ÛœÙH‹ˆÎˆŒðêYH\[\ÈH°ê\ÛœÙH‹ˆVÛ›×Ø[œÝÙ\—ØÛÝ[Bˆ›ÝYšXØ][Û–È™Û™H—HH›×Ø[œÝÙ\—ØÛÝ[HÂˆ›ÝYšXØ][Û–È™Û™WØ]—HHÛ›Ý×Ú\ÛÊ
HYˆ›ÝYšXØ][Û‹™Ù]
™Û™HŠH[ÙHˆ‚ˆ[ÙN‚ˆ›×Ø[œÝÙ\—ØÛÝ[Hˆ\Ü^HH”\œÛÛ›™H›Ú[H‚ˆ›ÝYšXØ][Û–È™Û™H—HHYBˆ›ÝYšXØ][Û–È™Û™WØ]—HHÛ›Ý×Ú\ÛÊ
B‚ˆ›ÝYšXØ][Û—ÛY]VÈ˜Ø[ÜÝ]\È—HH\Ü^Bˆ›ÝYšXØ][Û—ÛY]VÈ››×Ø[œÝÙ\—ØÛÝ[—HH›×Ø[œÝÙ\—ØÛÝ[ˆYˆÛÛ[Y[‚ˆ›ÝYšXØ][Û—ÛY]VÈ›\ÝØÛÛ[Y[—HHÛÛ[Y[‚ˆ˜Z[™YWÙ\Ü^WÛ˜[YHHÙ›Ü›X]Ý˜Z[™YWÛ˜[YJˆ›ÝYšXØ][Û—ÛY]K™Ù]
™š\œÝÛ˜[YH‹ˆŠKˆ›ÝYšXØ][Û—ÛY]K™Ù]
›\ÝÛ˜[YH‹ˆŠKˆ
Bˆ™[[˜ÙWÛX™[H
›ÝYšXØ][Û—ÛY]K™Ù]
œ™[[˜ÙWÛX™[ŠHÜˆ”™[[˜ÙHQHŠKœÝš\

BˆØ[ÚXÛÛˆH¼'çèˆˆYˆÝ]ÛÛYHOHÐSQˆ[ÙH
ÌNˆ¼'çèH‹Žˆ¼'çè‹Îˆ¼'å-ŸK™Ù]
›×Ø[œÝÙ\—ØÛÝ[¼'çèHŠJBˆØ[ÛX™[H
ˆˆžØØ[ÚXÛÛŸ^Ü™[[˜ÙWÛX™[HÝ˜Z[™YWÙ\Ü^WÛ˜[Y_HH\œÛÛ›™H\[0êYH‚ˆYˆÝ]ÛÛYHOHÐSQ‚ˆ[ÙHˆžØØ[ÚXÛÛŸ^Ü™[[˜ÙWÛX™[HÝ˜Z[™YWÙ\Ü^WÛ˜[Y_HHÙ\Ü^_H‚ˆ
BˆYØYZ[—Û›ÝYšXØ][ÛŠˆ]KˆØ[ÛX™[ˆY]O^Âˆ\HŽˆ˜YWÜ™[[˜ÙWØØ[Ü™\Ý[‹ˆ›Ý]ÛÛYHŽˆÝ]ÛÛYKˆ››×Ø[œÝÙ\—ØÛÝ[Žˆ›×Ø[œÝÙ\—ØÛÝ[ˆœÙ\ÜÚ[Û—ÚYŽˆ›ÝYšXØ][Û—ÛY]K™Ù]
œÙ\ÜÚ[Û—ÚYŠKˆ˜Z[™YWÚYŽˆ›ÝYšXØ][Û—ÛY]K™Ù]
˜Z[™YWÚYŠKˆ˜ÛÛ[Y[ŽˆÛÛ[Y[ˆ˜Ø[ÜÝ]\ÈŽˆ\Ü^Kˆœ™[[˜ÙWÚÙ^HŽˆ›ÝYšXØ][Û—ÛY]K™Ù]
œ™[[˜ÙWÚÙ^HŠKˆKˆ
B‚ˆØ]™WÙ]J]JBˆ™Yœ™\ÚYÜ^[ØYHÜÙXÜ™]\šX]Û›ÝYšXØ][Ûœ×Ü^[ØY
]JBˆ™]\›ˆœÛÛšYžJÂˆ›ÚÈŽˆYKˆ™Û™HŽˆ›ÛÛ
›ÝYšXØ][Û‹™Ù]
™Û™HŠJKˆ˜Ø[ÜÝ]\ÈŽˆ\Ü^Kˆ››×Ø[œÝÙ\—ØÛÝ[Žˆ›×Ø[œÝÙ\—ØÛÝ[ˆ
Šœ™Yœ™\ÚYÜ^[ØYˆJB‚‚ˆÈOOOOOOOOOOOOOOOOOOOOOOOOBˆÈ‘SU‘SQS•‘R‘UBˆÈOOOOOOOOOOOOOOOOOOOOOOOOB‚™YˆØ\[™ØYZ[—ØÛÛ[Y[Ù›YÊÝ\œ™[ˆÝ‹›Y×Ý^ˆÝŠHOˆÝŽ‚ˆÝ\œ™[H
Ý\œ™[ÜˆˆŠKœÝš\

BˆYˆ›ÝÝ\œ™[‚ˆ™]\›ˆ›Y×Ý^ˆYˆ›Y×Ý^[ˆÝ\œ™[‚ˆ™]\›ˆÝ\œ™[ˆ™]\›ˆÝ\œ™[
È—ˆˆ
È›Y×Ý^‚™YˆÜ™[[Ý™WØYZ[—ØÛÛ[Y[Ù›YÊÝ\œ™[ˆÝ‹›Y×Ý^ˆÝŠHOˆÝŽ‚ˆÝ\œ™[H
Ý\œ™[ÜˆˆŠKœÝš\

BˆYˆ›ÝÝ\œ™[‚ˆ™]\›ˆˆ‚ˆÙ\HÛ[™H›Üˆ[™H[ˆÝ\œ™[œÜ][™\Ê
HYˆ[™KœÝš\

HOH›Y×Ý^Bˆ™]\›ˆ—ˆ‹š›Ú[ŠÙ\
KœÝš\

B‚™YˆØØ\ÚÜ^[Y[Ù›Y×Ý^
ˆ˜]×Ø[[Ý[ˆ[žKˆ\×ÜÙ]Yˆ[žHH˜[ÙKˆÙ]YÙ]Nˆ[žHHˆ‹ˆÙ]YØÛÛ[Y[ˆ[žHHˆ‹ŠHOˆÝŽ‚ˆžN‚ˆ[[Ý[H›Ø]
ÝŠ˜]×Ø[[Ý[ÜˆˆŠKœ™\XÙJ‹‹‹ˆŠKœÝš\

JBˆ^Ù\
\Q\œ›Ü‹˜[YQ\œ›ÜŠN‚ˆ[[Ý[HŒˆYˆ[[Ý[H‚ˆ™]\›ˆˆ‚ˆ™]HHˆžØ[[Ý[‹Œ™ŸH‹œœÝš\
ŒŠKœœÝš\
‹ˆŠBˆYˆ\×ÜÙ]Y‚ˆ]WÝ^H
ÝŠÙ]YÙ]HÜˆˆŠKœÝš\

JBˆÛÛ[Y[Ý^H
ÝŠÙ]YØÛÛ[Y[ÜˆˆŠKœÝš\

JBˆÝY™š^Hˆ‚ˆYˆ]WÝ^‚ˆÝY™š^
ÏHˆˆHÙ]WÝ^H‚ˆYˆÛÛ[Y[Ý^‚ˆÝY™š^
ÏHˆˆ
ØÛÛ[Y[Ý^JH‚ˆ™]\›ˆˆžÜ™]_H]\›ÜÈ°êYÛ0ê\È[ˆ\Ü0êÙ\ÞÜÝY™š^Kˆ‚ˆ™]\›ˆˆžÜ™]_H]\›ÜÈ0è°êYÛ\ˆ[ˆ\Ü0êÙ\Ëˆ‚‚™YˆÜÞ[˜×ØØ\ÚÜ^[Y[ØÛÛ[Y[Ù›YÜÊ˜Z[™YNˆXÝ
HOˆ›Û™N‚ˆØ\ÚÙ›Y×ÛX\šÙ\œÈH
ˆ™]\›ÜÈ›Û0ê™H°êYÛ0ê\È[ˆ\Ü0êÙ\Ëˆ‹ˆ™]\›ÜÈ0è°êYÛ\ˆ[ˆ\Ü0êÙ\Ëˆ‹ˆ™]\›ÜÈ°êYÛ0ê\È[ˆ\Ü0êÙ\È‹ˆ
Bˆ›ÜˆÙ^H[ˆ
™š[˜[˜Ù[Y[ØÛÛ[Y[‹˜ÛÛ[Y[ŠN‚ˆÝ\œ™[Ý˜[YHH
˜Z[™YK™Ù]
Ù^JHÜˆˆŠKœÝš\

BˆÙ\Û[™\ÈHÂˆ[™H›Üˆ[™H[ˆÝ\œ™[Ý˜[YKœÜ][™\Ê
BˆYˆ›Ý[žJX\šÙ\ˆ[ˆ[™H›ÜˆX\šÙ\ˆ[ˆØ\ÚÙ›Y×ÛX\šÙ\œÊBˆBˆ˜Z[™YVÚÙ^WHH—ˆ‹š›Ú[ŠÙ\Û[™\ÊKœÝš\

B‚ˆ\×ØØ\ÚÜ^[Y[H›ÛÛ
˜Z[™YK™Ù]
˜Ø\ÚÜ^[Y[Ù[˜X›YŠJBˆØ\ÚÙ›YÈHØØ\ÚÜ^[Y[Ù›Y×Ý^
ˆ˜Z[™YK™Ù]
˜Ø\ÚÜ^[Y[Ø[[Ý[ŠKˆ˜Z[™YK™Ù]
˜Ø\ÚÜ^[Y[ÜÙ]YŠKˆ˜Z[™YK™Ù]
˜Ø\ÚÜ^[Y[ÜÙ]YÙ]HŠKˆ˜Z[™YK™Ù]
˜Ø\ÚÜ^[Y[ÜÙ]YØÛÛ[Y[ŠKˆ
BˆYˆ\×ØØ\ÚÜ^[Y[[™Ø\ÚÙ›YÎ‚ˆ˜Z[™YVÈ™š[˜[˜Ù[Y[ØÛÛ[Y[—HHØ\[™ØYZ[—ØÛÛ[Y[Ù›YÊ˜Z[™YK™Ù]
™š[˜[˜Ù[Y[ØÛÛ[Y[‹ˆŠKØ\ÚÙ›YÊBˆ˜Z[™YVÈ˜ÛÛ[Y[—HHØ\[™ØYZ[—ØÛÛ[Y[Ù›YÊ˜Z[™YK™Ù]
˜ÛÛ[Y[‹ˆŠKØ\ÚÙ›YÊB‚™YˆÜÙ[™Ü™[]™[Y[Ü[™[™×Ý˜[Y][Û—ÛY\ÜØYÙ\Ê˜Z[™YNˆXÝÙ\ÜÚ[ÛŽˆXÝ
HOˆ\VØ›ÛÛ›ÛÛN‚ˆš\œÝÛ˜[YHH
˜Z[™YK™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

Bˆ\ÝÛ˜[YHH
˜Z[™YK™Ù]
›\ÝÛ˜[YHŠHÜˆˆŠKœÝš\

Bˆ[XZ[H
˜Z[™YK™Ù]
™[XZ[ŠHÜˆˆŠKœÝš\

BˆÛ™HH
˜Z[™YK™Ù]
œÛ™HŠHÜˆˆŠKœÝš\

Bˆ˜Z[š[™×Û˜[YHH›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û‹˜Z[š[™×Ý\H‹ˆŠHÜˆÙ\ÜÚ[Û‹™Ù]
›˜[YHŠHÜˆ™›Ü›X][ÛˆŠB‚ˆÝXš™XÝH”°ê[0ê™[Y[[ˆ][HH˜[Y][ÛˆHX[™]‚ˆ[HXZ[Û^[Ý]
ˆˆˆ‚ˆ›Ûš›Ý\‹Ü‚‚ˆ’™HYH\›Y]ÈH™]™[š\ˆ™\œÈ›Ý\ÈÛÛ˜Ù\›˜[›Ý™H›Ü›X][ÛˆÝ›Û™ÏžÝ˜Z[š[™×Û˜[Y_OÜÝ›Û™Ï‹Ü‚‚ˆHÙH›Ý\‹›Ý\È‰Ø]™^ˆ\È[˜ÛÜ™H˜[Y0êHHX[™]H°ê[0ê™[Y[]YH›Ý\È›Ý\È]›ÛœÈ[›ÞpêK‚ˆ›Ý\ÈÙ\˜Z]Z[ÜÜÚX›HÝœH˜[Y\ˆHX[™]H°ê[0ê™[Y[Yš[ˆ]YH›Ý\ÈZ\ÜÚ[ÛœÈ˜[Y\ˆ›Ý™H[œØÜš\[ÛˆÂˆÚH›Ý\È‰Ø]™^ˆ\È™péÝHHY[ˆ
\Z\È›Ý™H˜[œ]YHSÓ•ÊHÝHÚH›Ý\È™[˜ÛÛ™^ˆ\ÈY™šXÝ[0ê\Ëˆ›Ý\ÈÝ]™^ˆ›Ý\ÈÛÛXÝ\ˆ]HŒˆÈÈŽÜ‚‚ˆ’™H›Ý\È™[Y\˜ÚYH\ˆ]˜[˜ÙKœÛ0ê[Y[RSS•Ü‚ˆˆˆŠBˆ[XZ[ÛÚÈHœ™]›×ÜÙ[™Ù[XZ[
[XZ[ÝXš™XÝ[˜Z[™YO]˜Z[™YJHYˆ[XZ[[ÙH˜[ÙB‚ˆÛ\ÈH
ˆ›Ûš›Ý\‹‚ˆˆ’™HYH\›Y]ÈH™]™[š\ˆ™\œÈ›Ý\ÈÛÛ˜Ù\›˜[›Ý™H›Ü›X][ÛˆÝ˜Z[š[™×Û˜[Y_Kˆ‚ˆHÙH›Ý\‹›Ý\È‰Ø]™^ˆ\È[˜ÛÜ™H˜[Y0êHHX[™]H°ê[0ê™[Y[]YH›Ý\È›Ý\È]›ÛœÈ[›ÞpêKˆ‚ˆ•›Ý\ÈÙ\˜Z]Z[ÜÜÚX›HÝœH˜[Y\ˆHX[™]H°ê[0ê™[Y[Yš[ˆ]YH›Ý\ÈZ\ÜÚ[ÛœÈ˜[Y\ˆ›Ý™H[œØÜš\[ÛˆÈ‚ˆ”ÚH›Ý\È‰Ø]™^ˆ\È™péÝHHY[ˆ
\Z\È›Ý™H˜[œ]YHSÓ•ÊHÝHÚH›Ý\È™[˜ÛÛ™^ˆ\ÈY™šXÝ[0ê\Ë‚ˆ›Ý\ÈÝ]™^ˆ›Ý\ÈÛÛXÝ\ˆ]HŒˆÈÈŽˆ‚ˆ’™H›Ý\È™[Y\˜ÚYH\ˆ]˜[˜ÙKÛ0ê[Y[RSS•‚ˆ
KœÝš\

BˆÛ\×ÛÚÈHœ™]›×ÜÙ[™ÜÛ\ÊÛ™KÛ\ÊHYˆÛ™H[ÙH˜[ÙB‚ˆ™]\›ˆ›ÛÛ
[XZ[ÛÚÊK›ÛÛ
Û\×ÛÚÊB‚‚™YˆÜÙ[™Ü™[]™[Y[Û™]×Ù]WÙ[XZ[
ˆ˜Z[™YNˆXÝˆÙ\ÜÚ[ÛŽˆXÝˆ™Z™XÝYÜ™\]Y\ÝˆXÝˆ™]×Ù]NˆÝ‹ˆÛÛ[Y[ˆÝˆHˆ‹ŠHOˆ›Û™N‚ˆš\œÝÛ˜[YHH
˜Z[™YK™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

Bˆ\ÝÛ˜[YHH
˜Z[™YK™Ù]
›\ÝÛ˜[YHŠHÜˆˆŠKœÝš\

Bˆ›Ü›X][Û—Ý\HH›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û‹˜Z[š[™×Ý\H‹ˆŠJB‚ˆ[[Ý[H™Z™XÝYÜ™\]Y\Ý™Ù]
˜[[Ý[‹ˆŠBˆØÚY[YÙ]HHœ—Ù]J™Z™XÝYÜ™\]Y\Ý™Ù]
œØÚY[YÙ]H‹ˆŠJBˆ™]×Ù]WÙœˆHœ—Ù]J™]×Ù]JHÜˆ™]×Ù]B‚ˆÝXš™XÝHˆ¼'äêH›Ý]™X]H°ê[0ê™[Y[›ÜÜðêH8 $ÈÙš\œÝÛ˜[Y_HÛ\ÝÛ˜[Y_H‹œÝš\

Bˆ[HXZ[Û^[Ý]
ˆˆˆ‚ˆˆÝ[OH^X[YÛŽ˜Ù[\ˆ¼'äêH›Ý]™X]H°ê[0ê™[Y[›ÜÜðêOÚ‚‚ˆ]ˆÝ[OH˜˜XÚÙÜ›Ý[™ˆÙŒÙŽØ›Ü™\ŽŒ\ÛÛYÙMYMÙXŽØ›Ü™\‹\˜Y]\ÎŒLœÜY[™ÎŒMÛX\™Ú[ŽŒM‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï”ÝYÚXZ\™HÜÝ›Û™ÏˆÙš\œÝÛ˜[Y_HÛ\ÝÛ˜[Y_OÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï‘›Ü›X][ÛˆÜÝ›Û™ÏˆÙ›Ü›X][Û—Ý\_OÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï“[Û[ÜÝ›Û™ÏˆØ[[Ý[OÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï‘]H[š]X[HÜÝ›Û™ÏˆÜØÚY[YÙ]_OÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï“›Ý]™[H]H›ÜÜðêYHÜÝ›Û™ÏˆÛ™]×Ù]WÙœŸOÜ‚ˆÙ]‚‚ˆÈÝ›Û™ÏÛÛ[Y[Z\™HÜÝ›Û™Ïœˆˆ
ÈÛÛ[Y[
ÈÜˆˆYˆÛÛ[Y[[ÙHˆŸBˆˆˆŠB‚ˆœ™]›×ÜÙ[™Ù[XZ[
˜Û[Y[[YÜ˜[XXØY[^K˜ÛÛH‹ÝXš™XÝ[
B‚‚\œÜÝ
‹Ø\KÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹Ùš[˜[˜Ù[Y[\™Z™]ÜÙ[™ŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WÙš[˜[˜Ù[Y[Ü™Z™]ÜÙ[™
Ù\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆ[[Ý[H
^[ØY™Ù]
˜[[Ý[ŠHÜˆˆŠKœÝš\

BˆØÚY[YÙ]HH
^[ØY™Ù]
œØÚY[YÙ]HŠHÜˆˆŠKœÝš\

B‚ˆYˆ›Ý[[Ý[Üˆ›ÝØÚY[YÙ]N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›Z\ÜÚ[™×ÙšY[ÈŸJK‚ˆ]HHØYÙ]J
BˆËHÙš[™ÜÙ\ÜÚ[Û—Ø[™Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››ÝÙ›Ý[™ŸJKˆYˆ›ÝÙš[˜[˜Ú[™×Ü\™\—Û[Ù[WÙ[˜X›Y

N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›[Ù[WÛØÚÙY‹›[Ù[HŽˆ™š[˜[˜Ú[™ÈŸJKÂ‚ˆÚÙ[ˆH]ZY]ZY

Kš^ˆÙXÜ™]\šX]ÝÚÙ[ˆH]ZY]ZY

Kš^ˆ[žWÚYH”VKHˆ
ÈÚÙ[–ÎŒLK\\Š
B‚ˆœÙ]Y˜][
™š[˜[˜Ù[Y[Ü™Z™XÝYÜ™\]Y\ÝÈ‹×JBˆÈ™š[˜[˜Ù[Y[Ü™Z™XÝYÜ™\]Y\ÝÈ—Kš[œÙ\
ÂˆšYŽˆ[žWÚYˆÚÙ[ˆŽˆÚÙ[‹ˆœÙXÜ™]\šX]ÝÚÙ[ˆŽˆÙXÜ™]\šX]ÝÚÙ[‹ˆ˜[[Ý[Žˆ[[Ý[ˆœØÚY[YÙ]HŽˆØÚY[YÙ]Kˆ˜]ŽˆÛ›Ý×Ú\ÛÊ
KˆœÝ]\ÈŽˆ”S‘S‘È‹ˆJB‚ˆÈ™š[˜[˜Ù[Y[ÜÝ]\È—HHš[—Ü™]šY]È‚ˆÈ™š[˜[˜Ù[Y[Ü™Z™XÝYÛ›ÝH—HH¸¦¨;î#È°ê[0ê™[Y[™Z™]0êH‚ˆÈ˜ÛÛ[Y[—HHØ\[™ØYZ[—ØÛÛ[Y[Ù›YÊ™Ù]
˜ÛÛ[Y[‹ˆŠK¸¦¨;î#È°ê[0ê™[Y[™Z™]0êHŠB‚ˆš\œÝÛ˜[YHH
™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

Bˆ\ÝÛ˜[YHH
™Ù]
›\ÝÛ˜[YHŠHÜˆˆŠKœÝš\

Bˆ[XZ[H
™Ù]
™[XZ[ŠHÜˆˆŠKœÝš\

BˆÛ™HH
™Ù]
œÛ™HŠHÜˆˆŠKœÝš\

Bˆ›Ü›X][Û—Ý\HH›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠJBˆ˜Z[š[™×Û˜[YHH›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠHÜˆË™Ù]
›˜[YHŠHÜˆ™›Ü›X][ÛˆŠBˆØÚY[YÙœˆHœ—Ù]JØÚY[YÙ]JHÜˆØÚY[YÙ]B‚ˆ˜\ÙHHP“P×ÐTÑWÕT“œœÝš\
‹ÈŠBˆ™\WÝ\›HˆžØ˜\Ù_KÜ™[]™[Y[\™Z™]KÞÝÚÙ[ŸH‚ˆÙXÜ™]\šX]Ý\›HˆžØ˜\Ù_KÜ™[]™[Y[\™Z™]K\ÙXÜ™]Z\™KÞÜÙXÜ™]\šX]ÝÚÙ[ŸH‚‚ˆÝXš™XÝH¸¦¨;î#È°ê[0ê™[Y[™Z™]0êH8 $ÈXÝ[Ûˆ™\]Z\ÙH‚ˆ[HXZ[Û^[Ý]
ˆˆˆ‚ˆ›Ûš›Ý\ˆÙš\œÝÛ˜[Y_HÛ\ÝÛ˜[Y_KÜ‚‚ˆ’™HYH\›Y]ÈH™]™[š\ˆ™\œÈ›Ý\ÈÛÛ˜Ù\›˜[›Ý™H›Ü›X][Û‚ˆÝ›Û™ÏžÙ›Ü›X][Û—Ý\_OÜÝ›Û™Ï‹Ü‚‚ˆ“›Ý\È]›ÛœÈHÛÛœÝ]\ˆ]YH›Ý™H°ê[0ê™[Y[	Ý[ˆ[Û[BˆÝ›Û™ÏžØ[[Ý[OÜÝ›Û™Ïˆ]\›ÜÈ[š]X[[Y[°ê]HHÝ›Û™ÏžÜØÚY[YÙœŸOÜÝ›Û™ÏˆH0ê]0êH™Z™]0êKÜ‚‚ˆ”Ý\œšY^‹]›Ý\ÈÝœ›Ý\È[™\]Y\ˆ0è]Y[H]H›Ý\ÈÝ]›ÛœÈ°ê]›Ú\ˆ[ˆ›Ý]™X]H°ê[0ê™[Y[ˆ[ˆÛ\]X[XÚHÏÜ‚‚ˆÝ[OH^X[YÛŽ˜Ù[\ŽÛX\™Ú[ŽŒN‚ˆH™YHžÜ™\WÝ\›H‚ˆÝ[OH™\Ü^Nš[›[™KX›ØÚÎØ˜XÚÙÜ›Ý[™ˆÌMŒÙXŽØÛÛÜŽˆÙ™™ŽÜY[™ÎŒLœMœØ›Ü™\‹\˜Y]\ÎŒLÝ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚŽ‚ˆ[™\]Y\ˆ[™H›Ý]™[H]BˆØO‚ˆÜ‚‚ˆ‘[ˆØ\ÈHY™šXÝ[0êH›Ý\ÈÝ]™^ˆ›Ý\ÈÛÛXÝ\ˆ]HŒˆÈÈŽÜ‚‚ˆ’™H›Ý\È™[Y\˜ÚYH\ˆ]˜[˜ÙKÜ‚‚ˆÛ0ê[Y[RSS•œ‘\™XÝ]\ˆ[0êYÜ˜[HXØY[^OÜ‚ˆˆˆŠB‚ˆ[XZ[ÛÚÈHœ™]›×ÜÙ[™Ù[XZ[
[XZ[ÝXš™XÝ[˜Z[™YO]
HYˆ[XZ[[ÙH˜[ÙB‚ˆÝ\Hœ—Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠJBˆ[™Hœ—Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÙ[™‹ˆŠJBˆ^[WÙ]HHœ—Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ë™^[WÙ]H‹ˆŠJBˆ›Ü›X][Û—Ù]\ÈH‘HÝ›Û™ÏžßOÜÝ›Û™Ïˆ]HÝ›Û™ÏžßOÜÝ›Û™Ïˆ‹™›Ü›X]
Ý\[™
HYˆÝ\[™[™[ÙH‘]\È0èÛÛ™š\›Y\ˆ‚‚ˆÙXÜ™]\šX]ÜÝXš™XÝHˆ¸¦¨;î#È°ê[0ê™[Y[™Z™]0êH8 $È˜\[0è°ê]›Ú\ˆ
Ùš\œÝÛ˜[Y_HÛ\ÝÛ˜[Y_JH‹œÝš\

BˆÙXÜ™]\šX]Ú[HXZ[Û^[Ý]
ˆˆˆ‚ˆˆÝ[OH^X[YÛŽ˜Ù[\ˆ¸¦¨;î#È°ê[0ê™[Y[™Z™]0êOÚ‚ˆ“Y\˜ÚHH˜\[\ˆHÝYÚXZ\™HÝ\ˆÛÛ™[š\ˆ8 &][™H›Ý]™[H]HH°ê[0ê™[Y[Ü‚‚ˆ]ˆÝ[OH˜˜XÚÙÜ›Ý[™ˆÙŒÙŽØ›Ü™\ŽŒ\ÛÛYÙMYMÙXŽØ›Ü™\‹\˜Y]\ÎŒLœÜY[™ÎŒMÛX\™Ú[ŽŒM‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï”ÝYÚXZ\™HÜÝ›Û™ÏˆÙš\œÝÛ˜[Y_HÛ\ÝÛ˜[Y_OÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï•0ê[0ê\Û™HÜÝ›Û™ÏˆÜÛ™HÜˆ¸ %ŸOÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï‘[XZ[ÜÝ›Û™ÏˆÙ[XZ[Üˆ¸ %ŸOÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï‘›Ü›X][ÛˆÜÝ›Û™ÏˆÝ˜Z[š[™×Û˜[Y_OÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï‘]\ÈH›Ü›X][ÛˆÜÝ›Û™ÏˆÙ›Ü›X][Û—Ù]\ßOÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï‘]H8 &Y^[Y[ˆÜÝ›Û™ÏˆÙ^[WÙ]HÜˆ¸ %ŸOÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï“[Û[ÜÝ›Û™ÏˆØ[[Ý[OÜ‚ˆÝ[OH›X\™Ú[ŽŒÝ›Û™Ï‘]H[š]X[HÜÝ›Û™ÏˆÜØÚY[YÙœŸOÜ‚ˆÙ]‚‚ˆÝ[OH^X[YÛŽ˜Ù[\ŽÛX\™Ú[ŽŒN‚ˆH™YHžÜÙXÜ™]\šX]Ý\›H‚ˆÝ[OH™\Ü^Nš[›[™KX›ØÚÎØ˜XÚÙÜ›Ý[™ˆÌMŒÙXŽØÛÛÜŽˆÙ™™ŽÜY[™ÎŒLœMœØ›Ü™\‹\˜Y]\ÎŒLÝ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚŽ‚ˆ›ÜÜÙ\ˆ[™H›Ý]™[H]BˆØO‚ˆÜ‚ˆˆˆŠBˆœ™]›×ÜÙ[™Ù[XZ[
ž›˜]ÎÐÛXZ[˜ÛÛH‹ÙXÜ™]\šX]ÜÝXš™XÝÙXÜ™]\šX]Ú[
B‚ˆÛ\×Û˜[YHHš\œÝÛ˜[YKœÝš\

BˆÛ\×Ü™Yš^Hˆ›Ûš›Ý\ˆÜÛ\×Û˜[Y_KˆYˆÛ\×Û˜[YH[ÙH›Ûš›Ý\‹‚ˆÛ\ÈH
ˆˆžÜÛ\×Ü™Yš^R™H™]šY[œÈ™\œÈ›Ý\ÈÛÛ˜Ù\›˜[›Ý™H›Ü›X][ÛˆÝ˜Z[š[™×Û˜[Y_Kˆ‚ˆˆ•›Ý™H°ê[0ê™[Y[	Ý[ˆ[Û[HØ[[Ý[H]\›ÜÈ°ê]HHÜØÚY[YÙœŸHH0ê]0êH™Z™]0êKˆ‚ˆ“›Ý\È›Ý\È™[Y\˜Ú[ÛœÈHšY[ˆ›Ý[Ú\ˆ›Ý\È[™\]Y\ˆ[™H›Ý]™[H]HH°ê[0ê™[Y[‚ˆˆ™[ˆÛ\]X[XÚHˆÜ™\WÝ\›H‚ˆ‘[ˆØ\ÈHY™šXÝ[0ê\Ë›Ý\ÈÝ]™^ˆ›Ý\ÈÛÛXÝ\ˆ]HŒˆÈÈŽˆ‚ˆ’™H›Ý\È™[Y\˜ÚYH\ˆ]˜[˜ÙK‚ˆÛ0ê[Y[RSS•H[0êYÜ˜[HXØY[^H‚ˆ
KœÝš\

BˆÛ\×ÛÚÈHœ™]›×ÜÙ[™ÜÛ\ÊÛ™KÛ\ÊHYˆÛ™H[ÙH˜[ÙB‚ˆYÛ›ÝYšXØ][ÛŠˆ]Kˆ››ÝYšXØ][Ûœ×Ü™[]™[Y[È‹ˆˆžÙš\œÝÛ˜[Y_HÛ\ÝÛ˜[Y_H8 (ˆÝ˜Z[š[™×Û˜[Y_H8 (ˆØ[[Ý[H8 (ˆÜØÚY[YÙœŸH‹ˆY]O^Âˆ™š\œÝÛ˜[YHŽˆš\œÝÛ˜[YKˆ›\ÝÛ˜[YHŽˆ\ÝÛ˜[YKˆ˜Z[š[™ÈŽˆ˜Z[š[™×Û˜[YKˆ˜[[Ý[Žˆ[[Ý[ˆœØÚY[YÙ]HŽˆØÚY[YÙ]KˆœÙ\ÜÚ[Û—ÚYŽˆË™Ù]
šYŠKˆ˜Z[™YWÚYŽˆ™Ù]
šYŠKˆ™[žWÚYŽˆ[žWÚYˆœÙXÜ™]\šX]ÝÚÙ[ˆŽˆÙXÜ™]\šX]ÝÚÙ[‹ˆKˆ
BˆœÙ]Y˜][
™š[˜[˜Ù[Y[Ü[™[™×Û›ÝYšXØ][Û—ÜÙ[Ø]‹ˆŠB‚ˆÖÈ˜Z[™Y\È—HHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JB‚ˆ™]\›ˆœÛÛšYžJÂˆ›ÚÈŽˆYKˆ™[XZ[ÛÚÈŽˆ›ÛÛ
[XZ[ÛÚÊKˆœÛ\×ÛÚÈŽˆ›ÛÛ
Û\×ÛÚÊKˆœ™\WÝ\›Žˆ™\WÝ\›ˆ››ÝHŽˆ™Ù]
™š[˜[˜Ù[Y[Ü™Z™XÝYÛ›ÝHŠKˆ˜ÛÛ[Y[Žˆ™Ù]
˜ÛÛ[Y[‹ˆŠKˆJB‚‚\œÜÝ
‹Ø\KÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹Ùš[˜[˜Ù[Y[Y[‹X][KÜÙ[™ŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WÙš[˜[˜Ù[Y[Ü[™[™×ÜÙ[™
Ù\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆËHÙš[™ÜÙ\ÜÚ[Û—Ø[™Ý˜Z[™YJ]KÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
BˆYˆ›ÝÈÜˆ›Ý‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››ÝÙ›Ý[™ŸJKˆYˆ›ÝÙš[˜[˜Ú[™×Ü\™\—Û[Ù[WÙ[˜X›Y

N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›[Ù[WÛØÚÙY‹›[Ù[HŽˆ™š[˜[˜Ú[™ÈŸJKÂ‚ˆ[™XYWÜÙ[Ø]H
™Ù]
™š[˜[˜Ù[Y[Ü[™[™×Û›ÝYšXØ][Û—ÜÙ[Ø]ŠHÜˆˆŠKœÝš\

BˆYˆ[™XYWÜÙ[Ø]‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ˜[™XYWÜÙ[‹œÙ[Ø]Žˆ[™XYWÜÙ[Ø]JK‚ˆ[XZ[ÛÚËÛ\×ÛÚÈHÜÙ[™Ü™[]™[Y[Ü[™[™×Ý˜[Y][Û—ÛY\ÜØYÙ\ÊÊB‚ˆÙ[Ø]HÛ›Ý×Ú\ÛÊ
BˆÈ™š[˜[˜Ù[Y[Ü[™[™×Û›ÝYšXØ][Û—ÜÙ[Ø]—HHÙ[Ø]‚ˆš\œÝÛ˜[YHH
™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

Bˆ\ÝÛ˜[YHH
™Ù]
›\ÝÛ˜[YHŠHÜˆˆŠKœÝš\

Bˆ˜Z[š[™×Û˜[YHH›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠHÜˆË™Ù]
›˜[YHŠHÜˆ™›Ü›X][ÛˆŠB‚ˆYÛ›ÝYšXØ][ÛŠˆ]Kˆ››ÝYšXØ][Ûœ×Ü™[]™[Y[Û›Û—Ý˜[Y\È‹ˆˆžÙš\œÝÛ˜[Y_HÛ\ÝÛ˜[Y_H8 (ˆÝ˜Z[š[™×Û˜[Y_H‹ˆY]O^Âˆ™š\œÝÛ˜[YHŽˆš\œÝÛ˜[YKˆ›\ÝÛ˜[YHŽˆ\ÝÛ˜[YKˆ˜Z[š[™ÈŽˆ˜Z[š[™×Û˜[YKˆœÙ\ÜÚ[Û—ÚYŽˆË™Ù]
šYŠKˆ˜Z[™YWÚYŽˆ™Ù]
šYŠKˆœÙ[Ø]ŽˆÙ[Ø]ˆKˆ
B‚ˆÖÈ˜Z[™Y\È—HHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JB‚ˆ™]\›ˆœÛÛšYžJÂˆ›ÚÈŽˆYKˆ™[XZ[ÛÚÈŽˆ›ÛÛ
[XZ[ÛÚÊKˆœÛ\×ÛÚÈŽˆ›ÛÛ
Û\×ÛÚÊKˆœÙ[Ø]ŽˆÙ[Ø]ˆœÙ[Ø]ÙœˆŽˆœ—Ù]JÙ[Ø]ÎŒLJHYˆÙ[Ø][ÙHˆ‹ˆJB‚‚\™Ù]
‹Ü™[]™[Y[\™Z™]KÏÚÙ[ˆŠB™Yˆ™[]™[Y[Ü™Z™]WÜYÙJÚÙ[ŽˆÝŠN‚ˆ]HHØYÙ]J
Bˆ›Ý[™H›Û™Bˆ›Ý[™Ý˜Z[™YHH›Û™Bˆ›Ý[™ÜÙ\ÜÚ[ÛˆH›Û™B‚ˆ›ÜˆÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JHÜˆ×N‚ˆ›Üˆ[ˆ
Ë™Ù]
˜Z[™Y\ÈŠHÜˆ×JN‚ˆ›Üˆ][ˆ
™Ù]
™š[˜[˜Ù[Y[Ü™Z™XÝYÜ™\]Y\ÝÈŠHÜˆ×JN‚ˆYˆ
]™Ù]
ÚÙ[ˆŠHÜˆˆŠKœÝš\

HOHÚÙ[Ž‚ˆ›Ý[™H]ˆ›Ý[™Ý˜Z[™YHHˆ›Ý[™ÜÙ\ÜÚ[ÛˆHÂˆœ™XZÂˆYˆ›Ý[™‚ˆœ™XZÂˆYˆ›Ý[™‚ˆœ™XZÂ‚ˆYˆ›Ý›Ý[™‚ˆ™]\›ˆÏ“Y[ˆ[˜[YHÝH^\°êKÚÏˆ‹‚ˆ™]×Ù]HH›Ý[™™Ù]
›™]×Ù]HŠB‚ˆ™]\›ˆ™[™\—Ý[\]Jˆœ™[]™[Y[Ü™Z™]Kš[‹ˆÚÙ[]ÚÙ[‹ˆ˜Z[™YOY›Ý[™Ý˜Z[™YKˆÙ\ÜÚ[ÛY›Ý[™ÜÙ\ÜÚ[Û‹ˆ›Ü›X][Û—ÛX™[Y›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
›Ý[™ÜÙ\ÜÚ[Û‹˜Z[š[™×Ý\H‹ˆŠJKˆ[[Ý[Y›Ý[™™Ù]
˜[[Ý[‹ˆŠKˆØÚY[YÙ]OYœ—Ù]J›Ý[™™Ù]
œØÚY[YÙ]H‹ˆŠJKˆ™Y—ÚYY›Ý[™™Ù]
šY‹ˆŠKˆ™]×Ù]O[™]×Ù]Kˆ
B‚‚\™Ù]
‹Ü™[]™[Y[\™Z™]K\ÙXÜ™]Z\™KÏÚÙ[ˆŠB™Yˆ™[]™[Y[Ü™Z™]WÜÙXÜ™]Z\™WÜYÙJÚÙ[ŽˆÝŠN‚ˆ]HHØYÙ]J
Bˆ›Ý[™H›Û™Bˆ›Ý[™Ý˜Z[™YHH›Û™Bˆ›Ý[™ÜÙ\ÜÚ[ÛˆH›Û™B‚ˆ›ÜˆÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JHÜˆ×N‚ˆ›Üˆ[ˆ
Ë™Ù]
˜Z[™Y\ÈŠHÜˆ×JN‚ˆ›Üˆ][ˆ
™Ù]
™š[˜[˜Ù[Y[Ü™Z™XÝYÜ™\]Y\ÝÈŠHÜˆ×JN‚ˆYˆ
]™Ù]
œÙXÜ™]\šX]ÝÚÙ[ˆŠHÜˆˆŠKœÝš\

HOHÚÙ[Ž‚ˆ›Ý[™H]ˆ›Ý[™Ý˜Z[™YHHˆ›Ý[™ÜÙ\ÜÚ[ÛˆHÂˆœ™XZÂˆYˆ›Ý[™‚ˆœ™XZÂˆYˆ›Ý[™‚ˆœ™XZÂ‚ˆYˆ›Ý›Ý[™‚ˆ™]\›ˆÏ“Y[ˆ[˜[YHÝH^\°êKÚÏˆ‹‚ˆ™]×Ù]HH›Ý[™™Ù]
›™]×Ù]HŠBˆ™]×Ù]WÙœˆHœ—Ù]J™]×Ù]JHYˆ™]×Ù]H[ÙHˆ‚‚ˆ™]\›ˆ™[™\—Ý[\]Jˆœ™[]™[Y[Ü™Z™]WÜÙXÜ™]Z\™Kš[‹ˆÚÙ[]ÚÙ[‹ˆ˜Z[™YOY›Ý[™Ý˜Z[™YKˆÙ\ÜÚ[ÛY›Ý[™ÜÙ\ÜÚ[Û‹ˆ›Ü›X][Û—ÛX™[Y›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
›Ý[™ÜÙ\ÜÚ[Û‹˜Z[š[™×Ý\H‹ˆŠJKˆ[[Ý[Y›Ý[™™Ù]
˜[[Ý[‹ˆŠKˆØÚY[YÙ]OYœ—Ù]J›Ý[™™Ù]
œØÚY[YÙ]H‹ˆŠJKˆ™Y—ÚYY›Ý[™™Ù]
šY‹ˆŠKˆ™]×Ù]O[™]×Ù]WÙœˆÜˆ™]×Ù]HÜˆˆ‹ˆ
B‚‚\œÜÝ
‹Ü™[]™[Y[\™Z™]K\ÙXÜ™]Z\™KÏÚÙ[‹Ü™\HŠB™Yˆ™[]™[Y[Ü™Z™]WÜÙXÜ™]Z\™WÜ™\JÚÙ[ŽˆÝŠN‚ˆ™]×Ù]HH
™\]Y\Ý™›Ü›K™Ù]
›™]×Ù]HŠHÜˆˆŠKœÝš\

B‚ˆ]HHØYÙ]J
Bˆ›Ý[™H›Û™Bˆ›Ý[™Ý˜Z[™YHH›Û™Bˆ›Ý[™ÜÙ\ÜÚ[ÛˆH›Û™B‚ˆ›ÜˆÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JHÜˆ×N‚ˆ›Üˆ[ˆ
Ë™Ù]
˜Z[™Y\ÈŠHÜˆ×JN‚ˆ›Üˆ][ˆ
™Ù]
™š[˜[˜Ù[Y[Ü™Z™XÝYÜ™\]Y\ÝÈŠHÜˆ×JN‚ˆYˆ
]™Ù]
œÙXÜ™]\šX]ÝÚÙ[ˆŠHÜˆˆŠKœÝš\

HOHÚÙ[Ž‚ˆ›Ý[™H]ˆ›Ý[™Ý˜Z[™YHHˆ›Ý[™ÜÙ\ÜÚ[ÛˆHÂˆœ™XZÂˆYˆ›Ý[™‚ˆœ™XZÂˆYˆ›Ý[™‚ˆœ™XZÂ‚ˆYˆ›Ý›Ý[™‚ˆ™]\›ˆÏ“Y[ˆ[˜[YHÝH^\°êKÚÏˆ‹‚ˆYˆ›Ý[™™Ù]
›™]×Ù]HŠN‚ˆ™]\›ˆ™[™\—Ý[\]Jˆœ™[]™[Y[Ü™Z™]WÜÙXÜ™]Z\™Kš[‹ˆÚÙ[]ÚÙ[‹ˆ˜Z[™YOY›Ý[™Ý˜Z[™YKˆÙ\ÜÚ[ÛY›Ý[™ÜÙ\ÜÚ[Û‹ˆ›Ü›X][Û—ÛX™[Y›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
›Ý[™ÜÙ\ÜÚ[Û‹˜Z[š[™×Ý\H‹ˆŠJKˆ[[Ý[Y›Ý[™™Ù]
˜[[Ý[‹ˆŠKˆØÚY[YÙ]OYœ—Ù]J›Ý[™™Ù]
œØÚY[YÙ]H‹ˆŠJKˆ™Y—ÚYY›Ý[™™Ù]
šY‹ˆŠKˆ™]×Ù]OYœ—Ù]J›Ý[™™Ù]
›™]×Ù]HŠJHÜˆ›Ý[™™Ù]
›™]×Ù]HŠKˆ
B‚ˆYˆ›Ý™]×Ù]N‚ˆ™]\›ˆÏ•™]Z[^ˆ[™\]Y\ˆ[™H]KÚÏˆ‹‚ˆ›Ý[™ÈœÝ]\È—HH‘Ó‘H‚ˆ›Ý[™Èœ™\ÜÛ™YØ]—HHÛ›Ý×Ú\ÛÊ
Bˆ›Ý[™È›™]×Ù]H—HH™]×Ù]Bˆ›Ý[™È›™]×Ù]WÜÛÝ\˜ÙH—HH”ÑPÔ‘UT’PU‚‚ˆÜÙ[™Ü™[]™[Y[Û™]×Ù]WÙ[XZ[
›Ý[™Ý˜Z[™YK›Ý[™ÜÙ\ÜÚ[Û‹›Ý[™™]×Ù]JB‚ˆ˜Z[™YWÙ\Ü^WÛ˜[YHHÙ›Ü›X]Ý˜Z[™YWÛ˜[YJ›Ý[™Ý˜Z[™YK™Ù]
™š\œÝÛ˜[YH‹ˆŠK›Ý[™Ý˜Z[™YK™Ù]
›\ÝÛ˜[YH‹ˆŠJBˆYØYZ[—Û›ÝYšXØ][ÛŠˆ]Kˆˆ¼'çèžÝ˜Z[™YWÙ\Ü^WÛ˜[Y_HH›Ý]™X]H°ê[0ê™[Y[›ÜÜðêHHÙœ—Ù]J™]×Ù]JHÜˆ™]×Ù]_H‹ˆY]O^Âˆ\HŽˆœ™[]™[Y[Û™]×Ù]H‹ˆœÛÝ\˜ÙHŽˆœÙXÜ™]\šX]ÜX›X×ÜYÙH‹ˆœÙ\ÜÚ[Û—ÚYŽˆ›Ý[™ÜÙ\ÜÚ[Û‹™Ù]
šYŠKˆ˜Z[™YWÚYŽˆ›Ý[™Ý˜Z[™YK™Ù]
šYŠKˆ™[žWÚYŽˆ›Ý[™™Ù]
šYŠKˆ˜ÛÛ[Y[Žˆ
›Ý[™™Ù]
˜ÛÛ[Y[ŠHÜˆˆŠKœÝš\

KˆKˆ
B‚ˆ›Ý[™ÜÙ\ÜÚ[Û–È˜Z[™Y\È—HHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
›Ý[™ÜÙ\ÜÚ[ÛŠBˆ›Ý[™ÜÙ\ÜÚ[Û‹œÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JB‚ˆ™]\›ˆˆˆ‚ˆ]ˆÝ[OH™›ÛY˜[Z[N\šX[Ø[œË\Ù\šYŽÛX^]ÚYLŒÛX\™Ú[ŽŒ]]ÎÜY[™ÎŒNØ›Ü™\ŽŒ\ÛÛYÙMYMÙXŽØ›Ü™\‹\˜Y]\ÎŒM‚ˆˆÝ[OH›X\™Ú[ŽŒL¸§!HY\˜ÚHOÚ‚ˆÝ[OH›X\™Ú[ŽŒØÛÛÜŽˆÌÍÍMLH“H›Ý]™[H]HHšY[ˆ0ê]0êH[œ™YÚ\Ý°êYKÜ‚ˆÙ]‚ˆˆˆ‚‚‚\œÜÝ
‹Ü™[]™[Y[\™Z™]KÏÚÙ[‹Ü™\HŠB™Yˆ™[]™[Y[Ü™Z™]WÜ™\JÚÙ[ŽˆÝŠN‚ˆ™]×Ù]HH
™\]Y\Ý™›Ü›K™Ù]
›™]×Ù]HŠHÜˆˆŠKœÝš\

BˆÛÛ[Y[H
™\]Y\Ý™›Ü›K™Ù]
˜ÛÛ[Y[ŠHÜˆˆŠKœÝš\

B‚ˆ]HHØYÙ]J
Bˆ›Ý[™H›Û™Bˆ›Ý[™Ý˜Z[™YHH›Û™Bˆ›Ý[™ÜÙ\ÜÚ[ÛˆH›Û™B‚ˆ›ÜˆÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JHÜˆ×N‚ˆ›Üˆ[ˆ
Ë™Ù]
˜Z[™Y\ÈŠHÜˆ×JN‚ˆ›Üˆ][ˆ
™Ù]
™š[˜[˜Ù[Y[Ü™Z™XÝYÜ™\]Y\ÝÈŠHÜˆ×JN‚ˆYˆ
]™Ù]
ÚÙ[ˆŠHÜˆˆŠKœÝš\

HOHÚÙ[Ž‚ˆ›Ý[™H]ˆ›Ý[™Ý˜Z[™YHHˆ›Ý[™ÜÙ\ÜÚ[ÛˆHÂˆœ™XZÂˆYˆ›Ý[™‚ˆœ™XZÂˆYˆ›Ý[™‚ˆœ™XZÂ‚ˆYˆ›Ý›Ý[™‚ˆ™]\›ˆÏ“Y[ˆ[˜[YHÝH^\°êKÚÏˆ‹‚ˆYˆ›Ý[™™Ù]
›™]×Ù]HŠN‚ˆ™]\›ˆ™[™\—Ý[\]Jˆœ™[]™[Y[Ü™Z™]Kš[‹ˆÚÙ[]ÚÙ[‹ˆ˜Z[™YOY›Ý[™Ý˜Z[™YKˆÙ\ÜÚ[ÛY›Ý[™ÜÙ\ÜÚ[Û‹ˆ›Ü›X][Û—ÛX™[Y›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
›Ý[™ÜÙ\ÜÚ[Û‹˜Z[š[™×Ý\H‹ˆŠJKˆ[[Ý[Y›Ý[™™Ù]
˜[[Ý[‹ˆŠKˆØÚY[YÙ]OYœ—Ù]J›Ý[™™Ù]
œØÚY[YÙ]H‹ˆŠJKˆ™Y—ÚYY›Ý[™™Ù]
šY‹ˆŠKˆ™]×Ù]OY›Ý[™™Ù]
›™]×Ù]HŠKˆ
B‚ˆ›Ý[™ÈœÝ]\È—HH‘Ó‘H‚ˆ›Ý[™Èœ™\ÜÛ™YØ]—HHÛ›Ý×Ú\ÛÊ
Bˆ›Ý[™È›™]×Ù]H—HH™]×Ù]Bˆ›Ý[™È˜ÛÛ[Y[—HHÛÛ[Y[ˆ›Ý[™È›™]×Ù]WÜÛÝ\˜ÙH—HH•RS‘QH‚‚ˆÜÙ[™Ü™[]™[Y[Û™]×Ù]WÙ[XZ[
›Ý[™Ý˜Z[™YK›Ý[™ÜÙ\ÜÚ[Û‹›Ý[™™]×Ù]KÛÛ[Y[
B‚ˆ˜Z[™YWÙ\Ü^WÛ˜[YHHÙ›Ü›X]Ý˜Z[™YWÛ˜[YJ›Ý[™Ý˜Z[™YK™Ù]
™š\œÝÛ˜[YH‹ˆŠK›Ý[™Ý˜Z[™YK™Ù]
›\ÝÛ˜[YH‹ˆŠJBˆYØYZ[—Û›ÝYšXØ][ÛŠˆ]Kˆˆ¼'çèžÝ˜Z[™YWÙ\Ü^WÛ˜[Y_HH›Ý]™X]H°ê[0ê™[Y[›ÜÜðêHHÙœ—Ù]J™]×Ù]JHÜˆ™]×Ù]_H‹ˆY]O^Âˆ\HŽˆœ™[]™[Y[Û™]×Ù]H‹ˆœÛÝ\˜ÙHŽˆ˜Z[™YWÜX›X×ÜYÙH‹ˆœÙ\ÜÚ[Û—ÚYŽˆ›Ý[™ÜÙ\ÜÚ[Û‹™Ù]
šYŠKˆ˜Z[™YWÚYŽˆ›Ý[™Ý˜Z[™YK™Ù]
šYŠKˆ™[žWÚYŽˆ›Ý[™™Ù]
šYŠKˆ˜ÛÛ[Y[ŽˆÛÛ[Y[ˆKˆ
B‚ˆ›Ý[™ÜÙ\ÜÚ[Û–È˜Z[™Y\È—HHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
›Ý[™ÜÙ\ÜÚ[ÛŠBˆ›Ý[™ÜÙ\ÜÚ[Û‹œÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JB‚ˆ™]\›ˆˆˆ‚ˆ]ˆÝ[OH™›ÛY˜[Z[N\šX[Ø[œË\Ù\šYŽÛX^]ÚYLŒÛX\™Ú[ŽŒ]]ÎÜY[™ÎŒNØ›Ü™\ŽŒ\ÛÛYÙMYMÙXŽØ›Ü™\‹\˜Y]\ÎŒM‚ˆˆÝ[OH›X\™Ú[ŽŒL¸§!HY\˜ÚHOÚ‚ˆÝ[OH›X\™Ú[ŽŒØÛÛÜŽˆÌÍÍMLH•›Ý™H°ê\ÛœÙHHšY[ˆ0ê]0êH˜[œÛZ\ÙKˆ›Ý\È™]™[›ÛœÈ™\œÈ›Ý\È˜\Y[Y[Ü‚ˆÙ]‚ˆˆˆ‚‚‚\™Ù]
‹ÜÛ™KY›ÛÝÝ\ÏÚÙ[ˆŠB™YˆÛ™WÙ›ÛÝÝ\ÜYÙJÚÙ[ŽˆÝŠN‚ˆÈYÙHX›\]YH˜XÝ[ÛˆÙXÜ°ê]Z\™Hˆ
Ø[œÈÙÚ[ŠK˜\ðêYHÝ\ˆ[ˆÚÙ[ˆ[š\]YBˆXÝ[ÛˆH
™\]Y\Ý˜\™ÜË™Ù]
˜XÝ[ÛˆŠHÜˆˆŠKœÝš\

HÈØ[YÈ›×Ø[œÝÙ\‚‚ˆ]HHØYÙ]J
Bˆ›Ý[™H›Û™Bˆ›Ý[™ÜÙ\ÜÚ[Û—ÚYH›Û™Bˆ›Ý[™Ý˜Z[™YWÚYH›Û™B‚ˆ›ÜˆÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JHÜˆ×N‚ˆ›Üˆ[ˆ
Ë™Ù]
˜Z[™Y\ÈŠHÜˆ×JN‚ˆ›Üˆ][ˆ
™Ù]
œÛ™WÙ›ÛÝÝ\ÈŠHÜˆ×JN‚ˆYˆ
]™Ù]
ÚÙ[ˆŠHÜˆˆŠKœÝš\

HOHÚÙ[Ž‚ˆ›Ý[™H]ˆ›Ý[™ÜÙ\ÜÚ[Û—ÚYHË™Ù]
šYŠBˆ›Ý[™Ý˜Z[™YWÚYH™Ù]
šYŠBˆœ™XZÂˆYˆ›Ý[™‚ˆœ™XZÂˆYˆ›Ý[™‚ˆœ™XZÂ‚ˆYˆ›Ý›Ý[™‚ˆ™]\›ˆÏ“Y[ˆ[˜[YHÝH^\°êKÚÏˆ‹‚ˆÈ]]HYÙH]ZHÝ]œ™H]]ÛX]\]Y[Y[[™H[Ù[H
ÛÛ[YH[X[™0êJBˆÈ][›ÚYHHÛÛ[Y[Z\™HšXHÔÕˆ™]\›ˆ™[™\—Ý[\]JˆœÛ™WÙ›ÛÝÝ\š[‹ˆÚÙ[]ÚÙ[‹ˆXÝ[ÛXXÝ[Û‹ˆ™Y—ÚYY›Ý[™™Ù]
šY‹ˆŠKŠB‚‚\œÜÝ
‹ÜÛ™KY›ÛÝÝ\ÏÚÙ[‹Ü™\HŠB™YˆÛ™WÙ›ÛÝÝ\Ü™\JÚÙ[ŽˆÝŠN‚ˆÝ]ÛÛYHH
™\]Y\Ý™›Ü›K™Ù]
›Ý]ÛÛYHŠHÜˆˆŠKœÝš\

K\\Š
BˆÛÛ[Y[H
™\]Y\Ý™›Ü›K™Ù]
˜ÛÛ[Y[ŠHÜˆˆŠKœÝš\

B‚ˆYˆÝ]ÛÛYH›Ý[ˆ
ÐSQ‹““×ÐS”ÕÑTˆŠN‚ˆ™]\›ˆÏXÝ[Ûˆ[˜[YKÚÏˆ‹‚ˆ]HHØYÙ]J
B‚ˆ×Ù›Ý[™H›Û™BˆÙ›Ý[™H›Û™Bˆ[žWÙ›Ý[™H›Û™B‚ˆ›ÜˆÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JHÜˆ×N‚ˆ›Üˆ[ˆ
Ë™Ù]
˜Z[™Y\ÈŠHÜˆ×JN‚ˆ›Üˆ][ˆ
™Ù]
œÛ™WÙ›ÛÝÝ\ÈŠHÜˆ×JN‚ˆYˆ
]™Ù]
ÚÙ[ˆŠHÜˆˆŠKœÝš\

HOHÚÙ[Ž‚ˆ×Ù›Ý[™HÂˆÙ›Ý[™Hˆ[žWÙ›Ý[™H]ˆœ™XZÂˆYˆ[žWÙ›Ý[™‚ˆœ™XZÂˆYˆ[žWÙ›Ý[™‚ˆœ™XZÂ‚ˆYˆ›Ý[žWÙ›Ý[™‚ˆ™]\›ˆÏ“Y[ˆ[˜[YHÝH^\°êKÚÏˆ‹‚ˆÈÛˆ[œ™YÚ\Ý™HH°ê\ÛœÙHÛÛ[YH[ˆ›Ý]™[0ê]°ê[™[Y[
\ÝÜš\]YJBˆÙ›Ý[™œÙ]Y˜][
œÛ™WÙ›ÛÝÝ\È‹×JBˆÙ›Ý[™ÈœÛ™WÙ›ÛÝÝ\È—Kš[œÙ\
ÂˆšYŽˆ”‹T‘THˆ
È]ZY]ZY

Kš^ÎŽK\\Š
Kˆ\HŽˆ”°âTÓ”ÑHÑPÔ°âURT‘H‹ˆ˜]ŽˆÛ›Ý×Ú\ÛÊ
Kˆ™]Z[ÈŽˆ
¸§!H\[0êHˆYˆÝ]ÛÛYHOHÐSQˆ[ÙH¸§c\ÈH›Ú[™™HŠKˆ˜ÛÛ[Y[ŽˆÛÛ[Y[ˆœ™YˆŽˆ[žWÙ›Ý[™™Ù]
šY‹ˆŠKˆJB‚ˆÈX\œ]YHH[X[™HÛÛ[YH˜Z]0êYH
Ü[Û›™[
Bˆ[žWÙ›Ý[™ÈœÝ]\È—HH‘Ó‘H‚ˆ[žWÙ›Ý[™È™Û™WØ]—HHÛ›Ý×Ú\ÛÊ
Bˆ[žWÙ›Ý[™È™Û™WÛÝ]ÛÛYH—HHÝ]ÛÛYB‚ˆ˜Z[™YWÙ\Ü^WÛ˜[YHHÙ›Ü›X]Ý˜Z[™YWÛ˜[YJÙ›Ý[™™Ù]
™š\œÝÛ˜[YH‹ˆŠKÙ›Ý[™™Ù]
›\ÝÛ˜[YH‹ˆŠJBˆYˆÝ]ÛÛYHOHÐSQŽ‚ˆYØYZ[—Û›ÝYšXØ][ÛŠˆ]Kˆˆ¼'çè”™[[˜ÙH0ê[0ê\Ûš\]YHÝ˜Z[™YWÙ\Ü^WÛ˜[Y_HH0ê]0êH\[0êH‹ˆY]O^Âˆ\HŽˆœ™[[˜ÙWØØ[Ü™\Ý[‹ˆœÛÝ\˜ÙHŽˆœÛ™WÙ›ÛÝÝ\ÜX›X×ÜYÙH‹ˆ›Ý]ÛÛYHŽˆÝ]ÛÛYKˆœÙ\ÜÚ[Û—ÚYŽˆ×Ù›Ý[™™Ù]
šYŠKˆ˜Z[™YWÚYŽˆÙ›Ý[™™Ù]
šYŠKˆ˜ÛÛ[Y[ŽˆÛÛ[Y[ˆ˜Ø[ÜÝ]\ÈŽˆ”\œÛÛ›™H›Ú[H‹ˆKˆ
Bˆ[ÙN‚ˆÝ\œ™[Û›×Ø[œÝÙ\ˆHÜ\œÙWÛ›×Ø[œÝÙ\—ØÛÝ[
[žWÙ›Ý[™™Ù]
››×Ø[œÝÙ\—ØÛÝ[ŠJBˆ›×Ø[œÝÙ\—ØÛÝ[HZ[ŠËÝ\œ™[Û›×Ø[œÝÙ\ˆ
ÈJBˆ[žWÙ›Ý[™È››×Ø[œÝÙ\—ØÛÝ[—HH›×Ø[œÝÙ\—ØÛÝ[ˆ\Ü^HHÂˆNˆŒY\ˆ\[\ÈH°ê\ÛœÙH‹ˆŽˆŒ°êYH\[\ÈH°ê\ÛœÙH‹ˆÎˆŒðêYH\[\ÈH°ê\ÛœÙH‹ˆVÛ›×Ø[œÝÙ\—ØÛÝ[BˆXÛÛˆHÌNˆ	ü'çèIËŽˆ	ü'çè	ËÎˆ	ü'å-	ßVÛ›×Ø[œÝÙ\—ØÛÝ[BˆYØYZ[—Û›ÝYšXØ][ÛŠˆ]KˆˆžÚXÛÛŸT™[[˜ÙH0ê[0ê\Ûš\]YHÝ˜Z[™YWÙ\Ü^WÛ˜[Y_HÙ\Ü^_H‹ˆY]O^Âˆ\HŽˆœ™[[˜ÙWØØ[Ü™\Ý[‹ˆœÛÝ\˜ÙHŽˆœÛ™WÙ›ÛÝÝ\ÜX›X×ÜYÙH‹ˆ›Ý]ÛÛYHŽˆÝ]ÛÛYKˆ››×Ø[œÝÙ\—ØÛÝ[Žˆ›×Ø[œÝÙ\—ØÛÝ[ˆœÙ\ÜÚ[Û—ÚYŽˆ×Ù›Ý[™™Ù]
šYŠKˆ˜Z[™YWÚYŽˆÙ›Ý[™™Ù]
šYŠKˆ˜ÛÛ[Y[ŽˆÛÛ[Y[ˆ˜Ø[ÜÝ]\ÈŽˆ\Ü^KˆKˆ
B‚ˆÈ\œÚ\Ýˆ×Ù›Ý[™È˜Z[™Y\È—HHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
×Ù›Ý[™
Bˆ×Ù›Ý[™œÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JB‚ˆ™]\›ˆˆˆ‚ˆ]ˆÝ[OH™›ÛY˜[Z[N\šX[Ø[œË\Ù\šYŽÛX^]ÚYLŒÛX\™Ú[ŽŒ]]ÎÜY[™ÎŒNØ›Ü™\ŽŒ\ÛÛYÙMYMÙXŽØ›Ü™\‹\˜Y]\ÎŒM‚ˆˆÝ[OH›X\™Ú[ŽŒL¸§!H°ê\ÛœÙH[œ™YÚ\Ý°êYOÚ‚ˆÝ[OH›X\™Ú[ŽŒØÛÛÜŽˆÌÍÍMLH“Y\˜ÚKH™]Ý\ˆHšY[ˆ0ê]0êHZ›Ý]0êH0è8 &Z\ÝÜš\]YKÜ‚ˆÙ]‚ˆˆˆ‚‚ˆÈOOOOOOOOOOOOOOOOOOOOOOOOBˆÈSPTÈ°ê]›ØÛÛ\]Xš[]0êH
ÝYÚXZ\™\ÈOˆ˜Z[™Y\ÊBˆÈOOOOOOOOOOOOOOOOOOOOOOOOB‚\œÜÝ
‹Ø\KÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËØÜ™X]HŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØÜ™X]WÝ˜Z[™YWØ[X\ÊÙ\ÜÚ[Û—ÚYˆÝŠN‚ˆÈ™Y\šYÙH™\œÈHœ˜ZYH›Û˜Ý[Û‚ˆ™]\›ˆ\WØÜ™X]WÝ˜Z[™YJÙ\ÜÚ[Û—ÚY
B‚\œÜÝ
‹Ø\KÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹Ù[]HŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WÙ[]WÝ˜Z[™YWØ[X\ÊÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ™]\›ˆ\WÙ[]WÝ˜Z[™YJÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
B‚\œÜÝ
‹Ø\KÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹Ý˜Z[™Y\ËÏ˜Z[™YWÚY‹Ý\]HŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WÝ\]WÝ˜Z[™YWØ[X\ÊÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆÈÛˆ\]HXÝY[\Ý[ˆÜÝYÚXZ\™\ËË‹‹‹Ý\]Bˆ™]\›ˆ\WÝ\]WÝ˜Z[™YJÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
B‚š[\Ü™Bš[\Ü[šXÛÙY]Bš[\Ü™XY[™Â™œ›ÛH›\ÚÈ[\Ü™\]Y\ÝœÛÛšYžB‚™YˆÛ›Ü›WÛ˜[YJÎˆÝŠHOˆÝŽ‚ˆÈH
ÈÜˆˆŠKœÝš\

K›ÝÙ\Š
BˆÈH[šXÛÙY]K››Ü›X[^™J“‘‘‹ÊBˆÈHˆ‹š›Ú[ŠÚ›ÜˆÚ[ˆÈYˆ[šXÛÙY]K˜Ø]YÛÜžJÚ
HOH“[ˆŠHÈ[›0ê™HXØÙ[ÂˆÈH™KœÝXŠˆ–×˜K^ŒNWJÈ‹ˆ‹ÊBˆÈH™KœÝXŠˆ—ÊÈ‹ˆ‹ÊKœÝš\

Bˆ™]\›ˆÂ‚™YˆÛX]ÚÝ˜Z[™YWÙœ›ÛWÙš[[˜[YJ˜Z[™Y\Îˆ\Ýš[[˜[YNˆÝŠN‚ˆˆˆ‚ˆX]ÚÚH“ÓH]°âS“ÓH\\˜Z\ÜÙ[[œÈH›ÛHHšXÚY\ˆ
›Ü›X[\ðêJK‚ˆ™[›ÚYH
˜Z[™YK›Û™JHÚHÒËÚ[›Ûˆ
›Û™K™X\ÛÛŠK‚ˆˆˆ‚ˆ›ˆHÛ›Ü›WÛ˜[YJš[[˜[YJB‚ˆ]ÈH×Bˆ›Üˆ[ˆ˜Z[™Y\Î‚ˆˆHÛ›Ü›WÛ˜[YJ™Ù]
›\ÝÛ˜[YH‹ˆŠJBˆ››HHÛ›Ü›WÛ˜[YJ™Ù]
™š\œÝÛ˜[YH‹ˆŠJBˆYˆ›ÝˆÜˆ›Ý››N‚ˆÛÛ[YBˆYˆˆ[ˆ›ˆ[™››H[ˆ›Ž‚ˆ]Ë˜\[™

B‚ˆYˆ[Š]ÊHOHN‚ˆ™]\›ˆ]ÖÌK›Û™BˆYˆ[Š]ÊHOH‚ˆ™]\›ˆ›Û™K››ÛKÜ°ê[›ÛH›Ûˆ›Ý]°ê\È[œÈHšXÚY\ˆ‚ˆ™]\›ˆ›Û™Kœ\ÚY]\œÈÝYÚXZ\™\ÈÛÜœ™\ÜÛ™[
Û[Ûž[YJH‚‚™YˆÙ^˜XÝÜ—Ý^
—Øž]\Îˆž]\ÊHOˆÝŽ‚ˆYˆ›Ý—Øž]\ÈÜˆ›ÝT—ÓP”T–WÐURSP“N‚ˆ™]\›ˆˆ‚ˆžN‚ˆœ›ÛH\ˆ[\Ü”™XY\‚ˆ™XY\ˆH”™XY\Šž]\ÒSÊ—Øž]\ÊJBˆ^Ù\^Ù\[ÛŽ‚ˆ™]\›ˆˆ‚‚ˆYÙ\ÈH×Bˆ›ÜˆYÙH[ˆ™XY\‹œYÙ\Î‚ˆžN‚ˆYÙ\Ë˜\[™
YÙK™^˜XÝÝ^

HÜˆˆŠBˆ^Ù\^Ù\[ÛŽ‚ˆÛÛ[YBˆ™]\›ˆ—ˆ‹š›Ú[ŠYÙ\ÊB‚‚™YˆÛX]ÚÝ˜Z[™YWÙœ›ÛWÜ\˜Ú[Z[—ÜŠ˜Z[™Y\Îˆ\Ýš[WØž]\Îˆž]\ÊN‚ˆ^HÛ›Ü›WÛ˜[YJÙ^˜XÝÜ—Ý^
š[WØž]\ÊJBˆYˆ›Ý^‚ˆ™]\›ˆ›Û™K^Hˆ[\ÚX›H‚‚ˆ]ÈH×Bˆ›Üˆ[ˆ˜Z[™Y\Î‚ˆˆHÛ›Ü›WÛ˜[YJ™Ù]
›\ÝÛ˜[YH‹ˆŠJBˆ››HHÛ›Ü›WÛ˜[YJ™Ù]
™š\œÝÛ˜[YH‹ˆŠJBˆYˆ›ÝˆÜˆ›Ý››N‚ˆÛÛ[YBˆYˆˆ[ˆ^[™››H[ˆ^‚ˆ]Ë˜\[™

B‚ˆYˆ[Š]ÊHOHN‚ˆ™]\›ˆ]ÖÌK›Û™BˆYˆ[Š]ÊHOH‚ˆ™]\›ˆ›Û™K››ÛKÜ°ê[›ÛH›Ûˆ›Ý]°ê\È[œÈH\˜Ú[Z[ˆ‚ˆ™]\›ˆ›Û™Kœ\ÚY]\œÈÝYÚXZ\™\ÈÛÜœ™\ÜÛ™[
Û[Ûž[YJH‚‚‚™YˆØZ[Ý˜YWÜ\˜Ú[Z[—ÜŠ˜\ÙWÜ—Øž]\Îˆž]\ËÝ×Ü]ˆÝŠHOˆž]\Î‚ˆYˆ›Ý˜\ÙWÜ—Øž]\Î‚ˆ˜Z\ÙH˜[YQ\œ›ÜŠœ\˜Ú[Z[—ÜÛÝ\˜ÙWÚ[›Ý]˜X›HŠBˆYˆ›Ý
T—ÓP”T–WÐURSP“H[™‘TÔ•P—ÓP”T–WÐURSP“JN‚ˆ˜Z\ÙH˜[YQ\œ›ÜŠ›Xœ×Ü—Û›Û—Ù\ÜÛšX›\ÈŠB‚ˆœ›ÛH\ˆ[\Ü”™XY\‹•Üš]\‚ˆœ›ÛH™\ÜX‹›X‹][È[\Ü[XYÙT™XY\‚ˆœ›ÛH™\ÜX‹œ™Ù[ˆ[\ÜØ[˜\Â‚ˆ™XY\ˆH”™XY\Šž]\ÒSÊ˜\ÙWÜ—Øž]\ÊJBˆYˆ›Ý™XY\‹œYÙ\Î‚ˆ˜Z\ÙH˜[YQ\œ›ÜŠœ\˜Ú[Z[—Ü—ÝšYHŠB‚ˆš\œÝÜYÙHH™XY\‹œYÙ\ÖÌBˆÚYH›Ø]
š\œÝÜYÙK›YYXX›ÞÚY
BˆZYÚH›Ø]
š\œÝÜYÙK›YYXX›ÞšZYÚ
B‚ˆÈ›Û™HÝÈH\˜Ú[Z[ˆ‹‚ˆÈÛˆ\\]YH[ˆ˜›YYˆ
0êX›Ü™
HÝ\ˆX\Ü]Y\ˆÝ[[Y[ˆÈH›[˜È
ÈHØY™H›Ú\ˆš\ÚX›\ÈÝ\ˆHðí0êH›Ú]‚ˆ›ÞÝÈHÚY
ˆŒLBˆ›ÞÚHZYÚ
ˆŒNMBˆ›ÞÞHÚY
ˆŽÍ‚ˆ›ÞÞHHZYÚ
ˆÌLBˆÈZ\Ý[Y[š[ˆ[X[™0êHˆ0êXØ[H0êYðê™[Y[HÝÈ™\œÈH›Ú]BˆÈÝ\ˆÝ\š[Y\ˆHš[]›[˜Èš\ÚX›HÝ\ˆH›Ü™›Ú]HØY™K‚ˆ›ÞÞ
ÏHÚY
ˆŒˆY[™ÈHˆÛ\ÞH›ÞÞHY[™ÂˆÛ\ÞHH›ÞÞHHY[™ÂˆÛ\ÝÈH›ÞÝÈ
È
Y[™È
ˆŠBˆÛ\ÚH›ÞÚ
È
Y[™È
ˆŠB‚ˆXÚÙ]Hž]\ÒSÊ
BˆÈHØ[˜\ËØ[˜\ÊXÚÙ]YÙ\Ú^™OJÚYZYÚ
JB‚ˆÚ][XYÙK›Ü[ŠÝ×Ü]
H\È[N‚ˆÛÜœ™XÝYH[XYÙSÜË™^Y—Ý˜[œÜÜÙJ[JBˆ™ØˆHÛÜœ™XÝY˜ÛÛ™\
”‘ÐˆŠBˆ[Y×Ü™XY\ˆH[XYÙT™XY\Š™ØŠBˆ]ËZH™Ø‹œÚ^™BˆYˆ]Èˆ[™Zˆ‚ˆ\™Ù]ÝÈHX^
KÛ\ÝÊBˆ\™Ù]ÚHX^
KÛ\Ú
B‚ˆÈ™[\\ÜØYÙHÝ[
ÛÝ™\ŠHHH›Û™HÛ\0êYKØ[œÈ0êY›Ü›X][Û‹‚ˆØØ[HHX^
\™Ù]ÝÈÈ]Ë\™Ù]ÚÈZ
Bˆ˜]×ÝÈHX^
K]È
ˆØØ[JBˆ˜]×ÚHX^
KZ
ˆØØ[JBˆ˜]×ÞHÛ\Þ
È
\™Ù]ÝÈH˜]×ÝÊHÈ‚ˆ˜]×ÞHHÛ\ÞH
È
\™Ù]ÚH˜]×Ú
HÈ‚‚ˆËœØ]™TÝ]J
BˆÛ\Ü]HË˜™YÚ[”]

BˆÛ\Ü]œ™XÝ
Û\ÞÛ\ÞK\™Ù]ÝË\™Ù]Ú
BˆË˜Û\]
Û\Ü]Ý›ÚÙOLš[L
BˆË™˜]Ò[XYÙJ[Y×Ü™XY\‹˜]×Þ˜]×ÞK˜]×ÝË˜]×Ú™\Ù\™P\ÜXÝ˜][ÏUYKX\ÚÏIØ]]ÉÊBˆËœ™\ÝÜ™TÝ]J
B‚ˆËœØ]™J
BˆXÚÙ]œÙYZÊ
B‚ˆÝ™\›^WÜ™XY\ˆH”™XY\ŠXÚÙ]
BˆÝ™\›^WÜYÙHHÝ™\›^WÜ™XY\‹œYÙ\ÖÌBˆš\œÝÜYÙK›Y\™ÙWÜYÙJÝ™\›^WÜYÙJB‚ˆÝ]Hž]\ÒSÊ
BˆÜš]\ˆH•Üš]\Š
Bˆ›ÜˆYÙH[ˆ™XY\‹œYÙ\Î‚ˆÜš]\‹˜YÜYÙJYÙJBˆÜš]\‹Üš]JÝ]
Bˆ™]\›ˆÝ]™Ù]˜[YJ
B‚‚™YˆÚ\×Ù\ÜÙ\ÛXWÜÙ\ÜÚ[ÛŠÙ\ÜÚ[Û—ÛØšŽˆXÝÜÝ‹[žWJHOˆ›ÛÛ‚ˆˆˆ”™]\›ˆÚ]\ˆ[È\ÛXH[\ÜÈ]\Ý™XÙZ]™HH˜Z[™YHÝËˆˆˆ‚ˆ\ØÜš\ÜˆHˆ‹š›Ú[Š
ˆÝŠÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠKˆÝŠÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹›˜[YH‹ˆŠHÜˆˆŠKˆ
JK\\Š
Bˆ™]\›ˆ‘T’QÑPS•ˆ[ˆ\ØÜš\ÜˆÜˆ‘TÔˆ[ˆ\ØÜš\Ü‚‚‚™YˆÜÝÜ™WÜ\˜Ú[Z[—ÙÙ[™\˜]YÜŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝ‹—Øž]\Îˆž]\ÊHOˆÝŽ‚ˆ˜\ÙHH˜Z[™YWÝ\ØYÙ\ŠÙ\ÜÚ[Û—ÚY˜Z[™YWÚY
Bˆ\™Ù]Ù\ˆHÜËœ]š›Ú[Š˜\ÙK™[]™\˜X›\ÈŠBˆÜË›XZÙY\œÊ\™Ù]Ù\‹^\ÝÛÚÏUYJBˆ˜[YHH]ZY]ZY

Kš^ÎŒLH
È‹œˆ‚ˆ]HÜËœ]š›Ú[Š\™Ù]Ù\‹˜[YJBˆÚ]Ü[Š]ØˆŠH\ÈŽ‚ˆ‹Üš]J—Øž]\ÊBˆ™]\›ˆ]‚‚™YˆÜ\œÚ\ÝØ[×Ù[]™\˜X›WÝÚÙ[ŠˆÙ\ÜÚ[Û—ÚYˆÝ‹ˆ˜Z[™YWÚYˆÝ‹ˆÚ[™ˆÝ‹ˆÚÙ[ŽˆÝ‹ŠHOˆXÝÜÝ‹[žWN‚ˆˆˆ]XÚH[Ë]\ØYY[]™\˜X›H\Ú[™ÈH]\Ý\œÚ\ÝY^[ØY‚‚ˆ[È[\ÜÈØ[ˆÜ[™Ù]™\˜[ÙXÛÛ™ÈÙ[™\˜][™ÈœÈ[™Ù[™[™Èœ™]›Âˆ›ÝYšXØ][ÛœËˆ\œÚ\Ý[™Èœ›ÛHH^[ØYØYY]HÝ\Ùˆ]ˆÛÜšÈØ[ˆÝ™\Üš]H™]Ù\ˆ˜Z[™YHÚ[™Ù\Ëˆ\ÈÛX[]ÛZXÈ]]][Ûˆ[ÛÂˆXZÙ\ÈHØÝ[Y[š\ÚX›HÛˆHYZ[ˆ˜Z[™YHÚY]™Y›Ü™H›ÝYšXØ][ÛœÂˆ\™H][\Y‚ˆˆˆ‚‚ˆYˆ]]]JØ[›ÛšXØ[ˆXÝÜÝ‹[žWJHOˆXÝÜÝ‹[žWN‚ˆÙ\ÜÚ[Û—ÛØšˆHš[™ÜÙ\ÜÚ[ÛŠØ[›ÛšXØ[Ù\ÜÚ[Û—ÚY
BˆYˆ›ÝÙ\ÜÚ[Û—ÛØšŽ‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙKœ™X\ÛÛˆŽˆœÙ\ÜÚ[Ûˆ[›Ý]˜X›H[™[	Ù[œ™YÚ\Ý™[Y[ŸB‚ˆÝ\œ™[Ý˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
Ù\ÜÚ[Û—ÛØšŠBˆÝ\œ™[Ý˜Z[™YHH™^
ˆ
][H›Üˆ][H[ˆÝ\œ™[Ý˜Z[™Y\ÈYˆÝŠ][K™Ù]
šYŠHÜˆˆŠHOHÝŠ˜Z[™YWÚY
JKˆ›Û™Kˆ
BˆYˆ›ÝÝ\œ™[Ý˜Z[™YN‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙKœ™X\ÛÛˆŽˆœÝYÚXZ\™H[›Ý]˜X›H[™[	Ù[œ™YÚ\Ý™[Y[ŸB‚ˆ[]™\˜X›\ÈHÝ\œ™[Ý˜Z[™YKœÙ]Y˜][
™[]™\˜X›\È‹ßJBˆ^\Ý[™ÈHÝŠ[]™\˜X›\Ë™Ù]
Ú[™
HÜˆˆŠKœÝš\

BˆYˆ^\Ý[™È[™^\Ý[™ÈOHÚÙ[Ž‚ˆX™[HSU‘TP“WÓP‘SË™Ù]
Ú[™™ØÝ[Y[ŠK›ÝÙ\Š
Bˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙKœ™X\ÛÛˆŽˆˆžÛX™[H0êZ°è^\Ý[
›Ûˆ™[\XðêJHŸB‚ˆ[]™\˜X›\ÖÚÚ[™HHÚÙ[‚ˆÝ\œ™[Ý˜Z[™YVÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
BˆÙ\ÜÚ[Û—ÛØš–È˜Z[™Y\È—HHÝ\œ™[Ý˜Z[™Y\ÂˆÙ\ÜÚ[Û—ÛØš‹œÜ
œÝYÚXZ\™\È‹›Û™JBˆ™]\›ˆÈ›ÚÈŽˆY_B‚ˆ™]\›ˆØ]ÛZX×Ý\]WÙ]J]]]JB‚‚™YˆÜ\œÚ\ÝØ[×Ù[XZ[Ú\ÝÜžWÙ[žJˆÙ\ÜÚ[Û—ÚYˆÝ‹ˆ˜Z[™YWÚYˆÝ‹ˆ[žNˆÜ[Û˜[ÑXÝÜÝ‹[žWWKŠHOˆ›Û™N‚ˆˆˆ“Y\™ÙHÛ™Hœ™]›È\ÝÜžH[žHÚ]Ý]™]Üš][™ÈHÝ[H]H^[ØYˆˆˆ‚ˆYˆ›Ý\Ú[œÝ[˜ÙJ[žKXÝ
N‚ˆ™]\›‚‚ˆYˆ]]]JØ[›ÛšXØ[ˆXÝÜÝ‹[žWJHOˆXÝÜÝ‹[žWN‚ˆÙ\ÜÚ[Û—ÛØšˆHš[™ÜÙ\ÜÚ[ÛŠØ[›ÛšXØ[Ù\ÜÚ[Û—ÚY
BˆYˆ›ÝÙ\ÜÚ[Û—ÛØšŽ‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[Ù_BˆÝ\œ™[Ý˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
Ù\ÜÚ[Û—ÛØšŠBˆÝ\œ™[Ý˜Z[™YHH™^
ˆ
][H›Üˆ][H[ˆÝ\œ™[Ý˜Z[™Y\ÈYˆÝŠ][K™Ù]
šYŠHÜˆˆŠHOHÝŠ˜Z[™YWÚY
JKˆ›Û™Kˆ
BˆYˆ›ÝÝ\œ™[Ý˜Z[™YN‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[Ù_B‚ˆ\ÝÜžHHÝ\œ™[Ý˜Z[™YK™Ù]
œÙ[Ù[XZ[Ú\ÝÜžHŠBˆYˆ›Ý\Ú[œÝ[˜ÙJ\ÝÜžK\Ý
N‚ˆ\ÝÜžHH×BˆÚYÛ˜]\™HH
ˆÝŠ[žK™Ù]
×Ù[XZ[ŠHÜˆˆŠKˆÝŠ[žK™Ù]
œÝXš™XÝŠHÜˆˆŠKˆÝŠ[žK™Ù]
œÙ[Ø]ŠHÜˆˆŠKˆ
BˆYˆ›Ý[žJ
ˆÝŠ][K™Ù]
×Ù[XZ[ŠHÜˆˆŠKˆÝŠ][K™Ù]
œÝXš™XÝŠHÜˆˆŠKˆÝŠ][K™Ù]
œÙ[Ø]ŠHÜˆˆŠKˆ
HOHÚYÛ˜]\™H›Üˆ][H[ˆ\ÝÜžHYˆ\Ú[œÝ[˜ÙJ][KXÝ
JN‚ˆ\ÝÜžKš[œÙ\
XÝ
[žJJBˆÝ\œ™[Ý˜Z[™YVÈœÙ[Ù[XZ[Ú\ÝÜžH—HH\ÝÜžVÎŒŒBˆÙ\ÜÚ[Û—ÛØš–È˜Z[™Y\È—HHÝ\œ™[Ý˜Z[™Y\ÂˆÙ\ÜÚ[Û—ÛØš‹œÜ
œÝYÚXZ\™\È‹›Û™JBˆ™]\›ˆÈ›ÚÈŽˆY_B‚ˆžN‚ˆØ]ÛZX×Ý\]WÙ]J]]]JBˆ^Ù\^Ù\[ÛŽ‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠˆ•[˜X›HÈ\œÚ\Ý[È[XZ[\ÝÜžH›ÜˆÙ\ÜÚ[ÛI\È˜Z[™YOI\È‹ˆÙ\ÜÚ[Û—ÚYˆ˜Z[™YWÚYˆ
B‚‚\œÜÝ
‹Ø\KÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹Ü\˜Ú[Z[‹Ø[×Ý\ØYŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WÜ\˜Ú[Z[—Ø[×Ý\ØY
Ù\ÜÚ[Û—ÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆœÙ\ÜÚ[Û—Û›ÝÙ›Ý[™ŸJK‚ˆ˜Z[š[™×Ý\HH
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠKœÝš\

K\\Š
BˆYˆ˜Z[š[™×Ý\HOH‘T’QÑPS•QHŽ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆœ\˜Ú[Z[—Ü™\Ù\™YÙ›Ü—Ý˜YHŸJK‚ˆYˆ›Ý
T—ÓP”T–WÐURSP“H[™‘TÔ•P—ÓP”T–WÐURSP“JN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›Z\ÜÚ[™×Ü—Ù\[™[˜ÚY\ÈŸJKLÂ‚ˆš[\ÈH™\]Y\Ý™š[\Ë™Ù]\Ý
™š[\ÈŠBˆYˆ›Ýš[\Î‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››×Ùš[\ÈŸJK‚ˆÙ[™Û›ÝYšXØ][ÛœÈH
™\]Y\Ý™›Ü›K™Ù]
œÙ[™Û›ÝYšXØ][ÛœÈ‹ŒHŠHÜˆŒHŠKœÝš\

K›ÝÙ\Š
H›Ý[ˆÈŒ‹™˜[ÙH‹››È‹››Ûˆ‹›Ù™ˆŸB‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆ™XÙZ]™YHˆYYH×Bˆ˜Z[YH×B‚ˆ›Üˆˆ[ˆš[\Î‚ˆYˆ›ÝˆÜˆ›Ý‹™š[[˜[YN‚ˆÛÛ[YB‚ˆ™XÙZ]™Y
ÏHBˆÜšYÚ[˜[Û˜[YHH‹™š[[˜[YBˆ^HÜØY™WÙ^
ÜšYÚ[˜[Û˜[YJBˆYˆ^OH‹œˆŽ‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ™›Ü›X][˜[YH
ˆ[š\]Y[Y[
HŸJBˆÛÛ[YB‚ˆžN‚ˆžN‚ˆ‹œÝ™X[KœÙYZÊ
Bˆ^Ù\^Ù\[ÛŽ‚ˆ\ÜÂˆ—Øž]\ÈH‹œ™XY

HÜˆˆˆ‚ˆ^Ù\^Ù\[ÛŽ‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ›XÝ\™H[\ÜÜÚX›HŸJBˆÛÛ[YB‚ˆ˜Z[™YK™X\ÛÛˆHÛX]ÚÝ˜Z[™YWÙœ›ÛWÜ\˜Ú[Z[—ÜŠ˜Z[™Y\Ë—Øž]\ÊBˆYˆ›Ý˜Z[™YN‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ™X\ÛÛˆÜˆ››Ûˆ˜]XÚ0êHŸJBˆÛÛ[YB‚ˆ˜Z[™YWÚYH˜Z[™YK™Ù]
šYŠHÜˆ˜Z[™YK™Ù]
˜Z[™YWÚYŠHÜˆ˜Z[™YK™Ù]
œ\œÛÛ˜[ÚYŠBˆYˆ›Ý˜Z[™YWÚY‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ˜Z[™YWÚY[›Ý]˜X›HŸJBˆÛÛ[YB‚ˆ^\Ý[™ÈH

˜Z[™YK™Ù]
™[]™\˜X›\ÈŠHÜˆßJK™Ù]
œ\˜Ú[Z[ˆŠHÜˆˆŠKœÝš\

BˆYˆ^\Ý[™Î‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆœ\˜Ú[Z[ˆ0êZ°è^\Ý[
›Ûˆ™[\XðêJHŸJBˆÛÛ[YB‚ˆÝ×ÝÚÙ[ˆH
˜Z[™YK™Ù]
šY[]WÜÝÈŠHÜˆˆŠKœÝš\

BˆYˆ›ÝÝ×ÝÚÙ[Ž‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆœÝÈ	ÚY[]0êHXœÙ[HÝ\ˆHšXÚHÝYÚXZ\™HŸJBˆÛÛ[YB‚ˆÝ×Ü]HÙ]ÚÙ[š^™WÜ]
Ý×ÝÚÙ[ŠBˆYˆ›ÝÜËœ]™^\ÝÊÝ×Ü]
N‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆœÝÈ	ÚY[]0êH[›Ý]˜X›HŸJBˆÛÛ[YB‚ˆžN‚ˆš[˜[ÜˆHØZ[Ý˜YWÜ\˜Ú[Z[—ÜŠ—Øž]\ËÝ×Ü]
Bˆš[˜[Ü]HÜÝÜ™WÜ\˜Ú[Z[—ÙÙ[™\˜]YÜŠÙ\ÜÚ[Û—ÚY˜Z[™YWÚYš[˜[ÜŠBˆÚÙ[ˆHÝÚÙ[š^™WÜ]
š[˜[Ü]
Bˆ^Ù\^Ù\[Ûˆ\ÈN‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆˆ™ðê[°ê\˜][Ûˆ\˜Ú[Z[ˆ[\ÜÜÚX›NˆÜÝŠJ_HŸJBˆÛÛ[YB‚ˆ\œÚ\ÝÜ™\Ý[HÜ\œÚ\ÝØ[×Ù[]™\˜X›WÝÚÙ[ŠÙ\ÜÚ[Û—ÚY˜Z[™YWÚYœ\˜Ú[Z[ˆ‹ÚÙ[ŠBˆYˆ›Ý\œÚ\ÝÜ™\Ý[™Ù]
›ÚÈŠN‚ˆÜØY™WÜ™[[Ý™WÙš[Jš[˜[Ü]
Bˆ˜Z[Y˜\[™
Âˆ™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKˆœ™X\ÛÛˆŽˆ\œÚ\ÝÜ™\Ý[™Ù]
œ™X\ÛÛˆŠHÜˆ™[œ™YÚ\Ý™[Y[H\˜Ú[Z[ˆ[\ÜÜÚX›H‹ˆJBˆÛÛ[YB‚ˆ˜Z[™YKœÙ]Y˜][
™[]™\˜X›\È‹ßJBˆ˜Z[™YVÈ™[]™\˜X›\È—VÈœ\˜Ú[Z[ˆ—HHÚÙ[‚ˆ˜Z[™YVÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
B‚ˆYˆÙ[™Û›ÝYšXØ][ÛœÎ‚ˆžN‚ˆ[šÈHˆžÔP“P×ÔÕQS•ÔÔ•SÐTÑKœœÝš\
	ËÉÊ_KÙ\ÜXÙKÞÝ˜Z[™YK™Ù]
	ÜX›X×ÝÚÙ[‰Ë	ÉÊ_H‚ˆX™[HSU‘TP“WÓP‘SÖÈœ\˜Ú[Z[ˆ—Bˆš\œÝÛ˜[YHH
˜Z[™YK™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

HÜˆ“XY[YK[ÛœÚY]\ˆ‚ˆ›Ü›X][Û—Ý\HH›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠJBˆÝ\Hœ—Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠJBˆ[™Hœ—Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÙ[™‹ˆŠJB‚ˆÝXš™XÝHˆžÛX™[H\ÜÛšX›H8 $È[0êYÜ˜[HXØY[^H‚ˆ[HXZ[Û^[Ý]
ˆˆˆ‚ˆˆÝ[OW^X[YÛŽ˜Ù[\—¸§!HÛX™[H\ÜÛšX›OÚ‚‚ˆ›Ûš›Ý\ˆÝ›Û™ÏžÙš\œÝÛ˜[Y_OÜÝ›Û™Ï‹Ü‚‚ˆ‚ˆ›Ý\È]›ÛœÈHZ\Ú\ˆH›Ý\È[™›Ü›Y\ˆ]YH›Ý™HÝ›Û™ÏžÛX™[OÜÝ›Û™Ï‚ˆ\Ý0ê\ÛÜ›XZ\È\ÜÛšX›H[œÈ›Ý™H\ÜXÙHÝYÚXZ\™K‚ˆÜ‚‚ˆ]ˆÝ[OW˜˜XÚÙÜ›Ý[™ˆÙŒÙŽØ›Ü™\ŽŒ\ÛÛYÙMYMÙXŽØ›Ü™\‹\˜Y]\ÎŒLœÜY[™ÎŒMÛX\™Ú[ŽŒMœ‚ˆÝ[OW›X\™Ú[ŽŒL‚ˆÝ›Û™Ï¼'äã›Ü›X][ÛˆÜÝ›Û™ÏˆÙ›Ü›X][Û—Ý\_BˆÈˆ8 %Ý›Û™Ï‘]\ÈÜÝ›Û™Ïˆˆ
ÈÝ\
Èˆ]Hˆ
È[™Yˆ
Ý\Üˆ[™
H[ÙHˆŸBˆÜ‚‚ˆÝ[OW›X\™Ú[ŽŒ‚ˆÝ›Û™Ï¼'äãHXØðêY\ˆ0è›Ý™H\ÜXÙHÝYÚXZ\™HÜÝ›Û™Ïœ‚ˆH™YWžÛ[šßWˆÝ[OW˜ÛÛÜŽˆÌYŽNÝ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚ˜›ÛžÛ[šßOØO‚ˆÜ‚ˆÙ]‚‚ˆÝ[OW^X[YÛŽ˜Ù[\ŽÛX\™Ú[‹]ÜŒN‚ˆH™YWžÛ[šßW‚ˆÝ[OW™\Ü^Nš[›[™KX›ØÚÎØ˜XÚÙÜ›Ý[™ˆÌYŽNØÛÛÜŽÚ]NÜY[™ÎŒLœNØ›Ü™\‹\˜Y]\ÎŒLÂˆ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚ˜›Û‚ˆ<'äbHXØðêY\ˆ0è[Ûˆ\ÜXÙHÝYÚXZ\™BˆØO‚ˆÜ‚ˆˆˆŠB‚ˆÛ\×Û˜[YHH
˜Z[™YK™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

BˆÛ\ÈH
ˆˆ’[0êYÜ˜[HXØY[^H8§!HÜÛ\×Û˜[YH
È	Ë	ÈYˆÛ\×Û˜[YH[ÙH	ÉßWˆ‚ˆˆ•›Ý™HÛX™[H\Ý\ÜÛšX›HÝ\ˆ›Ý™H\ÜXÙH—ˆ‚ˆˆžÛ[šßWˆ‚ˆˆHšY[0íHX[H[0êYÜ˜[HXØY[^H‚ˆ
B‚ˆ[XZ[ÜÙ[Hœ™]›×ÜÙ[™Ù[XZ[
˜Z[™YK™Ù]
™[XZ[‹ˆŠKÝXš™XÝ[˜Z[™YO]˜Z[™YJBˆYˆ[XZ[ÜÙ[‚ˆ\ÝÜžHH˜Z[™YK™Ù]
œÙ[Ù[XZ[Ú\ÝÜžHŠHÜˆ×BˆÜ\œÚ\ÝØ[×Ù[XZ[Ú\ÝÜžWÙ[žJˆÙ\ÜÚ[Û—ÚYˆ˜Z[™YWÚYˆ\ÝÜžVÌHYˆ\ÝÜžH[ÙH›Û™Kˆ
Bˆœ™]›×ÜÙ[™ÜÛ\Ê˜Z[™YK™Ù]
œÛ™H‹ˆŠKÛ\ÊBˆ^Ù\^Ù\[ÛŽ‚ˆ\ÜÂ‚ˆYY˜\[™
Âˆ™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKˆ˜Z[™YWÚYŽˆ˜Z[™YWÚYˆ˜Z[™YWÛ˜[YHŽˆˆžÝ˜Z[™YK™Ù]
	Ùš\œÝÛ˜[YIË	ÉÊ_HÝ˜Z[™YK™Ù]
	Û\ÝÛ˜[YIË	ÉÊ_H‹œÝš\

BˆJB‚ˆ™]\›ˆœÛÛšYžJÂˆ›ÚÈŽˆYKˆœ™XÙZ]™YŽˆ™XÙZ]™Yˆ˜YYØÛÝ[Žˆ[ŠYY
Kˆ˜YYŽˆYYˆ™˜Z[YŽˆ˜Z[YˆœÙ[™Û›ÝYšXØ][ÛœÈŽˆÙ[™Û›ÝYšXØ][ÛœËˆJB‚‚\œÜÝ
‹Ø\KÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÜÝØ[×Ý\ØYŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WÜÜÝØ[×Ý\ØY
Ù\ÜÚ[Û—ÚYˆÝŠN‚ˆ[\Ü˜XÙX˜XÚÂ‚ˆ]HHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆœÙ\ÜÚ[Û—Û›ÝÙ›Ý[™ŸJK‚ˆš[\ÈH™\]Y\Ý™š[\Ë™Ù]\Ý
™š[\ÈŠBˆYˆ›Ýš[\Î‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››×Ùš[\ÈŸJK‚ˆÙ[™Û›ÝYšXØ][ÛœÈH
™\]Y\Ý™›Ü›K™Ù]
œÙ[™Û›ÝYšXØ][ÛœÈ‹ŒHŠHÜˆŒHŠKœÝš\

K›ÝÙ\Š
H›Ý[ˆÈŒ‹™˜[ÙH‹››È‹››Ûˆ‹›Ù™ˆŸB‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊB‚ˆ™XÙZ]™YHˆYYH×Bˆ˜Z[YH×B‚ˆ›Üˆˆ[ˆš[\Î‚ˆYˆ›ÝˆÜˆ›Ý‹™š[[˜[YN‚ˆÛÛ[YB‚ˆ™XÙZ]™Y
ÏHBˆÜšYÚ[˜[Û˜[YHH‹™š[[˜[YBˆ^HÜØY™WÙ^
ÜšYÚ[˜[Û˜[YJB‚ˆYˆ^›Ý[ˆ
‹œˆ‹‹šœÈ‹‹šœYÈ‹‹œ™ÈŠN‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ™^[œÚ[Ûˆ›Ûˆ]]Üš\ðêYHŸJBˆÛÛ[YB‚ˆ˜Z[™YK™X\ÛÛˆHÛX]ÚÝ˜Z[™YWÙœ›ÛWÙš[[˜[YJ˜Z[™Y\ËÜšYÚ[˜[Û˜[YJBˆYˆ›Ý˜Z[™YN‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ™X\ÛÛˆÜˆ››Ûˆ˜]XÚ0êHŸJBˆÛÛ[YB‚ˆÈ8§!HðêXÝ\š\ÙH	ÚY
Ù[ÛˆÛˆØÚ0ê[XJBˆ˜Z[™YWÚYH˜Z[™YK™Ù]
šYŠHÜˆ˜Z[™YK™Ù]
˜Z[™YWÚYŠHÜˆ˜Z[™YK™Ù]
œ\œÛÛ˜[ÚYŠBˆYˆ›Ý˜Z[™YWÚY‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ˜Z[™YWÚY[›Ý]˜X›H
YX[œ]X[[œÈ]KšœÛÛŠHŸJBˆÛÛ[YB‚ˆÈ8§!HÚH0êZ°è[ˆÔÕÛˆ‰ðêXÜ˜\ÙH\È
ÈÛˆ‰Ù[›ÚYH\Âˆ^\Ý[™ÈH

˜Z[™YK™Ù]
™[]™\˜X›\ÈŠHÜˆßJK™Ù]
˜Ø\WÜÜÝŠHÜˆˆŠKœÝš\

BˆYˆ^\Ý[™Î‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ™0êZ°è[ˆÔÕ^\Ý[
›Ûˆ™[\XðêJHŸJBˆÛÛ[YB‚‚ˆžN‚ˆÈ8§!HðêXÝ\š]0êHˆ™[Y]HÝ\œÙ]\ˆ]H0êX]
Ù[Ûˆ˜]šYØ]]\ˆÈ›ÞH0éØH0ê]š]H\ÈšXÚY\œÈšY\ÊBˆžN‚ˆ‹œÝ™X[KœÙYZÊ
Bˆ^Ù\^Ù\[ÛŽ‚ˆ\ÜÂ‚ˆÝÜ™YHÜÝÜ™WÙš[JÙ\ÜÚ[Û—ÚY˜Z[™YWÚY™[]™\˜X›\È‹ŠBˆÚÙ[ˆHÝÚÙ[š^™WÜ]
ÝÜ™Y
B‚ˆ^Ù\^Ù\[Ûˆ\ÈN‚ˆÈ8§!HÛˆÙÈ	Ù\œ™]\ˆÛÛ\0êH[œÈ™[™\‚ˆš[
OOH•SÈÔÕˆ\œ™]\ˆÝØÚØYÙHOOHŠBˆš[
œÙ\ÜÚ[Û—ÚYˆ‹Ù\ÜÚ[Û—ÚY
Bˆš[
˜Z[™YWÚYˆ‹˜Z[™YWÚY
Bˆš[
™š[[˜[YNˆ‹ÜšYÚ[˜[Û˜[YJBˆ˜XÙX˜XÚËœš[Ù^Ê
B‚ˆÈ8§!H]Ûˆ™[›ÚYH[ˆY\ÜØYÙH][Hðí0êHRBˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆˆ™\œ™]\ˆÝØÚØYÙNˆÜÝŠJ_HŸJBˆÛÛ[YB‚ˆ˜Z[™YKœÙ]Y˜][
™[]™\˜X›\È‹ßJBˆ˜Z[™YVÈ™[]™\˜X›\È—VÈ˜Ø\WÜÜÝ—HHÚÙ[‚ˆ˜Z[™YVÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
B‚ˆÈ8§!H[›ÚHXZ[
ÈÓTÈ
ÛÛ[YH	Ú[\ÜX[Y[[]™\˜X›\ÊBˆYˆÙ[™Û›ÝYšXØ][ÛœÎ‚ˆžN‚ˆ[šÈHˆžÔP“P×ÔÕQS•ÔÔ•SÐTÑKœœÝš\
	ËÉÊ_KÙ\ÜXÙKÞÝ˜Z[™YK™Ù]
	ÜX›X×ÝÚÙ[‰Ë	ÉÊ_H‚ˆX™[HSU‘TP“WÓP‘SÖÈ˜Ø\WÜÜÝ—B‚ˆš\œÝÛ˜[YHH
˜Z[™YK™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

HÜˆ“XY[YK[ÛœÚY]\ˆ‚ˆ›Ü›X][Û—Ý\HH›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠJBˆÝ\Hœ—Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠJBˆ[™Hœ—Ù]JÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÙ[™‹ˆŠJB‚ˆ^˜WÛ[™HH
ˆ¼'ênˆ›Ý™HØ\HÔÕ\Ý\ÜÛšX›HÝ\ˆ›Ý™H\ÜXÙH[ˆYÛ™Kˆ‚ˆ“›Ý\È›Ý\È™[Y]›ÛœÈ0êYØ[[Y[[ˆ^[\Z\™H\Y\ˆ[ˆXZ[ˆ›Ü™H‚ˆŠ][[Ûˆˆ]XÝ[ˆ\XØ]H™HÙ\˜H0ê[]œ°êJKˆ‚ˆÛÛœÙ\™^‹[H°êXÚY]\Ù[Y[[H]]0ê™H[X[™0êYH\ˆ[ˆ[\ÞY]\‹ˆ‚ˆ
B‚ˆÝXš™XÝHˆžÛX™[H\ÜÛšX›H8 $È[0êYÜ˜[HXØY[^HˆÈ8§!H’VPÒB‚ˆ[HXZ[Û^[Ý]
ˆˆˆ‚ˆˆÝ[OH^X[YÛŽ˜Ù[\ˆ¸§!HÛX™[H\ÜÛšX›OÚ‚‚ˆ›Ûš›Ý\ˆÝ›Û™ÏžÙš\œÝÛ˜[Y_OÜÝ›Û™Ï‹Ü‚‚ˆ‚ˆ›Ý\È]›ÛœÈHZ\Ú\ˆH›Ý\È[™›Ü›Y\ˆ]YH›Ý™HÝ›Û™ÏžÛX™[OÜÝ›Û™Ï‚ˆ\Ý0ê\ÛÜ›XZ\È\ÜÛšX›H[œÈ›Ý™H\ÜXÙHÝYÚXZ\™K‚ˆÜ‚‚ˆÝ[OIÛX\™Ú[‹]ÜŒLÙ›Û]ÙZYÚÌ	ÏžÙ^˜WÛ[™_OÜ‚‚ˆ]ˆÝ[OH˜˜XÚÙÜ›Ý[™ˆÙŒÙŽØ›Ü™\ŽŒ\ÛÛYÙMYMÙXŽØ›Ü™\‹\˜Y]\ÎŒLœÜY[™ÎŒMÛX\™Ú[ŽŒMœ‚ˆÝ[OH›X\™Ú[ŽŒL‚ˆÝ›Û™Ï¼'äã›Ü›X][ÛˆÜÝ›Û™ÏˆÙ›Ü›X][Û—Ý\_BˆÈˆ8 %Ý›Û™Ï‘]\ÈÜÝ›Û™Ïˆˆ
ÈÝ\
Èˆ]Hˆ
È[™Yˆ
Ý\Üˆ[™
H[ÙHˆŸBˆÜ‚‚ˆÝ[OH›X\™Ú[ŽŒ‚ˆÝ›Û™Ï¼'äãHXØðêY\ˆ0è›Ý™H\ÜXÙHÝYÚXZ\™HÜÝ›Û™Ïœ‚ˆH™YHžÛ[šßHˆÝ[OH˜ÛÛÜŽˆÌYŽNÝ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚ˜›ÛžÛ[šßOØO‚ˆÜ‚ˆÙ]‚‚ˆÝ[OH^X[YÛŽ˜Ù[\ŽÛX\™Ú[‹]ÜŒN‚ˆH™YHžÛ[šßH‚ˆÝ[OH™\Ü^Nš[›[™KX›ØÚÎØ˜XÚÙÜ›Ý[™ˆÌYŽNØÛÛÜŽÚ]NÜY[™ÎŒLœNØ›Ü™\‹\˜Y]\ÎŒLÂˆ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚ˜›Û‚ˆ<'äbHXØðêY\ˆ0è[Ûˆ\ÜXÙHÝYÚXZ\™BˆØO‚ˆÜ‚‚ˆÝ[OH›X\™Ú[‹]ÜŒŒœ‚ˆÝ\ˆÝ]H]Y\Ý[Û‹›Ý\ÈÝ]™^ˆ›Ý\ÈÛÛXÝ\ˆ]HÝ›Û™ÏŒŒˆÈÈŽÜÝ›Û™Ï‹‚ˆÜ‚‚ˆÝ[OH›X\™Ú[‹]ÜŒŒœ‚ˆšY[ˆÛÜ™X[[Y[œ‚ˆÝ›Û™ÏÛ0ê[Y[RSS•ÜÝ›Û™Ïœ‚ˆ\™XÝ]\ˆ[0êYÜ˜[HXØY[^BˆÜ‚ˆˆˆŠB‚ˆÛ\×Û˜[YHH
˜Z[™YK™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

BˆÛ\ÈH
ˆˆ’[0êYÜ˜[HXØY[^H8§!HÜÛ\×Û˜[YH
È	Ë	ÈYˆÛ\×Û˜[YH[ÙH	ÉßH‚ˆˆ•›Ý™HÛX™[H\Ý\ÜÛšX›HÝ\ˆ›Ý™H\ÜXÙHÝYÚXZ\™HˆÛ[šßH‚ˆˆHšY[0íHX[H[0êYÜ˜[HXØY[^H‚ˆ
B‚ˆYˆ
˜Z[™YK™Ù]
™[XZ[ŠHÜˆˆŠKœÝš\

N‚ˆœ™]›×ÜÙ[™Ù[XZ[
˜Z[™YK™Ù]
™[XZ[‹ˆŠKÝXš™XÝ[˜Z[™YO]˜Z[™YJBˆYˆ
˜Z[™YK™Ù]
œÛ™HŠHÜˆˆŠKœÝš\

N‚ˆœ™]›×ÜÙ[™ÜÛ\Ê˜Z[™YK™Ù]
œÛ™H‹ˆŠKÛ\ÊB‚ˆ^Ù\^Ù\[Ûˆ\ÈN‚ˆš[
OOH•SÈÔÕˆ\œ™]\ˆ[›ÚHXZ[ÜÛ\ÈOOH‹™\ŠJJB‚‚‚ˆYY˜\[™
Âˆ™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKˆ˜Z[™YWÚYŽˆ˜Z[™YWÚYˆ˜Z[™YWÛ˜[YHŽˆˆžÝ˜Z[™YK™Ù]
	Ùš\œÝÛ˜[YIË	ÉÊ_HÝ˜Z[™YK™Ù]
	Û\ÝÛ˜[YIË	ÉÊ_H‹œÝš\

BˆJB‚ˆÈ\œÚ\ÝˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JB‚ˆ™]\›ˆœÛÛšYžJÂˆ›ÚÈŽˆYKˆœ™XÙZ]™YŽˆ™XÙZ]™Yˆ˜YYØÛÝ[Žˆ[ŠYY
Kˆ˜YYŽˆYYˆ™˜Z[YŽˆ˜Z[YˆœÙ[™Û›ÝYšXØ][ÛœÈŽˆÙ[™Û›ÝYšXØ][ÛœÂˆJB‚‚\œÜÝ
‹Ø\KÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹Ù\ÛYKØ[×Ý\ØYŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WÙ\ÛYWØ[×Ý\ØY
Ù\ÜÚ[Û—ÚYˆÝŠN‚ˆ[\Ü˜XÙX˜XÚÂ‚ˆ]HHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆœÙ\ÜÚ[Û—Û›ÝÙ›Ý[™ŸJK‚ˆ\×Ù\ÜÙ\ÛXHHÚ\×Ù\ÜÙ\ÛXWÜÙ\ÜÚ[ÛŠÊBˆYˆ\×Ù\ÜÙ\ÛXH[™›Ý
T—ÓP”T–WÐURSP“H[™‘TÔ•P—ÓP”T–WÐURSP“JN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›Z\ÜÚ[™×Ü—Ù\[™[˜ÚY\ÈŸJKLÂ‚ˆš[\ÈH™\]Y\Ý™š[\Ë™Ù]\Ý
™š[\ÈŠBˆYˆ›Ýš[\Î‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››×Ùš[\ÈŸJK‚ˆÙ[™Û›ÝYšXØ][ÛœÈH
™\]Y\Ý™›Ü›K™Ù]
œÙ[™Û›ÝYšXØ][ÛœÈ‹ŒHŠHÜˆŒHŠKœÝš\

K›ÝÙ\Š
H›Ý[ˆÈŒ‹™˜[ÙH‹››È‹››Ûˆ‹›Ù™ˆŸB‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊB‚ˆ™XÙZ]™YHˆYYH×Bˆ˜Z[YH×B‚ˆ›Üˆˆ[ˆš[\Î‚ˆYˆ›ÝˆÜˆ›Ý‹™š[[˜[YN‚ˆÛÛ[YB‚ˆ™XÙZ]™Y
ÏHBˆÜšYÚ[˜[Û˜[YHH‹™š[[˜[YBˆ^HÜØY™WÙ^
ÜšYÚ[˜[Û˜[YJB‚ˆYˆ\×Ù\ÜÙ\ÛXH[™^OH‹œˆŽ‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ™›Ü›X][˜[YH
ˆ[š\]Y[Y[Ý\ˆ[ˆ\0íYHTÔ
HŸJBˆÛÛ[YB‚ˆYˆ^›Ý[ˆ
‹œˆ‹‹šœÈ‹‹šœYÈ‹‹œ™ÈŠN‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ™^[œÚ[Ûˆ›Ûˆ]]Üš\ðêYHŸJBˆÛÛ[YB‚ˆ—Øž]\ÈH›Û™Bˆ˜Z[™YK™X\ÛÛˆHÛX]ÚÝ˜Z[™YWÙœ›ÛWÙš[[˜[YJ˜Z[™Y\ËÜšYÚ[˜[Û˜[YJBˆYˆ›Ý˜Z[™YH[™^OH‹œˆŽ‚ˆžN‚ˆ‹œÝ™X[KœÙYZÊ
Bˆ—Øž]\ÈH‹œ™XY

HÜˆˆˆ‚ˆ‹œÝ™X[KœÙYZÊ
Bˆ˜Z[™YK—Ü™X\ÛÛˆHÛX]ÚÝ˜Z[™YWÙœ›ÛWÜ\˜Ú[Z[—ÜŠ˜Z[™Y\Ë—Øž]\ÊBˆYˆ›Ý˜Z[™YN‚ˆYˆ™X\ÛÛˆOH››ÛKÜ°ê[›ÛH›Ûˆ›Ý]°ê\È[œÈHšXÚY\ˆˆ[™—Ü™X\ÛÛˆOH››ÛKÜ°ê[›ÛH›Ûˆ›Ý]°ê\È[œÈH\˜Ú[Z[ˆŽ‚ˆ™X\ÛÛˆH››ÛKÜ°ê[›ÛH›Ûˆ›Ý]°ê\È[œÈH›ÛHHšXÚY\ˆšH[œÈHˆ‚ˆ[ÙN‚ˆ™X\ÛÛˆHˆžÜ™X\ÛÛŸNÈŽˆÜ—Ü™X\ÛÛŸH‚ˆ^Ù\^Ù\[ÛŽ‚ˆ™X\ÛÛˆHˆžÜ™X\ÛÛŸNÈXÝ\™HHˆ[\ÜÜÚX›H‚ˆYˆ›Ý˜Z[™YN‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ™X\ÛÛˆÜˆ››Ûˆ˜]XÚ0êHŸJBˆÛÛ[YB‚ˆ˜Z[™YWÚYH˜Z[™YK™Ù]
šYŠHÜˆ˜Z[™YK™Ù]
˜Z[™YWÚYŠHÜˆ˜Z[™YK™Ù]
œ\œÛÛ˜[ÚYŠBˆYˆ›Ý˜Z[™YWÚY‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ˜Z[™YWÚY[›Ý]˜X›HŸJBˆÛÛ[YB‚ˆÈ8§!HÚH0êZ°è[ˆ\0íYKÛˆ‰ðêXÜ˜\ÙH\È
ÈÛˆ‰Ù[›ÚYH\Âˆ^\Ý[™ÈH

˜Z[™YK™Ù]
™[]™\˜X›\ÈŠHÜˆßJK™Ù]
™\ÛYHŠHÜˆˆŠKœÝš\

BˆYˆ^\Ý[™Î‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ™0êZ°è[ˆ\0íYH^\Ý[
›Ûˆ™[\XðêJHŸJBˆÛÛ[YB‚ˆÝ×Ü]Hˆ‚ˆYˆ\×Ù\ÜÙ\ÛXN‚ˆÝ×ÝÚÙ[ˆHÝŠ˜Z[™YK™Ù]
šY[]WÜÝÈŠHÜˆˆŠKœÝš\

BˆYˆ›ÝÝ×ÝÚÙ[Ž‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆœÝÈ	ÚY[]0êHXœÙ[HÝ\ˆHšXÚHÝYÚXZ\™HŸJBˆÛÛ[YBˆÝ×Ü]HÙ]ÚÙ[š^™WÜ]
Ý×ÝÚÙ[ŠBˆYˆ›ÝÜËœ]™^\ÝÊÝ×Ü]
N‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆœÝÈ	ÚY[]0êH[›Ý]˜X›HŸJBˆÛÛ[YB‚ˆžN‚ˆžN‚ˆ‹œÝ™X[KœÙYZÊ
Bˆ^Ù\^Ù\[ÛŽ‚ˆ\ÜÂ‚ˆYˆ\×Ù\ÜÙ\ÛXN‚ˆYˆ—Øž]\È\È›Û™N‚ˆ—Øž]\ÈH‹œ™XY

HÜˆˆˆ‚ˆš[˜[ÜˆHØZ[Ý˜YWÜ\˜Ú[Z[—ÜŠ—Øž]\ËÝ×Ü]
BˆÝÜ™YHÜÝÜ™WÜ\˜Ú[Z[—ÙÙ[™\˜]YÜŠÙ\ÜÚ[Û—ÚY˜Z[™YWÚYš[˜[ÜŠBˆ[ÙN‚ˆÝÜ™YHÜÝÜ™WÙš[JÙ\ÜÚ[Û—ÚY˜Z[™YWÚY™[]™\˜X›\È‹ŠBˆÚÙ[ˆHÝÚÙ[š^™WÜ]
ÝÜ™Y
Bˆ^Ù\^Ù\[Ûˆ\ÈN‚ˆš[
OOH•SÈTÓQNˆ\œ™]\ˆÝØÚØYÙHOOHŠBˆ˜XÙX˜XÚËœš[Ù^Ê
Bˆ™X\ÛÛˆH™ðê[°ê\˜][ÛˆH\0íYH]™XÈÝÈ[\ÜÜÚX›HˆYˆ\×Ù\ÜÙ\ÛXH[ÙH™\œ™]\ˆÝØÚØYÙH‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆˆžÜ™X\ÛÛŸNˆÜÝŠJ_HŸJBˆÛÛ[YB‚ˆ\œÚ\ÝÜ™\Ý[HÜ\œÚ\ÝØ[×Ù[]™\˜X›WÝÚÙ[ŠÙ\ÜÚ[Û—ÚY˜Z[™YWÚY™\ÛYH‹ÚÙ[ŠBˆYˆ›Ý\œÚ\ÝÜ™\Ý[™Ù]
›ÚÈŠN‚ˆÜØY™WÜ™[[Ý™WÙš[JÝÜ™Y
Bˆ˜Z[Y˜\[™
Âˆ™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKˆœ™X\ÛÛˆŽˆ\œÚ\ÝÜ™\Ý[™Ù]
œ™X\ÛÛˆŠHÜˆ™[œ™YÚ\Ý™[Y[H\0íYH[\ÜÜÚX›H‹ˆJBˆÛÛ[YB‚ˆ˜Z[™YKœÙ]Y˜][
™[]™\˜X›\È‹ßJBˆ˜Z[™YVÈ™[]™\˜X›\È—VÈ™\ÛYH—HHÚÙ[‚ˆ˜Z[™YVÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
B‚ˆÈ8§!H[›ÚHXZ[
ÈÓTÈ
XZ[[œšXÚH
ÈÓTÈ
È]š\ÈÛÛÙÛJBˆYˆÙ[™Û›ÝYšXØ][ÛœÎ‚ˆžN‚ˆ[šÈHˆžÔP“P×ÔÕQS•ÔÔ•SÐTÑKœœÝš\
	ËÉÊ_KÙ\ÜXÙKÞÝ˜Z[™YK™Ù]
	ÜX›X×ÝÚÙ[‰Ë	ÉÊ_H‚ˆX™[HSU‘TP“WÓP‘SÖÈ™\ÛYH—B‚ˆš\œÝÛ˜[YHH
˜Z[™YK™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

HÜˆ“XY[YK[ÛœÚY]\ˆ‚ˆÝXš™XÝHˆžÛX™[H\ÜÛšX›H8 $È[0êYÜ˜[HXØY[^H‚‚ˆÈKKH0ê]XÝ[Ûˆ\H›Ü›X][Ûˆ
TÈÈLÔÈ\šYÙX[
HKKBˆ›Ü›X][Û—Ý\HH›Ü›X][Û—ÛX™[
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠJBˆH
›Ü›X][Û—Ý\HÜˆˆŠK›ÝÙ\Š
B‚ˆÛ˜\×Ý]HHˆ‚ˆÛ˜\×Ú[Hˆ‚‚ˆYˆ˜\Èˆ[ˆ‚ˆÛ˜\×Ý]HH¼'äãØ\H›Ù™\ÜÚ[Û›™[Hˆ]XÝ[™H0ê[X\˜ÚH‚ˆÛ˜\×Ú[Hˆˆ‚ˆÝ[OH›X\™Ú[ŽŒ‚ˆÝ›Û™Ï•›Ý\È‰Ø]™^ˆ]XÝ[™H0ê[X\˜ÚH0èY™™XÝY\ˆÝ\ˆ›Ý™HØ\H›Ù™\ÜÚ[Û›™[KÜÝ›Û™Ï‚ˆ›Ý™H\0íYHH0ê]0êH]]ÛX]\]Y[Y[˜[œÛZ\È]HÓTÈ]ZH›ØðêHXÝY[[Y[0è[™H[œ]pêHYZ[š\Ý˜]]™K‚ˆ0êÈ]YH	Ù[œ]pêHÙ\˜H\›Z[°êYK›Ý\È™XÙ]œ™^ˆ›Ý™HØ\H›Ù™\ÜÚ[Û›™[H\™XÝ[Y[Ú^ˆ›Ý\È\ˆÛÝ\œšY\ˆÜÝ[‚ˆÜ‚ˆÝ[OH›X\™Ú[ŽŒL‚ˆÝ›Û™Ï”Ý\ˆ˜\[ÜÝ›Û™Ïˆ›Ý\È™HÝ]™^ˆ\È^\˜Ù\ˆH›Ù™\ÜÚ[Ûˆ[]YH›Ý\È‰Ø]™^ˆ\È™péÝH›Ý™HØ\H›Ù™\ÜÚ[Û›™[K‚ˆÜ‚ˆˆˆ‚ˆ[Yˆ˜LÜˆ[ˆ‚ˆÛ˜\×Ý]HH¼'äãØ\H›Ù™\ÜÚ[Û›™[Hˆ0ê[X\˜ÚH0èY™™XÝY\ˆÝ\ˆ0ê[0ê\Ù\šXÙ\ÈÓTÈ‚ˆÛ˜\×Ú[Hˆˆ‚ˆÝ[OH›X\™Ú[ŽŒ‚ˆ›Ý\ÈÝ]™^ˆ0è°ê\Ù[›ØðêY\ˆ0èH[X[™HHØ\H›Ù™\ÜÚ[Û›™[H\Z\È	Ù\ÜXÙH0ê[0ê\Ù\šXÙ\ÈHÓTË‚ˆÜ‚ˆ[Ý[OH›X\™Ú[ŽŒLNÈY[™ÎŒÈ[™KZZYÚŒKˆ‚ˆO”ÚH›Ý\È0ê\È0êZ°èYÙ[HðêXÝ\š]0êHˆÛ\]Y^ˆÝ\ˆÝ›Û™Ïˆ“XH[X[™HÛÛ˜Ù\›™H[™H^[œÚ[ÛˆHØ\H›Ù™\ÜÚ[Û›™[HÜÝ›Û™Ï‹ÛO‚ˆO”ÚH›Ý\È‰ðê\È\ÈYÙ[HðêXÝ\š]0êHˆÛ\]Y^ˆÝ\ˆÝ›Û™Ïˆ“XH[X[™HÛÛ˜Ù\›™H[™HØ\H›Ù™\ÜÚ[Û›™[HÜÝ›Û™Ï‹ÛO‚ˆO‘[œÈ\È]^Ø\ËÛÛ\0ê]^ˆHXœš\]YHÝ›Û™Ïˆ’‰ØZH[ˆ•PˆÜÝ›Û™Ïˆ[ˆ[™\]X[‚ˆÝ›Û™Ï›Ý™H“ÓOÜÝ›Û™Ïˆ
[š\]Y[Y[›Ý™H›ÛK\È›Ý™H°ê[›ÛJH]›Ý™HÝ›Û™Ï“•PÜÝ›Û™Ï‚ˆ
\ÈÝ›Û™ÏÈ\›šY\œÈÚY™œ™\ÏÜÝ›Û™ÏˆH›Ý™H[pê\›È	Ø]]Üš\Ø][Ûˆ°êX[X›HÝHH›Ý™HØ\H›Ù™\ÜÚ[Û›™[JK‚ˆÛO‚ˆO”ÝZ]™^ˆ\È0ê]\\È]0ê[0êXÚ\™Ù^ˆ\ÈpêÙ\È\ÝYšXØ]]™\È‚ˆÝ›Û™ÏœpêÙH	ÚY[]0êOÜÝ›Û™Ï‹Ý›Û™Ïš\ÝYšXØ]YˆHÛZXÚ[OÜÝ›Û™ÏˆH[Ú[œÈHÈ[Ú\Ë]Ý›Û™Ï›Ý™H\0íYOÜÝ›Û™Ï‹‚ˆÛO‚ˆÝ[‚ˆÝ[OH›X\™Ú[ŽŒLœ‚ˆH™YHšÎ‹ËÙ\Ý][\Ù\šXÙ\ËXÛ˜\Ëš[\šY]\‹™ÛÝ]‹™œ‹È‚ˆÝ[OH˜ÛÛÜŽˆÌYŽNÝ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚŽ‚ˆ<'äbHÛ\]Y^ˆXÚHÝ\ˆ[X[™\ˆ›Ý™HØ\H›Ù™\ÜÚ[Û›™[BˆØO‚ˆÜ‚ˆˆˆ‚ˆ[Yˆ™\šYÙX[ˆ[ˆ‚ˆÛ˜\×Ý]HH¼'äãYÜ°ê[Y[\šYÙX[ˆ0ê[X\˜ÚH0èY™™XÝY\ˆ‚ˆÛ˜\×Ú[Hˆˆ‚ˆÝ[OH›X\™Ú[ŽŒ‚ˆ›Ý\ÈÝ]™^ˆ0è°ê\Ù[›ØðêY\ˆ0è›Ý™H[X[™H	ØYÜ°ê[Y[\šYÙX[\™XÝ[Y[\Z\ÈHÚ]H[\›™]HÓTÂˆ[ˆÛÛ\0ê][H›Ü›][Z\™H[ˆÛ\]X[XÚH‚ˆÜ‚ˆÝ[OH›X\™Ú[ŽŒLœ‚ˆH™YHšÎ‹ËÝÝÝË˜Û˜\Ëš[\šY]\‹™ÛÝ]‹™œ‹Ñ[X\˜Ú\ËY[‹[YÛ™KÕ›Ý\ËY]\Ë][‹\\XÝ[Y\‹Ñ\šYÙ\‹][™KY[™\š\ÙKYK\ÙXÝ\š]K\š]™YK][‹[Ü™Ø[š\ÛYKYKY›Ü›X][Û‹][‹\Ù\šXÙKZ[\›™KYK\ÙXÝ\š]KÑ\šYÙ\‹][‹[Ü™Ø[š\ÛYKYKY›Ü›X][Û‹][™KY[™\š\ÙKYK\ÙXÝ\š]K\š]™YK][‹\Ù\šXÙKZ[\›™KYK\ÙXÝ\š]H‚ˆÝ[OH˜ÛÛÜŽˆÌYŽNÝ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚŽ‚ˆ<'äbH˜Z\™HXH[X[™H	ØYÜ°ê[Y[\šYÙX[ˆØO‚ˆÜ‚ˆˆˆ‚‚ˆÛ˜\×Ø›ØÚÈHˆ‚ˆYˆÛ˜\×Ú[‚ˆÛ˜\×Ø›ØÚÈHˆˆˆ‚ˆ]ˆÝ[OH˜˜XÚÙÜ›Ý[™ˆÙ™™ÙYØ›Ü™\ŽŒ\ÛÛYÙ™YØXNØ›Ü™\‹\˜Y]\ÎŒMÜY[™ÎŒMÛX\™Ú[ŽŒMœ‚ˆ]ˆÝ[OH™›Û]ÙZYÚŽLÛX\™Ú[ŽŒžØÛ˜\×Ý]_OÙ]‚ˆ]ˆÝ[OH˜ÛÛÜŽˆÌLLNÎÛ[™KZZYÚŒKˆžØÛ˜\×Ú[OÙ]‚ˆÙ]‚ˆˆˆ‚‚ˆÈKKH›ØÈ]š\ÈÛÛÙÛH
ÛÛ˜Z[˜Ø[›ËÛÝ\
HKKBˆ]š\×Ø›ØÚÈHˆˆ‚ˆ]ˆÝ[OH˜˜XÚÙÜ›Ý[™ˆÙXÙ™NØ›Ü™\ŽŒ\ÛÛYØ˜™ÙØ›Ü™\‹\˜Y]\ÎŒMÜY[™ÎŒMÛX\™Ú[ŽŒN‚ˆ]ˆÝ[OH™›Û]ÙZYÚŽLÛX\™Ú[ŽŒ¸«d[ˆ]š\ÈÛÛÙÛK0éØH›Ý\ÈZYH0ê[›Ü›pê[Y[Ù]‚ˆ]ˆÝ[OH˜ÛÛÜŽˆÌYŽÛ[™KZZYÚŒKˆ‚ˆÚHH›Ü›X][Ûˆ›Ý\ÈH0ê]0êH][KÝ]™^‹]›Ý\È™[™™HÝ›Û™ÏŒHZ[]OÜÝ›Û™ÏˆÝ\ˆZ\ÜÙ\ˆ[ˆ]š\ÈÂˆ0áØHZYH\È]\œÈÝYÚXZ\™\È0èÚÚ\Ú\ˆ[™H0êXÛÛHðê\šY]\ÙK]0éØH›Ý\È\›Y]8 &X[pê[[Ü™\ˆ[˜ÛÜ™H›Ý™HXØÛÛ\YÛ™[Y[‚ˆÙ]‚ˆ]ˆÝ[OH^X[YÛŽ˜Ù[\ŽÛX\™Ú[‹]ÜŒLœ‚ˆH™YHšÎ‹ËÙËœYÙKÜ‹ÐÖŒYËY™^V’PQH‚ˆÝ[OH™\Ü^Nš[›[™KX›ØÚÎØ˜XÚÙÜ›Ý[™ˆÌYŽNØÛÛÜŽÚ]NÜY[™ÎŒLMØ›Ü™\‹\˜Y]\ÎŒLÂˆ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚŽL‚ˆ<'äbHZ\ÜÙ\ˆ[ˆ]š\ÈÛÛÙÛBˆØO‚ˆÙ]‚ˆÙ]‚ˆˆˆ‚‚ˆ[HXZ[Û^[Ý]
ˆˆˆ‚ˆˆÝ[OH^X[YÛŽ˜Ù[\ˆ¸§!HÛX™[H\ÜÛšX›OÚ‚‚ˆ›Ûš›Ý\ˆÝ›Û™ÏžÙš\œÝÛ˜[Y_OÜÝ›Û™Ï‹Ü‚‚ˆÝ[OH›X\™Ú[‹]ÜŒLÙ›Û]ÙZYÚŽ‚ˆ<'ã¢H°ê[XÚ]][ÛœÈH›Ý™H\0íYH\ÝXZ[[˜[\ÜÛšX›H[œÈ›Ý™H\ÜXÙHÝYÚXZ\™K‚ˆÜ‚‚ˆ]ˆÝ[OH˜˜XÚÙÜ›Ý[™ˆÙŒÙŽØ›Ü™\ŽŒ\ÛÛYÙMYMÙXŽØ›Ü™\‹\˜Y]\ÎŒLœÜY[™ÎŒMÛX\™Ú[ŽŒMœ‚ˆÝ[OH›X\™Ú[ŽŒL‚ˆÝ›Û™Ï¼'äã›Ü›X][ÛˆÜÝ›Û™ÏˆÙ›Ü›X][Û—Ý\_BˆÜ‚‚ˆÝ[OH›X\™Ú[ŽŒ‚ˆÝ›Û™Ï¼'äãHXØðêY\ˆ0è›Ý™H\ÜXÙHÝYÚXZ\™HÜÝ›Û™Ïœ‚ˆH™YHžÛ[šßHˆÝ[OH˜ÛÛÜŽˆÌYŽNÝ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚ˜›ÛžÛ[šßOØO‚ˆÜ‚ˆÙ]‚‚ˆÝ[OH^X[YÛŽ˜Ù[\ŽÛX\™Ú[‹]ÜŒN‚ˆH™YHžÛ[šßH‚ˆÝ[OH™\Ü^Nš[›[™KX›ØÚÎØ˜XÚÙÜ›Ý[™ˆÌYŽNØÛÛÜŽÚ]NÜY[™ÎŒLœNØ›Ü™\‹\˜Y]\ÎŒLÂˆ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚ˜›Û‚ˆ<'äbHXØðêY\ˆ0è[Ûˆ\ÜXÙHÝYÚXZ\™BˆØO‚ˆÜ‚‚ˆØÛ˜\×Ø›ØÚßB‚ˆØ]š\×Ø›ØÚßB‚ˆÝ[OH›X\™Ú[‹]ÜŒN‚ˆÝ\ˆÝ]H]Y\Ý[Û‹›Ý\ÈÝ]™^ˆ›Ý\ÈÛÛXÝ\ˆ]HÝ›Û™ÏŒŒˆÈÈŽÜÝ›Û™Ï‹‚ˆÜ‚‚ˆÝ[OH›X\™Ú[‹]ÜŒN‚ˆšY[ˆÛÜ™X[[Y[œ‚ˆÝ›Û™ÏÛ0ê[Y[RSS•ÜÝ›Û™Ïœ‚ˆ\™XÝ]\ˆ[0êYÜ˜[HXØY[^BˆÜ‚‚ˆˆÝ[OH›X\™Ú[ŽŒœØ›Ü™\Ž››Û™NØ›Ü™\‹]ÜŒ\ÛÛYÙMYMÙXˆ‚‚ˆÝ[OH™›Û\Ú^™NŒLœØÛÛÜŽˆÍ˜ÌŽÝ^X[YÛŽ˜Ù[\ŽÛ[™KZZYÚŒKˆ‚ˆ0ªH[0êYÜ˜[HXØY[^H8 %Y\˜ÚHH›Ý™HÛÛ™šX[˜ÙH<'ä¦Ïœ‚ˆMÚ[Z[ˆHØ\œ™[ÝHÍQÑUÕTˆT‘ÑS”ÈÈMˆYHHš]›ÛHÍLHT’TÏœ‚ˆH™YHšÎ‹ËÝÝÝËš[YÜ˜[XXØY[^K˜ÛÛH‚ˆÝ[OH˜ÛÛÜŽˆÌYŽNÝ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚ˜›Û‚ˆ[YÜ˜[XXØY[^K˜ÛÛBˆØO‚ˆÜ‚ˆˆˆŠB‚ˆÛ\×Û˜[YHH
˜Z[™YK™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

BˆÛ\ÈH
ˆˆ’[0êYÜ˜[HXØY[^H8§!HÜÛ\×Û˜[YH
È	Ë	ÈYˆÛ\×Û˜[YH[ÙH	ÉßH‚ˆˆ›Ý™HÛX™[H\Ý\ÜÛšX›HÝ\ˆ›Ý™H\ÜXÙHˆÛ[šßH‚ˆˆŠZYHˆŒˆÈÈŽ
H‚ˆ
B‚ˆYˆ
˜Z[™YK™Ù]
™[XZ[ŠHÜˆˆŠKœÝš\

N‚ˆ[XZ[ÜÙ[Hœ™]›×ÜÙ[™Ù[XZ[
˜Z[™YK™Ù]
™[XZ[‹ˆŠKÝXš™XÝ[˜Z[™YO]˜Z[™YJBˆYˆ[XZ[ÜÙ[‚ˆ\ÝÜžHH˜Z[™YK™Ù]
œÙ[Ù[XZ[Ú\ÝÜžHŠHÜˆ×BˆÜ\œÚ\ÝØ[×Ù[XZ[Ú\ÝÜžWÙ[žJˆÙ\ÜÚ[Û—ÚYˆ˜Z[™YWÚYˆ\ÝÜžVÌHYˆ\ÝÜžH[ÙH›Û™Kˆ
BˆYˆ
˜Z[™YK™Ù]
œÛ™HŠHÜˆˆŠKœÝš\

N‚ˆœ™]›×ÜÙ[™ÜÛ\Ê˜Z[™YK™Ù]
œÛ™H‹ˆŠKÛ\ÊB‚ˆ^Ù\^Ù\[Ûˆ\ÈN‚ˆš[
OOH•SÈTÓQNˆ\œ™]\ˆ[›ÚHXZ[ÜÛ\ÈOOH‹™\ŠJJB‚ˆYY˜\[™
Âˆ™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKˆ˜Z[™YWÚYŽˆ˜Z[™YWÚYˆ˜Z[™YWÛ˜[YHŽˆˆžÝ˜Z[™YK™Ù]
	Ùš\œÝÛ˜[YIË	ÉÊ_HÝ˜Z[™YK™Ù]
	Û\ÝÛ˜[YIË	ÉÊ_H‹œÝš\

BˆJB‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKœ™XÙZ]™YŽˆ™XÙZ]™Y˜YYØÛÝ[Žˆ[ŠYY
K˜YYŽˆYY™˜Z[YŽˆ˜Z[YœÙ[™Û›ÝYšXØ][ÛœÈŽˆÙ[™Û›ÝYšXØ][ÛœßJB‚\œÜÝ
‹Ø\KÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹Ø]\Ý][Û‹Ø[×Ý\ØYŠBYZ[—ÛÙÚ[—Ü™\]Z\™YYZ[—ÝÜš]WÜ™\]Z\™Y™Yˆ\WØ]\Ý][Û—Ø[×Ý\ØY
Ù\ÜÚ[Û—ÚYˆÝŠN‚ˆ[\Ü˜XÙX˜XÚÂ‚ˆ]HHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆœÙ\ÜÚ[Û—Û›ÝÙ›Ý[™ŸJK‚ˆš[\ÈH™\]Y\Ý™š[\Ë™Ù]\Ý
™š[\ÈŠBˆYˆ›Ýš[\Î‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››×Ùš[\ÈŸJK‚ˆÙ[™Û›ÝYšXØ][ÛœÈH
™\]Y\Ý™›Ü›K™Ù]
œÙ[™Û›ÝYšXØ][ÛœÈ‹ŒHŠHÜˆŒHŠKœÝš\

K›ÝÙ\Š
H›Ý[ˆÈŒ‹™˜[ÙH‹››È‹››Ûˆ‹›Ù™ˆŸB‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊB‚ˆ™XÙZ]™YHˆYYH×Bˆ˜Z[YH×B‚ˆ›Üˆˆ[ˆš[\Î‚ˆYˆ›ÝˆÜˆ›Ý‹™š[[˜[YN‚ˆÛÛ[YB‚ˆ™XÙZ]™Y
ÏHBˆÜšYÚ[˜[Û˜[YHH‹™š[[˜[YBˆ^HÜØY™WÙ^
ÜšYÚ[˜[Û˜[YJB‚ˆYˆ^›Ý[ˆ
‹œˆ‹‹šœÈ‹‹šœYÈ‹‹œ™ÈŠN‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ™^[œÚ[Ûˆ›Ûˆ]]Üš\ðêYHŸJBˆÛÛ[YB‚ˆ˜Z[™YK™X\ÛÛˆHÛX]ÚÝ˜Z[™YWÙœ›ÛWÙš[[˜[YJ˜Z[™Y\ËÜšYÚ[˜[Û˜[YJBˆYˆ›Ý˜Z[™YN‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ™X\ÛÛˆÜˆ››Ûˆ˜]XÚ0êHŸJBˆÛÛ[YB‚ˆ˜Z[™YWÚYH˜Z[™YK™Ù]
šYŠHÜˆ˜Z[™YK™Ù]
˜Z[™YWÚYŠHÜˆ˜Z[™YK™Ù]
œ\œÛÛ˜[ÚYŠBˆYˆ›Ý˜Z[™YWÚY‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ˜Z[™YWÚY[›Ý]˜X›HŸJBˆÛÛ[YB‚ˆÈ8§!HÚH0êZ°è[™H]\Ý][Û‹Ûˆ‰ðêXÜ˜\ÙH\È
ÈÛˆ‰Ù[›ÚYH\Âˆ^\Ý[™ÈH

˜Z[™YK™Ù]
™[]™\˜X›\ÈŠHÜˆßJK™Ù]
˜]\Ý][Û—Ùš[—Ù›Ü›X][ÛˆŠHÜˆˆŠKœÝš\

BˆYˆ^\Ý[™Î‚ˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆ™0êZ°è[™H]\Ý][Ûˆ^\Ý[H
›Ûˆ™[\XðêYJHŸJBˆÛÛ[YB‚ˆžN‚ˆžN‚ˆ‹œÝ™X[KœÙYZÊ
Bˆ^Ù\^Ù\[ÛŽ‚ˆ\ÜÂ‚ˆÝÜ™YHÜÝÜ™WÙš[JÙ\ÜÚ[Û—ÚY˜Z[™YWÚY™[]™\˜X›\È‹ŠBˆÚÙ[ˆHÝÚÙ[š^™WÜ]
ÝÜ™Y
Bˆ^Ù\^Ù\[Ûˆ\ÈN‚ˆš[
OOH•SÈUTÕUSÓŽˆ\œ™]\ˆÝØÚØYÙHOOHŠBˆ˜XÙX˜XÚËœš[Ù^Ê
Bˆ˜Z[Y˜\[™
È™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKœ™X\ÛÛˆŽˆˆ™\œ™]\ˆÝØÚØYÙNˆÜÝŠJ_HŸJBˆÛÛ[YB‚ˆ˜Z[™YKœÙ]Y˜][
™[]™\˜X›\È‹ßJBˆ˜Z[™YVÈ™[]™\˜X›\È—VÈ˜]\Ý][Û—Ùš[—Ù›Ü›X][Ûˆ—HHÚÙ[‚ˆ˜Z[™YVÈ\]YØ]—HHÛ›Ý×Ú\ÛÊ
B‚ˆÈ8§!HXZ[
ÈÛ\ÂˆYˆÙ[™Û›ÝYšXØ][ÛœÎ‚ˆžN‚ˆ[šÈHˆžÔP“P×ÔÕQS•ÔÔ•SÐTÑKœœÝš\
	ËÉÊ_KÙ\ÜXÙKÞÝ˜Z[™YK™Ù]
	ÜX›X×ÝÚÙ[‰Ë	ÉÊ_H‚ˆX™[HSU‘TP“WÓP‘SÖÈ˜]\Ý][Û—Ùš[—Ù›Ü›X][Ûˆ—B‚ˆš\œÝÛ˜[YHH
˜Z[™YK™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

HÜˆ“XY[YK[ÛœÚY]\ˆ‚ˆÝXš™XÝHˆžÛX™[H\ÜÛšX›H8 $È[0êYÜ˜[HXØY[^H‚‚ˆ[HXZ[Û^[Ý]
ˆˆˆ‚ˆˆÝ[OH^X[YÛŽ˜Ù[\ˆ¸§!HÛX™[H\ÜÛšX›OÚ‚ˆ›Ûš›Ý\ˆÝ›Û™ÏžÙš\œÝÛ˜[Y_OÜÝ›Û™Ï‹Ü‚ˆ¼'äá›Ý™H]\Ý][ÛˆHš[ˆH›Ü›X][Ûˆ\Ý\ÜÛšX›H[œÈ›Ý™H\ÜXÙHÝYÚXZ\™KÜ‚ˆÝ[OH^X[YÛŽ˜Ù[\ŽÛX\™Ú[‹]ÜŒN‚ˆH™YHžÛ[šßHˆÝ[OH™\Ü^Nš[›[™KX›ØÚÎØ˜XÚÙÜ›Ý[™ˆÌYŽNØÛÛÜŽÚ]NÜY[™ÎŒLœNØ›Ü™\‹\˜Y]\ÎŒLÝ^YXÛÜ˜][ÛŽ››Û™NÙ›Û]ÙZYÚ˜›Û‚ˆ<'äbHXØðêY\ˆ0è[Ûˆ\ÜXÙHÝYÚXZ\™BˆØO‚ˆÜ‚ˆˆˆŠB‚ˆÛ\×Û˜[YHH
˜Z[™YK™Ù]
™š\œÝÛ˜[YHŠHÜˆˆŠKœÝš\

BˆÛ\ÈH
ˆˆ’[0êYÜ˜[HXØY[^H8§!HÜÛ\×Û˜[YH
È	Ë	ÈYˆÛ\×Û˜[YH[ÙH	ÉßH‚ˆˆ•›Ý™HÛX™[H\Ý\ÜÛšX›HÝ\ˆ›Ý™H\ÜXÙHÝYÚXZ\™HˆÛ[šßHHšY[0íHX[H[0êYÜ˜[HXØY[^H‚ˆ
B‚ˆYˆ
˜Z[™YK™Ù]
™[XZ[ŠHÜˆˆŠKœÝš\

N‚ˆœ™]›×ÜÙ[™Ù[XZ[
˜Z[™YK™Ù]
™[XZ[‹ˆŠKÝXš™XÝ[˜Z[™YO]˜Z[™YJBˆYˆ
˜Z[™YK™Ù]
œÛ™HŠHÜˆˆŠKœÝš\

N‚ˆœ™]›×ÜÙ[™ÜÛ\Ê˜Z[™YK™Ù]
œÛ™H‹ˆŠKÛ\ÊB‚ˆ^Ù\^Ù\[Ûˆ\ÈN‚ˆš[
OOH•SÈUTÕUSÓŽˆ\œ™]\ˆ[›ÚHXZ[ÜÛ\ÈOOH‹™\ŠJJB‚ˆYY˜\[™
Âˆ™š[[˜[YHŽˆÜšYÚ[˜[Û˜[YKˆ˜Z[™YWÚYŽˆ˜Z[™YWÚYˆ˜Z[™YWÛ˜[YHŽˆˆžÝ˜Z[™YK™Ù]
	Ùš\œÝÛ˜[YIË	ÉÊ_HÝ˜Z[™YK™Ù]
	Û\ÝÛ˜[YIË	ÉÊ_H‹œÝš\

BˆJB‚ˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]JB‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKœ™XÙZ]™YŽˆ™XÙZ]™Y˜YYØÛÝ[Žˆ[ŠYY
K˜YYŽˆYY™˜Z[YŽˆ˜Z[YJB‚‚‚ˆÈOOOOOOOOOOOOOOOOOOOOOOOOBˆÈQHTÔHÜÜÚY\ˆH˜Z\ØXš[]0êBˆÈOOOOOOOOOOOOOOOOOOOOOOOOB•QWÑUWÑ’SHHÜËœ]š›Ú[ŠT”ÒTÕÑT‹™]WÝ˜YKšœÛÛˆŠB—Ý˜YWÛØÚÈH™XY[™Ë”“ØÚÊ
B‚•QWÐU’T×ÐQRS—ÑQUSÈHÂˆ››ÛWØXØÛÛ\YÛ˜]]\ˆŽˆÛ0ê[Y[RSS•‹ˆ™[XZ[Žˆ˜Û[Y[[YÜ˜[XXØY[^K˜ÛÛH‹ˆ[\Û™HŽˆŒŒˆÈÈŽ‹ˆ›Ü™Ø[š\ÛYHŽˆ’[0êYÜ˜[HÛÛ›™XÝ‹ŸB‚™YˆÛ›Ý×Ú\Û×Ý]Ê
HOˆÝŽ‚ˆ™]\›ˆ]][YK™]][YK]Û›ÝÊ
Kœ™\XÙJZXÜ›ÜÙXÛÛ™L
Kš\ÛÙ›Ü›X]

H
È–ˆ‚‚™YˆÝ˜YWÙY˜][ÙÜÜÚY\ŠÜÜÚY\—ÚYˆÜ[Û˜[ÜÝ—HH›Û™JHOˆXÝÜÝ‹[žWN‚ˆ›ÝÈHÛ›Ý×Ú\Û×Ý]Ê
Bˆ™]\›ˆÂˆšYŽˆÜÜÚY\—ÚYÜˆÝŠ]ZY]ZY

JKˆœÝ]]ÙÜÜÚY\ˆŽˆ˜œ›ÝZ[Ûˆ‹ˆ›˜]\™WÙ[X[™HŽˆš[š]X[H‹ˆ˜Ø[™Y]ŽˆÂˆ››ÛWÛ˜Z\ÜØ[˜ÙHŽˆˆ‹››ÛWÝ\ØYÙHŽˆˆ‹œ™[›Û\ÈŽˆˆ‹™]WÛ˜Z\ÜØ[˜ÙHŽˆˆ‹›˜][Û˜[]HŽˆˆ‹ˆ™Ù[œ™HŽˆˆ‹›š]™X]WÙ›Ü›X][ÛˆŽˆˆ‹›š]™X]WØÙ\YšXØ][ÛˆŽˆˆ‹˜Ù\YšXØ][Ûœ×ÛØ[Y\ÈŽˆˆ‹ˆ˜Y™\ÜÙHŽˆˆ‹˜ÛÙWÜÜÝ[Žˆˆ‹š[HŽˆˆ‹[\Û™HŽˆˆ‹™[XZ[Žˆˆ‹œÝ]]Žˆˆ‹˜ÛÛ™[[Û—ØÛÛXÝ]™HŽˆˆ‹›Øš™XÝYœÈŽˆ×BˆKˆ˜Ù\YšXØ][ÛˆŽˆÂˆš[][HŽˆ‘T’QÑPS•8 &QS•‘T’TÑHHðâPÕT’U0âH’U°âQH‹ˆœ›˜ÜŽˆÎH‹ˆ˜Ù\YšXØ]]\ˆŽˆ”ÐÓÕPH“Ô“PUSÓˆ‹ˆ›Ü[ÛˆŽˆ“È‹ˆœ\˜ÛÝ\œ×ÛY[[ÛˆŽˆ“È‹ˆœ™\™\]Z\ÈŽˆˆ‹ˆš\ÙHŽˆ˜ÛÛ\]H‹ˆ˜›ØÜ×Ýš\Ù\ÈŽˆ×BˆKˆ™^\šY[˜Ù\ÈŽˆÞÈ™]WÙX]Žˆˆ‹™\™YHŽˆˆ‹™\ØÜš\[ÛˆŽˆˆŸWKˆš\ÝYšXØ]Yœ×Ù^\šY[˜ÙHŽˆ×Kˆ˜›ØÜ×ØÛÛ\][˜Ù\ÈŽˆÂˆ˜XÝ]š]LHŽˆÈ˜ÛÛ[Y[Z\™\ÈŽˆˆ‹˜ÛÛ\][˜ÙLHŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙLˆŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙLÈŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙMŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸ_Kˆ˜XÝ]š]LˆŽˆÈ˜ÛÛ[Y[Z\™\ÈŽˆˆ‹˜ÛÛ\][˜ÙLHŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙLˆŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙLÈŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙMŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸ_Kˆ˜XÝ]š]LÈŽˆÈ˜ÛÛ[Y[Z\™\ÈŽˆˆ‹˜ÛÛ\][˜ÙLHŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙLˆŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙLÈŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙMŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸ_Kˆ˜XÝ]š]MŽˆÈ˜ÛÛ[Y[Z\™\ÈŽˆˆ‹˜ÛÛ\][˜ÙLHŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙLˆŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙLÈŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙMŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸ_Kˆ˜XÝ]š]MHŽˆÈ˜ÛÛ[Y[Z\™\ÈŽˆˆ‹˜ÛÛ\][˜ÙLHŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙLˆŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙLÈŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸK˜ÛÛ\][˜ÙMŽˆÈš[][HŽˆˆ‹œÝ]]ŽˆˆŸ_BˆKˆœ\˜ÛÝ\œ×Ü™]š\Ú[Û›™[ŽˆÂˆ˜XØÛÛ\YÛ™[Y[Ú[™]šYY[ŽˆÈš]\™\ÈŽˆˆ‹›[Ù[]\ÈŽˆˆŸKˆ˜XØÛÛ\YÛ™[Y[ØÛÛXÝYˆŽˆÈš]\™\ÈŽˆˆ‹›[Ù[]\ÈŽˆˆŸKˆ™›Ü›X][Ûœ×Ü™X[X›\ÈŽˆÈ›Ü™Ø[š\ÛYHŽˆˆ‹š[][HŽˆˆ‹›Øš™XÝYœÈŽˆˆ‹š]\™\ÈŽˆˆŸKˆš[[Y\œÚ[ÛˆŽˆÈ\HŽˆˆ‹œÝXÝ\™HŽˆˆ‹›Øš™XÝYœÈŽˆˆ‹š]\™\ÈŽˆˆŸKˆ˜]]™\×ØXÝ[ÛœÈŽˆˆ‚ˆKˆ˜]š\×ØYZ[ˆŽˆÂˆ™XÚ\Ú[ÛˆŽˆˆ‹›[Ý]˜][ÛˆŽˆˆ‹››ÛWØXØÛÛ\YÛ˜]]\ˆŽˆˆ‹™[XZ[Žˆˆ‹ˆ[\Û™HŽˆˆ‹›Ü™Ø[š\ÛYHŽˆˆ‹™]HŽˆˆ‚ˆKˆ™[™ØYÙ[Y[ŽˆÂˆœÛÝZZ]WØXØÛÛ\YÛ™[Y[Žˆ˜[ÙK˜XØÛÜ™Ø[˜[\ÙHŽˆ˜[ÙKˆ›Y]WÜÚYÛ˜]\™HŽˆˆ‹™]WÜÚYÛ˜]\™HŽˆˆ‹››ÛWÜÚYÛ˜]\™HŽˆˆ‹œÚYÛ˜]\™WÝ˜XÙHŽˆˆ‹œÚYÛ˜]\™WÜÚYÛ™YØ]Žˆˆ‹˜ÛÛ[Y[Z\™\×ÙY˜]›Ü˜X›HŽˆˆ‚ˆKˆ˜Ü™X]YØ]Žˆ›ÝËˆ\]YØ]Žˆ›ÝËˆB‚™YˆÝ˜YWÛØYØ[

HOˆXÝÜÝ‹[žWN‚ˆÚ]Ý˜YWÛØÚÎ‚ˆYˆ›ÝÜËœ]™^\ÝÊQWÑUWÑ’SJN‚ˆ™XÛÝ™\™YÙœ›ÛHHÜ™XÛÝ™\—Ù]WÙš[JQWÑUWÑ’SJBˆYˆ™XÛÝ™\™YÙœ›ÛN‚ˆ™XÛÝ™\™YHÛØYÝ˜[YÚœÛÛ—Ü^[ØY
QWÑUWÑ’SJBˆYˆ\Ú[œÝ[˜ÙJ™XÛÝ™\™YXÝ
N‚ˆYˆ™ÜÜÚY\œÈˆ›Ý[ˆ™XÛÝ™\™YÜˆ›Ý\Ú[œÝ[˜ÙJ™XÛÝ™\™YÈ™ÜÜÚY\œÈ—K\Ý
N‚ˆ™XÛÝ™\™YÈ™ÜÜÚY\œÈ—HH×Bˆ™]\›ˆ™XÛÝ™\™Yˆ]HHÈ™ÜÜÚY\œÈŽˆ×_BˆÝ˜YWÜØ]™WØ[
]JBˆ™]\›ˆ]BˆžN‚ˆÚ]Ü[ŠQWÑUWÑ’SKœˆ‹[˜ÛÙ[™ÏH]‹NŠH\ÈŽ‚ˆ]HHœÛÛ‹›ØY
ŠBˆYˆ›Ý\Ú[œÝ[˜ÙJ]KXÝ
N‚ˆ]HHÈ™ÜÜÚY\œÈŽˆ×_BˆYˆ™ÜÜÚY\œÈˆ›Ý[ˆ]HÜˆ›Ý\Ú[œÝ[˜ÙJ]VÈ™ÜÜÚY\œÈ—K\Ý
N‚ˆ]VÈ™ÜÜÚY\œÈ—HH×Bˆ™]\›ˆ]Bˆ^Ù\^Ù\[ÛŽ‚ˆ˜XÚÝ\HQWÑUWÑ’SH
È‹˜ÛÜœ\ˆˆ
ÈÝŠ[
]][YK™]][YK]Û›ÝÊ
K[Y\Ý[\

JJBˆžN‚ˆÜËœ™\XÙJQWÑUWÑ’SK˜XÚÝ\
Bˆ^Ù\^Ù\[ÛŽ‚ˆ\ÜÂ‚ˆ™XÛÝ™\™YÙœ›ÛHHÜ™XÛÝ™\—Ù]WÙš[JQWÑUWÑ’SJBˆYˆ™XÛÝ™\™YÙœ›ÛN‚ˆ™XÛÝ™\™YHÛØYÝ˜[YÚœÛÛ—Ü^[ØY
QWÑUWÑ’SJBˆYˆ\Ú[œÝ[˜ÙJ™XÛÝ™\™YXÝ
N‚ˆYˆ™ÜÜÚY\œÈˆ›Ý[ˆ™XÛÝ™\™YÜˆ›Ý\Ú[œÝ[˜ÙJ™XÛÝ™\™YÈ™ÜÜÚY\œÈ—K\Ý
N‚ˆ™XÛÝ™\™YÈ™ÜÜÚY\œÈ—HH×Bˆ™]\›ˆ™XÛÝ™\™Y‚ˆ]HHÈ™ÜÜÚY\œÈŽˆ×_BˆÝ˜YWÜØ]™WØ[
]JBˆ™]\›ˆ]B‚™YˆÝ˜YWÜØ]™WØ[
]NˆXÝÜÝ‹[žWJHOˆ›Û™N‚ˆÝÜš]WÚœÛÛ—ÝÚ]Ø˜XÚÝ\ÊQWÑUWÑ’SK]KÝ˜YWÛØÚÊB‚™YˆÝ˜YWÙš[™ÙÜÜÚY\Š]NˆXÝÜÝ‹[žWKÜÜÚY\—ÚYˆÝŠHOˆÜ[Û˜[ÑXÝÜÝ‹[žWWN‚ˆ›Üˆ[ˆ]K™Ù]
™ÜÜÚY\œÈ‹×JN‚ˆYˆ™Ù]
šYŠHOHÜÜÚY\—ÚY‚ˆ™]\›ˆˆ™]\›ˆ›Û™B‚™YˆÝ˜YWÙš[™Û]\ÝÙ›Ü—Ý˜Z[™YJ˜Z[™YWÚYˆÝŠHOˆÜ[Û˜[ÑXÝÜÝ‹[žWWN‚ˆYˆ›Ý˜Z[™YWÚY‚ˆ™]\›ˆ›Û™Bˆ]HHÝ˜YWÛØYØ[

BˆÜÜÚY\œÈHÂˆ›Üˆ[ˆ]K™Ù]
™ÜÜÚY\œÈ‹×JBˆYˆÝŠ
™Ù]
›Y]HŠHÜˆßJK™Ù]
˜Z[™YWÚYŠHÜˆˆŠHOHÝŠ˜Z[™YWÚY
BˆBˆYˆ›ÝÜÜÚY\œÎ‚ˆ™]\›ˆ›Û™BˆÜÜÚY\œËœÛÜ
Ù^O[[X™Hˆ™Ù]
\]YØ]ŠHÜˆ™Ù]
˜Ü™X]YØ]ŠHÜˆˆ‹™]™\œÙOUYJBˆ™]\›ˆÜÜÚY\œÖÌB‚™YˆÜ—Ù\ØØ\J^ˆ[žJHOˆÝŽ‚ˆÈHÝŠ^ÜˆˆŠBˆ™]\›ˆËœ™\XÙJ—‹—ŠKœ™\XÙJŠ‹—
ŠKœ™\XÙJŠH‹—
HŠB‚™YˆØZ[ÜÚ[\WÜŠ[™\Îˆ\ÝÜÝ—JHOˆž]\Î‚ˆÛX[—Û[™\ÈHÛ[™HYˆ\Ú[œÝ[˜ÙJ[™KÝŠH[ÙHÝŠ[™JH›Üˆ[™H[ˆ[™\×BˆYˆ›ÝÛX[—Û[™\Î‚ˆÛX[—Û[™\ÈHÈˆ—B‚ˆØš™XÝÎˆ\ÝØž]\×HH×BˆØš™XÝË˜\[™
ˆŒHØšˆÕ\HÐØ][ÙÈÔYÙ\Èˆˆˆ[™Øš—ˆŠBˆØš™XÝË˜\[™
ˆŒˆØšˆÕ\HÔYÙ\ÈÒÚYÈÌÈ—HÐÛÝ[Hˆ[™Øš—ˆŠBˆØš™XÝË˜\[™
ˆŒÈØšˆÕ\HÔYÙHÔ\™[ˆˆÓYYXP›ÞÌNMH—HÔ™\ÛÝ\˜Ù\ÈÑ›ÛÑŒHˆˆˆÐÛÛ[ÈHˆˆ[™Øš—ˆŠBˆØš™XÝË˜\[™
ˆØšˆÕ\HÑ›ÛÔÝX\HÕ\LHÐ˜\ÙQ›ÛÒ[™]XØHˆ[™Øš—ˆŠB‚ˆHHBˆÛÛ[Û[™\ÈHÈ•‹‹ÑŒHHˆ—Bˆ›Üˆ˜]È[ˆÛX[—Û[™\Î‚ˆ\ÈHÜ˜]ÖÚNšH
ÈLLH›ÜˆH[ˆ˜[™ÙJ[Š˜]ÊKLL
WHÜˆÈˆ—Bˆ›Üˆ\[ˆ\Î‚ˆYˆH‚ˆœ™XZÂˆÛÛ[Û[™\Ë˜\[™
ˆŒHHÌÞ_HH
×Ü—Ù\ØØ\J\
_JHˆŠBˆHOHL‚ˆYˆH‚ˆœ™XZÂˆÛÛ[Û[™\Ë˜\[™
‘UŠBˆÛÛ[H
—ˆ‹š›Ú[ŠÛÛ[Û[™\ÊH
È—ˆŠK™[˜ÛÙJ›][‹LH‹\œ›ÜœÏHœ™\XÙHŠBˆØš™XÝË˜\[™
ˆHØšˆÓ[™ÝÛ[ŠÛÛ[
_HˆÝ™X[Wˆ‹™[˜ÛÙJ˜\ØÚZHŠH
ÈÛÛ[
Èˆ™[™Ý™X[W™[™Øš—ˆŠB‚ˆˆHž]X\œ˜^Jˆ‰T‹LKˆŠBˆÙ™œÙ]ÈHÌBˆ›ÜˆØšˆ[ˆØš™XÝÎ‚ˆÙ™œÙ]Ë˜\[™
[ŠŠJBˆ‹™^[™
ØšŠB‚ˆ™Y—ÜÜÈH[ŠŠBˆÝ[H[ŠØš™XÝÊH
ÈBˆ‹™^[™
ˆž™Y—ŒÝÝ[Wˆ‹™[˜ÛÙJ˜\ØÚZHŠJBˆ‹™^[™
ˆŒMLÍHˆˆŠBˆ›ÜˆÙ™ˆ[ˆÙ™œÙ]ÖÌN—N‚ˆ‹™^[™
ˆžÛÙ™ŽŒLHˆˆ‹™[˜ÛÙJ˜\ØÚZHŠJBˆ‹™^[™
ˆ˜Z[\ˆÔÚ^™HÝÝ[HÔ›ÛÝHˆ—œÝ\™Y—žÞ™Y—ÜÜßW‰IQSÑˆ‹™[˜ÛÙJ˜\ØÚZHŠJBˆ™]\›ˆž]\ÊŠB‚™YˆÝ˜YWÙÜÜÚY\—Ý×Û[™\ÊÜÜÚY\ŽˆXÝÜÝ‹[žWJHOˆ\ÝÜÝ—N‚ˆØ[™Y]HÜÜÚY\‹™Ù]
˜Ø[™Y]‹ßJBˆÙ\YšXØ][ÛˆHÜÜÚY\‹™Ù]
˜Ù\YšXØ][Ûˆ‹ßJBˆ\˜ÛÝ\œÈHÜÜÚY\‹™Ù]
œ\˜ÛÝ\œ×Ü™]š\Ú[Û›™[‹ßJBˆ]š\ÈHÜÜÚY\‹™Ù]
˜]š\×ØYZ[ˆ‹ßJBˆ[™ØYÙ[Y[HÜÜÚY\‹™Ù]
™[™ØYÙ[Y[‹ßJBˆØš™XÝYœÈH‹‹š›Ú[ŠØ[™Y]™Ù]
›Øš™XÝYœÈŠHÜˆ×JBˆ›ØÜ×Ýš\Ù\ÈH‹‹š›Ú[ŠÙ\YšXØ][Û‹™Ù]
˜›ØÜ×Ýš\Ù\ÈŠHÜˆ×JB‚ˆ[™\ÈHÂˆ‘ÔÔÒQTˆHRTÐP’SUHQHTÔ‹ˆˆ’QÜÜÚY\ŽˆÙÜÜÚY\‹™Ù]
	ÚY	Ê_H‹ˆˆ”Ý]]ÜÜÚY\ŽˆÙÜÜÚY\‹™Ù]
	ÜÝ]]ÙÜÜÚY\‰Ê_H‹ˆˆ‹ˆŒKˆ˜]\™HHH[X[™H‹ˆˆ“˜]\™NˆÙÜÜÚY\‹™Ù]
	Û˜]\™WÙ[X[™IÊ_H‹ˆˆ‹ˆŒ‹ˆ[™›Ü›X][ÛœÈÙ[™\˜[\ÈÝ\ˆHØ[™Y]‹ˆˆ“›ÛHH˜Z\ÜØ[˜ÙNˆØØ[™Y]™Ù]
	Û›ÛWÛ˜Z\ÜØ[˜ÙIÊ_H‹ˆˆ“›ÛH	Ý\ØYÙNˆØØ[™Y]™Ù]
	Û›ÛWÝ\ØYÙIÊ_H‹ˆˆ”™[›Û\ÎˆØØ[™Y]™Ù]
	Ü™[›Û\ÉÊ_H‹ˆˆ‘]HH˜Z\ÜØ[˜ÙNˆØØ[™Y]™Ù]
	Ù]WÛ˜Z\ÜØ[˜ÙIÊ_H‹ˆˆ“˜][Û˜[]NˆØØ[™Y]™Ù]
	Û˜][Û˜[]IÊ_H‹ˆˆY™\ÜÙNˆØØ[™Y]™Ù]
	ØY™\ÜÙIÊ_H‹ˆˆÛÙHÜÝ[ˆØØ[™Y]™Ù]
	ØÛÙWÜÜÝ[	Ê_H‹ˆˆ•š[NˆØØ[™Y]™Ù]
	Ýš[IÊ_H‹ˆˆ•[\Û™NˆØØ[™Y]™Ù]
	Ý[\Û™IÊ_H‹ˆˆ‘[XZ[ˆØØ[™Y]™Ù]
	Ù[XZ[	Ê_H‹ˆˆ“Øš™XÝYœÎˆÛØš™XÝYœßH‹ˆˆ‹ˆŒËˆÙ\YšXØ][Ûˆ›Ù™\ÜÚ[Û›™[Hš\ÙYH‹ˆˆ’[][NˆØÙ\YšXØ][Û‹™Ù]
	Ú[][IÊ_H‹ˆˆ”“ÔˆØÙ\YšXØ][Û‹™Ù]
	Ü›˜Ü	Ê_H‹ˆˆÙ\YšXØ]]\ŽˆØÙ\YšXØ][Û‹™Ù]
	ØÙ\YšXØ]]\‰Ê_H‹ˆˆ”\˜ÛÝ\œËÛY[[ÛŽˆØÙ\YšXØ][Û‹™Ù]
	Ü\˜ÛÝ\œ×ÛY[[Û‰Ê_H‹ˆˆ•\HHš\ÙYNˆØÙ\YšXØ][Û‹™Ù]
	Ýš\ÙIÊ_H‹ˆˆ›ØÜÈš\Ù\ÎˆØ›ØÜ×Ýš\Ù\ßH‹ˆˆ‹ˆˆ^\šY[˜Ù\È›Ù™\ÜÚ[Û›™[\ÈÝH\œÛÛ›™[\È‹ˆB‚ˆ›ÜˆY^[ˆ[[Y\˜]JÜÜÚY\‹™Ù]
™^\šY[˜Ù\ÈŠHÜˆ×KÝ\LJN‚ˆ[™\Ë™^[™
Âˆˆ‘^\šY[˜ÙHÚYNˆX]^Ù^™Ù]
	Ù]WÙX]	Ê_H\™YO^Ù^™Ù]
	Ù\™YIÊ_H‹ˆˆ‘\ØÜš\[ÛŽˆÙ^™Ù]
	Ù\ØÜš\[Û‰Ê_H‹ˆJB‚ˆ[™\Ë™^[™
Èˆ‹KˆÜÚ][Û›™[Y[\ˆÛÛ\][˜Ù\È—JBˆ›ØÜÈHÜÜÚY\‹™Ù]
˜›ØÜ×ØÛÛ\][˜Ù\È‹ßJBˆ›ÜˆH[ˆ˜[™ÙJKŠN‚ˆXÝH›ØÜË™Ù]
ˆ˜XÝ]š]^Ú_H‹ßJBˆ[™\Ë˜\[™
ˆXÝ]š]HÚ_NˆŠBˆ›Üˆˆ[ˆ˜[™ÙJKJN‚ˆÛÛ\HXÝ™Ù]
ˆ˜ÛÛ\][˜Ù^ÚŸH‹ßJHYˆ\Ú[œÝ[˜ÙJXÝXÝ
H[ÙHßBˆ[™\Ë˜\[™
ˆˆHÛÛ\][˜ÙHÚŸNˆ[][O^ØÛÛ\™Ù]
	Ú[][IÊ_HÝ]]^ØÛÛ\™Ù]
	ÜÝ]]	Ê_HŠBˆ[™\Ë˜\[™
ˆˆHÛÛ[Y[Z\™\ÎˆÊXÝÜˆßJK™Ù]
	ØÛÛ[Y[Z\™\ÉÊHYˆ\Ú[œÝ[˜ÙJXÝXÝ
H[ÙH	ÉßHŠB‚ˆ[™\Ë™^[™
Âˆˆ‹ˆ‹ˆ\˜ÛÝ\œÈ™]š\Ú[Û›™[‹ˆˆXØÛÛ\YÛ™[Y[[™]šYY[
]\™\ÊNˆÊ\˜ÛÝ\œË™Ù]
	ØXØÛÛ\YÛ™[Y[Ú[™]šYY[	ÊHÜˆßJK™Ù]
	Ú]\™\ÉÊ_H‹ˆˆXØÛÛ\YÛ™[Y[ÛÛXÝYˆ
]\™\ÊNˆÊ\˜ÛÝ\œË™Ù]
	ØXØÛÛ\YÛ™[Y[ØÛÛXÝY‰ÊHÜˆßJK™Ù]
	Ú]\™\ÉÊ_H‹ˆˆ‘›Ü›X][ÛœÈ™X[X›\ÎˆÊ\˜ÛÝ\œË™Ù]
	Ù›Ü›X][Ûœ×Ü™X[X›\ÉÊHÜˆßJK™Ù]
	ÛÜ™Ø[š\ÛYIÊ_HÈÊ\˜ÛÝ\œË™Ù]
	Ù›Ü›X][Ûœ×Ü™X[X›\ÉÊHÜˆßJK™Ù]
	Ú[][IÊ_H‹ˆˆ’[[Y\œÚ[ÛŽˆÊ\˜ÛÝ\œË™Ù]
	Ú[[Y\œÚ[Û‰ÊHÜˆßJK™Ù]
	ÜÝXÝ\™IÊ_H‹ˆˆ]]™\ÈXÝ[ÛœÎˆÜ\˜ÛÝ\œË™Ù]
	Ø]]™\×ØXÝ[ÛœÉÊ_H‹ˆˆ‹ˆËˆ›Ü›][Z\™H	Ø]š\ÈH˜Z\ØXš[]H‹ˆˆ‘XÚ\Ú[ÛŽˆØ]š\Ë™Ù]
	ÙXÚ\Ú[Û‰Ê_H‹ˆˆ“[Ý]˜][ÛŽˆØ]š\Ë™Ù]
	Û[Ý]˜][Û‰Ê_H‹ˆˆXØÛÛ\YÛ˜]]\ŽˆØ]š\Ë™Ù]
	Û›ÛWØXØÛÛ\YÛ˜]]\‰Ê_H
Ø]š\Ë™Ù]
	Ù[XZ[	Ê_KØ]š\Ë™Ù]
	Ý[\Û™IÊ_JH‹ˆˆ‹ˆŽˆXØÛÜ™Ý\ˆ	Ø[˜[\ÙHHH˜Z\ØXš[]H‹ˆˆ”ÛÝZZ]HXØÛÛ\YÛ™[Y[ˆÉÓÝZIÈYˆ[™ØYÙ[Y[™Ù]
	ÜÛÝZZ]WØXØÛÛ\YÛ™[Y[	ÊH[ÙH	Ó›Û‰ßH‹ˆˆÛÛ[Y[Z\™\ÈÚH]š\È0êY˜]›Ü˜X›NˆÙ[™ØYÙ[Y[™Ù]
	ØÛÛ[Y[Z\™\×ÙY˜]›Ü˜X›IÊ_H‹ˆˆXØÛÜ™[˜[\ÙNˆÉÓÝZIÈYˆ[™ØYÙ[Y[™Ù]
	ØXØÛÜ™Ø[˜[\ÙIÊH[ÙH	Ó›Û‰ßH‹ˆˆ”ÚYÛ˜]\™NˆÙ[™ØYÙ[Y[™Ù]
	Û›ÛWÜÚYÛ˜]\™IÊ_HHÙ[™ØYÙ[Y[™Ù]
	Ù]WÜÚYÛ˜]\™IÊ_HHÙ[™ØYÙ[Y[™Ù]
	ÛY]WÜÚYÛ˜]\™IÊ_H‹ˆˆ•˜XÙHÚYÛ˜]\™NˆÙ[™ØYÙ[Y[™Ù]
	ÜÚYÛ˜]\™WÝ˜XÙIÊ_H
Ù[™ØYÙ[Y[™Ù]
	ÜÚYÛ˜]\™WÜÚYÛ™YØ]	Ê_JH‹ˆJBˆ™]\›ˆ[™\Â‚™YˆÛY\™ÙWÙXÝ
˜\ÙNˆXÝÜÝ‹[žWK[˜ÛÛZ[™ÎˆXÝÜÝ‹[žWJHOˆ›Û™N‚ˆ›ÜˆËˆ[ˆ[˜ÛÛZ[™Ëš][\Ê
N‚ˆYˆ\Ú[œÝ[˜ÙJ‹XÝ
H[™\Ú[œÝ[˜ÙJ˜\ÙK™Ù]
ÊKXÝ
N‚ˆÛY\™ÙWÙXÝ
˜\ÙVÚ×KŠBˆ[ÙN‚ˆ˜\ÙVÚ×HH‚‚™YˆÝ˜[Y]WÝ˜YWÙ›Ü—ÜÝX›Z]
ÜÜÚY\ŽˆXÝÜÝ‹[žWJHOˆ\ÝÜÝ—N‚ˆ\œ›ÜœÎˆ\ÝÜÝ—HH×B‚ˆYˆ
ÜÜÚY\‹™Ù]
›˜]\™WÙ[X[™HŠHÜˆˆŠHOHš[š]X[HŽ‚ˆ\œ›ÜœË˜\[™
“˜]\™HHH[X[™HˆÙ][HH˜[]\ˆ[š]X[H\Ý]]Üš\ðêYHŠB‚ˆØ[™Y]HÜÜÚY\‹™Ù]
˜Ø[™Y]‹ßJBˆ™\]Z\™YÙšY[ÈHÂˆ››ÛWÛ˜Z\ÜØ[˜ÙHŽˆ“›ÛHH˜Z\ÜØ[˜ÙH‹ˆœ™[›Û\ÈŽˆ”°ê[›ÛJÊH‹ˆ™]WÛ˜Z\ÜØ[˜ÙHŽˆ‘]HH˜Z\ÜØ[˜ÙH‹ˆ™[XZ[ŽˆY™\ÜÙH[XZ[‹ˆBˆ›ÜˆÙ^KX™[[ˆ™\]Z\™YÙšY[Ëš][\Ê
N‚ˆYˆ›Ý
ÝŠØ[™Y]™Ù]
Ù^JHÜˆˆŠKœÝš\

JN‚ˆ\œ›ÜœË˜\[™
ˆŒpê™H0ê]\H
[™›Ü›X][ÛœÈØ[™Y]
HˆÛX™[HX[œ]X[ŠB‚ˆÙ\YšXØ][ÛˆHÜÜÚY\‹™Ù]
˜Ù\YšXØ][Ûˆ‹ßJBˆYˆ
Ù\YšXØ][Û‹™Ù]
š\ÙHŠHÜˆˆŠHOH˜ÛÛ\]HŽ‚ˆ\œ›ÜœË˜\[™
“HÙ\YšXØ][Ûˆš\ðêYHÚ]0ê™HHÙ\YšXØ][Ûˆ›Ù™\ÜÚ[Û›™[H[œÈÛÛˆ[0êYÜ˜[]0êHŠB‚ˆ^\šY[˜Ù\ÈHÜÜÚY\‹™Ù]
™^\šY[˜Ù\ÈŠHYˆ\Ú[œÝ[˜ÙJÜÜÚY\‹™Ù]
™^\šY[˜Ù\ÈŠK\Ý
H[ÙH×Bˆ\×Ùš[YÙ^\šY[˜ÙHH[žJˆ\Ú[œÝ[˜ÙJ^XÝ
Bˆ[™ÝŠ^™Ù]
™]WÙX]ŠHÜˆˆŠKœÝš\

Bˆ[™ÝŠ^™Ù]
™\™YHŠHÜˆˆŠKœÝš\

Bˆ[™ÝŠ^™Ù]
™\ØÜš\[ÛˆŠHÜˆˆŠKœÝš\

Bˆ›Üˆ^[ˆ^\šY[˜Ù\Âˆ
BˆYˆ›Ý\×Ùš[YÙ^\šY[˜ÙN‚ˆ\œ›ÜœË˜\[™
ŒðêYH0ê]\H
^0ê\šY[˜Ù\ÈHØ[™Y]
Hˆ]H[Ú[œÈ[™H^0ê\šY[˜ÙHÚ]0ê™H™[œÙZYÛ°êYHŠB‚ˆ\ÝYšXØ]YœÈHÜÜÚY\‹™Ù]
š\ÝYšXØ]Yœ×Ù^\šY[˜ÙHŠHYˆ\Ú[œÝ[˜ÙJÜÜÚY\‹™Ù]
š\ÝYšXØ]Yœ×Ù^\šY[˜ÙHŠK\Ý
H[ÙH×BˆYˆ›Ý\ÝYšXØ]YœÎ‚ˆ\œ›ÜœË˜\[™
ŒðêYH0ê]\H
^0ê\šY[˜Ù\ÈHØ[™Y]
Hˆ]H[Ú[œÈ[ˆ\ÝYšXØ]Yˆ	Ù^0ê\šY[˜ÙH›Ù™\ÜÚ[Û›™[HÚ]0ê™H0ê\ÜðêHŠB‚ˆ›ØÜ×ØÛÛ\][˜Ù\ÈHÜÜÚY\‹™Ù]
˜›ØÜ×ØÛÛ\][˜Ù\È‹ßJBˆ›ÜˆXÝ]š]WÚY[ˆ˜[™ÙJKŠN‚ˆXÝ]š]HH›ØÜ×ØÛÛ\][˜Ù\Ë™Ù]
ˆ˜XÝ]š]^ØXÝ]š]WÚYH‹ßJBˆ›ÜˆÛÛ\][˜ÙWÚY[ˆ˜[™ÙJKJN‚ˆÛÛ\][˜ÙHHXÝ]š]K™Ù]
ˆ˜ÛÛ\][˜Ù^ØÛÛ\][˜ÙWÚYH‹ßJBˆYˆ›ÝÝŠÛÛ\][˜ÙK™Ù]
š[][HŠHÜˆˆŠKœÝš\

N‚ˆ\œ›ÜœË˜\[™
ˆˆ0êYH0ê]\H
X›X]HHÜÚ][Û›™[Y[
Hˆ[][0êHX[œ]X[Ý\ˆXÝ]š]0êHØXÝ]š]WÚYKÛÛ\0ê][˜ÙHØÛÛ\][˜ÙWÚYH‚ˆ
BˆYˆ›ÝÝŠÛÛ\][˜ÙK™Ù]
œÝ]]ŠHÜˆˆŠKœÝš\

N‚ˆ\œ›ÜœË˜\[™
ˆˆ0êYH0ê]\H
X›X]HHÜÚ][Û›™[Y[
HˆXÝ]š]0êHX[œ]X[HÝ\ˆXÝ]š]0êHØXÝ]š]WÚYKÛÛ\0ê][˜ÙHØÛÛ\][˜ÙWÚYH‚ˆ
BˆYˆ›ÝÝŠ
XÝ]š]HÜˆßJK™Ù]
˜ÛÛ[Y[Z\™\ÈŠHÜˆˆŠKœÝš\

N‚ˆ\œ›ÜœË˜\[™
ˆˆ0êYH0ê]\H
X›X]HHÜÚ][Û›™[Y[
HˆÛÛ[Y[Z\™HX[œ]X[Ý\ˆXÝ]š]0êHØXÝ]š]WÚYH‚ˆ
B‚ˆYˆ
Ø[™Y]™Ù]
œÝ]]ŠHÜˆˆŠHOHœØ[\šYWÜš]™Hˆ[™ÝŠØ[™Y]™Ù]
˜ÛÛ™[[Û—ØÛÛXÝ]™HŠHÜˆˆŠKœÝš\

N‚ˆ\œ›ÜœË˜\[™
Œpê™H0ê]\H
[™›Ü›X][ÛœÈØ[™Y]
HˆHÛÛ™[[ÛˆÛÛXÝ]™HÚ]™\Ý\ˆšYHÜœÈØ[\špêHHÙXÝ]\ˆš]°êHŠB‚ˆ[™ØYÙ[Y[HÜÜÚY\‹™Ù]
™[™ØYÙ[Y[‹ßJBˆYˆ›Ý›ÛÛ
[™ØYÙ[Y[™Ù]
˜XØÛÜ™Ø[˜[\ÙHŠJN‚ˆ\œ›ÜœË˜\[™
ðêYH0ê]\H
XØÛÜ™	Ø[˜[\ÙJHˆ›Ý\È]™^ˆXØÙ\\ˆ	Ø[˜[\ÙHHÜÜÚY\ˆŠBˆYˆ›ÝÝŠ[™ØYÙ[Y[™Ù]
›Y]WÜÚYÛ˜]\™HŠHÜˆˆŠKœÝš\

N‚ˆ\œ›ÜœË˜\[™
ðêYH0ê]\H
XØÛÜ™	Ø[˜[\ÙJHˆY]HHÚYÛ˜]\™HX[œ]X[ŠBˆYˆ›ÝÝŠ[™ØYÙ[Y[™Ù]
™]WÜÚYÛ˜]\™HŠHÜˆˆŠKœÝš\

N‚ˆ\œ›ÜœË˜\[™
ðêYH0ê]\H
XØÛÜ™	Ø[˜[\ÙJHˆ]HHÚYÛ˜]\™HX[œ]X[HŠBˆYˆ›ÝÝŠ[™ØYÙ[Y[™Ù]
››ÛWÜÚYÛ˜]\™HŠHÜˆˆŠKœÝš\

N‚ˆ\œ›ÜœË˜\[™
ðêYH0ê]\H
XØÛÜ™	Ø[˜[\ÙJHˆ›ÛH]°ê[›ÛHHÚYÛ˜]Z\™HX[œ]X[ÈŠBˆYˆ›ÝÝŠ[™ØYÙ[Y[™Ù]
œÚYÛ˜]\™WÝ˜XÙHŠHÜˆˆŠKœÝš\

HÜˆ›ÝÝŠ[™ØYÙ[Y[™Ù]
œÚYÛ˜]\™WÜÚYÛ™YØ]ŠHÜˆˆŠKœÝš\

N‚ˆ\œ›ÜœË˜\[™
ðêYH0ê]\H
XØÛÜ™	Ø[˜[\ÙJHˆÚYÛ˜]\™H0ê[XÝ›Ûš\]YHØ›YØ]Ú\™HŠBˆ™]\›ˆ\œ›ÜœÂ‚™YˆÝ˜YWÝ\ØYÙ\ŠÜÜÚY\—ÚYˆÝŠHOˆÝŽ‚ˆ˜\ÙHHÜËœ]š›Ú[ŠT”ÒTÕÑT‹\ØYÈ‹˜YH‹ÝŠÜÜÚY\—ÚYÜˆˆŠKœÝš\

JBˆÜË›XZÙY\œÊ˜\ÙK^\ÝÛÚÏUYJBˆ™]\›ˆ˜\ÙB‚™YˆÜÝÜ™WÝ˜YWÙš[JÜÜÚY\—ÚYˆÝ‹ŠHOˆÝŽ‚ˆ\™Ù]Ù\ˆHÝ˜YWÝ\ØYÙ\ŠÜÜÚY\—ÚY
Bˆš[[˜[YHHÙXÝ\™WÙš[[˜[YJ‹™š[[˜[YHÜˆœYXÙWÚ\ÝYšXØ]]™HŠBˆ^HÜØY™WÙ^
š[[˜[YJBˆYˆ^[™^›Ý[ˆSÕÑQÑV‚ˆ˜Z\ÙH˜[YQ\œ›ÜŠ™^[œÚ[Û—Û›ÝØ[ÝÙYŠBˆÝÜ™YÛ˜[YHH]ZY]ZY

Kš^ÎŒLH
È
^ÜˆˆŠBˆ]HÜËœ]š›Ú[Š\™Ù]Ù\‹ÝÜ™YÛ˜[YJBˆ‹œØ]™J]
Bˆ™]\›ˆ]‚\œÜÝ
	ËØ\KÝ˜YKÏÜÜÚY\—ÚY‹Ù^\šY[˜ÙKYØÜËÝ\ØY	ÊB™Yˆ\WÝ˜YWÙ^\šY[˜ÙWÙØÜ×Ý\ØY
ÜÜÚY\—ÚYˆÝŠN‚ˆ]HHÝ˜YWÛØYØ[

BˆÜÜÚY\ˆHÝ˜YWÙš[™ÙÜÜÚY\Š]KÜÜÚY\—ÚY
BˆYˆ›ÝÜÜÚY\Ž‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››ÝÙ›Ý[™ŸJK‚ˆYZ[—ÙY]Û[ÙHH›ÛÛ
Ù\ÜÚ[Û‹™Ù]
	ØYZ[—ÛÙÙÙYÚ[‰ÊJBˆYˆ
ÜÜÚY\‹™Ù]
	ÜÝ]]ÙÜÜÚY\‰ÊHÜˆ	ÉÊKœÝš\

K›ÝÙ\Š
HOH	ÜÛÝ[Z\ÉÈ[™›ÝYZ[—ÙY]Û[ÙN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ˜[™XYWÜÝX›Z]YŸJKÂ‚ˆ[˜ÛÛZ[™×Ùš[\ÈH™\]Y\Ý™š[\Ë™Ù]\Ý
	Ùš[\ÉÊHÜˆ™\]Y\Ý™š[\Ë™Ù]\Ý
	Ùš[IÊBˆ[˜ÛÛZ[™×Ùš[\ÈHÙˆ›Üˆˆ[ˆ[˜ÛÛZ[™×Ùš[\ÈYˆˆ[™‹™š[[˜[YWBˆYˆ›Ý[˜ÛÛZ[™×Ùš[\Î‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ›Z\ÜÚ[™×Ùš[HŸJK‚ˆ\ÝYšXØ]YœÈHÜÜÚY\‹™Ù]
	Ú\ÝYšXØ]Yœ×Ù^\šY[˜ÙIÊHYˆ\Ú[œÝ[˜ÙJÜÜÚY\‹™Ù]
	Ú\ÝYšXØ]Yœ×Ù^\šY[˜ÙIÊK\Ý
H[ÙH×BˆYYH×Bˆ›Üˆˆ[ˆ[˜ÛÛZ[™×Ùš[\Î‚ˆžN‚ˆÝÜ™YHÜÝÜ™WÝ˜YWÙš[JÜÜÚY\—ÚYŠBˆ^Ù\˜[YQ\œ›ÜŽ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ™^[œÚ[Û—Û›ÝØ[ÝÙYŸJKˆÚÙ[ˆHÝÚÙ[š^™WÜ]
ÝÜ™Y
Bˆ[žHHÂˆšYŽˆÝŠ]ZY]ZY

JKˆ›˜[YHŽˆÙXÝ\™WÙš[[˜[YJ‹™š[[˜[YHÜˆš\ÝYšXØ]YˆŠKˆÚÙ[ˆŽˆÚÙ[‹ˆ\ØYYØ]ŽˆÛ›Ý×Ú\Û×Ý]Ê
KˆBˆ\ÝYšXØ]YœË˜\[™
[žJBˆYY˜\[™
[žJB‚ˆÜÜÚY\–ÉÚ\ÝYšXØ]Yœ×Ù^\šY[˜ÙI×HH\ÝYšXØ]YœÂˆÜÜÚY\–ÉÝ\]YØ]	×HHÛ›Ý×Ú\Û×Ý]Ê
BˆÝ˜YWÜØ]™WØ[
]JB‚ˆÜÙ[™Ý˜YWØYZ[—Û›ÝYšXØ][ÛŠˆZ›Ý]H\ÝYšXØ]YŠÊH	Ù^0ê\šY[˜ÙHQH‹ˆÜÜÚY\YÜÜÚY\‹ˆ]Z[Ï^Âˆ››ÛXœ™WÙšXÚY\œÈŽˆ[ŠYY
Kˆ™šXÚY\œÈŽˆ‹‹š›Ú[ŠÝŠ][K™Ù]
›˜[YHŠHÜˆˆŠH›Üˆ][H[ˆYY
KˆKˆ
B‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK™š[\ÈŽˆ\ÝYšXØ]YœË˜YYŽˆYYJB‚\œÜÝ
	ËØ\KÝ˜YKÏÜÜÚY\—ÚY‹Ù^\šY[˜ÙKYØÜËÏØ×ÚY‹Ù[]IÊB™Yˆ\WÝ˜YWÙ^\šY[˜ÙWÙØ×Ù[]JÜÜÚY\—ÚYˆÝ‹Ø×ÚYˆÝŠN‚ˆ]HHÝ˜YWÛØYØ[

BˆÜÜÚY\ˆHÝ˜YWÙš[™ÙÜÜÚY\Š]KÜÜÚY\—ÚY
BˆYˆ›ÝÜÜÚY\Ž‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››ÝÙ›Ý[™ŸJK‚ˆYZ[—ÙY]Û[ÙHH›ÛÛ
Ù\ÜÚ[Û‹™Ù]
	ØYZ[—ÛÙÙÙYÚ[‰ÊJBˆYˆ
ÜÜÚY\‹™Ù]
	ÜÝ]]ÙÜÜÚY\‰ÊHÜˆ	ÉÊKœÝš\

K›ÝÙ\Š
HOH	ÜÛÝ[Z\ÉÈ[™›ÝYZ[—ÙY]Û[ÙN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ˜[™XYWÜÝX›Z]YŸJKÂ‚ˆ\ÝYšXØ]YœÈHÜÜÚY\‹™Ù]
	Ú\ÝYšXØ]Yœ×Ù^\šY[˜ÙIÊHYˆ\Ú[œÝ[˜ÙJÜÜÚY\‹™Ù]
	Ú\ÝYšXØ]Yœ×Ù^\šY[˜ÙIÊK\Ý
H[ÙH×BˆÙ\H×Bˆ[]YH›Û™Bˆ›Üˆ[žH[ˆ\ÝYšXØ]YœÎ‚ˆYˆÝŠ
[žHÜˆßJK™Ù]
	ÚY	ÊHÜˆ	ÉÊHOHÝŠØ×ÚY
N‚ˆ[]YH[žBˆ[ÙN‚ˆÙ\˜\[™
[žJB‚ˆYˆ›Ý[]Y‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››ÝÙ›Ý[™ŸJK‚ˆÚÙ[ˆHÝŠ
[]YÜˆßJK™Ù]
	ÝÚÙ[‰ÊHÜˆ	ÉÊKœÝš\

BˆYˆÚÙ[Ž‚ˆžN‚ˆœHÙ]ÚÙ[š^™WÜ]
ÚÙ[ŠBˆYˆÜËœ]™^\ÝÊœ
N‚ˆÜØY™WÜ™[[Ý™WÙš[Jœ
Bˆ^Ù\^Ù\[ÛŽ‚ˆ\ÜÂ‚ˆÜÜÚY\–ÉÚ\ÝYšXØ]Yœ×Ù^\šY[˜ÙI×HHÙ\ˆÜÜÚY\–ÉÝ\]YØ]	×HHÛ›Ý×Ú\Û×Ý]Ê
BˆÝ˜YWÜØ]™WØ[
]JB‚ˆÜÙ[™Ý˜YWØYZ[—Û›ÝYšXØ][ÛŠˆ”Ý\™\ÜÚ[Ûˆ	Ý[ˆ\ÝYšXØ]Yˆ	Ù^0ê\šY[˜ÙHQH‹ˆÜÜÚY\YÜÜÚY\‹ˆ]Z[Ï^È™šXÚY\ˆŽˆ
[]YÜˆßJK™Ù]
›˜[YHŠHÜˆˆŸKˆ
B‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYK™š[\ÈŽˆÙ\JB‚\™Ù]
	ËØYZ[‹Ý˜YKÏÜÜÚY\—ÚY‹Ù^\šY[˜ÙKYØÜËžš\	ÊBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ý˜YWÙ^\šY[˜ÙWÙØÜ×Þš\
ÜÜÚY\—ÚYˆÝŠN‚ˆ]HHÝ˜YWÛØYØ[

BˆÜÜÚY\ˆHÝ˜YWÙš[™ÙÜÜÚY\Š]KÜÜÚY\—ÚY
BˆYˆ›ÝÜÜÚY\Ž‚ˆX›Ü

B‚ˆ\ÝYšXØ]YœÈHÜÜÚY\‹™Ù]
	Ú\ÝYšXØ]Yœ×Ù^\šY[˜ÙIÊHYˆ\Ú[œÝ[˜ÙJÜÜÚY\‹™Ù]
	Ú\ÝYšXØ]Yœ×Ù^\šY[˜ÙIÊK\Ý
H[ÙH×BˆYˆ›Ý\ÝYšXØ]YœÎ‚ˆX›Ü

B‚ˆYˆHž]\ÒSÊ
BˆÚ]š\š[K–š\š[JY‹	ÝÉËÛÛ\™\ÜÚ[Û^š\š[K–’TÑQ“UQ
H\ÈŽ‚ˆ›ÜˆY[žH[ˆ[[Y\˜]J\ÝYšXØ]YœËÝ\LJN‚ˆÚÙ[ˆHÝŠ
[žHÜˆßJK™Ù]
	ÝÚÙ[‰ÊHÜˆ	ÉÊKœÝš\

BˆYˆ›ÝÚÙ[Ž‚ˆÛÛ[YBˆœHÙ]ÚÙ[š^™WÜ]
ÚÙ[ŠBˆYˆ›ÝÜËœ]™^\ÝÊœ
N‚ˆÛÛ[YBˆÜšYÚ[˜[Û˜[YHHÙXÝ\™WÙš[[˜[YJ
[žHÜˆßJK™Ù]
	Û˜[YIÊHÜˆ	ÉÊBˆ^HÜËœ]œÜ]^
ÜšYÚ[˜[Û˜[YJVÌWHÜˆÜËœ]œÜ]^
œ
VÌWHÜˆ	ÉÂˆ\˜Û˜[YHHˆ’\ÝYšXØ]Y—Ù^\šY[˜ÙWÞÚY^Ù^H‚ˆ‹Üš]Jœ\˜Û˜[YOX\˜Û˜[YJB‚ˆY‹œÙYZÊ
Bˆš\˜[YHHˆ•QWÒ\ÝYšXØ]Yœ×Ñ^\šY[˜ÙWÞÙÜÜÚY\—ÚYKžš\‚ˆ™]\›ˆÙ[™Ùš[JY‹\×Ø]XÚY[UYKÝÛ›ØYÛ˜[YO^š\˜[YKZ[Y]\OIØ\XØ][Û‹Þš\	ÊB‚™YˆÝ˜YWØÜ™X]WØ[™Ü™Y\™XÝÙ›Ü—Ý˜Z[™YWÝÚÙ[Š˜Z[™YWÝÚÙ[ŽˆÝŠN‚ˆ˜Z[™YWÝÚÙ[ˆH
˜Z[™YWÝÚÙ[ˆÜˆ	ÉÊKœÝš\

Bˆ[šÙYÝ˜Z[™YWÚYH	ÉÂˆ[šÙYÜÙ\ÜÚ[Û—ÚYH	ÉÂ‚ˆYˆ˜Z[™YWÝÚÙ[Ž‚ˆ]WÛXZ[ˆHØYÙ]J
BˆËHš[™ÜÙ\ÜÚ[Û—Ø[™Ý˜Z[™YWØžWÝÚÙ[Š]WÛXZ[‹˜Z[™YWÝÚÙ[ŠBˆYˆÈ[™‚ˆ˜Z[š[™×Ý\HHÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠBˆYˆ›Ý™\]Z\™YÙØÜ×Ø\™WÙ\ÜÚ]Y
˜Z[š[™×Ý\KÜÙ\ÜÚ[Û—ÙÙ]
Ë™]WÜÝ\‹ˆŠJN‚ˆX›Ü
ÊBˆ[šÙYÝ˜Z[™YWÚYHÝŠ™Ù]
	ÚY	ÊHÜˆ	ÉÊBˆ[šÙYÜÙ\ÜÚ[Û—ÚYHÝŠË™Ù]
	ÚY	ÊHÜˆ	ÉÊB‚ˆ]HHÝ˜YWÛØYØ[

B‚ˆYˆ[šÙYÝ˜Z[™YWÚY‚ˆ^\Ý[™×ÙÜÜÚY\œÈHÂˆ›Üˆ[ˆ]K™Ù]
™ÜÜÚY\œÈ‹×JBˆYˆÝŠ
™Ù]
›Y]HŠHÜˆßJK™Ù]
˜Z[™YWÚYŠHÜˆˆŠHOH[šÙYÝ˜Z[™YWÚYˆBˆ^\Ý[™×ÙÜÜÚY\œËœÛÜ
Ù^O[[X™Hˆ™Ù]
\]YØ]ŠHÜˆ™Ù]
˜Ü™X]YØ]ŠHÜˆˆ‹™]™\œÙOUYJBˆ›Üˆ^\Ý[™È[ˆ^\Ý[™×ÙÜÜÚY\œÎ‚ˆYˆ
^\Ý[™Ë™Ù]
	ÜÝ]]ÙÜÜÚY\‰ÊHÜˆ	ÉÊKœÝš\

K›ÝÙ\Š
HOH	ÜÛÝ[Z\ÉÎ‚ˆY]HH^\Ý[™ËœÙ]Y˜][
	ÛY]IËßJBˆYˆ˜Z[™YWÝÚÙ[ˆ[™›ÝÝŠY]K™Ù]
	Ý˜Z[™YWÝÚÙ[‰ÊHÜˆ	ÉÊKœÝš\

N‚ˆY]VÉÝ˜Z[™YWÝÚÙ[‰×HH˜Z[™YWÝÚÙ[‚ˆ^\Ý[™ÖÉÝ\]YØ]	×HHÛ›Ý×Ú\Û×Ý]Ê
BˆÝ˜YWÜØ]™WØ[
]JBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ	Ý˜YWÝÚ^˜\™	ËÚÙ[Y^\Ý[™ÖÉÚY	×JJB‚ˆÜÜÚY\ˆHÝ˜YWÙY˜][ÙÜÜÚY\Š
BˆÜÜÚY\‹œÙ]Y˜][
	ÛY]IËßJVÉÛ[šØYÙWÚY	×HHÝŠ]ZY]ZY

JBˆYˆ˜Z[™YWÝÚÙ[Ž‚ˆÜÜÚY\‹œÙ]Y˜][
	ÛY]IËßJVÉÝ˜Z[™YWÝÚÙ[‰×HH˜Z[™YWÝÚÙ[‚ˆYˆ[šÙYÝ˜Z[™YWÚY‚ˆÜÜÚY\–ÉÛY]I×VÉÝ˜Z[™YWÚY	×HH[šÙYÝ˜Z[™YWÚYˆÜÜÚY\–ÉÛY]I×VÉÜÙ\ÜÚ[Û—ÚY	×HH[šÙYÜÙ\ÜÚ[Û—ÚY‚ˆ]KœÙ]Y˜][
™ÜÜÚY\œÈ‹×JKš[œÙ\
ÜÜÚY\ŠBˆÝ˜YWÜØ]™WØ[
]JB‚ˆÜÙ[™Ý˜YWØYZ[—Û›ÝYšXØ][ÛŠˆÜ°êX][Ûˆ	Ý[ˆÜÜÚY\ˆQH\Z\È	Ù\ÜXÙHØ[™Y]‹ˆ˜Z[™YO]Yˆ˜Z[™YWÝÚÙ[ˆ[™	Ý	È[ˆØØ[Ê
H[ÙH›Û™KˆÜÜÚY\YÜÜÚY\‹ˆÙ\ÜÚ[Û—ÛØš\ÈYˆ˜Z[™YWÝÚÙ[ˆ[™	ÜÉÈ[ˆØØ[Ê
H[ÙH›Û™Kˆ]Z[Ï^È›ÜšYÚ[™HŽˆ‘\ÜXÙHØ[™Y]ŸKˆ
B‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ	Ý˜YWÝÚ^˜\™	ËÚÙ[YÜÜÚY\–ÉÚY	×JJB‚‚‚‚\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹Ý˜YKYÜÜÚY\‹ØÜ™Y\ˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—ØÜ™X]WÝ˜YWÙÜÜÚY\ŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝŠN‚ˆ]HHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆX›Ü

B‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆH™^

›Üˆ[ˆ˜Z[™Y\ÈYˆ™Ù]
šYŠHOH˜Z[™YWÚY
K›Û™JBˆYˆ›Ý‚ˆX›Ü

B‚ˆ˜Z[š[™×Ý\HH
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠKœÝš\

K\\Š
BˆYˆ˜Z[š[™×Ý\HOH‘T’QÑPS•QHŽ‚ˆX›Ü

B‚ˆ˜YWÙ]HHÝ˜YWÛØYØ[

BˆÜÜÚY\ˆHÝ˜YWÙY˜][ÙÜÜÚY\Š
BˆÜÜÚY\‹œÙ]Y˜][
›Y]H‹ßJVÈ›[šØYÙWÚY—HHÝŠ]ZY]ZY

JBˆÜÜÚY\–È›Y]H—VÈ˜Z[™YWÚY—HHÝŠ˜Z[™YWÚY
BˆÜÜÚY\–È›Y]H—VÈœÙ\ÜÚ[Û—ÚY—HHÝŠÙ\ÜÚ[Û—ÚY
Bˆ˜Z[™YWÝÚÙ[ˆHÝŠ™Ù]
ÚÙ[ˆŠHÜˆˆŠKœÝš\

BˆYˆ˜Z[™YWÝÚÙ[Ž‚ˆÜÜÚY\–È›Y]H—VÈ˜Z[™YWÝÚÙ[ˆ—HH˜Z[™YWÝÚÙ[‚‚ˆ˜YWÙ]KœÙ]Y˜][
™ÜÜÚY\œÈ‹×JKš[œÙ\
ÜÜÚY\ŠBˆÝ˜YWÜØ]™WØ[
˜YWÙ]JB‚ˆÜÙ[™Ý˜YWØYZ[—Û›ÝYšXØ][ÛŠˆÜ°êX][Ûˆ	Ý[ˆÜÜÚY\ˆQH\ˆ	ØYZ[š\Ý˜][Ûˆ‹ˆ˜Z[™YO]ˆÜÜÚY\YÜÜÚY\‹ˆÙ\ÜÚ[Û—ÛØš\Ëˆ]Z[Ï^È›ÜšYÚ[™HŽˆYZ[š\Ý˜][ÛˆŸKˆ
B‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YWÝÚ^˜\™‹ÚÙ[YÜÜÚY\–ÈšY—KYZ[—ÙY]LJJB‚‚‚\œÜÝ
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÏÙ\ÜÚ[Û—ÚY‹ÜÝYÚXZ\™\ËÏ˜Z[™YWÚY‹Ý˜YKYÜÜÚY\‹ÏÜÜÚY\—ÚY‹Ü™\Ù]ŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ü™\Ù]Ý˜YWÙÜÜÚY\ŠÙ\ÜÚ[Û—ÚYˆÝ‹˜Z[™YWÚYˆÝ‹ÜÜÚY\—ÚYˆÝŠN‚ˆ]WÛXZ[ˆHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]WÛXZ[‹Ù\ÜÚ[Û—ÚY
BˆYˆ›ÝÎ‚ˆX›Ü

B‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆH™^

›Üˆ[ˆ˜Z[™Y\ÈYˆÝŠ™Ù]
šYŠHÜˆˆŠHOHÝŠ˜Z[™YWÚY
JK›Û™JBˆYˆ›Ý‚ˆX›Ü

B‚ˆ˜Z[š[™×Ý\HH
ÜÙ\ÜÚ[Û—ÙÙ]
Ë˜Z[š[™×Ý\H‹ˆŠHÜˆˆŠKœÝš\

K\\Š
BˆYˆ˜Z[š[™×Ý\HOH‘T’QÑPS•QHŽ‚ˆX›Ü

B‚ˆ˜YWÙ]HHÝ˜YWÛØYØ[

BˆÜÜÚY\ˆHÝ˜YWÙš[™ÙÜÜÚY\Š˜YWÙ]KÜÜÚY\—ÚY
BˆYˆ›ÝÜÜÚY\Ž‚ˆX›Ü

B‚ˆY]HHÜÜÚY\‹™Ù]
›Y]HŠHYˆ\Ú[œÝ[˜ÙJÜÜÚY\‹™Ù]
›Y]HŠKXÝ
H[ÙHßBˆYˆÝŠY]K™Ù]
˜Z[™YWÚYŠHÜˆˆŠHOHÝŠ˜Z[™YWÚY
HÜˆÝŠY]K™Ù]
œÙ\ÜÚ[Û—ÚYŠHÜˆˆŠHOHÝŠÙ\ÜÚ[Û—ÚY
N‚ˆX›Ü

B‚ˆ›Üˆ[žH[ˆÜÜÚY\‹™Ù]
š\ÝYšXØ]Yœ×Ù^\šY[˜ÙHŠHYˆ\Ú[œÝ[˜ÙJÜÜÚY\‹™Ù]
š\ÝYšXØ]Yœ×Ù^\šY[˜ÙHŠK\Ý
H[ÙH×N‚ˆÚÙ[ˆHÝŠ
[žHÜˆßJK™Ù]
ÚÙ[ˆŠHÜˆˆŠKœÝš\

BˆYˆÚÙ[Ž‚ˆžN‚ˆœHÙ]ÚÙ[š^™WÜ]
ÚÙ[ŠBˆYˆÜËœ]™^\ÝÊœ
N‚ˆÜØY™WÜ™[[Ý™WÙš[Jœ
Bˆ^Ù\^Ù\[ÛŽ‚ˆ\ÜÂ‚ˆ™\Ù]ÙÜÜÚY\ˆHÝ˜YWÙY˜][ÙÜÜÚY\ŠÜÜÚY\—ÚY
Bˆ™\Ù]ÙÜÜÚY\–È›Y]H—HHXÝ
Y]JBˆ™\Ù]ÙÜÜÚY\–È˜Ü™X]YØ]—HHÜÜÚY\‹™Ù]
˜Ü™X]YØ]ŠHÜˆ™\Ù]ÙÜÜÚY\–È˜Ü™X]YØ]—Bˆ™\Ù]ÙÜÜÚY\–È\]YØ]—HHÛ›Ý×Ú\Û×Ý]Ê
BˆÜÜÚY\‹˜ÛX\Š
BˆÜÜÚY\‹\]J™\Ù]ÙÜÜÚY\ŠBˆÝ˜YWÜØ]™WØ[
˜YWÙ]JB‚ˆšY]ÈH˜YWÜÝ]\×ÝšY]Ê›]œ™]ÌWÝÙÈŠBˆÈ˜YWÜÝ]\È—HHšY]ÖÈšÙ^H—BˆÈ˜YWÜÝ]\×ÛX™[—HHšY]ÖÈ›X™[—BˆÈ˜YWØXÝ[Û—Ù]\È—HHßB‚ˆÈ™[Z\ÙH0è°ê\›ÈHÝ]\È\È0ê]\\ÈQHY™šXÚ0êY\È[œÈ	ØYZ[š\Ý˜][Ûˆ]ÐÓÕPK‚ˆÈÛˆÛÛœÙ\™H\È[™›Ü›X][ÛœÈ	ÚY[]0êHHÝYÚXZ\™KXZ\ÈÛˆY™˜XÙH\È˜[ÛœËˆÈ0êXÚ\Ú[ÛœË]\È][™XØ]]\œÈXÚš\]Y\Èpê\È]H\˜ÛÝ\œÈQK‚ˆ›ÜˆÙ^H[ˆ
ˆ˜YWÚ\žWÙ]H‹ˆ›]œ™]ÌWÝ˜[œÛZ]YÜØÛÝXWØ]‹ˆ›]œ™]Ì—Ý˜[œÛZ]YÜØÛÝXWØ]‹ˆœØÛÝXWÜÝ]\È‹ˆœØÛÝXWÜ›ØÙ\ÜÙYØ]‹ˆœØÛÝXWÜ›ØÙ\ÜÙYØ]ÛX™[‹ˆœØÛÝXWÛ]œ™]Ì—ÜÝ]\È‹ˆœØÛÝXWÛ]œ™]Ì—Ü›ØÙ\ÜÙYØ]‹ˆœØÛÝXWÛ]œ™]Ì—Ü›ØÙ\ÜÙYØ]ÛX™[‹ˆœØÛÝXWØÛÛ\[Y[\žWÙØÝ[Y[×Ü™]šY]×ÜÝ]\È‹ˆœØÛÝXWØÛÛ\[Y[\žWÙØÝ[Y[×Ü™]šY]ÙYØ]‹ˆœØÛÝXWØÛÛ\[Y[\žWÙØÝ[Y[×Ü™]šY]ÙYØ]ÛX™[‹ˆœØÛÝXWØÛÛ\[Y[\žWÙØÝ[Y[×Ü™XÙZ]™YØ]‹ˆœØÛÝXWØYYÙØÝ[Y[È‹ˆœØÛÝXWØÛÛ\[Y[\žWÙØÝ[Y[È‹ˆ˜ÛÛ\[Y[\žWÙØÝ[Y[È‹ˆœØÛÝXWÚY[ˆ‹ˆœØÛÝXWÚY[—Ø]‹ˆ˜YWÜ™[[˜Ù\×ÜÝ]H‹ˆ
N‚ˆœÜ
Ù^K›Û™JBˆÈœØÛÝXWÙ›Ü˜ÙWÝš\ÚX›H—HH˜[ÙB‚ˆ\[™Ý˜Z[™YWÚ\ÝÜžWÙ]™[
“]œ™]H°êZ[š]X[\ðêH‹‘ÜÜÚY\ˆH˜Z\ØXš[]0êHQH™[Z\È0è°ê\›È‹˜XÝ[Ûˆ‹Û›Ý×Ú\ÛÊ
JBˆÖÈ˜Z[™Y\È—HH˜Z[™Y\ÂˆËœÜ
œÝYÚXZ\™\È‹›Û™JBˆØ]™WÙ]J]WÛXZ[ŠB‚ˆÜÙ[™Ý˜YWØYZ[—Û›ÝYšXØ][ÛŠˆ”°êZ[š]X[\Ø][ÛˆH]œ™]HQH‹ˆ˜Z[™YO]ˆÜÜÚY\YÜÜÚY\‹ˆÙ\ÜÚ[Û—ÛØš\Ëˆ]Z[Ï^È˜XÝ[Û—ØYZ[ˆŽˆœ™\Ù]Û]œ™]ÌHŸKˆ
B‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ý˜Z[™YWÜYÙH‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
JB‚\™Ù]
	ËÝ˜YKÛ›Ý]™X]KÏ˜Z[™YWÝÚÙ[‰ÊB™Yˆ˜YWÛ™]×Ù›Ü—Ý˜Z[™YJ˜Z[™YWÝÚÙ[ŽˆÝŠN‚ˆ™]\›ˆÝ˜YWØÜ™X]WØ[™Ü™Y\™XÝÙ›Ü—Ý˜Z[™YWÝÚÙ[Š˜Z[™YWÝÚÙ[ŠB‚‚\™Ù]
	ËÝ˜YKÛ›Ý]™X]IÊB™Yˆ˜YWÛ™]Ê
N‚ˆ˜Z[™YWÝÚÙ[ˆH
™\]Y\Ý˜\™ÜË™Ù]
	Ý˜Z[™YWÝÚÙ[‰ÊHÜˆ	ÉÊKœÝš\

BˆYˆ›Ý˜Z[™YWÝÚÙ[Ž‚ˆ˜Z[™YWÝÚÙ[ˆHÝ˜YWÙ^˜XÝÝ˜Z[™YWÝÚÙ[—Ùœ›ÛWÜ™Y™\™\Š™\]Y\ÝšXY\œË™Ù]
	Ô™Y™\™\‰Ë	ÉÊJBˆ™]\›ˆÝ˜YWØÜ™X]WØ[™Ü™Y\™XÝÙ›Ü—Ý˜Z[™YWÝÚÙ[Š˜Z[™YWÝÚÙ[ŠB‚\™Ù]
	ËÝ˜YKÏÚÙ[‰ÊB™Yˆ˜YWÝÚ^˜\™
ÚÙ[ŽˆÝŠN‚ˆ]HHÝ˜YWÛØYØ[

BˆÜÜÚY\ˆHÝ˜YWÙš[™ÙÜÜÚY\Š]KÚÙ[ŠBˆYˆ›ÝÜÜÚY\Ž‚ˆX›Ü

B‚ˆYZ[—ÙY]Û[ÙHH™\]Y\Ý˜\™ÜË™Ù]
	ØYZ[—ÙY]	ÊHOH	ÌIÈ[™›ÛÛ
Ù\ÜÚ[Û‹™Ù]
	ØYZ[—ÛÙÙÙYÚ[‰ÊJBˆYˆ
ÜÜÚY\‹™Ù]
	ÜÝ]]ÙÜÜÚY\‰ÊHÜˆ	ÉÊKœÝš\

K›ÝÙ\Š
HOH	ÜÛÝ[Z\ÉÈ[™›ÝYZ[—ÙY]Û[ÙN‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ	Ý˜YWÜÝXØÙ\ÜÉËÚÙ[]ÚÙ[ŠJB‚ˆY]HHÜÜÚY\‹™Ù]
	ÛY]IÊHYˆ\Ú[œÝ[˜ÙJÜÜÚY\‹™Ù]
	ÛY]IÊKXÝ
H[ÙHßBˆØ]™WÛ]\—Ý\›H	ÉÂˆYˆYZ[—ÙY]Û[ÙN‚ˆÙ\ÜÚ[Û—ÚYHÝŠY]K™Ù]
	ÜÙ\ÜÚ[Û—ÚY	ÊHÜˆ	ÉÊKœÝš\

Bˆ˜Z[™YWÚYHÝŠY]K™Ù]
	Ý˜Z[™YWÚY	ÊHÜˆ	ÉÊKœÝš\

BˆYˆÙ\ÜÚ[Û—ÚY[™˜Z[™YWÚY‚ˆØ]™WÛ]\—Ý\›H\›Ù›ÜŠ	ØYZ[—Ý˜Z[™YWÜYÙIËÙ\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY˜Z[™YWÚY]˜Z[™YWÚY
Bˆ[ÙN‚ˆ˜Z[™YWÝÚÙ[ˆHÝŠY]K™Ù]
	Ý˜Z[™YWÝÚÙ[‰ÊHÜˆ	ÉÊKœÝš\

BˆYˆ˜Z[™YWÝÚÙ[Ž‚ˆØ]™WÛ]\—Ý\›H\›Ù›ÜŠ	ÜX›X×Ý˜Z[™YWÜÜXÙIËÚÙ[]˜Z[™YWÝÚÙ[ŠB‚ˆ™]\›ˆ™[™\—Ý[\]Jˆ	Ý˜YWÝÚ^˜\™š[	ËˆÜÜÚY\YÜÜÚY\‹ˆÜÜÚY\—ÚœÛÛZœÛÛ‹™[\ÊÜÜÚY\‹[œÝ\™WØ\ØÚZOQ˜[ÙJKˆYZ[—ÙY]Û[ÙOXYZ[—ÙY]Û[ÙKˆØ]™WÛ]\—Ý\›\Ø]™WÛ]\—Ý\›ˆ
B‚\œÜÝ
	ËØ\KÝ˜YKÏÜÜÚY\—ÚY‹ÜØ]™IÊB\œ]Ú
	ËØ\KÝ˜YKÏÜÜÚY\—ÚY‹ÜØ]™IÊB™Yˆ\WÝ˜YWÜØ]™JÜÜÚY\—ÚYˆÝŠN‚ˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJBˆYˆ^[ØY\È›Û™N‚ˆžN‚ˆ^[ØYHœÛÛ‹›ØYÊ
™\]Y\Ý™Ù]Ù]J\×Ý^UYJHÜˆžßHŠKœÝš\

HÜˆžßHŠBˆ^Ù\^Ù\[ÛŽ‚ˆ^[ØYHßBˆYˆ›Ý\Ú[œÝ[˜ÙJ^[ØYXÝ
N‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆš[˜[YÜ^[ØYŸJK‚ˆ]HHÝ˜YWÛØYØ[

BˆÜÜÚY\ˆHÝ˜YWÙš[™ÙÜÜÚY\Š]KÜÜÚY\—ÚY
BˆYˆ›ÝÜÜÚY\Ž‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››ÝÙ›Ý[™ŸJK‚ˆYZ[—ÙY]Û[ÙHH›ÛÛ
Ù\ÜÚ[Û‹™Ù]
	ØYZ[—ÛÙÙÙYÚ[‰ÊJBˆYˆ
ÜÜÚY\‹™Ù]
	ÜÝ]]ÙÜÜÚY\‰ÊHÜˆ	ÉÊKœÝš\

K›ÝÙ\Š
HOH	ÜÛÝ[Z\ÉÈ[™›ÝYZ[—ÙY]Û[ÙN‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ˜[™XYWÜÝX›Z]YŸJKÂ‚ˆÛY\™ÙWÙXÝ
ÜÜÚY\‹^[ØY
B‚ˆÈÛÛ˜Z[\Èpê]Y\ˆðí0êHÙ\™]\‚ˆÜÜÚY\–È›˜]\™WÙ[X[™H—HHš[š]X[H‚ˆØ[™Y]HÜÜÚY\‹™Ù]
˜Ø[™Y]ŠHYˆ\Ú[œÝ[˜ÙJÜÜÚY\‹™Ù]
˜Ø[™Y]ŠKXÝ
H[ÙHßBˆYˆØ[™Y]™Ù]
œÝ]]ŠHOHœØ[\šYWÜš]™HŽ‚ˆØ[™Y]È˜ÛÛ™[[Û—ØÛÛXÝ]™H—HHˆ‚‚ˆ[™ØYÙ[Y[HÜÜÚY\‹™Ù]
™[™ØYÙ[Y[ŠHYˆ\Ú[œÝ[˜ÙJÜÜÚY\‹™Ù]
™[™ØYÙ[Y[ŠKXÝ
H[ÙHßBˆ™[›Û\ÈHÝŠØ[™Y]™Ù]
œ™[›Û\ÈŠHÜˆˆŠKœÝš\

Bˆ›ÛWÝ\ØYÙHHÝŠØ[™Y]™Ù]
››ÛWÝ\ØYÙHŠHÜˆˆŠKœÝš\

Bˆ›ÛWÛ˜Z\ÜØ[˜ÙHHÝŠØ[™Y]™Ù]
››ÛWÛ˜Z\ÜØ[˜ÙHŠHÜˆˆŠKœÝš\

Bˆ[Û˜[YHHˆ‹š›Ú[ŠÜ\›Üˆ\[ˆÜ™[›Û\Ë›ÛWÝ\ØYÙHÜˆ›ÛWÛ˜Z\ÜØ[˜ÙWHYˆ\JKœÝš\

BˆYˆ[Û˜[YN‚ˆ[™ØYÙ[Y[È››ÛWÜÚYÛ˜]\™H—HH[Û˜[YBˆYˆ›ÝÝŠ[™ØYÙ[Y[™Ù]
™]WÜÚYÛ˜]\™HŠHÜˆˆŠKœÝš\

N‚ˆ[™ØYÙ[Y[È™]WÜÚYÛ˜]\™H—HH]][YK™]KÙ^J
Kš\ÛÙ›Ü›X]

BˆÜÜÚY\–È™[™ØYÙ[Y[—HH[™ØYÙ[Y[‚ˆÜÜÚY\–È\]YØ]—HHÛ›Ý×Ú\Û×Ý]Ê
BˆÝ˜YWÜØ]™WØ[
]JBˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKšYŽˆÜÜÚY\—ÚY\]YØ]ŽˆÜÜÚY\–È\]YØ]—_JB‚\œÜÝ
	ËØ\KÝ˜YKÏÜÜÚY\—ÚY‹ÜÝX›Z]	ÊB™Yˆ\WÝ˜YWÜÝX›Z]
ÜÜÚY\—ÚYˆÝŠN‚ˆ]HHÝ˜YWÛØYØ[

BˆÜÜÚY\ˆHÝ˜YWÙš[™ÙÜÜÚY\Š]KÜÜÚY\—ÚY
BˆYˆ›ÝÜÜÚY\Ž‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ››ÝÙ›Ý[™ŸJK‚ˆ\œ›ÜœÈHÝ˜[Y]WÝ˜YWÙ›Ü—ÜÝX›Z]
ÜÜÚY\ŠBˆYˆ\œ›ÜœÎ‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆ˜[ÙK™\œ›ÜœÈŽˆ\œ›ÜœßJK‚ˆÜÜÚY\–ÈœÝ]]ÙÜÜÚY\ˆ—HHœÛÝ[Z\È‚ˆÜÜÚY\–È\]YØ]—HHÛ›Ý×Ú\Û×Ý]Ê
BˆÝ˜YWÜØ]™WØ[
]JB‚ˆY]HHÜÜÚY\‹™Ù]
	ÛY]IÊHÜˆßBˆ˜Z[™YWÚYHÝŠY]K™Ù]
	Ý˜Z[™YWÚY	ÊHÜˆ	ÉÊBˆÙ\ÜÚ[Û—ÚYHÝŠY]K™Ù]
	ÜÙ\ÜÚ[Û—ÚY	ÊHÜˆ	ÉÊB‚ˆ]WÛXZ[ˆHØYÙ]J
BˆÈHš[™ÜÙ\ÜÚ[ÛŠ]WÛXZ[‹Ù\ÜÚ[Û—ÚY
HYˆÙ\ÜÚ[Û—ÚY[ÙH›Û™BˆH›Û™B‚ˆYˆÈ[™˜Z[™YWÚY‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆH™^

›Üˆ[ˆ˜Z[™Y\ÈYˆÝŠ™Ù]
	ÚY	ÊHÜˆ	ÉÊHOH˜Z[™YWÚY
K›Û™JBˆ[ÙN‚ˆ˜Z[™YWÝÚÙ[ˆHÝŠY]K™Ù]
	Ý˜Z[™YWÝÚÙ[‰ÊHÜˆ	ÉÊKœÝš\

BˆYˆ˜Z[™YWÝÚÙ[Ž‚ˆËHš[™ÜÙ\ÜÚ[Û—Ø[™Ý˜Z[™YWØžWÝÚÙ[Š]WÛXZ[‹˜Z[™YWÝÚÙ[ŠBˆYˆÈ[™‚ˆ˜Z[™YWÚYHÝŠ™Ù]
	ÚY	ÊHÜˆ	ÉÊBˆÙ\ÜÚ[Û—ÚYHÝŠË™Ù]
	ÚY	ÊHÜˆ	ÉÊBˆÜÜÚY\‹œÙ]Y˜][
	ÛY]IËßJVÉÝ˜Z[™YWÚY	×HH˜Z[™YWÚYˆÜÜÚY\‹œÙ]Y˜][
	ÛY]IËßJVÉÜÙ\ÜÚ[Û—ÚY	×HHÙ\ÜÚ[Û—ÚYˆÜÜÚY\–ÉÝ\]YØ]	×HHÛ›Ý×Ú\Û×Ý]Ê
BˆÝ˜YWÜØ]™WØ[
]JB‚ˆYˆÈ[™‚ˆ˜Z[™Y\ÈHÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
ÊBˆÝ\œ™[Ý˜Z[™YWÚYHÝŠ™Ù]
	ÚY	ÊHÜˆ	ÉÊBˆH™^

›Üˆ[ˆ˜Z[™Y\ÈYˆÝŠ™Ù]
	ÚY	ÊHÜˆ	ÉÊHOHÝ\œ™[Ý˜Z[™YWÚY
K
B‚ˆ™]š[Ý\×ÜÝ]\ÈH˜YWÜÝ]\×ÝšY]Ê™Ù]
	Ý˜YWÜÝ]\ÉÊHÜˆ™Ù]
	Ý˜YWÜÝ]\×ÛX™[	ÊJVÉÚÙ^I×BˆšY]ÈH˜YWÜÝ]\×ÝšY]Ê	Û]œ™]ÌWØ[˜[\Ú\ÉÊBˆÉÝ˜YWÜÝ]\É×HHšY]ÖÉÚÙ^I×BˆÉÝ˜YWÜÝ]\×ÛX™[	×HHšY]ÖÉÛX™[	×BˆYˆ›Ý\Ú[œÝ[˜ÙJ™Ù]
	Ý˜YWØXÝ[Û—Ù]\ÉÊKXÝ
N‚ˆÉÝ˜YWØXÝ[Û—Ù]\É×HHßBˆYˆ›ÝÉÝ˜YWØXÝ[Û—Ù]\É×K™Ù]
	Û]œ™]ÌWÜ™XÙZ]™Y	ÊN‚ˆÉÝ˜YWØXÝ[Û—Ù]\É×VÉÛ]œ™]ÌWÜ™XÙZ]™Y	×HHœ—Ù]J]][YK™]][YK]Û›ÝÊ
KœÝ™[YJ	ÉVKI[KIY	ÊJBˆ\[™Ý˜Z[™YWÚ\ÝÜžWÙ]™[
‘ÜÜÚY\ˆ0ê\ÜðêH\ˆHØ[™Y]‹“]œ™]HÛÝ[Z\È‹˜XÝ[Ûˆ‹Û›Ý×Ú\ÛÊ
JBˆ˜Z[™YWÙ\Ü^WÛ˜[YHHÙ›Ü›X]Ý˜Z[™YWÛ˜[YJ™Ù]
	Ùš\œÝÛ˜[YIË	ÉÊK™Ù]
	Û\ÝÛ˜[YIË	ÉÊJBˆYØYZ[—Û›ÝYšXØ][ÛŠˆ]WÛXZ[‹ˆˆ•QH]œ™]{î#ø èÈ0ê\ÜðêH\ˆÝ˜Z[™YWÙ\Ü^WÛ˜[Y_H‹ˆY]O^Âˆ	Ý\IÎˆ	Ý˜YWÛ]œ™]ÌWÜÝX›Z]	Ëˆ	ÜÙ\ÜÚ[Û—ÚY	ÎˆË™Ù]
	ÚY	ÊKˆ	Ý˜Z[™YWÚY	Îˆ™Ù]
	ÚY	ÊKˆ	Ý˜YWÙÜÜÚY\—ÚY	ÎˆÜÜÚY\—ÚYˆKˆ
BˆÜÙ[™Ý˜YWØYZ[—Û›ÝYšXØ][ÛŠˆ‘›Ü›][Z\™HQHÛÝ[Z\È‹ˆ˜Z[™YO]ˆÜÜÚY\YÜÜÚY\‹ˆÙ\ÜÚ[Û—ÛØš\Ëˆ]Z[Ï^ÂˆœÝ]]Ýš\ÙHŽˆšY]ÖÉÛX™[	×Kˆ™]WÜ™XÙ\[Û—Û]œ™]ÌHŽˆÉÝ˜YWØXÝ[Û—Ù]\É×K™Ù]
	Û]œ™]ÌWÜ™XÙZ]™Y	ÊHÜˆˆ‹ˆKˆ
BˆÖÉÝ˜Z[™Y\É×HH˜Z[™Y\ÂˆËœÜ
	ÜÝYÚXZ\™\ÉË›Û™JBˆØ]™WÙ]J]WÛXZ[ŠB‚ˆYˆ™]š[Ý\×ÜÝ]\ÈOHšY]ÖÉÚÙ^I×N‚ˆÛ›ÝYžWÝ˜YWÜÝ]\×ØÚ[™ÙJšY]ÖÉÚÙ^I×JBˆ[ÙN‚ˆš[
ˆˆ–ÕQWVÑSPRSHÝ]][˜Ú[™ðêH\°êÈÛÝ[Z\ÜÚ[Ûˆ]œ™]K\È	Ù[XZ[[›ÞpêNˆ‚ˆˆ˜Z[™YWÚY^ØÝ\œ™[Ý˜Z[™YWÚY\ŸHÝ]\Ï^ÝšY]ÖÉÚÙ^I×H\ŸH‚ˆ
Bˆ[ÙN‚ˆÜÙ[™Ý˜YWØYZ[—Û›ÝYšXØ][ÛŠˆ‘›Ü›][Z\™HQHÛÝ[Z\È‹ˆÜÜÚY\YÜÜÚY\‹ˆ]Z[Ï^Âˆ˜]™\\ÜÙ[Y[Žˆ“XZ\ÛÛˆÙ\ÜÚ[Û‹ÜÝYÚXZ\™H[›Ý]˜X›H‹ˆœÙ\ÜÚ[Û—ÚYŽˆÙ\ÜÚ[Û—ÚYˆ˜Z[™YWÚYŽˆ˜Z[™YWÚYˆKˆ
Bˆš[
ˆˆ–ÕQWVÑSPRSHXZ\ÛÛˆÙ\ÜÚ[Û‹ÜÝYÚXZ\™H[›Ý]˜X›H\°êÈÛÝ[Z\ÜÚ[Ûˆ]œ™]Nˆ‚ˆˆ™ÜÜÚY\—ÚY^ÙÜÜÚY\—ÚY\ŸHÙ\ÜÚ[Û—ÚY^ÜÙ\ÜÚ[Û—ÚY\ŸH˜Z[™YWÚY^Ý˜Z[™YWÚY\ŸH‚ˆ
B‚ˆ™]\›ˆœÛÛšYžJÈ›ÚÈŽˆYKœ™Y\™XÝÝ\›Žˆ\›Ù›ÜŠ	Ý˜YWÜÝXØÙ\ÜÉËÚÙ[YÜÜÚY\—ÚY
_JB‚\™Ù]
	ËÝ˜YKÏÚÙ[‹ÜÝXØÙ\ÉÊB™Yˆ˜YWÜÝXØÙ\ÜÊÚÙ[ŽˆÝŠN‚ˆ]HHÝ˜YWÛØYØ[

BˆÜÜÚY\ˆHÝ˜YWÙš[™ÙÜÜÚY\Š]KÚÙ[ŠBˆYˆ›ÝÜÜÚY\Ž‚ˆX›Ü

Bˆ˜Z[™YWÜÜXÙWÝ\›H›Û™BˆY]HHÜÜÚY\‹™Ù]
	ÛY]IÊHÜˆßBˆ˜Z[™YWÝÚÙ[ˆH
Y]K™Ù]
	Ý˜Z[™YWÝÚÙ[‰ÊHÜˆ	ÉÊKœÝš\

BˆYˆ˜Z[™YWÝÚÙ[Ž‚ˆ˜Z[™YWÜÜXÙWÝ\›H\›Ù›ÜŠ	ÜX›X×Ý˜Z[™YWÜÜXÙIËÚÙ[]˜Z[™YWÝÚÙ[ŠBˆ™]\›ˆ™[™\—Ý[\]J	Ý˜YWÜÝXØÙ\ÜËš[	ËÜÜÚY\YÜÜÚY\‹˜Z[™YWÜÜXÙWÝ\›]˜Z[™YWÜÜXÙWÝ\›
B‚\™Ù]
	ËØYZ[‹Ý˜YIÊBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ý˜YWÛ\Ý

N‚ˆ]HHÝ˜YWÛØYØ[

BˆÜÜÚY\œÈHÛÜY
]K™Ù]
™ÜÜÚY\œÈ‹×JKÙ^O[[X™Hˆ™Ù]
\]YØ]‹ˆŠK™]™\œÙOUYJBˆ™]\›ˆ™[™\—Ý[\]J	ØYZ[—Ý˜YWÛ\Ýš[	ËÜÜÚY\œÏYÜÜÚY\œÊB‚\œ›Ý]J	ËØYZ[‹Ý˜YKÏÜÜÚY\—ÚY‰ËY]ÙÏVÉÑÑU	Ë	ÔÔÕ	×JBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ý˜YWÙ]Z[
ÜÜÚY\—ÚYˆÝŠN‚ˆ]HHÝ˜YWÛØYØ[

BˆÜÜÚY\ˆHÝ˜YWÙš[™ÙÜÜÚY\Š]KÜÜÚY\—ÚY
BˆYˆ›ÝÜÜÚY\Ž‚ˆX›Ü

B‚ˆYˆ™\]Y\Ý›Y]ÙOH	ÔÔÕ	Î‚ˆXÝ[ÛˆH™\]Y\Ý™›Ü›K™Ù]
	ØXÝ[Û‰Ë	ÉÊKœÝš\

Bˆ™Y\™XÝÙ[™Ú[H›Û™Bˆ™Y\™XÝÚÝØ\™ÜÈHßBˆ›ÝYšXØ][Û—ØXÝ[ÛˆH“Z\ÙH0è›Ý\ˆÜÜÚY\ˆQH‚ˆ›ÝYšXØ][Û—Ù]Z[ÈHÈ˜XÝ[Û—ØYZ[ˆŽˆXÝ[ÛŸBˆYˆXÝ[ÛˆOH	Ý\]WØ]š\ÉÎ‚ˆ]š\ÈHÜÜÚY\‹œÙ]Y˜][
	Ø]š\×ØYZ[‰ËßJBˆ]š\ÖÉÙXÚ\Ú[Û‰×HH™\]Y\Ý™›Ü›K™Ù]
	ÙXÚ\Ú[Û‰Ë	ÉÊKœÝš\

Bˆ]š\ÖÉÛ[Ý]˜][Û‰×HH™\]Y\Ý™›Ü›K™Ù]
	Û[Ý]˜][Û‰Ë	ÉÊKœÝš\

Bˆ]š\ÖÉÛ›ÛWØXØÛÛ\YÛ˜]]\‰×HH™\]Y\Ý™›Ü›K™Ù]
	Û›ÛWØXØÛÛ\YÛ˜]]\‰Ë	ÉÊKœÝš\

Bˆ]š\ÖÉÙ[XZ[	×HH™\]Y\Ý™›Ü›K™Ù]
	Ù[XZ[	Ë	ÉÊKœÝš\

Bˆ]š\ÖÉÝ[\Û™I×HH™\]Y\Ý™›Ü›K™Ù]
	Ý[\Û™IË	ÉÊKœÝš\

Bˆ]š\ÖÉÛÜ™Ø[š\ÛYI×HH™\]Y\Ý™›Ü›K™Ù]
	ÛÜ™Ø[š\ÛYIË	ÉÊKœÝš\

Bˆ]š\ÖÉÙ]I×HH™\]Y\Ý™›Ü›K™Ù]
	Ù]IË	ÉÊKœÝš\

Bˆ›ÝYšXØ][Û—ØXÝ[ÛˆH]š\ÈYZ[š\Ý˜]YˆQHZ\È0è›Ý\ˆ‚ˆ›ÝYšXØ][Û—Ù]Z[Ë\]JÂˆ™XÚ\Ú[ÛˆŽˆ]š\ÖÉÙXÚ\Ú[Û‰×Kˆ™]WØ]š\ÈŽˆ]š\ÖÉÙ]I×Kˆ˜XØÛÛ\YÛ˜]]\ˆŽˆ]š\ÖÉÛ›ÛWØXØÛÛ\YÛ˜]]\‰×KˆJBˆY]HHÜÜÚY\‹™Ù]
	ÛY]IÊHÜˆßBˆÙ\ÜÚ[Û—ÚYHÝŠY]K™Ù]
	ÜÙ\ÜÚ[Û—ÚY	ÊHÜˆ	ÉÊKœÝš\

Bˆ˜Z[™YWÚYHÝŠY]K™Ù]
	Ý˜Z[™YWÚY	ÊHÜˆ	ÉÊKœÝš\

BˆYˆÙ\ÜÚ[Û—ÚY[™˜Z[™YWÚY‚ˆ™Y\™XÝÙ[™Ú[H	ØYZ[—Ý˜Z[™YWÜYÙIÂˆ™Y\™XÝÚÝØ\™ÜÈHÉÜÙ\ÜÚ[Û—ÚY	ÎˆÙ\ÜÚ[Û—ÚY	Ý˜Z[™YWÚY	Îˆ˜Z[™YWÚYBˆ[YˆXÝ[ÛˆOH	ÛX\š×Ü™XÙ]˜X›IÎ‚ˆÜÜÚY\–ÉÜÝ]]ÙÜÜÚY\‰×HH	Ü™XÙ]˜X›IÂˆ›ÝYšXØ][Û—ØXÝ[ÛˆH‘ÜÜÚY\ˆQHX\œ]pêH™XÙ]˜X›H‚ˆ[YˆXÝ[ÛˆOH	ÛX\š×Ü™Y\ÙIÎ‚ˆÜÜÚY\–ÉÜÝ]]ÙÜÜÚY\‰×HH	Ü™Y\ÙIÂˆ›ÝYšXØ][Û—ØXÝ[ÛˆH‘ÜÜÚY\ˆQHX\œ]pêH™Y\ðêH‚ˆÜÜÚY\–ÉÝ\]YØ]	×HHÛ›Ý×Ú\Û×Ý]Ê
BˆÝ˜YWÜØ]™WØ[
]JBˆÜÙ[™Ý˜YWØYZ[—Û›ÝYšXØ][ÛŠ›ÝYšXØ][Û—ØXÝ[Û‹ÜÜÚY\YÜÜÚY\‹]Z[Ï[›ÝYšXØ][Û—Ù]Z[ÊBˆYˆ™Y\™XÝÙ[™Ú[‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ™Y\™XÝÙ[™Ú[
Šœ™Y\™XÝÚÝØ\™ÜÊJBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ	ØYZ[—Ý˜YWÙ]Z[	ËÜÜÚY\—ÚYYÜÜÚY\—ÚY
JB‚ˆ]š\×ØYZ[ˆHXÝ
ÜÜÚY\‹™Ù]
	Ø]š\×ØYZ[‰ÊHÜˆßJBˆ›ÜˆÙ^KY˜][Ý˜[YH[ˆQWÐU’T×ÐQRS—ÑQUSËš][\Ê
N‚ˆYˆ›ÝÝŠ]š\×ØYZ[‹™Ù]
Ù^JHÜˆ	ÉÊKœÝš\

N‚ˆ]š\×ØYZ[–ÚÙ^WHHY˜][Ý˜[YBˆYˆ›ÝÝŠ]š\×ØYZ[‹™Ù]
	Ù]IÊHÜˆ	ÉÊKœÝš\

N‚ˆ]š\×ØYZ[–ÉÙ]I×HH]][YK™]][YK››ÝÊ
KœÝ™[YJ	ÉVKI[KIY	ÊB‚ˆ™]\›ˆ™[™\—Ý[\]J	ØYZ[—Ý˜YWÙ]Z[š[	ËÜÜÚY\YÜÜÚY\‹]š\×ØYZ[X]š\×ØYZ[ŠB‚\™Ù]
	ËØYZ[‹Ý˜YKÏÜÜÚY\—ÚY‹Ù^Ü	ÊBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ý˜YWÙ^Ü
ÜÜÚY\—ÚYˆÝŠN‚ˆ]HHÝ˜YWÛØYØ[

BˆÜÜÚY\ˆHÝ˜YWÙš[™ÙÜÜÚY\Š]KÜÜÚY\—ÚY
BˆYˆ›ÝÜÜÚY\Ž‚ˆX›Ü

B‚ˆÝ]]ÛX™[ÈHÂˆ˜œ›ÝZ[ÛˆŽˆœ›ÝZ[Ûˆ‹ˆœÛÝ[Z\ÈŽˆ”ÛÝ[Z\È‹ˆœ™XÙ]˜X›HŽˆ”™XÙ]˜X›H‹ˆœ™Y\ÙHŽˆ”™Y\ðêH‹ˆBˆXÚ\Ú[Û—ÛX™[ÈHÂˆ™˜Z\ØX›HŽˆ‘˜Z\ØX›H‹ˆ™˜Z\ØX›WØÛÛ\[Y[ÈŽˆ‘˜Z\ØX›H]™XÈÛÛ\0ê[Y[È‹ˆ››Û—Ù˜Z\ØX›HŽˆ“›Ûˆ˜Z\ØX›H‹ˆB‚ˆ™]\›ˆ™[™\—Ý[\]Jˆ	ØYZ[—Ý˜YWÙ^Üš[	ËˆÜÜÚY\YÜÜÚY\‹ˆÝ]]ÛX™[Ï\Ý]]ÛX™[ËˆXÚ\Ú[Û—ÛX™[ÏYXÚ\Ú[Û—ÛX™[Ëˆ[›™^ÜYÙ\ÏLKˆ
B‚‘TÔÕRS’S‘×ÔPÕWÓSRUH‘TÔÓÑ‘’PÒPSÔPÕWÔUQTÕSÓ—ÔÑPÓÓ‘ÈHB‘TÔÕRS’S‘×ÔPÕWÔUQTÕSÓ”ÈHÂˆÈœ]Y\Ý[ÛˆŽˆ”]Y[H]]Üš]0êH0ê[]œ™H	Ø]]Üš\Ø][Ûˆ	Ù^\˜Ù\ˆ	Ý[™H[™\š\ÙHHðêXÝ\š]0êHš]°êYHÈ‹˜ÚÚXÙ\ÈŽˆÈ“HÓTÈ‹“H°êY™XÝ\™H‹“HXZ\šYH‹“HÚ[Xœ™HHÛÛ[Y\˜ÙH—K˜[œÝÙ\ˆŽˆKˆÈœ]Y\Ý[ÛˆŽˆ”[™[ÛÛXšY[ˆH[\È\ÈØÝ[Y[È™[]YœÈ]HÛÛ°íH\ÈØ[\špê\ÈÚ]™[Z[È™\Ý\ˆXØÙ\ÜÚX›\ÈÈ‹˜ÚÚXÙ\ÈŽˆÈ•[ˆ[Ú\È‹•[ˆ[ˆ‹”Ù[Ûˆ\È\°êY\È0êYØ[\È\XØX›\È‹’[È™HÛÛ˜[XZ\ÈÛÛœÙ\°ê\È—K˜[œÝÙ\ˆŽˆŸKˆÈœ]Y\Ý[ÛˆŽˆ”]Y[š[˜Ú\HÚ]ÝZY\ˆH\šYÙX[ÜœÈHHÛÛXÝHHÛ›°êY\È\œÛÛ›™[\ÈÈ‹˜ÚÚXÙ\ÈŽˆÈÛÛXÝ\ˆÝ]\È\ÈÛ›°êY\ÈÜÜÚX›\È‹“[Z]\ˆHÛÛXÝH]^Û›°êY\È°êXÙ\ÜØZ\™\È‹”\YÙ\ˆ\ÈÛ›°êY\È]™XÈÝ\È\ÈÛY[È‹ÛÛœÙ\™\ˆ\ÈÛ›°êY\ÈØ[œÈ[Z]H—K˜[œÝÙ\ˆŽˆ_KˆÈœ]Y\Ý[ÛˆŽˆ]˜[	ØY™™XÝ\ˆ[ˆYÙ[0è[™HZ\ÜÚ[Û‹H\šYÙX[Ú]›Ý[[Y[°ê\šYšY\ˆˆ‹˜ÚÚXÙ\ÈŽˆÈ”ØHØ\H›Ù™\ÜÚ[Û›™[H[ˆÛÝ\œÈH˜[Y]0êH‹”ÛÛˆ\›Z\ÈHÛÛœÝZ\™H‹”ÛÛˆ[œØÜš\[Ûˆ0ê[XÝÜ˜[H‹”ÛÛˆX›Û›™[Y[H˜[œÜÜ—K˜[œÝÙ\ˆŽˆKˆÈœ]Y\Ý[ÛˆŽˆ‘[ˆØ\È	Ú[˜ÚY[Ý\ˆ[™H™\Ý][Û‹]Y[HXÝ[Ûˆ\Ýš[Üš]Z\™HÝ\ˆH\šYÙX[È‹˜ÚÚXÙ\ÈŽˆÈ”Ý\š[Y\ˆÝ]H˜XÙH‹][™™HHš[ˆHÛÛ˜]‹”ðêXÝ\š\Ù\‹ÛÛœÚYÛ™\ˆ\È˜Z]È]\\]Y\ˆ\È›ØðêY\™\È‹”X›Y\ˆ[[pêYX][Y[Ý\ˆ\È°ê\ÙX]^ÛØÚX]^—K˜[œÝÙ\ˆŽˆŸK—B‚‚™YˆÚ\×Ù\ÜÚ[š]X[ÜÙ\ÜÚ[ÛŠÙ\ÜÚ[Û—ÛØšŽˆXÝÜÝ‹[žWJHOˆ›ÛÛ‚ˆ\ØÜš\ÜˆHˆž×ÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹	Ý˜Z[š[™×Ý\IË	ÉÊ_H×ÜÙ\ÜÚ[Û—ÙÙ]
Ù\ÜÚ[Û—ÛØš‹	Û˜[YIË	ÉÊ_H‹\\Š
Bˆ™]\›ˆ
‘TÔˆ[ˆ\ØÜš\ÜˆÜˆ‘T’QÑPS•ˆ[ˆ\ØÜš\ÜŠH[™•QHˆ›Ý[ˆ\ØÜš\Ü‚‚‚™YˆÙ\ÜÙ^[WÛÜ—Í
]NˆXÝÜÝ‹[žWKÙ\ÜÚ[Û—ÚYˆÝŠHOˆXÝÜÝ‹[žWN‚ˆÙ\ÜÚ[Û—ÛØšˆHš[™ÜÙ\ÜÚ[ÛŠ]KÙ\ÜÚ[Û—ÚY
BˆYˆ›ÝÙ\ÜÚ[Û—ÛØšˆÜˆ›ÝÚ\×Ù\ÜÚ[š]X[ÜÙ\ÜÚ[ÛŠÙ\ÜÚ[Û—ÛØšŠN‚ˆX›Ü

Bˆ™]\›ˆÙ\ÜÚ[Û—ÛØš‚‚‚™YˆÙ\ÜÛÙ™šXÚX[Ø][\ÛÜ—Í
^[NˆXÝÜÝ‹[žWK][\ÚYˆÝŠHOˆXÝÜÝ‹[žWN‚ˆ][\H™^

][H›Üˆ][H[ˆ^[K™Ù]
™\ÜÛÙ™šXÚX[ÜXÝWØ][\È‹×JBˆYˆ\Ú[œÝ[˜ÙJ][KXÝ
H[™][K™Ù]
šYŠHOH][\ÚY
K›Û™JBˆYˆ›Ý][\‚ˆX›Ü

Bˆ™]\›ˆ][\‚‚™YˆÙ\ÜÜXÝWØ]Y]
][\ˆXÝÜÝ‹[žWK]™[ˆÝ‹
Š™]Z[Îˆ[žJHOˆÝŽ‚ˆˆˆ\[™[Û›KÙ\™\‹Y]YØ[™Y]H]Y]˜Z[›ÜˆHÙ™šXÚX[PÕKˆˆˆ‚ˆ[Y\Ý[\HÛ›Ý×Ú\Û×Ý]Ê
Bˆ][\œÙ]Y˜][
˜]Y]ÛÙÈ‹×JK˜\[™
È˜]Žˆ[Y\Ý[\™]™[Žˆ]™[
Š™]Z[ßJBˆ™]\›ˆ[Y\Ý[\‚‚™YˆÙ\ÜÜXÝWÜ\œÙWÝ]Ê˜[YNˆÝŠHOˆ]][YK™]][YN‚ˆ™]\›ˆ]][YK™]][YK™œ›ÛZ\ÛÙ›Ü›X]
˜[YKœ™\XÙJ–ˆ‹ŠÌŒŠJB‚‚™YˆÙ\ÜØØ[™Y]WÛ˜[YJØ[™Y]NˆXÝÜÝ‹[žWJHOˆÝŽ‚ˆ™]\›ˆˆžØØ[™Y]K™Ù]
	Ùš\œÝÛ˜[YIË	ÉÊ_HØØ[™Y]K™Ù]
	Û\ÝÛ˜[YIË	ÉÊ_H‹œÝš\

HÜˆØ[™Y]‚‚‚™YˆÙ\ÜÛ™]×ØØ[™Y]WØ][\
Ø[™Y]NˆXÝÜÝ‹[žWJHOˆXÝÜÝ‹[žWN‚ˆˆˆZ[H›ÛZ[˜]]™HPÕHÛÜHÚ]Hš]˜]KØ[™Y]K\ÜXÚYšXÈ]Y\Ý[ÛˆÜ™\‹ˆˆˆ‚ˆÜ™\ˆH\Ý
˜[™ÙJ[ŠTÔÕRS’S‘×ÔPÕWÔUQTÕSÓ”ÊJJBˆ˜[™ÛK”Þ\Ý[T˜[™ÛJ
KœÚY™›JÜ™\ŠBˆ™]\›ˆÂˆ˜Ø[™Y]WÚYŽˆÝŠØ[™Y]K™Ù]
šYŠHÜˆˆŠKˆ˜Ø[™Y]WÛ˜[YHŽˆÙ\ÜØØ[™Y]WÛ˜[YJØ[™Y]JKˆœÝ]\ÈŽˆœ™XYH‹ˆœ]Y\Ý[Û—ÛÜ™\ˆŽˆÜ™\‹ˆ˜[œÝÙ\œÈŽˆ×KˆB‚‚™YˆÙ\ÜØØ[™Y]WØ][\ÊØ[™Y]\Îˆ\ÝÑXÝÜÝ‹[žWWJHOˆ\ÝÑXÝÜÝ‹[žWWN‚ˆˆˆ\ÜÚYÛˆ\Ý[˜ÝÜ™\œÈÚ[™]™\ˆH]Y\Ý[Ûˆ˜[šÈ\È[›ÝYÚ\›]]][ÛœËˆˆˆ‚ˆ\ÜÚYÛ™Y\ÙYH×KÙ]

Bˆ›ÜˆØ[™Y]H[ˆØ[™Y]\Î‚ˆ][HHÙ\ÜÛ™]×ØØ[™Y]WØ][\
Ø[™Y]JBˆÜ™\ˆH\J][VÈœ]Y\Ý[Û—ÛÜ™\ˆ—JBˆÚ[HÜ™\ˆ[ˆ\ÙY[™[Š\ÙY
HLŒˆÈHH\›]]][ÛœÈ›ÜˆHÝ\œ™[˜[šÂˆ˜[™ÛK”Þ\Ý[T˜[™ÛJ
KœÚY™›J][VÈœ]Y\Ý[Û—ÛÜ™\ˆ—JBˆÜ™\ˆH\J][VÈœ]Y\Ý[Û—ÛÜ™\ˆ—JBˆ\ÙY˜Y
Ü™\ŠBˆ\ÜÚYÛ™Y˜\[™
][JBˆ™]\›ˆ\ÜÚYÛ™Y‚‚™YˆÙ\ÜØ][\×Ù›Ü—Ü™YÚ\Ý\™YÝ˜Z[™Y\Êˆ^[NˆXÝÜÝ‹[žWK][\Îˆ\ÝÑXÝÜÝ‹[žWWBŠHOˆ\ÝÑXÝÜÝ‹[žWWN‚ˆXÝ]™WÚYÈHÜÝŠ][K™Ù]
šYŠHÜˆˆŠH›Üˆ][H[ˆÜ™YÚ\Ý\™YÝ˜Z[™Y\Ê^[J_Bˆš[\™YH×Bˆ›Üˆ][\[ˆ][\Î‚ˆYˆ›Ý\Ú[œÝ[˜ÙJ][\XÝ
N‚ˆÛÛ[YBˆ][\ÝšY]ÈHXÝ
][\
BˆØ[™Y]\ÈH][\™Ù]
˜Ø[™Y]\ÈŠHYˆ\Ú[œÝ[˜ÙJ][\™Ù]
˜Ø[™Y]\ÈŠK\Ý
H[ÙH×Bˆ][\ÝšY]ÖÈ˜Ø[™Y]\È—HHÂˆØ[™Y]H›ÜˆØ[™Y]H[ˆØ[™Y]\ÂˆYˆ›ÝÝŠØ[™Y]K™Ù]
˜Ø[™Y]WÚYŠHÜˆˆŠBˆÜˆÝŠØ[™Y]K™Ù]
˜Ø[™Y]WÚYŠHÜˆˆŠH[ˆXÝ]™WÚYÂˆBˆš[\™Y˜\[™
][\ÝšY]ÊBˆ™]\›ˆš[\™Y‚‚™YˆÙ\ÜØ][\Ü™\Ý[Ê][\ˆXÝÜÝ‹[žWJHOˆ\ÝÑXÝÜÝ‹[žWWN‚ˆ™\Ý[ÈH×Bˆ›ÜˆØ[™Y]H[ˆ][\™Ù]
˜Ø[™Y]\È‹×JN‚ˆ[œÝÙ\œÈHØ[™Y]K™Ù]
˜[œÝÙ\œÈ‹×JHYˆ\Ú[œÝ[˜ÙJØ[™Y]K™Ù]
˜[œÝÙ\œÈŠK\Ý
H[ÙH×BˆØÛÜ™HHÝ[JH›Üˆ[œÝÙ\ˆ[ˆ[œÝÙ\œÈYˆ[œÝÙ\‹™Ù]
˜ÛÜœ™XÝŠJBˆ™\Ý[Ë˜\[™
ÊŠ˜Ø[™Y]KœØÛÜ™HŽˆØÛÜ™KÝ[Žˆ[ŠTÔÕRS’S‘×ÔPÕWÔUQTÕSÓ”Ê_JBˆ™]\›ˆ™\Ý[Â‚‚™YˆÙ\ÜÜX›X×ÜXÝJ]NˆXÝÜÝ‹[žWKÚÙ[ŽˆÝ‹Ú[™ˆÝ‹][\ÚYˆÝŠN‚ˆ^[K˜Z[™YHHš[™ÜÙ\ÜÚ[Û—Ø[™Ý˜Z[™YWØžWÝÚÙ[Š]KÚÙ[ŠBˆYˆ
ˆ›Ý^[BˆÜˆ›Ý˜Z[™YBˆÜˆÝ˜Z[™YWÜ™YÚ\Ý˜][Û—Ú\×ØØ[˜Ù[Y
˜Z[™YJBˆÜˆ›ÝÚ\×Ù\ÜÚ[š]X[ÜÙ\ÜÚ[ÛŠ^[JBˆÜˆ›ÝÜX›X×Ú\×Ø]]Y
ÚÙ[ŠBˆ
N‚ˆX›Ü

BˆÙ^HH™\ÜÝ˜Z[š[™×ÜXÝWØ][\ÈˆYˆÚ[™OH˜Z[š[™Èˆ[ÙH™\ÜÙ^[WÜXÝWØ][\È‚ˆ][\H™^

H›ÜˆH[ˆ^[K™Ù]
Ù^K×JHYˆ\Ú[œÝ[˜ÙJKXÝ
H[™K™Ù]
šYŠHOH][\ÚY
K›Û™JBˆØ[™Y]HH™^

È›ÜˆÈ[ˆ
][\ÜˆßJK™Ù]
˜Ø[™Y]\È‹×JBˆYˆË™Ù]
˜Ø[™Y]WÚYŠHOHÝŠ˜Z[™YK™Ù]
šYŠHÜˆˆŠJK›Û™JBˆYˆ›Ý][\Üˆ›ÝØ[™Y]N‚ˆX›Ü

Bˆ™]\›ˆ^[K˜Z[™YK][\Ø[™Y]B‚‚\™Ù]
‹ØYZ[‹Ù^[\ÈŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ù^[\Ê
N‚ˆ]HHØYÙ]J
Bˆ^[\ÈHÜÈ›ÜˆÈ[ˆ]K™Ù]
œÙ\ÜÚ[ÛœÈ‹×JHYˆ\Ú[œÝ[˜ÙJËXÝ
H[™›ÝË™Ù]
˜\˜Ú]™YŠH[™Ú\×Ù\ÜÚ[š]X[ÜÙ\ÜÚ[ÛŠÊWBˆ^[\ËœÛÜ
Ù^O[[X™HÎˆ
ÜÙ\ÜÚ[Û—ÙÙ]
Ë™^[WÙ]H‹ˆŠHÜˆŽNNNH‹ÜÙ\ÜÚ[Û—ÙÙ]
Ë›˜[YH‹ˆŠJJBˆ^[WÝšY]ÜÈH×Bˆ›Üˆ^[H[ˆ^[\Î‚ˆ^[WÝšY]ÈHXÝ
^[JBˆ^[WÝšY]ÖÈ˜Z[™Y\È—HHÜ™YÚ\Ý\™YÝ˜Z[™Y\Ê^[JBˆ^[WÝšY]ËœÜ
œÝYÚXZ\™\È‹›Û™JBˆ^[WÝšY]ÜË˜\[™
^[WÝšY]ÊBˆ™]\›ˆ™[™\—Ý[\]J˜YZ[—Ù^[\Ëš[‹^[\ÏY^[WÝšY]ÜËXÝWÛ[Z]QTÔÕRS’S‘×ÔPÕWÓSRU
B‚‚\™Ù]
‹ØYZ[‹Ù^[\ËÏÙ\ÜÚ[Û—ÚYˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ù^[WÙ]Z[
Ù\ÜÚ[Û—ÚYˆÝŠN‚ˆ]HHØYÙ]J
Bˆ^[HHÙ\ÜÙ^[WÛÜ—Í
]KÙ\ÜÚ[Û—ÚY
Bˆ][\ÈH^[K™Ù]
™\ÜÝ˜Z[š[™×ÜXÝWØ][\ÈŠHYˆ\Ú[œÝ[˜ÙJ^[K™Ù]
™\ÜÝ˜Z[š[™×ÜXÝWØ][\ÈŠK\Ý
H[ÙH×Bˆ^[WØ][\ÈH^[K™Ù]
™\ÜÙ^[WÜXÝWØ][\ÈŠHYˆ\Ú[œÝ[˜ÙJ^[K™Ù]
™\ÜÙ^[WÜXÝWØ][\ÈŠK\Ý
H[ÙH×Bˆ™]\›ˆ™[™\—Ý[\]J˜YZ[—Ù^[WÙ]Z[š[‹^[OY^[K˜Z[™Y\ÏWÜ™YÚ\Ý\™YÝ˜Z[™Y\Ê^[JKˆ][\ÏWÙ\ÜØ][\×Ù›Ü—Ü™YÚ\Ý\™YÝ˜Z[™Y\Ê^[K][\ÊKˆ^[WØ][\ÏWÙ\ÜØ][\×Ù›Ü—Ü™YÚ\Ý\™YÝ˜Z[™Y\Ê^[K^[WØ][\ÊKˆXÝWÛ[Z]QTÔÕRS’S‘×ÔPÕWÓSRUˆÛÛ\]Y\™\]Y\Ý˜\™ÜË™Ù]
˜ÛÛ\]YŠHOHŒHŠB‚‚\œÜÝ
‹ØYZ[‹Ù^[\ËÏÙ\ÜÚ[Û—ÚY‹Ý˜Z[š[™Ë\XÝHŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ù^[WÝ˜Z[š[™×ÜXÝWÜÝ\
Ù\ÜÚ[Û—ÚYˆÝŠN‚ˆ]HHØYÙ]J
Bˆ^[HHÙ\ÜÙ^[WÛÜ—Í
]KÙ\ÜÚ[Û—ÚY
Bˆ][\ÈH^[KœÙ]Y˜][
™\ÜÝ˜Z[š[™×ÜXÝWØ][\È‹×JBˆYˆ›Ý\Ú[œÝ[˜ÙJ][\Ë\Ý
N‚ˆ][\ÈH^[VÈ™\ÜÝ˜Z[š[™×ÜXÝWØ][\È—HH×BˆYˆ[Š][\ÊHHTÔÕRS’S‘×ÔPÕWÓSRU‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ù^[WÙ]Z[‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY[Z]HŒHŠJBˆ][\HÈšYŽˆ]ZY]ZY

Kš^˜Ü™X]YØ]ŽˆÛ›Ý×Ú\Û×Ý]Ê
KœÝ]\ÈŽˆ›Ü[ˆ‹ˆ˜Ø[™Y]\ÈŽˆÙ\ÜØØ[™Y]WØ][\ÊÜ™YÚ\Ý\™YÝ˜Z[™Y\Ê^[JJ_Bˆ][\Ë˜\[™
][\
BˆØ]™WÙ]J]JBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ù^[WÙ]Z[‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚYÜ[™YH˜Z[š[™ÈŠJB‚‚\œÜÝ
‹ØYZ[‹Ù^[\ËÏÙ\ÜÚ[Û—ÚY‹Ù^[K\XÝHŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ù^[WÜXÝWÛÜ[ŠÙ\ÜÚ[Û—ÚYˆÝŠN‚ˆ]HHØYÙ]J
Bˆ^[HHÙ\ÜÙ^[WÛÜ—Í
]KÙ\ÜÚ[Û—ÚY
Bˆ][\ÈH^[KœÙ]Y˜][
™\ÜÙ^[WÜXÝWØ][\È‹×JBˆ][\HÈšYŽˆ]ZY]ZY

Kš^˜Ü™X]YØ]ŽˆÛ›Ý×Ú\Û×Ý]Ê
KœÝ]\ÈŽˆ›Ü[ˆ‹ˆ˜Ø[™Y]\ÈŽˆÙ\ÜØØ[™Y]WØ][\ÊÜ™YÚ\Ý\™YÝ˜Z[™Y\Ê^[JJ_Bˆ][\Ë˜\[™
][\
BˆØ]™WÙ]J]JBˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ù^[WÙ]Z[‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚYÜ[™YH™^[HŠJB‚‚\™Ù]
‹Ù\ÜXÙKÏÚÙ[‹ÜXÝKÏÚ[™‹Ï][\ÚYˆŠB™YˆX›X×Ý˜Z[™YWÜXÝJÚÙ[ŽˆÝ‹Ú[™ˆÝ‹][\ÚYˆÝŠN‚ˆYˆÚ[™›Ý[ˆÈ˜Z[š[™È‹™^[HŸN‚ˆX›Ü

Bˆ]HHØYÙ]J
Bˆ^[K˜Z[™YK][\Ø[™Y]HHÙ\ÜÜX›X×ÜXÝJ]KÚÙ[‹Ú[™][\ÚY
BˆYˆØ[™Y]K™Ù]
œÝ]\ÈŠHOHœ™XYHŽ‚ˆØ[™Y]VÈœÝ]\È—HHš[—Ü›ÙÜ™\ÜÈ‚ˆØ[™Y]VÈœÝ\YØ]—HHÛ›Ý×Ú\Û×Ý]Ê
BˆØ]™WÙ]J]JBˆ™]\›ˆ™[™\—Ý[\]JœX›X×Ý˜Z[™YWÜXÝKš[‹^[OY^[K˜Z[™YO]˜Z[™YKÚÙ[]ÚÙ[‹Ú[™ZÚ[™ˆ][\X][\Ø[™Y]OXØ[™Y]K]Y\Ý[Û—ØÛÝ[[[ŠTÔÕRS’S‘×ÔPÕWÔUQTÕSÓ”ÊKˆ]Y\Ý[Û—ÜÙXÛÛ™ÏQTÔÓÑ‘’PÒPSÔPÕWÔUQTÕSÓ—ÔÑPÓÓ‘ÊB‚‚\œÜÝ
‹Ù\ÜXÙKÏÚÙ[‹ÜXÝKÏÚ[™‹Ï][\ÚY‹Ø[œÝÙ\ˆŠB™YˆX›X×Ý˜Z[™YWÜXÝWØ[œÝÙ\ŠÚÙ[ŽˆÝ‹Ú[™ˆÝ‹][\ÚYˆÝŠN‚ˆ]HHØYÙ]J
Bˆ^[K˜Z[™YK][\Ø[™Y]HHÙ\ÜÜX›X×ÜXÝJ]KÚÙ[‹Ú[™][\ÚY
BˆYˆØ[™Y]K™Ù]
œÝ]\ÈŠHOHš[—Ü›ÙÜ™\ÜÈŽ‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆÙHPÕH\Ý0êZ°è\›Z[°êKˆŸKBˆ^[ØYH™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßBˆÜÚ][Û‹Ù[XÝYH^[ØY™Ù]
œÜÚ][ÛˆŠK^[ØY™Ù]
˜[œÝÙ\ˆŠBˆÜ™\ˆHØ[™Y]K™Ù]
œ]Y\Ý[Û—ÛÜ™\ˆ‹×JBˆYˆ›Ý\Ú[œÝ[˜ÙJÜÚ][Û‹[
HÜˆÜÚ][ÛˆOH[ŠØ[™Y]K™Ù]
˜[œÝÙ\œÈ‹×JJHÜˆÜÚ][ÛˆH[ŠÜ™\ŠN‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”]Y\Ý[Ûˆ[˜[YHÝH0êZ°è°ê\Û™YKˆŸKBˆÛÝ\˜ÙWÚ[™^HÜ™\–ÜÜÚ][Û—Bˆ]Y\Ý[ÛˆHTÔÕRS’S‘×ÔPÕWÔUQTÕSÓ”ÖÜÛÝ\˜ÙWÚ[™^BˆXY[™\ÈHØ[™Y]K™Ù]
œ]Y\Ý[Û—ÙXY[™\È‹×JBˆXY[™WØ]HXY[™\ÖÜÜÚ][Û—HYˆÜÚ][Ûˆ[ŠXY[™\ÊH[ÙH›Û™Bˆ[YYÛÝ]H›ÛÛ
XY[™WØ][™Ù\ÜÜXÝWÜ\œÙWÝ]ÊÛ›Ý×Ú\Û×Ý]Ê
JHHÙ\ÜÜXÝWÜ\œÙWÝ]ÊXY[™WØ]
JBˆYˆÙ[XÝY\È›Û™H[™›Ý[YYÛÝ]‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ“H[\ÈH°ê\ÛœÙH‰Ù\Ý\È[˜ÛÜ™H0êXÛÝ[0êKˆŸKBˆYˆ›Ý[YYÛÝ][™
›Ý\Ú[œÝ[˜ÙJÙ[XÝY[
HÜˆ›ÝHÙ[XÝY[Š]Y\Ý[Û–È˜ÚÚXÙ\È—JJN‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”°ê\ÛœÙH[˜[YKˆŸKˆØ[™Y]KœÙ]Y˜][
˜[œÝÙ\œÈ‹×JK˜\[™
ÈœÜÚ][ÛˆŽˆÜÚ][Û‹œ]Y\Ý[Û—Ú[™^ŽˆÛÝ\˜ÙWÚ[™^ˆœÙ[XÝYØ[œÝÙ\ˆŽˆ›Û™HYˆ[YYÛÝ][ÙHÙ[XÝYˆ˜ÛÜœ™XÝŽˆ˜[ÙHYˆ[YYÛÝ][ÙHÙ[XÝYOH]Y\Ý[Û–È˜[œÝÙ\ˆ—Kˆ[˜[œÝÙ\™YŽˆ[YYÛÝ]˜[œÝÙ\™YØ]ŽˆÛ›Ý×Ú\Û×Ý]Ê
_JBˆÛÛ\]YH[ŠØ[™Y]VÈ˜[œÝÙ\œÈ—JHOH[ŠÜ™\ŠBˆYˆÛÛ\]Y‚ˆØ[™Y]VÈœÝ]\È—HH˜ÛÛ\]Y‚ˆØ[™Y]VÈ˜ÛÛ\]YØ]—HHÛ›Ý×Ú\Û×Ý]Ê
BˆYˆ[
Ë™Ù]
œÝ]\ÈŠHOH˜ÛÛ\]Yˆ›ÜˆÈ[ˆ][\™Ù]
˜Ø[™Y]\È‹×JJN‚ˆ][\ÈœÝ]\È—HH˜ÛÛ\]Y‚ˆ][\È˜ÛÛ\]YØ]—HHÛ›Ý×Ú\Û×Ý]Ê
BˆØ]™WÙ]J]JBˆ™]\›ˆÈ›ÚÈŽˆYK˜ÛÛ\]YŽˆÛÛ\]Y[YYÛÝ]Žˆ[YYÛÝ]B‚‚\™Ù]
‹Ù\ÜXÙKÏÚÙ[‹ÜXÝKÏÚ[™‹Ï][\ÚY‹Ü]Y\Ý[Û‹Ï[œÜÚ][ÛˆŠB™YˆX›X×Ý˜Z[™YWÜXÝWÜ]Y\Ý[ÛŠÚÙ[ŽˆÝ‹Ú[™ˆÝ‹][\ÚYˆÝ‹ÜÚ][ÛŽˆ[
N‚ˆ]HHØYÙ]J
BˆËËËØ[™Y]HHÙ\ÜÜX›X×ÜXÝJ]KÚÙ[‹Ú[™][\ÚY
BˆÜ™\ˆHØ[™Y]K™Ù]
œ]Y\Ý[Û—ÛÜ™\ˆ‹×JBˆYˆØ[™Y]K™Ù]
œÝ]\ÈŠHOHš[—Ü›ÙÜ™\ÜÈˆÜˆÜÚ][ÛˆOH[ŠØ[™Y]K™Ù]
˜[œÝÙ\œÈ‹×JJHÜˆ›ÝHÜÚ][Ûˆ[ŠÜ™\ŠN‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”]Y\Ý[Ûˆ[™\ÜÛšX›KˆŸKBˆÈHXY[™H™[Û™ÜÈÈH]Y\Ý[Û‹›ÝÈHœ›ÝÜÙ\ˆYÙKˆÙY\[™È]ˆÈÚ]HØ[™Y]H™]™[ÈH™Yœ™\Ú
ÜˆHÙXÛÛ™XŠHœ›ÛHÜ˜[[™ÈBˆÈœ™\ÚK\ÙXÛÛ™\š[Ù‚ˆXY[™\ÈHØ[™Y]KœÙ]Y˜][
œ]Y\Ý[Û—ÙXY[™\È‹×JBˆYˆÜÚ][Ûˆ[ŠXY[™\ÊH[™XY[™\ÖÜÜÚ][Û—N‚ˆXY[™WØ]HXY[™\ÖÜÜÚ][Û—Bˆ[ÙN‚ˆÜ[™YØ]HÛ›Ý×Ú\Û×Ý]Ê
BˆXY[™WØ]H
Ù\ÜÜXÝWÜ\œÙWÝ]ÊÜ[™YØ]
H
È]][YK[YY[JˆÙXÛÛ™ÏQTÔÓÑ‘’PÒPSÔPÕWÔUQTÕSÓ—ÔÑPÓÓ‘Âˆ
JKš\ÛÙ›Ü›X]

Kœ™\XÙJŠÌŒ‹–ˆŠBˆÚ[H[ŠXY[™\ÊHHÜÚ][ÛŽ‚ˆXY[™\Ë˜\[™
›Û™JBˆXY[™\ÖÜÜÚ][Û—HHXY[™WØ]ˆØ]™WÙ]J]JBˆÛÝ\˜ÙHHTÔÕRS’S‘×ÔPÕWÔUQTÕSÓ”ÖÛÜ™\–ÜÜÚ][Û—WBˆ™]\›ˆÈœ]Y\Ý[ÛˆŽˆÛÝ\˜ÙVÈœ]Y\Ý[Ûˆ—K˜ÚÚXÙ\ÈŽˆÛÝ\˜ÙVÈ˜ÚÚXÙ\È—Kˆ™XY[™WØ]ŽˆXY[™WØ]œÙ\™\—Ý[YHŽˆÛ›Ý×Ú\Û×Ý]Ê
_B‚‚\™Ù]
‹ØYZ[‹Ù^[\ËÏÙ\ÜÚ[Û—ÚY‹ÜXÝKÏÚ[™‹Ï][\ÚY‹Ü™\Ý[ËœˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ù^[WÜXÝWÜ™\Ý[×ÜŠÙ\ÜÚ[Û—ÚYˆÝ‹Ú[™ˆÝ‹][\ÚYˆÝŠN‚ˆœ›ÛH™\ÜX‹›Xˆ[\ÜÛÛÜœÂˆœ›ÛH™\ÜX‹›X‹œYÙ\Ú^™\È[\ÜMˆœ›ÛH™\ÜX‹›X‹œÝ[\È[\ÜÙ]Ø[\TÝ[TÚY]\˜YÜ˜\Ý[Bˆœ›ÛH™\ÜX‹›X‹[š]È[\Ü[Bˆœ›ÛH™\ÜX‹œ]\\È[\ÜÚ[\QØÕ[\]K\˜YÜ˜\ÜXÙ\‹X›KX›TÝ[Bˆ]HHØYÙ]J
NÈ^[HHÙ\ÜÙ^[WÛÜ—Í
]KÙ\ÜÚ[Û—ÚY
BˆÙ^HH™\ÜÝ˜Z[š[™×ÜXÝWØ][\ÈˆYˆÚ[™OH˜Z[š[™Èˆ[ÙH™\ÜÙ^[WÜXÝWØ][\È‚ˆ][\H™^

H›ÜˆH[ˆ^[K™Ù]
Ù^K×JHYˆK™Ù]
šYŠHOH][\ÚY
K›Û™JBˆYˆ›Ý][\ˆX›Ü

Bˆ][\HÙ\ÜØ][\×Ù›Ü—Ü™YÚ\Ý\™YÝ˜Z[™Y\Ê^[KØ][\JVÌBˆÝ]]Hž]\ÒSÊ
NÈØÈHÚ[\QØÕ[\]JÝ]]YÙ\Ú^™OPMšYÚX\™Ú[LN
›[KYX\™Ú[LN
›[JBˆÝ[\ÈHÙ]Ø[\TÝ[TÚY]

NÈ]HH\˜YÜ˜\Ý[J”XÝU]H‹\™[\Ý[\ÖÈ•]H—K^ÛÛÜXÛÛÜœË’^ÛÛÜŠˆÌÌL™NHŠJBˆÝÜžHHÔ\˜YÜ˜\
’S•0âQÔSHPÐQSVH‹]JK\˜YÜ˜\
ˆ”°ê\Ý[]ÈPÕH8 %ÉÑ^[Y[‰ÈYˆÚ[™OH	Ù^[IÈ[ÙH	Ñ[˜pë›™[Y[	ßH‹Ý[\ÖÈ’XY[™Ìˆ—JKˆ\˜YÜ˜\
[™\ØØ\JÝŠÜÙ\ÜÚ[Û—ÙÙ]
^[K	Û˜[YIË	ÔÙ\ÜÚ[Û‰ÊJJKÝ[\ÖÈ“›Ü›X[—JKÜXÙ\ŠK
›[JWBˆ›ÝÜÈHÖÈØ[™Y]‹”Ý]]‹”ØÛÜ™H‹”°ê]\ÜÚ]H—WBˆ›Üˆ™\Ý[[ˆÙ\ÜØ][\Ü™\Ý[Ê][\
N‚ˆÝH›Ý[™
L
ˆ™\Ý[ÈœØÛÜ™H—HÈ™\Ý[ÈÝ[—JHYˆ™\Ý[ÈÝ[—H[ÙHˆ›ÝÜË˜\[™
Ü™\Ý[È˜Ø[™Y]WÛ˜[YH—K•\›Z[°êHˆYˆ™\Ý[™Ù]
œÝ]\ÈŠHOH˜ÛÛ\]Yˆ[ÙH‘[ˆÛÝ\œÈ‹ˆžÜ™\Ý[ÉÜØÛÜ™I×_HÈÜ™\Ý[ÉÝÝ[	×_H‹ˆžÜÝH	H—JBˆX›HHX›J›ÝÜËÛÛÚYÏVÍÍJ›[KÍJ›[KJ›[KJ›[WJNÈX›KœÙ]Ý[JX›TÝ[JÂˆ
PÒÑÔ“ÕS‘‹

K
LK
KÛÛÜœË’^ÛÛÜŠˆÌÌL™NHŠJK
•VÓÓÔˆ‹

K
LK
KÛÛÜœËÚ]JKˆ
‘“Ó•SQH‹

K
LK
K’[™]XØKP›ÛŠK
‘Ô’Q‹

K
LKLJKÛÛÜœË’^ÛÛÜŠˆØØ™YLHŠJKˆ
”“ÕÐPÒÑÔ“ÕS‘È‹
JK
LKLJKØÛÛÜœËÚ]KÛÛÜœË’^ÛÛÜŠˆÙŽ˜Y˜ÈŠWJK
”QS‘È‹

K
LKLJK
WJJBˆÝÜžK˜\[™
X›JNÈØË˜Z[
ÝÜžJNÈÝ]]œÙYZÊ
Bˆ™]\›ˆÙ[™Ùš[JÝ]]Z[Y]\OH˜\XØ][Û‹Üˆ‹\×Ø]XÚY[UYKÝÛ›ØYÛ˜[YOHœ™\Ý[]Ë\XÝKœˆŠB‚‚\™Ù]
‹ØYZ[‹Ù^[\ËÏÙ\ÜÚ[Û—ÚY‹Ý˜Z[š[™Ë\XÝKÏ][\ÚYˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ù^[WÝ˜Z[š[™×ÜXÝWÜ^JÙ\ÜÚ[Û—ÚYˆÝ‹][\ÚYˆÝŠN‚ˆ]HHØYÙ]J
Bˆ^[HHÙ\ÜÙ^[WÛÜ—Í
]KÙ\ÜÚ[Û—ÚY
Bˆ][\H™^

H›ÜˆH[ˆ^[K™Ù]
™\ÜÝ˜Z[š[™×ÜXÝWØ][\È‹×JHYˆK™Ù]
šYŠHOH][\ÚY
K›Û™JBˆYˆ›Ý][\‚ˆX›Ü

Bˆ][\HÙ\ÜØ][\×Ù›Ü—Ü™YÚ\Ý\™YÝ˜Z[™Y\Ê^[KØ][\JVÌBˆYˆ][\™Ù]
œÝ]\ÈŠHOH˜ÛÛ\]YŽ‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ù^[WÙ]Z[‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚYÛÛ\]YHŒHŠJBˆ™]\›ˆ™[™\—Ý[\]J˜YZ[—Ù^[WÜXÝKš[‹^[OY^[K][\X][\]Y\Ý[ÛœÏQTÔÕRS’S‘×ÔPÕWÔUQTÕSÓ”ÊB‚‚\œÜÝ
‹ØYZ[‹Ù^[\ËÏÙ\ÜÚ[Û—ÚY‹Ý˜Z[š[™Ë\XÝKÏ][\ÚY‹ØÛÛ\]HŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ù^[WÝ˜Z[š[™×ÜXÝWØÛÛ\]JÙ\ÜÚ[Û—ÚYˆÝ‹][\ÚYˆÝŠN‚ˆ]HHØYÙ]J
Bˆ^[HHÙ\ÜÙ^[WÛÜ—Í
]KÙ\ÜÚ[Û—ÚY
Bˆ][\H™^

H›ÜˆH[ˆ^[K™Ù]
™\ÜÝ˜Z[š[™×ÜXÝWØ][\È‹×JHYˆK™Ù]
šYŠHOH][\ÚY
K›Û™JBˆYˆ›Ý][\‚ˆX›Ü

BˆYˆ][\™Ù]
œÝ]\ÈŠHOH˜ÛÛ\]YŽ‚ˆ][\ÈœÝ]\È—HH˜ÛÛ\]Y‚ˆ][\È˜ÛÛ\]YØ]—HHÛ›Ý×Ú\Û×Ý]Ê
BˆØ]™WÙ]J]JBˆ™]\›ˆÈ›ÚÈŽˆYKœ™Y\™XÝŽˆ\›Ù›ÜŠ˜YZ[—Ù^[WÙ]Z[‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚYÛÛ\]YHŒHŠ_B‚‚\œÜÝ
‹ØYZ[‹Ù^[\ËÏÙ\ÜÚ[Û—ÚY‹ÛÙ™šXÚX[\XÝKÏØ[™Y]WÚYˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ù^[WÛÙ™šXÚX[ÜXÝWÜÝ\
Ù\ÜÚ[Û—ÚYˆÝ‹Ø[™Y]WÚYˆÝŠN‚ˆˆˆÜ™X]HHÛ™H›Û‹\™\Ý[XX›HÙ™šXÚX[][\\ÜÚYÛ™YÈHØ[™Y]Kˆˆˆ‚ˆ]HHØYÙ]J
Bˆ^[HHÙ\ÜÙ^[WÛÜ—Í
]KÙ\ÜÚ[Û—ÚY
BˆØ[™Y]HH™^

][H›Üˆ][H[ˆÜÙ\ÜÚ[Û—Ý˜Z[™Y\×Û\Ý
^[JBˆYˆÝŠ][K™Ù]
šYŠJHOHØ[™Y]WÚY
K›Û™JBˆYˆ›ÝØ[™Y]N‚ˆX›Ü

Bˆ][\ÈH^[KœÙ]Y˜][
™\ÜÛÙ™šXÚX[ÜXÝWØ][\È‹×JBˆ^\Ý[™ÈH™^

][H›Üˆ][H[ˆ][\ÈYˆ][K™Ù]
˜Ø[™Y]WÚYŠHOHØ[™Y]WÚY
K›Û™JBˆYˆ^\Ý[™Î‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ•[™H[]]™HÙ™šXÚY[H^\ÝH0êZ°èÝ\ˆÙHØ[™Y]ˆŸKBˆ][\HÂˆšYŽˆ]ZY]ZY

Kš^ˆ˜Ø[™Y]WÚYŽˆØ[™Y]WÚYˆ˜Ø[™Y]WÛ˜[YHŽˆˆžØØ[™Y]K™Ù]
	Ùš\œÝÛ˜[YIË	ÉÊ_HØØ[™Y]K™Ù]
	Û\ÝÛ˜[YIË	ÉÊ_H‹œÝš\

KˆœÝ]\ÈŽˆœ™XYH‹ˆ˜Ü™X]YØ]ŽˆÛ›Ý×Ú\Û×Ý]Ê
Kˆœ]Y\Ý[ÛœÈŽˆ×Kˆ˜[œÝÙ\œÈŽˆ×Kˆ˜]Y]ÛÙÈŽˆ×KˆBˆÙ\ÜÜXÝWØ]Y]
][\˜][\ØÜ™X]YŠBˆ][\Ë˜\[™
][\
BˆØ]™WÙ]J]JBˆ™]\›ˆÈ›ÚÈŽˆYKœ^WÝ\›Žˆ\›Ù›ÜŠ˜YZ[—Ù^[WÛÙ™šXÚX[ÜXÝWÜ^H‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚYˆ][\ÚYX][\ÈšY—JK˜][\ÚYŽˆ][\ÈšY—_KŒB‚‚\™Ù]
‹ØYZ[‹Ù^[\ËÏÙ\ÜÚ[Û—ÚY‹ÛÙ™šXÚX[\XÝKÏ][\ÚYˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ù^[WÛÙ™šXÚX[ÜXÝWÜ^JÙ\ÜÚ[Û—ÚYˆÝ‹][\ÚYˆÝŠN‚ˆ]HHØYÙ]J
Bˆ^[HHÙ\ÜÙ^[WÛÜ—Í
]KÙ\ÜÚ[Û—ÚY
Bˆ][\HÙ\ÜÛÙ™šXÚX[Ø][\ÛÜ—Í
^[K][\ÚY
BˆYˆ][\™Ù]
œÝ]\ÈŠH[ˆÈ˜ÛÛ\]Y‹›ØÚÙYŸN‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—Ù^[WÙ]Z[‹Ù\ÜÚ[Û—ÚY\Ù\ÜÚ[Û—ÚY
JBˆÛZ[WÚÙ^HHˆ™\ÜÛÙ™šXÚX[ÜXÝWÞØ][\ÚYH‚ˆÛZ[HHÙ\ÜÚ[Û‹™Ù]
ÛZ[WÚÙ^JBˆYˆ][\™Ù]
˜ÛZ[WÚYŠH[™ÛZ[HOH][\È˜ÛZ[WÚY—N‚ˆÙ\ÜÜXÝWØ]Y]
][\[˜]]Üš^™YÜ™\Ý[YWÜ™Z™XÝYŠBˆØ]™WÙ]J]JBˆX›Ü
KÙ]H[]]™H\Ý0êZ°èÝ]™\HÝ\ˆ[ˆ]]™H˜]šYØ]]\‹ˆŠBˆYˆ›Ý][\™Ù]
˜ÛZ[WÚYŠN‚ˆ][\È˜ÛZ[WÚY—HH]ZY]ZY

Kš^ˆ][\ÈœÝ]\È—HHš[—Ü›ÙÜ™\ÜÈ‚ˆÙ\ÜÚ[Û–ØÛZ[WÚÙ^WHH][\È˜ÛZ[WÚY—BˆÙ\ÜÜXÝWØ]Y]
][\˜][\ØÛZ[YYŠBˆØ]™WÙ]J]JBˆ™]\›ˆ™[™\—Ý[\]J˜YZ[—Ù^[WÜXÝWÛÙ™šXÚX[š[‹^[OY^[K][\X][\ˆ]Y\Ý[Û—ØÛÝ[[[ŠTÔÕRS’S‘×ÔPÕWÔUQTÕSÓ”ÊKˆ]Y\Ý[Û—ÜÙXÛÛ™ÏQTÔÓÑ‘’PÒPSÔPÕWÔUQTÕSÓ—ÔÑPÓÓ‘ÊB‚‚™YˆÙ\ÜÛÙ™šXÚX[ØÛZ[WÛÜ—ÍJ][\ˆXÝÜÝ‹[žWK][\ÚYˆÝŠHOˆ›Û™N‚ˆYˆ][\™Ù]
œÝ]\ÈŠHOHš[—Ü›ÙÜ™\ÜÈˆÜˆÙ\ÜÚ[Û‹™Ù]
ˆ™\ÜÛÙ™šXÚX[ÜXÝWÞØ][\ÚYHŠHOH][\™Ù]
˜ÛZ[WÚYŠN‚ˆX›Ü
K•[]]™H™\œ›ÝZ[0êYHÝH™\š\ÙH›Ûˆ]]Üš\ðêYKˆŠB‚‚\™Ù]
‹ØYZ[‹Ù^[\ËÏÙ\ÜÚ[Û—ÚY‹ÛÙ™šXÚX[\XÝKÏ][\ÚY‹ØÛØÚÈŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ù^[WÛÙ™šXÚX[ÜXÝWØÛØÚÊÙ\ÜÚ[Û—ÚYˆÝ‹][\ÚYˆÝŠN‚ˆ]HHØYÙ]J
Bˆ][\HÙ\ÜÛÙ™šXÚX[Ø][\ÛÜ—Í
Ù\ÜÙ^[WÛÜ—Í
]KÙ\ÜÚ[Û—ÚY
K][\ÚY
BˆÙ\ÜÛÙ™šXÚX[ØÛZ[WÛÜ—ÍJ][\][\ÚY
Bˆ™]\›ˆÈœÙ\™\—Ý[YHŽˆÛ›Ý×Ú\Û×Ý]Ê
_B‚‚\œÜÝ
‹ØYZ[‹Ù^[\ËÏÙ\ÜÚ[Û—ÚY‹ÛÙ™šXÚX[\XÝKÏ][\ÚY‹Ü]Y\Ý[ÛœËÏ[š[™^‹ÛÜ[ˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ù^[WÛÙ™šXÚX[ÜXÝWÛÜ[—Ü]Y\Ý[ÛŠÙ\ÜÚ[Û—ÚYˆÝ‹][\ÚYˆÝ‹[™^ˆ[
N‚ˆ]HHØYÙ]J
Bˆ][\HÙ\ÜÛÙ™šXÚX[Ø][\ÛÜ—Í
Ù\ÜÙ^[WÛÜ—Í
]KÙ\ÜÚ[Û—ÚY
K][\ÚY
BˆÙ\ÜÛÙ™šXÚX[ØÛZ[WÛÜ—ÍJ][\][\ÚY
BˆYˆ[™^Üˆ[™^H[ŠTÔÕRS’S‘×ÔPÕWÔUQTÕSÓ”ÊN‚ˆX›Ü

Bˆ]Y\Ý[ÛœÈH][\œÙ]Y˜][
œ]Y\Ý[ÛœÈ‹×JBˆYˆ[™^[Š]Y\Ý[ÛœÊN‚ˆ™]\›ˆ]Y\Ý[ÛœÖÚ[™^BˆYˆ[™^OH[Š]Y\Ý[ÛœÊN‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ“Ü™™H\È]Y\Ý[ÛœÈ[˜[YKˆŸKBˆYˆ[™^[™›Ý[žJ[œÝÙ\‹™Ù]
œ]Y\Ý[Û—Ú[™^ŠHOH[™^HH›Üˆ[œÝÙ\ˆ[ˆ][\™Ù]
˜[œÝÙ\œÈ‹×JJN‚ˆ™]š[Ý\×ÙXY[™HHÙ\ÜÜXÝWÜ\œÙWÝ]Ê]Y\Ý[ÛœÖÚ[™^HWVÈ™XY[™WØ]—JBˆYˆ]][YK™]][YK››ÝÊ]][YK[Y^›Û™K]ÊHH™]š[Ý\×ÙXY[™N‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ“H]Y\Ý[Ûˆ°êXðêY[H\Ý[˜ÛÜ™HXÝ]™KˆŸKBˆÜ[™YØ]HÙ\ÜÜXÝWØ]Y]
][\œ]Y\Ý[Û—ÛÜ[™Y‹]Y\Ý[Û—Ú[™^Z[™^
BˆXY[™HHÙ\ÜÜXÝWÜ\œÙWÝ]ÊÜ[™YØ]
H
È]][YK[YY[JÙXÛÛ™ÏQTÔÓÑ‘’PÒPSÔPÕWÔUQTÕSÓ—ÔÑPÓÓ‘ÊBˆÛÝ\˜ÙHHTÔÕRS’S‘×ÔPÕWÔUQTÕSÓ”ÖÚ[™^Bˆ]Y\Ý[ÛˆHÈœ]Y\Ý[Û—Ú[™^Žˆ[™^œ]Y\Ý[ÛˆŽˆÛÝ\˜ÙVÈœ]Y\Ý[Ûˆ—K˜ÚÚXÙ\ÈŽˆÛÝ\˜ÙVÈ˜ÚÚXÙ\È—Kˆ›Ü[™YØ]ŽˆÜ[™YØ]™XY[™WØ]ŽˆXY[™Kš\ÛÙ›Ü›X]

Kœ™\XÙJŠÌŒ‹–ˆŠ_Bˆ]Y\Ý[ÛœË˜\[™
]Y\Ý[ÛŠBˆØ]™WÙ]J]JBˆ™]\›ˆ]Y\Ý[Û‹ŒB‚‚\œÜÝ
‹ØYZ[‹Ù^[\ËÏÙ\ÜÚ[Û—ÚY‹ÛÙ™šXÚX[\XÝKÏ][\ÚY‹Ü]Y\Ý[ÛœËÏ[š[™^‹Ø[œÝÙ\ˆŠBYZ[—ÛÙÚ[—Ü™\]Z\™Y™YˆYZ[—Ù^[WÛÙ™šXÚX[ÜXÝWØ[œÝÙ\ŠÙ\ÜÚ[Û—ÚYˆÝ‹][\ÚYˆÝ‹[™^ˆ[
N‚ˆ]HHØYÙ]J
Bˆ^[HHÙ\ÜÙ^[WÛÜ—Í
]KÙ\ÜÚ[Û—ÚY
Bˆ][\HÙ\ÜÛÙ™šXÚX[Ø][\ÛÜ—Í
^[K][\ÚY
BˆÙ\ÜÛÙ™šXÚX[ØÛZ[WÛÜ—ÍJ][\][\ÚY
Bˆ]Y\Ý[ÛœÈH][\™Ù]
œ]Y\Ý[ÛœÈ‹×JBˆYˆ[™^H[Š]Y\Ý[ÛœÊHÜˆ[™^‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”]Y\Ý[Ûˆ›ÛˆÝ]™\KˆŸKBˆYˆ[žJ[œÝÙ\‹™Ù]
œ]Y\Ý[Û—Ú[™^ŠHOH[™^›Üˆ[œÝÙ\ˆ[ˆ][\™Ù]
˜[œÝÙ\œÈ‹×JJN‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”°ê\ÛœÙH0êZ°è[œ™YÚ\Ý°êYKˆŸKBˆ™XÙZ]™YØ]HÛ›Ý×Ú\Û×Ý]Ê
BˆÙ[XÝYH
™\]Y\Ý™Ù]ÚœÛÛŠÚ[[UYJHÜˆßJK™Ù]
˜[œÝÙ\ˆŠBˆYˆ›Ý\Ú[œÝ[˜ÙJÙ[XÝY[
HÜˆÙ[XÝYÜˆÙ[XÝYH[ŠTÔÕRS’S‘×ÔPÕWÔUQTÕSÓ”ÖÚ[™^VÈ˜ÚÚXÙ\È—JN‚ˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”°ê\ÛœÙH[˜[YKˆŸKˆYˆÙ\ÜÜXÝWÜ\œÙWÝ]Ê™XÙZ]™YØ]
HˆÙ\ÜÜXÝWÜ\œÙWÝ]Ê]Y\Ý[ÛœÖÚ[™^VÈ™XY[™WØ]—JN‚ˆÙ\ÜÜXÝWØ]Y]
][\›]WØ[œÝÙ\—Ü™Z™XÝY‹]Y\Ý[Û—Ú[™^Z[™^Ù[XÝYØ[œÝÙ\\Ù[XÝYˆ™XÙZ]™YØ]\™XÙZ]™YØ]
BˆØ]™WÙ]J]JBˆ™]\›ˆÈ›ÚÈŽˆ˜[ÙK™\œ›ÜˆŽˆ”°ê\ÛœÙH™péÝYH\°êÈ8 &pêXÚ0êX[˜ÙHÙ\™]\‹ˆ‹œ™XÙZ]™YØ]Žˆ™XÙZ]™YØ]KBˆ[œÝÙ\ˆHÈœ]Y\Ý[Û—Ú[™^Žˆ[™^œÙ[XÝYØ[œÝÙ\ˆŽˆÙ[XÝYœ™XÙZ]™YØ]Žˆ™XÙZ]™YØ]Bˆ][\œÙ]Y˜][
˜[œÝÙ\œÈ‹×JK˜\[™
[œÝÙ\ŠBˆÙ\ÜÜXÝWØ]Y]
][\˜[œÝÙ\—Ü™XÛÜ™Y‹
Š˜[œÝÙ\ŠBˆYˆ[™^OH[ŠTÔÕRS’S‘×ÔPÕWÔUQTÕSÓ”ÊHHN‚ˆ][\ÈœÝ]\È—HH˜ÛÛ\]Y‚ˆ][\È˜ÛÛ\]YØ]—HH™XÙZ]™YØ]ˆÙ\ÜÜXÝWØ]Y]
][\˜][\ØÛÛ\]YŠBˆÙ\ÜÚ[Û‹œÜ
ˆ™\ÜÛÙ™šXÚX[ÜXÝWÞØ][\ÚYH‹›Û™JBˆØ]™WÙ]J]JBˆ™]\›ˆÈ›ÚÈŽˆYK
Š˜[œÝÙ\‹˜ÛÛ\]YŽˆ][\ÈœÝ]\È—HOH˜ÛÛ\]YŸB‚‚\™Ù]
‹ØYZ[‹ÜÙ\ÜÚ[ÛœËÈŠB™YˆYZ[—ÜÙ\ÜÚ[Ûœ×ÜÛ\ÚÜ™Y\™XÝ

N‚ˆ™]\›ˆ™Y\™XÝ
\›Ù›ÜŠ˜YZ[—ÜÙ\ÜÚ[ÛœÈŠKÛÙOLÌJB‚‚šYˆÜ\™\—ÜÜÝÜ™\×ÜÚYÝÊ
N‚ˆžN‚ˆØ›ÛÝÝ˜\Ü\™\—ÜÜÝÜ™\×ÜÚYÝÊ
Bˆ^Ù\\™\”ÜÝÜ™\Ñ\œ›ÜŽ‚ˆÈÚYÝÈ[ÙH\È[[[Û˜[H›Û‹Y\Ü\]™Nˆ”ÓÓˆ™[XZ[œÈHÛÝ\˜ÙBˆÈ[™XÝ]™H[ÙHÚ[›Ý™H[˜X›Y[[™\šYšXØ][ÛˆÝXØÙYYË‚ˆ\›ÙÙÙ\‹™^Ù\[ÛŠœ\™\—ÜÜÝÜ™\ÈÚYÝ×Ø›ÛÝÝ˜\Ù˜Z[YŠB‚‚šYˆÜ\™\—ÜÜÝÜ™\×ØXÝ]™J
N‚ˆÈH˜Z[Y[š]X[XÝ]Ý™\ˆØ]H]\Ý™]™[H™]ÈÛÜšÙ\ˆœ›ÛHÙ\š[™ÂˆÈ˜Y™šXËˆ™]™\ˆ[\ÜÝ[H”ÓÓˆ]]ÛX]XØ[H[ˆXÝ]™H[ÙK‚ˆÝ™\šYžWÜ\™\—ÜÜÝÜ™\×Ú[š]X[ØÝ]Ý™\Š
B‚‚—ÛÙ×ÛY[[ÜžWÜÝYÙJQ•T—Ô“ÕUWÔ‘QÒTÕUSÓˆ‹ÐTÒSTÔ•ÔÕT•QÐU‹HŠB—ÛÙ×ÛY[[ÜžWÜÝYÙJ’STÔ•ÑS‘Ô‘PS‹ÐTÒSTÔ•ÔÕT•QÐU‹HŠB‚šYˆ×Û˜[YW×ÈOH—×ÛXZ[—×ÈŽ‚ˆXY×Ù[˜X›YHÜË™[š\›Û‹™Ù]
‘“TÒ×ÑP•QÈ‹ŒŠHOHŒH‚ˆ\œ[ŠÜÝHŒŒŒŒ‹ÜZ[
ÜË™[š\›Û‹™Ù]
”Ô•‹L
JKXYÏYXY×Ù[˜X›Y
B