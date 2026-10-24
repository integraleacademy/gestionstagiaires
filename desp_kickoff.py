"""DESP Paris/Puget kickoff decks, released on the first training day.

The supplied 24-slide decks retain their programme, artwork and site details.
Only session dates and the first-day e-learning wording are composed at runtime.
"""
from datetime import date, datetime
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from flask import abort, redirect, request, send_file, url_for
import aps_kickoff as shared

ASSETS = Path(__file__).with_name('desp_kickoff_assets')
VERSION = '20261024-1'
DATE_FIELDS = ('date_start', 'date_end', 'dirigeant_remote_start', 'dirigeant_remote_end',
               'dirigeant_in_person_start', 'dirigeant_in_person_end', 'exam_date')
CITIES = {'paris': 'Paris', 'puget': 'Puget-sur-Argens'}


def today():
    return datetime.now(ZoneInfo('Europe/Paris')).date()


def location(services, training):
    """Use the same Paris/Puget routing as DESP conventions and convocations."""
    descriptor = f"{services._session_get(training, 'training_type', '')} {services._session_get(training, 'name', '')}"
    if re.search(r'\b(MAC|VAE|RECYCLAGE)\b', descriptor, re.I):
        return None
    if (training.get('partner_id') or services.INTEGRALE_PARTNER_ID) != services.INTEGRALE_PARTNER_ID:
        return None
    slug = services._automation_document_config(training).get('slug')
    return {'desp_paris': 'paris', 'desp_puget': 'puget'}.get(slug)


def supported(services, training):
    return location(services, training) is not None


def schedule(services, training):
    """Require the recorded remote, onsite and exam dates; never invent them."""
    dates = {key: shared._date(services._session_get(training, key, '')) for key in DATE_FIELDS}
    dates['date_start'] = dates['dirigeant_remote_start'] or dates['date_start']
    dates['date_end'] = dates['dirigeant_in_person_end'] or dates['date_end']
    if not all(dates.values()):
        raise ValueError('Complétez les dates du e-learning, du présentiel et de l’examen dans « Modifier la session ».')
    start, remote_end, onsite, end, exam = (dates[key] for key in (
        'dirigeant_remote_start', 'dirigeant_remote_end', 'dirigeant_in_person_start',
        'dirigeant_in_person_end', 'exam_date'))
    if not start <= remote_end < onsite <= end <= exam:
        raise ValueError('Vérifiez l’ordre des dates : e-learning, présentiel, puis examen.')
    if (exam-start).days > 366:
        raise ValueError('Vérifiez les dates de la session DESP : la période dépasse un an.')
    return dates


def view(services, training, trainee=None):
    city = location(services, training)
    if not city:
        return None
    try:
        dates = schedule(services, training)
    except ValueError as error:
        return dict(available=False, ready=False, error=str(error), city=CITIES[city])
    cancelled = bool(trainee and services._trainee_registration_is_cancelled(trainee))
    return dict(available=today() >= dates['date_start'] and not cancelled,
                ready=True, error='', city=CITIES[city])


def _block(page, spec, text):
    """Wrap inside the original text box, reducing font size only when needed."""
    import pymupdf as fitz
    fontpath = shared.ASSETS / ('Rubik-Bold.ttf' if spec['bold'] else 'Rubik-Regular.ttf')
    font = fitz.Font(fontfile=str(fontpath))
    x, original_y = spec['origin']
    width = spec['rect'][2]-x-3
    size = spec['size']
    while True:
        lines = []
        for paragraph in text.split('\n'):
            line = ''
            for word in paragraph.split():
                candidate = (line+' '+word).strip()
                if line and font.text_length(candidate, fontsize=size) > width:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            lines.append(line)
        y = original_y-(spec['size']-size)*font.ascender
        fits = (y+(len(lines)-1)*size*1.2-font.descender*size <= spec['rect'][3]+.5
                and all(font.text_length(line, fontsize=size) <= width for line in lines))
        if fits:
            break
        size -= .25
        if size < 10:
            raise ValueError('Les dates ne tiennent pas dans le diaporama DESP. Vérifiez la session.')
    shared._text(page, '\n'.join(lines), x, y, size, spec['color'], spec['bold'])


