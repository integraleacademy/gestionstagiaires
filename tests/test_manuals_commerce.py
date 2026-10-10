import base64
import copy
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pytest
import app as host
import manuals_commerce as commerce
from test_manuals_shop import shop, signup, login, csrf, order_form, all_data


def submitted(shop, **fields):
    c = shop["client"]
    signup(c)
    login(c)
    location = c.post("/admin/manuels/recapitulatif", data=order_form(c, **fields)).location
    response = c.post(location + "/confirmer", data={"csrf_token": csrf(c, location), "confirm": "yes"})
    assert response.status_code == 303
    return all_data(shop)["manual_orders"][0]


def run(order):
    with host.app.app_context():
        commerce.process_order(host, order["partner_id"], order["id"])


def retry(order):
    with host.app.app_context():
        commerce.queue_again(host, order["partner_id"], order["id"])
    run(order)


@pytest.fixture
def merchant(shop, monkeypatch):
    settings = {"manual_vat": "5.5", "manual_exemption": "", "usb_vat": "20", "usb_exemption": ""}
    def configure(data):
        data["manuals_commerce_settings"] = settings
        return {}
    host._atomic_update_data(configure)
    monkeypatch.setattr(host, "_qonto_is_configured", lambda: True)
    monkeypatch.setattr(host, "_qonto_oauth_connected", lambda *a: True)
    monkeypatch.setattr(host, "_qonto_oauth_has_scope", lambda *a: True)
    monkeypatch.setattr(host, "get_qonto_invoice_iban", lambda: "FR7612345678901234567890185")
    state = {"calls": [], "invoice": None, "payment": None, "unknown_invoice": False, "wrong_total": False, "payment_disabled": False, "payment_pending": False, "pdf_downloads": [], "pdf_unavailable": False, "paid": False, "payments": None, "unknown_payment": False}
    def invoice_pdf(invoice_id):
        assert not host.has_request_context()
        state["pdf_downloads"].append(invoice_id)
        if state["pdf_unavailable"]:
            raise host.QontoPdfUnavailableError("PDF en cours de génération", 409)
        return b"%PDF-1.4\ninvoice fixture\n%%EOF", "F-2026-123.pdf"
    monkeypatch.setattr(host, "fetch_qonto_client_invoice_pdf", invoice_pdf)
    def request(method, path, payload=None, params=None, **kwargs):
        assert not host.has_request_context(), "Merchant Qonto calls must not run in a tenant request"
        state["calls"].append((method, path, copy.deepcopy(payload), copy.deepcopy(params), kwargs))
        if path == "/v2/organization":
            return {"organization": {"id": "merchant-1", "bank_accounts": [{"id": "merchant-account"}]}}
        if path == "/v2/clients" and method == "GET":
            return {"clients": []}
        if path == "/v2/clients" and method == "POST":
            state["client"] = payload
            return {"client": {"id": "client-centre", **payload}}
        if path == "/v2/client_invoices" and method == "POST":
            total = 0
            for item in payload["items"]:
                total += int((Decimal(item["unit_price"]["value"]) * Decimal(item["quantity"]) * (1 + Decimal(item["vat_rate"])) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            # Match the documented response, not the request: currency belongs
            # to total_amount and client_id is returned as a nested client.
            state["invoice"] = {**payload, "id": "invoice-1", "organization_id": "merchant-1", "number": "F-2026-123", "total_amount_cents": total + (1 if state["wrong_total"] else 0), "total_amount": {"value": str(Decimal(total) / 100), "currency": "EUR"}, "invoice_url": "https://pay.qonto.com/invoices/invoice-1"}
            state["invoice"].pop("currency")
            state["invoice"]["client"] = {"id": state["invoice"].pop("client_id")}
            if state["unknown_invoice"]:
                raise RuntimeError("Read timeout after provider accepted invoice")
            return {"client_invoice": copy.deepcopy(state["invoice"])}
        if path == "/v2/client_invoices" and method == "GET":
            return {"client_invoices": [copy.deepcopy(state["invoice"])] if state["invoice"] else [], "meta": {"total_pages": 1}}
        if path == "/v2/client_invoices/invoice-1/finalize":
            state["invoice"]["status"] = state.get("invoice_status_after_finalize", "unpaid")
            return {"client_invoice": copy.deepcopy(state["invoice"])}
        if path == "/v2/client_invoices/invoice-1/mark_as_paid":
            state["invoice"].update(status="paid", paid_at=payload["paid_at"])
            return {"client_invoice": copy.deepcopy(state["invoice"])}
        if path == "/v2/client_invoices/invoice-1":
            return {"client_invoice": copy.deepcopy(state["invoice"])}
        if path == "/v2/payment_links/payment_methods":
            if state["payment_disabled"]:
                raise host.QontoConfigurationError("Liens de paiement à activer")
            if state["payment_pending"]:
                return {"payment_link_payment_methods": []}
            return {"payment_link_payment_methods": [{"name": "credit_card", "enabled": True}, {"name": "paypal", "enabled": False}]}
        if path == "/v2/payment_links/connections":
            return {"status": "pending" if state["payment_pending"] else "enabled", "bank_account_id": "merchant-account"}
        if path == "/v2/payment_links" and method == "POST":
            state["payment"] = {**payload["payment_link"], "id": "link-1", "url": "https://pay.qonto.com/link-1", "status": "open"}
            if "items" in payload["payment_link"]:
                cents = sum(int((Decimal(i["unit_price"]["value"]) * Decimal(i["quantity"]) * (1 + Decimal(i["vat_rate"])) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) for i in payload["payment_link"]["items"])
                state["payment"].update(resource_type="Basket", amount={"value": f"{Decimal(cents)/100:.2f}", "currency": "EUR"}, invoice_id=None)
            if state["unknown_payment"]:
                raise RuntimeError("Read timeout after provider accepted payment link")
            return {"payment_link": copy.deepcopy(state["payment"])}
        if path == "/v2/payment_links" and method == "GET":
            return {"payment_links": [copy.deepcopy(state["payment"])] if state["payment"] else [], "meta": {"total_pages": 1}}
        if path == "/v2/payment_links/link-1/payments":
            payments = state["payments"] if state["payments"] is not None else ([{"id": "capture-1", "status": "paid", "amount": copy.deepcopy(state["payment"]["amount"]), "paid_at": "2026-01-01T10:00:00Z", "payment_method": "credit_card", "debitor_email": "payer@example.test"}] if state["paid"] else [])
            return {"payments": copy.deepcopy(payments), "meta": {"total_pages": 1}}
        if path == "/v2/payment_links/link-1":
            return copy.deepcopy(state["payment"])  # Documented GET response is unwrapped.
        raise AssertionError((method, path))
    monkeypatch.setattr(host, "_qonto_request", request)
    return state


def test_portal_links_to_aps_vtc_ordering(shop):
    client = shop["client"]
    signup(client)
    login(client)
    portal = client.get("/admin/organisme")
    assert portal.status_code == 200 and "Commander des accès" in portal.text
    root = "/admin/organisme/e-learning"
    page = client.get(root)
    assert page.status_code == 200
    assert root + '/nouveau' in page.text and root + '/nouveau?mode=individual' in page.text
    assert 'name="last_name"' not in page.text
    assert 'Prochainement' not in page.text

    creation = client.get(root + "/nouveau")
    assert creation.status_code == 200
    for field in ('name="mode" value="group"', 'name="mode" value="individual"',
                  'name="course_code" value="aps"', 'name="course_code" value="vtc"'):
        assert field in creation.text
    assert 'name="last_name"' not in creation.text
    request_id = re.search(rb'name="request_id" value="([^"]+)"', creation.data).group(1).decode()
    created = client.post(root + "/nouveau", data={"csrf_token": csrf(client, root + "/nouveau"),
                          "request_id": request_id, "mode": "group", "course_code": "aps", "group_name": "APS septembre 2026"})
    assert created.status_code == 303 and root + "/groupes/" in created.location
    roster = client.get(created.location)
    assert roster.status_code == 200
    assert all('name="' + field + '"' in roster.text for field in ("last_name", "first_name", "email"))
    assert "Enregistrer et continuer plus tard" in roster.text and "Créer les espaces e-learning" in roster.text
    saved = all_data(shop)["manual_orders"]
    assert len(saved) == 1 and saved[0]["order_type"] == "elearning_group" and not saved[0].get("commerce")


def test_order_emails_invoice_payment_and_no_duplicates(shop, merchant):
    order = submitted(shop, billing_different="yes", billing_address="2 rue Facturation", billing_postal_code="69001", billing_city="Lyon")
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "waiting_payment" and flow["payment_status"] == "unpaid"
    assert not flow.get("invoice_id") and merchant["invoice"] is None
    assert merchant["payment"]["amount"] == {"value": "2599.00", "currency": "EUR"}
    assert merchant["payment"]["resource_type"] == "Basket" and merchant["payment"]["reusable"] is False
    assert merchant["payment"]["potential_payment_methods"] == ["credit_card"]
    assert flow["emails"]["payment_customer"]["status"] == "sent"
    assert "invoice_customer" not in flow["emails"] and not merchant["pdf_downloads"]
    payment_mail, payment_meta = shop["mails"][-1]
    assert "paiement à effectuer" in payment_mail[1]
    assert "Votre commande est à régler" in payment_mail[2]
    for content in (payment_mail[2], payment_meta["text_content"]):
        assert "Payer 2\u202f599,00 €" in content
        assert "Après confirmation du paiement, votre facture sera créée" in content
        assert "paiement est confirmé" not in content
        assert "facture acquittée" not in content and "pièce jointe" not in content
    assert payment_mail[2].index("Payer 2\u202f599,00 €") < payment_mail[2].index("Manuel APS")
    assert "Place à vos prochaines formations" not in payment_mail[2]
    assert not shop["mails"][-1][1]["attachments"]
    for path in ("/admin/organisme", "/admin/manuels", f"/admin/manuels/commandes/{order['id']}"):
        page = shop["client"].get(path)
        assert "Régler en ligne" in page.text and "pay.qonto.com/invoices/" not in page.text
    retry(order)
    assert len(shop["mails"]) == 4 and merchant["invoice"] is None
    merchant["paid"] = True
    retry(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "ready" and flow["payment_status"] == flow["invoice_status"] == "paid"
    assert not flow["queued"] and flow["invoice_id"] == "invoice-1"
    assert merchant["client"]["billing_address"]["city"] == "Lyon"
    assert "Commande réglée en ligne" in merchant["invoice"]["terms_and_conditions"]
    assert "capture-1" in merchant["invoice"]["terms_and_conditions"]
    assert flow["confirmed_payment"]["link_id"] == "link-1"
    assert flow["emails"]["invoice_customer"]["status"] == "sent"
    assert base64.b64decode(shop["mails"][-1][1]["attachments"][0]["content"]).startswith(b"%PDF")
    invoice_mail, invoice_meta = shop["mails"][-1]
    assert "facture acquittée F-2026-123" in invoice_mail[1]
    for content in (invoice_mail[2], invoice_meta["text_content"]):
        assert "Nous avons bien reçu votre paiement." in content
        assert "facture acquittée F-2026-123" in content
        assert "Montant réglé" in content
        assert "Montant à régler" not in content and "Payer " not in content
        assert "facture sera créée" not in content
    for path in ("/admin/organisme", "/admin/manuels", f"/admin/manuels/commandes/{order['id']}"):
        page = shop["client"].get(path)
        assert "https://pay.qonto.com/invoices/invoice-1" in page.text
        assert "Régler en ligne" not in page.text
    retry(order)
    assert len(shop["mails"]) == 5
    assert sum(m == "POST" and p == "/v2/client_invoices" for m,p,*_ in merchant["calls"]) == 1
    assert sum(m == "POST" and p == "/v2/payment_links" for m,p,*_ in merchant["calls"]) == 1
    assert sum(p.endswith("/mark_as_paid") for m,p,*_ in merchant["calls"]) == 1


def test_emails_survive_qonto_configuration_failure(shop, monkeypatch):
    order = submitted(shop)
    monkeypatch.setattr(host, "_qonto_is_configured", lambda: False)
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "needs_setup" and not flow["queued"]
    assert flow["emails"]["confirmation_customer"]["status"] == "sent"
    assert flow["emails"]["notification_admin"]["status"] == "sent"
    retry(order)
    assert len(shop["mails"]) == 3


def test_failed_customer_email_retries_without_admin_duplicate(shop, merchant, monkeypatch):
    order = submitted(shop)
    original = host.brevo_send_email
    def fail_customer(*args, **kwargs):
        if kwargs["metadata"]["purpose"] == "manuals_confirmation_customer":
            # Checkout is ready before a slow or failing delivery can block it.
            flow = all_data(shop)["manual_orders"][0]["commerce"]
            assert flow["status"] == "waiting_payment" and flow["payment_url"]
            assert merchant["invoice"] is None
            return {"ok": False}
        return original(*args, **kwargs)
    monkeypatch.setattr(host, "brevo_send_email", fail_customer)
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "waiting_payment" and flow["queued"]
    assert shop["client"].get(f"/admin/manuels/commandes/{order['id']}/paiement/statut").json["payment_url"]
    monkeypatch.setattr(host, "brevo_send_email", original)
    retry(order)
    assert [m[0][0] for m in shop["mails"]].count(commerce.ADMIN_EMAIL) == 1
    assert all_data(shop)["manual_orders"][0]["commerce"]["emails"]["confirmation_customer"]["status"] == "sent"


def test_invoice_is_recovered_after_lost_response(shop, merchant):
    order = submitted(shop)
    merchant["paid"] = True
    merchant["unknown_invoice"] = True
    run(order)
    retry(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "ready", flow
    assert sum(m == "POST" and p == "/v2/client_invoices" for m,p,*_ in merchant["calls"]) == 1



def test_unknown_invoice_never_recreated_after_restart(shop, merchant):
    order = submitted(shop)
    merchant["paid"] = True
    merchant["unknown_invoice"] = True
    run(order)
    merchant["invoice"] = None
    retry(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["status"] == "needs_review"
    assert sum(m == "POST" and p == "/v2/client_invoices" for m,p,*_ in merchant["calls"]) == 1



def test_wrong_invoice_total_stays_draft(shop, merchant):
    order = submitted(shop)
    merchant["paid"] = True
    merchant["wrong_total"] = True
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "needs_review"
    assert merchant["invoice"]["status"] == "draft"
    assert not any("finalize" in call[1] for call in merchant["calls"])
    assert merchant["payment"] is not None
    assert "invoice_customer" not in flow["emails"]
    assert not merchant["pdf_downloads"]



def test_pending_activation_keeps_order_without_invoice_then_sends_payment_link(shop, merchant, monkeypatch):
    order = submitted(shop)
    merchant["payment_pending"] = True
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "payment_pending" and flow["queued"] and flow["attempts"] == 0
    assert "invoice_customer" not in flow["emails"] and not flow.get("invoice_id")
    assert not flow.get("payment_url") and len(shop["mails"]) == 3
    for path in ("/admin/organisme", "/admin/manuels", f"/admin/manuels/commandes/{order['id']}"):
        page = shop["client"].get(path)
        assert "pay.qonto.com/invoices/" not in page.text and "Régler en ligne" not in page.text
    calls_before = len(merchant["calls"])
    run(order)
    assert len(merchant["calls"]) == calls_before
    monkeypatch.setattr(commerce.time, "time", lambda: flow["next_attempt"] + 1)
    merchant["payment_pending"] = False
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "waiting_payment" and flow["emails"]["payment_customer"]["status"] == "sent"
    assert "Votre commande est à régler" in shop["mails"][-1][0][2]
    assert merchant["invoice"] is None and not merchant["pdf_downloads"]
    retry(order)
    assert len(shop["mails"]) == 4


def test_pdf_generation_failure_retries_email_without_duplicate_invoice(shop, merchant, monkeypatch):
    order = submitted(shop)
    run(order)
    merchant.update(paid=True, pdf_unavailable=True)
    retry(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["payment_status"] == "paid" and flow["invoice_status"] == "paid"
    assert flow["emails"]["invoice_customer"]["status"] == "failed" and flow["queued"]
    assert len(shop["mails"]) == 4
    assert "https://pay.qonto.com/invoices/invoice-1" in shop["client"].get("/admin/organisme").text
    next_attempt = flow["next_attempt"]
    monkeypatch.setattr(commerce.time, "time", lambda: next_attempt + 1)
    merchant["pdf_unavailable"] = False
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["emails"]["invoice_customer"]["status"] == "sent" and len(shop["mails"]) == 5
    assert sum(m == "POST" and p == "/v2/client_invoices" for m,p,*_ in merchant["calls"]) == 1


def test_payment_setup_recovers_without_creating_an_unpaid_invoice(shop, merchant):
    order = submitted(shop)
    merchant["payment_disabled"] = True
    run(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["status"] == "needs_setup"
    assert merchant["invoice"] is None
    merchant["payment_disabled"] = False
    retry(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["status"] == "waiting_payment"
    assert merchant["invoice"] is None


def test_paid_status_comes_only_from_qonto(shop, merchant):
    order = submitted(shop)
    run(order)
    c = shop["client"]
    detail = f"/admin/manuels/commandes/{order['id']}"
    c.get(detail + "?paid=1&status=paid")
    assert all_data(shop)["manual_orders"][0]["commerce"]["payment_status"] == "unpaid"
    merchant["payment"]["status"] = "paid"
    retry(order)
    assert merchant["invoice"] is None  # Link status alone is not a captured payment.
    assert all_data(shop)["manual_orders"][0]["commerce"]["payment_status"] == "processing"
    merchant["paid"] = True
    retry(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["payment_status"] == "paid" and flow["queued"] is False
    assert "Régler en ligne" not in c.get(detail).text


def test_partial_payment_disables_full_amount_link_and_does_not_invoice(shop, merchant):
    order = submitted(shop)
    run(order)
    merchant["payments"] = [{"id": "partial-1", "status": "paid", "amount": {"value": "100.00", "currency": "EUR"}, "paid_at": "2026-01-01T10:00:00Z"}]
    retry(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "needs_review" and not flow["payment_url"]
    assert merchant["invoice"] is None
    assert "Régler en ligne" not in shop["client"].get(f"/admin/manuels/commandes/{order['id']}").text


def test_parallel_workers_claim_once(shop, merchant):
    order = submitted(shop)
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: run(order), range(2)))
    assert merchant["invoice"] is None
    assert sum(m == "POST" and p == "/v2/payment_links" for m,p,*_ in merchant["calls"]) == 1
    merchant["paid"] = True
    commerce.queue_again(host, order["partner_id"], order["id"])
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: run(order), range(2)))
    assert sum(m == "POST" and p == "/v2/client_invoices" for m,p,*_ in merchant["calls"]) == 1
    assert [m[0][0] for m in shop["mails"]].count(commerce.ADMIN_EMAIL) == 1


def test_commerce_settings_and_order_retry_are_admin_only(shop, merchant):
    order = submitted(shop)
    c = shop["client"]
    assert c.get("/admin/commandes-manuels/reglages").status_code == 302
    assert c.post("/admin/commandes-manuels/reglages", data={}).status_code == 403
    with host.app.test_request_context():
        with pytest.raises(RuntimeError, match="outside customer"):
            commerce.process_order(host, order["partner_id"], order["id"])
    admin = host.app.test_client()
    admin.post("/admin/login", data={"username": "admin@example.test", "password": "platform-test-pass"})
    url = "/admin/commandes-manuels/reglages"
    token = csrf(admin, url)
    assert admin.post(url, data={"csrf_token": token, "manual_vat": "0", "usb_vat": "20"}).status_code == 400
    assert admin.post(url, data={"csrf_token": token, "manual_vat": "5.5", "usb_vat": "20"}).status_code == 303
    detail = f"/admin/commandes-manuels/{order['partner_id']}/{order['id']}"
    assert admin.post(detail, data={"csrf_token": csrf(admin, detail), "action": "retry"}).status_code == 303


def test_other_organism_cannot_refresh_or_see_invoice(shop, merchant):
    order = submitted(shop)
    run(order)
    other = host.app.test_client()
    signup(other, email="other@example.test")
    login(other, email="other@example.test")
    detail = f"/admin/manuels/commandes/{order['id']}"
    assert other.get(detail).status_code == 404
    assert other.post(detail + "/actualiser", data={"csrf_token": csrf(other, "/admin/manuels")}).status_code == 404
    assert "invoice-1" not in other.get("/admin/organisme").text
    assert "invoice-1" not in other.get("/admin/manuels").text


@pytest.mark.parametrize("value", ["javascript:alert(1)", "https://pay.qonto.com.evil.test/x", "https://evil.test/x", "//pay.qonto.com/x", "https://user:pass@pay.qonto.com/x"])
def test_untrusted_payment_links_rejected(value):
    assert commerce.safe_payment_url(value) == ""


def test_payment_oauth_is_bound_to_this_service_and_state(shop, monkeypatch):
    from urllib.parse import urlparse, parse_qs
    monkeypatch.setattr(host, '_qonto_oauth_is_configured', lambda: True)
    monkeypatch.setattr(host, '_qonto_oauth_client_id', lambda: 'test-client')
    monkeypatch.setattr(host, '_qonto_oauth_client_secret', lambda: 'test-secret')
    exchange=[]
    monkeypatch.setattr(host, '_exchange_qonto_oauth_token', lambda payload: exchange.append(payload) or {'access_token':'dummy-access','refresh_token':'dummy-refresh','expires_in':3600,'scope':host.QONTO_OAUTH_SCOPE+' payment_link.read payment_link.write'})
    admin=host.app.test_client()
    admin.post('/admin/login', data={'username':'admin@example.test','password':'platform-test-pass'})
    connect='/admin/commandes-manuels/connexion-paiement'
    callback='/api/commerce/connexion-paiement/retour'
    response=admin.get(connect)
    params=parse_qs(urlparse(response.location).query)
    assert params['redirect_uri']==['https://gestionstagiaires-test-v2.onrender.com'+callback]
    assert 'payment_link.write' in params['scope'][0]
    assert admin.get(callback+'?state=forged&code=no').status_code==400
    assert not exchange
    params=parse_qs(urlparse(admin.get(connect).location).query)
    assert admin.get(callback+'?state='+params['state'][0]+'&code=local-code').status_code==302
    assert len(exchange)==1
    assert exchange[0]['redirect_uri']==params['redirect_uri'][0]
    assert admin.get(callback+'?state='+params['state'][0]+'&code=local-code').status_code==400
    data=json.loads(Path(host.DATA_FILE).read_text())
    assert data['qonto_oauth']['refresh_token']=='dummy-refresh'
    assert all(not p.get('qonto_oauth') for p in all_data(shop)['partners'])


def test_missing_tax_does_not_emit_invoice(shop, merchant):
    order=submitted(shop)
    def clear(data):
        data.pop('manuals_commerce_settings',None)
        return {}
    host._atomic_update_data(clear)
    run(order)
    assert all_data(shop)['manual_orders'][0]['commerce']['status']=='needs_setup'
    assert not merchant['calls']
    assert len(shop['mails'])==3


def test_oauth_cannot_collect_payment_for_another_merchant(shop, merchant, monkeypatch):
    order = submitted(shop)
    original = host._qonto_request
    def different_merchant(method, path, payload=None, params=None, **kwargs):
        result = original(method, path, payload, params, **kwargs)
        if path == "/v2/payment_links/connections":
            result["bank_account_id"] = "another-merchant-account"
        return result
    monkeypatch.setattr(host, "_qonto_request", different_merchant)
    run(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["status"] == "needs_review"
    assert merchant["payment"] is None and merchant["invoice"] is None


def test_login_preserves_owned_order_link(shop):
    order=submitted(shop)
    client=shop['client']
    client.get('/admin/logout')
    path='/admin/manuels/commandes/'+order['id']
    response=client.post('/admin/login',data={'username':'centre@example.test','password':'Une phrase robuste 2026!','next':path})
    assert response.location==path


def test_missing_payment_scope_does_not_invoice_and_resumes_without_duplicate(shop, merchant, monkeypatch):
    order = submitted(shop)
    monkeypatch.setattr(host, "_qonto_oauth_has_scope", lambda scope, *a: scope != "payment_link.write")
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "needs_setup" and not flow.get("invoice_id")
    assert "Autorisez les liens de paiement" in flow["error"]
    assert "invoice_customer" not in flow["emails"] and not merchant["calls"]
    customer_page = shop["client"].get(f"/admin/manuels/commandes/{order['id']}").text
    assert "Consulter ma facture" not in customer_page and "Régler en ligne" not in customer_page
    assert "Terminer la configuration" not in customer_page
    monkeypatch.setattr(host, "_qonto_oauth_has_scope", lambda *a: True)
    retry(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["status"] == "waiting_payment"
    assert merchant["invoice"] is None


@pytest.mark.parametrize("top_currency,nested_currency", [(None, "USD"), ("EUR", "USD"), ("USD", "EUR"), (None, None)])
def test_invalid_or_conflicting_invoice_currency_blocks_finalization(shop, merchant, monkeypatch, top_currency, nested_currency):
    order = submitted(shop)
    merchant["paid"] = True
    original = host._qonto_request
    def request(method, path, *args, **kwargs):
        result = original(method, path, *args, **kwargs)
        if method == "POST" and path == "/v2/client_invoices":
            result["client_invoice"]["currency"] = top_currency
            result["client_invoice"]["total_amount"]["currency"] = nested_currency
        return result
    monkeypatch.setattr(host, "_qonto_request", request)
    run(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["status"] == "needs_review"
    assert not any(p.endswith("/finalize") for m, p, *_ in merchant["calls"])



def test_staff_order_link_keeps_order_and_shows_both_setup_blockers(shop, merchant, monkeypatch):
    order = submitted(shop)
    host._atomic_update_data(lambda data: data.pop("manuals_commerce_settings", None) and {})
    monkeypatch.setattr(host, "_qonto_oauth_has_scope", lambda *a: False)
    run(order)
    admin = host.app.test_client()
    admin.post("/admin/login", data={"username": "admin@example.test", "password": "platform-test-pass"})
    original_path = f"/admin/manuels/commandes/{order['id']}"
    response = admin.get(original_path)
    assert response.location == f"/admin/commandes-manuels/{order['partner_id']}/{order['id']}"
    page = admin.get(response.location).text
    assert "À renseigner : manuels imprimés, supports PowerPoint sur clé USB" in page
    assert "Autorisation Qonto manquante" in page
    assert "Terminer la configuration" in page
    assert "Facture et paiement : activation à terminer" in admin.get("/admin/commandes-manuels").text
    assert admin.get("/admin/manuels/commandes/unknown").status_code == 404


def test_canceled_legacy_invoice_is_not_emailed_or_recreated(shop, merchant):
    order = legacy_order(shop, merchant, "canceled")
    run(order)
    retry(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["invoice_status"] == "canceled" and not flow["queued"]
    assert "invoice_customer" not in flow["emails"] and "payment_customer" not in flow["emails"]
    assert not merchant["pdf_downloads"] and merchant["payment"] is None
    assert not any(m == "POST" and p == "/v2/client_invoices" for m,p,*_ in merchant["calls"])
    admin = host.app.test_client()
    admin.post("/admin/login", data={"username": "admin@example.test", "password": "platform-test-pass"})
    page = admin.get(f"/admin/commandes-manuels/{order['partner_id']}/{order['id']}")
    assert "Non envoyé : facture annulée" in page.text
    assert "Facture annulée" in shop["client"].get("/admin/organisme").text
    assert "pay.qonto.com" not in page.text and "pay.qonto.com" not in shop["client"].get("/admin/organisme").text


def legacy_order(shop, merchant, status="unpaid"):
    order = submitted(shop)
    merchant["invoice"] = {"id": "invoice-1", "organization_id": "merchant-1", "purchase_order": order["id"], "client": {"id": "client-centre"}, "status": status, "number": "F-2026-123", "total_amount_cents": order["total_cents"], "total_amount": {"value": f"{Decimal(order['total_cents'])/100:.2f}", "currency": "EUR"}, "invoice_url": "https://pay.qonto.com/invoices/invoice-1"}
    def update(data):
        current = data["manual_orders"][0]
        current["commerce"].update(flow="legacy", invoice_id="invoice-1", client_id="client-centre")
        return {}
    host._atomic_update_data(update, partner_id=order["partner_id"])
    return order


@pytest.mark.parametrize("status", ["open", "pending", "authorized", "failed", "canceled", "expired"])
def test_unsettled_payments_never_create_or_send_invoice(shop, merchant, status):
    order = submitted(shop)
    run(order)
    merchant["payments"] = [{"id": "attempt-1", "status": status, "amount": merchant["payment"]["amount"], "paid_at": None}]
    retry(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "waiting_payment" and flow["queued"]
    assert merchant["invoice"] is None and not flow.get("invoice_id")
    assert "invoice_customer" not in flow["emails"] and not merchant["pdf_downloads"]
    assert not any(p.startswith("/v2/client_invoices") for _, p, *_ in merchant["calls"])


def test_checkout_is_recovered_after_lost_response_without_second_charge_link(shop, merchant):
    order = submitted(shop)
    merchant["unknown_payment"] = True
    run(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["status"] == "retry"
    retry(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "waiting_payment" and flow["payment_id"] == "link-1"
    assert sum(m == "POST" and p == "/v2/payment_links" for m,p,*_ in merchant["calls"]) == 1
    assert merchant["invoice"] is None


def test_unknown_checkout_never_recreated_after_restart(shop, merchant):
    order = submitted(shop)
    merchant["unknown_payment"] = True
    run(order)
    merchant["payment"] = None
    retry(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["status"] == "needs_review"
    assert sum(m == "POST" and p == "/v2/payment_links" for m,p,*_ in merchant["calls"]) == 1
    assert merchant["invoice"] is None


@pytest.mark.parametrize("field,value", [("currency", "USD"), ("value", "NaN"), ("value", "2599.001"), ("value", "9999.00")])
def test_invalid_settlement_amount_blocks_invoice(shop, merchant, field, value):
    order = submitted(shop)
    run(order)
    amount = dict(merchant["payment"]["amount"], **{field: value})
    merchant["payments"] = [{"id": "capture-1", "status": "paid", "amount": amount, "paid_at": "2026-01-01T10:00:00Z"}]
    retry(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "needs_review" and not flow.get("confirmed_payment")
    assert merchant["invoice"] is None


@pytest.mark.parametrize("mutation", ["id", "items", "reusable", "merchant"])
def test_checkout_identity_must_remain_bound_to_order(shop, merchant, mutation):
    order = submitted(shop)
    run(order)
    merchant["paid"] = True
    if mutation == "id":
        merchant["payment"]["id"] = "another-link"
    elif mutation == "items":
        merchant["payment"]["items"][0]["description"] = "Another order"
    elif mutation == "reusable":
        merchant["payment"]["reusable"] = True
    else:
        def change(data):
            data["manual_orders"][0]["commerce"]["merchant_id"] = "original-merchant"
            return {}
        host._atomic_update_data(change, partner_id=order["partner_id"])
    retry(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["status"] == "needs_review"
    assert merchant["invoice"] is None


def test_zero_vat_keeps_exact_prices_and_invoice_follows_payment_date(shop, merchant):
    settings = {"manual_vat": "0", "manual_exemption": "S293B", "usb_vat": "0", "usb_exemption": "S293B"}
    host._atomic_update_data(lambda data: data.update(manuals_commerce_settings=settings) or {})
    order = submitted(shop)
    run(order)
    assert merchant["invoice"] is None
    for expected, item in zip(order["items"], merchant["payment"]["items"]):
        assert item["quantity"] == expected["quantity"]
        assert item["vat_rate"] == "0"
        assert item["unit_price"]["value"] == f"{Decimal(expected['unit_cents'])/100:.2f}"
    assert host.cleanQontoPayload({"payment_link": {"reusable": False}})["payment_link"]["reusable"] is False
    merchant["paid"] = True
    retry(order)
    assert all(i["vat_rate"] == "0" and i["vat_exemption_reason"] == "S293B" for i in merchant["invoice"]["items"])
    assert merchant["invoice"]["issue_date"] == commerce.dt.datetime.now(commerce.ZoneInfo("Europe/Paris")).date().isoformat()
    assert merchant["invoice"]["paid_at"] == "2026-01-01"


def test_existing_unpaid_invoice_is_reused_but_only_sent_after_payment(shop, merchant):
    order = legacy_order(shop, merchant)
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["invoice_status"] == "unpaid" and flow["payment_url"]
    assert "invoice_customer" not in flow["emails"]
    merchant["invoice"]["status"] = "paid"
    retry(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["emails"]["invoice_customer"]["status"] == "sent"
    assert not any(m == "POST" and p == "/v2/client_invoices" for m,p,*_ in merchant["calls"])


def test_customer_can_request_payment_refresh_before_invoice_exists(shop, merchant):
    order = submitted(shop)
    run(order)
    detail = f"/admin/manuels/commandes/{order['id']}"
    page = shop["client"].get(detail)
    assert "Actualiser le paiement" in page.text
    response = shop["client"].post(detail + "/actualiser", data={"csrf_token": csrf(shop["client"], detail)})
    assert response.status_code == 303
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["queued"] and flow["next_attempt"] == 0 and not flow.get("invoice_id")


def test_automatic_checkout_reads_only_owned_verified_payment(shop, merchant):
    order = submitted(shop)
    client = shop['client']
    detail = f"/admin/manuels/commandes/{order['id']}"
    checkout = detail + '/paiement'
    status = checkout + '/statut'
    assert client.get(status).json == {'payment_url': '', 'waiting': True}
    assert not merchant['calls']
    run(order)
    before = list(merchant['calls'])
    response = client.get(status)
    assert response.json == {'payment_url': 'https://pay.qonto.com/link-1', 'waiting': False}
    assert response.cache_control.no_store
    assert 'data-checkout-url="https://pay.qonto.com/link-1"' in client.get(checkout).text
    assert 'data-checkout' not in client.get(detail).text  # Back never reopens payment.
    for path in (detail, '/admin/organisme', '/admin/manuels'):
        links = re.findall(r'<a\b[^>]*href="https://pay.qonto.com/link-1"[^>]*>', client.get(path).text)
        assert links and all('target="_blank"' not in link for link in links)
    assert merchant['calls'] == before  # Browsing/polling cannot call the merchant API.
    assert merchant['invoice'] is None
    anonymous = host.app.test_client()
    assert anonymous.get(status).status_code == 302
    assert 'pay.qonto.com' not in anonymous.get(status).text


def test_automatic_checkout_stops_for_paid_cancelled_unavailable_or_unsafe_link(shop, merchant):
    order = submitted(shop)
    run(order)
    original = all_data(shop)['manual_orders'][0]
    detail = f"/admin/manuels/commandes/{order['id']}"
    checkout = detail + '/paiement'
    cases = [
        {'status': 'draft'}, {'status': 'cancelled'},
        {'commerce': {'payment_status': 'paid'}},
        {'commerce': {'payment_status': 'processing'}},
        {'commerce': {'invoice_status': 'canceled'}},
        {'commerce': {'payment_link_status': 'expired'}},
        {'commerce': {'status': 'needs_review'}},
        {'commerce': {'status': 'needs_setup'}},
        {'commerce': {'payment_url': 'https://pay.qonto.com.evil.test/checkout'}},
    ]
    for changes in cases:
        def update(data):
            current = next(o for o in data['manual_orders'] if o['id'] == order['id'])
            current.clear()
            current.update(copy.deepcopy(original))
            current.update({k: v for k, v in changes.items() if k != 'commerce'})
            current['commerce'].update(changes.get('commerce', {}))
            return {}
        host._atomic_update_data(update, partner_id=order['partner_id'])
        assert shop['client'].get(checkout + '/statut?paid=true&payment_url=https://evil.test').json == {'payment_url': '', 'waiting': False}
        response = shop['client'].get(checkout)
        assert response.status_code == 303 and response.location == detail
    assert merchant['invoice'] is None


