import copy
import datetime as dt
import fcntl
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

import app as gestion_app
from wedof_automation import run_live_automation, sync_folder_automation_status
from wedof_discovery import merge_verified_folders
from wedof_service import WedofApiError


NOW = dt.datetime(2026, 11, 1, 16, 30, tzinfo=ZoneInfo("Europe/Paris"))


def folder(identifier="F1", start="2026-10-29", end="2026-11-12", state="accepted"):
    return {"externalId": identifier, "type": "cpf", "state": state,
            "trainingActionInfo": {"startDate": start, "endDate": end}}


def test_missing_unlinked_folders_are_caught_up_once_using_original_dates():
    folders = [folder(), folder("F2", "2026-10-30", "2026-12-10")]
    data = {}
    merge_verified_folders(data, folders, observed_at=NOW)
    remote = {f["externalId"]: copy.deepcopy(f) for f in folders}
    client = Mock()
    client.get_registration_folder_for_automation.side_effect = lambda identifier: remote[identifier]
    def declare(identifier, date):
        assert date == remote[identifier]["trainingActionInfo"]["startDate"]
        remote[identifier]["state"] = "inTraining"
    client.declare_registration_folder_in_training.side_effect = declare
    first = run_live_automation(client, data, now=NOW)
    second = run_live_automation(client, data, now=NOW + dt.timedelta(minutes=5))
    assert first["entry_success"] == 2
    assert second["entry_success"] == 0
    assert client.declare_registration_folder_in_training.call_count == 2
    client.declare_registration_folder_service_done.assert_not_called()
    client.list_registration_folders.assert_not_called()
    assert all(row["local_link_status"] == "unlinked" for row in data["wedof_automation_status"])


def test_future_dates_and_existing_blocks_are_preserved():
    block = {"external_id": "BLOCKED", "action": "entry_training", "active": True,
             "reason_code": "no_show"}
    data = {"wedof_automation_blocks": [block]}
    merge_verified_folders(data, [folder("BLOCKED"), folder("LATER", "2026-11-02")], observed_at=NOW)
    client = Mock()
    result = run_live_automation(client, data, now=NOW)
    assert result["blocked"] == 1
    assert data["wedof_automation_blocks"] == [block]
    client.get_registration_folder_for_automation.assert_not_called()
    client.declare_registration_folder_in_training.assert_not_called()


def test_new_historic_enrolment_is_visible_but_requires_review_only_once():
    historic = folder("OLD", "2026-09-21", "2026-10-21")
    data = {}
    first = merge_verified_folders(data, [historic], observed_at=NOW)
    assert first["historical_blocked"] == 1
    assert data["wedof_automation_status"][0]["entry_training"]["status"] == "blocked"
    # The normal admin unblock remains effective on subsequent discoveries.
    data["wedof_automation_blocks"][0]["active"] = False
    second = merge_verified_folders(data, [historic], observed_at=NOW + dt.timedelta(hours=1))
    assert second["historical_blocked"] == 0
    assert data["wedof_automation_status"][0]["entry_training"]["status"] == "dry_run_due_late"


def test_discovery_does_not_block_an_already_tracked_overdue_enrolment():
    historic = folder("OLD", "2026-09-21", "2026-10-21")
    data = {}
    sync_folder_automation_status(data, historic, now=NOW - dt.timedelta(days=20))
    result = merge_verified_folders(data, [historic], observed_at=NOW)
    assert result["historical_blocked"] == 0
    assert data["wedof_automation_status"][0]["entry_training"]["status"] == "dry_run_due_late"


def test_listing_cannot_replace_a_newer_webhook_or_delete_unrelated_records():
    data = {}
    newer = folder(state="canceledByAttendee")
    sync_folder_automation_status(data, newer, now=NOW + dt.timedelta(seconds=1))
    sync_folder_automation_status(data, folder("OTHER"), now=NOW)
    original = copy.deepcopy(data)
    result = merge_verified_folders(data, [folder()], observed_at=NOW)
    assert result["newer_preserved"] == 1
    assert data["wedof_automation_status"] == original["wedof_automation_status"]


@pytest.fixture
def store(monkeypatch):
    data = {}
    monkeypatch.setenv("WEDOF_RECONCILIATION_ENABLED", "true")
    monkeypatch.setattr(gestion_app, "_atomic_update_data", lambda fn: fn(data))
    return data


