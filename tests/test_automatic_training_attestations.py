import datetime as dt
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

import app as gestion
from automatic_training_attestations import STATE_KEY, run


def clock(day, hour=9):
    return dt.datetime.fromisoformat(day).replace(hour=hour, tzinfo=ZoneInfo("Europe/Paris"))


@pytest.fixture
def attestation_case(monkeypatch, tmp_path):
    trainee = {
        "id": "T1",
        "first_name": "Alice",
        "last_name": "EXEMPLE",
        "email": "alice@example.test",
    }
    training = {
        "id": "S1",
        "name": "APS SEPTEMBRE 2026",
        "training_type": "APS",
        "date_start": "2026-09-07",
        "date_end": "2026-10-09",
        "trainees": [trainee],
    }
    data = {
        "sessions": [training],
        "training_attestations_scheduler": {"activated_on": "2026-09-19"},
    }
    entry_docx = tmp_path / "entry.docx"
    entry_pdf = tmp_path / "entry.pdf"
    end_docx = tmp_path / "end.docx"
    end_pdf = tmp_path / "end.pdf"
    entry_pdf.write_bytes(b"entry-pdf")
    end_pdf.write_bytes(b"end-pdf")
    entry_docx.write_bytes(b"entry-docx")
    end_docx.write_bytes(b"end-docx")
    email = Mock(side_effect=lambda *args, **kwargs: {
        "ok": True,
        "message_id": f"message-{email.call_count}",
    })

    monkeypatch.setattr(gestion, "load_data", lambda *args, **kwargs: data)
    monkeypatch.setattr(gestion, "_atomic_update_data", lambda mutate: mutate(data))
    monkeypatch.setattr(gestion, "_generate_aps_entry_attestation_files", lambda *args: (str(entry_docx), str(entry_pdf)))
    monkeypatch.setattr(gestion, "_generate_aps_end_attestation_files", lambda *args: (str(end_docx), str(end_pdf)))
    monkeypatch.setattr(gestion, "brevo_send_email", email)
    monkeypatch.setattr(gestion, "_store_public_file_token", lambda path: f"token:{Path(path).name}")

    with gestion.app.test_request_context():
        yield data, training, trainee, email


def test_active_session_entry_is_backfilled_once_and_end_waits(attestation_case):
    _, _, trainee, email = attestation_case

    report = run(gestion, now=clock("2026-09-19"))

    assert report["entry_sent"] == report["emails_accepted"] == 1
    assert report["end_sent"] == report["failed"] == 0
    assert trainee["attestation_entree_aps_sent_at"]
    assert not trainee.get("attestation_fin_aps_sent_at")
    assert trainee[STATE_KEY]["entry"]["email_status"] == "ACCEPTE"
    assert trainee["sent_email_history"][0]["source"] == "automatic_training_attestation"
    assert email.call_args.kwargs["metadata"]["attestation_kind"] == "entry"
    assert run(gestion, now=clock("2026-09-19", 10))["processed"] == 0
    assert email.call_count == 1


def test_end_attestation_is_sent_once_on_training_end_date(attestation_case):
    _, _, trainee, email = attestation_case
    run(gestion, now=clock("2026-09-19"))

    report = run(gestion, now=clock("2026-10-09"))

    assert report["end_sent"] == report["emails_accepted"] == 1
    assert trainee["attestation_fin_aps_sent_at"]
    assert trainee[STATE_KEY]["end"]["email_status"] == "ACCEPTE"
    assert email.call_args.kwargs["metadata"]["attestation_kind"] == "end"
    assert run(gestion, now=clock("2026-10-09", 10))["processed"] == 0
    assert email.call_count == 2


def test_cancelled_registration_is_never_generated_or_emailed(attestation_case):
    _, _, trainee, email = attestation_case
    trainee["registration_cancelled"] = True

    report = run(gestion, now=clock("2026-09-19"))

    assert report["processed"] == report["due"] == 0
    assert report["skipped_cancelled"] == 1
    assert STATE_KEY not in trainee
    email.assert_not_called()


