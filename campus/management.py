"""Management owns enrolments; only the learner service handles new public course visits."""
import hashlib
import os
from pathlib import Path
import threading
from urllib.parse import quote, urlencode

from psycopg.conninfo import conninfo_to_dict

from flask import abort, g, redirect, request, session

from campus import db, directory, handoff, migration
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

    def campus_link(token, target=None):
        path = handoff.destination(token, target)
        if not session.get(f"public_auth_{token}"):
            return base + path
        return base + "/espace/" + quote(token, safe="") + "?" + urlencode({"from": "gestion", "next": path})

    host.app.jinja_env.globals["campus_public_url"] = base
    host.app.jinja_env.globals["campus_link"] = campus_link
    host.app.jinja_env.globals["campus_external_vtc"] = directory.external_vtc_course
    # Render stops the old disk-backed instance before this new worker starts.
    # At this point nobody can still write its SQLite databases. Enabling this
    # mode on an already-running legacy worker is intentionally unsupported.
    if not db.enabled():
        raise RuntimeError("La gestion du Campus nécessite sa base PostgreSQL.")
    # On a later administrative restart, the existing signed-off disk must not
    # depend on a reachable Campus DB for unrelated functions such as billing.
    dsn = conninfo_to_dict(os.environ["CAMPUS_DATABASE_URL"])
    database_id = hashlib.sha256(repr(tuple(dsn.get(k) for k in ("host", "port", "dbname"))).encode()).hexdigest()
    marker = Path(host.PERSIST_DIR) / ".campus-migration-complete"
    if not marker.is_file() or marker.read_text().strip() != database_id:
        report = migration.activate(host, lambda: read_source(host))
        temporary = marker.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(database_id)
        os.replace(temporary, marker)
        host.app.logger.warning("CAMPUS_MIGRATION verified=%s", report)
    state = {"wake": threading.Event(), "stop": threading.Event()}

    def source_revision():
        stat = os.stat(host.DATA_FILE)
        tenants = host._get_partner_postgres_store().bundle_revisions() if host._partner_postgres_active() else ()
        return (stat.st_ino, stat.st_size, stat.st_mtime_ns, tenants)

    def refresh():
        previous = None
        while not state["stop"].is_set():
            state["wake"].wait(45)
            state["wake"].clear()
            if state["stop"].is_set():
                return
            try:
                revision = source_revision()
                if revision != previous:
                    directory.synchronize(lambda: read_source(host), host)
                    previous = revision
            except Exception:
                host.app.logger.exception("Campus: mise à jour de l’annuaire en attente")
            # Coalesce unrelated form autosaves and background notifications.
            state["stop"].wait(3)

    thread = threading.Thread(target=refresh, daemon=True, name="campus-enrolments")
    state["thread"] = thread
    host.app.extensions["campus_directory"] = state
    state["wake"].set()
    thread.start()

    @host.app.get("/espace/<token>/campus/autoriser")
    def campus_authorize(token):
        state = request.args.get("state", "")
        if not handoff.valid_nonce(state):
            abort(400)
        if not session.get(f"public_auth_{token}"):
            return redirect(base + "/espace/" + quote(token, safe="") + "/login")
        entry = directory.lookup(token)
        if not entry or entry[2]:
            abort(403)
        code = handoff.issue(token, state)
        response = redirect(base + "/connexion/gestion?" + urlencode({"code": code}))
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

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
            path = request.full_path.removesuffix("?")
            token = (request.view_args or {}).get("token", "")
            return redirect(campus_link(token, path) if request.path.startswith("/espace/") else base + path, code=302)
