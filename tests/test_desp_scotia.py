from io import BytesIO
import json
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
import pytest
from werkzeug.http import parse_options_header

import app as host
import desp_jury_projects as projects
from desp_scotia import GROUPS
from tests.test_desp_jury_projects import portal, person, upload, pdf, error


def admin(portal):
    with portal[0].session_transaction() as session:
        session.update(admin_logged_in=True, admin_role="admin")
    return portal[0]


def seed(portal):
    upload(portal, {1: b"PROJECT ONE", 2: b"PROJECT TWO"})
    data = json.loads(portal[1].read_text())
    trainee = data["sessions"][0]["trainees"][0]
    for key, label in [("candidate_info_sheet", b"CANDIDATE"), ("desp_exam_sworn_statement", b"ATTESTATION")]:
        path = portal[1].parent / (key + ".pdf")
        path.write_bytes(pdf(label))
        trainee["documents"].append({"key": key, "file": path.name, "files": [path.name]})
    trainee["candidate_sheet"] = {"first_names": "Élodie", "last_name": "DUPRÉ", "study_domain": "Sécurité",
                                 "financing": "France Travail", "situation": "Salarié"}
    trainee["professional_experience_sheet"] = {
        "first_name": "Élodie", "last_name": "DUPRÉ", "training_name": "DESP initial Paris",
        "last_certification": "Bac professionnel", "current_situation": "employed",
        "experiences": [{"job_title": "Cheffe de site", "company_name": "Société Exemple",
                         "start_date": "2022-02-01", "current_job": True, "contract_type": "cdi",
                         "work_time_percent": 100, "executive_status": "yes"}],
        "validation_name": "Élodie DUPRÉ", "validation_date": "2026-11-04", "signature": "Élodie DUPRÉ",
    }
    portal[1].write_text(json.dumps(data))
    client = admin(portal)
    assert client.post("/admin/sessions/S1/stagiaires/T1/attestation-elearning.pdf",
        data={"document_check_token":"csrf-test", "certificate":(BytesIO(pdf(b"ELEARNING")), "attestation.pdf")}).status_code == 200
    return client


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
    result = client.get(row["download_url"])
    assert result.status_code == 200 and result.mimetype == "application/pdf"
    disposition, options = parse_options_header(result.headers["Content-Disposition"])
    assert disposition == "inline" and options["filename"] == "Dossier SCOTIA Élodie DUPRÉ.pdf"
    pages = PdfReader(BytesIO(result.data)).pages
    texts = [" ".join(page.extract_text().split()) for page in pages]
    assert "Dossier SCOTIA" in texts[0] and all(label in texts[0] for _, label in GROUPS)
    assert "DESP initial Paris" in texts[0] and "10/11/2026" in texts[0]
    covers = [i for i, text in enumerate(texts) if "PIÈCE " in text]
    content = ["DOSSIER CANDIDAT", "Fiche expérience professionnelle", "ATTESTATION",
               "PROJECT ONE", "PROJECT TWO", "ELEARNING"]
    labels = [GROUPS[i][1] for i in (0, 1, 2, 3, 3, 4)]
    assert len(covers) == len(content)
    for i, label, value in zip(covers, labels, content):
        assert label in texts[i] and "Élodie" in texts[i] and "DUPRÉ" in texts[i]
        assert value in texts[i + 1]
    assert "Document 1 sur 2" in texts[covers[3]] and "Document 2 sur 2" in texts[covers[4]]
    assert "Cheffe de site" in texts[covers[1] + 1]
    assert "CANDIDATE" not in " ".join(texts)
    assert not next(row for row in rows(client) if row["id"] == "T2")["ready"]


@pytest.mark.parametrize("key", [key for key, _ in GROUPS])
def test_each_missing_component_blocks_ui_and_direct_download(portal, key):
    client = seed(portal)
    data = json.loads(portal[1].read_text())
    trainee = data["sessions"][0]["trainees"][0]
    if key == "elearning":
        from desp_scotia import certificate_path
        certificate_path(host, data["sessions"][0], trainee).unlink()
    elif key == "project":
        trainee.pop(projects.KEY)
    elif key == "candidate_info_sheet":
        trainee.pop("candidate_sheet")  # The old upload is still there.
    elif key == "professional_experience_sheet":
        trainee.pop(key)
    else:
        trainee["documents"] = [d for d in trainee["documents"] if d["key"] != key]
    portal[1].write_text(json.dumps(data))
    assert not first(client)["ready"] and not first(client)["download_url"]
    assert download(client).status_code == 409
    navigation = client.get("/admin/sessions/S1/stagiaires/T1/dossier-scotia.pdf", headers={"Accept": "text/html"})
    assert navigation.status_code == 409 and navigation.mimetype == "text/plain"
    assert "Dossier SCOTIA incomplet" in navigation.get_data(as_text=True)


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
    pages = PdfReader(BytesIO(download(client).data)).pages
    assert sum("PIÈCE " in p.extract_text() for p in pages) == 5
    assert not any("Document 1 sur 2" in p.extract_text() for p in pages)
    Path(host._detokenize_path(projects.documents(person(portal))[0]["file"])).unlink()
    assert download(client).status_code == 409


