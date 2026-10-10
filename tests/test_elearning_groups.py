"""Persistent rosters and payment batches, using both supported tenant stores.

Exercise the customer HTTP workflow and the real merchant worker with an
in-memory Qonto substitute. No bill or learner email reaches a real provider.
"""
import copy
import json
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict

import app as host
import elearning_orders as learning
from test_elearning_orders import mark_paid, prepare
from test_manuals_commerce import merchant, retry, run
from test_manuals_shop import all_data, csrf, login, shop, signup


ROOT = "/admin/organisme/e-learning"


class HiddenFields(HTMLParser):
    def __init__(self, html, *, include_visible=False):
        super().__init__()
        self.fields = {}
        self.include_visible = include_visible
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "input" and (self.include_visible or values.get("type") == "hidden") and values.get("name"):
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
    manifest = json.loads((Path(learning.__file__).parent / "elearning_native/vtc/manifest.json").read_text())
    assert [(m["course_id"], m["course_version"], m["required_minutes"]) for m in paid["modules"]] == [
        (m["id"], m["version"], m["planned_minutes"]) for m in manifest["modules"]]
    assert sum(m["required_minutes"] for m in paid["modules"]) == manifest["planned_minutes"]
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


def deletion_fields(shop, url):
    return {"csrf_token": csrf(shop["client"], url), "revision": str(record(shop, url)["revision"]), "confirm": "yes"}


@pytest.mark.parametrize("mode", ["group", "individual"])
def test_delete_saved_preparation_removes_it_from_customer_views_and_invalidates_old_quote(shop, merchant, mode):
    prepare(shop)
    client = shop["client"]
    url = create(client, mode=mode, name="À supprimer")
    save(shop, url, [person()])
    old_quote = quote(client, url)
    response = client.post(url + "/supprimer", data=deletion_fields(shop, url))
    assert response.status_code == 303
    assert record(shop, url).get("deleted_at")
    assert url not in client.get(ROOT).text
    assert client.get(url).status_code == 404
    assert client.get(url + "/recapitulatif").status_code == 404
    assert client.post(url + "/creer-espaces", data=old_quote).status_code == 404
    assert not purchases(shop) and not merchant["calls"]
    assert len(shop["mails"]) == 1


def test_delete_unbilled_confirmed_batch_stops_queued_activation_and_billing(shop, merchant):
    prepare(shop)
    client = shop["client"]
    url = create(client)
    save(shop, url, [person()])
    order = confirm(shop, url)
    assert order["commerce"]["queued"] and not order["commerce"].get("invoice_id")
    assert client.post(url + "/supprimer", data=deletion_fields(shop, url)).status_code == 303
    cancelled = next(o for o in purchases(shop) if o["id"] == order["id"])
    assert cancelled["status"] == "cancelled" and not cancelled["commerce"]["queued"]
    assert record(shop, url).get("deleted_at")
    run(order)
    retry(order)
    assert not merchant["calls"] and not purchases(shop)[0].get("activated_at")
    assert len(shop["mails"]) == 1


def test_delete_never_wins_over_existing_worker_lease_or_newer_group_revision(shop, merchant):
    prepare(shop)
    client = shop["client"]
    url = create(client)
    group = save(shop, url, [person()])
    stale = deletion_fields(shop, url)
    order = confirm(shop, url)
    assert client.post(url + "/supprimer", data=stale).status_code == 409
    assert not record(shop, url).get("deleted_at")

    def lease(data):
        stored = next(o for o in data["manual_orders"] if o["id"] == order["id"])
        stored["commerce"].update(lease_token="working-now", lease_until=time.time() + 600, status="processing")
    host._atomic_update_data(lease, partner_id=group["partner_id"])
    before = copy.deepcopy(purchases(shop)[0])
    assert client.post(url + "/supprimer", data=deletion_fields(shop, url)).status_code == 409
    assert purchases(shop)[0] == before
    assert not record(shop, url).get("deleted_at") and not merchant["calls"]


