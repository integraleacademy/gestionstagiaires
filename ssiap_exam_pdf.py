"""Portrait examination PDFs, based on the centre's individual and collective PV models."""
import io
import os
import datetime as dt
import zipfile
from functools import lru_cache
from zoneinfo import ZoneInfo

import fitz
from html import escape
from PIL import Image, ImageOps, UnidentifiedImageError

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
GOLD = colors.HexColor('#e5c77e')
FONT, BOLD = 'SSIAPSans', 'SSIAPSansBold'
for font_name, filename in ((FONT, 'DejaVuSans.ttf'), (BOLD, 'DejaVuSans-Bold.ttf')):
    pdfmetrics.registerFont(TTFont(font_name, '/usr/share/fonts/truetype/dejavu/' + filename))


def paragraph(canvas, text, x, top, width=WIDTH, size=10, color=NAVY, bold=False, leading=None, alignment=0):
    style = ParagraphStyle('text', fontName=BOLD if bold else FONT, fontSize=size,
                           leading=leading or size * 1.45, textColor=color, spaceAfter=0, alignment=alignment)
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


def approval_footer(config, *, dark=False, pagination=''):
    c, stream = new_pdf('Agrément SSIAP')
    text = config['approval']
    c.setFillColor(MINT if dark else MUTED)
    size = min(7.3, (WIDTH - 42) / max(pdfmetrics.stringWidth(text, FONT, 1), 1))
    c.setFont(FONT, size)
    c.drawString(M, 14, text)
    if pagination:
        c.setFont(FONT, 7.3)
        c.drawRightString(W - M, 14, pagination)
    return finish(c, stream)


def form_contact(page, font, config, kind, font_bytes):
    """Replace only the centre's variable contact fields, keeping the supplied form."""
    if kind == 'individual':
        regions = [(26, 188, 298, 220), (26, 230, 298, 262)]
        phone_y, mail_y, approval_y = 201, 215, 244
    else:
        regions = [(26, 134, 290, 166), (26, 168, 290, 185)]
        phone_y, mail_y, approval_y = 146, 161, 179
    for region in regions:
        page.add_redact_annot(fitz.Rect(region), fill=(1, 1, 1))
    page.apply_redactions(images=0, graphics=0, text=0)
    # Redaction removes unused font resources from the blank master.
    page.insert_font(fontname='ExamRegular', fontbuffer=font_bytes)
    form_text(page, font, 'Tél : ' + config['contact_phone'], 28.45, phone_y, 260, 11)
    form_text(page, font, 'Email : ' + config['contact_email'], 28.45, mail_y, 260, 11)
    form_text(page, font, config['approval'], 28.45, approval_y, 538, 9.5)


def form_jurors(page, font, members, rect):
    if not members:
        return
    lines = []
    for member in members:
        lines.append(name(member))
        if member.get('company'):
            lines.append(member['company'])
    text = '\n'.join(lines)
    for size in (9.5, 9, 8, 7):
        shape = page.new_shape()
        if shape.insert_textbox(rect, text, fontname='ExamRegular', fontsize=size, lineheight=1.25) >= 0:
            shape.commit()
            return
    raise ValueError('Les informations du jury sont trop longues pour le cadre du modèle officiel. Réduisez les noms des structures.')


def form_centre_signature(page, font, assets, kind):
    if kind == 'individual':
        form_text(page, font, 'Clément VAILLANT', 399, 705, 164, 9.5)
        signature_rect = fitz.Rect(434, 711, 504, 750)
        stamp_rect = fitz.Rect(400, 745, 563, 791)
    else:
        # The two columns above belong to the jury; sign beside the centre's own label.
        signature_rect = fitz.Rect(185, 778, 253, 816)
        stamp_rect = fitz.Rect(327, 778, 450, 820)
    page.insert_image(signature_rect, stream=assets['signature'], keep_proportion=True)
    page.insert_image(stamp_rect, stream=assets['stamp'], keep_proportion=True)


def form_footer(page, config):
    with fitz.open(stream=approval_footer(config), filetype='pdf') as footer:
        page.show_pdf_page(page.rect, footer)


