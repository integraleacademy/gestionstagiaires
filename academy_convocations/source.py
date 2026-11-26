"""Read the personalized Word model in document order, including merged tables and links."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from docx.oxml.ns import qn
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = ROOT / "static/fonts/convocations"
PORTAL = "https://integraleconnect.com/espacestagiaire"


def simple(value):
    return " ".join(value.split())


def paragraph_text(paragraph):
    pieces = []
    for node in paragraph.xpath('.//w:t|.//w:br[not(@w:type="page")]|.//w:tab'):
        pieces.append(
            node.text or ""
            if node.tag == qn("w:t")
            else "\n"
            if node.tag == qn("w:br")
            else " "
        )
    return "\n".join(
        simple(line) for line in "".join(pieces).splitlines() if line.strip()
    )


@dataclass
class Picture:
    data: bytes
    description: str
    width: int
    height: int


@dataclass
class Cell:
    paragraphs: list
    pictures: list


class Block:
    def __init__(self, rows):
        self.rows = rows
        self.text = [p for row in rows for cell in row for p in cell.paragraphs]
        self.pictures = [p for row in rows for cell in row for p in cell.pictures]


class Source:
    def __init__(self, document):
        self.document = document
        self.links = {}
        self.blocks = [[]]
        for item in document.element.body:
            if item.tag == qn("w:tbl"):
                rows = [
                    [self.cell(tc, document.part) for tc in tr.xpath("./w:tc")]
                    for tr in item.xpath("./w:tr")
                ]
            elif item.tag == qn("w:p"):
                rows = [[self.cell(item, document.part)]]
            else:
                continue
            block = Block(rows)
            if block.text or block.pictures:
                self.blocks[-1].append(block)
            if item.xpath('.//w:br[@w:type="page"]') and self.blocks[-1]:
                self.blocks.append([])
        self.blocks = [page for page in self.blocks if page]
        self.pages = [[p for b in page for p in b.text] for page in self.blocks]
        section = document.sections[0]
        self.header = [
            t
            for p in section.header._element.xpath(".//w:p")
            if (t := paragraph_text(p))
        ]
        foot = [
            t
            for p in section.footer._element.xpath(".//w:p")
            if (t := paragraph_text(p))
        ]
        contact = re.sub(r"\s*\d*\s*/\s*\d*\s*$", "", foot[0]) if foot else ""
        self.footer_contact = (
            [s.strip() for s in re.split(r"(?=04 22 47 07 68)", contact, 1)]
            if contact
            else []
        )
        self.legal = foot[1:]
        self.portal = PORTAL
        self.maps = next((v for v in self.links.values() if "google.com/maps" in v), "")
        self.logo = ROOT / "static/logo-integrale.png"

    def cell(self, element, part):
        paragraphs = [element] if element.tag == qn("w:p") else element.xpath(".//w:p")
        texts = [s for p in paragraphs if (s := paragraph_text(p))]
        for link in element.xpath(".//w:hyperlink[@r:id]"):
            rid = link.get(qn("r:id"))
            if rid in part.rels and part.rels[rid].is_external:
                self.links[simple("".join(link.xpath(".//w:t/text()")))] = part.rels[
                    rid
                ].target_ref
        pictures = []
        for shape in element.xpath(".//wp:inline|.//wp:anchor"):
            blips = shape.xpath(".//a:blip")
            if not blips:
                continue
            ident = blips[0].get(qn("r:embed"))
            if not ident or ident not in part.related_parts:
                continue
            binary = part.related_parts[ident].blob
            with Image.open(BytesIO(binary)) as im:
                width, height = im.size
            props = shape.xpath("./wp:docPr")
            pictures.append(
                Picture(
                    binary,
                    (props[0].get("descr") or "") if props else "",
                    width,
                    height,
                )
            )
        return Cell(texts, pictures)
