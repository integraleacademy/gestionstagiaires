"""SSIAP diploma overlays and the postal covering letter for the DDSIS."""
import datetime as dt
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


# Measured from the vector rules of the supplied Canva PDF, in PDF points.
PHOTO_TOP = 26.414764404296875
PHOTO_RIGHT = 815.5130004882812
PHOTO_WIDTH, PHOTO_HEIGHT = 35 * mm, 45 * mm


def watermark(pdf, width, height, text="APERÇU - NON VALABLE"):
    pdf.saveState()
    pdf.setFillColor(colors.HexColor('#777777'))
    pdf.setFillAlpha(0.25)
    pdf.translate(width / 2, height / 2)
    pdf.rotate(25)
    pdf.setFont('Helvetica-Bold', 34)
    pdf.drawCentredString(0, 0, text)
    pdf.restoreState()


def diplomas_pdf(diplomas, template_path, draw_photo, *, preview=False):
    """Preserve the supplied vector template and its signature at its native size."""
    template = PdfReader(template_path)
    page_width, page_height = map(float, (template.pages[0].mediabox.width, template.pages[0].mediabox.height))
    overlay = BytesIO()
    pdf = canvas.Canvas(overlay, pagesize=(page_width, page_height), pageCompression=1)

    def field(value, x, top_baseline, width):
        text = str(value or '')
        size = min(10.5, width / max(pdfmetrics.stringWidth(text, 'Helvetica-Bold', 1), 1))
        line = pdf.beginText(x, page_height - top_baseline)
        # Do not inherit text spacing or rise from the background template.
        line.setRise(0)
        line.setCharSpace(0)
        line.setWordSpace(0)
        line.setHorizScale(100)
        line.setFont('Helvetica-Bold', size)
        line.textOut(text)
        pdf.drawText(line)

    for row in diplomas:
        draw_photo(pdf, str(row.get('photo_path') or ''), PHOTO_RIGHT - PHOTO_WIDTH,
                   page_height - PHOTO_TOP - PHOTO_HEIGHT, PHOTO_WIDTH, PHOTO_HEIGHT)
        field(row['exam_date'], 611, 317.1919, 195)
        field(row['name'], 460, 348.7038, 346)
        field(row['birth_date'], 460, 364.4597, 346)
        field(row['birth_place'], 460, 380.2156, 346)
        field(row['name'], 493, 458.9953, 313)
        field(row['number'], 493, 474.7513, 313)
        field(row.get('exam_number') or ('À renseigner' if preview else ''), 475, 490.5072, 331)
        field(row['exam_date'], 180, 491.5701, 165)
        if preview:
            watermark(pdf, page_width, page_height)
        pdf.showPage()
    pdf.save()
    overlay.seek(0)
    overlays = PdfReader(overlay)
    writer = PdfWriter()
    for page in overlays.pages:
        # Each merged page needs independent streams and resources.
        writer.reset_translation(template)
        combined = writer.add_page(template.pages[0])
        # The supplied PDF has a non-zero MediaBox origin (8.58 pt vertically).
        combined.merge_transformed_page(page, Transformation().translate(
            tx=float(combined.mediabox.left), ty=float(combined.mediabox.bottom)))
    writer.add_metadata({'/Title': 'Aperçu des diplômes SSIAP' if preview else 'Diplômes SSIAP', '/Author': 'Intégrale Academy'})
    output = BytesIO()
    writer.write(output)
    output.seek(0)
    return output