def individual(training, trainee, config, candidate, root):
    """Fill administrative details; the jury still writes marks and signs by hand."""
    check_model(config)
    raw, font_bytes = official_template(root, 'individual')
    with fitz.open(stream=raw, filetype='pdf') as document:
        page = document[0]
        font = fitz.Font(fontbuffer=font_bytes)
        form_contact(page, font, config, 'individual', font_bytes)
        form_date(page, font, config['date'], 96.2007446)
        form_text(page, font, 'Nom : ' + str(trainee.get('last_name') or '').upper(), 28.45, 338.05078, 261, 12)
        form_text(page, font, 'Prénom : ' + str(trainee.get('first_name') or ''), 301.95, 338.05078, 261, 12)
        form_jurors(page, font, [m for m in config['jury'] if m['role'] == 'member'], fitz.Rect(33, 700, 203, 744))
        form_jurors(page, font, [m for m in config['jury'] if m['role'] == 'president'], fitz.Rect(215, 700, 385, 744))
        form_centre_signature(page, font, signature_assets(root), 'individual')
        form_footer(page, config)
        document.set_metadata({'title': 'PV individuel SSIAP 1 - ' + name(trainee), 'author': 'Intégrale Academy'})
        return document.tobytes(garbage=3, deflate=True)


def official_identity(c, config):
    """Centre identifiers from the SSIAP agreement and the site's legal identity."""
    c.setStrokeColor(colors.HexColor('#dce4ea'))
    c.line(M, 96, W - M, 96)
    lines = [
        'Intégrale Sécurité Formations · SASU · Enseigne Intégrale Academy',
        'SIRET : 840 899 884 00026 · RCS Fréjus 840 899 884 · Code NAF : 8559A',
        'N° de déclaration d’activité (NDA) : 93830600283 · DREETS Provence-Alpes-Côte d’Azur',
        'Cet enregistrement ne vaut pas agrément de l’État.',
        config['contact_email'] + ' · ' + config['contact_phone'],
    ]
    for index, text in enumerate(lines):
        paragraph(c, text, M, 86 - index * 11, size=7.4, color=MUTED, alignment=1)


def candidate_portrait(c, path, x, y, width, height):
    c.setFillColor(LIGHT)
    c.roundRect(x, y, width, height, 6, fill=1, stroke=0)
    if path:
        try:
            with Image.open(path) as source:
                photo = ImageOps.exif_transpose(source).convert('RGB')
                c.drawImage(ImageReader(photo), x + 3, y + 3, width - 6, height - 6,
                            preserveAspectRatio=True, anchor='c')
            return
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            pass
    paragraph(c, 'Photo\nà ajouter', x + 5, y + height / 2 + 13, width - 10,
              size=9, color=MUTED, alignment=1)


