import copy
from contextlib import ExitStack
from unittest.mock import patch

import pytest

import app as gestion_app

REAL_BILLING_LINES = gestion_app._billing_lines


@pytest.fixture
def editor():
    rows = [
        {'date': '2026-08-29', 'amount': 1146.66, 'status': 'failed', 'index': 1,
         'rejection_treated': True, 'excluded_from_schedule_totals': True,
         'qonto_direct_debit_subscription_id': 'OLD'},
        {'date': '2026-09-05', 'amount': 1146.66, 'status': 'failed', 'index': 1,
         'is_rejection_retry': True, 'qonto_direct_debit_subscription_id': 'RETRY'},
        {'date': '2026-09-29', 'amount': 1146.66, 'status': 'scheduled', 'index': 2,
         'qonto_direct_debit_subscription_id': 'FUTURE'},
        {'date': '2026-10-29', 'amount': 1146.68, 'status': 'scheduled', 'index': 3,
         'qonto_direct_debit_subscription_id': 'LAST'},
    ]
    line = {'id': 'L1', 'traineeId': 'T1', 'sessionId': 'S1',
            'financingType': 'PERSONNEL', 'amount': 3440, 'amountTTC': 3440,
            'paymentMode': 'sepa_direct_debit', 'qonto_direct_debit_mandate_id': 'MANDATE',
            'qonto_mandate_status': 'active', 'qontoClientId': 'CLIENT',
            'directDebitInstallments': rows,
            'sepa_payment_plan': {'installments': copy.deepcopy(rows)}}
    data = {'billing_lines': [line]}
    client = gestion_app.app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
        session['admin_role'] = 'admin'
    with ExitStack() as stack:
        stack.enter_context(patch.object(gestion_app, 'load_data', return_value=data))
        stack.enter_context(patch.object(gestion_app, '_billing_lines', return_value=[line]))
        stack.enter_context(patch.object(gestion_app, '_billing_lines_for_trainee_session',
                                       side_effect=lambda d, tid, sid: [line] if (tid, sid) == ('T1', 'S1') else []))
        stack.enter_context(patch.object(gestion_app, '_financing_partner_module_enabled', return_value=True))
        saved = stack.enter_context(patch.object(gestion_app, 'save_data'))
        def atomic(mutator):
            before = copy.deepcopy(data)
            result = mutator(data)
            if data != before:
                saved(data)
            return result
        stack.enter_context(patch.object(gestion_app, '_atomic_update_data', side_effect=atomic))
        remote = stack.enter_context(patch.object(gestion_app, '_qonto_request', side_effect=AssertionError('No bank writes allowed')))
        yield client, line, data, saved, remote
        remote.assert_not_called()


def send(editor, action, **details):
    client, line, *_ = editor
    return client.post('/api/billing/installments', json={
        'scope': 'tracking', 'lineId': 'L1', 'traineeId': 'T1', 'sessionId': 'S1',
        'expectedSchedule': gestion_app._installment_edit_snapshot(line),
        'action': action, **details,
    })


def test_date_edit_preserves_qonto_links_history_and_persistence_aliases(editor):
    result = send(editor, 'update', installmentIndex=2, date='2026-10-03')
    assert result.status_code == 200
    _, line, data, *_ = editor
    rows = line['directDebitInstallments']
    assert rows is line['sepa_payment_plan']['installments']
    assert rows[2]['date'] == rows[2]['due_date'] == '2026-10-03'
    assert rows[2]['qonto_original_due_date'] == '2026-09-29'
    assert rows[2]['qonto_direct_debit_subscription_id'] == 'FUTURE'
    assert rows[0]['status'] == rows[1]['status'] == 'failed'
    assert line['sepa_payment_plan']['total_due'] == 3440
    assert data['billing_lines'][0]['directDebitInstallments'][2]['date'] == '2026-10-03'
    assert line['financial_tracking_override']['edit_history'][0]['before'][2]['date'] == '2026-09-29'


def test_delete_add_and_delete_last_row_keep_history_but_recompute_counts(editor):
    assert send(editor, 'delete', installmentIndex=2).status_code == 200
    line = editor[1]
    assert line['sepa_payment_plan']['total_installments'] == 2
    assert line['sepa_payment_plan']['total_due'] == 2293.34
    assert len(line['directDebitInstallments']) == 4
    assert send(editor, 'add', date='2026-11-10', amount=600).status_code == 200
    assert line['sepa_payment_plan']['total_installments'] == 3
    assert line['sepa_payment_plan']['total_due'] == 2893.34
    assert line['directDebitInstallments'][-1]['tracking_pending_qonto']
    assert not line['directDebitInstallments'][-1].get('qonto_direct_debit_subscription_id')
    for index in (1, 3, 4):
        assert send(editor, 'delete', installmentIndex=index).status_code == 200
    assert line['sepa_payment_plan']['total_installments'] == 0
    assert line['sepa_payment_plan']['total_due'] == 0
    assert gestion_app._effective_sepa_installments(line) == []
    assert send(editor, 'add', date='2026-12-01', amount=3440).status_code == 200
    assert len(gestion_app._effective_sepa_installments(line)) == 1
    assert line['sepa_payment_plan']['total_due'] == 3440


