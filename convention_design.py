"""Presentation of newly generated agreements; never rewrites contractual text.

Applied after business fields have been filled, before PDF conversion. Source
models and already issued/signed PDFs are deliberately not part of this API.
"""
import re
import hashlib
import json
import math
from pathlib import Path
from copy import deepcopy

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.text.paragraph import Paragraph
from docx.text.run import Run


INK = NAVY = "14283F"
PALE = "F1F5FA"
GOLD = "F3C65F"
CREAM = "FFF5DA"
GREEN = "176344"
MINT = "E8F5EE"
PURPLE = "6D28D9"
LILAC = "F3EEFC"
MUTED = "596A7D"
FONT = "DejaVu Sans"
# Keep the original financial emphasis instead of flattening every run to black.
ACCENTS = {"DC2626": "B42318", "B42318": "B42318", "16A34A": GREEN,
           "15803D": GREEN, "047857": GREEN, GREEN: GREEN,
           "6D28D9": PURPLE, "1D4ED8": "2563EB"}
WIDTH = 17.4
ANCHOR = re.compile(r"\{\{s\d+\||BTSMARK_")
ARTICLE = re.compile(r"^Article\s+\d", re.I)
LOGO = Path(__file__).parent / "static/parcours-alternance/logo.png"
# Registration numbers already present in the Academy's approved source models.
REGISTRATION_LINES = (
    "CNAPS n° FOR-083-2027-02-08-20200755135 · SSIAP n° 8323 · NDA n° 93830600283",
    "ADEF APS n° 8320032701 · ADEF A3P n° 8320111201 · QUALIOPI n° 03169",
)


def document_reference(kind, *identity):
    """Stable on regeneration, distinct for each learner/session and agreement kind."""
    payload = json.dumps([kind, *identity], ensure_ascii=False, sort_keys=True, default=str)
    return ("CTR" if kind == "contrat" else "CONV") + "-" + hashlib.sha256(payload.encode()).hexdigest()[:12].upper()


def _remove(parent, *tags):
    for tag in tags:
        for child in list(parent.findall(qn(tag))):
            parent.remove(child)


def _property(parent, tag, **attributes):
    element = parent.find(qn(tag))
    if element is None:
        element = OxmlElement(tag)
        parent.append(element)
    for key, value in attributes.items():
        element.set(qn("w:" + key), str(value))
    return element


def _font(paragraph, size=9, color=INK, bold=None):
    # Include hyperlink runs without changing their targets or text nodes.
    for node in paragraph._p.xpath(".//w:r"):
        run = Run(node, paragraph)
        original_color = str(run.font.color.rgb or "")
        run.font.name = FONT
        run.font.size = Pt(size)
        run.font.color.rgb = RGBColor.from_string(ACCENTS.get(original_color, color) if color == INK else color)
        run.font.highlight_color = None
        run.font.all_caps = False
        if bold is not None:
            run.bold = bold
        if run._r.rPr is not None:
            _remove(run._r.rPr, "w:shd")


