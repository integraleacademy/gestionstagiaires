"""Search publication must not expose staging, or misrepresent sale terms."""
import json

import pytest
from flask import Flask

from manuals_catalogue import CATALOGUE
from manuals_seo import indexable, public_metadata, public_origin


ORIGIN = 'https://www.integraleconnect.com'


@pytest.fixture
def published(monkeypatch):
    monkeypatch.setenv('MANUALS_PUBLIC_URL', ORIGIN)
    monkeypatch.setenv('MANUALS_INDEXABLE', 'true')
    return Flask(__name__)


def test_only_explicitly_published_domain_is_indexable(published, monkeypatch):
    for host in ('www.integraleconnect.com', 'integraleconnect.com',
                 'gestionstagiaires-r5no.onrender.com', 'gestionstagiaires-test-v2.onrender.com',
                 'preview.integraleconnect.com', 'localhost', 'unrelated.example'):
        with published.test_request_context('/', base_url='https://' + host):
            assert indexable() is (host == 'www.integraleconnect.com')
            assert public_origin() == ORIGIN
    monkeypatch.setenv('MANUALS_INDEXABLE', 'false')
    with published.test_request_context('/', base_url=ORIGIN):
        assert not indexable()


def test_missing_publication_switch_stays_private(monkeypatch):
    monkeypatch.delenv('MANUALS_INDEXABLE', raising=False)
    monkeypatch.setenv('MANUALS_PUBLIC_URL', ORIGIN)
    with Flask(__name__).test_request_context('/', base_url=ORIGIN):
        assert not indexable()


def test_prices_and_minimum_quantities_match_every_manual():
    for book in CATALOGUE:
        metadata = public_metadata(ORIGIN, '/manuels/' + book['code'],
                                   'Manuel ' + book['name'], book['description'], book=book)
        product = next(item for item in metadata['data']['@graph'] if item['@type'] == 'Product')
        first, bulk = product['offers']
        assert first['price'] == f"{book['price'] / 100:.2f}"
        assert first['eligibleQuantity']['minValue'] == 50
        assert first['eligibleQuantity']['maxValue'] == 99
        assert bulk['price'] == f"{book['bulk_price'] / 100:.2f}"
        assert bulk['eligibleQuantity']['minValue'] == 100
        assert 'maxValue' not in bulk['eligibleQuantity']
        assert product['image'] == ORIGIN + '/static/manuals/' + book['code'] + '.webp'
        assert 'aggregateRating' not in product
        assert all('availability' not in offer for offer in product['offers'])
        assert 'onrender.com' not in json.dumps(metadata)


def test_usb_offers_are_per_unit_and_have_distinct_references():
    for book in CATALOGUE:
        if book['usb_price'] is None:
            continue
        metadata = public_metadata(ORIGIN, '/supports-formateurs/' + book['code'],
                                   'PowerPoint ' + book['name'], book['description'], book=book)
        product = next(item for item in metadata['data']['@graph'] if item['@type'] == 'Product')
        assert product['sku'] == 'usb_' + book['code']
        assert product['offers'][0]['price'] == f"{book['usb_price'] / 100:.2f}"
        assert product['offers'][0]['eligibleQuantity']['minValue'] == 1


def test_course_sales_pause_is_not_advertised_as_available():
    course = {'code': 'aps', 'name': 'APS', 'title': 'Agent de prévention et de sécurité',
              'planned_minutes': 3720, 'unit_cents': 5900}
    for enabled in (False, True):
        metadata = public_metadata(ORIGIN, '/e-learning/aps', 'E-learning APS', 'Parcours APS',
                                   course=course, sales_enabled=enabled)
        item = next(item for item in metadata['data']['@graph'] if item['@type'] == 'Course')
        assert item['timeRequired'] == 'PT3720M'
        assert item['offers']['price'] == '59.00'
        assert item['offers']['availability'].endswith('InStock' if enabled else 'OutOfStock')


def test_catalogue_lists_link_to_public_product_pages():
    for path, count in (('/manuels', 15), ('/supports-formateurs', 14)):
        metadata = public_metadata(ORIGIN, path, 'Catalogue', 'Catalogue')
        listing = next(item for item in metadata['data']['@graph'] if item['@type'] == 'ItemList')
        assert listing['numberOfItems'] == count
        assert all(item['url'].startswith(ORIGIN + path + '/') for item in listing['itemListElement'])
        assert not any(item['@type'] == 'Product' for item in metadata['data']['@graph'])
