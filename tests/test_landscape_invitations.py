"""Check the published stationery through the same generator as the trainee portal."""

from pathlib import Path
from zipfile import ZipFile

import pymupdf
import pytest
from docx import Document
from docxtpl import DocxTemplate

import app
from academy_convocations import family
from academy_convocations.drawing import PALETTES
from academy_convocations.source import PORTAL, Source


@pytest.mark.parametrize(
    "name,group",
    [
        ("Dirigeant DESP", "desp"),
        ("DESP VAE", "vae"),
        ("VTC", "vtc"),
        ("APS", "aps"),
        ("AFC APS SSIAP", "aps"),
        ("A3P", "a3p"),
        ("SSIAP 3", "ssiap"),
        ("MAC SST", "sst"),
        ("MAC APS", "mac_aps"),
        ("Habilitation électrique H0B0", "habilitation"),
    ],
)
def test_course_palette(name, group):
    assert family(name) == group


@pytest.mark.parametrize(
    "course,title,group",
    [
        ("DIRIGEANT initial", "DESP Paris", "desp"),
        ("APS", "APS", "aps"),
        ("SST", "Sauveteur secouriste du travail", "sst"),
    ],
)
def test_published_pair_keeps_the_source_text_and_course_color(
    tmp_path, monkeypatch, course, title, group
):
    session = dict(
        id="invitation-sample",
        name=title,
        training_type=course,
        date_start="2027-01-04",
        date_end="2027-02-18",
        exam_date="2027-02-19",
        dirigeant_remote_start="2027-01-04",
        dirigeant_remote_end="2027-02-05",
        dirigeant_in_person_start="2027-02-08",
        dirigeant_in_person_end="2027-02-18",
    )
    trainee = dict(
        id="candidate",
        first_name="Alix & Lou",
        last_name="Exemple",
        email="candidate@example.invalid",
        city="Paris",
        zip_code="75002",
    )
    monkeypatch.setattr(app, "APS_CONVOCATION_DIR", str(tmp_path))
    with app.app.test_request_context("/"):
        docx, pdf = app._generate_aps_convocation_files(session, trainee)
        context = app._build_aps_convocation_context(session, trainee)
        path = app._ssiap_document_template(
            session, trainee, "convocation", app._aps_template_path
        )
    template = DocxTemplate(path)
    template.render(context, autoescape=True)
    original = tmp_path / "source.docx"
    template.save(original)
    source = Source(Document(original))

    with pymupdf.open(pdf) as book:
        assert len(book) == len(source.pages)
        links = {link.get("uri") for page in book for link in page.get_links()}
        assert PORTAL in links
        for i, (page, rows) in enumerate(zip(book, source.pages), 1):
            assert page.rect.width > page.rect.height
            assert any(im[2:4] == (2048, 2048) for im in page.get_images())
            expected = [
                *source.header,
                *source.footer_contact,
                f"{i}/{len(book)}",
                *source.legal,
                *rows,
            ]
            assert "".join("".join(expected).split()) == "".join(
                page.get_text().split()
            )
        assert "Alix & Lou EXEMPLE" in book[0].get_text()
        fill = book[1].get_drawings()[1]["fill"]
        assert (
            bytes(round(value * 255) for value in fill).hex()
            == PALETTES[group][0][1:].lower()
        )
        if group == "desp":
            assert len(book) == 7
            assert any(link and "google.com/maps/dir/" in link for link in links)
            assert "Poissonnière" in book[-1].get_text()
    word = Document(docx)
    assert word.sections[0].page_width > word.sections[0].page_height
    assert word.element.xpath(".//w:framePr") and word.element.xpath(".//w:hyperlink")
    with ZipFile(Path(docx)) as archive:
        assert (
            len([part for part in archive.namelist() if part.endswith(".odttf")]) == 3
        )


def test_generic_invitation_does_not_start_other_automations():
    course = {"training_type": "SST", "name": "Formation SST"}
    config = app._automation_document_config(course)
    assert config["manual_invitation"] and config["convocation_only"]
    assert not config["enabled"]
    assert not app._convention_triggers_convocation(course)
