import copy
import datetime as dt
from pathlib import Path
from unittest.mock import Mock

import pytest

import app as gestion
import ssiap_pathways as paths
from automatic_training_attestations import _scheduled_date


@pytest.fixture
def case(monkeypatch):
    trainee = {"id": "T1", "first_name": "Alice", "last_name": "EXEMPLE",
               "email": "alice@example.test", "ssiap_pathway": "ssiap",
               "training_price": "980", "public_token": "sample-ssiapseul"}
    training = {"id": "S1", "name": "SSIAP 1 NOVEMBRE", "training_type": "SSIAP",
                "date_start": "2026-11-09", "date_end": "2026-11-20", "exam_date": "2026-11-23",
                "trainees": [trainee]}
    training["ssiap_pathways"] = paths.validate(training, {
        **paths.DEFAULTS, "sst_dates": ["2026-11-06", "2026-11-05"],
        "ssiap_price": "980", "ssiap_sst_price": "1120"})
    data = {"sessions": [training]}
    monkeypatch.setattr(gestion, "load_data", lambda *a, **kw: data)
    monkeypatch.setattr(gestion, "save_data", Mock())
    monkeypatch.setattr(gestion, "_atomic_update_data", lambda mutate: mutate(data))
    email = Mock()
    monkeypatch.setattr(gestion, "brevo_send_email", email)
    monkeypatch.setattr(gestion, "brevo_send_sms", Mock())
    client = gestion.app.test_client()
    with client.session_transaction() as session:
        session["admin_logged_in"] = True
        session["admin_role"] = "admin"
    return training, trainee, client, email


def test_same_session_resolves_two_individual_schedules(case):
    training, trainee, _, _ = case
    alone = paths.resolve(training, trainee)
    combined = paths.resolve(training, {**trainee, "ssiap_pathway": "ssiap_sst"})
    assert (alone["date_start"], alone["total_hours"], alone["sst_dates"]) == ("2026-11-09", "70", [])
    assert (combined["date_start"], combined["total_hours"], combined["price"]) == ("2026-11-05", "84", "1120")
    assert combined["ssiap_start"] == training["date_start"] == "2026-11-09"
    assert paths.resolve({"training_type": "APS"}, trainee) is None
    assert paths.resolve({"training_type": "SSIAP"}, trainee) is None


@pytest.mark.parametrize("change", [
    {"sst_dates": "2026-11-05"}, {"sst_dates": ["invalid"]},
    {"ssiap_hours": "NaN"}, {"sst_hours": "0"}, {"ssiap_price": "-2"}])
def test_invalid_settings_are_rejected_without_saving(case, change):
    training, _, client, email = case
    before = copy.deepcopy(training)
    response = client.post('/api/sessions/S1/update', json={"ssiap_pathways": {**training["ssiap_pathways"], **change}})
    assert response.status_code == 400
    assert training == before
    gestion.save_data.assert_not_called()
    email.assert_not_called()


def test_config_and_choice_preserve_existing_documents_and_financing(case):
    training, trainee, client, email = case
    trainee.update(convention_aps_pdf_path="signed.pdf", convocation_aps_sent_at="2026-10-01",
                   cpf_amount="800", yousign={"status": "done", "signed_pdf_path": "signed.pdf"})
    signed_state = copy.deepcopy(trainee["yousign"])
    response = client.post('/api/sessions/S1/stagiaires/T1/parcours-ssiap',
                           json={"ssiap_pathway": "ssiap_sst", "training_price": "1120"})
    assert response.status_code == 200
    assert trainee["ssiap_pathway"] == "ssiap_sst"
    assert trainee["training_price"] == "1120"
    assert trainee["cpf_amount"] == "800"
    assert trainee["yousign"] == signed_state
    assert trainee["ssiap_pathway_history"][-1]["convention_aps_pdf_path"] == "signed.pdf"
    assert trainee["convocation_aps_sent_at"] == "2026-10-01"
    email.assert_not_called()
    response = client.post('/api/sessions/S1/update', json={"ssiap_pathways": {**training["ssiap_pathways"], "sst_dates": []}})
    assert response.status_code == 400


def test_choice_requires_dates_and_respects_cancellation_and_read_only(case):
    training, trainee, client, _ = case
    url = '/api/sessions/S1/stagiaires/T1/parcours-ssiap'
    payload = {"ssiap_pathway": "ssiap_sst", "training_price": "1120"}
    training["ssiap_pathways"]["sst_dates"] = []
    assert client.post(url, json=payload).status_code == 400
    trainee["registration_cancelled"] = True
    assert client.post(url, json=payload).status_code == 409
    with client.session_transaction() as session:
        session["admin_role"] = "viewer"
    assert client.post(url, json=payload).status_code == 403
    assert client.post('/api/sessions/S1/update', json={"ssiap_pathways": {}}).status_code == 403


