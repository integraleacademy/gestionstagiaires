"""One-dossier browser observation pilot, isolated from all business workflows.

No EDOF request, authentication material, business write, or outbound HTTP call
belongs in this module. A browser response is an observation, not a signed API
attestation. The receiver stores only the explicit schema below; results expire after 24 hours and are purged on access.
"""

import datetime as dt
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import zipfile
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, jsonify, request, send_file, session


TEST_SERVICE_ID = "srv-d928tc19rddc7388qie0"
TEST_ORIGIN = "https://gestionstagiaires-test-v2.onrender.com"
SIRET = "84089988400026"
PAIR_TTL = 15 * 60
RESULT_TTL = 24 * 60 * 60
MAX_BODY = 32 * 1024
ID_RE = re.compile(r"[0-9]{6,20}\Z")
KEY_RE = re.compile(r"edoftest1\.([0-9]{6,20})\.([A-Za-z0-9_-]{43})\Z")
TOP_FIELDS = {
    "id", "trainingId", "trainingActionId", "currentState", "beginDate",
    "endDate", "currentBillingState", "billingDate", "paymentState",
    "codeReconnaissance", "attendee", "trainingActionInfo",
}
ATTENDEE_FIELDS = {"firstName", "lastName", "email"}
INFO_FIELDS = {
    "title", "sessionId", "sessionStartDate", "sessionEndDate", "totalIncl",
    "teachingFees", "indicativeDuration", "hoursInCenter",
    "trainingCompletionRate", "validatedServiceDone",
}
STATE_LABELS = {
    "accepted": "Accepté", "inTraining": "Entrée déclarée",
    "serviceDoneDeclared": "Service fait déclaré",
    "serviceDoneValidated": "Service fait validé",
}


class InvalidObservation(ValueError):
    pass


def _object(value, allowed):
    if not isinstance(value, dict) or set(value) - allowed:
        raise InvalidObservation("Format non reconnu : utilisez le module Chrome fourni.")
    return value


def _text(value, limit=250):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise InvalidObservation("Un champ texte est invalide.")
    return value.strip() or None


def _date(value):
    value = _text(value, 32)
    if value is None:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise InvalidObservation("Une date est invalide.")


def _number(value, maximum=10_000_000):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidObservation("Un montant ou une durée est invalide.")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not 0 <= number <= maximum:
            raise InvalidObservation("Un montant ou une durée est hors limites.")
        return format(number.quantize(Decimal("0.01")), "f")
    except InvalidOperation as exc:
        raise InvalidObservation("Un nombre est invalide.") from exc


def normalize_observation(payload, expected_id):
    envelope = _object(payload, {"siret", "folder"})
    if envelope.get("siret") != SIRET:
        raise InvalidObservation("L’organisme ne correspond pas à cet essai.")
    folder = _object(envelope.get("folder"), TOP_FIELDS)
    if folder.get("id") != expected_id or not ID_RE.fullmatch(expected_id):
        raise InvalidObservation("Le dossier ne correspond pas au numéro préparé.")
    attendee = _object({} if folder.get("attendee") is None else folder["attendee"], ATTENDEE_FIELDS)
    info = _object({} if folder.get("trainingActionInfo") is None else folder["trainingActionInfo"], INFO_FIELDS)
    for value in (folder.get("trainingId"), folder.get("trainingActionId"), info.get("sessionId")):
        value = _text(value)
        if value and not value.startswith(SIRET + "_"):
            raise InvalidObservation("La formation ne correspond pas à cet organisme.")
    validated = info.get("validatedServiceDone")
    if validated is not None and not isinstance(validated, bool):
        raise InvalidObservation("La validation du service fait est invalide.")
    return {
        "folder_id": expected_id,
        "first_name": _text(attendee.get("firstName"), 120),
        "last_name": _text(attendee.get("lastName"), 120),
        "email": _text(attendee.get("email"), 254),
        "title": _text(info.get("title"), 1000),
        "training_id": _text(folder.get("trainingId")),
        "training_action_id": _text(folder.get("trainingActionId")),
        "edof_session_id": _text(info.get("sessionId")),
        "start_date": _date(folder.get("beginDate")),
        "end_date": _date(folder.get("endDate")),
        "session_start_date": _date(info.get("sessionStartDate")),
        "session_end_date": _date(info.get("sessionEndDate")),
        "state": _text(folder.get("currentState"), 80),
        "certification_code": _text(folder.get("codeReconnaissance"), 80),
        "total_incl": _number(info.get("totalIncl")),
        "teaching_fees": _number(info.get("teachingFees")),
        "duration_hours": _number(info.get("indicativeDuration"), 10000),
        "center_hours": _number(info.get("hoursInCenter"), 10000),
        "completion_rate": _number(info.get("trainingCompletionRate"), 100),
        "service_done_validated": validated,
        "billing_state": _text(folder.get("currentBillingState"), 80),
        "billing_date": _date(folder.get("billingDate")),
        "payment_state": _text(folder.get("paymentState"), 80),
    }


