"""Public entry points and real workflow with provider responses isolated."""
from unittest.mock import Mock
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
                   total_cents="1",**extras)
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


def test_vehicle_payment_and_documents(host,tmp_path):
    client,store,oid,path,csrf=begin(host,"vehicule")
    row=store.get(oid)
    assert (row["stage"], row["total_cents"])==("billing",15000)
    _,invoice=providers(host,store,row)
    invoice["purchase_order"]="VTC-"+oid
    orders.document(row,tmp_path/"provider.pdf")
    host.fetch_qonto_client_invoice_pdf=Mock(return_value=((tmp_path/"provider.pdf").read_bytes(),"invoice.pdf"))
    row=cycle(host,store,oid)
    assert row["payment_url"].startswith("https://pay.qonto.com")
    assert client.get(path+"/vehicle.pdf").status_code==404
    invoice["status"]="paid"
    row=cycle(host,store,oid)
    assert row["stage"]=="paid"
    assert client.get(path+"/vehicle.pdf").mimetype=="application/pdf"
    assert client.get(path+"/invoice.pdf").mimetype=="application/pdf"
    assert client.get(path+"x/vehicle.pdf").status_code==404
    assert client.get(path+"/convention.pdf").status_code==404
    assert not host._yousign_json.called
    create=[call for call in host._qonto_request.call_args_list if call.args[:2]==("POST","/v2/client_invoices")]
    assert len(create)==1 and create[0].args[2]["items"][0]["unit_price"]["value"]=="125.000000"


def test_training_contract_before_collection(host,monkeypatch):
    slot=dict(day="2026-12-01",start="08:30",end="12:00",duration="3 h 30",trainer="Formateur VTC qualifié")
    Store(host).publish("slot",slot,1)
    client,store,oid,path,csrf=begin(host,"formation",slot_id="slot")
    row=store.get(oid)
    assert row["stage"]=="contract" and not store.slots("2026-10-31")
    signature,invoice=providers(host,store,row)
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
    invoice["status"]="paid"
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