def cover(training, trainee, config, candidate, docs, root, photo_path=''):
    c, stream = new_pdf('Dossier examen SSIAP - ' + name(trainee))
    c.setFillColor(colors.HexColor('#f7f9fb'))
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(0, 570, W, H - 570, fill=1, stroke=0)
    c.setFillColor(GOLD)
    c.rect(M, 594, 3, 130, fill=1, stroke=0)
    logo = os.path.join(root, 'static', 'logo-integrale.png')
    if os.path.isfile(logo):
        c.drawImage(logo, M, 756, 46, 46, preserveAspectRatio=True, mask='auto')
    paragraph(c, 'INTÉGRALE ACADEMY', M + 62, 791, WIDTH - 62, 12, colors.white, bold=True)
    paragraph(c, 'DOSSIER CANDIDAT · EXAMEN DE CERTIFICATION', M + 62, 770, WIDTH - 62, 7.5, GOLD)
    paragraph(c, 'Dossier examen', M + 18, 729, WIDTH - 18, 30, colors.white, bold=True)
    paragraph(c, config['level'], M + 18, 688, WIDTH - 18, 45, GOLD, bold=True)
    paragraph(c, 'Service de sécurité incendie\net d’assistance aux personnes', M + 18, 622,
              WIDTH - 18, 10, colors.white, leading=15)
    level_one = config['level'] == 'SSIAP 1'
    illustration_name = 'ssiap1-exam-cover-illustration.png' if level_one else 'ssiap-exam-cover-illustration.png'
    illustration = os.path.join(root, 'static', 'img', illustration_name)
    if os.path.isfile(illustration):
        illustration_width, illustration_height = (190, 180) if level_one else (204, 204)
        c.drawImage(illustration, W - M - 190, 576, illustration_width, illustration_height,
                    preserveAspectRatio=True, anchor='c', mask='auto')

    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor('#dce4ea'))
    c.roundRect(M, 411, WIDTH, 143, 10, fill=1, stroke=1)
    paragraph(c, 'CANDIDAT', M + 18, 537, WIDTH - 156, 8, TEAL, bold=True)
    first, last = str(trainee.get('first_name') or ''), str(trainee.get('last_name') or '').upper()
    fitted = min(22, (WIDTH - 156) / max(pdfmetrics.stringWidth(v, BOLD, 1) for v in (first, last, ' ')))
    paragraph(c, first + '\n' + last, M + 18, 517, WIDTH - 156, fitted, bold=True, leading=28)
    paragraph(c, 'Référence candidat · ' + str(trainee.get('id') or ''), M + 18, 441,
              WIDTH - 156, 7.5, MUTED)
    candidate_portrait(c, photo_path, W - M - 112, 421, 102, 123)

    for x, label in [(M, 'JOUR DE L’EXAMEN'), (M + 265, 'PÉRIODE DE FORMATION')]:
        paragraph(c, label, x, 387, 225, 8, TEAL, bold=True)
    paragraph(c, frdate(config['date']), M, 371, 240, 21, bold=True)
    hours = config['time'] or 'Horaire à renseigner'
    if config['end_time']:
        hours += ' - ' + config['end_time']
    paragraph(c, hours, M, 339, 240, 11, MUTED)
    paragraph(c, f"Du {frdate(training.get('date_start'))}\nau {frdate(training.get('date_end'))}",
              M + 265, 367, WIDTH - 265, 12, leading=20)
    c.setFillColor(LIGHT)
    c.roundRect(M, 239, WIDTH, 78, 8, fill=1, stroke=0)
    paragraph(c, 'LIEU DE L’EXAMEN', M + 16, 305, WIDTH - 32, 8, TEAL, bold=True)
    y = paragraph(c, config['location'], M + 16, 288, WIDTH - 32, 11, bold=True)
    paragraph(c, config['address'], M + 16, y - 3, WIDTH - 32, 9, MUTED, leading=12)
    paragraph(c, 'Dans ce dossier', M, 218, size=12, bold=True)
    contents = ['PV individuel', 'Pièce d’identité', 'SST ou secourisme', 'Certificat médical',
                'Attestation d’indépendance', 'Attestation de capacité']
    for index, label in enumerate(contents):
        x = M + (265 if index >= 3 else 0)
        top = 192 - (index % 3) * 23
        c.setFillColor(TEAL)
        c.circle(x + 7, top - 6, 7, fill=1, stroke=0)
        paragraph(c, str(index + 1), x, top, 14, 7.5, colors.white, bold=True, alignment=1)
        paragraph(c, label, x + 22, top, 225, 8.5, MUTED)
    complete = all(d['available'] and not d['review'] for d in docs)
    status = 'Pièces réunies et attestations signées' if complete else 'Dossier à compléter ou à vérifier'
    paragraph(c, status, M, 106, size=9, color=TEAL, bold=True)
    c.setStrokeColor(colors.HexColor('#dce4ea'))
    c.line(M, 66, W - M, 66)
    paragraph(c, config['contact_email'] + ' · ' + config['contact_phone'], M, 50, size=8, color=MUTED)
    return finish(c, stream)


