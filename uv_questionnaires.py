"""Versioned end-of-UV knowledge checks, separate from certification exams."""
from datetime import date, datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
import hmac
import json
import re
import secrets
import time
from xml.sax.saxutils import escape

from flask import abort, jsonify, redirect, render_template, request, send_file, session, url_for

import afc_schedule

VERSION = '20261026'
TITLE = "Questionnaire de fin d'UV - Evaluation formative"
COHORT_START = date(2026, 10, 26)
QUESTION_SECONDS = 45
NOTICE = 'Le questionnaire de fin d’UV doit impérativement être réalisé pendant les cours et en présence du formateur.'
BANK_DIR = Path(__file__).with_name('uv_questionnaires')


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


def _result(trainee, course, number):
    return ((trainee.get('uv_questionnaires') or {}).get(course) or {}).get(str(number))


def unit(course, number, version=VERSION):
    return next((row for row in bank(version)['courses'].get(course, {}).get('units', [])
                 if row['number'] == number and not re.search(r'\bSST\b', row['title'], re.I)), None)


def view(services, training, trainee):
    course = course_for(training)
    if not course or not eligible(training):
        return None
    start = practical_start(training, trainee)
    rows = []
    for row in bank()['courses'][course]['units']:
        if not unit(course, row['number']):
            continue
        result = _result(trainee, course, row['number'])
        rows.append(dict(number=row['number'], title=row['title'],
                         score=result.get('score') if result else None,
                         submitted_at=result.get('submitted_at') if result else '',
                         completed=bool(result)))
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


def attempt_state(services, trainee, course, number, attempt, row, now):
    result = _result(trainee, course, number)
    if result:
        return dict(completed=True, score=result['score'])
    if not attempt:
        return dict(started=False, completed=False)
    question = row['questions'][attempt['index']]
    return dict(started=True, completed=False, index=attempt['index'] + 1,
                total=len(row['questions']), remaining_ms=max(0, int((attempt['deadline']-now)*1000)),
                question=dict(id=question['id'], prompt=question['prompt'], options=question['options']))


def register(app, services):
    def public_pair(token, data):
        training, trainee = services.find_session_and_trainee_by_token(data, token)
        if not training or not trainee or not eligible(training):
            abort(404)
        return training, trainee

    @app.route('/espace/<token>/questionnaires-uv/<int:number>', methods=['GET', 'POST'])
    def public_uv_questionnaire(token, number):
        if not services._public_is_authed(token):
            return redirect(url_for('public_trainee_login', token=token))
        training, trainee = public_pair(token, services.load_data(run_background_tasks=False))
        course = course_for(training)
        if not available(services, training, trainee):
            abort(403, description='Ces questionnaires sont accessibles à partir du début du présentiel, pendant les cours et en présence du formateur.')
        result = _result(trainee, course, number)
        row = unit(course, number, result['version'] if result else VERSION)
        if not row:
            abort(404)
        csrf = session.setdefault('uv_questionnaire_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            payload = request.get_json(silent=True) or request.form
            if not hmac.compare_digest(str(payload.get('csrf') or ''), csrf):
                abort(403)
            action = payload.get('action')
            if action not in {'start', 'answer', 'sync'}:
                return jsonify(error='Rechargez le questionnaire pour continuer.'), 400
            def mutate(current):
                current_training, current_trainee = public_pair(token, current)
                if course_for(current_training) != course or not available(services, current_training, current_trainee):
                    abort(409, description='Les conditions d’accès ont changé. Actualisez votre espace.')
                saved = _result(current_trainee, course, number)
                if saved:
                    return dict(completed=True, score=saved['score'])
                attempts = current_trainee.get('uv_questionnaire_attempts', {}).get(course, {})
                attempt = attempts.get(str(number))
                now = clock()
                if not attempt:
                    if action == 'sync':
                        return dict(started=False, completed=False)
                    if action != 'start' or payload.get('in_class') != 'yes':
                        abort(400, description='Confirmez votre présence en cours avec le formateur avant de commencer.')
                    attempt = dict(version=VERSION, answers={}, index=0, deadline=now+QUESTION_SECONDS,
                                   started_at=services._now_iso())
                    current_trainee.setdefault('uv_questionnaire_attempts', {}).setdefault(course, {})[str(number)] = attempt
                active_row = unit(course, number, attempt['version'])
                if not active_row:
                    abort(409)
                question = active_row['questions'][attempt['index']]
                # Reloads and concurrent tabs cannot reset the deadline or overwrite a previous answer.
                expired = now >= attempt['deadline']
                if expired:
                    advance(services, current_trainee, course, number, attempt, active_row, '', now)
                elif action == 'answer' and payload.get('question_id') == question['id']:
                    answer = payload.get('answer')
                    if answer not in {o['id'] for o in question['options']}:
                        abort(400, description='Sélectionnez une réponse avant de valider.')
                    advance(services, current_trainee, course, number, attempt, active_row, answer, now)
                return attempt_state(services, current_trainee, course, number, attempt, active_row, now)
            response = jsonify(services._atomic_update_data(mutate))
        else:
            response = app.make_response(render_template('uv_questionnaire.html',
                training=training, trainee=trainee, course=course, number=number, title=row['title'],
                questionnaire_title=TITLE, questions=row['questions'] if result else [],
                result=result, correction=bool(result), admin_preview=False, notice=NOTICE,
                csrf=csrf, seconds_per_question=QUESTION_SECONDS,
                back_url=url_for('public_trainee_space', token=token), token=token))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    def admin_pair(session_id, trainee_id, number):
        training, _, trainee = services._find_session_trainee(
            services.load_data(run_background_tasks=False), session_id, trainee_id)
        if not training or not trainee or not eligible(training):
            abort(404)
        course = course_for(training)
        result = _result(trainee, course, number)
        row = unit(course, number, result['version'] if result else VERSION)
        if not row:
            abort(404)
        return training, trainee, course, row, result

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
