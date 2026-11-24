"""Admin screens for a shared SSIAP session with individual SST enrolments."""
import copy
import datetime as dt
from zoneinfo import ZoneInfo
from flask import abort, jsonify, render_template, request
import ssiap_pathways as paths


def set_enrolment(services, training, trainee, payload):
    choice = str(payload.get("ssiap_pathway") or "")
    paths.validate_choice(training, choice)
    if not paths.enabled(training) and not paths.level_one(training):
        raise ValueError("Enregistrez d’abord les paramètres des parcours de la session.")
    current_choice = paths.selected(trainee)
    default = paths.settings(training)[choice + "_price"]
    if choice == current_choice:
        default = trainee.get("training_price") if trainee.get("training_price") not in ("", None) else default
    price = paths.number(payload.get("training_price", default), "Tarif du stagiaire", optional=True)
    if choice in paths.MAINTENANCE and not price:
        price = paths.MAINTENANCE[choice]["price"]
    diploma = str(payload.get("ssiap_original_diploma", trainee.get("ssiap_original_diploma") or "")).strip()
    if len(diploma) > 100:
        raise ValueError("Le numéro de diplôme doit tenir sur 100 caractères.")
    if current_choice == choice and str(trainee.get("training_price", "")) == price and diploma == (trainee.get("ssiap_original_diploma") or ""):
        return
    previous = {key: copy.deepcopy(trainee.get(key)) for key in (
        "ssiap_pathway", "training_price", "convocation_aps_pdf_path", "convention_aps_pdf_path",
        "attestation_entree_aps_pdf_path", "attestation_fin_aps_pdf_path", "ssiap_attendance", "ssiap_original_diploma")}
    previous["changed_at"] = services._now_iso()
    trainee.setdefault("ssiap_pathway_history", []).append(previous)
    if current_choice != choice:
        trainee.pop("ssiap_attendance", None)
        by_key = {d.get("key"): d for d in trainee.get("documents", []) if isinstance(d, dict)}
        required = {d["key"] for d in services.required_docs_for_training("SSIAP", {**trainee, "ssiap_pathway": choice})}
        previous["documents"] = [copy.deepcopy(d) for k, d in by_key.items() if k not in required]
        for event in reversed(trainee["ssiap_pathway_history"]):
            for doc in event.get("documents", []):
                if doc.get("key") in required:
                    by_key.setdefault(doc["key"], copy.deepcopy(doc))
        trainee["documents"] = list(by_key.values())
    trainee.update(ssiap_pathway=choice, training_price=price, ssiap_original_diploma=diploma,
                   ssiap_pathway_changed_at=previous["changed_at"], updated_at=previous["changed_at"])
    services.ensure_documents_schema_for_trainee(trainee, training.get("training_type") or training.get("type_formation") or "SSIAP")
    services.append_trainee_history_event(trainee, "Parcours SSIAP modifié",
        f"{paths.CHOICES[choice]} · Tarif : {price or 'à préciser'} €", "info")


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
                               config=paths.settings(training), enabled=paths.enabled(training),
                               maintenance=paths.MAINTENANCE if paths.level_one(training) else {})

    @app.get('/admin/sessions/<session_id>/stagiaires/<trainee_id>/parcours-ssiap')
    @services.admin_login_required
    def admin_ssiap_trainee_pathway(session_id, trainee_id):
        _, training = training_data(session_id)
        trainee = next((t for t in services._session_trainees_list(training) if t.get('id') == trainee_id), None)
        if not trainee:
            abort(404)
        return render_template('admin_ssiap_trainee_pathway.html', session=training, trainee=trainee,
                               config=paths.settings(training), enabled=paths.enabled(training),
                               choice=paths.selected(trainee), pathway=paths.resolve(training, trainee),
                               options=paths.choice_options(training, trainee), level_one=paths.level_one(training))

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
                set_enrolment(services, training, trainee, payload)
            except ValueError as exc:
                return {'ok': False, 'error': str(exc), 'status': 400}
            return {'ok': True, 'label': paths.CHOICES[paths.selected(trainee)]}

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
        return render_template('admin_ssiap_convocations.html', session=training, rows=rows, options=paths.choice_options(training))

    @app.get('/admin/sessions/<session_id>/presences-ssiap')
    @services.admin_login_required
    def admin_ssiap_attendance(session_id):
        _, training = training_data(session_id)
        if not paths.level_one(training):
            abort(404)
        today = dt.datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
        config = paths.settings(training)
        start, end = paths.group_period(training)
        days = set(config["sst_dates"])
        for key in paths.MAINTENANCE:
            days.update(config[key + "_dates"])
        if start and end:
            first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
            days.update(day.isoformat() for i in range((last-first).days + 1)
                        if (day := first + dt.timedelta(days=i)).weekday() < 5)
        days = sorted(days)
        selected = request.args.get("jour") or next((d for d in days if d >= today), days[-1] if days else "")
        if selected and selected not in days:
            abort(400)
        rows = []
        for trainee in services._registered_trainees(training):
            key = paths.selected(trainee)
            if paths.expected_on(training, trainee, selected):
                rows.append({"trainee": trainee, "label": paths.CHOICES[key],
                             "status": (trainee.get("ssiap_attendance") or {}).get(selected, "")})
        return render_template("admin_ssiap_attendance.html", session=training, days=days, day=selected,
                               rows=rows, today=today)

    @app.post('/api/sessions/<session_id>/stagiaires/<trainee_id>/presence-ssiap')
    @services.admin_login_required
    @services.admin_write_required
    def api_ssiap_attendance(session_id, trainee_id):
        payload = request.get_json(silent=True) or {}
        day, status = payload.get("day"), payload.get("status")
        def update(data):
            training = services.find_session(data, session_id)
            trainee = next((t for t in services._session_trainees_list(training) if t.get("id") == trainee_id), None) if training else None
            if not trainee or not paths.level_one(training) or services._trainee_registration_is_cancelled(trainee):
                return {"ok": False, "error": "Inscription indisponible."}
            if not paths.expected_on(training, trainee, day) or day > dt.datetime.now(ZoneInfo("Europe/Paris")).date().isoformat():
                return {"ok": False, "error": "Cette journée ne peut pas être émargée."}
            labels = {"present":"Présence complète vérifiée", "absent":"Absent", "partial":"Présence partielle"}
            if status not in labels:
                return {"ok": False, "error": "Choisissez un état de présence."}
            if trainee.setdefault("ssiap_attendance", {}).get(day) != status:
                trainee["ssiap_attendance"][day] = status
                services.append_trainee_history_event(trainee, "Présence SSIAP", f"{services.fr_date(day)} · {labels[status]}", "info")
            return {"ok": True}
        result = services._atomic_update_data(update)
        return jsonify(result), 200 if result.get("ok") else 400
