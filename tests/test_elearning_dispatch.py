"""Explicit centre dispatch after verified payment; no real messages or bills."""
import copy
import re
import time

import pytest

import app as host
import elearning_orders as learning
import manuals_commerce as commerce
from test_elearning_orders import submit, latest, mark_paid, send_accesses, prepare
from test_elearning_groups import create, save, person, confirm
from test_manuals_commerce import merchant, run, retry
from test_manuals_shop import shop, csrf, all_data, signup, login


ROOT = "/admin/organisme/e-learning/commandes/"


def post_dispatch(client, order, **extra):
    url = ROOT + order["id"]
    return client.post(url + "/envoyer-acces", data={"csrf_token": csrf(client, url), **extra})


def learner_mails(shop, order):
    recipients = {p["email"] for p in order["learners"]}
    return [mail for mail in shop["mails"] if mail[0][0] in recipients]


@pytest.mark.parametrize("code", ["aps", "mac-aps", "a3p", "vtc"])
def test_payment_and_refresh_never_dispatch_until_explicit_post(shop, merchant, code):
    order = submit(shop, code=code)
    client = shop["client"]
    url = ROOT + order["id"]
    run(order)
    page = client.get(url)
    button = re.search(r'<button[^>]*>Envoyer les accès e-learning aux stagiaires</button>', page.text)
    assert button and "disabled" in button.group()
    assert post_dispatch(client, order, paid="true", free_snapshot="true").status_code == 409
    assert not latest(shop).get("access_dispatch_requested_at")
    mark_paid(merchant)
    retry(order)
    # Return parameters, page visits and payment retries cannot request a send.
    client.get(url + "?paid=true&send_accesses=yes")
    retry(order)
    current = latest(shop)
    assert learning.entitled(current) and not current.get("activated_at")
    assert not learner_mails(shop, order)
    assert current["commerce"]["lease_until"] == 0
    token = learning.access_token(host, current, current["learners"][0])
    assert host.app.test_client().get("/apprendre/" + token).status_code == 404
    status = client.get(url + "/statut").json
    assert status["can_send"] and not status["dispatch_requested"]
    button = re.search(r'<button[^>]*>Envoyer les accès e-learning aux stagiaires</button>', client.get(url).text)
    assert button and "disabled" not in button.group()
    assert client.get(url + "/envoyer-acces").status_code in {302, 405}
    assert not latest(shop).get("access_dispatch_requested_at")
    assert post_dispatch(client, order).status_code == 303
    assert not learner_mails(shop, order)  # Only the merchant worker sends.
    assert post_dispatch(client, order).status_code == 303
    requested = latest(shop)["access_dispatch_requested_at"]
    run(order)
    sent = latest(shop)
    assert sent["activated_at"] and len(learner_mails(shop, order)) == 2
    assert sent["access_dispatch_requested_at"] == requested
    assert sent["access_dispatch_requested_by"]
    before = copy.deepcopy(sent)
    assert post_dispatch(client, order).status_code == 303
    run(order)
    assert latest(shop) == before
    assert len(learner_mails(shop, order)) == 2


def test_partial_payment_cancelled_order_and_cross_tenant_posts_are_blocked(shop, merchant):
    order = submit(shop)
    run(order)
    merchant["invoice"].update(paid_amount={"value": "59.00", "currency": "EUR"})
    retry(order)
    assert post_dispatch(shop["client"], order).status_code == 409
    other = host.app.test_client()
    signup(other, email="other-dispatch@example.test")
    login(other, email="other-dispatch@example.test")
    token = csrf(other, "/admin/organisme/e-learning")
    assert other.post(ROOT + order["id"] + "/envoyer-acces", data={"csrf_token": token, "partner_id": order["partner_id"]}).status_code == 404
    mark_paid(merchant)
    retry(order)
    def cancel(data):
        commerce._find(data, order["partner_id"], order["id"])["status"] = "cancelled"
        return {}
    host._atomic_update_data(cancel, partner_id=order["partner_id"])
    assert post_dispatch(shop["client"], order).status_code == 409
    assert not learner_mails(shop, order)


def test_dispatch_requires_csrf_and_editable_active_centre(shop):
    order = submit(shop, free=True)
    client = shop["client"]
    url = ROOT + order["id"] + "/envoyer-acces"
    assert client.post(url).status_code == 400
    token = csrf(client, ROOT + order["id"])
    with client.session_transaction() as state:
        original_role = state["admin_role"]
        state["admin_role"] = "viewer"
    assert client.post(url, data={"csrf_token": token}).status_code == 403
    with client.session_transaction() as state:
        state["admin_role"] = original_role
    host._atomic_update_data(lambda data: host._partner_or_404(data, order["partner_id"]).update(status="suspended"), partner_id=order["partner_id"])
    response = client.post(url, data={"csrf_token": token})
    assert response.status_code == 302 and "/admin/login" in response.location
    assert not latest(shop).get("access_dispatch_requested_at")


def test_group_distinguishes_paid_batch_from_new_unpaid_participants(shop, merchant):
    prepare(shop)
    client = shop["client"]
    group_url = create(client)
    save(shop, group_url, [person()])
    first = confirm(shop, group_url)
    run(first)
    assert "Envoyer les accès e-learning aux stagiaires" in client.get(group_url).text
    mark_paid(merchant)
    retry(first)
    ready = client.get(group_url).text
    assert "Prêt à envoyer" in ready and "Paiement confirmé" in ready
    save(shop, group_url, [person("alex@example.test", "Alex", "Durand")])
    second = confirm(shop, group_url)
    send_accesses(shop, first)
    data = all_data(shop)
    unpaid = commerce._find(data, second["partner_id"], second["id"])
    assert not unpaid.get("access_dispatch_requested_at") and not unpaid.get("activated_at")
    assert len(learner_mails(shop, first)) == 1 and not learner_mails(shop, second)


def test_request_during_payment_worker_is_durable_and_releases_lease(shop, merchant, monkeypatch):
    order = submit(shop)
    run(order)
    mark_paid(merchant)
    original = learning.send_message
    observed = []
    def interleave(host_module, current, key, recipient, **kwargs):
        if key == "invoice_paid":
            assert latest(shop)["commerce"]["lease_until"] > time.time()
            observed.append(post_dispatch(shop["client"], order).status_code)
        return original(host_module, current, key, recipient, **kwargs)
    monkeypatch.setattr(learning, "send_message", interleave)
    retry(order)
    pending = latest(shop)
    assert observed == [303]
    assert pending["access_dispatch_requested_at"] and pending["commerce"]["queued"]
    assert pending["commerce"]["lease_until"] == 0 and pending["commerce"]["next_attempt"] == 0
    assert not learner_mails(shop, order)
    monkeypatch.setattr(learning, "send_message", original)
    run(order)
    assert len(learner_mails(shop, order)) == 2 and not latest(shop)["commerce"]["queued"]


def test_legacy_active_links_survive_without_automatic_unsent_emails(shop):
    order = submit(shop, free=True)
    run(order)
    order = send_accesses(shop, order)
    token = learning.access_token(host, order, order["learners"][0])
    def legacy(data):
        current = commerce._find(data, order["partner_id"], order["id"])
        current.pop("access_dispatch_requested_at")
        current.pop("access_dispatch_requested_by")
        current["commerce"]["emails"].pop("learner_" + current["learners"][1]["id"])
        return {}
    host._atomic_update_data(legacy, partner_id=order["partner_id"])
    before = len(shop["mails"])
    retry(order)
    assert len(shop["mails"]) == before
    assert learning.learner_context(all_data(shop), token)[1]
    assert learning.status_view(latest(shop))["can_send"]