def test_saved_online_form_supplies_all_fields_even_with_a_stale_upload(portal):
    from lxml import html

    client = seed(portal)
    form = html.fromstring(client.get("/espace/PUB-T1/fiche-candidat").data).forms[0]
    values = {name: "Valeur" + str(i) for i, name in enumerate(form.fields.keys(), 1)}
    values.update(financing="CPF + France Travail", situation="Salarié", interviewer="Clément VAILLANT")
    assert client.post(form.action, data=values).status_code == 302
    assert first(client)["ready"]
    result = download(client)
    assert result.status_code == 200
    pages = PdfReader(BytesIO(result.data)).pages
    text = " ".join(pages[2].extract_text().split())
    for value in values.values():
        assert value in text
    assert "DOSSIER CANDIDAT" in text and "SCOTIA FORMATION" in text
    assert "ENREGISTRER" not in text
    assert "CANDIDATE" not in text


def test_experience_and_project_keep_all_pages_and_the_saved_signature(portal):
    from reportlab.pdfgen.canvas import Canvas

    client = seed(portal)
    data = json.loads(portal[1].read_text())
    trainee = data["sessions"][0]["trainees"][0]
    sheet = trainee["professional_experience_sheet"]
    sheet["experiences"] = [dict(sheet["experiences"][0], job_title=f"Poste numéro {i}") for i in range(1, 6)]
    sheet["signature"] = "Signature enregistrée"
    portal[1].write_text(json.dumps(data))
    path = Path(host._detokenize_path(projects.documents(trainee)[0]["file"]))
    canvas = Canvas(str(path))
    for value in ("PROJECT PAGE ONE", "PROJECT PAGE TWO"):
        canvas.drawString(40, 700, value)
        canvas.showPage()
    canvas.save()
    pages = [p.extract_text() for p in PdfReader(BytesIO(download(client).data)).pages]
    experience = "".join(pages[next(i for i, txt in enumerate(pages) if "PIÈCE 02" in txt) + 1:
                               next(i for i, txt in enumerate(pages) if "PIÈCE 03" in txt)])
    assert all(f"Poste numéro {i}" in experience for i in range(1, 6))
    assert "Signature enregistrée" in experience
    index = next(i for i, text in enumerate(pages) if "Document 1 sur 2" in text)
    assert [page.strip() for page in pages[index + 1:index + 3]] == ["PROJECT PAGE ONE", "PROJECT PAGE TWO"]


def test_legacy_initial_session_can_complete_both_online_forms(portal):
    data = json.loads(portal[1].read_text())
    data["sessions"][0].update(training_type="DESP INITIAL", date_start="2026-05-01")
    portal[1].write_text(json.dumps(data))
    client = portal[0]
    candidate_form = client.get("/espace/PUB-T1/fiche-candidat")
    assert candidate_form.status_code == 200
    assert 'value="FORMATION INITIALE"' in candidate_form.get_data(as_text=True)
    assert client.post("/espace/PUB-T1/fiche-candidat/enregistrer", data={"last_name": "DUPRÉ"}).status_code == 302
    assert "data-pro-sheet-open" in client.get("/espace/PUB-T1").get_data(as_text=True)
    response = client.post("/espace/PUB-T1/fiche-experience-professionnelle", json={
        "current_situation": "employed", "qualification_level": "bac", "qualification_since": "2016-01-01",
        "last_certification": "Bac", "validation_name": "Élodie DUPRÉ", "validation_date": "2026-05-02",
        "certified": True, "experiences": [{"job_title": "Cheffe de site", "company_name": "Exemple",
            "start_date": "2017-01-01", "current_job": True, "work_time_percent": "100",
            "contract_type": "cdi", "executive_status": "yes"}],
    })
    assert response.status_code == 200
    states = {doc["key"]: doc["available"] for doc in first(admin(portal))["documents"]}
    assert states["candidate_info_sheet"] and states["professional_experience_sheet"]


def test_png_attestation_is_converted(portal):
    client = seed(portal)
    data = json.loads(portal[1].read_text())
    path = portal[1].parent / "scan.png"
    Image.new("RGB", (200, 300), "white").save(path)
    data["sessions"][0]["trainees"][0]["documents"][1].update(file=path.name, files=[])
    portal[1].write_text(json.dumps(data))
    assert first(client)["ready"]
    pages = PdfReader(BytesIO(download(client).data)).pages
    index = next(i for i, page in enumerate(pages) if "PIÈCE 03" in page.extract_text())
    assert pages[index + 1].images and "Projet de cadrage" in pages[index + 2].extract_text()


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


def test_certificate_replacement_requires_admin_write_csrf_and_valid_pdf(portal):
    client = seed(portal)
    url = "/admin/sessions/S1/stagiaires/T1/attestation-elearning.pdf"
    def replace(content, token="csrf-test"):
        return client.post(url, data={"certificate": (BytesIO(content), "attestation.pdf"),
                                      "document_check_token": token})
    assert replace(b"broken").status_code == 400
    assert replace(pdf(b"OTHER"), "wrong").status_code == 403
    assert client.get(url).data == pdf(b"ELEARNING")
    assert replace(pdf(b"NEW")).status_code == 200
    assert PdfReader(BytesIO(download(client).data)).pages[-1].extract_text().strip() == "NEW"
    with client.session_transaction() as session:
        session["admin_role"] = "viewer"
    assert replace(pdf(b"NO")).status_code == 403
