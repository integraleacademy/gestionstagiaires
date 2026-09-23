import copy
import json
from pathlib import Path
from types import SimpleNamespace

from flask import Flask
import pytest

import app as gestion
import cnaps_notification_recovery as recovery


NOW = '2026-09-23T17:00:00Z'
SIGNATURE = 'AP A3P ACTIF • 2027-03-22'
ROW = {'last_name': 'TEST', 'first_name': 'Jane', 'nub': '1234567', 'tracking_id': '115'}


@pytest.fixture
def fixture(monkeypatch, tmp_path):
    monkeypatch.setattr(gestion, '_now_iso', lambda: NOW)
    monkeypatch.setattr(gestion, 'BACKUP_DIR', str(tmp_path / 'backups'))
    Path(gestion.BACKUP_DIR).mkdir()
    monkeypatch.setattr(gestion, 'enrich_cnaps_tracking_rows_with_enrollment', lambda rows, data: rows)
    data = {'sessions': [], 'cnaps_status_change_notifications': [], 'cnaps_public_annuaire_statuses': {
        'TEST|1234567': {'state_code': 'titles', 'signature': SIGNATURE, 'checked_at': NOW,
                         'status_since': '2026-09-23T15:45:00Z', 'tracking_id': '115'}}}
    candidates = recovery.active_rows(gestion, data, [ROW, ROW])
    plan = {'id': 'batch1', 'created_at': NOW, 'rows': candidates,
            'recipients': [gestion.CNAPS_STATUS_CHANGE_NOTIFICATION_TO, *gestion.CNAPS_STATUS_CHANGE_NOTIFICATION_CC]}
    calls = []
    monkeypatch.setattr(gestion, 'brevo_send_email', lambda *args, **kwargs: calls.append((args, kwargs)) or {'ok': True, 'message_id': 'receipt1'})
    return data, plan, calls


def test_recovery_handles_corrupted_map_without_fabricating_history_and_is_idempotent(fixture):
    data, plan, emails = fixture
    original = copy.deepcopy(data['cnaps_public_annuaire_statuses'])
    assert len(plan['rows']) == 1
    result = recovery.apply_batch(gestion, data, plan, {'TEST|1234567'})
    assert result['created'] == ['TEST|1234567']
    assert data['cnaps_status_change_notifications']['TEST|1234567']['previous_status'] == recovery.UNKNOWN_PREVIOUS
    assert data['cnaps_status_change_notifications']['TEST|1234567']['email_status'] == 'pending'
    assert not emails  # Creation runs under the transaction; sending is separate.
    assert data['cnaps_public_annuaire_statuses'] == original
    assert recovery.apply_batch(gestion, data, plan, {'TEST|1234567'})['created'] == []


def test_backup_history_recovers_observed_no_title_and_proven_receipt_only(fixture):
    data, plan, _ = fixture
    old = {'cnaps_public_annuaire_statuses': {'TRACKING|115': {'state_code': 'no_title', 'checked_at': '2026-09-22T09:00:00Z'}},
           'cnaps_status_change_notifications': {'TEST|1234567': {'signature': SIGNATURE, 'sent_at': '2026-09-22T10:00:00Z',
                'reviewed_at': '2026-09-22T11:00:00Z', 'email_message_id': 'old1'}}}
    (Path(gestion.BACKUP_DIR) / 'data_json.20260922T110000.json').write_text(json.dumps(old))
    (Path(gestion.BACKUP_DIR) / 'data_json.20260922T120000.json').write_text('{bad')
    report = recovery.inspect_backups(gestion, plan['rows'])
    assert report['read'] == 1 and report['invalid'] == 1
    assert plan['rows'][0]['previous_status'] == 'Aucun titre CNAPS trouvé'
    result = recovery.apply_batch(gestion, data, plan, {'TEST|1234567'})
    assert result['restored'] == ['TEST|1234567'] and not result['created']
    restored = data['cnaps_status_change_notifications']['TEST|1234567']
    assert restored['email_status'] == 'sent'
    assert restored['email_message_id'] == 'old1' and restored['reviewed_at']


@pytest.mark.parametrize('change', ['deleted', 'stale', 'changed', 'ambiguous'])
def test_batch_skips_unsafe_or_changed_dossiers(fixture, change):
    data, plan, _ = fixture
    allowed = {'TEST|1234567'}
    if change == 'deleted':
        allowed.clear()
    if change == 'stale':
        data['cnaps_public_annuaire_statuses']['TEST|1234567']['checked_at'] = '2026-09-22T09:00:00Z'
    if change == 'changed':
        data['cnaps_public_annuaire_statuses']['TEST|1234567']['signature'] = 'CAR APS ACTIF'
    if change == 'ambiguous':
        plan['rows'][0]['ambiguous_email'] = True
    assert recovery.apply_batch(gestion, data, plan, allowed)['created'] == []
    assert not data['cnaps_status_change_notifications']


