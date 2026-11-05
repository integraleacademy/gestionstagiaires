"""PDF version of the saved online candidate sheet (same fields as its print view)."""
from html import escape
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Image
from ssiap_exam_pdf import FONT, BOLD

SECTIONS = (
    ("Formation", (
        ("formation_type", "Type de formation"), ("date_entree_stage", "Date d’entrée en stage"),
        ("situation", "Situation professionnelle"), ("company", "Entreprise (salarié ou employeur)"),
        ("financing", "Financement"), ("interviewer", "Entretien réalisé par"))),
    ("Le candidat", (
        ("last_name", "Nom"), ("usage_name", "Nom d’usage"), ("first_names", "Prénoms"),
        ("address", "Adresse"), ("postal_code", "Code postal"), ("city", "Ville"),
        ("phone", "Téléphone"), ("email", "Adresse mail"), ("birth_date", "Date de naissance"),
        ("birth_city", "Lieu de naissance"), ("department", "Département"),
        ("country", "Pays"), ("nationality", "Nationalité"),
        ("emergency_contact", "Contact d’urgence (nom et téléphone)"),
        ("cnaps_number", "Carte professionnelle CNAPS"))),
    ("Suivi des titres RNCP auprès de France compétences", (
        ("study_level", "Niveau d’étude à l’entrée en formation"), ("study_domain", "Domaine des études suivies"),
        ("last_certification_level", "Niveau de la dernière certification"),
        ("last_certification_domain", "Domaine de la dernière certification"),
        ("last_job", "Dernier métier et poste exercé"), ("years_experience", "Durée en années"),
        ("company_name", "Nom de l’entreprise"), ("gross_salary", "Rémunération brute annuelle"))),
)


def build(candidate, host, trainee):
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=36, rightMargin=36,
                            topMargin=32, bottomMargin=50, title="Fiche de renseignement candidat DESP")
    normal = ParagraphStyle("candidate", fontName=FONT, fontSize=8, leading=11)
    heading = ParagraphStyle("section", fontName=BOLD, fontSize=10, leading=14,
                             spaceBefore=10, spaceAfter=5, keepWithNext=True)
    title = ParagraphStyle("title", fontName=BOLD, fontSize=16, leading=21, spaceAfter=8)
    def p(text, style=normal):
        return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)
    story = [p("Fiche de renseignement candidat", title), p("DESP initial · Dossier SCOTIA")]
    photo = str(trainee.get("identity_photo") or "")
    if photo and host._partner_can_access_upload_token(photo):
        path = Path(host._detokenize_path(photo))
        if path.is_file():
            try:
                from PIL import Image as PILImage, ImageOps
                with PILImage.open(path) as source:
                    picture = ImageOps.exif_transpose(source).convert("RGB")
                    picture.thumbnail((600, 800))
                    data = BytesIO()
                    picture.save(data, format="JPEG")
                    data.seek(0)
                image = Image(data, width=48, height=64, kind="proportional")
                story[0] = Table([[story[0], image]], colWidths=[doc.width - 60, 60])
            except (OSError, ValueError):
                pass  # The photo is optional in the existing candidate sheet.
    for label, fields in SECTIONS:
        story.append(p(label, heading))
        rows = [[p(label), p(candidate.get(key))] for key, label in fields]
        table = Table(rows, colWidths=[215, doc.width - 215], hAlign="LEFT")
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f8")),
            ("LINEBELOW", (0, 0), (-1, -1), .3, colors.HexColor("#d5dfe9")),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(table)
    def footer(canvas, _doc):
        canvas.setFont(FONT, 6.5)
        canvas.drawCentredString(A4[0] / 2, 29, "SCOTIA FORMATION - 1662 RN7 - 06270 Villeneuve Loubet")
        canvas.drawCentredString(A4[0] / 2, 19, "NDA 93061023706 - Siret 91812189800012 - APE 8559A - www.scotiagroupe.com")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
