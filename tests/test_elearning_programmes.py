"""The approved brochure is public, independently of purchases and sales pauses."""
import pytest

import app as host
from elearning_programmes import PROGRAMMES
from test_manuals_shop import shop, signup, login


def test_public_programme_is_available_before_purchase_and_during_sales_pause(shop, monkeypatch):
    import elearning_sales

    monkeypatch.setattr(elearning_sales, "enabled", lambda host: False)
    client = shop["client"]
    page = client.get("/e-learning/aps")
    assert page.status_code == 200
    assert "Ventes momentanément indisponibles" in page.text
    assert page.text.count('href="/e-learning/aps/programme.pdf"') == 2
    response = client.get("/e-learning/aps/programme.pdf")
    assert response.status_code == 200 and response.mimetype == "application/pdf"
    assert response.data == PROGRAMMES["aps"]["path"].read_bytes()
    assert "attachment; filename=Programme_E-learning_APS_62h_Integrale_Connect.pdf" in response.headers["Content-Disposition"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert client.head("/e-learning/aps/programme.pdf").status_code == 200
    assert not shop["mails"]


def test_public_programme_remains_available_to_logged_in_accounts(shop):
    client = shop["client"]
    signup(client)
    login(client)
    assert client.get("/e-learning/aps/programme.pdf").status_code == 200
    admin = host.app.test_client()
    assert admin.post("/admin/login", data={"username": "admin@example.test", "password": "platform-test-pass"}).status_code == 302
    assert admin.get("/e-learning/aps/programme.pdf").status_code == 200


@pytest.mark.parametrize("code", ["vtc", "mac-aps", "a3p", "unknown"])
def test_no_aps_document_for_other_courses(shop, code):
    client = shop["client"]
    assert client.get(f"/e-learning/{code}/programme.pdf").status_code == 404
    page = client.get(f"/e-learning/{code}")
    assert "Télécharger le programme PDF" not in page.text


def test_missing_programme_returns_not_found(shop, monkeypatch, tmp_path):
    monkeypatch.setitem(PROGRAMMES["aps"], "path", tmp_path / "missing.pdf")
    assert shop["client"].get("/e-learning/aps/programme.pdf").status_code == 404
