"""Prepare the supplied 24-slide DESP decks for session-specific PDF overlays.

Offline maintenance only. First export both PowerPoints to PDF with LibreOffice.
Usage: python prepare_templates.py SOURCE_PPTX_DIRECTORY EXPORTED_PDF_DIRECTORY
"""
import json
from pathlib import Path
import sys
import zipfile

from lxml import etree as ET
import pymupdf as fitz

ASSETS = Path(__file__).resolve().parent
NAMES = {
    1: ['text-1-3', 'text-1-4'], 4: ['text-4-4'],
    6: ['text-6-2', 'text-6-3', 'text-6-5'], 7: ['text-7-1'],
    8: ['text-8-4'], 14: ['text-12-1'], 17: ['text-15-0'],
    24: ['text-22-3', 'text-22-5', 'text-22-8'],
}
NS = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'}


def prepare(source, exported_pdf, city):
    specs = []
    with zipfile.ZipFile(source) as archive, fitz.open(exported_pdf) as doc:
        assert len(doc) == 24
        for number, page in enumerate(doc, 1):
            spans = [s for b in page.get_text('dict')['blocks']
                     for line in b.get('lines', []) for s in line['spans']]

            def remove(name, box):
                matching = [s for s in spans if box.contains(
                    (fitz.Rect(s['bbox']).tl+fitz.Rect(s['bbox']).br)/2)]
                assert matching, (city, number, name)
                first = matching[0]
                specs.append(dict(page=number, name=name, rect=list(box),
                                  origin=first['origin'], size=first['size'],
                                  bold='Bold' in first['font'], color=first['color']))
                for span in matching:
                    page.add_redact_annot(fitz.Rect(span['bbox']) + (-.2, -.2, .2, .2), fill=False)

            xml = ET.fromstring(archive.read(f'ppt/slides/slide{number}.xml'))
            for shape in xml.xpath('.//p:sp', namespaces=NS):
                name = shape.xpath('string(p:nvSpPr/p:cNvPr/@name)', namespaces=NS)
                if name not in NAMES.get(number, []):
                    continue
                off = shape.find('p:spPr/a:xfrm/a:off', NS)
                ext = shape.find('p:spPr/a:xfrm/a:ext', NS)
                x, y = (int(off.get(a))/12700 for a in ('x', 'y'))
                w, h = (int(ext.get(a))/12700 for a in ('cx', 'cy'))
                remove(name, fitz.Rect(x, y, x+w, y+h))
            if number == 5:
                # Month grids are recomposed from saved session dates, including year changes.
                page.add_redact_annot(fitz.Rect(35, 30, 925, 500), fill=False)
            page.apply_redactions(images=0, graphics=0)
            if number == 5:
                page.draw_rect(fitz.Rect(35, 30, 925, 500), color=None,
                               fill=(1, 253/255, 248/255), overlay=True)
        assert len(specs) == 13, (city, len(specs))
        assert not any('2026' in p.get_text() for p in doc), 'Unreplaced session date'
        doc.set_metadata({'title': f'Réunion de lancement DESP {city} — modèle',
                          'author': 'Intégrale Academy'})
        doc.subset_fonts()
        doc.save(ASSETS/f'{city}.pdf', garbage=4, deflate=True)
        (ASSETS/f'{city}.json').write_text(json.dumps(specs, ensure_ascii=False, indent=2))
        print(city, len(doc), 'slides;', len(specs), 'dynamic areas')


if __name__ == '__main__':
    for city, label, month in [('paris', 'Paris', 'octobre'), ('puget', 'Puget', 'novembre')]:
        basename = f'Diaporama_DESP_{label}_{month}_2026_calendrier_visuel'
        prepare(Path(sys.argv[1])/(basename+'.pptx'), Path(sys.argv[2])/(basename+'.pdf'), city)
