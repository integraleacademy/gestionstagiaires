"""Create the matching editable Word file from the typeset page, without duplicating copy.

Photos, seals and the paper design form the background. All printed text sits above it
in native positioned Word paragraphs, with the original hyperlinks and a normal text order.
"""

from io import BytesIO
from uuid import uuid5, NAMESPACE_URL
from lxml import etree
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from .source import FONT_DIR
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.shared import Pt, RGBColor
import pymupdf

FACES = {
    "Barlow-Regular": "Barlow",
    "Barlow-SemiBold": "Barlow SemiBold",
    "BarlowCondensed-Bold": "Barlow Condensed",
}


def word_element(tag, attrs):
    node = OxmlElement(tag)
    for key, val in attrs.items():
        node.set(qn(key), str(val))
    return node


def embed_fonts(doc):
    """Embed the licensed print fonts for Word installations without Barlow."""
    table = doc.part.part_related_by(RT.FONT_TABLE)
    xml = etree.fromstring(table.blob)
    for face, name in FACES.items():
        filename = face + ".ttf"
        key = uuid5(NAMESPACE_URL, "https://integraleconnect.com/fonts/" + filename)
        mask = key.bytes[::-1]
        data = bytearray((FONT_DIR / filename).read_bytes())
        for i in range(32):
            data[i] ^= mask[i % 16]
        blob = Part(
            PackURI("/word/fonts/" + face + ".odttf"),
            "application/vnd.openxmlformats-officedocument.obfuscatedFont",
            bytes(data),
            doc.part.package,
        )
        rid = table.relate_to(blob, RT.FONT)
        font = word_element("w:font", {"w:name": name})
        font.append(word_element("w:family", {"w:val": "swiss"}))
        tag = "w:embedBold" if face.endswith("-Bold") else "w:embedRegular"
        font.append(
            word_element(tag, {"r:id": rid, "w:fontKey": "{" + str(key).upper() + "}"})
        )
        xml.append(font)
    table._blob = etree.tostring(
        xml, encoding="UTF-8", xml_declaration=True, standalone=True
    )


def background(paragraph, graphic, width, height):
    shape = (
        paragraph.add_run()
        .add_picture(graphic, width=Pt(width), height=Pt(height))
        ._inline
    )
    anchor = OxmlElement("wp:anchor")
    for key, value in {
        "distT": 0,
        "distB": 0,
        "distL": 0,
        "distR": 0,
        "simplePos": 0,
        "relativeHeight": 0,
        "behindDoc": 1,
        "locked": 1,
        "layoutInCell": 1,
        "allowOverlap": 1,
    }.items():
        anchor.set(key, str(value))
    origin = OxmlElement("wp:simplePos")
    origin.set("x", "0")
    origin.set("y", "0")
    anchor.append(origin)
    for axis in ("H", "V"):
        pos = OxmlElement("wp:position" + axis)
        pos.set("relativeFrom", "page")
        offset = OxmlElement("wp:posOffset")
        offset.text = "0"
        pos.append(offset)
        anchor.append(pos)
    for child in list(shape):
        if child.tag == qn("wp:docPr"):
            anchor.append(OxmlElement("wp:wrapNone"))
        anchor.append(child)
    shape.getparent().replace(shape, anchor)


def positioned_text(doc, span, width, links):
    x, y, x1, _ = span["bbox"]
    text = span["text"]
    if not text.strip():
        return
    font = span["font"].split("+")[-1]
    size = span["size"]
    p = doc.add_paragraph()
    fmt = p.paragraph_format
    fmt.space_before = fmt.space_after = Pt(0)
    fmt.line_spacing = Pt(size * 1.2)
    fmt.widow_control = False
    # Allow font substitution in Word while keeping neighbouring columns independent.
    box = min(width - x, max((x1 - x) * 1.25 + 5, x1 - x + size * 2))
    p._p.get_or_add_pPr().append(
        word_element(
            "w:framePr",
            {
                "w:hAnchor": "page",
                "w:vAnchor": "page",
                "w:x": round(x * 20),
                "w:y": round(y * 20),
                "w:w": round(box * 20),
                "w:wrap": "none",
                "w:vSpace": 0,
                "w:hSpace": 0,
            },
        )
    )
    run = p.add_run(text)
    run.font.name = FACES.get(font, "Barlow")
    run.bold = font.endswith("-Bold")
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(f"{span['color']:06X}")
    midpoint = pymupdf.Point((x + x1) / 2, span["origin"][1] - size * 0.34)
    for target in links:
        if midpoint not in target["from"]:
            continue
        link = OxmlElement("w:hyperlink")
        if target.get("uri"):
            link.set(
                qn("r:id"),
                doc.part.relate_to(target["uri"], RT.HYPERLINK, is_external=True),
            )
        elif isinstance(target.get("page"), int) and target["page"] >= 0:
            link.set(qn("w:anchor"), "Page" + str(target["page"] + 1))
        elif str(target.get("page", "")).isdigit():
            link.set(qn("w:anchor"), "Page" + str(target["page"]))
        else:
            continue
        link.append(run._r)
        p._p.append(link)
        break


def write(pdf_path, docx_path):
    doc = Document()
    embed_fonts(doc)
    doc.core_properties.title = "Convocation · Intégrale Academy"
    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.left_margin = section.right_margin = section.top_margin = (
        section.bottom_margin
    ) = Pt(0)
    section.header_distance = section.footer_distance = Pt(0)
    with pymupdf.open(pdf_path) as printed, pymupdf.open(pdf_path) as artwork:
        for i, page in enumerate(printed):
            width, height = page.rect.width, page.rect.height
            section.page_width, section.page_height = Pt(width), Pt(height)
            if i:
                doc.add_page_break()
            holder = doc.add_paragraph()
            fmt = holder.paragraph_format
            fmt.space_before = fmt.space_after = Pt(0)
            fmt.line_spacing = Pt(1)

            holder._p.append(
                word_element(
                    "w:bookmarkStart", {"w:id": i + 1, "w:name": f"Page{i + 1}"}
                )
            )
            holder._p.append(word_element("w:bookmarkEnd", {"w:id": i + 1}))
            background_page = artwork[i]
            background_page.add_redact_annot(
                background_page.rect, fill=False, cross_out=False
            )
            background_page.apply_redactions(images=0, graphics=0, text=0)
            pix = background_page.get_pixmap(
                matrix=pymupdf.Matrix(1.75, 1.75), alpha=False
            )
            background(holder, BytesIO(pix.tobytes("png")), width, height)
            links = page.get_links()
            for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        positioned_text(doc, span, width, links)
            # Word positions floating paragraphs relative to their following body paragraph.
            # End the page before adding the next page's break and artwork.
            terminator = doc.add_paragraph()
            terminator.paragraph_format.space_before = Pt(0)
            terminator.paragraph_format.space_after = Pt(0)
            terminator.paragraph_format.line_spacing = Pt(1)
    doc.save(docx_path)
