"""A date printed somewhere on the cover is insufficient: it belongs in its APS row."""

import pymupdf
import pytest
from docx import Document

import app
from academy_convocations.agenda import desp_periods
from academy_convocations.source import PORTAL


STUDENT = dict(id="specimen", first_name="Camille", last_name="Exemple",
               email="exemple@example.invalid")


def render(tmp_path, monkeypatch, training, student=STUDENT):
    monkeypatch.setattr(app, "APS_CONVOCATION_DIR", str(tmp_path))
    with app.app.test_request_context("/"):
        return app._generate_aps_convocation_files(training, student)


def assert_row(page, value, x, y, size):
    spans = [span for block in page.get_text("dict")["blocks"]
             for line in block.get("lines", []) for span in line["spans"] if span["text"] == value]
    assert len(spans) == 1, value
    actual = spans[0]
    assert actual["bbox"][:2] == pytest.approx((x, y), abs=1)
    assert actual["size"] == pytest.approx(size, abs=.1)


@pytest.mark.parametrize("city,year,venue", [
    ("Paris", 2027, "34 rue Poissonnière"),
    ("Puget-sur-Argens", 2027, "54 chemin du Carreou"),
    ("Paris", 2026, "53 rue des Vinaigriers"),
])
def test_initial_courses_show_actual_phases_at_aps_coordinates_in_pdf_and_word(
    tmp_path, monkeypatch, city, year, venue
):
    training = dict(id="course", training_type="DIRIGEANT initial", name=f"DESP {city}",
                    date_start=f"{year}-04-05", date_end=f"{year}-05-20", exam_date=f"{year}-05-21",
                    dirigeant_remote_start=f"{year}-04-05", dirigeant_remote_end=f"{year}-05-07",
                    dirigeant_in_person_start=f"{year}-05-10", dirigeant_in_person_end=f"{year}-05-20",
                    convocation_time="09h15", exam_time="08h45")
    docx, pdf = render(tmp_path, monkeypatch, training)
    dates = (f"Du 5 avril au 7 mai {year}", f"Du 10 au 20 mai {year}", f"Le 21 mai {year} à 08h45")
    with pymupdf.open(pdf) as book:
        cover = book[0]
        assert_row(cover, "Vos dates de formation", 455, 55, 31)
        for n, (label, value) in enumerate(zip(
            ["Formation à distance", f"Au centre de formation à {city}", "Examen DESP"], dates
        )):
            assert_row(cover, label, 499, 113 + n * 81, 12)
            assert_row(cover, value, 499, 133 + n * 81, 25)
        assert cover.search_for(venue)[0].y0 > 400
        assert cover.search_for(f"05/04/{year} à 09h15")[0].x0 < 100
        assert cover.search_for("Zoom" if city == "Paris" else "Accueil au centre")
        assert any(link.get("uri") == PORTAL for link in cover.get_links())
        assert book[1].search_for(f"05/04/{year} à 09h15")
        assert book[3].search_for(f"21/05/{year} · 08h45")
        assert book[4].search_for(f"21/05/{year} à 08h45")
        pages = len(book)
    word = Document(docx)
    for text in dates:
        assert text in word.element.xpath(".//w:t/text()")
    for target in (4, pages):
        assert word.element.xpath(f'.//w:hyperlink[@w:anchor="Page{target}"]')


@pytest.mark.parametrize("jury", ["2027-05-21", ""])
def test_vae_cover_shows_its_own_milestones(tmp_path, monkeypatch, jury):
    session = dict(id="vae", training_type="DIRIGEANT VAE", name="Accompagnement VAE",
                   date_start="2027-04-05", date_end="2027-05-20", exam_date=jury)
    _, pdf = render(tmp_path, monkeypatch, session)
    with pymupdf.open(pdf) as book:
        cover = book[0]
        assert_row(cover, "Période d’accompagnement VAE", 499, 113, 12)
        assert_row(cover, "Du 5 avril au 20 mai 2027", 499, 133, 25)
        assert bool(cover.search_for("Jury VAE")) is bool(jury)
        if jury:
            assert_row(cover, "Le 21 mai 2027", 499, 214, 25)
        assert not cover.search_for("Examen DESP")


def test_partial_or_historical_dates_keep_only_known_boundaries():
    session = dict(dirigeant_remote_end="18/04/2027", dirigeant_in_person_start="10/05/2027")
    assert desp_periods(session, "05/04/2027", "20/05/2027") == (
        ("2027-04-05", "2027-04-18"), ("2027-05-10", "2027-05-20"))
    session = dict(dirigeant_remote_start="2027-04-05", dirigeant_in_person_end="2027-05-20")
    assert desp_periods(session, "2027-04-05", "2027-05-20") == (
        ("2027-04-05", ""), ("", "2027-05-20"))
    assert desp_periods({"dirigeant_remote_end": "2027-03-01"}, "2027-04-05", "2027-05-20") == (
        ("", ""), ("", ""))
