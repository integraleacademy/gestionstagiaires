"""Shared landscape stationery. Coordinates are points from the top left of an A4 page."""

from functools import lru_cache
from io import BytesIO
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from .source import FONT_DIR, simple

ORANGE = "#C2410C"
EMPH = "#FFA165"
INK = "#282320"
WHITE = "#FFFFFF"
WARM = "#FFFAF5"
CREAM = "#FFF0E4"
HAIR = "#DECEC1"
MUTED = "#574F49"
L, R = 216, 811
BW = R - L
PALETTES = {
    "desp": (ORANGE, CREAM, INK, EMPH),
    "vae": (ORANGE, CREAM, INK, EMPH),
    "vtc": ("#7E22CE", "#F3E8FF", "#25222E", "#D7A7FF"),
    "aps": ("#1D4ED8", "#DBEAFE", "#1B2432", "#9AC1FF"),
    "a3p": ("#15803D", "#DCFCE7", "#1D2923", "#93DEA4"),
    "ssiap": ("#B91C1C", "#FEE2E2", "#2B2224", "#FFA49C"),
    "sst": ("#558538", "#EEF4DF", "#252920", "#BCD899"),
    "mac_aps": ("#173C5B", "#E1EBF0", "#18252E", "#A6C6DF"),
    "habilitation": ("#CC6B0A", "#FFF0DB", "#30281E", "#FFC27D"),
    "other": ("#375569", "#EAF0F4", "#202E38", "#B6D5E5"),
}
FONT_FILES = {
    "Bar": "Barlow-Regular.ttf",
    "BarB": "Barlow-SemiBold.ttf",
    "Cond": "BarlowCondensed-Bold.ttf",
}


@lru_cache(maxsize=1)
def register_fonts():
    for name, file in FONT_FILES.items():
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))


class LayoutDoesNotFit(ValueError):
    """An unusually large field needs the flowing page layout."""


def split_lines(value, font, size, width):
    lines = []
    for block in value.splitlines():
        words = block.split()
        if not words:
            continue
        current = words[0]
        for word in words[1:]:
            if pdfmetrics.stringWidth(current + " " + word, font, size) > width:
                lines.append(current)
                current = word
            else:
                current += " " + word
        lines.append(current)
    return lines


