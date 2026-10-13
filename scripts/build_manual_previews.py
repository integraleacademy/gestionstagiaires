"""Extract selected public pages from privately held specimen source PDFs.

Usage: python scripts/build_manual_previews.py /path/to/private/source-pdfs
Full sources must never be copied back into static/.
"""
from pathlib import Path
import sys

import fitz


# One-based PDF positions, not printed folios. Existing specimen watermarks stay.
SAMPLES = {
    "ssiap1": ("specimenssiap.pdf", [1, 6, 11, 12, 13, 14, 29, 30, 45, 46]),
    "aps": ("specimenaps.pdf", [1, 6, 11, 12, 30, 31, 60, 61, 100, 101]),
    "a3p": ("specimena3p.pdf", [1, 6, 11, 12, 30, 31, 60, 61, 99, 100]),
    "vtc": ("specimenvtc.pdf", [4, 5, 6, 7, 8, 9, 14, 15, 16, 101]),
    "dssp": ("specimendssp.pdf", [1, 6, 7, 8, 12, 13, 29, 30, 59, 60]),
    "sst": ("specimensst.pdf", [1, 5, 6, 7, 8, 9, 10, 18, 23, 30]),
}


def build(source_dir, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    for code, (source_name, selected) in SAMPLES.items():
        with fitz.open(source_dir / source_name) as source, fitz.open() as sample:
            for number in selected:
                sample.insert_pdf(source, from_page=number - 1, to_page=number - 1,
                                  links=False, annots=False, widgets=False)
            sample.set_metadata({"title": f"Manuel {code.upper()} - Extrait de 10 pages",
                                 "author": "Intégrale Academy",
                                 "subject": "Spécimen - Reproduction interdite"})
            # Write a new document, not an incremental save of the full source.
            target = output_dir / f"{code}-10-pages.pdf"
            sample.save(target, garbage=4, clean=True, deflate=True)
        with fitz.open(target) as check:
            assert len(check) == 10 and check.embfile_count() == 0
        print(f"{target.name}: 10 pages")


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(__file__).resolve().parents[1] / "static/manuals/specimens")
