import copy
import datetime
import json
import uuid
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest

import app as gestion_app
from manual_document_reminders import build_content, document_actions

REAL_ATOMIC_UPDATE = gestion_app._atomic_update_data


@pytest.fixture
def context(monkeypatch):
    today = datetime.datetime.now(ZoneInfo("Europe/Paris")).date()
    trainee = {
        "id": "T1", "first_name": "Alice", "last_name": "EXEMPLE",
        "email": "alice@example.test", "phone": "0600000000", "public_token": "test-token",
        "birth_date": "1990-01-01", "birth_city": "Paris", "birth_country": "France",
        "nationality": "Française", "address": "1 rue Exemple", "zip_code": "75001", "city": "Paris",
        "carte_vitale": "123456789012345",
        "professional_experience_sheet": {"status": "A CONTRÔLER"},
        "documents": [
            {"key": "id", "status": "CONFORME", "files": ["id.pdf"]},
            {"key": "photo", "status": "NON DÉPOSÉ"},
            {"key": "carte_vitale_doc", "status": "A CONTRÔLER", "files": ["vitale.pdf"]},
            {"key": "certificat_medical_ssiap", "status": "NON CONFORME", "file": "certificat.pdf", "comment": "Merci d’utiliser le modèle officiel."},
        ],
    }
    training = {"id": "S1", "name": "SSIAP 1", "training_type": "SSIAP 1", "date_start": (today + datetime.timedelta(days=28)).isoformat(), "trainees": [trainee]}
    data = {"sessions": [training]}
    calls = {"email": [], "sms": []}
    monkeypatch.setattr(gestion_app, "load_data", lambda *args, **kwargs: data)
    monkeypatch.setattr(gestion_app, "save_data", lambda *args, **kwargs: None)
    monkeypatch.setattr(gestion_app, "_atomic_update_data", lambda mutator: mutator(data))
    monkeypatch.setattr(gestion_app, "brevo_send_email", lambda *args, **kwargs: calls["email"].append((args, kwargs)) or {"ok": True, "message_id": "fake-email"})
    monkeypatch.setattr(gestion_app, "brevo_send_sms", lambda *args, **kwargs: calls["sms"].append((args, kwargs)) or True)
    client = gestion_app.app.test_client()
    with client.session_transaction() as session:
        session["admin_logged_in"] = True
        session["admin_role"] = "admin"
    return client, data, training, trainee, calls


def preview(client):
    response = client.get("/api/admin/sessions/S1/docs/manual-reminder-preview")
    assert response.status_code == 200
    return response.get_json()


def send(client, prepared, *, request_id=None):
    item = prepared["eligible"][0]
    return client.post(item["send_url"], json={
        "csrf": prepared["csrf"], "preview_token": item["preview_token"],
        "request_id": request_id or uuid.uuid4().hex,
    })


def test_preview_asks_only_for_missing_or_rejected_documents(context):
    client, data, training, trainee, calls = context
    before = copy.deepcopy(trainee)
    content = preview(client)["eligible"][0]
    assert trainee == before
    assert calls == {"email": [], "sms": []}
    assert [item["action"] for item in content["documents"]] == ["À déposer", "À corriger"]
    assert content["missing_information"] == []  # No CNAPS PRE/CAR for SSIAP.
    assert "Carte vitale" not in content["sms"]
    assert "secourisme" not in content["sms"]
    assert "Photo d’identité" in content["text"] and "Certificat médical" in content["sms"]
    assert "modèle officiel" in content["text"]
    assert "04 22 47 07 68" in content["sms"]
    assert "/espace/test-token" in content["text"]


@pytest.mark.parametrize("change,expected", [
    ({"registration_cancelled": True}, "annulée"),
    ({"force_dossier_complete": True}, "complet"),
    ({"email": "", "phone": ""}, "manquants"),
])
def test_ineligible_trainees_are_excluded(context, change, expected):
    client, data, training, trainee, calls = context
    trainee.update(change)
    result = preview(client)
    assert not result["eligible"]
    assert expected in result["skipped"][0]["reason"]
    assert calls == {"email": [], "sms": []}


@pytest.mark.parametrize("date_start", ["", "2020-01-01"])
def test_undated_and_past_sessions_are_excluded(context, date_start):
    client, data, training, trainee, calls = context
    training["date_start"] = date_start
    assert preview(client)["eligible"] == []


