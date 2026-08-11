import datetime as dt
import os
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import requests

import app as gestion_app
from wedof_automation import run_live_automation
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
        return [self.initial] if self.initial["state"] == state else []

    def get_registration_folder(self, external_id):
        self.gets += 1
        return self.after if self.posts and self.after else self.initial

    def declare_registration_folder_in_training(self, external_id, date):
        self.posts.append(("entry_training", external_id, date))
        if self.error: raise self.error

    def declare_registration_folder_service_done(self, external_id, date, **kwargs):
        self.posts.append(("service_done", external_id, date, kwargs))
        if self.error: raise self.error


def test_fail_closed_environment_requires_exact_pair():
    for enabled, dry, expected in [("true", "false", True), ("false", "false", False),
                                   ("true", "true", False), ("invalid", "false", False),
                                   ("true", "", False)]:
        with patch.dict(os.environ, {"WEDOF_AUTOMATION_ENABLED": enabled, "WEDOF_DRY_RUN": dry}, clear=False):
            assert gestion_app._wedof_live_mode_enabled() is expected


def test_entry_due_and_not_before_target_using_only_wedof_date():
    for hour, expected in [(17, 0), (18, 1)]:
        client = Client(folder(start="2026-08-11", localDate="1999-01-01"),
                        folder(state="inTraining", start="2026-08-11"))
        data = {"wedof_automation_actions": [], "wedof_automation_status": [], "wedof_automation_runs": []}
        result = run_live_automation(client, data, now=dt.datetime(2026, 8, 11, hour, 1, tzinfo=PARIS))
        assert len(client.posts) == expected
        assert result["entry_success"] == expected


def test_generic_late_service_done_uses_previous_day_and_is_journalled_for_dashboard():
    initial = folder(state="inTraining", end="2026-08-10")
    client = Client(initial, folder(state="serviceDoneDeclared", end="2026-08-10"))
    data = {"wedof_automation_actions": [], "wedof_automation_status": [], "wedof_automation_runs": []}
    result = run_live_automation(client, data, now=dt.datetime(2026, 8, 11, 8, 0, tzinfo=PARIS))
    assert client.posts[0][:3] == ("service_done", "GENERIC-1", "2026-08-10")
    assert result["service_done_success"] == 1
    assert data["wedof_automation_actions"][0]["status"] == "success"
    assert data["wedof_automation_status"][0]["service_done"]["status"] == "success"
    assert not ({"first_name", "last_name", "email", "phone"} & data["wedof_automation_actions"][0].keys())


def test_manual_block_and_maintenance_prevent_all_mutations():
    initial = folder(state="inTraining", end="2026-08-10")
    for data, now in [({"wedof_automation_blocks": [{"external_id": "GENERIC-1", "action": "service_done", "active": True}]},
                       dt.datetime(2026, 8, 11, 8, tzinfo=PARIS)),
                      ({}, dt.datetime(2026, 8, 11, 6, tzinfo=PARIS))]:
        data.update(wedof_automation_actions=[], wedof_automation_status=[], wedof_automation_runs=[])
        client = Client(initial)
        result = run_live_automation(client, data, now=now)
        assert not client.posts
        assert result.get("blocked", 0) == 1 or result["status"] == "skipped_maintenance_window"


def test_block_added_after_reservation_is_rechecked_before_post():
    client = Client(folder(), folder(state="inTraining"))
    data = {"wedof_automation_blocks": [], "wedof_automation_actions": [],
            "wedof_automation_status": [], "wedof_automation_runs": []}

    def block_during_reservation(current):
        current["wedof_automation_blocks"].append(
            {"external_id": "GENERIC-1", "action": "entry_training", "active": True})

    result = run_live_automation(client, data, now=dt.datetime(2026, 8, 11, 19, tzinfo=PARIS),
                                 persist_reservation=block_during_reservation)
    assert not client.posts
    assert result["blocked"] == 1
    assert data["wedof_automation_actions"][0]["status"] == "blocked"
    assert data["wedof_automation_actions"][0]["last_error_code"] == "manual_block"


def test_double_run_and_old_processing_never_post_twice():
    initial, after = folder(), folder(state="inTraining")
    client = Client(initial, after)
    data = {"wedof_automation_actions": [], "wedof_automation_status": [], "wedof_automation_runs": []}
    now = dt.datetime(2026, 8, 11, 19, tzinfo=PARIS)
    run_live_automation(client, data, now=now)
    run_live_automation(client, data, now=now)
    assert len(client.posts) == 1
    assert len(data["wedof_automation_actions"]) == 1
    stale = Client(initial)
    stale_data = {"wedof_automation_actions": [{**data["wedof_automation_actions"][0], "status": "processing"}],
                  "wedof_automation_status": [], "wedof_automation_runs": []}
    run_live_automation(stale, stale_data, now=now)
    assert not stale.posts
    assert stale_data["wedof_automation_actions"][0]["status"] == "uncertain_after_timeout"


def test_timeout_reconciles_success_or_becomes_uncertain():
    timeout = WedofApiError("timeout", "wedof_timeout", ambiguous=True)
    for after, status in [(folder(state="inTraining"), "success"), (None, "uncertain_after_timeout")]:
        client = Client(folder(), after, timeout)
        data = {"wedof_automation_actions": [], "wedof_automation_status": [], "wedof_automation_runs": []}
        run_live_automation(client, data, now=dt.datetime(2026, 8, 11, 19, tzinfo=PARIS))
        assert len(client.posts) == 1
        assert data["wedof_automation_actions"][0]["status"] == status


def test_http_errors_are_clean_and_never_retried_in_same_run():
    for status in (400, 401, 403, 429, 500):
        error = WedofApiError("clean", "code", status in (429, 500), status)
        client = Client(folder(), error=error)
        data = {"wedof_automation_actions": [], "wedof_automation_status": [], "wedof_automation_runs": []}
        run_live_automation(client, data, now=dt.datetime(2026, 8, 11, 19, tzinfo=PARIS))
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