def _paragraph(paragraph):
    text = paragraph.text.strip()
    fmt = paragraph.paragraph_format
    signature_space = fmt.space_after
    fmt.alignment = WD_ALIGN_PARAGRAPH.LEFT
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(7)
    fmt.line_spacing = 1.25
    fmt.keep_with_next = False
    fmt.keep_together = False
    fmt.widow_control = True
    fmt.page_break_before = False
    _remove(paragraph._p.get_or_add_pPr(), "w:pBdr", "w:shd")
    # Pagination belongs to the new layout, not the old fixed page positions.
    for br in paragraph._p.xpath('.//w:br[@w:type="page"]'):
        br.getparent().remove(br)
    if ANCHOR.search(text):
        # Keep the marker's original font/spacing so Yousign can detect it and
        # the reserved signature rectangle remains at least 160 x 60 points.
        fmt.keep_together = True
        fmt.space_after = max(signature_space or 0, Pt(12))
        return
    _font(paragraph)
    if not text and not paragraph._p.xpath(".//w:drawing | .//w:pict | .//w:fldChar"):
        fmt.space_after = Pt(2)
        fmt.line_spacing = Pt(1)
        _property(paragraph._p.get_or_add_pPr(), "w:rPr")
        _property(paragraph._p.pPr.find(qn("w:rPr")), "w:sz", val=2)
        _font(paragraph, 1)
    elif re.match(r"^Article\s+\d", text, re.I) or text.startswith("Signature "):
        paragraph.style = "Heading 2"
        fmt.space_before = Pt(13)
        fmt.space_after = Pt(8)
        fmt.keep_with_next = True
        fmt.keep_together = True
        fmt.left_indent = Cm(0)
        fmt.first_line_indent = Cm(0)
        _font(paragraph, 11.5, NAVY, True)
        border = _property(paragraph._p.get_or_add_pPr(), "w:pBdr")
        _property(border, "w:bottom", val="single", sz=6, color=GOLD, space=5)
        for run in paragraph.runs:
            run.underline = False
    elif text.startswith("SECTION "):
        paragraph.style = "Heading 1"
        fmt.space_before = Pt(18)
        fmt.space_after = Pt(8)
        fmt.keep_with_next = True
        _font(paragraph, 12, NAVY, True)
    elif text.startswith(("Durée", "Date", "Période", "Lieu de la formation", "Lieu de formation", "Horaires", "Fait ")):
        _font(paragraph, 9, INK, True)
        fmt.keep_together = True
        if text.startswith("Fait "):
            fmt.keep_with_next = True
    elif text.startswith(("** ", "*Aucune", "* Aucune")):
        _font(paragraph, 8, MUTED)
        fmt.space_before = Pt(7)
        fmt.space_after = Pt(9)
    elif text.startswith("Tableau de prise en charge"):
        _font(paragraph, 10, NAVY, True)
        fmt.space_before = Pt(10)
        fmt.space_after = Pt(8)
        fmt.keep_with_next = True
    elif len(text) < 140 and (text.endswith(":") or all(r.bold for r in paragraph.runs if r.text.strip())):
        fmt.keep_with_next = True
        fmt.keep_together = True


def _title(paragraph, *, secondary=False):
    paragraph.style = "Title"
    fmt = paragraph.paragraph_format
    fmt.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fmt.left_indent = Cm(0)
    fmt.first_line_indent = Cm(0)
    fmt.space_before = Pt(6)
    fmt.space_after = Pt(8)
    fmt.keep_with_next = True
    fmt.keep_together = True
    fmt.line_spacing = 1.2
    _font(paragraph, 20 if secondary else 23, NAVY, True)
    legal_subtitle = False
    for run in paragraph.runs:
        legal_subtitle = legal_subtitle or run.text.lstrip().startswith("(Articles")
        if legal_subtitle:
            run.font.size = Pt(8)
            run.bold = False
            run.font.color.rgb = RGBColor.from_string(MUTED)


