"""Personal, read-only jury agendas shared through opaque links in jury mail."""
import datetime as dt
import hashlib
import hmac
import re
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from flask import make_response

import ssiap_exam as exam
from exam_context import all_exams
from ssiap_exam_mail import DAYS, MONTHS


def _email(value):
    return str(value or '').strip().casefold()


def access_token(services, email):
    # Stable links contain neither the recipient's email nor an enumerable ID.
    key = services.app.secret_key
    if isinstance(key, str):
        key = key.encode('utf-8')
    return hmac.new(key, ('jury-planning:v1:' + _email(email)).encode('utf-8'), hashlib.sha256).hexdigest()


def _assignments(services, data):
    for training in all_exams(s for s in data.get('sessions', []) if isinstance(s, dict)):
        if (not exam.jury_supported(training)
                or training.get('partner_id') not in (None, '', services.INTEGRALE_PARTNER_ID)):
            continue
        if not exam.state(training).get('config'):
            continue
        config = exam.settings(training)
        for member in config.get('jury', []):
            if exam.MAIL_RE.fullmatch(_email(member.get('email'))):
                yield training, config, member


def agenda(services, data, email, *, today=None):
    today = today or dt.datetime.now(ZoneInfo('Europe/Paris')).date()
    upcoming, undated, seen = [], [], set()
    name = ''
    for training, config, member in _assignments(services, data):
        if _email(member['email']) != _email(email):
            continue
        name = name or ' '.join(str(member.get(k) or '').strip() for k in ('first_name', 'last_name')).strip()
        if training.get('archived') or training.get('cancelled'):
            continue
        try:
            date = dt.date.fromisoformat(config.get('date') or '')
        except (TypeError, ValueError):
            date = None
        if date and date < today:
            continue
        identity = str(training.get('id') or '')
        exam_identity = (identity, exam.state_key(training))
        if exam_identity in seen:
            continue
        seen.add(exam_identity)
        contact_email = config.get('contact_email') or ''
        phone = str(config.get('contact_phone') or '')
        entry = {key: str(config.get(key) or '') for key in (
            'level', 'time', 'arrival_time', 'end_time', 'location', 'address', 'instructions',
            'contact_name', 'contact_email', 'contact_phone')}
        entry.update(
            session_id=identity, exam_family=exam.state_key(training), date=date.isoformat() if date else '',
            date_label=(f'{DAYS[date.weekday()]} {date.day} {MONTHS[date.month - 1]} {date.year}' if date else 'Date à confirmer'),
            day=str(date.day) if date else '—',
            month=(MONTHS[date.month - 1] + ' ' + str(date.year)) if date else 'À confirmer',
            role='Président du jury' if member.get('role') == 'president' else 'Membre du jury',
            contact_url=('mailto:' + quote(contact_email, safe='@.') if exam.MAIL_RE.fullmatch(contact_email) else ''),
            phone_url='tel:' + re.sub(r'[^+0-9]', '', phone) if phone else '',
            directions_url=('https://www.google.com/maps/search/?' + urlencode({'api': '1', 'query': entry['address']})
                            if entry['address'] else ''),
        )
        (upcoming if date else undated).append(entry)
    upcoming.sort(key=lambda item: (item['date'], item['time'], item['level'], item['session_id']))
    undated.sort(key=lambda item: (item['level'], item['session_id']))
    return {'name': name, 'upcoming': upcoming, 'undated': undated}


def mail_context(services, data, training, member, *, today=None):
    planning = agenda(services, data, member['email'], today=today)
    current_id = str(training.get('id') or '')
    return {
        'url': services.APP_BASE_URL.rstrip('/') + '/jury/planning/' + access_token(services, member['email']),
        'dates': [item for item in planning['upcoming'] if (item['session_id'], item['exam_family']) != (current_id, exam.state_key(training))],
        'undated': [item for item in planning['undated'] if (item['session_id'], item['exam_family']) != (current_id, exam.state_key(training))],
    }


def register(app, services):
    @app.get('/jury/planning/<token>')
    def public_jury_planning(token):
        email = ''
        data = {}
        if re.fullmatch(r'[a-f0-9]{64}', token):
            data = services.load_data(run_background_tasks=False)
            checked = set()
            for _, _, member in _assignments(services, data):
                candidate = _email(member['email'])
                if candidate in checked:
                    continue
                checked.add(candidate)
                if hmac.compare_digest(token, access_token(services, candidate)):
                    email = candidate
                    break
        planning = agenda(services, data, email) if email else None
        # A standalone public page must not inject the administration's context.
        response = make_response(app.jinja_env.get_template('jury_planning.html').render(planning=planning),
                                 200 if planning is not None else 404)
        response.headers.update({
            'Cache-Control': 'private, no-store, max-age=0', 'Pragma': 'no-cache',
            'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex, nofollow, noarchive',
            'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        })
        return response
