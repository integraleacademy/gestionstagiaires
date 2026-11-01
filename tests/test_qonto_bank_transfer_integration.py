from copy import deepcopy
from unittest.mock import Mock
import pytest
import app as gestion_app


@pytest.fixture
def finance(monkeypatch):
    trainee = {'id': 'T-BANK', 'first_name': 'Alex', 'last_name': 'Martin',
               'personal_amount': 1250, 'cpf_amount': 1750}
    data = {'sessions': [{'id': 'S-BANK', 'training_type': 'A3P', 'date_start': '2026-09-01',
                         'date_end': '2026-10-26', 'trainees': [trainee]}], 'billing_lines': []}
    line = gestion_app._billing_lines(data)[0]
    line.update(invoiceStatus='external_generated', paymentStatus='not_applicable')
    gestion_app._save_billing_line(data, line)
    monkeypatch.setattr(gestion_app, 'load_data', lambda **kwargs: data)
    monkeypatch.setattr(gestion_app, 'save_data', Mock())
    monkeypatch.setattr(gestion_app, '_atomic_update_data', lambda update: update(data))
    monkeypatch.setattr(gestion_app, '_qonto_is_configured', lambda: True)
    monkeypatch.setattr(gestion_app, '_discover_cpf_qonto_invoice', lambda *args, **kwargs: ({}, False))
    for name in ('create_qonto_invoice', 'create_qonto_direct_debit_subscription', 'send_qonto_invoice'):
        monkeypatch.setattr(gestion_app, name, Mock(side_effect=AssertionError('Unexpected write: '+name)))
    transfer = {'id': 'transfer-bank', 'amount_cents': 125000, 'currency': 'EUR', 'status': 'completed',
                'side': 'credit', 'operation_type': 'transfer', 'settled_at': '2026-09-03T12:32:00Z',
                'label': 'M ALEX MARTIN', 'reference': 'Virement de M Alex Martin'}
    fetch = Mock(return_value=[transfer])
    monkeypatch.setattr(gestion_app, '_fetch_qonto_bank_transactions', fetch)
    client = gestion_app.app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
        session['admin_role'] = 'admin'
    return client, data, trainee, fetch


def test_manual_sync_connects_bank_transfer_and_external_invoice_without_duplication(finance):
    client, data, trainee, fetch = finance
    first = client.post('/api/billing/sync-qonto', json={'traineeId': 'T-BANK', 'sessionId': 'S-BANK'})
    assert first.status_code == 200
    assert first.json['bank_transfer_matched_count'] == 1
    summary = first.json['financial_summary']
    assert summary['paid_total_cents'] == 125000
    assert summary['remaining_total_cents'] == 0
    assert summary['qonto_payment_entries'][0]['source'] == 'qonto_bank_transfer'
    line = gestion_app._billing_lines(data)[0]
    assert line['invoiceStatus'] == 'external_generated'
    assert line['qontoBankTransferPaidCents'] == 125000
    second = client.post('/api/billing/sync-qonto', json={'traineeId': 'T-BANK', 'sessionId': 'S-BANK'})
    assert second.json['financial_summary']['paid_total_cents'] == 125000
    assert second.json['bank_transfer_matched_count'] == 0
    report = gestion_app._session_financial_report(data, data['sessions'][0])
    assert report['rows'][0]['personal_paid'] == 1250
    assert report['rows'][0]['personal_remaining'] == 0
    assert report['rows'][0]['invoices'][0]['financer_type'] == 'PERSONNEL'
    assert report['rows'][0]['invoices'][0]['paid'] == 1250
    assert report['unknown_payment_count'] == 0


def test_opening_trainee_refreshes_transfer_then_throttles(finance):
    client, data, trainee, fetch = finance
    url = '/api/billing/trainee/T-BANK/session/S-BANK'
    assert client.get(url).json['financial_summary']['paid_total_cents'] == 125000
    assert client.get(url).json['financial_summary']['paid_total_cents'] == 125000
    fetch.assert_called_once()


def test_local_only_view_does_not_read_bank(finance):
    client, data, trainee, fetch = finance
    assert client.get('/api/billing/trainee/T-BANK/session/S-BANK?local=1').status_code == 200
    fetch.assert_not_called()


def test_reversed_transfer_stops_counting_but_keeps_proof(finance):
    client, data, trainee, fetch = finance
    gestion_app._sync_qonto_bank_transfers(data, force=True)
    fetch.return_value[0]['status'] = 'reversed'
    gestion_app._sync_qonto_bank_transfers(data, force=True)
    lines = gestion_app._billing_lines(data)
    assert lines[0]['qontoBankTransfers'][0]['status'] == 'reversed'
    assert gestion_app.calculate_trainee_financial_summary(trainee, lines)['paid_total_cents'] == 0


def test_background_sync_includes_transfer_only_line(finance):
    client, data, trainee, fetch = finance
    result = gestion_app.run_qonto_background_sync()
    assert result['bank_transfer_matched_count'] == 1
    assert gestion_app.calculate_trainee_financial_summary(trainee, gestion_app._billing_lines(data))['paid_total_cents'] == 125000


