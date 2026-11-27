import copy
from pathlib import Path

import pymupdf
import pytest
from docx import Document

import app


CANDIDATE = dict(id="sample", first_name="Camille", last_name="Exemple", email="camille@example.test",
                 training_price="3900", cpf_amount="3500", personal_amount="400")
SESSION = dict(date_start="2027-04-19", date_end="2027-06-02", exam_date="2027-06-03",
               crm_center="Puget-sur-Argens")


@pytest.mark.parametrize("kind,name,settings,hours,qualification", [
    ("SSIAP 3", "Avril", {}, "216", "Chef de service"),
    ("SSIAP", "SSIAP-3 avril", {"ssiap_pathways": {"ssiap_hours": "70"}}, "216", "Chef de service"),
    ("SSIAP 2", "Avril", {}, "70", "Chef d’équipe"),
])
def test_contract_includes_the_right_syllabus_and_financing(tmp_path, kind, name, settings, hours, qualification):
    session = dict(SESSION, training_type=kind, name=name, **settings)
    source = app._ssiap_document_template(session, CANDIDATE, "convention", app._aps_convention_template_path)
    destination = tmp_path / Path(source).name
    destination.write_bytes(Path(source).read_bytes())
    values = app._aps_convention_replacements(session, CANDIDATE)
    app._replace_docx_xml_placeholders(str(destination), values)
    body = " ".join(Document(destination).element.body.xpath(".//w:t/text()"))
    assert qualification in body and f"{hours} heures" in body
    assert "03/06/2027" in body and "SSIAP 1" not in body
    assert ("notice technique" if hours == "216" else "séquence pédagogique") in body
    assert values["montant_formation"] == "3900" and values["montant_cpf"] == "3500"
    assert values["montant_financement_personnel"] == "400"
    assert app._assert_aps_convention_has_no_business_placeholders(str(destination))[1]


@pytest.mark.parametrize("course,details,expected", [
    ("APS", {}, [("APS", "03/06/2027")]),
    ("SSIAP 1", {}, [("SSIAP 1", "03/06/2027")]),
    ("SSIAP 2", {}, [("SSIAP 2", "03/06/2027")]),
    ("SSIAP 3", {"ssiap_exam_date": "2027-06-04"}, [("SSIAP 3", "04/06/2027")]),
    ("APS + SSIAP 1", {"ssiap_exam_date": "2027-06-09"}, [("APS", "03/06/2027"), ("SSIAP 1", "09/06/2027")]),
    ("AFC APS + SSIAP 1", {"afc_enabled": True, "ssiap_exam_date": "2027-06-09"},
     [("APS", "03/06/2027"), ("SSIAP 1", "09/06/2027")]),
    ("Recyclage SSIAP 1", {}, []),
])
def test_each_exam_has_its_own_personal_letter(tmp_path, monkeypatch, course, details, expected):
    monkeypatch.setattr(app, "APS_CONVOCATION_DIR", str(tmp_path))
    session = dict(SESSION, training_type=course, name=course, **details)
    with app.app.test_request_context("/"):
        editable, pdf = app._generate_aps_convocation_files(session, copy.deepcopy(CANDIDATE))
    with pymupdf.open(pdf) as book:
        pages = [" ".join(p.get_text().split()) for p in book]
    letters = [page for page in pages if "convocation officielle à l’examen" in page.lower()]
    assert len(letters) == len(expected)
    for letter, (exam, date) in zip(letters, expected):
        assert exam in letter and date in letter and "Camille EXEMPLE" in letter
        assert all(other not in letter for _, other in expected if other != date)
    assert len(Document(editable).element.xpath(".//w:framePr")) > 0


def test_unknown_exam_details_and_cma_are_never_guessed():
    session = dict(SESSION, training_type="SSIAP 3", name="SSIAP 3", exam_date="")
    letter, = app._build_aps_convocation_context(session, CANDIDATE)["convocations_examens"]
    assert not letter["day"] and not letter["time"]
    session.update(training_type="VTC", name="VTC", exam_theory_date="2027-05-19")
    rows = app._build_aps_convocation_context(session, {**CANDIDATE, "vtc_offer": "practice"})["convocations_examens"]
    assert len(rows) == 1 and rows[0]["kind"] == "cma" and not rows[0]["day"]
