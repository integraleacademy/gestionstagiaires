import datetime as dt
import json
from types import SimpleNamespace

import pytest

from edof_entry_request import run_entry
from edof_declarations import records
from test_edof_declarations import API_PREFIX, EDOF_HOST, ENTRY as HISTORICAL_ENTRY, FOLDER, ROW, prepare


ENTRY = {**HISTORICAL_ENTRY, "actual_date": ROW["session_start_date"]}


class Portal:
    def __init__(self, folder=FOLDER, state="ACCEPTED", effective=None, row=ROW, expected_date="01/01/2026"):
        self.folder, self.state, self.effective = folder, state, effective
        self.row, self.expected_date = row, expected_date
        self.writes = []
        self.refused = False
        self.request = self

    def get(self, url, **options):
        assert url.endswith("/" + FOLDER) and options["max_redirects"] == 0
        data = {"id": self.folder, "attendee": {"firstName": self.row["first_name"], "lastName": self.row["last_name"]},
                "trainingActionInfo": {"sessionStartDate": self.row["session_start_date"], "sessionEndDate": self.row["session_end_date"]},
                "currentState": self.state, "beginDate": self.effective}
        return SimpleNamespace(url=url, status=200, body=lambda: json.dumps(data).encode(), dispose=lambda: None)

    def put(self, url, data, **options):
        assert url.endswith("/" + FOLDER + "/status") and options["max_redirects"] == 0
        assert data == {"state": "IN_TRAINING", "date": self.expected_date}
        self.writes.append(data)
        if not self.refused:
            self.state, self.effective = "IN_TRAINING", data["date"]
        return SimpleNamespace(url=url, status=422 if self.refused else 204, dispose=lambda: None)


def run(portal, spec, path, origin=EDOF_HOST):
    witness = SimpleNamespace(url="https://" + origin + API_PREFIX + "pad", method="GET", all_headers=lambda: {})
    return run_entry(portal, witness, spec, path, EDOF_HOST, API_PREFIX)["code"]


def test_reads_before_and_after_single_reserved_write(tmp_path):
    portal = Portal()
    spec = prepare(tmp_path, ENTRY)
    assert run(portal, spec, tmp_path) == "declaration_confirmed"
    assert len(portal.writes) == 1 and records(tmp_path)[0]["status"] == "sending"
    assert run(portal, spec, tmp_path) == "declaration_confirmed"
    assert len(portal.writes) == 1


@pytest.mark.parametrize("portal,mode,origin,reason", [
    (Portal(folder="987654321"), "declare", EDOF_HOST, "declaration_changed"),
    (Portal(state="CANCELLED"), "declare", EDOF_HOST, "declaration_changed"),
    (Portal(state="IN_TRAINING", effective="04/01/2026"), "reconcile", EDOF_HOST, "declaration_unverified"),
    (Portal(), "reconcile", EDOF_HOST, "declaration_unverified"),
    (Portal(), "declare", "example.invalid", "declaration_changed"),
])
def test_no_write_for_mismatch_or_reconciliation(tmp_path, portal, mode, origin, reason):
    spec = prepare(tmp_path, ENTRY)
    assert run(portal, {**spec, "mode": mode}, tmp_path, origin) == reason
    assert not portal.writes


def test_refusal_requires_unchanged_dossier_and_cannot_replay(tmp_path):
    spec = prepare(tmp_path, ENTRY)
    portal = Portal()
    portal.refused = True
    assert run(portal, spec, tmp_path) == "declaration_refused"
    assert run(portal, spec, tmp_path) == "declaration_blocked"
    assert len(portal.writes) == 1


def test_accepted_folder_on_6_november_is_sent_once_with_its_edof_date(tmp_path, monkeypatch):
    import cpf_provider
    import edof_declarations as ledger
    from edof_schedule import PARIS

    instant = dt.datetime(2026, 11, 6, 18, tzinfo=PARIS)

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(dt, "datetime", Clock)
    monkeypatch.setattr(cpf_provider, "on_test_service", lambda: True)
    monkeypatch.setattr(ledger, "authoritative_proofs", lambda ids: {folder: {"blocks": []} for folder in ids})
    cpf_provider.ProviderStore(tmp_path).switch("integrale", 0, "admin")
    row = {**ROW, "state": "accepted", "session_start_date": "2026-11-06", "session_end_date": "2026-11-20"}
    store = SimpleNamespace(directory=tmp_path, data_file=None)
    snapshot = {"rows": {FOLDER: row}}

    assert ledger.discover(store, "owner", snapshot)["entry_training"] == 1
    spec = ledger.next_job(store, 1)
    assert ledger.check_before_job(store, spec)
    portal = Portal(row=row, expected_date="06/11/2026")
    assert run(portal, spec, tmp_path) == "declaration_confirmed"
    ledger.complete(tmp_path, spec, "declaration_confirmed", portal.state)
    assert ledger.discover(store, "owner", snapshot)["existing"] == 1
    assert ledger.next_job(store, 1) is None
    assert len(portal.writes) == 1


