"""Public entry points and real workflow with provider responses isolated."""
from unittest.mock import Mock
import copy
import pytest
from lxml import html
from pypdf import PdfReader
from test_exam_retakes import host, providers

import exam_retakes
import vtc_public_orders as orders
from vtc_order_store import Store


def begin(host, offer, **extras):
    host._is_external_partner_session = lambda: False
    host._current_partner_id = lambda: ""
    client = host.app.test_client()
    checkout = "/vtc/commande/" + offer
    form = html.fromstring(client.get(checkout).data)
    payload = dict(first_name="Camille",last_name="EXEMPLE",email="vtc@example.test",phone="0612345678",
                   address="10 rue des Tests",zip_code="83480",city="Puget-sur-Argens",accepted="yes",admissible="yes",
                   csrf_token=form.xpath('//input[@name="csrf_token"]/@value')[0],draft=form.xpath('//input[@name="draft"]/@value')[0],
                   total_cents="1",exam_centre="06")
    payload.update(extras)
    assert client.post(checkout,data=payload).status_code==303
    assert client.post(checkout,data=payload).status_code==303
    store=Store(host)
    assert len(store.recent(0))==1
    row=store.get(payload["draft"])
    with host.app.app_context():
        orders.process_pending(host)
        key=orders.token(row)
    assert not hasattr(host,"_qonto_request")
    path="/vtc/suivi/"+key
    assert client.get(path).status_code==200
    csrf=payload["csrf_token"]
    assert client.post(path,data={"action":"verify","csrf_token":csrf}).status_code==303
    return client,store,row["id"],path,csrf


def cycle(host,store,oid):
    row=store.get(oid)
    row["due"]=0
    store.save(row)
    with host.app.app_context(): orders.process_pending(host)
    row=store.get(oid)
    assert not row.get("error"),row.get("error")
    return row


def basket_providers(host, store, row):
    signature, invoice = providers(host, store, row)
    invoice["purchase_order"] = "VTC-" + row["id"]
    original = host._qonto_request.side_effect
    host._now_iso = exam_retakes.now
    host.QontoApiError = type("QontoApiError", (Exception,), {})
    def qonto(method, path, payload=None, **kwargs):
        if path == "/v2/payment_links/connections":
            return {"status":"enabled", "bank_account_id":"bank"}
        if path == "/v2/organization":
            return {"organization":{"id":"org-1","bank_accounts":[{"id":"bank"}]}}
        if (method, path) == ("POST", "/v2/payment_links"):
            basket = payload["payment_link"]
            assert basket["reusable"] is False and "invoice_id" not in basket
            assert basket["items"][0]["type"] == "service"
            host.payment_link.update(basket, resource_type="Basket")
            host.payment_link.pop("invoice_id", None)
            return {"payment_link":copy.deepcopy(host.payment_link)}
        if path == "/v2/client_invoices/invoice-1/mark_as_paid":
            assert payload == {"paid_at":"2026-10-31"}
            invoice["status"] = "paid"
        return original(method, path, payload, **kwargs)
    host._qonto_request.side_effect = qonto
    return signature, invoice


def capture(host, invoice, status="paid"):
    host.card_payments = [{"id":"capture-1", "status":status, "paid_at":"2026-10-30T23:13:00Z",
                           "amount":invoice["total_amount"].copy()}]


def creations(host, endpoint):
    return [call for call in host._qonto_request.call_args_list if call.args[:2] == ("POST", endpoint)]