def test_amount_only_edit_recomputes_totals_and_preserves_original_bank_amount(editor):
    assert send(editor, 'update', installmentIndex=2, amount='900,25').status_code == 200
    _, line, data, saved, _ = editor
    row = line['directDebitInstallments'][2]
    assert row['date'] == row['due_date'] == '2026-09-29'
    assert row['amount'] == 900.25
    assert row['qonto_original_amount'] == 1146.66
    assert row['tracking_pending_qonto'] is True
    assert line['sepa_payment_plan']['total_due'] == 3193.59
    assert line['sepa_payment_plan']['total_installments'] == 3
    assert line['paymentPlan']['schedule'][1]['amount'] == 900.25
    assert data['billing_lines'][0]['directDebitInstallments'][2]['amount'] == 900.25
    audit = line['financial_tracking_override']['edit_history'][0]
    assert audit['before'][2]['amount'] == 1146.66
    assert audit['after'][2]['amount'] == 900.25
    saved.reset_mock()
    assert send(editor, 'update', installmentIndex=2, amount=900.25).status_code == 200
    saved.assert_not_called()
    assert send(editor, 'update', installmentIndex=2, amount=800).status_code == 200
    assert row['qonto_original_amount'] == 1146.66


def test_stale_schedule_wrong_trainee_and_duplicate_add_do_not_save(editor):
    assert send(editor, 'update', installmentIndex=2, date='2026-10-03', expectedSchedule=[]).status_code == 409
    assert send(editor, 'delete', installmentIndex=2, traineeId='T2').status_code == 404
    assert send(editor, 'add', date='2026-09-29', amount=1146.66).status_code == 409
    editor[3].assert_not_called()


@pytest.mark.parametrize('action,details', [
    ('update', {'installmentIndex': 0, 'date': '2026-11-01'}),
    ('update', {'installmentIndex': 1, 'date': '2026-11-01'}),
    ('update', {'installmentIndex': 2, 'date': '2026-02-30'}),
    ('add', {'date': '2026-12-01', 'amount': -5}),
    ('add', {'date': '2026-12-01', 'amount': 'NaN'}),
    ('add', {'date': '2026-12-01', 'amount': 1.234}),
    *[('update', {'installmentIndex': 2, 'amount': value})
      for value in (-5, 0, '', None, 'NaN', 'Infinity', 1.234, 1000000.01)],
])
def test_invalid_or_historical_changes_are_rejected(editor, action, details):
    before = copy.deepcopy(editor[1])
    assert send(editor, action, **details).status_code in (400, 409)
    assert editor[1] == before
    editor[3].assert_not_called()


def test_paid_row_and_readonly_admin_are_protected(editor):
    line = editor[1]
    gestion_app._sepa_installments(line)[2]['status'] = 'completed'
    assert send(editor, 'delete', installmentIndex=2).status_code == 409
    assert send(editor, 'update', installmentIndex=2, amount=100).status_code == 409
    with editor[0].session_transaction() as session:
        session['admin_role'] = 'viewer'
    assert send(editor, 'add', date='2026-12-01', amount=100).status_code == 403
    assert send(editor, 'update', installmentIndex=3, amount=100).status_code == 403
    editor[3].assert_not_called()


def test_automatic_creation_is_disabled_for_manually_edited_schedule(editor):
    assert send(editor, 'add', date='2026-12-01', amount=100).status_code == 200
    result = gestion_app.ensure_qonto_sepa_installments_for_line(editor[1])
    assert result['manual_tracking'] is True
    assert result['created'] == 0


def test_bank_payment_restores_removed_row_without_counting_another_slot_twice(editor):
    assert send(editor, 'delete', installmentIndex=2).status_code == 200
    _, line, data, *_ = editor
    event = {'id': 'COLL', 'direct_debit_subscription_id': 'FUTURE', 'status': 'completed',
             'collection_date': '2026-09-29'}
    assert gestion_app._apply_qonto_collection_webhook(data, event)
    effective = gestion_app._effective_sepa_installments(line)
    assert len(effective) == 3
    assert sum(row['amount'] for row in effective if row['status'] == 'completed') == 1146.66


def test_qonto_sync_keeps_changed_tracking_date_for_pending_collection(editor):
    assert send(editor, 'update', installmentIndex=2, date='2026-10-03').status_code == 200
    line = editor[1]
    collection = {'id': 'COLL', 'direct_debit_subscription_id': 'FUTURE', 'status': 'pending',
                  'collection_date': '2026-09-29'}
    with patch.object(gestion_app, '_resolve_qonto_direct_debit_mandate_for_line', return_value={}), \
         patch.object(gestion_app, 'list_qonto_direct_debit_collections',
                      side_effect=lambda sid: {'direct_debit_collections': [collection] if sid == 'FUTURE' else []}):
        gestion_app._sync_qonto_direct_debit_line(line)
    row = line['directDebitInstallments'][2]
    assert row['date'] == row['due_date'] == '2026-10-03'
    assert row['tracking_pending_qonto'] is True


