"""Sales pause across tenant stores, stale forms and already purchased access."""
import json
from pathlib import Path

import pytest

import app as host
import elearning_orders as learning
import elearning_sales as sales
from test_manuals_shop import shop, csrf, all_data, order_form
from test_manuals_commerce import merchant, run, retry
from test_elearning_orders import send_accesses, prepare, form, latest, submit, mark_paid
from test_elearning_groups import create, save, person, quote, purchases, record


ADMIN = "/admin/commandes-elearning"
ROOT = "/admin/organisme/e-learning"


def admin_client():
    client = host.app.test_client()
    assert client.post("/admin/login", data={"username": "admin@example.test", "password": "platform-test-pass"}).status_code == 302
    return client


def toggle(client, enabled):
    fields = {"csrf_token": csrf(client, ADMIN), "action": "sales_settings"}
    if enabled:
        fields["sales_enabled"] = "yes"
    response = client.post(ADMIN, data=fields)
    assert response.status_code == 303, response.text
    assert sales.enabled(host) is enabled


def test_admin_switch_persists_without_changing_prices_or_tenant_records(shop):
    pid = prepare(shop)
    admin = admin_client()
    assert sales.enabled(host)
    assert 'name="sales_enabled" value="yes" checked' in admin.get(ADMIN).text
    before = all_data(shop)
    toggle(admin, False)
    settings = json.loads(sales.settings_path(host).read_text())
    assert settings["enabled"] is False and settings["updated_at"]
    assert all_data(shop) == before
    assert "Ventes suspendues" in admin.get(ADMIN).text
    # Changing billing/prices must not accidentally reopen the shop.
    assert admin.post(ADMIN, data={"csrf_token": csrf(admin, ADMIN), "partner_id": pid,
                                  "aps_price": "55", "vtc_price": "150"}).status_code == 303
    assert not sales.enabled(host)
    assert "Ventes suspendues" in admin_client().get(ADMIN).text
    toggle(admin, True)
    assert 'name="sales_enabled" value="yes" checked' in admin.get(ADMIN).text


def test_only_platform_admin_with_valid_csrf_can_toggle(shop):
    prepare(shop)
    fields = {"action": "sales_settings", "csrf_token": csrf(shop["client"], ROOT)}
    assert shop["client"].post(ADMIN, data=fields).status_code == 403
    assert host.app.test_client().post(ADMIN, data=fields).status_code in {302, 401}
    admin = admin_client()
    assert admin.post(ADMIN, data={"action": "sales_settings"}).status_code == 400
    assert admin.post(ADMIN, data={"action": "sales_settings", "csrf_token": "invalid"}).status_code == 400
    assert sales.enabled(host)


@pytest.mark.parametrize("code", ["aps", "mac-aps", "vtc"])
def test_stale_direct_orders_blocked_and_reopen_without_losing_drafts(shop, merchant, code):
    prepare(shop)
    client = shop["client"]
    fields = form(client, course_code=code)
    draft_url = client.post(ROOT + "/recapitulatif", data=fields).location
    confirmation = {"csrf_token": csrf(client, draft_url), "confirm": "yes", "terms_version": "2026-10-12"}
    admin = admin_client()
    toggle(admin, False)
    before, mails = all_data(shop), len(shop["mails"])
    for path, payload in [(ROOT + "/recapitulatif", fields), (draft_url + "/confirmer", confirmation)]:
        response = client.post(path, data=payload)
        assert response.status_code == 409 and sales.TITLE in response.text
    assert all_data(shop) == before and len(shop["mails"]) == mails
    assert not merchant["calls"] and latest(shop)["status"] == "draft"
    assert "Votre brouillon est conservé" in client.get(draft_url).text
    toggle(admin, True)
    assert client.post(draft_url + "/confirmer", data=confirmation).status_code == 303
    assert latest(shop)["status"] == "received"


def test_stale_group_quote_and_creation_blocked_but_rosters_remain_editable(shop, merchant):
    prepare(shop)
    client = shop["client"]
    url = create(client)
    save(shop, url, [person()])
    quoted = quote(client, url)
    from test_elearning_groups import HiddenFields
    creation = HiddenFields(client.get(ROOT + "/nouveau").text).fields
    creation.update(course_code="aps", mode="individual", group_name="")
    admin = admin_client()
    toggle(admin, False)
    before = all_data(shop)
    for response in [client.get(ROOT + "/nouveau"), client.post(ROOT + "/nouveau", data=creation),
                     client.get(url + "/recapitulatif"), client.post(url + "/creer-espaces", data=quoted)]:
        assert response.status_code == 409 and sales.TITLE in response.text
    assert all_data(shop) == before and not purchases(shop) and not merchant["calls"]
    assert 'data-sales-paused="true"' in client.get(url).text
    learner = record(shop, url)["learners"][0]
    save(shop, url, [{**learner, "first_name": "Camille corrigée"}])
    toggle(admin, True)
    response = client.post(url + "/creer-espaces", data=quote(client, url))
    assert response.status_code == 303 and len(purchases(shop)) == 1


def test_public_and_customer_pages_show_pause_without_disabling_other_products(shop):
    prepare(shop)
    admin = admin_client()
    toggle(admin, False)
    public = host.app.test_client()
    for path in ["/", "/e-learning", "/e-learning/aps", "/e-learning/mac-aps", "/e-learning/vtc"]:
        response = public.get(path)
        assert response.status_code == 200
        assert sales.TITLE in response.text and sales.MESSAGE in response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert '/e-learning/nouveau' not in response.text
    for path in ["/admin/organisme", ROOT, ROOT + "?view=catalogue"]:
        response = shop["client"].get(path)
        assert response.status_code == 200 and sales.TITLE in response.text
        assert '/e-learning/nouveau' not in response.text
    for path in ["/manuels", "/supports-formateurs"]:
        assert public.get(path).status_code == 200
    response = shop["client"].post("/admin/manuels/recapitulatif", data=order_form(shop["client"]))
    assert response.status_code == 303
    toggle(admin, True)
    assert sales.TITLE not in public.get("/e-learning").text


def test_existing_payment_and_learner_access_continue_during_pause(shop, merchant):
    order = submit(shop)
    run(order)
    toggle(admin_client(), False)
    mark_paid(merchant)
    retry(order)
    order = latest(shop)
    assert learning.entitled(order) and not order.get("activated_at")
    order = send_accesses(shop, order)
    assert order["activated_at"]
    url = ROOT + "/commandes/" + order["id"]
    assert shop["client"].get(url).status_code == 200
    assert shop["client"].get(url + "/statut").json["active"]
    assert shop["client"].get(url + "/facture").status_code == 200
    token = learning.access_token(host, order, order["learners"][0])
    assert learning.learner_context(all_data(shop), token)[1]
    learner_page = host.app.test_client().get("/apprendre/" + token)
    assert learner_page.status_code == 200 and sales.TITLE not in learner_page.text


def test_corrupt_setting_fails_closed_and_admin_can_restore(shop):
    sales.settings_path(host).write_text("{broken")
    assert not sales.enabled(host)
    toggle(admin_client(), True)
    assert sales.enabled(host)
