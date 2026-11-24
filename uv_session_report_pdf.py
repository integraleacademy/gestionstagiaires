"""A print layout for one UV, with a measured page budget shared by roster and questions."""
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, Paragraph, Table, TableStyle
from werkzeug.exceptions import Forbidden, NotFound

from identity_photos import load_photo
from uv_questionnaire_pdf import fonts

INK = HexColor('#193246')
TEAL = HexColor('#12665F')
GOLD = HexColor('#DCAC6C')
RUST = HexColor('#984C32')
MUTED = HexColor('#506575')
RULE = HexColor('#D5E0E2')
PALE = HexColor('#F2F7F6')
MINT = HexColor('#DAEEE9')
WIDTH, HEIGHT = A4
MARGIN = 35
BODY = WIDTH - 2 * MARGIN
BOTTOM = 47
QUESTION_HEADER = 25
# Shares of the table width are fixed so repeated column headers always align.
STAT_WIDTHS = (33, 38, 41, 52)
TEXT_WIDTH = BODY - sum(STAT_WIDTHS) - 57


def _text(c, x, y, value, font, size, color=INK, align='left'):
    c.setFillColor(color)
    c.setFont(font, size)
    draw = {'left': c.drawString, 'center': c.drawCentredString, 'right': c.drawRightString}[align]
    draw(x, y, str(value))


def _paragraph(value, font, size, leading, color, width):
    style = ParagraphStyle('text', fontName=font, fontSize=size, leading=leading, textColor=color)
    p = Paragraph(escape(str(value)), style)
    p.wrap(width, 10000)
    return p


def _in_box(c, value, font, size, color, x, top, width, height):
    p = _paragraph(value, font, size, size * 1.22, color, width)
    scale = min(1, height / p.height) if p.height else 1
    c.saveState()
    c.translate(x, top)
    c.scale(scale, scale)
    p.drawOn(c, 0, -p.height)
    c.restoreState()


def _avatar(c, host, person, x, y, diameter, bold):
    radius = diameter / 2
    if person.photo_token:
        try:
            picture, _ = load_photo(host, person.photo_token, max_size=112)
        except (ValueError, Forbidden, NotFound):
            picture = None
        if picture is not None:
            with picture, ImageOps.fit(picture, (88, 88), Image.Resampling.LANCZOS, centering=(.5, .38)) as square:
                c.saveState()
                crop = c.beginPath()
                crop.circle(x + radius, y + radius, radius)
                c.clipPath(crop, stroke=0)
                c.drawImage(ImageReader(square), x, y, width=diameter, height=diameter)
                c.restoreState()
            return
    c.setFillColor(MINT)
    c.circle(x + radius, y + radius, radius, fill=1, stroke=0)
    _text(c, x + radius, y + radius - 3, person.initials, bold, 9, TEAL, 'center')


class ParticipantCard(Flowable):
    def __init__(self, person, host, face):
        super().__init__()
        self.person, self.host, self.face = person, host, face

    def wrap(self, width, height):
        self.width = width
        self.name = _paragraph(self.person.name, self.face[1], 9.5, 12, INK, width - 101)
        self.height = max(39, self.name.height + 24)
        return self.width, self.height

    def draw(self):
        c, p = self.canv, self.person
        regular, bold = self.face
        c.setFillColor(white)
        c.setStrokeColor(RULE)
        c.setLineWidth(.6)
        c.roundRect(.4, .4, self.width - .8, self.height - .8, 6, stroke=1, fill=1)
        _avatar(c, self.host, p, 8, (self.height - 25) / 2, 25, bold)
        self.name.drawOn(c, 41, self.height - 8 - self.name.height)
        _text(c, 41, 7, 'Copie remise' if p.score is not None else p.status, regular, 7.5, MUTED)
        if p.score is not None:
            c.setFillColor(PALE)
            c.roundRect(self.width - 49, (self.height - 18) / 2, 42, 18, 6, fill=1, stroke=0)
            _text(c, self.width - 28, self.height / 2 - 3.5, f'{p.score}/20', bold, 9, TEAL, 'center')


