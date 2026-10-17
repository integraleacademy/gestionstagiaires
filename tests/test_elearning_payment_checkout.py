"""Checkout regressions: verified capture, no premature e-mail, scoped return."""
import copy
import re

import pytest
from werkzeug.datastructures import MultiDict

import app as host
import elearning_orders as learning
from manuals_shop import base_url
from test_manuals_shop import shop, all_data, csrf, signup, login
from test_manuals_commerce import merchant, run, retry
from test_elearning_orders import submit, latest, prepare
from test_elearning_groups import create, save, quote, person


def centre_messages(shop):
    return [mail for mail in shop['mails'] if mail[1].get('metadata', {}).get('purpose', '').startswith('elearning_')]


def test_verified_card_capture_unlocks_before_invoice_reconciliation_and_only_one_email(shop, merchant):
    order = submit(shop)
    run(order)
    assert not centre_messages(shop)
    assert not learning.entitled(latest(shop))
    merchant['paid'] = True
    # A card capture can be settled before the invoice API reports the payout.
    merchant['invoice'].update(status='unpaid', amount_paid={'value': '0.00', 'currency': 'EUR'})
    retry(order)
    current = latest(shop)
    assert learning.entitled(current)
    assert current['commerce']['payment_status'] == 'paid'
    assert current['commerce']['remaining_cents'] == 0
    assert not current.get('activated_at')  # The centre still controls dispatch.
    messages = centre_messages(shop)
    assert len(messages) == 1
    assert 'Commande confirmée' in messages[0][0][1]
    assert 'paiement a bien été reçu' in messages[0][0][2]
    assert messages[0][1]['attachments']
    retry(order)
    assert len(centre_messages(shop)) == 1
    assert not any('/mark_as_paid' in path for _, path, *_ in merchant['calls'])
    url = '/admin/organisme/e-learning/commandes/' + order['id']
    status = shop['client'].get(url + '/statut')
    assert status.json['paid'] is True and not status.json['checkout_url']
    assert 'no-store' in status.headers['Cache-Control']
    confirmation = shop['client'].get(url + '/confirmation')
    assert confirmation.status_code == 200 and 'Commande confirmée' in confirmation.text
    assert 'data-el-celebration=' in confirmation.text
    assert 'data-confetti' in confirmation.text
    assert 'data-el-celebration=' not in shop['client'].get(url).text
    assert 'Régler ma facture' not in confirmation.text
    invoice_link = re.search(r'<a\b[^>]*href="' + re.escape(url + '/facture') + r'"[^>]*>', confirmation.text).group()
    assert 'target="_blank"' in invoice_link and 'rel="noopener noreferrer"' in invoice_link
    invoice = shop['client'].get(url + '/facture')
    assert invoice.status_code == 200 and invoice.mimetype == 'application/pdf'
    assert invoice.headers['Content-Disposition'].startswith('inline;')


@pytest.mark.parametrize('status,amount,currency,paid_at', [
    ('authorized', '118.00', 'EUR', '2026-01-01T10:00:00Z'),
    ('pending', '118.00', 'EUR', '2026-01-01T10:00:00Z'),
    ('failed', '118.00', 'EUR', '2026-01-01T10:00:00Z'),
    ('paid', '59.00', 'EUR', '2026-01-01T10:00:00Z'),
    ('paid', '119.00', 'EUR', '2026-01-01T10:00:00Z'),
    ('paid', '118.00', 'USD', '2026-01-01T10:00:00Z'),
    ('paid', '118.00', 'EUR', ''),
    ('paid', '118.00', 'EUR', '2099-01-01T10:00:00Z'),
])
def test_unverified_capture_never_unlocks_or_sends_confirmation(shop, merchant, status, amount, currency, paid_at):
    order = submit(shop)
    run(order)
    merchant['payments'] = [{'id': 'capture-1', 'status': status, 'amount': {'value': amount, 'currency': currency}, 'paid_at': paid_at}]
    retry(order)
    assert not learning.entitled(latest(shop))
    assert not centre_messages(shop)
    url = '/admin/organisme/e-learning/commandes/' + order['id']
    assert shop['client'].get(url + '/confirmation?paid=true').status_code == 303


