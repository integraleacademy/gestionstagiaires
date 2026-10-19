"""Portrait examination PDFs, based on the centre's individual and collective PV models."""
import io
import os
from html import escape

from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from ssiap_exam import frdate

W, H = A4
M = 18 * mm
WIDTH = W - 2 * M
NAVY = colors.HexColor('#0c1a2f')
TEAL = colors.HexColor('#008da8')
MINT = colors.HexColor('#a1d4cb')
MUTED = colors.HexColor('#546579')
LIGHT = colors.HexColor('#eef4f8')
FONT, BOLD = 'SSIAPSans', 'SSIAPSansBold'
for font_name, filename in ((FONT, 'DejaVuSans.ttf'), (BOLD, 'DejaVuSans-Bold.ttf')):
    pdfmetrics.registerFont(TTFont(font_name, '/usr/share/fonts/truetype/dejavu/' + filename))


def paragraph(canvas, text, x, top, width=WIDTH, size=10, color=NAVY, bold=False, leading=None):
    style = ParagraphStyle('text', fontName=BOLD if bold else FONT, fontSize=size,
                           leading=leading or size * 1.45, textColor=color, spaceAfter=0)
    p = Paragraph(escape(str(text)).replace('\n', '<br/>'), style)
    _, height = p.wrap(width, H)
    p.drawOn(canvas, x, top - height)
    return top - height


def new_pdf(title):
    stream = io.BytesIO()
    c = Canvas(stream, pagesize=A4)
    c.setTitle(title)
    c.setAuthor('Intégrale Academy')
    return c, stream


def finish(c, stream):
    c.save()
    return stream.getvalue()


def header(c, title, subtitle, root):
    c.setFillColor(TEAL)
    c.rect(0, H - 5, W, 5, fill=1, stroke=0)
    logo = os.path.join(root, 'static', 'logo-integrale.png')
    if os.path.isfile(logo):
        c.drawImage(logo, M, H - 24 * mm, width=32 * mm, height=13 * mm, preserveAspectRatio=True, anchor='c', mask='auto')
    paragraph(c, 'INTÉGRALE ACADEMY / EXAMEN SSIAP', M + 40 * mm, H - 16 * mm,
              WIDTH - 40 * mm, 8, MUTED)
    y = paragraph(c, title, M, H - 38 * mm, size=24, bold=True)
    y = paragraph(c, subtitle, M, y - 9, size=10, color=MUTED)
    return y - 22


def section(c, label, y):
    c.setFillColor(LIGHT)
    c.roundRect(M, y - 24, WIDTH, 24, 5, fill=1, stroke=0)
    paragraph(c, label, M + 10, y - 5, WIDTH - 20, 10, bold=True)
    return y - 36


def info(c, config, y):
    y = paragraph(c, 'Organisé par Intégrale Sécurité Formations - Intégrale Academy', M, y, size=10, bold=True)
    y = paragraph(c, f"{config['location']} · {config['address']}", M, y - 5, size=9)
    y = paragraph(c, f"Tél. {config['contact_phone']} · {config['contact_email']}", M, y - 4, size=9)
    return paragraph(c, config['approval'], M, y - 4, size=8, color=MUTED) - 17


def name(trainee):
    return ' '.join([str(trainee.get('first_name') or ''), str(trainee.get('last_name') or '').upper()]).strip()


def checkbox(c, x, y, label, checked=False):
    c.setStrokeColor(MUTED)
    c.rect(x, y - 9, 9, 9, stroke=1, fill=0)
    if checked:
        c.setStrokeColor(TEAL)
        c.line(x + 2, y - 5, x + 4, y - 7)
        c.line(x + 4, y - 7, x + 8, y - 2)
    paragraph(c, label, x + 15, y + 2, 120, 9)


def jury_names(config, role):
    return ', '.join(name(m) for m in config['jury'] if m['role'] == role)


def signature_boxes(c, config, y, *, collective=False):
    cols = [('Président du jury', jury_names(config, 'president'), 'Signature et cachet'),
            ('Membre(s) du jury', jury_names(config, 'member'), 'Signature'),
            ('Organisme de formation', 'Clément VAILLANT', 'Signature et cachet' if collective else 'Cachet')]
    cell_width = WIDTH / 3
    for index, (label, person, hint) in enumerate(cols):
        x = M + index * cell_width
        c.setStrokeColor(colors.HexColor('#d7e1eb'))
        c.rect(x, y - 100, cell_width, 100, stroke=1, fill=0)
        bottom = paragraph(c, label, x + 8, y - 9, cell_width - 16, 9, bold=True)
        bottom = paragraph(c, person, x + 8, bottom - 6, cell_width - 16, 8)
        paragraph(c, hint, x + 8, bottom - 4, cell_width - 16, 7, color=MUTED)


