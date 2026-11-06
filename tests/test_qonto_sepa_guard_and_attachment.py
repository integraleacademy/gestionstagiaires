import copy
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

import app as gestion
from qonto_sepa_guard import ensure_subscription


def test_two_concurrent_stale_snapshots_create_once(tmp_path):
    create = Mock(return_value={'subscription': {'id': 'sub'}})
    def run():
        return ensure_subscription(tmp_path, 'mandate:line:1', {'amount': 490}, lambda: '', create)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sorted(results) == [('sub', False), ('sub', True)]
    create.assert_called_once()


def test_timeout_never_repeats_post_and_can_recover_remote_result(tmp_path):
    create = Mock(side_effect=TimeoutError('Response lost after Qonto accepted'))
    with pytest.raises(TimeoutError):
        ensure_subscription(tmp_path, 'key', {}, lambda: '', create)
    with pytest.raises(ValueError, match='précédente'):
        ensure_subscription(tmp_path, 'key', {}, lambda: '', create)
    assert ensure_subscription(tmp_path, 'key', {}, lambda: 'found', create) == ('found', False)
    create.assert_called_once()
    with pytest.raises(ValueError, match='paramètres'):
        ensure_subscription(tmp_path, 'key', {'amount': 1}, lambda: '', create)


@pytest.fixture
def line():
    return {'id': 'bill_test', 'traineeId': 'trainee', 'sessionId': 'session',
            'financingType': 'PERSONNEL', 'amount': 980, 'amountTTC': 980,
            'paymentMode': 'sepa_direct_debit', 'invoiceStatus': 'finalized',
            'qontoInvoiceNumber': 'FL-1-PROFORMA', 'qontoClientId': 'client',
            'qonto_direct_debit_mandate_id': 'mandate', 'qonto_mandate_rum': 'RUM',
            'qonto_mandate_status': 'active',
            'directDebitInstallments': [{'index': 1, 'schedule_index': 1,
                'date': '2026-10-21', 'amount': 490, 'status': 'completed',
                'qonto_direct_debit_subscription_id': 'sub-old', 'qonto_direct_debit_collection_id': 'col-old'}]}


def test_invoice_after_mandate_reuses_original_bill_reference(tmp_path, monkeypatch, line):
    line['directDebitInstallments'] = [{'index': 1, 'date': '2026-11-04', 'amount': 490}]
    monkeypatch.setattr(gestion, 'PERSIST_DIR', str(tmp_path))
    monkeypatch.setattr(gestion, '_ensure_qonto_oauth_ready', lambda: None)
    monkeypatch.setattr(gestion, 'get_qonto_bank_account_id', lambda: 'bank')
    monkeypatch.setattr(gestion, 'list_qonto_direct_debit_subscriptions', lambda *a, **k: {'subscriptions': [{
        'id': 'existing', 'direct_debit_mandate_id': 'mandate', 'reference': 'bill_test - échéance 1/1',
        'initial_collection_date': '2026-11-04', 'amount': {'value': '490.00', 'currency': 'EUR'}}]})
    create = Mock(side_effect=AssertionError('No Qonto POST allowed'))
    monkeypatch.setattr(gestion, 'create_qonto_direct_debit_subscription', create)
    result = gestion.ensure_qonto_sepa_installments_for_line(line)
    assert result['created'] == 0
    assert gestion._sepa_installments(line)[0]['qonto_direct_debit_subscription_id'] == 'existing'
    create.assert_not_called()


def test_distinct_paid_collections_of_one_slot_are_not_hidden(line):
    row = copy.deepcopy(line['directDebitInstallments'][0])
    row.update(qonto_direct_debit_collection_id='col-two', qonto_direct_debit_subscription_id='sub-two')
    line['directDebitInstallments'].append(row)
    gestion._sync_sepa_aliases(line)
    assert gestion._reconciled_qonto_paid_cents(line, 0) == 98000
    assert line['sepa_payment_plan']['total_paid'] == 980
    assert line['qontoDuplicateDebitWarning']
    assert all(item['duplicate_qonto_schedule'] for item in line['directDebitInstallments'])
    line['directDebitInstallments'].append(copy.deepcopy(row))
    assert gestion._reconciled_qonto_paid_cents(line, 0) == 98000


