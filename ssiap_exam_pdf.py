"""Portrait examination PDFs, based on the centre's individual and collective PV models."""
import io
import os
import datetime as dt
import zipfile
from functools import lru_cache
from zoneinfo import ZoneInfo

import fitz
from html import escape

from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph
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


@lru_cache(maxsize=2)
def official_template(root, kind):
    path = os.path.join(root, 'templates_word', 'ssiap_exam', f'pv_{kind}_ssiap1.pdf')
    with open(path, 'rb') as source:
        raw = source.read()
    with fitz.open(stream=raw, filetype='pdf') as document:
        font = next(f for f in document[0].get_fonts() if f[4] == 'ExamRegular')
        font_bytes = document.extract_font(font[0])[3]
    return raw, font_bytes


def form_text(page, font, text, x, y, width, size=12):
    text = str(text or '').replace('\n', ' ').strip()
    if not text:
        return
    length = font.text_length(text, fontsize=size)
    fitted = min(size, size * width / max(length, 1))
    if fitted < 7:
        raise ValueError('Une information est trop longue pour le champ du modèle officiel. Réduisez-la avant de télécharger le PV.')
    page.insert_text((x, y), text, fontname='ExamRegular', fontsize=fitted, color=(0, 0, 0))


def check_model(config):
    if config['level'] != 'SSIAP 1':
        raise ValueError('Le modèle fourni concerne le SSIAP 1. Un modèle officiel correspondant est nécessaire pour ce niveau.')


def form_date(page, font, date, y):
    text = 'Examen du ' + (frdate(date) if date else '____/____/____')
    form_text(page, font, text, (float(page.rect.width) - font.text_length(text, fontsize=13)) / 2, y, 300, 13)


def individual(training, trainee, config, candidate, root):
    """Fill identity and date only; every jury field is the untouched supplied form."""
    check_model(config)
    raw, font_bytes = official_template(root, 'individual')
    with fitz.open(stream=raw, filetype='pdf') as document:
        page = document[0]
        font = fitz.Font(fontbuffer=font_bytes)
        form_date(page, font, config['date'], 96.2007446)
        form_text(page, font, 'Nom : ' + str(trainee.get('last_name') or '').upper(), 28.45, 338.05078, 261, 12)
        form_text(page, font, 'Prénom : ' + str(trainee.get('first_name') or ''), 301.95, 338.05078, 261, 12)
        document.set_metadata({'title': 'PV individuel SSIAP 1 - ' + name(trainee), 'author': 'Intégrale Academy'})
        return document.tobytes(garbage=3, deflate=True)


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
    complete = all(d['available'] and not d['review'] for d in docs)
    status = 'Pièces réunies et attestations signées' if complete else 'Dossier à compléter ou à vérifier'
    y = paragraph(c, status, M, y, size=11, color=MINT, bold=True)
    paragraph(c, 'PV individuel · Identité · Secourisme · Certificat médical\nAttestation d’indépendance · Attestation de capacité', M, y - 12, size=9, color=colors.white)
    paragraph(c, config['contact_email'] + ' · ' + config['contact_phone'], M, 36, size=8, color=MINT)
    return finish(c, stream)


