"""Run scheduled jobs outside Gunicorn's four HTTP request threads.

The JSON store requires one application process. A single bounded maintenance
queue also avoids several cron jobs loading/writing that store simultaneously.
Jobs retain their existing business logic, locks and durable delivery state.
After a process restart, callers see a missing job and the scheduler retries on
its next normal run; a POST is never automatically replayed by the polling client.
"""
from collections import OrderedDict
from functools import wraps
import hashlib
import hmac
import logging
import os
import queue
import threading
import time
import uuid

from flask import copy_current_request_context, jsonify, request


class MaintenanceQueue:
    def __init__(self, app, capacity=12, history_limit=128):
        self.app = app
        gunicorn_logger = logging.getLogger("gunicorn.error")
        self.logger = gunicorn_logger if gunicorn_logger.handlers else app.logger
        self.capacity = capacity
        self.history_limit = history_limit
        self.lock = threading.Lock()
        self.jobs = OrderedDict()
        self.active = {}
        self.pending = queue.Queue(maxsize=capacity)
        self.thread = None

    def submit(self, key, endpoint, callback):
        with self.lock:
            if key in self.active:
                return dict(self.jobs[self.active[key]])
            if len(self.active) >= self.capacity:
                return None
            job_id = uuid.uuid4().hex
            job = {"job_id": job_id, "endpoint": endpoint, "status": "queued"}
            self.jobs[job_id] = job
            self.active[key] = job_id
            self.pending.put_nowait((job_id, key, callback))
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, name="maintenance-jobs", daemon=True)
                self.thread.start()
            return dict(job)

    def get(self, job_id, endpoint):
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job and job["endpoint"] == endpoint else None

    def _run(self):
        while True:
            job_id, key, callback = self.pending.get()
            started = time.monotonic()
            with self.lock:
                job = self.jobs[job_id]
                job["status"] = "running"
            self.logger.info("MAINTENANCE_JOB_START endpoint=%s job=%s", job["endpoint"], job_id)
            try:
                payload, status_code = callback()
            except Exception:
                self.logger.exception("MAINTENANCE_JOB_FAILED endpoint=%s job=%s", job["endpoint"], job_id)
                payload, status_code = {"ok": False, "error": "maintenance_job_failed"}, 500
            with self.lock:
                job.update(status="finished", result=payload, status_code=status_code)
                self.active.pop(key, None)
                for old_id in list(self.jobs):
                    if len(self.jobs) <= self.history_limit:
                        break
                    if self.jobs[old_id]["status"] == "finished":
                        del self.jobs[old_id]
            self.logger.info(
                "MAINTENANCE_JOB_END endpoint=%s job=%s status=%s duration_ms=%d",
                job["endpoint"], job_id, status_code, (time.monotonic() - started) * 1000,
            )
            self.pending.task_done()
            # Do not retain the last copied Flask context (and its full data
            # payload) while the worker is idle between scheduled runs.
            del callback, payload, job


def register_maintenance_jobs(legacy):
    app = legacy.app
    if "maintenance_jobs" in app.extensions:
        return
    runner = MaintenanceQueue(app)
    app.extensions["maintenance_jobs"] = runner
    endpoints = {
        "internal_cnaps_public_annuaire_monitor": "cnaps",
        "internal_cron_qonto_sync": "qonto",
        "internal_cron_wedof_automation": "cron",
        "internal_cron_wedof_reconciliation": "cron",
        "internal_cron_document_reminders": "cron",
        "internal_cron_afc_documents_reminders": "cron",
        "internal_cron_convocation_signature_reminders": "cron",
        "internal_cron_cash_payment_reminders": "cron",
        "internal_cron_a3p_hosting_reminders": "cron",
        "internal_cron_daily_recap": "cron",
    }

    def register(endpoint, secret_kind):
        original = app.view_functions[endpoint]

        def authorized():
            if secret_kind == "cnaps":
                expected = legacy.CNAPS_MONITOR_TOKEN
                provided = request.headers.get("X-CNAPS-Monitor-Token", "")
            else:
                expected = ((os.environ.get("QONTO_SYNC_CRON_SECRET") if secret_kind == "qonto" else "")
                            or os.environ.get("CRON_SECRET") or "").strip()
                provided = (request.headers.get("X-Cron-Secret") or "").strip()
                if endpoint not in {"internal_cron_qonto_sync", "internal_cron_document_reminders"}:
                    provided = provided or (request.args.get("token") or "").strip()
            return bool(expected and provided and hmac.compare_digest(expected, provided))

        def job_response(job):
            if job["status"] == "finished":
                return jsonify(job["result"]), job["status_code"]
            response = jsonify(ok=True, status=job["status"], job_id=job["job_id"])
            response.status_code = 202
            response.headers["Retry-After"] = "3"
            return response

        @wraps(original)
        def submit(*args, **kwargs):
            if not authorized():
                return jsonify(ok=False, error="forbidden"), 403
            # Cache the body before the HTTP request ends. The copied request
            # receives its own Flask g/cache; no request data is shared by threads.
            body = request.get_data()
            query = tuple(sorted((k, v) for k, v in request.args.items(multi=True) if k != "token"))
            key = (endpoint, hashlib.sha256(body + repr(query).encode()).hexdigest())

            @copy_current_request_context
            def execute():
                response = app.make_response(original(*args, **kwargs))
                payload = response.get_json(silent=True)
                if not isinstance(payload, dict):
                    return {"ok": False, "error": "invalid_job_response"}, 500
                return payload, response.status_code

            job = runner.submit(key, endpoint, execute)
            if job is None:
                return jsonify(ok=False, error="maintenance_queue_full"), 503
            return job_response(job)

        def status():
            if not authorized():
                return jsonify(ok=False, error="forbidden"), 403
            job = runner.get(request.args.get("job_id", ""), endpoint)
            if job is None:
                return jsonify(ok=False, error="maintenance_job_not_found"), 404
            return job_response(job)

        app.view_functions[endpoint] = submit
        rules = [rule.rule for rule in app.url_map.iter_rules(endpoint) if "POST" in rule.methods]
        for index, rule in enumerate(rules):
            app.add_url_rule(rule, endpoint=f"{endpoint}_job_status_{index}", view_func=status, methods=["GET"])

    for endpoint, secret_kind in endpoints.items():
        if endpoint in app.view_functions:
            register(endpoint, secret_kind)
