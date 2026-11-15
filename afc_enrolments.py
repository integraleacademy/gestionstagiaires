"""Import existing AFC candidates into an AFC session without duplicate enrolments."""
import hmac
import os
import re
import unicodedata

from flask import abort, jsonify, request
import afc_schedule


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '').casefold())
                   if not unicodedata.combining(c)).strip()


def candidates(data):
    return [c for c in (data.get('afc') or {}).get('candidates', [])
            if isinstance(c, dict) and not c.get('archived')]


def fields(candidate):
    return {target: str(candidate.get(source) or '') for target, source in (
        ('last_name', 'nom'), ('first_name', 'prenom'), ('email', 'email'),
        ('phone', 'telephone'), ('birth_date', 'birth_date'), ('birth_city', 'birth_city'),
        ('address', 'address'), ('zip_code', 'zip_code'), ('city', 'city'))}


def supported(services, training):
    return bool(training and afc_schedule.enabled(training)
                and training.get('partner_id') in (None, '', services.INTEGRALE_PARTNER_ID))


def same_legacy_contact(trainee, candidate):
    if (normalized(trainee.get('last_name')) != normalized(candidate.get('nom'))
            or normalized(trainee.get('first_name')) != normalized(candidate.get('prenom'))):
        return False
    email = normalized(candidate.get('email'))
    phone = re.sub(r'\D', '', str(candidate.get('telephone') or ''))
    return bool((email and email == normalized(trainee.get('email')))
                or (phone and phone == re.sub(r'\D', '', str(trainee.get('phone') or ''))))


def duplicate(services, training, candidate):
    for trainee in services._session_trainees_list(training):
        if str(trainee.get('afc_candidate_id') or '') == str(candidate['id']):
            return trainee
        ft = re.sub(r'\s+', '', str(candidate.get('identifiant_ft') or '')).upper()
        if ft and ft == re.sub(r'\s+', '', str(trainee.get('identifiant_ft') or '')).upper():
            return trainee
        # Legacy imports did not retain the AFC identifier. Match a name AND
        # contact, never just a shared family email or a namesake.
        if same_legacy_contact(trainee, candidate):
            return trainee
    return None


def validate(services, data, training, candidate_id):
    if not supported(services, training):
        raise ValueError('L’import depuis AFC est réservé aux sessions AFC d’Intégrale Academy.')
    candidate = next((c for c in candidates(data) if str(c.get('id')) == candidate_id), None)
    if candidate is None:
        raise ValueError('Ce candidat AFC est introuvable ou archivé. Actualisez la liste.')
    if duplicate(services, training, candidate):
        raise ValueError('Ce candidat figure déjà dans cette session. Ouvrez son dossier existant.')
    return candidate


def insert(services, data, session_id, candidate_id, trainee):
    training = services.find_session(data, session_id)
    try:
        candidate = validate(services, data, training, candidate_id)
        trainee.update(afc_schedule.trainee_update(training, trainee, {
            'training_date_start': trainee.get('training_date_start', '')}))
    except ValueError as exc:
        return {'ok': False, 'error': str(exc), 'status': 409}
    trainee.update(afc_candidate_id=candidate_id,
                   identifiant_ft=str(candidate.get('identifiant_ft') or ''),
                   afc_imported_at=services._now_iso())
    if trainee.get('cnaps') != 'CARTE PROFESSIONNELLE OK':
        trainee['cnaps'] = services._normalize_cnaps_status(candidate.get('cnaps_status') or 'INCONNU')
    rows = services._session_trainees_list(training)
    rows.insert(0, trainee)
    training['trainees'] = rows
    training.pop('stagiaires', None)
    candidate['enrolled_at'] = candidate.get('enrolled_at') or services._now_iso()
    services.increment_partner_trainee_usage(data, training.get('partner_id') or services.INTEGRALE_PARTNER_ID, trainee)
    return {'ok': True, 'enrolled_at': candidate['enrolled_at']}


def register(app, services):
    @app.get('/api/integrations/plateformegestion/afc-attendance')
    def afc_attendance_roster():
        secret = os.environ.get('AFC_ATTENDANCE_SYNC_TOKEN', '').strip()
        if not secret or not hmac.compare_digest(
                request.headers.get('Authorization', '').encode(), ('Bearer ' + secret).encode()):
            abort(403)
        source_id = request.args.get('session_id', '').strip()
        start, end = request.args.get('date_start', ''), request.args.get('date_end', '')
        if not source_id and not (start and end):
            return jsonify(ok=False, error='Une session ou ses deux dates sont nécessaires.'), 400
        data = services.load_data(run_background_tasks=False)
        sessions = [s for s in data.get('sessions', []) if supported(services, s)]
        if source_id:
            matches = [s for s in sessions if s.get('id') == source_id]
        else:
            matches = [s for s in sessions if services._session_get(s, 'date_start') == start
                       and services._session_get(s, 'date_end') == end]
        if not matches:
            return jsonify(ok=False, error='Session AFC introuvable.'), 404
        if len(matches) != 1:
            return jsonify(ok=False, error='Plusieurs sessions AFC correspondent aux dates.'), 409
        training = matches[0]
        # Archived candidates can still be enrolled in a session.
        pool = [c for c in (data.get('afc') or {}).get('candidates', []) if isinstance(c, dict)]
        by_id = {c['id']: c for c in pool if c.get('id')}
        rows = []
        trainees = sorted(services._registered_trainees(training), key=services._trainee_alpha_sort_key)
        for trainee in trainees:
            candidate = by_id.get(trainee.get('afc_candidate_id')) or {}
            identifier = candidate.get('identifiant_ft') or trainee.get('identifiant_ft')
            if not identifier and not trainee.get('afc_candidate_id'):
                legacy = [c for c in pool if same_legacy_contact(trainee, c)]
                if len(legacy) == 1 and sum(same_legacy_contact(t, legacy[0]) for t in trainees) == 1:
                    identifier = legacy[0].get('identifiant_ft')
            period = afc_schedule.effective_session(training, trainee)
            rows.append({'id': trainee['id'], 'lastName': trainee.get('last_name') or '',
                         'firstName': trainee.get('first_name') or '',
                         'france_travail_id': str(identifier or '').strip(),
                         'entryDate': period['date_start'], 'exitDate': period['date_end'],
                         'ranHours': trainee.get('afc_ran_hours')})
        return jsonify(ok=True, session={'id': training['id'], 'name': services._session_get(training, 'name')},
                       students=rows)

    @app.get('/api/admin/sessions/<session_id>/afc-candidates')
    @services.admin_login_required
    def api_afc_session_candidates(session_id):
        data = services.load_data(run_background_tasks=False)
        training = services.find_session(data, session_id)
        if not supported(services, training):
            abort(404)
        query = normalized(request.args.get('q', ''))[:150]
        rows = []
        for candidate in candidates(data):
            if query and query not in normalized(' '.join(str(candidate.get(k) or '') for k in (
                    'nom', 'prenom', 'email', 'telephone', 'identifiant_ft'))):
                continue
            rows.append({'id': candidate['id'], **fields(candidate),
                         'identifiant_ft': str(candidate.get('identifiant_ft') or ''),
                         'decision': str(candidate.get('decision') or ''),
                         'already_enrolled': duplicate(services, training, candidate) is not None})
        rows.sort(key=lambda row: (row['already_enrolled'], normalized(row['last_name']), normalized(row['first_name'])))
        response = jsonify(ok=True, candidates=rows[:100], total=len(rows))
        response.headers['Cache-Control'] = 'private, no-store'
        return response
