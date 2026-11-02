import datetime
import re
from unittest.mock import Mock

import pytest

import app as gestion_app


@pytest.mark.parametrize('personal,other,closed', [
    (0, 0, True), (4.99, 0, True), (0, 5, True),
    (0, 5.01, False), (3, 3, False),
])
def test_financial_closure_uses_session_total_and_five_euro_boundary(personal, other, closed):
    trainees = [
        {'id': 'T1', 'personal_amount': personal, 'cpf_amount': 1750},
        {'id': 'T2', 'other_amount': other},
    ]
    report = gestion_app._session_financial_report(
        {}, {'id': 'S', 'trainees': trainees}, session_lines=[], include_cpf=False,
    )
    assert report['overview']['remaining'] == personal + other
    assert report['overview']['closed'] is closed


def test_unknown_external_payment_does_not_close_at_zero_confirmed_due():
    report = gestion_app._session_financial_report(
        {}, {'id': 'S', 'trainees': [{'id': 'T', 'other_amount': 980}]},
        session_lines=[{'traineeId': 'T', 'financingType': 'AUTRE',
                        'amount': 980, 'invoiceStatus': 'external_generated'}],
        include_cpf=False,
    )
    assert report['overview']['remaining'] == 0
    assert report['overview']['unverified'] == 980
    assert report['overview']['closed'] is False


def test_only_ended_cards_have_financial_border_and_link_to_same_report(monkeypatch):
    today = datetime.date.today()
    def session(identifier, end_delta, amount, start_delta=-30):
        return {'id': identifier, 'name': identifier, 'training_type': 'SSIAP 1',
                'partner_id': gestion_app.INTEGRALE_PARTNER_ID,
                'date_start': (today + datetime.timedelta(days=start_delta)).isoformat(),
                'date_end': (today + datetime.timedelta(days=end_delta)).isoformat(),
                'trainees': [{'id': 'T-' + identifier, 'other_amount': amount}]}
    data = {'sessions': [session('CLOSED', -1, 5), session('OPEN', -2, 5.01),
                         session('ONGOING', 0, 0), session('FUTURE', 30, 100, 10)],
            'billing_lines': []}
    monkeypatch.setattr(gestion_app, 'load_data', lambda **kwargs: data)
    monkeypatch.setattr(gestion_app, '_load_wedof_webhooks', lambda: [])
    remote = Mock(side_effect=AssertionError('Rendering must not contact Qonto'))
    monkeypatch.setattr(gestion_app, '_qonto_request', remote)
    client = gestion_app.app.test_client()
    with client.session_transaction() as auth:
        auth['admin_logged_in'] = True
        auth['admin_role'] = 'admin'
    response = client.get('/admin/sessions')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    cards = {}
    for classes, body in re.findall(r'<article class="([^"]*session-card[^"]*)"[^>]*>(.*?)</article>', html, re.S):
        name = re.search(r'<h2[^>]*>(.*?)</h2>', body, re.S).group(1).strip()
        cards[name] = (classes.split(), body)
    assert 'session-card--financial-closed' in cards['CLOSED'][0]
    assert 'session-card--financial-open' in cards['OPEN'][0]
    for identifier in ('ONGOING', 'FUTURE'):
        assert not any('financial-' in name for name in cards[identifier][0])
    for identifier, amount in (('CLOSED', '5,00'), ('OPEN', '5,01')):
        href = re.search(r'<a class="pill pill-financial-[^"]*" href="([^"]+)"', cards[identifier][1]).group(1)
        assert href == f'/admin/sessions/{identifier}/trainees/financial'
        report = client.get(href)
        assert report.status_code == 200
        kpi = re.search(r'financial-card--balance.*?financial-card__value">(.*?)</strong>', report.get_data(as_text=True), re.S).group(1)
        assert amount in kpi
    remote.assert_not_called()
