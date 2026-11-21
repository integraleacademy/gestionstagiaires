"""Create self-hosted email images from existing Intégrale Academy assets.

This script is deliberately offline. Render builds the two small PNG files
after copying the repository; email templates use stable same-origin URLs.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
OUT = STATIC / "images" / "email"
AVATAR_PATH = OUT / "cpf-cassandre-avatar.png"
LOGO_PATH = OUT / "cpf-academy-wordmark.png"


def make_avatar(source: Path = OUT / "cassandre-signature.png",
                dest: Path = AVATAR_PATH) -> Path:
    # The official signature asset contains Cassandre's original memoji on
    # the upper left. Use its existing portrait, not an invented replacement.
    with Image.open(source) as original:
        face = original.convert("RGBA")
        width, height = face.size
        # Reference dimensions: 1410 × 450. Slightly generous around gold ring.
        crop = tuple(round(value * (width if n % 2 == 0 else height))
                     for n, value in enumerate((39 / 1410, 33 / 450,
                                                 215 / 1410, 209 / 450)))
        face = face.crop(crop)
        face = ImageOps.fit(face, (256, 256), method=Image.Resampling.LANCZOS)
        mask = Image.new("L", (256, 256))
        ImageDraw.Draw(mask).ellipse((0, 0, 255, 255), fill=255)
        face.putalpha(mask)
        dest.parent.mkdir(parents=True, exist_ok=True)
        face.save(dest, format="PNG", optimize=True)
    return dest


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make_wordmark(source: Path = STATIC / "logo-integrale.png",
                  dest: Path = LOGO_PATH) -> Path:
    """Brand's real mark plus a high-contrast wordmark for the navy email hero."""
    with Image.open(source) as base:
        original = base.convert("RGBA")
        # Render at 2× for sharp text at the email's displayed width.
        icon = ImageOps.fit(original, (216, 216), method=Image.Resampling.LANCZOS)
        mask = Image.new("L", icon.size)
        ImageDraw.Draw(mask).ellipse((1, 1, 214, 214), fill=255)
        icon.putalpha(mask)
        result = Image.new("RGBA", (1110, 250), (0, 0, 0, 0))
        result.alpha_composite(icon, (5, 17))
        draw = ImageDraw.Draw(result)
        draw.text((258, 38), "INTÉGRALE", font=_font(89), fill=(255, 255, 255, 255))
        draw.text((258, 134), "ACADEMY", font=_font(82), fill=(248, 203, 108, 255))
        dest.parent.mkdir(parents=True, exist_ok=True)
        result.save(dest, format="PNG", optimize=True)
    return dest


def build():
    return make_avatar(), make_wordmark()


if __name__ == "__main__":
    for output in build():
        with Image.open(output) as picture:
            picture.verify()
        print("EDOF CPF email asset OK:", output.relative_to(ROOT))
