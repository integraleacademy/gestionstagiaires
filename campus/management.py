"""Management owns enrolments; only the learner service handles new public course visits."""
import threading

from flask import g, redirect, request, session

from campus import directory, migration
from campus.links import origin


def read_source(host):
    # Privileged projection has no admin/tenant cookie. A partial partner overlay
    # is never authoritative for revoking or restoring external access.
    with host.app.test_request_context("/"):
        data = host.load_data(run_background_tasks=False, persist_normalization=False)
        if host._partner_postgres_active() and getattr(g, "partner_postgres_platform_baselines", None) is None:
            raise RuntimeError("Annuaire des partenaires indisponible.")
        return data


def install(host):
    base = origin()
    host.app.jinja_env.globals["campus_public_url"] = base
    # Render stops the old disk-backed instance before this new worker starts.
    # At this point nobody can still write its SQLite databases. Enabling this
    # mode on an already-running legacy worker is intentionally unsupported.
    report = migration.activate(host, lambda: read_source(host))
    host.app.logger.warning("CAMPUS_MIGRATION verified=%s", report)
    state = {"wake": threading.Event(), "stop": threading.Event()}

    def refresh():
        while not state["stop"].is_set():
            state["wake"].wait(45)
            state["wake"].clear()
            if state["stop"].is_set():
                return
            try:
                directory.synchronize(lambda: read_source(host), host)
            except Exception:
                host.app.logger.exception("Campus: mise à jour de l’annuaire en attente")
            # Coalesce unrelated form autosaves and background notifications.
            state["stop"].wait(3)

    thread = threading.Thread(target=refresh, daemon=True, name="campus-enrolments")
    state["thread"] = thread
    host.app.extensions["campus_directory"] = state
    thread.start()

    @host.app.after_request
    def update_enrolments(response):
        if (request.method in {"POST", "PATCH", "PUT", "DELETE"} and response.status_code < 400
                and (session.get("admin_logged_in") or request.path.startswith("/webhooks/"))):
            state["wake"].set()
        return response

    @host.app.before_request
    def learning_entry():
        if request.method not in ("GET", "HEAD") or session.get("admin_logged_in"):
            return
        endpoint = request.endpoint or ""
        if ((endpoint.startswith("native_elearning.") and request.path.startswith("/espace/"))
                or endpoint in {"public_uv_questionnaire", "manuals_shop.elearning_access"}):
            return redirect(base + request.path, code=302)
