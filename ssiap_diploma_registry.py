"""Issued SSIAP diplomas, archival reissues and public verification."""
import base64
import binascii
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import ijson
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESSIV
from flask import abort, make_response, redirect, render_template, request, send_file, session, url_for
from PIL import Image

import ssiap_diploma_numbers as numbers
import ssiap_exam as exam
import ssiap_exam_diplomas as details
from identity_photos import MAX_SOURCE_BYTES, decode_photo, printable_portrait

PRIVATE_KEYS = "ssiap_verification_private"
MANUAL = "ssiap_manual_diplomas"
HISTORY = "ssiap_issued_diplomas"
LEVELS = {
    "SSIAP 1": "Agent des services de sécurité incendie et d’assistance à personnes",
    "SSIAP 2": "Chef d’équipe des services de sécurité incendie et d’assistance à personnes",
    "SSIAP 3": "Chef de service de sécurité incendie et d’assistance à personnes",
}
FORM_DEFAULTS = dict(civility="Monsieur", birth_country="France", level="SSIAP 1",
                     issuer="Intégrale Academy", issue_place="Puget-sur-Argens")
PRINT_FIELDS = ("first_name", "last_name", "name", "birth_date", "birth_place", "level",
                "number", "exam_number", "exam_date", "exam_place", "issue_date", "issue_place",
                "issuer", "approval", "registration", "representative", "jury_representative",
                "issuer_details", "version", "photo_reference")
ASSOCIATED_DATA = [b"integrale/ssiap/diploma/v1"]


def internal(services, training):
    return (training.get("partner_id") or services.INTEGRALE_PARTNER_ID) == services.INTEGRALE_PARTNER_ID


def fingerprint(row):
    content = json.dumps([row.get(k, "") for k in PRINT_FIELDS], ensure_ascii=False, separators=(",", ":"))
    return hashlib.blake2s(content.encode(), digest_size=16).hexdigest()


def cipher(services, *, create=False):
    # All workers and subsequent deployments use the same key on the persistent disk.
    directory = Path(services.PERSIST_DIR) / PRIVATE_KEYS
    path = directory / "verification.key"
    if create and not path.exists():
        directory.mkdir(mode=0o700, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".ssiap-key-") as temp:
            temp.write(AESSIV.generate_key(bit_length=512))
            temp.flush()
            os.fsync(temp.fileno())
            try:
                os.link(temp.name, path)
            except FileExistsError:
                pass
    return AESSIV(path.read_bytes())


def verification_url(services, row):
    payload = [row["session_id"], row["trainee_id"], row.get("retake_source", ""), fingerprint(row)]
    encrypted = cipher(services, create=True).encrypt(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(), ASSOCIATED_DATA)
    token = base64.urlsafe_b64encode(encrypted).decode().rstrip("=")
    return services._public_base_url().rstrip("/") + "/v/ssiap/" + token


def decode_link(services, token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,640}", token):
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        if base64.urlsafe_b64encode(raw).decode().rstrip("=") != token:
            return None
        return json.loads(cipher(services).decrypt(raw, ASSOCIATED_DATA))
    except (FileNotFoundError, InvalidTag, binascii.Error, UnicodeError, json.JSONDecodeError):
        return None


def session_rows(services, data, training):
    if not internal(services, training):
        return
    roster = services._session_trainees_list(training)
    retakes = training.get("ssiap_exam", {}).get("retake_results", {})
    if not any(t.get("ssiap_diploma_number") for t in roster) and not retakes:
        return
    context = exam.for_family(training, "ssiap")
    candidates = exam.active_candidates(services, context, data=data) if retakes else roster
    for trainee in candidates:
        if trainee.get("ssiap_diploma_number") and numbers.eligible(services, context, trainee):
            yield services._ssiap_diploma_row(context, trainee, lookup_department=False)


def remember_issued(data, rows):
    # A removed enrolment or a reassigned number must not erase the issuance history.
    for row in rows:
        if not row["internal"]:
            continue
        signature = fingerprint(row)
        versions = data.setdefault(HISTORY, {}).setdefault(row["session_id"], {}).setdefault(row["trainee_id"], {})
        if signature not in versions:
            versions[signature] = {k: row[k] for k in ("session_id", "trainee_id", "name", "first_name",
                "last_name", "birth_date", "number", "level", "exam_date", "exam_number")}


def archived_editions(data, active):
    for sid, candidates in data.get(HISTORY, {}).items():
        for tid, versions in candidates.items():
            for signature, row in versions.items():
                if active.get((sid, tid)) != signature:
                    yield dict(row, retired=True)


def portrait_path(services, digest):
    if not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
        return ""
    return str(Path(services.PERSIST_DIR) / "ssiap_portraits" / (digest + ".jpg"))


