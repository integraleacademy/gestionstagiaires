import datetime as dt
import os
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import requests

import app as gestion_app
from wedof_automation import run_live_automation, sync_folder_automation_status
from wedof_matching import extract_folder
from wedof_service import WedofApiError, WedofClient


PARIS = ZoneInfo("Europe/Paris")


def folder(external_id="GENERIC-1", state="accepted", start="2026-08-11", end="2026-08-11", **extra):
    value = {"externalId": external_id, "type": "cpf", "state": state,
             "trainingActionInfo": {"startDate": start, "endDate": end}}
    value.update(extra)
    return value


class Client:
    def __init__(self, initial, after=None, error=None):
        self.initial, self.after, self.error = initial, after, error
        self.posts, self.gets = [], 0

    def list_registration_folders(self, state):
        raise AssertionError("Le live ne doit jamais lister les dossiers WEDOF")

    def get_registration_folder(self, external_id):
        self.gets += 1
        return self.after if self.posts and self.after else self.initial

    def declare_registration_folder_in_training(self, external_id, date):
        self.posts.append(("entry_training", external_id, date))
        if self.error: raise self.error

    def declare_registration_folder_service_done(self, external_id, date, **kwargs):
        self.posts.append(("service_done", external_id, date, kwargs))
        if self.error: raise self.error


def automation_data(initial, now, **extra):
    data = {
        "wedof_automation_actions": [],
        "wedof_automation_status": [],
        "wedof_automation_runs": [],
        "wedof_folder_cache": [{**extract_folder(initial), "synced_at": now.isoformat()}],
        **extra,
    }
    sync_folder_automation_status(data, initial, now=now)
    return data


def automation_rows(folders, now):
    data = {
        "wedof_automation_actions": [],
        "wedof_automation_status": [],
        "wedof_automation_runs": [],
        "wedof_folder_cache": [],
    }
    for current in folders:
        data["wedof_folder_cache"].append({
            **extract_folder(current),
            "synced_at": now.isoformat(),
        })
        sync_folder_automation_status(data, current, now=now)
    return data


def test_live_mode_only_obeys_explicit_kill_switch():
    legacy_values = {
        "WEDOF_AUTOMATION_ENABLED": "false",
        "WEDOF_DRY_RUN": "true",
        "WEDOF_CRON_ENABLED": "false",
    }
    for kill_switch, expected in [
        ("", True), ("false", True), ("0", True), ("true", False), ("1", False),
    ]:
        env = {**legacy_values, "WEDOF_AUTOMATION_KILL_SWITCH": kill_switch}
        with patch.dict(os.environ, env, clear=False):
            assert gestion_app._wedof_live_mode_enabled() is expected

def test_entry_due_and_not_before_target_using_only_wedof_date():
    for hour, expected in [(17, 0), (18, 1)]:
        now = dt.datetime(2026, 8, 11, hour, 1, tzinfo=PARIS)
        initial = folder(start="2026-08-11", localDate="1999-01-01")
        client = Client(initial,
                        folder(state="inTraining", start="2026-08-11"))
        data = automation_data(initial, now)
        result = run_live_automation(client, data, now=now)
        assert len(client.posts) == expected
        assert result["entry_success"] == expected
        assert client.gets == expected * 2


def test_future_live_action_is_persisted_as_planned_without_remote_mutation():
    now = dt.datetime(2026, 8, 12, 15, 25, tzinfo=PARIS)
    initial = folder(start="2026-09-07", end="2026-10-09")
    client = Client(initial)
    data = automation_data(
        initial, now,
        wedof_links=[{"external_id": "GENERIC-1", "active": True}],
    )
    result = run_live_automation(client, data, now=now)
    assert not client.posts
    assert client.gets == 0
    assert result["candidates"] == 0
    assert len(data["wedof_automation_status"]) == 1
    status = data["wedof_automation_status"][0]
    assert status["entry_training"]["status"] == "planned"
    assert status["service_done"]["status"] == "waiting_for_in_training"
    assert status["local_link_status"] == "linked"


