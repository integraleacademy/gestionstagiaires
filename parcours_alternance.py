"""Public 2027 apprenticeship applications and private, durable admissions inbox."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

YEAR = 2027
PUBLIC_URL = "https://www.integraleconnect.com/parcoursalternance"
ADMIN_URL = "https://gestionstagiaires-r5no.onrender.com/admin/parcours-alternance"
CONTACT = "ecole@integraleacademy.com"
STATUSES = {"new": "Nouvelle", "contacted": "À recontacter", "interview": "Entretien prévu", "accepted": "Retenue", "declined": "Non retenue", "archived": "Archivée"}
SITUATIONS = ("En études", "En emploi", "En recherche d’emploi", "En reconversion", "Autre situation")
SLOTS = ("Le matin", "L’après-midi", "Peu importe")
TIMELINE = (
    {"period": "Janvier → février", "title": "Tu prépares l’APS", "detail": "175 h de formation, examen puis demande de carte professionnelle CNAPS.", "kind": "aps"},
    {"period": "Mars → juin", "title": "Tu passes à l’action en entreprise", "detail": "Tes premières missions de sécurité, après obtention des autorisations nécessaires.", "kind": "work"},
    {"period": "Juin → juillet", "title": "Tu prépares l’A3P", "detail": "328 h pour apprendre la protection physique des personnes et le travail en équipe.", "kind": "a3p"},
    {"period": "Juillet → décembre", "title": "Tu développes ton expérience", "detail": "Une nouvelle période en entreprise pour gagner en autonomie.", "kind": "work"},
    {"period": "Décembre", "title": "Tu complètes avec le SSIAP 1", "detail": "70 h de formation en sécurité incendie, puis l’examen.", "kind": "ssiap"},
)


def today():
    return dt.datetime.now(ZoneInfo("Europe/Paris")).date()


def age_on(birth, day):
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def validate(payload, day=None):
    if not isinstance(payload, dict):
        raise ValueError("Le formulaire est invalide.")
    day = day or today()
    try:
        birth = dt.date.fromisoformat(str(payload.get("birth_date", "")))
    except ValueError:
        raise ValueError("Indique une date de naissance valide.") from None
    if birth >= day or age_on(birth, day) > 120:
        raise ValueError("Vérifie ta date de naissance.")
    if age_on(birth, day) >= 26:
        raise ValueError("Malheureusement, tu ne peux pas candidater à ce parcours sécurité en alternance : il est réservé aux personnes de moins de 26 ans au moment de leur candidature.")
    if payload.get("available_year") is not True:
        raise ValueError("Tu dois être disponible de janvier à décembre 2027 pour candidater à ce parcours.")
    if payload.get("judicial_clear") is not True:
        raise ValueError("Malheureusement, tu ne peux pas poursuivre cette candidature en ligne. Contacte notre équipe pour faire le point sur ta situation et les démarches CNAPS. Seul le CNAPS décide de la délivrance de ses autorisations.")
    if payload.get("license_b") is not True:
        raise ValueError("Le permis B est nécessaire pour ce parcours. Contacte-nous pour préparer une future candidature.")
    if payload.get("mobile_departments") is not True:
        raise ValueError("Tu dois pouvoir te déplacer en entreprise dans le Var et les Alpes-Maritimes, notamment à Cannes.")
    if payload.get("privacy_consent") is not True:
        raise ValueError("Confirme que tu as lu l’information sur tes données et que tu souhaites être recontacté pour ta candidature.")
    clean = {}
    for field, label, minimum, maximum in (
        ("last_name", "ton nom", 1, 100), ("first_name", "ton prénom", 1, 100),
        ("city", "ta ville", 2, 120), ("motivation", "ta motivation (30 caractères minimum)", 30, 2000),
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
            raise ValueError(f"Vérifie {label}.")
        clean[field] = value.strip()
    for field in ("last_name", "first_name", "city"):
        clean[field] = " ".join(clean[field].split())
    clean["last_name"] = clean["last_name"].upper()
    email = str(payload.get("email", "")).strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^\s<>@\x00-\x1f]+@[^\s<>@\x00-\x1f]+\.[^\s<>@\x00-\x1f]+", email):
        raise ValueError("Vérifie ton adresse e-mail.")
    phone = re.sub(r"[ .()\-]", "", str(payload.get("phone", "")))
    if not re.fullmatch(r"(?:0[1-9]\d{8}|\+[1-9]\d{7,14})", phone):
        raise ValueError("Vérifie ton numéro de téléphone, par exemple 06 12 34 56 78.")
    postcode = str(payload.get("postcode", "")).strip()
    if not re.fullmatch(r"\d{5}", postcode):
        raise ValueError("Indique un code postal à 5 chiffres.")
    situation, slot, vehicle = payload.get("situation"), payload.get("contact_slot"), payload.get("vehicle")
    if situation not in SITUATIONS or slot not in SLOTS or vehicle not in ("yes", "no", "planned"):
        raise ValueError("Complète ta situation, ton moyen de transport et ton créneau de contact.")
    clean.update(birth_date=birth.isoformat(), email=email, phone=phone, postcode=postcode,
                 situation=situation, contact_slot=slot, vehicle=vehicle, campaign=YEAR,
                 available_year=True, license_b=True, mobile_departments=True, privacy_consent=True,
                 privacy_version="2026-10-22", age_at_submission=age_on(birth, day))
    # Do not persist criminal-history answers, failed applications or arbitrary fields.
    return clean


@contextmanager
def database(host):
    path = Path(host.PERSIST_DIR) / "parcours_alternance.sqlite3"
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA busy_timeout=15000")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS applications (
          id TEXT PRIMARY KEY, dedupe TEXT UNIQUE NOT NULL, request_key TEXT UNIQUE NOT NULL,
          created_at TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
          notes TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 0,
          staff_mail TEXT NOT NULL DEFAULT 'pending', candidate_mail TEXT NOT NULL DEFAULT 'pending',
          staff_attempt TEXT, candidate_attempt TEXT,
          staff_tries INTEGER NOT NULL DEFAULT 0, candidate_tries INTEGER NOT NULL DEFAULT 0,
          staff_error TEXT NOT NULL DEFAULT '', candidate_error TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires INTEGER NOT NULL);
        """)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def unpack(row):
    if row is None:
        abort(404)
    item = dict(row)
    item.update(json.loads(item.pop("payload")))
    item["created_display"] = dt.datetime.fromisoformat(item["created_at"]).astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H:%M")
    item["birth_display"] = dt.date.fromisoformat(item["birth_date"]).strftime("%d/%m/%Y")
    return item