def test_complete_or_pending_review_dossier_is_not_reminded(context):
    client, data, training, trainee, calls = context
    for doc in trainee["documents"]:
        doc.update(status="A CONTRÔLER", files=["uploaded.pdf"])
    assert preview(client)["eligible"] == []


def test_both_channels_and_history_are_saved_without_changing_automatic_reminders(context):
    client, data, training, trainee, calls = context
    trainee["docs_relance_auto_planned_date"] = "2099-01-01"
    prepared = preview(client)
    result = send(client, prepared).get_json()
    assert result["ok"] and not result["partial"]
    assert result["email_status"] == result["sms_status"] == "ACCEPTE"
    assert len(calls["email"]) == len(calls["sms"]) == 1
    assert calls["email"][0][1]["text_content"] == prepared["eligible"][0]["text"]
    assert calls["sms"][0][0][1] == prepared["eligible"][0]["sms"]
    assert trainee["docs_last_relance_at"]
    assert trainee["sent_email_history"][0]["to_email"] == "alice@example.test"
    assert not trainee["manual_docs_reminder_history"][0]["pending"]
    assert trainee["docs_relance_auto_planned_date"] == "2099-01-01"


def test_repeated_click_does_not_duplicate_messages(context):
    client, data, training, trainee, calls = context
    prepared = preview(client)
    request_id = uuid.uuid4().hex
    assert send(client, prepared, request_id=request_id).get_json()["ok"]
    assert send(client, prepared, request_id=request_id).get_json()["ok"]
    assert send(client, prepared).get_json()["ok"]
    assert len(calls["email"]) == len(calls["sms"]) == 1


def test_partial_failure_is_visible_and_retry_only_sends_failed_channel(context, monkeypatch):
    client, data, training, trainee, calls = context
    monkeypatch.setattr(gestion_app, "brevo_send_sms", lambda *args: False)
    prepared = preview(client)
    result = send(client, prepared).get_json()
    assert not result["ok"] and result["partial"]
    assert result["email_status"] == "ACCEPTE" and result["sms_status"] == "ECHEC"
    monkeypatch.setattr(gestion_app, "brevo_send_sms", lambda *args: calls["sms"].append(args) or True)
    assert send(client, prepared).get_json()["ok"]
    assert len(calls["email"]) == len(calls["sms"]) == 1


def test_email_error_does_not_prevent_sms_and_failed_dict_is_not_success(context, monkeypatch):
    client, data, training, trainee, calls = context
    monkeypatch.setattr(gestion_app, "brevo_send_email", lambda *args, **kwargs: {"ok": False, "error": "Refus Brevo"})
    result = send(client, preview(client)).get_json()
    assert result["email_status"] == "ECHEC"
    assert result["sms_status"] == "ACCEPTE"
    assert result["partial"]
    assert "Refus Brevo" in result["error"]


def test_missing_contact_is_reported_as_partial(context):
    client, data, training, trainee, calls = context
    trainee["phone"] = ""
    result = send(client, preview(client)).get_json()
    assert result["partial"] and not result["ok"]
    assert result["sms_status"] == "ABSENT"
    assert calls["sms"] == []


def test_both_failures_never_claim_a_successful_reminder(context, monkeypatch):
    client, data, training, trainee, calls = context
    monkeypatch.setattr(gestion_app, "brevo_send_email", lambda *args, **kwargs: {"ok": False})
    monkeypatch.setattr(gestion_app, "brevo_send_sms", lambda *args: False)
    result = send(client, preview(client)).get_json()
    assert not result["ok"] and not result["partial"]
    assert result["email_status"] == result["sms_status"] == "ECHEC"
    assert not trainee.get("docs_last_relance_at")


