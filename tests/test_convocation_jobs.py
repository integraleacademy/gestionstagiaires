import sqlite3
import threading
import time
import uuid
from types import SimpleNamespace

import pytest
from flask import Flask, jsonify, request, session

import convocation_jobs


SEND_URL = "/admin/sessions/S1/stagiaires/T1/convocation-aps/send"


@pytest.fixture
def service(tmp_path):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="fixture-only")
    started = threading.Event()
    release = threading.Event()
    calls = []
    deliveries = []
    host = SimpleNamespace(app=app, PERSIST_DIR=str(tmp_path),
                           _current_partner_id=lambda: session.get("partner_id", ""))

    @app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/convocation-aps/send")
    def admin_send_aps_convocation(session_id, trainee_id):
        if not session.get("admin_logged_in"):
            return jsonify(ok=False), 403
        if request.headers.get("Prefer") == "respond-async":
            return convocation_jobs.defer(host, "send", session_id, trainee_id)
        calls.append((session["partner_id"], trainee_id))
        started.set()
        assert release.wait(5)
        if trainee_id == "cancelled":
            return jsonify(ok=False, error="Inscription annulée"), 409
        deliveries.append((trainee_id, convocation_jobs.begin_delivery()))
        return jsonify(ok=True, status="sent")

    @app.get("/admin/convocations/jobs/<job_id>")
    def admin_convocation_job_status(job_id):
        return convocation_jobs.status(host, job_id)

    def client(tenant):
        client = app.test_client()
        with client.session_transaction() as state:
            state.update(admin_logged_in=True, admin_username=tenant + "-manager",
                         partner_id=tenant, admin_role="admin")
        return client

    yield SimpleNamespace(alice=client("A"), bob=client("B"), started=started,
                          release=release, calls=calls, deliveries=deliveries, app=app, host=host)
    release.set()
    worker = app.extensions.get("convocation_jobs")
    if worker:
        worker["stop"].set()
        worker["wake"].set()
        worker["thread"].join(timeout=5)


def post(client, key, url=SEND_URL, *, skip_sent=False):
    return client.post(url, json={"skip_if_already_sent": skip_sent}, headers={
        "Prefer": "respond-async", "Idempotency-Key": key,
    })


def finish(client, response):
    deadline = time.monotonic() + 5
    status_url = response.json.get("status_url")
    while response.status_code == 202:
        assert time.monotonic() < deadline, "job did not reach a terminal response"
        response = client.get(status_url)
        if response.status_code == 202:
            time.sleep(0.01)
    return response


def test_duplicate_clicks_share_work_and_retries_replay_original_result(service):
    first_key, second_key = str(uuid.uuid4()), str(uuid.uuid4())
    first = post(service.alice, first_key)
    assert first.status_code == 202
    assert service.started.wait(2)
    assert service.alice.get(first.json["status_url"]).status_code == 202
    for key in (first_key, second_key):
        duplicate = post(service.alice, key)
        assert duplicate.status_code == 202
        assert duplicate.json["job_id"] == first.json["job_id"]

    service.release.set()
    assert finish(service.alice, first).json == {"ok": True, "status": "sent"}
    for key in (first_key, second_key):
        replay = finish(service.alice, post(service.alice, key))
        assert replay.status_code == 200
        assert replay.json == {"ok": True, "status": "sent"}
    assert service.calls == [("A", "T1")]

    # A later, explicitly requested resend uses its own operation key.
    result = finish(service.alice, post(service.alice, str(uuid.uuid4())))
    assert result.status_code == 200
    assert service.calls == [("A", "T1"), ("A", "T1")]


def test_ticket_and_idempotency_are_scoped_to_tenant(service):
    key = str(uuid.uuid4())
    first = post(service.alice, key)
    assert first.status_code == 202
    assert service.started.wait(2)
    assert service.bob.get(first.json["status_url"]).status_code == 404
    other = post(service.bob, key)
    assert other.status_code == 202
    assert other.json["job_id"] != first.json["job_id"]
    # The second conversion waits off the HTTP threads.
    assert service.calls == [("A", "T1")]
    service.release.set()
    assert finish(service.alice, first).status_code == 200
    assert finish(service.bob, other).status_code == 200
    assert service.calls == [("A", "T1"), ("B", "T1")]


def test_job_preserves_business_error(service):
    service.release.set()
    key = str(uuid.uuid4())
    url = SEND_URL.replace("/T1/", "/cancelled/")
    result = finish(service.alice, post(service.alice, key, url))
    assert result.status_code == 409
    assert result.json == {"ok": False, "error": "Inscription annulée"}
    assert finish(service.alice, post(service.alice, key, url)).status_code == 409
    assert service.calls == [("A", "cancelled")]


def test_restart_resumes_before_email_and_does_not_repeat_a_started_delivery(service, monkeypatch):
    service.release.set()
    first_key, second_key = str(uuid.uuid4()), str(uuid.uuid4())
    # Capture two real tickets and stop the dispatcher before it claims either.
    with monkeypatch.context() as patch:
        patch.setattr(convocation_jobs, "_run", lambda host, state: state["stop"].wait(5))
        first = post(service.alice, first_key)
        second_url = SEND_URL.replace("/T1/", "/T2/")
        second = post(service.alice, second_key, second_url)
        worker = service.app.extensions["convocation_jobs"]
        worker["stop"].set()
        worker["thread"].join(2)

    # Simulate a process death after the first transport handoff and before
    # transport for the second. Only the latter may safely be executed again.
    with sqlite3.connect(worker["path"]) as db:
        db.execute("UPDATE jobs SET state='sending' WHERE id=?", (first.json["job_id"],))
        db.execute("UPDATE jobs SET state='running' WHERE id=?", (second.json["job_id"],))
    convocation_jobs.start_worker(service.host)
    uncertain = finish(service.alice, first)
    assert uncertain.status_code == 409
    assert uncertain.json["uncertain"] is True
    assert finish(service.alice, post(service.alice, first_key)).json == uncertain.json
    assert finish(service.alice, second).status_code == 200
    assert service.calls == [("A", "T2")]
    assert service.deliveries == [
        ("T2", {"metadata": {"idempotency_key": second.json["job_id"]}})
    ]


def test_bulk_and_manual_click_on_same_pending_send_do_not_deliver_twice(service):
    bulk_key, manual_key = str(uuid.uuid4()), str(uuid.uuid4())
    bulk = post(service.alice, bulk_key, skip_sent=True)
    assert bulk.status_code == 202
    assert service.started.wait(2)
    manual = post(service.alice, manual_key)
    assert manual.json["job_id"] == bulk.json["job_id"]
    service.release.set()
    assert finish(service.alice, bulk).status_code == 200
    assert finish(service.alice, post(service.alice, bulk_key)).status_code == 200
    assert finish(service.alice, post(service.alice, manual_key, skip_sent=True)).status_code == 200
    assert len(service.deliveries) == 1


def test_queue_rejects_overflow_and_keeps_existing_requests_pollable(service):
    first = post(service.alice, str(uuid.uuid4()))
    assert service.started.wait(2)
    for i in range(1, 64):
        url = SEND_URL.replace("/T1/", f"/pending-{i}/")
        assert post(service.alice, str(uuid.uuid4()), url).status_code == 202
    extra = post(service.alice, str(uuid.uuid4()), SEND_URL.replace("/T1/", "/overflow/"))
    assert extra.status_code == 429
    assert service.alice.get(first.json["status_url"]).status_code == 202
    assert len(service.calls) == 1
