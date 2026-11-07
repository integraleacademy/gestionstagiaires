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


def test_company_transfer_credits_other_financing_and_reopens_session_if_reversed(third_party):
    client, data, trainee, fetch, detail = third_party
    trainee.update(personal_amount=0, other_amount=1250)
    data['billing_lines'] = []
    line = gestion_app._billing_lines(data)[0]
    assert line['financingType'] == 'AUTRE'
    line.update(invoiceStatus='external_generated', paymentStatus='not_applicable')
    gestion_app._save_billing_line(data, line)

    response = assign_third_party(third_party)
    assert response.status_code == 200, response.json
    assert response.json['remaining_cents'] == 0
    summary = client.get('/api/billing/trainee/T-BANK/session/S-BANK?local=1').json['financial_summary']
    assert summary['by_financer']['AUTRE']['paid_amount_cents'] == 125000
    assert summary['by_financer']['PERSONNEL']['paid_amount_cents'] == 0
    assert trainee['cpf_amount'] == 1750
    report = gestion_app._session_financial_report(data, data['sessions'][0])
    assert report['overview']['remaining'] == 0
    assert report['overview']['closed'] is True

    fetch.return_value[0]['status'] = 'reversed'
    gestion_app._sync_qonto_bank_transfers(data, force=True)
    report = gestion_app._session_financial_report(data, data['sessions'][0])
    assert report['overview']['remaining'] == 1250
    assert report['overview']['closed'] is False


@pytest.mark.parametrize('line', [
    {'financingType': 'CPF', 'amount': 1000},
    {'financingType': 'AUTRE', 'financeurName': 'CAISSE DES DEPOTS', 'amount': 1000},
])
def test_manual_bank_assignment_still_excludes_cpf(line):
    assert gestion_app._manual_bank_line_error(line)


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
    {'manualPaymentInvoiceId':'some-invoice'}, {'amountPaid':100}, {'invoiceStatus':'draft'},
])
def test_manual_allocation_blocks_other_payment_modes(third_party, change):
    third_party[1]['billing_lines'][0].update(change)
    assert search_third_party(third_party).status_code == 409
    third_party[3].assert_not_called()


def removed_installment(third_party, subscription_id=''):
    row = {'amount':1250, 'status':'scheduled', 'date':'2026-11-04',
           'tracking_removed_at':'2026-10-30T12:00:00Z', 'excluded_from_schedule_totals':True}
    if subscription_id:
        row['qonto_direct_debit_subscription_id'] = subscription_id
    third_party[1]['billing_lines'][0]['directDebitInstallments'] = [row]
    return row


def test_removed_local_schedule_does_not_block_received_transfer(third_party):
    removed_installment(third_party)
    response = assign_third_party(third_party)
    assert response.status_code == 200, response.json
    assert response.json['remaining_cents'] == 0
    assert third_party[1]['billing_lines'][0]['directDebitInstallments'][0]['tracking_removed_at']


@pytest.mark.parametrize('last_page', [None, 0, False, ''])
def test_removed_bank_schedule_requires_verified_cancellation(third_party, monkeypatch, last_page):
    removed_installment(third_party, 'old-subscription')
    subscription = Mock(return_value={'direct_debit_subscription':{'id':'old-subscription','status':'canceled'}})
    collections = Mock(return_value={'direct_debit_collections':[], 'meta':{'next_page':last_page}})
    monkeypatch.setattr(gestion_app, 'get_qonto_direct_debit_subscription', subscription)
    monkeypatch.setattr(gestion_app, 'list_qonto_direct_debit_collections', collections)
    response = assign_third_party(third_party)
    assert response.status_code == 200, response.json
    assert subscription.call_count == collections.call_count == 2


def test_removed_bank_schedule_still_active_blocks(third_party, monkeypatch):
    removed_installment(third_party, 'old-subscription')
    monkeypatch.setattr(gestion_app, 'get_qonto_direct_debit_subscription', lambda sid: {
        'direct_debit_subscription':{'id':sid,'status':'active'}})
    response = search_third_party(third_party)
    assert response.status_code == 400
    assert 'reste actif' in response.json['error']
    third_party[3].assert_not_called()


