"""Make issued A3P module attestations available to their authenticated learner."""
from pathlib import Path

from flask import abort, redirect, request, send_file, url_for

KINDS = {'conducteur': "Attestation de conducteur d’autorité", 'stu': "Attestation de secourisme tactique d’urgence (STU)"}


def record(trainee, kind):
    value = trainee.get('a3p_driver_attestation') or {}
    if not isinstance(value, dict):
        return {}
    return (value.get('stu') or {}) if kind == 'stu' else value


def existing_pdf(services, trainee, kind):
    value = record(trainee, kind)
    path = str(value.get('pdf_path') or '') if isinstance(value, dict) else ''
    if not path:
        return None
    candidate = Path(path).resolve()
    root = Path(services.APS_END_ATTESTATION_DIR).resolve()
    return candidate if candidate.is_relative_to(root) and candidate.is_file() and candidate.stat().st_size else None


def released(services, trainee):
    # Older completed dossiers may predate the two complementary documents.
    return bool(trainee.get('attestation_fin_aps_sent_at') or trainee.get('attestation_fin_aps_pdf_token')
                or (trainee.get('deliverables') or {}).get('attestation_fin_formation'))


def view(services, training, trainee, token):
    if not services._a3p_has_driver_attestation(training) or services._trainee_registration_is_cancelled(trainee):
        return []
    return [dict(kind=kind, label=label, available=bool(existing_pdf(services, trainee, kind) or released(services, trainee)),
                 url=url_for('public_a3p_attestation', token=token, kind=kind)) for kind, label in KINDS.items()]


def register(app, services):
    @app.get('/espace/<token>/attestations-a3p/<kind>.pdf')
    def public_a3p_attestation(token, kind):
        if not services._public_is_authed(token):
            return redirect(url_for('public_trainee_login', token=token))

        def pair(data):
            training, trainee = services.find_session_and_trainee_by_token(data, token)
            if kind not in KINDS or not training or not trainee or not services._a3p_has_driver_attestation(training):
                abort(404)
            if services._trainee_registration_is_cancelled(trainee):
                abort(403)
            return training, trainee

        training, trainee = pair(services.load_data(run_background_tasks=False))
        path = existing_pdf(services, trainee, kind)
        if not path:
            if not released(services, trainee):
                abort(404)
            generate = services._generate_a3p_stu_attestation_files if kind == 'stu' else services._generate_a3p_driver_attestation_files
            docx, pdf = generate(training, trainee, training['id'], trainee['id'])
            def persist(data):
                _, current = pair(data)
                if not released(services, current):
                    abort(409)
                root = current.setdefault('a3p_driver_attestation', {})
                target = root.setdefault('stu', {}) if kind == 'stu' else root
                target.update(docx_path=docx, pdf_path=pdf, generated_at=services._now_iso())
                return existing_pdf(services, current, kind)
            path = services._atomic_update_data(persist)
            if not path:
                abort(404)
        response = send_file(path, mimetype='application/pdf', as_attachment=request.args.get('download') == '1',
                             download_name=f'attestation-{kind}-a3p-{trainee["id"]}.pdf')
        response.headers['Cache-Control'] = 'private, no-store'
        return response
