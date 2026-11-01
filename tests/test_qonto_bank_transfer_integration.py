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
                'side': 'credit', 'operation_type': 'income', 'subject_type': 'Income', 'settled_at': '2026-09-03T12:32:00Z',
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


def test_already_linked_reversal_missing_from_dated_listing_is_read_by_id(monkeypatch):
    monkeypatch.setattr(gestion_app, 'get_qonto_organization_bank_accounts', lambda: {'bank_accounts': [{'id': 'a'}]})
    proof = {'id': 'existing-credit', 'amount_cents': 125000, 'currency': 'EUR', 'status': 'completed',
             'side': 'credit', 'operation_type': 'transfer', 'paid_at': '2026-09-03T12:32:00Z'}
    remote = Mock(side_effect=[{'transactions': [], 'meta': {'next_page': None}},
                              {'transaction': dict(proof, operation_type='income', subject_type='Income', status='reversed', settled_at=None, paid_at=None)}])
    monkeypatch.setattr(gestion_app, '_qonto_request', remote)
    line = {'id': 'L1', 'dateStart': '2026-09-01', 'qontoBankTransfers': [proof]}
    transactions = gestion_app._fetch_qonto_bank_transactions([line])
    assert remote.call_args_list[-1].args == ('GET', '/v2/transactions/existing-credit')
    matches = gestion_app.match_bank_transfers([line], transactions)
    assert gestion_app.bank_transfer_paid_cents({'qontoBankTransfers': matches['L1']}) == 0
    assert matches['L1'][0]['paid_at'] == proof['paid_at']


def test_transaction_detail_with_wrong_id_fails_closed(monkeypatch):
    monkeypatch.setattr(gestion_app, 'get_qonto_organization_bank_accounts', lambda: {'bank_accounts': [{'id': 'a'}]})
    remote = Mock(side_effect=[{'transactions': [], 'meta': {'next_page': None}}, {'transaction': {'id': 'wrong'}}])
    monkeypatch.setattr(gestion_app, '_qonto_request', remote)
    with pytest.raises(ValueError, match='incomplète'):
        gestion_app._fetch_qonto_bank_transactions([{'dateStart': '2026-09-01', 'qontoBankTransfers': [{'id': 'existing-credit'}]}])


@pytest.fixture
def third_party(finance, monkeypatch):
    client, data, trainee, fetch = finance
    fetch.return_value[0].update(label='MME AURORE VERON', clean_counterparty_name='Aurore VERON',
                                 reference='Participation formation', transfer={'iban': 'PRIVATE-IBAN'})
    detail = Mock(side_effect=lambda *args, **kwargs: {'transaction': deepcopy(fetch.return_value[0])})
    monkeypatch.setattr(gestion_app, '_qonto_request', detail)
    with client.session_transaction() as session:
        session['admin_username'] = 'admin-test'
    return client, data, trainee, fetch, detail


def search_third_party(fixture):
    client, data, *_ = fixture
    return client.post('/api/billing/bank-transfers/search', json={
        'lineId': gestion_app._billing_lines(data)[0]['id'], 'query': 'veron aurore',
        'dateFrom': '2025-01-01'})


def assign_third_party(fixture, search=None):
    search = search if search is not None else search_third_party(fixture)
    assert search.status_code == 200, search.json
    return fixture[0].post('/api/billing/bank-transfers/assign', json={
        'selectionToken': search.json['transactions'][0]['selection_token']})


def test_third_party_search_and_assignment_soldes_personal_only(third_party):
    client, data, trainee, fetch, detail = third_party
    search = search_third_party(third_party)
    assert search.status_code == 200, search.json
    assert 'PRIVATE-IBAN' not in repr(search.json)
    assert search.json['transactions'][0]['payer_name'] == 'Aurore VERON'
    assert not data['billing_lines'][0].get('qontoBankTransfers')
    response = assign_third_party(third_party, search)
    assert response.status_code == 200, response.json
    assert response.json['remaining_cents'] == 0
    summary = client.get('/api/billing/trainee/T-BANK/session/S-BANK?local=1').json['financial_summary']
    assert summary['paid_total_cents'] == 125000
    assert summary['remaining_total_cents'] == 0
    proof = data['billing_lines'][0]['qontoBankTransfers'][0]
    assert proof['payer_name'] == 'Aurore VERON'
    assert proof['allocation_method'] == 'manual'
    assert proof['allocated_by'] == 'admin-test'
    assert data['billing_lines'][0]['invoiceStatus'] == 'external_generated'
    assert trainee['cpf_amount'] == 1750
    assert all(call.args[0] == 'GET' for call in detail.call_args_list)
    assert assign_third_party(third_party, search).status_code == 409
    assert len(data['billing_lines'][0]['qontoBankTransfers']) == 1