def individual(training, trainee, config, candidate, root):
    c, stream = new_pdf('PV individuel - ' + name(trainee))
    y = header(c, "Fiche d’évaluation", f"{config['level']} · Examen du {frdate(config['date'])}" + (f" à {config['time']}" if config['time'] else ''), root)
    y = info(c, config, y)
    y = section(c, 'CANDIDAT', y)
    y = paragraph(c, f"Nom : {str(trainee.get('last_name') or '').upper()}\nPrénom : {trainee.get('first_name') or ''}", M, y, size=12, bold=True) - 20
    y = section(c, 'ÉPREUVE ÉCRITE (QCM)', y)
    paragraph(c, f"Note : {candidate['grade'] or '........'} / 20", M, y, size=12)
    checkbox(c, M + 215, y - 2, 'VALIDÉ', candidate['written'] == 'valid')
    checkbox(c, M + 335, y - 2, 'AJOURNÉ', candidate['written'] == 'failed')
    y = paragraph(c, 'Réussie le : ' + (frdate(candidate['written_date']) if candidate['written_date'] else '................................'), M, y - 29, size=9) - 20
    y = section(c, 'ÉPREUVE PRATIQUE', y)
    paragraph(c, 'Évaluation finale', M, y, size=10)
    checkbox(c, M + 215, y - 2, 'APTE', candidate['practical'] == 'fit')
    checkbox(c, M + 335, y - 2, 'INAPTE', candidate['practical'] == 'unfit')
    y = paragraph(c, 'Réussie le : ' + (frdate(candidate['practical_date']) if candidate['practical_date'] else '................................'), M, y - 29, size=9) - 17
    y = paragraph(c, 'Motivation de l’inaptitude', M, y, size=9, bold=True) - 7
    c.setStrokeColor(colors.HexColor('#d7e1eb'))
    box_height = 104
    c.rect(M, y - box_height, WIDTH, box_height, stroke=1, fill=0)
    end = paragraph(c, candidate['reason'], M + 10, y - 9, WIDTH - 20, size=9)
    if end < y - box_height + 5:
        raise ValueError('La motivation de l’inaptitude est trop longue pour le PV. Réduisez-la.')
    signature_boxes(c, config, y - box_height - 22)
    return finish(c, stream)


def cover(training, trainee, config, candidate, docs, root):
    c, stream = new_pdf('Dossier examen SSIAP - ' + name(trainee))
    c.setFillColor(NAVY)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(TEAL)
    c.rect(0, H - 5, W, 5, fill=1, stroke=0)
    logo = os.path.join(root, 'static', 'logo-integrale.png')
    if os.path.isfile(logo):
        c.drawImage(logo, M, H - 29 * mm, 17 * mm, 17 * mm, preserveAspectRatio=True, mask='auto')
    paragraph(c, 'INTÉGRALE ACADEMY / DOSSIER CANDIDAT', M + 24 * mm, H - 18 * mm, WIDTH - 24 * mm, 8, colors.white)
    y = paragraph(c, 'Dossier examen\n' + config['level'], M, H - 45 * mm, size=34, color=colors.white, bold=True, leading=39)
    y = paragraph(c, name(trainee), M, y - 15, size=21, color=MINT, bold=True) - 18
    illustration = os.path.join(root, 'static', 'manuals', 'powerpoint-previews', 'ssiap1_recyclage-scene.webp')
    if os.path.isfile(illustration):
        image_height = 69 * mm
        c.drawImage(ImageReader(illustration), M, y - image_height, WIDTH, image_height, preserveAspectRatio=True, anchor='c')
        y -= image_height + 20
    details = [('FORMATION', f"Du {frdate(training.get('date_start'))} au {frdate(training.get('date_end'))}"),
               ('EXAMEN', f"{frdate(config['date'])}" + (f" à {config['time']}" if config['time'] else ' - heure à renseigner')),
               ('LIEU', config['location'] + '\n' + config['address'])]
    for label, value in details:
        y = paragraph(c, label, M, y, size=8, color=MINT, bold=True) - 4
        y = paragraph(c, value, M, y, size=11, color=colors.white) - 14
    complete = all(d['available'] and not d['review'] for d in docs) and candidate['independence'] and candidate['ability']
    status = 'Pièces réunies et attestations validées' if complete else 'Dossier à compléter ou à vérifier'
    y = paragraph(c, status, M, y, size=11, color=MINT, bold=True)
    paragraph(c, 'PV individuel · Identité · Secourisme · Certificat médical\nAttestation d’indépendance · Attestation de capacité', M, y - 12, size=9, color=colors.white)
    paragraph(c, config['contact_email'] + ' · ' + config['contact_phone'], M, 36, size=8, color=MINT)
    return finish(c, stream)


