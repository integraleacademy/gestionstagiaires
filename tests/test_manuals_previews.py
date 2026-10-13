"""No public URL may return a full manual, even after replacing an asset."""
import io
from pathlib import Path

from flask import Flask
from pypdf import PdfReader, PdfWriter
import pytest

from manuals_presentation import PRESENTATIONS
from manuals_previews import LEGACY_SPECIMENS, register

STATIC = Path(__file__).resolve().parents[1] / "static"
SAMPLES = [(code, b) for code, b in PRESENTATIONS.items() if b.get("specimen")]


@pytest.fixture
def client():
    app = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")
    register(app)
    return app.test_client()


@pytest.mark.parametrize("code,book", SAMPLES)
def test_every_download_contains_only_advertised_pages(client, code, book):
    response = client.get("/static/" + book["specimen"])
    assert response.status_code == 200, code
    assert response.mimetype == "application/pdf"
    reader = PdfReader(io.BytesIO(response.data))
    assert len(reader.pages) == book["specimen_pages"] <= 10
    assert not reader.attachments
    assert response.headers["Cache-Control"] == "no-store"
    assert "noindex" in response.headers["X-Robots-Tag"]


@pytest.mark.parametrize("legacy,code", LEGACY_SPECIMENS.items())
def test_old_urls_and_query_parameters_cannot_expose_full_source(client, legacy, code):
    assert not (STATIC / legacy).exists()
    old = "/static/" + legacy + "?download=1&page=200&full=true"
    response = client.get(old)
    assert response.status_code == 308
    assert response.location == "/static/" + PRESENTATIONS[code]["specimen"]
    result = client.get(old, follow_redirects=True)
    assert len(PdfReader(io.BytesIO(result.data)).pages) == 10
    assert client.head(old).status_code == 308
    # Dot segments must obey the same policy as Flask's static-file handler.
    assert client.get("/static/manuals/../" + legacy).status_code == 308


def test_unknown_and_full_replacement_files_are_never_served(tmp_path):
    app = Flask(__name__, static_folder=str(tmp_path), static_url_path="/static")
    register(app)
    client = app.test_client()
    target = tmp_path / PRESENTATIONS["ssiap1"]["specimen"]
    target.parent.mkdir(parents=True)

    def write(pages):
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=420, height=595)
        writer.write(target)

    write(10)
    url = "/static/" + PRESENTATIONS["ssiap1"]["specimen"]
    assert client.get(url).status_code == 200
    write(264)
    for headers in ({}, {"Range": "bytes=0-1023"}, {"If-None-Match": "old-etag"}):
        assert client.get(url, headers=headers).status_code == 404
    assert client.head(url).status_code == 404
    target.write_bytes(b"not a PDF")
    assert client.get(url).status_code == 404
    (target.parent / "full.pdf").write_bytes(b"unlisted content")
    assert client.get("/static/manuals/specimens/full.pdf").status_code == 404
    assert client.get("/static/specimen-secret.pdf").status_code == 404