def test_invoice_generation_preserves_already_programmed_schedule(monkeypatch, line):
    before = copy.deepcopy(line['directDebitInstallments'])
    ensure = Mock(return_value={'created': 0})
    monkeypatch.setattr(gestion, 'ensure_qonto_sepa_installments_for_line', ensure)
    monkeypatch.setattr(gestion, '_active_qonto_mandate', Mock(side_effect=AssertionError('No new mandate')))
    gestion._setup_qonto_direct_debit_for_line(line, {'mode': 'cash', 'schedule': []})
    assert line['directDebitInstallments'][0]['qonto_direct_debit_collection_id'] == before[0]['qonto_direct_debit_collection_id']
    assert line['paymentMode'] == 'sepa_direct_debit'
    ensure.assert_called_once_with(line)


@pytest.fixture
def attachment(monkeypatch, line):
    data = {'billing_lines': [line]}
    remote = {'id': 'col-new', 'direct_debit_subscription_id': 'sub-new',
              'unique_mandate_reference': 'RUM', 'collection_date': '2026-11-03',
              'amount': {'value': '490.00', 'currency': 'EUR'}, 'status': 'completed',
              'reference': 'Règlement créé dans Qonto'}
    monkeypatch.setattr(gestion, 'load_data', lambda *a, **k: copy.deepcopy(data))
    monkeypatch.setattr(gestion, '_find_billing_line', lambda d, key: next((row for row in d['billing_lines'] if row['id'] == key), None))
    monkeypatch.setattr(gestion, '_qonto_background_lines', lambda d: {row['id']: row for row in d['billing_lines']})
    monkeypatch.setattr(gestion, '_atomic_update_data', lambda mutate: mutate(data))
    monkeypatch.setattr(gestion, '_save_billing_line', lambda d, row: d['billing_lines'].__setitem__(0, row))
    monkeypatch.setattr(gestion, 'get_qonto_direct_debit_mandate', lambda _: {'direct_debit_mandate': {
        'id': 'mandate', 'client_id': 'client', 'unique_mandate_reference': 'RUM'}})
    monkeypatch.setattr(gestion, '_all_qonto_direct_debit_collections_for_rum', lambda _: [copy.deepcopy(remote)])
    monkeypatch.setattr(gestion, '_qonto_request', Mock(side_effect=AssertionError('No remote mutation')))
    gestion.app.config.update(TESTING=True, SECRET_KEY='test-key')
    client = gestion.app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
        session['admin_role'] = 'admin'
    return client, data, remote


def search(client):
    response = client.post('/api/billing/direct-debits/search', json={'lineId': 'bill_test'})
    assert response.status_code == 200, response.json
    return response.json['collections']


def test_attach_external_payment_once_and_update_balance(attachment):
    client, data, _ = attachment
    token = search(client)[0]['selection_token']
    response = client.post('/api/billing/direct-debits/attach', json={'selectionToken': token})
    assert response.status_code == 200, response.json
    assert response.json['remaining_cents'] == 0
    target = data['billing_lines'][0]
    assert target['paymentStatus'] == 'paid'
    assert target['financial_tracking_override']['enabled']
    assert target['directDebitInstallments'][-1]['qonto_direct_debit_collection_id'] == 'col-new'
    assert client.post('/api/billing/direct-debits/attach', json={'selectionToken': token}).status_code == 409
    assert search(client) == []
    gestion._qonto_request.assert_not_called()


@pytest.mark.parametrize('change', ['returned', 'amount', 'owner', 'line'])
def test_rechecks_remote_and_local_state_before_attachment(attachment, change):
    client, data, remote = attachment
    token = search(client)[0]['selection_token']
    if change == 'returned':
        remote['status'] = 'returned'
    elif change == 'amount':
        remote['amount']['value'] = '500'
    elif change == 'owner':
        other = copy.deepcopy(data['billing_lines'][0]); other['id'] = 'other'
        other['directDebitInstallments'][0]['qonto_direct_debit_collection_id'] = 'col-new'
        data['billing_lines'].append(other)
    else:
        data['billing_lines'][0]['amountTTC'] = 900
    response = client.post('/api/billing/direct-debits/attach', json={'selectionToken': token})
    assert response.status_code == 409, response.json
    assert len(data['billing_lines'][0]['directDebitInstallments']) == 1


def test_attachment_refuses_tampered_token_and_readonly_user(attachment):
    client, _, _ = attachment
    assert client.post('/api/billing/direct-debits/attach', json={'selectionToken': 'tampered'}).status_code == 409
    with client.session_transaction() as session:
        session['admin_role'] = 'viewer'
    assert client.post('/api/billing/direct-debits/search', json={'lineId': 'bill_test'}).status_code == 403
