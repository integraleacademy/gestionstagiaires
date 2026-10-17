"""Single-use, expiring partner password recovery without storing plaintext tokens."""
import hashlib
import hmac
import threading
from concurrent.futures import ThreadPoolExecutor
from flask import abort, flash, redirect, request, session, url_for
from itsdangerous import URLSafeTimedSerializer, BadSignature

_MAIL_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='account-recovery')
_MAIL_SLOTS = threading.BoundedSemaphore(16)

PUBLIC_ENDPOINTS = {'manuals_shop.forgot_password', 'manuals_shop.reset_password'}


def register_routes(host, bp, *, page, check_csrf, base_url):
    def signer():
        return URLSafeTimedSerializer(host.app.secret_key, salt='manuals-password-recovery-v1')

    def fingerprint(user):
        return hmac.new(str(host.app.secret_key).encode(), str(user.get('password_hash', '')).encode(), hashlib.sha256).hexdigest()

    def eligible(auth, user):
        return bool(user and user.get('active', True) and user.get('password_hash') and
                    any(p.get('id') == user.get('partner_id') and p.get('status') in {'active', 'trial'} for p in auth.get('partners', [])))

    @bp.route('/mot-de-passe-oublie', methods=['GET', 'POST'])
    def forgot_password():
        sent = False
        if request.method == 'POST':
            check_csrf()
            email = (request.form.get('email') or '').strip().lower()[:254]
            # Same status/body for missing, disabled and throttled accounts.
            limited = host._partner_login_is_rate_limited('password-reset:' + email)
            sent = True
            if not limited:
                auth = host._load_partner_auth_data()
                user = host._find_user_by_email(auth, email)
                if eligible(auth, user):
                    token = signer().dumps({'uid': user['id'], 'pid': user['partner_id'], 'version': fingerprint(user)})
                    reset_url = base_url(host) + url_for('manuals_shop.reset_password', token=token)
                    from flask import render_template
                    html = render_template('manuals/reset_email.html', reset_url=reset_url, user=user, email_base_url=base_url(host))
                    def deliver():
                        try:
                            host.brevo_send_email(email, 'Réinitialiser votre mot de passe Intégrale Connect', html,
                                text_content='Un changement de mot de passe a été demandé. Ce lien est valable 30 minutes et une seule fois : ' + reset_url + '\nSi vous n’êtes pas à l’origine de cette demande, ignorez ce message.',
                                metadata={'partner_id': user['partner_id'], 'purpose': 'password_recovery'})
                        except Exception:
                            host.app.logger.warning('password_recovery_delivery_failed')
                        finally:
                            _MAIL_SLOTS.release()
                    # Deliver after returning control, so a network send cannot
                    # disclose whether an e-mail exists through response timing.
                    if _MAIL_SLOTS.acquire(blocking=False):
                        try:
                            _MAIL_POOL.submit(deliver)
                        except RuntimeError:
                            _MAIL_SLOTS.release()
        return page('password_recovery.html', public=True, sent=sent, reset=False, errors=[])

    @bp.route('/reinitialiser-mot-de-passe/<token>', methods=['GET', 'POST'])
    def reset_password(token):
        errors = []
        try:
            payload = signer().loads(token, max_age=1800)
            auth = host._load_partner_auth_data()
            user = next((u for u in auth.get('users', []) if u.get('id') == payload.get('uid') and u.get('partner_id') == payload.get('pid')), None)
            if not eligible(auth, user) or not hmac.compare_digest(fingerprint(user), str(payload.get('version', ''))):
                raise ValueError
        except (BadSignature, ValueError, TypeError, KeyError):
            return page('password_recovery.html', public=True, invalid=True, reset=False, sent=False, errors=[]), 400
        if request.method == 'POST':
            check_csrf()
            if host._partner_login_is_rate_limited('password-change:' + user['id']):
                return page('password_recovery.html', public=True, reset=True, errors=['Trop de tentatives. Réessayez dans quelques minutes.']), 429
            password = request.form.get('password', '')
            if not 12 <= len(password) <= 128:
                errors.append('Choisissez un mot de passe de 12 à 128 caractères.')
            if password != request.form.get('password_confirmation'):
                errors.append('Les mots de passe doivent être identiques.')
            if not errors:
                password_hash = host._hash_password(password)
                def change(data):
                    current = next((u for u in data.get('users', []) if u.get('id') == user['id'] and u.get('partner_id') == user['partner_id']), None)
                    if not eligible(data, current) or not hmac.compare_digest(fingerprint(current), payload['version']):
                        abort(400, 'Ce lien a déjà été utilisé ou a expiré.')
                    current.update(password_hash=password_hash, password_changed_at=host._now_iso(), updated_at=host._now_iso())
                    host._append_activity_log(data, 'password_reset', 'user', current['id'], current['partner_id'])
                    return {}
                # Recovery authority comes from the verified token, not from an
                # unrelated tenant session that may still be open in this browser.
                session.clear()
                host._atomic_update_data(change, partner_id=user['partner_id'])
                flash('Votre mot de passe a été modifié. Vous pouvez vous connecter.', 'success')
                return redirect(url_for('admin_login', next=url_for('manuals_shop.home'), password_reset='1'), code=303)
        return page('password_recovery.html', public=True, reset=True, errors=errors), (400 if errors else 200)