def test_vehicle_payment_and_documents(host,tmp_path):
    client,store,oid,path,csrf=begin(host,"vehicule")
    row=store.get(oid)
    assert (row["stage"], row["total_cents"])==("billing",15000)
    _,invoice=basket_providers(host,store,row)
    invoice["purchase_order"]="VTC-"+oid
    orders.document(row,tmp_path/"provider.pdf")
    host.fetch_qonto_client_invoice_pdf=Mock(return_value=((tmp_path/"provider.pdf").read_bytes(),"invoice.pdf"))
    row=cycle(host,store,oid)
    assert row["payment_url"].startswith("https://pay.qonto.com")
    assert client.get(path+"/vehicle.pdf").status_code==404
    assert not creations(host, "/v2/client_invoices")
    capture(host, invoice)
    row=cycle(host,store,oid)
    assert row["stage"]=="paid"
    assert client.get(path+"/vehicle.pdf").mimetype=="application/pdf"
    assert client.get(path+"/invoice.pdf").mimetype=="application/pdf"
    assert client.get(path+"x/vehicle.pdf").status_code==404
    assert client.get(path+"/convention.pdf").status_code==404
    assert not host._yousign_json.called
    create=[call for call in host._qonto_request.call_args_list if call.args[:2]==("POST","/v2/client_invoices")]
    assert "Règlement intégral reçu le 31/10/2026" in create[0].args[2]["terms_and_conditions"]
    assert create[0].args[2]["items"][0]["vat_rate"] == "0"
    assert len(create)==1 and create[0].args[2]["items"][0]["unit_price"]["value"]=="150.000000"


def test_training_contract_before_collection(host,monkeypatch):
    slot=dict(day="2026-12-01",start="08:30",end="12:00",duration="3 h 30",trainer="Formateur VTC qualifié")
    Store(host).publish("slot",slot,1)
    client,store,oid,path,csrf=begin(host,"formation",slot_id="slot")
    row=store.get(oid)
    assert row["stage"]=="contract" and not store.slots("2026-10-31")
    signature,invoice=basket_providers(host,store,row)
    invoice["purchase_order"]="VTC-"+oid
    row=cycle(host,store,oid)
    assert row["signature_url"].startswith("https://")
    pdf=" ".join(p.extract_text() for p in PdfReader(store.document(oid,"convention")).pages)
    assert "600" in pdf and "105 h" not in pdf and "3 h 30" in pdf
    signature["status"]="done"
    row=cycle(host,store,oid)
    assert row["stage"]=="delivery" and not host._qonto_request.called
    assert client.get(path+"/signed.pdf").status_code==200
    assert client.post("/admin/commandes-vtc/"+oid,data={}).status_code==401
    with client.session_transaction() as s:s.update(admin_logged_in=True,admin_role="admin")
    action=dict(action="delivered",delivered="yes",csrf_token=csrf)
    client.post("/admin/commandes-vtc/"+oid,data=action)
    assert store.get(oid)["stage"]=="delivery"
    monkeypatch.setattr(exam_retakes,"today",lambda:"2026-12-15")
    client.post("/admin/commandes-vtc/"+oid,data=action)
    assert cycle(host,store,oid)["payment_url"]
    assert not creations(host, "/v2/client_invoices")
    capture(host, invoice)
    assert cycle(host,store,oid)["stage"]=="paid"
    assert client.get(path+"/completion.pdf").status_code==200


def test_cpf_booking_and_funding(host,monkeypatch):
    client,store,oid,path,csrf=begin(host,"cpf")
    host._qonto_request=Mock(side_effect=AssertionError("CPF must never be billed by card"))
    page=client.get(path)
    assert orders.BOOKING.encode() in page.data
    with client.session_transaction() as s:s.update(admin_logged_in=True,admin_role="admin")
    action=dict(action="schedule",day="2026-12-01",start="08:30",end="12:00",trainer="Mme Exemple, formatrice VTC",csrf_token=csrf)
    client.post("/admin/commandes-vtc/"+oid,data=action)
    assert store.get(oid)["stage"]=="calendar"
    action.update(funding_confirmed="yes",cpf_reference="123456789012")
    client.post("/admin/commandes-vtc/"+oid,data=action)
    assert cycle(host,store,oid)["stage"]=="funded" and not host._qonto_request.called
    assert client.get(path+"/vehicle.pdf").status_code==200
    assert client.get(path+"/invoice.pdf").status_code==404


