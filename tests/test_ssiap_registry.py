import io
import json
from urllib.parse import urlsplit

import pymupdf
import pytest
from PIL import Image
from pypdf import PdfReader

import app as services
import ssiap_diploma_registry as registry

ROOT = "/admin/outils/diplomes-ssiap"
FORM = dict(civility="Madame", first_name="Éva", last_name="EXEMPLE", birth_date="1990-02-12",
            birth_city="Lyon", birth_department="69", birth_country="France", exam_date="2022-09-02",
            level="SSIAP 2", number="ARCHIVE-2022-014", exam_number="EX-22-03", exam_place="Fréjus",
            issue_date="2022-09-16", issue_place="Fréjus", issuer="Intégrale Academy",
            approval="Agrément de septembre 2020", registration="Référence historique",
            representative="Camille Exemple", jury_representative="Alex Exemple")


@pytest.fixture
def site(tmp_path, monkeypatch):
    path = tmp_path / "data.json"
    training = dict(id="S1", name="Session SSIAP 1", training_type="SSIAP 1", exam_date="2026-09-04",
                    ssiap_exam_number="EX-26-01", archived=True, trainees=[
                        dict(id="T1", first_name="Léa", last_name="TEST", birth_date="1991-04-19",
                             birth_city="Paris", birth_department="75", ssiap_exam_status="certified",
                             ssiap_diploma_number="083-8323-1-2026-00001")])
    path.write_text(json.dumps({"sessions": [training]}))
    monkeypatch.setattr(services, "DATA_FILE", str(path))
    monkeypatch.setattr(services, "PERSIST_DIR", str(tmp_path))
    monkeypatch.setattr(services, "BACKUP_SNAPSHOT_BEFORE_SAVE", False)
    monkeypatch.setattr(services, "_lookup_birth_department_code", lambda city: "")
    client = services.app.test_client()
    with client.session_transaction() as admin:
        admin.update(admin_logged_in=True, admin_role="admin")
    return client, path


def photo(color="teal"):
    stream = io.BytesIO()
    Image.new("RGB", (240, 320), color).save(stream, "PNG")
    stream.seek(0)
    return stream, "portrait.png"


def post_form(client, **changes):
    client.get(ROOT + "/regenerer")
    with client.session_transaction() as admin:
        csrf = admin["ssiap_archive_csrf"]
    return client.post(ROOT + "/regenerer", data={**FORM, "csrf": csrf, "photo": photo(), **changes})


def qr_path(pdf):
    assert pdf.status_code == 200
    reader = PdfReader(io.BytesIO(pdf.data))
    assert "Vérifiez-moi" in reader.pages[0].extract_text()
    with pymupdf.open(stream=pdf.data, filetype="pdf") as doc:
        links = [a["uri"] for a in doc[0].get_links() if a.get("uri") and "/v/ssiap/" in a["uri"]]
    assert len(links) == 1
    return urlsplit(links[0]).path


def test_archival_reissue_and_correction(site):
    admin, path = site
    public = services.app.test_client()
    assert public.get(ROOT).status_code == 302
    response = post_form(admin)
    assert response.status_code == 303
    before = json.loads(path.read_text())
    assert len(before["sessions"]) == 1 and len(before["sessions"][0]["trainees"]) == 1
    key, record = next(iter(before[registry.MANUAL].items()))
    assert record["number"] == FORM["number"]
    assert "Le diplôme est prêt" in admin.get(response.location).text
    archive = ROOT + "/archives/" + key
    pdf = admin.get(archive + "/pdf")
    link = qr_path(pdf)
    assert admin.get("/admin/uploads/" + registry.PRIVATE_KEYS + "/verification.key").status_code == 404
    assert qr_path(admin.get(archive + "/pdf")) == link
    assert not any(value in link for value in ("EXEMPLE", "1990", key, FORM["number"]))
    text = PdfReader(io.BytesIO(pdf.data)).pages[0].extract_text()
    assert all(x in text for x in ("SSIAP 2", "02/09/2022", "16/09/2022", FORM["number"], FORM["approval"]))
    assert "29/05/2026" not in text and "SSIAP 1" not in text
    checked = public.get(link)
    assert checked.status_code == 200
    assert all(x in checked.text for x in ("Diplôme vérifié", "Éva", "EXEMPLE", "12/02/1990", FORM["number"]))
    assert "no-store" in checked.headers["Cache-Control"] and "noindex" in checked.headers["X-Robots-Tag"]
    with admin.session_transaction() as session:
        csrf = session["ssiap_archive_csrf"]
    change = {**FORM, "last_name": "CORRIGÉ", "csrf": csrf, "version": record["version"], "photo": photo("navy")}
    assert admin.post(archive + "/modifier", data=change).status_code == 303
    assert public.get(link).status_code == 404 and "EXEMPLE" not in public.get(link).text
    assert "CORRIGÉ" in public.get(qr_path(admin.get(archive + "/pdf"))).text
    assert admin.post(archive + "/modifier", data={**FORM, "csrf": csrf, "version": record["version"]}).status_code == 409
    assert len(json.loads(path.read_text())[registry.MANUAL]) == 1


