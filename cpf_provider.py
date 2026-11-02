"""Exclusive and durable CPF provider selection on the establishment’s persistent disks."""
from contextlib import closing, contextmanager
import fcntl
from functools import wraps
import os
from pathlib import Path
import sqlite3
import time

TEST_SERVICE_ID = "srv-d928tc19rddc7388qie0"
PROD_SERVICE_ID = "srv-d5oss66id0rc73avvne0"
PROVIDERS = {"wedof": "WeDoF", "integrale": "Intégrale EDOF"}


class ProviderUnavailable(ValueError):
    pass


class ProviderStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def connect(self):
        path = self.directory / "cpf-providers.sqlite3"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        db = sqlite3.connect(path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS selections (
            revision INTEGER PRIMARY KEY, provider TEXT NOT NULL CHECK(provider IN ('wedof','integrale')),
            changed REAL NOT NULL, actor TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS pending_provider_switch (
            id INTEGER PRIMARY KEY CHECK(id=1), target TEXT NOT NULL, remote_revision INTEGER NOT NULL,
            operation TEXT NOT NULL, actor TEXT NOT NULL)""")
        return db

    def state(self, db=None):
        if db is None:
            with closing(self.connect()) as conn:
                return self.state(conn)
        row = db.execute("SELECT * FROM selections ORDER BY revision DESC LIMIT 1").fetchone()
        state = dict(row) if row else {"provider": "wedof", "revision": 0, "changed": None, "actor": ""}
        pending = db.execute("SELECT * FROM pending_provider_switch WHERE id=1").fetchone()
        state["pending"] = dict(pending) if pending else None
        return state

    def lock(self, exclusive=False):
        self.directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.directory / "cpf-providers.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise ProviderUnavailable("Un traitement ou une bascule est en cours. Réessayez après sa fin.") from None
        except BaseException:
            os.close(fd)
            raise
        return fd

    def acquire(self, provider):
        fd = self.lock()
        try:
            state = self.state()
            if state["pending"]:
                raise ProviderUnavailable("Bascule en attente de confirmation. Les traitements sont suspendus.")
            if state["provider"] != provider:
                raise ProviderUnavailable(f"{PROVIDERS[provider]} est désactivé pour cet établissement.")
            return fd
        except BaseException:
            os.close(fd)
            raise

    def switch(self, target, revision, actor):
        if target not in PROVIDERS:
            raise ValueError("Système CPF inconnu.")
        fd = self.lock(exclusive=True)
        try:
            with closing(self.connect()) as db, db:
                return self.set_locked(db, target, revision, actor)
        finally:
            os.close(fd)

    def set_locked(self, db, target, revision, actor, *, record=False):
        state = self.state(db)
        if revision != state["revision"]:
            raise ProviderUnavailable("Le choix a changé depuis l’affichage de cette page. Actualisez-la.")
        if record or state["provider"] != target:
            db.execute("INSERT INTO selections VALUES (?, ?, ?, ?)", (revision + 1, target, time.time(), actor))
        return self.state(db)


def on_test_service():
    return os.environ.get("RENDER_SERVICE_ID") == TEST_SERVICE_ID


def current_store():
    if on_test_service():
        return ProviderStore("/var/data")
    if os.environ.get("RENDER_SERVICE_ID") == PROD_SERVICE_ID:
        return ProviderStore("/data")
    return None


def acquire_provider(provider):
    store = current_store()
    try:
        if store is None:
            return None
        fd = store.acquire(provider)
        if on_test_service():
            from cpf_provider_bridge import production_request
            try:
                if production_request()["provider"] != provider:
                    raise ProviderUnavailable("La production ne confirme pas le même système CPF.")
            except BaseException:
                os.close(fd)
                raise
        return fd
    except (OSError, sqlite3.Error) as exc:
        raise ProviderUnavailable("Impossible de vérifier le système CPF actif. Traitement suspendu.") from exc


@contextmanager
def provider_operation(provider):
    fd = acquire_provider(provider)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)


def wedof_transport(function):
    @wraps(function)
    def controlled(*args, **kwargs):
        from wedof_service import WedofApiError
        try:
            with provider_operation("wedof"):
                return function(*args, **kwargs)
        except ProviderUnavailable as exc:
            raise WedofApiError(str(exc), "wedof_provider_disabled", False, 409) from exc
    return controlled


def register_wedof_guards(app):
    # Apply before the maintenance queue wrapper so the worker rechecks the
    # selection on execution, including the hourly invoice pass and CRM relays.
    if current_store() is None:
        return
    from flask import jsonify, redirect, request, session, url_for
    def wrap(view, endpoint):
        @wraps(view)
        def guarded(*args, **kwargs):
            try:
                with provider_operation("wedof"):
                    return view(*args, **kwargs)
            except ProviderUnavailable as exc:
                if endpoint == "admin_wedof_requests":
                    if not session.get("admin_logged_in"):
                        return redirect(url_for("admin_login", next=request.path))
                    dashboard = (url_for("integrale_edof.index") if "integrale_edof.index" in app.view_functions
                                 else "https://gestionstagiaires-test-v2.onrender.com/admin/edof-test")
                    return redirect(dashboard, code=303)
                if endpoint == "wedof_webhook" or endpoint.startswith("internal_cron"):
                    return jsonify(ok=True, status="suspended", mode="disabled", reason=str(exc)), 200
                return jsonify(ok=False, error=str(exc)), 409
        return guarded
    for endpoint, view in list(app.view_functions.items()):
        if (endpoint in {"wedof_webhook", "send_wedof_to_salesforce", "send_wedof_to_crm",
                         "internal_wedof_governor_reserve", "internal_wedof_governor_lock_acquire"}
                or endpoint.startswith("internal_cron_wedof")
                or endpoint.startswith(("admin_wedof_", "admin_mark_wedof_", "admin_delete_wedof_", "admin_test_wedof_"))
):
            app.view_functions[endpoint] = wrap(view, endpoint)
