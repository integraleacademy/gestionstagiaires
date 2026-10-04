"""Self-service training centres and an isolated, persistent manuals shop.

Accounts reuse the partner store (JSON or PostgreSQL). A persisted account_type
enforces a positive route allowlist; hiding menu links is not an access control.
Orders are quoted exclusively on the server, then confirmed with a one-use draft
identifier. Network delivery only happens after durable account/order creation.
"""
from __future__ import annotations

import datetime as dt
import hmac
import io
import os
import re
import secrets
import uuid
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, session, url_for
from PIL import Image, UnidentifiedImageError


CATALOGUE = (
    {"code": "ssiap1", "name": "SSIAP 1", "title": "Sécurité incendie et assistance à personnes", "description": "Des schémas et des situations illustrées pour rendre la sécurité incendie concrète.", "color": "#c64042", "price": 1700, "bulk_price": 1700},
    {"code": "aps", "name": "APS", "title": "Agent de prévention et de sécurité", "description": "Des situations professionnelles pour relier les cours aux missions quotidiennes de l’agent.", "color": "#2468b3", "price": 2000, "bulk_price": 1800},
    {"code": "a3p", "name": "A3P", "title": "Protection physique des personnes", "description": "Des missions illustrées et des schémas pour travailler les méthodes de protection.", "color": "#28795f", "price": 2200, "bulk_price": 2000},
    {"code": "vtc", "name": "VTC", "title": "Voiture de transport avec chauffeur", "description": "Un support structuré pour organiser les révisions et travailler les situations professionnelles.", "color": "#7951a8", "price": 2200, "bulk_price": 2000},
    {"code": "dssp", "name": "DSSP", "title": "Dirigeant d’une société de sécurité privée", "description": "Des méthodes, calculs expliqués et fiches pour aborder la gestion d’une société de sécurité.", "color": "#d77824", "price": 2200, "bulk_price": 2000},
    {"code": "sst", "name": "SST", "title": "Sauveteur secouriste du travail", "description": "Des situations illustrées pour comprendre la prévention et accompagner l’apprentissage des premiers secours.", "color": "#558538", "price": 1200, "bulk_price": 1000},
)
STATUSES = {"received": "Reçue", "confirmed": "Confirmée", "production": "En préparation", "shipped": "Expédiée", "cancelled": "Annulée"}
PUBLIC_ENDPOINTS = {"manuals_shop.register_account", "manuals_shop.registration_complete", "manuals_shop.resend_welcome"}
CUSTOMER_ENDPOINTS = {"manuals_shop.catalogue", "manuals_shop.checkout", "manuals_shop.confirm_order", "manuals_shop.order_detail", "manuals_shop.order_logo"}
SAFE_ENDPOINTS = {"static", "admin_login", "admin_login_post", "admin_logout"} | PUBLIC_ENDPOINTS | CUSTOMER_ENDPOINTS
MAX_LOGO_BYTES = 5 * 1024 * 1024


def money(cents):
    return f"{int(cents) / 100:,.2f}".replace(",", "\u202f").replace(".", ",") + " €"


def csrf_token():
    if not session.get("manuals_csrf"):
        session["manuals_csrf"] = secrets.token_urlsafe(32)
    return session["manuals_csrf"]


def check_csrf():
    expected = session.get("manuals_csrf", "")
    supplied = request.form.get("csrf_token", "")
    if not expected or not supplied or not hmac.compare_digest(str(expected), str(supplied)):
        abort(400, "Le formulaire a expiré. Rechargez la page avant de réessayer.")


