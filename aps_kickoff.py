"""Session-specific APS kickoff PDF, released on the first training day.

The approved 41-slide deck is kept as a vector PDF. Only session dates,
the calendar and the training-centre details are composed dynamically.
No trainee data, public file token, cron job or persistent-data write is needed.
"""
import calendar
from datetime import date, datetime
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path
import re
from threading import RLock
from zoneinfo import ZoneInfo

from flask import abort, redirect, request, send_file, url_for
import afc_schedule

ASSETS = Path(__file__).with_name('aps_kickoff_assets')
VERSION = '20261024-1'
MONTHS = ('', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
          'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre')
DAYS = ('lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche')
DATE_FIELDS = ('date_start', 'date_end', 'aps_remote_start', 'aps_remote_end',
               'aps_in_person_start', 'aps_in_person_end', 'exam_date')
_PDF_LOCK = RLock()
BLUE, GREEN, GOLD = '#2251D9', '#087B68', '#E1B447'
NAVY, MUTED, PALE = '#14223D', '#556581', '#EDF2FA'


def today():
    return datetime.now(ZoneInfo('Europe/Paris')).date()


def supported(services, training):
    kind = str(services._session_get(training, 'training_type', '')).strip().upper()
    return bool(re.match(r'^APS\b', kind)
                and not re.search(r'\b(MAC|VAE|RECYCLAGE)\b', kind)
                and not afc_schedule.enabled(training)
                and (training.get('partner_id') or services.INTEGRALE_PARTNER_ID)
                == services.INTEGRALE_PARTNER_ID)


def _date(raw):
    try:
        return date.fromisoformat(str(raw or '').strip())
    except ValueError:
        return None


def schedule(services, training):
    """Reuse saved session dates; do not infer missing exam/phase dates."""
    values = {key: _date(services._session_get(training, key, '')) for key in DATE_FIELDS}
    # An explicitly recorded remote start is the start of this hybrid course.
    values['date_start'] = values['aps_remote_start'] or values['date_start']
    values['date_end'] = values['aps_in_person_end'] or values['date_end']
    if not all(values.values()):
        raise ValueError('Complétez les dates du e-learning, du présentiel et de l’examen dans « Modifier la session ».')
    start, remote_end = values['aps_remote_start'], values['aps_remote_end']
    onsite, end, exam = (values[k] for k in ('aps_in_person_start', 'aps_in_person_end', 'exam_date'))
    if not start <= remote_end < onsite <= end <= exam:
        raise ValueError('Vérifiez l’ordre des dates : e-learning, présentiel, puis examen.')
    if (exam - start).days > 366:
        raise ValueError('Vérifiez les dates de la session APS : la période dépasse un an.')
    return values


def view(services, training, trainee=None):
    if not supported(services, training):
        return None
    try:
        dates = schedule(services, training)
    except ValueError as error:
        return dict(available=False, ready=False, error=str(error), start_label='')
    cancelled = bool(trainee and services._trainee_registration_is_cancelled(trainee))
    return dict(available=today() >= dates['date_start'] and not cancelled,
                ready=True, error='', start_label=dates['date_start'].strftime('%d/%m/%Y'))


def french(day, year=True, weekday=False):
    value = f'{day.day} {MONTHS[day.month]}' + (f' {day.year}' if year else '')
    return f'{DAYS[day.weekday()]} {value}' if weekday else value


def period(start, end, year=True):
    if start == end:
        return french(start, year)
    if (start.year, start.month) == (end.year, end.month):
        return f'{start.day} au {french(end, year)}'
    return f'{french(start, year and start.year != end.year)} au {french(end, year)}'


def months_between(start, end):
    year, month = start.year, start.month
    result = []
    while (year, month) <= (end.year, end.month):
        result.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return result


def calendar_phase(day, dates):
    if day == dates['exam_date']:
        return GOLD
    if dates['aps_remote_start'] <= day <= dates['aps_remote_end']:
        return BLUE
    if dates['aps_in_person_start'] <= day <= dates['aps_in_person_end']:
        return GREEN
    return PALE


def _rgb(value):
    if isinstance(value, int):
        return ((value >> 16 & 255)/255, (value >> 8 & 255)/255, (value & 255)/255)
    return tuple(int(value.lstrip('#')[i:i+2], 16)/255 for i in (0, 2, 4))


