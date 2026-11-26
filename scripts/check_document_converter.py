#!/usr/bin/env python3
"""Exercise the installed converter with synthetic files, without Flask or keys.

Run during the container build so a missing Office filter, image codec or Linux
worker restriction fails the build instead of failing a trainee's upload.
"""

from io import BytesIO
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docx import Document
from PIL import Image
from pypdf import PdfReader

import document_conversion as conversion


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_pdf(data, filename, pages):
    require(filename.endswith(".pdf") and data.startswith(b"%PDF-"), "Conversion did not produce a PDF")
    reader = PdfReader(BytesIO(data), strict=True)
    require(len(reader.pages) == pages, f"Expected {pages} PDF pages, got {len(reader.pages)}")
    return reader


def check_office():
    txt, name = conversion.convert_upload("Synthetic text document\nLisibilité vérifiée.\n".encode(), "example.txt")
    reader = read_pdf(txt, name, 1)
    text = reader.pages[0].extract_text() or ""
    require("Synthetic text document" in text and "Lisibilité" in text, "Text import lost content or UTF-8 accents")

    source = Document()
    source.add_paragraph("SYNTHETIC FIRST PAGE")
    source.add_paragraph("Document d’essai, sans données personnelles.")
    source.add_page_break()
    source.add_paragraph("SYNTHETIC SECOND PAGE")
    incoming = BytesIO()
    source.save(incoming)
    output, name = conversion.convert_upload(incoming.getvalue(), "two-pages.docx")
    reader = read_pdf(output, name, 2)
    require("SYNTHETIC FIRST PAGE" in (reader.pages[0].extract_text() or ""), "DOCX first page missing")
    require("SYNTHETIC SECOND PAGE" in (reader.pages[1].extract_text() or ""), "DOCX second page missing")
    unchanged, _ = conversion.convert_upload(output, "existing.pdf")
    require(unchanged == output, "Existing PDF was modified")
    print("OK: real TXT and two-page DOCX conversions; existing PDF preserved", flush=True)


def check_images():
    with Image.new("RGB", (64, 96), "white") as sample:
        for fmt, suffix in (("JPEG", "jpg"), ("PNG", "png")):
            encoded = BytesIO()
            sample.save(encoded, format=fmt)
            original = encoded.getvalue()
            output, name = conversion.convert_upload(original, "synthetic." + suffix)
            read_pdf(output, name, 1)
            portrait, photo_name = conversion.convert_upload(original, "portrait." + suffix, photo=True)
            require(portrait == original and photo_name.endswith("." + suffix), fmt + " identity image was modified")

        # Exercise the real HEVC encoder and decoder supplied by pillow-heif.
        # A registry-only check would miss a wheel without a working codec.
        heic = BytesIO()
        sample.save(heic, format="HEIF")
        output, name = conversion.convert_upload(heic.getvalue(), "synthetic.heic")
        read_pdf(output, name, 1)
        portrait, photo_name = conversion.convert_upload(heic.getvalue(), "portrait.heic", photo=True)
        with Image.open(BytesIO(portrait)) as decoded:
            decoded.load()
            require(decoded.format == "JPEG" and decoded.size == sample.size and photo_name.endswith(".jpg"), "HEIC portrait did not remain an image")

        second = Image.new("RGB", sample.size, "black")
        try:
            multipage = BytesIO()
            sample.save(multipage, format="TIFF", save_all=True, append_images=[second])
            output, name = conversion.convert_upload(multipage.getvalue(), "two-pages.tiff")
            read_pdf(output, name, 2)
        finally:
            second.close()
    print("OK: JPEG, PNG, HEIC and two-page TIFF; portraits remain images", flush=True)


def check_linux_worker():
    if not sys.platform.startswith("linux"):
        print("SKIP: Linux socket isolation probe (not a Linux host)", flush=True)
        return
    # No connections are attempted. Creating an Internet socket must itself be
    # denied, through the same executable, environment and worker as Office.
    probe = """
import errno
import socket
for family in (socket.AF_INET, socket.AF_INET6):
    try:
        candidate = socket.socket(family, socket.SOCK_STREAM)
    except OSError as error:
        if error.errno != errno.EPERM:
            raise
    else:
        candidate.close()
        raise RuntimeError('Internet sockets are not blocked')
"""
    with tempfile.TemporaryDirectory(prefix="converter-worker-check-") as directory:
        conversion._run_office([sys.executable, "-c", probe], Path(directory))
    print("OK: Linux worker blocks IPv4 and IPv6 sockets", flush=True)


