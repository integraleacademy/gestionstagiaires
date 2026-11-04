"""Presentation of newly generated agreements; never rewrites contractual text.

Applied after business fields have been filled, before PDF conversion. Source
models and already issued/signed PDFs are deliberately not part of this API.
"""
import re
from copy import deepcopy

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
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
    fmt.line_spacing = 1.4
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
        if "dispositions financières" in text.lower():
            fmt.space_before = Pt(0)
            fmt.space_after = Pt(16)
            _font(paragraph, 20, NAVY, True)
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
        row.height = None
        row.height_rule = None
        _property(row._tr.get_or_add_trPr(), "w:cantSplit")
        for ci, cell in enumerate(row.cells):
            cell.width = Cm(widths[ci])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
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
            if signature and ri == len(table.rows) - 1:
                # Minimum, never exact: longer names and signature images can grow.
                row.height = Cm(3.5)
                from docx.enum.table import WD_ROW_HEIGHT_RULE
                row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST


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
                  and Paragraph(n, document).text.startswith("Entre l’organisme de formation")), None)
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
            if p.text.lstrip().startswith("-"):
                fmt.left_indent = Cm(.35)
                fmt.first_line_indent = Cm(-.35)
                fmt.tab_stops.clear_all()
                fmt.tab_stops.add_tab_stop(Cm(.35))


def _header_footer(document):
    visited = set()
    for section in document.sections:
        section.page_width, section.page_height = Cm(21), Cm(29.7)
        section.left_margin = section.right_margin = Cm(1.8)
        section.top_margin, section.bottom_margin = Cm(4), Cm(2.3)
        section.header_distance, section.footer_distance = Cm(.65), Cm(.8)
        for container in (section.header, section.first_page_header, section.even_page_header,
                          section.footer, section.first_page_footer, section.even_page_footer):
            if container.is_linked_to_previous or id(container._element) in visited:
                continue
            visited.add(id(container._element))
            is_footer = container._element.tag == qn("w:ftr")
            if not is_footer:
                # Legacy header grids are only positioning devices. Remove their
                # empty rows and columns so the navy banner has no white seams.
                for table in list(container.tables):
                    for node in list(table._tbl.xpath(".//w:p")):
                        table._tbl.addprevious(node)
                    table._tbl.getparent().remove(table._tbl)
                for node in list(container._element.xpath("./w:p")):
                    if not node.xpath(".//w:t | .//w:drawing | .//w:pict | .//w:fldChar | .//w:bookmarkStart | .//w:bookmarkEnd"):
                        node.getparent().remove(node)
            for table in container.tables:
                table.alignment = WD_TABLE_ALIGNMENT.LEFT
                table.autofit = False
                _remove(table._tbl.tblPr, "w:tblInd", "w:tblpPr", "w:tblBorders")
                _property(table._tbl.tblPr, "w:tblW", w=round(WIDTH / 2.54 * 1440), type="dxa")
                for col in table.columns:
                    col.width = Cm(WIDTH / len(table.columns))
                for row in table.rows:
                    for cell in row.cells:
                        cell.width = Cm(WIDTH / len(table.columns))
                        cp = cell._tc.get_or_add_tcPr()
                        _remove(cp, "w:tcBorders", "w:shd")
                        borders = _property(cp, "w:tcBorders")
                        for side in ("top", "bottom", "left", "right"):
                            _property(borders, "w:" + side, val="nil")
                        margins = _property(cp, "w:tcMar")
                        for side in ("top", "bottom", "left", "right"):
                            _property(margins, "w:" + side, w=0, type="dxa")
            for node in container._element.xpath(".//w:p"):
                p = Paragraph(node, container)
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.line_spacing = 1
                p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
                _remove(p._p.get_or_add_pPr(), "w:pBdr", "w:shd")
                _font(p, 7 if is_footer else 8, MUTED if is_footer else NAVY)
            if is_footer:
                if container.paragraphs:
                    border = _property(container.paragraphs[0]._p.get_or_add_pPr(), "w:pBdr")
                    _property(border, "w:top", val="single", sz=4, color="D5DFE9", space=6)
                continue
            # Use the existing artwork. Inline placement eliminates page-edge
            # floating images and overlap; both image extents retain their ratio.
            for anchor in list(container._element.xpath(".//wp:anchor")):
                inline = OxmlElement("wp:inline")
                for tag in ("wp:extent", "wp:effectExtent", "wp:docPr", "wp:cNvGraphicFramePr", "a:graphic"):
                    child = anchor.find(qn(tag))
                    if child is not None:
                        inline.append(child)
                anchor.getparent().replace(anchor, inline)
            for inline in container._element.xpath(".//wp:inline"):
                extent = inline.find(qn("wp:extent"))
                if extent is None:
                    continue
                old_width = int(extent.get("cx"))
                if old_width <= Cm(8.5):
                    continue
                ratio = Cm(8.5) / old_width
                for node in [extent, *inline.xpath(".//a:xfrm/a:ext")]:
                    for key in ("cx", "cy"):
                        node.set(key, str(round(int(node.get(key)) * ratio)))
            # A navy and gold frame echoes the retake convention while keeping
            # the original header artwork and every embedded legal detail.
            paragraphs = list(container._element.xpath(".//w:p"))
            if paragraphs:
                first = _property(paragraphs[0].get_or_add_pPr(), "w:pBdr")
                _property(first, "w:top", val="single", sz=72, color=NAVY, space=0)
                last = _property(paragraphs[-1].get_or_add_pPr(), "w:pBdr")
                _property(last, "w:bottom", val="single", sz=18, color=GOLD, space=6)
                for node in paragraphs:
                    _property(node.get_or_add_pPr(), "w:shd", val="clear", fill=NAVY)
                    _font(Paragraph(node, container), 8, "FFFFFF")
                    if node.xpath(".//w:drawing | .//w:pict"):
                        Paragraph(node, container).alignment = WD_ALIGN_PARAGRAPH.CENTER


