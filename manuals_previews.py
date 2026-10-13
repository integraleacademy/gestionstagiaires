"""Public samples contain at most ten pages, including at their old URLs."""
from functools import lru_cache
from pathlib import Path
import posixpath

from flask import abort, redirect, request, url_for
from pypdf import PdfReader

from manuals_presentation import PRESENTATIONS

MAX_PREVIEW_PAGES = 10
LEGACY_SPECIMENS = {
    "specimenssiap.pdf": "ssiap1",
    "specimenaps.pdf": "aps",
    "specimena3p.pdf": "a3p",
    "specimenvtc.pdf": "vtc",
    "specimendssp.pdf": "dssp",
    "specimensst.pdf": "sst",
}


def preview_path():
    if request.endpoint != "static":
        return None
    filename = posixpath.normpath((request.view_args or {}).get("filename", ""))
    if filename.startswith("manuals/specimens/") or (
        filename.startswith("specimen") and filename.endswith(".pdf")
    ):
        return filename
    return None


@lru_cache(maxsize=32)
def _page_count(path, modified_ns, size):
    # The file version is part of the key: a replacement is checked again.
    with open(path, "rb") as stream:
        return len(PdfReader(stream).pages)


def register(app):
    allowed = {
        book["specimen"]: book["specimen_pages"]
        for book in PRESENTATIONS.values() if book.get("specimen")
    }

    @app.before_request
    def limited_manual_samples():
        filename = preview_path()
        if filename is None:
            return None
        if filename in LEGACY_SPECIMENS:
            code = LEGACY_SPECIMENS[filename]
            return redirect(url_for("static", filename=PRESENTATIONS[code]["specimen"]), code=308)
        if filename not in allowed:
            abort(404)
        path = Path(app.static_folder) / filename
        try:
            stat = path.stat()
            pages = _page_count(str(path), stat.st_mtime_ns, stat.st_size)
        except Exception:
            app.logger.warning("manual_preview_unavailable: %s", filename)
            abort(404)
        # Fail closed if a full book is accidentally uploaded as a sample.
        if pages != allowed[filename] or not 1 <= pages <= MAX_PREVIEW_PAGES:
            app.logger.error("manual_preview_page_limit: %s", filename)
            abort(404)

    @app.after_request
    def manual_sample_headers(response):
        if preview_path() is not None:
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response