def manual_row(services, key, record):
    return {**record, "session_id": "", "trainee_id": key, "internal": True, "manual": True,
            "name": " ".join((record["civility"], record["first_name"], record["last_name"])),
            "birth_date": services._diploma_date_fr(record["birth_date"]),
            "birth_place": services._ssiap_birth_place_label(dict(record), lookup_department=False),
            "exam_date": services._diploma_date_fr(record["exam_date"]),
            "issue_date": services._diploma_date_fr(record["issue_date"]),
            "photo_path": portrait_path(services, record["photo_reference"])}


def public_record(services, payload):
    sid, tid, source, expected = payload
    # Stream just the referenced session(s) or archive record. An unknown token
    # never opens the trainee store, and a scan never runs admin maintenance jobs.
    try:
        with open(services.DATA_FILE, "rb") as stream:
            if not sid:
                record = next(ijson.items(stream, f"{MANUAL}.{tid}"), None)
                row = manual_row(services, tid, record) if record else None
            else:
                wanted = {sid, source} - {""}
                found = {}
                for training in ijson.items(stream, "sessions.item"):
                    if training.get("id") in wanted and internal(services, training):
                        found[training["id"]] = training
                        if len(found) == len(wanted):
                            break
                rows = session_rows(services, {"sessions": list(found.values())}, found[sid]) if sid in found else ()
                row = next((item for item in rows if item["trainee_id"] == tid), None)
    except FileNotFoundError:
        return None
    if row and hmac.compare_digest(expected, fingerprint(row)):
        return row
    return None


def form_values(services, form):
    info = details.clean(services, {**form, "result": "certified"})
    for key in ("first_name", "last_name", "birth_date", "birth_city", "birth_country", "exam_date"):
        if not info[key]:
            raise ValueError("Renseignez le champ « " + details.LABELS[key] + " ».")
    if form.get("level") not in LEVELS:
        raise ValueError("Choisissez le niveau SSIAP du diplôme d’origine.")
    info["level"] = form["level"]
    for key, label, limit, required in (
            ("number", "Numéro du diplôme", 90, True), ("exam_number", "Numéro d’examen", 90, True),
            ("issue_place", "Lieu de délivrance", 120, True), ("issuer", "Organisme de formation", 150, True),
            ("exam_place", "Lieu d’examen", 160, False), ("approval", "Agrément préfectoral", 250, False),
            ("registration", "Référence de certification", 140, False),
            ("representative", "Représentant du centre", 140, False),
            ("jury_representative", "Représentant du DDSIS", 140, False),
            ("issuer_details", "Coordonnées de l’organisme", 250, False)):
        value = " ".join(str(form.get(key) or "").split())
        if (required and not value) or len(value) > limit:
            raise ValueError(f"Vérifiez le champ « {label} » ({limit} caractères maximum).")
        info[key] = value
    info["issue_date"] = details.iso_date(services, form.get("issue_date"))
    today = dt.datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    if not info["birth_date"] < info["exam_date"] <= info["issue_date"] <= today:
        raise ValueError("Vérifiez les dates de naissance, d’examen et de délivrance d’origine.")
    info.pop("result")
    return info


def prepare_portrait(upload):
    if not upload or not upload.filename:
        return None
    content = upload.stream.read(MAX_SOURCE_BYTES + 1)
    if len(content) > MAX_SOURCE_BYTES:
        raise ValueError("La photo dépasse 25 Mo.")
    with decode_photo(content, 1000) as photo:
        output = io.BytesIO()
        photo.save(output, "JPEG", quality=92, optimize=True)
    return output.getvalue()


def verification_portrait(path):
    """Embed the printable crop in the verified response without exposing the upload."""
    if not path:
        return None
    try:
        with printable_portrait(path) as photo:
            return "data:image/jpeg;base64," + base64.b64encode(photo.getbuffer()).decode("ascii")
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def store_portrait(path, content):
    dest = Path(path)
    dest.parent.mkdir(exist_ok=True, mode=0o700)
    if dest.exists():
        return
    with tempfile.NamedTemporaryFile(dir=dest.parent, prefix=".portrait-") as temp:
        temp.write(content)
        temp.flush()
        os.fsync(temp.fileno())
        try:
            os.link(temp.name, dest)
        except FileExistsError:
            pass


