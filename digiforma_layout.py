"""Flow-based attendance layout: no source coordinates or fixed row heights."""

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    Image, KeepTogether, LongTable, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

INK = colors.HexColor("#172D3B")
MUTED = colors.HexColor("#536674")
LIGHT = colors.HexColor("#F0F4F6")
GOLD = colors.HexColor("#E9BB57")
LINE = colors.HexColor("#D9E1E5")
WIDTH = A4[0] - 80


def _text(value):
    return escape(str(value or "Non renseigné").replace("\u00a0", " ").replace("—", "-").replace("–", "-"))


def render_attendance(report, signature):
    styles = {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=24, leading=28, textColor=INK, spaceAfter=18),
        "heading": ParagraphStyle("heading", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=INK, spaceAfter=12),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14, textColor=INK, spaceAfter=8),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8.5, leading=11, textColor=MUTED),
        "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=9.5, leading=12.5, textColor=INK),
        "center": ParagraphStyle("center", fontName="Helvetica", fontSize=9.2, leading=12, alignment=TA_CENTER, textColor=INK),
        "header": ParagraphStyle("header", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=colors.white),
        "log": ParagraphStyle("log", fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK),
    }

    def p(value, style="body"):
        return Paragraph(_text(value).replace("\n", "<br/>"), styles[style])

    def table(rows, widths, *, header=True):
        result = LongTable(rows, colWidths=widths, repeatRows=1 if header else 0,
                           hAlign="LEFT", splitByRow=1, splitInRow=1)
        commands = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LINEBELOW", (0, 0), (-1, -1), .4, LINE),
        ]
        if header:
            commands += [
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ]
        result.setStyle(TableStyle(commands))
        return result

    def details(items):
        return table([[p(label, "small"), p(value, "cell")] for label, value in items if value],
                     [150, WIDTH - 150], header=False)

    def page_chrome(canvas, doc):
        canvas.saveState()
        logo = Path(__file__).parent / "static/logo-integrale.png"
        if logo.is_file():
            canvas.drawImage(str(logo), 40, A4[1] - 65, width=34, height=34, mask="auto")
        canvas.setFillColor(INK)
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawString(84, A4[1] - 43, "INTÉGRALE ACADEMY")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(84, A4[1] - 57, "Attestation d'assiduité - formation à distance")
        canvas.setStrokeColor(GOLD)
        canvas.setLineWidth(2)
        canvas.line(40, A4[1] - 76, A4[0] - 40, A4[1] - 76)
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(.5)
        canvas.line(40, 48, A4[0] - 40, 48)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(40, 34, "Établi à partir du relevé Digiforma - mise en page Intégrale Academy")
        canvas.restoreState()

    identity = report["identity"]
    story = [p("ATTESTATION\nD'ASSIDUITÉ", "title")]
    if identity.get("attested_name"):
        story += [p(identity["attested_name"], "heading")]
    if identity.get("training_title"):
        story += [p(identity["training_title"])]
    story += [Spacer(1, 12), p("Formation et participation", "heading")]
    story += [details([
        ("Période de formation", identity.get("period")),
        ("Lieu", identity.get("location")),
        ("Type d'action", identity.get("action_type")),
        ("Durée prévue", identity.get("planned_duration")),
        ("Durée effectivement suivie", identity.get("effective_duration")),
        ("Taux de réalisation", identity.get("completion_rate")),
        ("Identifiant Digiforma", identity.get("email")),
        ("Jours d'accès", identity.get("access_days")),
        ("Connexions - synthèse Digiforma", identity.get("connection_duration")),
        ("Connexions - total du journal", report.get("connection_total")),
    ])]
    story += [Spacer(1, 18), p("Attestation du prestataire", "heading")]
    story += [p("Je soussigné Clément VAILLANT, directeur général d'Intégrale Academy, "
                "atteste de la participation du stagiaire à la formation et des éléments "
                "d'assiduité détaillés dans le présent document, repris du relevé Digiforma.")]
    if report.get("provider"):
        story += [Spacer(1, 8), p(report["provider"], "small")]

    for course in report["courses"]:
        story += [PageBreak(), p(f"PARCOURS {course['number']}", "small"), Spacer(1, 6),
                  p(course["title"], "heading")]
        metrics = []
        for key, label in (("planned", "Durée prévue"), ("completed", "Durée réalisée"),
                           ("status", "Statut"), ("progress", "Progression")):
            if course.get(key):
                metrics.append(label + " : " + course[key])
        if metrics:
            story += [p("   |   ".join(metrics), "small"), Spacer(1, 16)]
        rows = [[p(label, "header") for label in (
            "Module / activité", "Avancée pédagogique", "Première connexion", "Dernière connexion",
        )]]
        for activity in course["activities"]:
            label = _text(activity["name"])
            extra = " - ".join(x for x in (activity.get("type"), activity.get("duration")) if x)
            if extra:
                label += '<br/><font size="8" color="#536674">' + _text(extra) + "</font>"
            rows.append([
                Paragraph(label, styles["cell"]),
                p(activity.get("progress"), "center"),
                p(activity.get("first"), "center"),
                p(activity.get("last"), "center"),
            ])
        if len(rows) > 1:
            story += [table(rows, [WIDTH - 285, 85, 100, 100])]
        else:
            story += [p("Aucune activité détaillée dans le relevé source.", "small")]
        if course.get("total"):
            total = course["total"]
            story += [Spacer(1, 10), details([
                ("Total du parcours", total.get("duration")),
                ("Première connexion", total.get("first")),
                ("Dernière connexion", total.get("last")),
                ("Avancée pédagogique", total.get("progress")),
            ])]

    story += [PageBreak(), p("JOURNAL DES CONNEXIONS", "heading")]
    if identity.get("email"):
        story += [p("Identifiant : " + identity["email"], "small"), Spacer(1, 12)]
    connections = report["connections"]
    if connections:
        rows = [[p(label, "header") for label in (
            "Connexion", "Déconnexion", "Durée de connexion", "Adresse IP",
        )]]
        rows += [[p(value, "log") for value in row] for row in connections]
        journal = table(rows, [124, 124, WIDTH - 337, 89])
        journal.setStyle(TableStyle([
            ("TOPPADDING", (0, 1), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story += [journal]
    if report.get("connection_total"):
        story += [Spacer(1, 12), p("Durée totale du journal : " + report["connection_total"])]
    signature_block = [Spacer(1, 18)]
    if report.get("issued"):
        signature_block += [p(report["issued"])]
    signature_block += [p("Clément VAILLANT", "heading"), p("Directeur général Intégrale Academy", "small"),
                        Spacer(1, 8), Image(BytesIO(signature), width=170, height=66, kind="proportional", hAlign="LEFT")]
    story += [KeepTogether(signature_block)]
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=40, rightMargin=40,
                            topMargin=96, bottomMargin=66, title="Attestation d'assiduité",
                            author="Intégrale Academy", pageCompression=1)
    doc.build(story, onFirstPage=page_chrome, onLaterPages=page_chrome)
    return output.getvalue()
