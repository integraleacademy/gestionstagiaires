"""Only a title becoming ACTIF may create/display/send a CNAPS alert."""
import copy

import pytest

import app as host


ACTIVE = {"check_status": "success", "active_titles": [
    {"display_status": "AP SH ACTIF", "date_fin_validite": "2027-03-22"}
]}
EMPTY = {"check_status": "success", "active_titles": []}
IDENTITY = {"first_name": "Jane", "last_name": "DOE", "nub": "1234567", "tracking_id": "158"}


@pytest.fixture
def state(monkeypatch):
    data = {"sessions": [], "cnaps_public_annuaire_statuses": {}, "cnaps_status_change_notifications": {}}
    emails = []
    monkeypatch.setattr(host, "load_data", lambda **kwargs: data)
    monkeypatch.setattr(host, "save_data", lambda *args, **kwargs: None)
    monkeypatch.setattr(host, "update_data", lambda fn, **kwargs: fn(data))
    monkeypatch.setattr(host, "brevo_send_email", lambda *args, **kwargs: emails.append(args) or {"ok": True, "message_id": "test-only"})
    monkeypatch.setattr(host, "CNAPS_MONITOR_REQUEST_DELAY_SECONDS", 0)
    return data, emails


@pytest.mark.parametrize("status", [
    "", "NUB absent", "Aucun titre CNAPS trouvé", "AP SH INACTIF", "AP SH REFUSÉ",
    "INCONNU", "En cours", "Vérification CNAPS impossible", "NON ACTIF", "PAS ACTIF", "NON-ACTIF",
])
def test_non_active_targets_never_create_alerts(state, status):
    data, emails = state
    assert not host._create_cnaps_status_change_notification(
        data, **IDENTITY, previous_status="NUB absent", new_status=status)
    assert data["cnaps_status_change_notifications"] == {}
    assert emails == []
    assert host._cnaps_pending_status_change_count(data) == 0


@pytest.mark.parametrize("previous", ["NUB absent", "Aucun titre CNAPS trouvé", "AP SH INACTIF", "AP SH REFUSÉ"])
def test_only_actual_activation_notifies_once(state, previous):
    data, emails = state
    data["cnaps_public_annuaire_statuses"]["TRACKING|158"] = {"display_status": previous, "signature": previous}
    assert host._record_cnaps_tracking_state(data, **IDENTITY, result=copy.deepcopy(ACTIVE))
    assert not host._record_cnaps_tracking_state(data, **IDENTITY, result=copy.deepcopy(ACTIVE))
    assert len(emails) == 1
    assert host._cnaps_pending_status_change_count(data) == 1


def test_missing_nub_then_no_title_then_active(state):
    data, emails = state
    host._record_cnaps_tracking_state(data, **{**IDENTITY, "nub": ""})
    assert not host._record_cnaps_tracking_state(data, **IDENTITY, result=copy.deepcopy(EMPTY))
    assert data["cnaps_public_annuaire_statuses"]["TRACKING|158"]["state_code"] == "no_title"
    assert not emails
    assert host._record_cnaps_tracking_state(data, **IDENTITY, result=copy.deepcopy(ACTIVE))
    assert len(emails) == 1
    assert "Aucun titre CNAPS trouvé" in emails[0][2]


def test_first_active_snapshot_is_a_baseline_not_a_mass_alert(state):
    data, emails = state
    assert not host._record_cnaps_tracking_state(data, **IDENTITY, result=copy.deepcopy(ACTIVE))
    assert not emails
    assert host._cnaps_pending_status_change_count(data) == 0


def test_active_expiry_or_format_change_does_not_notify(state):
    data, emails = state
    data["cnaps_public_annuaire_statuses"]["TRACKING|158"] = {
        "signature": "Autorisation préalable - Surveillance humaine ou gardiennage • ACTIF",
        "known": True,
    }
    assert not host._record_cnaps_tracking_state(data, **IDENTITY, result=copy.deepcopy(ACTIVE))
    renewed = copy.deepcopy(ACTIVE)
    renewed["active_titles"][0]["date_fin_validite"] = "2028-03-22"
    assert not host._record_cnaps_tracking_state(data, **IDENTITY, result=renewed)
    assert not emails
    assert not data["cnaps_status_change_notifications"]


def test_additional_distinct_title_becoming_active_is_not_lost(state):
    data, emails = state
    host._record_cnaps_tracking_state(data, **IDENTITY, result=copy.deepcopy(ACTIVE))
    additional = copy.deepcopy(ACTIVE)
    additional["active_titles"].append({"display_status": "CP SH ACTIF"})
    assert host._record_cnaps_tracking_state(data, **IDENTITY, result=additional)
    assert not host._record_cnaps_tracking_state(data, **IDENTITY, result=additional)
    assert len(emails) == 1


@pytest.mark.parametrize("result", [
    {"check_status": "error", "active_titles": []},
    {**ACTIVE, "check_status": "error"},
])
def test_error_is_not_a_transition_even_with_stale_active_payload(state, result):
    data, emails = state
    host._record_cnaps_tracking_state(data, **{**IDENTITY, "nub": ""})
    before = copy.deepcopy(data)
    assert not host._record_cnaps_tracking_state(data, **IDENTITY, result=copy.deepcopy(result))
    assert not host._notify_cnaps_status_change(data, **IDENTITY, result=copy.deepcopy(result))
    assert data == before
    assert not emails


