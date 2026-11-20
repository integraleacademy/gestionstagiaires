"""Nominative documents for the practical VTC offers, separate from the 105 h course."""
import os
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from exam_retakes import date_label, money
from vtc_order_finance import METHODS, method
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


def document(row, path, *, contract=False, completed=False):
    font = retake_font()
    normal = ParagraphStyle("body", fontName=font, fontSize=9.5, leading=12.5, textColor=colors.HexColor("#21354D"), spaceAfter=5)
    heading = ParagraphStyle("heading", parent=normal, fontName=font+"-Bold", fontSize=12, leading=16, spaceBefore=6)
    title = ParagraphStyle("title", parent=heading, fontSize=20, leading=25, spaceAfter=12)
    story, field = [], {}

    def line(text, style=normal):
        story.append(Paragraph(escape(str(text)), style))

    person = row["person"]
    name = person["first_name"] + " " + person["last_name"]
    title_text = "Attestation de mise à disposition du véhicule"
    vehicle_only = row["offer"] == "vehicule"
    if contract:
        title_text = "Convention de mise à disposition du véhicule" if vehicle_only else "Convention de formation pratique VTC"
    elif completed:
        title_text = "Attestation de réalisation"
    line(title_text, title)
    line(SCHOOL + " · SIREN 840 899 884 · NDA 93830600283")
    line("Candidat : " + name)
    if contract:
        address = ", ".join(filter(None, [person.get("address"), " ".join(filter(None, [person.get("zip_code"), person.get("city")]))]))
        if address:
            line("Adresse : " + address)
        line("Contact : " + person["email"] + " · " + person["phone"])
        line(OFFERS[row["offer"]], heading)
        if vehicle_only:
            line("Intégrale Academy met à disposition du candidat un véhicule à double commande pour son passage "
                 "à l’épreuve pratique VTC organisée par la CMA. La prestation porte uniquement sur le prêt du véhicule le jour de l’examen.")
            line("La date et l’horaire définitifs sont fixés par la CMA. Le candidat transmet sa convocation à l’école "
                 "afin de coordonner le passage avec le centre.")
        else:
            if row["offer"] == "formation":
                line("Contrat individuel de formation professionnelle")
            line("Objectif : préparer l’épreuve pratique d’admission. Public : candidats admissibles à l’examen pratique VTC. "
                 "Prérequis : permis B en cours de validité et admissibilité à l’épreuve pratique.")
            slot = row.get("slot")
            if slot:
                line("Séance en présentiel le " + date_label(slot["day"]) + " de " + slot["start"] + " à " + slot["end"]
                     + " (" + slot["duration"] + "), au centre de Puget-sur-Argens. Formateur : " + slot["trainer"] + ".")
            else:
                line("Projet de convention · Date, horaires et formateur à compléter avant signature.")
            line("Exercices de prise en charge du client, préparation d’un itinéraire, conduite en sécurité et facturation. "
                 "Mise en situation au volant d’un véhicule à double commande, observation et bilan avec le formateur. "
                 "La CMA organise et évalue l’examen. Une attestation de réalisation est délivrée à l’issue de la formation.")
        if row.get("exam_date"):
            line("Date d’examen communiquée : " + date_label(row["exam_date"]) + ".")
        line("Les droits d’examen sont à régler directement à la CMA.")
        line("Prix et règlement", heading)
        line("Prix total : " + money(row["total_cents"]) + " TTC. Mode de règlement : " + METHODS[method(row)] + ".")
        if vehicle_only:
            line("Le centre accorde un délai de rétractation de 14 jours après la commande, avant exécution. "
                 "En cas d’indisponibilité à la date convenue, un autre créneau est proposé avec votre accord "
                 "ou la prestation non fournie est remboursée.")
        elif row["offer"] == "cpf":
            if row.get("cpf_reference"):
                line("Prise en charge confirmée par le centre. Dossier Mon Compte Formation : " + row["cpf_reference"] + ".")
            else:
                line("Prise en charge sous réserve de validation du dossier sur Mon Compte Formation.")
            line("Les modalités de financement et d’annulation figurent dans votre dossier Mon Compte Formation.")
        else:
            line("Aucun acompte. Règlement après la réalisation de la formation et la mise à disposition du véhicule, "
                 "à l’issue du délai de rétractation. Vous disposez de 14 jours à compter de la conclusion du contrat "
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
        centre = CENTRES.get(row.get("exam_centre"))
        line("Centre d’examen : " + centre if centre else AREA)
        line(CMA)
    line(CONTACT)
    if contract:
        class Signature(Flowable):
            width, height = 225, 65
            def draw(self):
                x, y = self.canv.absolutePosition(0, 0)
                field.update(page=self.canv.getPageNumber(), x=round(x), y=round(A4[1]-y-60), width=210, height=60)
        story.append(KeepTogether([Paragraph("Signature du candidat", heading), Spacer(1, 2), Signature()]))
    tmp = Path(path).with_suffix(".writing")
    pdf = SimpleDocTemplate(str(tmp), pagesize=A4, leftMargin=48, rightMargin=48, topMargin=119, bottomMargin=61)
    frame = retake_page_frame(font, "CONVENTION" if contract else "ATTESTATION", row["id"][:10].upper(), "EXAMEN PRATIQUE VTC")
    pdf.build(story, onFirstPage=frame, onLaterPages=frame)
    os.replace(tmp, path)
    return field
