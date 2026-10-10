"""Persistent rosters and payment batches, using both supported tenant stores.

Exercise the customer HTTP workflow and the real merchant worker with an
in-memory Qonto substitute. No bill or learner email reaches a real provider.
"""
import copy
from html.parser import HTMLParser

import pytest
from werkzeug.datastructures import MultiDict

import app as host
import elearning_orders as learning
from test_elearning_orders import mark_paid, prepare
from test_manuals_commerce import merchant, retry, run
from test_manuals_shop import all_data, csrf, login, shop, signup


ROOT = "/admin/organisme/e-learning"


class HiddenFields(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.fields = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "input" and values.get("type") == "hidden" and values.get("name"):
            self.fields[values["name"]] = values.get("value", "")


def record(shop, url):
    return next(o for o in all_data(shop)["manual_orders"] if o["id"] == url.rsplit("/", 1)[-1])


def purchases(shop):
    return [o for o in all_data(shop)["manual_orders"] if learning.is_order(o)]


def person(email="camille@example.test", first="Camille", last="Martin", **fields):
    return {"last_name": last, "first_name": first, "email": email, **fields}


def create(client, *, mode="group", code="aps", name="APS septembre 2026"):
    response = client.get(ROOT + "/nouveau")
    assert response.status_code == 200
    fields = HiddenFields(response.text).fields
    fields.update(mode=mode, course_code=code, group_name=name)
    result = client.post(ROOT + "/nouveau", data=fields)
    assert result.status_code == 303, result.text
    return result.location


def save_fields(shop, url, people, **updates):
    group = record(shop, url)
    fields = MultiDict({"csrf_token": csrf(shop["client"], url), "revision": str(group["revision"]),
                        "group_name": group["group_name"], "course_code": group["course_code"]})
    for learner in people:
        for field, value in (("learner_id", learner.get("id", "")), ("last_name", learner["last_name"]),
                             ("first_name", learner["first_name"]), ("email", learner["email"])):
            fields.add(field, value)
    for key, value in updates.items():
        fields[key] = value
    return fields


def save(shop, url, people, **updates):
    response = shop["client"].post(url + "/enregistrer", data=save_fields(shop, url, people, **updates))
    assert response.status_code == 303, response.text
    return record(shop, url)


def quote(client, url):
    response = client.get(url + "/recapitulatif")
    assert response.status_code == 200, response.text
    fields = HiddenFields(response.text).fields
    assert {"csrf_token", "request_id", "revision", "quote_token"} <= fields.keys()
    fields.update(confirm="yes", address="1 rue du Test", postal_code="75001", city="Paris")
    return fields


def confirm(shop, url, fields=None):
    response = shop["client"].post(url + "/creer-espaces", data=fields or quote(shop["client"], url))
    assert response.status_code == 303, response.text
    return record(shop, response.location)


def test_empty_group_survives_relogin_and_multiple_roster_edits_without_checkout(shop, merchant):
    prepare(shop)
    client = shop["client"]
    url = create(client)
    initial = record(shop, url)
    assert initial["learners"] == [] and initial["order_type"] == "elearning_group"
    assert not purchases(shop) and not initial.get("commerce")
    assert client.get(url + "/recapitulatif").status_code == 303

    client.get("/admin/logout")
    fresh = host.app.test_client()
    login(fresh)
    shop["client"] = fresh
    assert "APS septembre 2026" in fresh.get(ROOT).text
    assert fresh.get(url).status_code == 200

    group = save(shop, url, [person(), person("alex@example.test", "Alex", "Durand")])
    first, second = copy.deepcopy(group["learners"])
    group = save(shop, url, [{**first, "first_name": "Camille corrigée"}, second,
                              person("sam@example.test", "Sam", "Moreau")])
    assert group["learners"][0]["id"] == first["id"]
    assert group["learners"][0]["first_name"] == "Camille corrigée"
    group = save(shop, url, [group["learners"][0], group["learners"][2]], group_name="APS octobre 2026")
    assert group["group_name"] == "APS octobre 2026"
    assert {p["email"] for p in group["learners"]} == {"camille@example.test", "sam@example.test"}
    assert group["revision"] > initial["revision"]
    assert not purchases(shop) and not merchant["calls"]
    assert len(shop["mails"]) == 1  # Only the organism's account welcome.


def test_create_is_idempotent_and_individual_mode_allows_one_person_only(shop):
    prepare(shop)
    client = shop["client"]
    fields = HiddenFields(client.get(ROOT + "/nouveau").text).fields
    fields.update(mode="individual", course_code="aps", group_name="")
    first = client.post(ROOT + "/nouveau", data=fields)
    duplicate = client.post(ROOT + "/nouveau", data=fields)
    assert first.status_code == duplicate.status_code == 303
    assert first.location == duplicate.location
    assert len(all_data(shop)["manual_orders"]) == 1
    url = first.location
    group = save(shop, url, [person()])
    invalid = save_fields(shop, url, [group["learners"][0], person("alex@example.test", "Alex")])
    assert client.post(url + "/enregistrer", data=invalid).status_code == 400
    assert record(shop, url) == group
    order = confirm(shop, url)
    assert order["total_cents"] == 5900 and len(order["learners"]) == 1


def test_quote_does_not_charge_and_verified_full_payment_alone_activates_batch(shop, merchant):
    prepare(shop)
    client = shop["client"]
    url = create(client)
    group = save(shop, url, [person(), person("alex@example.test", "Alex", "Durand")])
    fields = quote(client, url)
    assert not purchases(shop) and not merchant["calls"]
    fields.update(total_cents="0", unit_cents="1", free_snapshot="true", partner_id="forged-tenant")
    order = confirm(shop, url, fields)
    assert order["group_id"] == group["id"] and order["partner_id"] == group["partner_id"]
    assert order["total_cents"] == 11800 and order["free_snapshot"] is False
    assert {p["id"] for p in order["learners"]} == {p["id"] for p in group["learners"]}
    assert not merchant["calls"] and not order.get("activated_at")
    assert confirm(shop, url, fields)["id"] == order["id"]
    assert len(purchases(shop)) == 1

    run(order)
    current = purchases(shop)[0]
    assert current["commerce"]["status"] == "waiting_payment"
    assert not learning.entitled(current) and not current.get("activated_at")
    assert not any(m[0][0] in {"camille@example.test", "alex@example.test"} for m in shop["mails"])
    # A return URL and a partially paid invoice must both leave access blocked.
    client.get(url + "?paid=true")
    merchant["invoice"].update(paid_amount={"value": "59.00", "currency": "EUR"})
    retry(order)
    assert not purchases(shop)[0].get("activated_at")
    mark_paid(merchant)
    retry(order)
    paid = purchases(shop)[0]
    assert learning.entitled(paid) and paid["activated_at"]
    for learner in paid["learners"]:
        token = learning.access_token(host, paid, learner)
        assert learning.learner_context(all_data(shop), token)[1]["id"] == learner["id"]
    assert sum(m[0][0] in {"camille@example.test", "alex@example.test"} for m in shop["mails"]) == 2
    before = len(shop["mails"])
    retry(order)
    assert len(shop["mails"]) == before
    assert sum(method == "POST" and path == "/v2/client_invoices" for method, path, *_ in merchant["calls"]) == 1


def test_new_people_after_payment_are_a_separate_batch_and_keep_existing_access(shop, merchant):
    prepare(shop)
    client = shop["client"]
    url = create(client)
    save(shop, url, [person()])
    first = confirm(shop, url)
    run(first)
    mark_paid(merchant)
    retry(first)
    paid = copy.deepcopy(purchases(shop)[0])
    token = learning.access_token(host, paid, paid["learners"][0])
    group = record(shop, url)
    forbidden = save_fields(shop, url, [{**group["learners"][0], "email": "changed@example.test"}])
    assert client.post(url + "/enregistrer", data=forbidden).status_code == 400
    assert record(shop, url) == group

    # The form sends editable rows only; an omitted paid person must stay.
    group = save(shop, url, [person("alex@example.test", "Alex", "Durand")], group_name="APS septembre — complément")
    assert {p["email"] for p in group["learners"]} == {"camille@example.test", "alex@example.test"}
    second = confirm(shop, url)
    assert second["id"] != paid["id"] and second["group_id"] == paid["group_id"]
    assert second["total_cents"] == 5900
    assert [p["email"] for p in second["learners"]] == ["alex@example.test"]
    assert next(o for o in purchases(shop) if o["id"] == paid["id"]) == paid
    assert learning.learner_context(all_data(shop), token)[1]["email"] == "camille@example.test"
    assert not second.get("activated_at") and not learning.entitled(second)


def test_stale_save_and_quote_cannot_overwrite_or_charge_changed_roster(shop, merchant):
    prepare(shop)
    client = shop["client"]
    url = create(client)
    group = save(shop, url, [person()])
    stale_save = save_fields(shop, url, [{**group["learners"][0], "first_name": "Outdated"}])
    stale_quote = quote(client, url)
    updated = save(shop, url, [group["learners"][0], person("alex@example.test", "Alex")])
    assert client.post(url + "/enregistrer", data=stale_save).status_code == 409
    assert record(shop, url) == updated
    assert client.post(url + "/creer-espaces", data=stale_quote).status_code == 409
    assert record(shop, url) == updated
    assert not purchases(shop) and not merchant["calls"]
    order = confirm(shop, url)
    assert len(order["learners"]) == 2 and order["total_cents"] == 11800


def test_tariff_change_requires_review_and_new_total_is_server_priced(shop, merchant):
    pid = prepare(shop)
    client = shop["client"]
    url = create(client)
    save(shop, url, [person()])
    old = quote(client, url)
    host._atomic_update_data(lambda data: host._partner_or_404(data, pid).update(elearning_pricing={"aps": {"unit_cents": 4250}}), partner_id=pid)
    response = client.post(url + "/creer-espaces", data=old)
    assert response.status_code == 409
    assert not purchases(shop) and not merchant["calls"]
    order = confirm(shop, url)
    assert order["unit_cents"] == order["total_cents"] == 4250


def test_unconfigured_price_keeps_group_editable_without_an_order(shop):
    prepare(shop)
    client = shop["client"]
    url = create(client, code="vtc", name="VTC novembre 2026")
    group = save(shop, url, [person()])
    fields = quote(client, url)
    assert client.post(url + "/creer-espaces", data=fields).status_code == 400
    assert not purchases(shop) and record(shop, url) == group
    assert client.get(url).status_code == 200


def test_free_access_still_requires_final_confirmation_and_never_calls_billing(shop, monkeypatch):
    prepare(shop, code="vtc", free=True)
    monkeypatch.setattr(host, "_qonto_request", lambda *a, **kw: pytest.fail("A free batch must not call Qonto"))
    url = create(shop["client"], mode="individual", code="vtc", name="")
    save(shop, url, [person()])
    fields = quote(shop["client"], url)
    assert not purchases(shop) and len(shop["mails"]) == 1
    order = confirm(shop, url, fields)
    assert order["free_snapshot"] is True and order["total_cents"] == 0
    assert not order.get("activated_at")
    run(order)
    paid = purchases(shop)[0]
    assert paid["activated_at"] and learning.entitled(paid)
    assert sum(m["required_minutes"] for m in paid["modules"]) == 105 * 60
    assert sum(m[0][0] == "camille@example.test" for m in shop["mails"]) == 1


def test_group_routes_are_tenant_bound_csrf_protected_and_viewer_read_only(shop):
    prepare(shop)
    client = shop["client"]
    url = create(client)
    save(shop, url, [person()])
    owner_quote = quote(client, url)
    owner_save = save_fields(shop, url, record(shop, url)["learners"])
    original = copy.deepcopy(all_data(shop)["manual_orders"])
    other = host.app.test_client()
    assert signup(other, email="other@example.test").status_code == 303
    login(other, email="other@example.test")
    assert url not in other.get(ROOT).text
    assert other.get(url).status_code == 404
    assert other.get(url + "/recapitulatif").status_code == 404
    other_token = csrf(other, ROOT + "/nouveau")
    for suffix, fields in (("/enregistrer", owner_save), ("/recapitulatif", owner_save), ("/creer-espaces", owner_quote)):
        payload = fields.copy()
        payload["csrf_token"] = other_token
        assert other.post(url + suffix, data=payload).status_code == 404

    for suffix, fields in (("/enregistrer", owner_save), ("/recapitulatif", owner_save), ("/creer-espaces", owner_quote)):
        payload = fields.copy()
        payload.pop("csrf_token")
        assert client.post(url + suffix, data=payload).status_code == 400
    assert client.post(ROOT + "/nouveau", data={"mode": "group", "course_code": "aps"}).status_code == 400
    with client.session_transaction() as session:
        session["admin_role"] = "viewer"
    assert client.get(url).status_code == 200
    for suffix, fields in (("/enregistrer", owner_save), ("/recapitulatif", owner_save), ("/creer-espaces", owner_quote)):
        assert client.post(url + suffix, data=fields).status_code == 403
    assert client.post(ROOT + "/nouveau", data=owner_save).status_code == 403
    assert all_data(shop)["manual_orders"] == original


def test_quote_tampering_and_duplicate_email_never_create_purchase(shop):
    prepare(shop)
    client = shop["client"]
    url = create(client)
    group = save(shop, url, [person()])
    duplicate = save_fields(shop, url, [group["learners"][0], person("CAMILLE@example.test", "Another")])
    assert client.post(url + "/enregistrer", data=duplicate).status_code == 400
    assert record(shop, url) == group
    fields = quote(client, url)
    assert client.post(url + "/creer-espaces", data={**fields, "quote_token": "forged"}).status_code == 400
    assert client.post(url + "/creer-espaces", data={**fields, "request_id": "a" * 32}).status_code == 400
    assert client.post(url + "/creer-espaces", data={**fields, "revision": "999"}).status_code == 400
    assert client.post(url + "/creer-espaces", data={**fields, "confirm": "no"}).status_code == 400
    assert not purchases(shop) and record(shop, url) == group