def _roster_rows(report, host, face):
    rows = []
    half = (BODY - 10) / 2
    style = TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)])
    for i in range(0, len(report.participants), 2):
        cards = [ParticipantCard(p, host, face) for p in report.participants[i:i+2]]
        row = Table([[cards[0], '', cards[1] if len(cards) == 2 else '']], colWidths=[half, 10, half], style=style)
        rows.append((row, row.wrap(BODY, HEIGHT)[1]))
    return rows


def _centers():
    start = BODY - sum(STAT_WIDTHS)
    for width in STAT_WIDTHS:
        yield start + width / 2
        start += width


class QuestionRow(Flowable):
    def __init__(self, q, all_versions, face):
        super().__init__()
        self.q, self.face = q, face
        self.prompt = _paragraph(q.prompt, face[1], 9, 12, INK, TEXT_WIDTH)
        self.answer = _paragraph(q.answer, face[0], 8.6, 11.5, TEAL, TEXT_WIDTH - 8)
        self.edition = ', '.join(f'{v[6:8]}.{v[4:6]}.{v[2:4]}' for v in sorted(q.versions)) if q.versions != all_versions else ''
        self.width = BODY
        self.height = max(45, self.prompt.height + self.answer.height + 22)

    def draw(self):
        c, q = self.canv, self.q
        regular, bold = self.face
        center = self.height / 2
        _text(c, 1, self.height - 17, f'Q{q.number:02}', bold, 9, INK)
        if self.edition:
            _in_box(c, self.edition, regular, 6.8, MUTED, 1, self.height - 22, 42, self.height - 23)
        self.prompt.drawOn(c, 48, self.height - 8 - self.prompt.height)
        self.answer.drawOn(c, 56, 8)
        c.setStrokeColor(TEAL)
        c.setLineWidth(1.6)
        c.line(49, 9, 49, 7 + self.answer.height)
        good, wrong, blank, rate = _centers()
        for x, value, color in ((good, q.correct, TEAL), (wrong, q.wrong, RUST), (blank, q.blank, MUTED)):
            _text(c, x, center - 3, value, bold, 10, color, 'center')
        frac = q.correct / q.total
        _text(c, rate, center + 1, f'{frac:.0%}'.replace('%', ' %'), bold, 8.8, INK, 'center')
        c.setFillColor(RULE)
        c.roundRect(rate - 15, center - 7, 30, 3, 1.5, stroke=0, fill=1)
        if frac:
            c.setFillColor(TEAL)
            c.rect(rate - 15, center - 7, 30 * frac, 3, stroke=0, fill=1)
        c.setStrokeColor(RULE)
        c.setLineWidth(.5)
        c.line(0, 0, BODY, 0)


def _table_header(c, face):
    c.setFillColor(PALE)
    c.roundRect(0, -QUESTION_HEADER + 2, BODY, QUESTION_HEADER - 2, 4, fill=1, stroke=0)
    for x, label in zip(_centers(), ('Justes', 'Fausses', 'Sans rép.', 'Réussite')):
        _text(c, x, -15, label, face[1], 7.1, INK, 'center')
    _text(c, 6, -15, 'N°', face[1], 7.5, MUTED)
    _text(c, 48, -15, 'Question et bonne réponse', face[1], 8, INK)


def _partition(rows, rooms):
    """Split near equal density, keeping whole questions and at least one row per page."""
    groups, index = [], 0
    remaining = sum(height for _, height in rows)
    for page, room in enumerate(rooms[:-1]):
        target = remaining * room / sum(rooms[page:])
        end = index + 1
        used = rows[index][1]
        while end < len(rows) - (len(rooms) - page - 1):
            after = used + rows[end][1]
            if abs(target - used) <= abs(target - after):
                break
            used = after
            end += 1
        groups.append(rows[index:end])
        index = end
        remaining -= used
    groups.append(rows[index:])
    return groups


