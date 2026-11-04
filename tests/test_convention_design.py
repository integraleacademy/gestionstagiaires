"""Legal wording, artwork, amounts and signing markers must survive restyling."""
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from lxml import etree

import pytest
from docx import Document

from convention_design import style_document, document_reference, REGISTRATION_LINES
from docx.oxml.ns import qn
import company_convention

ROOT = Path(__file__).resolve().parents[1]
MODELS = sorted((ROOT / 'templates_word').glob('convention*.docx'))


def content_snapshot(data):
    with ZipFile(BytesIO(data)) as package:
        result = {}
        for name in package.namelist():
            if name == 'word/document.xml':
                root = etree.fromstring(package.read(name))
                result[name] = [(etree.QName(n).localname, n.text, sorted(n.attrib.items()))
                                for n in root.iter() if etree.QName(n).localname in
                                {'t', 'instrText', 'fldChar', 'blip', 'imagedata', 'hyperlink'}]
        # Only the banner is replaced; every picture used by the contractual
        # body (including the Academy's signature) must remain byte-identical.
        root = etree.fromstring(package.read('word/document.xml'))
        ids = set(root.xpath('//@r:embed | //@r:id', namespaces={'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}))
        rels = etree.fromstring(package.read('word/_rels/document.xml.rels'))
        for rel in rels:
            if rel.get('Id') in ids and not rel.get('Type').endswith(('/header', '/footer')):
                target = rel.get('Target')
                result['relationship:' + rel.get('Id')] = target
                if target.startswith('media/'):
                    result[target] = package.read('word/' + target)
        return result


def as_bytes(doc):
    out = BytesIO(); doc.save(out); return out.getvalue()


@pytest.mark.parametrize('model', MODELS, ids=lambda p: p.stem)
def test_all_individual_models_keep_exact_text_fields_links_and_artwork(model):
    original = model.read_bytes()
    doc = Document(BytesIO(original))
    baseline = content_snapshot(as_bytes(doc))
    style_document(doc)
    assert content_snapshot(as_bytes(doc)) == baseline
    assert model.read_bytes() == original
    section = doc.sections[0]
    assert round(section.page_width.cm, 1) == 21
    assert round(section.page_height.cm, 1) == 29.7
    footer = '\n'.join(p.text for p in section.footer.paragraphs)
    for line in REGISTRATION_LINES:
        assert line in footer
    if model.stem == 'conventiondespparis':
        assert '840 899 884 00034' in footer
        assert '142 rue de Rivoli' in footer
        assert '840 899 884 00026' not in footer
    headings = [p for p in doc.paragraphs if p.text.startswith('Article ')]
    assert headings[0].paragraph_format.page_break_before
    assert {r.font.size.pt for p in headings for r in p.runs if r.text.strip()} == {11.5}
    for p in headings:
        if 'Garanties disciplinaires' in p.text:
            assert p.paragraph_format.keep_with_next  # Parent heading stays with Article 13.1.
    for p in doc.paragraphs:
        if p.text.startswith(('(Articles', 'RÈGLEMENT INTÉRIEUR')):
            assert p.alignment == 1  # Centred, including the legal subtitle.
    available = section.page_width - section.left_margin - section.right_margin
    for table in doc.tables:
        assert sum(c.width for c in table.columns) <= available + 10000


@pytest.mark.parametrize('model', [p for p in MODELS if p.stem not in {'conventionvae', 'conventionafc'}], ids=lambda p: p.stem)
def test_employer_clauses_and_signature_artwork_are_unchanged(model):
    company = dict(name='Société Exemple', address='12 avenue des Entreprises, Puget-sur-Argens',
                   representative='Camille Exemple, directrice', remote_rate='35,43', payment='Virement à réception.')
    values = dict(nom_complet='MARTIN Alex', date_jour='04/11/2026', lieu_formation='Puget-sur-Argens')
    doc = company_convention.build_document(model, company, values)
    before = content_snapshot(as_bytes(doc))
    style_document(doc)
    assert content_snapshot(as_bytes(doc)) == before


def test_apprenticeship_text_financial_values_and_signature_markers_are_unchanged():
    import bts_contract_documents as bts
    from tests.test_bts_contracts import assets, settings
    from tests.test_bts_cerfa import complete_values
    values = complete_values()
    values.update(cfa_siret='84089988400026', cfa_uai='0831774C')
    with patch.object(bts, 'style_document'):
        before = bts.fill_convention('formation', values, settings(values), assets())
    after = bts.fill_convention('formation', values, settings(values), assets())
    assert content_snapshot(after) == content_snapshot(before)


def test_financial_colours_and_separate_article_survive_layout():
    doc = style_document(Document(ROOT / 'templates_word/conventionaps.docx'))
    financing = next(t for t in doc.tables if t.cell(0, 0).text.startswith('CPF mobilisé'))
    fills = [row.cells[0]._tc.get_or_add_tcPr().find(qn('w:shd')).get(qn('w:fill'))
             for row in financing.rows]
    assert fills == ['E8F5EE', 'F3EEFC', 'FFF5DA']
    assert any(p.text == 'Article 9 - Interruption de stage' for p in doc.paragraphs)
    assert not any(p.text.startswith('*') and 'Article 9 -' in p.text for p in doc.paragraphs)
    engagement = next(t for t in doc.tables if t.cell(0, 0).text.startswith('Engagement du stagiaire'))
    assert engagement.cell(0, 0)._tc.get_or_add_tcPr().find(qn('w:shd')).get(qn('w:fill')) == 'FFF5DA'
    assert any(str(r.font.color.rgb) == 'B42318' and '5 jours' in r.text
               for p in engagement.cell(0, 0).paragraphs for r in p.runs)


def test_reference_survives_regeneration_and_distinguishes_contracts():
    def header(key, new_date):
        doc = Document(ROOT / 'templates_word/conventionssiap.docx')
        doc.add_paragraph(new_date)
        style_document(doc, reference_key=key)
        return '\n'.join(doc.sections[0].header._element.xpath('.//w:t/text()'))
    key = ('session-1', 'stagiaire-1', 'conventionssiap.docx')
    ref = document_reference('contrat', key)
    assert ref in header(key, '04/11/2026')
    assert ref in header(key, '05/11/2026')
    assert ref not in header(('session-2', *key[1:]), '04/11/2026')
    assert ref not in header((key[0], 'stagiaire-2', key[2]), '04/11/2026')
    assert document_reference('convention', key) != ref
