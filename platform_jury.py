"""Receive confirmed jury members from the session planning application."""
import hashlib
import hmac
import os
import re
import time
import unicodedata

import requests
from flask import jsonify, request

import afc_schedule
import desp_kickoff
import ssiap_exam as exam
from exam_context import all_exams


NAMES_URL = 'https://plateformegestion.onrender.com/api/integrations/gestionstagiaires/jury-identite'


def integration_key():
    dedicated = os.environ.get('JURY_SYNC_TOKEN', '').strip()
    if dedicated:
        return dedicated
    shared = os.environ.get('AFC_ATTENDANCE_SYNC_TOKEN', '').strip()
    return hmac.new(shared.encode(), b'plateformegestion:jury:v1', hashlib.sha256).hexdigest() if shared else ''


def identity(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if c.isalnum())


class MatchError(ValueError):
    pass


def locate(services, data, selector, linked_source=''):
    if not selector['level'] and not selector['afc'] and not selector['target_id']:
        raise MatchError('Associez cette session à un examen dans la fiche jury.')
    matches = []
    for training in all_exams(data.get('sessions', [])):
        if training.get('partner_id') not in (None, '', services.INTEGRALE_PARTNER_ID):
            continue
        if not exam.jury_supported(training) or afc_schedule.enabled(training) != selector['afc']:
            continue
        config = exam.settings(training)
        if selector['level'] and config['level'] != selector['level']:
            continue
        if selector['site'] and config['level'] == 'DESP initial' and desp_kickoff.location(services, training) != selector['site']:
            continue
        # The two AFC exams share a training ID. Their exam date or level
        # must still select exactly one examination.
        if selector['target_id'] and training['id'] != selector['target_id']:
            continue
        if selector['target_id'] and linked_source in exam.state(training).get('platform_confirmations', {}):
            return training  # A name correction follows the saved link even if the exam moved.
        exam_date = config.get('date') or ('' if selector['afc'] else services._session_get(training, 'exam_date'))
        dates_match = bool(selector['exam_date'] and selector['exam_date'] == exam_date)
        if selector['afc'] and selector['exam_date'] and exam_date and not dates_match:
            continue
        period_match = all(selector[key] and selector[key] == services._session_get(training, key)
                           for key in ('date_start', 'date_end'))
        if dates_match or (selector['target_id'] and selector['level']) or (
                period_match and selector['level'] and (not exam_date or not selector['exam_date'])):
            matches.append((training, dates_match, period_match))
    if len(matches) > 1:
        precise = [row for row in matches if row[1] and row[2]]
        if precise:
            matches = precise
    if len(matches) != 1:
        raise MatchError('Plusieurs examens correspondent. Précisez la session dans la fiche jury.'
                         if matches else 'Aucun examen correspondant. Vérifiez la formation, la date et la session associée.')
    return matches[0][0]


def validated(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('session'), dict) or not isinstance(payload.get('member'), dict):
        raise ValueError('Confirmation invalide.')
    raw, person = payload['session'], payload['member']
    selector = {key: exam.clean_text(raw.get(key, ''), key, 100)
                for key in ('source_id', 'target_id', 'level', 'site')}
    for key in ('date_start', 'date_end', 'exam_date'):
        selector[key] = exam.clean_date(raw.get(key), key)
    selector['afc'] = raw.get('afc', False)
    if (not re.fullmatch(r'[\w-]{1,100}', selector['source_id'], re.ASCII)
            or type(selector['afc']) is not bool
            or selector['site'] not in ('', 'paris', 'puget')
            or selector['level'] not in ('', 'APS', 'A3P', 'DESP initial', 'SSIAP 1', 'SSIAP 2', 'SSIAP 3')):
        raise ValueError('Session ou examen invalide.')
    member = {k: exam.clean_text(person.get(k, ''), k, limit) for k, limit in (
        ('id', 100), ('first_name', 80), ('last_name', 80), ('email', 254), ('phone', 40))}
    if not re.fullmatch(r'[\w-]{1,100}', member['id'], re.ASCII) or not member['first_name'] or not member['last_name']:
        raise ValueError('Identité du membre de jury incomplète.')
    if member['email'] and not exam.MAIL_RE.fullmatch(member['email']):
        raise ValueError('Adresse e-mail du jury invalide.')
    member['last_name'] = member['last_name'].upper()
    version = person.get('name_version', 0)
    if type(version) is not int or not 0 <= version < 2**53:
        raise ValueError('Version du nom invalide.')
    if version:
        member['name_version'] = version
    return selector, member


