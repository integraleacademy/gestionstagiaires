"""Merchant-side order fulfilment, never run in a customer's request context.

The order is the durable queue. Short atomic claims work with both stores;
network calls never hold a store lock. An uncertain invoice creation is
reconciled by its immutable purchase_order before any further action.
"""
from __future__ import annotations

import copy
import os
import threading
import time
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse

from flask import has_request_context

ADMIN_EMAIL = "clement@integraleacademy.com"
VAT_RATES = {"0", "2.1", "5.5", "10", "20"}
EXEMPTIONS = {"S293B", "S261", "S262", "S262.1", "S259", "S283"}
PAYMENT_LABELS = {"unpaid": "À régler", "paid": "Payée", "partially_paid": "Partiellement réglée", "canceled": "Facture annulée", "draft": "Facture en préparation"}
PAYMENT_SCOPES = ("client_invoices.read", "payment_link.read", "payment_link.write")


class SetupRequired(Exception):
    pass


class ReviewRequired(Exception):
    pass


def settings_from(data):
    return copy.deepcopy(data.get("manuals_commerce_settings") or {})


def configuration_status(host, data, order=None):
    """Read local prerequisites without contacting Qonto or starting billing."""
    settings = settings_from(data)
    taxes = (order or {}).get("commerce", {}).get("taxes") or {}
    kinds = {line["kind"] for line in order["items"]} if order else {"manual", "usb"}
    missing_taxes = []
    for kind in sorted(kinds):
        tax = taxes.get(kind) or {}
        rate = tax.get("rate", settings.get(kind + "_vat"))
        exemption = tax.get("exemption", settings.get(kind + "_exemption"))
        if rate not in VAT_RATES or (rate == "0" and exemption not in EXEMPTIONS):
            missing_taxes.append("manuels imprimés" if kind == "manual" else "supports PowerPoint sur clé USB")
    return {
        "api_configured": host._qonto_is_configured(),
        "iban_configured": bool(os.environ.get("QONTO_IBAN", "").strip()),
        "missing_taxes": missing_taxes,
        "payment_authorized": host._qonto_oauth_connected(data) and all(
            host._qonto_oauth_has_scope(scope, data) for scope in PAYMENT_SCOPES
        ),
    }


def validate_settings(form):
    result = {}
    for kind in ("manual", "usb"):
        rate = str(form.get(kind + "_vat", "")).strip().replace(",", ".")
        if rate not in VAT_RATES:
            raise ValueError("Sélectionnez le taux de TVA des manuels et des supports PowerPoint.")
        exemption = str(form.get(kind + "_exemption", "")).strip()
        if rate == "0" and exemption not in EXEMPTIONS:
            raise ValueError("Précisez le motif d’exonération pour chaque catégorie à 0 %.")
        result[kind + "_vat"] = rate
        result[kind + "_exemption"] = exemption if rate == "0" else ""
    return result


def tax_snapshot(order, settings):
    snapshot = {}
    for kind in {line["kind"] for line in order["items"]}:
        rate = settings.get(kind + "_vat")
        exemption = settings.get(kind + "_exemption", "")
        if rate not in VAT_RATES or (rate == "0" and exemption not in EXEMPTIONS):
            raise SetupRequired("Renseignez la TVA des produits dans les réglages des commandes.")
        snapshot[kind] = {"rate": rate, "exemption": exemption}
    return snapshot