def check_training_invitation():
    from academy_convocations import publish
    from academy_convocations.source import PORTAL, ROOT
    from docxtpl import DocxTemplate
    import pymupdf

    template = ROOT / "templates_word/convocationformation.docx"
    with tempfile.TemporaryDirectory(prefix="training-invitation-check-") as work:
        editable = Path(work) / "invitation.docx"
        pdf = editable.with_suffix(".pdf")
        source = DocxTemplate(template)
        source.render({
            "convocation_intitule": "SST", "formation_nom": "SST",
            "nom_complet": "Camille EXEMPLE", "periode_formation": "du 04/01/2027 au 05/01/2027",
            "convocation_site": "Centre de formation", "convocation_examen": "",
            "convocation_session_complement": "",
        })
        source.save(editable)
        publish(Document(editable), template.name, "sst", editable, pdf,
                calendar_rows=[{"kind": "period", "label": "Période de formation", "start": "2027-01-04", "end": "2027-01-05"}])
        with pymupdf.open(pdf) as book:
            require(len(book) == 4 and all(page.rect.width > page.rect.height for page in book),
                    "Incorrect training invitation page layout")
            require(all("Camille EXEMPLE" in book[i].get_text() for i in (0, 1)), "Lost recipient")
            require(book[2].search_for("Janvier 2027") and all(page.search_for("(VAE)") for page in book),
                    "Missing monthly calendar or Qualiopi VAE category")
            require(book[3].search_for("ATTITUDE & RESPECT") and not book[2].search_for("planning individuel"),
                    "Missing APS rules page or obsolete calendar note")
            require(book[1].search_for("Clément VAILLANT") and any(im[2:4] == (283, 158) for im in book[1].get_images()),
                    "Missing director signature")
            require(any(link.get("uri") == PORTAL for page in book for link in page.get_links()),
                    "Lost trainee portal link")
        word = Document(editable)
        require(word.sections[0].page_width > word.sections[0].page_height
                and word.element.xpath(".//w:framePr") and word.element.xpath(".//w:hyperlink"),
                "Landscape Word invitation did not retain editable content and links")
    print("OK: course calendar, director signature and Qualiopi VAE - PDF and editable Word", flush=True)


def check_aps_invitation():
    """Render the APS model with fictional data in the actual deployment image."""
    from academy_convocations import publish
    from academy_convocations.source import ROOT
    from docxtpl import DocxTemplate
    import pymupdf

    template = ROOT / "templates_word/convocationaps.docx"
    with tempfile.TemporaryDirectory(prefix="aps-parking-check-") as work:
        editable = Path(work) / "invitation.docx"
        pdf = editable.with_suffix(".pdf")
        source = DocxTemplate(template)
        source.render({
            "nom_complet": "Camille EXEMPLE", "code_postal": "83000", "ville": "TOULON",
            "periode_formation": "du 01/03/2027 au 15/04/2027",
            "periode_elearning": "du 01/03/2027 au 10/03/2027",
            "periode_presentiel": "du 11/03/2027 au 15/04/2027",
            "aps_distance_longue": "du 1er au 10 mars 2027",
            "aps_centre_longue": "du 11 mars au 15 avril 2027", "aps_examen_long": "16 avril 2027",
            "date_ouverture": "01/03/2027", "date_examen": "16/04/2027", "date_jour": "01/02/2027",
            "heure_convocation": "08h30", "heure_examen": "08h00",
        }, autoescape=True)
        source.save(editable)
        publish(Document(editable), template.name, "aps", editable, pdf)
        with pymupdf.open(pdf) as book:
            dates = book[0].get_text()
            require(len(book) == 8 and all(value in dates for value in
                    ["Du 1er au 10 mars 2027", "Du 11 mars au 15 avril 2027", "Le 16 avril 2027 à 08h00"]),
                    "Missing APS training or exam dates on the cover")
            calendar_page = book[3].get_text()
            require(all(value in calendar_page for value in
                    ["Mars 2027", "Avril 2027", "01/03/2027 à 08h30",
                     "16/04/2027 à 08h00", "Sous réserve de modifications."]),
                    "Missing APS monthly calendar or session details")
            require(any(link.get("uri", "").endswith("/parking-puget.svg") for link in book[-1].get_links()),
                    "Missing Puget parking plan")
            require((ROOT / "static/images/convocations/parking-puget.svg").is_file(),
                    "Enlarged Puget parking map missing from the image")
    print("OK: APS monthly calendar, cover dates and Puget parking map", flush=True)


