from datetime import date
from pathlib import Path

import pymupdf
import pytest
from docx import Document
from academy_convocations.agenda import Agenda, entries
from academy_convocations.aps_calendar import CENTRE, EXAM, OFF
from academy_convocations.source import Source

import app


def test_maintenance_dates_and_optional_jury():
    data = {
        "maintien_ssiap": True,
        "parcours_label": "Recyclage SSIAP 1",
        "dates_parcours": "05/04/2027, 08/04/2027",
    }
    agenda = Agenda(entries({}, {}, data, "ssiap"))
    assert agenda.color(date(2027, 4, 5)) == CENTRE
    assert agenda.color(date(2027, 4, 6)) == OFF
    assert agenda.color(date(2027, 4, 8)) == CENTRE
    vae = entries(
        {},
        {},
        {"date_debut_formation": "05/04/2027", "date_fin_formation": "06/05/2027"},
        "vae",
    )
    assert [r["kind"] for r in vae] == ["period"]


def test_vtc_two_formulas_and_individual_exam():
    training = {
        "date_examen_theorique": "2027-01-26",
        "practice_training_date": "2027-02-15",
        "exam_practice_date": "2027-02-22",
    }
    context = {
        "date_formation_pratique": "16/02/2027",
        "heure_formation_pratique": "09h00",
        "heure_fin_formation_pratique": "12h00",
        "mention_groupe_pratique": "Groupe 2",
    }
    full = entries(training, {}, context, "vtc")
    assert {day for row in full for day in row["days"]} == {
        "2027-01-26",
        "2027-02-16",
        "2027-02-22",
    }
    practice = entries(
        training,
        {"vtc_offer": "practice", "vtc_practice_exam_date": "2027-02-23"},
        context,
        "vtc",
    )
    agenda = Agenda(practice)
    assert agenda.color(date(2027, 1, 26)) == OFF
    assert agenda.color(date(2027, 2, 16)) == CENTRE
    assert agenda.color(date(2027, 2, 22)) == OFF
    assert agenda.color(date(2027, 2, 23)) == EXAM


@pytest.mark.parametrize(
    "filename",
    sorted((Path(app.app.root_path) / "templates_word").glob("convocation*.docx")),
)
def test_model_certification_and_signer(filename):
    source = Source(Document(filename))
    assert "faire valider les acquis de l’expérience (VAE)" in source.legal[-1]
    assert any(
        b.pictures
        for section in source.blocks
        for b in section
        if any("Directeur général" in line for line in b.text)
    )


def test_vae_calendar_and_signature_below_name_are_present_in_word_and_pdf(
    tmp_path, monkeypatch
):
    training = dict(
        id="session",
        name="Accompagnement VAE",
        training_type="DIRIGEANT VAE",
        date_start="2027-05-03",
        date_end="2027-06-18",
        training_location="34 rue Poissonnière, 75002 Paris",
    )
    student = dict(
        id="demo",
        first_name="Camille",
        last_name="Exemple",
        email="exemple@example.invalid",
    )
    monkeypatch.setattr(app, "APS_CONVOCATION_DIR", str(tmp_path))
    with app.app.test_request_context("/"):
        doc, pdf = app._generate_aps_convocation_files(training, student)
    word = Document(doc)
    assert word.element.xpath('.//w:hyperlink[@w:anchor="Page3"]')
    with pymupdf.open(pdf) as book:
        assert (
            len(book) == 3
            and book[2].search_for("Mai 2027")
            and book[2].search_for("Juin 2027")
        )
        assert all(page.search_for("(VAE)") for page in book)
        role = book[1].search_for("Directeur général Intégrale Academy")[0]
        pen = next(
            i
            for i in book[1].get_image_info()
            if (i["width"], i["height"]) == (283, 158)
        )
        bbox = pymupdf.Rect(pen["bbox"])
        assert (
            75 <= bbox.width <= 82 and bbox.y0 > role.y1 and abs(bbox.x0 - role.x0) < 2
        )
        assert not book[2].search_for("Jury VAE")
