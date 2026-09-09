from copy import deepcopy
from unittest.mock import Mock

import pytest

import app as gestion_app


URL = '/api/billing/trainee/T-AUTO/session/S-AUTO'
OLD = '2020-01-01T00:00:00Z'


@pytest.fixture
def finance(monkeypatch):
    data = {
        'sessions': [{
            'id': 'S-AUTO', 'training_type': 'APS',
            'date_start': '2026-09-01', 'date_end': '2026-09-30',
            'trainees': [{
                'id': 'T-AUTO', 'first_name': 'Alice', 'last_name': 'Test',
                'personal_amount': 950,
            }],
        }],
        'billing_lines': [],
    }
    line = gestion_app._billing_lines(data)[0]
    line.update(qontoInvoiceId='inv-auto', invoiceStatus='finalized', paymentStatus='unpaid')
    gestion_app._save_billing_line(data, line)
    monkeypatch.setattr(gestion_app, 'load_data', lambda: data)
    monkeypatch.setattr(gestion_app, 'save_data', Mock())
    monkeypatch.setattr(gestion_app, '_qonto_is_configured', lambda: True)
    # Fail immediately if automatic reads ever schedule or send something.
    for name in (
        'create_qonto_invoice', 'create_qonto_direct_debit_subscription',
        '_send_qonto_mandate_link', '_refresh_cpf_link_from_wedof',
    ):
        monkeypatch.setattr(gestion_app, name, Mock(side_effect=AssertionError(name)))
    client = gestion_app.app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
        session['admin_role'] = 'admin'
    return client, data


def invoice(paid=950):
    return {'client_invoice': {
        'id': 'inv-auto', 'number': 'F-AUTO',
        'status': 'paid' if paid == 950 else 'finalized',
        'total_amount': {'value': '950.00'},
        'amount_paid': {'value': str(paid)},
    }}


def test_personal_payment_refreshes_again_after_five_minutes_in_same_browser(finance, monkeypatch):
    client, data = finance
    get_invoice = Mock(side_effect=[invoice(300), invoice(950)])
    monkeypatch.setattr(gestion_app, 'get_qonto_invoice', get_invoice)

    first = client.get(URL)
    assert first.status_code == 200
    assert first.json['financial_summary']['paid_total_cents'] == 30000
    assert client.get(URL).json['financial_summary']['paid_total_cents'] == 30000
    assert get_invoice.call_count == 1

    # Elapsed TTL, while keeping exactly the same authenticated browser session.
    data['billing_lines'][0]['qontoLastSyncedAt'] = OLD
    data['billing_lines'][0]['qontoAutoSyncAttemptedAt'] = OLD
    second = client.get(URL)
    assert second.json['financial_summary']['paid_total_cents'] == 95000
    assert second.json['lines'][0]['qonto_invoice']['remaining_amount_cents'] == 0
    assert get_invoice.call_count == 2


def test_failure_keeps_payment_then_retries_without_manual_button(finance, monkeypatch):
    client, data = finance
    get_invoice = Mock(side_effect=[invoice(300), RuntimeError('Qonto unavailable'), invoice(950)])
    monkeypatch.setattr(gestion_app, 'get_qonto_invoice', get_invoice)
    client.get(URL)
    data['billing_lines'][0].update(qontoLastSyncedAt=OLD, qontoAutoSyncAttemptedAt=OLD)

    failed = client.get(URL)
    assert failed.status_code == 200
    assert failed.json['financial_summary']['paid_total_cents'] == 30000
    assert 'nouvelle tentative automatique' in failed.json['lines'][0]['syncWarning']
    client.get(URL)
    assert get_invoice.call_count == 2

    data['billing_lines'][0]['qontoAutoSyncAttemptedAt'] = OLD
    recovered = client.get(URL)
    assert recovered.json['financial_summary']['paid_total_cents'] == 95000
    assert not recovered.json['lines'][0]['syncWarning']
    assert get_invoice.call_count == 3