def record(services, data, selector, person):
    person = person.copy()
    version = person.pop('name_version', 0)
    source = selector['source_id'] + '/' + person['id']
    training = locate(services, data, selector, source if version else '')
    state = training.setdefault(exam.state_key(training), {})
    config = exam.settings(training)
    members = list(config['jury'])
    links = state.get('platform_confirmations', {})
    saved_version = state.get('platform_name_versions', {}).get(source, 0)
    result = {'ok': True, 'session_id': training['id']}
    if version:
        result['name_version'] = max(version, saved_version)
    linked = source in links
    if linked:
        if version <= saved_version:
            return result
        matches = [m for m in members if m['id'] == links[source]]
        if not matches:
            raise MatchError('Ce juré a été retiré de cet examen dans Gestion stagiaires.')
    else:
        email = person['email'].casefold()
        matches = [m for m in members if email and (m.get('email') or '').strip().casefold() == email]
        if not matches:
            matches = [m for m in members if all(identity(m.get(k) or '') == identity(person[k])
                                                  for k in ('first_name', 'last_name'))
                       and (not email or not m.get('email'))]
    if len(matches) > 1:
        raise MatchError('Plusieurs membres du jury correspondent à cette identité.')
    if matches:
        member = matches[0]
        # Preserve IDs, presidential roles, mail receipts and manually entered details.
        if not linked:
            for field in ('email', 'phone'):
                if person[field] and not member.get(field):
                    member[field] = person[field]
    else:
        if len(members) >= 12:
            raise MatchError('La session compte déjà douze membres de jury.')
        stable_id = 'pg-' + hashlib.sha256(person['id'].encode()).hexdigest()[:24]
        if any(m['id'] == stable_id for m in members):
            raise MatchError('Un membre porte déjà cet identifiant avec une autre identité.')
        member = {**person, 'id': stable_id, 'company': '', 'role': 'member'}
        members.append(member)
    if version:
        member.update(first_name=person['first_name'], last_name=person['last_name'])
        state.setdefault('platform_name_versions', {})[source] = version
        state.get('platform_name_outbox', {}).pop(source, None)
    state['config'] = {**config, 'jury': members}
    state.setdefault('platform_confirmations', {})[source] = member['id']
    state['revision'] = state.get('revision', 0) + 1
    state['updated_at'] = services._now_iso()
    exam.remember_jury(data, [member], state['updated_at'], names_only=linked)
    return result


def queue_name_edits(training, state, previous, members):
    """Persist explicit admin edits together with the exam save, only for linked jurors."""
    before = {m['id']: m for m in previous}
    changed = {m['id']: m for m in members if m['id'] in before and
               any(m[k] != before[m['id']].get(k) for k in ('first_name', 'last_name'))}
    family = exam.state_key(training)
    exam_key = ('aps' if family == 'security_exam' else 'ssiap1') if afc_schedule.enabled(training) else ''
    for source, member_id in state.get('platform_confirmations', {}).items():
        if member_id not in changed:
            continue
        sid, jid = source.split('/', 1)
        member = changed[member_id]
        versions = state.setdefault('platform_name_versions', {})
        version = max(time.time_ns() // 1000, versions.get(source, 0) + 1)
        event = {'session_id': sid, 'member_id': jid, 'exam': exam_key, 'name_version': version,
                 'first_name': member['first_name'], 'last_name': member['last_name']}
        versions[source] = version
        state.setdefault('platform_name_outbox', {})[source] = event
    return [(training['id'], family, source, event) for source, event in state.get('platform_name_outbox', {}).items()]


def send_name_edits(services, pending):
    if not pending:
        return True
    key = integration_key()
    if not key:
        return False
    acknowledged = set()
    for sid, family, source, event in pending:
        try:
            payload = {k: v for k, v in event.items() if k != 'last_attempt'}
            reply = requests.post(NAMES_URL, json=payload, headers={'Authorization': 'Bearer ' + key},
                                  timeout=(2, 4), allow_redirects=False)
            reply.raise_for_status()
            receipt = reply.json()
            if (isinstance(receipt, dict) and receipt.get('ok') is True and
                    type(receipt.get('name_version')) is int and receipt['name_version'] >= event['name_version']):
                acknowledged.add((sid, family, source, event['name_version']))
        except (requests.RequestException, ValueError):
            continue  # The saved outbox is retried after a temporary outage.
    def finish(data):
        for sid, family, source, event in pending:
            training = services.find_session(data, sid)
            if training and training.get('partner_id') in (None, '', services.INTEGRALE_PARTNER_ID):
                box = training.get(family, {}).get('platform_name_outbox', {})
                version = event['name_version']
                if box.get(source, {}).get('name_version') == version:
                    if (sid, family, source, version) in acknowledged:
                        del box[source]
                    else:
                        box[source]['last_attempt'] = time.time()
    services._atomic_update_data(finish)
    return len(acknowledged) == len(pending)


def retry_name_edits(services, data, limit):
    pending = [(training['id'], exam.state_key(training), source, event)
               for training in all_exams(data.get('sessions', []))
               if training.get('partner_id') in (None, '', services.INTEGRALE_PARTNER_ID)
               for source, event in exam.state(training).get('platform_name_outbox', {}).items()]
    pending.sort(key=lambda item: item[3].get('last_attempt', 0))
    send_name_edits(services, pending[:limit])


def register(app, services):
    @app.route('/api/integrations/plateformegestion/jury-confirmations', methods=['HEAD', 'POST'])
    def platform_jury_confirmation():
        key = integration_key()
        if not key or not hmac.compare_digest(request.headers.get('Authorization', '').encode(), ('Bearer ' + key).encode()):
            return jsonify(ok=False, error='Accès à la synchronisation refusé.'), 403
        if request.method == 'HEAD':
            return '', 204
        try:
            selector, member = validated(request.get_json(silent=True))
            result = services._atomic_update_data(lambda data: record(services, data, selector, member))
        except MatchError as exc:
            return jsonify(ok=False, error=str(exc)), 409
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        return jsonify(result)
