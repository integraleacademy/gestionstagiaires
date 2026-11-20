"""Receive confirmed jury members from the session planning application."""
import hashlib
import hmac
import os
import re
import unicodedata

from flask import jsonify, request

import afc_schedule
import desp_kickoff
import ssiap_exam as exam
from exam_context import all_exams


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


def locate(services, data, selector):
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
    return selector, member


def record(services, data, selector, person):
    training = locate(services, data, selector)
    state = training.setdefault(exam.state_key(training), {})
    config = exam.settings(training)
    members = list(config['jury'])
    source = selector['source_id'] + '/' + person['id']
    links = state.get('platform_confirmations', {})
    if source in links:
        return {'ok': True, 'session_id': training['id']}
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
    state['config'] = {**config, 'jury': members}
    state.setdefault('platform_confirmations', {})[source] = member['id']
    state['revision'] = state.get('revision', 0) + 1
    state['updated_at'] = services._now_iso()
    exam.remember_jury(data, [member], state['updated_at'])
    return {'ok': True, 'session_id': training['id']}


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