def _text(page, text, x, y, size, color=NAVY, bold=False, width=None, align='left'):
    import pymupdf as fitz
    fontpath = ASSETS / ('Rubik-Bold.ttf' if bold else 'Rubik-Regular.ttf')
    font = fitz.Font(fontfile=str(fontpath))
    if width:
        size = min(size, width/max(font.text_length(line, fontsize=1) for line in str(text).split('\n')))
    for index, line in enumerate(str(text).split('\n')):
        offset = (width-font.text_length(line, fontsize=size))/2 if width and align == 'center' else 0
        page.insert_text((x+offset, y+index*size*1.2), line, fontsize=size,
                         fontname='aps_bold' if bold else 'aps_regular', fontfile=str(fontpath), color=_rgb(color))


def _block(page, spec, text):
    x0, y0, x1, y1 = spec['rect']
    _text(page, text, spec['origin'][0], spec['origin'][1], spec['size'],
          spec['color'], spec['bold'], width=x1-max(x0, spec['origin'][0])-3)


def _calendar(page, dates, city):
    import pymupdf as fitz
    start, end = dates['date_start'], dates['exam_date']
    months = months_between(start, end)
    _text(page, 'Du '+period(start, end), 45, 119, 17, MUTED, width=870)
    if len(months) <= 3:
        gap = 24
        width = (870-gap*(len(months)-1))/len(months)
        for index, (year, month) in enumerate(months):
            left, top = 45+index*(width+gap), 167
            _text(page, f'{MONTHS[month].upper()} {year}', left, 154, 21, bold=True, width=width)
            cw, rh = width/7, 30
            for column, label in enumerate(('Lun.', 'Mar.', 'Mer.', 'Jeu.', 'Ven.', 'Sam.', 'Dim.')):
                x = left+column*cw
                page.draw_rect(fitz.Rect(x, top, x+cw-2, top+24), color=None, fill=_rgb(NAVY))
                _text(page, label, x, top+17, min(13, cw*.24), '#FFFFFF', width=cw-2, align='center')
            weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
            for row in range(6):
                for column in range(7):
                    day = weeks[row][column] if row < len(weeks) else 0
                    if not day:
                        continue
                    x, y = left+column*cw, top+27+row*rh
                    value = date(year, month, day)
                    color = calendar_phase(value, dates)
                    page.draw_rect(fitz.Rect(x, y, x+cw-2, y+rh-2), color=None, fill=_rgb(color))
                    _text(page, str(day), x, y+21, min(17, cw*.40),
                          '#FFFFFF' if color in (BLUE, GREEN) else NAVY, color == GOLD,
                          width=cw-2, align='center')
    else:
        # Long or interrupted sessions remain readable with a proportional timeline.
        total = max(1, (end-start).days+1)
        for index, (label, first, last, color) in enumerate((
            ('E-learning à distance', dates['aps_remote_start'], dates['aps_remote_end'], BLUE),
            ('Présentiel au centre de formation', dates['aps_in_person_start'], dates['aps_in_person_end'], GREEN),
            ('Examen', end, end, GOLD))):
            y = 167+index*67
            _text(page, label+' · '+period(first, last), 45, y, 18, color, True, 870)
            page.draw_rect(fitz.Rect(45, y+9, 915, y+32), color=None, fill=_rgb(PALE))
            x = 45+870*(first-start).days/total
            right = min(915, x+max(6, 870*((last-first).days+1)/total))
            page.draw_rect(fitz.Rect(x, y+9, right, y+32), color=None, fill=_rgb(color))
    legends = [
        (45, 278, 'E-learning à distance', dates['aps_remote_start'], dates['aps_remote_end'], '62 h de parcours en ligne', BLUE),
        (345, 297, 'Présentiel au centre de formation', dates['aps_in_person_start'], dates['aps_in_person_end'], city, GREEN),
        (660, 255, 'Examen', end, end, 'Selon votre convocation', '#A57411')]
    for x, width, label, first, last, detail, color in legends:
        _text(page, label, x, 407, 17, color, True, width)
        _text(page, period(first, last), x, 432, 16, NAVY, True, width)
        _text(page, detail, x, 455, 15, MUTED, width=width)