def test_legacy_false_alerts_disappear_from_badges_without_deleting_history(state):
    data, _ = state
    data["cnaps_status_change_notifications"] = {
        "DOE|1234567": {"signature": "Aucun titre CNAPS trouvé", "previous_status": "NUB absent", "tracking_id": "158", "email_status": "sent", "email_message_id": "preserve-receipt"},
        "MISSING|": {"signature": "NUB absent", "tracking_id": "159"},
        "RENEWED|7654321": {"signature": "AP SH ACTIF • 2028-01-01", "previous_status": "AP SH ACTIF • 2027-01-01"},
        "REAL|2345678": {"signature": "AP SH ACTIF", "previous_status": "Aucun titre CNAPS trouvé"},
        "SEEN|3456789": {"signature": "CP SH ACTIF", "reviewed_at": "2026-09-01T10:00:00Z"},
    }
    before = copy.deepcopy(data)
    rows = host._annotate_cnaps_tracking_status_changes([
        {**IDENTITY},
        {"last_name": "MISSING", "nub": "", "tracking_id": "159"},
        {"last_name": "RENEWED", "nub": "7654321"},
        {"last_name": "REAL", "nub": "2345678"},
        {"last_name": "SEEN", "nub": "3456789"},
    ], data)
    by_name = {row["last_name"]: row for row in rows}
    assert not by_name["DOE"]["status_change_notified"]
    assert not by_name["MISSING"]["status_change_notified"]
    assert not by_name["RENEWED"]["status_change_notified"]
    assert by_name["REAL"]["status_change_notified"]
    assert by_name["SEEN"]["status_change_reviewed"]
    assert host._cnaps_pending_status_change_count(data) == 1
    assert data == before  # In particular, never erase an email receipt.


def test_tracking_id_fallback_also_filters_legacy_false_alert(state):
    data, _ = state
    data["cnaps_status_change_notifications"]["OLD|1234567"] = {
        "signature": "Aucun titre CNAPS trouvé", "tracking_id": "158"}
    row = host._annotate_cnaps_tracking_status_changes([{**IDENTITY}], data)[0]
    assert not row["status_change_notified"]


def test_old_invalid_outbox_is_cancelled_not_resent(state):
    data, emails = state
    data["cnaps_status_change_notifications"] = {
        "DOE|1234567": {"signature": "Aucun titre CNAPS trouvé", "previous_status": "NUB absent", "email_status": "failed", "created_at": "2026-09-01T10:00:00Z"},
        "MISSING|": {"signature": "NUB absent", "email_status": "pending"},
        "REAL|2345678": {"signature": "AP SH ACTIF", "previous_status": "Aucun titre CNAPS trouvé", "email_status": "pending", "last_name": "REAL", "nub": "2345678"},
    }
    host._deliver_pending_cnaps_notifications()
    assert len(emails) == 1
    assert data["cnaps_status_change_notifications"]["REAL|2345678"]["email_status"] == "sent"
    for key in ("DOE|1234567", "MISSING|"):
        entry = data["cnaps_status_change_notifications"][key]
        assert entry["email_status"] == "cancelled"
        assert entry["email_cancelled_reason"] == "not_an_activation"
    host._deliver_pending_cnaps_notifications()
    assert len(emails) == 1


def test_page_and_sidebar_counter_filter_false_alert_even_on_fetch_failure(state, monkeypatch):
    data, _ = state
    data["cnaps_status_change_notifications"]["DOE|1234567"] = {
        "signature": "Aucun titre CNAPS trouvé", "previous_status": "NUB absent", "tracking_id": "158"}
    monkeypatch.setattr(host, "fetch_cnapsv3_tracking_requests", lambda: ([{**IDENTITY}], None))
    client = host.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role="admin")
    response = client.get("/admin/sessions/suivi-cnaps")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-status-change="false" data-last-name="DOE"' in html
    assert '<span class="cnaps-status-change ' not in html
    assert client.get("/api/cnaps_status_changes/pending").get_json()["count"] == 0
    monkeypatch.setattr(host, "fetch_cnapsv3_tracking_requests", lambda: ([], "temporarily unavailable"))
    assert client.get("/api/cnaps_status_changes/pending").get_json()["count"] == 0


def test_monitor_only_notifies_after_later_activation(state, monkeypatch):
    data, emails = state
    row = {**IDENTITY, "nub": ""}
    current = copy.deepcopy(EMPTY)
    monkeypatch.setattr(host, "fetch_cnapsv3_tracking_requests", lambda: ([row], None))
    monkeypatch.setattr(host, "fetch_cnaps_public_annuaire", lambda *args: copy.deepcopy(current))
    assert host.run_cnaps_public_annuaire_monitor()["notified"] == 0
    row["nub"] = IDENTITY["nub"]
    assert host.run_cnaps_public_annuaire_monitor()["notified"] == 0
    assert emails == []
    current.update(ACTIVE)
    assert host.run_cnaps_public_annuaire_monitor()["notified"] == 1
    assert host.run_cnaps_public_annuaire_monitor()["notified"] == 0
    assert len(emails) == 1
