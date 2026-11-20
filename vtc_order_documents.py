"""Nominative documents for the practical VTC offers, separate from the 105 h course."""
import os
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate

from exam_retakes import date_label, money
from vtc_order_finance import METHODS, method
from vtc_individual_offers import write_pdf
import vtc_offer_contracts
from exam_retakes_documents import retake_font, retake_page_frame

CMA = ("Au moment de votre inscription à l’examen pratique auprès de la Chambre de métiers "
       "et de l’artisanat, indiquez « Intégrale Academy – Intégrale Sécurité Formations » comme "
       "établissement mettant le véhicule à disposition. Cela permet de coordonner votre passage "
       "avec ceux des autres candidats du centre.")
CENTRES = {"06": "Saint-Laurent-du-Var (06)", "83": "La Valette-du-Var (83)"}
AREA = "Le véhicule est proposé uniquement pour les examens de Saint-Laurent-du-Var (06) et de La Valette-du-Var (83)."
OFFERS = {"vehicule": "Prêt du véhicule à double commande",
          "formation": "Formation pratique et prêt du véhicule", "cpf": "Formation pratique et prêt du véhicule"}
BOOKING = "https://calendly.com/integraleacademy/chauffeurvtc"
SCHOOL = "Intégrale Sécurité Formations – Intégrale Academy, 54 chemin du Carreou, 83480 Puget-sur-Argens"
CONTACT = "ecole@integraleacademy.com · 04 22 47 07 68"


def order_contract(host, row, path):
    cpf = row["offer"] == "cpf"
    funding = []
    if cpf:
        reference = row.get("cpf_reference")
        funding = ["Prise en charge confirmée par le centre. Dossier Mon Compte Formation – " + reference + "."
                   if reference else "Prise en charge sous réserve de validation du dossier sur Mon Compte Formation."]
    doc = vtc_offer_contracts.build(
        practice=row["offer"] != "vehicule", person=row["person"], price=money(row["total_cents"]) + " TTC",
        exam_day=row.get("exam_date"), centre=CENTRES.get(row.get("exam_centre")), slot=row.get("slot"),
        reference=("commande-vtc", row["id"], row.get("agreement_version", 1), row["offer"]),
        payment=METHODS[method(row)], online_order=True, cpf=cpf, funding=funding,
    )
    # Publish only a complete PDF, with its matching coordinates, after conversion and validation.
    with tempfile.TemporaryDirectory(prefix="convention-vtc-", dir=path.parent) as folder:
        _, pdf = write_pdf(host, doc, folder, "convention")
        clean, anchors = host._prepare_yousign_pdf_and_fields(pdf)
        fields = [a for a in anchors if a["type"] == "signature"]
        if len(fields) != 1:
            raise ValueError("Le cadre de signature du candidat est introuvable dans la convention VTC.")
        field = {key: fields[0][key] for key in ("page", "x", "y", "width", "height")}
        os.replace(clean, path)
    return field


def document(row, path, *, completed=False):
    font = retake_font()
    normal = ParagraphStyle("body", fontName=font, fontSize=9.5, leading=12.5, textColor=colors.HexColor("#21354D"), spaceAfter=5)
    heading = ParagraphStyle("heading", parent=normal, fontName=font+"-Bold", fontSize=12, leading=16, spaceBefore=6)
    title = ParagraphStyle("title", parent=heading, fontSize=20, leading=25, spaceAfter=12)
    story = []

    def line(text, style=normal):
        story.append(Paragraph(escape(str(text)), style))

    person = row["person"]
    name = person["first_name"] + " " + person["last_name"]
    title_text = "Attestation de mise à disposition du véhicule"
    if completed:
        title_text = "Attestation de réalisation"
    line(title_text, title)
    line(SCHOOL + " · SIREN 840 899 884 · NDA 93830600283")
    line("Candidat : " + name)
    if completed:
        slot = row["slot"]
        line("Formation pratique VTC", heading)
        line(f"Intégrale Sécurité Formations atteste que {name} a suivi la séance de préparation à l’épreuve pratique VTC "
             f"le {date_label(slot['day'])}, de {slot['start']} à {slot['end']} ({slot['duration']}), à Puget-sur-Argens.")
        line("Formateur : " + slot["trainer"] + ".")
    else:
        line("Examen pratique VTC", heading)
        line(f"Intégrale Sécurité Formations certifie mettre à la disposition de {name} un véhicule à double commande pour "
             "son passage à l’épreuve pratique VTC organisé avec le centre.")
        if row.get("exam_date"):
            line("Date de passage communiquée : " + date_label(row["exam_date"]) + ".")
        line("Cette attestation accompagne votre convocation officielle de la CMA. L’équipe du centre coordonne la mise à disposition du véhicule.")
    if not completed:
        centre = CENTRES.get(row.get("exam_centre"))
        line("Centre d’examen : " + centre if centre else AREA)
        line(CMA)
    line(CONTACT)
    tmp = Path(path).with_suffix(".writing")
    pdf = SimpleDocTemplate(str(tmp), pagesize=A4, leftMargin=48, rightMargin=48, topMargin=119, bottomMargin=61)
    frame = retake_page_frame(font, "ATTESTATION", row["id"][:10].upper(), "EXAMEN PRATIQUE VTC")
    pdf.build(story, onFirstPage=frame, onLaterPages=frame)
    os.replace(tmp, path)
