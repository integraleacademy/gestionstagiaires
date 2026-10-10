"""Payment gating, tenant isolation and durable deliveries, with no real network."""
import copy
import json
import re
import secrets
from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict

import app as host
import elearning_orders as learning
import manuals_commerce as commerce
from elearning_native.integration import register_native_elearning
register_native_elearning(host)
from test_manuals_shop import shop, signup, login, csrf, all_data
from test_manuals_commerce import merchant, run, retry


def latest(shop):
    return next(o for o in all_data(shop)["manual_orders"] if learning.is_order(o))


def prepare(shop, *, code="aps", free=False):
    client = shop["client"]
    signup(client)
    login(client)
    pid = next(p["id"] for p in all_data(shop)["partners"] if p.get("account_type") == "manuals_only")
    if free or code == "vtc":
        host._atomic_update_data(lambda data: host._partner_or_404(data, pid).update(elearning_pricing={code: {"unit_cents": 7300, "free": free}}), partner_id=pid)
    def tax(data):
        data.setdefault("manuals_commerce_settings", {}).update(elearning_vat="0", elearning_exemption="S261")
        return {}
    host._atomic_update_data(tax)
    return pid


def form(client, **updates):
    fields = MultiDict({"csrf_token": csrf(client, "/admin/organisme/e-learning"), "request_id": secrets.token_hex(16), "course_code": "aps", "group_name": "Groupe test", "address": "1 rue du Test", "postal_code": "75001", "city": "Paris", "total_cents": "0", "free_snapshot": "true"})
    for last, first, email in [("Martin", "Camille", "camille@example.test"), ("Durand", "Alex", "alex@example.test")]:
        for k,v in (("last_name",last),("first_name",first),("email",email)):
            fields.add(k,v)
    fields.update(updates)
    return fields


def submit(shop, *, code="aps", free=False):
    prepare(shop, code=code, free=free)
    client = shop["client"]
    fields = form(client)
    fields["course_code"] = code
    response = client.post("/admin/organisme/e-learning/recapitulatif", data=fields)
    assert response.status_code == 303, response.text
    url = response.location
    assert client.post(url + "/confirmer", data={"csrf_token": csrf(client, url), "confirm": "yes"}).status_code == 303
    return latest(shop)


def mark_paid(merchant):
    merchant["invoice"].update(status="paid", paid_amount=copy.deepcopy(merchant["invoice"]["total_amount"]), paid_at="2026-10-08")


def test_group_quoted_server_side_and_idempotent(shop, merchant):
    prepare(shop)
    c = shop["client"]
    fields = form(c)
    url = c.post("/admin/organisme/e-learning/recapitulatif", data=fields).location
    assert c.post("/admin/organisme/e-learning/recapitulatif", data=fields).location == url
    order = latest(shop)
    assert order["total_cents"] == 11800 and order["free_snapshot"] is False
    assert len(order["learners"]) == 2 and len(order["modules"]) == 15
    assert c.post(url + "/confirmer", data={"confirm":"yes"}).status_code == 400
    confirmation = {"csrf_token": csrf(c,url), "confirm":"yes"}
    assert c.post(url+"/confirmer",data=confirmation).status_code == 303
    assert c.post(url+"/confirmer",data=confirmation).status_code == 303
    run(order)
    order = latest(shop)
    assert order["commerce"]["status"] == "waiting_payment"
    assert order["commerce"]["invoice_id"] == "invoice-1"
    assert merchant["invoice"]["settings"]["transaction_type"] == "services"
    assert not learning.entitled(order) and not order.get("activated_at")
    assert not any(m[0][0] in {"camille@example.test","alex@example.test"} for m in shop["mails"])
    assert c.get(url+"/facture").status_code == 200
    assert c.get("/admin/manuels/commandes/" + order["id"]).status_code == 404
    assert c.get(url+"/statut").json["active"] is False


