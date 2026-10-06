import base64
import copy
import json
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
    state = {"calls": [], "invoice": None, "payment": None, "unknown_invoice": False, "wrong_total": False, "payment_disabled": False, "payment_pending": False, "pdf_downloads": [], "pdf_unavailable": False}
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
        if path == "/v2/client_invoices/invoice-1":
            return {"client_invoice": copy.deepcopy(state["invoice"])}
        if path == "/v2/payment_links/payment_methods":
            if state["payment_disabled"]:
                raise host.QontoConfigurationError("Liens de paiement à activer")
            if state["payment_pending"]:
                return {"payment_link_payment_methods": []}
            return {"payment_link_payment_methods": [{"name": "credit_card", "enabled": True}, {"name": "paypal", "enabled": False}]}
        if path == "/v2/payment_links/connections":
            return {"status": "pending" if state["payment_pending"] else "enabled"}
        if path == "/v2/payment_links" and method == "POST":
            state["payment"] = {**payload["payment_link"], "id": "link-1", "url": "https://pay.qonto.com/link-1", "status": "open"}
            return {"payment_link": copy.deepcopy(state["payment"])}
        if path == "/v2/payment_links" and method == "GET":
            return {"payment_links": [copy.deepcopy(state["payment"])] if state["payment"] else [], "meta": {"total_pages": 1}}
        if path == "/v2/payment_links/link-1":
            return {"payment_link": copy.deepcopy(state["payment"])}
        raise AssertionError((method, path))
    monkeypatch.setattr(host, "_qonto_request", request)
    return state


def test_portal_and_upcoming_have_no_purchase_actions(shop):
    signup(shop["client"])
    login(shop["client"])
    for path in ("/admin/organisme", "/admin/organisme/e-learning"):
        page = shop["client"].get(path)
        assert page.status_code == 200
        assert "Prochainement" in page.text
    page = shop["client"].get("/admin/organisme/e-learning")
    assert "59 €" in page.text and "89 €" in page.text and "157 h 30" in page.text
    assert '<form' not in page.text and 'type="submit"' not in page.text
    assert shop["client"].post("/admin/organisme/e-learning").status_code in {403, 405}


