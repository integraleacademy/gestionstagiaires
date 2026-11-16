"""Reproduce a Qonto callback overtaking the successful draft creation."""

import json
from unittest.mock import Mock

import pytest

import app as gestion


@pytest.fixture
def storage(monkeypatch, tmp_path):
    for name, value in {
        'PERSIST_DIR': tmp_path,
        'DATA_FILE': tmp_path / 'data.json',
        'BACKUP_DIR': tmp_path / 'backups',
    }.items():
        monkeypatch.setattr(gestion, name, str(value))
    (tmp_path / 'backups').mkdir()
    monkeypatch.setattr(gestion, '_partner_postgres_active', lambda: False)
    monkeypatch.setattr(gestion, '_partner_postgres_shadow', lambda: False)
    monkeypatch.setattr(gestion, '_verify_qonto_webhook_signature', lambda _body: True)
    gestion.save_data({'sessions': [{
        'id': 'S-TEST', 'training_type': 'APS',
        'date_start': '2026-11-02', 'date_end': '2026-12-04',
        'trainees': [{'id': 'T-TEST', 'first_name': 'Test', 'last_name': 'Invoice',
                      'personal_amount': 950}],
    }]})
    # Complete normalisation before the simulated concurrent requests.
    gestion.load_data()
    return tmp_path / 'data.json'


@pytest.mark.parametrize('event_invoice_id', ['inv-created', 'inv-unrelated'])
def test_webhook_cannot_erase_draft_created_during_remote_fetch(storage, monkeypatch, event_invoice_id):
    def remote_response(invoice_id):
        # The webhook has begun, but Qonto's GET has not returned yet. The
        # original create-draft request now persists its successful response.
        current = json.loads(storage.read_text())
        line = gestion._billing_lines(current)[0]
        line.update(qontoInvoiceId='inv-created', qontoDraftId='inv-created',
                    invoiceStatus='draft', invoiceGeneratedAt='2026-09-16T11:36:56Z')
        gestion._save_billing_line(current, line)
        current['sessions'][0]['trainees'][0]['comment'] = 'Concurrent edit'
        gestion.save_data(current)
        return {'client_invoice': {'id': invoice_id, 'status': 'draft',
                                   'total_amount': {'value': '950.00'}}}

    monkeypatch.setattr(gestion, 'get_qonto_invoice', remote_response)
    finalize = Mock(return_value={'client_invoice': {
        'id': 'inv-created', 'status': 'finalized', 'number': 'F-TEST',
        'total_amount': {'value': '950.00'},
    }})
    monkeypatch.setattr(gestion, 'finalize_qonto_invoice', finalize)
    client = gestion.app.test_client()
    callback = client.post('/api/webhooks/qonto', json={
        'event': 'v1/client-invoices.created', 'data': {'id': event_invoice_id},
    })
    assert callback.status_code == 200 and callback.json['queued']
    inbox = gestion.qonto_webhook_inbox.Inbox(storage.parent)
    assert inbox.process_one(gestion._process_qonto_webhook, gestion.app.logger)
    persisted = json.loads(storage.read_text())
    line = gestion._billing_lines(persisted)[0]
    assert line['qontoInvoiceId'] == 'inv-created'
    assert persisted['sessions'][0]['trainees'][0]['comment'] == 'Concurrent edit'
    assert persisted['qonto_webhook_history'][-1]['result'] == (
        'updated' if event_invoice_id == 'inv-created' else 'ignored'
    )
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role='admin', admin_username='test@example.test')
    finalized = client.post('/api/billing/finalize', json={'lineId': line['id']})
    assert finalized.status_code == 200
    finalize.assert_called_once_with('inv-created')
    create = Mock(side_effect=AssertionError('A retry must not create another invoice'))
    monkeypatch.setattr(gestion, 'create_qonto_invoice', create)
    retry = client.post('/api/billing/create-draft', json={'lineId': line['id']})
    assert retry.json['ignored'] is True
    create.assert_not_called()


def test_webhook_does_not_restore_an_invoice_reset_during_remote_fetch(storage, monkeypatch):
    current = json.loads(storage.read_text())
    line = gestion._billing_lines(current)[0]
    line.update(qontoInvoiceId='inv-old', qontoDraftId='inv-old', invoiceStatus='draft')
    gestion._save_billing_line(current, line)
    gestion.save_data(current)

    def reset_during_fetch(_invoice_id):
        current = json.loads(storage.read_text())
        line = gestion._billing_lines(current)[0]
        line.update(qontoInvoiceId='', qontoDraftId='', invoiceStatus='not_invoiced')
        gestion._save_billing_line(current, line)
        gestion.save_data(current)
        return {'client_invoice': {'id': 'inv-old', 'status': 'paid',
                                   'total_amount': {'value': '950.00'},
                                   'amount_paid': {'value': '950.00'}}}

    monkeypatch.setattr(gestion, 'get_qonto_invoice', reset_during_fetch)
    response = gestion.app.test_client().post('/api/webhooks/qonto', json={
        'event': 'v1/client-invoices.updated', 'data': {'id': 'inv-old'},
    })
    assert response.status_code == 200
    assert response.json['queued']
    assert gestion.qonto_webhook_inbox.Inbox(storage.parent).process_one(gestion._process_qonto_webhook, gestion.app.logger)
    persisted = gestion._billing_lines(json.loads(storage.read_text()))[0]
    assert not persisted['qontoInvoiceId']
    assert persisted['invoiceStatus'] == 'not_invoiced'


def test_signed_mandate_preserves_concurrent_admin_edits_and_runs_once(storage, monkeypatch):
    data = gestion.load_data()
    line = gestion._billing_lines(data)[0]
    line.update(qonto_direct_debit_mandate_id='mandate-test', mandateStatus='pending', paymentMode='sepa_direct_debit')
    gestion._save_billing_line(data, line)
    gestion.save_data(data)
    calls = []

    def slow_scheduling(line):
        calls.append(line['id'])
        def admin_edit(current):
            current['sessions'][0]['trainees'][0]['comment'] = 'Edited while Qonto was busy'
            current.setdefault('notifications_admin', []).insert(0, {'id': 'admin-notice'})
            return {}
        gestion._atomic_update_data(admin_edit)
        return {'created': 0}

    monkeypatch.setattr(gestion, 'ensure_qonto_sepa_installments_for_line', slow_scheduling)
    payload = {'id': 'delivery-mandate-signed', 'type': 'v1/sepa-direct-debit-mandates',
               'data': {'id': 'mandate-test', 'status': 'signed'}}
    client = gestion.app.test_client()
    assert client.post('/api/webhooks/qonto', json=payload).json['queued']
    assert client.post('/api/qonto/webhooks', json=payload).json['queued']
    inbox = gestion.qonto_webhook_inbox.Inbox(storage.parent)
    assert inbox.process_one(gestion._process_qonto_webhook, gestion.app.logger)
    assert not inbox.process_one(gestion._process_qonto_webhook, gestion.app.logger)
    current = json.loads(storage.read_text())
    assert current['sessions'][0]['trainees'][0]['comment'] == 'Edited while Qonto was busy'
    assert current['notifications_admin'][0]['id'] == 'admin-notice'
    assert current['billing_lines'][0]['qonto_mandate_status'] in {'signed', 'active'}
    assert calls == [line['id']]
