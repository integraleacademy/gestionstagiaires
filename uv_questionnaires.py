"""Versioned end-of-UV knowledge checks, separate from certification exams."""
from copy import deepcopy
from datetime import date, datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
import hmac
import json
import re
import secrets
import threading
import time
from xml.sax.saxutils import escape

from flask import abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for

import afc_schedule
from uv_questionnaire_context import UnversionedSource, index_for
from uv_questionnaire_store import UV_FIELDS, UVQuestionnaireStore

VERSION = '20261026'
TITLE = "Questionnaire de fin d'UV - Evaluation formative"
COHORT_START = date(2026, 10, 26)
QUESTION_SECONDS = 45
NOTICE = 'Le questionnaire de fin d’UV doit impérativement être réalisé pendant les cours et en présence du formateur.'
BANK_DIR = Path(__file__).with_name('uv_questionnaires')
_BACKUP_LOCK = threading.Lock()
_LAST_BACKUPS = {}


@lru_cache(maxsize=16)
def bank(version=VERSION):
    if not re.fullmatch(r'\d{8}', str(version)):
        raise ValueError('Version du questionnaire invalide.')
    return json.loads((BANK_DIR / f'{version}.json').read_text(encoding='utf-8'))


def course_for(training):
    text = str(training.get('training_type') or training.get('name') or '').upper()
    if re.search(r'\b(MAC|VAE|RECYCLAGE)\b', text):
        return ''
    if afc_schedule.enabled(training):
        return 'aps'
    for code in ('aps', 'a3p'):
        if re.match(rf'^{code}\b', text, re.I):
            return code
    return ''


def _date(value):
    try:
        return date.fromisoformat(str(value or ''))
    except ValueError:
        return None


def eligible(training):
    """Eligibility follows the session start, not a later individual/practical date."""
    start = _date(training.get('date_start'))
    return bool(course_for(training) and start and start >= COHORT_START)


def today():
    return datetime.now(ZoneInfo('Europe/Paris')).date()


def practical_start(training, trainee):
    explicit = _date(training.get('aps_in_person_start'))
    if afc_schedule.enabled(training):
        # AFC is wholly in person. Ignore legacy APS remote/practical subperiods.
        return _date(afc_schedule.effective_session(training, trainee).get('date_start'))
    if explicit:
        return explicit
    # APS has a remote phase: never unlock merely because the overall course began.
    if course_for(training) == 'aps' or training.get('aps_elearning_enabled') or training.get('aps_remote_start'):
        return None
    return _date(training.get('date_start'))


def available(services, training, trainee):
    start = practical_start(training, trainee)
    return bool(eligible(training) and start and today() >= start
                and not services._trainee_registration_is_cancelled(trainee))


def _entry(trainee, field, course, number):
    return ((trainee.get(field) or {}).get(course) or {}).get(str(number))


def _result(trainee, course, number):
    return _entry(trainee, 'uv_questionnaires', course, number)


def _generation(trainee, course, number):
    return _entry(trainee, 'uv_questionnaire_resets', course, number) or ''


def _store_path(services):
    configured = services.app.config.get('UV_QUESTIONNAIRE_DB_PATH')
    return Path(configured or Path(services.DATA_FILE).with_name('uv-questionnaires.sqlite3'))


def _store(services):
    return UVQuestionnaireStore(_store_path(services))


def _public_pair(services, token, *, original_loader=None):
    """Read one UV context without normalizing/copying all business records."""
    loader = services.load_data
    path = getattr(services, 'DATA_FILE', None)
    # An injected data provider or authoritative PostgreSQL tenant needs its
    # own freshness rules. Keep the existing scoped reader for those sources.
    use_index = (path and original_loader is not None and loader is original_loader
                 and not getattr(services, '_partner_postgres_active', lambda: False)()
                 and not getattr(services, '_is_partner_data_scope_session', lambda: False)())
    if use_index:
        try:
            return index_for(path).lookup(token)
        except UnversionedSource:
            pass
        except (OSError, ValueError):
            # Do not authorize a removed token using the previous cached file.
            abort(503, description='Le contexte du questionnaire est momentanément indisponible. Réessayez.')
    data = loader(run_background_tasks=False, persist_normalization=False)
    return services.find_session_and_trainee_by_token(data, token)


