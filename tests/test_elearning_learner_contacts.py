"""Contact corrections use real partner transactions and mocked mail delivery."""
import copy
import time

import pytest
from lxml import html

import app as host
import elearning_orders as learning
import manuals_commerce as commerce
from test_elearning_groups import create, save, person, confirm, record, save_fields
from test_elearning_orders import prepare, submit, latest, send_accesses, mark_paid
from test_elearning_reporting import activated, seed_course, tracked, database_dump
from test_manuals_commerce import run, retry, merchant
from test_manuals_shop import shop, csrf, all_data, signup, login
from test_partner_workspace import as_admin


def contact_url(record, learner=None):
    return f"/admin/organisme/e-learning/dossiers/{record['id']}/stagiaires/{(learner or record['learners'][0])['id']}/contact"


def fields(client, record, *, action="save_email", email="corrected@example.test", **extra):
    # CSRF can be obtained from either administrator or partner form.
    with client.session_transaction() as state:
        state.setdefault("manuals_csrf", "contact-test-csrf")
        token = state["manuals_csrf"]
    return {"csrf_token": token, "action": action, "email": email,
            "expected_email": record["learners"][0]["email"], **extra}


def edit(shop, order, **extra):
    return shop["client"].post(contact_url(order), data=fields(shop["client"], order, **extra))


@pytest.mark.parametrize("admin", [False, True])
def test_correction_resends_one_link_revokes_wrong_recipient_and_keeps_progress(shop, admin):
    order, root = seed_course(activated(shop))
    tracked(root, order)
    before_progress = database_dump(root)
    before_mails = len(shop["mails"])
    old_link = learning.access_token(host, order, order["learners"][0])
    if admin:
        as_admin(shop["client"])
    response = edit(shop, order, email="  Corrected@Example.Test  ", return_to="partner" if admin else "order")
    assert response.status_code == 303
    if admin:
        assert f"/admin/partners/{order['partner_id']}?tab=learning" in response.location
    corrected = latest(shop)
    assert corrected["learners"][0]["email"] == "corrected@example.test"
    assert corrected["learners"][0]["id"] == order["learners"][0]["id"]
    assert corrected["learners"][0]["activated_at"] == order["learners"][0]["activated_at"]
    assert corrected["learners"][1] == order["learners"][1]
    for key in ("modules", "items", "total_cents", "unit_cents", "billing", "centre"):
        assert corrected[key] == order[key]
    new_link = learning.access_token(host, corrected, corrected["learners"][0])
    assert new_link != old_link
    assert learning.learner_context(all_data(shop), old_link) == (None, None)
    assert learning.learner_context(all_data(shop), new_link)[1]["id"] == order["learners"][0]["id"]
    assert len(shop["mails"]) == before_mails
    run(corrected)
    sent = shop["mails"][before_mails:]
    assert len(sent) == 1 and sent[0][0][0] == "corrected@example.test"
    assert new_link in sent[0][0][2] and old_link not in sent[0][0][2]
    assert latest(shop)["commerce"]["emails"]["learner_" + order["learners"][0]["id"]]["status"] == "sent"
    assert database_dump(root) == before_progress
    run(corrected)
    assert len(shop["mails"]) == before_mails + 1


def test_resend_without_change_is_throttled_and_preserves_link(shop):
    order = activated(shop)
    before = len(shop["mails"])
    old_link = learning.access_token(host, order, order["learners"][0])
    assert edit(shop, order, action="resend").status_code == 303
    assert edit(shop, order, action="resend").status_code == 303
    run(order)
    assert edit(shop, order, action="resend").status_code == 303
    run(order)
    assert len(shop["mails"]) == before + 1
    assert shop["mails"][-1][0][0] == order["learners"][0]["email"]
    assert learning.access_token(host, latest(shop), latest(shop)["learners"][0]) == old_link


def test_failed_individual_delivery_is_retried_without_resending_other_people(shop, monkeypatch):
    order = activated(shop)
    before = len(shop["mails"])
    sender = host.brevo_send_email
    assert edit(shop, order).status_code == 303
    monkeypatch.setattr(host, "brevo_send_email", lambda *a, **k: {"ok": False})
    run(order)
    pending = latest(shop)
    key = "learner_" + order["learners"][0]["id"]
    assert pending["commerce"]["queued"] and pending["commerce"]["emails"][key]["status"] == "failed"
    assert pending["learners"][0]["email"] == "corrected@example.test"
    monkeypatch.setattr(host, "brevo_send_email", sender)
    retry(order)
    assert len(shop["mails"]) == before + 1
    assert latest(shop)["commerce"]["emails"][key]["status"] == "sent"


def test_legacy_individual_resend_does_not_activate_or_send_other_people(shop):
    order = activated(shop)
    def legacy(current):
        current.pop("access_dispatch_requested_at")
        current.pop("activated_at")
        other = current["learners"][1]
        other.pop("activated_at")
        current["commerce"]["emails"].pop("learner_" + other["id"])
    commerce._mutate(host, order["partner_id"], order["id"], legacy)
    before = len(shop["mails"])
    assert edit(shop, order, action="resend").status_code == 303
    run(order)
    assert len(shop["mails"]) == before + 1
    assert not latest(shop)["learners"][1].get("activated_at")
    assert not latest(shop).get("access_dispatch_requested_at")


