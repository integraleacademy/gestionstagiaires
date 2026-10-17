"""Merchant hub keeps sales, tax settings and all order types on one admin surface."""
import copy

import app as host
import elearning_sales as sales
from test_manuals_shop import shop, csrf, signup, login, all_data
from test_partner_workspace import as_admin

HUB = '/admin/partners'
SETTINGS = '/admin/commandes-manuels/reglages'
SALES = '/admin/commandes-elearning'


def test_hub_sales_and_tax_controls_share_existing_state(shop):
    client = shop['client']
    signup(client)
    as_admin(client)
    assert client.get(HUB).status_code == 200
    before = copy.deepcopy(all_data(shop))
    for tab in ('organisations', 'orders', 'invoices', 'settings'):
        page = client.get(HUB + '?tab=' + tab)
        assert page.status_code == 200
        assert 'name="sales_enabled"' in page.text
        assert 'name="return_to" value="partners"' in page.text
    assert all_data(shop) == before
    response = client.post(SALES, data={'csrf_token': csrf(client, HUB), 'action': 'sales_settings', 'return_to': 'partners'})
    assert response.status_code == 303 and response.location == HUB
    assert not sales.enabled(host)
    assert 'Ventes suspendues' in client.get(HUB).text
    values = {'csrf_token': csrf(client, HUB), 'return_to': 'partners', 'manual_vat': '5.5', 'usb_vat': '20', 'elearning_vat': '0', 'elearning_exemption': 'S261'}
    response = client.post(SETTINGS, data=values)
    assert response.status_code == 303 and response.location == HUB + '?tab=settings'
    assert not sales.enabled(host)  # Editing VAT must never reopen sales.
    with host.app.test_request_context():
        settings = host.load_data(run_background_tasks=False)['manuals_commerce_settings']
    assert settings['elearning_vat'] == '0' and settings['elearning_exemption'] == 'S261'
    assert settings['usb_vat'] == '20' and settings['manual_vat'] == '5.5'
    values['elearning_exemption'] = ''
    assert client.post(SETTINGS, data=values).status_code == 400
    with host.app.test_request_context():
        assert host.load_data(run_background_tasks=False)['manuals_commerce_settings'] == settings
    # Older two-category forms cannot erase the e-learning VAT setting.
    values.pop('elearning_vat')
    assert client.post(SETTINGS, data=values).status_code == 303
    with host.app.test_request_context():
        assert host.load_data(run_background_tasks=False)['manuals_commerce_settings']['elearning_exemption'] == 'S261'
    assert client.post(SALES, data={'csrf_token': csrf(client, HUB), 'action': 'sales_settings', 'sales_enabled': 'yes', 'return_to': 'partners'}).location == HUB
    assert sales.enabled(host)
    after = all_data(shop)
    for key in ('users', 'partners', 'manual_orders'):
        assert after.get(key, []) == before.get(key, [])


def test_hub_shows_physical_and_learning_orders_and_invoices(shop):
    client = shop['client']
    signup(client)
    pid = all_data(shop)['users'][0]['partner_id']
    def seed(data):
        for kind, oid, ref in [('manual', 'manual-test', 'MAN-TEST'), ('elearning', 'learning-test', 'EL-TEST')]:
            data.setdefault('manual_orders', []).append({'id': oid, 'partner_id': pid, 'order_type': kind,
                'reference': ref, 'course_code': 'a3p', 'status': 'received', 'submitted_at': '2026-10-17T10:00:00Z',
                'total_cents': 15000, 'items': [], 'learners': [],
                'commerce': {'invoice_id': 'invoice-'+oid, 'invoice_number': 'FACT-'+ref, 'payment_status': 'unpaid'}})
        data['manual_orders'].append({'id': 'draft', 'partner_id': pid, 'reference': 'HIDDEN-DRAFT', 'status': 'draft'})
        return {}
    with host.app.test_request_context():
        host._atomic_update_data(seed, partner_id=pid)
    as_admin(client)
    assert client.get(HUB).status_code == 200
    before = copy.deepcopy(all_data(shop))
    for tab in ('orders', 'invoices'):
        page = client.get(HUB + '?tab=' + tab)
        assert page.status_code == 200
        assert 'MAN-TEST' in page.text and 'EL-TEST' in page.text and 'HIDDEN-DRAFT' not in page.text
        assert 'Gérer les accès' in page.text and 'Gérer la commande' in page.text
        assert 'Centre de formation test' in page.text
    assert all_data(shop) == before


def test_hub_controls_require_platform_admin_and_csrf(shop):
    client = shop['client']
    signup(client)
    login(client)
    fields = {'csrf_token': csrf(client, '/admin/manuels'), 'return_to': 'partners', 'action': 'sales_settings'}
    assert client.get(HUB).status_code == 302
    assert client.post(SALES, data=fields).status_code == 403
    assert client.post(SETTINGS, data=fields).status_code == 403
    as_admin(client)
    assert client.post(SALES, data={'action': 'sales_settings', 'return_to': 'partners'}).status_code == 400
    assert client.post(SETTINGS, data={'return_to': 'partners'}).status_code == 400
    pid = all_data(shop)['users'][0]['partner_id']
    with client.session_transaction() as session:
        session['assist_partner_id'] = pid
    assert client.post(SALES, data=fields).status_code == 403
    assert client.post(SETTINGS, data=fields).status_code == 403
    assert sales.enabled(host)
