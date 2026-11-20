"""SSIAP diploma overlays and the postal covering letter for the DDSIS."""
import datetime as dt
from functools import lru_cache
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
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.platypus import BaseDocTemplate, Frame, Image, KeepTogether, LongTable, NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle


# Measured from the vector rules of the supplied Canva PDF, in PDF points.
PHOTO_TOP = 26.414764404296875
PHOTO_RIGHT = 815.5130004882812
PHOTO_WIDTH, PHOTO_HEIGHT = 35 * mm, 45 * mm

# A fixed right-hand window area on the A4 insert. The address stays inside
# this zone with generous inset margins; the letter starts below it.
SDIS_WINDOW = (105 * mm, 40 * mm, 100 * mm, 45 * mm)  # left, top, width, height


def watermark(pdf, width, height, text="APERÇU - NON VALABLE"):
    pdf.saveState()
    pdf.setFillColor(colors.HexColor('#777777'))
    pdf.setFillAlpha(0.25)
    pdf.translate(width / 2, height / 2)
    pdf.rotate(25)
    pdf.setFont('Helvetica-Bold', 34)
    pdf.drawCentredString(0, 0, text)
    pdf.restoreState()


def draw_verification(pdf, url, width):
    size = 26 * mm
    # Clear of both signature lines and above the red bottom rule.
    x = width - 9.5 * mm - size
    y = 11 * mm
    qr = QrCodeWidget(url, barWidth=size, barHeight=size, barBorder=4, barLevel="M")
    pdf.saveState()
    pdf.setFillColor(colors.white)
    pdf.rect(x, y, size, size, stroke=0, fill=1)
    drawing = Drawing(size, size)
    drawing.add(qr)
    renderPDF.draw(drawing, pdf, x, y)
    pdf.setFillColor(colors.HexColor("#163f78"))
    label = "Vérifiez-moi"
    text = pdf.beginText(x + (size - pdfmetrics.stringWidth(label, "Helvetica-Bold", 8.5)) / 2, y - 7)
    text.setFont("Helvetica-Bold", 8.5)
    text.setCharSpace(0)
    text.setWordSpace(0)
    text.setHorizScale(100)
    text.textOut(label)
    pdf.drawText(text)
    pdf.linkURL(url, (x, y - 10, x + size, y + size), relative=0, thickness=0)
    pdf.restoreState()


@lru_cache(maxsize=2)
def archive_artwork(template_path):
    """Keep the supplied logo, colour artwork and rules, removing all fixed claims and signatures."""
    import pymupdf
    with pymupdf.open(template_path) as doc:
        page = doc[0]
        for image in page.get_image_info(xrefs=True):
            if image["bbox"][1] > 500 and image["xref"]:
                page.delete_image(image["xref"])
        page.add_redact_annot(page.rect, fill=False)
        page.apply_redactions(images=0, graphics=0, text=0)
        return doc.tobytes(garbage=4, deflate=True)


