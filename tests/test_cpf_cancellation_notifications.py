import copy
from unittest.mock import Mock

import pytest

import app as application
import wedof_cancellation_notifications as alerts


def folder(**changes):
    return {"externalId": "CPF-ANN-1", "type": "cpf", "state": alerts.ATTENDEE_CANCELLATION_STATE,
            "attendee": {"firstName": "Marie", "lastName": "Exemple", "email": "marie@example.test", "phoneNumber": "0600000000"},
            "trainingActionInfo": {"title": "Agent de prévention et de sécurité", "sessionStartDate": "2026-09-07", "sessionEndDate": "2026-10-09", "totalIncl": 1650, "duration": 175},
            "pricing": {"cpfAmount": 1600, "attendeeAmount": 50, "franceTravailAmount": 0},
            "cancellationReason": "Indisponibilité du titulaire", **changes}


def queued():
    entries = [{"id": "EVENT-1"}]
    item = alerts.enqueue(entries, entries[0], folder(), ("Sujet", "<p>HTML</p>", "Texte"), now=1000)
    return entries, item


@pytest.mark.parametrize("state", ["accepted", "canceledByAttendee", "canceledByOrganism", "refusedByAttendee", ""])
def test_only_exact_status_enqueues(state):
    entries = [{}]
    assert alerts.enqueue(entries, entries[0], folder(state=state), ("S", "H", "T")) is None


def test_other_training_types_do_not_enqueue():
    assert not alerts.is_cancellation(folder(type="apprenticeship"))
    assert not alerts.is_cancellation(folder(type="individual"))


def test_one_mail_each_despite_later_notifications_and_restarts():
    entries, notification = queued()
    persisted = []
    def save(value):
        persisted[:] = copy.deepcopy(value)
    send = Mock(return_value={"ok": True, "message_id": "brevo-1"})
    alerts.deliver(entries, notification, save=save, send=send, now=1000)
    assert [call.args[0] for call in send.call_args_list] == list(alerts.RECIPIENTS)
    assert all(row["status"] == "sent" for row in notification["recipients"].values())
    entries = copy.deepcopy(persisted)
    entries.insert(0, {"id": "EVENT-2"})
    original = alerts.enqueue(entries, entries[0], folder(), ("New", "New", "New"), now=2000)
    alerts.deliver(entries, original, save=save, send=send, now=2000)
    assert send.call_count == 2
    assert alerts.QUEUE_KEY not in entries[0]


def test_retry_only_failed_recipient_with_identical_message_and_key():
    entries, notification = queued()
    send = Mock(side_effect=[{"ok": True}, {"ok": False, "status_code": 429}, {"ok": True}])
    save = Mock()
    alerts.deliver(entries, notification, save=save, send=send, now=1000)
    alerts.deliver(entries, notification, save=save, send=send, now=1100)
    assert send.call_count == 2
    alerts.deliver(entries, notification, save=save, send=send, now=1301)
    assert send.call_count == 3
    assert send.call_args_list[1] == send.call_args_list[2]
    assert send.call_args.args[0] == "clement@integraleacademy.com"


def test_sending_state_is_saved_before_external_delivery():
    entries, notification = queued()
    persisted = []
    def save(value):
        persisted[:] = copy.deepcopy(value)
    def send(email, *_args, **_kwargs):
        assert persisted[0][alerts.QUEUE_KEY]["recipients"][email]["status"] == "sending"
        return {"ok": True}
    alerts.deliver(entries, notification, save=save, send=send, now=1000)


def test_no_unsafe_retry_after_ambiguous_idempotency_window():
    entries, notification = queued()
    send = Mock(side_effect=TimeoutError)
    alerts.deliver(entries, notification, save=Mock(), send=send, now=1000)
    alerts.deliver(entries, notification, save=Mock(), send=send, now=2300)
    assert send.call_count == 2
    assert all(row["status"] == "needs_review" for row in notification["recipients"].values())


def test_configuration_rejections_remain_retryable_without_expiry():
    entries, notification = queued()
    send = Mock(return_value={"ok": False, "not_sent": True})
    alerts.deliver(entries, notification, save=Mock(), send=send, now=1000)
    alerts.deliver(entries, notification, save=Mock(), send=send, now=10000)
    assert send.call_count == 4
    assert all(row["status"] == "failed" for row in notification["recipients"].values())


