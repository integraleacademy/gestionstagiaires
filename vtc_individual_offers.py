"""Individual VTC practical-only and examination vehicle-loan offers.

These offers are attached to the ordinary trainee record, never to VTC orders.
No background e-learning assignment, theory course or examination fee is included.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import uuid

from exam_retakes import money
import vtc_offer_contracts
from training_convocations import PORTAL_URL

from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT

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


def _contract_document(training, trainee, *, practice_slot=None, reference=None, funding=(), cpf=False):
    kind = offer(trainee)
    return vtc_offer_contracts.build(
        practice=kind == PRACTICE, person=trainee, price=money(int(PRICES[kind]) * 100) + " TTC",
        exam_day=trainee.get("vtc_practice_exam_date") or training.get("exam_practice_date"),
        centre=CENTRES.get(str(trainee.get("vtc_exam_center") or "").lower()), slot=practice_slot,
        reference=reference or (training.get("id"), trainee.get("id"), kind),
        funding=funding, cpf=cpf,
    )


def _examiner_document(training, trainee):
    # Use the same stationery as the VTC convocation while keeping the vehicle-only wording.
    doc = Document(Path(__file__).parent / "templates_word" / "convocationvtc.docx")
    doc.element.body.clear_content()
    for rel in list(doc.part.rels.values()):
        if rel.reltype in (RT.IMAGE, RT.HYPERLINK):
            doc.part.drop_rel(rel.rId)
    doc.core_properties.title = "Prêt de véhicule pour l’examen pratique VTC"
    title = doc.add_paragraph()
    label = title.add_run("DOCUMENT À PRÉSENTER AUX EXAMINATEURS")
    label.bold = True
    label.font.size = Pt(9)
    label.font.color.rgb = RGBColor.from_string("09677B")
    banner = doc.add_table(rows=1, cols=2)
    banner.autofit = False
    text, art = banner.rows[0].cells
    banner.columns[0].width = text.width = Cm(12.6)
    banner.columns[1].width = art.width = Cm(4.8)
    artwork = Path(__file__).parent / "static/images/convocations/vehicule.png"
    art.paragraphs[0].add_run().add_picture(str(artwork), width=Cm(4.1))
    heading = text.paragraphs[0].add_run("Prêt de véhicule pour l’examen pratique VTC")
    heading.bold = True
    heading.font.size = Pt(23)
    heading.font.color.rgb = RGBColor.from_string("0C1A2F")

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
    exam_date, centre = _exam_details(training, trainee)
    _heading(doc, "Candidat")
    _add(doc, "Nom et prénom : " + full_name)
    if exam_date:
        _add(doc, "Date de l’examen pratique communiquée : " + exam_date)
    else:
        _add(doc, "Date de l’examen pratique : selon convocation officielle de la CMA")
    _add(doc, "Centre d’examen : " + centre)

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
    portal = doc.add_paragraph("Espace stagiaire · ")
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), doc.part.relate_to(PORTAL_URL, RT.HYPERLINK, is_external=True))
    run = portal.add_run(PORTAL_URL)
    run.font.color.rgb = RGBColor.from_string("09677B")
    run.underline = True
    link.append(run._r)
    portal._p.append(link)
    return doc


def write_pdf(host, document, output_dir, base):
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
    kind = offer(trainee)
    funding = []
    cpf = False
    if kind == PRACTICE:
        # Older enrolments can retain the amounts of the full course after an offer change.
        # Only reproduce an allocation that reconciles with this particular contract.
        amounts = {
            "Compte personnel de formation": trainee.get("cpf_amount") or trainee.get("montant_cpf"),
            "Autre financement": trainee.get("other_amount") or trainee.get("montant_autre"),
            "Financement personnel": trainee.get("personal_amount") or trainee.get("montant_financement_personnel") or trainee.get("montant_personnel"),
        }
        cents = {label: round(host._parse_financial_amount(value) * 100) for label, value in amounts.items()}
        if all(value >= 0 for value in cents.values()) and sum(cents.values()) == int(PRICES[kind]) * 100:
            funding = [label + " – " + money(value) + "." for label, value in cents.items() if value]
            cpf = bool(cents["Compte personnel de formation"])
        elif any(cents.values()):
            funding = ["Toute prise en charge est déterminée par l’accord du financeur correspondant à la présente formule."]
    reference = (session_id or training.get("id"), trainee_id or trainee.get("id") or key, kind)
    doc = _contract_document(training, trainee, practice_slot=slot, reference=reference, funding=funding, cpf=cpf)
    return write_pdf(host, doc, folder, "convention_vtc_" + offer(trainee) + "_" + key)


def vehicle_hash(training, trainee):
    fields = {
        "version": 4, "offer": offer(trainee),
        "identity": [trainee.get(k) for k in ("id", "first_name", "last_name", "vtc_exam_center", "vtc_practice_exam_date")],
        "exam_dates": [training.get("exam_practice_date"), training.get("exam_date")],
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def examiner_document(host, training, trainee, output_dir, base):
    if not is_vtc(training) or not vehicle(trainee):
        raise ValueError("Attestation réservée à la formule prêt du véhicule uniquement.")
    return write_pdf(host, _examiner_document(training, trainee), output_dir, base)