class ObservationStore:
    def __init__(self, directory):
        self.path = Path(directory) / "edof_readonly_test.sqlite3"

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Create with restrictive permissions before SQLite opens the file.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA secure_delete = ON")
        db.execute("""CREATE TABLE IF NOT EXISTS observations (
            key_hash TEXT PRIMARY KEY, owner TEXT NOT NULL, folder_id TEXT NOT NULL,
            expires_at REAL NOT NULL, received_at REAL, result TEXT)""")
        now = time.time()
        db.execute("DELETE FROM observations WHERE (result IS NULL AND expires_at < ?) OR received_at < ?",
                   (now, now - RESULT_TTL))
        db.commit()
        return db

    def prepare(self, owner, folder_id):
        key = f"edoftest1.{folder_id}.{secrets.token_urlsafe(32)}"
        db = self.connect()
        try:
            with db:
                db.execute("DELETE FROM observations WHERE owner = ? AND result IS NULL", (owner,))
                db.execute("INSERT INTO observations (key_hash, owner, folder_id, expires_at) VALUES (?, ?, ?, ?)",
                           (hashlib.sha256(key.encode()).hexdigest(), owner, folder_id, time.time() + PAIR_TTL))
            return key
        finally:
            db.close()

    def receive(self, key, payload):
        match = KEY_RE.fullmatch(key)
        if not match:
            raise PermissionError("Code d’essai invalide, expiré ou déjà utilisé.")
        db = self.connect()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                digest = hashlib.sha256(key.encode()).hexdigest()
                row = db.execute("SELECT * FROM observations WHERE key_hash = ?", (digest,)).fetchone()
                if not row or row["expires_at"] < time.time() or row["result"] is not None:
                    raise PermissionError("Code d’essai invalide, expiré ou déjà utilisé.")
                observation = normalize_observation(payload, row["folder_id"])
                # Keep at most one result per browser session, away from data.json.
                db.execute("DELETE FROM observations WHERE owner = ? AND result IS NOT NULL", (row["owner"],))
                db.execute("UPDATE observations SET result = ?, received_at = ? WHERE key_hash = ?",
                           (json.dumps(observation, ensure_ascii=False), time.time(), digest))
        finally:
            db.close()

    def latest(self, owner):
        db = self.connect()
        try:
            row = db.execute("SELECT result, received_at FROM observations WHERE owner = ? AND result IS NOT NULL ORDER BY received_at DESC LIMIT 1", (owner,)).fetchone()
            if not row:
                return None
            return {"fields": json.loads(row["result"]), "received_at": dt.datetime.fromtimestamp(row["received_at"], dt.timezone.utc).isoformat()}
        finally:
            db.close()

    def clear(self, owner):
        db = self.connect()
        try:
            with db:
                db.execute("DELETE FROM observations WHERE owner = ?", (owner,))
        finally:
            db.close()


def local_comparison(data, folder_id):
    """Only exact existing CPF links; never create a match from a person's name."""
    links = [item for item in data.get("wedof_links", []) if isinstance(item, dict)
             and item.get("active") is True and str(item.get("external_id") or "") == folder_id]
    if len(links) != 1:
        return {"status": "ambiguous" if links else "absent"}
    link = links[0]
    matches = []
    for group in data.get("sessions", []):
        if not isinstance(group, dict) or str(group.get("id")) != str(link.get("session_id")):
            continue
        for trainee in group.get("trainees", group.get("stagiaires", [])) or []:
            if isinstance(trainee, dict) and str(trainee.get("id")) == str(link.get("trainee_id")):
                matches.append({"status": "found", "session_name": group.get("name"),
                                "first_name": trainee.get("first_name") or trainee.get("prenom"),
                                "last_name": trainee.get("last_name") or trainee.get("nom"),
                                "email": trainee.get("email") or trainee.get("mail"),
                                "start_date": group.get("date_start") or group.get("date_debut"),
                                "end_date": group.get("date_end") or group.get("date_fin")})
    return matches[0] if len(matches) == 1 else {"status": "ambiguous" if matches else "stale"}


