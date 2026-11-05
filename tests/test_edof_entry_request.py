import datetime as dt
import json
from types import SimpleNamespace

import pytest

from edof_entry_request import run_entry
from edof_declarations import records
from test_edof_declarations import API_PREFIX, EDOF_HOST, ENTRY, FOLDER, ROW, prepare


class Portal:
    def __init__(self, folder=FOLDER, state="ACCEPTED", effective=None, row=ROW, expected_date="03/01/2026"):
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