def test_hourly_discovery_is_durable_and_reads_only_accepted_folders(store):
    client = Mock()
    client.list_registration_folders.return_value = [folder()]
    assert gestion_app._refresh_wedof_accepted_folders(client, now=NOW)["status"] == "success"
    assert store["wedof_automation_status"][0]["external_id"] == "F1"
    assert gestion_app._refresh_wedof_accepted_folders(client, now=NOW + dt.timedelta(minutes=5))["status"] == "not_due"
    assert client.list_registration_folders.call_count == 1
    client.list_registration_folders.assert_called_with("accepted")
    assert gestion_app._refresh_wedof_accepted_folders(client, now=NOW + dt.timedelta(hours=1))["status"] == "success"
    assert client.list_registration_folders.call_count == 2


def test_failed_discovery_keeps_existing_schedules_and_backs_off(store):
    sync_folder_automation_status(store, folder(), now=NOW)
    original = copy.deepcopy(store["wedof_automation_status"])
    client = Mock()
    client.list_registration_folders.side_effect = WedofApiError("unavailable", "wedof_timeout", True)
    result = gestion_app._refresh_wedof_accepted_folders(client, now=NOW)
    assert result == {"status": "error", "error": "wedof_timeout"}
    assert store["wedof_automation_status"] == original
    gestion_app._refresh_wedof_accepted_folders(client, now=NOW + dt.timedelta(minutes=5))
    assert client.list_registration_folders.call_count == 1


def test_disabled_and_maintenance_discovery_do_not_read_wedof(store, monkeypatch):
    client = Mock()
    monkeypatch.setenv("WEDOF_RECONCILIATION_ENABLED", "false")
    assert gestion_app._refresh_wedof_accepted_folders(client, now=NOW)["status"] == "disabled"
    monkeypatch.setenv("WEDOF_RECONCILIATION_ENABLED", "true")
    monkeypatch.setenv("WEDOF_MAINTENANCE_WINDOW_ENABLED", "true")
    assert gestion_app._refresh_wedof_accepted_folders(client, now=NOW.replace(hour=6))["status"] == "skipped_maintenance_window"
    client.list_registration_folders.assert_not_called()


def test_live_wrapper_reloads_discovered_records_before_selecting_work(store, monkeypatch, tmp_path):
    monkeypatch.setattr(gestion_app, "PERSIST_DIR", str(tmp_path))
    monkeypatch.setattr(gestion_app, "WEDOF_AUTOMATION_LOCK_FILE", str(tmp_path / "wedof.lock"))
    monkeypatch.setattr(gestion_app, "_wedof_live_mode_enabled", lambda: True)
    monkeypatch.setattr(gestion_app, "load_data", lambda **kw: copy.deepcopy(store))
    monkeypatch.setattr(gestion_app, "acquire_wedof_governor_lease", lambda *a, **kw: {"acquired": True})
    def discover(client):
        merge_verified_folders(store, [folder()], observed_at=NOW)
        return {"status": "success"}
    monkeypatch.setattr(gestion_app, "_refresh_wedof_accepted_folders", discover)
    def live(client, data, **kw):
        assert data["wedof_automation_status"][0]["external_id"] == "F1"
        return {"ok": True}
    monkeypatch.setattr(gestion_app, "run_live_automation", live)
    monkeypatch.setattr(gestion_app, "WedofClient", Mock())
    assert gestion_app.run_wedof_automation_live()["discovery"] == {"status": "success"}


def test_manual_refresh_waits_for_live_worker_instead_of_overwriting_its_snapshot(store, monkeypatch, tmp_path):
    lock_path = tmp_path / "wedof.lock"
    monkeypatch.setattr(gestion_app, "PERSIST_DIR", str(tmp_path))
    monkeypatch.setattr(gestion_app, "WEDOF_AUTOMATION_LOCK_FILE", str(lock_path))
    client = gestion_app.app.test_client()
    with client.session_transaction() as session:
        session["admin_logged_in"] = True
    with lock_path.open("a+") as held_lock, patch.object(gestion_app, "WedofClient") as remote:
        fcntl.flock(held_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        response = client.post("/admin/wedof/matching/preview")
        assert response.status_code == 302
        remote.assert_not_called()
        assert store == {}


def test_failed_manual_refresh_does_not_replace_persisted_schedules(store, monkeypatch):
    sync_folder_automation_status(store, folder(), now=NOW)
    original = copy.deepcopy(store)
    remote = Mock()
    remote.list_registration_folders.side_effect = WedofApiError("unavailable", "wedof_timeout", True)
    monkeypatch.setattr(gestion_app, "WedofClient", lambda: remote)
    client = gestion_app.app.test_client()
    with client.session_transaction() as session:
        session["admin_logged_in"] = True
    assert client.post("/admin/wedof/matching/preview").status_code == 302
    assert store == original