def backup_state(services, reason='manual'):
    """Include a standalone SQLite snapshot in the existing backup lifecycle.

    Automatic snapshots are throttled; answering a question never calls this.
    Use SQLite's backup API so acknowledged answers still in WAL are included.
    """
    path = _store_path(services)
    if not path.is_file():
        return None
    periodic = reason in {'before-save', 'interval'}
    with _BACKUP_LOCK:
        key = str(path.resolve())
        now = time.monotonic()
        if periodic and now - _LAST_BACKUPS.get(key, float('-inf')) < services.BACKUP_MIN_INTERVAL_SECONDS:
            return None
        destination = Path(services.BACKUP_DIR) / (
            'uv_questionnaires.' + datetime.utcnow().strftime('%Y%m%dT%H%M%S.%fZ')
            + '.' + secrets.token_hex(4) + '.sqlite3')
        _store(services).backup_to(destination)
        _LAST_BACKUPS[key] = time.monotonic()
        services._cleanup_backups_for('uv_questionnaires')
        return destination


def _storage_key(services, training, trainee):
    return (str(training.get('partner_id') or services.INTEGRALE_PARTNER_ID),
            str(training.get('id') or ''), str(trainee.get('id') or ''))


def _legacy_state(trainee):
    return {field: trainee[field] for field in UV_FIELDS if field in trainee}


def stored_trainee(services, training, trainee):
    """Overlay authoritative UV state without modifying administrative snapshots.

    Old attempts/results remain readable and are imported on their first mutation.
    An existing SQLite row (including a reset) always wins over legacy JSON.
    """
    saved = _store(services).read(_storage_key(services, training, trainee))
    if saved is None:
        return trainee
    person = {field: value for field, value in trainee.items() if field not in UV_FIELDS}
    person.update(saved)
    return person


def transfer_state(services, source, target, trainee):
    """Keep one state across an authorized administrative session transfer.

    A storage alias also routes answers already in flight to the same row.
    Creating it before saving the administrative move leaves the source intact
    if that save fails, and never copies potentially stale answers.
    """
    _store(services).transfer(_storage_key(services, source, trainee),
                              _storage_key(services, target, trainee), _legacy_state(trainee))


def _question_context(trainee, course, number):
    attempt = _entry(trainee, 'uv_questionnaire_attempts', course, number)
    result = _result(trainee, course, number)
    row = unit(course, number, (result or attempt or {}).get('version', VERSION))
    if not row:
        abort(404)
    return row, attempt, result


def preserve_state(payload, canonical, trainees, default_partner):
    """Only the UV transactions own these fields. Ignore older form snapshots."""
    fields = ('uv_questionnaire_attempts', 'uv_questionnaires', 'uv_questionnaire_resets')
    saved = {
        (training.get('partner_id') or default_partner, str(training.get('id')), str(person.get('id'))): person
        for training in canonical.get('sessions', [])
        for person in trainees(training)
        if any(field in person for field in fields)
    }
    if not saved:
        return
    for training in payload.get('sessions', []):
        scope = (training.get('partner_id') or default_partner, str(training.get('id')))
        for person in trainees(training):
            current = saved.get((*scope, str(person.get('id'))))
            if current is not None:
                for field in fields:
                    if field not in current:
                        person.pop(field, None)
                    elif person.get(field) != current[field]:
                        person[field] = deepcopy(current[field])


def unit(course, number, version=VERSION):
    return next((row for row in bank(version)['courses'].get(course, {}).get('units', [])
                 if row['number'] == number and not re.search(r'\bSST\b', row['title'], re.I)), None)


def view(services, training, trainee):
    course = course_for(training)
    if not course or not eligible(training):
        return None
    trainee = stored_trainee(services, training, trainee)
    start = practical_start(training, trainee)
    rows = []
    for row in bank()['courses'][course]['units']:
        if not unit(course, row['number']):
            continue
        result = _result(trainee, course, row['number'])
        attempt = _entry(trainee, 'uv_questionnaire_attempts', course, row['number'])
        rows.append(dict(number=row['number'], title=row['title'],
                         score=result.get('score') if result else None,
                         submitted_at=result.get('submitted_at') if result else '',
                         completed=bool(result),
                         in_progress=bool(attempt and not result),
                         generation=_generation(trainee, course, row['number'])))
    return dict(course=course, label=course.upper(), title=TITLE, notice=NOTICE, units=rows,
                completed_count=sum(row['completed'] for row in rows),
                available=available(services, training, trainee),
                start_label=start.strftime('%d/%m/%Y') if start else '',
                cancelled=services._trainee_registration_is_cancelled(trainee))


