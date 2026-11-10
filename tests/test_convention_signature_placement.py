"""Signatures must stay below the label and wholly inside the blank table cell."""
from pathlib import Path
import shutil
import subprocess

from docx import Document
import fitz
import pytest
from reportlab.pdfgen.canvas import Canvas

import app as host
from convention_design import style_document

ROOT = Path(__file__).resolve().parents[1]


def test_convention_moves_field_below_label_without_changing_foad_detector(tmp_path):
    source = tmp_path / "contract.pdf"
    c = Canvas(str(source), pagesize=(595, 842))
    c.drawString(60, 520, "Signature")
    c.drawString(60, 490, "{{s1|signature|160|60}}")
    c.save()
    original = source.read_bytes()
    old = host._detect_yousign_pdf_anchors(str(source))[0]
    clean, fields = host._prepare_yousign_pdf_and_fields(str(source))
    field = fields[0]
    with fitz.open(clean) as pdf:
        label = pdf[0].search_for("Signature")[0]
        assert field["y"] > label.y1 + 5
        assert old["y"] < label.y1  # Reproduces the overlap before the fix.
        assert field["height"] == 80
    assert source.read_bytes() == original
    assert host._detect_yousign_pdf_anchors(str(source))[0] == old


@pytest.mark.parametrize("model", sorted((ROOT / "templates_word").glob("convention*.docx")),
                         ids=lambda p: p.stem)
def test_real_convention_signature_cells(model, tmp_path):
    binary = shutil.which("libreoffice") or shutil.which("soffice")
    if not binary:
        pytest.skip("LibreOffice is required to verify the real Word/PDF layout")
    target = tmp_path / "contract.docx"
    style_document(Document(model)).save(target)
    subprocess.run([binary, "-env:UserInstallation=" + (tmp_path / "profile").as_uri(),
                    "--headless", "--convert-to", "pdf", "--outdir", str(tmp_path), str(target)],
                   check=True, capture_output=True, timeout=90)
    clean, fields = host._prepare_yousign_pdf_and_fields(str(target.with_suffix(".pdf")))
    assert fields
    with fitz.open(clean) as pdf:
        for field in fields:
            if field["type"] != "signature":
                continue
            page = pdf[field["page"] - 1]
            box = fitz.Rect(field["x"], field["y"], field["x"] + field["width"], field["y"] + field["height"])
            cells = [drawing["rect"] for drawing in page.get_drawings()
                     if drawing["type"] == "f" and 200 < drawing["rect"].width < 300
                     and drawing["rect"].contains(box)]
            assert cells, (model.name, field)
            cell = min(cells, key=lambda rect: rect.height)
            assert box.y1 < cell.y1 - 2
            labels = [fitz.Rect(word[:4]) for word in page.get_text("words")
                      if word[4].casefold() == "signature" and cell.contains(fitz.Rect(word[:4]))]
            assert labels and all(box.y0 > rect.y1 + 5 for rect in labels)
            visible_text = host.YOUSIGN_TECHNICAL_ANCHOR_PATTERN.sub("", page.get_text(clip=box))
            assert not visible_text.strip(), "The signature must not overlap printed text"


def test_signature_row_reserves_space_even_when_blank_lines_collapse(tmp_path):
    binary = shutil.which('libreoffice') or shutil.which('soffice')
    if not binary:
        pytest.skip('LibreOffice is required to verify the Word/PDF layout')
    document = Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = 'Pour le stagiaire'
    table.cell(0, 1).text = 'Pour l’organisme de formation'
    signer = table.cell(1, 0)
    signer.text = 'Signature'
    signer.add_paragraph('{{s1|signature|160|60}}')
    target = tmp_path / 'compact.docx'
    style_document(document).save(target)
    subprocess.run([binary, '-env:UserInstallation=' + (tmp_path / 'profile').as_uri(),
                    '--headless', '--convert-to', 'pdf', '--outdir', str(tmp_path), str(target)],
                   check=True, capture_output=True, timeout=90)
    source = target.with_suffix('.pdf')
    _, (field,) = host._prepare_yousign_pdf_and_fields(str(source))
    with fitz.open(source) as pdf:
        page = pdf[field['page'] - 1]
        label, = [fitz.Rect(word[:4]) for word in page.get_text('words') if word[4] == 'Signature']
        seal = fitz.Rect(field['x'], field['y'], field['x'] + field['width'], field['y'] + field['height'])
        assert seal.height >= 80 and seal.y0 > label.y1 + 5
        assert any(d['type'] == 'f' and 200 < d['rect'].width < 300 and d['rect'].contains(label)
                   and d['rect'].contains(seal) and d['rect'].y1 >= seal.y1 + 4 for d in page.get_drawings())