@pytest.mark.parametrize("state", ["paid", "active", "active_cancelled"])
def test_paid_or_ever_activated_group_cannot_be_deleted(shop, merchant, state):
    prepare(shop)
    client = shop["client"]
    url = create(client)
    save(shop, url, [person()])
    order = confirm(shop, url)
    run(order)
    mark_paid(merchant)
    if state == "paid":
        def paid_without_activation(data):
            stored = next(o for o in data["manual_orders"] if o["id"] == order["id"])
            stored["commerce"].update(invoice_status="paid", payment_status="paid", paid_cents=stored["total_cents"], remaining_cents=0)
        host._atomic_update_data(paid_without_activation, partner_id=order["partner_id"])
    else:
        retry(order)
        if state == "active_cancelled":
            host._atomic_update_data(lambda data: next(o for o in data["manual_orders"] if o["id"] == order["id"]).update(status="cancelled"), partner_id=order["partner_id"])
    before = copy.deepcopy(purchases(shop)[0])
    calls = len(merchant["calls"])
    assert client.post(url + "/supprimer", data=deletion_fields(shop, url)).status_code == 409
    assert not record(shop, url).get("deleted_at")
    assert purchases(shop)[0] == before and len(merchant["calls"]) == calls
    assert client.get(url).status_code == 200


def test_delete_is_tenant_bound_csrf_protected_and_viewer_read_only(shop):
    prepare(shop)
    client = shop["client"]
    url = create(client)
    fields = deletion_fields(shop, url)
    before = copy.deepcopy(record(shop, url))
    other = host.app.test_client()
    assert signup(other, email="other@example.test").status_code == 303
    login(other, email="other@example.test")
    assert other.post(url + "/supprimer", data={**fields, "csrf_token": csrf(other, ROOT + "/nouveau")}).status_code == 404
    assert client.post(url + "/supprimer", data={**fields, "csrf_token": "wrong"}).status_code == 400
    assert client.post(url + "/supprimer", data={**fields, "confirm": "no"}).status_code == 400
    with client.session_transaction() as state:
        state["admin_role"] = "viewer"
    assert client.post(url + "/supprimer", data=fields).status_code == 403
    assert record(shop, url) == before


def billing_fields(client, url):
    response = client.get(url + "/recapitulatif")
    assert response.status_code == 200
    fields = HiddenFields(response.text, include_visible=True).fields
    return {key: fields.get(key, "") for key in ("address", "postal_code", "city")}


def test_next_preparation_prefills_prior_order_billing_after_relogin(shop):
    prepare(shop)
    client = shop["client"]
    first = create(client)
    save(shop, first, [person()])
    known = {"address": "18 avenue de l'École", "postal_code": "83480", "city": "Puget-sur-Argens"}
    confirm(shop, first, {**quote(client, first), **known})
    client.get("/admin/logout")
    login(client)
    next_group = create(client, name="APS octobre 2026")
    save(shop, next_group, [person("alex@example.test", "Alex")])
    assert billing_fields(client, next_group) == known


@pytest.mark.parametrize("source", ["billing", "delivery"])
def test_billing_uses_latest_complete_own_placed_order_then_group_overrides(shop, source):
    pid = prepare(shop)
    client = shop["client"]
    url = create(client)
    save(shop, url, [person()])
    own = {"address": "2 rue Facturation", "postal_code": "69001", "city": "Lyon"}
    wrong = {"address": "Private other centre", "postal_code": "99999", "city": "Other"}
    def seed(data):
        host._partner_or_404(data, pid).update(address="Old profile", postal_code="75001", city="Paris")
        orders = data.setdefault("manual_orders", [])
        orders.extend([
            {"id": "previous-own", "partner_id": pid, "order_type": "manuals", "status": "received", "created_at": "2026-01-02T10:00:00Z", source: copy.deepcopy(own)},
            {"id": "newer-incomplete", "partner_id": pid, "order_type": "manuals", "status": "received", "created_at": "2026-02-02T10:00:00Z", "billing": {"address": "Incomplete"}},
            {"id": "newer-draft", "partner_id": pid, "order_type": "manuals", "status": "draft", "created_at": "2026-03-02T10:00:00Z", "billing": copy.deepcopy(wrong)},
            {"id": "newer-cancelled", "partner_id": pid, "order_type": "manuals", "status": "cancelled", "created_at": "2026-04-02T10:00:00Z", "billing": copy.deepcopy(wrong)},
        ])
    host._atomic_update_data(seed, partner_id=pid)
    assert billing_fields(client, url) == own
    def override(data):
        next(o for o in data["manual_orders"] if o["id"] == url.rsplit("/", 1)[-1])["billing"] = {"address": "Adresse de ce groupe"}
    host._atomic_update_data(override, partner_id=pid)
    assert billing_fields(client, url) == {**own, "address": "Adresse de ce groupe"}
    fields = {**quote(client, url), "address": "", "postal_code": "", "city": ""}
    response = client.post(url + "/creer-espaces", data=fields)
    assert response.status_code == 400
    posted = HiddenFields(response.text, include_visible=True).fields
    assert all(posted[key] == "" for key in ("address", "postal_code", "city"))


