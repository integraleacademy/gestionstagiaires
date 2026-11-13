"""Recover an existing invoice without issuing invoices, messages or debits."""

import copy
import json
from unittest.mock import Mock

import pytest

import app as gestion


@pytest.fixture
def dossier(monkeypatch, tmp_path):
    for name, value in {'PERSIST_DIR': tmp_path, 'DATA_FILE': tmp_path / 'data.json',
                        'BACKUP_DIR': tmp_path / 'backups'}.items():
        monkeypatch.setattr(gestion, name, str(value))
    (tmp_path / 'backups').mkdir()
    monkeypatch.setattr(gestion, '_partner_postgres_active', lambda: False)
    monkeypatch.setattr(gestion, '_partner_postgres_shadow', lambda: False)
    monkeypatch.setattr(gestion, '_financing_partner_module_enabled', lambda: True)
    monkeypatch.setattr(gestion, '_qonto_is_configured', lambda: True)
    for name in ('create_qonto_invoice', 'finalize_qonto_invoice',
                 '_setup_qonto_direct_debit_for_line', 'ensure_qonto_sepa_installments_for_line',
                 'send_qonto_invoice'):
        if hasattr(gestion, name):
            monkeypatch.setattr(gestion, name, Mock(side_effect=AssertionError('No external mutation during recovery')))
    data = {'sessions': [{'id': 'S-RECOVERY', 'training_type': 'APS',
                         'date_start': '2027-01-04', 'date_end': '2027-02-18',
                         'trainees': [{'id': 'T-RECOVERY', 'first_name': 'Test',
                                       'last_name': 'Recovery', 'personal_amount': 950}]}]}
    gestion.save_data(data)
    current = gestion.load_data()
    line = gestion._billing_lines(current)[0]
    line.update(generationInProgress=True, qontoClientId='client-recovery',
                qontoCustomerId='client-recovery', qonto_mandate_client_id='client-recovery',
                qonto_direct_debit_mandate_id='mandate-existing', mandateStatus='active',
                paymentMode='cash', directDebitInstallments=[], paymentPlan={})
    gestion._save_billing_line(current, line)
    gestion.save_data(current)
    remote = {'id': 'invoice-existing', 'number': 'F-TEST-123', 'status': 'unpaid',
              'client_id': 'client-recovery',
              'client': {'id': 'client-recovery', 'name': 'Test Recovery'},
              'currency': 'EUR', 'total_amount': {'value': '950.00', 'currency': 'EUR'},
              'amount_paid': {'value': '0.00', 'currency': 'EUR'},
              'issue_date': '2026-11-12', 'due_date': '2026-12-12',
              'performance_start_date': '2027-01-04', 'performance_end_date': '2027-02-18'}
    find = Mock(return_value=copy.deepcopy(remote))
    get = Mock(side_effect=lambda _id: copy.deepcopy(remote))
    monkeypatch.setattr(gestion, 'find_qonto_invoice_by_number', find)
    monkeypatch.setattr(gestion, 'get_qonto_invoice', get)
    client = gestion.app.test_client()
    with client.session_transaction() as auth:
        auth.update(admin_logged_in=True, admin_role='admin', admin_username='test@example.test')
    return client, line['id'], remote, find, get, tmp_path / 'data.json'


def search(dossier):
    client, line_id, *_ = dossier
    return client.post('/api/billing/invoices/search', json={
        'lineId': line_id, 'invoiceNumber': 'F-TEST-123'})


def test_lookup_and_attachment_only_restore_existing_invoice(dossier):
    client, line_id, remote, find, get, path = dossier
    before = json.loads(path.read_text())
    preview = search(dossier)
    assert preview.status_code == 200, preview.json
    assert preview.json['invoice']['total_amount_cents'] == 95000
    assert json.loads(path.read_text())['billing_lines'] == before['billing_lines']
    attached = client.post('/api/billing/invoices/attach', json={
        'selectionToken': preview.json['selectionToken']})
    assert attached.status_code == 200, attached.json
    stored = gestion._find_billing_line(json.loads(path.read_text()), line_id)
    assert stored['qontoInvoiceId'] == remote['id']
    assert stored['qontoInvoiceNumber'] == remote['number']
    assert stored['invoiceGeneratedAt'] == remote['issue_date']
    assert stored['generationInProgress'] is False
    assert stored['qonto_direct_debit_mandate_id'] == 'mandate-existing'
    assert stored['directDebitInstallments'] == []
    assert stored['paymentMode'] == 'cash'
    assert stored['paymentPlan'] == {}
    assert stored['logs'][-1]['action'] == 'Facture Qonto existante rattachée au dossier'
    find.assert_called_once_with('F-TEST-123')
    assert get.call_count == 2
    replay = client.post('/api/billing/invoices/attach', json={
        'selectionToken': preview.json['selectionToken']})
    assert replay.status_code == 409
    assert len(json.loads(path.read_text())['billing_lines']) == 1


def test_attachment_rechecks_remote_client_and_amount(dossier):
    client, line_id, remote, _, _, path = dossier
    preview = search(dossier)
    assert preview.status_code == 200
    remote['total_amount']['value'] = '951.00'
    rejected = client.post('/api/billing/invoices/attach', json={
        'selectionToken': preview.json['selectionToken']})
    assert rejected.status_code == 409
    assert not gestion._find_billing_line(json.loads(path.read_text()), line_id)['qontoInvoiceId']


