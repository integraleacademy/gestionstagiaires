import copy
import datetime as dt
import json
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

import app as gestion
from automatic_document_reminders import HISTORY_KEY, phase_key, run, schedule
from manual_document_reminders import build_content

REAL_ATOMIC = gestion._atomic_update_data
REAL_SAVE = gestion.save_data
START = dt.date(2026, 10, 12)


def clock(day, hour=9):
    return dt.datetime.fromisoformat(day).replace(hour=hour, tzinfo=ZoneInfo("Europe/Paris"))


@pytest.fixture
def dossier(monkeypatch):
    trainee = {
        "id": "T1", "first_name": "Alice", "last_name": "EXEMPLE", "email": "alice@example.test",
        "phone": "0600000000", "public_token": "test-token", "birth_date": "1990-01-01",
        "birth_city": "Paris", "birth_country": "France", "nationality": "Française",
        "address": "1 rue Exemple", "zip_code": "75001", "city": "Paris", "carte_vitale": "123456789012345",
        "professional_experience_sheet": {"status": "A CONTRÔLER"},
        "documents": [{"key": "id", "status": "CONFORME", "files": ["id.pdf"]},
                      {"key": "photo", "status": "NON DÉPOSÉ"},
                      {"key": "carte_vitale_doc", "status": "A CONTRÔLER", "files": ["vitale.pdf"]},
                      {"key": "certificat_medical_ssiap", "status": "NON CONFORME", "file": "old.pdf", "comment": "Modèle officiel requis"}],
    }
    training = {"id": "S1", "name": "SSIAP 1 OCTOBRE 2026", "training_type": "SSIAP 1", "date_start": START.isoformat(), "trainees": [trainee]}
    data = {"sessions": [training], "document_reminders_scheduler": {"activated_on": "2026-09-14"}}
    email = Mock(side_effect=lambda *a, **kw: {"ok": True, "message_id": f"message-{email.call_count}"})
    sms = Mock(return_value=True)
    monkeypatch.setattr(gestion, "load_data", lambda *a, **kw: data)
    monkeypatch.setattr(gestion, "save_data", lambda *a, **kw: None)
    monkeypatch.setattr(gestion, "_atomic_update_data", lambda mutate: mutate(data))
    monkeypatch.setattr(gestion, "brevo_send_email", email)
    monkeypatch.setattr(gestion, "brevo_send_sms", sms)
    with gestion.app.test_request_context():
        yield data, training, trainee, email, sms


def test_three_dates_same_modern_template_and_exact_history(dossier):
    data, training, trainee, email, sms = dossier
    for stage, day in ((25, "2026-09-17"), (15, "2026-09-27"), (10, "2026-10-02")):
        assert run(gestion, now=clock(day))["processed"] == 1
        assert run(gestion, now=clock(day, 10))["processed"] == 0
        attempt = trainee[HISTORY_KEY][0]
        assert attempt["automatic_stage"] == stage
        assert attempt["phase_key"] == phase_key(START, stage)
        assert not attempt["pending"]
        args, kwargs = email.call_args
        # The scheduled flow renders through the exact shared manual template.
        preview, reason = gestion._manual_docs_preview(training, trainee, today=clock(day).date(), automatic_stage=stage)
        assert not reason and args[2] == preview["html"]
        assert kwargs["text_content"] == preview["text"]
        assert "linear-gradient(120deg,#111827,#18386c)" in args[2]
        assert "Accéder à mon espace stagiaire" in args[2]
        assert "Photo d’identité" in args[2] and "Modèle officiel requis" in args[2]
        assert "04 22 47 07 68" in sms.call_args.args[1]
        assert "Carte vitale" not in sms.call_args.args[1]
        assert trainee["sent_email_history"][0]["html"] == args[2]
        assert trainee["sent_email_history"][0]["automatic_stage"] == stage
    assert email.call_count == sms.call_count == 3
    assert len(gestion.build_trainee_email_history_entries(trainee)) == 3
    assert "Dernier jour" in email.call_args.args[1]
    assert "au plus tard aujourd’hui" in email.call_args.args[2]
    assert "Date limite aujourd’hui" in sms.call_args.args[1]


