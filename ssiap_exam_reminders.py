"""Durable jury reminders at J-7, driven by the existing protected Render cron."""
import datetime as dt
import secrets
import time
from zoneinfo import ZoneInfo

from ssiap_exam import (MAIL_RE, active_candidates, build_mail, candidate_settings,
                        digest, frdate, settings, state, supported)

PARIS = ZoneInfo('Europe/Paris')


def local_clock(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    return now.astimezone(PARIS)


def due_date(config):
    try:
        return dt.date.fromisoformat(config['date']) - dt.timedelta(days=7)
    except (ValueError, KeyError, TypeError):
        return None


def eligible(services, training):
    return (supported(training) and not training.get('archived') and not training.get('cancelled')
            and training.get('partner_id') in (None, '', services.INTEGRALE_PARTNER_ID)
            and bool(state(training).get('config')))


def attempt_for(training, member, config):
    """An earlier manual reminder may coexist; one sent from J-7 replaces the scheduled one."""
    due = due_date(config)
    if not due:
        return None
    for entry in reversed(state(training).get('mail_history', [])):
        if entry.get('kind') != 'reminder' or entry.get('to', '').casefold() != member.get('email', '').casefold():
            continue
        if entry.get('exam_date') != config['date']:
            # Legacy messages already carry the exact exam date in their subject.
            if entry.get('exam_date') or frdate(config['date']) not in entry.get('subject', ''):
                continue
        if entry.get('source') == 'automatic_j7':
            return entry
        try:
            sent = local_clock(dt.datetime.fromisoformat(entry['at'].replace('Z', '+00:00'))).date()
        except (KeyError, ValueError, TypeError):
            sent = due
        if sent >= due:
            return entry
    return None


def retry_allowed(attempt, now):
    if not attempt:
        return True
    if not (attempt.get('source') == 'automatic_j7' and attempt.get('status') == 'failed'
            and attempt.get('not_sent') is True and attempt.get('attempt_number', 1) < 3):
        return False
    try:
        previous = dt.datetime.fromisoformat(attempt['at'].replace('Z', '+00:00'))
        return (now - local_clock(previous)).total_seconds() >= 1800
    except (KeyError, ValueError, TypeError):
        return False


def preparation_error(services, training, config, member):
    if not eligible(services, training):
        return 'Session inactive ou organisation non enregistrée'
    if not all(config.get(k) for k in ('date', 'time', 'location', 'address')) or not due_date(config):
        return 'Date, heure et lieu à compléter'
    if not MAIL_RE.fullmatch(config.get('contact_email', '')):
        return 'E-mail du centre à compléter'
    if not MAIL_RE.fullmatch(member.get('email', '')):
        return 'E-mail du jury à compléter'
    if not any(candidate_settings(training, t)['included'] for t in active_candidates(services, training)):
        return 'Aucun candidat présenté'
    return ''


def schedule(services, training, *, now=None):
    local = local_clock(now)
    config = settings(training)
    due = due_date(config)
    members = {}
    for member in config['jury']:
        attempt = attempt_for(training, member, config)
        error = preparation_error(services, training, config, member)
        if attempt:
            status = attempt.get('status', 'unknown')
            label = {'sent': 'Envoyé', 'sending': 'En cours / à vérifier', 'unknown': 'Envoi à vérifier',
                     'failed': 'Échec de l’envoi'}.get(status, 'À vérifier')
            if retry_allowed(attempt, local) and due == local.date():
                label += ' · nouvelle tentative prévue'
        elif error:
            status, label = 'incomplete', error
        elif due < local.date():
            status, label = 'missed', 'Échéance passée · envoi manuel disponible'
        else:
            status, label = 'scheduled', 'Programmé le ' + frdate(due.isoformat()) + ' à partir de 09:00'
        members[member['id']] = {'status': status, 'label': label,
                                'at': (attempt or {}).get('finished_at') or (attempt or {}).get('at', '')}
    return {'enabled': True, 'date': due.isoformat() if due else '', 'time': '09:00',
            'timezone': 'Europe/Paris', 'members': members}


def run(services, *, now=None, dry_run=False, limit=10):
    local = local_clock(now)
    report = {'ok': True, 'status': 'checked', 'checked': 0, 'due': 0,
              'processed': 0, 'emails_accepted': 0, 'failed': 0}
    if not 9 <= local.hour < 20:
        report['status'] = 'outside_sending_hours'
        return report
    data = services.load_data(run_background_tasks=False)
    candidates, seen = [], set()
    for training in data.get('sessions', []):
        if not eligible(services, training):
            continue
        config = settings(training)
        if due_date(config) != local.date():
            continue  # No bulk catch-up of old exam reminders on deployment.
        for member in config['jury']:
            report['checked'] += 1
            identity = (training['id'], member.get('email', '').casefold())
            if (identity not in seen and not preparation_error(services, training, config, member)
                    and retry_allowed(attempt_for(training, member, config), local)):
                seen.add(identity)
                candidates.append((training['id'], member['id'], config['date'], member['email']))
    report['due'] = len(candidates)
    if dry_run:
        report['status'] = 'dry_run'
        return report
    started = time.monotonic()
    for session_id, jury_id, exam_date, recipient in candidates:
        if report['processed'] >= limit or time.monotonic() - started > 90:
            break

        def reserve(current):
            training = services.find_session(current, session_id)
            if not training or not eligible(services, training):
                return {}
            config = settings(training)
            member = next((m for m in config['jury'] if m['id'] == jury_id), None)
            if (not member or config['date'] != exam_date or member['email'] != recipient
                    or due_date(config) != local.date() or preparation_error(services, training, config, member)):
                return {}
            previous = attempt_for(training, member, config)
            if not retry_allowed(previous, local):
                return {}
            count = sum(candidate_settings(training, t)['included'] for t in active_candidates(services, training))
            content = build_mail(training, config, member, 'reminder', count,
                                 services.APP_BASE_URL.rstrip('/') + '/static/logo-integrale.png', today=local.date())
            delivery_key = 'ssiap-j7-' + digest([session_id, exam_date, recipient.casefold()])
            entry = {'id': secrets.token_hex(20), 'to': content['to'], 'subject': content['subject'],
                     'kind': 'reminder', 'source': 'automatic_j7', 'status': 'sending',
                     'at': local.isoformat(), 'jury_id': jury_id, 'exam_date': exam_date,
                     'scheduled_for': due_date(config).isoformat(), 'idempotency_key': delivery_key,
                     'attempt_number': (previous or {}).get('attempt_number', 0) + 1}
            training.setdefault('ssiap_exam', {}).setdefault('mail_history', []).append(entry)
            return {'content': content, 'entry_id': entry['id'], 'delivery_key': delivery_key}

        reserved = services._atomic_update_data(reserve)
        if not reserved:
            continue
        report['processed'] += 1
        content = reserved['content']
        try:
            result = services.brevo_send_email(content['to'], content['subject'], content['html'],
                text_content=content['text'], reply_to=content['reply_to'],
                metadata={'purpose': 'ssiap_exam_reminder', 'source': 'automatic_j7', 'session_id': session_id,
                          'idempotency_key': reserved['delivery_key']})
            result = result if isinstance(result, dict) else {'ok': result is True}
        except Exception:
            services.app.logger.exception('SSIAP automatic jury reminder delivery unconfirmed')
            result = {'ok': False}
        accepted = result.get('ok') is True
        # Retry only an explicit refusal, never an uncertain provider timeout or crash.
        code = result.get('status_code')
        not_sent = result.get('not_sent') is True or (isinstance(code, int) and 400 <= code < 500 and code != 408)

        def finish(current):
            training = services.find_session(current, session_id)
            for entry in state(training or {}).get('mail_history', []):
                if entry.get('id') == reserved['entry_id']:
                    entry.update(status='sent' if accepted else ('failed' if not_sent else 'unknown'),
                                 finished_at=local_clock(now).isoformat(), not_sent=not_sent,
                                 message_id=str(result.get('message_id') or ''))
            return {}

        services._atomic_update_data(finish)
        report['emails_accepted' if accepted else 'failed'] += 1
    report['ok'] = report['failed'] == 0
    return report
