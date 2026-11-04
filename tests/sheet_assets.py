"""Load the JS and CSS linked by a trainee sheet for source-level UI tests."""
from pathlib import Path


def with_sheet_assets(markup):
    root = Path(__file__).resolve().parents[1] / "static"
    for name in ("css/trainee-sheet.css", "js/trainee-sheet.js"):
        if name in markup:
            markup += "\n" + (root / name).read_text(encoding="utf-8")
    return markup