def test_future_dates_and_daytime_window_respect_paris_summer_and_winter(dossier):
    data, training, trainee, email, sms = dossier
    assert run(gestion, now=clock("2026-09-16"))["processed"] == 0
    assert run(gestion, now=clock("2026-09-17", 8))["status"] == "outside_sending_hours"
    assert run(gestion, now=clock("2026-09-17", 20))["status"] == "outside_sending_hours"
    assert run(gestion, now=dt.datetime(2026, 9, 17, 7, tzinfo=dt.timezone.utc))["processed"] == 1
    training["date_start"] = "2027-01-26"
    assert run(gestion, now=dt.datetime(2027, 1, 1, 7, tzinfo=dt.timezone.utc))["status"] == "outside_sending_hours"
    assert run(gestion, now=dt.datetime(2027, 1, 1, 8, tzinfo=dt.timezone.utc))["processed"] == 1


@pytest.mark.parametrize("change", ["cancelled", "archived", "complete", "pending", "past", "vtc", "vae", "other_partner"])
def test_only_actionable_authorized_dossiers_are_notified(dossier, change):
    data, training, trainee, email, sms = dossier
    if change == "cancelled": trainee["registration_cancelled"] = True
    elif change == "archived": training["archived"] = True
    elif change == "complete": trainee["force_dossier_complete"] = True
    elif change == "pending":
        for doc in trainee["documents"]: doc.update(status="A CONTRÔLER", files=["uploaded.pdf"])
    elif change == "past": training["date_start"] = "2026-09-16"
    elif change == "vtc": training["training_type"] = "VTC"
    elif change == "vae": training["training_type"] = "DIRIGEANT VAE"
    elif change == "other_partner": training["partner_id"] = "other-partner"
    assert run(gestion, now=clock("2026-09-17"))["processed"] == 0
    email.assert_not_called()
    sms.assert_not_called()


def test_dry_run_and_activation_do_not_catch_up_old_stages(dossier):
    data, training, trainee, email, sms = dossier
    before = copy.deepcopy(data)
    assert run(gestion, now=clock("2026-09-17"), dry_run=True)["due"] == 1
    assert data == before
    data.pop("document_reminders_scheduler")
    assert run(gestion, now=clock("2026-09-24"))["processed"] == 0
    assert data["document_reminders_scheduler"]["activated_on"] == "2026-09-24"
    assert run(gestion, now=clock("2026-09-27"))["processed"] == 1
    assert [x["automatic_stage"] for x in trainee[HISTORY_KEY]] == [15]
    assert email.call_count == sms.call_count == 1


def test_outage_catches_up_only_current_relevant_phase(dossier):
    data, training, trainee, email, sms = dossier
    assert run(gestion, now=clock("2026-09-28"))["processed"] == 1
    assert trainee[HISTORY_KEY][0]["automatic_stage"] == 15
    assert email.call_count == sms.call_count == 1
    assert run(gestion, now=clock("2026-09-28", 10))["processed"] == 0


def test_manual_and_legacy_j15_do_not_cancel_other_phases(dossier):
    data, training, trainee, email, sms = dossier
    trainee["docs_last_relance_at"] = "2026-09-16T09:00:00Z"
    assert run(gestion, now=clock("2026-09-17"))["processed"] == 1
    trainee.pop(HISTORY_KEY)
    trainee["docs_relance_auto_sent_at"] = "2026-09-27T08:00:00Z"
    assert run(gestion, now=clock("2026-09-27"))["processed"] == 0
    assert run(gestion, now=clock("2026-10-02"))["processed"] == 1
    assert len(trainee[HISTORY_KEY]) == 2


def test_inflight_manual_blocks_auto_and_overlapping_crons_do_not_duplicate(dossier):
    data, training, trainee, email, sms = dossier
    current = clock("2026-09-17")
    trainee["manual_docs_reminder_history"] = [{"pending": True, "attempted_at": current.isoformat()}]
    assert run(gestion, now=current)["processed"] == 0
    trainee["manual_docs_reminder_history"] = []
    def during_email(*args, **kwargs):
        assert run(gestion, now=current)["processed"] == 0
        return {"ok": True, "message_id": "unique"}
    email.side_effect = during_email
    assert run(gestion, now=current)["processed"] == 1
    assert email.call_count == sms.call_count == 1


