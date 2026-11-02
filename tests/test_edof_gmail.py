import base64
from functools import wraps
from pathlib import Path
import time
from urllib.parse import parse_qs, urlsplit

from flask import Flask, jsonify, session
import pytest

import edof_gmail as gmail
import edof_server_browser as browser
import edof_server_test as server

EMAIL = "camille.exemple@gmail.com"
SECRET = "synthetic-private-secret-for-unit-tests-only"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("EDOF_EFP_USERNAME", EMAIL)
    return gmail.Vault(tmp_path, gmail.connector_key(SECRET))


def test_encrypted_vault_expiry_account_binding_and_single_use(vault, monkeypatch):
    vault.put("gmail", {"refresh_token": "synthetic-private-refresh"})
    assert b"synthetic-private-refresh" not in vault.path.read_bytes()
    assert EMAIL.encode() not in vault.path.read_bytes()
    assert vault.get("gmail")["refresh_token"] == "synthetic-private-refresh"
    assert vault.path.stat().st_mode & 0o777 == 0o600
    vault.put("oauth", {"state": "synthetic-state"}, ttl=10)
    assert vault.get("oauth", consume=True)
    assert vault.get("oauth", consume=True) is None
    vault.put("browser", {"cookies": []}, ttl=1)
    now = time.time()
    monkeypatch.setattr(gmail.time, "time", lambda: now + 2)
    assert vault.get("browser") is None
    monkeypatch.setenv("EDOF_EFP_USERNAME", "another@example.invalid")
    assert vault.get("gmail") is None
    assert gmail.connector_key("dev-secret-change-me") is None


def test_oauth_requests_only_readonly_offline_scope_with_pkce(monkeypatch):
    monkeypatch.setenv("EDOF_GOOGLE_CLIENT_ID", "synthetic-client-id")
    url = gmail.authorization_url("synthetic-state", "synthetic-verifier")
    query = parse_qs(urlsplit(url).query)
    assert query["scope"] == [gmail.SCOPE]
    assert query["redirect_uri"] == [gmail.CALLBACK]
    assert query["access_type"] == ["offline"]
    assert query["code_challenge_method"] == ["S256"]
    assert "synthetic-verifier" not in url


@pytest.mark.parametrize("email,scope,refresh,expected", [
    (EMAIL, gmail.SCOPE, "synthetic-refresh", None),
    ("wrong@gmail.com", gmail.SCOPE, "synthetic-refresh", "gmail_account_mismatch"),
    (EMAIL, "https://www.googleapis.com/auth/gmail.metadata", "synthetic-refresh", "gmail_permission_missing"),
    (EMAIL, gmail.SCOPE, None, "gmail_permission_missing"),
])
def test_connection_requires_right_mailbox_and_refresh_token(vault, monkeypatch, email, scope, refresh, expected):
    monkeypatch.setattr(gmail, "token_request", lambda data: {"access_token": "synthetic-access", "refresh_token": refresh, "scope": scope})
    monkeypatch.setattr(gmail, "google_json", lambda *a, **k: {"emailAddress": email})
    if expected:
        with pytest.raises(gmail.GmailError) as exc:
            gmail.finish_authorization(vault, "synthetic-code", "synthetic-verifier")
        assert exc.value.code == expected
        assert vault.get("gmail") is None
    else:
        gmail.finish_authorization(vault, "synthetic-code", "synthetic-verifier")
        assert vault.get("gmail") == {"refresh_token": "synthetic-refresh"}


