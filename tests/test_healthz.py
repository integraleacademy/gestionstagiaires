from app import app


def test_healthz_is_public_and_lightweight():
    response = app.test_client().get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "service": "gestionstagiaires"}
    assert "Cache-Control" not in response.headers