def grade(questions, answers):
    if set(answers) != {q['id'] for q in questions}:
        raise ValueError('Veuillez répondre aux 20 questions avant de valider.')
    for q in questions:
        if answers[q['id']] not in {'', *[o['id'] for o in q['options']]}:
            raise ValueError('Une réponse est invalide. Veuillez vérifier le questionnaire.')
    return sum(answers[q['id']] == q['answer'] for q in questions)


def _public_questions(row):
    # The answer key and explanations never enter an unsubmitted public page.
    return [dict(id=q['id'], prompt=q['prompt'], options=q['options']) for q in row['questions']]


def pdf(training, trainee, course, row, result=None, correction=False):
    from uv_questionnaire_pdf import build
    return build(training, trainee, course, row, result, correction, title=TITLE, notice=NOTICE)


def clock():
    return time.time()


def advance(services, trainee, course, number, attempt, row, answer, now):
    question = row['questions'][attempt['index']]
    if not answer:
        attempt.setdefault('expired_deadlines', {})[question['id']] = attempt['deadline']
    attempt['answers'][question['id']] = answer
    attempt['index'] += 1
    if attempt['index'] == len(row['questions']):
        result = dict(version=attempt['version'], answers=dict(attempt['answers']),
                      score=grade(row['questions'], attempt['answers']),
                      submitted_at=services._now_iso(), in_class=True,
                      started_at=attempt['started_at'], seconds_per_question=QUESTION_SECONDS)
        trainee.setdefault('uv_questionnaires', {}).setdefault(course, {})[str(number)] = result
    else:
        attempt['deadline'] = now + QUESTION_SECONDS


def attempt_state(trainee, course, number, attempt, row):
    result = _result(trainee, course, number)
    if result:
        return dict(completed=True, score=result['score'])
    if not attempt:
        return dict(started=False, completed=False)
    question = row['questions'][attempt['index']]
    return dict(started=True, completed=False, index=attempt['index'] + 1,
                total=len(row['questions']), deadline=attempt['deadline'],
                question=dict(id=question['id'], prompt=question['prompt'], options=question['options']))


def _valid_answer(question, payload):
    answer = payload.get('answer')
    if answer not in [option['id'] for option in question['options']]:
        abort(400, description='Sélectionnez une réponse avant de valider.')
    return answer


def _apply_action(services, trainee, course, number, row, attempt, payload, received_at):
    action = payload['action']
    question_id = payload.get('question_id')
    result = _result(trainee, course, number)
    # A timeout from another tab may acquire the lock ahead of an on-time answer.
    expired_deadlines = (attempt or {}).get('expired_deadlines', {})
    previous_deadline = expired_deadlines.get(question_id)
    if (action == 'answer' and previous_deadline is not None
            and previous_deadline - QUESTION_SECONDS <= received_at < previous_deadline):
        question = next(q for q in row['questions'] if q['id'] == question_id)
        attempt['answers'][question_id] = _valid_answer(question, payload)
        del expired_deadlines[question_id]
        if result:
            result['answers'][question_id] = attempt['answers'][question_id]
            result['score'] = grade(row['questions'], result['answers'])
    elif not result:
        if not attempt:
            if action == 'sync':
                return dict(started=False, completed=False)
            if action != 'start' or payload.get('in_class') != 'yes':
                abort(400, description='Confirmez votre présence en cours avec le formateur avant de commencer.')
            attempt = dict(version=VERSION, answers={}, index=0, deadline=clock()+QUESTION_SECONDS,
                           started_at=services._now_iso())
            trainee.setdefault('uv_questionnaire_attempts', {}).setdefault(course, {})[str(number)] = attempt
        else:
            question = row['questions'][attempt['index']]
            # A replay for an earlier question must never expire the current one.
            if question_id == question['id'] or (not question_id and action in {'sync', 'start'}):
                if received_at >= attempt['deadline']:
                    advance(services, trainee, course, number, attempt, row, '', clock())
                elif action == 'answer' and received_at >= attempt['deadline'] - QUESTION_SECONDS:
                    advance(services, trainee, course, number, attempt, row, _valid_answer(question, payload), clock())
    state = attempt_state(trainee, course, number, attempt, row)
    if action == 'answer' and question_id in (attempt or {}).get('expired_deadlines', {}):
        state['answer_expired'] = True
    return state


