"""Authenticated read/practice endpoints for the VTC annales library."""
import hashlib
import secrets
from pathlib import Path

from flask import abort, jsonify, render_template, request, send_file, url_for

from . import annales
from .exams import ExamStore
from .paths import assigned_modules


def register(blueprint, *, admin_required, learner_session, learner_context, root,
             csrf_token, require_csrf):
    def section_or_404(section_id):
        section = annales.load_section(section_id)
        if not section:
            abort(404)
        return section

    def learner_access(token, section):
        return learner_context(token, 'academy-vtc-' + section['module'].lower())

    def catalog_page(token=None):
        allowed = set('ABCDEFG')
        if token:
            session_obj, _ = learner_session(token)
            allowed = {m['course_id'][-1].upper() for m in assigned_modules(session_obj)
                       if m['course_id'].startswith('academy-vtc-')}
            if not allowed:
                abort(403)
        documents = annales.sources()
        for doc in documents:
            doc['sections'] = [s for s in doc['sections'] if s['module'] in allowed]
            for section in doc['sections']:
                section['active_count'] = sum(q['status'] == 'active' for q in section['questions'])
                section['historical_count'] = len(section['questions']) - section['active_count']
                section['url'] = url_for('native_elearning.annales_learner_exam', token=token, section_id=section['id']) if token else url_for('native_elearning.annales_admin_exam', section_id=section['id'])
        documents = [d for d in documents if d['sections']]
        return render_template('vtc_annales_catalog.html', documents=documents, preview=not token,
                               total=sum(len(s['questions']) for d in documents for s in d['sections']),
                               back_url=url_for('native_elearning.learner_path', token=token) if token else url_for('native_elearning.admin_vtc_catalog'))

    def links(result, token=None):
        for q in result['corrections']:
            q['lesson_links'] = [{'ref': ref, 'url': url_for('native_elearning.annales_learner_lesson', token=token, ref=ref) if token else url_for('native_elearning.annales_admin_lesson', ref=ref)} for ref in q['lesson_refs']]
        return result

    def page(section_id, token=None):
        section = section_or_404(section_id)
        history = []
        context_key = 'admin-preview'
        if token:
            session_obj, trainee, _ = learner_access(token, section)
            tid = trainee.get('id') or trainee.get('trainee_id')
            context_key = hashlib.sha256(f'{session_obj["id"]}:{tid}:{token}'.encode()).hexdigest()[:24]
            history = ExamStore(root() / 'tracking.sqlite3').history(session_obj['id'], tid, section)
        public = annales.public_section(section)
        for q in public['questions']:
            if q.get('image'):
                q['image'] = url_for('native_elearning.annales_learner_image', token=token, section_id=section_id, question_id=q['id']) if token else url_for('native_elearning.annales_admin_image', section_id=section_id, question_id=q['id'])
        config = {'exam': public, 'preview': not token, 'csrfToken': csrf_token(),
                  'attemptId': secrets.token_hex(16), 'contextKey': context_key,
                  'submitUrl': url_for('native_elearning.annales_learner_submit', token=token, section_id=section_id) if token else url_for('native_elearning.annales_admin_submit', section_id=section_id)}
        return render_template('vtc_annales_exam.html', exam=public, config=config, history=history,
                               preview=not token, back_url=url_for('native_elearning.annales_learner_catalog', token=token) if token else url_for('native_elearning.annales_admin_catalog'))

    def submit(section_id, token=None):
        require_csrf()
        section = section_or_404(section_id)
        if token:
            session_obj, trainee, _ = learner_access(token, section)
        if request.content_length and request.content_length > 128_000:
            abort(413)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or payload.get('version') != section['version']:
            return jsonify(ok=False, error='Ce sujet a été mis à jour. Rechargez la page.'), 409
        try:
            result = annales.grade(section, payload.get('answers'))
            if token:
                result = ExamStore(root() / 'tracking.sqlite3').save(session_obj['id'], trainee.get('id') or trainee.get('trainee_id'), section, payload.get('attempt_id'), result)
            return jsonify(ok=True, result=links(result, token))
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    def lesson(ref, token=None):
        notes = annales.lesson_notes(ref)
        if not notes:
            abort(404)
        cid = 'academy-vtc-' + ref[0].lower()
        activity = 'vtc-' + ref.lower().replace('.', '-') + '-cours'
        if token:
            _, _, course = learner_context(token, cid)
            course_url = url_for('native_elearning.course_player', token=token, course_id=cid, activity=activity) if activity in course['activity_order'] else ''
        else:
            course_url = url_for('native_elearning.admin_preview', course_id=cid, activity=activity)
        return render_template('vtc_annales_lesson.html', ref=ref, notes=notes, course_url=course_url,
                               back_url=url_for('native_elearning.annales_learner_catalog', token=token) if token else url_for('native_elearning.annales_admin_catalog'))

    def picture(section_id, question_id, token=None):
        section = section_or_404(section_id)
        if token:
            learner_access(token, section)
        q = next((q for q in section['questions'] if q['id'] == question_id), None)
        if not q or not q.get('image'):
            abort(404)
        assets = (Path(__file__).parent / 'vtc' / 'assets').resolve()
        path = (assets / q['image']).resolve()
        if assets not in path.parents or not path.is_file():
            abort(404)
        return send_file(path, conditional=True)

    @blueprint.after_request
    def private_annales(response):
        if (request.endpoint or '').startswith('native_elearning.annales_'):
            response.headers['Cache-Control'] = 'private, no-store'
        return response

    @blueprint.get('/admin/elearning/vtc/annales')
    @admin_required
    def annales_admin_catalog():
        return catalog_page()

    @blueprint.get('/espace/<token>/elearning/vtc/annales')
    def annales_learner_catalog(token):
        return catalog_page(token)

    @blueprint.get('/admin/elearning/vtc/annales/<section_id>')
    @admin_required
    def annales_admin_exam(section_id):
        return page(section_id)

    @blueprint.get('/espace/<token>/elearning/vtc/annales/<section_id>')
    def annales_learner_exam(token, section_id):
        return page(section_id, token)

    @blueprint.post('/api/admin/elearning/vtc/annales/<section_id>')
    @admin_required
    def annales_admin_submit(section_id):
        return submit(section_id)

    @blueprint.post('/api/espace/<token>/elearning/vtc/annales/<section_id>')
    def annales_learner_submit(token, section_id):
        return submit(section_id, token)

    @blueprint.get('/admin/elearning/vtc/notions/<ref>')
    @admin_required
    def annales_admin_lesson(ref):
        return lesson(ref)

    @blueprint.get('/espace/<token>/elearning/vtc/notions/<ref>')
    def annales_learner_lesson(token, ref):
        return lesson(ref, token)

    @blueprint.get('/admin/elearning/vtc/annales/<section_id>/images/<question_id>')
    @admin_required
    def annales_admin_image(section_id, question_id):
        return picture(section_id, question_id)

    @blueprint.get('/espace/<token>/elearning/vtc/annales/<section_id>/images/<question_id>')
    def annales_learner_image(token, section_id, question_id):
        return picture(section_id, question_id, token)