def test_session_legacy_pdf_and_withdrawal(site):
    admin, path = site
    assert "Léa" in admin.get(ROOT + "?annee=2026").text
    assert "Léa" not in admin.get(ROOT + "?annee=2022").text
    public = services.app.test_client()
    link = qr_path(admin.get(ROOT + "/pdf/S1/T1"))
    assert "19/04/1991" in public.get(link).text
    assert qr_path(admin.post("/admin/sessions/S1/ssiap-diplomas")) == link
    state = json.loads(path.read_text())
    state["sessions"][0]["trainees"][0]["ssiap_exam_status"] = "failed"
    path.write_text(json.dumps(state))
    assert public.get(link).status_code == 404
    assert "Diplôme vérifié" not in public.get(link).text
    assert admin.get(ROOT + "/pdf/S1/T1").status_code == 404
    assert "Ancienne édition" in admin.get(ROOT).text


def test_duplicates_rights_and_invalid_files(site):
    admin, path = site
    assert post_form(admin, number="083-8323-1-2026-00001").status_code == 400
    assert post_form(admin, photo=(io.BytesIO(b"not an image"), "photo.jpg")).status_code == 400
    assert admin.post(ROOT + "/regenerer", data={"csrf": "wrong"}).status_code == 403
    assert not json.loads(path.read_text()).get(registry.MANUAL)
    assert post_form(admin).status_code == 303
    assert post_form(admin, number=FORM["number"].lower()).status_code == 400
    with admin.session_transaction() as session:
        session["admin_role"] = "viewer"
    assert admin.get(ROOT).status_code == 200
    assert admin.get(ROOT + "/regenerer").status_code == 403
    with admin.session_transaction() as session:
        session.update(admin_role="partner_admin", partner_id="external")
    assert admin.get(ROOT).status_code in (302, 403)
    public = services.app.test_client()
    assert public.get("/v/ssiap/" + "a" * 64).status_code == 404


def test_reserved_reference_not_allocated_in_a_session(site):
    admin, path = site
    assert post_form(admin, number="083-8323-1-2026-00002").status_code == 303
    data = json.loads(path.read_text())
    training = data["sessions"][0]
    training["trainees"].append({**training["trainees"][0], "id": "T2", "ssiap_diploma_number": ""})
    path.write_text(json.dumps(data))
    response = admin.post("/admin/sessions/S1/ssiap-diplomas")
    assert response.status_code == 200
    assert json.loads(response.headers["X-SSIAP-Diploma-Numbers"])["T2"].endswith("00003")


@pytest.mark.parametrize("level", ["SSIAP 2", "SSIAP 3"])
def test_other_levels_have_their_own_number_and_label(site, level):
    admin, path = site
    data = json.loads(path.read_text())
    training = data["sessions"][0]
    training.update(name=level, training_type=level)
    training["trainees"][0].pop("ssiap_diploma_number")
    path.write_text(json.dumps(data))
    pdf = admin.post("/admin/sessions/S1/ssiap-diplomas")
    link = qr_path(pdf)
    assert json.loads(pdf.headers["X-SSIAP-Diploma-Numbers"])["T1"] == f"083-8323-{level[-1]}-2026-00001"
    assert level in services.app.test_client().get(link).text
    assert "SSIAP 1" not in PdfReader(io.BytesIO(pdf.data)).pages[0].extract_text()
