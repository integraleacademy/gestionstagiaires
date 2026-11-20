"""Variable institutional mentions on Intégrale Academy's original SSIAP 1 artwork."""
import datetime as dt
from functools import lru_cache

import pymupdf
from reportlab.lib import colors
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics

from ssiap_exam import DEFAULTS


# Narrow bands across the native text baselines, in top-left PDF points.
# The graphic, logo, certification heading and signature rules are separate elements.
SLOTS = {
    "certification_heading": (390, 155, 665, 157),
    "registration": (414, 173, 635, 175),
    "centre": (225, 203, 641, 205),
    "approval": (250, 235, 615, 237),
    "approval_date": (558, 235, 614, 237),
    "contact": (251, 249, 618, 285),
    "issue_place": (46, 488, 176, 490),
    "centre_caption": (240, 510, 412, 512),
    "signatory": (206, 525, 444, 527),
}


def stock_changes(row):
    """Describe only the printed slots that differ from the supplied artwork."""
    changes = {}
    issuer = row.get("issuer", "Intégrale Academy")
    academy = issuer.casefold() == "intégrale academy"
    rep = row.get("representative", "")
    official_rep = academy and rep.casefold().replace("–", "-").removeprefix("monsieur ") in (
        "", "clément vaillant", "clément vaillant - directeur général")
    if not official_rep:
        changes["centre"] = f"Le centre de formation {issuer}" + (f" représenté par {rep}," if rep else ",")
        changes["signatory"] = rep
    if not academy:
        changes["centre_caption"] = "Le représentant du centre"
    if row.get("issuer_details") or not academy:
        changes["contact"] = row.get("issuer_details", "")

    date = row.get("exam_date", "")
    try:
        exam_date = dt.datetime.strptime(date, "%d/%m/%Y").date()
    except ValueError:
        exam_date = None
    registration = row.get("registration", "")
    if registration:
        if registration.casefold().replace(" ", "") not in ("rs5641", "5641", "francecompétencesn°5641"):
            changes["registration"] = registration
    elif row.get("manual") and exam_date and not 2022 <= exam_date.year <= 2026:
        # France compétences RS5641 covers courses from 01/01/2022 through 31/12/2026.
        changes.update(certification_heading="", registration="")

    approval = row.get("approval", DEFAULTS["approval"])
    if not approval and academy and exam_date and dt.date(2020, 10, 8) <= exam_date < dt.date(2025, 10, 8):
        # Var prefectural order of 08/10/2020, amended by order 25/044 (03/03/2025).
        changes["approval_date"] = "08/10/2020"
    else:
        if not approval and academy and exam_date and dt.date(2026, 5, 29) <= exam_date < dt.date(2031, 5, 29):
            approval = DEFAULTS["approval"]
        if approval != DEFAULTS["approval"] or not academy:
            changes["approval"] = approval if approval != DEFAULTS["approval"] else ""

    place = row.get("issue_place", "Puget-sur-Argens")
    if place.casefold().replace("-", " ") != "puget sur argens":
        changes["issue_place"] = f"Fait à {place} le {row.get('issue_date') or date}"
    return changes


@lru_cache(maxsize=12)
def stock_without_slots(template_path, slots):
    """Remove the changed text only; keep the exact vector watermark behind it."""
    with pymupdf.open(template_path) as doc:
        page = doc[0]
        if "signatory" in slots:
            for image in page.get_image_info(xrefs=True):
                if image["bbox"][1] > 500 and image["xref"]:
                    page.delete_image(image["xref"])
        for slot in slots:
            page.add_redact_annot(SLOTS[slot], fill=False)
        # The model's translucent watermark is text in its own Form XObject.
        # Redaction can remove its oversized letters behind the contact lines.
        watermark = next(item for item in page.get_xobjects() if item[1] == "X19")
        page.apply_redactions(images=0, graphics=0, text=0)
        new_watermark = next(item for item in page.get_xobjects() if item[3] == watermark[3])
        if new_watermark[0] != watermark[0]:
            doc.xref_copy(watermark[0], new_watermark[0])
        return doc.tobytes(garbage=4, deflate=True)


def draw_mentions(pdf, height, changes, row):
    from ssiap_exam_pdf import FONT, BOLD

    def draw(text, left, right, top, size=10.5, font=FONT, lines=1, align="centre", end_at_baseline=False):
        if not text:
            return
        width = right - left
        while len(wrapped := simpleSplit(text, font, size, width)) > lines:
            size -= .25
        if end_at_baseline:
            top -= (len(wrapped) - 1) * (size + 2)
        for index, line in enumerate(wrapped):
            fitted = min(size, width / max(pdfmetrics.stringWidth(line, font, 1), 1))
            line_width = pdfmetrics.stringWidth(line, font, fitted)
            x = left if align == "left" else left + (width - line_width) / 2
            obj = pdf.beginText(x, height - top - index * (size + 2))
            obj.setFont(font, fitted)
            obj.setCharSpace(0)
            obj.setWordSpace(0)
            obj.setHorizScale(100)
            obj.textOut(line)
            pdf.drawText(obj)

    pdf.saveState()
    pdf.setFillColor(colors.HexColor("#2c2c2c"))
    draw(changes.get("registration"), 342, 706, 176.6, 16, BOLD)
    draw(changes.get("centre"), 170, 695, 206.9, lines=2, end_at_baseline=True)
    draw(changes.get("approval"), 164, 702, 238.4, lines=2, end_at_baseline=True)
    draw(changes.get("approval_date"), 557.87, 614, 238.4, 10.25, align="left")
    draw(changes.get("contact"), 166, 700, 254.2, lines=3)
    draw(changes.get("issue_place"), 47.28, 363, 491.57, align="left")
    draw(changes.get("centre_caption"), 197, 453, 513.3)
    draw(changes.get("signatory"), 201, 449, 528.3, 10.5, BOLD, lines=2)
    if row.get("manual"):
        draw(row.get("exam_place"), 248, 661, 333)
        draw(row.get("jury_representative"), 455, 687, 528.3, 10.5, BOLD, lines=2)
    pdf.restoreState()