def test_in_progress_request_is_not_sent_twice(context, monkeypatch):
    client, data, training, trainee, calls = context
    prepared = preview(client)
    trainee["manual_docs_reminder_history"] = [{
        "id": uuid.uuid4().hex, "pending": True,
        "attempted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }]
    assert send(client, prepared).status_code == 409
    assert calls == {"email": [], "sms": []}


def test_delivery_persistence_preserves_concurrent_edits(context, monkeypatch, tmp_path):
    client, data, training, trainee, calls = context
    prepared = preview(client)
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps(data))
    monkeypatch.setattr(gestion_app, "DATA_FILE", str(data_file))
    monkeypatch.setattr(gestion_app, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(gestion_app, "_partner_postgres_active", lambda: False)
    monkeypatch.setattr(gestion_app, "_atomic_update_data", REAL_ATOMIC_UPDATE)

    def sms_provider(*args):
        current = json.loads(data_file.read_text())
        t = current["sessions"][0]["trainees"][0]
        assert t["manual_docs_reminder_history"][0]["email_status"] == "ACCEPTE"
        assert t["sent_email_history"][0]["html"] == prepared["eligible"][0]["html"]
        t["comment"] = "Concurrent admin edit"
        current["sessions"][0]["trainees"].append({"id": "T2", "first_name": "Autre"})
        data_file.write_text(json.dumps(current))
        return True

    monkeypatch.setattr(gestion_app, "brevo_send_sms", sms_provider)
    assert send(client, prepared).get_json()["ok"]
    current = json.loads(data_file.read_text())
    assert current["sessions"][0]["trainees"][0]["comment"] == "Concurrent admin edit"
    assert current["sessions"][0]["trainees"][1]["id"] == "T2"
    assert current["sessions"][0]["trainees"][0]["manual_docs_reminder_history"][0]["sms_status"] == "ACCEPTE"


def test_email_history_survives_worker_interruption_during_sms(context, monkeypatch, tmp_path):
    client, data, training, trainee, calls = context
    prepared = preview(client)
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps(data))
    monkeypatch.setattr(gestion_app, "DATA_FILE", str(data_file))
    monkeypatch.setattr(gestion_app, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(gestion_app, "_partner_postgres_active", lambda: False)
    monkeypatch.setattr(gestion_app, "_atomic_update_data", REAL_ATOMIC_UPDATE)
    monkeypatch.setattr(gestion_app, "load_data", lambda *a, **kw: json.loads(data_file.read_text()))

    def interrupted_sms(*args):
        raise SystemExit("worker stopped")

    monkeypatch.setattr(gestion_app, "brevo_send_sms", interrupted_sms)
    with pytest.raises(SystemExit):
        send(client, prepared)
    current = json.loads(data_file.read_text())["sessions"][0]["trainees"][0]
    assert current["manual_docs_reminder_history"][0]["pending"]
    assert len(current["sent_email_history"]) == 1
    assert current["sent_email_history"][0]["message_id"] == "fake-email"
    response = client.get("/api/admin/sessions/S1/stagiaires/T1/email-history")
    assert response.status_code == 200
    assert "Transmission confirmée" in response.get_data(as_text=True)
    assert len(gestion_app.build_trainee_email_history_entries(current)) == 1


def test_history_refresh_and_detail_page_show_the_exact_sent_email(context, monkeypatch):
    client, data, training, trainee, calls = context
    url = "/api/admin/sessions/S1/stagiaires/T1/email-history"
    assert "Aucun mail" in client.get(url).get_data(as_text=True)
    prepared = preview(client)
    monkeypatch.setattr(gestion_app, "brevo_send_sms", lambda *a: False)
    assert send(client, prepared).get_json()["partial"]
    response = client.get(url)
    assert response.cache_control.no_store

    class PreviewParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.previews = []

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if "data-open-email-preview" in values:
                self.previews.append(values)

    for markup in (response.get_data(as_text=True), client.get("/admin/sessions/S1/stagiaires/T1").get_data(as_text=True)):
        parser = PreviewParser()
        parser.feed(markup)
        assert len(parser.previews) == 1
        assert parser.previews[0]["data-email-html"] == prepared["eligible"][0]["html"]
        assert parser.previews[0]["data-email-subject"] == prepared["eligible"][0]["subject"]
        assert " à " in parser.previews[0]["data-email-date"]
        assert "Transmission confirmée" in markup

    # Retrying the SMS must not add a second mail to either history source.
    monkeypatch.setattr(gestion_app, "brevo_send_sms", lambda *a: True)
    assert send(client, prepared).get_json()["ok"]
    assert len(gestion_app.build_trainee_email_history_entries(trainee)) == 1
    assert len(trainee["sent_email_history"]) == 1


def test_old_confirmed_attempts_are_recovered_but_failures_and_sms_retries_are_not():
    attempt = {"id": "old", "attempted_at": "2026-09-14T14:00:00Z", "pending": True,
               "email_status": "ACCEPTE", "email": "alice@example.test", "subject": "Relance",
               "text": "Bonjour <Alice>", "message_id": "old-message"}
    failed = dict(attempt, id="failed", email_status="ECHEC", message_id="")
    sms_retry = {"id": "retry", "email_status": "ACCEPTE", "attempted_at": "2026-09-14T14:01:00Z"}
    trainee = {"manual_docs_reminder_history": [sms_retry, failed, attempt]}
    entries = gestion_app.build_trainee_email_history_entries(trainee)
    assert len(entries) == 1
    assert entries[0]["manual_reminder"]
    assert "Bonjour &lt;Alice&gt;" in entries[0]["html"]
    trainee["sent_email_history"] = [{"to_email": attempt["email"], "subject": "Relance", "sent_at": attempt["attempted_at"], "html": "original"}]
    entries = gestion_app.build_trainee_email_history_entries(trainee)
    assert len(entries) == 1 and entries[0]["html"] == "original"


def test_history_does_not_claim_failed_or_unattempted_mail_was_sent(context, monkeypatch):
    client, data, training, trainee, calls = context
    monkeypatch.setattr(gestion_app, "brevo_send_email", lambda *a, **kw: {"ok": False})
    send(client, preview(client))
    assert gestion_app.build_trainee_email_history_entries(trainee) == []
    assert "Aucun mail" in client.get("/api/admin/sessions/S1/stagiaires/T1/email-history").get_data(as_text=True)


def test_history_endpoint_requires_login_and_known_trainee(context):
    client, data, training, trainee, calls = context
    assert client.get("/api/admin/sessions/S1/stagiaires/missing/email-history").status_code == 404
    with client.session_transaction() as session:
        session.clear()
    assert client.get("/api/admin/sessions/S1/stagiaires/T1/email-history").status_code == 401


def test_cancelled_or_modified_dossier_is_rechecked_at_send_time(context):
    client, data, training, trainee, calls = context
    prepared = preview(client)
    trainee["registration_cancelled"] = True
    assert send(client, prepared).status_code == 409
    trainee["registration_cancelled"] = False
    trainee["email"] = "changed@example.test"
    assert send(client, prepared).status_code == 409
    assert calls == {"email": [], "sms": []}


def test_authorization_and_csrf_are_required(context):
    client, data, training, trainee, calls = context
    prepared = preview(client)
    prepared["csrf"] = "wrong"
    assert send(client, prepared).status_code == 403
    with client.session_transaction() as session:
        session["admin_role"] = "viewer"
    assert client.get("/api/admin/sessions/S1/docs/manual-reminder-preview").status_code == 403
    assert send(client, prepared).status_code == 403
    with client.session_transaction() as session:
        session.clear()
    assert client.get("/api/admin/sessions/S1/docs/manual-reminder-preview").status_code == 401
    assert calls == {"email": [], "sms": []}


def test_deadline_and_overdue_wording_and_html_escaping():
    kwargs = dict(first_name="<Alice>", training="SSIAP 1", start_date=datetime.date(2026, 10, 12),
                  portal_link="https://example.test/espace/demo", documents=[{"label": "Photo", "action": "À corriger", "comment": "<script>"}], missing_information=[])
    before = build_content(today=datetime.date(2026, 9, 14), **kwargs)
    assert before["deadline"] == "2026-10-02"
    assert "au plus tard le 02/10/2026" in before["text"]
    assert "&lt;Alice&gt;" in before["html"] and "<script>" not in before["html"]
    after = build_content(today=datetime.date(2026, 10, 5), **kwargs)
    assert "déposer immédiatement" in after["text"]
    assert "Échéance du 02/10/2026 dépassée" in after["sms"]


def test_a3p_no_permis_and_online_forms_are_not_requested_again():
    trainee = {"no_permis": True, "candidate_sheet_saved_at": "2026-09-01", "documents": [
        {"key": "candidate_info_sheet", "status": "A CONTRÔLER"},
    ], "professional_experience_sheet": {"status": "CONFORME"}}
    required = [{"key": "permis", "label": "Permis"}, {"key": "candidate_info_sheet", "label": "Fiche candidat"}]
    assert document_actions(trainee, required, training_type="A3P", experience_required=True) == []


def test_session_page_renders_the_button_and_shared_script(context):
    client, data, training, trainee, calls = context
    response = client.get("/admin/sessions/S1/trainees")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "RELANCE MANUELLE" in page
    assert "/api/admin/sessions/S1/docs/manual-reminder-preview" in page
    assert "manual-docs-reminder.js" in page
