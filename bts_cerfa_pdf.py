"""Fill the supplied interactive CERFA without changing its printed layout."""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import re
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth

from bts_cerfa import FIELDS, SECTIONS, active_section

TEMPLATE = Path(__file__).resolve().parent / "templates_word" / "cerfa_10103-14.pdf"
TEMPLATE_SHA256 = "b5458256a21740bdd9d89982de526d1732939f2c3d9b7d98d873f7ce7d3b864d"


def tx(number):
    return "Zone de texte 8" + ("_" + str(number) if number != 1 else "")


def day_field(number):
    return "Zone de texte 21" + ("_" + str(number) if number != 1 else "")


def check(number):
    return "Case #C3#A0 cocher " + str(number)


TEXT = {
    "contract_mode": 54, "employer_name": 1, "employer_siret": 2, "employer_type": 3,
    "employer_specific": 4, "employer_headcount": 5, "employer_idcc": 6, "employer_ape": 7,
    "employer_address_complement": 8, "employer_postcode": 9, "employer_city": 10,
    "employer_phone": 11, "employer_email": 12,
    "apprentice_last_name": 15, "apprentice_usage_name": 16, "apprentice_first_name": 17,
    "apprentice_nir": 18, "apprentice_address_complement": 21, "apprentice_postcode": 22,
    "apprentice_city": 23, "apprentice_phone": 24, "apprentice_email": 25,
    "apprentice_birth_department": 26, "apprentice_birth_city": 27,
    "apprentice_previous_situation": 28, "apprentice_previous_diploma": 29,
    "apprentice_previous_class": 30, "apprentice_previous_diploma_title": 31,
    "apprentice_highest_diploma": 32, "apprentice_nationality": 33, "apprentice_social_regime": 34,
    "guardian_name": 35, "guardian_address_complement": 38, "guardian_postcode": 39,
    "guardian_city": 40, "guardian_email": 41,
    "tutor_last_name": 42, "tutor_first_name": 43, "tutor_email": 44, "tutor_job": 45,
    "tutor2_last_name": 46, "tutor2_first_name": 47, "tutor2_email": 48, "tutor2_job": 49,
    "tutor_diploma": 50, "tutor2_diploma": 51, "tutor_level": 52, "tutor2_level": 53,
    "previous_contract_number": 55, "weekly_hours": 68, "weekly_minutes": 69,
    "contract_derogation": 70, "contract_type": 71,
    "cfa_uai": 73, "cfa_siret": 74, "diploma_code": 75, "rncp": 76, "training_diploma_type": 77,
    "cfa_city": 78, "cfa_address_complement": 81, "cfa_postcode": 82,
    "site_siret": 83, "site_uai": 84, "site_city": 85, "site_address_complement": 88, "site_postcode": 89,
    "signing_city": 90, "cfa_name": 99, "training_title": 100, "site_name": 101, "remote_hours": 102,
}
DATES = {"apprentice_birth_date": 7, "tutor_birth_date": 4, "tutor2_birth_date": 1,
         "contract_conclusion": 16, "contract_start": 19, "practical_start": 22,
         "amendment_date": 13, "contract_end": 10, "training_start": 25, "exam_end": 28}
ADDRESSES = {"employer": (14, 13), "apprentice": (19, 20), "guardian": (37, 36),
             "cfa": (79, 80), "site": (86, 87)}
CHOICES = {
    "employer_sector": {"private": "1", "public": "2"},
    "apprentice_sex": {"M": "3", "F": "4"},
    "apprentice_high_level_athlete": {"yes": "5", "no": "5_2"},
    "apprentice_rqth": {"yes": "5_3", "no": "5_4"},
    "apprentice_rqth_young": {"yes": "5_5", "no": "5_6"},
    "apprentice_rqth_boe": {"yes": "5_7", "no": "5_8"},
    "apprentice_business_project": {"yes": "5_9", "no": "5_10"},
    "cfa_company": {"yes": "5_11", "no": "5_12"},
    "hazardous_work": {"yes": "5_13", "no": "5_14"},
    "employer_unemployment": {"yes": "2_2"}, "tutor_attestation": {"yes": "6"},
    "cfa_same_site": {"yes": "7"}, "documents_attestation": {"yes": "8"},
}
# Positions follow the visual order of the two periods on each printed year.
SALARY = ((1, 1, 81, 84, 95, 96), (1, 2, 87, 90, 97, 98),
          (2, 1, 37, 40, 56, 57), (2, 2, 43, 46, 58, 59),
          (3, 1, 49, 52, 60, 61), (3, 2, 55, 58, 62, 63),
          (4, 1, 61, 64, 64, 65), (4, 2, 67, 70, 66, 67))
RESERVED = {tx(i) for i in range(91, 95)} | {day_field(i) for i in range(31, 37)}


class CerfaPdfError(ValueError):
    pass


