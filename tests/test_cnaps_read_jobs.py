import copy
import threading

import pytest

import app as legacy
from cnaps_read_jobs import CnapsQueue


ASYNC = {"Prefer": "respond-async"}
DIRECTORY = "/api/cnaps_public_annuaire?nom=Test&prenom=Camille&nub=0123456&cache=bypass"


def client_for(role="admin", partner_id=""):
    client = legacy.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role=role, partner_id=partner_id)
    return client


@pytest.fixture
def runner(monkeypatch):
    queue = CnapsQueue(legacy.app, capacity=2, history_limit=5)
    monkeypatch.setitem(legacy.app.extensions, "cnaps_read_jobs", queue)
    return queue


def test_directory_async_deduplicates_scopes_bounds_and_persists_once(monkeypatch, runner):
    data = {"sessions": [], "cnaps_public_annuaire_statuses": {}}
    requests = []
    deliveries = []
    source_started, release = threading.Event(), threading.Event()

    def fetch(name, nub):
        requests.append((name, nub))
        source_started.set()
        assert release.wait(5)
        return {"check_status": "success", "active_titles": []}

    monkeypatch.setattr(legacy, "fetch_cnaps_public_annuaire", fetch)
    monkeypatch.setattr(legacy, "load_data", lambda **kwargs: data)
    monkeypatch.setattr(legacy, "save_data", lambda data, **kwargs: None)
    monkeypatch.setattr(legacy, "_deliver_pending_cnaps_notifications", lambda: deliveries.append(True))
    client = client_for()
    try:
        accepted = client.get(DIRECTORY, headers=ASYNC)
        assert accepted.status_code == 202 and source_started.wait(5)
        status_url = accepted.get_json()["status_url"]
        assert client.get(DIRECTORY.replace("Test", "TEST"), headers=ASYNC).get_json()["status_url"] == status_url
        assert client.get(status_url).status_code == 202
        assert legacy.app.test_client().get(status_url).status_code == 401
        assert client_for(role="partner_admin", partner_id="different-tenant").get(status_url).status_code == 404
        second = client.get(DIRECTORY.replace("0123456", "7654321"), headers=ASYNC)
        assert second.status_code == 202
        busy = client.get(DIRECTORY.replace("0123456", "7654322"), headers=ASYNC)
        assert busy.status_code == 429 and busy.headers["Retry-After"]
        assert len(requests) == 1
    finally:
        release.set()
        runner.pending.join()
    result = client.get(status_url)
    assert result.status_code == 200 and result.get_json()["checked_at"]
    assert len(requests) == len(deliveries) == 2
    assert legacy._cnaps_annuaire_snapshots(data)("test", "0123456")["result"]["check_status"] == "success"


def test_failed_async_check_preserves_last_success(monkeypatch, runner):
    saved = {"cnaps_public_annuaire_statuses": {
        "TEST|0123456": {"checked_at": "2025-12-01", "signature": "Carte pro • 2028-06-30", "known": True}
    }}
    expected = copy.deepcopy(saved)
    monkeypatch.setattr(legacy, "fetch_cnaps_public_annuaire", lambda *_: {"check_status": "error"})
    monkeypatch.setattr(legacy, "load_data", lambda **kwargs: saved)
    monkeypatch.setattr(legacy, "save_data", lambda *_a, **_k: pytest.fail("unexpected write"))
    client = client_for()
    accepted = client.get(DIRECTORY, headers=ASYNC)
    runner.pending.join()
    assert client.get(accepted.get_json()["status_url"]).status_code == 502
    snapshot = legacy._cnaps_annuaire_snapshots(saved)("test", "0123456")
    assert snapshot["checked_at"] == "2025-12-01"
    assert snapshot["result"]["active_titles"][0]["date_fin_validite"] == "2028-06-30"
    assert saved == expected


