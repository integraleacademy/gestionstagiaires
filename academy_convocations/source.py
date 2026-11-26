"""Read the personalized Word model in document order, including merged tables and links."""

from dataclasses import dataclass
from functools import lru_cache
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
        self.agenda = None
        self.puget_parking = False
        self.venue_stamp = None
        self.course_label = "FORMATION PROFESSIONNELLE"
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


@lru_cache(maxsize=1)
def puget_model():
    from docx import Document

    return Source(Document(ROOT / "templates_word" / "convocationaps.docx"))


def use_puget_plan(source, template_name, site):
    """Use the verified Puget plan only for the actual centre or its existing access page."""
    from unicodedata import normalize

    venue = normalize("NFKD", site or "").encode("ascii", "ignore").decode().lower()
    words = " ".join(re.findall(r"[a-z0-9]+", venue))
    local = words in {
        "puget",
        "puget sur argens",
        "centre de puget sur argens",
    } or bool(re.search(r"54 (?:chemin|ch) du carreou", words) and "puget" in words)
    prior = bool(
        source.blocks
        and any(
            pic.description.startswith("Schéma des parkings de Puget")
            for block in source.blocks[-1]
            for pic in block.pictures
        )
        and "PARKING" in " ".join(source.pages[-1][:2]).upper()
    )
    if template_name == "convocationformation.docx":
        if local:
            source.venue_stamp = puget_model().blocks[1][-1].pictures[-1]
        elif "34 rue poissonniere" in words and "paris" in words:
            path = ROOT / "templates_word" / "cachet-paris-2027.png"
            with Image.open(path) as im:
                source.venue_stamp = Picture(
                    path.read_bytes(), "Cachet Intégrale Academy Paris", *im.size
                )
    if not prior and not (local and template_name == "convocationformation.docx"):
        return
    reference = puget_model()
    position = len(source.pages) - int(prior)
    source.blocks[position:] = [reference.blocks[-1]]
    page = list(reference.pages[-1])
    if prior:
        page[3] = next(
            (s for s in source.pages[-1] if s.startswith("Adresse")), page[3]
        )
    source.pages[position:] = [page]
    source.links.update(
        {s: reference.links[s] for s in reference.pages[-1] if s in reference.links}
    )
    source.maps = reference.maps
    source.puget_parking = True


def add_director_signature(document):
    """Use the same director's signature and centre stamp as the signed training letters."""
    from docx.shared import Pt

    cell = document.add_table(rows=1, cols=1).cell(0, 0)
    cell.paragraphs[0].add_run("Monsieur Clément VAILLANT")
    cell.add_paragraph("Directeur général Intégrale Academy")
    para = cell.add_paragraph()
    for pic, width in zip(puget_model().blocks[1][-1].pictures, (77, 135)):
        para.add_run().add_picture(BytesIO(pic.data), width=Pt(width))