def attestation(training, trainee, config, candidate, kind, assets, root):
    c, stream = new_pdf('Attestation - ' + name(trainee))
    independence = kind == 'independence'
    validated = candidate[kind]
    title = 'Attestation d’indépendance' if independence else 'Attestation de capacité'
    y = header(c, title, f"{config['level']} · Examen du {frdate(config['date'])}", root)
    y = info(c, config, y)
    if not validated:
        y = section(c, 'PROJET - VALIDATION DU CENTRE NÉCESSAIRE', y)
    y = paragraph(c, name(trainee), M, y, size=21, bold=True) - 24
    intro = 'Je soussigné, Clément VAILLANT, Directeur général d’Intégrale Academy, représentant l’organisme Intégrale Sécurité Formations,'
    if independence:
        body = f"atteste que le candidat {name(trainee)}, présenté à l’examen {config['level']} du {frdate(config['date'])}, n’exerce pas dans la même entreprise ou structure que les examinateurs ou les membres du jury de cet examen."
    else:
        body = f"atteste qu’à la suite de l’évaluation réalisée par le centre de formation le {frdate(candidate['evaluation_date'])}, le candidat {name(trainee)}, présenté à l’examen {config['level']} du {frdate(config['date'])}, a la capacité de rendre compte sur la main courante des anomalies constatées lors d’une ronde et d’alerter les secours."
    y = paragraph(c, intro, M, y, size=12, leading=20) - 20
    y = paragraph(c, body, M, y, size=12, leading=20) - 30
    if independence and config['jury']:
        y = paragraph(c, 'Jury désigné pour cet examen', M, y, size=10, bold=True) - 7
        for member in config['jury']:
            y = paragraph(c, name(member) + (' - ' + member['company'] if member['company'] else ''), M, y, size=9) - 4
        y -= 16
    if validated:
        y = paragraph(c, 'Fait à Puget-sur-Argens, le ' + frdate(candidate.get('validated_at')), M, y, size=10) - 25
        y = paragraph(c, 'Clément VAILLANT\nDirecteur général Intégrale Academy', M, y, size=11, bold=True) - 18
        if y < 120:
            raise ValueError('Le contenu de l’attestation est trop long. Réduisez les informations du jury.')
        for key, x, width in [('signature', M, 48 * mm), ('stamp', M + 65 * mm, 58 * mm)]:
            c.drawImage(ImageReader(io.BytesIO(assets[key])), x, y - 62, width, 62, preserveAspectRatio=True, anchor='c', mask='auto')
    else:
        paragraph(c, 'Cette attestation sera signée et tamponnée après validation de son contenu dans la fiche Examen du candidat.', M, y, size=10, color=MUTED)
    return finish(c, stream)