def test_centres_and_confirmation_privacy(host):
    client = host.app.test_client()
    url = "/vtc/commande/vehicule"
    page = html.fromstring(client.get(url).data)
    payload = dict(first_name="Camille", last_name="Exemple", email="vtc@example.test",
                   phone="0612345678", address="10 rue des Tests", city="Nice", zip_code="06000",
                   accepted="yes", csrf_token=page.xpath('//input[@name="csrf_token"]/@value')[0],
                   draft=page.xpath('//input[@name="draft"]/@value')[0])
    for code in ("", "75"):
        assert client.post(url, data=dict(payload, exam_centre=code)).status_code == 400
    assert client.post(url, data=dict(payload, exam_centre="83")).status_code == 303
    for _ in range(2):
        confirmation = client.get(url + "/confirmation")
        assert b"vtc@example.test" in confirmation.data
        assert b"La Valette-du-Var (83)" in confirmation.data
        assert orders.token(Store(host).get(payload["draft"])).encode() not in confirmation.data
        assert confirmation.headers["Cache-Control"] == "no-store"
    assert b"vtc@example.test" not in host.app.test_client().get(url + "/confirmation").data
    with host.app.app_context():
        orders.process_pending(host)
    args = host.brevo_send_email.call_args
    assert 'data-academy-email' in args.args[2] and "La Valette-du-Var (83)" in args.args[2]
    assert 'Confirmer mon adresse e-mail' in args.args[2] and '150 €' in args.kwargs['text_content']


def test_payment_states_and_safe_redirect(host):
    client, store, oid, path, _ = begin(host, "vehicule")
    row = store.get(oid)
    # Existing orders predate the centre selection and still have a working private dossier.
    row.pop("exam_centre")
    store.save(row)
    assert client.get(path + "/etat-paiement").json == {"state": "preparing"}
    assert b'id="payment-wait"' in client.get(path).data
    assert client.get(path + "/payer").location == path
    _, invoice = basket_providers(host, store, row)
    invoice["purchase_order"] = "VTC-" + oid
    row = cycle(host, store, oid)
    assert client.get(path + "/etat-paiement").json == {"state": "ready"}
    assert 'Payer 150 € par carte' in client.get(path).get_data(as_text=True)
    assert client.get(path + "/payer").location == row["payment_url"]
    for status, problem, state in [
        ("unpaid", True, "unavailable"), ("processing", False, "processing"),
        ("partially_paid", False, "review"), ("canceled", False, "review"), ("paid", False, "documents"),
    ]:
        row.update(payment_status=status, billing_problem=problem, paid_cents=row["total_cents"] if status == "paid" else 0)
        store.save(row)
        assert client.get(path + "/etat-paiement").json == {"state": state}
        assert client.get(path + "/payer").location == path
        assert b'class="button pay-button"' not in client.get(path).data
    row.update(payment_status="unpaid", payment_url="https://not-qonto.example/checkout")
    store.save(row)
    assert client.get(path + "/payer").location == path
    assert client.get(path + "x/etat-paiement").status_code == 404


def test_fixed_exam_date_explains_availability_before_payment(host):
    client, store, oid, path, _ = begin(host, "vehicule", exam_date="2026-12-10", exam_centre="83")
    assert store.get(oid)["stage"] == "availability"
    assert 'vérifie la disponibilité' in client.get(path).get_data(as_text=True)
    assert client.get(path + "/payer").location == path


def test_legacy_unbilled_vehicle_uses_zero_vat(host):
    client, store, oid, path, _ = begin(host, "vehicule")
    row = store.get(oid)
    row["vat_rate"] = "20"
    store.save(row)
    _, invoice = basket_providers(host, store, row)
    invoice["purchase_order"] = "VTC-" + oid
    cycle(host, store, oid)
    assert not creations(host, "/v2/client_invoices")
    capture(host, invoice)
    orders.sync_card_billing(host, store, store.get(oid))
    calls = creations(host, "/v2/client_invoices")
    item = calls[0].args[2]["items"][0]
    assert item["vat_rate"] == "0"
    assert item["unit_price"]["value"] == "150.000000"
    assert store.get(oid)["vat_rate"] == "0"


