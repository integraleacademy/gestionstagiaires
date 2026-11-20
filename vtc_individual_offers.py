"""Individual VTC practical-only and examination vehicle-loan offers.

These offers are attached to the ordinary trainee record, never to VTC orders.
No background e-learning assignment, theory course or examination fee is included.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

FULL = "full"
PRACTICE = "practice"
VEHICLE = "vehicle"
OFFERS = {FULL, PRACTICE, VEHICLE}
PRICES = {PRACTICE: "600", VEHICLE: "150"}
LABELS = {
    PRACTICE: "Formation pratique VTC et prêt du véhicule le jour de l'examen",
    VEHICLE: "Prêt du véhicule le jour de l'examen pratique VTC",
}
SCHOOL = "Intégrale Sécurité Formations – Intégrale Academy"
SCHOOL_ADDRESS = "54 chemin du Carreou, 83480 Puget-sur-Argens"
SCHOOL_CONTACT = "ecole@integraleacademy.com – 04 22 47 07 68"
SCHOOL_IDENTITY = "SIREN 840 899 884 – Déclaration d'activité 93830600283"
CENTRES = {"nice": "Saint-Laurent-du-Var (06)", "toulon": "La Valette-du-Var (83)"}


def offer(trainee):
    value = str((trainee or {}).get("vtc_offer") or FULL).strip().lower()
    return value if value in OFFERS else FULL


def reduced(trainee):
    return offer(trainee) in PRICES


def vehicle(trainee):
    return offer(trainee) == VEHICLE


def is_vtc(training):
    return "VTC" in str((training or {}).get("training_type") or (training or {}).get("type_formation") or "").upper()


def validate(value):
    value = str(value or "").strip().lower()
    if value not in OFFERS:
        raise ValueError("Formule VTC inconnue. Choisissez le parcours complet, la formation pratique ou le prêt du véhicule.")
    return value


def update(trainee, requested, default_price):
    """Update the commercial selection atomically with its fixed TTC price."""
    requested = validate(requested)
    previous = offer(trainee)
    if previous == requested:
        return False
    if previous == FULL and requested != FULL:
        trainee["vtc_full_price_before_offer"] = str(
            trainee.get("training_price") or default_price or "1500"
        ).strip()
    trainee["vtc_offer"] = requested
    trainee["training_price"] = (
        PRICES[requested] if requested != FULL
        else str(trainee.get("vtc_full_price_before_offer") or default_price or "1500")
    )
    trainee["vtc_offer_updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return True


def _date(value):
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        return dt.date.fromisoformat(value[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return value


def _exam_details(training, trainee):
    exam = trainee.get("vtc_practice_exam_date") or training.get("exam_practice_date") or training.get("exam_date")
    centre = CENTRES.get(str(trainee.get("vtc_exam_center") or "").strip().lower(),
                         "Lieu communiqué par la Chambre de métiers et de l'artisanat")
    return _date(exam), centre


def _add(doc, text, *, bold=False):
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(6)
    run = paragraph.add_run(text)
    run.bold = bold
    return paragraph


def _heading(doc, title):
    doc.add_heading(title, level=2)


def _make_document(training, trainee, *, practice_slot=None, examiner=False):
    kind = offer(trainee)
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(1.7)
    section.bottom_margin = Cm(1.6)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)
    normal = doc.styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(6)

    title = ("DOCUMENT À PRÉSENTER AUX EXAMINATEURS LE JOUR DE VOTRE EXAMEN PRATIQUE"
             if examiner else
             "CONVENTION DE MISE À DISPOSITION D’UN VÉHICULE – VTC"
             if kind == VEHICLE else
             "CONTRAT DE FORMATION PRATIQUE VTC ET MISE À DISPOSITION D’UN VÉHICULE")
    heading = doc.add_heading(title, 0)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in heading.runs:
        run.font.size = Pt(15)

    _add(doc, SCHOOL, bold=True)
    _add(doc, SCHOOL_ADDRESS)
    _add(doc, SCHOOL_IDENTITY)
    _add(doc, SCHOOL_CONTACT)
    doc.add_paragraph()
    full_name = " ".join(
        filter(None, [str(trainee.get("first_name") or "").strip(),
                      str(trainee.get("last_name") or "").strip().upper()])
    )
    if not full_name:
        raise ValueError("Renseignez le prénom et le nom du candidat avant la génération du document.")
    postal = ", ".join(filter(None, [
        str(trainee.get("address") or "").strip(),
        " ".join(filter(None, [
            str(trainee.get("zip_code") or "").strip(),
            str(trainee.get("city") or "").strip(),
        ])),
    ]))
    exam_date, centre = _exam_details(training, trainee)
    _heading(doc, "Candidat")
    _add(doc, "Nom et prénom : " + full_name)
    if not examiner:
        if postal:
            _add(doc, "Adresse : " + postal)
        _add(doc, "E-mail : " + str(trainee.get("email") or "") +
             "  |  Téléphone : " + str(trainee.get("phone") or ""))
    if exam_date:
        _add(doc, "Date de l’examen pratique communiquée : " + exam_date)
    else:
        _add(doc, "Date de l’examen pratique : selon convocation officielle de la CMA")
    _add(doc, "Centre d’examen : " + centre)

    if examiner:
        _heading(doc, "Attestation de mise à disposition")
        _add(doc, "Intégrale Sécurité Formations atteste mettre à la disposition du candidat "
             + full_name + " un véhicule à doubles commandes pour son passage à l’épreuve "
             "pratique de l’examen de chauffeur VTC, dans le cadre de la prestation convenue.")
        _add(doc, "Cette attestation doit être présentée aux examinateurs avec la convocation "
             "officielle délivrée par la Chambre de métiers et de l’artisanat. "
             "Elle ne remplace pas la convocation de la CMA.")
        _add(doc, "Pour organiser la présentation du véhicule et confirmer les informations "
             "utiles à l’examen, contactez directement l’établissement.")
        _add(doc, "Fait à Puget-sur-Argens, le " + dt.date.today().strftime("%d/%m/%Y") + ".")
        _add(doc, SCHOOL + " – Coordonnées : " + SCHOOL_CONTACT)
        return doc

    _heading(doc, "Objet et contenu de la prestation")
    if kind == PRACTICE:
        _add(doc, "La prestation comprend exclusivement une séance de préparation à l’épreuve "
             "pratique d’admission VTC, ainsi que la mise à disposition du véhicule à doubles "
             "commandes le jour de l’examen pratique.")
        _add(doc, "Objectifs : prise en charge d’un client, préparation de l’itinéraire, "
             "conduite professionnelle en sécurité, mise en situation, examen blanc et "
             "prise en main du véhicule. Suivi assuré par un formateur.")
        slot = practice_slot or {}
        if slot.get("date"):
            times = " de " + str(slot.get("start") or "") + " à " + str(slot.get("end") or "") if slot.get("start") else ""
            _add(doc, "Séance pratique : " + _date(slot["date"]) + times +
                 ", au centre Intégrale Academy de Puget-sur-Argens.")
        else:
            _add(doc, "Séance pratique : date et horaire à convenir avec le candidat avant la prestation.")
        _add(doc, "Public : candidats préparant l’épreuve pratique VTC. "
             "Prérequis : permis B en cours de validité et admissibilité à l’épreuve pratique.")
        _add(doc, "À l’issue de la séance, l’établissement peut délivrer une attestation "
             "de réalisation de la formation pratique suivie.")
    else:
        _add(doc, "La prestation consiste exclusivement en la mise à disposition "
             "d’un véhicule à doubles commandes le jour de l’épreuve pratique VTC.")
        _add(doc, "Aucune formation, aucun cours théorique, aucun accès e-learning "
             "et aucune séance de préparation pratique ne sont inclus.")
        _add(doc, "Le candidat doit transmettre à Intégrale Academy sa convocation "
             "officielle de la CMA afin de coordonner la mise à disposition du véhicule.")

    _heading(doc, "Examen et modalités")
    _add(doc, "L’examen pratique est organisé et évalué par la Chambre de métiers et de "
         "l’artisanat (CMA). Les droits d’inscription et frais d’examen CMA ne sont pas compris "
         "dans la présente prestation, sauf prise en charge expressément convenue par écrit.")
    _add(doc, "La mise à disposition du véhicule est prévue pour le centre et la date "
         "d’examen confirmés par l’organisateur. Le candidat doit présenter sa convocation "
         "et les justificatifs exigés par la CMA.")
    _add(doc, "La présente formule n’ouvre aucun accès à la formation théorique ni au e-learning.")

    _heading(doc, "Prix et conditions de règlement")
    _add(doc, "Prix forfaitaire TTC : " + PRICES[kind] + " €.", bold=True)
    _add(doc, "Les modalités de paiement sont celles acceptées lors de l’inscription "
         "et figurant sur la facture ou dans le dossier individuel du candidat.")

    _heading(doc, "Report, annulation et rétractation")
    _add(doc, "En cas de changement de date d’examen, le candidat informe le centre "
         "dès réception de l’information. Toute modification de prestation fait l’objet "
         "d’un accord préalable entre les parties.")
    _add(doc, "En cas d’impossibilité de fournir la prestation du fait de l’établissement, "
         "une nouvelle date sera proposée avec l’accord du candidat ou la prestation "
         "non réalisée sera remboursée.")
    _add(doc, "Lorsqu’un droit de rétractation s’applique à la conclusion à distance, "
         "il s’exerce conformément aux dispositions légales en vigueur. "
         "Contact : " + SCHOOL_CONTACT + ".")
    _heading(doc, "Signature électronique du candidat")
    _add(doc, "Je reconnais avoir pris connaissance de la nature et des limites de "
         "la prestation ainsi que de son tarif forfaitaire TTC.")
    p = doc.add_paragraph()
    p.add_run("{{s1|signature|160|80}}")
    return doc


def _write_pdf(host, document, output_dir, base):
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    docx_path = folder / (base + ".docx")
    pdf_path = folder / (base + ".pdf")
    document.save(docx_path)
    with tempfile.TemporaryDirectory(prefix="vtc-offer-office-") as profile:
        command = [host._find_libreoffice_binary(),
                   "-env:UserInstallation=" + Path(profile).as_uri(),
                   "--headless", "--convert-to", "pdf",
                   "--outdir", str(folder), str(docx_path)]
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
    if not pdf_path.is_file() or pdf_path.stat().st_size < 500:
        raise RuntimeError("La conversion PDF du document VTC n’a pas abouti.")
    return str(docx_path), str(pdf_path)


def convention(host, training, trainee, session_id="", trainee_id="", *, output_dir=None):
    if not is_vtc(training) or not reduced(trainee):
        raise ValueError("Cette convention est exclusivement réservée aux formules VTC réduites.")
    folder = output_dir
    if folder is None:
        Path(host.YOUSIGN_CONVENTION_DIR).mkdir(parents=True, exist_ok=True)
        folder = tempfile.mkdtemp(prefix="convention-vtc-", dir=host.YOUSIGN_CONVENTION_DIR)
    key = "".join(c if c.isalnum() or c in "-_" else "_" for c in
                  (trainee.get("id") or trainee_id or uuid.uuid4().hex))
    slot = host._vtc_practice_appointment(training, trainee) if offer(trainee) == PRACTICE else None
    doc = _make_document(training, trainee, practice_slot=slot)
    return _write_pdf(host, doc, folder, "convention_vtc_" + offer(trainee) + "_" + key)


def vehicle_hash(training, trainee):
    fields = {
        "version": 2, "offer": offer(trainee),
        "identity": [trainee.get(k) for k in ("id", "first_name", "last_name", "vtc_exam_center", "vtc_practice_exam_date")],
        "exam_dates": [training.get("exam_practice_date"), training.get("exam_date")],
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def examiner_document(host, training, trainee, output_dir, base):
    if not is_vtc(training) or not vehicle(trainee):
        raise ValueError("Attestation réservée à la formule prêt du véhicule uniquement.")
    return _write_pdf(host, _make_document(training, trainee, examiner=True), output_dir, base)