def sdis_letter(diplomas, config, root, *, preview=False):
    from ssiap_exam_pdf import FONT, BOLD, signature_assets
    assets = signature_assets(root)
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                                 topMargin=16*mm, bottomMargin=18*mm, title='Courrier de transmission des diplômes SSIAP au DDSIS du Var',
                                 author='Clément VAILLANT - Intégrale Academy')
    navy = colors.HexColor('#172b43')
    body = ParagraphStyle('letter', fontName=FONT, fontSize=9.5, leading=14, spaceAfter=8, textColor=navy)
    small = ParagraphStyle('small', parent=body, fontSize=8, leading=11, spaceAfter=2)
    right = ParagraphStyle('right', parent=body, alignment=TA_RIGHT)
    heading = ParagraphStyle('heading', parent=body, fontName=BOLD, fontSize=10, leading=14, spaceAfter=12)
    cell = ParagraphStyle('cell', parent=body, fontSize=8, leading=10.5, spaceAfter=0)
    header_cell = ParagraphStyle('headercell', parent=cell, fontName=BOLD, textColor=colors.white)
    p = lambda text, style=body: Paragraph(text, style)
    safe = lambda value: escape(str(value or ''))
    number = str(config.get('exam_number') or 'À renseigner')
    date = diplomas[0]['exam_date']
    level = str(config.get('level') or 'SSIAP 1')
    approval = str(config.get('approval') or 'Agrément SSIAP n°8323 délivré par la Préfecture du Var le 29/05/2026')
    today = dt.datetime.now(ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y')
    sender = []
    logo = Path(root) / 'static/logo-integrale.png'
    if logo.is_file():
        width, height = ImageReader(str(logo)).getSize()
        sender.append(Image(str(logo), width=22*mm, height=22*mm*height/width, hAlign='LEFT'))
    sender.extend([p('<b>INTÉGRALE ACADEMY</b>', small),
                   p('54 chemin du Carreou<br/>83480 PUGET-SUR-ARGENS<br/>04 22 47 07 68 · ecole@integraleacademy.com', small),
                   p('SIRET : 840 899 884 00026', small)])
    recipient = [Spacer(1, 10*mm), p('<b>DDSIS du Var</b><br/>Groupement Prévention - Secrétariat<br/>24, Allée de Vaugrenier - ZAC Les Ferrières<br/><b>83490 LE MUY</b>')]
    addresses = Table([[sender, recipient]], colWidths=[84*mm, 84*mm], hAlign='LEFT')
    addresses.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'), ('LEFTPADDING',(0,0),(-1,-1),0), ('RIGHTPADDING',(0,0),(-1,-1),0)]))
    story = [addresses, Spacer(1, 4*mm), p(f'À Puget-sur-Argens, le {today}', right),
             p(f'Objet : transmission des diplômes {safe(level)}<br/>Examen n° {safe(number)} du {safe(date)}', heading),
             p(safe(approval), small), Spacer(1, 3*mm), p('Madame, Monsieur,'),
             p(f'Je vous prie de trouver ci-joints les <b>{len(diplomas)} diplômes</b> des candidats certifiés à l’issue de notre examen <b>{safe(level)} n° {safe(number)}</b>, organisé le <b>{safe(date)}</b> dans les locaux d’Intégrale Academy, <b>54 chemin du Carreou, 83480 Puget-sur-Argens</b>, pour signature par le représentant du DDSIS.'),
             p('La liste des candidats certifiés et les références des diplômes transmis figurent ci-dessous :')]
    table_rows = [[p(label, header_cell) for label in ['N°', 'Candidat certifié', 'Date de<br/>naissance', 'Lieu de naissance', 'Numéro de diplôme']]]
    for index, row in enumerate(diplomas, 1):
        name = row['name'].removeprefix('Monsieur ').removeprefix('Madame ')
        table_rows.append([p(str(index), cell), p(safe(name), cell), p(safe(row['birth_date']), cell),
                           p(safe(row['birth_place']), cell), p(safe(row.get('number') or 'À générer'), cell)])
    table = Table(table_rows, colWidths=[8*mm, 40*mm, 24*mm, 46*mm, 50*mm], repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),navy), ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                               ('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
                               ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
                               ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, colors.HexColor('#f3f6f8')]),
                               ('LINEBELOW',(0,0),(-1,0),0.5,navy), ('LINEBELOW',(0,1),(-1,-1),0.25,colors.HexColor('#dce3e8'))]))
    story.append(table)

    def asset(name, width):
        stream = BytesIO(assets[name])
        x, y = ImageReader(stream).getSize()
        stream.seek(0)
        return Image(stream, width=width, height=width*y/x)

    signature = Table([[asset('signature', 31*mm), asset('stamp', 65*mm)]], colWidths=[45*mm, 85*mm])
    signature.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),0)]))
    story.append(KeepTogether([Spacer(1, 4*mm),
        p('Je vous prie d’agréer, Madame, Monsieur, l’expression de mes salutations distinguées.'),
        p('<b>Clément VAILLANT</b><br/>Directeur général - Intégrale Academy'), signature,
        p(f'Pièces jointes : {len(diplomas)} diplôme(s) {safe(level)}.', small)]))

    def footer(pdf, doc):
        pdf.saveState()
        pdf.setStrokeColor(colors.HexColor('#ccd7df'))
        pdf.line(18*mm, 14*mm, A4[0]-18*mm, 14*mm)
        pdf.setFont(FONT, 7)
        pdf.setFillColor(navy)
        pdf.drawString(18*mm, 10*mm, f'Intégrale Academy · Examen n° {number} · {date}')
        pdf.drawRightString(A4[0]-18*mm, 10*mm, f'Page {doc.page}')
        if preview:
            watermark(pdf, *A4, 'APERÇU')
        pdf.restoreState()
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    output.seek(0)
    return output
