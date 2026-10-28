"""Shared, reversible portrait cropping for trainee sheets and SSIAP diplomas."""
import hashlib
import hmac
import io
import json
import math
import os
import secrets
from pathlib import Path

from flask import abort, jsonify, request, send_file, session, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.datastructures import FileStorage

RATIO = 7 / 9  # Printed identity photograph: 35 x 45 mm.
MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
PHOTO_FIELDS = ('identity_photo', 'identity_photo_original', 'identity_photo_crop')


class PhotoConflict(Exception):
    pass


def revision(trainee):
    return hashlib.sha256(json.dumps({key: trainee.get(key) for key in PHOTO_FIELDS}, sort_keys=True).encode()).hexdigest()


def source_token(trainee):
    return str(trainee.get('identity_photo_original') or trainee.get('identity_photo') or '')


def decode_photo(content, max_size=None):
    try:
        with Image.open(io.BytesIO(content)) as source:
            # Smartphone HDR JPEGs are detected as MPO: frame 0 is the portrait,
            # while subsequent frames may only contain the HDR gain map.
            if source.format not in ('JPEG', 'MPO', 'PNG', 'WEBP') or source.width * source.height > 40_000_000:
                raise ValueError
            source.seek(0)
            if max_size:
                source.draft('RGB', (max_size * 2, max_size * 2))
            photo = ImageOps.exif_transpose(source).convert('RGB')
            photo.load()
            if max_size:
                photo.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            return photo
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError('Photo illisible. Utilisez un JPG, PNG ou WebP de 40 mégapixels maximum.') from exc


def load_photo(services, token, max_size=None):
    if not token or not services._partner_can_access_upload_token(token):
        abort(404)
    path = services._detokenize_path(token)
    try:
        with open(path, 'rb') as source:
            content = source.read(MAX_SOURCE_BYTES + 1)
    except OSError:
        abort(404)
    if len(content) > MAX_SOURCE_BYTES:
        raise ValueError('La photo existante dépasse 25 Mo. Remplacez-la par une image plus légère.')
    return decode_photo(content, max_size), hashlib.sha256(content).hexdigest()


def validate_crop(data, photo):
    if not isinstance(data, dict) or data.get('version') != 2:
        raise ValueError('Cadrage invalide.')
    rotation = data.get('rotation')
    if isinstance(rotation, bool) or rotation not in (0, 90, 180, 270):
        raise ValueError('Rotation invalide.')
    values = {}
    for key in ('cx', 'cy', 'width', 'height', 'straighten'):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Cadrage invalide.')
        values[key] = float(value)
    iw, ih = photo.size
    w, h = values['width'] * iw, values['height'] * ih
    if not -45 <= values['straighten'] <= 45 or w < 20 or h < 20 or abs(w / h - RATIO) > .002:
        raise ValueError('Le cadrage doit conserver le format 35 × 45 mm et une taille suffisante.')
    angle = math.radians(rotation + values['straighten'])
    half_w = (abs(math.cos(angle)) * w + abs(math.sin(angle)) * h) / 2
    half_h = (abs(math.sin(angle)) * w + abs(math.cos(angle)) * h) / 2
    cx, cy = values['cx'] * iw, values['cy'] * ih
    if cx < half_w - .01 or cx > iw - half_w + .01 or cy < half_h - .01 or cy > ih - half_h + .01:
        raise ValueError('Le cadre doit rester dans la photo.')
    return dict(version=2, rotation=rotation, **values)


def render_crop(photo, crop):
    iw, ih = photo.size
    w, h = crop['width'] * iw, crop['height'] * ih
    unit = max(3, min(100, int(h / 9)))
    out_w, out_h = unit * 7, unit * 9
    angle = math.radians(crop['rotation'] + crop['straighten'])
    a, b = math.cos(angle) * w / out_w, math.sin(angle) * h / out_h
    d, e = -math.sin(angle) * w / out_w, math.cos(angle) * h / out_h
    c = crop['cx'] * iw - a * out_w / 2 - b * out_h / 2
    f = crop['cy'] * ih - d * out_w / 2 - e * out_h / 2
    return photo.transform((out_w, out_h), Image.Transform.AFFINE, (a, b, c, d, e, f),
                           resample=Image.Resampling.BICUBIC, fillcolor='white')


def photo_metadata(services, session_id, trainee):
    token = str(trainee.get('identity_photo') or '')
    available = bool(token and os.path.isfile(services._detokenize_path(token)))
    rev = revision(trainee)
    base = url_for('admin_identity_photo', session_id=session_id, trainee_id=trainee['id'])
    return {'id': str(trainee['id']), 'revision': rev, 'photo_available': available,
            'photo_api': base, 'photo_url': base + '/image?v=' + rev if available else ''}