def attestation(training, trainee, config, candidate, kind, assets, root):
    c, stream = new_pdf('Attestation - ' + name(trainee))
    independence = kind == 'independence'
    c.setFillColor(NAVY)
    c.rect(0, H - 5, W, 5, fill=1, stroke=0)
    logo = os.path.join(root, 'static', 'logo-integrale.png')
    if os.path.isfile(logo):
        c.drawImage(logo, M, H - 36 * mm, 22 * mm, 22 * mm, preserveAspectRatio=True, mask='auto')
    paragraph(c, 'INTÉGRALE ACADEMY', M + 30 * mm, H - 18 * mm, WIDTH - 30 * mm, 12, bold=True)
    paragraph(c, 'Intégrale Sécurité Formations\n54 chemin du Carreou · 83480 Puget-sur-Argens',
              M + 30 * mm, H - 25 * mm, WIDTH - 30 * mm, 8.5, MUTED)
    c.setStrokeColor(colors.HexColor('#dce4ea'))
    c.line(M, H - 44 * mm, W - M, H - 44 * mm)
    paragraph(c, 'Attestation', M, H - 59 * mm, size=28, bold=True, alignment=1)
    c.setFillColor(LIGHT)
    c.roundRect(M, H - 110 * mm, WIDTH, 52, 7, fill=1, stroke=0)
    paragraph(c, name(trainee), M + 12, H - 94 * mm, WIDTH - 24, 16, bold=True, alignment=1)
    paragraph(c, f"{config['level']} · Examen du {frdate(config['date'])}", M + 12, H - 102 * mm,
              WIDTH - 24, 9, MUTED, alignment=1)
    y = H - 124 * mm
    intro = 'Je soussigné, Clément VAILLANT, Directeur général d’Intégrale Academy, représentant l’organisme Intégrale Sécurité Formations,'
    if independence:
        body = f"atteste que le candidat {name(trainee)}, présenté à l’examen {config['level']} du {frdate(config['date'])}, n’exerce pas dans la même entreprise ou structure que les examinateurs ou les membres du jury de cet examen."
    else:
        body = f"atteste qu’à la suite de l’évaluation réalisée par le centre de formation, le candidat {name(trainee)}, présenté à l’examen {config['level']} du {frdate(config['date'])}, a la capacité de rendre compte sur la main courante des anomalies constatées lors d’une ronde et d’alerter les secours."
    y = paragraph(c, intro, M, y, size=11, leading=19) - 16
    y = paragraph(c, body, M, y, size=11, leading=19) - 32
    issued_date = dt.datetime.now(ZoneInfo('Europe/Paris')).date().isoformat()
    y = min(y, 302)
    y = paragraph(c, 'Fait à Puget-sur-Argens, le ' + frdate(issued_date), M, y, size=10, alignment=1) - 22
    y = paragraph(c, 'Clément VAILLANT', M, y, size=11, bold=True, alignment=1)
    y = paragraph(c, 'Directeur général Intégrale Academy', M, y - 3, size=9, color=MUTED, alignment=1) - 12
    for key, x, width, height in [('signature', W / 2 - 67 * mm, 45 * mm, 27 * mm),
                                 ('stamp', W / 2 + 3 * mm, 64 * mm, 27 * mm)]:
        c.drawImage(ImageReader(io.BytesIO(assets[key])), x, y - height, width, height, preserveAspectRatio=True, anchor='c', mask='auto')
    official_identity(c, config)
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