def test_paid_invoice_activates_individual_emails_only_once(shop, merchant):
    order = submit(shop)
    run(order)
    mark_paid(merchant)
    retry(order)
    order = latest(shop)
    assert learning.entitled(order) and order["activated_at"]
    assert order["commerce"]["payment_status"] == "paid"
    assert order["commerce"]["queued"] is False
    messages = [m for m in shop["mails"] if m[0][0] in {"camille@example.test","alex@example.test"}]
    assert len(messages) == 2
    tokens = []
    for person in order["learners"]:
        token = learning.access_token(host, order, person)
        tokens.append(token)
        data = all_data(shop)
        assert learning.learner_context(data,token)[1]["id"] == person["id"]
        assert token not in str(order)
        mail = next(m[0][2] for m in messages if m[0][0] == person["email"])
        assert token in mail and "https://gestionstagiaires-test-v2.onrender.com/apprendre/" in mail
    assert len(set(tokens)) == 2
    before = len(shop["mails"])
    retry(order)
    assert len(shop["mails"]) == before
    assert sum(m == "POST" and p == "/v2/client_invoices" for m,p,*_ in merchant["calls"]) == 1


@pytest.mark.parametrize("status,paid,remaining", [("unpaid",0,11800),("paid",5900,5900),("canceled",11800,0)])
def test_incomplete_or_cancelled_payment_never_grants_access(status,paid,remaining):
    order = {"id":"o","order_type":"elearning","status":"received","total_cents":11800,"commerce":{"invoice_id":"i","invoice_status":status,"payment_status":"paid","paid_cents":paid,"remaining_cents":remaining}}
    assert not learning.entitled(order)


def test_wrong_invoice_total_fails_closed(shop, merchant):
    order = submit(shop)
    merchant["wrong_total"] = True
    run(order)
    order = latest(shop)
    assert order["commerce"]["status"] == "needs_review"
    assert not order.get("activated_at")


def test_free_vtc_never_calls_billing_and_pins_current_curriculum(shop, monkeypatch):
    order = submit(shop, code="vtc", free=True)
    monkeypatch.setattr(host,"_qonto_request",lambda *a,**k: pytest.fail("No Qonto call for free access"))
    run(order)
    order = latest(shop)
    assert order["total_cents"] == 0 and learning.entitled(order)
    manifest = json.loads((Path(learning.__file__).parent / "elearning_native/vtc/manifest.json").read_text())
    assert [(m["course_id"], m["course_version"], m["required_minutes"]) for m in order["modules"]] == [
        (m["id"], m["version"], m["planned_minutes"]) for m in manifest["modules"]]
    assert sum(m["required_minutes"] for m in order["modules"]) == manifest["planned_minutes"]
    assert not order["commerce"].get("invoice_id")
    assert all(p.get("activated_at") for p in order["learners"])
    assert sum(k.startswith("learner_") for k in order["commerce"]["emails"]) == 2


def test_failed_learner_mail_retries_without_recreating_access(shop, merchant, monkeypatch):
    order = submit(shop)
    run(order)
    mark_paid(merchant)
    sender = host.brevo_send_email
    monkeypatch.setattr(host,"brevo_send_email", lambda email,*a,**k: {"ok":False} if email == "alex@example.test" else sender(email,*a,**k))
    retry(order)
    first = latest(shop)
    assert first["commerce"]["queued"] is True
    assert first["learners"][0]["activated_at"]
    monkeypatch.setattr(host,"brevo_send_email",sender)
    retry(order)
    second = latest(shop)
    assert first["learners"] == second["learners"]
    assert second["commerce"]["queued"] is False
    assert sum(m[0][0] == "camille@example.test" for m in shop["mails"]) == 1
    assert sum(m[0][0] == "alex@example.test" for m in shop["mails"]) == 1


def test_partners_cannot_read_other_orders_or_change_prices(shop):
    order = submit(shop,free=True)
    other = host.app.test_client()
    assert signup(other,email="other@example.test").status_code == 303
    login(other,email="other@example.test")
    url = "/admin/organisme/e-learning/commandes/" + order["id"]
    for suffix in ("","/statut","/facture"):
        assert other.get(url+suffix).status_code == 404
    assert other.post(url+"/actualiser",data={"csrf_token":csrf(other,"/admin/organisme/e-learning")}).status_code == 404
    assert other.post("/admin/commandes-elearning",data={"partner_id":order["partner_id"],"aps_free":"yes"}).status_code == 403


