import copy
import datetime
from unittest.mock import Mock

import pytest

import app as gestion_app


URL = '/internal/cron/qonto-sync'
HEADERS = {'X-Cron-Secret': 'test-qonto-cron'}


@pytest.fixture
def background(monkeypatch):
    data = {'sessions': [{
        'id': 'S-BACKGROUND', 'training_type': 'APS',
        'date_start': '2026-09-01', 'date_end': '2026-09-30',
        'trainees': [
            {'id': f'T-{i}', 'first_name': 'Test', 'last_name': str(i), 'personal_amount': 950}
            for i in range(2)
        ],
    }], 'billing_lines': []}
    for line in gestion_app._billing_lines(data):
        line.update(qontoInvoiceId='inv-' + line['traineeId'], invoiceStatus='finalized', paymentStatus='unpaid')
        gestion_app._save_billing_line(data, line)
    load = Mock(return_value=data)
    monkeypatch.setattr(gestion_app, 'load_data', load)
    monkeypatch.setattr(gestion_app, '_atomic_update_data', lambda update: update(data))
    monkeypatch.setattr(gestion_app, '_qonto_is_configured', lambda: True)
    monkeypatch.setenv('QONTO_SYNC_CRON_SECRET', 'test-qonto-cron')
    for name in ('create_qonto_invoice', 'create_qonto_direct_debit_subscription',
                 'send_qonto_invoice', '_refresh_cpf_link_from_wedof'):
        monkeypatch.setattr(gestion_app, name, Mock(side_effect=AssertionError('Unexpected write: ' + name)))
    remote = Mock(side_effect=lambda invoice_id: {'client_invoice': {
        'id': invoice_id, 'number': invoice_id, 'status': 'paid',
        'total_amount': {'value': '950.00'}, 'amount_paid': {'value': '950.00'},
    }})
    monkeypatch.setattr(gestion_app, 'get_qonto_invoice', remote)
    return gestion_app.app.test_client(), data, remote, load


@pytest.mark.parametrize('headers', [{}, {'X-Cron-Secret': 'wrong'}])
def test_cron_rejects_missing_or_wrong_secret(background, headers):
    client, _, remote, load = background
    assert client.post(URL, headers=headers).status_code == 403
    remote.assert_not_called()
    load.assert_not_called()


def test_secret_is_not_accepted_in_url(background):
    client, _, remote, _ = background
    assert client.post(URL + '?token=test-qonto-cron').status_code == 403
    remote.assert_not_called()


def test_updates_multiple_closed_records_without_admin_session(background):
    client, data, remote, load = background
    response = client.post(URL, headers=HEADERS)
    assert response.status_code == 200
    assert response.json['synced_count'] == 2
    assert response.json['remaining_count'] == 0
    assert {line['qonto_amount_paid_cents'] for line in data['billing_lines']} == {95000}
    assert data['qonto_background_sync_status']['synced_count'] == 2
    load.assert_called_once_with(run_background_tasks=False)
    assert remote.call_count == 2
    assert client.post(URL, headers=HEADERS).json['attempted_count'] == 0
    assert remote.call_count == 2


def test_limited_batch_moves_on_to_other_records(background, monkeypatch):
    client, _, remote, _ = background
    monkeypatch.setattr(gestion_app, 'QONTO_BACKGROUND_SYNC_MAX_LINES', 1)
    first = client.post(URL, headers=HEADERS)
    assert first.json['synced_count'] == 1
    assert first.json['remaining_count'] == 1
    second = client.post(URL, headers=HEADERS)
    assert second.json['synced_count'] == 1
    assert second.json['remaining_count'] == 0
    assert {call.args[0] for call in remote.call_args_list} == {'inv-T-0', 'inv-T-1'}


def test_api_failure_does_not_block_other_invoices_and_is_throttled(background):
    client, data, remote, _ = background
    success = remote.side_effect

    def fetch(invoice_id):
        if invoice_id == 'inv-T-0':
            raise RuntimeError('unavailable')
        return success(invoice_id)

    remote.side_effect = fetch
    response = client.post(URL, headers=HEADERS)
    assert response.status_code == 200
    assert response.json['synced_count'] == 1
    assert response.json['failed_count'] == 1
    assert next(line for line in data['billing_lines'] if line['traineeId'] == 'T-1')['qonto_amount_paid_cents'] == 95000
    assert client.post(URL, headers=HEADERS).json['attempted_count'] == 0
    assert remote.call_count == 2