def dossier(training, trainee, config, candidate, docs, root, photo_path=''):
    from document_conversion import convert_upload, ConversionError
    assets = signature_assets(root)
    writer = PdfWriter()
    writer.append(io.BytesIO(cover(training, trainee, config, candidate, docs, root, photo_path)))
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
        if i == 2:  # The individual PV already carries the same approval footer.
            continue
        footer = approval_footer(config, pagination=f'{i:02d} / {len(writer.pages):02d}')
        page.merge_page(PdfReader(io.BytesIO(footer)).pages[0])
    writer.add_metadata({'/Title': 'Dossier examen SSIAP - ' + name(trainee), '/Author': 'Intégrale Academy'})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def attendance(training, trainees, config, root):
    """Keep candidates and jury together, with readable overflow for large groups."""
    widths = [26, WIDTH - 244, 109, 109]
    rows = []
    for group, people in [('Candidats', trainees), ('Jury', config['jury'])]:
        for index, person in enumerate(people, 1):
            title = Paragraph(escape(name(person)), ParagraphStyle(
                'attendance-name', fontName=BOLD, fontSize=9.5, leading=12, textColor=NAVY))
            _, title_height = title.wrap(widths[1] - 14, H)
            detail, detail_height = None, 0
            if group == 'Jury':
                role = 'Président du jury' if person['role'] == 'president' else 'Membre du jury'
                label = role + (' · ' + person['company'] if person.get('company') else '')
                detail = Paragraph(escape(label), ParagraphStyle(
                    'attendance-role', fontName=FONT, fontSize=7.5, leading=10, textColor=MUTED))
                _, detail_height = detail.wrap(widths[1] - 14, H)
            height = max(42 if detail else 24, title_height + detail_height + (16 if detail else 12))
            rows.append((group, index, title, title_height, detail, detail_height, height))

    c, stream = new_pdf('Feuille de présence - ' + config['level'])

    def page_header():
        c.setFillColor(TEAL)
        c.rect(0, H - 5, W, 5, fill=1, stroke=0)
        logo = os.path.join(root, 'static', 'logo-integrale.png')
        if os.path.isfile(logo):
            c.drawImage(logo, M, H - 83, 49, 49, preserveAspectRatio=True, anchor='c', mask='auto')
        paragraph(c, 'INTÉGRALE ACADEMY · EXAMEN ' + config['level'], M + 65, H - 36,
                  WIDTH - 65, 8, TEAL, bold=True)
        paragraph(c, 'Feuille de présence', M + 65, H - 51, WIDTH - 65, 23, bold=True)
        hours = config['time'] or 'Horaire à renseigner'
        if config['end_time']:
            hours += ' - ' + config['end_time']
        y = paragraph(c, 'Examen du ' + frdate(config['date']) + ' · ' + hours,
                      M, H - 105, size=12, bold=True) - 5
        y = paragraph(c, config['location'] + ' · ' + config['address'], M, y, size=9, color=MUTED) - 14
        return paragraph(c, 'Émarger matin et après-midi. Indiquer « absent » ou « non concerné » si nécessaire.',
                         M, y, size=8, color=MUTED) - 12

    top = page_header()
    capacity = top - 110  # Keep the centre's legal footer clear.
    pages, current, used, previous = [], [], 0, None
    for row in rows:
        extra = row[-1] + (30 + (12 if current else 0) if row[0] != previous else 0)
        if current and used + extra > capacity:
            pages.append(current)
            current, used, previous = [], 0, None
            extra = row[-1] + 30
        current.append(row)
        used += extra
        previous = row[0]
    if current or not pages:
        pages.append(current)

    for page_number, page_rows in enumerate(pages, 1):
        y = top if page_number == 1 else page_header()
        group_count = len({row[0] for row in page_rows})
        available = y - 110 - 30 * group_count - 12 * max(0, group_count - 1)
        # Expand the signature boxes when the group fits comfortably on one page.
        extra_height = min(10, max(0, available - sum(row[-1] for row in page_rows)) / max(1, len(page_rows)))
        previous = None
        for group, index, title, title_height, detail, detail_height, minimum in page_rows:
            if group != previous:
                if previous:
                    y -= 12
                labels = ['N°', 'Candidats · Nom et prénom' if group == 'Candidats' else 'Membres du jury',
                          'Matin\nSignature', 'Après-midi\nSignature']
                c.setFillColor(NAVY)
                c.roundRect(M, y - 30, WIDTH, 30, 4, fill=1, stroke=0)
                x = M
                for label, width in zip(labels, widths):
                    paragraph(c, label, x + 5, y - (8 if x == M + 26 else 4), width - 10, 8,
                              colors.white, bold=True, alignment=0 if x == M + 26 else 1, leading=10)
                    x += width
                y -= 30
                previous = group
            row_height = minimum + extra_height
            if index % 2 == 1:
                c.setFillColor(LIGHT)
                c.rect(M, y - row_height, WIDTH, row_height, fill=1, stroke=0)
            c.setStrokeColor(colors.HexColor('#dce4ea'))
            c.setLineWidth(.5)
            c.rect(M, y - row_height, WIDTH, row_height, fill=0, stroke=1)
            x = M
            for width in widths[:-1]:
                x += width
                c.line(x, y, x, y - row_height)
            paragraph(c, str(index), M + 3, y - (row_height - 12) / 2,
                      widths[0] - 6, 8, MUTED, alignment=1)
            text_height = title_height + detail_height + (3 if detail else 0)
            bottom = y - (row_height - text_height) / 2 - title_height
            title.drawOn(c, M + 33, bottom)
            if detail:
                detail.drawOn(c, M + 33, bottom - 3 - detail_height)
            y -= row_height
        if not page_rows:
            paragraph(c, 'Aucun candidat ou membre du jury renseigné pour cet examen.', M, y - 15, size=10, color=MUTED)
        official_identity(c, config)
        c.setFont(FONT, 7)
        c.setFillColor(MUTED)
        c.drawString(M, 14, config['approval'])
        c.drawRightString(W - M, 14, f'{page_number:02d} / {len(pages):02d}')
        c.showPage()
    return finish(c, stream)


def collective(training, trainees, config, root):
    """Repeat the unchanged 14-slot model when needed, without extending its table."""
    check_model(config)
    raw, font_bytes = official_template(root, 'collective')
    font = fitz.Font(fontbuffer=font_bytes)
    assets = signature_assets(root)
    output = fitz.open()
    for start in range(0, max(1, len(trainees)), 14):
        with fitz.open(stream=raw, filetype='pdf') as document:
            page = document[0]
            form_contact(page, font, config, 'collective', font_bytes)
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
            form_centre_signature(page, font, assets, 'collective')
            form_footer(page, config)
            # The jury's results and signature areas remain blank.
            output.insert_pdf(document)
    output.set_metadata({'title': 'Procès-verbal collectif SSIAP 1', 'author': 'Intégrale Academy'})
    result = output.tobytes(garbage=3, deflate=True)
    output.close()
    return result
