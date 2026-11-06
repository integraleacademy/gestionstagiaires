import pytest
from flask import Flask, Response, redirect

from maintenance_recovery import register_maintenance_recovery


@pytest.fixture
def client():
    app = Flask(__name__)
    register_maintenance_recovery(app, enabled=True)
    register_maintenance_recovery(app, enabled=True)

    @app.route("/page", methods=["GET", "POST"])
    def page():
        return Response("<!doctype html><body>Private page</body>", headers={"ETag": '"old"'})

    @app.get("/data")
    def data():
        return {"ok": True}

    @app.get("/partial")
    def partial():
        return "<p>Fragment</p>"

    @app.get("/download")
    def download():
        return Response("<body>Downloaded document</body>", headers={"Content-Disposition": "attachment"})

    @app.get("/stream")
    def stream():
        return Response(iter(["<body>", "Stream", "</body>"]), mimetype="text/html")

    @app.get("/redirect")
    def redirect_route():
        return redirect("/page")

    return app.test_client()


def test_full_browser_page_registers_once_and_updates_length(client):
    result = client.get("/page", headers={"Sec-Fetch-Dest": "document"})
    assert result.data.count(b"maintenance-register.js") == 1
    assert result.data.endswith(b"</body>")
    assert result.content_length == len(result.data)
    assert "ETag" not in result.headers
    assert "Set-Cookie" not in result.headers


def test_older_browser_navigation_is_supported(client):
    assert b"maintenance-register.js" in client.get("/page", headers={"Accept": "text/html"}).data


@pytest.mark.parametrize("path,method,headers", [
    ("/page", "POST", {"Sec-Fetch-Dest": "document"}),
    ("/page", "GET", {"Sec-Fetch-Dest": "empty", "Accept": "text/html"}),
    ("/page", "GET", {"X-Requested-With": "XMLHttpRequest", "Accept": "text/html"}),
    ("/page", "GET", {"Accept": "application/json"}),
    ("/data", "GET", {"Sec-Fetch-Dest": "document"}),
    ("/partial", "GET", {"Sec-Fetch-Dest": "document"}),
    ("/download", "GET", {"Sec-Fetch-Dest": "document"}),
    ("/stream", "GET", {"Sec-Fetch-Dest": "document"}),
    ("/redirect", "GET", {"Sec-Fetch-Dest": "document"}),
])
def test_non_page_responses_are_unchanged(client, path, method, headers):
    assert b"maintenance-register.js" not in client.open(path, method=method, headers=headers).data


def test_other_render_services_are_not_modified(monkeypatch):
    monkeypatch.setenv("RENDER_SERVICE_ID", "another-service")
    app = Flask(__name__)
    register_maintenance_recovery(app)
    assert "maintenance_recovery" not in app.extensions