def test_manual_assignment_survives_sync_and_reversal_preserves_audit(third_party):
    client, data, trainee, fetch, detail = third_party
    assert assign_third_party(third_party).status_code == 200
    gestion_app._sync_qonto_bank_transfers(data, force=True)
    proof = data['billing_lines'][0]['qontoBankTransfers'][0]
    assert proof['allocated_by'] == 'admin-test'
    fetch.return_value[0]['status'] = 'reversed'
    gestion_app._sync_qonto_bank_transfers(data, force=True)
    line = gestion_app._billing_lines(data)[0]
    assert line['qontoBankTransfers'][0]['allocation_method'] == 'manual'
    assert gestion_app.calculate_trainee_financial_summary(trainee, [line])['paid_total_cents'] == 0


@pytest.mark.parametrize('change', [{'status':'pending'}, {'status':'reversed'}, {'side':'debit'},
                                 {'currency':'USD'}, {'operation_type':'card'}, {'settled_at':'2099-01-01'}])
def test_manual_search_excludes_unsettled_or_wrong_type(third_party, change):
    third_party[3].return_value[0].update(change)
    assert search_third_party(third_party).json['transactions'] == []


def test_manual_search_blocks_overpayment_and_existing_allocation(third_party):
    client, data, trainee, fetch, detail = third_party
    fetch.return_value[0]['amount_cents'] = 125001
    row = search_third_party(third_party).json['transactions'][0]
    assert row['blocked_reason'] and 'selection_token' not in row
    fetch.return_value[0]['amount_cents'] = 125000
    data['billing_lines'].append({'id':'historic-line', 'qontoBankTransfers':[dict(fetch.return_value[0])]})
    row = search_third_party(third_party).json['transactions'][0]
    assert row['assigned'] and 'selection_token' not in row


def test_manual_double_allocation_is_checked_under_atomic_lock(third_party, monkeypatch):
    client, data, trainee, fetch, detail = third_party
    search = search_third_party(third_party)
    def concurrent_allocation(mutator):
        data['billing_lines'].append({'id':'concurrent-line','qontoBankTransfers':[dict(fetch.return_value[0])]})
        return mutator(data)
    monkeypatch.setattr(gestion_app, '_atomic_update_data', concurrent_allocation)
    assert assign_third_party(third_party, search).status_code == 409
    assert not data['billing_lines'][0].get('qontoBankTransfers')


def test_manual_rechecks_bank_before_saving(third_party):
    search = search_third_party(third_party)
    third_party[3].return_value[0]['status'] = 'reversed'
    assert assign_third_party(third_party, search).status_code == 409
    assert not third_party[1]['billing_lines'][0].get('qontoBankTransfers')


def test_manual_rejects_edited_dossier_and_forged_selection(third_party):
    client, data, trainee, fetch, detail = third_party
    search = search_third_party(third_party)
    trainee['personal_amount'] = 1500
    assert assign_third_party(third_party, search).status_code == 409
    assert client.post('/api/billing/bank-transfers/assign', json={'selectionToken':'forged'}).status_code == 409
    detail.assert_not_called()


def test_manual_rejects_concurrent_target_edit(third_party, monkeypatch):
    search = search_third_party(third_party)
    def concurrent_edit(mutator):
        third_party[2]['personal_amount'] = 1500
        return mutator(third_party[1])
    monkeypatch.setattr(gestion_app, '_atomic_update_data', concurrent_edit)
    assert assign_third_party(third_party, search).status_code == 409
    assert not third_party[1]['billing_lines'][0].get('qontoBankTransfers')


def test_two_partial_third_party_transfers_settle_once(third_party):
    client, data, trainee, fetch, detail = third_party
    fetch.return_value[0]['amount_cents'] = 50000
    assert assign_third_party(third_party).json['remaining_cents'] == 75000
    fetch.return_value[0].update(id='second-transfer', amount_cents=75000)
    assert assign_third_party(third_party).json['remaining_cents'] == 0
    assert gestion_app.bank_transfer_paid_cents(data['billing_lines'][0]) == 125000