def guard_request(host):
    """Protect *every* namespace, including future API routes and CRM routes."""
    if request.endpoint == "static" or not host._is_external_partner_session():
        return None
    auth = host._load_partner_auth_data()
    partner = next((p for p in auth.get("partners", []) if p.get("id") == session.get("partner_id")), None)
    restricted = session.get("manuals_only") or (partner or {}).get("account_type") == "manuals_only"
    if not restricted:
        return None
    user = next((u for u in auth.get("users", []) if u.get("id") == session.get("user_id") and u.get("partner_id") == session.get("partner_id")), None)
    if not partner or not user or not user.get("active", True) or partner.get("status") not in {"active", "trial"}:
        session.clear()
        if host._request_expects_json():
            return {"ok": False, "error": "session_expired"}, 401
        return redirect(url_for("admin_login", error="inactive"))
    g.manuals_partner = partner
    session["manuals_only"] = True
    if request.endpoint in SAFE_ENDPOINTS:
        return None
    if request.method in {"GET", "HEAD"} and not host._request_expects_json():
        return redirect(url_for("manuals_shop.catalogue"))
    return {"ok": False, "error": "manuals_only", "message": "Votre espace est réservé aux commandes de manuels."}, 403


def quote_items(form):
    """Money is integer cents. Browser totals, names and partner IDs are ignored."""
    lines = []
    for book in CATALOGUE:
        for kind in ("manual", "usb"):
            raw = str(form.get(f"{kind}_{book['code']}") or "0").strip()
            if not re.fullmatch(r"[0-9]{1,5}", raw):
                raise ValueError(f"Quantité invalide pour {book['name']}.")
            qty = int(raw)
            if qty == 0:
                continue
            if (kind == "manual" and not 50 <= qty <= 10000) or (kind == "usb" and not 1 <= qty <= 100):
                raise ValueError(f"{book['name']} : choisissez de 50 à 10 000 manuels, ou de 1 à 100 clés USB.")
            price = (book["bulk_price"] if qty >= 100 else book["price"]) if kind == "manual" else (9900 if book["code"] == "sst" else 19900)
            lines.append({"code": book["code"], "kind": kind, "label": ("Manuel " if kind == "manual" else "PowerPoint sur clé USB — ") + book["name"], "quantity": qty, "unit_cents": price, "total_cents": qty * price})
    if not lines:
        raise ValueError("Choisissez au moins un manuel ou un support PowerPoint.")
    return lines