def deliver(host, application_id, *, automatic=False):
    """Durable per-recipient states; a retry never resends an accepted email."""
    for kind in ("staff", "candidate"):
        now = dt.datetime.now(dt.timezone.utc)
        cutoff = (now - dt.timedelta(minutes=5)).isoformat()
        due = f" AND {kind}_tries<5 AND ({kind}_attempt IS NULL OR {kind}_attempt<?)" if automatic else ""
        with database(host) as db:
            claimed = db.execute(f"""UPDATE applications SET {kind}_mail='sending', {kind}_attempt=?, {kind}_tries={kind}_tries+1
                WHERE id=? AND ({kind}_mail IN ('pending','failed') OR ({kind}_mail='sending' AND {kind}_attempt<?)){due}""",
                (now.isoformat(), application_id, cutoff) + ((cutoff,) if automatic else ())).rowcount
            row = db.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone()
        if not claimed or row is None:
            continue
        item = unpack(row)
        staff = kind == "staff"
        recipient = "clement@integraleacademy.com" if staff else item["email"]
        title = f"Nouvelle candidature alternance 2027 · {item['first_name']} {item['last_name']}" if staff else "Ta candidature est bien reçue · Intégrale Academy"
        body = host.app.jinja_env.get_template("parcours_alternance/email.html").render( item=item, staff=staff, public_url=PUBLIC_URL,
                               admin_url=ADMIN_URL, contact=CONTACT)
        plain = (f"Nouvelle candidature : {item['first_name']} {item['last_name']}. Consultez le dossier : {ADMIN_URL}/{application_id}" if staff else
                 f"Bonjour {item['first_name']}, ta candidature au parcours sécurité en alternance 2027 est bien enregistrée sous la référence {application_id}. Notre équipe va étudier ton projet et te recontacter. Ce message ne vaut pas admission. Contact : {CONTACT}, 04 22 47 07 68.")
        try:
            result = host.brevo_send_email(recipient, title, body, text_content=plain,
                sender_name="Intégrale Academy", reply_to={"email": item["email"] if staff else CONTACT, "name": item["first_name"] if staff else "Intégrale Academy"},
                metadata={"purpose": "parcours_alternance_" + kind, "idempotency_key": f"alternance-{application_id}-{kind}"})
            ok = result.get("ok") is True if isinstance(result, dict) else result is True
        except Exception:
            host.app.logger.warning("alternance_email_failed application_id=%s kind=%s", application_id, kind)
            ok = False
        with database(host) as db:
            db.execute(f"UPDATE applications SET {kind}_mail=?, {kind}_error=? WHERE id=?",
                       ("sent" if ok else "failed", "" if ok else "Envoi non confirmé. Vous pouvez réessayer.", application_id))