@pytest.mark.parametrize('channel', ['sync', 'webhook'])
@pytest.mark.parametrize('status,bank_amount,expected_amount,pending', [
    ('pending', 1146.66, 900.25, True),
    ('pending', None, 900.25, True),
    ('pending', 900.25, 900.25, False),
    ('completed', 1146.66, 1146.66, False),
    ('completed', None, 1146.66, False),
    ('completed', 900.25, 900.25, False),
])
def test_bank_sync_preserves_pending_edits_and_uses_actual_paid_amount(
        editor, channel, status, bank_amount, expected_amount, pending):
    assert send(editor, 'update', installmentIndex=2, amount=900.25).status_code == 200
    _, line, data, *_ = editor
    collection = {'id': 'COLL', 'direct_debit_subscription_id': 'FUTURE', 'status': status,
                  'collection_date': '2026-09-29'}
    if bank_amount is not None:
        collection['amount'] = {'value': str(bank_amount), 'currency': 'EUR'}
    if channel == 'sync':
        with patch.object(gestion_app, '_resolve_qonto_direct_debit_mandate_for_line', return_value={}), \
             patch.object(gestion_app, 'list_qonto_direct_debit_collections',
                          side_effect=lambda sid: {'direct_debit_collections': [collection] if sid == 'FUTURE' else []}):
            gestion_app._sync_qonto_direct_debit_line(line)
    else:
        assert gestion_app._apply_qonto_collection_webhook(data, collection)
    row = line['directDebitInstallments'][2]
    assert row['amount'] == expected_amount
    assert bool(row.get('tracking_pending_qonto')) is pending
    assert ('qonto_original_amount' in row) is pending
    assert line['sepa_payment_plan']['total_due'] == round(2293.34 + expected_amount, 2)
    if status == 'completed':
        assert line['sepa_payment_plan']['total_paid'] == expected_amount


def test_payment_without_amount_uses_latest_bank_confirmation(editor):
    assert send(editor, 'update', installmentIndex=2, amount=900.25).status_code == 200
    _, line, data, *_ = editor
    collection = {'id': 'COLL', 'direct_debit_subscription_id': 'FUTURE', 'status': 'pending',
                  'collection_date': '2026-09-29', 'amount': {'value': '950.00'}}
    assert gestion_app._apply_qonto_collection_webhook(data, collection)
    row = line['directDebitInstallments'][2]
    assert row['amount'] == 900.25
    assert row['qonto_original_amount'] == 950
    collection.update(status='completed')
    collection.pop('amount')
    assert gestion_app._apply_qonto_collection_webhook(data, collection)
    assert row['amount'] == line['sepa_payment_plan']['total_paid'] == 950
    assert not row.get('tracking_pending_qonto')


def test_persisted_changes_survive_real_billing_line_reconstruction(editor):
    _, template_line, data, *_ = editor
    data['sessions'] = [{'id': 'S1', 'training_type': 'APS', 'date_start': '2026-09-01', 'date_end': '2026-10-01', 'trainees': [
        {'id': 'T1', 'first_name': 'Test', 'last_name': 'Échéancier', 'personal_amount': 3440}
    ]}]
    data['billing_lines'] = []
    generated = next(line for line in REAL_BILLING_LINES(data) if line['financingType'] == 'PERSONNEL')
    generated.update({key: copy.deepcopy(value) for key, value in template_line.items() if key != 'id'})
    data['billing_lines'] = [generated]
    with patch.object(gestion_app, '_billing_lines', side_effect=REAL_BILLING_LINES), \
         patch.object(gestion_app, '_billing_lines_for_trainee_session', side_effect=lambda d, tid, sid: REAL_BILLING_LINES(d)):
        for action, details in [('update', {'installmentIndex': 2, 'date': '2026-10-03', 'amount': 900}),
                                ('delete', {'installmentIndex': 3}),
                                ('add', {'date': '2026-12-01', 'amount': 500})]:
            line = next(item for item in REAL_BILLING_LINES(data) if item['id'] == generated['id'])
            response = editor[0].post('/api/billing/installments', json={
                'scope': 'tracking', 'lineId': line['id'], 'traineeId': 'T1', 'sessionId': 'S1',
                'action': action, 'expectedSchedule': gestion_app._installment_edit_snapshot(line), **details,
            })
            assert response.status_code == 200, response.get_json()
        rebuilt = next(item for item in REAL_BILLING_LINES(data) if item['id'] == generated['id'])
    assert rebuilt['directDebitInstallments'][2]['date'] == '2026-10-03'
    assert rebuilt['directDebitInstallments'][2]['amount'] == 900
    assert rebuilt['directDebitInstallments'][3]['tracking_removed_at']
    assert rebuilt['directDebitInstallments'][-1]['amount'] == 500
    assert rebuilt['sepa_payment_plan']['total_due'] == 2546.66
    assert rebuilt['sepa_payment_plan']['total_installments'] == 3