@lru_cache(maxsize=8)
def _build_pdf(key):
    import pymupdf as fitz
    payload = json.loads(key)
    dates = {k: date.fromisoformat(v) for k, v in payload['dates'].items()}
    start, end, exam = (dates[k] for k in ('date_start', 'date_end', 'exam_date'))
    remote_end, onsite = dates['aps_remote_end'], dates['aps_in_person_start']
    month_label = f'{MONTHS[start.month]} {start.year}'
    values = {
        (1, 'cover-subtitle'): f'Réunion de lancement\nSession de {month_label}',
        (1, 'cover-dates'): f'{period(start, end)}\nExamen le {french(exam)}',
        (9, 'remote-table-period'): 'Du '+period(start, remote_end),
        (27, 'section'): ('Du '+period(start, remote_end)).upper(),
        (30, 'title'): 'Le point avant le '+french(remote_end),
        (30, 'takeaway'): 'Rendez-vous au centre de formation à partir du '+french(onsite, weekday=True)+'.',
        (31, 'title'): 'Votre accueil à '+payload['city'],
        (31, 'item-title-0'): 'Du '+period(onsite, end),
        (31, 'item-body-1'): payload['address'],
        (35, 'title'): 'L’examen du '+french(exam),
        (35, 'big-value'): french(exam, year=False),
        (35, 'big-label'): f'{exam.year}, selon votre convocation',
        (41, 'item-body-2'): f'Présentiel dès le {french(onsite)}. Examen le {french(exam)}.',
    }
    with fitz.open(ASSETS / 'template.pdf') as document:
        for spec in json.loads((ASSETS / 'layout.json').read_text()):
            text = ('INTÉGRALE ACADEMY   /   APS '+month_label.upper() if spec['name'] == 'footer'
                    else values[(spec['page'], spec['name'])])
            _block(document[spec['page']-1], spec, text)
        _calendar(document[7], dates, payload['city'])
        document.set_metadata({'title': 'Réunion de lancement APS — '+month_label,
                               'author': 'Intégrale Academy', 'subject': 'Session du '+period(start, end)})
        document.subset_fonts()
        return document.tobytes(garbage=4, deflate=True)


def pdf(services, training):
    dates = schedule(services, training)
    payload = dict(version=VERSION, dates={k: v.isoformat() for k, v in dates.items()},
                   city=services.APS_CONVOCATION_CENTER_CITY,
                   address=f'{services.APS_CONVOCATION_CENTER_ADDRESS}\n'
                           f'{services.APS_CONVOCATION_CENTER_ZIP} {services.APS_CONVOCATION_CENTER_CITY}')
    # PyMuPDF is not thread-safe; cache only completed immutable byte strings.
    with _PDF_LOCK:
        return _build_pdf(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def register(app, services):
    # Expose the same eligibility predicate to both administration templates.
    app.jinja_env.globals['aps_kickoff_supported'] = lambda training: supported(services, training)

    def response(training):
        try:
            content = pdf(services, training)
        except ValueError as error:
            abort(409, description=str(error))
        start = schedule(services, training)['date_start'].isoformat()
        result = send_file(BytesIO(content), mimetype='application/pdf',
                           as_attachment=request.args.get('download') == '1',
                           download_name=f'Diaporama_APS_{start}.pdf', max_age=0)
        result.headers['Cache-Control'] = 'private, no-store'
        result.headers['X-Content-Type-Options'] = 'nosniff'
        return result

    @app.get('/espace/<token>/diaporama-aps.pdf')
    def public_aps_kickoff_pdf(token):
        if not services._public_is_authed(token):
            return redirect(url_for('public_trainee_login', token=token))
        training, trainee = services.find_session_and_trainee_by_token(
            services.load_data(run_background_tasks=False), token)
        if not training or not trainee or not supported(services, training):
            abort(404)
        state = view(services, training, trainee)
        if not state['available']:
            abort(403, description='Le diaporama est accessible à partir du premier jour de formation.')
        return response(training)

    @app.get('/admin/sessions/<session_id>/diaporama-aps.pdf')
    @services.admin_login_required
    def admin_aps_kickoff_pdf(session_id):
        training = services.find_session(services.load_data(run_background_tasks=False), session_id)
        if not training or not supported(services, training):
            abort(404)
        return response(training)
