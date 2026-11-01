from functools import wraps
import json
import os
from pathlib import Path
import subprocess

from flask import Flask, jsonify, session
import pytest

import edof_server_browser as browser
import edof_server_test as server


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_all_edof_business_writes_blocked(method):
    assert not browser.permitted_request(f"https://{browser.EDOF_HOST}{browser.API_PREFIX}123456789012/inTraining", method)
    assert not browser.permitted_request(f"https://{browser.EDOF_HOST}/unknown-mutation", method)


def test_only_official_efp_login_can_post():
    path = "/auth/realms/efp/login-actions/authenticate?session_code=synthetic"
    assert browser.permitted_request(f"https://{browser.EFP_HOST}" + path, "POST")
    assert not browser.permitted_request(f"http://{browser.EFP_HOST}" + path, "POST")
    assert not browser.permitted_request("https://example.invalid" + path, "POST")
    assert not browser.permitted_request(f"https://{browser.EFP_HOST}/account/password", "POST")
    assert browser.permitted_request(f"https://{browser.EDOF_HOST}{browser.API_PREFIX}123456789012", "GET")


def test_projection_removes_pii_and_preserves_unknowns():
    raw = {"id": "123456789012", "title": "0", "attendee": {"firstName": "Camille", "lastName": "EXEMPLE", "phoneNumber": "synthetic-private", "birthDate": "synthetic-private"},
        "trainingActionInfo": {"title": "Formation exemple", "totalIncl": 1600},
        "authorization": "synthetic-private", "history": ["synthetic-private"]}
    result = browser.project_folder(raw)
    assert "synthetic-private" not in json.dumps(result)
    assert result["title"] == "Formation exemple"
    assert result["billing_state"] is None and result["payment_state"] is None


@pytest.mark.parametrize("text,code", [("Je ne suis pas un robot", "human_verification"), ("Saisissez le code de vérification", "verification_code"), ("Identifiant ou mot de passe incorrect", "credentials_rejected"), ("Connexion à EDOF", None), ("403 Forbidden", None)])
def test_classification_does_not_infer_bot_block_from_http(text, code):
    assert browser.classify_text(text) == code


@pytest.mark.parametrize("payload", [{"mode": "read"}, {"mode": "read", "folder_id": "../../other"}, {"mode": "read", "first_name": "Camille"}, {"mode": "read", "folder_id": "123456789012", "password": "synthetic"}, {"mode": "write", "folder_id": "123456789012"}])
def test_search_input_rejects_injection_and_credential_submission(payload):
    with pytest.raises(ValueError):
        server.validate_spec(payload)


def test_search_spec_and_identity():
    assert server.validate_spec({"mode": "read", "first_name": " Camille ", "last_name": "EXEMPLE"})["first_name"] == "Camille"
    assert browser.identity(" Jean-François ") == browser.identity("JEAN FRANCOIS")


def test_diagnostics_only_expose_categories_not_auth_parameters():
    url = f"https://{browser.EFP_HOST}/auth/realms/efp/login-actions/authenticate?session_code=synthetic-secret&username=synthetic@example.invalid"
    signals = {"login_post_status": 200, "callback_status": None, "blocked_efp_posts": 0, "raw_error": "synthetic-secret", "cookie": "synthetic-secret"}
    result = browser.diagnostic_summary(url, True, False, signals)
    assert result["location"] == "efp_login"
    assert result["login_post_status"] == 200
    assert "synthetic" not in json.dumps(result)
    assert "cookie" not in result and "raw_error" not in result
    assert browser.location_category(f"https://{browser.EDOF_HOST}/idp/edof/api/v2/callback?code=synthetic-secret") == "edof_callback"
    assert browser.location_category(f"https://{browser.EFP_HOST}/auth/realms/efp/login-actions/required-action?execution=synthetic-secret") == "efp_required_action"


@pytest.mark.parametrize("text,code", [("Nom d’utilisateur ou mot de passe invalide.", "credentials_rejected"), ("Votre compte est désactivé.", "account_unavailable"), ("Saisissez votre code d’authentification.", "verification_code")])
def test_additional_authentication_outcomes(text, code):
    assert browser.classify_text(text) == code


