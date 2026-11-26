"""In-person venue for Intégrale Academy's initial DESP sessions in Paris."""
from datetime import date, datetime
from pathlib import Path
import re

from campus import INTEGRALE_PARTNER_ID
import security_exam_jury

FIRST_SESSION = date(2027, 1, 1)
LEGACY = "Atelier Modulable – 53 rue des Vinaigriers 75010 PARIS"
NAME = "Intégrale Academy"
STREET = "34 rue Poissonnière"
CITY = "75002 Paris"
LANDMARK = "à 50 mètres du Grand Rex"
ADDRESS = f"{STREET} {CITY} - {LANDMARK}"
FULL_ADDRESS = f"{NAME} {ADDRESS}"
ENTRANCE = "Bâtiment B, 1er étage"
WALK = ("À la sortie 1, longez le boulevard jusqu’au Grand Rex. Prenez la rue Poissonnière "
        "sur le côté du cinéma et continuez jusqu’au n° 34.")
PRIMARY_METRO = "Bonne Nouvelle · lignes 8 et 9 · sortie 1 « Rue du Sentier »"
OTHER_METROS = "Grands Boulevards · lignes 8 et 9 · sortie 5 « Rue Saint-Fiacre »"
SENTIER = "Sentier · ligne 3"
BUS = "Poissonnière – Bonne Nouvelle · lignes 20, 32 et 39"
PARKING = "Parking Rex Atrium, 5–7 rue du Faubourg Poissonnière, Paris 9e"
DIRECTIONS_URL = "https://www.google.com/maps/dir/?api=1&destination=34+rue+Poissonni%C3%A8re%2C+75002+Paris"
MAP_FILE = "images/desp-paris-acces.png"
STATIC_DIR = Path(__file__).with_name("static")
MAP_PATH = STATIC_DIR / MAP_FILE


def is_paris(training):
    # The planning sync stores the centre separately even for an unnamed city in the title.
    centre = training.get("crm_center") or training.get("centre") or training.get("center")
    descriptor = centre or " ".join(str(training.get(key) or "") for key in
                                    ("training_type", "type_formation", "type", "name", "nom"))
    return bool(re.search(r"\bParis\b", str(descriptor), re.I))


def applies(training):
    if (not training or not is_paris(training)
            or training.get("partner_id") not in (None, "", INTEGRALE_PARTNER_ID)
            or security_exam_jury.level(training) != "DESP initial"):
        return False
    # DESP starts with distance learning. Historical records may carry only the global start.
    start = training.get("dirigeant_remote_start") or training.get("date_start") or training.get("date_debut")
    raw = str(start or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw[:10], fmt).date() >= FIRST_SESSION
        except ValueError:
            continue
    return False


def old_or_default_address(value):
    text = str(value or "").strip().casefold()
    return (text in ("", "à préciser", "paris", "intégrale academy", "intégrale academy – paris")
            or any(part in text for part in ("vinaigriers", "atelier modulable", "villa de lourcine", "carreou")))


def document_context(training):
    if applies(training):
        return {"lieu_presentiel_paris": FULL_ADDRESS, "lieu_formation": FULL_ADDRESS,
                "lieu_examen": FULL_ADDRESS}
    return {"lieu_presentiel_paris": LEGACY}


def access_details():
    return dict(name=NAME, street=STREET, city=CITY, landmark=LANDMARK, entrance=ENTRANCE,
                walk=WALK, metro=PRIMARY_METRO, other_metro=OTHER_METROS, sentier=SENTIER,
                bus=BUS, parking=PARKING, url=DIRECTIONS_URL, map_file=MAP_FILE)


def set_training_header(document):
    """Replace the legacy Paris letterhead that prints rue de Rivoli on every page."""
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    section = document.sections[0]
    section.header_distance = Cm(.7)
    section.top_margin = Cm(3.55)
    header = section.header
    for node in list(header._element):
        header._element.remove(node)
    table = header.add_table(1, 2, width=section.page_width - section.left_margin - section.right_margin)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    logo, info = table.rows[0].cells
    for column, cell, width in zip(table.columns, (logo, info),
                                   (Cm(4.9), section.page_width - section.left_margin - section.right_margin - Cm(4.9))):
        column.width = cell.width = width
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    shade = OxmlElement("w:shd")
    shade.set(qn("w:fill"), "172F3F")
    logo._tc.get_or_add_tcPr().append(shade)
    p = logo.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(0)
    p.add_run().add_picture(str(STATIC_DIR / "parcours-alternance" / "logo.png"), width=Cm(4.2))
    lines = (("Centre de formation OF-CFA agréé · Paris", 9, True),
             (STREET + " · " + CITY, 12, True),
             ("04 22 47 07 68 · ecole@integraleacademy.com", 8, False),
             ("SIRET 840 899 884 00034 · APE 8559A · NDA 93830600283 · UAI 0756548K", 7, False))
    for i, (value, size, bold) in enumerate(lines):
        p = info.add_paragraph() if i else info.paragraphs[0]
        p.paragraph_format.left_indent = Cm(.22)
        p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1
        run = p.add_run(value)
        run.font.name = "Calibri"
        run.font.size = Pt(size)
        run.bold = bold
        run.font.color.rgb = RGBColor.from_string("173645")
