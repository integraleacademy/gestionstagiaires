"""Fixed MAC APS pricing and paid access, with simulated providers and tenants."""
import copy
from decimal import Decimal, ROUND_HALF_UP

import pytest

import app as host
import elearning_orders as learning
import manuals_commerce as commerce
from elearning_native import mac_aps
from manuals_public import TERMS_VERSION
from test_elearning_groups import ROOT, confirm, create, person, purchases, quote, save
from test_elearning_orders import form, latest, mark_paid, prepare
from test_manuals_commerce import merchant, retry, run
from test_manuals_shop import all_data, csrf, login, shop, signup


CODE = "mac-aps"


@pytest.mark.parametrize("saved", [{}, {"unit_cents": 1, "free": True}, {"unit_cents": None}, {"unit_cents": 9900}, {"unit_cents": 0, "free": True}])
def test_mac_aps_price_is_4900_for_every_centre(saved):
    price = learning.prices({"elearning_pricing": {CODE: saved}})[CODE]
    assert price["name"] == "MAC APS"
    assert price["configured"] and price["fixed_price"] and price["free"] is False
    assert price["unit_cents"] == 4900
    assert price["planned_minutes"] == 840 and price["duration_label"] == "14 h"
    assert CODE not in learning.parse_prices({"mac-aps_price": "0.01", "mac-aps_free": "yes"})