class Book:
    def __init__(self, ref, out, family="desp", *, canvas=None):
        register_fonts()
        self.ref = ref
        self.W, self.H = landscape(A4)
        self.c = canvas or Canvas(
            str(out), pagesize=(self.W, self.H), pageCompression=1
        )
        if canvas is None:
            self.c.setTitle("Convocation · Intégrale Academy")
            self.c.setAuthor("Intégrale Academy")
        self.accent, self.light, self.ink, self.bright = PALETTES.get(
            family, PALETTES["other"]
        )
        self.n = 0
        self.source_page = 0
        self.total = len(ref.pages)
        self.image_cache = {}

    def rect(self, x, y, w, h, col, stroke=None, width=0.8):
        c = self.c
        c.saveState()
        c.setLineWidth(width)
        if col:
            c.setFillColor(HexColor(col))
        if stroke:
            c.setStrokeColor(HexColor(stroke))
        c.rect(x, self.H - y - h, w, h, fill=bool(col), stroke=bool(stroke))
        c.restoreState()

    def line(self, x, y, x2, y2, col=HAIR, width=0.7):
        c = self.c
        c.saveState()
        c.setStrokeColor(HexColor(col))
        c.setLineWidth(width)
        c.line(x, self.H - y, x2, self.H - y2)
        c.restoreState()

    def txt(self, x, b, s, font, size, col=INK):
        c = self.c
        c.saveState()
        c.setFont(font, size)
        c.setFillColor(HexColor(col))
        c.drawString(x, self.H - b, s)
        c.restoreState()

    def paragraph(self, x, top, w, text, font, size, col=INK, leading=None):
        leading = leading or size * 1.29
        lines = split_lines(text, font, size, w)
        for i, line in enumerate(lines):
            width = pdfmetrics.stringWidth(line, font, size)
            if width > w + 0.25:
                raise LayoutDoesNotFit("Champ sans coupure plus large que sa colonne")
            self.txt(x, top + size + i * leading, line, font, size, col)
        return top + size + max(0, len(lines) - 1) * leading

    def emit(self, i, x, y, w, font="Bar", size=11.5, col=INK, leading=None):
        if i != self.next or i >= len(self.items):
            raise LayoutDoesNotFit("Structure du modèle personnalisée")
        self.next += 1
        return self.paragraph(x, y, w, self.items[i], font, size, col, leading)

    def bitmap(self, pic, x, y, w, h=None):
        key = id(pic)
        if key not in self.image_cache:
            self.image_cache[key] = ImageReader(BytesIO(pic.data))
        h = h or w * pic.height / pic.width
        self.c.drawImage(self.image_cache[key], x, self.H - y - h, w, h, mask="auto")
        return y + h

    def img(self, name, x, y, w):
        if name == "logo.png":
            self.c.drawImage(str(self.ref.logo), x, self.H - y - w, w, w, mask="auto")
            return y + w
        dims = {
            "plan-paris.png": (1800, 956),
            "cachet.png": (1174, 410),
            "signature.png": (241, 134),
        }
        key = dims[name]
        pic = next(
            (
                p
                for page in self.ref.blocks
                for b in page
                for p in b.pictures
                if (p.width, p.height) == key
            ),
            None,
        )
        if pic is None:
            raise LayoutDoesNotFit("Visuel de convocation personnalisé")
        return self.bitmap(pic, x, y, w)

    def link(self, x, y, w, h, url):
        if not url:
            return
        bounds = (x, self.H - y - h, x + w, self.H - y)
        if url.startswith("#"):
            self.c.linkRect("", url[1:], bounds, relative=0, thickness=0)
        else:
            self.c.linkURL(url, bounds, relative=0, thickness=0)

    def printed_link(self, i, x, y, w, url, size=11):
        width = pdfmetrics.stringWidth(simple(self.items[i]), "BarB", size)
        end = self.emit(i, x, y, w, "BarB", size, self.accent)
        self.line(x, end + 2, x + width, end + 2, self.accent, 0.65)
        self.link(x, y - 1, width, end + 4 - y, url)
        return end

    def qr(self, x, y, w):
        pic = next(
            p for b in self.ref.blocks[-1] for p in b.pictures if "QR" in p.description
        )
        self.bitmap(pic, x, y, w)
        self.link(x, y, w, w, self.ref.maps)

    def signature(self, x, y, size=137):
        self.img("signature.png", x, y + 2, 77)
        self.img("cachet.png", x + 89, y, size)

    def footer(self):
        y = self.H - 60
        self.rect(0, y, self.W, 60, WHITE)
        self.line(33, y, self.W - 33, y)
        name, contacts = (self.ref.footer_contact + ["", ""])[:2]
        self.txt(33, y + 14, name, "BarB", 9.2)
        self.txt(
            46 + pdfmetrics.stringWidth(name, "BarB", 9.2),
            y + 14,
            contacts,
            "Bar",
            8.6,
            MUTED,
        )
        folio = f"{self.n} / {self.total}"
        self.txt(
            self.W - 33 - pdfmetrics.stringWidth(folio, "BarB", 9.1),
            y + 14,
            folio,
            "BarB",
            9.1,
        )
        lines = self.ref.legal
        top = y + 21
        for s in lines[:2]:
            top = self.paragraph(33, top, 450, s, "Bar", 7.7, MUTED, 8.5) + 3
        if len(lines) > 2:
            self.paragraph(
                492, y + 22, self.W - 525, " ".join(lines[2:]), "Bar", 7.6, MUTED, 9.25
            )

    def begin(self, cover=False, *, items=None, outline=None):
        self.n += 1
        if items is None:
            items = self.ref.pages[self.source_page]
            self.source_page += 1
        if (
            not cover
            and len(items) >= 2
            and items[1].casefold()
            in {
                "convocation officielle en formation",
                "convocation officielle à l’examen",
                "convocation officielle formation pratique",
                "règles de vie en formation",
                "documents administratifs",
                "distanciel & présentiel",
                "calendrier des examens",
            }
        ):
            items = [items[0], items[1].capitalize(), *items[2:]]
        self.items = items
        self.next = 0
        self.rect(0, 0, self.W, self.H, WHITE)
        h = (self.ref.header + ["", ""])[:2]
        if cover:
            self.rect(0, 0, 425, 359, self.ink)
            self.rect(0, 0, 425, 6, self.accent)
            self.rect(
                425, 0, self.W - 425, 359, WARM if self.accent == ORANGE else "#FBFAFA"
            )
            self.img("logo.png", 33, 26, 52)
            self.txt(108, 45, h[0], "BarB", 11.1, WHITE)
            self.txt(108, 64, h[1], "Bar", 10.6, "#F8EEE5")
        else:
            self.rect(0, 0, 191, self.H - 60, self.accent)
            self.img("logo.png", 24, 23, 48)
            self.txt(24, 96, h[0], "BarB", 9.9, WHITE)
            self.txt(24, 113, h[1], "Bar", 9.1, WHITE)
            self.line(24, 129, 168, 129, self.bright)
        self.footer()
        key = f"p{self.n}"
        self.c.bookmarkPage(key)
        title = outline or (
            simple(" ".join(self.items[1:3])) if cover else simple(self.items[1])
        )
        self.c.addOutlineEntry(title, key)

    def icon(self, key, x, y, size, col=ORANGE):
        shapes = {
            "bed": [
                [(2, 5), (2, 21)],
                [(22, 5), (22, 21)],
                [(2, 10), (22, 10)],
                [(2, 17), (22, 17)],
                [(4, 8), (8, 8)],
                [(4, 15), (8, 15)],
                [(16, 10), (16, 21)],
                [(19, 10), (19, 21)],
                [(16, 14), (19, 14)],
            ],
            "kitchen": [
                [(3, 8), (21, 8), (21, 21), (3, 21), (3, 8)],
                [(6, 5), (10, 5)],
                [(15, 5), (19, 5)],
                [(6, 12), (18, 12), (18, 18), (6, 18), (6, 12)],
            ],
            "bag": [
                [(3, 7), (21, 7), (21, 21), (3, 21), (3, 7)],
                [(8, 7), (8, 3), (16, 3), (16, 7)],
                [(7, 12), (17, 12)],
            ],
            "roll": [
                [(8, 4), (16, 4), (19, 7), (19, 15), (16, 18), (9, 18)],
                [(6, 8), (6, 21), (15, 21), (15, 8)],
                [(8, 14), (12, 14)],
            ],
            "clean": [
                [(13, 2), (13, 11)],
                [(8, 11), (17, 11), (21, 21), (4, 21), (8, 11)],
                [(10, 15), (8, 20)],
                [(14, 15), (15, 20)],
            ],
            "calendar": [
                [(3, 5), (21, 5), (21, 21), (3, 21), (3, 5)],
                [(3, 10), (21, 10)],
                [(7, 2), (7, 7)],
                [(17, 2), (17, 7)],
            ],
            "laptop": [
                [(4, 4), (20, 4), (20, 16), (4, 16), (4, 4)],
                [(4, 16), (1, 20), (23, 20), (20, 16)],
            ],
            "building": [
                [(2, 21), (22, 21)],
                [(5, 21), (5, 8), (12, 3), (19, 8), (19, 21)],
                [(9, 10), (9, 12)],
                [(15, 10), (15, 12)],
                [(10, 21), (10, 16), (14, 16), (14, 21)],
            ],
            "pin": [[(5, 11), (6, 15), (12, 22), (18, 15), (19, 11)]],
            "parking": [
                [
                    (4, 2),
                    (20, 2),
                    (22, 4),
                    (22, 20),
                    (20, 22),
                    (4, 22),
                    (2, 20),
                    (2, 4),
                    (4, 2),
                ],
                [(9, 18), (9, 6), (14, 6), (17, 8), (17, 11), (14, 13), (9, 13)],
            ],
            "shirt": [
                [
                    (8, 3),
                    (3, 5),
                    (1, 10),
                    (5, 12),
                    (6, 10),
                    (6, 21),
                    (18, 21),
                    (18, 10),
                    (19, 12),
                    (23, 10),
                    (21, 5),
                    (16, 3),
                    (15, 5),
                    (12, 6),
                    (9, 5),
                    (8, 3),
                ]
            ],
            "list": [[(8, 6), (21, 6)], [(8, 12), (21, 12)], [(8, 18), (21, 18)]],
            "paper": [
                [(5, 2), (15, 2), (19, 6), (19, 22), (5, 22), (5, 2)],
                [(14, 2), (14, 7), (19, 7)],
                [(8, 12), (16, 12)],
                [(8, 16), (15, 16)],
            ],
            "mail": [
                [(2, 5), (22, 5), (22, 19), (2, 19), (2, 5)],
                [(2, 6), (12, 13), (22, 6)],
            ],
            "clock": [[(12, 6), (12, 12), (17, 15)]],
            "train": [
                [(5, 3), (19, 3), (19, 17), (5, 17), (5, 3)],
                [(5, 10), (19, 10)],
                [(7, 17), (4, 21)],
                [(17, 17), (20, 21)],
                [(7, 20), (17, 20)],
            ],
            "people": [
                [(2, 21), (2, 18), (5, 15), (12, 15), (15, 18), (15, 21)],
                [(16, 15), (19, 15), (22, 18), (22, 21)],
            ],
            "badge": [[(7, 16), (6, 21), (11, 19), (14, 21), (16, 16)]],
        }
        circles = {
            "clock": [(12, 12, 9)],
            "pin": [(12, 9, 7), (12, 9, 2)],
            "list": [(3, 6, 1), (3, 12, 1), (3, 18, 1)],
            "people": [(8, 8, 3.5), (18, 9, 2.7)],
            "badge": [(11, 9, 6)],
            "train": [(8, 14, 1), (16, 14, 1)],
        }
        k = size / 24
        c = self.c
        c.saveState()
        c.setLineWidth(1.5 * k)
        c.setLineJoin(1)
        c.setLineCap(1)
        c.setStrokeColor(HexColor(col))
        for points in shapes.get(key, []):
            path = c.beginPath()
            path.moveTo(x + points[0][0] * k, self.H - y - points[0][1] * k)
            for px, py in points[1:]:
                path.lineTo(x + px * k, self.H - y - py * k)
            c.drawPath(path, stroke=1, fill=0)
        for cx, cy, r in circles.get(key, []):
            c.circle(x + cx * k, self.H - y - cy * k, r * k, stroke=1, fill=0)
        c.restoreState()

    def side(self, icon="paper"):
        self.emit(0, 24, 148, 146, "BarB", 8.4, WHITE, 12)
        label = self.items[1]
        size = 31 if any(c.islower() for c in label) else 23.8
        while any(pdfmetrics.stringWidth(w, "Cond", size) > 146 for w in label.split()):
            size -= 0.5
        self.emit(1, 24, 182, 146, "Cond", size, WHITE, size * 1.08)
        self.line(24, 401, 167, 401, self.bright)
        self.icon(icon, 24, 428, 37, WHITE)

    def finish(self):
        if self.next != len(self.items):
            raise LayoutDoesNotFit("Paragraphes supplémentaires dans le modèle")
        self.c.showPage()

    def save(self):
        if self.n != self.total:
            raise LayoutDoesNotFit("Pagination du modèle modifiée")
        self.c.save()