def test_store_owner_isolation_expiry_cooldown_and_interruption(tmp_path, monkeypatch):
    now = 1000000.0
    monkeypatch.setattr(server.time, "time", lambda: now)
    store = server.ServerTestStore(tmp_path)
    job = store.reserve("owner-a", "read")
    assert store.latest("owner-b") == []
    with pytest.raises(ValueError):
        store.reserve("owner-b", "access")
    now += 181
    assert store.latest("owner-a")[0]["code"] == "interrupted"
    with pytest.raises(ValueError):
        store.reserve("owner-a", "read")
    now += 121
    job2 = store.reserve("owner-a", "read")
    store.finish(job2, {"code": "read_success", "fresh_session": True})
    assert store.latest("owner-a")[0]["finished"]
    assert (store.path.stat().st_mode & 0o777) == 0o600
    now += 86401
    assert store.latest("owner-a") == []


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.delenv("EDOF_EFP_USERNAME", raising=False)
    monkeypatch.delenv("EDOF_EFP_PASSWORD", raising=False)
    root = Path(server.__file__).parent
    app = Flask(__name__, template_folder=str(root / "templates"))
    app.config.update(TESTING=True, SECRET_KEY="synthetic-test-only")
    store = server.ServerTestStore(tmp_path)
    def required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not session.get("admin"):
                return jsonify(ok=False), 401
            return view(*args, **kwargs)
        return wrapper
    server.register_routes(app, store, admin_required=required, can_access=lambda: not session.get("partner"))
    @app.context_processor
    def forbidden_context():
        raise AssertionError("Legacy business context must not run")
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin"] = True
    assert client.get("/admin/edof-test/server").status_code == 200
    with client.session_transaction() as sess:
        csrf = sess["edof_server_csrf"]
    return app, client, store, csrf


def test_route_auth_csrf_secrets_missing_and_no_start(web, monkeypatch):
    app, client, store, csrf = web
    monkeypatch.setattr(server, "start_job", lambda *a: pytest.fail("Must not start browser"))
    assert app.test_client().get("/admin/edof-test/server/status").status_code == 401
    assert client.post("/admin/edof-test/server/run", json={"mode": "access"}).status_code == 403
    response = client.post("/admin/edof-test/server/run", json={"mode": "read", "folder_id": "123456789012"}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 409
    with client.session_transaction() as sess:
        sess["partner"] = True
    assert client.get("/admin/edof-test/server/status").status_code == 403


def test_readonly_routes_do_not_leak_env_or_other_owner_results(web, monkeypatch):
    app, client, store, csrf = web
    monkeypatch.setenv("EDOF_EFP_USERNAME", "synthetic@example.invalid")
    monkeypatch.setenv("EDOF_EFP_PASSWORD", "synthetic-private-password")
    job = store.reserve("someone-else", "access")
    store.finish(job, {"code": "read_success", "fields": {"email": "other@example.invalid"}})
    response = client.get("/admin/edof-test/server/status")
    assert response.json["config"]["credentials_configured"] is True
    assert response.json["jobs"] == []
    text = response.get_data(as_text=True) + client.get("/admin/edof-test/server").get_data(as_text=True)
    assert "synthetic-private-password" not in text and "synthetic@example.invalid" not in text and "other@example.invalid" not in text


def test_service_gate_blocks_production(monkeypatch):
    monkeypatch.setenv("RENDER_SERVICE_ID", "production")
    monkeypatch.setattr(server, "register_routes", lambda *a, **k: pytest.fail("Production route registered"))
    server.register_edof_server_test(None)
    assert browser.run_browser({"mode": "access"})["code"] == "wrong_environment"


def test_timeout_kills_process_tree_and_hides_diagnostics(tmp_path, monkeypatch):
    store = server.ServerTestStore(tmp_path)
    job = store.reserve("owner", "read")
    calls = []
    temporary_paths = []
    monkeypatch.setenv("DATABASE_URL", "synthetic-database-secret")
    monkeypatch.setenv("EDOF_EFP_PASSWORD", "synthetic-efp-secret")
    class Child:
        pid = 12345
        def communicate(self, input=None, timeout=None):
            if timeout:
                raise subprocess.TimeoutExpired("synthetic-private-command", timeout)
            return "", ""
    def popen(*args, **kwargs):
        assert "DATABASE_URL" not in kwargs["env"]
        assert kwargs["env"]["EDOF_EFP_PASSWORD"] == "synthetic-efp-secret"
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["start_new_session"] is True
        temporary_paths.append(Path(kwargs["env"]["TMPDIR"]))
        (temporary_paths[-1] / "synthetic-profile").write_text("synthetic-temporary-secret")
        return Child()
    monkeypatch.setattr(server.subprocess, "Popen", popen)
    monkeypatch.setattr(server.os, "killpg", lambda pid, sig: calls.append(pid))
    fd = os.open(tmp_path / "lock", os.O_CREAT | os.O_RDWR, 0o600)
    server.execute_job(store, job, {"mode": "read", "folder_id": "123456789012"}, fd)
    assert calls == [12345]
    assert not temporary_paths[0].exists()
    assert store.latest("owner")[0]["code"] == "timeout"
    assert "synthetic-private" not in json.dumps(store.latest("owner"))
