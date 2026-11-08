"""Dossier cover and named dividers for the DESP initial examination."""
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors

from security_exam_pdf import CONTACT, draw_cover_identity
from ssiap_exam_pdf import (
    W, H, M, WIDTH, NAVY, TEAL, MUTED, LIGHT, GOLD, finish, new_pdf, paragraph,
)


def _footer(canvas):
    canvas.setStrokeColor(colors.HexColor("#dce4ea"))
    canvas.line(M, 66, W - M, 66)
    paragraph(canvas, CONTACT["contact_email"] + " · " + CONTACT["contact_phone"],
              M, 50, size=8, color=MUTED)


def build(host, training, trainee, photo, sections):
    first = host.normalize_first_name(trainee.get("first_name") or "")
    last = host.normalize_last_name(trainee.get("last_name") or "")
    session_name = host._session_get(training, "name", "") or "DESP initial"
    exam = host.fr_date(host._session_get(training, "exam_date", "")) or "À renseigner"
    start = host.fr_date(host._session_get(training, "date_start", ""))
    end = host.fr_date(host._session_get(training, "date_end", ""))
    period = " au ".join(filter(None, (start, end))) or "À renseigner"
    root = host.app.root_path
    canvas, output = new_pdf(f"Dossier SCOTIA · {first} {last}")
    draw_cover_identity(canvas, trainee, root, BytesIO(photo) if photo else None,
                        title="Dossier SCOTIA", acronym="DESP", qualification="Dirigeant d’entreprise de sécurité privée",
                        first_name=first, last_name=last)
    logo = str(Path(host.app.static_folder) / "scotia.png")
    center_x, center_y = W - M - 83, 665
    canvas.saveState()
    seal = canvas.beginPath()
    seal.circle(center_x, center_y, 54)
    canvas.clipPath(seal, stroke=0)
    canvas.drawImage(logo, center_x - 64, center_y - 62, 128, 124,
                     preserveAspectRatio=True, anchor="c", mask="auto")
    canvas.restoreState()
    paragraph(canvas, "SESSION", M, 386, size=8, color=TEAL, bold=True)
    paragraph(canvas, session_name, M, 369, size=15, bold=True)
    paragraph(canvas, "PÉRIODE DE FORMATION", M, 313, 255, 8, TEAL, bold=True)
    paragraph(canvas, period, M, 295, 255, 12)
    paragraph(canvas, "DATE DE L’EXAMEN", M + 268, 313, WIDTH - 268, 8, TEAL, bold=True)
    paragraph(canvas, exam, M + 268, 295, WIDTH - 268, 13, bold=True)
    y = paragraph(canvas, "Dans ce dossier", M, 244, size=13, bold=True) - 10
    for index, (label, _) in enumerate(sections, 1):
        paragraph(canvas, f"{index:02d}", M, y, 24, 9, TEAL, bold=True)
        y = paragraph(canvas, label, M + 27, y, WIDTH - 27, 10) - 8
    _footer(canvas)
    canvas.showPage()

    for number, (label, files) in enumerate(sections, 1):
        for part in range(1, len(files) + 1):
            canvas.setFillColor(NAVY)
            canvas.rect(0, H - 80, W, 80, stroke=0, fill=1)
            paragraph(canvas, "INTÉGRALE ACADEMY", M, H - 33, 235, 11, colors.white, bold=True)
            paragraph(canvas, "DOSSIER SCOTIA  /  DESP", M + 240, H - 34,
                      WIDTH - 240, 9, GOLD, bold=True, alignment=2)
            part_label = f"PIÈCE {number:02d} / {len(sections):02d}"
            if len(files) > 1:
                part_label += f"   ·   Document {part} sur {len(files)}"
            paragraph(canvas, part_label, M, 627, size=11, color=TEAL, bold=True)
            canvas.setFillColor(GOLD)
            canvas.rect(M, 597, 45, 3, fill=1, stroke=0)
            top = paragraph(canvas, label, M, 574, size=31, bold=True, leading=40)
            top = min(365, top - 38)
            canvas.setFillColor(LIGHT)
            canvas.roundRect(M, top - 92, WIDTH, 92, 8, fill=1, stroke=0)
            half = WIDTH / 2
            for x, field, value in ((M + 16, "NOM", last), (M + half, "PRÉNOM", first)):
                paragraph(canvas, field, x, top - 15, half - 24, 8, TEAL, bold=True)
                paragraph(canvas, value, x, top - 35, half - 24, 15, bold=True, leading=18)
            top = paragraph(canvas, session_name, M, top - 113, size=12, bold=True)
            paragraph(canvas, "Date de l’examen · " + exam, M, top - 6, size=10, color=MUTED)
            _footer(canvas)
            canvas.showPage()
    return finish(canvas, output)