def test_concurrent_name_or_amount_edit_rejects_match(finance):
    client, data, trainee, fetch = finance
    snapshot = deepcopy(data)
    def mutate_during_fetch(lines):
        trainee['personal_amount'] = 2000
        return fetch.return_value
    fetch.side_effect = mutate_during_fetch
    result = gestion_app._sync_qonto_bank_transfers(snapshot, force=True)
    assert result['conflict_count'] == 1
    assert not data['billing_lines'][0].get('qontoBankTransfers')
    # The caller may save its working snapshot after refreshing other invoices.
    # It must now contain the concurrent edit rather than overwrite it.
    assert snapshot['sessions'][0]['trainees'][0]['personal_amount'] == 2000


def test_fetch_failure_keeps_previous_payment_and_throttles(finance):
    client, data, trainee, fetch = finance
    gestion_app._sync_qonto_bank_transfers(data, force=True)
    fetch.side_effect = RuntimeError('bank unavailable')
    result = gestion_app._sync_qonto_bank_transfers(data, force=True)
    assert result['errors']
    assert 'indisponible' in data['billing_lines'][0]['qontoBankTransferSyncWarning']
    assert gestion_app.calculate_trainee_financial_summary(trainee, gestion_app._billing_lines(data))['paid_total_cents'] == 125000


def test_read_all_accounts_pages_and_include_reversals(monkeypatch):
    monkeypatch.setattr(gestion_app, 'get_qonto_organization_bank_accounts', lambda: {'bank_accounts': [{'id':'a'}, {'id':'b'}]})
    remote = Mock(side_effect=[{'transactions': [{'id':'one'}], 'meta': {'next_page':2}},
                               {'transactions': [{'id':'two'}], 'meta': {'next_page':None}},
                               {'transactions': [], 'meta': {'next_page':None}}])
    monkeypatch.setattr(gestion_app, '_qonto_request', remote)
    transactions = gestion_app._fetch_qonto_bank_transactions([{'dateStart': '2026-09-01'}])
    assert [item['id'] for item in transactions] == ['one', 'two']
    assert [call.kwargs['params']['bank_account_id'] for call in remote.call_args_list] == ['a','a','b']
    assert remote.call_args_list[0].kwargs['params']['status[]'] == ['completed','reversed']
    assert all(call.args[:2] == ('GET', '/v2/transactions') for call in remote.call_args_list)


def test_incomplete_pagination_fails_closed(monkeypatch):
    monkeypatch.setattr(gestion_app, 'get_qonto_organization_bank_accounts', lambda: {'bank_accounts': [{'id':'a'}]})
    monkeypatch.setattr(gestion_app, '_qonto_request', lambda *args, **kwargs: {'transactions': [], 'meta': {'next_page':3}})
    with pytest.raises(ValueError, match='Pagination'):
        gestion_app._fetch_qonto_bank_transactions([{'dateStart': '2026-09-01'}])


def test_external_invoice_generation_stays_blocked(finance):
    client, data, trainee, fetch = finance
    line = gestion_app._billing_lines(data)[0]
    response = client.post('/api/admin/billing-lines/' + line['id'] + '/generate-invoice')
    assert response.status_code == 409
    gestion_app.create_qonto_invoice.assert_not_called()


def test_bank_pagination_time_budget_fails_without_partial_reconciliation(monkeypatch):
    monkeypatch.setattr(gestion_app, 'get_qonto_organization_bank_accounts', lambda: {'bank_accounts': [{'id':'a'}]})
    monotonic = Mock(side_effect=[0, 26])
    monkeypatch.setattr(gestion_app.time, 'monotonic', monotonic)
    request = Mock()
    monkeypatch.setattr(gestion_app, '_qonto_request', request)
    with pytest.raises(ValueError, match='trop longue'):
        gestion_app._fetch_qonto_bank_transactions([{'dateStart': '2026-09-01'}])
    request.assert_not_called()


def test_historical_unbilled_homonym_blocks_scoped_automatic_match(finance):
    client, data, trainee, fetch = finance
    data['sessions'].append({'id': 'OLD', 'training_type': 'APS', 'date_start': '2025-01-01',
                             'date_end': '2025-02-01', 'trainees': [dict(trainee, id='OTHER-PERSON')]})
    result = gestion_app._sync_qonto_bank_transfers(data, force=True)
    assert result['matched_count'] == 0
    assert not data['billing_lines'][0].get('qontoBankTransfers')


def test_auto_refresh_uses_updated_trainee_after_conflict(finance, monkeypatch):
    client, data, trainee, fetch = finance
    snapshot = deepcopy(data)
    monkeypatch.setattr(gestion_app, 'load_data', lambda **kwargs: snapshot)
    def concurrent_edit(lines):
        trainee['personal_amount'] = 2000
        return fetch.return_value
    fetch.side_effect = concurrent_edit
    response = client.get('/api/billing/trainee/T-BANK/session/S-BANK')
    assert response.json['financial_summary']['planned_total_cents'] == 200000
    assert response.json['financial_summary']['paid_total_cents'] == 0