def valid_siret(value):
    if not re.fullmatch(r"[0-9]{14}", value) or len(set(value)) == 1:
        return False
    # La Poste uses the published alternate check for its establishments.
    if value.startswith("356000000"):
        return sum(map(int, value)) % 5 == 0
    return sum((int(c) * 2 // 10 + int(c) * 2 % 10) if i % 2 == 0 else int(c) for i, c in enumerate(value)) % 10 == 0


def base_url(host):
    # Render's service URL keeps test-v2 welcome links on test-v2 even when the
    # legacy student-portal configuration deliberately points at production.
    for value in (os.getenv("MANUALS_BASE_URL"), os.getenv("RENDER_EXTERNAL_URL"), host._public_base_url()):
        parsed = urlparse(value or "")
        if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
            return f"https://{parsed.netloc}"
    raise ValueError("Adresse publique de l’espace non configurée")


def save_logo(host, upload, partner_id, draft_id):
    if not upload or not upload.filename:
        return ""
    raw = upload.stream.read(MAX_LOGO_BYTES + 1)
    if len(raw) > MAX_LOGO_BYTES:
        raise ValueError("Le logo doit peser moins de 5 Mo.")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in {"PNG", "JPEG", "WEBP"} or im.width * im.height > 16000000:
                raise ValueError("Choisissez un logo PNG, JPEG ou WebP de 16 mégapixels maximum.")
            im.load()
            im = im.convert("RGBA")
            root = Path(host.get_partner_storage_path(partner_id, "logos"))
            name = f"manuals-{draft_id}.png"
            im.save(root / name, format="PNG")
            return name
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Ce fichier n’est pas une image valide. Choisissez un logo PNG, JPEG ou WebP.") from exc


def register(host):
    app = host.app
    bp = Blueprint("manuals_shop", __name__)
    app.add_template_filter(money, "manuals_money")

    @bp.after_request
    def private_pages(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def page(template, **context):
        return render_template("manuals/" + template, csrf_token=csrf_token(), statuses=STATUSES, **context)

    def customer(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("admin_logged_in"):
                return redirect(url_for("admin_login", next=url_for("manuals_shop.catalogue")))
            if not host._is_external_partner_session():
                if host._is_super_admin_session():
                    return redirect(url_for("manuals_shop.admin_orders"))
                abort(403)
            if session.get("admin_role") == "viewer" and request.method == "POST":
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    def partner_data():
        data = host.load_data()
        partner = host._current_partner(data)
        if not partner or partner.get("status") not in {"active", "trial"}:
            abort(403)
        return data, partner

    def send_welcome(partner_id, user_id):
        now = host._now_iso()
        def claim(data):
            partner = host._partner_or_404(data, partner_id)
            user = next((u for u in data.get("users", []) if u.get("id") == user_id and u.get("partner_id") == partner_id), None)
            if not user:
                abort(404)
            delivery = partner.get("welcome_email", {})
            if delivery.get("status") == "sent":
                return {"sent": True}
            if delivery.get("last_attempt_at") and (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(delivery["last_attempt_at"].replace("Z", "+00:00"))).total_seconds() < 60:
                return {"sent": False}
            partner["welcome_email"] = {"status": "sending", "last_attempt_at": now}
            return {"partner": dict(partner), "user": dict(user)}
        claimed = host._atomic_update_data(claim, partner_id=partner_id)
        if "partner" not in claimed:
            return claimed.get("sent", False)
        partner, user = claimed["partner"], claimed["user"]
        try:
            login_url = base_url(host) + url_for("admin_login", next=url_for("manuals_shop.catalogue"))
            body = render_template("manuals/welcome_email.html", partner=partner, user=user, login_url=login_url)
            result = host.brevo_send_email(user["email"], "Votre espace organisme de formation est créé", body,
                text_content=f"Bonjour {user['first_name']},\nVotre espace organisme de formation {partner['name']} a bien été créé.\nConnectez-vous avec votre adresse e-mail et le mot de passe choisi : {login_url}\nRetrouvez vos manuels personnalisés et vos commandes.\nIntégrale Academy — 04 22 47 07 68",
                metadata={"partner_id": partner_id, "user_id": user_id, "purpose": "manuals_welcome"})
        except Exception:
            app.logger.exception("manuals_welcome_failed partner_id=%s", partner_id)
            result = {"ok": False}
        def record(data):
            p = host._partner_or_404(data, partner_id)
            p["welcome_email"] = {"status": "sent" if result.get("ok") else "failed", "last_attempt_at": now, "message_id": result.get("message_id", "")}
            return {}
        host._atomic_update_data(record, partner_id=partner_id)
        return bool(result.get("ok"))

    @bp.route("/creer-mon-espace", methods=["GET", "POST"])
    def register_account():
        if session.get("admin_logged_in"):
            return redirect(url_for("manuals_shop.catalogue"))
        values = {k: (request.form.get(k) or "").strip() for k in ("centre", "siret", "first_name", "last_name", "email")}
        errors = []
        status = 200
        if request.method == "POST":
            check_csrf()
            if host._partner_login_is_rate_limited("registration:" + values["email"].lower()):
                return page("register.html", values=values, errors=["Trop de tentatives. Patientez quelques minutes avant de réessayer."]), 429
            values["email"] = values["email"].lower()
            values["siret"] = re.sub(r"\s", "", values["siret"])
            password = request.form.get("password", "")
            if not 2 <= len(values["centre"]) <= 160:
                errors.append("Indiquez le nom du centre (2 à 160 caractères).")
            if not valid_siret(values["siret"]):
                errors.append("Vérifiez votre SIRET : il doit comporter 14 chiffres valides.")
            if any(not 1 <= len(values[k]) <= 100 for k in ("first_name", "last_name")):
                errors.append("Indiquez votre nom et votre prénom (100 caractères maximum chacun).")
            if len(values["email"]) > 254 or not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", values["email"]):
                errors.append("Indiquez une adresse e-mail valide.")
            if len(password) < 12 or len(password) > 128:
                errors.append("Choisissez un mot de passe de 12 à 128 caractères.")
            if password != request.form.get("password_confirmation", ""):
                errors.append("Les deux mots de passe doivent être identiques.")
            if request.form.get("website_url"):
                errors.append("Le formulaire n’a pas pu être envoyé.")
            reserved = {str(host.ADMIN_USER or "").lower(), str(host.SECRETARY_USER or "").lower(), str(host.SCOTIA_USER or "").lower()}
            if not errors and (values["email"] in reserved or host._find_user_by_email(host._load_partner_auth_data(), values["email"])):
                errors.append("Cette adresse e-mail est déjà utilisée. Connectez-vous à votre espace ou contactez-nous.")
            if not errors:
                pid, uid, now = str(uuid.uuid4()), str(uuid.uuid4()), host._now_iso()
                partner = {"id": pid, "name": values["centre"], "legal_name": values["centre"], "siret": values["siret"], "email": values["email"], "contact_first_name": values["first_name"], "contact_last_name": values["last_name"], "status": "active", "account_type": "manuals_only", "subscription_plan": "manuels", "enabled_modules": [], "max_users": 1, "created_at": now, "updated_at": now}
                user = {"id": uid, "partner_id": pid, "email": values["email"], "first_name": values["first_name"], "last_name": values["last_name"], "role": "partner_admin", "active": True, "password_hash": host._hash_password(password), "invitation_activated_at": now, "created_at": now, "updated_at": now}
                def create(data):
                    if host._find_user_by_email(data, values["email"]):
                        raise host.PartnerPostgresDuplicateEmail("duplicate_email")
                    data.setdefault("partners", []).append(partner)
                    data.setdefault("users", []).append(user)
                    host._append_activity_log(data, "manuals_account_created", "partner", pid, pid)
                    return {}
                try:
                    host._atomic_update_data(create, partner_id=pid, seed_bundle={"partners": [], "users": [], "invitations": [], "activity_logs": [], "manual_orders": []})
                except host.PartnerPostgresDuplicateEmail:
                    errors.append("Cette adresse e-mail est déjà utilisée. Connectez-vous à votre espace.")
                else:
                    session.clear()
                    session["manuals_registration"] = {"partner_id": pid, "user_id": uid, "name": values["centre"], "email": values["email"]}
                    session["manuals_welcome_sent"] = send_welcome(pid, uid)
                    return redirect(url_for("manuals_shop.registration_complete"), code=303)
            status = 400
        return page("register.html", values=values, errors=errors), status

    @bp.get("/espace-cree")
    def registration_complete():
        if not session.get("manuals_registration"):
            return redirect(url_for("manuals_shop.register_account"))
        return page("registered.html", account=session["manuals_registration"], welcome_sent=session.get("manuals_welcome_sent"))

    @bp.post("/espace-cree/renvoyer-email")
    def resend_welcome():
        check_csrf()
        account = session.get("manuals_registration")
        if not account:
            abort(403)
        session["manuals_welcome_sent"] = send_welcome(account["partner_id"], account["user_id"])
        return redirect(url_for("manuals_shop.registration_complete"), code=303)

    @bp.get("/admin/manuels")
    @customer
    def catalogue():
        data, partner = partner_data()
        orders = sorted((o for o in data.get("manual_orders", []) if o.get("partner_id") == partner["id"] and o.get("status") != "draft"), key=lambda o: o.get("created_at", ""), reverse=True)
        values = {}
        if request.args.get("draft"):
            draft = find_order(data, request.args["draft"])
            if draft["status"] != "draft":
                return redirect(url_for("manuals_shop.order_detail", order_id=draft["id"]))
            values = dict(draft["delivery"])
            values.update({key: draft.get(key, "") for key in ("notes", "session_date", "personalization")})
            values["draft_id"] = draft["id"]
            values["existing_logo"] = bool(draft.get("logo_filename"))
            for line in draft["items"]:
                values[f"{line['kind']}_{line['code']}"] = line["quantity"]
        drafts = sorted((o for o in data.get("manual_orders", []) if o.get("status") == "draft"), key=lambda o: o.get("created_at", ""), reverse=True)
        return page("catalogue.html", partner=partner, books=CATALOGUE, orders=orders, drafts=drafts, values=values, errors=[])

    @bp.post("/admin/manuels/recapitulatif")
    @customer
    def checkout():
        check_csrf()
        data, partner = partner_data()
        values = {k: (request.form.get(k) or "").strip() for k in ("recipient", "phone", "address", "address_extra", "postal_code", "city", "country", "notes", "session_date", "personalization")}
        values.update({f"{kind}_{b['code']}": request.form.get(f"{kind}_{b['code']}", "0") for b in CATALOGUE for kind in ("manual", "usb")})
        previous = None
        if request.form.get("draft_id"):
            previous = find_order(data, request.form["draft_id"])
            if previous["status"] != "draft":
                return redirect(url_for("manuals_shop.order_detail", order_id=previous["id"]), code=303)
            values["draft_id"] = previous["id"]
            values["existing_logo"] = bool(previous.get("logo_filename"))
        draft_id = previous["id"] if previous else str(uuid.uuid4())
        new_logo = ""
        try:
            lines = quote_items(request.form)
            for key, label, maximum in (("recipient", "le destinataire", 160), ("phone", "le téléphone", 30), ("address", "l’adresse de livraison", 200), ("postal_code", "le code postal", 20), ("city", "la ville", 100), ("country", "le pays", 80)):
                if not 1 <= len(values[key]) <= maximum:
                    raise ValueError(f"Renseignez {label} (maximum {maximum} caractères).")
            if len(values["notes"]) > 2000 or len(values["address_extra"]) > 200:
                raise ValueError("Le commentaire ou le complément d’adresse est trop long.")
            if values["session_date"]:
                try:
                    dt.date.fromisoformat(values["session_date"])
                except ValueError:
                    raise ValueError("La date de session n’est pas valide.")
            has_manual = any(line["kind"] == "manual" for line in lines)
            personalization = values["personalization"] if has_manual else "none"
            if has_manual and personalization not in {"upload", "later"}:
                raise ValueError("Choisissez comment nous transmettre votre logo.")
            new_logo = save_logo(host, request.files.get("logo"), partner["id"], str(uuid.uuid4())) if personalization == "upload" else ""
            logo = (new_logo or (previous or {}).get("logo_filename", "")) if personalization == "upload" else ""
            if personalization == "upload" and not logo:
                raise ValueError("Ajoutez votre logo ou choisissez de l’envoyer plus tard.")
        except ValueError as exc:
            orders = [o for o in data.get("manual_orders", []) if o.get("status") != "draft"]
            return page("catalogue.html", partner=partner, books=CATALOGUE, orders=orders, values=values, errors=[str(exc)]), 400
        order = {"id": draft_id, "partner_id": partner["id"], "created_by": session.get("user_id"), "status": "draft", "created_at": host._now_iso(), "items": lines, "total_cents": sum(line["total_cents"] for line in lines), "shipping_cents": 0, "tariff_version": "2026", "centre": {k: partner.get(k, "") for k in ("name", "siret", "email", "contact_first_name", "contact_last_name")}, "delivery": {k: values[k] for k in ("recipient", "phone", "address", "address_extra", "postal_code", "city", "country")}, "notes": values["notes"], "session_date": values["session_date"], "personalization": personalization, "logo_filename": logo}
        def persist(data):
            orders = data.setdefault("manual_orders", [])
            current = next((o for o in orders if o.get("id") == draft_id), None)
            if current:
                if current["status"] != "draft":
                    abort(409, "Cette commande a déjà été confirmée.")
                current.update(order)
            else:
                if sum(1 for o in orders if o.get("status") == "draft") >= 30:
                    abort(429, "Trop de brouillons. Reprenez un récapitulatif déjà ouvert ou contactez-nous.")
                orders.append(order)
            return {}
        try:
            host._atomic_update_data(persist)
        except Exception:
            if new_logo:
                (Path(host.get_partner_storage_path(partner["id"], "logos")) / new_logo).unlink(missing_ok=True)
            raise
        if previous and previous.get("logo_filename") and previous["logo_filename"] != logo:
            old_name = previous["logo_filename"]
            if re.fullmatch(r"manuals-[a-f0-9-]{36}\.png", old_name):
                (Path(host.get_partner_storage_path(partner["id"], "logos")) / old_name).unlink(missing_ok=True)
        return redirect(url_for("manuals_shop.order_detail", order_id=draft_id), code=303)

    def find_order(data, order_id):
        order = next((o for o in data.get("manual_orders", []) if o.get("id") == order_id), None)
        if not order:
            abort(404)
        if not host._is_super_admin_session() and order.get("partner_id") != host._current_partner_id():
            abort(404)
        return order

    @bp.get("/admin/manuels/commandes/<order_id>")
    @customer
    def order_detail(order_id):
        data, partner = partner_data()
        return page("order.html", partner=partner, order=find_order(data, order_id), staff=False)

    @bp.post("/admin/manuels/commandes/<order_id>/confirmer")
    @customer
    def confirm_order(order_id):
        check_csrf()
        if request.form.get("confirm") != "yes":
            abort(400, "Confirmez avoir vérifié les quantités et les coordonnées.")
        def confirm(data):
            order = find_order(data, order_id)
            if order["status"] != "draft":
                return {"created": False, "id": order_id}
            order.update(status="received", reference="MAN-" + dt.datetime.now().strftime("%Y") + "-" + order_id[:8].upper(), submitted_at=host._now_iso())
            host._append_activity_log(data, "manual_order_submitted", "manual_order", order_id, order["partner_id"], {"reference": order["reference"], "total_cents": order["total_cents"]})
            return {"created": True, "id": order_id}
        host._atomic_update_data(confirm)
        return redirect(url_for("manuals_shop.order_detail", order_id=order_id), code=303)

    @bp.get("/admin/manuels/commandes/<order_id>/logo")
    @host.admin_login_required
    def order_logo(order_id):
        order = find_order(host.load_data(), order_id)
        name = order.get("logo_filename", "")
        if not re.fullmatch(r"manuals-[a-f0-9-]{36}\.png", name):
            abort(404)
        path = Path(host.get_partner_storage_path(order["partner_id"], "logos")) / name
        if not path.is_file():
            abort(404)
        response = send_file(path, mimetype="image/png", as_attachment=True, download_name="logo-centre.png")
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @bp.get("/admin/commandes-manuels")
    @host.admin_login_required
    @host.require_super_admin
    def admin_orders():
        orders = sorted((o for o in host.load_data().get("manual_orders", []) if o.get("status") != "draft"), key=lambda o: o.get("submitted_at", ""), reverse=True)
        return page("admin_orders.html", orders=orders, staff=True)

    @bp.route("/admin/commandes-manuels/<partner_id>/<order_id>", methods=["GET", "POST"])
    @host.admin_login_required
    @host.require_super_admin
    def admin_order(partner_id, order_id):
        if request.method == "POST":
            check_csrf()
            status = request.form.get("status")
            if status not in STATUSES:
                abort(400)
            def update(data):
                order = find_order(data, order_id)
                if order["partner_id"] != partner_id or order["status"] == "draft":
                    abort(404)
                order["status"] = status
                order["updated_at"] = host._now_iso()
                host._append_activity_log(data, "manual_order_status_changed", "manual_order", order_id, partner_id, {"status": status})
                return {}
            host._atomic_update_data(update, partner_id=partner_id)
            flash("Le statut de la commande a été mis à jour.", "success")
            return redirect(url_for("manuals_shop.admin_order", partner_id=partner_id, order_id=order_id), code=303)
        order = find_order(host.load_data(), order_id)
        if order["partner_id"] != partner_id or order["status"] == "draft":
            abort(404)
        return page("order.html", order=order, partner=order["centre"], staff=True)

    app.register_blueprint(bp)