def test_generic_folder_cache_never_enrols_a_dossier_into_live_automation():
    now = dt.datetime(2026, 9, 2, 19, 0, tzinfo=PARIS)
    initial = folder("SEARCH-RESULT", start="2026-09-01")
    data = {
        "wedof_automation_actions": [],
        "wedof_automation_status": [],
        "wedof_automation_runs": [],
        "wedof_folder_cache": [{**extract_folder(initial), "synced_at": now.isoformat()}],
    }
    client = Client(initial, folder("SEARCH-RESULT", state="inTraining"))

    result = run_live_automation(client, data, now=now)

    assert result["candidates"] == 0
    assert client.gets == 0
    assert client.posts == []
    assert data["wedof_automation_status"] == []


def test_live_candidates_are_oldest_first_and_bounded_per_run():
    now = dt.datetime(2026, 9, 3, 19, 0, tzinfo=PARIS)
    data = automation_rows([
        folder("NEWEST", start="2026-09-02"),
        folder("OLDEST", start="2026-08-31"),
        folder("MIDDLE", start="2026-09-01"),
    ], now)
    client = Mock()
    client.get_registration_folder.side_effect = WedofApiError(
        "temporary", "wedof_server_error", True, 500,
    )

    with patch.dict(os.environ, {"WEDOF_LIVE_MAX_CANDIDATES_PER_RUN": "2"}):
        result = run_live_automation(client, data, now=now)

    assert [call.args[0] for call in client.get_registration_folder.call_args_list] == [
        "OLDEST", "MIDDLE",
    ]
    assert result["candidates"] == 3
    assert result["selected"] == 2
    assert result["processed"] == 2
    assert result["remaining"] == 1
    assert result["candidate_limit"] == 2


def test_permanent_error_never_hides_a_later_executable_action():
    now = dt.datetime(2026, 9, 3, 19, 0, tzinfo=PARIS)
    data = automation_rows([
        folder("PERMANENT", start="2026-08-31"),
        folder("EXECUTABLE", start="2026-09-01"),
    ], now)
    data["wedof_automation_actions"] = [{
        "external_id": "PERMANENT", "action": "entry_training",
        "status": "error", "last_http_status": 400,
    }]
    client = Mock()
    client.get_registration_folder.side_effect = WedofApiError(
        "temporary", "wedof_server_error", True, 500,
    )

    with patch.dict(os.environ, {"WEDOF_LIVE_MAX_CANDIDATES_PER_RUN": "1"}):
        result = run_live_automation(client, data, now=now)

    client.get_registration_folder.assert_called_once_with("EXECUTABLE")
    assert result["candidates"] == 1
    assert result["processed"] == 1
    assert result["remaining"] == 0


def test_quota_error_stops_the_run_and_keeps_every_due_action_pending():
    now = dt.datetime(2026, 9, 2, 19, 0, tzinfo=PARIS)
    data = automation_rows([
        folder("A", start="2026-09-01"),
        folder("B", start="2026-09-01"),
        folder("C", start="2026-09-01"),
    ], now)
    client = Mock()
    client.get_registration_folder.side_effect = WedofApiError(
        "quota", "wedof_quota_exceeded", False, 429,
    )

    result = run_live_automation(client, data, now=now)

    client.get_registration_folder.assert_called_once_with("A")
    assert result["status"] == "quota_blocked"
    assert result["stop_reason"] == "wedof_quota_exceeded"
    assert result["quota_blocked"] == 1
    assert result["processed"] == 1
    assert result["remaining"] == 2
    statuses = {row["external_id"]: row for row in data["wedof_automation_status"]}
    assert statuses["A"]["entry_training"]["status"] == "quota_blocked"
    assert statuses["A"]["entry_training"]["planned_date"] == "2026-09-01"
    assert statuses["B"]["entry_training"]["status"] == "dry_run_due_late"
    assert statuses["C"]["entry_training"]["status"] == "dry_run_due_late"


def test_generic_late_service_done_uses_previous_day_and_is_journalled_for_dashboard():
    initial = folder(state="inTraining", end="2026-08-10")
    client = Client(initial, folder(state="serviceDoneDeclared", end="2026-08-10"))
    now = dt.datetime(2026, 8, 11, 8, 0, tzinfo=PARIS)
    data = automation_data(initial, now)
    result = run_live_automation(client, data, now=now)
    assert client.posts[0][:3] == ("service_done", "GENERIC-1", "2026-08-10")
    assert result["service_done_success"] == 1
    assert data["wedof_automation_actions"][0]["status"] == "success"
    assert data["wedof_automation_status"][0]["service_done"]["status"] == "success"
    assert not ({"first_name", "last_name", "email", "phone"} & data["wedof_automation_actions"][0].keys())


