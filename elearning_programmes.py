"""Published course programmes shared by the catalogue and learner reports."""
from pathlib import Path

from flask import abort, send_file


PROGRAMMES = {
    "aps": {
        "path": Path(__file__).resolve().parent / "documents" / "elearning" / "programme-aps-62h-integrale-connect.pdf",
        "filename": "Programme_E-learning_APS_62h_Integrale_Connect.pdf",
        "title": "Programme APS · 62 h",
        "description": "Le détail des 15 modules et des 62 séquences, les correspondances ADEF et les heures à prévoir en ligne et en présentiel.",
    },
}


def programme_download(code):
    programme = PROGRAMMES.get(code)
    if not programme or not programme["path"].is_file():
        abort(404)
    return send_file(programme["path"], mimetype="application/pdf", as_attachment=True,
                     download_name=programme["filename"], max_age=0)
