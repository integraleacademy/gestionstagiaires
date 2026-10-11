"""Two original diagrams using only the reviewed C.04 / C.06 lesson notions."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'elearning_native/vtc/assets/media/vtc/v11'
FONT = ROOT / 'scripts/academy_videos/assets/Manrope-600.ttf'
BOLD = FONT.with_name('Manrope-800.ttf')
SCALE = 2
BG, INK, PURPLE, SOFT = '#f8f5fd', '#281c3a', '#7045bd', '#eee6f8'


class Diagram:
    def __init__(self):
        self.image = Image.new('RGB', (800*SCALE, 800*SCALE), BG)
        self.draw = ImageDraw.Draw(self.image)

    @staticmethod
    def box(coords):
        return tuple(round(x*SCALE) for x in coords)

    def rect(self, bounds, radius=0, fill=SOFT, outline=None, width=1):
        self.draw.rounded_rectangle(self.box(bounds), radius*SCALE,
                                    fill=fill, outline=outline, width=width*SCALE)

    def ellipse(self, bounds, fill, outline=None, width=1):
        self.draw.ellipse(self.box(bounds), fill=fill, outline=outline, width=width*SCALE)

    def line(self, coords, fill, width=8):
        self.draw.line(self.box(coords), fill=fill, width=width*SCALE, joint='curve')

    def polygon(self, points, fill):
        self.draw.polygon([self.box(point) for point in points], fill=fill)

    def text(self, value, x, y, size, width, bold=False, color=INK, centered=False):
        font = ImageFont.truetype(str(BOLD if bold else FONT), size*SCALE)
        measured = self.draw.textlength(value, font=font)/SCALE
        assert measured <= width, (value, measured, width)
        if centered:
            x += (width-measured)/2
        self.draw.text(self.box((x, y)), value, font=font, fill=color)

    def save(self, filename):
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / filename
        self.image.resize((800, 800), Image.Resampling.LANCZOS).save(path, optimize=True)
        return path


def blind_spots():
    d = Diagram()
    d.text('Angles morts', 48, 18, 70, 704, True, centered=True)
    # Illustrative shaded zones, with no claimed angle or distance.
    d.polygon([(287, 266), (83, 382), (77, 579), (286, 456)], '#f3d7a2')
    d.polygon([(477, 266), (680, 382), (687, 579), (478, 456)], '#f3d7a2')
    d.line((287, 266, 83, 382), '#b07929', 5)
    d.line((477, 266, 680, 382), '#b07929', 5)
    d.rect((302, 150, 462, 540), 54, '#53647e')
    d.rect((278, 241, 311, 271), 9, '#34435b')
    d.rect((453, 241, 486, 271), 9, '#34435b')
    d.rect((316, 200, 448, 402), 23, '#b9c6da')
    d.polygon([(325, 179), (439, 179), (448, 221), (316, 221)], '#dde6f1')
    d.rect((319, 426, 445, 478), 12, '#d1dbe9')
    d.line((382, 326, 382, 255), '#ffffff', 13)
    d.polygon([(382, 241), (353, 272), (411, 272)], '#ffffff')
    d.text('Rétroviseurs + contrôle', 36, 625, 54, 728, True, color=PURPLE, centered=True)
    d.text('adapté avant de se déporter', 36, 695, 46, 728, True, centered=True)
    return d.save('illustration-c-04-angles-morts.png')


def restraints():
    d = Diagram()
    d.text('Installer les', 40, 30, 64, 720, True, centered=True)
    d.text('passagers', 40, 104, 64, 720, True, centered=True)
    d.rect((32, 204, 386, 626), 28, '#eee6f8')
    d.rect((414, 204, 768, 626), 28, '#eee6f8')
    # Symbolic front views; no model-specific installation or new legal rule.
    d.rect((111, 232, 307, 475), 51, '#657693')
    d.ellipse((171, 249, 247, 325), '#f8f5fd')
    d.rect((156, 335, 262, 448), 35, '#f8f5fd')
    d.line((275, 329, 167, 436), PURPLE, 23)
    d.line((154, 437, 265, 437), PURPLE, 20)
    d.rect((196, 425, 224, 449), 4, '#281c3a')
    # The spoken lesson requires following the seat and vehicle notices.
    d.rect((480, 234, 705, 475), 67, '#7e64a8')
    d.rect((508, 267, 676, 460), 42, '#d9c9ed')
    d.ellipse((557, 289, 627, 359), BG)
    d.rect((548, 366, 636, 457), 30, BG)
    d.line((560, 364, 592, 423, 624, 364), PURPLE, 17)
    d.line((592, 423, 592, 458), PURPLE, 16)
    d.ellipse((577, 412, 607, 442), '#281c3a')
    d.text('Ceinture', 44, 510, 56, 330, True, centered=True)
    d.text('Siège', 426, 496, 53, 330, True, centered=True)
    d.text('adapté', 426, 549, 53, 330, True, centered=True)
    d.text('Préparer dès', 40, 639, 57, 720, True, centered=True)
    d.text('la réservation', 40, 705, 57, 720, True, centered=True)
    return d.save('illustration-c-06-retenue.png')


if __name__ == '__main__':
    for path in (blind_spots(), restraints()):
        print(path)