def register(app, services):
    def find(data, session_id, trainee_id):
        training = services.find_session(data, session_id)
        if not training:
            abort(404)
        trainees = services._session_trainees_list(training)
        trainee = next((t for t in trainees if str(t.get('id')) == trainee_id), None)
        if not trainee:
            abort(404)
        training['trainees'] = trainees
        return training, trainee

    def read(session_id, trainee_id):
        return find(services.load_data(run_background_tasks=False), session_id, trainee_id)[1]

    def csrf():
        return session.setdefault('identity_photo_csrf', secrets.token_urlsafe(32))

    def check_csrf():
        expected = session.get('identity_photo_csrf', '')
        supplied = request.headers.get('X-CSRF-Token', '')
        if not expected or not hmac.compare_digest(supplied, expected):
            abort(403)

    def respond(value, status=200):
        response = jsonify(value)
        response.status_code = status
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.get('/api/admin/sessions/<session_id>/trainees/<trainee_id>/identity-photo')
    @services.admin_login_required
    def admin_identity_photo(session_id, trainee_id):
        trainee = read(session_id, trainee_id)
        return respond(dict(ok=True, csrf=csrf(), read_only=session.get('admin_role') == 'viewer',
                            **photo_metadata(services, session_id, trainee)))

    @app.get('/api/admin/sessions/<session_id>/trainees/<trainee_id>/identity-photo/image')
    @services.admin_login_required
    def admin_identity_photo_image(session_id, trainee_id):
        trainee = read(session_id, trainee_id)
        original = request.args.get('original') == '1'
        token = source_token(trainee) if original else str(trainee.get('identity_photo') or '')
        try:
            photo, source_hash = load_photo(services, token, 2400 if original else 600)
        except ValueError as exc:
            return respond({'ok': False, 'error': str(exc)}, 400)
        output = io.BytesIO()
        photo.save(output, 'JPEG', quality=92)
        photo.close()
        output.seek(0)
        response = send_file(output, mimetype='image/jpeg')
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Photo-Source'] = source_hash
        response.headers['X-Photo-Revision'] = revision(trainee)
        crop = trainee.get('identity_photo_crop') or {}
        if original and crop.get('source_hash') == source_hash:
            response.headers['X-Photo-Crop'] = json.dumps(crop)
        return response

    def persist(session_id, trainee_id, expected, updater):
        def update(data):
            training, trainee = find(data, session_id, trainee_id)
            if expected != revision(trainee):
                raise PhotoConflict('La photo a changé depuis son ouverture. Rouvrez le recadrage avant de réessayer.')
            updater(trainee)
            trainee['updated_at'] = services._now_iso()
            training['trainees'] = services._session_trainees_list(training)
            training.pop('stagiaires', None)
            return dict(ok=True, **photo_metadata(services, session_id, trainee))
        return services._atomic_update_data(update)

    def store_photo(photo, session_id, trainee_id):
        output = io.BytesIO()
        photo.save(output, 'JPEG', quality=95)
        photo.close()
        output.seek(0)
        path = services._store_file(session_id, trainee_id, 'identity_photo', FileStorage(output, filename='portrait.jpg'))
        return path, services._tokenize_path(path)

    @app.post('/api/admin/sessions/<session_id>/trainees/<trainee_id>/identity-photo/crop')
    @services.admin_login_required
    @services.admin_write_required
    def admin_identity_photo_crop(session_id, trainee_id):
        check_csrf()
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return respond({'ok': False, 'error': 'Cadrage invalide.'}, 400)
        trainee = read(session_id, trainee_id)
        path = None
        try:
            photo, source_hash = load_photo(services, source_token(trainee))
            if data.get('source_hash') != source_hash or data.get('revision') != revision(trainee):
                photo.close()
                raise PhotoConflict('La photo a changé. Rouvrez le recadrage.')
            if data.get('reset') is True:
                photo.close()
                def updater(current):
                    current['identity_photo'] = source_token(current)
                    current.pop('identity_photo_original', None)
                    current.pop('identity_photo_crop', None)
            else:
                try:
                    crop = validate_crop(data, photo)
                    cropped = render_crop(photo, crop)
                finally:
                    photo.close()
                path, token = store_photo(cropped, session_id, trainee_id)
                def updater(current):
                    current['identity_photo_original'] = source_token(current)
                    current['identity_photo'] = token
                    current['identity_photo_crop'] = dict(crop, source_hash=source_hash)
            result = persist(session_id, trainee_id, data.get('revision'), updater)
            path = None
            return respond(result)
        except PhotoConflict as exc:
            return respond({'ok': False, 'error': str(exc)}, 409)
        except ValueError as exc:
            return respond({'ok': False, 'error': str(exc)}, 400)
        finally:
            if path:
                Path(path).unlink(missing_ok=True)

    @app.post('/api/admin/sessions/<session_id>/trainees/<trainee_id>/identity-photo/upload')
    @services.admin_login_required
    @services.admin_write_required
    def admin_identity_photo_upload(session_id, trainee_id):
        check_csrf()
        read(session_id, trainee_id)
        if request.content_length and request.content_length > MAX_UPLOAD_BYTES + 65536:
            return respond({'ok': False, 'error': 'La photo ne doit pas dépasser 10 Mo.'}, 413)
        uploaded = request.files.get('photo')
        if not uploaded or not uploaded.filename:
            return respond({'ok': False, 'error': 'Choisissez une photo JPG, PNG ou WebP.'}, 400)
        content = uploaded.stream.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            return respond({'ok': False, 'error': 'La photo ne doit pas dépasser 10 Mo.'}, 413)
        path = None
        try:
            photo = decode_photo(content)
            path, token = store_photo(photo, session_id, trainee_id)
            def updater(current):
                current['identity_photo'] = token
                current.pop('identity_photo_original', None)
                current.pop('identity_photo_crop', None)
            result = persist(session_id, trainee_id, request.form.get('revision'), updater)
            path = None
            return respond(result)
        except PhotoConflict as exc:
            return respond({'ok': False, 'error': str(exc)}, 409)
        except ValueError as exc:
            return respond({'ok': False, 'error': str(exc)}, 400)
        finally:
            if path:
                Path(path).unlink(missing_ok=True)
