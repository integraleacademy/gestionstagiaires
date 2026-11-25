"""Two-page, printable individual UV questionnaires and submitted copies."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import KeepInFrame, Paragraph, Spacer

NAVY = colors.HexColor('#182f49')
BLUE = colors.HexColor('#285d83')
GOLD = colors.HexColor('#c5a15a')
MUTED = colors.HexColor('#526479')
LINE = colors.HexColor('#dce5ee')


def fonts():
    for root in (Path('/usr/share/fonts/truetype/dejavu'), Path('/usr/share/fonts/dejavu')):
        regular, bold = root/'DejaVuSans.ttf', root/'DejaVuSans-Bold.ttf'
        if regular.exists() and bold.exists():
            if 'UVSans' not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont('UVSans', str(regular)))
                pdfmetrics.registerFont(TTFont('UVSansBold', str(bold)))
            return 'UVSans', 'UVSansBold'
    return 'Helvetica', 'Helvetica-Bold'


def _draw_block(canvas, items, x, top, width, height):
    # Account for actual wrapped text, including longer archived editions.
    block = KeepInFrame(width, height, items, mode='shrink', mergeSpace=False)
    _, used = block.wrapOn(canvas, width, height)
    block.drawOn(canvas, x, top - used)
    return top - used


def build(training, trainee, course, row, result=None, correction=False, *, title, notice):
    return build_copies(training, course, [(trainee, row, result)], correction=correction, title=title, notice=notice)


def build_copies(training, course, copies, *, title, notice, correction=True):
    # One canvas shares the logo and fonts across all candidates and UVs.
    out = BytesIO()
    canvas = Canvas(out, pagesize=A4)
    canvas.setTitle(title)
    canvas.setAuthor('Intégrale Academy')
    for index, (trainee, row, result) in enumerate(copies):
        key = f'copie-{index}'
        canvas.bookmarkPage(key)
        name = ' '.join(str(trainee.get(k) or '') for k in ('last_name', 'first_name')).strip()
        canvas.addOutlineEntry(f"{name} · UV {row['number']:02}", key)
        _draw_unit(canvas, training, trainee, course, row, result, correction, notice)
    canvas.save()
    out.seek(0)
    return out


def _draw_unit(canvas, training, trainee, course, row, result, correction, notice):
    regular, bold = fonts()
    width, height = A4
    margin, gutter = 12 * mm, 8 * mm
    full_width = width - 2 * margin
    column_width = (full_width - gutter) / 2
    body = ParagraphStyle('choice', fontName=regular, fontSize=9, leading=11, textColor=NAVY)
    prompt = ParagraphStyle('question', parent=body, fontName=bold, fontSize=9.4, leading=12, spaceAfter=3)
    note = ParagraphStyle('explanation', parent=body, fontSize=8.3, leading=10.5, textColor=MUTED)
    topic = ParagraphStyle('topic', parent=prompt, fontSize=12, leading=15, textColor=BLUE)
    mode = 'Réponses et correction' if result else 'Corrigé formateur' if correction else 'Questionnaire vierge'
    corrected = correction or bool(result)
    name = ' '.join(str(trainee.get(k) or '') for k in ('first_name', 'last_name')).strip()
    identity = f"Stagiaire : {name}   ·   Dossier : {trainee.get('id', '')}"
    unit = f"{course.upper()} · UV {row['number']:02}"
    questions = row['questions']

    def question_items(index, question):
        items = [Paragraph(f"{index:02}. {escape(question['prompt'])}", prompt)]
        selected = result.get('answers', {}).get(question['id']) if result else None
        for letter, option in enumerate(question['options']):
            marks = []
            if corrected and option['id'] == question['answer']:
                marks.append('Bonne réponse')
            if selected == option['id']:
                marks.append('Votre réponse')
            suffix = f' <font name="{bold}" color="#285d83">· {" · ".join(marks)}</font>' if marks else ''
            box = '' if corrected else '[   ]  '
            items.append(Paragraph(f"{box}{chr(65 + letter)}. {escape(option['text'])}{suffix}", body))
        if corrected:
            prefix = 'Sans réponse (temps écoulé). ' if result and not selected else ''
            items.extend((Spacer(1, 2), Paragraph(prefix + escape(question['explanation']), note)))
        return items

    midpoint = (len(questions) + 1) // 2
    pages = [questions[:midpoint], questions[midpoint:]] if len(questions) > 10 else [questions]
    first = 1
    for page_no, page_questions in enumerate(pages, 1):
        canvas.setFillColor(NAVY)
        canvas.rect(0, height - 8 * mm, width, 8 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont(bold, 8.5)
        canvas.drawString(margin, height - 5.5 * mm, 'INTÉGRALE ACADEMY')
        canvas.drawRightString(width - margin, height - 5.5 * mm, unit)
        canvas.drawImage(str(Path(__file__).with_name('static') / 'logo-integrale.png'),
                         margin, height - 26 * mm, 16 * mm, 16 * mm, preserveAspectRatio=True, mask='auto')
        canvas.setFillColor(NAVY)
        canvas.setFont(bold, 17)
        canvas.drawString(margin + 20 * mm, height - 18 * mm, "Questionnaire de fin d'UV")
        canvas.setFillColor(MUTED)
        canvas.setFont(regular, 9)
        canvas.drawString(margin + 20 * mm, height - 24 * mm, 'Evaluation formative')
        canvas.drawRightString(width - margin, height - 24 * mm, mode)
        meta = [Paragraph(escape(row['title']), topic),
                Paragraph(escape(identity) + '   ·   Session : ' + escape(str(training.get('name') or '')), body)]
        if result:
            meta.append(Paragraph(f"Score : {result['score']}/20   ·   Terminé le {escape(str(result['submitted_at']))}", body))
        pages_top = _draw_block(canvas, meta, margin, height - 29 * mm, full_width, 27 * mm)
        canvas.setStrokeColor(GOLD)
        canvas.line(margin, pages_top - 4, width - margin, pages_top - 4)

        top, bottom = pages_top - 12, 24 * mm
        half = (len(page_questions) + 1) // 2
        for column, group in enumerate((page_questions[:half], page_questions[half:])):
            items = []
            for question in group:
                if items:
                    items.append(Spacer(1, 10))
                items.extend(question_items(first, question))
                first += 1
            if items:
                _draw_block(canvas, items, margin + column * (column_width + gutter),
                            top, column_width, top - bottom)
        canvas.setStrokeColor(LINE)
        canvas.line(width / 2, top, width / 2, bottom)
        canvas.line(margin, bottom - 4, width - margin, bottom - 4)
        if not result:
            canvas.setFont(regular, 8.5)
            canvas.drawString(margin, 18 * mm, 'Date : __________________   Formateur : __________________   Signature du stagiaire : __________________')
        canvas.setFillColor(MUTED)
        canvas.setFont(regular, 8)
        canvas.drawString(margin, 13 * mm, f'{len(questions)} questions · 1 seule réponse · 1 point par bonne réponse')
        canvas.drawRightString(width - margin, 13 * mm, f'{unit} · Page {page_no}/{len(pages)}')
        _draw_block(canvas, [Paragraph(escape(notice), note)], margin, 10 * mm, full_width, 7 * mm)
        canvas.showPage()
