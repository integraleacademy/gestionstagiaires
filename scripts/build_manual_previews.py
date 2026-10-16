"""Build curated public samples from privately held source PDFs.

Usage: python scripts/build_manual_previews.py PRIVATE_DIR [OTHER_PRIVATE_DIR]
Requires PyMuPDF and Pillow. Full sources must never be copied into static/.
Each public page is flattened separately: unused PDF resources, attachments,
links, annotations, and unselected pages cannot travel into the public sample.
"""
from pathlib import Path
import argparse
import io
import sys

import fitz
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from manuals_preview_selection import PREVIEW_SELECTIONS, preview_filename


def build(source_dirs, review_dir=None):
    for code, selection in PREVIEW_SELECTIONS.items():
        source_path = next((folder / selection['source'] for folder in source_dirs
                            if (folder / selection['source']).is_file()), None)
        if source_path is None:
            raise FileNotFoundError(selection['source'])
        selected = selection['pages']
        assert 1 <= len(selected) <= 20 and len(set(selected)) == len(selected)
        assert all(number in selected for number, _ in selection['gallery'])
        images = {}
        with fitz.open(source_path) as source, fitz.open() as sample:
            assert max(selected) <= len(source)
            for number in selected:
                page = source[number - 1]
                if not selection.get('watermarked'):
                    center = page.rect.tl + (page.rect.br - page.rect.tl) * .5
                    size = page.rect.width / 9
                    point = fitz.Point(center.x - size * 2.4, center.y)
                    page.insert_text(point, 'SPECIMEN', fontsize=size, fontname='hebo',
                                     color=(.15, .24, .36), fill_opacity=.14,
                                     morph=(point, fitz.Matrix(30)))
                    page.insert_text((18, page.rect.height - 11),
                                     'EXTRAIT DE DEMONSTRATION - REPRODUCTION INTERDITE',
                                     fontsize=5.5, color=(.25, .32, .4))
                pix = page.get_pixmap(dpi=150, alpha=False, colorspace=fitz.csRGB)
                bitmap = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
                images[number] = bitmap
                jpeg = io.BytesIO()
                bitmap.save(jpeg, 'JPEG', quality=84, optimize=True)
                exported = sample.new_page(width=page.rect.width, height=page.rect.height)
                exported.insert_image(exported.rect, stream=jpeg.getvalue())
            sample.set_metadata({
                'title': f"{code.upper()} - {'Exemples' if selection.get('examples') else 'Extrait'} de {len(selected)} pages",
                'author': 'Intégrale Academy',
                'subject': 'Specimen - Reproduction interdite',
                'keywords': 'Pages selectionnees : ' + ', '.join(map(str, selected)),
            })
            output = ROOT / 'static' / preview_filename(code)
            output.parent.mkdir(parents=True, exist_ok=True)
            sample.save(output, garbage=4, deflate=True)
        with fitz.open(output) as check:
            assert len(check) == len(selected) and check.embfile_count() == 0
            assert all(len(page.get_images()) == 1 for page in check)
        for index, (number, _) in enumerate(selection['gallery'], 1):
            images[number].save(ROOT / f'static/manuals/previews/{code}-{index}.webp',
                                'WEBP', quality=88, method=6)
        if review_dir:
            review_dir.mkdir(parents=True, exist_ok=True)
            cols = min(5, len(selected))
            rows = (len(selected) + cols - 1) // cols
            sheet = Image.new('RGB', (cols * 250, rows * 370), '#e9edf2')
            draw = ImageDraw.Draw(sheet)
            for i, number in enumerate(selected):
                image = images[number].copy()
                image.thumbnail((230, 335))
                x, y = (i % cols) * 250 + 10, (i // cols) * 370 + 10
                sheet.paste(image, (x, y))
                draw.text((x, y + 340), f'{code} - source p. {number}', fill='black')
            sheet.save(review_dir / f'{code}.jpg', quality=90)
        print(f'{code}: {len(selected)} pages, {output.stat().st_size // 1024} Ko')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_dirs', type=Path, nargs='+')
    parser.add_argument('--review-dir', type=Path)
    args = parser.parse_args()
    build(args.source_dirs, args.review_dir)
