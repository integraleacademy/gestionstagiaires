"""Public search metadata, built from the same catalogue as the storefront.

No customer records, invented ratings, stock levels or delivery promises belong
in these graphs. Prices are TTC and quantity thresholds remain explicit.
"""
import os
from urllib.parse import urlparse

from flask import request

from manuals_catalogue import CATALOGUE


COURSE_IMAGES = {
    'aps': 'images/aps62-cover.webp',
    'mac-aps': 'images/mac-aps-cover.webp',
    'a3p': 'manuals/powerpoint-previews/a3p-scene.webp',
    'vtc': 'images/learner-welcome-vtc.webp',
}
CATEGORY_NAMES = {
    'manuels': 'Manuels de formation',
    'supports-formateurs': 'Supports PowerPoint sur clé USB',
    'e-learning': 'Parcours e-learning',
}


def public_origin():
    value = os.getenv('MANUALS_PUBLIC_URL') or os.getenv('MANUALS_BASE_URL') or os.getenv('RENDER_EXTERNAL_URL') or request.url_root
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username:
        return request.url_root.rstrip('/')
    return parsed.scheme + '://' + parsed.netloc


def indexable():
    host = request.host.split(':')[0].lower()
    configured = os.getenv('MANUALS_INDEXABLE', '').strip().lower()
    # A staging/preview host must never compete with the commercial domain.
    if '.onrender.com' in host or host in {'localhost', '127.0.0.1'} or 'test' in host or 'preview' in host:
        return False
    return configured == 'true' and host == urlparse(public_origin()).hostname


def product_name(book):
    """Keep long recycling titles readable in search results."""
    if book['code'].endswith('_recyclage'):
        return 'SSIAP ' + book['name'].split('SSIAP ')[-1] + ' recyclage / RAN'
    return book['name']


