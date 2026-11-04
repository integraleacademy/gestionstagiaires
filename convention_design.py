"""Presentation of newly generated agreements; never rewrites contractual text.

Applied after business fields have been filled, before PDF conversion. Source
models and already issued/signed PDFs are deliberately not part of this API.
"""
import re

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.text.paragraph import Paragraph
from docx.text.run import Run


INK = "263238"
NAVY = "243746"
PALE = "F3F5F6"
GOLD = "FFF3D6"
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


def _font(paragraph, size=10.5, color=INK, bold=None):
    # Include hyperlink runs without changing their targets or text nodes.
    for node in paragraph._p.xpath(".//w:r"):
        run = Run(node, paragraph)
        run.font.name = "Calibri"
        run.font.size = Pt(size)
        run.font.color.rgb = RGBColor.from_string(color)
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
    fmt.space_after = Pt(5)
    fmt.line_spacing = 1.12
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
        fmt.space_after = Pt(6)
        fmt.keep_with_next = True
        fmt.keep_together = True
        fmt.left_indent = Cm(0)
        fmt.first_line_indent = Cm(0)
        _font(paragraph, 12, "000000", True)
        for run in paragraph.runs:
            run.underline = False
    elif text.startswith("SECTION "):
        paragraph.style = "Heading 1"
        fmt.space_before = Pt(18)
        fmt.space_after = Pt(8)
        fmt.keep_with_next = True
        _font(paragraph, 13, "000000", True)
    elif text.startswith(("Durée", "Date", "Période", "Lieu de la formation", "Lieu de formation", "Horaires", "Fait ")):
        _font(paragraph, 10.5, INK, True)
        fmt.keep_together = True
        if text.startswith("Fait "):
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
    _font(paragraph, 19 if secondary else 22, "000000", True)


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
                _property(borders, "w:" + side, val="single", sz=4, color="D9D9D9")
            margins = _property(cp, "w:tcMar")
            for side, value in (("top", 110), ("bottom", 110), ("left", 140), ("right", 140)):
                _property(margins, "w:" + side, w=value, type="dxa")
            fill = "FFFFFF"
            if prices:
                fill = NAVY if ci == 2 else PALE
            elif financing:
                fill = GOLD if ri == 2 else (PALE if ri == 0 else "FFFFFF")
            elif ri == 0:
                fill = NAVY
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
                color = "FFFFFF" if fill == NAVY else INK
                size = 10 if financing else 10.5
                if prices and pi > 0 and ci != 1:
                    size = 16
                _font(paragraph, size, color, True if (prices or ri == 0 or (financing and ci == 1)) else None)
                if prices or (financing and ci == 1):
                    fmt.alignment = WD_ALIGN_PARAGRAPH.CENTER
            if signature and ri == len(table.rows) - 1:
                # Minimum, never exact: longer names and signature images can grow.
                row.height = Cm(3.5)
                from docx.enum.table import WD_ROW_HEIGHT_RULE
                row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST


def _header_footer(document):
    visited = set()
    for section in document.sections:
        section.page_width, section.page_height = Cm(21), Cm(29.7)
        section.left_margin = section.right_margin = Cm(1.8)
        section.top_margin, section.bottom_margin = Cm(4.5), Cm(2.4)
        section.header_distance, section.footer_distance = Cm(1), Cm(.8)
        for container in (section.header, section.first_page_header, section.even_page_header,
                          section.footer, section.first_page_footer, section.even_page_footer):
            if container.is_linked_to_previous or id(container._element) in visited:
                continue
            visited.add(id(container._element))
            is_footer = container._element.tag == qn("w:ftr")
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
                _font(p, 7.5 if is_footer else 9, "59646C" if is_footer else "000000")
            if is_footer:
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
                if old_width <= Cm(10.5):
                    continue
                ratio = Cm(10.5) / old_width
                for node in [extent, *inline.xpath(".//a:xfrm/a:ext")]:
                    for key in ("cx", "cy"):
                        node.set(key, str(round(int(node.get(key)) * ratio)))


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


def style_document(document):
    before = _content(document)
    for name in ("Normal", "Title", "Heading 1", "Heading 2"):
        style = document.styles[name] if name in document.styles else document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.font.name = "Calibri"
        style.font.color.rgb = RGBColor.from_string("000000" if name != "Normal" else INK)
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
        for index, p in enumerate(table.cell(0, 0).paragraphs):
            _paragraph(p)
            p.paragraph_format.left_indent = Cm(0)
            p.paragraph_format.first_line_indent = Cm(0)
            if text.startswith(("Contrat de formation", "Convention de formation", "RÈGLEMENT INTÉRIEUR")):
                if index == 0:
                    _title(p, secondary=text.startswith("RÈGLEMENT"))
                    p.paragraph_format.page_break_before = text.startswith("RÈGLEMENT")
                else:
                    _font(p, 9.5, "59646C", False)
                    p.paragraph_format.space_after = Pt(14)
                    p.paragraph_format.keep_with_next = True
            elif text.startswith(("Et le ", "Entreprise acheteuse")):
                _font(p, 11, INK, True)
                p.paragraph_format.space_before = Pt(10)
                p.paragraph_format.space_after = Pt(10)
                p.paragraph_format.keep_with_next = True
            elif text.startswith("Engagement du stagiaire") and index == 0:
                _font(p, 11, "000000", True)
                p.paragraph_format.space_before = Pt(9)
                p.paragraph_format.keep_with_next = True
            elif len(text) < 240 and len(table.cell(0, 0).paragraphs) == 1 and not text.startswith(("Le prix ", "Engagement ")):
                _font(p, 13, "000000", True)
                p.paragraph_format.space_before = Pt(5)
                p.paragraph_format.space_after = Pt(10)
                p.paragraph_format.keep_with_next = True
            table._tbl.addprevious(p._p)
        table._tbl.getparent().remove(table._tbl)
    # The old models use empty paragraphs as fixed spacers. After reflow these
    # can spill onto a blank page immediately before an annex page break.
    # Remove only empty body paragraphs, never text, fields, bookmarks or images.
    for p in list(document.paragraphs):
        if not p._p.xpath(".//w:t | .//w:br | .//w:drawing | .//w:pict | .//w:fldChar | .//w:bookmarkStart | .//w:bookmarkEnd") and p._p.find(".//" + qn("w:sectPr")) is None:
            p._p.getparent().remove(p._p)
    if _content(document) != before:
        raise ValueError("La mise en page ne doit modifier aucun texte, champ ou visuel de la convention.")
    return document


def restyle_file(path):
    document = style_document(Document(path))
    document.save(path)
