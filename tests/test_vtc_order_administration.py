from io import BytesIO
from jinja2 import ChoiceLoader, DictLoader
from lxml import html
from pypdf import PdfReader

import exam_retakes
import vtc_order_agreements as agreements
import vtc_public_orders as orders
from test_exam_retakes import host
from test_vtc_public_orders import begin, basket_providers, creations, cycle


def admin_order(host, offer):
    client, store, oid, public, csrf = begin(host, offer)
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role="admin")
    host.app.jinja_loader = ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}), host.app.jinja_loader,
    ])
    return client, store, "/admin/commandes-vtc/" + oid, public, csrf


def post(client, url, csrf, action, **values):
    result = client.post(url, data=dict(csrf_token=csrf, action=action, **values))
    assert result.status_code == 303 and result.location == url


def pdf_text(response):
    assert response.mimetype == "application/pdf"
    return " ".join(page.extract_text() for page in PdfReader(BytesIO(response.data)).pages)


SLOT = dict(day="2026-12-07", start="09:00", end="12:30", trainer="Marie Exemple, formatrice VTC")


def test_vehicle_agreement_is_independent_of_checkout(host):
    client, store, dossier, public, csrf = admin_order(host, "vehicule")
    oid = dossier.rsplit("/", 1)[1]
    row = store.get(oid)
    signature, _ = basket_providers(host, store, row)
    post(client, dossier, csrf, "generate")
    draft = store.get(oid)
    assert draft["stage"] == "billing" and not host._yousign_json.called
    preview = client.get(dossier + "/convention.pdf?apercu=1")
    assert preview.headers["Content-Disposition"].startswith("inline")
    text = pdf_text(preview)
    assert "mise à disposition" in text and "150,00 €" in text and "600,00 €" not in text
    assert "Contrat individuel" not in text
    assert client.get(public + "/convention.pdf").status_code == 404

    post(client, dossier, csrf, "send", revision="obsolete")
    assert agreements.state(store.get(oid)) == "draft"
    for _ in range(2):
        post(client, dossier, csrf, "send", revision=draft["pdf_sha256"])
    row = cycle(host, store, oid)
    assert row["stage"] == "billing" and agreements.state(row) == "sent"
    assert client.get(public + "/convention.pdf").status_code == 200
    assert b"Signer ma convention" in client.get(public).data
    for _ in range(2):
        post(client, dossier, csrf, "remind")
        cycle(host, store, oid)
    assert len([c for c in host.brevo_send_email.call_args_list if "Rappel de signature" in c.args[1]]) == 1
    signature["status"] = "done"
    row = cycle(host, store, oid)
    assert row["stage"] == "billing" and agreements.state(row) == "signed"
    assert len([c for c in host._yousign_json.call_args_list if c.args == ("POST", "/signature_requests")]) == 1
    assert client.get(public + "/signed.pdf").status_code == 200
    assert not creations(host, "/v2/client_invoices")
    assert client.get(public + "/vehicle.pdf").status_code == 404


def test_cpf_missing_address_preview_planning_and_signed_copy(host):
    client, store, dossier, public, csrf = admin_order(host, "cpf")
    oid = dossier.rsplit("/", 1)[1]
    row = store.get(oid)
    assert "address" not in row["person"]
    signature, _ = basket_providers(host, store, row)
    post(client, dossier, csrf, "generate")
    old_revision = store.get(oid)["pdf_sha256"]
    post(client, dossier, csrf, "send", revision=old_revision)
    assert agreements.state(store.get(oid)) == "draft"
    post(client, dossier, csrf, "generate", **SLOT)
    text = pdf_text(client.get(dossier + "/convention.pdf"))
    assert "600,00 €" in text and "3 h 30" in text and "CPF" in text and "par carte" not in text
    post(client, dossier, csrf, "send", revision=store.get(oid)["pdf_sha256"])
    row = cycle(host, store, oid)
    assert row["stage"] == "calendar" and row["agreement_state"] == "sent"
    post(client, dossier, csrf, "schedule", cpf_reference="123456789012", funding_confirmed="yes")
    signature["status"] = "done"
    row = cycle(host, store, oid)
    assert row["stage"] == "funded" and row["agreement_state"] == "signed"
    assert not host._qonto_request.called
    assert client.get(public + "/signed.pdf").status_code == 200