def test_previous_billing_never_leaks_across_organisms(shop):
    pid = prepare(shop)
    client = shop["client"]
    own = create(client)
    save(shop, own, [person()])
    private = {"address": "Adresse privée du premier organisme", "postal_code": "83480", "city": "Puget-sur-Argens"}
    confirm(shop, own, {**quote(client, own), **private})
    other = host.app.test_client()
    assert signup(other, email="other@example.test").status_code == 303
    login(other, email="other@example.test")
    shop["client"] = other
    other_group = create(other)
    save(shop, other_group, [person("other-learner@example.test", "Other")])
    assert billing_fields(other, other_group) == {"address": "", "postal_code": "", "city": ""}


def cancellation_provider(monkeypatch, merchant, *, lose_cancel_response=False):
    """Extend the existing isolated merchant with the two cancellation calls."""
    original = host._qonto_request
    state = {"lost": False}
    def request(method, path, payload=None, params=None, **kwargs):
        if method == "PATCH" and path == "/v2/payment_links/link-1/deactivate":
            assert not host.has_request_context()
            merchant["calls"].append((method, path, copy.deepcopy(payload), copy.deepcopy(params), kwargs))
            merchant["payment"]["status"] = "canceled"
            return {"payment_link": copy.deepcopy(merchant["payment"])}
        if method == "POST" and path == "/v2/client_invoices/invoice-1/mark_as_canceled":
            assert not host.has_request_context()
            merchant["calls"].append((method, path, copy.deepcopy(payload), copy.deepcopy(params), kwargs))
            merchant["invoice"]["status"] = "canceled"
            if lose_cancel_response and not state["lost"]:
                state["lost"] = True
                raise RuntimeError("Provider accepted cancellation before response timeout")
            return {"client_invoice": copy.deepcopy(merchant["invoice"])}
        return original(method, path, payload=payload, params=params, **kwargs)
    monkeypatch.setattr(host, "_qonto_request", request)
    return state


def billed_group(shop, merchant):
    prepare(shop)
    url = create(shop["client"])
    save(shop, url, [person()])
    order = confirm(shop, url)
    run(order)
    return url, next(o for o in purchases(shop) if o["id"] == order["id"])


def test_invoiced_group_is_visible_until_remote_invoice_and_payment_link_are_cancelled(shop, merchant, monkeypatch):
    url, order = billed_group(shop, merchant)
    cancellation_provider(monkeypatch, merchant)
    before_calls = len(merchant["calls"])
    response = shop["client"].post(url + "/supprimer", data=deletion_fields(shop, url))
    assert response.status_code == 303
    assert len(merchant["calls"]) == before_calls  # Provider calls stay outside HTTP requests.
    assert record(shop, url).get("deletion_requested_at") and not record(shop, url).get("deleted_at")
    assert shop["client"].get(url).status_code == 200
    assert url in shop["client"].get(ROOT).text
    assert purchases(shop)[0].get("cancellation_requested_at")
    run(order)
    cancelled = purchases(shop)[0]
    assert cancelled["status"] == "cancelled" and not cancelled["commerce"]["queued"]
    assert record(shop, url).get("deleted_at") and shop["client"].get(url).status_code == 404
    assert merchant["invoice"]["status"] == merchant["payment"]["status"] == "canceled"
    assert cancelled["commerce"]["invoice_id"] == order["commerce"]["invoice_id"]
    for key in ("learners", "modules", "billing", "total_cents", "reference"):
        assert cancelled[key] == order[key]
    assert not cancelled.get("activated_at")
    assert not any(m[0][0] == "camille@example.test" for m in shop["mails"])


