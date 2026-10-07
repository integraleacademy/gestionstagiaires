import copy
import json

import app as gestion_app
import pytest


ACTIVE = {"check_status": "success", "active_titles": [{"display_status": "AP A3P ACTIF", "date_fin_validite": "2027-03-22"}]}


@pytest.fixture
def cnaps_data(monkeypatch):
    data = {"sessions": [], "cnaps_public_annuaire_statuses": {}, "cnaps_status_change_notifications": {}}
    monkeypatch.setattr(gestion_app, "load_data", lambda **kwargs: data)
    monkeypatch.setattr(gestion_app, "save_data", lambda payload, **kwargs: None)
    monkeypatch.setattr(gestion_app, "CNAPS_MONITOR_REQUEST_DELAY_SECONDS", 0)
    return data


def test_monitor_uses_manual_nub_and_skips_deleted_rows(cnaps_data, monkeypatch):
    row = {"tracking_id": "115", "last_name": "TEST", "first_name": "Jane", "nub": ""}
    deleted = {"tracking_id": "116", "last_name": "DELETED", "first_name": "Jane", "nub": "7654321"}
    gestion_app._record_cnaps_tracking_state(cnaps_data, first_name="Jane", last_name="TEST", nub="", tracking_id="115")
    cnaps_data["cnaps_tracking_manual_nubs"] = {"TEST|JANE": "1234567"}
    cnaps_data["cnaps_tracking_deleted_keys"] = ["DELETED|JANE|7654321"]
    monkeypatch.setattr(gestion_app, "fetch_cnapsv3_tracking_requests", lambda: ([row, deleted], None))
    queries, sent = [], []
    monkeypatch.setattr(gestion_app, "fetch_cnaps_public_annuaire", lambda name, nub: queries.append((name, nub)) or ACTIVE)
    monkeypatch.setattr(gestion_app, "brevo_send_email", lambda *args, **kwargs: sent.append(args) or {"ok": True})
    result = gestion_app.run_cnaps_public_annuaire_monitor()
    assert queries == [("TEST", "1234567")]
    assert result["notified"] == 1
    assert len(sent) == 1
    assert cnaps_data["cnaps_status_change_notifications"]["TEST|1234567"]["email_status"] == "sent"


def test_outbox_persists_before_email_and_retries_without_new_change(cnaps_data, monkeypatch):
    saved = []
    monkeypatch.setattr(gestion_app, "save_data", lambda payload, **kwargs: saved.append(copy.deepcopy(payload)))
    gestion_app._record_cnaps_tracking_state(cnaps_data, first_name="Jane", last_name="TEST", nub="1234567", tracking_id="115", result={"active_titles": []})
    monkeypatch.setattr(gestion_app, "fetch_cnaps_public_annuaire", lambda *args: copy.deepcopy(ACTIVE))
    attempts = []

    def deliver(*args, **kwargs):
        assert any(item["cnaps_status_change_notifications"].get("TEST|1234567", {}).get("email_status") == "pending" for item in saved)
        assert not gestion_app._data_lock._is_owned()
        attempts.append(args)
        return {"ok": len(attempts) > 1, "error": "temporary outage", "message_id": "receipt"}

    monkeypatch.setattr(gestion_app, "brevo_send_email", deliver)
    client = gestion_app.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role="admin")
    response = client.get('/api/cnaps_public_annuaire?nom=TEST&prenom=Jane&nub=1234567&tracking_id=115')
    assert response.status_code == 200
    notification = cnaps_data["cnaps_status_change_notifications"]["TEST|1234567"]
    assert notification["email_status"] == "failed"
    gestion_app._deliver_pending_cnaps_notifications()
    assert len(attempts) == 1  # Backoff, no immediate duplicate.
    notification["email_last_attempt_at"] = "2020-01-01T00:00:00Z"
    gestion_app._deliver_pending_cnaps_notifications()
    assert notification["email_status"] == "sent"
    assert notification["email_message_id"] == "receipt"
    gestion_app._deliver_pending_cnaps_notifications()
    assert len(attempts) == 2


def test_trainee_page_reuses_tracking_identity(cnaps_data, monkeypatch):
    cnaps_data["cnaps_public_annuaire_statuses"] = {
        "TRACKING|115": {"state_code": "no_title", "tracking_id": "115"},
        "TEST|1234567": {"state_code": "no_title", "tracking_id": "115"},
    }
    sent = []
    monkeypatch.setattr(gestion_app, "brevo_send_email", lambda *args, **kwargs: sent.append(args) or {"ok": True})
    assert gestion_app._record_cnaps_tracking_state(cnaps_data, first_name="", last_name="TEST", nub="1234567", result=ACTIVE)
    assert not gestion_app._record_cnaps_tracking_state(cnaps_data, first_name="Jane", last_name="TEST", nub="1234567", tracking_id="115", result=ACTIVE)
    assert len(sent) == 1
    assert cnaps_data["cnaps_public_annuaire_statuses"]["TRACKING|115"]["known"]


