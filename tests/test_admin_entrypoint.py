from urllib.parse import urlparse

import pytest

import app as gestion


@pytest.mark.parametrize("path", ["/admin", "/admin/"])
def test_admin_entrypoint_opens_sessions_for_signed_in_admin(path):
    client = gestion.app.test_client()
    with client.session_transaction() as session:
        session["admin_logged_in"] = True
        session["admin_role"] = "admin"

    response = client.get(path)

    assert response.status_code == 301
    assert response.location == "/admin/sessions"


@pytest.mark.parametrize("path", ["/admin", "/admin/"])
def test_admin_entrypoint_still_requires_login(path):
    client = gestion.app.test_client()

    response = client.get(path, follow_redirects=True)

    assert response.status_code == 200
    assert urlparse(response.request.url).path == "/admin/login"
