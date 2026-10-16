"""Tenant-scoped logo/BAT approval and shipping workflow, separate from payments."""
import datetime as dt
import hashlib
import io
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse
from flask import abort, flash, redirect, render_template, request, send_file, session, url_for
from pypdf import PdfReader

CUSTOMER_ENDPOINTS = {'manuals_shop.upload_order_logo', 'manuals_shop.order_bat', 'manuals_shop.approve_bat', 'manuals_shop.reorder'}


def validate_status(order, status):
    if status in {'production', 'shipped'} and order.get('terms_acceptance') and any(i['kind'] == 'manual' for i in order.get('items', [])):
        if order.get('fulfillment', {}).get('bat', {}).get('status') != 'approved':
            abort(400, 'Un bon à tirer validé par le client est nécessaire avant l’impression ou l’expédition.')
    if status in {'production', 'shipped'} and order.get('commerce', {}).get('payment_status') != 'paid':
        abort(400, 'Le règlement doit être confirmé avant la préparation ou l’expédition.')


def register_routes(host, bp, *, page, customer, partner_data, check_csrf, find_order, save_logo, quote_items, base_url):
    def notify(partner_id, order_id, event_id):
        """Claim before sending; retries are explicit, never repeat an uncertain send."""
        def claim(data):
            order = find_order(data, order_id)
            events = order.get('fulfillment', {}).get('events', [])
            event = next((e for e in events if e['id'] == event_id), None)
            if not event or event.get('email_status') in {'sent', 'sending'}:
                return {}
            event['email_status'] = 'sending'
            return {'email': order['centre']['email'], 'reference': order.get('reference', order_id), 'message': event['message']}
        message = host._atomic_update_data(claim, partner_id=partner_id)
        if not message:
            return
        link = base_url(host) + url_for('manuals_shop.order_detail', order_id=order_id)
        try:
            result = host.brevo_send_email(message['email'], 'Suivi de votre commande ' + message['reference'],
                render_template('manuals/fulfillment_email.html', message=message, order_url=link),
                text_content=message['message'] + '\nConsulter votre commande : ' + link,
                metadata={'partner_id': partner_id, 'purpose': 'manuals_fulfillment', 'event_id': event_id})
            status = 'sent' if result.get('ok') else 'failed'
        except Exception:
            # A timeout may occur after delivery. Leave it for manual inspection.
            status = 'uncertain'
            host.app.logger.warning('manuals_fulfillment_email_uncertain order_id=%s', order_id)
        def record(data):
            order = find_order(data, order_id)
            event = next(e for e in order['fulfillment']['events'] if e['id'] == event_id)
            event['email_status'] = status
            return {}
        host._atomic_update_data(record, partner_id=partner_id)

    def add_event(order, message, email=False):
        event = {'id': str(uuid.uuid4()), 'at': host._now_iso(), 'message': message, 'user_id': session.get('user_id') or session.get('admin_username'), 'email_status': 'pending' if email else 'none'}
        order.setdefault('fulfillment', {}).setdefault('events', []).append(event)
        return event['id']

    def storage(partner_id):
        root = Path(host.get_partner_storage_path(partner_id, 'documents')) / 'manuals-bat'
        root.mkdir(parents=True, exist_ok=True)
        return root

    @bp.post('/admin/manuels/commandes/<order_id>/transmettre-logo')
    @customer
    def upload_order_logo(order_id):
        check_csrf()
        data, partner = partner_data()
        order = find_order(data, order_id)
        if order['status'] in {'draft', 'production', 'shipped', 'cancelled'} or order.get('personalization') == 'none':
            abort(409, 'Le logo ne peut plus être modifié à ce stade. Contactez notre équipe.')
        try:
            name = save_logo(host, request.files.get('logo'), partner['id'], str(uuid.uuid4()))
            if not name:
                raise ValueError('Choisissez un fichier logo.')
        except ValueError as exc:
            flash(str(exc), 'error')
            return redirect(url_for('manuals_shop.order_detail', order_id=order_id), code=303)
        def save(data):
            current = find_order(data, order_id)
            if current['status'] in {'production', 'shipped', 'cancelled'}:
                abort(409)
            current.update(logo_filename=name, personalization='upload')
            bat = current.get('fulfillment', {}).get('bat')
            if bat:
                bat['status'] = 'superseded'
            add_event(current, 'Logo reçu. Notre équipe prépare votre personnalisation.')
            return {}
        try:
            host._atomic_update_data(save, partner_id=partner['id'])
        except Exception:
            (Path(host.get_partner_storage_path(partner['id'], 'logos')) / name).unlink(missing_ok=True)
            raise
        flash('Votre logo a été transmis. Une nouvelle validation du BAT sera nécessaire.', 'success')
        return redirect(url_for('manuals_shop.order_detail', order_id=order_id), code=303)

    @bp.get('/admin/manuels/commandes/<order_id>/bon-a-tirer')
    @host.admin_login_required
    def order_bat(order_id):
        order = find_order(host.load_data(), order_id)
        bat = order.get('fulfillment', {}).get('bat', {})
        name = bat.get('filename', '')
        if not re.fullmatch(r'[a-f0-9-]{36}\.pdf', name):
            abort(404)
        path = storage(order['partner_id']) / name
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype='application/pdf', as_attachment=True, download_name='BAT-' + order.get('reference', order_id) + '-v' + str(bat['version']) + '.pdf')

    @bp.post('/admin/manuels/commandes/<order_id>/bon-a-tirer/decision')
    @customer
    def approve_bat(order_id):
        check_csrf()
        _, partner = partner_data()
        decision = request.form.get('decision')
        note = request.form.get('note', '').strip()
        if decision not in {'approve', 'correct'} or len(note) > 2000 or (decision == 'correct' and not note):
            abort(400, 'Indiquez les corrections souhaitées (2 000 caractères maximum).')
        if decision == 'approve' and request.form.get('confirm_bat') != 'yes':
            abort(400, 'Confirmez avoir vérifié le bon à tirer.')
        def save(data):
            order = find_order(data, order_id)
            bat = order.get('fulfillment', {}).get('bat', {})
            if order['status'] in {'production', 'shipped', 'cancelled'} or str(bat.get('version')) != request.form.get('bat_version') or bat.get('status') != 'pending':
                abort(409, 'Ce BAT n’attend plus de validation. Rechargez la commande.')
            bat.update(status='approved' if decision == 'approve' else 'correction_requested', decided_at=host._now_iso(), decided_by=session.get('user_id'), note=note)
            add_event(order, 'BAT version ' + str(bat['version']) + (' validé.' if decision == 'approve' else ' : corrections demandées.'))
            host._append_activity_log(data, 'manual_bat_' + decision, 'manual_order', order_id, partner['id'], {'version': bat['version'], 'sha256': bat['sha256']})
            return {}
        host._atomic_update_data(save, partner_id=partner['id'])
        flash('Votre décision a été enregistrée.', 'success')
        return redirect(url_for('manuals_shop.order_detail', order_id=order_id), code=303)

    @bp.post('/admin/commandes-manuels/<partner_id>/<order_id>/suivi')
    @host.admin_login_required
    @host.require_super_admin
    def update_fulfillment(partner_id, order_id):
        if host._is_partner_data_scope_session():
            abort(403)
        check_csrf()
        action = request.form.get('action')
        data = host.load_data()
        order = find_order(data, order_id)
        if order['partner_id'] != partner_id or order['status'] == 'draft':
            abort(404)
        if action == 'retry_email':
            event_id = request.form.get('event_id')
            event = next((e for e in order.get('fulfillment', {}).get('events', []) if e['id'] == event_id), None)
            if not event or event.get('email_status') != 'failed':
                abort(409)
            notify(partner_id, order_id, event_id)
            return redirect(url_for('manuals_shop.admin_order', partner_id=partner_id, order_id=order_id), code=303)
        bat_update = None
        new_path = None
        if action == 'upload_bat':
            if order.get('personalization') == 'none' or not order.get('logo_filename') or order['status'] in {'production','shipped','cancelled'}:
                abort(409, 'Recevez le logo avant de préparer le BAT, et avant le début de l’impression.')
            upload = request.files.get('bat')
            raw = upload.stream.read(10 * 1024 * 1024 + 1) if upload else b''
            if not raw.startswith(b'%PDF-') or len(raw) > 10 * 1024 * 1024:
                abort(400, 'Choisissez un PDF de 10 Mo maximum.')
            try:
                reader = PdfReader(io.BytesIO(raw))
                if reader.is_encrypted or not 1 <= len(reader.pages) <= 100:
                    raise ValueError
            except Exception:
                abort(400, 'Ce PDF ne peut pas être lu (100 pages maximum, sans mot de passe).')
            name = str(uuid.uuid4()) + '.pdf'
            new_path = storage(partner_id) / name
            new_path.write_bytes(raw)
            bat_update = {'filename': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'uploaded_at': host._now_iso(), 'status': 'pending', 'logo_filename': order['logo_filename']}
        elif action != 'shipping':
            abort(400)
        tracking = request.form.get('tracking_number', '').strip()
        tracking_url = request.form.get('tracking_url', '').strip()
        carrier = request.form.get('carrier', '').strip()
        expected = request.form.get('expected_dispatch', '').strip()
        if action == 'shipping':
            if max(len(tracking),len(carrier)) > 120 or len(tracking_url) > 1000:
                abort(400)
            parsed = urlparse(tracking_url)
            if tracking_url and (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password):
                abort(400, 'Le lien de suivi doit être une adresse HTTPS.')
            if expected:
                try:
                    dt.date.fromisoformat(expected)
                except ValueError:
                    abort(400, 'Date invalide.')
        def update(data):
            current = find_order(data, order_id)
            if current['partner_id'] != partner_id or current['status'] in {'draft','cancelled'}:
                abort(409)
            state = current.setdefault('fulfillment', {})
            if action == 'upload_bat':
                if current['status'] in {'production','shipped'} or current.get('logo_filename') != bat_update['logo_filename']:
                    abort(409)
                previous = state.get('bat')
                if previous:
                    state.setdefault('bat_history', []).append(dict(previous))
                state['bat'] = {**bat_update, 'version': (previous or {}).get('version', 0) + 1}
                message = 'Votre bon à tirer est disponible. Consultez-le et validez-le depuis votre commande.'
            else:
                status = request.form.get('status') or current['status']
                if status not in {'received','confirmed','production','shipped'}:
                    abort(400)
                validate_status(current, status)
                current['status'] = status
                state.update(tracking_number=tracking, tracking_url=tracking_url, carrier=carrier, expected_dispatch=expected)
                message = 'Votre commande a été expédiée.' if status == 'shipped' else 'Le suivi de préparation de votre commande a été mis à jour.'
                if expected:
                    message += ' Expédition prévue le ' + dt.date.fromisoformat(expected).strftime('%d/%m/%Y') + '.'
            event_id = add_event(current, message, email=request.form.get('notify') == 'yes')
            host._append_activity_log(data, 'manual_fulfillment_updated', 'manual_order', order_id, partner_id, {'action': action})
            return {'event_id':event_id}
        try:
            result = host._atomic_update_data(update, partner_id=partner_id)
        except Exception:
            if new_path:
                new_path.unlink(missing_ok=True)
            raise
        if request.form.get('notify') == 'yes':
            notify(partner_id, order_id, result['event_id'])
        flash('Le suivi a été enregistré.', 'success')
        return redirect(url_for('manuals_shop.admin_order', partner_id=partner_id, order_id=order_id), code=303)

    @bp.post('/admin/manuels/commandes/<order_id>/recommander')
    @customer
    def reorder(order_id):
        check_csrf()
        data, partner = partner_data()
        previous = find_order(data, order_id)
        if previous['status'] == 'draft':
            abort(400)
        selection = {f"{line['kind']}_{line['code']}": str(line['quantity']) for line in previous['items']}
        try:
            lines = quote_items(selection)
        except ValueError:
            flash('Certaines références ont changé. Choisissez vos supports dans le catalogue.', 'warning')
            return redirect(url_for('manuals_shop.catalogue'), code=303)
        draft_id = str(uuid.uuid4())
        import copy
        draft = {k:copy.deepcopy(previous.get(k)) for k in ('delivery','billing','personalization','notes','centre')}
        draft.update(id=draft_id, partner_id=partner['id'], created_by=session.get('user_id'), created_at=host._now_iso(), status='draft', items=lines, total_cents=sum(line['total_cents'] for line in lines), shipping_cents=0, tariff_version='2026', session_date='', logo_filename='')
        draft['centre'] = {k:partner.get(k,'') for k in ('name','siret','email','contact_first_name','contact_last_name')}
        name = previous.get('logo_filename','')
        copied = None
        if re.fullmatch(r'manuals-[a-f0-9-]{36}\.png', name):
            root = Path(host.get_partner_storage_path(partner['id'],'logos'))
            if (root / name).is_file():
                draft['logo_filename'] = 'manuals-' + str(uuid.uuid4()) + '.png'
                copied = root / draft['logo_filename']
                copied.write_bytes((root / name).read_bytes())
        if draft['personalization'] == 'upload' and not draft['logo_filename']:
            draft['personalization'] = 'later'
        def create(data):
            orders = data.setdefault('manual_orders', [])
            if sum(1 for o in orders if o.get('partner_id') == partner['id'] and o.get('status') == 'draft') >= 30:
                abort(429, 'Reprenez un brouillon existant avant d’en créer un autre.')
            orders.append(draft)
            return {}
        try:
            host._atomic_update_data(create, partner_id=partner['id'])
        except Exception:
            if copied:
                copied.unlink(missing_ok=True)
            raise
        flash('Sélection reprise aux tarifs actuels. Vérifiez les quantités et les coordonnées.', 'success')
        return redirect(url_for('manuals_shop.catalogue', draft=draft_id), code=303)