def register(host):
    bp = Blueprint("parcours_alternance", __name__)
    serializer = URLSafeTimedSerializer(host.app.secret_key, salt="parcours-alternance-2027")

    def csrf():
        return session.setdefault("parcours_alternance_csrf", secrets.token_urlsafe(32))

    def check_csrf(value):
        expected = session.get("parcours_alternance_csrf", "")
        if not expected or not isinstance(value, str) or not hmac.compare_digest(expected, value):
            abort(400, "Le formulaire a expiré. Recharge la page avant de réessayer.")

    def staff_only(view):
        @wraps(view)
        @host.admin_login_required
        def wrapped(*args, **kwargs):
            if not host._is_super_admin_session() or session.get("assist_partner_id"):
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    @bp.after_request
    def private_response(response):
        if request.endpoint != "parcours_alternance.brochure":
            response.headers["Cache-Control"] = "no-store"
        if "/candidature" in request.path or "/admin/" in request.path:
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        if request.endpoint in {"parcours_alternance.application", "parcours_alternance.submit"}:
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'self'; form-action 'self'"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    @bp.get("/parcoursalternance")
    @bp.get("/parcoursalternance/")
    def landing():
        return render_template("parcours_alternance/landing.html", timeline=TIMELINE, public_url=PUBLIC_URL)

    @bp.get("/parcoursalternance/candidature")
    def application():
        return render_template("parcours_alternance/application.html", timeline=TIMELINE, csrf=csrf(),
            submission_token=serializer.dumps(uuid.uuid4().hex), server_date=today().isoformat(),
            situations=SITUATIONS, slots=SLOTS, public_url=PUBLIC_URL)

    @bp.get("/parcoursalternance/brochure")
    def brochure():
        return send_file(Path(host.app.root_path) / "static/parcours-alternance/brochure-parcours-alternance-2027.pdf",
            mimetype="application/pdf", as_attachment=True, download_name="Brochure-Parcours-securite-alternance-2027.pdf", max_age=3600)

    @bp.post("/parcoursalternance/candidature")
    def submit():
        if request.content_length and request.content_length > 20000:
            return {"ok": False, "error": "Le formulaire est trop volumineux."}, 413
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return {"ok": False, "error": "Le formulaire est invalide."}, 400
        check_csrf(payload.get("csrf"))
        try:
            token = serializer.loads(str(payload.get("submission_token", "")), max_age=86400)
        except (BadSignature, SignatureExpired):
            return {"ok": False, "error": "Le formulaire a expiré. Recharge la page pour recommencer."}, 400
        key = hashlib.sha256(token.encode()).hexdigest()
        if payload.get("website"):
            return {"ok": False, "error": "La candidature n’a pas pu être envoyée."}, 400
        now = dt.datetime.now(dt.timezone.utc)
        # Only an HMAC of the remote address is kept, for at most 24 hours.
        address = (request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip() or request.remote_addr or "unknown")[:200]
        rate_key = hmac.new(str(host.app.secret_key).encode(), f"{address}:{now.date()}".encode(), hashlib.sha256).hexdigest()
        with database(host) as db:
            previous = db.execute("SELECT id,candidate_mail FROM applications WHERE request_key=?", (key,)).fetchone()
            if previous:
                return {"ok": True, "reference": previous["id"], "email_sent": previous["candidate_mail"] == "sent"}
            db.execute("DELETE FROM rate_limits WHERE expires<?", (int(now.timestamp()),))
            db.execute("INSERT INTO rate_limits VALUES (?, 1, ?) ON CONFLICT(key) DO UPDATE SET count=count+1",
                       (rate_key, int(now.timestamp()) + 86400))
            count = db.execute("SELECT count FROM rate_limits WHERE key=?", (rate_key,)).fetchone()["count"]
        if count > 30:
            return {"ok": False, "error": "Trop de tentatives. Réessaie plus tard ou contacte notre équipe."}, 429
        try:
            clean = validate(payload)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        dedupe = hashlib.sha256(f"{YEAR}:{clean['email']}:{clean['birth_date']}".encode()).hexdigest()
        reference = "ALT-" + uuid.uuid4().hex[:12].upper()
        with database(host) as db:
            db.execute("DELETE FROM applications WHERE created_at<?", ((now - dt.timedelta(days=365)).isoformat(),))
            inserted = db.execute("INSERT OR IGNORE INTO applications (id,dedupe,request_key,created_at,payload) VALUES (?,?,?,?,?)",
                                 (reference, dedupe, key, now.isoformat(), json.dumps(clean, ensure_ascii=False))).rowcount
        if not inserted:
            # Do not disclose an existing application identifier to a different browser.
            return {"ok": True, "reference": "", "already_received": True}
        deliver(host, reference)
        with database(host) as db:
            row = db.execute("SELECT candidate_mail FROM applications WHERE id=?", (reference,)).fetchone()
        return {"ok": True, "reference": reference, "email_sent": row["candidate_mail"] == "sent"}, 201

    @bp.get("/admin/parcours-alternance")
    @staff_only
    def inbox():
        query = request.args.get("q", "").strip()[:100].casefold()
        status = request.args.get("status", "")
        with database(host) as db:
            rows = [unpack(row) for row in db.execute("SELECT * FROM applications ORDER BY created_at DESC")]
        counts = {key: sum(row["status"] == key for row in rows) for key in STATUSES}
        selected = [row for row in rows if (not status or row["status"] == status) and (not query or query in " ".join(str(row[k]) for k in ("first_name", "last_name", "email", "city", "id")).casefold())]
        return render_template("parcours_alternance/admin.html", applications=selected, counts=counts,
                               title="Parcours alternance · Candidatures", total=len(rows), statuses=STATUSES, status=status, q=request.args.get("q", ""), public_url=PUBLIC_URL)

    @bp.get("/admin/parcours-alternance/<application_id>")
    @staff_only
    def detail(application_id):
        with database(host) as db:
            item = unpack(db.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone())
        return render_template("parcours_alternance/detail.html", title=f"{item['first_name']} {item['last_name']} · Parcours alternance", item=item, statuses=STATUSES, csrf=csrf())

    @bp.post("/admin/parcours-alternance/<application_id>")
    @staff_only
    def update(application_id):
        check_csrf(request.form.get("csrf"))
        action = request.form.get("action")
        with database(host) as db:
            item = unpack(db.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone())
            if action == "save":
                status, notes = request.form.get("status"), request.form.get("notes", "").strip()
                if status not in STATUSES or len(notes) > 4000:
                    abort(400)
                updated = db.execute("UPDATE applications SET status=?, notes=?, revision=revision+1 WHERE id=? AND revision=?",
                    (status, notes, application_id, request.form.get("revision"))).rowcount
                if not updated:
                    abort(409, "Ce dossier a été modifié entre-temps. Rechargez-le avant d’enregistrer.")
            elif action == "delete":
                db.execute("DELETE FROM applications WHERE id=?", (application_id,))
            elif action != "retry":
                abort(400)
        if action == "retry":
            deliver(host, application_id)
            flash("La relance des envois a été effectuée. Consultez l’état de chaque mail ci-dessous.", "info")
        elif action == "delete":
            flash("La candidature a été supprimée.", "success")
            return redirect(url_for("parcours_alternance.inbox"))
        else:
            flash("Le suivi a été enregistré.", "success")
        return redirect(url_for("parcours_alternance.detail", application_id=application_id))

    host.app.register_blueprint(bp)
    # Apply the established public-page security and indexing policy to the showcase.
    host.manuals_shop.manuals_public.CACHEABLE.add("parcours_alternance.landing")
    # Logged-in shop customers can also visit the public recruitment pages.
    host.manuals_shop.SAFE_ENDPOINTS.update({"parcours_alternance." + name for name in ("landing", "application", "submit", "brochure")})