def test_partial_capture_reconciles_after_remaining_payment(shop, merchant):
    order = submit(shop)
    run(order)
    payment = {'id': 'part-1', 'status': 'paid', 'amount': {'value': '59.00', 'currency': 'EUR'}, 'paid_at': '2026-01-01T10:00:00Z'}
    merchant['payments'] = [payment]
    retry(order)
    assert not learning.entitled(latest(shop))
    merchant['payments'].append({**copy.deepcopy(payment), 'id': 'part-2'})
    retry(order)
    assert learning.entitled(latest(shop)) and len(centre_messages(shop)) == 1


def test_wrong_invoice_link_never_unlocks(shop, merchant):
    order = submit(shop)
    run(order)
    merchant['payment']['invoice_id'] = 'another-invoice'
    merchant['paid'] = True
    retry(order)
    assert not learning.entitled(latest(shop)) and not centre_messages(shop)


def test_ajax_group_checkout_is_idempotent_and_normalizes_identity(shop, merchant):
    prepare(shop)
    client = shop['client']
    url = create(client)
    save(shop, url, [person(first='cLÉMent', last='vaillant')])
    fields = quote(client, url)
    response = client.post(url + '/creer-espaces', data=fields, headers={'Accept': 'application/json'})
    assert response.status_code == 200 and response.json['confirmation_url'].endswith('/confirmation')
    repeat = client.post(url + '/creer-espaces', data=fields, headers={'Accept': 'application/json'})
    assert repeat.json == response.json
    order = latest(shop)
    assert order['learners'][0]['last_name'] == 'VAILLANT'
    assert order['learners'][0]['first_name'] == 'Clément'
    assert client.get(response.json['confirmation_url']).status_code == 303
    other = host.app.test_client()
    signup(other, email='other@example.test')
    login(other, email='other@example.test')
    assert other.get(response.json['status_url']).status_code == 404
    assert other.get(response.json['confirmation_url']).status_code == 404


def test_names_preserve_accents_and_compound_separators():
    people = learning.parse_learners(MultiDict({'last_name': 'd’ortiz-dupré', 'first_name': 'jEAN-pIERRE élIE', 'email': 'p@example.test'}))
    assert people[0]['last_name'] == 'D’ORTIZ-DUPRÉ'
    assert people[0]['first_name'] == 'Jean-Pierre Élie'


def test_production_confirmation_links_use_connect_and_staging_remains_isolated(monkeypatch):
    monkeypatch.delenv('MANUALS_BASE_URL', raising=False)
    monkeypatch.setenv('MANUALS_PUBLIC_URL', 'https://www.integraleconnect.com')
    with host.app.app_context():
        monkeypatch.setenv('RENDER_EXTERNAL_URL', 'https://gestionstagiaires-r5no.onrender.com')
        assert base_url(host) == 'https://www.integraleconnect.com'
        monkeypatch.setenv('RENDER_EXTERNAL_URL', 'https://gestionstagiaires-test-v2.onrender.com')
        assert base_url(host) == 'https://gestionstagiaires-test-v2.onrender.com'


def test_modal_close_refresh_is_scoped_csrf_protected_and_never_trusts_client_payment(shop, merchant):
    order = submit(shop)
    run(order)
    client = shop['client']
    url = '/admin/organisme/e-learning/commandes/' + order['id']
    assert 'data-el-celebration=' not in client.get(url).text
    rejected = client.post(url + '/actualiser', headers={'Accept': 'application/json'})
    assert rejected.status_code == 400
    response = client.post(url + '/actualiser', data={'csrf_token': csrf(client, url), 'paid': 'true'}, headers={'Accept': 'application/json'})
    assert response.status_code == 200
    assert response.json['paid'] is False
    assert 'no-store' in response.headers['Cache-Control']
    assert not learning.entitled(latest(shop))
    assert not centre_messages(shop)
    assert client.get(url + '/confirmation?paid=true').status_code == 303
    other = host.app.test_client()
    signup(other, email='modal-other@example.test')
    login(other, email='modal-other@example.test')
    other.get('/admin/organisme/e-learning')
    with other.session_transaction() as session:
        other_csrf = session['manuals_csrf']
    assert other.post(url + '/actualiser', data={'csrf_token': other_csrf}, headers={'Accept': 'application/json'}).status_code == 404