def standalone_panel(
    canvas, family, logo, brand_lines, kicker, title, *, quality_box=(33, 12, 770)
):
    """Sidebar used by standalone exam invitations, including dossier inserts."""
    register_fonts()
    color, _, _, bright = PALETTES.get(family, PALETTES["other"])
    width, height = landscape(A4)
    canvas.saveState()
    canvas.setFillColor(HexColor(color))
    canvas.rect(0, 60, 191, height - 60, stroke=0, fill=1)
    canvas.drawImage(str(logo), 24, height - 72, 48, 48, mask="auto")
    canvas.setFillColor(HexColor(WHITE))
    y = height - 93
    for line in brand_lines:
        canvas.setFont("BarB" if y == height - 93 else "Bar", 9.1)
        for chunk in split_lines(line, "Bar", 9.1, 145):
            canvas.drawString(24, y, chunk)
            y -= 13
    canvas.setStrokeColor(HexColor(bright))
    canvas.line(24, y - 5, 165, y - 5)
    canvas.setFont("BarB", 9.3)
    canvas.drawString(24, y - 32, kicker)
    y -= 67
    canvas.setFont("Cond", 26)
    for line in split_lines(title, "Cond", 26, 145):
        canvas.drawString(24, y, line)
        y -= 29
    canvas.setFillColor(HexColor("#506477"))
    x, baseline, width = quality_box
    canvas.setFont("Bar", 8)
    label = "Qualiopi · Actions de formation, actions de formation par apprentissage et actions permettant de faire valider les acquis de l’expérience (VAE)."
    for line in split_lines(label, "Bar", 8, width):
        canvas.drawString(x, baseline, line)
        baseline -= 10
    canvas.restoreState()