def test_partial_failure_stays_visible_without_automatic_duplicate(dossier):
    data, training, trainee, email, sms = dossier
    sms.return_value = False
    assert run(gestion, now=clock("2026-09-17"))["failed"] == 1
    assert len(trainee["sent_email_history"]) == 1
    assert schedule(trainee, START, dt.date(2026, 9, 17))[0]["state"] == "Transmission à vérifier"
    assert run(gestion, now=clock("2026-09-17", 10))["processed"] == 0
    assert email.call_count == sms.call_count == 1


def test_claim_and_email_history_survive_sms_worker_interruption(dossier, monkeypatch, tmp_path):
    data, training, trainee, email, sms = dossier
    path = tmp_path / "data.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(gestion, "DATA_FILE", str(path))
    monkeypatch.setattr(gestion, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(gestion, "_partner_postgres_active", lambda: False)
    monkeypatch.setattr(gestion, "_atomic_update_data", REAL_ATOMIC)
    monkeypatch.setattr(gestion, "load_data", lambda *a, **kw: json.loads(path.read_text()))
    def interrupt_sms(*args):
        saved = json.loads(path.read_text())
        current = saved["sessions"][0]["trainees"][0]
        assert current[HISTORY_KEY][0]["sms_status"] == "EN_COURS"
        assert current["sent_email_history"][0]["html"] == email.call_args.args[2]
        current["comment"] = "Concurrent edit kept"
        path.write_text(json.dumps(saved))
        raise SystemExit("worker stopped")
    sms.side_effect = interrupt_sms
    with pytest.raises(SystemExit): run(gestion, now=clock("2026-09-17"))
    assert run(gestion, now=clock("2026-09-17", 10))["failed"] == 1
    current = json.loads(path.read_text())["sessions"][0]["trainees"][0]
    assert current["comment"] == "Concurrent edit kept"
    assert current[HISTORY_KEY][0]["sms_status"] == "INCONNU"
    assert len(gestion.build_trainee_email_history_entries(current)) == 1
    assert email.call_count == sms.call_count == 1


def test_disabled_afc_sms_stay_disabled(dossier):
    data, training, trainee, email, sms = dossier
    training["name"] = "AFC SSIAP 1"
    report = run(gestion, now=clock("2026-09-17"))
    assert report["emails_accepted"] == 1
    assert report["sms_accepted"] == report["failed"] == 0
    assert trainee[HISTORY_KEY][0]["sms_status"] == "DESACTIVE"
    sms.assert_not_called()


def test_stale_admin_save_cannot_erase_receipts_and_cause_another_send(dossier, monkeypatch, tmp_path):
    data, training, trainee, email, sms = dossier
    stale = copy.deepcopy(data)
    path = tmp_path / "data.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(gestion, "DATA_FILE", str(path))
    monkeypatch.setattr(gestion, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(gestion, "_partner_postgres_active", lambda: False)
    monkeypatch.setattr(gestion, "_partner_postgres_shadow", lambda: False)
    monkeypatch.setattr(gestion, "_atomic_update_data", REAL_ATOMIC)
    monkeypatch.setattr(gestion, "load_data", lambda *a, **kw: json.loads(path.read_text()))
    assert run(gestion, now=clock("2026-09-17"))["processed"] == 1
    stale["sessions"][0]["trainees"][0]["comment"] = "Saved from an old page"
    REAL_SAVE(stale)
    current = json.loads(path.read_text())["sessions"][0]["trainees"][0]
    assert current["comment"] == "Saved from an old page"
    assert current[HISTORY_KEY][0]["email_status"] == "ACCEPTE"
    assert current["sent_email_history"][0]["html"] == email.call_args.args[2]
    assert run(gestion, now=clock("2026-09-17", 10))["processed"] == 0
    assert email.call_count == sms.call_count == 1


def test_cron_secret_is_required_and_dry_run_is_forwarded(monkeypatch):
    client = gestion.app.test_client()
    engine = Mock(return_value={"ok": True, "status": "dry_run", "due": 0})
    monkeypatch.setattr(gestion, "run_automatic_document_reminders", engine)
    monkeypatch.delenv("CRON_SECRET", raising=False)
    url = "/internal/cron/document-reminders"
    assert client.post(url).status_code == 403
    monkeypatch.setenv("CRON_SECRET", "test-secret")
    assert client.post(url, headers={"X-Cron-Secret": "wrong"}).status_code == 403
    engine.assert_not_called()
    assert client.post(url, headers={"X-Cron-Secret": "test-secret"}, json={"dry_run": True}).status_code == 200
    assert engine.call_args.kwargs["dry_run"] is True