@pytest.mark.parametrize('status', ['completed', 'pending', 'unknown'])
def test_canceled_subscription_with_paid_or_pending_collection_blocks(third_party, monkeypatch, status):
    removed_installment(third_party, 'old-subscription')
    monkeypatch.setattr(gestion_app, 'get_qonto_direct_debit_subscription', lambda sid: {
        'direct_debit_subscription':{'id':sid,'status':'canceled'}})
    monkeypatch.setattr(gestion_app, 'list_qonto_direct_debit_collections', lambda *args, **kwargs: {
        'direct_debit_collections':[{'id':'collection','status':status}], 'meta':{'next_page':None}})
    assert search_third_party(third_party).status_code == 400
    third_party[3].assert_not_called()


def test_removed_bank_schedule_is_rechecked_at_assignment(third_party, monkeypatch):
    removed_installment(third_party, 'old-subscription')
    remote = {'direct_debit_subscription':{'id':'old-subscription','status':'canceled'}}
    monkeypatch.setattr(gestion_app, 'get_qonto_direct_debit_subscription', lambda sid: remote)
    monkeypatch.setattr(gestion_app, 'list_qonto_direct_debit_collections', lambda *args, **kwargs: {
        'direct_debit_collections':[], 'meta':{'next_page':None}})
    search = search_third_party(third_party)
    remote['direct_debit_subscription']['status'] = 'active'
    assert assign_third_party(third_party, search).status_code == 409
    assert not third_party[1]['billing_lines'][0].get('qontoBankTransfers')


def test_removed_paid_collection_cannot_be_ignored(third_party):
    removed_installment(third_party)['status'] = 'completed'
    assert search_third_party(third_party).status_code == 409
    third_party[3].assert_not_called()


@pytest.mark.parametrize('pagination', [{'next_page':True}, {'next_page':2}, {'total_pages':2}])
def test_canceled_subscription_checks_every_page_before_accepting(third_party, monkeypatch, pagination):
    removed_installment(third_party, 'old-subscription')
    monkeypatch.setattr(gestion_app, 'get_qonto_direct_debit_subscription', lambda sid: {
        'direct_debit_subscription':{'id':sid,'status':'canceled'}})
    collections = Mock(side_effect=[
        {'direct_debit_collections':[{'id':'rejected','status':'failed'}], 'meta':pagination},
        {'direct_debit_collections':[{'status':'completed'}], 'meta':{'next_page':0}},
    ])
    monkeypatch.setattr(gestion_app, 'list_qonto_direct_debit_collections', collections)
    assert search_third_party(third_party).status_code == 400
    assert collections.call_count == 2
    third_party[3].assert_not_called()


def test_canceled_subscription_missing_collection_list_fails_closed(third_party, monkeypatch):
    removed_installment(third_party, 'old-subscription')
    monkeypatch.setattr(gestion_app, 'get_qonto_direct_debit_subscription', lambda sid: {
        'direct_debit_subscription':{'id':sid,'status':'canceled'}})
    monkeypatch.setattr(gestion_app, 'list_qonto_direct_debit_collections', lambda *args, **kwargs: {'meta':{'next_page':0}})
    assert search_third_party(third_party).status_code == 400
    third_party[3].assert_not_called()


@pytest.mark.parametrize('old_status', ['failed', 'rejected', 'returned', 'refunded'])
def test_historical_rejected_debit_does_not_hide_verified_transfer(third_party, monkeypatch, old_status):
    link_unpaid_invoice(third_party, monkeypatch)
    removed_installment(third_party)['status'] = old_status
    client, data, trainee, fetch, detail = third_party
    data['billing_lines'][0]['financial_tracking_override'] = {'enabled':True, 'source':'inline_schedule'}
    response = assign_third_party(third_party)
    assert response.status_code == 200, response.json
    line = gestion_app._billing_lines(data)[0]
    assert line['qonto_invoice']['paid_amount_cents'] == 125000
    summary = gestion_app.calculate_trainee_financial_summary(trainee, [line])
    assert summary['paid_total_cents'] == 125000
    assert summary['remaining_total_cents'] == 0
    assert summary['qonto_payment_entries'][0]['transactions'][0]['payer_name'] == 'Aurore VERON'
    fetch.return_value[0]['status'] = 'reversed'
    gestion_app._sync_qonto_bank_transfers(data, force=True)
    line = gestion_app._billing_lines(data)[0]
    assert line['qonto_invoice']['paid_amount_cents'] == 0
    assert gestion_app.calculate_trainee_financial_summary(trainee, [line])['remaining_total_cents'] == 125000


