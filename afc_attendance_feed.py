"""Read and correct the enrolled trainees used by the France Travail attendance sheets."""
import hmac
import os
import re
import uuid

from flask import abort, jsonify, request
from werkzeug.exceptions import HTTPException

import afc_enrolments
import afc_hours
import afc_schedule
from afc_import import normalize_ft_id

EDITABLE = {'france_travail_id', 'entryDate', 'ranHours'}


def select_training(services, data, source_id, start, end):
    sessions = [s for s in data.get('sessions', []) if afc_enrolments.supported(services, s)]
    if source_id:
        matches = [s for s in sessions if s.get('id') == source_id]
    else:
        if not (start and end):
            abort(400, description='Une session ou ses deux dates sont nécessaires.')
        matches = [s for s in sessions if services._session_get(s, 'date_start') == start
                   and services._session_get(s, 'date_end') == end]
    if not matches:
        abort(404, description='Session AFC introuvable.')
    if len(matches) != 1:
        abort(409, description='Plusieurs sessions AFC correspondent aux dates.')
    return matches[0]


def enrolled_records(services, training):
    if isinstance(training.get('trainees'), list):
        return [(t, t) for t in services._registered_trainees(training, include_withdrawn=True)]
    records = []
    for raw in training.get('stagiaires') or []:
        if not isinstance(raw, dict) or services._trainee_registration_is_cancelled(raw):
            continue
        trainee = {**raw, **services._convert_old_stagiaire_to_trainee(raw)}
        if not raw.get('id'):
            # The old UI's conversion generates a new ID on every read. Keep a
            # stable lookup for this feed; a collision is rejected on update.
            identity = [training['id'], *(raw.get(k) or '' for k in ('nom', 'prenom', 'email', 'date_naissance'))]
            trainee['id'] = 'legacy-' + uuid.uuid5(uuid.NAMESPACE_OID, '\0'.join(identity)).hex
        records.append((raw, trainee))
    return records


def roster(services, data, training):
    records = sorted(enrolled_records(services, training), key=lambda pair: services._trainee_alpha_sort_key(pair[1]))
    pool = [c for c in (data.get('afc') or {}).get('candidates', []) if isinstance(c, dict)]
    by_id = {c['id']: c for c in pool if c.get('id')}
    result = []
    for raw, trainee in records:
        link = trainee.get('afc_candidate_id')
        candidate = by_id.get(link)
        if not link and not trainee.get('afc_attendance_ft_edited_at') and not trainee.get('identifiant_ft'):
            legacy = [c for c in pool if afc_enrolments.same_legacy_contact(trainee, c)]
            if len(legacy) == 1 and sum(afc_enrolments.same_legacy_contact(t, legacy[0]) for _, t in records) == 1:
                candidate = legacy[0]
        identifier = (candidate or {}).get('identifiant_ft') or trainee.get('identifiant_ft')
        period = afc_schedule.participation_period(training, trainee)
        row = {'id': trainee['id'], 'lastName': trainee.get('last_name') or '',
               'firstName': trainee.get('first_name') or '', 'france_travail_id': str(identifier or '').strip(),
               'entryDate': period['date_start'], 'exitDate': period['date_end'], 'ranHours': trainee.get('afc_ran_hours')}
        result.append((row, raw, by_id.get(link)))
    return result


def clean_changes(changes, raw, training):
    clean = dict(changes)
    updates = {}
    if 'france_travail_id' in clean:
        value = clean['france_travail_id']
        if not isinstance(value, str) or len(value) > 64 or (value.strip() and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 -]*', value.strip())):
            raise ValueError('Vérifiez les lettres et les chiffres de l’identifiant France Travail.')
        clean['france_travail_id'] = updates['identifiant_ft'] = normalize_ft_id(value.strip().upper())[1]
    if 'ranHours' in clean:
        hours = clean['ranHours']
        entry = clean.get('entryDate') or raw.get('training_date_start')
        planned = type(hours) is int and hours not in afc_hours.PROFILES and afc_hours.remaining_ran(training).get(entry) == hours
        if hours is not None and not planned and (type(hours) is not int or hours not in afc_hours.PROFILES):
            raise ValueError('Choisissez un profil de remise à niveau ou le volume prévu à cette date.')
        updates.update(afc_ran_hours=hours, afc_ran_from_planning=planned)
        if planned:
            updates['afc_start_override'] = entry
    if 'entryDate' in clean:
        if not clean['entryDate']:
            raise ValueError('Renseignez la date d’entrée en formation.')
        updates.update(afc_schedule.trainee_update(training, {**raw, **updates}, {'training_date_start': clean['entryDate']}))
        clean['entryDate'] = updates['training_date_start']
    return clean, updates


