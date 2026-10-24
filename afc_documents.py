"""AFC document batches: one reserved, independently persisted operation per learner."""
import base64
import copy
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets

from flask import abort, jsonify, request, session, url_for

DOCUMENTS = {'convention', 'convocation'}
ACTIONS = {'generate', 'send'}


class DeliveryError(RuntimeError):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


def signed(services, trainee):
    return services._trainee_convention_is_signed(trainee) or trainee.get('convention_status') == 'signed'


def fingerprint(services, training, trainee, document):
    build = services._aps_convention_replacements if document == 'convention' else services._build_aps_convocation_context
    value = {'context': build(training, trainee), 'email': trainee.get('email'), 'phone': trainee.get('phone')}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def reason(services, training, trainee, document, action, *, check_operation=True):
    if training.get('archived') or services._trainee_registration_is_cancelled(trainee):
        return 'Inscription annulée ou session archivée.'
    if not services._automation_is_enabled(training, trainee):
        return 'Automatisations indisponibles.'
    operation = (trainee.get('afc_document_operations') or {}).get(document) or {}
    state = trainee.get('convention_signature') or {}
    if document == 'convention':
        if signed(services, trainee):
            return 'Convention déjà signée.'
        if state.get('signature_email_sent_at') or trainee.get('convention_auto_sent_at'):
            return 'Convention déjà envoyée.'
        if state.get('signature_request_id'):
            if action == 'generate':
                return 'Une demande de signature existe déjà.'
            if not state.get('signature_link') or state.get('status') not in {'ongoing', 'activated'}:
                return 'Demande de signature à vérifier dans la fiche stagiaire.'
    elif trainee.get('convocation_aps_sent_at'):
        return 'Convocation déjà envoyée.'
    if check_operation and operation.get('status') in {'running', 'uncertain'}:
        return 'Traitement en cours ou à vérifier dans la fiche stagiaire.'
    effective = services.afc_schedule.effective_session(training, trainee)
    if not effective.get('date_start') or not effective.get('date_end'):
        return 'Dates individuelles de formation manquantes.'
    if not trainee.get('first_name') or not trainee.get('last_name'):
        return 'Nom ou prénom manquant.'
    if action == 'send':
        if not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+', str(trainee.get('email') or '').strip()):
            return 'Adresse e-mail manquante ou invalide.'
        if document == 'convention' and not state.get('signature_request_id') and not services._normalize_yousign_sms_phone(trainee.get('phone')):
            return 'Téléphone mobile requis pour la signature.'
    return ''


