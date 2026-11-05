"""Nominative documents for the practical VTC offers, separate from the 105 h course."""
import os
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer

from exam_retakes import date_label
from exam_retakes_documents import retake_font, retake_page_frame

CMA = ("Au moment de votre inscription à l’examen pratique auprès de la Chambre de métiers "
       "et de l’artisanat, indiquez « Intégrale Academy – Intégrale Sécurité Formations » comme "
       "établissement mettant le véhicule à disposition. Cela permet de coordonner votre passage "
       "avec ceux des autres candidats du centre.")
OFFERS = {"vehicule": "Prêt du véhicule à double commande",
          "formation": "Formation pratique et prêt du véhicule", "cpf": "Formation pratique et prêt du véhicule"}
BOOKING = "https://calendly.com/integraleacademy/chauffeurvtc"
SCHOOL = "Intégrale Sécurité Formations – Intégrale Academy, 54 chemin du Carreou, 83480 Puget-sur-Argens"
CONTACT = "ecole@integraleacademy.com · 04 22 47 07 68"


def document(row, path, *, contract=False, completed=False):
    font = retake_font()
    normal = ParagraphStyle("body", fontName=font, fontSize=9.5, leading=13, textColor=colors.HexColor("#21354D"), spaceAfter=6)
    heading = ParagraphStyle("heading", parent=normal, fontName=font+"-Bold", fontSize=12, leading=16, spaceBefore=6)
    title = ParagraphStyle("title", parent=heading, fontSize=20, leading=25, spaceAfter=12)
    story, field = [], {}

    def line(text, style=normal):
        story.append(Paragraph(escape(str(text)), style))

    person = row["person"]
    name = person["first_name"] + " " + person["last_name"]
    title_text = "Attestation de mise à disposition du véhicule"
    if contract:
        title_text = "Contrat individuel de formation professionnelle"
    elif completed:
        title_text = "Attestation de réalisation"
    line(title_text, title)
    line(SCHOOL + " · SIREN 840 899 884 · NDA 93830600283")
    line("Candidat : " + name)
    if contract:
        line("Adresse : " + person["address"] + ", " + person["zip_code"] + " " + person["city"])
        slot = row["slot"]
        line("Formation pratique à l’examen VTC", heading)
        line("Objectif : préparer l’épreuve pratique d’admission. Public : candidats admissibles à l’examen pratique VTC. "
             "Prérequis : permis B en cours de validité et admissibilité à l’épreuve pratique.")
        line("Séance en présentiel le " + date_label(slot["day"]) + " de " + slot["start"] + " à " + slot["end"]
             + " (" + slot["duration"] + "), au centre de Puget-sur-Argens. Formateur : " + slot["trainer"] + ".")
        line("Exercices de prise en charge du client, préparation d’un itinéraire, conduite en sécurité et facturation. "
             "Mise en situation au volant d’un véhicule à double commande, observation et bilan avec le formateur. "
             "La CMA organise et évalue l’examen. Une attestation de réalisation est délivrée à l’issue de la formation.")
        line("Véhicule fourni pour votre passage à l’examen pratique. Les droits d’examen sont à régler directement à la CMA.")
        line("Prix, règlement et rétractation", heading)
        line("Prix total : 600 € TTC. Aucun acompte. Règlement par carte après la réalisation de la formation et la mise à disposition "
             "du véhicule, à l’issue du délai de rétractation. Vous disposez de 14 jours à compter de la conclusion du contrat "
             "à distance pour vous rétracter. Utilisez le bouton de votre suivi, écrivez à ecole@integraleacademy.com "
             "ou adressez un courrier au centre. Un accusé de réception vous sera transmis.")
        line("En cas d’abandon ou de force majeure, seules les prestations effectivement réalisées sont dues, au prorata "
             "de leur valeur. En cas d’annulation par le centre, une nouvelle date vous est proposée ou les prestations "
             "non réalisées sont remboursées.")
    elif completed:
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
        line(CMA)
    line(CONTACT)
    if contract:
        class Signature(Flowable):
            width, height = 225, 65
            def draw(self):
                x, y = self.canv.absolutePosition(0, 0)
                field.update(page=self.canv.getPageNumber(), x=round(x), y=round(A4[1]-y-60), width=210, height=60)
        line("Signature du candidat", heading)
        story.extend([Spacer(1, 2), Signature()])
    tmp = Path(path).with_suffix(".writing")
    pdf = SimpleDocTemplate(str(tmp), pagesize=A4, leftMargin=48, rightMargin=48, topMargin=119, bottomMargin=61)
    frame = retake_page_frame(font, "CONTRAT" if contract else "ATTESTATION", row["id"][:10].upper(), "EXAMEN PRATIQUE VTC")
    pdf.build(story, onFirstPage=frame, onLaterPages=frame)
    os.replace(tmp, path)
    return field