def pdf_values(values):
    values = dict(values)
    # A former guardian/site must not remain on a new document after a condition changes.
    for groups in SECTIONS.values():
        for section in groups:
            if not active_section(section, values):
                for f in section["fields"]:
                    values[f["key"]] = ""
    if values.get("apprentice_rqth") != "no":
        values["apprentice_rqth_young"] = values["apprentice_rqth_boe"] = ""
    if values.get("employer_sector") != "public":
        values["employer_unemployment"] = ""
    if not values.get("contract_type", "").startswith("3"):
        values["amendment_date"] = ""
    if not values.get("contract_type", "").startswith(("2", "3")):
        values["previous_contract_number"] = ""
    result, labels = {}, {}

    def put(name, value, key):
        result[name] = str(value or "")
        labels[name] = FIELDS[key]["label"]

    def date(key, start):
        parts = ("", "", "")
        if values.get(key):
            try:
                value = dt.date.fromisoformat(values[key])
                parts = (value.strftime("%d"), value.strftime("%m"), value.strftime("%Y"))
            except ValueError:
                raise CerfaPdfError("Date invalide : " + FIELDS[key]["label"]) from None
        for index, part in enumerate(parts):
            put(day_field(start + index), part, key)

    for key, number in TEXT.items():
        value = values.get(key, "")
        if key == "rncp":
            value = re.sub(r"^RNCP\s*", "", value.upper())
        if key == "contract_derogation" and value == "none":
            value = ""
        put(tx(number), value, key)
    for key, number in DATES.items():
        date(key, number)
    for prefix, (number, street) in ADDRESSES.items():
        key = prefix + "_address"
        address = values.get(key, "")
        split = re.match(r"^(\d+(?:\s*(?:bis|ter|quater|[A-Za-z]))?)\s+(.+)$", address, re.I)
        put(tx(number), split.group(1) if split else "", key)
        put(tx(street), split.group(2) if split else address, key)
    for key, choices in CHOICES.items():
        for choice, number in choices.items():
            put(check(number), "/Yes" if values.get(key) == choice else "/Off", key)
    for year, period, start, end, rate, basis in SALARY:
        prefix = f"salary_{year}_{period}_"
        date(prefix + "start", start)
        date(prefix + "end", end)
        rate_value = values.get(prefix + "rate", "")
        if rate_value:
            rate_value = format(Decimal(rate_value).normalize(), "f").replace(".", ",")
        put(tx(rate), rate_value, prefix + "rate")
        put(tx(basis), values.get(prefix + "basis", ""), prefix + "basis")
    for key, whole, fraction in (("gross_salary", tx(72), day_field(73)),
                                 ("benefit_food", day_field(75), day_field(76)),
                                 ("benefit_housing", day_field(77), day_field(78))):
        parts = ("", "") if not values.get(key) else format(Decimal(values[key]).quantize(Decimal(".01")), ".2f").split(".")
        put(whole, parts[0], key)
        put(fraction, parts[1], key)
    put(day_field(74), values.get("pension_fund", ""), "pension_fund")
    put(day_field(79), "X" if values.get("benefit_other") == "yes" else "", "benefit_other")
    put(day_field(80), values.get("training_hours", ""), "training_hours")
    return result, labels


def generate_pdf(values):
    try:
        template = TEMPLATE.read_bytes()
    except OSError:
        raise CerfaPdfError("Le modèle CERFA n’est pas disponible. Contactez l’administrateur.") from None
    if hashlib.sha256(template).hexdigest() != TEMPLATE_SHA256:
        raise CerfaPdfError("Le modèle CERFA a changé. Son remplissage doit être vérifié avant génération.")
    reader = PdfReader(io.BytesIO(template))
    mapping, labels = pdf_values(values)
    fields = reader.get_fields() or {}
    if set(fields) != set(mapping) | RESERVED or len(reader.pages) != 2:
        raise CerfaPdfError("Les champs du modèle CERFA ne correspondent pas au formulaire attendu.")
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.pdf_header = reader.pdf_header
    # All 216 source widgets already belong to the canonical field tree.
    # Do not reattach them or create duplicate fields with the same name.
    updates = {name: "" for name in RESERVED}
    for page in writer.pages:
        for reference in page.get("/Annots", []):
            widget = reference.get_object()
            name = widget.get("/T")
            if name not in mapping:
                continue
            value = mapping[name]
            if widget.get("/FT") == "/Btn":
                updates[name] = value
                continue
            width = float(widget["/Rect"][2]) - float(widget["/Rect"][0]) - 2
            text_width = stringWidth(value, "Helvetica", 8) if value else 0
            size = min(8, 8 * width / text_width) if text_width else 8
            if size < 5.5:
                raise CerfaPdfError("Texte trop long pour le CERFA : « " + labels[name] + " ». Abrégez ce champ avant de générer le PDF.")
            updates[name] = (value, "/He", size)
    writer.update_page_form_field_values(None, updates, auto_regenerate=False)
    writer.add_metadata({"/Title": "Contrat d’apprentissage - CERFA 10103*14", "/Author": "Intégrale Academy"})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
