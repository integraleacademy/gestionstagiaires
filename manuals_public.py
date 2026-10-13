"""Public commercial pages, indexing policy and shared security headers."""
import os
import hashlib
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape
from flask import Response, abort, request, session, url_for
from manuals_catalogue import CATALOGUE
from manuals_support_previews import SUPPORT_PREVIEWS
import elearning_orders

TERMS_VERSION = '2026-10-12'
# Published versions are immutable: append future versions, keep the old file.
TERMS_TEMPLATES = {TERMS_VERSION: 'manuals/legal/conditions_2026-10-12.html'}
PUBLIC_ENDPOINTS = {'manuals_shop.usb_catalogue', 'manuals_shop.usb_detail', 'manuals_shop.public_elearning', 'manuals_shop.public_course', 'manuals_shop.legal_page', 'manuals_shop.robots', 'manuals_shop.sitemap', 'manuals_shop.favicon'}
CACHEABLE = PUBLIC_ENDPOINTS | {'home', 'manuals_shop.public_presentation', 'manuals_shop.public_manual_detail'}


def public_origin():
    value = os.getenv('MANUALS_PUBLIC_URL') or os.getenv('MANUALS_BASE_URL') or os.getenv('RENDER_EXTERNAL_URL') or request.url_root
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username:
        return request.url_root.rstrip('/')
    return parsed.scheme + '://' + parsed.netloc


def indexable():
    host = request.host.split(':')[0].lower()
    configured = os.getenv('MANUALS_INDEXABLE', '').lower()
    # A staging/preview host must never compete with the commercial domain.
    if '.onrender.com' in host or host in {'localhost', '127.0.0.1'} or 'test' in host or 'preview' in host:
        return False
    return configured == 'true' and host == urlparse(public_origin()).hostname


def acceptance(host):
    if request.form.get('terms_version') != TERMS_VERSION:
        abort(400, 'Les conditions de vente ont évolué. Rechargez le récapitulatif avant de confirmer.')
    checksum = hashlib.sha256((Path(host.app.root_path) / host.app.template_folder / TERMS_TEMPLATES[TERMS_VERSION]).read_bytes()).hexdigest()
    return {'sha256': checksum, 'version': TERMS_VERSION, 'accepted_at': host._now_iso(), 'user_id': session.get('user_id'), 'url': '/conditions-de-vente?version=' + TERMS_VERSION}


def register_routes(host, bp, *, page):
    @host.app.context_processor
    def commercial_context():
        completed = ''
        if request.endpoint in {'manuals_shop.order_payment', 'manuals_shop.order_detail'} and session.get('manuals_cart_completed') == (request.view_args or {}).get('order_id'):
            session.pop('manuals_cart_completed', None)
            completed = str(session.get('partner_id', '')) + ':' + str(session.get('user_id', ''))
        return {'storefront_staff': bool(session.get('admin_logged_in') and host._is_super_admin_session()),
                'storefront_customer': bool(session.get('admin_logged_in') and host._is_external_partner_session()),
                'cart_completed_key':completed, 'terms_version': TERMS_VERSION, 'canonical_url': public_origin() + request.path,
                'public_origin': public_origin(), 'page_indexable': indexable() and request.endpoint in CACHEABLE}

    @host.app.after_request
    def storefront_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        if request.is_secure or request.host.endswith('.onrender.com'):
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000')
        if request.endpoint in CACHEABLE or request.endpoint == 'admin_login':
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; media-src 'self'; frame-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'self'; form-action 'self'"
            response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        elif request.endpoint and request.endpoint.startswith('manuals_shop.'):
            response.headers.setdefault('Content-Security-Policy', "base-uri 'self'; object-src 'none'; frame-ancestors 'self'; form-action 'self' https://pay.qonto.com https://pay-sandbox.qonto.com")
        if not indexable() or request.endpoint not in CACHEABLE:
            response.headers['X-Robots-Tag'] = 'noindex, nofollow' if not indexable() else 'noindex, follow'
        if request.endpoint in CACHEABLE and request.method in {'GET','HEAD'} and response.status_code == 200:
            response.headers['Cache-Control'] = 'private, max-age=120' if not session.get('admin_logged_in') else 'no-store'
            response.vary.add('Cookie')
        return response

    @bp.get('/supports-formateurs')
    def usb_catalogue():
        return page('usb.html', public=True, staff=False, books=[b for b in CATALOGUE if b['usb_price'] is not None], book=None, support_previews=SUPPORT_PREVIEWS)

    @bp.get('/supports-formateurs/<code>')
    def usb_detail(code):
        book = next((b for b in CATALOGUE if b['code'] == code and b['usb_price'] is not None), None)
        if not book:
            abort(404)
        return page('usb.html', public=True, staff=False, books=CATALOGUE, book=book, support_previews=SUPPORT_PREVIEWS)

    @bp.get('/e-learning')
    def public_elearning():
        return page('learning_public.html', public=True, staff=False, courses=elearning_orders.prices({}), course=None)

    @bp.get('/e-learning/<code>')
    def public_course(code):
        courses = elearning_orders.prices({})
        if code not in courses:
            abort(404)
        return page('learning_public.html', public=True, staff=False, courses=courses, course=courses[code], modules=elearning_orders.curriculum(code))

    @bp.get('/mentions-legales')
    @bp.get('/confidentialite')
    @bp.get('/conditions-de-vente')
    @bp.get('/personnalisation-livraison')
    def legal_page():
        version = request.args.get('version') or TERMS_VERSION
        if version not in TERMS_TEMPLATES:
            abort(404)
        slug = request.path.strip('/')
        return page('legal.html', public=True, staff=False, slug=slug, terms_template=TERMS_TEMPLATES[version])

    @bp.get('/robots.txt')
    def robots():
        text = 'User-agent: *\n'
        if indexable():
            text += 'Allow: /\nDisallow: /admin/\nDisallow: /api/\nDisallow: /reinitialiser-mot-de-passe/\nSitemap: ' + public_origin() + '/sitemap.xml\n'
        else:
            text += 'Disallow: /\n'
        return Response(text, mimetype='text/plain')

    @bp.get('/sitemap.xml')
    def sitemap():
        paths = ['/', '/manuels', '/supports-formateurs', '/e-learning', '/personnalisation-livraison', '/mentions-legales', '/confidentialite', '/conditions-de-vente']
        paths += ['/manuels/' + b['code'] for b in CATALOGUE]
        paths += ['/supports-formateurs/' + b['code'] for b in CATALOGUE if b['usb_price']]
        paths += ['/e-learning/' + code for code in elearning_orders.COURSES]
        xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        xml += ''.join('<url><loc>' + escape(public_origin() + path) + '</loc></url>' for path in paths)
        return Response(xml + '</urlset>', mimetype='application/xml')

    @bp.get('/favicon.ico')
    def favicon():
        from flask import send_from_directory
        return send_from_directory(host.app.static_folder, 'favicon.ico')
