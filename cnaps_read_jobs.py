"""Bound administrator-triggered remote checks in the single application process."""
from collections import OrderedDict
import hashlib
import time

from flask import copy_current_request_context, jsonify, request, session, url_for

from maintenance_jobs import MaintenanceQueue


class CnapsQueue(MaintenanceQueue):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        self.recent = OrderedDict()

    def cached(self, key):
        with self.lock:
            entry = self.recent.get(key)
            if entry and time.monotonic() < entry[0]:
                return entry[1]
            self.recent.pop(key, None)
            return None

    def remember(self, key, payload):
        with self.lock:
            self.recent[key] = (time.monotonic() + 900, payload)
            self.recent.move_to_end(key)
            if len(self.recent) > 1024:
                self.recent.popitem(last=False)


def requested():
    return "respond-async" in {token.strip().lower() for token in request.headers.get("Prefer", "").split(",")}


def _scope(legacy):
    # The public directory result also contains tenant-specific alert counts.
    scope = (legacy._current_partner_id(), session.get("admin_role"), legacy._is_super_admin_session())
    return "cnaps-" + hashlib.sha256(repr(scope).encode()).hexdigest()


def _reply(job):
    if job["status"] == "finished":
        return jsonify(job["result"]), job["status_code"]
    response = jsonify(ok=True, job_id=job["job_id"], status=job["status"],
                       status_url=url_for("api_cnaps_verification_status", job_id=job["job_id"]))
    response.status_code = 202
    response.headers["Retry-After"] = "2"
    return response


def defer(legacy, identity, action, *, remember=False, reuse=False):
    app = legacy.app
    scope = _scope(legacy)
    runner = app.extensions["cnaps_read_jobs"]
    key = (scope, request.endpoint, identity)
    if reuse:
        cached = runner.cached(key)
        if cached is not None:
            return jsonify(cached)

    @copy_current_request_context
    def execute():
        response = app.make_response(action())
        payload = response.get_json(silent=True)
        if not isinstance(payload, dict):
            return {"ok": False, "error": "invalid_cnaps_response"}, 500
        if remember and response.status_code == 200 and payload.get("ok"):
            runner.remember(key, payload)
        return payload, response.status_code

    job = runner.submit(key, scope, execute)
    if job is None:
        response = jsonify(ok=False, error="Le CNAPS traite déjà plusieurs demandes. Réessayez dans un instant.")
        response.status_code = 429
        response.headers["Retry-After"] = "3"
        return response
    return _reply(job)


def status(legacy, job_id):
    job = legacy.app.extensions["cnaps_read_jobs"].get(job_id, _scope(legacy))
    if job is None:
        return jsonify(ok=False, error="Vérification introuvable. Vous pouvez la relancer."), 404
    return _reply(job)


def initialize(app):
    app.extensions["cnaps_read_jobs"] = CnapsQueue(app, capacity=12, history_limit=64)