def test_brevo_matching_requires_nub_and_full_status_not_name_alone(fixture, monkeypatch):
    _, plan, _ = fixture
    body = ['NUB 7654321 ' + SIGNATURE]
    def get(host, path, params=None):
        if path == 'emails':
            return {'transactionalEmails': [{'email': host.CNAPS_STATUS_CHANGE_NOTIFICATION_TO,
                'subject': 'Changement de statut CNAPS — Jane TEST', 'uuid': 'valid-uuid', 'date': NOW, 'messageId': 'old-id'}]}
        return {'body': body[0]}
    monkeypatch.setattr(recovery, '_brevo_get', get)
    recovery.inspect_brevo(gestion, plan['rows'])
    assert plan['rows'][0]['receipt'] is None
    body[0] = '<p>NUB : 1234567</p><p>' + SIGNATURE + '</p>'
    recovery.inspect_brevo(gestion, plan['rows'])
    assert plan['rows'][0]['receipt']['email_message_id'] == 'old-id'


def test_recovery_mail_is_explicit_and_uses_existing_recipients(fixture):
    data, plan, calls = fixture
    recovery.apply_batch(gestion, data, plan, {'TEST|1234567'})
    item = data['cnaps_status_change_notifications']['TEST|1234567']
    receipt = gestion._send_cnaps_notification_email(data, 'TEST|1234567', item)
    assert receipt['email_status'] == 'sent'
    args, kwargs = calls[0]
    assert args[0] == gestion.CNAPS_STATUS_CHANGE_NOTIFICATION_TO
    assert args[1] == 'Rattrapage CNAPS — Jane TEST'
    assert 'Notification de rattrapage' in args[2] and 'date d’acceptation inconnue' in args[2]
    assert kwargs['cc_emails'] == gestion.CNAPS_STATUS_CHANGE_NOTIFICATION_CC


def test_batches_limit_new_notifications_and_continue_without_duplicates(fixture):
    data, plan, calls = fixture
    example = copy.deepcopy(plan['rows'][0])
    plan['rows'] = []
    data['cnaps_public_annuaire_statuses'] = {}
    for index in range(13):
        row = {**example, 'nub': str(1234567 + index), 'key': f'TEST|{1234567 + index}', 'tracking_id': str(index)}
        plan['rows'].append(row)
        data['cnaps_public_annuaire_statuses'][row['key']] = {'state_code': 'titles', 'signature': SIGNATURE, 'checked_at': NOW}
    allowed = set(data['cnaps_public_annuaire_statuses'])
    assert len(recovery.apply_batch(gestion, data, plan, allowed)['created']) == 10
    assert len(recovery.apply_batch(gestion, data, plan, allowed)['created']) == 3
    assert not recovery.apply_batch(gestion, data, plan, allowed)['created']
    assert len(data['cnaps_status_change_notifications']) == 13 and not calls


def test_delivery_verification_correlates_receipts_and_recipients_without_sending(fixture, monkeypatch):
    data, plan, calls = fixture
    recovery.apply_batch(gestion, data, plan, {'TEST|1234567'})
    item = data['cnaps_status_change_notifications']['TEST|1234567']
    item.update(email_status='sent', email_message_id='receipt1')
    monkeypatch.setattr(gestion, '_atomic_update_data', lambda mutator: mutator(data))
    monkeypatch.setattr(recovery, '_brevo_get', lambda host, path, params: {'events': [
        {'email': params['email'], 'event': 'delivered', 'messageId': 'receipt1'},
        {'email': 'unrelated@example.org', 'event': 'hard_bounce', 'messageId': 'receipt1'}]})
    recovery.verify_delivery(gestion, data, plan)
    assert item['email_delivery'] == {email: 'delivered' for email in plan['recipients']}
    assert not calls


def test_route_requires_internal_admin_and_csrf(tmp_path, monkeypatch):
    host = SimpleNamespace(**vars(gestion))
    host.app = Flask(__name__)
    host.app.secret_key = 'test-secret'
    host.PERSIST_DIR = str(tmp_path)
    host.load_data = lambda **kwargs: {}
    host._current_partner_id = lambda: session_partner[0]
    session_partner = ['integrale']
    recovery.register_cnaps_notification_recovery(host)
    client = host.app.test_client()
    path = '/admin/tools/cnaps-notification-recovery'
    assert client.post(path, headers={'Accept': 'application/json'}).status_code == 401
    for role, partner in [('viewer', 'integrale'), ('admin', 'external')]:
        with client.session_transaction() as state:
            state.update(admin_logged_in=True, admin_role=role)
        session_partner[0] = partner
        assert client.post(path).status_code == 403
    with client.session_transaction() as state:
        state['admin_role'] = 'admin'
    session_partner[0] = 'integrale'
    assert client.post(path, data={'action': 'apply', 'csrf': 'wrong'}).status_code == 403


def test_preview_does_not_send_and_fails_closed_when_brevo_is_unavailable(fixture, monkeypatch):
    data, _, calls = fixture
    monkeypatch.setattr(gestion, 'fetch_cnapsv3_tracking_requests', lambda: ([ROW], None))
    monkeypatch.setattr(gestion, 'load_data', lambda **kwargs: data)
    monkeypatch.setattr(recovery, '_brevo_get', lambda *args, **kwargs: (_ for _ in ()).throw(ValueError('HTTP 503')))
    with pytest.raises(ValueError, match='HTTP 503'):
        recovery.make_plan(gestion)
    assert not calls and not data['cnaps_status_change_notifications']