def register(app, services):
    original_loader = services.load_data

    def reset_csrf():
        return session.setdefault('uv_reset_csrf', secrets.token_urlsafe(32))

    app.jinja_env.globals['uv_reset_csrf'] = reset_csrf

    def public_context(token, number, access_status=403):
        training, trainee = _public_pair(services, token, original_loader=original_loader)
        if not training or not trainee or not eligible(training):
            abort(404)
        if not available(services, training, trainee):
            abort(access_status, description='Ces questionnaires sont accessibles pendant les cours en présentiel.')
        trainee = stored_trainee(services, training, trainee)
        course = course_for(training)
        row, attempt, result = _question_context(trainee, course, number)
        return training, trainee, course, row, attempt, result

    @app.route('/espace/<token>/questionnaires-uv/<int:number>', methods=['GET', 'POST'])
    def public_uv_questionnaire(token, number):
        processing_started = time.monotonic()
        received_at = clock()
        if not services._public_is_authed(token):
            return redirect(url_for('public_trainee_login', token=token))
        csrf = session.setdefault('uv_questionnaire_csrf', secrets.token_urlsafe(32))
        if request.method == 'GET':
            training, trainee, course, row, _, result = public_context(token, number)
            response = app.make_response(render_template('uv_questionnaire.html',
                training=training, trainee=trainee, course=course, number=number, title=row['title'],
                questionnaire_title=TITLE, questions=row['questions'] if result else [],
                result=result, correction=bool(result), admin_preview=False, notice=NOTICE,
                csrf=csrf, generation=_generation(trainee, course, number), seconds_per_question=QUESTION_SECONDS,
                back_url=url_for('public_trainee_space', token=token), token=token))
        else:
            payload = request.get_json(silent=True) or request.form
            if not isinstance(payload, dict) or not hmac.compare_digest(str(payload.get('csrf') or '').encode(), csrf.encode()):
                abort(403)
            action = payload.get('action')
            if action not in ('start', 'answer', 'sync') or not isinstance(payload.get('question_id', ''), str):
                abort(400)
            training, trainee, course, row, attempt, result = public_context(token, number)
            if (payload.get('generation') or '') != _generation(trainee, course, number):
                return jsonify(reset=True), 409
            state = None
            if action in ('start', 'sync'):
                # Opening a page, returning to a tab and ordinary syncs need no write.
                if result or not attempt:
                    needs_write = not result and action == 'start'
                else:
                    current_id = row['questions'][attempt['index']]['id']
                    needs_write = received_at >= attempt['deadline'] and payload.get('question_id') in (None, current_id)
                if not needs_write:
                    state = attempt_state(trainee, course, number, attempt, row)
            if state is None:
                def mutate(person):
                    if (payload.get('generation') or '') != _generation(person, course, number):
                        return dict(reset=True)
                    row, attempt, _ = _question_context(person, course, number)
                    return _apply_action(services, person, course, number, row, attempt, payload, received_at)
                # Only this learner's small state is written. Never take the
                # general JSON lock or run administrative work in this transaction.
                state = _store(services).mutate(_storage_key(services, training, trainee),
                                                _legacy_state(trainee), mutate)
                if state.get('reset'):
                    return jsonify(state), 409
            if 'deadline' in state:
                # Report time remaining after the durable commit, not before it.
                processing_finished = time.monotonic()
                response_at = clock()
                state['remaining_ms'] = max(0, int((state.pop('deadline') - response_at) * 1000))
                # The browser removes transport time from this snapshot. Server
                # processing is already included in remaining_ms, so expose its
                # monotonic duration to avoid subtracting that time twice.
                state['server_processing_ms'] = max(0, int((processing_finished - processing_started) * 1000))
            response = jsonify(state)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    def admin_pair(session_id, trainee_id, number, data=None):
        if data is None:
            data = services.load_data(run_background_tasks=False, persist_normalization=False)
        training, _, trainee = services._find_session_trainee(data, session_id, trainee_id)
        if not training or not trainee or not eligible(training):
            abort(404)
        owner = training.get('partner_id') or services.INTEGRALE_PARTNER_ID
        unrestricted = services._is_super_admin_session() and not session.get('assist_partner_id')
        if not unrestricted and owner != (services._current_partner_id() or services.INTEGRALE_PARTNER_ID):
            abort(404)
        trainee = stored_trainee(services, training, trainee)
        course = course_for(training)
        row, _, result = _question_context(trainee, course, number)
        return training, trainee, course, row, result

    @app.post('/admin/sessions/<session_id>/stagiaires/<trainee_id>/questionnaires-uv/<int:number>/reinitialiser')
    @services.admin_login_required
    @services.admin_write_required
    def admin_uv_questionnaire_reset(session_id, trainee_id, number):
        expected = session.get('uv_reset_csrf')
        if not expected or not hmac.compare_digest(request.form.get('csrf', '').encode(), expected.encode()):
            abort(403)

        training, trainee, course, _, _ = admin_pair(session_id, trainee_id, number)

        def reset(person):
            if request.form.get('generation') != _generation(person, course, number):
                return False
            if not _result(person, course, number) and not _entry(person, 'uv_questionnaire_attempts', course, number):
                return False
            for field in ('uv_questionnaires', 'uv_questionnaire_attempts'):
                person.get(field, {}).get(course, {}).pop(str(number), None)
            person.setdefault('uv_questionnaire_resets', {}).setdefault(course, {})[str(number)] = secrets.token_urlsafe(16)
            return True

        changed = _store(services).mutate(_storage_key(services, training, trainee),
                                          _legacy_state(trainee), reset)
        if changed:
            flash(f'Le questionnaire UV {number:02} a été remis à zéro.', 'uv_reset')
        else:
            flash('Cette tentative a déjà été remise à zéro.', 'uv_reset')
        return redirect(url_for('admin_trainee_page', session_id=session_id, trainee_id=trainee_id,
                                _anchor='questionnaires-uv'), code=303)

    @app.get('/admin/sessions/<session_id>/stagiaires/<trainee_id>/questionnaires-uv/<int:number>')
    @services.admin_login_required
    def admin_uv_questionnaire(session_id, trainee_id, number):
        training, trainee, course, row, result = admin_pair(session_id, trainee_id, number)
        response = app.make_response(render_template('uv_questionnaire.html',
            training=training, trainee=trainee, course=course, number=number, title=row['title'],
            questionnaire_title=TITLE, questions=row['questions'], result=result, correction=True, admin_preview=True,
            notice=NOTICE,
            back_url=url_for('admin_trainee_page', session_id=session_id, trainee_id=trainee_id)))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.get('/admin/sessions/<session_id>/stagiaires/<trainee_id>/questionnaires-uv/<int:number>/tester')
    @services.admin_login_required
    def admin_uv_questionnaire_demo(session_id, trainee_id, number):
        training, trainee, course, row, _ = admin_pair(session_id, trainee_id, number)
        response = app.make_response(render_template('uv_questionnaire.html',
            training=training, trainee=trainee, course=course, number=number, title=row['title'],
            questionnaire_title=TITLE, questions=[], demo_questions=row['questions'], demo=True,
            result=None, correction=False, admin_preview=True, notice=NOTICE,
            seconds_per_question=QUESTION_SECONDS,
            back_url=url_for('admin_trainee_page', session_id=session_id, trainee_id=trainee_id)))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.get('/admin/sessions/<session_id>/stagiaires/<trainee_id>/questionnaires-uv/<int:number>.pdf')
    @services.admin_login_required
    def admin_uv_questionnaire_pdf(session_id, trainee_id, number):
        training, trainee, course, row, result = admin_pair(session_id, trainee_id, number)
        mode = request.args.get('mode', 'blank')
        if mode not in {'blank', 'correction', 'answers'} or (mode == 'answers' and not result):
            abort(404)
        output = pdf(training, trainee, course, row,
                     result=result if mode == 'answers' else None, correction=mode != 'blank')
        response = send_file(output, mimetype='application/pdf', as_attachment=True,
                            download_name=f'{course.upper()}_UV{number:02}_{trainee_id}_{mode}.pdf')
        response.headers['Cache-Control'] = 'private, no-store'
        return response

