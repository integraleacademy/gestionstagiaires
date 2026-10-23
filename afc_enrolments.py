"""Import existing AFC candidates into an AFC session without duplicate enrolments."""
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


def duplicate(services, training, candidate):
    for trainee in services._session_trainees_list(training):
        if str(trainee.get('afc_candidate_id') or '') == str(candidate['id']):
            return trainee
        ft = re.sub(r'\s+', '', str(candidate.get('identifiant_ft') or '')).upper()
        if ft and ft == re.sub(r'\s+', '', str(trainee.get('identifiant_ft') or '')).upper():
            return trainee
        # Legacy imports did not retain the AFC identifier. Match a name AND
        # contact, never just a shared family email or a namesake.
        if (normalized(trainee.get('last_name')) == normalized(candidate.get('nom'))
                and normalized(trainee.get('first_name')) == normalized(candidate.get('prenom'))):
            email = normalized(candidate.get('email'))
            phone = re.sub(r'\D', '', str(candidate.get('telephone') or ''))
            if ((email and email == normalized(trainee.get('email')))
                    or (phone and phone == re.sub(r'\D', '', str(trainee.get('phone') or '')))):
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
