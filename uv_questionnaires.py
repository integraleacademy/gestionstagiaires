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
from xml.sax.saxutils import escape

from flask import abort, redirect, render_template, request, send_file, session, url_for

import afc_schedule

VERSION = '20261024'
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
    return bool(course_for(training) and start and today() >= start
                and not services._trainee_registration_is_cancelled(trainee))


def _result(trainee, course, number):
    return ((trainee.get('uv_questionnaires') or {}).get(course) or {}).get(str(number))


def unit(course, number, version=VERSION):
    return next((row for row in bank(version)['courses'].get(course, {}).get('units', [])
                 if row['number'] == number), None)


def view(services, training, trainee):
    course = course_for(training)
    if not course:
        return None
    start = practical_start(training, trainee)
    rows = []
    for row in bank()['courses'][course]['units']:
        result = _result(trainee, course, row['number'])
        rows.append(dict(number=row['number'], title=row['title'],
                         score=result.get('score') if result else None,
                         submitted_at=result.get('submitted_at') if result else '',
                         completed=bool(result)))
    return dict(course=course, label=course.upper(), notice=NOTICE, units=rows,
                available=available(services, training, trainee),
                start_label=start.strftime('%d/%m/%Y') if start else '',
                cancelled=services._trainee_registration_is_cancelled(trainee))


def grade(questions, answers):
    if set(answers) != {q['id'] for q in questions}:
        raise ValueError('Veuillez répondre aux 20 questions avant de valider.')
    for q in questions:
        if answers[q['id']] not in {o['id'] for o in q['options']}:
            raise ValueError('Une réponse est invalide. Veuillez vérifier le questionnaire.')
    return sum(answers[q['id']] == q['answer'] for q in questions)


def _public_questions(row):
    # The answer key and explanations never enter an unsubmitted public page.
    return [dict(id=q['id'], prompt=q['prompt'], options=q['options']) for q in row['questions']]


def pdf(training, trainee, course, row, result=None, correction=False):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=(210*mm, 297*mm),
                            rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=20*mm, bottomMargin=20*mm,
                            title=f'{course.upper()} · UV {row["number"]} · Questionnaire')
    normal = ParagraphStyle('normal', fontName='Helvetica', fontSize=9.5, leading=13, spaceAfter=6)
    heading = ParagraphStyle('heading', parent=normal, fontName='Helvetica-Bold', fontSize=17, leading=21, spaceAfter=12)
    bold = ParagraphStyle('bold', parent=normal, fontName='Helvetica-Bold', textColor=colors.HexColor('#152b49'))
    small = ParagraphStyle('small', parent=normal, fontSize=8, leading=11)
    def p(text, style=normal):
        return Paragraph(escape(str(text)), style)
    name = ' '.join(str(trainee.get(k) or '') for k in ('first_name', 'last_name')).strip()
    mode = 'Réponses et correction' if result else 'Corrigé formateur' if correction else 'Questionnaire'
    story = [p('INTÉGRALE ACADEMY', bold), p(f'{course.upper()} — UV {row["number"]}', heading),
             p(row['title'], bold), p(mode, bold),
             p(f'Stagiaire : {name} · Dossier : {trainee.get("id", "")}'),
             p(f'Session : {training.get("name", "")}'), p(NOTICE, bold),
             p('20 questions · Une seule réponse par question · 1 point par bonne réponse.'),
             p('Évaluation pédagogique de connaissances. Ne remplace ni les mises en situation pratiques ni les épreuves de certification.', small)]
    if result:
        story += [p(f'Score : {result["score"]}/20 · Remis le {result["submitted_at"]}', bold),
                  p('Le stagiaire a déclaré réaliser ce questionnaire pendant les cours et en présence du formateur.', small)]
    else:
        story += [p('Date : __________________    Formateur : __________________'),
                  p('Signature du stagiaire : __________________', small)]
    story.append(Spacer(1, 5*mm))
    for index, q in enumerate(row['questions'], 1):
        block = [p(f'{index:02}. {q["prompt"]}', bold)]
        answers = result.get('answers', {}) if result else {}
        for o in q['options']:
            marker = '[X]' if answers.get(q['id']) == o['id'] else '[ ]'
            block.append(p(f'{marker} {o["id"]}. {o["text"]}'))
        if correction or result:
            answer = next(o for o in q['options'] if o['id'] == q['answer'])
            block += [p(f'Bonne réponse : {answer["id"]}. {answer["text"]}', bold), p(q['explanation'], small)]
        block.append(Spacer(1, 3*mm))
        story.append(KeepTogether(block))
    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#526174'))
        canvas.drawString(18*mm, 12*mm, f'{course.upper()} · UV {row["number"]} · Intégrale Academy')
        canvas.drawRightString(192*mm, 12*mm, f'Page {document.page}')
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    output.seek(0)
    return output