def test_invalid_learners_and_unknown_price(shop):
    prepare(shop)
    c = shop["client"]
    fields = form(c); fields.setlist("email",["Same@example.test","same@example.test"])
    assert c.post("/admin/organisme/e-learning/recapitulatif",data=fields).status_code == 400
    fields = form(c); fields["course_code"]="vtc"
    assert c.post("/admin/organisme/e-learning/recapitulatif",data=fields).status_code == 400
    fields = form(c); fields.setlist("first_name",[""])
    assert c.post("/admin/organisme/e-learning/recapitulatif",data=fields).status_code == 400


def test_price_change_before_confirmation_requires_new_quote(shop):
    pid = prepare(shop)
    c=shop["client"]
    url=c.post("/admin/organisme/e-learning/recapitulatif",data=form(c)).location
    host._atomic_update_data(lambda data:host._partner_or_404(data,pid).update(elearning_pricing={"aps":{"unit_cents":1000}}),partner_id=pid)
    assert c.post(url+"/confirmer",data={"csrf_token":csrf(c,url),"confirm":"yes"}).status_code == 409
    assert latest(shop)["status"] == "draft"


def test_admin_can_set_partner_tariff_and_gratuity(shop):
    pid=prepare(shop)
    c=host.app.test_client()
    c.post("/admin/login",data={"username":"admin@example.test","password":"platform-test-pass"})
    url="/admin/commandes-elearning?partner_id="+pid
    data={"csrf_token":csrf(c,url),"partner_id":pid,"aps_price":"42,50","vtc_price":"","vtc_free":"yes"}
    assert c.post(url,data=data).status_code == 303
    partner=next(p for p in all_data(shop)["partners"] if p["id"]==pid)
    assert learning.prices(partner)["aps"]["unit_cents"] == 4250
    assert learning.prices(partner)["vtc"]["free"] is True


def test_inactive_partner_or_cancelled_order_blocks_existing_token(shop):
    order=submit(shop,free=True);run(order);order=latest(shop)
    token=learning.access_token(host,order,order["learners"][0]);data=all_data(shop)
    assert learning.learner_context(data,token)[1]
    data["manual_orders"][0]["status"]="cancelled"
    assert learning.learner_context(data,token)==(None,None)
    data=all_data(shop)
    next(p for p in data["partners"] if p["id"]==order["partner_id"])["status"]="suspended"
    assert learning.learner_context(data,token)==(None,None)


@pytest.mark.parametrize("code", ["aps", "vtc"])
def test_personal_link_opens_only_purchased_curriculum(shop, code):
    order=submit(shop,code=code,free=True)
    person=order["learners"][0]
    token=learning.access_token(host,order,person)
    learner=host.app.test_client()
    access="/apprendre/"+token
    assert learner.get(access).status_code == 404
    run(order)
    page=learner.get(access)
    assert page.status_code == 200 and person["first_name"] in page.text
    response=learner.post(access,data={"csrf_token":csrf(learner,access)})
    assert response.status_code == 303
    path=learner.get(response.location)
    assert path.status_code == 200, path.text
    first=order["modules"][0]["course_id"]
    player=learner.get(response.location+"/"+first)
    assert player.status_code == 200
    other="academy-vtc-a" if code=="aps" else "academy-aps62-01"
    assert learner.get(response.location+"/"+other).status_code == 403
    assert learner.get('/admin/organisme').status_code == 302


def test_partial_payment_is_rechecked_until_fully_paid(shop, merchant):
    order=submit(shop);run(order)
    merchant["invoice"].update(paid_amount={"value":"59.00","currency":"EUR"})
    retry(order)
    current=latest(shop)
    assert not current.get("activated_at") and current["commerce"]["queued"]
    mark_paid(merchant)
    def ready(data):
        target=commerce._find(data,order["partner_id"],order["id"])
        target["commerce"]["next_attempt"]=0
        return {}
    host._atomic_update_data(ready,partner_id=order["partner_id"])
    run(order)
    assert learning.entitled(latest(shop)) and latest(shop)["activated_at"]


def test_individual_order_and_viewer_cannot_confirm(shop):
    prepare(shop)
    c=shop["client"];fields=form(c)
    for key in ("last_name","first_name","email"):
        fields.setlist(key,[fields.getlist(key)[0]])
    response=c.post("/admin/organisme/e-learning/recapitulatif",data=fields)
    assert response.status_code==303
    order=latest(shop)
    assert len(order["learners"])==1 and order["total_cents"]==5900
    token=csrf(c,response.location)
    with c.session_transaction() as state: state["admin_role"]="viewer"
    assert c.post(response.location+"/confirmer",data={"csrf_token":token,"confirm":"yes"}).status_code==403



