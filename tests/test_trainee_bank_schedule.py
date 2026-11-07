from unittest.mock import patch

import pytest

import app as gestion


def subscription(sid, date, reference='Facture-1 - reprogrammation', **extras):
    return dict(id=sid, direct_debit_mandate_id='mandat', schedule_type='one_off',
                status='scheduled', schedule_next_collection_date=date, reference=reference,
                amount={'value': '367.50', 'currency': 'EUR'}) | extras


def test_same_day_subscriptions_history_dates_and_invoice_scope():
    line = {'id': 'ligne', 'qontoInvoiceNumber': 'Facture-1', 'qonto_direct_debit_mandate_id': 'mandat',
            'directDebitInstallments': [{'qonto_direct_debit_subscription_id': 'mensuel'}]}
    retries = [subscription(sid, '2026-11-10') for sid in ('a', 'b', 'c')]
    monthly = subscription('mensuel', '2026-11-30', 'Autre libellé', schedule_type='monthly',
                           initial_collection_date='2026-09-30')
    other = subscription('autre', '2026-11-10', 'Facture-10 - reprogrammation')
    foreign = subscription('hors-dossier', '2026-11-10', direct_debit_mandate_id='autre')
    cancelled = subscription('annulé', None, status='canceled')
    pages = [{'direct_debit_subscriptions': [other, foreign, *retries], 'meta': {'total_pages': 2}},
             {'direct_debit_subscriptions': [*retries, monthly, cancelled], 'meta': {'total_pages': 2}}]
    def fetch_collections(subscription_id, **_):
        rows = [{'id': 'op-1', 'direct_debit_subscription_id': 'mensuel', 'collection_date': '2026-10-02',
                 'amount': {'value': '367.50'}, 'status': 'declined', 'status_reason_code': 'AM04'}]
        rows.append(dict(rows[0], id='autre-op', direct_debit_subscription_id='autre'))
        return {'direct_debit_collections': rows}
    with patch.object(gestion, 'list_qonto_direct_debit_subscriptions', side_effect=pages), \
         patch.object(gestion, 'list_qonto_direct_debit_collections', side_effect=fetch_collections):
        upcoming, history = gestion._trainee_bank_schedule([line])
    assert [row['id'] for row in upcoming] == ['a', 'b', 'c', 'mensuel']
    assert sum(row['amount_cents'] for row in upcoming if row['date'] == '2026-11-10') == 110250
    assert upcoming[-1]['frequency'] == 'monthly'
    assert [(row['id'], row['date'], row['reason_code']) for row in history] == [('op-1', '2026-10-02', 'AM04')]


def test_incomplete_pages_do_not_return_zero_or_partial_history():
    with patch.object(gestion, 'list_qonto_direct_debit_subscriptions', return_value={'message': 'invalid'}):
        with pytest.raises(ValueError, match='incomplète'):
            gestion._trainee_bank_schedule([{'qonto_direct_debit_subscription_id': 'sub'}])


def test_bank_route_forbids_partner_and_does_not_call_qonto():
    client = gestion.app.test_client()
    url = '/api/billing/trainee/T/session/S/bank-schedule'
    with patch.object(gestion, '_qonto_request') as remote:
        assert client.get(url).status_code in {302, 401, 403}
        with client.session_transaction() as session:
            session['admin_logged_in'] = True
            session['admin_role'] = 'admin'
        with patch.object(gestion, '_is_partner_data_scope_session', return_value=True):
            assert client.get(url).status_code == 403
        with patch.object(gestion, '_financing_partner_module_enabled', return_value=False):
            assert client.get(url).status_code == 403
        remote.assert_not_called()


def test_bank_route_scopes_the_dossier_and_never_saves():
    client = gestion.app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
        session['admin_role'] = 'admin'
    with patch.object(gestion, 'load_data', return_value={}), \
         patch.object(gestion, '_billing_lines_for_trainee_session', return_value=[]) as scope, \
         patch.object(gestion, '_financing_partner_module_enabled', return_value=True), \
         patch.object(gestion, '_qonto_request') as remote, patch.object(gestion, 'save_data') as save:
        response = client.get('/api/billing/trainee/T/session/S/bank-schedule')
        assert response.status_code == 200
        assert response.json['upcoming'] == response.json['history'] == []
        scope.assert_called_once_with({}, 'T', 'S')
        remote.assert_not_called()
        save.assert_not_called()


def test_attached_collection_does_not_import_rest_of_an_external_plan():
    line = {'id': 'L', 'qonto_direct_debit_subscription_id': 'shared',
            'directDebitInstallments': [{'qonto_attachment': True, 'qonto_direct_debit_collection_id': 'attached',
                                         'qonto_direct_debit_subscription_id': 'shared'}]}
    rows = [dict(id=cid, direct_debit_subscription_id='shared', status='completed',
                 amount={'value': '10.00'}, collection_date='2026-11-01') for cid in ('attached', 'other')]
    with patch.object(gestion, 'list_qonto_direct_debit_subscriptions',
                      return_value={'items': [subscription('shared', '2026-11-10')]}), \
         patch.object(gestion, 'list_qonto_direct_debit_collections', return_value={'items': rows}):
        upcoming, history = gestion._trainee_bank_schedule([line])
    assert upcoming == []
    assert [row['id'] for row in history] == ['attached']
