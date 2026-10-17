"""The shop shares Qonto's registered callback without crossing service boundaries."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import app as host
from test_manuals_shop import shop
from test_partner_workspace import as_admin

ORIGIN = "https://gestionstagiaires-test-v2.onrender.com"
CALLBACK = "/api/qonto/oauth/callback"
CONNECT = "/admin/commandes-manuels/connexion-paiement"


@pytest.fixture
def payment_admin(shop, monkeypatch):
    monkeypatch.setitem(host.app.config, "SERVER_NAME", urlsplit(ORIGIN).netloc)
    monkeypatch.setattr(host, "QONTO_OAUTH_REDIRECT_URI", ORIGIN + CALLBACK)
    monkeypatch.setattr(host, "_qonto_oauth_is_configured", lambda: True)
    monkeypatch.setattr(host, "_qonto_oauth_client_id", lambda: "test-client")
    monkeypatch.setattr(host, "_qonto_oauth_client_secret", lambda: "test-secret")
    client = shop["client"]
    as_admin(client)
    return client


def test_custom_domain_starts_on_callback_host_before_creating_state(payment_admin, monkeypatch):
    monkeypatch.setitem(host.app.config, "SERVER_NAME", None)
    alias = "https://www.integraleconnect.com"
    with payment_admin.session_transaction(base_url=alias) as session:
        session.update(admin_logged_in=True, admin_role="super_admin", platform_role="super_admin",
                       partner_id=host.INTEGRALE_PARTNER_ID, admin_username="admin@example.test")
    response = payment_admin.get(CONNECT + "?return_to=partners", base_url=alias)
    assert response.location == ORIGIN + CONNECT + "?return_to=partners"
    with payment_admin.session_transaction(base_url=alias) as session:
        assert "manuals_payment_connection" not in session


def test_test_service_cannot_authorize_production_callback(payment_admin, monkeypatch):
    monkeypatch.setattr(host, "QONTO_OAUTH_REDIRECT_URI", host.QONTO_OAUTH_PRODUCTION_REDIRECT_URI)
    response = payment_admin.get(CONNECT + "?return_to=partners")
    assert response.location == "/admin/partners?tab=settings"
    with payment_admin.session_transaction() as session:
        assert "manuals_payment_connection" not in session
        assert "ne correspond pas à ce service" in session["_flashes"][-1][1]


@pytest.mark.parametrize("invalid", ["expired", "missing", "forged"])
def test_shared_callback_rejects_expired_missing_and_forged_payment_state(payment_admin, monkeypatch, invalid):
    exchanges = []
    monkeypatch.setattr(host, "_exchange_qonto_oauth_token", lambda payload: exchanges.append(payload))
    params = parse_qs(urlsplit(payment_admin.get(CONNECT).location).query)
    state = params["state"][0]
    with payment_admin.session_transaction() as session:
        if invalid == "expired":
            saved = dict(session["manuals_payment_connection"])
            saved["created"] -= 601
            session["manuals_payment_connection"] = saved
        elif invalid == "missing":
            session.pop("manuals_payment_connection")
        else:
            state = host.QONTO_PAYMENT_STATE_PREFIX + "forged"
    response = payment_admin.get(CALLBACK, query_string={"state": state, "code": "test-code"})
    assert response.status_code == 400
    assert exchanges == []


def test_shared_payment_callback_still_requires_platform_admin(payment_admin, monkeypatch):
    exchanges = []
    monkeypatch.setattr(host, "_exchange_qonto_oauth_token", lambda payload: exchanges.append(payload))
    params = parse_qs(urlsplit(payment_admin.get(CONNECT).location).query)
    with payment_admin.session_transaction() as session:
        session["admin_role"] = "viewer"
        session["platform_role"] = "viewer"
    response = payment_admin.get(CALLBACK, query_string={"state": params["state"][0], "code": "test-code"})
    assert response.status_code == 403
    assert exchanges == []


def test_missing_payment_permissions_keep_existing_connection(payment_admin, monkeypatch):
    data = json.loads(Path(host.DATA_FILE).read_text())
    previous = {"access_token": "existing-test-token", "refresh_token": "existing-test-refresh", "scope": host.QONTO_OAUTH_SCOPE}
    data["qonto_oauth"] = previous
    Path(host.DATA_FILE).write_text(json.dumps(data))
    monkeypatch.setattr(host, "_exchange_qonto_oauth_token", lambda payload: {
        "access_token": "incomplete-test-token", "refresh_token": "incomplete-test-refresh",
        "expires_in": 3600, "scope": host.QONTO_OAUTH_SCOPE,
    })
    params = parse_qs(urlsplit(payment_admin.get(CONNECT + "?return_to=partners").location).query)
    response = payment_admin.get(CALLBACK, query_string={"state": params["state"][0], "code": "test-code"})
    assert response.location == "/admin/partners?tab=settings"
    assert json.loads(Path(host.DATA_FILE).read_text())["qonto_oauth"] == previous
    with payment_admin.session_transaction() as session:
        assert "n’a pas accordé toutes les autorisations" in session["_flashes"][-1][1]