def _table(table):
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    props = table._tbl.tblPr
    _remove(props, "w:tblInd", "w:tblpPr", "w:tblBorders", "w:shd")
    _property(props, "w:tblW", w=round(WIDTH / 2.54 * 1440), type="dxa")
    count = len(table.columns)
    signature = table.cell(0, 0).text.strip().startswith("Pour ")
    financing = count == 3 and table.cell(0, 0).text.strip().startswith("CPF mobilisé")
    prices = count == 3 and table.cell(0, 0).text.strip().startswith("PRIX HT")
    if signature:
        previous = table._tbl.getprevious()
        while previous is not None and previous.tag == qn("w:p"):
            p = Paragraph(previous, table._parent)
            if p.text.strip() and not p.text.startswith(("Fait ", "Signature ")):
                break
            p.paragraph_format.keep_with_next = True
            previous = previous.getprevious()
    widths = [4.4, 3.2, 9.8] if financing else [WIDTH / count] * count
    for col, width in zip(table.columns, widths):
        col.width = Cm(width)
    for ri, row in enumerate(table.rows):
        signature_row = signature and ri == len(table.rows) - 1
        # Reserve the printed label, the 80pt Yousign seal and cell padding
        # even when the PDF renderer compacts empty lines in the source model.
        row.height = Cm(4.8) if signature_row else None
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST if signature_row else None
        _property(row._tr.get_or_add_trPr(), "w:cantSplit")
        for ci, cell in enumerate(row.cells):
            cell.width = Cm(widths[ci])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if signature_row and ANCHOR.search(cell.text):
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            cp = cell._tc.get_or_add_tcPr()
            _remove(cp, "w:tcBorders", "w:shd")
            borders = _property(cp, "w:tcBorders")
            for side in ("top", "left", "bottom", "right"):
                _property(borders, "w:" + side, val="single", sz=4, color="D5DFE9")
            margins = _property(cp, "w:tcMar")
            for side, value in (("top", 160), ("bottom", 140), ("left", 180), ("right", 180)):
                _property(margins, "w:" + side, w=value, type="dxa")
            fill = "FFFFFF"
            if prices:
                fill = (PALE, "F8FAFC", MINT)[ci]
            elif financing:
                fill = (MINT, LILAC, CREAM)[min(ri, 2)]
            elif ri == 0:
                fill = PALE
            elif ri % 2:
                fill = PALE
            _property(cp, "w:shd", val="clear", fill=fill)
            for pi, paragraph in enumerate(cell.paragraphs):
                _paragraph(paragraph)
                fmt = paragraph.paragraph_format
                fmt.space_after = Pt(3)
                fmt.space_before = Pt(0)
                fmt.left_indent = Cm(0)
                fmt.first_line_indent = Cm(0)
                fmt.keep_together = True
                # Keep compact financial and signature tables on the same page.
                fmt.keep_with_next = ri < len(table.rows) - 1 or pi < len(cell.paragraphs) - 1
                if ANCHOR.search(paragraph.text):
                    continue
                if not paragraph.text.strip():
                    continue
                color = INK
                size = 8.5 if financing else 9
                if financing and ci < 2:
                    color = (GREEN, PURPLE, "B45309")[min(ri, 2)]
                if prices and ci == 2:
                    color = GREEN
                if prices and pi > 0 and ci != 1:
                    size = 18
                elif financing and ci == 1:
                    size = 12
                _font(paragraph, size, color, True if (prices or ri == 0 or (financing and ci == 1)) else None)
                if prices or (financing and ci == 1):
                    fmt.alignment = WD_ALIGN_PARAGRAPH.CENTER
            if ri == 0 and not financing:
                _property(borders, "w:bottom", val="single", sz=8, color=GOLD)


def _panel(table, fill, accent=GOLD, *, prominent=False):
    """Keep the original information blocks as coloured cards, with all runs intact."""
    emphasis = [(node, Run(node, table.cell(0, 0).paragraphs[0]).bold)
                for node in table._tbl.xpath(".//w:r")]
    _table(table)
    for node, bold in emphasis:
        Run(node, table.cell(0, 0).paragraphs[0]).bold = bold
    row = table.rows[0]
    for cell in row.cells:
        cp = cell._tc.get_or_add_tcPr()
        _property(cp, "w:shd", val="clear", fill=fill)
        borders = _property(cp, "w:tcBorders")
        for side in ("top", "right", "bottom"):
            _property(borders, "w:" + side, val="single", sz=4, color=fill)
        _property(borders, "w:left", val="single", sz=18, color=accent)
        for index, p in enumerate(cell.paragraphs):
            _font(p, 10 if prominent else 9, NAVY, True if prominent or (index == 0 and p.text.startswith("Engagement")) else None)
            p.paragraph_format.space_after = Pt(5 if index < len(cell.paragraphs) - 1 else 0)
            p.paragraph_format.line_spacing = 1.4
            if p.text.startswith("(ci-après"):
                _font(p, 8, MUTED, False)
    # Keep short cards with the next section, but not a complete financial block.
    if prominent:
        for p in row.cells[0].paragraphs:
            p.paragraph_format.keep_with_next = True