@pytest.mark.parametrize('linked', [True, False])
def test_transfer_after_partial_debit_keeps_both_receipts_and_reversal(third_party, monkeypatch, linked):
    client, data, trainee, fetch, detail = third_party
    if linked:
        link_unpaid_invoice(third_party, monkeypatch)
    line = data['billing_lines'][0]
    line.update(paymentMode='sepa_direct_debit', directDebitInstallments=[
        {'amount': 400, 'status': 'completed', 'qonto_direct_debit_subscription_id': 'old',
         'qonto_direct_debit_collection_id': 'settled'},
        {'amount': 400, 'status': 'failed', 'qonto_direct_debit_subscription_id': 'old'},
        {'amount': 450, 'status': 'scheduled', 'manual_tracking_entry': True, 'tracking_pending_qonto': True},
    ])
    sub = {'id': 'old', 'status': 'completed'}
    monkeypatch.setattr(gestion_app, 'get_qonto_direct_debit_subscription', lambda sid: sub)
    ops = [{'id': 'settled', 'amount': {'value': '400.00'}, 'status': 'completed'},
           {'id': 'reject', 'status': 'declined'}]
    monkeypatch.setattr(gestion_app, 'list_qonto_direct_debit_collections', lambda **kw: {'collections': ops})
    search = search_third_party(third_party).json
    assert search['remaining_cents'] == search['available_cents'] == 85000
    assert 'selection_token' not in search['transactions'][0]
    fetch.return_value[0]['amount_cents'] = 85000
    saved = assign_third_party(third_party)
    assert saved.status_code == 200, saved.json
    assert saved.json['paid_cents'] == 125000 and saved.json['remaining_cents'] == 0
    assert data['billing_lines'][0]['paymentMode'] == 'sepa_direct_debit'
    def summary():
        return gestion_app.calculate_trainee_financial_summary(trainee, gestion_app._billing_lines(data))
    assert summary()['paid_total_cents'] == 125000
    assert gestion_app._session_financial_report(data, data['sessions'][0])['rows'][0]['invoices'][0]['paid'] == 1250
    fetch.return_value[0]['status'] = 'reversed'
    gestion_app._sync_qonto_bank_transfers(data, force=True)
    assert summary()['paid_total_cents'] == 40000
    assert summary()['remaining_total_cents'] == 85000
    assert data['billing_lines'][0]['paymentStatus'] == 'partially_paid'


def test_only_unreserved_balance_is_available_and_is_rechecked(third_party, monkeypatch):
    client, data, trainee, fetch, detail = third_party
    sub = {'id': 'plan', 'status': 'scheduled', 'schedule_type': 'monthly',
           'schedule_total_collection_count': 3, 'amount': {'value': '300.00', 'currency': 'EUR'}}
    data['billing_lines'][0].update(qonto_direct_debit_subscription_id='plan',
        directDebitInstallments=[{'amount': 300, 'status': 'completed',
                                 'qonto_direct_debit_subscription_id': 'plan', 'qonto_direct_debit_collection_id': 'paid'}])
    ops = [{'id': 'paid', 'status': 'completed', 'amount': {'value': '300'}},
           {'id': 'in-flight', 'status': 'on_hold', 'amount': {'value': '300'}}]
    monkeypatch.setattr(gestion_app, 'get_qonto_direct_debit_subscription', lambda sid: sub)
    monkeypatch.setattr(gestion_app, 'list_qonto_direct_debit_collections', lambda **kw: {'collections': ops})
    fetch.return_value[0]['amount_cents'] = 35001
    response = search_third_party(third_party)
    assert response.json['reserved_cents'] == 60000
    assert response.json['remaining_cents'] == 95000
    assert response.json['available_cents'] == 35000
    assert 'selection_token' not in response.json['transactions'][0]
    fetch.return_value[0]['amount_cents'] = 35000
    search = search_third_party(third_party)
    sub['schedule_total_collection_count'] += 1
    assert assign_third_party(third_party, search).status_code == 409
    assert not data['billing_lines'][0].get('qontoBankTransfers')


def test_whole_balance_reserved_shows_transfer_without_offering_assignment(third_party):
    third_party[1]['billing_lines'][0]['directDebitInstallments'] = [{'amount': 1250, 'status': 'scheduled'}]
    result = search_third_party(third_party).json
    assert result['available_cents'] == 0
    assert result['transactions'][0]['blocked_reason']
    assert 'selection_token' not in result['transactions'][0]
