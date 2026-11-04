from io import BytesIO
import json
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
import pytest

import app as host
import desp_jury_projects as projects
from tests.test_desp_jury_projects import portal, person, upload, pdf, error


def admin(portal):
    with portal[0].session_transaction() as session:
        session.update(admin_logged_in=True, admin_role="admin")
    return portal[0]


def seed(portal, *, online=False):
    upload(portal, {1: b"PROJECT ONE", 2: b"PROJECT TWO"})
    data = json.loads(portal[1].read_text())
    trainee = data["sessions"][0]["trainees"][0]
    for key, label in [("candidate_info_sheet", b"CANDIDATE"), ("desp_exam_sworn_statement", b"ATTESTATION")]:
        path = portal[1].parent / (key + ".pdf")
        path.write_bytes(pdf(label))
        trainee["documents"].append({"key": key, "file": path.name, "files": [path.name]})
    if online:
        trainee["documents"] = trainee["documents"][1:]
        trainee["candidate_sheet"] = {"first_names": "Élodie", "last_name": "DUPRÉ", "study_domain": "Sécurité"}
        trainee["candidate_sheet_saved_at"] = "2026-11-04T10:00:00"
    portal[1].write_text(json.dumps(data))
    return admin(portal)


def rows(client):
    response = client.get("/api/admin/sessions/S1/desp-scotia")
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    return response.json["candidates"]


def first(client):
    return next(row for row in rows(client) if row["id"] == "T1")


def download(client):
    return client.get("/admin/sessions/S1/stagiaires/T1/dossier-scotia.pdf")


def test_single_pdf_all_pages_in_order_and_no_duplicate_file_token(portal):
    client = seed(portal)
    row = first(client)
    assert row["ready"] and row["download_url"]
    result = download(client)
    assert result.status_code == 200 and result.mimetype == "application/pdf"
    pages = PdfReader(BytesIO(result.data)).pages
    assert [page.extract_text().strip() for page in pages] == ["CANDIDATE", "ATTESTATION", "PROJECT ONE", "PROJECT TWO"]
    assert not next(row for row in rows(client) if row["id"] == "T2")["ready"]


@pytest.mark.parametrize("key", ["candidate_info_sheet", "desp_exam_sworn_statement", "project"])
def test_each_missing_component_blocks_ui_and_direct_download(portal, key):
    client = seed(portal)
    data = json.loads(portal[1].read_text())
    trainee = data["sessions"][0]["trainees"][0]
    if key == "project":
        trainee.pop(projects.KEY)
    else:
        trainee["documents"] = [d for d in trainee["documents"] if d["key"] != key]
    portal[1].write_text(json.dumps(data))
    assert not first(client)["ready"] and not first(client)["download_url"]
    assert download(client).status_code == 409


@pytest.mark.parametrize("mode", ["missing", "corrupt", "renamed", "encrypted"])
def test_bad_project_is_not_silently_skipped(portal, mode):
    client = seed(portal)
    path = Path(host._detokenize_path(projects.documents(person(portal))[1]["file"]))
    if mode == "missing":
        path.unlink()
    elif mode in {"corrupt", "renamed"}:
        path.write_bytes(b"%PDF-invalid" if mode == "corrupt" else b"PK-not-a-pdf")
    else:
        writer = PdfWriter(); writer.add_blank_page(width=595, height=842); writer.encrypt("password")
        with path.open("wb") as stream: writer.write(stream)
    assert not first(client)["ready"]
    assert download(client).status_code == 409


def test_one_project_pdf_is_sufficient_and_late_deletion_is_rechecked(portal):
    client = seed(portal)
    upload(portal, remove_2="1")
    assert first(client)["ready"]
    assert len(PdfReader(BytesIO(download(client).data)).pages) == 3
    Path(host._detokenize_path(projects.documents(person(portal))[0]["file"])).unlink()
    assert download(client).status_code == 409


def test_saved_online_sheet_is_exported_with_every_value(portal):
    client = seed(portal, online=True)
    assert first(client)["ready"]
    result = download(client)
    assert result.status_code == 200
    pages = PdfReader(BytesIO(result.data)).pages
    assert "Élodie" in pages[0].extract_text() and "Sécurité" in pages[0].extract_text()
    assert pages[-3].extract_text().strip() == "ATTESTATION"
    assert pages[-1].extract_text().strip() == "PROJECT TWO"


def test_png_attestation_is_converted(portal):
    client = seed(portal)
    data = json.loads(portal[1].read_text())
    path = portal[1].parent / "scan.png"
    Image.new("RGB", (200, 300), "white").save(path)
    data["sessions"][0]["trainees"][0]["documents"][1].update(file=path.name, files=[])
    portal[1].write_text(json.dumps(data))
    assert first(client)["ready"]
    assert len(PdfReader(BytesIO(download(client).data)).pages) == 4


def test_auth_cancelled_other_training_and_tenant_access(portal, monkeypatch):
    assert portal[0].get("/api/admin/sessions/S1/desp-scotia").status_code == 401
    client = seed(portal)
    monkeypatch.setattr(host, "_partner_can_access_upload_token", lambda token: False)
    assert not first(client)["ready"]
    assert download(client).status_code == 409
    monkeypatch.setattr(host, "_partner_can_access_upload_token", lambda token: True)
    data = json.loads(portal[1].read_text())
    data["sessions"][0]["trainees"][0]["registration_cancelled"] = True
    portal[1].write_text(json.dumps(data))
    assert [row["id"] for row in rows(client)] == ["T2"]
    assert download(client).status_code == 404
    data["sessions"][0]["training_type"] = "DIRIGEANT VAE"
    portal[1].write_text(json.dumps(data))
    assert client.get("/api/admin/sessions/S1/desp-scotia").status_code == 404


@pytest.mark.parametrize("name,content", [("project.docx", b"PK-office"), ("renamed.pdf", b"PK-office"),
                                        ("broken.pdf", b"%PDF-broken")])
def test_upload_rejects_non_pdf_content_without_losing_previous_files(portal, name, content):
    upload(portal, {1: b"existing"})
    previous = person(portal)[projects.KEY]
    upload(portal, file_1=(BytesIO(content), name))
    assert person(portal)[projects.KEY] == previous
    assert error(portal)


def test_exam_tab_and_pdf_only_public_inputs(portal):
    client = admin(portal)
    response = client.get("/admin/sessions/S1/trainees")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'data-exam-tab="scotia"' in text and 'Dossier SCOTIA' in text
    public = client.get("/espace/PUB-T1").get_data(as_text=True)
    assert 'accept=".pdf"' in public and 'Format accepté : PDF uniquement.' in public