def _organism_panel(document):
    """Arrange the two existing issuer blocks in reading order, without rewriting."""
    nodes = list(document.element.body)
    start = next((i for i, n in enumerate(nodes) if n.tag == qn("w:p")
                  and Paragraph(n, document).text.startswith(("Entre l’organisme de formation", "Entre l'organisme"))), None)
    if start is None:
        return
    stop = next((i for i in range(start + 1, len(nodes)) if nodes[i].tag == qn("w:tbl")), None)
    if stop is None:
        return
    paragraphs = [Paragraph(n, document) for n in nodes[start:stop] if n.tag == qn("w:p")]
    split = next((i for i, p in enumerate(paragraphs) if "centre de formation agréé" in p.text.lower()), None)
    if not split or not paragraphs[split + 1:]:
        return
    table = document.add_table(rows=1, cols=2)
    nodes[start].addprevious(table._tbl)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    _property(table._tbl.tblPr, "w:tblW", w=round(WIDTH / 2.54 * 1440), type="dxa")
    _property(table.rows[0]._tr.get_or_add_trPr(), "w:cantSplit")
    for col, cell, group, width in zip(table.columns, table.rows[0].cells,
                                      (paragraphs[:split], paragraphs[split:]), (8.2, 9.2)):
        col.width = cell.width = Cm(width)
        cell._tc.remove(cell.paragraphs[0]._p)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
        cp = cell._tc.get_or_add_tcPr()
        _property(cp, "w:shd", val="clear", fill=PALE)
        margins = _property(cp, "w:tcMar")
        for side in ("top", "bottom", "left", "right"):
            _property(margins, "w:" + side, w=180, type="dxa")
        borders = _property(cp, "w:tcBorders")
        for side in ("left", "right"):
            _property(borders, "w:" + side, val="single", sz=16, color="FFFFFF")
        for p in group:
            cell._tc.append(p._p)
            _font(p, 8, NAVY)
            fmt = p.paragraph_format
            fmt.left_indent = Cm(0)
            fmt.first_line_indent = Cm(0)
            fmt.line_spacing = 1.3
            fmt.space_after = Pt(5)
            fmt.keep_with_next = False
            if p.text.lstrip().startswith("-") or p._p.xpath("./w:pPr/w:numPr"):
                fmt.left_indent = Cm(.35)
                fmt.first_line_indent = Cm(-.35)
                fmt.tab_stops.clear_all()
                fmt.tab_stops.add_tab_stop(Cm(.35))


def _clear(container):
    for node in list(container._element):
        container._element.remove(node)


