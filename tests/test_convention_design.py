"""Legal wording, artwork, amounts and signing markers must survive restyling."""
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from lxml import etree

import pytest
from docx import Document

from convention_design import style_document
import company_convention

ROOT = Path(__file__).resolve().parents[1]
MODELS = sorted((ROOT / 'templates_word').glob('convention*.docx'))


def content_snapshot(data):
    with ZipFile(BytesIO(data)) as package:
        result = {}
        for name in package.namelist():
            if name.startswith('word/media/'):
                result[name] = package.read(name)
            elif name.startswith('word/') and name.endswith('.xml') and ('document' in name or 'header' in name or 'footer' in name):
                root = etree.fromstring(package.read(name))
                result[name] = [(etree.QName(n).localname, n.text, sorted(n.attrib.items()))
                                for n in root.iter() if etree.QName(n).localname in
                                {'t', 'instrText', 'fldChar', 'blip', 'imagedata', 'hyperlink'}]
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