@pytest.mark.parametrize("state", ["paid_invoice", "partial_invoice", "pending_payment", "malformed_payments"])
def test_deletion_rechecks_provider_and_refuses_settled_or_in_flight_money(shop, merchant, monkeypatch, state):
    url, order = billed_group(shop, merchant)
    cancellation_provider(monkeypatch, merchant)
    assert shop["client"].post(url + "/supprimer", data=deletion_fields(shop, url)).status_code == 303
    if state == "paid_invoice":
        mark_paid(merchant)
    elif state == "partial_invoice":
        merchant["invoice"].update(paid_amount={"value": "1.00", "currency": "EUR"})
    elif state == "pending_payment":
        merchant["payments"] = [{"id": "attempt-pending", "status": "pending", "amount": copy.deepcopy(merchant["payment"]["amount"])}]
    else:
        original = host._qonto_request
        def malformed(method, path, *args, **kwargs):
            if method == "GET" and path.endswith("/payments"):
                merchant["calls"].append((method, path, None, None, {}))
                return {}  # Unknown provider response must not mean no payments.
            return original(method, path, *args, **kwargs)
        monkeypatch.setattr(host, "_qonto_request", malformed)
    run(order)
    current = purchases(shop)[0]
    assert not record(shop, url).get("deleted_at") and shop["client"].get(url).status_code == 200
    assert current["status"] != "cancelled"
    assert not any(path.endswith("/deactivate") or path.endswith("/mark_as_canceled") for _, path, *_ in merchant["calls"])
    assert not current.get("activated_at")
    assert not any(m[0][0] == "camille@example.test" for m in shop["mails"])


def test_lost_cancellation_response_keeps_group_until_provider_state_is_reconciled(shop, merchant, monkeypatch):
    url, order = billed_group(shop, merchant)
    state = cancellation_provider(monkeypatch, merchant, lose_cancel_response=True)
    assert shop["client"].post(url + "/supprimer", data=deletion_fields(shop, url)).status_code == 303
    run(order)
    assert state["lost"]
    assert not record(shop, url).get("deleted_at")
    assert purchases(shop)[0]["commerce"]["queued"]
    assert shop["client"].get(url).status_code == 200
    before_calls = len(merchant["calls"])
    retry(order)
    assert len(merchant["calls"]) == before_calls  # A customer refresh cannot bypass cancellation scheduling.
    next_attempt = purchases(shop)[0]["commerce"]["next_attempt"]
    monkeypatch.setattr(time, "time", lambda: next_attempt + 1)
    run(order)
    assert record(shop, url).get("deleted_at")
    assert purchases(shop)[0]["status"] == "cancelled"
    assert sum(path.endswith("/mark_as_canceled") for _, path, *_ in merchant["calls"]) == 1
    assert not purchases(shop)[0].get("activated_at")


@pytest.mark.parametrize("marker", ["invoice_creation_started", "payment_creation_started"])
def test_expired_lease_with_unknown_provider_result_never_deletes_as_an_unbilled_order(shop, merchant, marker):
    prepare(shop)
    url = create(shop["client"])
    save(shop, url, [person()])
    order = confirm(shop, url)
    def interrupted(data):
        current = next(o for o in data["manual_orders"] if o["id"] == order["id"])
        current["commerce"].update({marker: host._now_iso(), "lease_token": "expired-worker", "lease_until": time.time() - 1})
    host._atomic_update_data(interrupted, partner_id=order["partner_id"])
    assert shop["client"].post(url + "/supprimer", data=deletion_fields(shop, url)).status_code == 303
    assert record(shop, url).get("deletion_requested_at") and not record(shop, url).get("deleted_at")
    run(order)
    current = purchases(shop)[0]
    assert current["status"] != "cancelled" and current["commerce"]["queued"]
    assert not record(shop, url).get("deleted_at")
    assert shop["client"].get(url).status_code == 200
    assert not any(method in {"POST", "PATCH", "DELETE"} for method, *_ in merchant["calls"])
    assert not current.get("activated_at") and len(shop["mails"]) == 1