def test_unrelated_stale_save_cannot_erase_cnaps_alert_or_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(gestion_app, "DATA_FILE", str(tmp_path / "data.json"))
    monkeypatch.setattr(gestion_app, "BACKUP_DIR", str(tmp_path / "backups"))
    before = {"sessions": [], "cnaps_public_annuaire_statuses": {"TEST|1234567": {"checked_at": "2026-09-23T10:00:00Z", "known": False}}}
    gestion_app.save_data(copy.deepcopy(before))
    current = copy.deepcopy(before)
    current["cnaps_public_annuaire_statuses"]["TEST|1234567"] = {"checked_at": "2026-09-23T11:00:00Z", "known": True}
    current["cnaps_status_change_notifications"] = {"TEST|1234567": {"created_at": "2026-09-23T11:00:00Z", "email_status": "sent", "sent_at": "2026-09-23T11:00:01Z"}}
    gestion_app.save_data(current)
    before["unrelated_field"] = "admin edit"
    gestion_app.save_data(before)
    final = json.loads((tmp_path / "data.json").read_text())
    assert final["unrelated_field"] == "admin edit"
    assert final["cnaps_public_annuaire_statuses"]["TEST|1234567"]["known"]
    assert final["cnaps_status_change_notifications"]["TEST|1234567"]["email_status"] == "sent"


def test_tracking_page_embeds_last_success_before_live_requests(cnaps_data, monkeypatch):
    gestion_app._record_cnaps_tracking_state(cnaps_data, first_name="Jane", last_name="TEST", nub="1234567", tracking_id="115", result=ACTIVE)
    monkeypatch.setattr(gestion_app, "fetch_cnapsv3_tracking_requests", lambda: ([{"tracking_id": "115", "last_name": "TEST", "first_name": "Jane", "nub": "1234567"}], None))
    client = gestion_app.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role="admin")
    response = client.get('/admin/sessions/suivi-cnaps')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-cnaps-snapshot=' in html
    assert 'AP A3P ACTIF' in html
    assert '2027-03-22' in html


@pytest.mark.parametrize('key', ['cnaps_public_annuaire_statuses', 'cnaps_status_change_notifications', 'cnaps_tracking_manual_nubs'])
def test_partner_overlay_never_erases_integrale_cnaps_maps(key):
    internal = {'TEST|1234567': {'known': True}} if key != 'cnaps_tracking_manual_nubs' else {'TEST|JANE': '1234567'}
    external = {'EXTERNAL|7654321': {'known': False}} if key != 'cnaps_tracking_manual_nubs' else {'EXTERNAL|JANE': '7654321'}
    canonical = {'partners': [], key: copy.deepcopy(internal)}
    bundle = {'partners': [{'id': 'external-centre', 'name': 'External'}], key: external}
    gestion_app._overlay_partner_bundle(canonical, bundle, "external-centre")
    assert canonical[key] == internal
    assert gestion_app._filter_data_for_partner(canonical, gestion_app.INTEGRALE_PARTNER_ID)[key] == internal
    assert gestion_app._filter_data_for_partner(canonical, 'external-centre')[key] == external
    assert gestion_app._filter_data_for_partner(canonical, 'another-centre')[key] == {}


def test_monitor_detects_transition_after_loading_external_partner(cnaps_data, monkeypatch):
    original_load = gestion_app.load_data
    bundle = {'partners': [{'id': 'external-centre', 'name': 'External'}]}
    def load_with_overlay(**kwargs):
        data = original_load(**kwargs)
        gestion_app._overlay_partner_bundle(data, bundle, "external-centre")
        return data
    monkeypatch.setattr(gestion_app, 'load_data', load_with_overlay)
    monkeypatch.setattr(gestion_app, 'fetch_cnapsv3_tracking_requests', lambda: ([{'tracking_id': '115', 'last_name': 'TEST', 'first_name': 'Jane', 'nub': '1234567'}], None))
    current = {'check_status': 'success', 'active_titles': []}
    monkeypatch.setattr(gestion_app, 'fetch_cnaps_public_annuaire', lambda *args: copy.deepcopy(current))
    emails = []
    monkeypatch.setattr(gestion_app, 'brevo_send_email', lambda *args, **kwargs: emails.append(args) or {'ok': True})
    assert gestion_app.run_cnaps_public_annuaire_monitor()['notified'] == 0
    current.update(ACTIVE)
    assert gestion_app.run_cnaps_public_annuaire_monitor()['notified'] == 1
    assert gestion_app.run_cnaps_public_annuaire_monitor()['notified'] == 0
    assert len(emails) == 1
    assert gestion_app.load_data()['cnaps_status_change_notifications']['TEST|1234567']['email_status'] == 'sent'