def test_cancellation_during_pdf_generation_closes_last_send_gate(attestation_case, monkeypatch):
    _, _, trainee, email = attestation_case
    original = gestion._generate_aps_entry_attestation_files

    def cancel_during_generation(*args):
        trainee["registration_cancelled"] = True
        return original(*args)

    monkeypatch.setattr(gestion, "_generate_aps_entry_attestation_files", cancel_during_generation)

    report = run(gestion, now=clock("2026-09-19"))

    assert report["processed"] == 1
    assert report["emails_accepted"] == 0
    assert trainee[STATE_KEY]["entry"]["email_status"] == "DESACTIVE"
    email.assert_not_called()


def test_activation_does_not_mail_an_old_completed_session(attestation_case):
    _, training, trainee, email = attestation_case
    training["date_start"] = "2026-08-01"
    training["date_end"] = "2026-09-01"

    report = run(gestion, now=clock("2026-09-19"))

    assert report["due"] == report["processed"] == 0
    assert not trainee.get("attestation_entree_aps_sent_at")
    assert not trainee.get("attestation_fin_aps_sent_at")
    email.assert_not_called()


def test_manual_attestation_routes_reject_cancelled_registration(attestation_case, monkeypatch):
    data, _, trainee, email = attestation_case
    trainee["registration_cancelled"] = True
    monkeypatch.setattr(gestion, "load_data", lambda *args, **kwargs: data)
    client = gestion.app.test_client()
    with client.session_transaction() as session:
        session["admin_logged_in"] = True
        session["admin_role"] = "admin"

    entry = client.post("/admin/sessions/S1/stagiaires/T1/attestation-entree-aps/send")
    end = client.post("/admin/sessions/S1/stagiaires/T1/attestation-fin-aps/send")

    assert entry.status_code == end.status_code == 409
    assert entry.get_json()["code"] == end.get_json()["code"] == "automation_disabled"
    assert "Automatisation désactivée" in entry.get_json()["error"]
    email.assert_not_called()


def test_cancellation_helper_stops_pending_automation_and_reactivation_releases_it():
    trainee = {
        "convocation_auto_scheduled_at": "2026-09-20T09:00:00Z",
        "docs_relance_auto_planned_date": "2026-09-25",
        "convention_signature": {"next_reminder_at": "2026-09-20T09:00:00Z"},
        "automatic_docs_reminder_history": [{
            "pending": True,
            "email_status": "EN_ATTENTE",
            "sms_status": "EN_ATTENTE",
        }],
        STATE_KEY: {"entry": {"pending": True, "email_status": "EN_ATTENTE"}},
    }

    gestion._disable_trainee_automations_for_cancellation(trainee, "2026-09-19T09:00:00Z")

    assert trainee["convocation_auto_scheduled_at"] == ""
    assert trainee["docs_relance_auto_planned_date"] == ""
    assert trainee["convention_signature"]["next_reminder_at"] == ""
    assert trainee["automatic_docs_reminder_history"][0]["email_status"] == "DESACTIVE"
    assert trainee[STATE_KEY]["entry"]["email_status"] == "DESACTIVE"
    assert trainee["automation_disabled_reason"] == "registration_cancelled"

    gestion._reactivate_trainee_automations(trainee)
    assert "automation_disabled_reason" not in trainee
    assert trainee["convocation_auto_scheduled_at"] == "2026-09-20T09:00:00Z"
    assert trainee["convention_signature"]["next_reminder_at"] == "2026-09-20T09:00:00Z"
    assert trainee["automatic_docs_reminder_history"] == []
    assert STATE_KEY not in trainee


def test_template_labels_automatic_sending_and_cancellation_lock():
    source = (Path(gestion.app.root_path) / "templates" / "admin_trainee.html").read_text()
    assert "Automatisation désactivée" in source
    assert source.count("Envoi automatique à la date prévue") == 2
    # Also compile the Jinja expression used by the date fallback.
    gestion.app.jinja_env.get_template("admin_trainee.html")