def register_edof_readonly_test(legacy):
    app = legacy.app
    # Server-side identity, never the caller-controlled Host header. No env
    # change or production Blueprint change is needed for this temporary pilot.
    enabled = os.environ.get("RENDER_SERVICE_ID") == TEST_SERVICE_ID
    app.config["EDOF_READONLY_TEST_ENABLED"] = enabled
    if not enabled:
        return
    register_routes(app, ObservationStore("/var/data"),
                    admin_required=legacy.admin_login_required,
                    can_access=lambda: legacy._is_super_admin_session() and not session.get("assist_partner_id"),
                    data_file=legacy.DATA_FILE)


def register_routes(app, store, *, admin_required, can_access, data_file):
    bp = Blueprint("edof_test", __name__)

    def admin_guard():
        if not can_access():
            abort(403)

    def owner():
        if not session.get("edof_test_owner"):
            session["edof_test_owner"] = secrets.token_urlsafe(32)
        return hashlib.sha256(session["edof_test_owner"].encode()).hexdigest()

    def check_csrf():
        expected = session.get("edof_test_csrf", "")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not hmac.compare_digest(expected, supplied):
            abort(403)

    @bp.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @bp.get("/api/edof-test/ping")
    def ping():
        return jsonify(ok=True, version="1.0", mode="browser_observation", autonomous_sync=False)

    @bp.get("/admin/edof-test")
    @admin_required
    def index():
        admin_guard()
        csrf = session.setdefault("edof_test_csrf", secrets.token_urlsafe(32))
        latest = store.latest(owner())
        comparison = None
        if latest:
            try:
                # Direct read avoids legacy load_data migrations/background jobs.
                with open(data_file, "r", encoding="utf-8") as source:
                    comparison = local_comparison(json.load(source), latest["fields"]["folder_id"])
            except (OSError, ValueError, TypeError, AttributeError):
                comparison = {"status": "unavailable"}
        # Do not run legacy context processors (notifications, CRM, etc.).
        return app.jinja_env.get_template("edof_readonly_test.html").render(
            csrf=csrf, latest=latest, comparison=comparison, state_labels=STATE_LABELS)

    @bp.get("/admin/edof-test/assets/<name>")
    @admin_required
    def asset(name):
        admin_guard()
        if name not in {"page.css", "page.js"}:
            abort(404)
        return send_file(Path(__file__).parent / "edof_test_assets" / name)

    @bp.post("/admin/edof-test/prepare")
    @admin_required
    def prepare():
        admin_guard()
        check_csrf()
        payload = request.get_json(silent=True)
        folder_id = payload.get("folder_id") if isinstance(payload, dict) else None
        if not isinstance(folder_id, str) or not ID_RE.fullmatch(folder_id):
            return jsonify(ok=False, error="Saisissez le numéro du dossier CPF, uniquement en chiffres."), 400
        return jsonify(ok=True, code=store.prepare(owner(), folder_id), expires_in=PAIR_TTL)

    @bp.post("/admin/edof-test/clear")
    @admin_required
    def clear():
        admin_guard()
        check_csrf()
        store.clear(owner())
        return jsonify(ok=True)

    @bp.post("/api/edof-test/receive")
    def receive():
        key = request.headers.get("X-Edof-Test-Key", "")
        if not KEY_RE.fullmatch(key):
            return jsonify(ok=False, error="Code d’essai requis."), 401
        if request.mimetype != "application/json":
            return jsonify(ok=False, error="Format JSON requis."), 415
        if request.content_length is not None and request.content_length > MAX_BODY:
            return jsonify(ok=False, error="Réponse trop volumineuse."), 413
        raw = request.stream.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            return jsonify(ok=False, error="Réponse trop volumineuse."), 413
        try:
            payload = json.loads(raw)
            store.receive(key, payload)
        except PermissionError as exc:
            return jsonify(ok=False, error=str(exc)), 401
        except (InvalidObservation, ValueError, UnicodeError):
            return jsonify(ok=False, error="Le dossier reçu ne correspond pas au format ou au numéro préparé."), 400
        return jsonify(ok=True, message="Dossier reçu dans l’aperçu Test V2."), 201

    @bp.get("/admin/edof-test/extension.zip")
    @admin_required
    def extension():
        admin_guard()
        root = Path(__file__).parent / "browser_extensions" / "edof_test"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in ("manifest.json", "devtools.html", "devtools.js", "panel.html", "panel.js", "core.js", "panel.css", "README.txt"):
                archive.write(root / name, "integrale-edof-test/" + name)
        buffer.seek(0)
        return send_file(buffer, mimetype="application/zip", as_attachment=True,
                         download_name="integrale-edof-test.zip", max_age=0)

    app.register_blueprint(bp)