def test_personal_practice_manual_workflow_and_offline_receipt(host, monkeypatch):
    client, store, dossier, public, csrf = admin_order(host, "formation")
    oid = dossier.rsplit("/", 1)[1]
    signature, invoice = basket_providers(host, store, store.get(oid))
    post(client, dossier, csrf, "generate", **SLOT)
    old_revision = store.get(oid)["pdf_sha256"]
    post(client, dossier, csrf, "payment_method", payment_method="transfer")
    row = store.get(oid)
    assert old_revision != row["pdf_sha256"] and "Virement bancaire" in pdf_text(client.get(dossier + "/convention.pdf"))
    post(client, dossier, csrf, "send", revision=row["pdf_sha256"])
    row = cycle(host, store, oid)
    assert row["stage"] == "contract" and row["agreement_state"] == "sent"
    original = client.get(dossier + "/convention.pdf").data
    post(client, dossier, csrf, "generate", **dict(SLOT, day="2026-12-10"))
    assert client.get(dossier + "/convention.pdf").data == original
    signature["status"] = "done"
    assert cycle(host, store, oid)["stage"] == "delivery"
    monkeypatch.setattr(exam_retakes, "today", lambda: "2026-12-08")
    post(client, dossier, csrf, "delivered", delivered="yes")
    assert cycle(host, store, oid)["stage"] == "billing"
    assert client.get(public + "/etat-paiement").json == {"state": "offline"}
    qonto = host._qonto_request.side_effect
    def accept_receipt(verb, path, payload=None, **kwargs):
        if (verb, path) == ("POST", "/v2/client_invoices/invoice-1/mark_as_paid"):
            assert payload == {"paid_at": "2026-12-08"}
            invoice["status"] = "paid"
            return {"client_invoice": invoice}
        return qonto(verb, path, payload, **kwargs)
    host._qonto_request.side_effect = accept_receipt
    post(client, dossier, csrf, "receive", paid_day="2026-12-08", reference="VIR-123", received="yes")
    post(client, dossier, csrf, "receive", paid_day="2026-12-08", reference="VIR-123", received="yes")
    row = cycle(host, store, oid)
    assert row["stage"] == "paid" and row["manual_receipt"]["method"] == "transfer"
    assert invoice["status"] == "paid" and len(creations(host, "/v2/client_invoices")) == 1
    assert not creations(host, "/v2/payment_links") and client.get(public + "/invoice.pdf").status_code == 200


def test_existing_link_is_reconciled_before_method_switch(host):
    client, store, dossier, public, csrf = admin_order(host, "vehicule")
    oid = dossier.rsplit("/", 1)[1]
    _, _ = basket_providers(host, store, store.get(oid))
    row = cycle(host, store, oid)
    link_id = row["payment_id"]
    qonto = host._qonto_request.side_effect
    def with_deactivation(verb, path, *args, **kwargs):
        if (verb, path) == ("PATCH", f"/v2/payment_links/{link_id}/deactivate"):
            host.payment_link["status"] = "canceled"
            return {"payment_link": host.payment_link}
        return qonto(verb, path, *args, **kwargs)
    host._qonto_request.side_effect = with_deactivation
    host.card_payments = [{"status":"authorized"}]
    post(client, dossier, csrf, "payment_method", payment_method="cash")
    assert orders.finance.method(store.get(oid)) == "card" and host.payment_link["status"] == "open"
    host.card_payments = []
    post(client, dossier, csrf, "payment_method", payment_method="cash")
    row = cycle(host, store, oid)
    assert row["retired_payment_links"] == [link_id] and "payment_id" not in row
    assert row["payment_method"] == "cash" and host.payment_link["status"] == "canceled"
    assert client.get(public + "/payer").location.endswith(public)
    assert not creations(host, "/v2/client_invoices")


def test_view_permissions_list_filters_and_legacy_signed_order(host):
    client, store, dossier, public, csrf = admin_order(host, "formation")
    oid = dossier.rsplit("/", 1)[1]
    assert client.get(dossier).status_code == 200
    listing = html.fromstring(client.get("/admin/commandes-vtc?q=EXEMPLE&offer=formation").data)
    assert listing.xpath('//a[@href=$href]', href=dossier)
    assert not html.fromstring(client.get("/admin/commandes-vtc?q=inconnu").data).xpath('//a[@href=$href]', href=dossier)
    assert client.post(dossier, data={"action":"generate"}).status_code == 400
    with client.session_transaction() as session:
        session["admin_role"] = "viewer"
    assert client.post(dossier, data={"action":"generate","csrf_token":csrf}).status_code == 403
    assert client.get(dossier + "/signed.pdf").status_code == 404
    row = store.get(oid)
    row.update(stage="delivery", signed_day="2026-10-30", request_id="old-request")
    store.save(row)
    assert agreements.state(row) == "signed"
    assert not html.fromstring(client.get(dossier).data).xpath('//button[@value="send"]')
    host._is_external_partner_session = lambda: True
    assert client.get(dossier).status_code == 403
    assert client.get(dossier + "/convention.pdf").status_code == 403


