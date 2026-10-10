"""Partner e-learning orders, using the existing tenant store and merchant queue.

An entitlement is never inferred from a browser return URL or a posted price.
Only a fully paid, verified invoice (or an administrator's free price snapshot)
can activate it. Learner records stay outside administrative trainee sessions.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from flask import abort, flash, redirect, request, session, url_for

import manuals_commerce as commerce

COURSES = {
    "aps": {"name": "APS", "title": "Agent de prévention et de sécurité", "color": "#2468b3", "default_cents": 5900, "folder": "aps62"},
    "vtc": {"name": "VTC", "title": "Chauffeur VTC", "color": "#7951a8", "default_cents": None, "folder": "vtc"},
}
CUSTOMER_ENDPOINTS = {"manuals_shop.elearning_checkout", "manuals_shop.elearning_order", "manuals_shop.elearning_confirm", "manuals_shop.elearning_refresh", "manuals_shop.elearning_status", "manuals_shop.elearning_invoice"}
MAX_LEARNERS = 100


def is_order(order):
    return order.get("order_type") == "elearning"


def is_record(order):
    """Both immutable purchases and editable rosters belong outside the manual shop."""
    return order.get("order_type") in {"elearning", "elearning_group"}


def prices(partner):
    saved = partner.get("elearning_pricing") or {}
    result = {}
    for code, course in COURSES.items():
        cfg = saved.get(code) or {}
        free = cfg.get("free") is True
        cents = cfg.get("unit_cents", course["default_cents"])
        if cents is not None and (type(cents) is not int or not 1 <= cents <= 10000000):
            cents = None
        minutes = sum(module["required_minutes"] for module in curriculum(code))
        hours, remaining = divmod(minutes, 60)
        duration_label = f"{hours} h" + (f" {remaining:02d} min" if remaining else "")
        result[code] = {**course, "code": code, "free": free, "unit_cents": 0 if free else cents,
                        "configured": free or cents is not None, "planned_minutes": minutes,
                        "hours": minutes / 60, "duration_label": duration_label}
    return result


def parse_prices(form):
    result = {}
    for code in COURSES:
        raw = str(form.get(code + "_price", "")).strip().replace(",", ".")
        cents = None
        if raw:
            try:
                amount = Decimal(raw)
                if not amount.is_finite() or amount <= 0 or amount > 100000 or amount * 100 != (amount * 100).to_integral_value():
                    raise ValueError
                cents = int(amount * 100)
            except (InvalidOperation, ValueError):
                raise ValueError("Indiquez un prix positif avec deux décimales maximum, ou cochez Gratuit.")
        result[code] = {"unit_cents": cents, "free": form.get(code + "_free") == "yes"}
    return result


def parse_learners(form):
    columns = [form.getlist(k) for k in ("last_name", "first_name", "email")]
    if len({len(c) for c in columns}) != 1 or not 1 <= len(columns[0]) <= MAX_LEARNERS:
        raise ValueError("Ajoutez entre 1 et 100 personnes avec nom, prénom et e-mail.")
    result, seen = [], set()
    for index, (last, first, email) in enumerate(zip(*columns), 1):
        last, first, email = last.strip(), first.strip(), email.strip().casefold()
        if not last or not first or max(len(last), len(first)) > 100 or any(ord(c) < 32 for c in last + first):
            raise ValueError(f"Personne {index} : renseignez un nom et un prénom valides.")
        if len(email) > 254 or not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", email):
            raise ValueError(f"Personne {index} : vérifiez l’adresse e-mail.")
        if email in seen:
            raise ValueError(f"Personne {index} : cette adresse e-mail figure déjà dans le groupe.")
        seen.add(email)
        result.append({"id": str(uuid.uuid4()), "last_name": last, "first_name": first, "email": email})
    return result


def curriculum(code):
    manifest = json.loads((Path(__file__).parent / "elearning_native" / COURSES[code]["folder"] / "manifest.json").read_text(encoding="utf-8"))
    return [{"course_id": m["id"], "course_version": m["version"], "title": m["title"], "required_minutes": m["planned_minutes"] if "planned_minutes" in m else int(Decimal(str(m["hours"])) * 60)} for m in manifest["modules"]]


def entitled(order):
    state = order.get("commerce") or {}
    if not is_order(order) or order.get("status") in {"draft", "cancelled"} or order.get("cancellation_requested_at"):
        return False
    if order.get("free_snapshot") is True and order.get("total_cents") == 0:
        return True
    return bool(order.get("total_cents", 0) > 0 and state.get("invoice_id") and state.get("invoice_status") == "paid"
                and state.get("payment_status") == "paid" and state.get("paid_cents", 0) >= order["total_cents"]
                and state.get("remaining_cents") == 0)


def status_view(order):
    state = order.get("commerce", {})
    return {"status": state.get("status"), "payment_status": state.get("payment_status"), "invoice_status": state.get("invoice_status"),
            "payment_url": bool(state.get("payment_url")), "payment_link_status": state.get("payment_link_status"),
            "active": bool(order.get("activated_at")), "mail_sent": sum(m.get("status") == "sent" for k, m in state.get("emails", {}).items() if k.startswith("learner_"))}



def centre_snapshot(partner):
    return {key: partner.get(key, "") for key in ("name", "siret", "email", "contact_first_name", "contact_last_name", "phone", "contact_email")}


def learner_brand(data, order, host=None):
    """Learner messages use this centre only, never platform contact defaults."""
    snapshot = order.get("centre") or {}
    partner = next((record for record in data.get("partners", []) if record.get("id") == order.get("partner_id")), {})
    def clean(value, limit):
        return " ".join(str(value or "").split())[:limit]
    name = clean(partner.get("name") or snapshot.get("name"), 160) or "Votre organisme de formation"
    email = ""
    # The editable organisation profile address takes precedence over legacy contacts.
    for candidate in (partner.get("email"), partner.get("contact_email"), snapshot.get("contact_email"), snapshot.get("email")):
        candidate = str(candidate or "").strip()
        if len(candidate) <= 254 and not any(ord(char) < 32 or char in "?#&" for char in candidate) and re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", candidate):
            email = candidate
            break
    phone = clean(partner.get("phone") if "phone" in partner else snapshot.get("phone"), 50)
    brand = {"name": name, "email": email, "phone": phone}
    if host is not None:
        from organisme_profile import logo_url
        brand["logo_url"] = logo_url(host, partner, _external=True) if partner else ""
    return brand

def learner_context(data, token, host=None):
    if not re.fullmatch(r"el_[A-Za-z0-9_-]{40,100}", str(token or "")):
        return None, None
    digest = hashlib.sha256(token.encode()).hexdigest()
    active_partners = {p["id"] for p in data.get("partners", []) if p.get("status") in {"active", "trial"}}
    for order in data.get("manual_orders", []):
        if not entitled(order) or order.get("partner_id") not in active_partners:
            continue
        for person in order.get("learners", []):
            if not person.get("activated_at") or not hmac.compare_digest(person.get("token_hash", ""), digest):
                continue
            virtual_session = {"id": "el-" + order["id"], "partner_id": order["partner_id"], "name": order.get("group_name") or "Parcours " + order["course_code"].upper(),
                               "training_type": order["course_code"].upper(), "date_start": person["activated_at"][:10], "aps_elearning_enabled": True,
                               "aps_native_modules": copy.deepcopy(order["modules"]), "aps_native_path_title": "Mon parcours " + order["course_code"].upper(),
                               "learner_brand": learner_brand(data, order, host=host)}
            return virtual_session, {**person, "public_token": token, "partner_id": order["partner_id"]}
    return None, None


def access_token(host, order, person):
    # Stable, unguessable per enrolment; only its hash is stored in the order.
    message = "elearning-order-v1:" + order["id"] + ":" + person["id"]
    return "el_" + hmac.new(str(host.app.secret_key).encode(), message.encode(), hashlib.sha256).hexdigest()


def activate(host, order):
    if not entitled(order):
        return False
    def update(current):
        if current.get("commerce", {}).get("lease_token") != order["commerce"]["lease_token"] or not entitled(current):
            raise commerce.ReviewRequired("La commande ne permet pas l’activation des accès.")
        now = host._now_iso()
        for person in current["learners"]:
            if not person.get("activated_at"):
                token = access_token(host, current, person)
                person.update(activated_at=now, token_hash=hashlib.sha256(token.encode()).hexdigest())
        current.setdefault("activated_at", now)
        return {"learners": copy.deepcopy(current["learners"]), "activated_at": current["activated_at"]}
    result = commerce._mutate(host, order["partner_id"], order["id"], update)
    order.update(result)
    return True


def send_message(host, order, key, recipient, *, person=None, invoice=False):
    import base64
    from manuals_shop import base_url, money
    state = order["commerce"]
    emails = copy.deepcopy(state.get("emails") or {})
    if emails.get(key, {}).get("status") == "sent":
        return True
    if person and (not entitled(order) or not person.get("activated_at")):
        return False
    emails[key] = {"status": "sending", "attempted_at": host._now_iso()}
    commerce._save(host, order, emails=emails)
    paid = entitled(order)
    title = "Votre formation vous attend" if person else ("Vos accès sont activés" if paid else "Votre commande e-learning")
    link = base_url(host) + ("/apprendre/" + access_token(host, order, person) if person else "/admin/organisme/e-learning/commandes/" + order["id"])
    brand = learner_brand(host.load_data(run_background_tasks=False), order, host=host) if person else None
    subject = ("Votre accès personnel " if person else "Commande e-learning ") + order["course_code"].upper() + " · " + (brand["name"] if person else "Intégrale Academy")
    if invoice:
        subject = ("Facture acquittée " if paid else "Facture à régler ") + state.get("invoice_number", "") + " · E-learning"
    body = host.app.jinja_env.get_template("manuals/elearning_email.html").render(order=order, person=person, title=title, link=link, paid=paid, invoice=invoice, money=money, learner_brand=brand)
    plain = (f"Bonjour {person['first_name']},\nVotre accès personnel au parcours {order['course_code'].upper()} est activé.\n" if person else f"Commande {order['reference']} : {len(order['learners'])} accès {order['course_code'].upper()}.\nTotal : {money(order['total_cents'])} TTC.\n" + ("Accès activés.\n" if paid else "Les accès seront activés uniquement après règlement intégral de la facture.\n"))
    plain += "Ouvrir mon espace : " + link
    send_options = {}
    if person:
        plain += "\n\n" + brand["name"]
        if brand["email"]:
            plain += "\nContact : " + brand["email"]
            send_options["reply_to"] = {"email": brand["email"], "name": brand["name"]}
        if brand["phone"]:
            plain += "\nTéléphone : " + brand["phone"]
        send_options["sender_name"] = brand["name"]
        # Only a verified platform-configured sending address may override From.
        send_options["sender_email"] = str(getattr(host, "ELEARNING_SENDER_EMAIL", "") or "").strip() or None
    else:
        plain += "\nIntégrale Academy — 04 22 47 07 68"
    try:
        attachments = []
        if invoice:
            pdf, name = host.fetch_qonto_client_invoice_pdf(state["invoice_id"])
            import os
            root = Path(host.get_partner_storage_path(order["partner_id"], "factures"))
            destination = root / ("elearning-" + order["id"] + ("-paid" if state.get("invoice_status") == "paid" else "-due") + ".pdf")
            temporary = root / ("." + uuid.uuid4().hex + ".tmp")
            try:
                temporary.write_bytes(pdf)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            attachments = [{"name": name, "content": base64.b64encode(pdf).decode("ascii")}]
        result = host.brevo_send_email(recipient, subject, body, text_content=plain, attachments=attachments,
                                     metadata={"partner_id": order["partner_id"], "order_id": order["id"], "purpose": "elearning_" + key}, **send_options)
    except Exception as exc:
        host.app.logger.warning("elearning_email_failed order=%s type=%s", order["id"], type(exc).__name__)
        result = {"ok": False}
    emails[key] = {"status": "sent" if result.get("ok") else "failed", "attempted_at": host._now_iso(), "message_id": result.get("message_id", "")}
    commerce._save(host, order, emails=emails)
    return bool(result.get("ok"))


def process_claimed(host, order):
    """Called by the merchant worker under its durable, ten-minute order lease."""
    if order.get("cancellation_requested_at"):
        from elearning_groups import process_cancellation
        return process_cancellation(host, order)
    outcome, error = "ready", ""
    try:
        if not order.get("free_snapshot"):
            invoice = commerce._ensure_invoice(host, order, commerce.settings_from(host.load_data(run_background_tasks=False)))
            if not entitled(order):
                commerce._ensure_payment_link(host, order, invoice)
                outcome = "waiting_payment"
        if entitled(order):
            activate(host, order)
    except commerce.PaymentPending as exc:
        outcome, error = "payment_pending", str(exc)
    except (commerce.SetupRequired, host.QontoConfigurationError) as exc:
        outcome, error = "needs_setup", str(exc)
    except commerce.ReviewRequired as exc:
        outcome, error = "needs_review", str(exc)
    except Exception as exc:
        outcome, error = "retry", host.format_qonto_error_for_front(exc)[:500]
        host.app.logger.warning("elearning_order_error order=%s type=%s", order["id"], type(exc).__name__)
    commerce._save(host, order, status=outcome, error=error)
    sent = send_message(host, order, "confirmation", order["centre"]["email"])
    state = order["commerce"]
    if state.get("invoice_id") and state.get("invoice_status") in {"unpaid", "paid"}:
        invoice_key = "invoice_paid" if entitled(order) else "invoice_due"
        sent = send_message(host, order, invoice_key, order["centre"]["email"], invoice=True) and sent
    if entitled(order) and order.get("activated_at"):
        for person in order["learners"]:
            sent = send_message(host, order, "learner_" + person["id"], person["email"], person=person) and sent
    state = order["commerce"]
    tracking = bool(state.get("invoice_id") and not entitled(order) and state.get("invoice_status") != "canceled")
    # Keep email retries durable even after a transient mail outage. Sent keys are never replayed.
    queued = tracking or not sent or outcome == "retry"
    delay = (60 if outcome in {"ready", "waiting_payment"} else 300) if tracking else min(60 * 2 ** min(state.get("attempts", 1), 6), 3600)
    commerce._save(host, order, status=outcome, error=error or ("Un e-mail sera renvoyé automatiquement." if not sent else ""),
                   queued=queued, next_attempt=time.time() + delay, attempts=0 if sent and tracking else state.get("attempts", 0), lease_until=0)


def register_routes(host, bp, *, page, customer, partner_data, check_csrf, kick_worker):
    def find(data, oid):
        order = next((o for o in data.get("manual_orders", []) if o.get("id") == oid and is_order(o)), None)
        if not order or (not host._is_super_admin_session() and order["partner_id"] != host._current_partner_id()):
            abort(404)
        return order

    def render_order(oid, staff=False):
        data = host.load_data()
        order = find(data, oid)
        return page("elearning_order.html", order=order, partner=order["centre"], staff=staff, unlocked=entitled(order), order_status=status_view(order))

    @bp.post("/admin/organisme/e-learning/recapitulatif")
    @customer
    def elearning_checkout():
        check_csrf()
        data, partner = partner_data()
        code = request.form.get("course_code")
        values = request.form.to_dict()
        rows = [{"last_name": l, "first_name": f, "email": e} for l, f, e in zip(request.form.getlist("last_name"), request.form.getlist("first_name"), request.form.getlist("email"))]
        try:
            if code not in COURSES:
                raise ValueError("Choisissez le parcours APS ou VTC.")
            price = prices(partner)[code]
            if not price["configured"]:
                raise ValueError("Contactez-nous pour définir votre tarif pour ce parcours.")
            people = parse_learners(request.form)
            group_name = request.form.get("group_name", "").strip()
            if len(group_name) > 150:
                raise ValueError("Le nom du groupe est limité à 150 caractères.")
            billing = {k: request.form.get(k, "").strip() for k in ("address", "postal_code", "city")}
            if not price["free"] and any(not 1 <= len(billing[k]) <= limit for k, limit in (("address", 200), ("postal_code", 20), ("city", 100))):
                raise ValueError("Complétez l’adresse de facturation de votre organisme.")
            billing.update(country="France", country_code="FR")
            token = request.form.get("request_id", "")
            if not re.fullmatch(r"[a-f0-9]{32}", token):
                raise ValueError("Rechargez le formulaire avant de commander.")
            modules = curriculum(code)
            quantity, unit = len(people), price["unit_cents"]
            oid = str(uuid.uuid4())
            order = {"id": oid, "order_type": "elearning", "partner_id": partner["id"], "created_by": session.get("user_id"), "status": "draft", "created_at": host._now_iso(),
                     "request_id": token, "course_code": code, "group_name": group_name, "learners": people, "modules": modules, "billing": billing,
                     "free_snapshot": price["free"], "unit_cents": unit, "total_cents": unit * quantity, "shipping_cents": 0,
                     "items": [{"kind": "elearning", "code": code, "label": "Accès e-learning " + code.upper(), "quantity": quantity, "unit_cents": unit, "total_cents": unit * quantity}],
                     "centre": centre_snapshot(partner)}
            def persist(current):
                existing = next((o for o in current.get("manual_orders", []) if o.get("partner_id") == partner["id"] and o.get("request_id") == token), None)
                if existing:
                    return {"id": existing["id"]}
                if sum(o.get("status") == "draft" and is_order(o) and o.get("partner_id") == partner["id"] for o in current.get("manual_orders", [])) >= 30:
                    abort(429, "Trop de brouillons. Reprenez une commande existante.")
                current.setdefault("manual_orders", []).append(order)
                return {"id": oid}
            result = host._atomic_update_data(persist, partner_id=partner["id"])
        except ValueError as exc:
            from elearning_groups import dashboard
            return page("elearning_catalogue.html", partner=partner, courses=prices(partner), groups=dashboard(data, partner), orders=[], values=values, rows=rows, request_id=request.form.get("request_id") or secrets.token_hex(16), errors=[str(exc)]), 400
        return redirect(url_for("manuals_shop.elearning_order", oid=result["id"]), code=303)

    @bp.get("/admin/organisme/e-learning/commandes/<oid>")
    @host.admin_login_required
    def elearning_order(oid):
        if not (host._is_super_admin_session() or host._is_external_partner_session()):
            abort(403)
        if not host._is_super_admin_session():
            partner_data()
        return render_order(oid, staff=host._is_super_admin_session())

    @bp.post("/admin/organisme/e-learning/commandes/<oid>/confirmer")
    @customer
    def elearning_confirm(oid):
        check_csrf()
        if request.form.get("confirm") != "yes":
            abort(400)
        _, partner = partner_data()
        def confirm(data):
            order = find(data, oid)
            if order["status"] != "draft":
                return {}
            current = host._partner_or_404(data, partner["id"])
            price = prices(current)[order["course_code"]]
            if (price["unit_cents"], price["free"]) != (order["unit_cents"], order["free_snapshot"]):
                abort(409, "Votre tarif a changé. Préparez une nouvelle commande pour consulter le nouveau total.")
            order.update(status="received", reference="EL-" + str(dt.date.today().year) + "-" + oid[:8].upper(), submitted_at=host._now_iso(),
                         commerce={"queued": True, "status": "pending", "flow": "elearning_invoice_first", "attempts": 0, "emails": {}})
            return {}
        host._atomic_update_data(confirm, partner_id=partner["id"])
        kick_worker()
        return redirect(url_for("manuals_shop.elearning_order", oid=oid), code=303)

    @bp.get("/admin/organisme/e-learning/commandes/<oid>/statut")
    @customer
    def elearning_status(oid):
        order = find(host.load_data(), oid)
        # No learner identities or access tokens in this polling response.
        return status_view(order)

    @bp.post("/admin/organisme/e-learning/commandes/<oid>/actualiser")
    @host.admin_login_required
    def elearning_refresh(oid):
        check_csrf()
        if session.get("admin_role") == "viewer" or not (host._is_super_admin_session() or host._is_external_partner_session()):
            abort(403)
        order = find(host.load_data(), oid)
        commerce.queue_again(host, order["partner_id"], oid, throttle=not host._is_super_admin_session())
        kick_worker()
        flash("La vérification du paiement et des e-mails est relancée.", "success")
        return redirect(url_for("manuals_shop.elearning_order", oid=oid), code=303)

    @bp.get("/admin/organisme/e-learning/commandes/<oid>/facture")
    @host.admin_login_required
    def elearning_invoice(oid):
        from flask import send_file
        import io
        order = find(host.load_data(), oid)
        state = order.get("commerce", {})
        if not state.get("invoice_id") or state.get("invoice_status") == "canceled":
            abort(404)
        # Invoice files are downloaded in the merchant worker, never with a tenant's credentials.
        path = Path(host.get_partner_storage_path(order["partner_id"], "factures")) / ("elearning-" + oid + ("-paid" if state.get("invoice_status") == "paid" else "-due") + ".pdf")
        if not path.is_file():
            abort(409, "La facture est en préparation. Réessayez dans quelques instants.")
        return send_file(io.BytesIO(path.read_bytes()), mimetype="application/pdf", as_attachment=True, download_name="Facture-" + order["reference"] + ".pdf")

    @bp.route("/admin/commandes-elearning", methods=["GET", "POST"])
    @host.admin_login_required
    @host.require_super_admin
    def elearning_admin():
        if host._is_partner_data_scope_session():
            abort(403, "Quittez l’assistance d’un organisme avant de modifier les tarifs.")
        data = host.load_data()
        pid = request.values.get("partner_id", "")
        selected = host._partner_or_404(data, pid) if pid else None
        errors = []
        if request.method == "POST":
            check_csrf()
            if not selected:
                abort(400)
            try:
                pricing = parse_prices(request.form)
                def save(current):
                    partner = host._partner_or_404(current, pid)
                    partner["elearning_pricing"] = pricing
                    partner["updated_at"] = host._now_iso()
                    host._append_activity_log(current, "elearning_prices_updated", "partner", pid, pid, pricing)
                    return {}
                host._atomic_update_data(save, partner_id=pid)
                flash("Les tarifs e-learning de ce partenaire sont enregistrés. Les commandes confirmées conservent leur tarif.", "success")
                return redirect(url_for("manuals_shop.elearning_admin", partner_id=pid), code=303)
            except ValueError as exc:
                errors = [str(exc)]
        orders = sorted((o for o in data.get("manual_orders", []) if is_order(o) and o.get("status") != "draft" and (not pid or o["partner_id"] == pid)), key=lambda o: o.get("submitted_at", ""), reverse=True)
        configuration = commerce.configuration_status(host, data, {"items": [{"kind": "elearning"}]})
        return page("elearning_admin.html", staff=True, partners=data.get("partners", []), selected=selected, courses=prices(selected or {}), orders=orders, errors=errors, configuration=configuration), (400 if errors else 200)

    @bp.route("/apprendre/<token>", methods=["GET", "POST"])
    def elearning_access(token):
        data = host.load_data(run_background_tasks=False)
        training, person = learner_context(data, token, host=host)
        if not person:
            abort(404, "Cet accès n’est pas disponible. Contactez votre organisme de formation.")
        if request.method == "POST":
            check_csrf()
            session.clear()
            session["public_auth_" + token] = True
            session.permanent = True
            return redirect(url_for("native_elearning.learner_path", token=token), code=303)
        return page("elearning_access.html", person=person, training=training, learner_brand=training["learner_brand"])

