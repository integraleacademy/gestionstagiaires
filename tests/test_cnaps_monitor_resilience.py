import json
import os
import tempfile
import threading
import time

import app as gestion_app


def test_healthz_responds_while_monitor_is_running(monkeypatch):
    monkeypatch.setattr(gestion_app, "CNAPS_MONITOR_TOKEN", "token")
    monkeypatch.setattr(gestion_app, "run_cnaps_public_annuaire_monitor", lambda: time.sleep(35) or {"status": "done"})
    client = gestion_app.app.test_client()

    started = threading.Event()

    def run_monitor():
        started.set()
        client.post("/internal/jobs/cnaps-public-annuaire-monitor", headers={"X-CNAPS-Monitor-Token": "token"})

    thread = threading.Thread(target=run_monitor)
    thread.start()
    assert started.wait(1)
    time.sleep(0.1)

    before = time.monotonic()
    response = client.get("/healthz")
    elapsed = time.monotonic() - before

    thread.join(timeout=40)
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "service": "gestionstagiaires"}
    assert elapsed < 0.5


def test_monitor_non_blocking_lock_prevents_second_execution(monkeypatch):
    monkeypatch.setattr(gestion_app, "CNAPS_MONITOR_TOKEN", "token")
    calls = []
    release = threading.Event()

    def fake_monitor():
        calls.append(time.monotonic())
        release.wait(5)
        return {"status": "done"}

    monkeypatch.setattr(gestion_app, "run_cnaps_public_annuaire_monitor", fake_monitor)
    client = gestion_app.app.test_client()

    first = threading.Thread(target=lambda: client.post("/internal/jobs/cnaps-public-annuaire-monitor", headers={"X-CNAPS-Monitor-Token": "token"}))
    first.start()
    time.sleep(0.1)
    second = client.post("/internal/jobs/cnaps-public-annuaire-monitor", headers={"X-CNAPS-Monitor-Token": "token"})
    release.set()
    first.join(timeout=5)

    assert second.status_code == 200
    assert second.get_json() == {"ok": True, "status": "already_running"}
    assert len(calls) == 1


def test_cnaps_timeout_is_reported_without_500(monkeypatch):
    monkeypatch.setattr(gestion_app, "fetch_cnapsv3_tracking_requests", lambda: ([{"last_name": "DOE", "first_name": "Jane", "nub": "1234567"}], None))
    monkeypatch.setattr(gestion_app, "load_data", lambda run_background_tasks=False: {})
    monkeypatch.setattr(gestion_app, "save_data", lambda data: None)
    monkeypatch.setattr(gestion_app, "fetch_cnaps_public_annuaire", lambda nom, nub: {"check_status": "error", "error": "timeout lecture"})
    result = gestion_app.run_cnaps_public_annuaire_monitor()
    assert result["status"] == "done"
    assert result["errors"] == 1
    assert result["checked"] == 0


def test_data_json_remains_valid_during_concurrent_reads_and_writes(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        data_file = os.path.join(directory, "data.json")
        monkeypatch.setattr(gestion_app, "DATA_FILE", data_file)
        monkeypatch.setattr(gestion_app, "BACKUP_DIR", os.path.join(directory, "backups"))
        os.makedirs(gestion_app.BACKUP_DIR, exist_ok=True)
        gestion_app.save_data({"sessions": [], "counter": 0}, preserve_qonto_oauth=False)
        stop = threading.Event()
        errors = []

        def reader():
            while not stop.is_set():
                try:
                    with open(data_file, "r", encoding="utf-8") as handle:
                        json.load(handle)
                except Exception as exc:
                    errors.append(exc)
                    stop.set()

        thread = threading.Thread(target=reader)
        thread.start()
        for index in range(50):
            gestion_app.save_data({"sessions": [], "counter": index}, preserve_qonto_oauth=False)
        stop.set()
        thread.join(timeout=5)
        with open(data_file, "r", encoding="utf-8") as handle:
            assert isinstance(json.load(handle), dict)
        assert errors == []


def test_update_data_prevents_deterministic_lost_update(monkeypatch):
    with tempfile.TemporaryDirectory() as directory:
        data_file = os.path.join(directory, "data.json")
        monkeypatch.setattr(gestion_app, "DATA_FILE", data_file)
        monkeypatch.setattr(gestion_app, "BACKUP_DIR", os.path.join(directory, "backups"))
        os.makedirs(gestion_app.BACKUP_DIR, exist_ok=True)
        gestion_app.save_data({"sessions": [], "items": {"a": False, "b": False}}, preserve_qonto_oauth=False)

        barrier = threading.Barrier(2)

        def set_item(item_key):
            # Both threads intentionally read the same stale snapshot before the
            # transaction. update_data must still merge each change into the
            # latest on-disk version instead of saving that stale copy.
            stale_snapshot = gestion_app.load_data(run_background_tasks=False)
            assert stale_snapshot["items"] == {"a": False, "b": False}
            barrier.wait(timeout=5)

            def mutator(data):
                data["items"][item_key] = True
            gestion_app.update_data(mutator, preserve_qonto_oauth=False)

        first = threading.Thread(target=set_item, args=("a",))
        second = threading.Thread(target=set_item, args=("b",))
        first.start()
        second.start()
        first.join(timeout=5)
        second.join(timeout=5)

        final_data = gestion_app.load_data(run_background_tasks=False)
        assert final_data["items"] == {"a": True, "b": True}
