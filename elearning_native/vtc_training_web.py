"""VTC supplemental practice: authenticated corrections without tracking writes."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from flask import abort, jsonify, render_template, request, session, url_for

from . import vtc
from .practice import grade_practice


ROOT = Path(__file__).parent / 'vtc' / 'training'


def _bank(course):
    """Prefer the assigned bank, then current supplements, without repinning a course."""
    cid = course['id']
    if not re.fullmatch(r'academy-vtc-[a-h]', cid):
        abort(404)
    current = vtc.load_bundled_course(cid)
    if not current:
        abort(404)
    versions = dict.fromkeys((course['version'], current['version']))
    for version in versions:
        if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', version):
            abort(404)
        path = ROOT / version / (cid + '.json')
        if not path.is_file():
            continue
        try:
            bank = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            abort(404)
        if (not isinstance(bank, dict) or bank.get('version') != version
                or bank.get('course_id') != cid or not isinstance(bank.get('activities'), list)):
            abort(404)
        allowed = set(course['activity_order'])
        # The first editions predate dossier IDs. Their assigned lessons still
        # provide an explicit boundary for supplements from a later bank.
        legacy = (course['version'] in {'20261006-vtc-v1', '20261006-vtc-v2'}
                  and version != course['version'])
        lesson_refs = {activity.get('vtc', {}).get('ref') for section in course['sections']
                       for activity in section['activities']
                       if activity['id'] in allowed and activity.get('vtc', {}).get('kind') == 'lesson'}

        def permitted(item):
            if not isinstance(item, dict) or not item.get('practice', {}).get('exercises'):
                return False
            if item.get('id') in allowed:
                return True
            refs = {exercise.get('competency') for exercise in item['practice']['exercises']}
            return (legacy and bool(refs) and None not in refs and '' not in refs
                    and refs.issubset(lesson_refs))

        bank['activities'] = [item for item in bank['activities']
                              if permitted(item)]
        return bank
    abort(404, "L’entraînement de cette matière sera disponible prochainement.")


def _available_media(activity, course):
    """Keep historical course asset permissions; offer the dialogue when needed."""
    activity = copy.deepcopy(activity)
    unavailable = False
    for exercise in activity['practice']['exercises']:
        # Branch feedback is not part of the public exercise contract.
        exercise.pop('branches', None)
        audio = exercise.get('audio')
        if not audio or audio in course.get('assets', []):
            continue
        unavailable = True
        exercise.pop('audio', None)
        dialogue = '\n'.join(f"{turn.get('speaker', '')} : {turn.get('text', '')}"
                             for turn in exercise.pop('transcript', []))
        translation = exercise.pop('translation', '')
        documents = exercise.setdefault('documents', [])
        if dialogue:
            documents.append({'title': 'Dialogue à lire', 'text': dialogue})
        if translation:
            documents.append({'title': 'Traduction du dialogue', 'text': translation})
    return activity, unavailable


def register(blueprint, *, admin_required, learner_context, csrf_token, require_csrf,
             prepare_activity, asset_token_for):
    def context(course_id, token=None):
        if not re.fullmatch(r'academy-vtc-[a-h]', course_id):
            abort(404)
        if token:
            session_obj, trainee, course = learner_context(token, course_id)
        else:
            version = request.args.get('version') or None
            course = vtc.load_bundled_course(course_id, version)
            if not course:
                abort(404)
            session_obj, trainee = None, None
        return course, _bank(course), session_obj, trainee

    def link(endpoint, course, token=None, **values):
        if token:
            return url_for('native_elearning.training_learner_' + endpoint,
                           token=token, course_id=course['id'], **values)
        return url_for('native_elearning.training_admin_' + endpoint,
                       course_id=course['id'], version=course['version'], **values)

    def find_activity(bank, activity_id):
        activity = next((item for item in bank['activities'] if item['id'] == activity_id), None)
        if not activity:
            abort(404)
        return activity

    def catalog_page(course_id, token=None):
        course, bank, _, _ = context(course_id, token)
        activities = [{'id': item['id'], 'title': item['title'],
                       'purpose': item['practice'].get('purpose', ''),
                       'count': len(item['practice']['exercises']),
                       'url': link('activity', course, token, activity_id=item['id'])}
                      for item in bank['activities']]
        back_url = (url_for('native_elearning.course_player', token=token, course_id=course_id)
                    if token else url_for('native_elearning.admin_preview', course_id=course_id,
                                         version=course['version']))
        return render_template('vtc_training_catalog.html', course=course, activities=activities,
                               preview=not token, back_url=back_url,
                               total=sum(item['count'] for item in activities))

    def activity_page(course_id, activity_id, token=None):
        course, bank, session_obj, trainee = context(course_id, token)
        raw = find_activity(bank, activity_id)
        raw, unavailable = _available_media(raw, course)
        asset_token = asset_token_for(course, token=token, session_obj=session_obj, trainee=trainee)
        activity = prepare_activity(raw, asset_token, course_id)
        # The shared journey renderer stores only this independent bank's draft.
        rendering_course = {**course, 'version': bank['version'] + ':' + str(raw['practice']['revision'])}
        config = {'answerUrl': link('answer', course, token, activity_id=activity_id,
                                   bank_version=bank['version'], revision=raw['practice']['revision']),
                  'csrfToken': csrf_token()}
        return render_template('vtc_training_activity.html', course=rendering_course,
                               activity=activity, preview=not token, free_practice=True,
                               preview_mode=True, preview_can_answer=session.get('admin_role') != 'viewer',
                               activity_completed=False, progress={'answers': {}}, config=config,
                               unavailable_audio=unavailable, back_url=link('catalog', course, token))

    def answer(course_id, activity_id, token=None):
        require_csrf()
        if session.get('admin_role') == 'viewer':
            abort(403)
        course, bank, _, _ = context(course_id, token)
        activity = find_activity(bank, activity_id)
        if (request.args.get('bank_version') != bank['version']
                or request.args.get('revision') != str(activity['practice']['revision'])):
            return jsonify(ok=False, error='Cet entraînement a été mis à jour. Rechargez la page.'), 409
        if request.content_length and request.content_length > 128_000:
            abort(413)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(ok=False, error='Réponse invalide.'), 400
        try:
            result = grade_practice(activity['practice'], payload.get('practice_answers'),
                                    payload.get('review_answers'), step=payload.get('practice_step'))
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        return jsonify(ok=True, **result)

    @blueprint.after_request
    def private_training(response):
        if (request.endpoint or '').startswith('native_elearning.training_'):
            response.headers['Cache-Control'] = 'private, no-store'
        return response

    @blueprint.get('/admin/elearning/vtc/entrainement/<course_id>')
    @admin_required
    def training_admin_catalog(course_id):
        return catalog_page(course_id)

    @blueprint.get('/espace/<token>/elearning/vtc/entrainement/<course_id>')
    def training_learner_catalog(token, course_id):
        return catalog_page(course_id, token)

    @blueprint.get('/admin/elearning/vtc/entrainement/<course_id>/<activity_id>')
    @admin_required
    def training_admin_activity(course_id, activity_id):
        return activity_page(course_id, activity_id)

    @blueprint.get('/espace/<token>/elearning/vtc/entrainement/<course_id>/<activity_id>')
    def training_learner_activity(token, course_id, activity_id):
        return activity_page(course_id, activity_id, token)

    @blueprint.post('/api/admin/elearning/vtc/entrainement/<course_id>/<activity_id>')
    @admin_required
    def training_admin_answer(course_id, activity_id):
        return answer(course_id, activity_id)

    @blueprint.post('/api/espace/<token>/elearning/vtc/entrainement/<course_id>/<activity_id>')
    def training_learner_answer(token, course_id, activity_id):
        return answer(course_id, activity_id, token)