def _header_footer(document, reference, kind):
    """The retake invitation's navy/gold banner, with native Word text and fields."""
    from docx.enum.table import WD_ROW_HEIGHT_RULE
    from docx.enum.text import WD_TAB_ALIGNMENT
    modes = document.settings.element.xpath('./w:compat/w:compatSetting[@w:name="compatibilityMode"]/@w:val')
    # Word 2010 positions a table relative to its first cell's text; newer
    # models position its border. Compensate without changing body pagination.
    banner_indent = -1021 if modes and int(modes[0]) >= 15 else 0
    visited = set()
    for section in document.sections:
        old_footer = " ".join(section.footer._element.xpath(".//w:t/text()"))
        paris = "84089988400034" in re.sub(r"\D", "", old_footer)
        siret = "840 899 884 00034" if paris else "840 899 884 00026"
        address = "142 rue de Rivoli · 75001 Paris" if paris else "54 chemin du Carreou · 83480 Puget-sur-Argens"
        extra_identity = "RCS Fréjus · UAI 0831774C" if "UAI 0831774C" in old_footer else ""
        section.page_width, section.page_height = Cm(21), Cm(29.7)
        section.left_margin = section.right_margin = Cm(1.8)
        section.top_margin, section.bottom_margin = Pt(125), Cm(2.8)
        section.header_distance, section.footer_distance = Pt(0), Cm(.7)
        section.different_first_page_header_footer = False
        for container in (section.header, section.even_page_header, section.footer, section.even_page_footer):
            if container._element in visited:
                continue
            visited.add(container._element)
            _clear(container)
            if container._element.tag == qn("w:ftr"):
                lines = (
                    "Intégrale Academy – Intégrale Sécurité Formations · SIRET " + siret + " · NAF 8559A",
                    address + " · 04 22 47 07 68 · ecole@integraleacademy.com",
                    *REGISTRATION_LINES,
                )
                for i, line in enumerate(lines):
                    p = container.add_paragraph(line)
                    p.paragraph_format.space_before = Pt(0)
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.line_spacing = Pt(10)
                    _font(p, 6.8, MUTED)
                    if i == 0:
                        border = _property(p._p.get_or_add_pPr(), "w:pBdr")
                        _property(border, "w:top", val="single", sz=4, color="D5DFE9", space=6)
                p = container.add_paragraph(extra_identity + "\tPage ")
                p.paragraph_format.tab_stops.add_tab_stop(Cm(WIDTH), WD_TAB_ALIGNMENT.RIGHT)
                for instruction in ("PAGE", "NUMPAGES"):
                    if instruction == "NUMPAGES":
                        p.add_run(" / ")
                    for field_type in ("begin", "instruction", "separate", "value", "end"):
                        run = p.add_run()
                        if field_type == "instruction":
                            field = OxmlElement("w:instrText"); field.text = instruction
                        elif field_type == "value":
                            field = OxmlElement("w:t"); field.text = "1"
                        else:
                            field = OxmlElement("w:fldChar"); field.set(qn("w:fldCharType"), field_type)
                        run._r.append(field)
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.line_spacing = Pt(10)
                _font(p, 6.8, MUTED)
                continue
            table = container.add_table(rows=1, cols=2, width=Cm(21))
            table.alignment = WD_TABLE_ALIGNMENT.LEFT
            table.autofit = False
            props = table._tbl.tblPr
            _property(props, "w:tblW", w=11906, type="dxa")
            _property(props, "w:tblInd", w=banner_indent, type="dxa")
            borders = _property(props, "w:tblBorders")
            for side in ("top", "left", "right", "insideH", "insideV"):
                _property(borders, "w:" + side, val="nil")
            _property(borders, "w:bottom", val="single", sz=24, color=GOLD)
            row = table.rows[0]
            row.height, row.height_rule = Pt(100), WD_ROW_HEIGHT_RULE.EXACTLY
            for i, (cell, width) in enumerate(zip(row.cells, (11, 10))):
                table.columns[i].width = cell.width = Cm(width)
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                cp = cell._tc.get_or_add_tcPr()
                _property(cp, "w:shd", val="clear", fill=NAVY)
                cell_borders = _property(cp, "w:tcBorders")
                for side in ("top", "left", "right"):
                    _property(cell_borders, "w:" + side, val="single", sz=4, color=NAVY)
                margins = _property(cp, "w:tcMar")
                for side, value in (("top", 0), ("bottom", 0), ("left", 1021 if i == 0 else 0), ("right", 1021 if i == 1 else 0)):
                    _property(margins, "w:" + side, w=value, type="dxa")
                p = cell.paragraphs[0]
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.line_spacing = 1
                if i == 0:
                    p.add_run().add_picture(str(LOGO), width=Pt(215))
                else:
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    p.add_run("VOTRE CONTRAT" if kind == "contrat" else "VOTRE CONVENTION")
                    _font(p, 9, GOLD, True)
                    p.paragraph_format.space_after = Pt(10)
                    p = cell.add_paragraph(("Contrat" if kind == "contrat" else "Convention") + " n° " + reference)
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    p.paragraph_format.space_after = Pt(0)
                    p.paragraph_format.line_spacing = 1
                    _font(p, 8, "FFFFFF")
            p = container.add_paragraph()
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = Pt(1)
            _font(p, 1)