def check_desp_invitation():
    from academy_convocations import publish
    from academy_convocations.source import ROOT
    from desp_paris_venue import FULL_ADDRESS, access_details
    from docxtpl import DocxTemplate
    import pymupdf

    context = {
        "nom_complet": "Camille EXEMPLE", "ville": "PARIS", "code_postal": "75002",
        "periode_formation": "du 04/01/2027 au 18/02/2027", "date_ouverture": "04/01/2027",
        "heure_convocation": "09h00", "date_examen": "19/02/2027", "heure_examen": "08h15",
        "date_jour": "16/12/2026", "periode_elearning": "du 04/01/2027 au 05/02/2027",
        "periode_presentiel": "du 08/02/2027 au 18/02/2027",
        "desp_distance_longue": "du 4 janvier au 5 février 2027",
        "desp_centre_longue": "du 8 au 18 février 2027", "desp_examen_long": "19 février 2027",
        "lieu_formation": FULL_ADDRESS, "lieu_examen": FULL_ADDRESS,
        **{"acces_" + key: value for key, value in access_details().items()},
    }
    rows = [
        dict(kind="remote", label="Formation à distance", start="2027-01-04", end="2027-02-05"),
        dict(kind="centre", label="Au centre de formation", start="2027-02-08", end="2027-02-18"),
        dict(kind="exam", label="Examen DESP", days=["2027-02-19"], time="08h15"),
    ]
    dates = ["Du 4 janvier au 5 février 2027", "Du 8 au 18 février 2027", "Le 19 février 2027 à 08h15"]
    with tempfile.TemporaryDirectory(prefix="desp-cover-check-") as work:
        for template_name in ("convocationdespparis_2027.docx", "convocationdesp.docx"):
            editable = Path(work) / template_name
            pdf = editable.with_suffix(".pdf")
            source = DocxTemplate(ROOT / "templates_word" / template_name)
            source.render(context, autoescape=True)
            source.save(editable)
            publish(Document(editable), template_name, "desp", editable, pdf, calendar_rows=rows)
            with pymupdf.open(pdf) as book:
                for value, y in zip(dates, (133, 214, 295)):
                    rects = book[0].search_for(value)
                    require(len(rects) == 1 and abs(rects[0].x0 - 499) < 1
                            and abs(rects[0].y0 - y) < 1 and rects[0].height > 25,
                            f"DESP date missing from its APS cover row: {template_name} / {value}")
                require(book[3].search_for("19/02/2027 · 08h15"), "Missing DESP monthly calendar")
            words = Document(editable).element.xpath(".//w:t/text()")
            require(all(date in words for date in dates), "Missing DESP cover dates in editable Word")
    print("OK: DESP covers show remote, onsite and exam dates in the APS layout", flush=True)


def check_a3p_invitation():
    from academy_convocations import publish
    from academy_convocations.source import ROOT
    from docxtpl import DocxTemplate
    import pymupdf

    template = ROOT / "templates_word/convocationa3p.docx"
    with tempfile.TemporaryDirectory(prefix="a3p-invitation-check-") as work:
        editable = Path(work) / "invitation.docx"
        pdf = editable.with_suffix(".pdf")
        source = DocxTemplate(template)
        source.render({"nom_complet": "Camille EXEMPLE", "ville": "PUGET-SUR-ARGENS",
                       "periode_formation": "du 08/03/2027 au 06/05/2027", "date_examen": "07/05/2027",
                       "date_debut_formation": "08/03/2027", "date_jour": "01/02/2027"}, autoescape=True)
        source.save(editable)
        publish(Document(editable), template.name, "a3p", editable, pdf)
        with pymupdf.open(pdf) as book:
            rules = book[4]
            left = rules.search_for("ATTITUDE & RESPECT")[0]
            right = rules.search_for("TENUE ADAPTÉE EN COURS")[0]
            require(left.y0 == right.y0 and right.x0 > left.x1 + 100, "Misaligned A3P training rules")
            require(book[5].search_for("dortoir collectif") and book[6].search_for("VIE COLLECTIVE")
                    and book[7].search_for("À MOINS DE 5 MINUTES") and book[8].search_for("COUCHAGE & HYGIÈNE"),
                    "Missing A3P residential pages")
    print("OK: APS reference rules and A3P accommodation in PDF and Word", flush=True)


def main():
    check_linux_worker()
    check_images()
    check_office()
    check_training_invitation()
    check_aps_invitation()
    check_desp_invitation()
    check_a3p_invitation()
    print("Document converter checks passed.", flush=True)


if __name__ == "__main__":
    main()