def link_unpaid_invoice(fixture, monkeypatch):
    line = fixture[1]['billing_lines'][0]
    line.update(qontoInvoiceId='invoice-linked', invoiceStatus='finalized', qonto_total_amount_cents=125000,
                qonto_amount_paid_cents=0, paymentMode='sepa_direct_debit')
    remote = {'id':'invoice-linked', 'status':'unpaid', 'number':'TEST-1',
              'total_amount':{'value':'1250.00'}, 'amount_paid':{'value':'0.00'}}
    monkeypatch.setattr(gestion_app, 'get_qonto_invoice', Mock(return_value={'client_invoice':remote}))
    return remote


def test_existing_qonto_invoice_gets_third_party_payment_and_reversal(third_party, monkeypatch):
    remote = link_unpaid_invoice(third_party, monkeypatch)
    client, data, trainee, fetch, detail = third_party
    response = assign_third_party(third_party)
    assert response.status_code == 200, response.json
    line = gestion_app._billing_lines(data)[0]
    assert line['qonto_invoice']['paid_amount_cents'] == 125000
    assert line['qontoRemoteAmountPaidCents'] == 0
    summary = gestion_app.calculate_trainee_financial_summary(trainee, [line])
    assert summary['qonto_payment_entries'][0]['transactions'][0]['payer_name'] == 'Aurore VERON'
    # Persist an invoice refresh, then reverse only the bank transfer: the
    # reconciled paid amount must never become a sticky remote invoice amount.
    gestion_app._apply_qonto_invoice_payment_to_billing_line(line, remote)
    remote.pop('amount_paid')
    gestion_app._apply_qonto_invoice_payment_to_billing_line(line, remote)
    assert line['qontoRemoteAmountPaidCents'] == 0
    gestion_app._save_billing_line(data, line)
    fetch.return_value[0]['status'] = 'reversed'
    gestion_app._sync_qonto_bank_transfers(data, force=True)
    line = gestion_app._billing_lines(data)[0]
    assert line['qonto_invoice']['paid_amount_cents'] == 0
    assert gestion_app.calculate_trainee_financial_summary(trainee, [line])['remaining_total_cents'] == 125000


@pytest.mark.parametrize('amount', ['1250.00', '1300.00', '-5.00'])
def test_existing_remote_payment_blocks_double_count(third_party, monkeypatch, amount):
    remote = link_unpaid_invoice(third_party, monkeypatch)
    remote['amount_paid'] = {'value':amount}
    assert search_third_party(third_party).status_code == 400
    third_party[3].assert_not_called()


def test_remote_invoice_paid_between_search_and_assign_blocks(third_party, monkeypatch):
    remote = link_unpaid_invoice(third_party, monkeypatch)
    search = search_third_party(third_party)
    remote['amount_paid'] = {'value':'1250.00'}
    assert assign_third_party(third_party, search).status_code == 409
    assert not third_party[1]['billing_lines'][0].get('qontoBankTransfers')


def test_manual_allocation_denies_viewer_and_external_partner(third_party, monkeypatch):
    client = third_party[0]
    with client.session_transaction() as session:
        session['admin_role'] = 'viewer'
    assert search_third_party(third_party).status_code == 403
    assert client.post('/api/billing/bank-transfers/assign',json={}).status_code == 403
    with client.session_transaction() as session:
        session['admin_role'] = 'admin'
    monkeypatch.setattr(gestion_app, '_is_partner_data_scope_session', lambda: True)
    assert search_third_party(third_party).status_code == 403
    assert client.post('/api/billing/bank-transfers/assign',json={}).status_code == 403
    third_party[3].assert_not_called()


@pytest.mark.parametrize('change', [
    {'directDebitInstallments':[{'amount':1250,'status':'scheduled'}]},
    {'manualPaymentInvoiceId':'some-invoice'}, {'amountPaid':100}, {'invoiceStatus':'draft'},
])
def test_manual_allocation_blocks_other_payment_modes(third_party, change):
    third_party[1]['billing_lines'][0].update(change)
    assert search_third_party(third_party).status_code == 409
    third_party[3].assert_not_called()