def test_funding_can_change_on_unconfirmed_practical_order(host):
    client, store, dossier, public, csrf = admin_order(host, "cpf")
    oid = dossier.rsplit("/", 1)[1]
    row = store.get(oid)
    row["stage"] = "verify"
    row.pop("verified_at")
    store.save(row)
    post(client, dossier, csrf, "payment_method", payment_method="cheque")
    row = store.get(oid)
    assert row["stage"] == "verify" and row["offer"] == "formation" and row["original_offer"] == "cpf"
    post(client, dossier, csrf, "generate", address="1 rue du Test", zip_code="06000", city="Nice", **SLOT)
    post(client, dossier, csrf, "send", revision=store.get(oid)["pdf_sha256"])
    signature, _ = basket_providers(host, store, store.get(oid))
    row = cycle(host, store, oid)
    assert row["stage"] == "verify" and row["agreement_state"] == "sent"
    assert b"Signer ma convention" not in client.get(public).data
    client.post(public, data={"action":"verify","csrf_token":csrf})
    assert store.get(oid)["stage"] == "contract"
    signature["status"] = "done"
    assert cycle(host, store, oid)["stage"] == "delivery"


def test_reissuing_an_active_request_keeps_its_pdf_and_sends_the_new_one(host):
    client, store, dossier, public, csrf = admin_order(host, "vehicule")
    oid = dossier.rsplit("/", 1)[1]
    signature, _ = basket_providers(host, store, store.get(oid))
    post(client, dossier, csrf, "generate")
    revision = store.get(oid)["pdf_sha256"]
    post(client, dossier, csrf, "send", revision=revision)
    cycle(host, store, oid)
    original = client.get(dossier + "/convention.pdf").data
    initial = host._yousign_json.side_effect
    def cancel_or_create(verb, path, **kwargs):
        if verb == "POST" and path.endswith("/cancel"):
            signature["status"] = "canceled"
        if verb == "POST" and path == "/signature_requests":
            assert kwargs["json"]["external_id"] == "vtc-v2-" + oid
            signature.update(status="draft", id="signature-2")
        return initial(verb, path, **kwargs)
    host._yousign_json.side_effect = cancel_or_create
    post(client, dossier, csrf, "restart", agreement_version="1", confirm_restart="yes")
    row = store.get(oid)
    assert row["agreement_state"] == "draft" and row["agreement_version"] == 2
    assert client.get(dossier + "/conventions/1.pdf").data == original
    assert client.get(public + "/convention.pdf").status_code == 404
    post(client, dossier, csrf, "send", revision=row["pdf_sha256"])
    row = cycle(host, store, oid)
    assert row["request_id"] == "signature-2"
    assert row["emails"]["signature-v2"]["sent_at"] and row["emails"]["signature"]["sent_at"]
    signature["status"] = "done"
    post(client, dossier, csrf, "restart", agreement_version="2", confirm_restart="yes")
    assert store.get(oid)["agreement_state"] == "sent"
    assert cycle(host, store, oid)["agreement_state"] == "signed"


def test_old_billing_error_does_not_block_vehicle_signature(host):
    client, store, dossier, public, csrf = admin_order(host, "vehicule")
    oid = dossier.rsplit("/", 1)[1]
    row = store.get(oid)
    row.update(billing_flow="invoice_first", invoice_id="invoice-1", client_id="client-1")
    store.save(row)
    signature, invoice = basket_providers(host, store, row)
    invoice["status"] = "canceled"
    post(client, dossier, csrf, "generate")
    post(client, dossier, csrf, "send", revision=store.get(oid)["pdf_sha256"])
    with host.app.app_context():
        orders.process_pending(host)
    row = store.get(oid)
    assert row["error"] and row["agreement_state"] == "sent" and not row["agreement_error"]
    signature["status"] = "done"
    post(client, dossier, csrf, "retry")
    with host.app.app_context():
        orders.process_pending(host)
    row = store.get(oid)
    assert row["stage"] == "billing" and row["agreement_state"] == "signed"
    assert client.get(public + "/signed.pdf").status_code == 200


def test_replacing_a_reserved_slot_returns_its_seat(host):
    slot = dict(SLOT, duration="3 h 30")
    store = orders.Store(host)
    store.publish("published", slot, 1)
    client, store, oid, _, csrf = begin(host, "formation", slot_id="published")
    dossier = "/admin/commandes-vtc/" + oid
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role="admin")
    assert not store.slots("2026-10-31")
    post(client, dossier, csrf, "restart", agreement_version="1", confirm_restart="yes")
    post(client, dossier, csrf, "generate", **dict(SLOT, day="2026-12-09"))
    row = store.get(oid)
    assert row["slot"]["day"] == "2026-12-09" and not row["selected_slot"]
    assert store.slots("2026-10-31")[0]["free"] == 1