def register(app, services):
    def training_or_404(data, session_id):
        training = services.find_session(data, session_id)
        if not training or not services.afc_schedule.enabled(training):
            abort(404)
        return training

    def pair(data, session_id, trainee_id):
        training = training_or_404(data, session_id)
        trainees = services._session_trainees_list(training)
        trainee = next((t for t in trainees if t.get('id') == trainee_id), None)
        if trainee is None:
            abort(404)
        training['trainees'] = trainees
        training.pop('stagiaires', None)
        return training, trainee

    @app.get('/api/admin/sessions/<session_id>/afc-documents')
    @services.admin_login_required
    @services.admin_write_required
    def admin_afc_documents_preview(session_id):
        document, action = request.args.get('document'), request.args.get('action')
        if document not in DOCUMENTS or action not in ACTIONS:
            abort(400)
        training = training_or_404(services.load_data(run_background_tasks=False), session_id)
        rows = []
        for trainee in services._session_trainees_list(training):
            blocked = reason(services, training, trainee, document, action)
            revision = ''
            if not blocked:
                try:
                    revision = fingerprint(services, training, trainee, document)
                except (ValueError, TypeError) as exc:
                    blocked = str(exc)
            preview_endpoint = 'admin_preview_convention' if document == 'convention' else 'admin_preview_aps_convocation'
            rows.append(dict(id=trainee['id'], name=' '.join(str(trainee.get(k) or '') for k in ('first_name', 'last_name')),
                             email=trainee.get('email') or '', eligible=not blocked, reason=blocked,
                             revision=revision, preview_url=url_for(preview_endpoint, session_id=session_id, trainee_id=trainee['id']),
                             execute_url=url_for('admin_afc_document_execute', session_id=session_id, trainee_id=trainee['id'])))
        response = jsonify(ok=True, rows=rows, csrf=session.setdefault('afc_documents_csrf', secrets.token_urlsafe(32)))
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.post('/api/admin/sessions/<session_id>/afc-documents/<trainee_id>')
    @services.admin_login_required
    @services.admin_write_required
    def admin_afc_document_execute(session_id, trainee_id):
        payload = request.get_json(silent=True) or {}
        expected = str(session.get('afc_documents_csrf') or '')
        if not expected or not hmac.compare_digest(str(payload.get('csrf') or ''), expected):
            abort(403)
        document, action = payload.get('document'), payload.get('action')
        request_id = str(payload.get('request_id') or '')
        if document not in DOCUMENTS or action not in ACTIONS or not re.fullmatch(r'[a-f0-9-]{32,36}', request_id):
            abort(400)

        def reserve(data):
            training, trainee = pair(data, session_id, trainee_id)
            operations = trainee.setdefault('afc_document_operations', {})
            previous = operations.get(document) or {}
            if previous.get('id') == request_id and previous.get('action') == action and previous.get('result'):
                return {'cached': previous['result']}
            blocked = reason(services, training, trainee, document, action)
            if blocked:
                return {'cached': dict(ok=True, skipped=True, message=blocked)}
            if fingerprint(services, training, trainee, document) != payload.get('revision'):
                return {'cached': dict(ok=False, message='Le dossier a changé. Rechargez la liste avant de continuer.')}
            operations[document] = dict(id=request_id, action=action, status='running', started_at=services._now_iso(),
                                        actor=str(session.get('admin_username') or 'admin'))
            return {'training': copy.deepcopy({k:v for k,v in training.items() if k not in {'trainees','stagiaires'}}),
                    'trainee': copy.deepcopy(trainee)}

        reserved = services._atomic_update_data(reserve)
        if 'cached' in reserved:
            return jsonify(reserved['cached'])
        training, trainee = reserved['training'], reserved['trainee']
        original = copy.deepcopy(trainee)
        uncertain = False

        def verify_current():
            current_training, current = pair(services.load_data(run_background_tasks=False), session_id, trainee_id)
            if services._trainee_registration_is_cancelled(current) or current_training.get('archived'):
                raise DeliveryError('Inscription annulée ou session archivée pendant le traitement.')
            if not services._automation_is_enabled(current_training, current):
                raise DeliveryError('Les automatisations ne sont plus disponibles.')
            if fingerprint(services, current_training, current, document) != payload.get('revision'):
                raise DeliveryError('Le dossier a changé pendant le traitement. Vérifiez la fiche stagiaire.')
            if document == 'convention' and signed(services, current):
                raise DeliveryError('La convention vient d’être signée. Aucun nouvel envoi effectué.')

        def persist(result=None):
            def mutate(data):
                current_training, current = pair(data, session_id, trainee_id)
                operation = (current.get('afc_document_operations') or {}).get(document) or {}
                if operation.get('id') != request_id:
                    raise RuntimeError('Le traitement a été remplacé.')
                # Merge only document fields, preserving concurrent edits and webhook signatures.
                for key, value in trainee.items():
                    if key == 'afc_document_operations' or original.get(key) == value:
                        continue
                    if key == 'sent_email_history':
                        history = current.setdefault(key, [])
                        for entry in reversed(value):
                            if not services._email_history_contains(history, entry):
                                history.insert(0, copy.deepcopy(entry))
                        current[key] = history[:200]
                    elif key == 'convention_signature':
                        target = current.setdefault(key, {})
                        already_signed = signed(services, current)
                        changes = {k:v for k,v in value.items() if (original.get(key) or {}).get(k) != v}
                        if already_signed:
                            changes = {k:v for k,v in changes.items() if k.startswith('signature_email_')}
                        target.update(copy.deepcopy(changes))
                    elif key.startswith(('convention_aps_', 'convocation_aps_', 'convocation_auto_')) or key == 'updated_at':
                        if key.startswith('convention_aps_') and signed(services, current):
                            continue
                        current[key] = copy.deepcopy(value)
                if result is not None:
                    operation.update(status='uncertain' if uncertain else 'done' if result['ok'] else 'failed',
                                     finished_at=services._now_iso(), result=result)
                return {'ok': True}
            services._atomic_update_data(mutate)

        def deliver(subject, html, *, text='', attachments=None):
            nonlocal uncertain
            verify_current()
            uncertain = True
            outcome = services.brevo_send_email(str(trainee['email']).strip(), subject, html, trainee=trainee,
                text_content=text, attachments=attachments or [], metadata={'idempotency_key': 'afc-documents-'+request_id})
            if isinstance(outcome, bool):
                outcome = {'ok': outcome, 'not_sent': not outcome}
            if not outcome.get('ok'):
                uncertain = not bool(outcome.get('not_sent') or outcome.get('status_code'))
                raise DeliveryError(outcome.get('error') or 'Le service d’envoi a refusé le message.', uncertain)
            uncertain = False

        try:
            verify_current()
            now = services._now_iso()
            if document == 'convention' and action == 'send':
                # Generation alone never creates a signature request or sends an email.
                uncertain = True
                state = services.create_yousign_convention_signature(training, trainee, session_id, trainee_id)
                uncertain = False
                persist()  # Keep the signature request even if the subsequent email fails.
                subject, html, text = services._build_yousign_signature_link_email(training, trainee, state['signature_link'])
                deliver(subject, html, text=text)
                state.update(signature_email_sent_at=services._now_iso(), signature_email_last_error='')
            else:
                generate = services._generate_aps_convention_files if document == 'convention' else services._generate_aps_convocation_files
                docx_path, pdf_path = generate(training, trainee, session_id, trainee_id)
                if document == 'convention':
                    pdf_path, _ = services._prepare_yousign_pdf_and_fields(pdf_path, signer_index=1)
                if not Path(pdf_path).is_file() or not Path(pdf_path).stat().st_size:
                    raise DeliveryError('Le PDF n’a pas pu être généré.')
                verify_current()
                prefix = document+'_aps_'
                trainee.update({prefix+'pdf_path': pdf_path, prefix+'docx_path': docx_path,
                                prefix+'generated_at': now, prefix+'status': 'generated', prefix+'last_error': ''})
                if document == 'convention':
                    services._yousign_state(trainee).update(unsigned_pdf_path=pdf_path, unsigned_docx_path=docx_path, created_at=now)
                else:
                    trainee[prefix+'pdf_token'] = services._store_public_file_token(pdf_path)
                if action == 'send':
                    if not services._aps_convocation_pdf_is_allowed(str(Path(pdf_path).resolve())):
                        raise DeliveryError('Le PDF de convocation n’est pas consultable.')
                    subject, html = services._build_aps_convocation_email(str(trainee.get('first_name') or ''),
                        training.get('date_start', ''), training.get('date_end', ''), training, trainee)
                    deliver(subject, html, attachments=[{'name': Path(pdf_path).name,
                            'content': base64.b64encode(Path(pdf_path).read_bytes()).decode('ascii')}])
                    trainee.update(convocation_aps_status='sent', convocation_aps_sent_at=services._now_iso(),
                                   convocation_aps_generated_from='word', convocation_auto_scheduled_at='', convocation_auto_last_error='')
            trainee['updated_at'] = services._now_iso()
            result = dict(ok=True, message='Envoyée' if action == 'send' else 'Générée')
        except Exception as exc:
            if isinstance(exc, DeliveryError):
                uncertain = exc.uncertain
            message = services._sanitize_yousign_error(str(exc))
            result = dict(ok=False, message=message + (' Vérifiez la fiche avant un nouvel envoi.' if uncertain else ''))
            app.logger.exception('AFC document failed document=%s action=%s trainee_id=%s', document, action, trainee_id)
        persist(result)
        return jsonify(result)