def attestation(training, trainee, config, candidate, kind, assets, root):
    c, stream = new_pdf('Attestation - ' + name(trainee))
    independence = kind == 'independence'
    title = 'Attestation d’indépendance' if independence else 'Attestation de capacité'
    y = header(c, title, f"{config['level']} · Examen du {frdate(config['date'])}", root)
    y = info(c, config, y)
    y = paragraph(c, name(trainee), M, y, size=21, bold=True) - 24
    intro = 'Je soussigné, Clément VAILLANT, Directeur général d’Intégrale Academy, représentant l’organisme Intégrale Sécurité Formations,'
    if independence:
        body = f"atteste que le candidat {name(trainee)}, présenté à l’examen {config['level']} du {frdate(config['date'])}, n’exerce pas dans la même entreprise ou structure que les examinateurs ou les membres du jury de cet examen."
    else:
        body = f"atteste qu’à la suite de l’évaluation réalisée par le centre de formation, le candidat {name(trainee)}, présenté à l’examen {config['level']} du {frdate(config['date'])}, a la capacité de rendre compte sur la main courante des anomalies constatées lors d’une ronde et d’alerter les secours."
    y = paragraph(c, intro, M, y, size=12, leading=20) - 20
    y = paragraph(c, body, M, y, size=12, leading=20) - 30
    issued_date = dt.datetime.now(ZoneInfo('Europe/Paris')).date().isoformat()
    y = paragraph(c, 'Fait à Puget-sur-Argens, le ' + frdate(issued_date), M, y, size=10) - 25
    y = paragraph(c, 'Clément VAILLANT\nDirecteur général Intégrale Academy', M, y, size=11, bold=True) - 18
    for key, x, width, height in [('signature', M, 48 * mm, 28 * mm), ('stamp', M + 65 * mm, 72 * mm, 28 * mm)]:
        c.drawImage(ImageReader(io.BytesIO(assets[key])), x, y - height, width, height, preserveAspectRatio=True, anchor='c', mask='auto')
    return finish(c, stream)


@lru_cache(maxsize=1)
def signature_assets(root):
    """Use the exact original stamp and Clément's signature from the SSIAP agreement."""
    try:
        with zipfile.ZipFile(os.path.join(root, 'templates_word', 'conventionssiap.docx')) as source:
            return {'stamp': source.read('word/media/image1.png'),
                    'signature': source.read('word/media/image2.png')}
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise RuntimeError('Le tampon ou la signature de la convention SSIAP est introuvable.') from exc


def dossier(training, trainee, config, candidate, docs, root):
    from document_conversion import convert_upload, ConversionError
    assets = signature_assets(root)
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
        if i == 2:  # Never add a footer, logo or page number to the official PV.
            continue
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
    """Repeat the unchanged 14-slot model when needed, without extending its table."""
    check_model(config)
    raw, font_bytes = official_template(root, 'collective')
    font = fitz.Font(fontbuffer=font_bytes)
    output = fitz.open()
    for start in range(0, max(1, len(trainees)), 14):
        with fitz.open(stream=raw, filetype='pdf') as document:
            page = document[0]
            form_date(page, font, config['date'], 81.75079)
            for index, trainee in enumerate(trainees[start:start + 14]):
                y = 256.85077 + index * 20
                form_text(page, font, str(trainee.get('last_name') or '').upper(), 28.45, y, 145, 14)
                form_text(page, font, trainee.get('first_name') or '', 180.8, y, 177, 14)
            equipment = str(config.get('equipment') or '').strip()
            if equipment:
                words, lines, line = equipment.split(), [], ''
                for word in words:
                    proposal = (line + ' ' + word).strip()
                    if font.text_length(proposal, fontsize=10) > 530 and line:
                        lines.append(line)
                        line = word
                    else:
                        line = proposal
                if line:
                    lines.append(line)
                if len(lines) > 2:
                    raise ValueError('La description des outils est trop longue pour les deux lignes du modèle officiel.')
                for index, line in enumerate(lines):
                    form_text(page, font, line, 28.45, 558 + index * 14, 530, 10)
            presidents = ', '.join(name(m) for m in config['jury'] if m['role'] == 'president')
            members = ', '.join(name(m) for m in config['jury'] if m['role'] == 'member')
            form_text(page, font, presidents, 28.45, 640, 260, 10)
            form_text(page, font, members, 301.25, 640, 260, 10)
            # Results, appraisals and signature areas remain blank for the jury.
            output.insert_pdf(document)
    output.set_metadata({'title': 'Procès-verbal collectif SSIAP 1', 'author': 'Intégrale Academy'})
    result = output.tobytes(garbage=3, deflate=True)
    output.close()
    return result
