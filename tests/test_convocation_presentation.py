"""Every published invitation must provide the same public trainee entrance."""
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm
from lxml import etree

import app
from training_convocations import PORTAL_URL


TEMPLATES = Path(app.app.root_path) / "templates_word"


@pytest.mark.parametrize("template", sorted(TEMPLATES.glob("convocation*.docx")), ids=lambda path: path.stem)
def test_official_logo_repeats_in_the_header_of_every_invitation(template):
    doc = Document(template)
    assert not doc.settings.odd_and_even_pages_header_footer
    for section in doc.sections:
        assert not section.different_first_page_header_footer
        header = section.header
        drawing, = header._element.xpath('.//wp:inline[wp:docPr[@descr="Logo officiel Intégrale Academy"]]')
        assert int(drawing.xpath('./wp:extent')[0].get('cx')) >= Cm(4)
        reference = drawing.xpath('.//a:blip')[0].get(qn('r:embed'))
        assert header.part.related_parts[reference].content_type == 'image/png'


def test_both_paris_letters_print_the_current_stamp():
    doc = Document(TEMPLATES / 'convocationdespparis_2027.docx')
    stamp = (TEMPLATES.parent / 'static/images/convocations/cachet-paris-2027.png').read_bytes()
    drawings = doc.element.xpath('.//wp:inline[wp:docPr[contains(@descr, "Cachet Intégrale Academy Paris")]]')
    assert len(drawings) == 2
    for drawing in drawings:
        ref = drawing.xpath('.//a:blip')[0].get(qn('r:embed'))
        assert doc.part.related_parts[ref].blob == stamp


@pytest.mark.parametrize("template", sorted(TEMPLATES.glob("convocation*.docx")), ids=lambda path: path.stem)
def test_portal_address_is_printed_and_clickable_in_every_word_invitation(template):
    with ZipFile(template) as archive:
        body = etree.fromstring(archive.read("word/document.xml"))
        metadata = etree.fromstring(archive.read("word/_rels/document.xml.rels"))
        text = "".join(body.itertext())
        targets = {rel.get("Id"): rel.get("Target") for rel in metadata}
        links = body.xpath("//*[local-name()='hyperlink']")
        assert any(PORTAL_URL in "".join(link.itertext())
                   and targets.get(link.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")) == PORTAL_URL
                   for link in links)
        assert "gestionstagiaires-r5no.onrender.com/espacestagiaire" not in text + str(targets.values())
        if template.name == "convocationdespparis_2027.docx":
            assert "acces_entrance" not in text and "Bâtiment B" not in text and "1er étage" not in text


def test_email_and_personalized_pdf_use_the_public_entrance_in_an_admin_preview():
    training = dict(training_type="APS", name="APS", date_start="2027-01-04",
                    date_end="2027-02-11", exam_date="2027-02-12")
    trainee = dict(first_name="Camille", last_name="Exemple", email="camille@example.test",
                   public_token="demo-private-token")
    with app.app.test_request_context("/admin/sessions"):
        context = app._build_aps_convocation_context(training, trainee)
        _, message = app._build_aps_convocation_email("Camille", session_obj=training, trainee=trainee)
    assert context["espace_stagiaire_url"] == PORTAL_URL
    assert f'href="{PORTAL_URL}"' in message