def test_learner_email_uses_centre_identity_and_reply_to_without_platform_contacts(shop, monkeypatch):
    order = submit(shop, free=True)
    monkeypatch.setattr(host, "ELEARNING_SENDER_EMAIL", "learning@verified-sender.example.test", raising=False)
    def brand(data):
        current = commerce._find(data, order["partner_id"], order["id"])
        current["centre"].update(name="École Horizon", email="contact@horizon.example.test", contact_email="pedagogie@horizon.example.test")
        # Older snapshots lack the phone field. Resolve only this exact tenant.
        current["centre"].pop("phone", None)
        host._partner_or_404(data, order["partner_id"])["phone"] = "01 84 00 22 33"
        return {}
    host._atomic_update_data(brand, partner_id=order["partner_id"])
    run(order)
    messages = [mail for mail in shop["mails"] if mail[0][0] in {"camille@example.test", "alex@example.test"}]
    assert len(messages) == 2
    for args, kwargs in messages:
        assert args[1] == "Votre accès personnel APS · École Horizon"
        assert kwargs["sender_name"] == "École Horizon"
        assert kwargs["sender_email"] == "learning@verified-sender.example.test"
        assert kwargs["reply_to"] == {"email": "pedagogie@horizon.example.test", "name": "École Horizon"}
        for content in (args[2], kwargs["text_content"]):
            assert "École Horizon" in content
            assert "pedagogie@horizon.example.test" in content
            assert "01 84 00 22 33" in content
            assert "clement@integraleacademy.com" not in content
            assert "04 22 47 07 68" not in content
            assert "INTÉGRALE ACADEMY" not in content and "Intégrale Academy" not in content
    merchant_messages = [mail for mail in shop["mails"] if mail[0][0] == "contact@horizon.example.test"]
    assert merchant_messages
    for args, kwargs in merchant_messages:
        assert "Intégrale Academy" in args[1]
        assert "clement@integraleacademy.com" in args[2]
        assert not {"sender_name", "sender_email", "reply_to"} & kwargs.keys()
    # Existing delivery idempotency is unchanged by the new presentation.
    previous = len(shop["mails"])
    retry(order)
    assert len(shop["mails"]) == previous


def test_learner_brand_fallback_is_tenant_scoped_and_validates_contacts():
    order = {"partner_id": "own", "centre": {"name": "Centre conservé", "email": "bad\r\nBcc: attacker@example.test"}}
    data = {"partners": [{"id": "other", "name": "Autre organisme", "email": "other@example.test", "phone": "09 00 00 00 00"},
                         {"id": "own", "name": "Centre actuel", "email": "centre@example.test", "phone": "01 00 00 00 00"}]}
    assert learning.learner_brand(data, order) == {"name": "Centre conservé", "email": "centre@example.test", "phone": "01 00 00 00 00"}
    assert learning.learner_brand({"partners": data["partners"][:1]}, {"partner_id": "own", "centre": {}}) == {
        "name": "Votre organisme de formation", "email": "", "phone": ""}
    assert learning.centre_snapshot(data["partners"][1])["phone"] == "01 00 00 00 00"
    order["centre"]["contact_email"] = "centre@example.test?subject=unexpected"
    assert learning.learner_brand(data, order)["email"] == "centre@example.test"


def test_learner_sender_never_uses_unverified_partner_address_as_from(shop, monkeypatch):
    order = submit(shop, free=True)
    monkeypatch.setattr(host, "ELEARNING_SENDER_EMAIL", "", raising=False)
    run(order)
    learner_messages = [mail for mail in shop["mails"] if mail[0][0] in {"camille@example.test", "alex@example.test"}]
    assert len(learner_messages) == 2
    for _, kwargs in learner_messages:
        assert kwargs["sender_email"] is None
        assert kwargs["reply_to"]["email"] == "centre@example.test"
    current = latest(shop)
    token = learning.access_token(host, current, current["learners"][0])
    access_page = host.app.test_client().get("/apprendre/" + token)
    assert access_page.status_code == 200
    assert current["centre"]["name"] in access_page.text
    assert "clement@integraleacademy.com" not in access_page.text