def test_order_emails_invoice_payment_and_no_duplicates(shop, merchant):
    order = submitted(shop, billing_different="yes", billing_address="2 rue Facturation", billing_postal_code="69001", billing_city="Lyon")
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "ready", flow
    assert flow["invoice_id"] == "invoice-1" and flow["payment_url"] == "https://pay.qonto.com/link-1"
    assert merchant["client"]["billing_address"]["city"] == "Lyon"
    assert merchant["payment"]["amount"] == {"value": "2599.00", "currency": "EUR"}
    assert merchant["payment"]["potential_payment_methods"] == ["credit_card"]
    for key in ("confirmation_customer", "notification_admin", "invoice_customer"):
        assert flow["emails"][key]["status"] == "sent"
    assert [m[0][0] for m in shop["mails"]] == ["centre@example.test", "centre@example.test", commerce.ADMIN_EMAIL, "centre@example.test"]
    assert "Régler ma commande" in shop["mails"][-1][0][2]
    assert flow["emails"]["invoice_customer"]["payment_link_included"] is True
    assert base64.b64decode(shop["mails"][-1][1]["attachments"][0]["content"]).startswith(b"%PDF")
    assert "https://pay.qonto.com/invoices/invoice-1" in shop["mails"][-1][1]["text_content"]
    retry(order)
    assert len(shop["mails"]) == 4
    assert sum(m == "POST" and p == "/v2/client_invoices" for m,p,*_ in merchant["calls"]) == 1
    assert sum(m == "POST" and p == "/v2/payment_links" for m,p,*_ in merchant["calls"]) == 1
    assert "Régler en ligne" in shop["client"].get(f"/admin/manuels/commandes/{order['id']}").text


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
            return {"ok": False}
        return original(*args, **kwargs)
    monkeypatch.setattr(host, "brevo_send_email", fail_customer)
    run(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["status"] == "retry"
    monkeypatch.setattr(host, "brevo_send_email", original)
    retry(order)
    assert [m[0][0] for m in shop["mails"]].count(commerce.ADMIN_EMAIL) == 1
    assert all_data(shop)["manual_orders"][0]["commerce"]["emails"]["confirmation_customer"]["status"] == "sent"


def test_invoice_is_recovered_after_lost_response(shop, merchant):
    order = submitted(shop)
    merchant["unknown_invoice"] = True
    run(order)
    retry(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "ready", flow
    assert sum(m == "POST" and p == "/v2/client_invoices" for m,p,*_ in merchant["calls"]) == 1


def test_unknown_invoice_never_recreated_after_restart(shop, merchant):
    order = submitted(shop)
    merchant["unknown_invoice"] = True
    run(order)
    merchant["invoice"] = None
    retry(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["status"] == "needs_review"
    assert sum(m == "POST" and p == "/v2/client_invoices" for m,p,*_ in merchant["calls"]) == 1


def test_wrong_invoice_total_stays_draft(shop, merchant):
    order = submitted(shop)
    merchant["wrong_total"] = True
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "needs_review"
    assert merchant["invoice"]["status"] == "draft"
    assert not any("finalize" in call[1] for call in merchant["calls"])
    assert merchant["payment"] is None
    assert "invoice_customer" not in flow["emails"]
    assert not merchant["pdf_downloads"]


def test_pending_payment_sends_pdf_and_shows_invoice_then_notifies_once(shop, merchant, monkeypatch):
    order = submitted(shop)
    merchant["payment_pending"] = True
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "payment_pending" and flow["queued"]
    assert flow["attempts"] == 0
    assert flow["emails"]["invoice_customer"]["status"] == "sent"
    assert flow["emails"]["invoice_customer"]["payment_link_included"] is False
    assert flow["emails"]["invoice_customer"]["attachment_name"] == "F-2026-123.pdf"
    assert not flow.get("payment_url")
    assert len(shop["mails"]) == 4
    html = shop["mails"][-1][0][2]
    assert "pièce jointe" in html and "en cours d’activation" in html
    assert "Régler ma commande" not in html
    for path in ("/admin/organisme", "/admin/manuels", f"/admin/manuels/commandes/{order['id']}"):
        page = shop["client"].get(path)
        assert page.status_code == 200
        assert "https://pay.qonto.com/invoices/invoice-1" in page.text
        assert "Régler en ligne" not in page.text
    calls_before = len(merchant["calls"])
    run(order)
    assert len(merchant["calls"]) == calls_before  # No polling before the due time.
    monkeypatch.setattr(commerce.time, "time", lambda: flow["next_attempt"] + 1)
    merchant["payment_pending"] = False
    run(order)  # The durable queue resumes automatically, without an admin retry.
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "ready"
    assert flow["emails"]["payment_customer"]["status"] == "sent"
    assert len(shop["mails"]) == 5
    assert "Le paiement en ligne est disponible" in shop["mails"][-1][0][1]
    assert "Régler ma commande" in shop["mails"][-1][0][2]
    assert not shop["mails"][-1][1]["attachments"]
    assert "Régler en ligne" in shop["client"].get("/admin/organisme").text
    assert merchant["pdf_downloads"] == ["invoice-1"]
    retry(order)
    assert len(shop["mails"]) == 5
    assert sum(m == "POST" and p == "/v2/client_invoices" for m, p, *_ in merchant["calls"]) == 1


def test_pdf_generation_failure_retries_email_without_duplicate_invoice(shop, merchant, monkeypatch):
    order = submitted(shop)
    merchant.update(payment_pending=True, pdf_unavailable=True)
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["emails"]["invoice_customer"]["status"] == "failed" and flow["queued"]
    assert len(shop["mails"]) == 3
    assert "https://pay.qonto.com/invoices/invoice-1" in shop["client"].get("/admin/organisme").text
    monkeypatch.setattr(commerce.time, "time", lambda: flow["next_attempt"] + 1)
    merchant["pdf_unavailable"] = False
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["emails"]["invoice_customer"]["status"] == "sent"
    assert len(shop["mails"]) == 4
    assert sum(m == "POST" and p == "/v2/client_invoices" for m, p, *_ in merchant["calls"]) == 1


def test_payment_setup_recovers_existing_invoice(shop, merchant):
    order = submitted(shop)
    merchant["payment_disabled"] = True
    run(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["status"] == "needs_setup"
    merchant["payment_disabled"] = False
    retry(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["status"] == "ready"
    assert sum(m == "POST" and p == "/v2/client_invoices" for m,p,*_ in merchant["calls"]) == 1


def test_paid_status_comes_only_from_qonto(shop, merchant):
    order = submitted(shop)
    run(order)
    c = shop["client"]
    detail = f"/admin/manuels/commandes/{order['id']}"
    c.get(detail + "?paid=1&status=paid")
    assert all_data(shop)["manual_orders"][0]["commerce"]["payment_status"] == "unpaid"
    merchant["invoice"]["status"] = "paid"
    retry(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["payment_status"] == "paid" and flow["queued"] is False
    assert "Régler en ligne" not in c.get(detail).text


def test_partial_payment_disables_full_amount_link(shop, merchant):
    order = submitted(shop)
    run(order)
    merchant["invoice"]["amount_paid_cents"] = 10000
    retry(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["payment_status"] == "partially_paid" and not flow["payment_url"]
    assert "Régler en ligne" not in shop["client"].get(f"/admin/manuels/commandes/{order['id']}").text


def test_parallel_workers_claim_once(shop, merchant):
    order = submitted(shop)
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


def test_oauth_cannot_pay_invoice_from_another_merchant(shop, merchant, monkeypatch):
    order=submitted(shop)
    original=host._qonto_request
    def different_merchant(method,path,payload=None,params=None,**kwargs):
        result=original(method,path,payload,params,**kwargs)
        if kwargs.get('use_oauth'):
            result['client_invoice']['organization_id']='another-merchant'
        return result
    monkeypatch.setattr(host,'_qonto_request',different_merchant)
    run(order)
    assert all_data(shop)['manual_orders'][0]['commerce']['status']=='needs_review'
    assert merchant['payment'] is None


def test_login_preserves_owned_order_link(shop):
    order=submitted(shop)
    client=shop['client']
    client.get('/admin/logout')
    path='/admin/manuels/commandes/'+order['id']
    response=client.post('/admin/login',data={'username':'centre@example.test','password':'Une phrase robuste 2026!','next':path})
    assert response.location==path


def test_missing_payment_scope_keeps_invoice_and_resumes_without_duplicate(shop, merchant, monkeypatch):
    order = submitted(shop)
    monkeypatch.setattr(host, "_qonto_oauth_has_scope", lambda scope, *a: scope != "payment_link.write")
    run(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["status"] == "needs_setup" and flow["invoice_status"] == "unpaid"
    assert "Autorisez les liens de paiement" in flow["error"]
    assert flow["emails"]["invoice_customer"]["status"] == "sent"
    assert not any(p.startswith("/v2/payment_links") or kw.get("use_oauth") for m, p, body, params, kw in merchant["calls"])
    customer_page = shop["client"].get(f"/admin/manuels/commandes/{order['id']}").text
    assert "Consulter ma facture" in customer_page
    assert "Régler en ligne" not in customer_page
    assert "Terminer la configuration" not in customer_page
    monkeypatch.setattr(host, "_qonto_oauth_has_scope", lambda *a: True)
    retry(order)
    assert all_data(shop)["manual_orders"][0]["commerce"]["status"] == "ready"
    assert sum(m == "POST" and p == "/v2/client_invoices" for m, p, *_ in merchant["calls"]) == 1


@pytest.mark.parametrize("top_currency,nested_currency", [(None, "USD"), ("EUR", "USD"), ("USD", "EUR"), (None, None)])
def test_invalid_or_conflicting_invoice_currency_blocks_finalization(shop, merchant, monkeypatch, top_currency, nested_currency):
    order = submitted(shop)
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


def test_canceled_invoice_is_not_emailed_or_recreated(shop, merchant):
    order = submitted(shop)
    merchant["invoice_status_after_finalize"] = "canceled"
    run(order)
    retry(order)
    flow = all_data(shop)["manual_orders"][0]["commerce"]
    assert flow["invoice_status"] == "canceled" and not flow["queued"]
    assert "invoice_customer" not in flow["emails"]
    assert "payment_customer" not in flow["emails"]
    assert not merchant["pdf_downloads"] and merchant["payment"] is None
    assert len(shop["mails"]) == 3
    assert sum(m == "POST" and p == "/v2/client_invoices" for m, p, *_ in merchant["calls"]) == 1
    admin = host.app.test_client()
    admin.post("/admin/login", data={"username": "admin@example.test", "password": "platform-test-pass"})
    page = admin.get(f"/admin/commandes-manuels/{order['partner_id']}/{order['id']}")
    assert "Non envoyé : facture annulée" in page.text
    assert "Facture annulée" in shop["client"].get("/admin/organisme").text
    assert "pay.qonto.com" not in page.text
    assert "pay.qonto.com" not in shop["client"].get("/admin/organisme").text