def edit_student(services, data, selector, payload):
    training = select_training(services, data, *selector)
    if training['id'] != payload.get('sourceSessionId'):
        abort(409, description='La session associée a changé. Actualisez la liste.')
    records = roster(services, data, training)
    matches = [item for item in records if item[0]['id'] == payload.get('studentId')]
    if len(matches) != 1:
        abort(409, description='Ce stagiaire ne figure plus de façon unique dans la session. Actualisez la liste.')
    row, raw, linked_candidate = matches[0]
    changes, previous = payload['changes'], payload['previous']
    clean, updates = clean_changes(changes, raw, training)
    for field, value in clean.items():
        if row[field] != previous[field] and row[field] != value:
            abort(409, description='Cette information a été modifiée depuis l’ouverture du tableau. Actualisez la ligne.')
    if all(row[field] == value for field, value in clean.items()):
        return row
    if 'france_travail_id' in clean and clean['france_travail_id'] != row['france_travail_id']:
        key = normalize_ft_id(clean['france_travail_id'])[0]
        if key and any(other['id'] != row['id'] and normalize_ft_id(other['france_travail_id'])[0] == key
                       for other, _, _ in records):
            raise ValueError('Cet identifiant appartient déjà à un autre inscrit de la session.')
        if linked_candidate is not None:
            linked_candidate['identifiant_ft'] = clean['france_travail_id']
        # An unlinked legacy candidate was only a read fallback. An explicit
        # correction (including clearing the field) belongs to this enrolment.
        raw['afc_attendance_ft_edited_at'] = services._now_iso()
    if 'entryDate' in clean and clean['entryDate'] != row['entryDate']:
        raw['afc_dates_changed_at'] = services._now_iso()
    raw.update(updates)
    return {**row, **clean, 'ranHours': raw.get('afc_ran_hours')}


def register(app, services):
    @app.route('/api/integrations/plateformegestion/afc-attendance', methods=['GET', 'PATCH'])
    def afc_attendance_roster():
        secret = os.environ.get('AFC_ATTENDANCE_SYNC_TOKEN', '').strip()
        if not secret or not hmac.compare_digest(
                request.headers.get('Authorization', '').encode(), ('Bearer ' + secret).encode()):
            abort(403)
        selector = (request.args.get('session_id', '').strip(), request.args.get('date_start', ''), request.args.get('date_end', ''))
        try:
            if request.method == 'PATCH':
                payload = request.get_json(silent=True)
                if not isinstance(payload, dict) or not isinstance(payload.get('changes'), dict) or not isinstance(payload.get('previous'), dict):
                    raise ValueError('Modification de stagiaire invalide.')
                keys = set(payload['changes'])
                if not keys or not keys <= EDITABLE or keys != set(payload['previous']):
                    raise ValueError('Champs de modification invalides.')
                if not all(isinstance(payload.get(k), str) and payload[k] for k in ('studentId', 'sourceSessionId')):
                    raise ValueError('Session ou stagiaire manquant.')
                row = services._atomic_update_data(lambda data: edit_student(services, data, selector, payload))
                return jsonify(ok=True, student=row)
            data = services.load_data(run_background_tasks=False)
            training = select_training(services, data, *selector)
            rows = [row for row, _, _ in roster(services, data, training)]
            return jsonify(ok=True, session={'id': training['id'], 'name': services._session_get(training, 'name'),
                                             'ranStartDates': afc_hours.config(training)['dates']}, students=rows)
        except HTTPException as error:
            return jsonify(ok=False, error=error.description), error.code
        except ValueError as error:
            return jsonify(ok=False, error=str(error)), 400