def test_invalid_duplicate_stale_and_inflight_requests_do_not_change_data(shop):
    order = activated(shop)
    before = copy.deepcopy(all_data(shop))
    for extra in ({"email": "invalid"}, {"email": "a@b.test\nBcc: bad@c.test"},
                  {"email": "ALEX@example.test"}, {"expected_email": "stale@example.test"}):
        assert edit(shop, order, **extra).status_code == 303
        assert all_data(shop) == before
    commerce._mutate(host, order["partner_id"], order["id"], lambda current: current["commerce"].update(lease_until=time.time() + 60))
    before = copy.deepcopy(all_data(shop))
    assert edit(shop, order).status_code == 303
    assert all_data(shop) == before


def test_unpaid_contact_can_change_but_cannot_send_or_change_billing(shop, merchant):
    order = submit(shop)
    run(order)
    before = latest(shop)
    assert edit(shop, order, action="resend").status_code == 303
    assert latest(shop) == before
    assert edit(shop, order).status_code == 303
    current = latest(shop)
    assert current["learners"][0]["email"] == "corrected@example.test"
    assert current["commerce"] == before["commerce"]
    assert not current.get("activated_at") and not current.get("access_dispatch_requested_at")
    mark_paid(merchant)
    retry(order)
    send_accesses(shop, latest(shop))
    recipients = [args[0] for args, _ in shop["mails"]]
    assert "corrected@example.test" in recipients and "camille@example.test" not in recipients


def test_group_roster_and_order_stay_in_sync_and_stale_roster_cannot_overwrite(shop):
    prepare(shop, free=True)
    group_url = create(shop["client"])
    save(shop, group_url, [person(), person("alex@example.test", "Alex", "Durand")])
    order = confirm(shop, group_url)
    run(order)
    order = send_accesses(shop, order)
    stale_fields = save_fields(shop, group_url, [])
    revision = record(shop, group_url)["revision"]
    assert edit(shop, order, return_to="group").location == group_url
    group = record(shop, group_url)
    assert group["learners"][0]["email"] == "corrected@example.test"
    assert group["revision"] == revision + 1
    assert record(shop, "/" + order["id"])["learners"][0]["email"] == "corrected@example.test"
    assert shop["client"].post(group_url + "/enregistrer", data=stale_fields).status_code == 409
    # A forged group request must not bypass the canonical paid enrolment.
    before = copy.deepcopy(all_data(shop))
    assert edit(shop, group, email="bypass@example.test").status_code == 303
    assert all_data(shop) == before
    page = shop["client"].get(group_url)
    assert "Modifier l’e-mail" in page.text and "Renvoyer le lien" in page.text
    assert "Pour corriger les coordonnées" not in page.text
    assert not html.fromstring(page.text).xpath("//form//form")


def test_admin_can_correct_unordered_group_learner_without_dispatch(shop):
    prepare(shop, free=True)
    group_url = create(shop["client"])
    group = save(shop, group_url, [person()])
    as_admin(shop["client"])
    assert edit(shop, group, return_to="partner").status_code == 303
    current = record(shop, group_url)
    assert current["learners"][0]["email"] == "corrected@example.test"
    assert not current.get("commerce") and not current.get("access_dispatch_requested_at")


def test_csrf_viewer_tenant_and_assistance_boundaries(shop):
    order = activated(shop)
    client = shop["client"]
    before = copy.deepcopy(all_data(shop)["manual_orders"])
    assert client.post(contact_url(order), data={"action": "resend"}).status_code == 400
    assert client.get(contact_url(order)).status_code in {302, 405}
    with client.session_transaction() as state:
        state["admin_role"] = "viewer"
    assert edit(shop, order).status_code == 403
    page = client.get("/admin/organisme/e-learning/commandes/" + order["id"])
    assert "Modifier l’e-mail" not in page.text and "Renvoyer le lien" not in page.text
    other = host.app.test_client()
    assert signup(other, email="other-contact@example.test").status_code == 303
    login(other, email="other-contact@example.test")
    assert other.post(contact_url(order), data=fields(other, order, partner_id=order["partner_id"])).status_code == 404
    other_pid = next(p["id"] for p in all_data(shop)["partners"] if p.get("email") == "other-contact@example.test")
    as_admin(client)
    with client.session_transaction() as state:
        state["assist_partner_id"] = other_pid
    assert edit(shop, order).status_code == 404
    assert all_data(shop)["manual_orders"] == before


def test_admin_roster_renders_forms_and_cancelled_order_cannot_be_edited(shop):
    order = activated(shop)
    as_admin(shop["client"])
    url = f"/admin/partners/{order['partner_id']}/learning/order/{order['id']}"
    response = shop["client"].get(url)
    assert response.status_code == 200
    doc = html.fromstring(response.text)
    assert len(doc.xpath("//form[input[@name='action' and @value='resend']]")) == 2
    assert len(doc.xpath("//form[input[@name='action' and @value='save_email']]")) == 2
    assert not doc.xpath("//form//form")
    commerce._mutate(host, order["partner_id"], order["id"], lambda current: current.update(status="cancelled"))
    before = copy.deepcopy(all_data(shop))
    assert edit(shop, order).status_code == 303
    assert all_data(shop) == before
    assert "Modifier l’e-mail" not in shop["client"].get(url).text