def message(body="EFP Connect. Votre code de sécurité : 123456", **overrides):
    result = {"id": "synthetic-message", "internalDate": str(int(time.time() * 1000)), "payload": {
        "mimeType": "text/plain", "headers": [
            {"name": "From", "value": gmail.SENDER}, {"name": "To", "value": EMAIL},
            {"name": "Subject", "value": "Code EFP Connect"},
            {"name": "Authentication-Results", "value": "mx.google.com; dkim=pass header.d=emploi.gouv.fr; dmarc=pass header.from=emploi.gouv.fr"}],
        "body": {"data": base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")}}}
    result.update(overrides)
    return result


def test_only_fresh_authenticated_login_code_can_be_extracted():
    started = time.time() - 1
    assert gmail.extract_code(message(), EMAIL, started) == "123456"
    assert gmail.extract_code(message(internalDate=str(int((started - 1) * 1000))), EMAIL, started) is None
    assert gmail.extract_code(message(), "another@gmail.com", started) is None
    for index, value in [(0, "attacker@example.invalid"), (3, "mx.google.com; dkim=fail header.d=emploi.gouv.fr")]:
        item = message()
        item["payload"]["headers"][index]["value"] = value
        assert gmail.extract_code(item, EMAIL, started) is None
    assert gmail.extract_code(message("EFP. Code de sécurité : 123456. Code : 654321"), EMAIL, started) is None
    assert gmail.extract_code(message("EFP. Réinitialiser votre mot de passe, code : 123456"), EMAIL, started) is None
    assert gmail.extract_code(message("EFP. Votre code est valable 30 minutes"), EMAIL, started) is None
    assert gmail.extract_code(message("EFP. Le code responsable des accès : 123456"), EMAIL, started) is None


def test_html_and_attachments_are_not_executed_or_read():
    item = message("<div>EFP Connect : votre code de sécurité : <b>123456</b></div><script>code : 987654</script>")
    item["payload"]["mimeType"] = "text/html"
    assert gmail.extract_code(item, EMAIL, time.time() - 1) == "123456"
    item["payload"]["filename"] = "piece-jointe.html"
    assert gmail.extract_code(item, EMAIL, time.time() - 1) is None


def test_gmail_reads_skip_preexisting_messages_and_never_modify_mail(vault, monkeypatch):
    vault.put("gmail", {"refresh_token": "synthetic-refresh"})
    monkeypatch.setattr(gmail, "token_request", lambda data: {"access_token": "synthetic-access", "scope": gmail.SCOPE})
    calls = []
    lists = iter([[{"id": "old"}], [{"id": "old"}, {"id": "new"}]])
    def get(method, url, **kwargs):
        assert method == "GET"
        calls.append((url, kwargs))
        if url.endswith("/messages"):
            return {"messages": next(lists)}
        assert url.endswith("/new")
        return message()
    monkeypatch.setattr(gmail, "google_json", get)
    inbox = gmail.GmailCodes(vault, EMAIL)
    assert inbox.wait_for_code(time.time() - 1) == "123456"
    assert len(calls) == 3
    assert gmail.SENDER in calls[0][1]["params"]["q"]
    assert EMAIL in calls[0][1]["params"]["q"]


@pytest.mark.parametrize("result,accepted", [
    ("dkim=pass header.i=@emploi.gouv.fr header.s=synthetic header.b=abc", True),
    ("dkim=pass (verified) header.i=sender@mail.emploi.gouv.fr", True),
    ("dkim=fail header.i=@emploi.gouv.fr; dkim=pass header.i=@example.invalid", False),
    ("dkim=pass header.d=example.invalid header.i=@emploi.gouv.fr", False),
    ("dkim=pass header.i=@emploi.gouv.fr.example.invalid", False),
    ("dkim=pass header.i=@notemploi.gouv.fr", False),
    ("spf=pass smtp.mailfrom=emploi.gouv.fr", False),
    ('dkim=fail reason="; dkim=pass header.i=@emploi.gouv.fr;"', False),
    ("spf=pass (nested (result); dkim=pass header.i=@emploi.gouv.fr;)", False),
    ("dkim=pass header.i=@emploi.gouv.fr header.i=@example.invalid", False),
])
def test_google_verified_sender_identity_is_bound_to_the_passing_clause(result, accepted):
    item = message()
    item["payload"]["headers"][-1]["value"] = "mx.google.com; " + result
    # Earlier (less trusted) hops cannot override Google's first verdict.
    item["payload"]["headers"].append({"name": "Authentication-Results", "value":
        "mx.google.com; dmarc=pass header.from=emploi.gouv.fr"})
    reasons = {}
    assert gmail.extract_code(item, EMAIL, time.time() - 1, rejections=reasons) == ("123456" if accepted else None)
    assert reasons == ({} if accepted else {"sender_authentication_failed": 1})


@pytest.mark.parametrize("case,expected", [
    ("absent", {}), ("refused", {"code_unrecognized": 1}),
    ("other_mx", {"authentication_header_missing": 1}),
])
def test_missing_code_only_reports_counts_and_never_rechecks_old_mail(monkeypatch, case, expected):
    box = object.__new__(gmail.GmailCodes)
    box.recipient, box.headers, box.baseline = EMAIL, {}, {"existing"}
    ids = ["existing"] if case == "absent" else ["existing", "synthetic-message"]
    monkeypatch.setattr(box, "list_ids", lambda since: ids)
    item = message("EDOF. Numéro de dossier : 123456")
    if case == "other_mx":
        item["payload"]["headers"][-1]["value"] = "example.invalid; dkim=pass header.d=emploi.gouv.fr"
    reads = []
    def read(method, url, **kwargs):
        assert method == "GET" and url.endswith("/synthetic-message")
        reads.append(url)
        return item
    monkeypatch.setattr(gmail, "google_json", read)
    clock = iter([0, 0, 1, 3])
    monkeypatch.setattr(gmail.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(gmail.time, "sleep", lambda seconds: None)
    with pytest.raises(gmail.GmailError) as exc:
        box.wait_for_code(time.time() - 1, timeout=2)
    assert exc.value.code == "gmail_code_missing"
    assert exc.value.diagnostics == {"gmail_messages_checked": sum(expected.values()), "gmail_rejections": expected}
    assert len(reads) == sum(expected.values())


def test_revoked_google_grant_discards_session(vault, monkeypatch):
    vault.put("gmail", {"refresh_token": "synthetic-refresh"})
    vault.put("browser", {"cookies": []})
    def rejected(*args):
        raise gmail.GmailError("gmail_reconnect_required")
    monkeypatch.setattr(gmail, "token_request", rejected)
    with pytest.raises(gmail.GmailError):
        gmail.GmailCodes(vault, EMAIL)
    assert vault.get("gmail") is None and vault.get("browser") is None

def test_test_v2_access_logs_do_not_include_auth_codes(monkeypatch):
    import datetime
    import runpy
    from gunicorn.config import Config
    from gunicorn.glogging import Logger
    class Response:
        status = "303 See Other"
        response_length = 0
        headers = {}
    environ = {"REQUEST_METHOD": "GET", "RAW_URI": "/admin/edof-test/server/gmail/callback?code=synthetic-private",
               "PATH_INFO": "/admin/edof-test/server/gmail/callback", "QUERY_STRING": "code=synthetic-private",
               "SERVER_PROTOCOL": "HTTP/1.1", "HTTP_REFERER": "https://example.invalid/?code=synthetic-private"}
    atoms = Logger(Config()).atoms(Response(), {}, environ, datetime.timedelta(seconds=1))
    monkeypatch.setenv("RENDER_SERVICE_ID", server.TEST_SERVICE_ID)
    config_path = Path(server.__file__).with_name("gunicorn.conf.py")
    fmt = runpy.run_path(str(config_path))["access_log_format"]
    assert "synthetic-private" not in fmt % atoms
    assert "/admin/edof-test/server/gmail/callback" in fmt % atoms
    monkeypatch.setenv("RENDER_SERVICE_ID", "production")
    assert "%(r)s" in runpy.run_path(str(config_path))["access_log_format"]



def test_only_auth_hosts_cookies_persist_no_local_storage():
    state = {"cookies": [{"domain": "efpconnect.emploi.gouv.fr", "secure": True, "value": "synthetic"},
                         {"domain": "tracker.example.invalid", "secure": True},
                         {"domain": "of.moncompteformation.gouv.fr", "secure": False}],
             "origins": [{"origin": "https://of.moncompteformation.gouv.fr", "localStorage": [{"name": "trainee", "value": "synthetic-private"}]}]}
    saved = browser.session_cookies(state)
    assert len(saved["cookies"]) == 1 and saved["origins"] == []
    assert not browser.private_page(browser.LOGIN_URL)
    assert browser.private_page(browser.DETAIL_PREFIX + "123456789012")


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setenv("EDOF_EFP_USERNAME", EMAIL)
    monkeypatch.setenv("EDOF_EFP_PASSWORD", "synthetic-efp-password")
    monkeypatch.setenv("EDOF_GOOGLE_CLIENT_ID", "synthetic-google-id")
    monkeypatch.setenv("EDOF_GOOGLE_CLIENT_SECRET", "synthetic-google-secret")
    app = Flask(__name__, template_folder=str(Path(server.__file__).parent / "templates"))
    app.config.update(TESTING=True, SECRET_KEY=SECRET)
    store = server.ServerTestStore(tmp_path)
    def required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not session.get("admin"):
                return jsonify(ok=False), 401
            return view(*args, **kwargs)
        return wrapper
    server.register_routes(app, store, admin_required=required, can_access=lambda: not session.get("partner"))
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin"] = True
    client.get("/admin/edof-test/server")
    with client.session_transaction() as sess:
        csrf = sess["edof_server_csrf"]
    return app, client, store, csrf


def test_gmail_oauth_requires_csrf_consent_owner_state_and_is_single_use(web, monkeypatch):
    app, client, store, csrf = web
    path = "/admin/edof-test/server/gmail"
    assert client.post(path + "/connect", data={"consent": "yes"}).status_code == 403
    assert client.post(path + "/connect", data={"csrf": csrf}).status_code == 400
    response = client.post(path + "/connect", data={"csrf": csrf, "consent": "yes"})
    assert response.status_code == 303
    state = parse_qs(urlsplit(response.location).query)["state"][0]
    calls = []
    monkeypatch.setattr(server, "finish_authorization", lambda *args: calls.append(True))
    wrong = app.test_client()
    with wrong.session_transaction() as sess:
        sess["admin"] = True
    assert "gmail=invalid" in wrong.get(path + "/callback", query_string={"code": "synthetic", "state": state}).location
    assert calls == []
    response = client.get(path + "/callback", query_string={"code": "synthetic", "state": state})
    assert "gmail=connected" in response.location and calls == [True]
    assert "gmail=invalid" in client.get(path + "/callback", query_string={"code": "synthetic", "state": state}).location
    assert calls == [True]


def test_status_never_exports_gmail_secrets_and_disconnect_clears_access(web):
    app, client, store, csrf = web
    vault = gmail.Vault(store.directory, store.connector_key)
    vault.put("gmail", {"refresh_token": "synthetic-refresh-token"})
    vault.put("browser", {"cookies": [{"value": "synthetic-cookie"}]})
    response = client.get("/admin/edof-test/server/status")
    assert response.json["gmail"]["connected"] is True
    assert "synthetic" not in response.get_data(as_text=True)
    assert EMAIL not in response.get_data(as_text=True)
    assert client.post("/admin/edof-test/server/gmail/disconnect").status_code == 403
    response = client.post("/admin/edof-test/server/gmail/disconnect", data={"csrf": csrf})
    assert "gmail=disconnected" in response.location
    assert vault.get("gmail") is None and vault.get("browser") is None