def test_public_canonical_domain_and_gateway_do_not_redirect_in_loop(host):
    client = host.app.test_client()
    path = "/vtc/commande/vehicule"
    response = client.get(path, base_url="https://gestionstagiaires-r5no.onrender.com")
    assert response.status_code == 302
    assert response.location == "https://admissions.integraleconnect.com"+path
    proxied = client.get(path, base_url="https://gestionstagiaires-r5no.onrender.com", headers={"X-VTC-Gateway":"admissions"})
    assert proxied.status_code == 200 and b'csrf_token' in proxied.data
    row = {"id":"a"*32, "access_key":"b"*43}
    assert orders.status_link(host,row).startswith("https://admissions.integraleconnect.com/vtc/suivi/")
    with host.app.test_request_context(path):
        rendered = host.app.jinja_env.get_template("vtc_orders/payment.html").render(
            payment="preparing", key=orders.token(row), row={"offer":"vehicule"}, csrf="test")
    assert 'Nous préparons votre paiement' in rendered
    assert 'Votre paiement<br>se prépare' not in rendered

@pytest.mark.parametrize("state", ["open", "authorized", "pending", "failed", "expired", "canceled"])
def test_no_invoice_without_captured_payment(host, state):
    _, store, oid, _, _ = begin(host, "vehicule")
    row = store.get(oid)
    _, invoice = basket_providers(host, store, row)
    capture(host, invoice, state)
    cycle(host, store, oid)
    cycle(host, store, oid)
    assert not creations(host, "/v2/client_invoices")
    assert len(creations(host, "/v2/payment_links")) == 1


def test_wrong_amount_and_lost_paid_response_do_not_duplicate_invoice(host):
    _, store, oid, _, _ = begin(host, "vehicule")
    row = store.get(oid)
    _, invoice = basket_providers(host, store, row)
    cycle(host, store, oid)
    capture(host, invoice)
    host.card_payments[0]["amount"]["value"] = "149.99"
    with pytest.raises(orders.ReviewRequired):
        orders.sync_card_billing(host, store, store.get(oid))
    assert not creations(host, "/v2/client_invoices")
    capture(host, invoice)
    original = host._qonto_request.side_effect
    def lose_response(method, path, *args, **kwargs):
        result = original(method, path, *args, **kwargs)
        if path.endswith("/mark_as_paid"):
            raise TimeoutError("response lost")
        return result
    host._qonto_request.side_effect = lose_response
    with pytest.raises(TimeoutError):
        orders.sync_card_billing(host, store, store.get(oid))
    host._qonto_request.side_effect = original
    orders.sync_card_billing(host, store, store.get(oid))
    assert len(creations(host, "/v2/client_invoices")) == 1
    assert len(creations(host, "/v2/payment_links")) == 1
    assert len(creations(host, "/v2/client_invoices/invoice-1/mark_as_paid")) == 1
    assert store.get(oid)["payment_status"] == "paid"


def test_existing_invoice_keeps_its_original_link(host):
    _, store, oid, _, _ = begin(host, "vehicule")
    row = store.get(oid)
    _, invoice = providers(host, store, row)
    invoice.update(purchase_order="VTC-"+oid, status="unpaid")
    row.update(invoice_id=invoice["id"], client_id="client-1", payment_id="payment-1")
    store.save(row)
    cycle(host, store, oid)
    assert store.get(oid)["billing_flow"] == "invoice_first"
    assert store.get(oid)["payment_url"] == host.payment_link["url"]
    assert not creations(host, "/v2/payment_links") and not creations(host, "/v2/client_invoices")
