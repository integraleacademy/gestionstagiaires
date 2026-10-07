import threading
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask, jsonify, request
import pytest

from maintenance_jobs import MaintenanceQueue, register_maintenance_jobs
from scripts.scheduled_job_client import wait_for_job


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "test-cron")
    monkeypatch.delenv("QONTO_SYNC_CRON_SECRET", raising=False)
    app = Flask(__name__)
    started, release = threading.Event(), threading.Event()
    calls = []

    @app.post("/internal/cron/document-reminders")
    def internal_cron_document_reminders():
        calls.append(request.get_json(silent=True) or {})
        started.set()
        assert release.wait(3)
        return jsonify(ok=True, processed=1)

    @app.get("/healthz")
    def health():
        return jsonify(ok=True)

    register_maintenance_jobs(SimpleNamespace(app=app))
    yield app, started, release, calls
    release.set()
    app.extensions["maintenance_jobs"].pending.join()


def test_queued_job_frees_http_and_duplicate_does_not_run_twice(service):
    app, started, release, calls = service
    client = app.test_client()
    url = "/internal/cron/document-reminders"
    headers = {"X-Cron-Secret": "test-cron"}
    first = client.post(url, headers=headers, json={"dry_run": True})
    assert first.status_code == 202
    assert started.wait(1)
    assert client.get("/healthz").json == {"ok": True}
    duplicate = client.post(url, headers=headers, json={"dry_run": True})
    assert duplicate.json["job_id"] == first.json["job_id"]
    status_url = url + "?job_id=" + first.json["job_id"]
    assert client.get(status_url, headers=headers).status_code == 202
    release.set()
    app.extensions["maintenance_jobs"].pending.join()
    result = client.get(status_url, headers=headers)
    assert result.status_code == 200
    assert result.json == {"ok": True, "processed": 1}
    assert calls == [{"dry_run": True}]


def test_authorization_is_checked_before_enqueue_and_for_polling(service):
    app, started, _, calls = service
    client = app.test_client()
    url = "/internal/cron/document-reminders"
    assert client.post(url).status_code == 403
    assert client.post(url + "?token=test-cron").status_code == 403
    assert client.get(url + "?job_id=anything").status_code == 403
    assert not started.is_set()
    assert calls == []


def test_queue_is_bounded_serial_and_preserves_failed_results():
    app = Flask(__name__)
    runner = MaintenanceQueue(app, capacity=2)
    started, release = threading.Event(), threading.Event()
    second = threading.Event()

    def first_job():
        started.set()
        assert release.wait(3)
        return {"ok": True}, 200

    try:
        one = runner.submit("one", "first", first_job)
        assert started.wait(1)
        two = runner.submit("two", "second", lambda: (second.set() or {"ok": False}, 503))
        assert two["status"] == "queued"
        assert not second.is_set()
        assert runner.submit("three", "third", lambda: ({"ok": True}, 200)) is None
        assert runner.get(one["job_id"], "second") is None
    finally:
        release.set()
        runner.pending.join()
    assert second.is_set()
    assert runner.get(two["job_id"], "second")["status_code"] == 503


def test_job_exception_is_reported_and_next_job_runs():
    runner = MaintenanceQueue(Flask(__name__))

    def fail():
        raise RuntimeError("test failure")

    bad = runner.submit("bad", "bad", fail)
    good = runner.submit("good", "good", lambda: ({"ok": True}, 200))
    runner.pending.join()
    assert runner.get(bad["job_id"], "bad")["status_code"] == 500
    assert runner.get(good["job_id"], "good")["status_code"] == 200


def test_poll_client_handles_old_server_and_only_gets_original_endpoint(monkeypatch):
    from scripts import scheduled_job_client as client
    response = Mock(status_code=200)
    get = Mock()
    monkeypatch.setattr(client.requests, "get", get)
    assert wait_for_job(response, url="https://example.test/job", headers={}) is response
    get.assert_not_called()
    queued = Mock(status_code=202)
    queued.json.return_value = {"status": "queued", "job_id": "opaque", "status_url": "https://untrusted.test/"}
    get.return_value = response
    monkeypatch.setattr(client.time, "sleep", lambda _: None)
    assert wait_for_job(queued, url="https://example.test/job", headers={"X-Cron-Secret": "test"}) is response
    get.assert_called_once_with("https://example.test/job", params={"job_id": "opaque"},
                               headers={"X-Cron-Secret": "test"}, timeout=30, allow_redirects=False)


def test_missing_job_is_returned_without_repeating_submission(monkeypatch):
    from scripts import scheduled_job_client as client
    queued = Mock(status_code=202)
    queued.json.return_value = {"status": "running", "job_id": "before-restart"}
    missing = Mock(status_code=404)
    monkeypatch.setattr(client.requests, "get", Mock(return_value=missing))
    monkeypatch.setattr(client.requests, "post", Mock(side_effect=AssertionError("Do not replay a POST")))
    monkeypatch.setattr(client.time, "sleep", lambda _: None)
    assert wait_for_job(queued, url="https://example.test/job", headers={}) is missing