class CompletionPortal(Portal):
    def __init__(self, state="inTraining", rate=None, end=None):
        super().__init__(state=state, effective=ROW["session_start_date"])
        self.rate, self.end = rate, end
        self.after_write = "serviceDoneDeclared"

    def get(self, url, **options):
        response = super().get(url, **options)
        data = json.loads(response.body())
        data["endDate"] = self.end
        data["trainingActionInfo"]["trainingCompletionRate"] = self.rate
        response.body = lambda: json.dumps(data).encode()
        return response

    def put(self, url, data, **options):
        assert url == "https://" + EDOF_HOST + API_PREFIX + FOLDER + "/status"
        assert options["max_redirects"] == 0
        assert data == {"state": "TERMINATED", "terminatedDate": "30/01/2026", "completed": True,
                        "absenceUnit": "", "absenceDuration": 0, "achievementRate": 100,
                        "forceMajeureAbsence": False, "terminatedReason": "8"}
        self.writes.append(data)
        self.state, self.end, self.rate = self.after_write, data["terminatedDate"], 100
        return SimpleNamespace(url=url, status=200, dispose=lambda: None)


def complete_service(portal, spec, path):
    from edof_entry_request import run_full_completion
    witness = SimpleNamespace(url="https://" + EDOF_HOST + API_PREFIX, method="GET", all_headers=lambda: {})
    return run_full_completion(portal, witness, spec, path, EDOF_HOST, API_PREFIX)


def test_combined_exit_needs_official_date_rate_and_status_and_never_replays(tmp_path):
    from test_edof_declarations import EXIT
    spec = prepare(tmp_path, {**EXIT, "actual_date": ROW["session_end_date"], "rate": 100, "motif": ""})
    portal = CompletionPortal()
    assert complete_service(portal, spec, tmp_path)["code"] == "declaration_confirmed"
    assert complete_service(portal, spec, tmp_path)["code"] == "declaration_confirmed"
    portal.state = "SERVICE_DONE_DECLARED"
    assert complete_service(portal, {**spec, "mode": "reconcile"}, tmp_path)["code"] == "declaration_confirmed"
    for end, rate in (("28/01/2026", 100), ("30/01/2026", None), ("30/01/2026", 90)):
        portal.end, portal.rate = end, rate
        assert complete_service(portal, {**spec, "mode": "reconcile"}, tmp_path)["code"] == "declaration_unverified"
    assert len(portal.writes) == 1


def test_exit_only_and_uncertain_receipts_are_not_full_confirmation(tmp_path):
    from test_edof_declarations import EXIT
    spec = prepare(tmp_path, {**EXIT, "actual_date": ROW["session_end_date"], "rate": 100, "motif": ""})
    portal = CompletionPortal()
    portal.after_write = "terminated"
    assert complete_service(portal, spec, tmp_path)["code"] == "declaration_exit_confirmed"
    assert complete_service(portal, {**spec, "mode": "reconcile"}, tmp_path)["code"] == "declaration_exit_confirmed"
    portal.state = "inTraining"
    assert complete_service(portal, spec, tmp_path)["code"] == "declaration_blocked"
    assert len(portal.writes) == 1


@pytest.mark.parametrize("action", ["partial", "hold", "before_entry", "hours", "other_folder", "wrong_state", "other_end_date"])
def test_exit_request_rejects_ineligible_operations(tmp_path, action):
    from test_edof_declarations import EXIT
    from edof_declarations import hold_folder
    spec = prepare(tmp_path, {**EXIT, "actual_date": ROW["session_end_date"], "rate": 100, "motif": ""})
    portal = CompletionPortal()
    if action == "partial":
        spec["intent"]["rate"] = 90
    elif action == "hold":
        hold_folder(tmp_path, FOLDER, True)
    elif action == "before_entry":
        portal.effective = "31/01/2026"
    elif action == "hours":
        spec["intent"].update(source="local", actual_hours="10")
    elif action == "other_end_date":
        spec["intent"]["actual_date"] = "2026-01-28"
    elif action == "other_folder":
        portal.folder = "987654321"
    elif action == "wrong_state":
        portal.state = "canceled"
    assert complete_service(portal, spec, tmp_path)["code"] in {
        "declaration_changed", "declaration_blocked", "declaration_evidence_changed", "declaration_terms_mismatch"}
    assert not portal.writes