def _content(document):
    """Exact contractual body, links, fields and picture references in reading order.

    The explicitly requested new banner, reference and registrations live only
    in the header/footer, outside this immutable contractual content.
    """
    elements = [document.element]
    tags = {qn(tag) for tag in ("w:t", "w:instrText", "w:fldChar", "w:hyperlink", "a:blip")}
    tags.add("{urn:schemas-microsoft-com:vml}imagedata")
    return [tuple((node.tag, node.text, tuple(sorted(node.attrib.items())))
                  for node in element.iter() if node.tag in tags)
            for element in elements]


def _article_flow(document):
    """Keep articles that fit a page together; long articles break between paragraphs."""
    children = list(document.element.body)
    first_article = True
    for i, node in enumerate(children):
        if node.tag != qn("w:p") or not ARTICLE.match(Paragraph(node, document).text):
            continue
        if first_article:
            Paragraph(node, document).paragraph_format.page_break_before = True
            first_article = False
        paragraphs = []
        estimated_height = 0
        for child in children[i:]:
            if child is not node and child.tag == qn("w:p"):
                text = Paragraph(child, document).text.strip()
                if ARTICLE.match(text) or text.startswith(("Signature ", "SECTION ", "RÈGLEMENT", "Annexe ")):
                    break
            if child.tag not in (qn("w:p"), qn("w:tbl")):
                break
            group = [child] if child.tag == qn("w:p") else child.xpath(".//w:p")
            paragraphs.extend(group)
            if child.tag == qn("w:p"):
                p = Paragraph(child, document)
                lines = sum(max(1, math.ceil(len(line) / 92)) for line in p.text.split("\n"))
                estimated_height += lines * 14 + 9
            else:
                # Conservative estimate, including cell padding and wrapped lines.
                for row in child.xpath("./w:tr"):
                    heights = []
                    cells = row.xpath("./w:tc")
                    for cell in cells:
                        heights.append(sum((max(1, math.ceil(len(Paragraph(p, document).text) / (92 / len(cells))))) * 15 + 5
                                           for p in cell.xpath(".//w:p")) + 18)
                    estimated_height += max(heights, default=0)
        financial = "dispositions financières" in Paragraph(node, document).text.lower()
        if financial:
            Paragraph(node, document).paragraph_format.page_break_before = True
        compact = estimated_height <= 560 or financial
        for p in paragraphs:
            fmt = Paragraph(p, document).paragraph_format
            fmt.keep_together = True
            # Fit a compact course description alongside Article 1, instead of
            # stranding the short object clause alone on an almost empty page.
            if compact and re.match(r"^Article\s+2\s*[-–]", Paragraph(node, document).text, re.I) and p is not node:
                fmt.line_spacing = 1.25
                fmt.space_after = Pt(5)
            if compact:
                fmt.keep_with_next = True
        if len(paragraphs) > 1 and compact:
            Paragraph(paragraphs[-1], document).paragraph_format.keep_with_next = False