def test_concurrent_edit_wins_over_background_result(background, monkeypatch):
    client, data, _, _ = background
    changed_id = data['billing_lines'][0]['id']

    def save_after_edit(update):
        data['billing_lines'][0]['clientName'] = 'Recipient edited during synchronization'
        return update(data)

    monkeypatch.setattr(gestion_app, '_atomic_update_data', save_after_edit)
    response = client.post(URL, headers=HEADERS)
    assert response.status_code == 200
    assert response.json['conflict_count'] == 1
    assert response.json['synced_count'] == 1
    line = next(line for line in data['billing_lines'] if line['id'] == changed_id)
    assert line['clientName'] == 'Recipient edited during synchronization'
    assert line.get('qonto_amount_paid_cents', 0) == 0


def test_new_webhook_payment_wins_over_earlier_qonto_response(background, monkeypatch):
    client, data, _, _ = background

    def save_after_webhook(update):
        data['billing_lines'][0]['qonto_amount_paid_cents'] = 44500
        data['billing_lines'][0]['qontoLastSyncedAt'] = gestion_app._now_iso()
        return update(data)

    monkeypatch.setattr(gestion_app, '_atomic_update_data', save_after_webhook)
    response = client.post(URL, headers=HEADERS)
    assert response.json['conflict_count'] == 1
    assert data['billing_lines'][0]['qonto_amount_paid_cents'] == 44500


def test_mandate_without_invoice_is_reconciled_without_scheduling(background, monkeypatch):
    client, data, _, _ = background
    line = data['billing_lines'][0]
    line.update(qontoInvoiceId=None, qontoDraftId=None, paymentMode='sepa_direct_debit',
                qonto_direct_debit_mandate_id='mandate-background')

    def refresh(debit_line, *, create_missing_subscriptions):
        assert create_missing_subscriptions is False
        debit_line['qonto_mandate_status'] = 'active'
        debit_line['qontoDirectDebitLastSyncedAt'] = gestion_app._now_iso()
        return {'errors': [], 'warning': ''}

    sync_debit = Mock(side_effect=refresh)
    monkeypatch.setattr(gestion_app, '_sync_qonto_direct_debit_line', sync_debit)
    response = client.post(URL, headers=HEADERS)
    assert response.json['synced_count'] == 2
    assert data['billing_lines'][0]['qonto_mandate_status'] == 'active'
    assert sync_debit.call_count == 1


def test_historical_persisted_invoice_is_not_lost_from_queue(background):
    client, data, remote, _ = background
    historical = copy.deepcopy(data['billing_lines'][0])
    historical.update(id='historical-line', traineeId='T-HISTORICAL', sessionId='S-HISTORICAL', qontoInvoiceId='inv-historical')
    data['billing_lines'].append(historical)
    response = client.post(URL, headers=HEADERS)
    assert response.json['synced_count'] == 3
    assert 'inv-historical' in {call.args[0] for call in remote.call_args_list}


def test_paid_invoice_is_checked_daily_instead_of_every_five_minutes(background):
    client, data, remote, _ = background
    line = data['billing_lines'][0]
    line.update(paymentStatus='paid', invoiceStatus='paid', qonto_amount_paid_cents=95000,
                qontoLastSyncedAt=(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=4)).isoformat())
    response = client.post(URL, headers=HEADERS)
    assert response.json['synced_count'] == 1
    remote.assert_called_once_with('inv-T-1')


def test_time_budget_leaves_remaining_work_for_next_run(background, monkeypatch):
    _, _, remote, _ = background
    clock = Mock(wraps=gestion_app.time)
    clock.monotonic = Mock(side_effect=[0, 0, 121])
    monkeypatch.setattr(gestion_app, 'time', clock)
    result = gestion_app.run_qonto_background_sync()
    assert result['synced_count'] == 1
    assert result['remaining_count'] == 1
    assert remote.call_count == 1


def test_overlapping_cron_is_skipped(background):
    client, _, remote, load = background
    with gestion_app._qonto_background_sync_lock:
        response = client.post(URL, headers=HEADERS)
    assert response.json == {'ok': True, 'status': 'already_running'}
    remote.assert_not_called()
    load.assert_not_called()


def test_missing_qonto_configuration_fails_without_fetching_data(background, monkeypatch):
    client, _, remote, load = background
    monkeypatch.setattr(gestion_app, '_qonto_is_configured', lambda: False)
    assert client.post(URL, headers=HEADERS).status_code == 503
    remote.assert_not_called()
    load.assert_not_called()


def test_total_api_failure_is_visible_to_scheduler(background):
    client, _, remote, _ = background
    remote.side_effect = RuntimeError('Qonto offline')
    response = client.post(URL, headers=HEADERS)
    assert response.status_code == 503
    assert response.json['failed_count'] == 2
    assert response.json['synced_count'] == 0