def dossier(training, trainee, config, candidate, docs, get_assets, root):
    from document_conversion import convert_upload, ConversionError
    assets = get_assets() if candidate['independence'] or candidate['ability'] else {}
    writer = PdfWriter()
    writer.append(io.BytesIO(cover(training, trainee, config, candidate, docs, root)))
    writer.append(io.BytesIO(individual(training, trainee, config, candidate, root)))
    total_bytes = 0
    for group in docs:
        if not group['available']:
            c, stream = new_pdf(group['label'])
            y = header(c, group['label'], name(trainee), root)
            paragraph(c, 'Pièce manquante ou fichier introuvable', M, y, size=18, bold=True)
            paragraph(c, 'Ajoutez le document dans la fiche du candidat, puis téléchargez à nouveau le dossier examen.', M, y - 55, size=11, color=MUTED)
            writer.append(io.BytesIO(finish(c, stream)))
            # Preserve any available pages, including one side of an incomplete identity document.
        for path in group['paths']:
            size = os.path.getsize(path)
            total_bytes += size
            if size > 25 * 1024 * 1024 or total_bytes > 75 * 1024 * 1024:
                raise ValueError('Le dossier dépasse la taille autorisée. Réduisez les pièces les plus volumineuses.')
            try:
                with open(path, 'rb') as source:
                    raw, _ = convert_upload(source.read(), os.path.basename(path))
                reader = PdfReader(io.BytesIO(raw))
                if len(reader.pages) + len(writer.pages) > 80:
                    raise ValueError('Le dossier dépasse 80 pages. Vérifiez les pièces du candidat.')
                for page in reader.pages:
                    page.transfer_rotation_to_content()
                    width, height = float(page.mediabox.width), float(page.mediabox.height)
                    scale = min(WIDTH / width, (H - 82) / height)
                    c, stream = new_pdf(group['label'])
                    paragraph(c, group['label'].upper() + ' / ' + name(trainee), M, H - 23, size=8, color=MUTED)
                    wrapper = PdfReader(io.BytesIO(finish(c, stream))).pages[0]
                    tx = (W - width * scale) / 2 - float(page.mediabox.left) * scale
                    ty = (H - height * scale) / 2 - float(page.mediabox.bottom) * scale
                    wrapper.merge_transformed_page(page, Transformation().scale(scale).translate(tx, ty))
                    writer.add_page(wrapper)
            except Exception as exc:
                raise ValueError(f"{group['label']} : le fichier ne peut pas être intégré. Remplacez-le par un PDF lisible.") from exc
    for kind in ('independence', 'ability'):
        writer.append(io.BytesIO(attestation(training, trainee, config, candidate, kind, assets, root)))
    for i, page in enumerate(writer.pages, 1):
        c, stream = new_pdf('Pagination')
        c.setFillColor(MINT if i == 1 else MUTED)
        c.setFont(FONT, 8)
        c.drawRightString(W - M, 20, f'{i:02d} / {len(writer.pages):02d}')
        page.merge_page(PdfReader(io.BytesIO(finish(c, stream))).pages[0])
    writer.add_metadata({'/Title': 'Dossier examen SSIAP - ' + name(trainee), '/Author': 'Intégrale Academy'})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def collective(training, trainees, config, root):
    c, stream = new_pdf('Procès-verbal collectif ' + config['level'])
    pages = [trainees[i:i + 12] for i in range(0, len(trainees), 12)] or [[]]
    for number, candidates in enumerate(pages, 1):
        y = header(c, 'Procès-verbal collectif', f"{config['level']} · Examen du {frdate(config['date'])} · Page {number}/{len(pages)}", root)
        y = info(c, config, y)
        style = ParagraphStyle('cell', fontName=FONT, fontSize=9, leading=11, textColor=NAVY)
        rows = [['NOMS', 'PRÉNOMS', 'RÉSULTATS']]
        for t in candidates:
            result = {'certified': 'CERTIFIÉ', 'failed': 'NON CERTIFIÉ'}.get(t.get('ssiap_exam_status'), '')
            rows.append([Paragraph(escape(str(value)), style) for value in (str(t.get('last_name') or '').upper(), t.get('first_name') or '', result)])
        if not candidates:
            rows.append(['Aucun candidat présenté', '', ''])
        table = Table(rows, colWidths=[WIDTH * .34, WIDTH * .31, WIDTH * .35], minRowHeights=[21] * len(rows))
        table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), NAVY), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), BOLD), ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('GRID', (0, 1), (-1, -1), .5, colors.HexColor('#d7e1eb')), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
        _, height = table.wrap(WIDTH, H)
        table.drawOn(c, M, y - height)
        y -= height + 18
        y = paragraph(c, 'Outils pédagogiques et techniques mis en œuvre', M, y, size=9, bold=True) - 5
        y = paragraph(c, config['equipment'] or '................................................................................................................', M, y, size=9) - 15
        if y < 170:
            c.showPage()
            y = header(c, 'Validation du procès-verbal', f"{config['level']} · Examen du {frdate(config['date'])} · Suite de la liste {number}", root)
        signature_boxes(c, config, y, collective=True)
        paragraph(c, 'Procès-verbal dressé par Monsieur Clément VAILLANT, représentant le responsable du centre de formation.', M, y - 113, size=8, color=MUTED)
        if number < len(pages):
            c.showPage()
    return finish(c, stream)
