"""Shared practical pages in the actual trainee PDFs and their editable counterparts."""

import re
from collections import Counter
from pathlib import Path

import pymupdf
import pytest
from docx import Document
from docxtpl import DocxTemplate

import app
from academy_convocations.source import Source


def words(text):
    return Counter(re.findall(r"[^\W_]+", text.casefold()))


def body_text(page):
    return page.get_text(clip=pymupdf.Rect(210, 0, 820, 534))


@pytest.mark.parametrize(
    "course,name",
    [
        ("A3P", "A3P"),
        ("DIRIGEANT initial", "DESP Paris"),
        ("VTC", "VTC"),
        ("SSIAP 1", "SSIAP 1"),
        ("MAC APS", "MAC APS"),
        ("DIRIGEANT VAE", "VAE"),
    ],
)
def test_all_training_rules_follow_aps_geometry_and_keep_local_wording(
    tmp_path, monkeypatch, course, name
):
    session = {
        "id": "reference",
        "training_type": course,
        "name": name,
        "date_start": "2027-03-08",
        "date_end": "2027-05-06",
        "exam_date": "2027-05-07",
        "practice_training_date": "2027-04-05",
    }
    student = {
        "id": "reference-trainee",
        "first_name": "Claire",
        "last_name": "Exemple",
        "email": "specimen@example.invalid",
    }
    monkeypatch.setattr(app, "APS_CONVOCATION_DIR", str(tmp_path))
    with app.app.test_request_context("/"):
        docx, pdf = app._generate_aps_convocation_files(session, student)
        context = app._build_aps_convocation_context(session, student)
        path = app._ssiap_document_template(
            session, student, "convocation", app._aps_template_path
        )
    template = DocxTemplate(path)
    template.render(context, autoescape=True)
    raw = tmp_path / "original.docx"
    template.save(raw)
    model = Source(Document(raw))
    target = "Règles de vie en formation"
    original_rules = next(
        (r for r in model.pages if r[1].casefold() == target.casefold()), None
    )
    if original_rules is None:
        original_rules = Source(
            Document(Path(app.app.root_path) / "templates_word/convocationaps.docx")
        ).pages[-2]

    with pymupdf.open(pdf) as book:
        (rules,) = [p for p in book if p.search_for("ATTITUDE & RESPECT")]
        labels = [
            "ATTITUDE & RESPECT",
            "TENUE ADAPTÉE EN COURS",
            "LOCAUX & MATÉRIEL",
            "Règles complémentaires",
        ]
        boxes = [rules.search_for(label)[0] for label in labels]
        for rect, (x, y) in zip(
            boxes, [(245, 104), (557.5, 104), (245, 244), (557.5, 244)]
        ):
            assert rect.x0 == pytest.approx(x, abs=0.5) and rect.y0 == pytest.approx(
                y, abs=0.5
            )
        assert words(body_text(rules)) == words(" ".join(original_rules[2:]))
        assert all(
            "Les journées de présence figurent" not in p.get_text() for p in book
        )
        if course == "A3P":
            for original_page, heading in zip(
                model.pages[5:9],
                [
                    "Hébergement sur place",
                    "Règles à respecter",
                    "Services sur place & à proximité",
                    "À prévoir pour votre formation",
                ],
            ):
                page_no = next(n for _, title, n in book.get_toc() if title == heading)
                assert words(body_text(book[page_no - 1])) == words(
                    " ".join(original_page[2:])
                )
        else:
            assert not any(p.search_for("dortoir collectif") for p in book)
    editable = " ".join(Document(docx).element.xpath(".//w:t/text()"))
    assert "Les journées de présence figurent" not in editable
    assert all(label in editable for label in labels)