def build_invoice_payload(order, client_id, iban):
    items = []
    for line in order["items"]:
        tax = order["commerce"]["taxes"][line["kind"]]
        rate = Decimal(tax["rate"]) / 100
        # Keep quantities and the brochure's exact TTC prices. Only finalize
        # after Qonto's own calculation is checked against the order total.
        net = (Decimal(line["unit_cents"]) / 100 / (1 + rate)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
        item = {"title": line["label"], "quantity": str(line["quantity"]),
                "unit_price": {"value": format(net, "f"), "currency": "EUR"},
                "vat_rate": str(rate),
                "description": f"Prix unitaire TTC : {Decimal(line['unit_cents']) / 100:.2f} EUR. Personnalisation et livraison incluses."}
        if tax["exemption"]:
            item["vat_exemption_reason"] = tax["exemption"]
        items.append(item)
    return {"client_id": client_id, "status": "draft", "currency": "EUR",
            "issue_date": order["submitted_at"][:10], "due_date": order["submitted_at"][:10],
            "purchase_order": order["id"], "header": "Commande " + order["reference"],
            "payment_methods": {"iban": iban}, "items": items,
            "settings": {"transaction_type": "goods"},
            "terms_and_conditions": "Paiement à réception de facture. Personnalisation et livraison incluses."}


def safe_payment_url(value):
    value = str(value or "").strip()
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.hostname in {"pay.qonto.com", "pay-sandbox.qonto.com"} and not parsed.username and not parsed.password:
        return value
    return ""


def _find(data, partner_id, order_id):
    return next((o for o in data.get("manual_orders", []) if o.get("id") == order_id and o.get("partner_id") == partner_id), None)


def _mutate(host, pid, oid, change):
    def update(data):
        order = _find(data, pid, oid)
        if order is None:
            return {}
        return change(order) or {}
    return host._atomic_update_data(update, partner_id=pid)


def _save(host, order, **fields):
    token = order["commerce"]["lease_token"]
    def update(current):
        state = current.setdefault("commerce", {})
        if state.get("lease_token") != token:
            raise ReviewRequired("Traitement repris par une autre exécution.")
        state.update(copy.deepcopy(fields))
        state["lease_until"] = time.time() + 600
        return {"commerce": copy.deepcopy(state)}
    result = _mutate(host, order["partner_id"], order["id"], update)
    if not result:
        raise ReviewRequired("La commande n’existe plus.")
    order["commerce"] = result["commerce"]


def _invoice_total(invoice):
    value = invoice.get("total_amount_cents")
    if value is not None:
        return int(value)
    money = invoice.get("total_amount", {})
    try:
        return int((Decimal(str(money.get("value") if isinstance(money, dict) else money)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError):
        raise ReviewRequired("Le montant de la facture Qonto est absent ou invalide.")


def _assert_invoice(order, invoice):
    if not invoice.get("id") or invoice.get("purchase_order") != order["id"]:
        raise ReviewRequired("La référence de commande de la facture Qonto ne correspond pas.")
    if order["commerce"].get("invoice_id") and invoice["id"] != order["commerce"]["invoice_id"]:
        raise ReviewRequired("L’identifiant de la facture Qonto ne correspond pas.")
    client = invoice.get("client") or {}
    if str(invoice.get("client_id") or client.get("id") or "") != order["commerce"]["client_id"]:
        raise ReviewRequired("Le client de la facture Qonto ne correspond pas.")
    # Qonto's invoice response puts currency in total_amount, unlike the
    # creation payload. Reject missing or conflicting currencies as before.
    total_amount = invoice.get("total_amount") or {}
    currencies = [value for value in (
        invoice.get("currency"),
        total_amount.get("currency") if isinstance(total_amount, dict) else None,
    ) if value]
    if not currencies or any(value != "EUR" for value in currencies) or _invoice_total(invoice) != order["total_cents"]:
        raise ReviewRequired("Le total calculé par Qonto diffère du total TTC de la commande. Vérifiez le brouillon avant toute émission.")


def _recover_invoice(host, order):
    for page in range(1, 51):
        payload = host.list_qonto_invoices({"filter[created_at_from]": order["submitted_at"], "sort_by": "created_at:desc", "per_page": 100, "page": page})
        invoices = list(host._iter_qonto_invoice_payloads(payload))
        matches = [inv for inv in invoices if inv.get("purchase_order") == order["id"]]
        if len(matches) > 1:
            raise ReviewRequired("Plusieurs factures portent cette référence de commande. Contrôle nécessaire dans Qonto.")
        if matches:
            return host._qonto_invoice_payload(host.get_qonto_invoice(matches[0]["id"]))
        if not host._qonto_invoice_list_has_next_page(payload, page, len(invoices), 100):
            return None
    raise ReviewRequired("La recherche de facture Qonto doit être vérifiée manuellement.")


def _ensure_invoice(host, order, settings):
    state = order["commerce"]
    if not host._qonto_is_configured():
        raise SetupRequired("Configurez la connexion API Qonto dans les réglages de la plateforme.")
    try:
        iban = host.get_qonto_invoice_iban()
    except ValueError:
        raise SetupRequired("L’IBAN de facturation Qonto n’est pas configuré (QONTO_IBAN).")
    if not state.get("taxes"):
        _save(host, order, taxes=tax_snapshot(order, settings))
    if not order["commerce"].get("client_id"):
        address = order.get("billing") or order["delivery"]
        country = address.get("country_code") or ("FR" if address.get("country", "").lower() in {"france", "fr"} else "")
        if not country:
            raise SetupRequired("Vérifiez le pays de l’adresse de facturation avant de créer la facture.")
        payload = {"kind": "company", "name": order["centre"]["name"], "email": order["centre"]["email"],
                   "tax_identification_number": order["centre"]["siret"], "currency": "EUR", "locale": "FR",
                   "billing_address": {"street_address": " ".join(filter(None, [address["address"], address.get("address_extra")])), "zip_code": address["postal_code"], "city": address["city"], "country_code": country}}
        result = host._qonto_request("GET", "/v2/clients", params={"filter[tax_identification_number]": order["centre"]["siret"]})
        exact = [c for c in result.get("clients", []) if re_tax(c.get("tax_identification_number")) == order["centre"]["siret"]]
        if exact:
            result = host.update_qonto_client(exact[0]["id"], payload)
        else:
            result = host._qonto_request("POST", "/v2/clients", payload, idempotency_key="manuals-client-" + order["id"])
        client = result.get("client") or result
        if not client.get("id"):
            raise RuntimeError("Qonto n’a pas renvoyé le client de facturation.")
        _save(host, order, client_id=client["id"])
    state = order["commerce"]
    if state.get("invoice_id"):
        invoice = host._qonto_invoice_payload(host.get_qonto_invoice(state["invoice_id"]))
    elif state.get("invoice_creation_started"):
        invoice = _recover_invoice(host, order)
        if not invoice:
            # Never gamble on the provider's 30-minute idempotency lifetime.
            raise ReviewRequired("Création de facture non confirmée : vérifiez Qonto avant de réautoriser une création. Aucune seconde facture n’a été émise.")
    else:
        payload = build_invoice_payload(order, state["client_id"], iban)
        _save(host, order, invoice_creation_started=host._now_iso())
        try:
            invoice = host._qonto_invoice_payload(host._qonto_request("POST", "/v2/client_invoices", payload, idempotency_key="manuals-invoice-" + order["id"]))
        except host.QontoApiError as exc:
            if exc.status_code in {400, 401, 403, 422, 429}:
                _save(host, order, invoice_creation_started="")
            raise
    if invoice.get("id"):
        _save(host, order, invoice_id=invoice["id"], invoice_number=invoice.get("number", ""))
    _assert_invoice(order, invoice)
    if invoice.get("status") == "draft":
        host.finalize_qonto_invoice(invoice["id"])
        invoice = host._qonto_invoice_payload(host.get_qonto_invoice(invoice["id"]))
        _assert_invoice(order, invoice)
    if invoice.get("status") not in {"unpaid", "paid", "canceled"}:
        raise ReviewRequired("La facture n’est pas encore finalisée dans Qonto.")
    normalized = host.normalize_qonto_invoice_payment_data(invoice)
    _save(host, order, invoice_number=invoice.get("number", ""), invoice_url=safe_payment_url(invoice.get("invoice_url")),
          invoice_status=invoice["status"], payment_status=normalized["qonto_payment_status"],
          paid_cents=normalized["qonto_amount_paid_cents"], remaining_cents=normalized["qonto_remaining_amount_cents"], synced_at=host._now_iso())
    return invoice


def re_tax(value):
    return "".join(c for c in str(value or "") if c.isdigit())


def _ensure_payment_link(host, order, invoice):
    state = order["commerce"]
    if state.get("payment_status") in {"paid", "canceled"}:
        return
    if state.get("payment_status") == "partially_paid":
        _save(host, order, payment_url="")
        raise ReviewRequired("Un règlement partiel a été constaté. Vérifiez le solde et le lien de paiement dans Qonto.")
    data = host.load_data(run_background_tasks=False)
    if not host._qonto_oauth_connected(data) or not all(host._qonto_oauth_has_scope(scope, data) for scope in PAYMENT_SCOPES):
        raise SetupRequired("La facture est créée. Autorisez les liens de paiement Qonto depuis les réglages de facturation pour permettre le règlement en ligne.")
    # Invoice API keys and payment OAuth credentials must belong to the same
    # merchant. Prove the OAuth grant can read this exact issued invoice.
    authorized_invoice = host._qonto_invoice_payload(host._qonto_request("GET", "/v2/client_invoices/" + invoice["id"], use_oauth=True))
    _assert_invoice(order, authorized_invoice)
    if authorized_invoice.get("organization_id") != invoice.get("organization_id"):
        raise ReviewRequired("La connexion de paiement Qonto n’appartient pas à l’organisme qui a émis la facture.")
    if state.get("payment_id"):
        result = host._qonto_request("GET", "/v2/payment_links/" + state["payment_id"])
        link = result.get("payment_link") or {}
    else:
        # Resolve a previous interrupted request by invoice ID, never by amount.
        link = None
        if state.get("payment_creation_started"):
            for page in range(1, 51):
                response = host._qonto_request("GET", "/v2/payment_links", params={"page": page, "per_page": 100})
                links = response.get("payment_links", [])
                matches = [p for p in links if p.get("invoice_id") == invoice["id"]]
                if len(matches) > 1:
                    raise ReviewRequired("Plusieurs liens de paiement existent pour cette facture. Vérifiez Qonto.")
                if matches:
                    link = matches[0]
                    break
                if not host._qonto_invoice_list_has_next_page(response, page, len(links), 100):
                    break
            if not link:
                raise ReviewRequired("Création du lien de paiement non confirmée. Vérifiez Qonto avant une nouvelle création.")
        if link is None:
            # Calling this read endpoint also checks OAuth scopes/provider activation.
            available = host._qonto_request("GET", "/v2/payment_links/payment_methods", params={"amount": f"{Decimal(order['total_cents']) / 100:.2f}", "currency": "EUR"})
            methods = [m["name"] for m in available.get("payment_link_payment_methods", []) if isinstance(m, dict) and m.get("enabled") is True and m.get("name") in {"credit_card", "apple_pay", "paypal", "ideal"}]
            if not methods:
                raise SetupRequired("Activez les liens de paiement Qonto et au moins un moyen de paiement dans votre compte Qonto.")
            payload = {"payment_link": {"invoice_id": invoice["id"], "invoice_number": invoice["number"], "debitor_name": order["centre"]["name"], "amount": {"value": f"{Decimal(order['total_cents']) / 100:.2f}", "currency": "EUR"}, "potential_payment_methods": methods}}
            _save(host, order, payment_creation_started=host._now_iso())
            try:
                response = host._qonto_request("POST", "/v2/payment_links", payload, idempotency_key="manuals-payment-" + order["id"])
                link = response.get("payment_link") or {}
            except host.QontoApiError as exc:
                if exc.status_code in {400, 401, 403, 422, 429}:
                    _save(host, order, payment_creation_started="")
                raise
    if link.get("invoice_id") != invoice["id"] or not link.get("id"):
        raise ReviewRequired("Le lien de paiement Qonto ne correspond pas à la facture.")
    amount = link.get("amount") or {}
    if amount.get("currency") != "EUR" or Decimal(str(amount.get("value", "-1"))) * 100 != order["total_cents"]:
        raise ReviewRequired("Le montant du lien de paiement ne correspond pas à la commande.")
    url = safe_payment_url(link.get("url"))
    if not url:
        raise ReviewRequired("Qonto n’a pas renvoyé de lien de paiement sécurisé.")
    _save(host, order, payment_id=link["id"], payment_url=url, payment_link_status=link.get("status"))
    if link.get("status") in {"expired", "canceled"}:
        _save(host, order, payment_url="")
        raise ReviewRequired("Le lien de paiement a expiré ou a été désactivé dans Qonto.")


def _send_email(host, order, key, recipient, staff=False):
    state = order["commerce"]
    emails = copy.deepcopy(state.get("emails") or {})
    if emails.get(key, {}).get("status") == "sent":
        return True
    emails[key] = {"status": "sending", "attempted_at": host._now_iso(), "to": recipient}
    _save(host, order, emails=emails)
    from manuals_shop import base_url, money
    detail_path = f"/admin/commandes-manuels/{order['partner_id']}/{order['id']}" if staff else f"/admin/manuels/commandes/{order['id']}"
    order_url = base_url(host) + detail_path
    invoice_ready = key == "invoice_customer"
    subject = ("Nouvelle commande " if staff else "Votre facture est disponible · " if invoice_ready else "Confirmation de commande · ") + order["reference"]
    # Standalone email: avoid request-only CRM context processors in the worker.
    body = host.app.jinja_env.get_template("manuals/order_email.html").render(order=order, staff=staff, invoice_ready=invoice_ready, order_url=order_url)
    lines = "\n".join(f"{i['quantity']} × {i['label']} : {money(i['total_cents'])}" for i in order["items"])
    text = f"{subject}\n{order['centre']['name']}\n{lines}\nTotal TTC : {money(order['total_cents'])}\nLivraison et personnalisation incluses.\nConsulter la commande : {order_url}"
    if order["commerce"].get("payment_url"):
        text += "\nRégler en ligne : " + order["commerce"]["payment_url"]
    try:
        result = host.brevo_send_email(recipient, subject, body, text_content=text, metadata={"partner_id": order["partner_id"], "purpose": "manuals_" + key, "order_id": order["id"]})
    except Exception:
        result = {"ok": False, "error": "Envoi indisponible"}
    emails[key] = {"status": "sent" if result.get("ok") else "failed", "attempted_at": host._now_iso(), "to": recipient, "message_id": result.get("message_id", "")}
    _save(host, order, emails=emails)
    return bool(result.get("ok"))


def process_order(host, pid, oid):
    if has_request_context():
        raise RuntimeError("Merchant fulfilment must run outside customer request contexts")
    now = time.time()
    def claim(order):
        state = order.setdefault("commerce", {})
        if order.get("status") in {"draft", "cancelled"} or not state.get("queued") or state.get("lease_until", 0) > now or state.get("next_attempt", 0) > now:
            return {}
        state.update(lease_token=str(uuid.uuid4()), lease_until=now + 600, status="processing", attempts=state.get("attempts", 0) + 1)
        return {"order": copy.deepcopy(order)}
    claimed = _mutate(host, pid, oid, claim)
    if not claimed:
        return
    order = claimed["order"]
    outcome, message = "ready", ""
    try:
        # Confirmations are independent of invoice setup or provider outages.
        customer_sent = _send_email(host, order, "confirmation_customer", order["centre"]["email"])
        admin_sent = _send_email(host, order, "notification_admin", ADMIN_EMAIL, staff=True)
        try:
            invoice = _ensure_invoice(host, order, settings_from(host.load_data(run_background_tasks=False)))
            _ensure_payment_link(host, order, invoice)
        except (SetupRequired, host.QontoConfigurationError) as exc:
            outcome, message = "needs_setup", str(exc)
        except ReviewRequired as exc:
            outcome, message = "needs_review", str(exc)
        except Exception as exc:
            outcome = "retry"
            message = host.format_qonto_error_for_front(exc)[:500]
            host.app.logger.warning("manual_order_billing_error order=%s type=%s", oid, type(exc).__name__)
        invoice_sent = True
        if order["commerce"].get("payment_url") or order["commerce"].get("payment_status") == "paid":
            invoice_sent = _send_email(host, order, "invoice_customer", order["centre"]["email"])
        sent = customer_sent and admin_sent and invoice_sent
        if outcome == "ready" and not sent:
            outcome, message = "retry", "Un e-mail n’a pas pu être envoyé. Une nouvelle tentative est programmée."
        state = order["commerce"]
        retry = outcome == "retry" and state["attempts"] < 8
        # Refresh settled status periodically, using only authoritative Qonto data.
        track = outcome == "ready" and state.get("payment_status") not in {"paid", "canceled"}
        _save(host, order, status=outcome, error=message, queued=retry or track or (not sent and state["attempts"] < 8),
              attempts=0 if outcome == "ready" else state["attempts"],
              next_attempt=now + (900 if track else min(60 * 2 ** min(state["attempts"], 6), 3600)), lease_until=0)
    finally:
        def release(current):
            state = current.get("commerce", {})
            if state.get("lease_token") == order["commerce"]["lease_token"]:
                state["lease_until"] = 0
        _mutate(host, pid, oid, release)


def queue_again(host, pid, oid, *, throttle=False):
    def change(order):
        if order.get("status") in {"draft", "cancelled"}:
            return {}
        state = order.setdefault("commerce", {})
        if throttle and state.get("refresh_requested_at", 0) > time.time() - 60:
            return {}
        if state.get("lease_until", 0) <= time.time():
            state.update(queued=True, next_attempt=0, attempts=0, refresh_requested_at=time.time())
        return {}
    _mutate(host, pid, oid, change)


def install_worker(host):
    lock, wake = threading.Lock(), threading.Event()
    running = [False]
    def run():
        logged_configuration = False
        while True:
            try:
                with host.app.app_context():
                    data = host.load_data(run_background_tasks=False)
                    if not logged_configuration:
                        host.app.logger.info("manuals_commerce_configuration invoice_api=%s iban=%s vat=%s payment_scopes=%s email_ready=%s",
                            host._qonto_is_configured(), bool(os.environ.get("QONTO_IBAN")), bool(settings_from(data)),
                            host._qonto_oauth_connected(data) and all(host._qonto_oauth_has_scope(s, data) for s in ("payment_link.read", "payment_link.write")),
                            not bool(host._missing_brevo_config()))
                        logged_configuration = True
                    orders = data.get("manual_orders", [])
                    for order in orders:
                        state = order.get("commerce", {})
                        if state.get("queued") and state.get("next_attempt", 0) <= time.time():
                            process_order(host, order["partner_id"], order["id"])
            except Exception as exc:
                host.app.logger.error("manual_order_worker_error type=%s", type(exc).__name__)
            wake.wait(45)
            wake.clear()
    def kick(*, notify=True):
        if host.app.testing or "PYTEST_CURRENT_TEST" in os.environ:
            return
        with lock:
            if not running[0]:
                threading.Thread(target=run, name="manuals-orders", daemon=True).start()
                running[0] = True
        if notify:
            wake.set()
    return kick
