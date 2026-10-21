"""Administrative follow-up of session trainees using their existing evidence.

Resolve the individual's pinned assignment, then use the same read-only report
and exports as purchased access. Viewing a report never activates learner access.
"""
from pathlib import Path

from flask import Response, abort, url_for
from werkzeug.utils import secure_filename

import elearning_orders as learning
from elearning_reporting import ProgressReader, certificate_pdf, connections_csv
from elearning_native.importer import CourseImportError
from elearning_native.paths import assigned_modules
from elearning_native.vtc_enrolments import effective_learner_session
from vtc_elearning_activation import STATE_KEY, is_vtc


def source_for(training, person):
    if not is_vtc(training):
        return None
    activation = person.get(STATE_KEY)
    if isinstance(activation, dict):
        # Administrators may inspect the assigned path before its activation.
        # Do not use the learner view, which correctly hides pending modules.
        effective = {**training, 'aps_native_modules': activation.get('modules') or []}
    else:
        effective = effective_learner_session(training, person)
    modules = assigned_modules(effective)
    if not modules:
        return None
    source = {'id': str(training['id']), 'source_kind': 'training_session',
              'course_code': 'vtc', 'group_name': training.get('name') or training.get('nom') or '',
              'modules': modules}
    return source, {**effective, 'aps_native_modules': modules}


def summary(host, training, person):
    if not is_vtc(training):
        return None
    link = url_for('manuals_shop.trainee_elearning_progress', session_id=training['id'], trainee_id=person['id'])
    try:
        resolved = source_for(training, person)
        if resolved is None:
            return None
        source, effective = resolved
        report = ProgressReader(host).report(source, person, detailed=False, session_obj=effective)
    except CourseImportError:
        return {'url': link, 'available': False}
    return {key: report[key] for key in ('available', 'progress_percent', 'active_time_label',
            'required_time_label', 'completed_modules', 'total_modules', 'status_label')} | {'url': link}


def register_routes(host, bp, *, page):
    def context(session_id, trainee_id):
        data = host.load_data()
        training = host.find_session(data, session_id)
        if not training or host._is_wedof_leads_session(training):
            abort(404)
        owner = training.get('partner_id') or host.INTEGRALE_PARTNER_ID
        unrestricted = host._is_super_admin_session() and not host.session.get('assist_partner_id')
        if not unrestricted and owner != (host._current_partner_id() or host.INTEGRALE_PARTNER_ID):
            abort(404)
        person = next((p for p in host._session_trainees_list(training) if str(p.get('id')) == trainee_id), None)
        if person is None:
            abort(404)
        try:
            resolved = source_for(training, person)
        except CourseImportError as exc:
            abort(409, str(exc))
        if resolved is None:
            abort(404)
        partner = (host._integrale_partner() if owner == host.INTEGRALE_PARTNER_ID else
                   next((p for p in data.get('partners', []) if p.get('id') == owner), None))
        if partner is None:
            abort(404)
        source, effective = resolved
        return partner, source, person, effective

    def logo(partner):
        if partner['id'] == host.INTEGRALE_PARTNER_ID:
            return Path(host.app.static_folder) / 'logo-integrale.png'
        from organisme_profile import logo_path
        return logo_path(host, partner)

    def pdf(content, filename):
        return Response(content, mimetype='application/pdf', headers={
            'Content-Disposition': f'inline; filename="{secure_filename(filename)}"'})

    base = '/admin/sessions/<session_id>/stagiaires/<trainee_id>/e-learning/suivi'

    @bp.get(base)
    @host.admin_login_required
    def trainee_elearning_progress(session_id, trainee_id):
        partner, source, person, effective = context(session_id, trainee_id)
        report = ProgressReader(host).report(source, person, session_obj=effective)
        return page('elearning_progress.html', partner=partner, order=source, person=person,
                    group=None, report=report, course=learning.COURSES[source['course_code']], staff=True,
                    back_url=url_for('admin_trainee_page', session_id=session_id, trainee_id=trainee_id) + '#vtcElearningFollowup',
                    activation_pending=bool(person.get(STATE_KEY) and not person[STATE_KEY].get('activated_at')),
                    report_link=lambda suffix='', **values: url_for('manuals_shop.trainee_elearning_progress' + suffix,
                        session_id=session_id, trainee_id=trainee_id, **values))

    @bp.get(base + '/attestation.pdf')
    @host.admin_login_required
    def trainee_elearning_progress_certificate(session_id, trainee_id):
        partner, source, person, effective = context(session_id, trainee_id)
        report = ProgressReader(host).report(source, person, session_obj=effective)
        return pdf(certificate_pdf(report, partner, source, person, logo_path=logo(partner)),
                   f"attestation-suivi-{person.get('last_name', '')}-{person.get('first_name', '')}.pdf")

    @bp.get(base + '/connexions.csv')
    @host.admin_login_required
    def trainee_elearning_progress_connections(session_id, trainee_id):
        _, source, person, effective = context(session_id, trainee_id)
        return connections_csv(ProgressReader(host).report(source, person, session_obj=effective), source['course_code'])

    @bp.get(base + '/examens/<exam_id>/<version>/<attempt_id>.pdf')
    @host.admin_login_required
    def trainee_elearning_progress_exam_copy(session_id, trainee_id, exam_id, version, attempt_id):
        from elearning_exam_pdf import exam_attempt_pdf
        partner, source, person, effective = context(session_id, trainee_id)
        attempt = ProgressReader(host).exam_attempt(source, person, exam_id, version, attempt_id, session_obj=effective)
        if attempt is None:
            abort(404)
        return pdf(exam_attempt_pdf(attempt, partner, source, person, logo_path=logo(partner)),
                   f"copie-examen-{exam_id}-{person.get('last_name', '')}-{attempt_id}.pdf")
