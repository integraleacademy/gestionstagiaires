"""Prepare browser-requested documents outside the web threads on a cache miss."""
import hashlib
import json
from functools import wraps

from flask import copy_current_request_context, current_app, g, jsonify, render_template, request, session

from maintenance_jobs import MaintenanceQueue


def browser_request():
    return (not g.get("preparing_convocation")
            and request.accept_mimetypes.best_match(("application/pdf", "text/html")) == "text/html")


def _scope():
    # Jobs store no URL or trainee access token, and can only be polled from the
    # same authorized document route and partner context.
    values = [request.path, session.get("partner_id"), session.get("assist_partner_id")]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def pollable(view):
    @wraps(view)
    def handle(*args, **kwargs):
        job_id = request.args.get("preparation")
        if not job_id:
            return view(*args, **kwargs)
        token = kwargs.get("token")
        if token and not (session.get("admin_logged_in") or session.get(f"public_auth_{token}")):
            return jsonify(ok=False, error="Connectez-vous pour consulter la convocation."), 403
        runner = current_app.extensions.get("convocation_previews")
        job = runner.get(job_id, _scope()) if runner else None
        headers = {"Cache-Control": "private, no-store"}
        if not job:
            return jsonify(ok=False, error="Veuillez rouvrir la convocation pour relancer la préparation."), 404, headers
        if job["status"] == "finished":
            return jsonify(job["result"]), job["status_code"], headers
        return jsonify(ok=True, status=job["status"]), 202, headers
    return handle


def wait_page():
    app = current_app._get_current_object()
    runner = app.extensions.get("convocation_previews")
    if runner is None:
        runner = app.extensions.setdefault("convocation_previews", MaintenanceQueue(app))
    scope = _scope()

    @copy_current_request_context
    def prepare():
        g.preparing_convocation = True
        # Repeat the original view's permission, cancellation and version checks
        # against fresh data. Do not retain a snapshot of the whole training file.
        response = app.full_dispatch_request()
        try:
            if response.status_code == 200 and response.mimetype == "application/pdf":
                return {"ok": True}, 200
            return {"ok": False, "error": "Impossible de préparer cette convocation. Rouvrez le document."}, 400
        finally:
            response.close()

    job = runner.submit(scope, scope, prepare)
    if job is None:
        return "Les convocations sont en cours de préparation. Réessayez dans un instant.", 429, {"Retry-After": "3"}
    return render_template("convocation_preparation.html", job=job), 202, {"Cache-Control": "private, no-store"}
