"""Publish Academy training invitations using the approved landscape stationery."""

import re
import unicodedata

VERSION = "convocations-examens-2027-1"


def family(value):
    value = unicodedata.normalize("NFKD", str(value or "").upper())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    if re.search(r"\bMAC\b.*\bAPS\b|\bAPS\b.*\bMAC\b", value):
        return "mac_aps"
    for pattern, key in [
        (r"\bAFC\b", "aps"),
        (r"\bVAE\b", "vae"),
        (r"DIRIGEANT|\bDESP\b", "desp"),
        (r"\bA3P\b|\bAPR\b", "a3p"),
        (r"\bVTC\b", "vtc"),
        (r"SSIAP", "ssiap"),
        (r"\bAPS\b", "aps"),
        (r"\bSST\b", "sst"),
        (r"HABILITATION|H0B0|MAN.OEUVRE|\bBS\b", "habilitation"),
    ]:
        if re.search(pattern, value):
            return key
    return "other"


def publish(
    document, template_name, group, docx_path, pdf_path, *, calendar_rows=None, site="", exams=None, recipient=""
):
    from . import editable, flow, paris
    from .exams import add_pages
    from .drawing import LayoutDoesNotFit
    from .source import Source, use_puget_plan, include_training_rules
    from .agenda import Agenda

    source = Source(document)
    source.agenda = Agenda(calendar_rows) if calendar_rows is not None else None
    source.course_label = dict(
        desp="FORMATION DESP",
        vae="PARCOURS VAE",
        vtc="CHAUFFEUR VTC",
        a3p="FORMATION A3P",
        ssiap="SÉCURITÉ INCENDIE",
        aps="PRÉVENTION ET SÉCURITÉ",
        sst="SECOURISME",
        mac_aps="MAINTIEN DES COMPÉTENCES",
    ).get(group, "FORMATION PROFESSIONNELLE")
    if template_name != "convocationaps.docx":
        use_puget_plan(source, template_name, site)
    if template_name == "convocationformation.docx":
        include_training_rules(source, group)
    add_pages(source, exams, recipient)
    if template_name == "convocationaps.docx":
        from . import aps

        aps.make(source, pdf_path)
    elif template_name == "vtc-vehicule":
        from . import vehicle

        vehicle.make(source, pdf_path)
    elif template_name == "convocationdespparis_2027.docx":
        try:
            paris.make(source, pdf_path)
        except LayoutDoesNotFit:
            flow.render(source, pdf_path, group)
    else:
        flow.render(source, pdf_path, group)
    editable.write(pdf_path, docx_path)