def test_manual_block_and_maintenance_prevent_all_mutations():
    initial = folder(state="inTraining", end="2026-08-10")
    for extra, now in [({"wedof_automation_blocks": [{"external_id": "GENERIC-1", "action": "service_done", "active": True}]},
                       dt.datetime(2026, 8, 11, 8, tzinfo=PARIS)),
                      ({}, dt.datetime(2026, 8, 11, 6, tzinfo=PARIS))]:
        data = automation_data(initial, now, **extra)
        client = Client(initial)
        result = run_live_automation(client, data, now=now)
        assert not client.posts
        assert result.get("blocked", 0) == 1 or result["status"] == "skipped_maintenance_window"


def test_block_added_after_reservation_is_rechecked_before_post():
    initial = folder()
    now = dt.datetime(2026, 8, 11, 19, tzinfo=PARIS)
    client = Client(initial, folder(state="inTraining"))
    data = automation_data(initial, now, wedof_automation_blocks=[])

    def block_during_reservation(current):
        current["wedof_automation_blocks"].append(
            {"external_id": "GENERIC-1", "action": "entry_training", "active": True})

    result = run_live_automation(client, data, now=now,
                                 persist_reservation=block_during_reservation)
    assert not client.posts
    assert result["blocked"] == 1
    assert data["wedof_automation_actions"][0]["status"] == "blocked"
    assert data["wedof_automation_actions"][0]["last_error_code"] == "manual_block"


def test_double_run_and_old_processing_never_post_twice():
    initial, after = folder(), folder(state="inTraining")
    client = Client(initial, after)
    now = dt.datetime(2026, 8, 11, 19, tzinfo=PARIS)
    data = automation_data(initial, now)
    run_live_automation(client, data, now=now)
    run_live_automation(client, data, now=now)
    assert len(client.posts) == 1
    assert len(data["wedof_automation_actions"]) == 1
    stale = Client(initial)
    stale_data = automation_data(initial, now)
    stale_data["wedof_automation_actions"] = [
        {**data["wedof_automation_actions"][0], "status": "processing"},
    ]
    run_live_automation(stale, stale_data, now=now)
    assert not stale.posts
    assert stale_data["wedof_automation_actions"][0]["status"] == "uncertain_after_timeout"


def test_timeout_reconciles_success_or_becomes_uncertain():
    timeout = WedofApiError("timeout", "wedof_timeout", ambiguous=True)
    for after, status in [(folder(state="inTraining"), "success"), (None, "uncertain_after_timeout")]:
        client = Client(folder(), after, timeout)
        now = dt.datetime(2026, 8, 11, 19, tzinfo=PARIS)
        data = automation_data(client.initial, now)
        run_live_automation(client, data, now=now)
        assert len(client.posts) == 1
        assert data["wedof_automation_actions"][0]["status"] == status


def test_http_errors_are_clean_and_never_retried_in_same_run():
    for status in (400, 401, 403, 429, 500):
        error = WedofApiError("clean", "code", status in (429, 500), status)
        client = Client(folder(), error=error)
        now = dt.datetime(2026, 8, 11, 19, tzinfo=PARIS)
        data = automation_data(client.initial, now)
        run_live_automation(client, data, now=now)
        assert len(client.posts) == 1
        assert data["wedof_automation_actions"][0]["last_http_status"] == status


def test_mutating_http_client_has_exact_payloads_and_one_attempt_on_timeout():
    session = Mock()
    session.post.side_effect = requests.Timeout()
    client = WedofClient("not-a-real-key", session=session)
    try:
        client.declare_registration_folder_in_training("X1", "2026-08-11")
    except WedofApiError as exc:
        assert exc.ambiguous
    assert session.post.call_count == 1
    session.post.reset_mock(side_effect=True)
    response = Mock(status_code=204, content=b"")
    session.post.return_value = response
    client.declare_registration_folder_service_done("X1", "2026-08-10")
    assert session.post.call_args.kwargs["json"] == {"absenceDuration": 0,
        "forceMajeureAbsence": False, "date": "2026-08-10"}
