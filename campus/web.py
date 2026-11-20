"""Learner-only WSGI application. No import of the administrative Flask app."""
import datetime as dt
import hmac
import os
from pathlib import Path
import secrets
import time
from types import SimpleNamespace
from urllib.parse import quote, urlencode

from flask import (Blueprint, Flask, abort, g, redirect, render_template,
                   request, session, url_for)
from campus import catalog, db, directory, handoff, migration
from elearning_native.paths import assigned_modules
from elearning_native.mac_aps import is_training as is_mac_aps
from elearning_native.web import create_native_elearning_blueprint
import uv_questionnaires


def create_app():
    root = Path(__file__).resolve().parent.parent
    app = Flask(__name__, template_folder=str(root / "templates"), static_folder=str(root / "static"))
    secret = os.environ.get("CAMPUS_SESSION_SECRET", "")
    if len(secret) < 32 or not db.enabled():
        raise RuntimeError("La clé de session et la base du Campus sont requises.")
    data_dir = Path(os.environ.get("CAMPUS_CACHE_DIR", "/tmp/integrale-campus"))
    data_dir.mkdir(parents=True, exist_ok=True)
    app.config.update(SECRET_KEY=secret, SESSION_COOKIE_NAME="integrale_campus",
                      SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      MAX_CONTENT_LENGTH=2 * 1024 * 1024,
                      PERMANENT_SESSION_LIFETIME=dt.timedelta(days=7),
                      UV_QUESTIONNAIRE_DB_PATH=str(data_dir / "uv-questionnaires.sqlite3"))
    directory.initialize()
    catalog.initialize()
    handoff.initialize()

    def record(token):
        cache = g.setdefault("campus_records", {})
        if token not in cache:
            cache[token] = directory.lookup(token)
        return cache[token]

    def pair(token, *, native=False):
        saved = record(token)
        if not saved:
            return None, None
        training, learner, _external = saved
        return (training.get("campus_native", training) if native else training), learner

    def authed(token):
        return bool(token and session.get("learner") == directory.digest(token) and record(token))

    def csrf():
        return session.setdefault("campus_csrf", secrets.token_urlsafe(32))

    def check_csrf():
        received = request.form.get("csrf", "")
        if not received or not hmac.compare_digest(received.encode(), csrf().encode()):
            abort(403)

    def sign_in(token):
        session.clear()
        session["learner"] = directory.digest(token)
        session.permanent = True

    def forbidden(*_args, **_kwargs):
        abort(403)

    def learning_enabled(training):
        label = str(training.get("training_type") or "").upper()
        if label.startswith("APS") or "VTC" in label:
            return bool(training.get("aps_elearning_enabled"))
        return bool(("A3P" in label or is_mac_aps(training)) and assigned_modules(training))

    def start_date(training):
        try:
            return dt.date.fromisoformat(str(training.get("date_start") or training.get("date_debut") or "")[:10])
        except ValueError:
            return None

    app.register_blueprint(create_native_elearning_blueprint(
        learner_only=True, get_persist_dir=lambda: str(data_dir), load_data=lambda: {},
        save_data=forbidden, mutate_data=forbidden, find_session=forbidden,
        find_session_and_trainee_by_token=lambda _data, token: pair(token, native=True),
        session_trainees=lambda _s: [], public_is_authed=authed,
        is_aps_elearning_session=learning_enabled, session_start_date=start_date,
    ))
    host = SimpleNamespace(app=app, DATA_FILE=str(data_dir / "unused.json"), INTEGRALE_PARTNER_ID=directory.INTERNAL,
        load_data=forbidden, _public_is_authed=authed, _trainee_registration_is_cancelled=lambda _: False,
        _now_iso=lambda: dt.datetime.now(dt.timezone.utc).isoformat())
    uv_questionnaires.register(app, host, learner_lookup=pair, public_only=True)
    admin_base = os.environ.get("CAMPUS_MANAGEMENT_URL", "").rstrip("/")

    activated = False

    @app.before_request
    def wait_for_cutover():
        nonlocal activated
        if not activated and request.endpoint not in {"health", "static"}:
            activated = migration.ready()
            if not activated:
                return "Le Campus sera ouvert après la reprise des dossiers pédagogiques.", 503, {"Retry-After": "60"}

    def return_to(token):
        return handoff.destination(token, request.args.get("next"))

    @app.before_request
    def keep_learning_destination():
        endpoint = request.endpoint or ""
        token = (request.view_args or {}).get("token") or ""
        if (request.method == "GET" and token and not token.startswith("el_") and
                (endpoint == "public_uv_questionnaire" or endpoint.startswith("native_elearning.")) and
                request.path.startswith("/espace/") and not authed(token)):
            return redirect(url_for("public_trainee_login", token=token, next=request.full_path.removesuffix("?")))

    @app.after_request
    def privacy(response):
        if request.endpoint != "static":
            response.headers.setdefault("Cache-Control", "private, no-store")
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

    @app.get("/healthz")
    def health():
        with db.pool().connection() as conn:
            conn.execute("SELECT 1 FROM campus_directory.settings LIMIT 1").fetchone()
        return {"ok": True, "service": "campus"}

    @app.route("/", methods=["GET", "POST"])
    @app.route("/espacestagiaire", methods=["GET", "POST"])
    @app.route("/espace/<token>/login", methods=["GET", "POST"], endpoint="public_trainee_login")
    def login(token=None):
        if token and authed(token):
            return redirect(return_to(token))
        error = ""
        if request.method == "POST":
            check_csrf()
            limiter = directory.failure_key(secret, request.remote_addr or "")
            if directory.too_many_failures(limiter):
                return render_template("campus/login.html", csrf=csrf(), error="Trop de tentatives. Réessayez dans quelques minutes."), 429
            found = directory.authenticate(request.form.get("last_name", ""), request.form.get("birth", ""), token)
            if found:
                sign_in(found)
                return redirect(return_to(found), code=303)
            directory.note_failure(limiter)
            error = "Accès introuvable. Vérifiez votre nom et votre date de naissance, ou utilisez votre lien personnel."
        return render_template("campus/login.html", csrf=csrf(), error=error), (401 if error else 200)

    external = Blueprint("manuals_shop", __name__)

    @external.route("/apprendre/<token>", methods=["GET", "POST"])
    def elearning_access(token):
        entry = record(token)
        if not entry or not entry[2]:
            abort(404)
        if request.method == "POST":
            check_csrf()
            sign_in(token)
            return redirect(url_for("native_elearning.learner_path", token=token), code=303)
        if authed(token):
            return redirect(url_for("native_elearning.learner_path", token=token))
        return render_template("campus/login.html", csrf=csrf(), bearer=True, error="")

    app.register_blueprint(external)

    @app.get("/espace/<token>")
    def public_trainee_space(token):
        if request.args.get("from") == "gestion" and not token.startswith("el_"):
            if authed(token):
                return redirect(return_to(token))
            if admin_base and record(token) and not record(token)[2]:
                state = secrets.token_urlsafe(32)
                session["campus_handoff"] = dict(token=token, state=state, target=return_to(token), issued=time.time())
                return redirect(admin_base + "/espace/" + quote(token, safe="") + "/campus/autoriser?" + urlencode({"state": state}))
        if not authed(token):
            return redirect(url_for("manuals_shop.elearning_access" if token.startswith("el_") else "public_trainee_login", token=token))
        training, learner = pair(token)
        native, _ = pair(token, native=True)
        when = start_date(native)
        external_vtc = learner.get("campus_external_vtc") or ""
        accessible = (external_vtc or native.get("individual_aps_access") or native.get("vtc_auto_access_available")
                      or (when and when <= dt.date.today()))
        legacy_url = str(learner.get("aps_elearning_login") or "").strip()
        external_aps = legacy_url if native.get("aps_elearning_enabled") and legacy_url.startswith("https://") else ""
        return render_template("campus/home.html", token=token, learner=learner, training=training,
                    uv=uv_questionnaires.view(host, training, learner), native=not external_vtc and bool(assigned_modules(native)),
                    accessible=accessible, legacy_url=external_vtc or external_aps,
                    dossier_url=(admin_base + "/espace/" + token) if admin_base and not record(token)[2] else "",
                    csrf=csrf())

    @app.get("/connexion/gestion")
    def management_login():
        pending = session.pop("campus_handoff", None)
        if not pending or not 0 <= time.time() - pending.get("issued", 0) <= 120:
            abort(400)
        token = pending["token"]
        if not handoff.consume(token, pending["state"], request.args.get("code", "")):
            abort(400)
        entry = record(token)
        if not entry or entry[2]:
            abort(403)
        sign_in(token)
        return redirect(handoff.destination(token, pending["target"]), code=303)

    @app.post("/deconnexion")
    def logout():
        check_csrf()
        session.clear()
        return redirect(url_for("login"), code=303)

    return app
