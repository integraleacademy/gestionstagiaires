"""Partner e-learning orders, using the existing tenant store and merchant queue.

An entitlement is never inferred from a browser return URL or a posted price.
Only a verified full invoice payment (or an allowed free price snapshot) and
the centre's explicit dispatch request can activate and send new accesses.
Prices and gratuity are set by the administrator for each partner.
Learner records stay outside administrative trainee sessions.
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
import elearning_sales

COURSES = {
    "aps": {"name": "APS", "title": "Agent de prévention et de sécurité", "color": "#2468b3", "default_cents": 5900, "folder": "aps62"},
    "mac-aps": {"name": "MAC APS", "title": "Maintien et actualisation des compétences APS", "color": "#173c5b", "default_cents": 4900},
    "a3p": {"name": "A3P", "title": "Agent de protection physique des personnes", "color": "#258252", "default_cents": 15000},
    "vtc": {"name": "VTC", "title": "Chauffeur VTC", "color": "#7951a8", "default_cents": 15000, "folder": "vtc"},
}
CUSTOMER_ENDPOINTS = {"manuals_shop.elearning_checkout", "manuals_shop.elearning_order", "manuals_shop.elearning_confirm", "manuals_shop.elearning_refresh", "manuals_shop.elearning_status", "manuals_shop.elearning_invoice", "manuals_shop.elearning_send_accesses", "manuals_shop.elearning_confirmation"}
MAX_LEARNERS = 100


def is_order(order):
    return order.get("order_type") == "elearning"


def is_record(order):
    """Both immutable purchases and editable rosters belong outside the manual shop."""
    return order.get("order_type") in {"elearning", "elearning_group"}


def course_label(code):
    """Keep stored product keys separate from names shown to learners and centres."""
    return COURSES.get(code, {}).get("name", str(code or "").upper())


def course_full_label(code):
    titles = {
        "aps": "Agent de prévention et de sécurité",
        "a3p": "Agent de protection physique des personnes",
        "mac-aps": "Maintien et actualisation des compétences d’agent de prévention et de sécurité",
        "vtc": "Conducteur de voiture de transport avec chauffeur",
    }
    return f"{titles[code]} ({course_label(code)})" if code in titles else course_label(code)


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
        result[code] = {**course, "code": code, "free": free, "unit_cents": 0 if free else cents, "configured_unit_cents": cents,
                        "configured": free or cents is not None, "planned_minutes": minutes,
                        "hours": minutes / 60, "duration_label": duration_label}
    return result


def parse_prices(form):
    result = {}
    for code, course in COURSES.items():
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


def normalize_name(value, *, surname=False):
    value = str(value or "").strip()
    if surname:
        return value.upper()
    return re.sub(r"(^|[\s\-’'])[^\W\d_]", lambda match: match.group().upper(), value.lower())


def parse_learners(form):
    columns = [form.getlist(k) for k in ("last_name", "first_name", "email")]
    if len({len(c) for c in columns}) != 1 or not 1 <= len(columns[0]) <= MAX_LEARNERS:
        raise ValueError("Ajoutez entre 1 et 100 personnes avec nom, prénom et e-mail.")
    result, seen = [], set()
    for index, (last, first, email) in enumerate(zip(*columns), 1):
        last, first, email = normalize_name(last, surname=True), normalize_name(first), email.strip().casefold()
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
    if code == "mac-aps":
        from elearning_native.mac_aps import curriculum_manifest
        manifest = curriculum_manifest()
    elif code == "a3p":
        from elearning_native.a3p import curriculum_manifest
        manifest = curriculum_manifest()
    else:
        manifest = json.loads((Path(__file__).parent / "elearning_native" / COURSES[code]["folder"] / "manifest.json").read_text(encoding="utf-8"))
    return [{"course_id": m["id"], "course_version": m["version"], "title": m["title"], "required_minutes": m["planned_minutes"] if "planned_minutes" in m else int(Decimal(str(m["hours"])) * 60)} for m in manifest["modules"]]


def entitled(order):
    state = order.get("commerce") or {}
    if not is_order(order) or order.get("status") in {"draft", "cancelled"} or order.get("cancellation_requested_at"):
        return False
    if order.get("course_code") == "mac-aps":
        # Keep validating the stored quote, including historical purchases.
        # Partner price changes never change an already confirmed order.
        unit = order.get("unit_cents")
        free = order.get("free_snapshot") is True
        if (type(unit) is not int or not (unit == 0 if free else 0 < unit <= 10000000)
                or (not free and order.get("free_snapshot") is not False)
                or not order.get("learners") or order.get("total_cents") != unit * len(order["learners"])):
            return False
    if order.get("free_snapshot") is True and order.get("total_cents") == 0:
        return True
    proof = state.get("confirmed_invoice_payment") or {}
    verified_capture = bool(proof.get("invoice_id") == state.get("invoice_id")
                            and proof.get("link_id") == state.get("payment_id") and proof.get("link_id")
                            and proof.get("payment_ids") and proof.get("verified_at")
                            and proof.get("amount_cents") == order.get("total_cents") and proof.get("currency") == "EUR")
    return bool(order.get("total_cents", 0) > 0 and state.get("invoice_id")
                and state.get("invoice_status") in {"paid", "unpaid"}
                and (state.get("invoice_status") == "paid" or verified_capture)
                and state.get("payment_status") == "paid" and state.get("paid_cents", 0) >= order["total_cents"]
                and state.get("remaining_cents") == 0)


def status_view(order):
    state = order.get("commerce", {})
    sent = sum(state.get("emails", {}).get("learner_" + p["id"], {}).get("status") == "sent"
               for p in order.get("learners", []))
    complete = bool(order.get("learners")) and sent == len(order["learners"])
    requested = bool(order.get("access_dispatch_requested_at"))
    checkout_url = commerce.safe_payment_url(state.get("payment_url")) if (
        order.get("status") not in {"draft", "cancelled"} and not order.get("cancellation_requested_at")
        and state.get("invoice_status") == "unpaid" and state.get("payment_status") == "unpaid"
        and state.get("payment_link_status") == "open") else ""
    return {"status": state.get("status"), "payment_status": state.get("payment_status"), "invoice_status": state.get("invoice_status"),
            "paid": entitled(order), "checkout_url": checkout_url,
            "payment_url": bool(state.get("payment_url")), "payment_link_status": state.get("payment_link_status"),
            "active": bool(order.get("activated_at")), "mail_sent": sent,
            "dispatch_requested": requested, "dispatch_complete": complete,
            "can_send": entitled(order) and not requested and not complete}


def checkout_response(oid):
    """Progressive enhancement for payment in the current browser tab."""
    location = url_for("manuals_shop.elearning_order", oid=oid)
    if request.accept_mimetypes.best == "application/json":
        return {"order_url": location, "status_url": url_for("manuals_shop.elearning_status", oid=oid),
                "confirmation_url": url_for("manuals_shop.elearning_confirmation", oid=oid)}
    return redirect(location, code=303)



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
            virtual_session = {"id": "el-" + order["id"], "partner_id": order["partner_id"], "name": order.get("group_name") or "Parcours " + course_label(order["course_code"]),
                               "training_type": course_label(order["course_code"]), "date_start": person["activated_at"][:10], "aps_elearning_enabled": True,
                               "aps_native_modules": copy.deepcopy(order["modules"]), "aps_native_path_title": "Mon parcours " + course_label(order["course_code"]),
                               "learner_brand": learner_brand(data, order, host=host)}
            return virtual_session, {**person, "public_token": token, "partner_id": order["partner_id"]}
    return None, None


def access_token(host, order, person):
    # Stable, unguessable per enrolment; only its hash is stored in the order.
    message = "elearning-order-v1:" + order["id"] + ":" + person["id"]
    return "el_" + hmac.new(str(host.app.secret_key).encode(), message.encode(), hashlib.sha256).hexdigest()


def activate(host, order):
    if not entitled(order) or not order.get("access_dispatch_requested_at"):
        return False
    def update(current):
        if (current.get("commerce", {}).get("lease_token") != order["commerce"]["lease_token"]
                or not entitled(current) or not current.get("access_dispatch_requested_at")):
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
    if not entitled(order):
        return False
    if person and (not person.get("activated_at") or not order.get("access_dispatch_requested_at")):
        return False
    emails[key] = {"status": "sending", "attempted_at": host._now_iso()}
    commerce._save(host, order, emails=emails)
    paid = entitled(order)
    title = "Votre formation vous attend" if person else "Votre commande est confirmée"
    link = base_url(host) + ("/apprendre/" + access_token(host, order, person) if person else "/admin/organisme/e-learning/commandes/" + order["id"])
    brand = learner_brand(host.load_data(run_background_tasks=False), order, host=host) if person else None
    subject = ("Votre accès personnel " if person else "Commande confirmée · E-learning ") + (course_full_label(order["course_code"]) if person else course_label(order["course_code"])) + " · " + (brand["name"] if person else "Intégrale Connect")
    body = host.app.jinja_env.get_template("manuals/elearning_email.html").render(order=order, person=person, title=title, link=link, paid=paid, invoice=invoice, money=money, learner_brand=brand, email_base_url=base_url(host))
    dispatch_note = ("Votre demande d’envoi des accès est enregistrée.\n" if order.get("access_dispatch_requested_at")
                     else "Cliquez sur « Envoyer les accès e-learning aux stagiaires » dans votre commande pour déclencher l’envoi.\n" if paid
                     else "Après règlement intégral, cliquez sur « Envoyer les accès e-learning aux stagiaires » dans votre commande.\n")
    plain = (f"Bonjour {person['first_name']},\n{brand['name']} vous a inscrit(e) au parcours {course_full_label(order['course_code'])}. Votre accès est maintenant activé.\n" if person else f"Commande {order['reference']} : {len(order['learners'])} accès {course_label(order['course_code'])}.\nTotal : {money(order['total_cents'])} TTC.\n" + dispatch_note)
    if order["course_code"] == "mac-aps":
        plain += "Ce programme numérique de préparation et de révision ne délivre pas à lui seul l’attestation réglementaire de stage MAC APS.\n"
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
            destination = root / ("elearning-" + order["id"] + ("-paid" if paid else "-due") + ".pdf")
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
    if key == "invoice_paid" and result.get("ok"):
        host.app.logger.info("elearning_confirmation_sent order=%s", order["id"])
    return bool(result.get("ok"))


def sync_invoice_payment(host, order):
    """Read captures for the exact invoice link, before the bank payout arrives.

    The caller has verified the invoice, OAuth merchant and link amount. A
    browser return, a link status alone or an authorized card never grants access.
    """
    state = order["commerce"]
    if not state.get("payment_id") or state.get("invoice_status") == "canceled":
        return
    paid, processing = {}, False
    for page in range(1, 51):
        payload = host._qonto_request("GET", f"/v2/payment_links/{state['payment_id']}/payments",
                                      params={"page": page, "per_page": 100})
        payments = payload.get("payments", [])
        if not isinstance(payments, list):
            raise commerce.ReviewRequired("La réponse de paiement Qonto doit être vérifiée.")
        for payment in payments:
            if payment.get("status") == "paid":
                if not payment.get("id"):
                    raise commerce.ReviewRequired("L’identifiant du règlement Qonto est absent.")
                amount = commerce._money_cents(payment.get("amount"))
                try:
                    paid_at = dt.datetime.fromisoformat(payment["paid_at"].replace("Z", "+00:00"))
                    if paid_at.tzinfo is None or paid_at > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5) or amount <= 0:
                        raise ValueError
                except (KeyError, TypeError, ValueError, AttributeError):
                    raise commerce.ReviewRequired("La date ou le montant du règlement Qonto doit être vérifié.")
                if payment["id"] in paid and paid[payment["id"]] != amount:
                    raise commerce.ReviewRequired("Le règlement Qonto contient des montants contradictoires.")
                paid[payment["id"]] = amount
            processing = processing or payment.get("status") in {"pending", "authorized"}
        if not host._qonto_invoice_list_has_next_page(payload, page, len(payments), 100):
            break
    else:
        raise commerce.ReviewRequired("La liste des règlements Qonto doit être vérifiée.")
    total = sum(paid.values())
    if total == order["total_cents"]:
        commerce._save(host, order, payment_status="paid", paid_cents=total, remaining_cents=0,
                       payment_url="", payment_link_status="paid",
                       confirmed_invoice_payment={"invoice_id": state["invoice_id"], "link_id": state["payment_id"],
                           "payment_ids": sorted(paid), "amount_cents": total, "currency": "EUR", "verified_at": host._now_iso()})
    elif total > 0:
        commerce._save(host, order, payment_url="", payment_status="partially_paid", paid_cents=total,
                       remaining_cents=max(0, order["total_cents"] - total), confirmed_invoice_payment={})
        raise commerce.ReviewRequired("Le règlement reçu ne correspond pas au total de la commande.")
    elif state.get("confirmed_invoice_payment"):
        commerce._save(host, order, payment_status="unpaid", paid_cents=0, remaining_cents=order["total_cents"],
                       confirmed_invoice_payment={}, payment_url="")
        raise commerce.ReviewRequired("Le règlement confirmé n’est plus retrouvé dans Qonto.")
    elif processing or state.get("payment_link_status") in {"paid", "processing"}:
        commerce._save(host, order, payment_status="processing", payment_url="")


def cache_invoice(host, order):
    """Keep the PDF available without requiring an unpaid invoice e-mail."""
    state = order["commerce"]
    if not state.get("invoice_id") or state.get("invoice_status") not in {"unpaid", "paid"}:
        return
    root = Path(host.get_partner_storage_path(order["partner_id"], "factures"))
    destination = root / ("elearning-" + order["id"] + ("-paid" if entitled(order) else "-due") + ".pdf")
    if destination.is_file():
        return
    pdf, _ = host.fetch_qonto_client_invoice_pdf(state["invoice_id"])
    temporary = root / ("." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(pdf)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def process_claimed(host, order):
    """Called by the merchant worker under its durable, ten-minute order lease."""
    if order.get("cancellation_requested_at"):
        from elearning_groups import process_cancellation
        return process_cancellation(host, order)
    previously_paid = entitled(order)
    outcome, error = "ready", ""
    try:
        if not order.get("free_snapshot"):
            invoice = commerce._ensure_invoice(host, order, commerce.settings_from(host.load_data(run_background_tasks=False)))
            if not entitled(order):
                commerce._ensure_payment_link(host, order, invoice)
                sync_invoice_payment(host, order)
                outcome = "ready" if entitled(order) else "waiting_payment"
        if entitled(order) and order.get("access_dispatch_requested_at"):
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
    if entitled(order) and not previously_paid:
        host.app.logger.info("elearning_payment_confirmed order=%s", order["id"])
    sent = True
    state = order["commerce"]
    try:
        cache_invoice(host, order)
    except Exception as exc:
        sent = False
        host.app.logger.warning("elearning_invoice_pdf_pending order=%s type=%s", order["id"], type(exc).__name__)
    already_confirmed_free = order.get("free_snapshot") and state.get("emails", {}).get("confirmation", {}).get("status") == "sent"
    if entitled(order) and not already_confirmed_free:
        # Reuse the historical paid-mail key to avoid resending settled orders.
        sent = send_message(host, order, "invoice_paid", order["centre"]["email"], invoice=bool(state.get("invoice_id"))) and sent
    if entitled(order) and order.get("access_dispatch_requested_at") and order.get("activated_at"):
        for person in order["learners"]:
            sent = send_message(host, order, "learner_" + person["id"], person["email"], person=person) and sent
    state = order["commerce"]
    tracking = bool(state.get("invoice_id") and not entitled(order) and state.get("invoice_status") != "canceled")
    # Keep email retries durable even after a transient mail outage. Sent keys are never replayed.
    queued = tracking or not sent or outcome == "retry"
    delay = (15 if outcome in {"ready", "waiting_payment"} else 60) if tracking else min(60 * 2 ** min(state.get("attempts", 1), 6), 3600)
    def finish(current):
        current_state = current.setdefault("commerce", {})
        if current_state.get("lease_token") != state.get("lease_token"):
            raise commerce.ReviewRequired("Traitement repris par une autre exécution.")
        # A centre may click after payment is saved while this worker is still
        # sending the invoice. Preserve that request and wake a fresh run.
        new_request = bool(current.get("access_dispatch_requested_at")) and not order.get("access_dispatch_requested_at")
        current_state.update(status=outcome, error=error or ("Un e-mail sera renvoyé automatiquement." if not sent else ""),
                             queued=queued or new_request, next_attempt=0 if new_request else time.time() + delay,
                             attempts=0 if sent and tracking else state.get("attempts", 0), lease_until=0)
        return {}
    commerce._mutate(host, order["partner_id"], order["id"], finish)


def register_routes(host, bp, *, page, customer, partner_data, check_csrf, kick_worker):
    @bp.errorhandler(elearning_sales.SalesUnavailable)
    def sales_unavailable(error):
        return page("elearning_sales_unavailable.html", elearning_sales_enabled=False, elearning_sales_notice=False), 409

    def find(data, oid):
        order = next((o for o in data.get("manual_orders", []) if o.get("id") == oid and is_order(o)), None)
        if not order or (not host._is_super_admin_session() and order["partner_id"] != host._current_partner_id()):
            abort(404)
        return order

    def render_order(oid, staff=False, confirmation=False):
        data = host.load_data()
        order = copy.deepcopy(find(data, oid))
        for person in order.get("learners", []):
            person.update(last_name=normalize_name(person.get("last_name"), surname=True), first_name=normalize_name(person.get("first_name")))
        if confirmation and not entitled(order):
            return redirect(url_for("manuals_shop.elearning_order", oid=oid), code=303)
        return page("elearning_order.html", order=order, partner=order["centre"], staff=staff, unlocked=entitled(order), order_status=status_view(order), confirmation=confirmation)

    @bp.post("/admin/organisme/e-learning/recapitulatif")
    @customer
    @elearning_sales.required(host)
    def elearning_checkout():
        check_csrf()
        data, partner = partner_data()
        code = request.form.get("course_code")
        values = request.form.to_dict()
        rows = [{"last_name": l, "first_name": f, "email": e} for l, f, e in zip(request.form.getlist("last_name"), request.form.getlist("first_name"), request.form.getlist("email"))]
        try:
            if code not in COURSES:
                raise ValueError("Choisissez un parcours APS, MAC APS, A3P ou VTC.")
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
                     "items": [{"kind": "elearning", "code": code, "label": "Accès e-learning " + course_label(code), "quantity": quantity, "unit_cents": unit, "total_cents": unit * quantity}],
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
        return render_order(oid, staff=host._is_super_admin_session() and not session.get("assist_partner_id"))

    @bp.get("/admin/organisme/e-learning/commandes/<oid>/confirmation")
    @customer
    def elearning_confirmation(oid):
        return render_order(oid, confirmation=True)

    @bp.post("/admin/organisme/e-learning/commandes/<oid>/confirmer")
    @customer
    @elearning_sales.required(host)
    def elearning_confirm(oid):
        check_csrf()
        if request.form.get("confirm") != "yes":
            abort(400)
        _, partner = partner_data()
        from manuals_public import acceptance
        terms = acceptance(host)
        def confirm(data):
            order = find(data, oid)
            if order["status"] != "draft":
                return {}
            current = host._partner_or_404(data, partner["id"])
            price = prices(current)[order["course_code"]]
            if (price["unit_cents"], price["free"]) != (order["unit_cents"], order["free_snapshot"]):
                abort(409, "Votre tarif a changé. Préparez une nouvelle commande pour consulter le nouveau total.")
            order["terms_acceptance"] = terms
            order.update(status="received", reference="EL-" + str(dt.date.today().year) + "-" + oid[:8].upper(), submitted_at=host._now_iso(),
                         commerce={"queued": True, "status": "pending", "flow": "elearning_invoice_first", "attempts": 0, "emails": {}})
            return {}
        host._atomic_update_data(confirm, partner_id=partner["id"])
        kick_worker()
        return checkout_response(oid)

    @bp.get("/admin/organisme/e-learning/commandes/<oid>/statut")
    @customer
    def elearning_status(oid):
        order = find(host.load_data(run_background_tasks=False), oid)
        state = order.get("commerce", {})
        if state.get("queued") and state.get("next_attempt", 0) <= time.time() and state.get("lease_until", 0) <= time.time():
            kick_worker()
        # No learner identities or access tokens in this polling response.
        return status_view(order), 200, {"Cache-Control": "no-store"}

    @bp.post("/admin/organisme/e-learning/commandes/<oid>/envoyer-acces")
    @customer
    def elearning_send_accesses(oid):
        check_csrf()
        _, partner = partner_data()
        def request_dispatch(data):
            order = find(data, oid)
            if not entitled(order):
                abort(409, "L’envoi des accès est bloqué jusqu’à la confirmation du règlement intégral.")
            delivery = status_view(order)
            if delivery["dispatch_complete"] or delivery["dispatch_requested"]:
                return {"complete": delivery["dispatch_complete"]}
            order.update(access_dispatch_requested_at=host._now_iso(), access_dispatch_requested_by=session.get("user_id"))
            # Keep any current worker's lease: it will pick up this request at
            # completion. A double click never creates another delivery.
            order.setdefault("commerce", {}).update(queued=True, next_attempt=0)
            return {"complete": False}
        result = host._atomic_update_data(request_dispatch, partner_id=partner["id"])
        kick_worker()
        flash("Les accès ont déjà été envoyés." if result.get("complete") else "L’envoi des accès e-learning aux stagiaires est demandé. Vous pouvez suivre chaque e-mail ci-dessous.", "success")
        return redirect(url_for("manuals_shop.elearning_order", oid=oid), code=303)

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
        path = Path(host.get_partner_storage_path(order["partner_id"], "factures")) / ("elearning-" + oid + ("-paid" if entitled(order) else "-due") + ".pdf")
        if not path.is_file():
            abort(409, "La facture est en préparation. Réessayez dans quelques instants.")
        return send_file(io.BytesIO(path.read_bytes()), mimetype="application/pdf", as_attachment=False, download_name="Facture-" + order["reference"] + ".pdf")

    @bp.route("/admin/commandes-elearning", methods=["GET", "POST"])
    @host.admin_login_required
    @host.require_super_admin
    def elearning_admin():
        if host._is_partner_data_scope_session():
            abort(403, "Quittez l’assistance d’un organisme avant de modifier les ventes ou les tarifs.")
        if request.method == "POST":
            check_csrf()
            if request.form.get("action") == "sales_settings":
                sales_enabled = request.form.get("sales_enabled") == "yes"
                elearning_sales.save(host, sales_enabled, session.get("user_id") or session.get("admin_user"))
                flash("Les ventes d’accès e-learning sont activées." if sales_enabled else
                      "Les ventes d’accès e-learning sont suspendues. Le message de mise à jour est affiché dans la boutique.", "success")
                if request.form.get("return_to") == "partners":
                    return redirect(url_for("admin_partners"), code=303)
                return redirect(url_for("manuals_shop.elearning_admin"), code=303)
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