def register(app, services):
    def public_pair(token, data):
        training, trainee = services.find_session_and_trainee_by_token(data, token)
        if not training or not trainee or not course_for(training):
            abort(404)
        return training, trainee

    @app.route('/espace/<token>/questionnaires-uv/<int:number>', methods=['GET', 'POST'])
    def public_uv_questionnaire(token, number):
        if not services._public_is_authed(token):
            return redirect(url_for('public_trainee_login', token=token))
        training, trainee = public_pair(token, services.load_data(run_background_tasks=False))
        course = course_for(training)
        if not available(services, training, trainee):
            abort(403, description='Ces questionnaires sont accessibles à partir du début de la formation pratique, pendant les cours et en présence du formateur.')
        result = _result(trainee, course, number)
        row = unit(course, number, result['version'] if result else VERSION)
        if not row:
            abort(404)
        error, values = '', {}
        csrf = session.setdefault('uv_questionnaire_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if not hmac.compare_digest(str(request.form.get('csrf') or ''), csrf):
                abort(403)
            if result:
                return redirect(url_for('public_uv_questionnaire', token=token, number=number), code=303)
            values = {k: v for k, v in request.form.items() if k.startswith('q')}
            try:
                if request.form.get('version') != VERSION:
                    raise ValueError('Le questionnaire a été actualisé. Rechargez la page avant de répondre.')
                if request.form.get('in_class') != 'yes':
                    raise ValueError('Confirmez que vous réalisez le questionnaire pendant les cours et en présence du formateur.')
                score = grade(row['questions'], values)
                def save(current):
                    current_training, current_trainee = public_pair(token, current)
                    if course_for(current_training) != course or not available(services, current_training, current_trainee):
                        abort(409, description='La session ou les conditions d’accès ont changé. Actualisez votre espace.')
                    entries = current_trainee.setdefault('uv_questionnaires', {}).setdefault(course, {})
                    if str(number) not in entries:
                        entries[str(number)] = dict(version=VERSION, answers=values, score=score,
                                                     submitted_at=services._now_iso(), in_class=True)
                    return {'ok': True}
                services._atomic_update_data(save)
                return redirect(url_for('public_uv_questionnaire', token=token, number=number), code=303)
            except ValueError as exc:
                error = str(exc)
        response = app.make_response(render_template('uv_questionnaire.html',
            training=training, trainee=trainee, course=course, number=number, title=row['title'],
            questions=row['questions'] if result else _public_questions(row),
            result=result, correction=bool(result), admin_preview=False, notice=NOTICE,
            values=values, error=error, csrf=csrf, version=VERSION,
            back_url=url_for('public_trainee_space', token=token), token=token))
        response.headers['Cache-Control'] = 'private, no-store'
        if error:
            response.status_code = 400
        return response

    def admin_pair(session_id, trainee_id, number):
        training, _, trainee = services._find_session_trainee(
            services.load_data(run_background_tasks=False), session_id, trainee_id)
        if not training or not trainee or not course_for(training):
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
            questions=row['questions'], result=result, correction=True, admin_preview=True,
            notice=NOTICE, values={}, error='',
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