def maintain(host):
    """Retry unconfirmed mail after five minutes and enforce the retention period."""
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = (now - dt.timedelta(minutes=5)).isoformat()
    with database(host) as db:
        db.execute("DELETE FROM applications WHERE created_at<?", ((now - dt.timedelta(days=365)).isoformat(),))
        db.execute("DELETE FROM rate_limits WHERE expires<?", (int(now.timestamp()),))
        rows = db.execute("""SELECT id FROM applications WHERE
          (staff_mail!='sent' AND staff_tries<5 AND (staff_attempt IS NULL OR staff_attempt<?)) OR
          (candidate_mail!='sent' AND candidate_tries<5 AND (candidate_attempt IS NULL OR candidate_attempt<?))
          ORDER BY created_at LIMIT 5""", (cutoff, cutoff)).fetchall()
    for row in rows:
        deliver(host, row["id"], automatic=True)


def start_worker(host):
    """One bounded worker, started after Gunicorn forks; no test/import side effects."""
    if "parcours_alternance_worker" in host.app.extensions:
        return
    stop = threading.Event()
    def run():
        while not stop.is_set():
            try:
                with host.app.app_context():
                    maintain(host)
            except Exception:
                host.app.logger.warning("alternance_maintenance_failed")
            stop.wait(60)
    thread = threading.Thread(target=run, name="parcours-alternance-mail", daemon=True)
    host.app.extensions["parcours_alternance_worker"] = {"thread": thread, "stop": stop}
    thread.start()
