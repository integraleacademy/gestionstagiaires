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
from academy_convocations.source import PORTAL, Source, puget_model


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
        added_page = {"desp": 4, "sst": 3}.get(group)
        if group == "sst":
            source.pages.append(puget_model().pages[-2])
        assert len(book) == len(source.pages) + int(added_page is not None)
        links = {link.get("uri") for page in book for link in page.get_links()}
        assert PORTAL in links
        original_pages = iter(source.pages)
        for i, page in enumerate(book, 1):
            assert page.rect.width > page.rect.height
            assert any(im[2:4] == (2048, 2048) for im in page.get_images())
            if i == added_page:
                assert page.search_for("Sous réserve de modifications.")
                assert page.search_for("Janvier 2027")
                continue
            rows = list(next(original_pages))
            # The approved sidebar uses sentence case, independently of the source Word's capitals.
            if i > 1 and rows[1].casefold() in {
                "documents administratifs",
                "règles de vie en formation",
                "distanciel & présentiel",
                "convocation officielle en formation",
                "convocation officielle à l’examen",
            }:
                rows[1] = rows[1].capitalize()
            expected = [
                *source.header,
                *source.footer_contact,
                f"{i}/{len(book)}",
                *source.legal,
                *rows,
            ]
            printed = "".join(page.get_text().split())
            if (group == "aps" and i == 4) or (added_page and i == 1):
                # The calendar adds the names of the months and the individual days.
                offset = 0
                for original_field in expected:
                    needle = "".join(original_field.split())
                    offset = printed.index(needle, offset) + len(needle)
            else:
                assert "".join("".join(expected).split()) == printed
        assert "Alix & Lou EXEMPLE" in book[0].get_text()
        fill = book[1].get_drawings()[1]["fill"]
        assert (
            bytes(round(value * 255) for value in fill).hex()
            == PALETTES[group][0][1:].lower()
        )
        if group == "desp":
            assert len(book) == 8
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


def test_aps_cover_uses_session_phases_and_both_letters_sign_below_the_director(
    tmp_path, monkeypatch
):
    # The phase dates deliberately differ from those of the January reference.
    session = dict(
        id="sample-september",
        name="APS septembre",
        training_type="APS",
        date_start="2027-09-01",
        date_end="2027-10-05",
        exam_date="2027-10-06",
        aps_remote_start="2027-09-01",
        aps_remote_end="2027-09-13",
        aps_in_person_start="2027-09-15",
        aps_in_person_end="2027-10-05",
        convocation_time="09h15",
        exam_time="08h45",
    )
    trainee = dict(
        id="sample",
        first_name="Camille",
        last_name="Exemple",
        email="test@example.invalid",
    )
    monkeypatch.setattr(app, "APS_CONVOCATION_DIR", str(tmp_path))
    with app.app.test_request_context("/"):
        editable, path = app._generate_aps_convocation_files(session, trainee)
    word = Document(editable)
    assert word.element.xpath('.//w:hyperlink[@w:anchor="Page8"]')
    assert word.element.xpath('.//w:hyperlink[@w:anchor="Page4"]')
    with pymupdf.open(path) as pdf:
        assert len(pdf) == 8
        cover = pdf[0].get_text()
        expected = [
            "Du 1er au 13 septembre 2027",
            "Du 15 septembre au 5 octobre 2027",
            "Le 6 octobre 2027 à 08h45",
            "01/09/2027 à 09h15",
        ]
        assert all(value in cover for value in expected)
        assert "01/09/2027 à 09h15" in pdf[1].get_text()
        assert "06/10/2027 à 08h45" in pdf[4].get_text()
        for value in (
            "Septembre 2027",
            "Octobre 2027",
            "Sous réserve de modifications.",
            "01/09/2027 à 09h15",
            "06/10/2027 à 08h45",
        ):
            assert pdf[3].search_for(value)
        assert any(link.get("page") in (7, "8") for link in pdf[0].get_links())
        for page in (pdf[0], pdf[2]):
            assert any(link.get("page") in (3, "4") for link in page.get_links())
        for page in (pdf[1], pdf[4]):
            (role,) = page.search_for("Directeur général Intégrale Academy")
            seals = [
                pymupdf.Rect(im["bbox"])
                for im in page.get_image_info()
                if (im["width"], im["height"]) in [(283, 158), (469, 159)]
            ]
            assert len(seals) == 2
            for seal in seals:
                assert role.y1 < seal.y0 < seal.y1 < page.rect.height - 60
                assert role.x0 - 1 <= seal.x0 < role.x1
        access = pdf[-1]
        for label in [
            "P1",
            "Parking principal",
            "P2",
            "Parking secondaire",
            "P3",
            "Parking public",
            "P4",
            "aux formateurs",
            "aux PMR",
        ]:
            assert access.search_for(label)
        links = {link.get("uri", "") for link in access.get_links()}
        assert any("54+chemin+du+Carreou" in link for link in links)
        assert any(link.endswith("/parking-puget.svg") for link in links)
        assert not any(
            (im["width"], im["height"]) == (1385, 779) for im in access.get_image_info()
        )