def _content(document):
    """Exact text nodes, fields and picture references in document order."""
    elements = [document.element]
    elements.extend(part.element for part in document.part.related_parts.values()
                    if hasattr(part, "element") and part.element.tag in {qn("w:hdr"), qn("w:ftr")})
    tags = {qn(tag) for tag in ("w:t", "w:instrText", "w:fldChar", "a:blip")}
    tags.add("{urn:schemas-microsoft-com:vml}imagedata")
    return [tuple((node.tag, node.text, tuple(sorted(node.attrib.items())))
                  for node in element.iter() if node.tag in tags)
            for element in elements]


def _keep_financial_sections(document):
    """Keep each compact financial summary together without a near-empty page before it."""
    children = list(document.element.body)
    for i, node in enumerate(children):
        if node.tag != qn("w:p") or "dispositions financières" not in Paragraph(node, document).text.lower():
            continue
        if not re.match(r"^Article\s+\d", Paragraph(node, document).text, re.I):
            continue
        paragraphs = []
        for child in children[i:]:
            if child is not node and child.tag == qn("w:p") and re.match(
                r"^(Article\s+\d|Signature )", Paragraph(child, document).text, re.I
            ):
                break
            paragraphs.extend([child] if child.tag == qn("w:p") else child.xpath(".//w:p"))
        for p in paragraphs:
            Paragraph(p, document).paragraph_format.keep_with_next = True
        if paragraphs:
            Paragraph(paragraphs[-1], document).paragraph_format.keep_with_next = False


def style_document(document):
    before = _content(document)
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
    _header_footer(document)
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
        if text.startswith(("Et le ", "Entreprise acheteuse")):
            next_node = table._tbl.getnext()
            if next_node is not None and next_node.tag == qn("w:p") and Paragraph(next_node, document).text.startswith("(ci-après"):
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
    _keep_financial_sections(document)
    if _content(document) != before:
        raise ValueError("La mise en page ne doit modifier aucun texte, champ ou visuel de la convention.")
    return document


def restyle_file(path):
    document = style_document(Document(path))
    document.save(path)