@pytest.mark.parametrize("quantity", [1, 2, 37, 100])
@pytest.mark.parametrize("vat,net", [("20", "40.83333333"), ("0", "49")])
def test_invoice_rounding_keeps_exact_mac_aps_ttc(quantity, vat, net):
    order = {"id": "specimen-order", "reference": "SPECIMEN", "order_type": "elearning",
             "submitted_at": "2026-10-12T09:00:00Z", "total_cents": quantity * 4900,
             "items": [{"kind": "elearning", "code": CODE, "label": "Accès e-learning MAC APS",
                        "quantity": quantity, "unit_cents": 4900, "total_cents": quantity * 4900}],
             "commerce": {"taxes": {"elearning": {"rate": vat, "exemption": "S261" if vat == "0" else ""}}}}
    payload = commerce.build_invoice_payload(order, "specimen-client", "FR7612345678901234567890185")
    item = payload["items"][0]
    assert item["title"] == "Accès e-learning MAC APS"
    assert Decimal(item["unit_price"]["value"]) == Decimal(net)
    total = (Decimal(item["unit_price"]["value"]) * Decimal(item["quantity"]) * (1 + Decimal(item["vat_rate"])) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    assert int(total) == quantity * 4900
    assert payload["settings"]["transaction_type"] == "services"


@pytest.mark.parametrize("overrides", [{"free_snapshot": True, "total_cents": 0}, {"unit_cents": 1, "total_cents": 1}, {"unit_cents": 9900, "total_cents": 9900}, {"total_cents": 9800}, {"learners": []}])
def test_mac_aps_entitlement_rejects_free_or_inconsistent_snapshots(overrides):
    order = {"order_type": "elearning", "course_code": CODE, "status": "received",
             "free_snapshot": False, "unit_cents": 4900, "total_cents": 4900, "learners": [{"id": "specimen"}],
             "commerce": {"invoice_id": "specimen-invoice", "invoice_status": "paid", "payment_status": "paid", "paid_cents": 9800, "remaining_cents": 0}}
    assert learning.entitled(order)
    order.update(overrides)
    assert not learning.entitled(order)


def test_legacy_mac_invoice_still_requires_full_original_payment():
    order = {"order_type": "elearning", "course_code": CODE, "status": "received",
             "free_snapshot": False, "unit_cents": 6000, "total_cents": 6000, "learners": [{"id": "specimen"}],
             "commerce": {"invoice_id": "legacy-invoice", "invoice_status": "paid", "payment_status": "paid",
                          "paid_cents": 4900, "remaining_cents": 1100}}
    assert not learning.entitled(order)
    order["commerce"].update(remaining_cents=0)
    assert not learning.entitled(order)
    order["commerce"].update(paid_cents=6000)
    assert learning.entitled(order)
    assert order["unit_cents"] == order["total_cents"] == 6000


def test_fixed_mac_price_is_visible_and_not_editable_in_admin(shop):
    pid = prepare(shop)
    admin = host.app.test_client()
    admin.post("/admin/login", data={"username": "admin@example.test", "password": "platform-test-pass"})
    url = "/admin/commandes-elearning?partner_id=" + pid
    page = admin.get(url)
    assert page.status_code == 200 and "MAC APS" in page.text and "49,00 €" in page.text
    assert 'name="mac-aps_price"' not in page.text and 'name="mac-aps_free"' not in page.text
    assert admin.post(url, data={"csrf_token": csrf(admin, url), "partner_id": pid,
                                "aps_price": "42.50", "vtc_price": "", "vtc_free": "yes",
                                "mac-aps_price": "0.01", "mac-aps_free": "yes"}).status_code == 303
    partner = next(p for p in all_data(shop)["partners"] if p["id"] == pid)
    assert CODE not in partner["elearning_pricing"]
    assert learning.prices(partner)[CODE]["unit_cents"] == 4900
    assert learning.prices(partner)["aps"]["unit_cents"] == 4250
    assert learning.prices(partner)["vtc"]["free"] is True


def test_direct_mac_checkout_ignores_posted_and_saved_discounts(shop, merchant):
    pid = prepare(shop)
    host._atomic_update_data(lambda data: host._partner_or_404(data, pid).update(elearning_pricing={CODE: {"unit_cents": 100, "free": True}}), partner_id=pid)
    fields = form(shop["client"])
    for key, value in {"course_code": CODE, "unit_cents": "1", "total_cents": "0", "free_snapshot": "true"}.items():
        fields[key] = value
    created = shop["client"].post(ROOT + "/recapitulatif", data=fields)
    assert created.status_code == 303, created.text
    order = latest(shop)
    assert order["unit_cents"] == 4900 and order["total_cents"] == 9800 and order["free_snapshot"] is False
    assert order["items"][0]["label"] == "Accès e-learning MAC APS"
    assert [(m["course_id"], m["course_version"], m["required_minutes"]) for m in order["modules"]] == [
        ("academy-macaps-02", mac_aps.VERSION, 180), ("academy-macaps-03", mac_aps.VERSION, 240), ("academy-macaps-05", mac_aps.VERSION, 420)]
    assert shop["client"].post(created.location + "/confirmer", data={"csrf_token": csrf(shop["client"], created.location), "confirm": "yes", "terms_version": TERMS_VERSION}).status_code == 303
    assert latest(shop)["terms_acceptance"]["version"] == TERMS_VERSION
    run(order)
    assert merchant["invoice"]["total_amount"] == {"value": "98", "currency": "EUR"}
    assert not latest(shop).get("activated_at") and not learning.entitled(latest(shop))


def test_mac_group_paid_only_activation_and_centre_branded_learner_access(shop, merchant):
    pid = prepare(shop)
    host._atomic_update_data(lambda data: host._partner_or_404(data, pid).update(name="Centre MAC Démonstration", email="formation@example.test", phone="0400000000"), partner_id=pid)
    host._atomic_update_data(lambda data: data["manuals_commerce_settings"].update(elearning_vat="20", elearning_exemption=""))
    client = shop["client"]
    url = create(client, code=CODE, name="MAC APS octobre · données de test")
    save(shop, url, [person(), person("alex@example.test", "Alex", "Durand")])
    fields = quote(client, url)
    fields.update(unit_cents="1", total_cents="0", free_snapshot="true", partner_id="forged-tenant")
    order = confirm(shop, url, fields)
    assert order["partner_id"] == pid and order["total_cents"] == 9800
    token = learning.access_token(host, order, order["learners"][0])
    learner = host.app.test_client()
    assert learner.get("/apprendre/" + token).status_code == 404
    run(order)
    current = latest(shop)
    assert current["commerce"]["status"] == "waiting_payment"
    assert Decimal(merchant["invoice"]["items"][0]["unit_price"]["value"]) == Decimal("40.83333333")
    assert merchant["payment"]["amount"] == {"value": "98.00", "currency": "EUR"}
    assert not any(mail[1].get("metadata", {}).get("purpose", "").startswith("elearning_learner_") for mail in shop["mails"])
    client.get(url + "?paid=true")
    merchant["invoice"].update(paid_amount={"value": "49.00", "currency": "EUR"})
    retry(order)
    assert not learning.entitled(latest(shop)) and learner.get("/apprendre/" + token).status_code == 404
    mark_paid(merchant)
    retry(order)
    paid = latest(shop)
    assert learning.entitled(paid) and paid["activated_at"]
    virtual, person_record = learning.learner_context(all_data(shop), token)
    assert virtual["training_type"] == "MAC APS" and mac_aps.is_training(virtual)
    assert [m["course_version"] for m in virtual["aps_native_modules"]] == [mac_aps.VERSION] * 3
    assert person_record["email"] == "camille@example.test"
    emails = [mail for mail in shop["mails"] if mail[1].get("metadata", {}).get("purpose", "").startswith("elearning_learner_")]
    assert len(emails) == 2
    for args, options in emails:
        assert "MAC APS" in args[1] and "Centre MAC Démonstration" in args[1]
        assert options["sender_name"] == "Centre MAC Démonstration"
        assert options["reply_to"]["email"] == "formation@example.test"
        assert "MAC-APS" not in args[2] and "formation@example.test" in args[2]
    count = len(shop["mails"])
    retry(order)
    assert len(shop["mails"]) == count
    access = "/apprendre/" + token
    assert learner.get(access).status_code == 200
    entered = learner.post(access, data={"csrf_token": csrf(learner, access)})
    assert entered.status_code == 303
    path = learner.get(entered.location)
    assert path.status_code == 200 and "MAC APS" in path.text
    assert "academy-macaps-02" in path.text
    assert all(module["title"] in path.text for module in paid["modules"])
    assert "academy-aps62" not in path.text


@pytest.mark.parametrize("original_price", [6000, 4900])
def test_mac_later_additions_keep_the_paid_batch_and_charge_only_new_people(shop, merchant, monkeypatch, original_price):
    prepare(shop)
    url = create(shop["client"], code=CODE, name="MAC APS · groupe test")
    save(shop, url, [person()])
    with monkeypatch.context() as previous_price:
        previous_price.setitem(learning.COURSES[CODE], "fixed_cents", original_price)
        first = confirm(shop, url)
        run(first)
        mark_paid(merchant)
        retry(first)
    paid = copy.deepcopy(purchases(shop)[0])
    assert paid["unit_cents"] == paid["total_cents"] == original_price
    token = learning.access_token(host, paid, paid["learners"][0])
    save(shop, url, [person("alex@example.test", "Alex", "Durand")])
    second = confirm(shop, url)
    assert second["id"] != paid["id"] and second["group_id"] == paid["group_id"]
    assert second["unit_cents"] == second["total_cents"] == 4900 and second["free_snapshot"] is False
    assert [p["email"] for p in second["learners"]] == ["alex@example.test"]
    assert not learning.entitled(second) and not second.get("activated_at")
    assert next(p for p in purchases(shop) if p["id"] == paid["id"]) == paid
    assert learning.learner_context(all_data(shop), token)[1]["email"] == "camille@example.test"
    assert [m["course_version"] for m in second["modules"]] == [mac_aps.VERSION] * 3


def test_mac_orders_and_groups_remain_tenant_bound(shop, merchant):
    prepare(shop)
    url = create(shop["client"], code=CODE, name="MAC APS · organisme A")
    save(shop, url, [person()])
    fields = quote(shop["client"], url)
    order = confirm(shop, url, fields)
    other = host.app.test_client()
    signup(other, email="other@example.test")
    login(other, email="other@example.test")
    before = copy.deepcopy(all_data(shop)["manual_orders"])
    for path in (url, url + "/recapitulatif", ROOT + "/commandes/" + order["id"], ROOT + "/commandes/" + order["id"] + "/statut", ROOT + "/commandes/" + order["id"] + "/facture"):
        assert other.get(path).status_code == 404
    fields["csrf_token"] = csrf(other, ROOT)
    assert other.post(url + "/creer-espaces", data=fields).status_code == 404
    assert other.post("/admin/commandes-elearning", data={"partner_id": order["partner_id"], "mac-aps_free": "yes"}).status_code == 403
    assert all_data(shop)["manual_orders"] == before
    assert not merchant["calls"]


def test_mac_group_records_the_current_terms_before_creating_any_purchase(shop, merchant):
    prepare(shop)
    url = create(shop["client"], code=CODE, name="MAC APS · acceptation de test")
    save(shop, url, [person()])
    fields = quote(shop["client"], url)
    assert fields["terms_version"] == TERMS_VERSION
    page = shop["client"].get(url + "/recapitulatif").text
    assert 'type="checkbox" name="confirm" value="yes" required' in page
    for change in ({"confirm": ""}, {"terms_version": ""}, {"terms_version": "outdated"}):
        assert shop["client"].post(url + "/creer-espaces", data={**fields, **change}).status_code == 400
        assert not purchases(shop) and not merchant["calls"]
    order = confirm(shop, url, fields)
    acceptance = order["terms_acceptance"]
    assert acceptance["version"] == TERMS_VERSION
    assert acceptance["user_id"] == order["created_by"] and len(acceptance["sha256"]) == 64
    assert acceptance["accepted_at"] and acceptance["url"] == "/conditions-de-vente?version=" + TERMS_VERSION
    assert order["total_cents"] == 4900 and not learning.entitled(order)