def _page_plan(roster, questions, first_room, next_room, question_room):
    # Prefer full-size print, then the fewest pages. Large classes or mixed editions
    # share the five-page budget without dropping a participant, wording or statistic.
    best_quality, best = 0, None
    for count in range(2, 6):
        for roster_count in range(1, count):
            q_count = count - roster_count
            if roster_count > len(roster) or q_count > len(questions):
                continue
            rooms = [first_room] + [next_room] * (roster_count - 1)
            rosters = _partition(roster, rooms)
            details = _partition(questions, [question_room - QUESTION_HEADER] * q_count)
            groups = rosters + details
            budgets = rooms + [question_room] * q_count
            sizes = [sum(h for _, h in group) + (QUESTION_HEADER if i >= roster_count else 0)
                     for i, group in enumerate(groups)]
            quality = min([1] + [budget / size for budget, size in zip(budgets, sizes)])
            if quality > best_quality:
                best_quality, best = quality, (rosters, details)
            if quality == 1:
                return best
    return best


def _draw_rows(c, group, top, face, questions=False):
    header = QUESTION_HEADER if questions else 0
    height = header + sum(h for _, h in group)
    scale = min(1, (top - BOTTOM) / height)
    c.saveState()
    c.translate(MARGIN + (BODY - BODY * scale) / 2, top)
    c.scale(scale, scale)
    if questions:
        _table_header(c, face)
    y = -header
    for row, size in group:
        y -= size
        row.drawOn(c, 0, y)
    c.restoreState()


def _frame(c, face, brand, label, stamp, page, count):
    regular, bold = face
    c.setFillColor(TEAL)
    c.roundRect(MARGIN, HEIGHT - 43, 4, 18, 2, stroke=0, fill=1)
    _in_box(c, brand, bold, 12, INK, MARGIN + 12, HEIGHT - 25, BODY - 185, 19)
    _text(c, WIDTH - MARGIN, HEIGHT - 39, label, bold, 9, MUTED, 'right')
    c.setStrokeColor(RULE)
    c.setLineWidth(.7)
    c.line(MARGIN, HEIGHT - 55, WIDTH - MARGIN, HEIGHT - 55)
    c.line(MARGIN, 36, WIDTH - MARGIN, 36)
    _text(c, MARGIN, 22, f'Évaluation formative   ·   Édité le {stamp}', regular, 7.6, MUTED)
    _text(c, WIDTH - MARGIN, 22, f'{page} / {count}', bold, 8.4, INK, 'right')


def _overview(c, face, report, unit, training):
    regular, bold = face
    top = HEIGHT - 70
    c.setFillColor(INK)
    c.roundRect(MARGIN, top - 105, BODY, 105, 9, fill=1, stroke=0)
    _text(c, MARGIN + 17, top - 21, 'RAPPORT FORMATEUR', bold, 8.4, GOLD)
    _in_box(c, unit['title'], bold, 20, white, MARGIN + 17, top - 29, BODY - 34, 48)
    _in_box(c, training.get('name') or training.get('nom') or training['id'], regular, 9.4,
            HexColor('#DDE9ED'), MARGIN + 17, top - 83, BODY - 34, 16)
    top -= 116
    scores = report.scores
    mean = f'{sum(scores)/len(scores):.1f}'.replace('.', ',')
    cards = [('Participation', f'{len(scores)} / {len(report.participants)}', 'copies remises'),
             ('Moyenne du groupe', f'{mean}/20', 'sur les copies remises'),
             ('Notes extrêmes', f'{min(scores)} – {max(scores)}', 'minimum et maximum sur 20')]
    width = (BODY - 16) / 3
    for i, (label, value, hint) in enumerate(cards):
        x = MARGIN + i * (width + 8)
        c.setFillColor(PALE)
        c.roundRect(x, top - 68, width, 68, 6, stroke=0, fill=1)
        _text(c, x + 11, top - 16, label, bold, 8.2, MUTED)
        _text(c, x + 11, top - 43, value, bold, 21, TEAL if i == 1 else INK)
        _text(c, x + 11, top - 58, hint, regular, 7.7, MUTED)
    top -= 92
    _text(c, MARGIN, top, 'Répartition des notes', bold, 10)
    width = BODY / 4
    for i, (low, high) in enumerate(((0, 4), (5, 9), (10, 14), (15, 20))):
        x = MARGIN + i * width
        n = sum(low <= score <= high for score in scores)
        _text(c, x, top - 18, f'{low} à {high}/20', regular, 8, MUTED)
        _text(c, x + width - 12, top - 18, n, bold, 9, INK, 'right')
        c.setFillColor(RULE)
        c.roundRect(x, top - 27, width - 12, 3, 1.5, fill=1, stroke=0)
        if n:
            c.setFillColor(TEAL)
            c.rect(x, top - 27, (width - 12) * n / len(scores), 3, fill=1, stroke=0)