def public_metadata(origin, path, title, description, *, book=None, course=None,
                    courses=None, sales_enabled=False):
    origin = origin.rstrip('/')
    canonical = origin + path
    organization_id = origin + '/#organization'
    website_id = origin + '/#website'
    page_id = canonical + '#webpage'
    image_path = 'manuals/previews/supports-formateurs.webp'
    image_alt = 'Manuels de formation et supports formateurs Intégrale Connect'
    parts = path.strip('/').split('/') if path != '/' else []
    category = parts[0] if parts else ''
    graph = [
        {'@type': 'Organization', '@id': organization_id,
         'name': 'Intégrale Academy', 'legalName': 'Intégrale Sécurité Formations',
         'url': origin + '/', 'logo': origin + '/static/logoic.webp',
         'email': 'clement@integraleacademy.com', 'telephone': '+33422470768'},
        {'@type': 'WebSite', '@id': website_id, 'name': 'Intégrale Connect',
         'url': origin + '/', 'inLanguage': 'fr-FR',
         'publisher': {'@id': organization_id}},
    ]
    page = {'@type': 'CollectionPage' if path.strip('/') in CATEGORY_NAMES else 'WebPage',
            '@id': page_id, 'url': canonical, 'name': title,
            'description': description, 'inLanguage': 'fr-FR',
            'isPartOf': {'@id': website_id}, 'publisher': {'@id': organization_id}}
    graph.append(page)

    if parts:
        crumbs = [('Accueil', '/')]
        if category in CATEGORY_NAMES:
            crumbs.append((CATEGORY_NAMES[category], '/' + category))
            if len(parts) > 1:
                if book:
                    label = ('PowerPoint ' if category == 'supports-formateurs' else 'Manuel ') + book['name']
                else:
                    label = 'E-learning ' + course['name'] if course else title
                crumbs.append((label, path))
        else:
            crumbs.append((title, path))
        breadcrumb_id = canonical + '#breadcrumb'
        graph.append({'@type': 'BreadcrumbList', '@id': breadcrumb_id,
                      'itemListElement': [
                          {'@type': 'ListItem', 'position': number,
                           'name': name, 'item': origin + url}
                          for number, (name, url) in enumerate(crumbs, 1)]})
        page['breadcrumb'] = {'@id': breadcrumb_id}

    def offer(cents, name, minimum=1, maximum=None):
        quantity = {'@type': 'QuantitativeValue', 'minValue': minimum, 'unitCode': 'C62'}
        if maximum is not None:
            quantity['maxValue'] = maximum
        return {'@type': 'Offer', 'url': canonical, 'name': name,
                'price': f'{cents / 100:.2f}', 'priceCurrency': 'EUR',
                'eligibleQuantity': quantity, 'seller': {'@id': organization_id},
                'priceSpecification': {'@type': 'UnitPriceSpecification',
                                       'price': f'{cents / 100:.2f}',
                                       'priceCurrency': 'EUR',
                                       'valueAddedTaxIncluded': True}}

    if book and category in {'manuels', 'supports-formateurs'}:
        is_manual = category == 'manuels'
        name = ('Manuel ' if is_manual else 'PowerPoint ') + book['name']
        if is_manual:
            image_path = 'manuals/' + book['code'] + '.webp'
            image_alt = 'Couverture du manuel ' + book['name']
            offers = [offer(book['price'], 'Prix par manuel, de 50 à 99 exemplaires', 50, 99),
                      offer(book['bulk_price'], 'Prix par manuel, à partir de 100 exemplaires', 100)]
        else:
            name += ' sur clé USB'
            image_path = 'manuals/powerpoint-previews/' + book['code'] + (
                '-1.webp' if book['code'] in {'aps', 'ssiap1'} else '-scene.webp')
            image_alt = 'Aperçu pédagogique du support PowerPoint ' + book['name']
            offers = [offer(book['usb_price'], 'Prix par clé USB, livraison incluse')]
        product_id = canonical + '#product'
        graph.append({'@type': 'Product', '@id': product_id, 'name': name,
                      'url': canonical, 'description': description,
                      'image': origin + '/static/' + image_path,
                      'sku': ('manual_' if is_manual else 'usb_') + book['code'],
                      'category': book['category_name'],
                      'brand': {'@type': 'Brand', 'name': 'Intégrale Academy'},
                      'offers': offers})
        page['mainEntity'] = {'@id': product_id}
    elif course and category == 'e-learning':
        image_path = COURSE_IMAGES[course['code']]
        image_alt = 'Parcours e-learning ' + course['name']
        course_id = canonical + '#course'
        item = {'@type': 'Course', '@id': course_id,
                'name': 'E-learning ' + course['name'] + ' — ' + course['title'],
                'courseCode': course['code'], 'url': canonical,
                'description': description, 'inLanguage': 'fr-FR',
                'image': origin + '/static/' + image_path,
                'provider': {'@id': organization_id},
                'audience': {'@type': 'Audience', 'audienceType': 'Stagiaires des organismes de formation'},
                'timeRequired': f"PT{course['planned_minutes']}M"}
        if course.get('unit_cents') is not None:
            item['offers'] = offer(course['unit_cents'], 'Accès individuel au parcours, par stagiaire')
            item['offers']['availability'] = 'https://schema.org/' + ('InStock' if sales_enabled else 'OutOfStock')
        graph.append(item)
        page['mainEntity'] = {'@id': course_id}
    elif category in CATEGORY_NAMES and len(parts) == 1:
        if category == 'e-learning':
            entries = [('E-learning ' + item['name'], '/e-learning/' + code)
                       for code, item in (courses or {}).items()]
        else:
            entries = [(('Manuel ' if category == 'manuels' else 'PowerPoint ') + item['name'],
                        '/' + category + '/' + item['code'])
                       for item in CATALOGUE if category == 'manuels' or item['usb_price'] is not None]
        list_id = canonical + '#collection'
        graph.append({'@type': 'ItemList', '@id': list_id, 'numberOfItems': len(entries),
                      'itemListElement': [
                          {'@type': 'ListItem', 'position': number, 'name': name, 'url': origin + url}
                          for number, (name, url) in enumerate(entries, 1)]})
        page['mainEntity'] = {'@id': list_id}

    page['primaryImageOfPage'] = {'@type': 'ImageObject', 'url': origin + '/static/' + image_path}
    return {'image': origin + '/static/' + image_path, 'image_alt': image_alt,
            'data': {'@context': 'https://schema.org', '@graph': graph}}