def archive_layout(pdf, row, height):
    from ssiap_diploma_registry import LEVELS
    from ssiap_exam_pdf import FONT, BOLD

    def centered(value, x, top, width, size=10, *, font=FONT, color="#202c40", lines=1):
        value = str(value or "")
        if not value:
            return
        while True:
            wrapped = simpleSplit(value, font, size, width)
            if len(wrapped) <= lines or size <= 5:
                break
            size -= .5
        pdf.setFillColor(colors.HexColor(color))
        for index, line in enumerate(wrapped):
            fitted = min(size, width / max(pdfmetrics.stringWidth(line, font, 1), 1))
            pdf.setFont(font, fitted)
            pdf.drawCentredString(x, height - top - index * (size + 2), line)

    level = row["level"]
    centered("INTÉGRALE", 82, 157, 145, 20, font=BOLD, color="#ffffff")
    centered("ACADEMY", 82, 183, 133, 20, font=BOLD, color="#ffffff")
    centered("Diplôme", 505, 51, 380, 20, font=BOLD)
    centered(LEVELS[level].upper(), 508, 75, 394, 12.5, font=BOLD, lines=2)
    centered(level, 505, 119, 320, 20, font=BOLD, color="#d33a38")
    centered(row.get("registration"), 480, 152, 430, 10, lines=2)
    centered(row["issuer"], 465, 187, 510, 14, font=BOLD)
    centered(row.get("issuer_details"), 460, 205, 510, 9, lines=2)
    centered(row.get("approval"), 452, 236, 525, 10, lines=2)
    centered("Diplôme délivré à", 443, 278, 580, 11)
    centered(row["name"], 440, 306, 630, 22, font=BOLD)
    centered("Né(e) le " + row["birth_date"] + " à " + row["birth_place"], 440, 331, 645, 12, lines=2)
    centered("A satisfait aux épreuves de l’examen " + level + " du " + row["exam_date"],
             425, 369, 710, 12, font=BOLD)
    centered(row.get("exam_place"), 425, 386, 640, 10, lines=2)
    centered("Conformément au procès-verbal du jury d’examen et à l’arrêté du 2 mai 2005 modifié.",
             425, 413, 710, 9)
    centered("Examen n° " + row["exam_number"], 425, 427, 695, 11)
    centered("Diplôme n° " + row["number"], 425, 452, 695, 15, font=BOLD)
    centered("Fait à " + row["issue_place"] + ", le " + row["issue_date"], 380, 482, 650, 10)
    centered("Le représentant du centre", 250, 517, 280, 10)
    centered(row.get("representative"), 250, 534, 270, 10, font=BOLD, lines=2)
    centered("Le représentant du DDSIS", 535, 517, 265, 10)
    centered(row.get("jury_representative"), 535, 534, 265, 10, font=BOLD, lines=2)
    pdf.setStrokeColor(colors.HexColor("#8b929b"))
    for x in (172, 457):
        pdf.line(x, height - 567, x + 155, height - 567)


def diplomas_pdf(diplomas, template_path, draw_photo, *, preview=False):
    """Preserve the supplied vector template and its signature at its native size."""
    from ssiap_diploma_model import draw_mentions, stock_changes, stock_without_slots

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

    backgrounds = []
    stocks = {("SSIAP 1", frozenset()): template}
    for row in diplomas:
        level = row.get("level", "SSIAP 1")
        changes = stock_changes(row) if level == "SSIAP 1" else {}
        stock = (level, frozenset(changes))
        if stock not in stocks:
            artwork = (stock_without_slots(template_path, stock[1]) if level == "SSIAP 1"
                       else archive_artwork(template_path))
            stocks[stock] = PdfReader(BytesIO(artwork))
        backgrounds.append(stocks[stock])
        draw_photo(pdf, str(row.get('photo_path') or ''), PHOTO_RIGHT - PHOTO_WIDTH,
                   page_height - PHOTO_TOP - PHOTO_HEIGHT, PHOTO_WIDTH, PHOTO_HEIGHT)
        if level != "SSIAP 1":
            archive_layout(pdf, row, page_height)
        else:
            field(row['exam_date'], 611, 317.1919, 195)
            field(row['name'], 460, 348.7038, 346)
            field(row['birth_date'], 460, 364.4597, 346)
            field(row['birth_place'], 460, 380.2156, 346)
            field(row['name'], 493, 458.9953, 313)
            field(row['number'], 493, 474.7513, 313)
            field(row.get('exam_number') or ('À renseigner' if preview else ''), 475, 490.5072, 331)
            if "issue_place" not in changes:
                field(row.get("issue_date") or row["exam_date"], 180, 491.5701, 165)
            if changes or row.get("manual"):
                draw_mentions(pdf, page_height, changes, row)
        if row.get("verification_url") and not preview:
            draw_verification(pdf, row["verification_url"], page_width)
        if preview:
            watermark(pdf, page_width, page_height)
        pdf.showPage()
    pdf.save()
    overlay.seek(0)
    overlays = PdfReader(overlay)
    writer = PdfWriter()
    for page, background in zip(overlays.pages, backgrounds):
        # Each merged page needs independent streams and resources.
        writer.reset_translation(background)
        combined = writer.add_page(background.pages[0])
        # The supplied PDF has a non-zero MediaBox origin (8.58 pt vertically).
        combined.merge_transformed_page(page, Transformation().translate(
            tx=float(combined.mediabox.left), ty=float(combined.mediabox.bottom)))
    writer.add_metadata({'/Title': 'Aperçu des diplômes SSIAP' if preview else 'Diplômes SSIAP', '/Author': 'Intégrale Academy'})
    output = BytesIO()
    writer.write(output)
    output.seek(0)
    return output