def _revision_focus(c, report, face, top):
    missed = (q for q in report.questions if q.correct < q.total)
    lowest = sorted(missed, key=lambda q: (q.correct / q.total, -(q.total - q.correct), q.number))[:2]
    lines = [(q, _paragraph(q.prompt, face[0], 9, 12, INK, BODY - 152)) for q in lowest]
    height = 30 + sum(p.height + 9 for _, p in lines)
    if not lines or top - height < BOTTOM:
        return
    c.setFillColor(PALE)
    c.roundRect(MARGIN, top - height, BODY, height, 6, stroke=0, fill=1)
    _text(c, MARGIN + 12, top - 17, 'Questions les moins réussies', face[1], 10)
    y = top - 25
    for q, prompt in lines:
        _text(c, MARGIN + 12, y - 9, f'Q{q.number:02}', face[1], 8.5, TEAL)
        prompt.drawOn(c, MARGIN + 45, y - prompt.height)
        _text(c, WIDTH - MARGIN - 12, y - 9, f'{100 * q.correct / q.total:.0f} % de réussite', face[1], 8, MUTED, 'right')
        y -= prompt.height + 9


def build(report, training, course, unit, *, brand, host):
    output = BytesIO()
    c = Canvas(output, pagesize=A4, pageCompression=1)
    face = fonts()
    label = f'{course.upper()}   /   UV {unit["number"]:02}'
    c.setTitle(f'Rapport formateur · {label} · {unit["title"]}')
    c.setAuthor(brand)
    stamp = datetime.now(ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y à %Hh%M')
    first_top, next_top = HEIGHT - 348, HEIGHT - 122
    q_top = HEIGHT - (154 if len(report.versions) > 1 else 140)
    roster = _roster_rows(report, host, face)
    questions = [QuestionRow(q, report.versions, face) for q in report.questions]
    groups, details = _page_plan(roster, [(q, q.height) for q in questions],
                                 first_top - BOTTOM, next_top - BOTTOM, q_top - BOTTOM)
    total = len(groups) + len(details)
    for i, group in enumerate(groups, 1):
        _frame(c, face, brand, label, stamp, i, total)
        top = first_top if i == 1 else next_top
        if i == 1:
            _overview(c, face, report, unit, training)
        _text(c, MARGIN, top + 13, 'Notes des stagiaires', face[1], 15)
        _draw_rows(c, group, top, face)
        if len(groups) == 1:
            _revision_focus(c, report, face, top - sum(h for _, h in group) - 12)
        c.showPage()
    for i, group in enumerate(details, len(groups) + 1):
        _frame(c, face, brand, label, stamp, i, total)
        _text(c, MARGIN, HEIGHT - 88, 'Analyse des questions', face[1], 21)
        _text(c, MARGIN, HEIGHT - 106, 'La bonne réponse figure sous chaque question. « Sans rép. » indique un délai écoulé.', face[0], 9, MUTED)
        _text(c, MARGIN, HEIGHT - 120, 'Le taux de réussite porte sur les copies remises ayant reçu cette question.', face[0], 9, MUTED)
        if len(report.versions) > 1:
            _text(c, MARGIN, HEIGHT - 134, 'La date sous le numéro distingue les variantes du questionnaire.', face[0], 9, MUTED)
        _draw_rows(c, group, q_top, face, questions=True)
        c.showPage()
    c.save()
    output.seek(0)
    return output