def test_create_selects_path_and_price_without_email(case):
    training, _, client, email = case
    response = client.post('/api/sessions/S1/trainees/create', json={
        "first_name": "Bob", "last_name": "Exemple", "email": "bob@example.test",
        "send_access": False, "ssiap_pathway": "ssiap_sst"})
    assert response.status_code == 200
    assert response.json["ssiap_pathway"] == "ssiap_sst"
    assert str(response.json["training_price"]) == "1120"
    assert len(training["trainees"]) == 2
    email.assert_not_called()


@pytest.mark.parametrize("suffix", ["parcours-ssiap", "stagiaires/T1/parcours-ssiap", "convocations-ssiap"])
def test_admin_screens_render_both_choices(case, suffix):
    _, _, client, email = case
    response = client.get('/admin/sessions/S1/' + suffix)
    assert response.status_code == 200
    assert "SSIAP" in response.text and "SST" in response.text
    email.assert_not_called()


def test_documents_and_emails_use_individual_dates_and_hours(case):
    training, trainee, _, _ = case
    for choice, start, duration in [("ssiap", "09/11/2026", "70"), ("ssiap_sst", "05/11/2026", "84")]:
        trainee["ssiap_pathway"] = choice
        for build in [gestion._build_aps_convocation_context, gestion._build_aps_entry_attestation_context,
                      gestion._build_aps_end_attestation_context, gestion._aps_convention_replacements]:
            context = build(training, trainee)
            assert context["date_debut_formation"] == start
            assert context["h_total"] == duration
            assert ("SST :" in context["detail_parcours"]) == (choice == "ssiap_sst")
        subject, body = gestion._build_aps_convocation_email("Alice", session_obj=training, trainee=trainee)
        assert paths.CHOICES[choice] in subject
        assert start in body
        template = gestion._ssiap_document_template(training, trainee, "convocation", gestion._aps_template_path)
        assert Path(template).is_file()
        assert template.endswith('_sst.docx') == (choice == "ssiap_sst")


def test_convention_requires_explicit_price_but_accepts_zero(case):
    training, trainee, _, _ = case
    trainee["training_price"] = ""
    training["ssiap_pathways"]["ssiap_price"] = ""
    with pytest.raises(ValueError, match="tarif"):
        gestion._aps_convention_replacements(training, trainee)
    trainee["training_price"] = "0"
    assert gestion._aps_convention_replacements(training, trainee)["montant_formation"] == "0"


def test_new_document_does_not_overwrite_previous_version(case):
    training, trainee, _, _ = case
    one = gestion._ssiap_document_filename('convocation', training, trainee)
    two = gestion._ssiap_document_filename('convocation', training, trainee)
    assert one != two
    assert gestion._ssiap_document_filename('convocation', {"training_type": "APS"}, trainee) == 'convocation'


def test_reminder_and_attestation_dates_follow_each_trainee(case, monkeypatch):
    training, solo, _, email = case
    today = dt.datetime.utcnow().date()
    training["date_start"] = (today + dt.timedelta(days=9)).isoformat()
    training["date_end"] = (today + dt.timedelta(days=20)).isoformat()
    training["ssiap_pathways"]["sst_dates"] = [(today + dt.timedelta(days=7)).isoformat(),
                                              (today + dt.timedelta(days=22)).isoformat()]
    combined = {**solo, "id": "T2", "ssiap_pathway": "ssiap_sst"}
    solo["convocation_aps_sent_at"] = combined["convocation_aps_sent_at"] = "2026-01-01"
    training["trainees"].append(combined)
    resend = Mock()
    monkeypatch.setattr(gestion, '_resend_convocation_before_training', resend)
    assert gestion.run_training_convocation_reminders({"sessions": [training]})["sent"] == 1
    assert resend.call_args.args[1]["id"] == "T2"
    assert _scheduled_date(gestion, training, "entry", solo) == today + dt.timedelta(days=9)
    assert _scheduled_date(gestion, training, "entry", combined) == today + dt.timedelta(days=7)
    assert _scheduled_date(gestion, training, "end", combined) == today + dt.timedelta(days=22)
    email.assert_not_called()


def test_bulk_send_skips_already_issued_convocation(case):
    _, trainee, client, email = case
    trainee["convocation_aps_sent_at"] = "2026-10-01"
    response = client.post('/admin/sessions/S1/stagiaires/T1/convocation-aps/send',
                           json={"skip_if_already_sent": True})
    assert response.status_code == 200
    assert response.json["skipped"] is True
    email.assert_not_called()