def sdis_letter(diplomas, config, root, *, preview=False):
    if not diplomas and not preview:
        raise ValueError('Aucun candidat certifié et présenté à cet examen.')
    from ssiap_exam_pdf import FONT, BOLD, signature_assets
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=BOLD, italic=FONT, boldItalic=BOLD)
    assets = signature_assets(root)
    output = BytesIO()
    document = BaseDocTemplate(output, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                               topMargin=20*mm, bottomMargin=20*mm,
                               title='Courrier de transmission des diplômes SSIAP au DDSIS du Var',
                               author='Clément VAILLANT - Intégrale Academy')
    navy = colors.HexColor('#172b43')
    body = ParagraphStyle('letter', fontName=FONT, fontSize=11, leading=16.5, spaceAfter=12, textColor=navy)
    small = ParagraphStyle('small', parent=body, fontSize=9, leading=13.5, spaceAfter=6)
    right = ParagraphStyle('right', parent=body, alignment=TA_RIGHT)
    heading = ParagraphStyle('heading', parent=body, fontName=BOLD, fontSize=11, leading=16, spaceAfter=8)
    cell = ParagraphStyle('cell', parent=body, fontSize=9.5, leading=14, spaceAfter=0)
    header_cell = ParagraphStyle('headercell', parent=cell, fontName=BOLD, textColor=colors.white)
    p = lambda text, style=body: Paragraph(text, style)
    safe = lambda value: escape(str(value or ''))
    number = str(config.get('exam_number') or 'À renseigner')
    try:
        date = dt.date.fromisoformat(str(config.get('date') or '')).strftime('%d/%m/%Y')
    except ValueError:
        date = diplomas[0]['exam_date'] if diplomas else 'À renseigner'
    level = str(config.get('level') or 'SSIAP 1')
    approval = str(config.get('approval') or 'Agrément SSIAP n°8323 délivré par la Préfecture du Var le 29/05/2026')
    today = dt.datetime.now(ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y')
    logo = Path(root) / 'static/logo-integrale.png'
    enclosure = ('ci-joint le <b>diplôme</b> du candidat certifié' if len(diplomas) == 1 else
                 f'ci-joints les <b>{len(diplomas)} diplômes</b> des candidats certifiés' if diplomas else
                 'ci-joints les diplômes des candidats certifiés')
    story = [p(f'À Puget-sur-Argens, le {today}', right), Spacer(1, 3*mm),
             p(f'Objet : transmission des diplômes {safe(level)}<br/>Examen n° {safe(number)} du {safe(date)}', heading),
             p(safe(approval), small), Spacer(1, 4*mm), p('Madame, Monsieur,'),
             p(f'Je vous prie de trouver {enclosure} à l’issue de notre examen <b>{safe(level)}</b>, organisé le <b>{safe(date)}</b> dans les locaux d’Intégrale Academy, <b>54 chemin du Carreou, 83480 Puget-sur-Argens</b>, pour signature par le représentant du DDSIS.'),
             p('Vous trouverez sur les pages suivantes la <b>liste des candidats certifiés</b>, avec leurs dates et lieux de naissance ainsi que les numéros des diplômes transmis.')]

    def asset(name, width):
        stream = BytesIO(assets[name])
        x, y = ImageReader(stream).getSize()
        stream.seek(0)
        return Image(stream, width=width, height=width*y/x)

    signature = Table([[asset('signature', 32*mm), asset('stamp', 58*mm)]], colWidths=[44*mm, 65*mm], hAlign='LEFT')
    signature.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                                   ('LEFTPADDING',(0,0),(-1,-1),0), ('RIGHTPADDING',(0,0),(-1,-1),0),
                                   ('TOPPADDING',(0,0),(-1,-1),3), ('BOTTOMPADDING',(0,0),(-1,-1),5)]))
    story.append(KeepTogether([
        p('Je vous prie d’agréer, Madame, Monsieur, l’expression de mes salutations distinguées.'),
        Spacer(1, 2*mm), p('<b>Clément VAILLANT</b><br/>Directeur général - Intégrale Academy'), signature,
        Spacer(1, 3*mm), p(f'Pièces jointes : {len(diplomas)} diplôme(s) {safe(level)} et liste des certifiés.' if diplomas else 'Pièces jointes : liste à compléter après les résultats.', small)]))
    story.extend([NextPageTemplate('certified-list'), PageBreak(),
                  p(f'<b>{len(diplomas)} candidat(s) certifié(s)</b>' if diplomas else '<b>Liste à compléter après les résultats</b>'), Spacer(1, 2*mm)])

    table_rows = [[p(label, header_cell) for label in ['N°', 'Candidat certifié', 'Date de<br/>naissance', 'Lieu de naissance', 'Numéro de diplôme']]]
    for index, row in enumerate(diplomas, 1):
        name = row['name'].removeprefix('Monsieur ').removeprefix('Madame ')
        table_rows.append([p(str(index), cell), p(safe(name), cell), p(safe(row['birth_date']), cell),
                           p(safe(row['birth_place']), cell), p(safe(row.get('number') or 'À générer'), cell)])
    if not diplomas:
        table_rows.append([p('<b>Aucun candidat certifié renseigné pour le moment.</b><br/>La liste sera complétée après la saisie des résultats dans l’onglet Diplômes.', cell), '', '', '', ''])
    table = LongTable(table_rows, colWidths=[10*mm, 43*mm, 25*mm, 42*mm, 50*mm], repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),navy), ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                               ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
                               ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),
                               ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, colors.HexColor('#f3f6f8')]),
                               ('LINEBELOW',(0,0),(-1,0),0.5,navy), ('LINEBELOW',(0,1),(-1,-1),0.25,colors.HexColor('#dce3e8'))]))
    if not diplomas:
        table.setStyle(TableStyle([('SPAN',(0,1),(-1,1)), ('BACKGROUND',(0,1),(-1,1),colors.HexColor('#fff5d9'))]))
    story.append(table)

    def footer(pdf, doc):
        pdf.setViewerPreference('PrintScaling', 'None')
        pdf.saveState()
        pdf.setStrokeColor(colors.HexColor('#ccd7df'))
        pdf.line(20*mm, 14*mm, A4[0]-20*mm, 14*mm)
        pdf.setFont(FONT, 7)
        pdf.setFillColor(navy)
        pdf.drawString(20*mm, 10*mm, f'Intégrale Academy · Examen n° {number} · {date}')
        pdf.drawRightString(A4[0]-20*mm, 10*mm, f'Page {doc.page}')
        if preview:
            watermark(pdf, *A4, 'APERÇU')
        pdf.restoreState()
    def at(pdf, text, x, top, width, style):
        paragraph = p(text, style)
        _, height = paragraph.wrap(width, A4[1])
        paragraph.drawOn(pdf, x, A4[1]-top-height)

    def cover_page(pdf, doc):
        footer(pdf, doc)
        if logo.is_file():
            pdf.drawImage(str(logo), 20*mm, A4[1]-40*mm, width=20*mm, height=22*mm,
                          preserveAspectRatio=True, anchor='c', mask='auto')
        at(pdf, '<b>INTÉGRALE ACADEMY</b>', 46*mm, 22*mm, 130*mm, heading)
        at(pdf, '54 chemin du Carreou<br/>83480 PUGET-SUR-ARGENS<br/>04 22 47 07 68<br/>ecole@integraleacademy.com<br/>SIRET : 840 899 884 00026',
           20*mm, 45*mm, 76*mm, small)
        address = ParagraphStyle('recipient', parent=body, fontSize=10.5, leading=14.5, spaceAfter=0)
        left, top, _, _ = SDIS_WINDOW
        at(pdf, '<b>DDSIS du Var</b><br/>Groupement Prévention - Secrétariat<br/>24, Allée de Vaugrenier<br/>ZAC Les Ferrières<br/><b>83490 LE MUY</b>',
           left+7*mm, top+5*mm, 83*mm, address)

    def list_page(pdf, doc):
        footer(pdf, doc)
        title = ParagraphStyle('listtitle', parent=heading, fontSize=17, leading=22)
        at(pdf, 'Liste des candidats certifiés', 20*mm, 20*mm, 170*mm, title)
        at(pdf, f'{safe(level)} - Examen du {safe(date)}<br/>N° {safe(number)}', 20*mm, 31*mm, 170*mm, small)

    def frame(top, name):
        return Frame(20*mm, 20*mm, 170*mm, A4[1]-(top+20)*mm, id=name,
                     leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

    document.addPageTemplates([
        PageTemplate(id='letter', frames=[frame(100, 'letter-body')], onPage=cover_page),
        PageTemplate(id='certified-list', frames=[frame(50, 'list-body')], onPage=list_page),
    ])
    document.build(story)
    output.seek(0)
    return output
