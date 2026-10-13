"""Public discovery must never make ordering or tenant data public."""
import re
from pathlib import Path

import app as host
from manuals_catalogue import CATALOGUE
from manuals_presentation import presentation_books
from test_manuals_shop import shop, signup, login, order_form, all_data


def test_anonymous_discovery_and_private_ordering(shop):
    client = shop["client"]
    for path in ("/", "/manuels"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'Intégrale Connect' in response.text
        assert '/creer-mon-espace' in response.text
        assert 'name="password"' not in response.text
    for book in CATALOGUE:
        response = client.get('/manuels/' + book['code'])
        assert response.status_code == 200
        assert book['name'] in response.text
        for src in re.findall(r'<img[^>]+src="([^"]+)"', response.text):
            assert client.get(src).status_code == 200, src
    assert client.get('/manuels/unknown').status_code == 404
    for path in ('/admin/organisme', '/admin/manuels', '/admin/organisme/e-learning',
                 '/admin/manuels/presentation', '/admin/commandes-manuels'):
        response = client.get(path)
        assert response.status_code == 302
        assert '/admin/login' in response.location
    assert client.post('/admin/manuels/recapitulatif', data={'manual_h0b0': '100'}).status_code == 302
    assert all_data(shop)['manual_orders'] == [] if shop['store'] else not all_data(shop).get('manual_orders')


def test_customer_can_browse_public_pages_without_exposing_private_identity(shop):
    client = shop['client']
    signup(client)
    login(client)
    for path in ('/', '/manuels', '/manuels/ssiap3'):
        response = client.get(path)
        assert response.status_code == 200
        assert 'Mon espace' in response.text
        assert 'centre@example.test' not in response.text
        assert 'Centre de formation test' not in response.text
    page = client.get('/admin/organisme')
    assert page.status_code == 200
    assert '15 manuels' in page.text
    assert 'PowerPoint sur clé USB' in page.text
    catalogue = client.get('/admin/manuels')
    assert catalogue.status_code == 200
    assert len(re.findall(r'data-kind="manual"', catalogue.text)) == 15
    assert len(re.findall(r'data-kind="usb"', catalogue.text)) == 14
    assert 'name="usb_mac_sst"' not in catalogue.text


def test_new_products_checkout_uses_brochure_prices_and_keeps_draft(shop):
    client = shop['client']
    signup(client)
    login(client)
    form = order_form(client, manual_aps='0', manual_sst='0', usb_ssiap1='0',
                      manual_h0b0='99', manual_ssiap2='100', manual_mac_sst='50',
                      usb_mac_aps='2', usb_ssiap3='1', unit_cents='1', total_cents='1')
    response = client.post('/admin/manuels/recapitulatif', data=form)
    assert response.status_code == 303
    draft = all_data(shop)['manual_orders'][0]
    assert draft['status'] == 'draft'
    assert draft['total_cents'] == 323800  # 99×9 + 100×15 + 50×9 + 2×99 + 199, in cents.
    assert client.get(response.location).status_code == 200
    resume = client.get('/admin/manuels?draft=' + draft['id'])
    assert 'name="manual_h0b0"' in resume.text and 'value="99"' in resume.text


def test_only_existing_specimens_and_previews_are_advertised(shop):
    client = shop['client']
    root = Path(host.__file__).parent / 'static'
    for book in presentation_books(CATALOGUE):
        page = client.get('/manuels/' + book['code'])
        if book['specimen']:
            assert (root / book['specimen']).is_file()
            assert f'Feuilleter {book["specimen_pages"]} pages' in page.text
        else:
            assert 'Télécharger l’extrait' not in page.text
            assert 'brochure-manuels-2026.pdf#page=' + str(book['brochure_page']) in page.text
        assert ('id="apercus"' in page.text) == bool(book['preview_labels'])


def test_every_trainer_product_has_three_public_previews_and_working_assets(shop):
    client = shop['client']
    products = [book for book in CATALOGUE if book['usb_price'] is not None]
    catalogue = client.get('/supports-formateurs')
    assert catalogue.status_code == 200
    assert catalogue.text.count('data-support-preview ') == 3 * len(products) == 42
    assets = set()
    for book in products:
        page = client.get('/supports-formateurs/' + book['code'])
        assert page.status_code == 200
        assert page.text.count('data-support-preview ') == 3
        assert f'data-preview-group="{book["code"]}"' in page.text
        assert 'href="#apercus"' in page.text
        assert f'<option value="{book["code"]}">' in catalogue.text
        assert ('Extraits du PowerPoint' in page.text) == (book['code'] in {'aps', 'ssiap1'})
        assert '.pptx' not in page.text
        assets.update(re.findall(r'<img[^>]+src="([^"]+)"', page.text))
    for src in assets:
        assert client.get(src).status_code == 200, src
    assert client.get('/supports-formateurs/mac_sst').status_code == 404
