import copy
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import partner_registration_notifications as notifications
from test_manuals_shop import all_data, host, login, shop, signup


def process(shop):
    with host.app.app_context():
        notifications.process_pending(host, all_data(shop))


def alerts(shop):
    return [mail for mail in shop["mails"] if mail[1].get("metadata", {}).get("purpose") == "partner_registration_admin"]


def partner(shop):
    return next(p for p in all_data(shop)["partners"] if p.get("account_type") == "manuals_only")


def test_signup_queues_alert_after_persistence_and_sends_once(shop, monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://gestionstagiaires-r5no.onrender.com")
    assert signup(shop["client"], centre="Centre <Formation> & Conseil").status_code == 303
    saved = partner(shop)
    assert saved[notifications.STATE_KEY]["status"] == "pending"
    assert not alerts(shop)
    process(shop)
    args, kwargs = alerts(shop)[0]
    assert args[0] == "clement@integraleacademy.com"
    assert args[1] == "Nouvel organisme inscrit · Centre <Formation> & Conseil"
    assert "Centre &lt;Formation&gt; &amp; Conseil" in args[2]
    assert "Centre <Formation>" not in args[2]
    for content in (args[2], kwargs["text_content"]):
        for value in ("73282932000074", "Camille Martin", "centre@example.test",
                      "https://www.integraleconnect.com/admin/partners/" + saved["id"],
                      host.fr_datetime(saved["created_at"])):
            assert value in content
        assert "Une phrase robuste" not in content
        assert all_data(shop)["users"][0]["password_hash"] not in content
    assert "https://www.integraleconnect.com/static/logoic.png" in args[2]
    assert kwargs["metadata"]["idempotency_key"] == "partner-registration-" + saved["id"]
    assert partner(shop)[notifications.STATE_KEY]["status"] == "sent"
    assert partner(shop)[notifications.STATE_KEY]["message_id"] == "test-message"
    assert shop["client"].get("/espace-cree").status_code == 200
    with shop["client"].session_transaction() as session:
        token = session["manuals_csrf"]
    assert shop["client"].post("/espace-cree/renvoyer-email", data={"csrf_token": token}).status_code == 303
    process(shop)
    assert len(alerts(shop)) == 1
    assert len(shop["mails"]) == 2


def test_invalid_and_duplicate_signups_do_not_queue_alerts(shop):
    assert signup(shop["client"], siret="00000000000000").status_code == 400
    process(shop)
    assert not alerts(shop)
    assert signup(shop["client"]).status_code == 303
    assert signup(host.app.test_client()).status_code == 400
    process(shop)
    assert len(alerts(shop)) == 1


@pytest.mark.parametrize("failure", ["rejected", "exception"])
def test_failed_alert_retries_without_duplicate_or_blocking_account(shop, monkeypatch, failure):
    assert signup(shop["client"]).status_code == 303
    original = host.brevo_send_email
    calls = []

    def fail(*args, **kwargs):
        calls.append(kwargs["metadata"]["idempotency_key"])
        if failure == "exception":
            raise TimeoutError("Mail provider unavailable")
        return {"ok": False}

    monkeypatch.setattr(host, "brevo_send_email", fail)
    process(shop)
    state = partner(shop)[notifications.STATE_KEY]
    assert state["status"] == "failed" and state["attempts"] == 1
    process(shop)
    assert len(calls) == 1
    login(shop["client"])
    assert shop["client"].get("/admin/manuels").status_code == 200
    monkeypatch.setattr(host, "brevo_send_email", original)
    monkeypatch.setattr(notifications.time, "time", lambda: state["next_attempt"] + 1)
    process(shop)
    process(shop)
    assert len(alerts(shop)) == 1
    assert alerts(shop)[0][1]["metadata"]["idempotency_key"] == calls[0]
    assert partner(shop)[notifications.STATE_KEY]["status"] == "sent"


def test_concurrent_workers_claim_one_alert(shop, monkeypatch):
    assert signup(shop["client"]).status_code == 303
    sending, release = threading.Event(), threading.Event()
    original = host.brevo_send_email

    def slow(*args, **kwargs):
        sending.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(host, "brevo_send_email", slow)
    snapshot = copy.deepcopy(all_data(shop))
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(process, shop)
        try:
            assert sending.wait(10)
            with host.app.app_context():
                notifications.process_pending(host, snapshot)
            assert not alerts(shop)
        finally:
            release.set()
        first.result()
    assert len(alerts(shop)) == 1


def test_legacy_accounts_are_not_backfilled(shop):
    assert signup(shop["client"]).status_code == 303
    saved = partner(shop)
    with host.app.app_context():
        def remove_marker(data):
            host._partner_or_404(data, saved["id"]).pop(notifications.STATE_KEY)
            return {}
        host._atomic_update_data(remove_marker, partner_id=saved["id"])
    process(shop)
    assert not alerts(shop)