def test_attachment_rejects_remote_identifier_change(dossier):
    client, line_id, remote, _, _, path = dossier
    preview = search(dossier)
    assert preview.status_code == 200
    remote['id'] = 'different-invoice'
    rejected = client.post('/api/billing/invoices/attach', json={
        'selectionToken': preview.json['selectionToken']})
    assert rejected.status_code == 409
    assert not gestion._find_billing_line(json.loads(path.read_text()), line_id)['qontoInvoiceId']


def test_lookup_rejects_invoice_owned_by_historical_legacy_dossier(dossier):
    client, line_id, remote, _, _, path = dossier

    def add_legacy(data):
        data['sessions'].append({'id': 'S-HISTORICAL', 'training_type': 'APS',
            'date_start': '2020-01-01', 'date_end': '2020-02-01',
            'trainees': [{'id': 'T-OLD', 'first_name': 'Historical', 'last_name': 'Owner',
                'personal_amount': 500, 'qonto_invoice': {
                    'qonto_invoice_id': remote['id'], 'qonto_invoice_number': remote['number'],
                    'amount_ttc': 950}}]})
        return {'ok': True}

    gestion._atomic_update_data(add_legacy)
    rejected = search(dossier)
    assert rejected.status_code == 409
    assert 'autre financement' in rejected.json['error']
    assert not gestion._find_billing_line(json.loads(path.read_text()), line_id)['qontoInvoiceId']


def test_attachment_rechecks_fresh_dossier_inside_transaction(dossier, monkeypatch):
    client, line_id, remote, _, get, path = dossier
    preview = search(dossier)
    assert preview.status_code == 200

    def changed_during_qonto_read(_invoice_id):
        def change(data):
            data['sessions'][0]['trainees'][0]['personal_amount'] = 960
            return {'ok': True}
        gestion._atomic_update_data(change)
        return copy.deepcopy(remote)

    get.side_effect = changed_during_qonto_read
    rejected = client.post('/api/billing/invoices/attach', json={
        'selectionToken': preview.json['selectionToken']})
    assert rejected.status_code == 409
    stored = json.loads(path.read_text())
    assert stored['sessions'][0]['trainees'][0]['personal_amount'] == 960
    assert not gestion._find_billing_line(stored, line_id)['qontoInvoiceId']


def test_attachment_rejects_changed_or_foreign_selection(dossier):
    client, *_ = dossier
    preview = search(dossier)
    assert preview.status_code == 200
    token = preview.json['selectionToken']
    rejected = client.post('/api/billing/invoices/attach', json={'selectionToken': token + 'changed'})
    assert rejected.status_code == 409
    with client.session_transaction() as auth:
        auth.pop('invoice_attachment_nonce')
    rejected = client.post('/api/billing/invoices/attach', json={'selectionToken': token})
    assert rejected.status_code == 409


def test_recovery_is_restricted_to_platform_admin(dossier, monkeypatch):
    client, line_id, _, find, *_ = dossier
    monkeypatch.setattr(gestion, '_is_partner_data_scope_session', lambda: True)
    denied = search(dossier)
    assert denied.status_code == 403
    find.assert_not_called()


def test_orphan_generation_cannot_issue_a_duplicate(dossier):
    client, line_id, *_ = dossier
    response = client.post('/api/billing/create-draft', json={'lineId': line_id})
    assert response.status_code == 400
    assert response.json['ignored'] is True
    assert 'rattachez' in response.json['message']


def test_old_admin_save_cannot_erase_recovered_invoice(dossier):
    client, line_id, _, _, _, path = dossier
    stale = gestion.load_data()
    preview = search(dossier)
    attached = client.post('/api/billing/invoices/attach', json={
        'selectionToken': preview.json['selectionToken']})
    assert attached.status_code == 200, attached.json
    stale['sessions'][0]['trainees'][0]['comment'] = 'New administrative note'
    gestion.save_data(stale)
    fresh = json.loads(path.read_text())
    assert fresh['sessions'][0]['trainees'][0]['comment'] == 'New administrative note'
    line = gestion._find_billing_line(fresh, line_id)
    assert line['qontoInvoiceNumber'] == 'F-TEST-123'
    assert line['generationInProgress'] is False


def test_old_mandate_save_preserves_invoice_created_after_snapshot(dossier):
    client, line_id, _, _, _, path = dossier
    stale = gestion.load_data()
    preview = search(dossier)
    attached = client.post('/api/billing/invoices/attach', json={
        'selectionToken': preview.json['selectionToken']})
    assert attached.status_code == 200
    old_line = gestion._find_billing_line(stale, line_id)
    old_line['qonto_mandate_rum'] = 'RUM-TEST-RECOVERED'
    gestion._billing_log(old_line, 'Mandat retrouvé', 'success', 'active')
    gestion._save_billing_line(stale, old_line)
    gestion.save_data(stale)
    line = gestion._find_billing_line(json.loads(path.read_text()), line_id)
    assert line['qontoInvoiceNumber'] == 'F-TEST-123'
    assert line['qonto_mandate_rum'] == 'RUM-TEST-RECOVERED'
    assert line['generationInProgress'] is False
    assert len(line['logs']) == 2
