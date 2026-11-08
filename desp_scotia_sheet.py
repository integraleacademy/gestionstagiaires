"""Print the same two completed forms the candidate and the school can open."""
from base64 import b64encode
from io import BytesIO
from pathlib import Path

from flask import render_template
from werkzeug.exceptions import HTTPException

import identity_photos


def portrait(host, trainee):
    token = trainee.get("identity_photo")
    if not token:
        return b""
    try:
        photo, _ = identity_photos.load_photo(host, token, max_size=800)
    except (ValueError, HTTPException):
        return b""
    output = BytesIO()
    photo.save(output, format="JPEG", quality=88)
    return output.getvalue()


def _data_url(raw, kind):
    return f"data:image/{kind};base64," + b64encode(raw).decode("ascii")


def _pdf(markup):
    from weasyprint import HTML
    from weasyprint.urls import URLFetcher

    # Only the two local logos and the authorized portrait are embedded in the HTML.
    return HTML(string=markup, url_fetcher=URLFetcher(allowed_protocols={"data"},
                                                      fail_on_errors=True)).write_pdf()


def candidate_pdf(host, training, trainee, photo):
    logo = Path(host.app.static_folder) / "scotia.png"
    return _pdf(render_template(
        "public_candidate_sheet_form.html", pdf_export=True, save_url="",
        candidate=host._build_candidate_sheet_data(training, trainee),
        photo_url=_data_url(photo, "jpeg") if photo else "",
        print_logo=_data_url(logo.read_bytes(), "png"),
    ))


def experience_pdf(host, training, trainee):
    logo = Path(host.app.static_folder) / "logo-integrale.png"
    return _pdf(host._render_professional_experience_sheet(
        training, trainee, trainee["professional_experience_sheet"],
        print_logo=_data_url(logo.read_bytes(), "png"),
    ))