@lru_cache(maxsize=8)
def _build_pdf(key):
    import pymupdf as fitz
    payload = json.loads(key)
    dates = {k: date.fromisoformat(v) for k, v in payload['dates'].items()}
    start, end, exam = (dates[k] for k in ('date_start', 'date_end', 'exam_date'))
    remote_end, onsite = dates['dirigeant_remote_end'], dates['dirigeant_in_person_start']
    city = CITIES[payload['location']]
    french, period = shared.french, shared.period
    years = str(start.year) if start.year == exam.year else f'{start.year} – {exam.year}'
    # Cross-year dates carry their year in the calendar to remove any ambiguity.
    year = start.year != exam.year
    values = {
        (1, 'text-1-3'): period(start, end),
        (1, 'text-1-4'): 'Examen le '+french(exam),
        (4, 'text-4-4'): 'L’examen final a lieu le '+french(exam)+', après la fin de la formation.',
        (5, 'calendar-year'): 'Dates '+years,
        (5, 'calendar-remote'): period(start, remote_end, year=year),
        (5, 'calendar-deadline'): french(remote_end, year=year),
        (5, 'calendar-onsite'): period(onsite, end, year=year),
        (5, 'calendar-exam'): french(exam, year=year),
        (6, 'text-6-2'): ('Du '+french(start, year=year)).upper(),
        (6, 'text-6-3'): ('Au '+french(exam)).upper(),
        (6, 'text-6-5'): 'À distance, réservez le temps nécessaire aux 174 h de e-learning.\n'
            f'À {city}, votre présence est obligatoire à tous les créneaux prévus.\n'
            f'Le {french(exam, year=year)}, réservez votre disponibilité pour l’examen.',
        (7, 'text-7-1'): ('Du '+period(start, remote_end)).upper(),
        (8, 'text-8-4'): 'Au plus tard\nle '+french(remote_end),
        (14, 'text-12-1'): ('Du '+period(onsite, end)).upper(),
        (17, 'text-15-0'): 'L’examen du '+french(exam),
        (24, 'text-22-3'): 'Votre accès au e-learning est ouvert. Vérifiez votre connexion à la plateforme.',
        (24, 'text-22-5'): f'Temps de travail à distance, déplacements à {city} et disponibilité '
            f'pour l’examen du {french(exam)}.',
        (24, 'text-22-8'): 'Démarrage le '+french(start),
    }
    with fitz.open(ASSETS/(payload['location']+'.pdf')) as doc:
        for spec in json.loads((ASSETS/(payload['location']+'.json')).read_text()):
            _block(doc[spec['page']-1], spec, values[(spec['page'], spec['name'])])
        doc.set_metadata({'title': f'Réunion de lancement DESP {city} — '+french(start),
                          'author': 'Intégrale Academy', 'subject': 'Session du '+period(start, end)})
        doc.subset_fonts()
        return doc.tobytes(garbage=4, deflate=True)


def pdf(services, training):
    city = location(services, training)
    if not city:
        raise ValueError('Cette session ne correspond pas à une formation initiale DESP Paris ou Puget.')
    dates = schedule(services, training)
    payload = dict(version=VERSION, location=city, dates={k: v.isoformat() for k, v in dates.items()})
    # APS and DESP share one lock because PyMuPDF is not thread-safe.
    with shared._PDF_LOCK:
        return _build_pdf(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def register(app, services):
    app.jinja_env.globals['desp_kickoff_supported'] = lambda training: supported(services, training)

    def response(training):
        try:
            content = pdf(services, training)
        except ValueError as error:
            abort(409, description=str(error))
        start = schedule(services, training)['date_start'].isoformat()
        city = location(services, training)
        result = send_file(BytesIO(content), mimetype='application/pdf',
                           as_attachment=request.args.get('download') == '1',
                           download_name=f'Diaporama_DESP_{city}_{start}.pdf', max_age=0)
        result.headers['Cache-Control'] = 'private, no-store'
        result.headers['X-Content-Type-Options'] = 'nosniff'
        return result

    @app.get('/espace/<token>/diaporama-desp.pdf')
    def public_desp_kickoff_pdf(token):
        if not services._public_is_authed(token):
            return redirect(url_for('public_trainee_login', token=token))
        training, trainee = services.find_session_and_trainee_by_token(
            services.load_data(run_background_tasks=False), token)
        if not training or not trainee or not supported(services, training):
            abort(404)
        if not view(services, training, trainee)['available']:
            abort(403, description='Le diaporama est accessible à partir du premier jour de formation.')
        return response(training)

    @app.get('/admin/sessions/<session_id>/diaporama-desp.pdf')
    @services.admin_login_required
    def admin_desp_kickoff_pdf(session_id):
        training = services.find_session(services.load_data(run_background_tasks=False), session_id)
        if not training or not supported(services, training):
            abort(404)
        return response(training)
