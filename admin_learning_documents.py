"""Read-only individual/group printing of the existing learning evidence."""
from io import BytesIO
from pathlib import Path

from flask import abort, jsonify, request, send_file, url_for
from pypdf import PdfWriter

import uv_questionnaires as uv
from elearning_native.aps_enrolments import is_native_aps_session
from elearning_reporting import ProgressReader, certificate_pdf
from trainee_elearning_reporting import source_for


def register(host):
    app = host.app

    def context(sid):
        data = host.load_data(run_background_tasks=False)
        training = host.find_session(data, sid)
        if not training or not (is_native_aps_session(training) or uv.eligible(training)):
            abort(404)
        owner = training.get('partner_id') or host.INTEGRALE_PARTNER_ID
        unrestricted = host._is_super_admin_session() and not host.session.get('assist_partner_id')
        if not unrestricted and owner != (host._current_partner_id() or host.INTEGRALE_PARTNER_ID):
            abort(404)
        partner = host._integrale_partner() if owner == host.INTEGRALE_PARTNER_ID else next(
            (p for p in data.get('partners', []) if p.get('id') == owner), None)
        if not partner:
            abort(404)
        people = sorted((p for p in host._session_trainees_list(training)
                         if not host._trainee_registration_is_cancelled(p)),
                        key=lambda p: (str(p.get('last_name', '')).casefold(), str(p.get('first_name', '')).casefold()))
        return training, partner, people

    @app.get('/api/admin/sessions/<session_id>/learning-documents')
    @host.admin_login_required
    def admin_learning_documents(session_id):
        training, _, people = context(session_id)
        course = uv.course_for(training)
        units = [r for r in uv.bank()['courses'].get(course, {}).get('units', []) if uv.unit(course, r['number'])] if uv.eligible(training) else []
        result = dict(ok=True, require_all_uv=course == 'aps', certificates=is_native_aps_session(training),
            units=[dict(number=r['number'], title=r['title']) for r in units],
            people=[dict(id=p['id'], name=' '.join(str(p.get(k) or '') for k in ('last_name', 'first_name')),
                         submitted=[r['number'] for r in units if uv._result(p, course, r['number'])],
                         certificate_url=url_for('manuals_shop.trainee_elearning_progress_certificate',
                             session_id=session_id, trainee_id=p['id']) if is_native_aps_session(training) else '') for p in people])
        return jsonify(result), 200, {'Cache-Control': 'private, no-store'}

    @app.get('/admin/sessions/<session_id>/learning-documents/<kind>.pdf')
    @host.admin_login_required
    def admin_learning_documents_pdf(session_id, kind):
        training, partner, people = context(session_id)
        if kind not in ('attestations', 'questionnaires'):
            abort(404)
        selected = set(request.args.getlist('trainee_id'))
        if not selected or not selected <= {str(p['id']) for p in people}:
            abort(400, 'Sélectionnez au moins un stagiaire actif de cette session.')
        people = [p for p in people if str(p['id']) in selected]
        writer = PdfWriter()
        if kind == 'attestations':
            if not is_native_aps_session(training):
                abort(404)
            reader = ProgressReader(host)
            if partner['id'] == host.INTEGRALE_PARTNER_ID:
                logo = Path(app.static_folder) / 'logo-integrale.png'
            else:
                from organisme_profile import logo_path
                logo = logo_path(host, partner)
            for person in people:
                source, effective = source_for(training, person)
                report = reader.report(source, person, session_obj=effective)
                content = certificate_pdf(report, partner, source, person, logo_path=logo)
                writer.append(BytesIO(content), outline_item=f"{person.get('last_name', '')} {person.get('first_name', '')}")
        else:
            if not uv.eligible(training):
                abort(404)
            mode = request.args.get('mode', 'blank')
            if mode not in ('blank', 'answers', 'correction'):
                abort(400, 'Type de questionnaire invalide.')
            course = uv.course_for(training)
            valid = {str(r['number']) for r in uv.bank()['courses'][course]['units'] if uv.unit(course, r['number'])}
            numbers = {n for n in request.args.getlist('uv') if n} or valid
            if not numbers <= valid:
                abort(400, 'Unité de valeur invalide.')
            if len(people) * len(numbers) > 500:
                abort(400, 'Sélectionnez moins de 500 questionnaires par impression.')
            if course == 'aps' and any(not uv._result(p, course, n) for p in people for n in valid):
                abort(409, 'Impression bloquée : chaque stagiaire sélectionné doit avoir remis tous ses questionnaires de fin d’UV.')
            for person in people:
                units = []
                for number in sorted(map(int, numbers)):
                    result = uv._result(person, course, number)
                    if mode == 'answers' and not result:
                        continue
                    row = uv.unit(course, number, result['version'] if result else uv.VERSION)
                    if not row:
                        abort(409, 'L’édition d’un questionnaire est indisponible. Aucun PDF partiel n’a été produit.')
                    if course == 'aps':
                        units.append((row, result))
                        continue
                    content = uv.pdf(training, person, course, row,
                                     result=result if mode == 'answers' else None, correction=mode != 'blank')
                    writer.append(content, outline_item=f"{person.get('last_name', '')} {person.get('first_name', '')} · UV {number:02}")
                if units:
                    from uv_questionnaire_pdf import build_dossier
                    content = build_dossier(training, person, units, mode, course=course, notice=uv.NOTICE)
                    writer.append(content, outline_item=f"{person.get('last_name', '')} {person.get('first_name', '')}")
        if not writer.pages:
            abort(409, 'Aucun questionnaire remis pour cette sélection. Choisissez les questionnaires vierges pour préparer la session.')
        output = BytesIO()
        writer.write(output)
        writer.close()
        output.seek(0)
        response = send_file(output, mimetype='application/pdf', download_name=f'{kind}-{session_id}.pdf')
        response.headers['Cache-Control'] = 'private, no-store'
        return response
