"""Admin screens for a shared SSIAP session with individual SST enrolments."""
import copy
from flask import abort, jsonify, render_template, request
import ssiap_pathways as paths


def register(app, services):
    def training_data(session_id):
        data = services.load_data(run_background_tasks=False)
        training = services.find_session(data, session_id)
        if not training or not paths.supported(training):
            abort(404)
        return data, training

    @app.get('/admin/sessions/<session_id>/parcours-ssiap')
    @services.admin_login_required
    def admin_ssiap_pathways(session_id):
        _, training = training_data(session_id)
        return render_template('admin_ssiap_pathways.html', session=training,
                               config=paths.settings(training), enabled=paths.enabled(training))

    @app.get('/admin/sessions/<session_id>/stagiaires/<trainee_id>/parcours-ssiap')
    @services.admin_login_required
    def admin_ssiap_trainee_pathway(session_id, trainee_id):
        _, training = training_data(session_id)
        trainee = next((t for t in services._session_trainees_list(training) if t.get('id') == trainee_id), None)
        if not trainee:
            abort(404)
        return render_template('admin_ssiap_trainee_pathway.html', session=training, trainee=trainee,
                               config=paths.settings(training), enabled=paths.enabled(training),
                               choice=paths.selected(trainee), pathway=paths.resolve(training, trainee))

    @app.post('/api/sessions/<session_id>/stagiaires/<trainee_id>/parcours-ssiap')
    @services.admin_login_required
    @services.admin_write_required
    def api_ssiap_trainee_pathway(session_id, trainee_id):
        payload = request.get_json(silent=True) or {}

        def update(data):
            training = services.find_session(data, session_id)
            trainee = next((t for t in services._session_trainees_list(training) if t.get('id') == trainee_id), None) if training else None
            if not trainee:
                return {'ok': False, 'error': 'Stagiaire introuvable.', 'status': 404}
            if services._trainee_registration_is_cancelled(trainee):
                return {'ok': False, 'error': 'Cette inscription est annulée.', 'status': 409}
            try:
                choice = str(payload.get('ssiap_pathway') or '')
                paths.validate_choice(training, choice)
                price = paths.number(payload.get('training_price'), 'Tarif du stagiaire', optional=True)
            except ValueError as exc:
                return {'ok': False, 'error': str(exc), 'status': 400}
            if not paths.enabled(training):
                return {'ok': False, 'error': 'Enregistrez d’abord les paramètres des parcours de la session.', 'status': 400}
            if trainee.get('ssiap_pathway') == choice and str(trainee.get('training_price') or '') == price:
                return {'ok': True}
            previous = {key: copy.deepcopy(trainee.get(key)) for key in (
                'ssiap_pathway', 'training_price', 'convocation_aps_pdf_path', 'convention_aps_pdf_path',
                'attestation_entree_aps_pdf_path', 'attestation_fin_aps_pdf_path')}
            previous['changed_at'] = services._now_iso()
            trainee.setdefault('ssiap_pathway_history', []).append(previous)
            trainee.update(ssiap_pathway=choice, training_price=price,
                           ssiap_pathway_changed_at=previous['changed_at'], updated_at=previous['changed_at'])
            services.append_trainee_history_event(trainee, 'Parcours SSIAP modifié',
                f"{paths.CHOICES[choice]} · Tarif : {price or 'à préciser'} €", 'info')
            return {'ok': True, 'label': paths.CHOICES[choice]}

        result = services._atomic_update_data(update)
        status = result.pop('status', 200)
        return jsonify(result), status

    @app.get('/admin/sessions/<session_id>/convocations-ssiap')
    @services.admin_login_required
    def admin_ssiap_convocations(session_id):
        _, training = training_data(session_id)
        rows = []
        for trainee in services._session_trainees_list(training):
            error = ''
            if services._trainee_registration_is_cancelled(trainee):
                error = 'Inscription annulée'
            elif not services._automation_is_enabled(training, trainee):
                error = 'Automatisations indisponibles'
            elif not str(trainee.get('email') or '').strip():
                error = 'Adresse e-mail manquante'
            else:
                try:
                    services._build_aps_convocation_context(training, trainee)
                except ValueError as exc:
                    error = str(exc)
            rows.append({'trainee': trainee, 'pathway': paths.resolve(training, trainee), 'error': error,
                         'already_sent': bool(trainee.get('convocation_aps_sent_at'))})
        return render_template('admin_ssiap_convocations.html', session=training, rows=rows)