def test_multiple_batches_cancel_in_sequence_and_a_late_payment_preserves_the_group(shop, merchant, monkeypatch):
    url, first = billed_group(shop, merchant)
    invoices = {"invoice-1": copy.deepcopy(merchant["invoice"])}
    links = {"link-1": copy.deepcopy(merchant["payment"])}
    save(shop, url, [person("alex@example.test", "Alex", "Durand")])
    second = confirm(shop, url)
    # The shared merchant fixture represents one provider object. Give this
    # second real workflow a separate provider namespace for the race scenario.
    merchant.update(invoice=None, payment=None)
    run(second)
    invoices["invoice-2"] = {**copy.deepcopy(merchant["invoice"]), "id": "invoice-2"}
    links["link-2"] = {**copy.deepcopy(merchant["payment"]), "id": "link-2", "invoice_id": "invoice-2"}
    def identify_second(data):
        current = next(o for o in data["manual_orders"] if o["id"] == second["id"])
        current["commerce"].update(invoice_id="invoice-2", payment_id="link-2")
    host._atomic_update_data(identify_second, partner_id=second["partner_id"])
    original = host._qonto_request
    def provider(method, path, payload=None, params=None, **kwargs):
        pieces = path.strip("/").split("/")
        collection = invoices if len(pieces) >= 3 and pieces[1] == "client_invoices" else links
        resource = collection.get(pieces[2]) if len(pieces) >= 3 else None
        if resource is not None:
            assert not host.has_request_context()
            merchant["calls"].append((method, path, copy.deepcopy(payload), copy.deepcopy(params), kwargs))
            if len(pieces) == 3 and method == "GET":
                return {"client_invoice": copy.deepcopy(resource)} if collection is invoices else copy.deepcopy(resource)
            if pieces[-1] == "payments" and method == "GET":
                return {"payments": [], "meta": {"total_pages": 1}}
            if pieces[-1] == "deactivate" and method == "PATCH":
                resource["status"] = "canceled"
                return {"payment_link": copy.deepcopy(resource)}
            if pieces[-1] == "mark_as_canceled" and method == "POST":
                resource["status"] = "canceled"
                return {"client_invoice": copy.deepcopy(resource)}
            raise AssertionError((method, path))
        return original(method, path, payload=payload, params=params, **kwargs)
    monkeypatch.setattr(host, "_qonto_request", provider)

    assert shop["client"].post(url + "/supprimer", data=deletion_fields(shop, url)).status_code == 303
    batches = purchases(shop)
    queued = [order for order in batches if order["commerce"]["queued"]]
    assert len(queued) == 1
    processing = queued[0]
    waiting = next(order for order in batches if order["id"] != processing["id"])
    before_calls = len(merchant["calls"])
    run(waiting)
    retry(waiting)
    assert len(merchant["calls"]) == before_calls

    run(processing)
    assert next(order for order in purchases(shop) if order["id"] == processing["id"])["status"] == "cancelled"
    waiting = next(order for order in purchases(shop) if order["id"] == waiting["id"])
    assert waiting["commerce"]["queued"] and not record(shop, url).get("deleted_at")
    invoice = invoices[waiting["commerce"]["invoice_id"]]
    invoice.update(status="paid", paid_amount=copy.deepcopy(invoice["total_amount"]), paid_at="2026-10-10")
    run(waiting)
    group = record(shop, url)
    paid = next(order for order in purchases(shop) if order["id"] == waiting["id"])
    assert not group.get("deleted_at") and not group.get("deletion_requested_at")
    assert paid["status"] != "cancelled" and not paid.get("cancellation_requested_at")
    assert paid["commerce"]["invoice_status"] == "paid" and paid["commerce"]["queued"]
    assert shop["client"].get(url).status_code == 200

    # Paid learners resume the normal access workflow; the cancelled batch's
    # roster can once again be prepared without altering the paid enrolment.
    run(paid)
    activated = next(order for order in purchases(shop) if order["id"] == paid["id"])
    assert activated["activated_at"] and learning.entitled(activated)
    token = learning.access_token(host, activated, activated["learners"][0])
    assert learning.learner_context(all_data(shop), token)[1]["id"] == activated["learners"][0]["id"]
    remaining = {p["id"] for p in processing["learners"]}
    quoted = confirm(shop, url)
    assert {p["id"] for p in quoted["learners"]} == remaining