def test_name_lookup_async_matches_existing_contract_and_invalid_requests_skip_queue(monkeypatch, runner):
    monkeypatch.setattr(legacy, "fetch_cnaps_lookup_by_name", lambda *_: {"status": "accepté"})
    client = client_for()
    assert client.get("/api/cnaps_lookup?nom=TEST", headers=ASYNC).status_code == 400
    assert client.get("/api/cnaps_public_annuaire?nom=TEST", headers=ASYNC).status_code == 400
    assert not runner.jobs
    lookup = "/api/cnaps_lookup?nom=TEST&prenom=Camille"
    expected = client.get(lookup).get_json()
    accepted = client.get(lookup, headers=ASYNC)
    runner.pending.join()
    assert client.get(accepted.get_json()["status_url"]).get_json() == expected


def test_combined_refresh_requires_write_access_and_executes_only_once(monkeypatch, runner):
    calls = []
    def refresh(session_id, trainee_id):
        calls.append((session_id, trainee_id))
        return {"ok": True, "cnaps_status": "ACCEPTE", "hosting_status": "reserved"}
    monkeypatch.setattr(legacy, "_refresh_trainee_external", refresh)
    route = "/api/sessions/S/stagiaires/T/refresh-external"
    assert client_for(role="viewer").post(route, headers=ASYNC).status_code == 403
    assert not runner.jobs
    client = client_for()
    status_url = client.post(route, headers=ASYNC).get_json()["status_url"]
    runner.pending.join()
    assert client.get(status_url).get_json()["cnaps_status"] == "ACCEPTE"
    assert client.get(status_url).status_code == 200
    automatic = client.post(route + "?automatic=1", headers=ASYNC)
    assert automatic.status_code == 200
    assert automatic.get_json()["hosting_status"] == "reserved"
    assert calls == [("S", "T")]
    assert client.post(route, headers=ASYNC).status_code == 202
    runner.pending.join()
    assert calls == [("S", "T")] * 2


@pytest.mark.parametrize(("concurrent_edit", "expected_code"), [
    ({"phone": "new input"}, 200),
    ({"last_name": "OTHER"}, 409),
    ({"cnaps": "REFUSÉ"}, 409),
    ({"email": "corrected@example.test"}, 409),
])
def test_combined_refresh_updates_only_matching_current_record(tmp_path, monkeypatch, concurrent_edit, expected_code):
    import json
    path = tmp_path / "data.json"
    monkeypatch.setattr(legacy, "DATA_FILE", str(path))
    monkeypatch.setattr(legacy, "BACKUP_DIR", str(tmp_path / "backups"))
    trainee = {"id": "T", "last_name": "TEST", "first_name": "Camille", "cnaps": "INCONNU"}
    initial = {"sessions": [{"id": "S", "training_type": "APS", "trainees": [trainee]}]}
    path.write_text(json.dumps(initial))
    def remote(*_):
        current = json.loads(path.read_text())
        current["sessions"][0]["trainees"][0].update(concurrent_edit)
        current["independent_update"] = True
        path.write_text(json.dumps(current))
        return "ACCEPTÉ"

    monkeypatch.setattr(legacy, "fetch_cnaps_status_by_name", remote)
    response = client_for().post("/api/sessions/S/stagiaires/T/refresh-external")
    assert response.status_code == expected_code
    stored = json.loads(path.read_text())
    assert stored["independent_update"] is True
    final = stored["sessions"][0]["trainees"][0]
    assert all(final[key] == value for key, value in concurrent_edit.items())
    if expected_code == 200:
        assert final["cnaps"] == "ACCEPTÉ"
        assert final["cnaps_history"][0]["status"] == "ACCEPTÉ"
    else:
        assert final["cnaps"] == concurrent_edit.get("cnaps", "INCONNU")
        assert "cnaps_history" not in final


def test_failed_async_name_lookup_never_returns_a_replacement_status(monkeypatch, runner):
    monkeypatch.setattr(legacy, "fetch_cnaps_lookup_by_name", lambda *_: None)
    client = client_for()
    url = "/api/cnaps_lookup?nom=Test&prenom=Camille"
    old = client.get(url)
    assert old.status_code == 200 and old.get_json()["statut_cnaps"] == "INCONNU"
    pending = client.get(url, headers=ASYNC)
    runner.pending.join()
    result = client.get(pending.get_json()["status_url"])
    assert result.status_code == 502 and not result.get_json()["ok"]
    assert "statut_cnaps" not in result.get_json()
    assert "statut_cnaps_history" not in result.get_json()