def setup_mandate(data, monkeypatch, *, with_invoice=False):
    line = data['billing_lines'][0]
    if not with_invoice:
        line.update(qontoInvoiceId=None, qontoDraftId=None)
    line.update(
        paymentMode='sepa_direct_debit',
        qonto_direct_debit_mandate_id='mandate-auto',
        directDebitInstallments=[{
            'date': '2026-09-09', 'due_date': '2026-09-09', 'amount': 950,
            'status': 'scheduled', 'index': 1,
            'qonto_direct_debit_subscription_id': 'subscription-auto',
        }],
    )
    monkeypatch.setattr(gestion_app, '_resolve_qonto_direct_debit_mandate_for_line',
                        Mock(return_value={'id': 'mandate-auto', 'status': 'active'}))
    monkeypatch.setattr(gestion_app, '_recover_qonto_installments_for_mandate', Mock(return_value=0))
    monkeypatch.setattr(gestion_app, '_recover_missing_qonto_rejection_retries', Mock(return_value=0))
    collections = Mock(return_value={'direct_debit_collections': [{
        'id': 'collection-auto', 'status': 'completed', 'amount_cents': 95000,
        'due_date': '2026-09-09', 'paid_at': '2026-09-09T04:00:00Z',
    }]})
    monkeypatch.setattr(gestion_app, 'list_qonto_direct_debit_collections', collections)
    return collections


def test_mandate_without_invoice_refreshes_and_never_schedules_a_debit(finance, monkeypatch):
    client, data = finance
    collections = setup_mandate(data, monkeypatch)
    ensure = Mock(side_effect=AssertionError('Automatic reading must not schedule debits'))
    monkeypatch.setattr(gestion_app, 'ensure_qonto_sepa_installments_for_line', ensure)

    response = client.get(URL)
    assert response.status_code == 200
    line = response.json['lines'][0]
    assert line['qonto_mandate_status'] == 'active'
    assert line['directDebitInstallments'][0]['status'] == 'completed'
    assert line['qontoDirectDebitLastSyncedAt']
    ensure.assert_not_called()
    collections.assert_called_once_with('subscription-auto')
    client.get(URL)
    assert collections.call_count == 1


def test_recent_invoice_webhook_does_not_postpone_stale_mandate(finance, monkeypatch):
    client, data = finance
    collections = setup_mandate(data, monkeypatch, with_invoice=True)
    data['billing_lines'][0]['qontoLastSyncedAt'] = gestion_app._now_iso()
    get_invoice = Mock(side_effect=AssertionError('Invoice already fresh'))
    monkeypatch.setattr(gestion_app, 'get_qonto_invoice', get_invoice)

    response = client.get(URL)
    assert response.status_code == 200
    assert response.json['lines'][0]['directDebitInstallments'][0]['status'] == 'completed'
    get_invoice.assert_not_called()
    collections.assert_called_once_with('subscription-auto')


def test_invoice_failure_does_not_block_mandate_reconciliation(finance, monkeypatch):
    client, data = finance
    collections = setup_mandate(data, monkeypatch, with_invoice=True)
    get_invoice = Mock(side_effect=RuntimeError('invoice temporarily unavailable'))
    monkeypatch.setattr(gestion_app, 'get_qonto_invoice', get_invoice)

    response = client.get(URL)
    assert response.status_code == 200
    assert response.json['lines'][0]['directDebitInstallments'][0]['status'] == 'completed'
    assert response.json['lines'][0]['syncWarning']
    collections.assert_called_once_with('subscription-auto')


def test_refresh_is_scoped_to_one_registration(finance, monkeypatch):
    client, data = finance
    other = deepcopy(data['sessions'][0]['trainees'][0])
    other['id'] = 'T-OTHER'
    data['sessions'][0]['trainees'].append(other)
    other_line = gestion_app._billing_lines_for_trainee_session(data, 'T-OTHER', 'S-AUTO')[0]
    other_line.update(qontoInvoiceId='inv-other', invoiceStatus='finalized')
    gestion_app._save_billing_line(data, other_line)
    get_invoice = Mock(return_value=invoice())
    monkeypatch.setattr(gestion_app, 'get_qonto_invoice', get_invoice)

    response = client.get(URL)
    assert response.status_code == 200
    get_invoice.assert_called_once_with('inv-auto')
    assert {line['traineeId'] for line in response.json['lines']} == {'T-AUTO'}
    client.get('/api/billing/trainee/T-MISSING/session/S-AUTO')
    get_invoice.assert_called_once_with('inv-auto')


def test_unconfigured_qonto_preserves_local_display(finance, monkeypatch):
    client, _ = finance
    monkeypatch.setattr(gestion_app, '_qonto_is_configured', lambda: False)
    get_invoice = Mock(side_effect=AssertionError('Qonto not configured'))
    monkeypatch.setattr(gestion_app, 'get_qonto_invoice', get_invoice)
    assert client.get(URL).status_code == 200
    get_invoice.assert_not_called()


def test_refresh_still_requires_authentication(finance, monkeypatch):
    get_invoice = Mock()
    monkeypatch.setattr(gestion_app, 'get_qonto_invoice', get_invoice)
    response = gestion_app.app.test_client().get(URL)
    assert response.status_code == 401
    get_invoice.assert_not_called()