def register(app, services):
    def internal_access():
        if services._is_partner_data_scope_session() or services._is_external_partner_session():
            abort(403)

    def private(response):
        response.headers.update({"Cache-Control": "private, no-store", "X-Robots-Tag": "noindex, nofollow, noarchive",
                                 "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"})
        return response

    @app.get("/v/ssiap/<token>")
    def public_ssiap_diploma(token):
        payload = decode_link(services, token)
        record = public_record(services, payload) if payload else None
        portrait = verification_portrait(record["photo_path"]) if record else None
        return private(make_response(render_template("ssiap_diploma_verify.html", diploma=record,
                                                    levels=LEVELS, portrait=portrait), 200 if record else 404))

    @app.get("/admin/outils/diplomes-ssiap")
    @services.admin_login_required
    def admin_ssiap_registry():
        internal_access()
        data = services.load_data(run_background_tasks=False)
        rows = [row for training in data.get("sessions", []) for row in session_rows(services, data, training)]
        active = {(r["session_id"], r["trainee_id"]): fingerprint(r) for r in rows}
        rows.extend(archived_editions(data, active))
        rows.extend(manual_row(services, k, v) for k, v in data.get(MANUAL, {}).items())
        query = services._normalized_commune_name(request.args.get("q", "")).split()
        year = request.args.get("annee", "")
        years = sorted({r["exam_date"][-4:] for r in rows if r["exam_date"]}, reverse=True)
        def matches(row):
            text = services._normalized_commune_name(" ".join((row["name"], row["number"], row["exam_number"], row["level"])))
            return (not year or row["exam_date"][-4:] == year) and all(term in text for term in query)
        rows = [r for r in rows if matches(r)]
        rows.sort(key=lambda r: (tuple(reversed(r["exam_date"].split("/"))), r["number"]), reverse=True)
        return private(make_response(render_template("admin_ssiap_registry.html", rows=rows, years=years, year=year)))

    @app.get("/admin/outils/diplomes-ssiap/pdf/<session_id>/<trainee_id>")
    @services.admin_login_required
    def admin_ssiap_registry_session_pdf(session_id, trainee_id):
        internal_access()
        data = services.load_data(run_background_tasks=False)
        training = services.find_session(data, session_id)
        rows = session_rows(services, data, training) if training else ()
        row = next((r for r in rows if r["trainee_id"] == trainee_id), None)
        if not row:
            abort(404)
        return diploma_pdf(row)

    def diploma_pdf(row):
        pdf = services._build_ssiap_diplomas_pdf([row])
        return private(send_file(pdf, mimetype="application/pdf", as_attachment=True,
                                 download_name="Diplome-" + services.secure_filename(row["number"]) + ".pdf"))

    @app.get("/admin/outils/diplomes-ssiap/archives/<key>/pdf")
    @services.admin_login_required
    def admin_ssiap_manual_pdf(key):
        internal_access()
        record = services.load_data(run_background_tasks=False).get(MANUAL, {}).get(key)
        if not record:
            abort(404)
        return diploma_pdf(manual_row(services, key, record))

    @app.get("/admin/outils/diplomes-ssiap/archives/<key>/photo")
    @services.admin_login_required
    def admin_ssiap_manual_photo(key):
        internal_access()
        record = services.load_data(run_background_tasks=False).get(MANUAL, {}).get(key)
        path = portrait_path(services, record["photo_reference"]) if record else ""
        if not path or not Path(path).is_file():
            abort(404)
        return private(send_file(path, mimetype="image/jpeg"))

    @app.route("/admin/outils/diplomes-ssiap/regenerer", methods=["GET", "POST"])
    @app.route("/admin/outils/diplomes-ssiap/archives/<key>/modifier", methods=["GET", "POST"])
    @services.admin_login_required
    @services.admin_write_required
    def admin_ssiap_reissue(key=None):
        internal_access()
        token = session.setdefault("ssiap_archive_csrf", secrets.token_urlsafe(32))
        data = services.load_data(run_background_tasks=False)
        original = data.get(MANUAL, {}).get(key)
        if key and not original:
            abort(404)
        values = original or FORM_DEFAULTS
        error, status = "", 200
        if request.method == "POST":
            if not hmac.compare_digest(token, request.form.get("csrf", "")):
                abort(403)
            values = request.form.to_dict()
            try:
                fields = form_values(services, values)
                photo = prepare_portrait(request.files.get("photo"))
                if not photo and not original:
                    raise ValueError("Sélectionnez la photo d’identité à imprimer sur le diplôme.")
                digest = hashlib.sha256(photo).hexdigest() if photo else original["photo_reference"]
                entry_id = key or secrets.token_hex(16)

                def save(current):
                    archive = current.setdefault(MANUAL, {})
                    saved = archive.get(entry_id)
                    if key and (not saved or saved["version"] != values.get("version")):
                        abort(409, description="Ce diplôme a été modifié. Rouvrez sa fiche avant de le corriger.")
                    number = fields["number"].upper()
                    duplicates = any(k != entry_id and rec["number"].upper() == number for k, rec in archive.items())
                    if duplicates or any(str(t.get("ssiap_diploma_number") or "").upper() == number
                                         for training in current.get("sessions", []) if internal(services, training)
                                         for t in numbers.numbering_trainees(services, training)):
                        raise ValueError("Ce numéro figure déjà dans le registre. Ouvrez le diplôme existant pour le corriger.")
                    if photo:
                        store_portrait(portrait_path(services, digest), photo)
                    archive[entry_id] = dict(fields, photo_reference=digest, version=secrets.token_hex(12))
                    return {"id": entry_id}

                services._atomic_update_data(save)
                return redirect(url_for("admin_ssiap_registry", q=fields["number"], regenere=entry_id), code=303)
            except ValueError as exc:
                error, status = str(exc), 400
        return private(make_response(render_template("admin_ssiap_reissue.html", values=values, levels=LEVELS,
                            key=key, csrf=token, error=error), status))