def style_document(document, *, reference_key=None):
    before = _content(document)
    text = " ".join(document.element.xpath(".//w:t/text()"))
    kind = "contrat" if "Contrat de formation professionnelle" in text[:400] else "convention"
    reference = document_reference(kind, reference_key if reference_key is not None else before)
    # Some source models put the next article in the footnote's paragraph.
    # Move the existing runs into their own paragraph, never recreate their text.
    for p in list(document.paragraphs):
        if not p.text.startswith("*"):
            continue
        for run in p.runs:
            if re.match(r"^Article\s+\d+\s*[-–]", run.text):
                heading = OxmlElement("w:p")
                if p._p.pPr is not None:
                    heading.append(deepcopy(p._p.pPr))
                p._p.addnext(heading)
                children = list(p._p)
                for node in children[children.index(run._r):]:
                    heading.append(node)
                break
    for name in ("Normal", "Title", "Heading 1", "Heading 2"):
        style = document.styles[name] if name in document.styles else document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.font.name = FONT
        style.font.color.rgb = RGBColor.from_string(INK)
        if style._element.pPr is not None:
            _remove(style._element.pPr, "w:pBdr", "w:shd")
    _header_footer(document, reference, kind)
    for p in document.paragraphs:
        _paragraph(p)
        if p.text.startswith(("Convention d’accompagnement", "Convention de formation")):
            _title(p, secondary=True)
        elif p.text.strip() == "Annexe à la convention de formation":
            _title(p, secondary=True)
            p.paragraph_format.page_break_before = True
    for table in list(document.tables):
        if len(table.rows) != 1 or len(table.columns) != 1:
            _table(table)
            continue
        # Narrative blocks become regular paragraphs; data remain true tables.
        text = table.cell(0, 0).text.strip()
        if text.startswith(("Et le ", "Entreprise acheteuse", "Entreprise financeuse")):
            next_node = table._tbl.getnext()
            if next_node is not None and next_node.tag == qn("w:p") and Paragraph(next_node, document).text.strip().startswith("(ci-après"):
                table.cell(0, 0)._tc.append(next_node)
            _panel(table, PALE, NAVY, prominent=True)
            continue
        if text.startswith(("Le prix ", "Engagement du stagiaire")):
            _panel(table, PALE if text.startswith("Le prix ") else CREAM)
            continue
        if len(text) < 240 and len(table.cell(0, 0).paragraphs) == 1 and not text.startswith(("Contrat de formation", "Convention de formation", "RÈGLEMENT")):
            _panel(table, CREAM, GOLD, prominent=True)
            continue
        for index, p in enumerate(table.cell(0, 0).paragraphs):
            _paragraph(p)
            p.paragraph_format.left_indent = Cm(0)
            p.paragraph_format.first_line_indent = Cm(0)
            if text.startswith(("Contrat de formation", "Convention de formation", "RÈGLEMENT INTÉRIEUR")):
                if index == 0:
                    _title(p, secondary=text.startswith("RÈGLEMENT"))
                    p.paragraph_format.page_break_before = text.startswith("RÈGLEMENT")
                else:
                    _font(p, 8, MUTED, False)
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    p.paragraph_format.space_after = Pt(14)
                    p.paragraph_format.keep_with_next = True
            table._tbl.addprevious(p._p)
        table._tbl.getparent().remove(table._tbl)
    _organism_panel(document)
    # The old models use empty paragraphs as fixed spacers. After reflow these
    # can spill onto a blank page immediately before an annex page break.
    # Remove only empty body paragraphs, never text, fields, bookmarks or images.
    for p in list(document.paragraphs):
        if not p._p.xpath(".//w:t | .//w:br | .//w:drawing | .//w:pict | .//w:fldChar | .//w:bookmarkStart | .//w:bookmarkEnd") and p._p.find(".//" + qn("w:sectPr")) is None:
            p._p.getparent().remove(p._p)
    # Real spacing between adjacent coloured cards: Word joins adjacent tables
    # without a separating paragraph, ignoring paragraph margins inside cells.
    for table in document.tables:
        if table._tbl.getprevious() is not None and table._tbl.getprevious().tag == qn("w:tbl"):
            spacer = OxmlElement("w:p")
            table._tbl.addprevious(spacer)
            p = Paragraph(spacer, document)
            p.paragraph_format.line_spacing = Pt(12)
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.keep_with_next = True
    employer = any(t.cell(0, 0).text.startswith(("Entreprise financeuse", "Entreprise acheteuse"))
                   for t in document.tables)
    if employer:
        # The first page identifies the parties. Let long programme articles
        # flow by paragraph instead of moving a whole article to the next page.
        headings = [p for p in document.paragraphs if ARTICLE.match(p.text.strip())]
        if headings:
            headings[0].paragraph_format.page_break_before = True
        for table in document.tables:
            if table.cell(0, 0).text.startswith("Pour "):
                for cell in table.rows[-1].cells:
                    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
    else:
        _article_flow(document)
    if _content(document) != before:
        raise ValueError("La mise en page ne doit modifier aucun texte, champ ou visuel de la convention.")
    return document


def restyle_file(path, *, reference_key=None):
    document = style_document(Document(path), reference_key=reference_key)
    document.save(path)