def test_email_has_complete_business_details_and_escaped_content():
    data = {"wedof_links": [{"external_id": "CPF-ANN-1", "active": True, "session_id": "S1", "trainee_id": "T1"}],
            "sessions": [{"id": "S1", "name": "APS septembre", "trainees": [{"id": "T1"}]}]}
    value = folder(attendee={"firstName": "Marie<script>alert(1)</script>", "lastName": "Exemple"}, secret="never-email-this")
    with application.app.app_context():
        subject, body, text = application.build_cpf_cancellation_alert_email(value, "2026-09-27T06:40:00Z", data)
    for expected in ("1 650,00 €", "1 600,00 €", "50,00 €", "0,00 €", "175 h", "07/09/2026", "09/10/2026", "APS septembre", "Indisponibilité du titulaire", "CPF-ANN-1", "27/09/2026 à 08:40"):
        assert expected in body and expected in text
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "never-email-this" not in body + text
    assert "/admin/sessions/S1/stagiaires/T1" in body
    assert "Annulation CPF" in subject


@pytest.fixture
def webhook(monkeypatch, tmp_path):
    monkeypatch.setenv("WEDOF_WEBHOOK_SECRET", "test-only")
    monkeypatch.setenv("WEDOF_AUTOMATION_KILL_SWITCH", "false")
    monkeypatch.setattr(application, "WEDOF_WEBHOOK_FILE", str(tmp_path / "webhooks.json"))
    monkeypatch.setattr(application, "load_data", Mock(return_value={"sessions": []}))
    monkeypatch.setattr(application, "_atomic_update_data", Mock())
    monkeypatch.setattr(application, "_fetch_wedof_folder_details", Mock(return_value={}))
    monkeypatch.setattr(application, "_process_vtc_cpf_auto_workflow", lambda value, *_args, **_kwargs: value)
    monkeypatch.setattr(application, "_send_wedof_entry_to_salesforce", Mock(return_value=({"success": True}, 200)))
    monkeypatch.setattr(application, "_send_wedof_entry_to_crm", Mock(return_value=({"success": True}, 200)))
    send = Mock(return_value={"ok": True})
    monkeypatch.setattr(application, "brevo_send_email", send)
    return application.app.test_client(), send


def post(client, value, delivery="E1", trusted=True):
    return client.post("/api/webhooks/wedof", json=value, headers={
        "X-Wedof-Secret": "test-only" if trusted else "wrong",
        "X-Wedof-Delivery": delivery, "X-Wedof-Event": "registrationFolder.updated"})


def test_authenticated_webhook_and_duplicate_event_are_idempotent(webhook):
    client, send = webhook
    for delivery in ("E1", "E1", "E2"):
        assert post(client, folder(), delivery).status_code == 200
    assert send.call_count == 2
    assert [call.args[0] for call in send.call_args_list] == list(alerts.RECIPIENTS)


def test_unsigned_webhook_never_notifies(webhook):
    client, send = webhook
    assert post(client, folder(), trusted=False).status_code == 200
    send.assert_not_called()
    assert not any(alerts.QUEUE_KEY in entry for entry in application._load_wedof_webhooks())


def test_partial_update_uses_historical_contact_and_formation(webhook):
    client, send = webhook
    post(client, folder(state="accepted"), "E1")
    send.assert_not_called()
    post(client, {"externalId": "CPF-ANN-1", "state": alerts.ATTENDEE_CANCELLATION_STATE}, "E2")
    assert send.call_count == 2
    assert "marie@example.test" in send.call_args.args[2]
    assert "Agent de prévention et de sécurité" in send.call_args.args[2]


def test_cron_retries_without_new_webhook_and_does_not_backfill(webhook, monkeypatch):
    client, send = webhook
    send.return_value = {"ok": False, "status_code": 429}
    post(client, folder())
    entries = application._load_wedof_webhooks()
    item = entries[0][alerts.QUEUE_KEY]
    for receipt in item["recipients"].values():
        receipt["last_attempt_at"] -= 301
    entries.append({"id": "OLD", "wedof_folder_details": folder(externalId="OLD-CPF")})
    application._save_wedof_webhooks(entries)
    send.return_value = {"ok": True}
    monkeypatch.setenv("CRON_SECRET", "cron-test")
    monkeypatch.setattr(application, "run_wedof_automation_live", Mock(return_value={"ok": True, "status": "done"}))
    response = client.post("/internal/cron/wedof-automation", headers={"X-Cron-Secret": "cron-test"})
    assert response.status_code == 200 and send.call_count == 4
    assert alerts.QUEUE_KEY not in application._load_wedof_webhooks()[-1]


def test_brevo_deduplication_acknowledges_existing_delivery(monkeypatch):
    monkeypatch.setattr(application, "_missing_brevo_config", lambda: [])
    response = Mock(status_code=400, text="duplicate")
    response.json.return_value = {"code": "duplicate_parameter", "message": "Email for the idempotency key has already been processed"}
    request = Mock(return_value=response)
    monkeypatch.setattr(application.requests, "post", request)
    result = application.brevo_send_email(alerts.RECIPIENTS[0], "S", "H", metadata={"idempotency_key": "fixed-key"})
    assert result["ok"] is True
    assert request.call_args.kwargs["json"]["headers"] == {"idempotencyKey": "fixed-key"}
