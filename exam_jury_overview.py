"""Read-only jury names and mail receipts for the session cards."""
import datetime as dt
from zoneinfo import ZoneInfo

import afc_schedule
from exam_context import all_exams
import ssiap_exam as exam
from ssiap_exam_reminders import schedule


def _sent_at(value):
    try:
        instant = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=dt.timezone.utc)
        return instant.astimezone(ZoneInfo('Europe/Paris')).strftime('%d/%m/%Y à %H:%M')
    except (ValueError, TypeError):
        return ''


def _badge(kind, receipt, reminder):
    label = 'Invitation' if kind == 'invitation' else 'Rappel'
    status = receipt['status']
    if status == 'sent':
        sent_at = _sent_at(receipt['at'])
        detail = label + (' envoyée' if kind == 'invitation' else ' envoyé')
        if sent_at:
            detail += ' le ' + sent_at + ' (heure de Paris)'
        return {'state': 'sent', 'icon': '✅', 'label': label, 'detail': detail}
    if status in ('failed', 'sending', 'unknown'):
        text = {'failed': ' : échec', 'sending': ' en cours', 'unknown': ' à vérifier'}[status]
        detail = label + text
        previous = _sent_at(receipt['last_sent_at'])
        if previous:
            detail += ' · précédent envoi réussi le ' + previous + ' (heure de Paris)'
        return {'state': status, 'icon': '⏳' if status == 'sending' else '⚠️',
                'label': label + text, 'detail': detail}
    if kind == 'reminder':
        status = reminder.get('status')
        if status == 'scheduled':
            return {'state': 'scheduled', 'icon': '⏳', 'label': 'Rappel J−7',
                    'detail': reminder['label'] + ' (heure de Paris)'}
        if status == 'incomplete':
            return {'state': 'incomplete', 'icon': '⚠️', 'label': 'Rappel à préparer',
                    'detail': reminder['label']}
    return {'state': 'not_sent', 'icon': '○', 'label': label + ' à envoyer',
            'detail': (reminder['label'] if kind == 'reminder' and reminder.get('status') == 'missed'
                       else label + (' non envoyée' if kind == 'invitation' else ' non envoyé'))}


def summary(services, training):
    if (not exam.jury_supported(training)
            or training.get('partner_id') not in (None, '', services.INTEGRALE_PARTNER_ID)):
        return None
    members = []
    exams = []
    afc = afc_schedule.enabled(training)
    for examination in all_exams([training]):
        roster = _members(services, examination)
        if afc:
            settings = exam.settings(examination)
            label = settings['level']
            for member in roster:
                member['exam_label'] = label
            exams.append({'label': label, 'date': settings.get('date'), 'members': roster})
        members.extend(roster)
    return {'members': members, 'exams': exams}


def _members(services, training):
    config = exam.settings(training)
    if not config['jury']:
        return []
    reminders = schedule(services, training)['members']
    confirmed = set(exam.state(training).get('platform_confirmations', {}).values())
    members = []
    for member in config['jury']:
        receipts = exam.mail_status(training, member)
        members.append({
            'name': ' '.join(str(member.get(key) or '').strip() for key in ('first_name', 'last_name')).strip(),
            'president': member.get('role') == 'president',
            'confirmed': member['id'] in confirmed,
            'email_missing': not exam.MAIL_RE.fullmatch(member.get('email') or ''),
            'badges': [_badge(kind, receipts[kind], reminders.get(member['id'], {}))
                       for kind in ('invitation', 'reminder')],
        })
    return members
