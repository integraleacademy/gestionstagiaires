"""Confirm existing-mandate schedules against real JSON persistence, without network."""

import copy
import datetime
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app as gestion


PREVIEW = '/api/billing/direct-debit/preview'
SCHEDULE = '/api/billing/direct-debit/schedule'


@pytest.fixture
def scheduling(monkeypatch, tmp_path):
    for name, value in {
        'PERSIST_DIR': tmp_path,
        'DATA_FILE': tmp_path / 'data.json',
        'BACKUP_DIR': tmp_path / 'backups',
    }.items():
        monkeypatch.setattr(gestion, name, str(value))
    (tmp_path / 'backups').mkdir()
    monkeypatch.setattr(gestion, '_partner_postgres_active', lambda: False)
    monkeypatch.setattr(gestion, '_partner_postgres_shadow', lambda: False)
    monkeypatch.setattr(gestion, '_financing_partner_module_enabled', lambda: True)
    monkeypatch.setattr(gestion, '_qonto_is_configured', lambda: True)
    monkeypatch.setattr(gestion, '_ensure_qonto_oauth_ready', lambda: None)
    monkeypatch.setitem(gestion.app.config, 'TESTING', True)
    monkeypatch.setitem(gestion.app.config, 'SECRET_KEY', 'test-scheduling-secret')
    for name in (
        '_qonto_request', 'create_qonto_invoice', 'finalize_qonto_invoice',
        'send_qonto_invoice', 'create_qonto_direct_debit_mandate',
        '_setup_qonto_direct_debit_for_line',
    ):
        monkeypatch.setattr(gestion, name, Mock(side_effect=AssertionError(
            'Scheduling an existing invoice must not create an invoice or mandate')))

    today = datetime.date.today()
    start = (today + datetime.timedelta(days=5)).isoformat()
    end = (today + datetime.timedelta(days=45)).isoformat()
    gestion.save_data({'sessions': [{
        'id': 'S-SCHEDULING', 'training_type': 'APS',
        'date_start': start, 'date_end': end,
        'trainees': [{'id': 'T-SCHEDULING', 'first_name': 'Test',
                      'last_name': 'Scheduling', 'personal_amount': 950}],
    }]})
    current = gestion.load_data()
    line = gestion._billing_lines(current)[0]
    invoice_id = '11111111-1111-4111-8111-111111111111'
    client_id = '22222222-2222-4222-8222-222222222222'
    mandate_id = '33333333-3333-4333-8333-333333333333'
    bank_id = '44444444-4444-4444-8444-444444444444'
    line.update(
        generationInProgress=False,
        qontoInvoiceId=invoice_id, qontoDraftId=invoice_id,
        qontoInvoiceNumber='F-SCHEDULE-001', invoiceStatus='sent',
        qontoClientId=client_id, qontoCustomerId=client_id,
        qonto_mandate_client_id=client_id,
        qonto_direct_debit_mandate_id=mandate_id,
        qonto_mandate_rum='RUM-SCHEDULING',
        qonto_mandate_status='active', mandateStatus='active',
        paymentMode='cash', paymentStatus='unpaid',
        qonto_total_amount_cents=95000, qonto_amount_paid_cents=0,
        qonto_remaining_amount_cents=95000,
        directDebitInstallments=[], paymentPlan={}, sepa_payment_plan={},
    )
    gestion._save_billing_line(current, line)
    gestion.save_data(current)
    gestion.load_data()  # Finish ordinary normalization before taking dry-run snapshots.

    invoice = {
        'id': invoice_id, 'number': 'F-SCHEDULE-001', 'status': 'unpaid',
        'client_id': client_id, 'client': {'id': client_id, 'name': 'Test Scheduling'},
        'currency': 'EUR',
        'total_amount': {'value': '950.00', 'currency': 'EUR'},
        'amount_paid': {'value': '0.00', 'currency': 'EUR'},
        'remaining_amount': {'value': '950.00', 'currency': 'EUR'},
        'issue_date': today.isoformat(),
        'due_date': (today + datetime.timedelta(days=30)).isoformat(),
        'performance_start_date': start, 'performance_end_date': end,
    }
    mandate = {
        'id': mandate_id, 'client_id': client_id, 'status': 'active',
        'unique_mandate_reference': 'RUM-SCHEDULING',
    }
    subscriptions = []
    get_invoice = Mock(side_effect=lambda _id: {'client_invoice': copy.deepcopy(invoice)})
    get_mandate = Mock(side_effect=lambda _id: {'direct_debit_mandate': copy.deepcopy(mandate)})
    list_subscriptions = Mock(side_effect=lambda *args, **kwargs: {
        'direct_debit_subscriptions': copy.deepcopy(subscriptions),
        'meta': {'current_page': 1, 'total_pages': 1, 'next_page': None},
    })

    def record_subscription(payload):
        record = dict(copy.deepcopy(payload),
                      id=f'50000000-0000-4000-8000-{len(subscriptions) + 1:012d}',
                      status='pending')
        subscriptions.append(record)
        return {'direct_debit_subscription': copy.deepcopy(record)}

    create = Mock(side_effect=record_subscription)
    monkeypatch.setattr(gestion, 'get_qonto_invoice', get_invoice)
    monkeypatch.setattr(gestion, 'get_qonto_direct_debit_mandate', get_mandate)
    monkeypatch.setattr(gestion, 'list_qonto_direct_debit_subscriptions', list_subscriptions)
    monkeypatch.setattr(gestion, 'get_qonto_bank_account_id', Mock(return_value=bank_id))
    monkeypatch.setattr(gestion, 'create_qonto_direct_debit_subscription', create)
    client = gestion.app.test_client()
    with client.session_transaction() as auth:
        auth.update(admin_logged_in=True, admin_role='admin',
                    admin_username='schedule-test@example.test')
    return SimpleNamespace(
        client=client, line_id=line['id'], invoice=invoice, mandate=mandate,
        bank_id=bank_id, path=tmp_path / 'data.json', root=tmp_path,
        get_invoice=get_invoice, get_mandate=get_mandate,
        list_subscriptions=list_subscriptions, create=create,
        subscriptions=subscriptions, record_subscription=record_subscription,
        schedule=[{'date': (today + datetime.timedelta(days=days)).isoformat(),
                   'amount': '475.00'} for days in (10, 40)],
    )


def preview(case, schedule=None):
    return case.client.post(PREVIEW, json={
        'lineId': case.line_id,
        'schedule': case.schedule if schedule is None else schedule,
    })


def confirmed_preview(case, schedule=None):
    response = preview(case, schedule)
    assert response.status_code == 200, response.json
    assert response.json['ok'] is True
    return response.json


def confirm(case, selection):
    return case.client.post(SCHEDULE, json={'selectionToken': selection['selectionToken']})


def stored_line(case):
    data = json.loads(case.path.read_text())
    return next(row for row in data['billing_lines'] if row['id'] == case.line_id)


def test_preview_is_read_only_and_names_the_invoice_and_signed_mandate(scheduling):
    before = json.loads(scheduling.path.read_text())['billing_lines']
    selection = confirmed_preview(scheduling)
    assert selection['summary']['invoiceNumber'] == scheduling.invoice['number']
    assert selection['summary']['mandateRum'] == scheduling.mandate['unique_mandate_reference']
    assert 'Scheduling' in selection['summary']['traineeName']
    assert selection['summary']['totalCents'] == 95000
    assert selection['summary']['remainingCents'] == 95000
    assert selection['resuming'] is False
    assert len(selection['schedule']) == 2
    assert json.loads(scheduling.path.read_text())['billing_lines'] == before
    assert not (scheduling.root / 'qonto_sepa_creation').exists()
    scheduling.create.assert_not_called()


def test_confirmation_persists_each_subscription_and_replay_does_not_repeat_posts(scheduling):
    selection = confirmed_preview(scheduling)
    response = confirm(scheduling, selection)
    assert response.status_code == 200, response.json
    assert response.json['ok'] is True
    assert response.json['count'] == 2
    assert len(set(response.json['subscriptionIds'])) == 2
    assert scheduling.create.call_count == 2
    for index, call in enumerate(scheduling.create.call_args_list):
        payload = call.args[0]
        assert payload['direct_debit_mandate_id'] == scheduling.mandate['id']
        assert payload['client_id'] == scheduling.mandate['client_id']
        assert payload['bank_account_id'] == scheduling.bank_id
        assert payload['initial_collection_date'] == scheduling.schedule[index]['date']
        assert Decimal(payload['amount']['value']) == Decimal('475.00')
        assert payload['amount']['currency'] == 'EUR'
        assert payload['schedule_type'] == 'one_off'
    line = stored_line(scheduling)
    assert line['qontoInvoiceId'] == scheduling.invoice['id']
    assert line['qonto_direct_debit_mandate_id'] == scheduling.mandate['id']
    assert line['paymentMode'] == 'sepa_direct_debit'
    assert line['paymentPlan']['qontoSchedulingOperation']['state'] == 'completed'
    ids = [row.get('qonto_direct_debit_subscription_id') for row in line['directDebitInstallments']]
    assert sorted(ids) == sorted(response.json['subscriptionIds'])
    replay = confirm(scheduling, selection)
    assert replay.status_code == 409, replay.json
    assert scheduling.create.call_count == 2


@pytest.mark.parametrize('role', ['viewer', 'partner'])
def test_only_platform_admin_may_preview_or_confirm(scheduling, monkeypatch, role):
    selection = confirmed_preview(scheduling)
    if role == 'partner':
        monkeypatch.setattr(gestion, '_is_partner_data_scope_session', lambda: True)
    else:
        with scheduling.client.session_transaction() as auth:
            auth['admin_role'] = role
    scheduling.get_invoice.reset_mock()
    assert preview(scheduling).status_code == 403
    assert confirm(scheduling, selection).status_code == 403
    scheduling.get_invoice.assert_not_called()
    scheduling.create.assert_not_called()


@pytest.mark.parametrize('entity,field,value', [
    ('invoice', 'id', 'different-invoice'),
    ('invoice', 'client_id', 'different-client'),
    ('mandate', 'id', 'different-mandate'),
    ('mandate', 'client_id', 'different-client'),
    ('mandate', 'unique_mandate_reference', 'DIFFERENT-RUM'),
    ('mandate', 'status', 'revoked'),
])
def test_preview_requires_exact_invoice_client_and_mandate_identity(scheduling, entity, field, value):
    getattr(scheduling, entity)[field] = value
    response = preview(scheduling)
    assert response.status_code in {400, 409}, response.json
    assert response.json['ok'] is False
    scheduling.create.assert_not_called()
    assert stored_line(scheduling)['paymentMode'] == 'cash'


@pytest.mark.parametrize('when', ['preview', 'confirmation'])
def test_fully_paid_invoice_cannot_receive_new_direct_debits(scheduling, when):
    selection = confirmed_preview(scheduling) if when == 'confirmation' else None
    scheduling.invoice.update(status='paid',
        amount_paid={'value': '950.00', 'currency': 'EUR'},
        remaining_amount={'value': '0.00', 'currency': 'EUR'})
    response = confirm(scheduling, selection) if selection else preview(scheduling)
    assert response.status_code in {400, 409}, response.json
    assert response.json['ok'] is False
    scheduling.create.assert_not_called()


def test_local_amount_changed_during_remote_recheck_is_not_scheduled(scheduling):
    selection = confirmed_preview(scheduling)

    def change_amount(_invoice_id):
        def mutate(data):
            data['sessions'][0]['trainees'][0]['personal_amount'] = 960
            return {'ok': True}
        gestion._atomic_update_data(mutate)
        return {'client_invoice': copy.deepcopy(scheduling.invoice)}

    scheduling.get_invoice.side_effect = change_amount
    response = confirm(scheduling, selection)
    assert response.status_code == 409, response.json
    scheduling.create.assert_not_called()
    assert json.loads(scheduling.path.read_text())['sessions'][0]['trainees'][0]['personal_amount'] == 960
    assert stored_line(scheduling)['paymentMode'] == 'cash'


@pytest.mark.parametrize('problem', ['amount', 'fractional_cent', 'negative', 'past', 'after_session_cutoff'])
def test_invalid_schedule_is_rejected_without_silently_adjusting_it(scheduling, problem):
    schedule = copy.deepcopy(scheduling.schedule)
    if problem == 'amount':
        schedule[-1]['amount'] = '474.99'
    elif problem == 'fractional_cent':
        schedule[0]['amount'] = '475.001'
        schedule[-1]['amount'] = '474.999'
    elif problem == 'negative':
        schedule[0]['amount'] = '-1.00'
        schedule[-1]['amount'] = '951.00'
    elif problem == 'past':
        schedule[0]['date'] = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    else:
        end = datetime.date.fromisoformat(scheduling.invoice['performance_end_date'])
        schedule[-1]['date'] = (end - datetime.timedelta(days=2)).isoformat()
    response = preview(scheduling, schedule)
    assert response.status_code in {400, 409}, response.json
    scheduling.create.assert_not_called()
    assert stored_line(scheduling)['paymentPlan'] == {}


def test_altered_confirmation_token_cannot_create_subscriptions(scheduling):
    selection = confirmed_preview(scheduling)
    selection['selectionToken'] += 'changed'
    response = confirm(scheduling, selection)
    assert response.status_code == 409, response.json
    scheduling.create.assert_not_called()


def test_successful_first_subscription_is_saved_if_the_second_fails(scheduling):
    selection = confirmed_preview(scheduling)

    def first_only(payload):
        if scheduling.create.call_count == 1:
            return scheduling.record_subscription(payload)
        # The first confirmation must already be durable before the next POST.
        saved = stored_line(scheduling)
        assert saved['directDebitInstallments'][0]['qonto_direct_debit_subscription_id'] == scheduling.subscriptions[0]['id']
        raise TimeoutError('Qonto response lost for the second installment')

    scheduling.create.side_effect = first_only
    response = confirm(scheduling, selection)
    assert response.status_code in {400, 409, 502}, response.json
    assert response.json['ok'] is False
    assert response.json['partial'] is True
    assert response.json['confirmedCount'] == 1
    line = stored_line(scheduling)
    assert line['paymentPlan']['qontoSchedulingOperation']['state'] == 'partial'
    assert len(line['directDebitInstallments']) == 2
    assert line['directDebitInstallments'][0]['qonto_direct_debit_subscription_id'] == scheduling.subscriptions[0]['id']
    assert not line['directDebitInstallments'][1].get('qonto_direct_debit_subscription_id')
    assert response.json['line']['directDebitInstallments'][0]['qonto_direct_debit_subscription_id'] == scheduling.subscriptions[0]['id']
    retry = confirmed_preview(scheduling)
    assert retry['resuming'] is True
    failed_retry = confirm(scheduling, retry)
    assert failed_retry.json['ok'] is False
    assert scheduling.create.call_count == 2  # The unknown second POST must never be repeated.
    assert stored_line(scheduling)['directDebitInstallments'][0]['qonto_direct_debit_subscription_id'] == scheduling.subscriptions[0]['id']


def test_timeout_is_never_reposted_and_can_recover_the_original_remote_result(scheduling):
    single = [{'date': scheduling.schedule[0]['date'], 'amount': '950.00'}]
    selection = confirmed_preview(scheduling, single)
    scheduling.create.side_effect = TimeoutError('Response lost after bank acceptance')
    failed = confirm(scheduling, selection)
    assert failed.json['ok'] is False
    assert scheduling.create.call_count == 1
    altered = copy.deepcopy(single)
    altered[0]['date'] = (datetime.date.fromisoformat(single[0]['date']) + datetime.timedelta(days=1)).isoformat()
    refused_change = preview(scheduling, altered)
    assert refused_change.status_code == 409, refused_change.json
    assert scheduling.create.call_count == 1
    retry = confirmed_preview(scheduling, single)
    assert retry['resuming'] is True
    blocked = confirm(scheduling, retry)
    assert blocked.json['ok'] is False
    assert scheduling.create.call_count == 1

    # The bank later exposes the very subscription created by the timed-out POST.
    payload = scheduling.create.call_args.args[0]
    scheduling.record_subscription(payload)
    recovered = confirm(scheduling, confirmed_preview(scheduling, single))
    assert recovered.status_code == 200, recovered.json
    assert recovered.json['ok'] is True
    assert recovered.json['subscriptionIds'] == [scheduling.subscriptions[0]['id']]
    assert scheduling.create.call_count == 1
    assert stored_line(scheduling)['paymentPlan']['qontoSchedulingOperation']['state'] == 'completed'


def test_ledger_id_without_remote_subscription_is_not_a_successful_recovery(scheduling, monkeypatch):
    single = [{'date': scheduling.schedule[0]['date'], 'amount': '950.00'}]
    selection = confirmed_preview(scheduling, single)
    atomic_update = gestion._atomic_update_data

    def lose_local_confirmation(mutator, **kwargs):
        if mutator.__name__ == 'save_slot':
            raise OSError('Local write lost after Qonto and ledger confirmed the subscription')
        return atomic_update(mutator, **kwargs)

    monkeypatch.setattr(gestion, '_atomic_update_data', lose_local_confirmation)
    failed = confirm(scheduling, selection)
    assert failed.json['ok'] is False
    assert scheduling.create.call_count == 1
    assert not stored_line(scheduling)['directDebitInstallments'][0].get('qonto_direct_debit_subscription_id')
    monkeypatch.setattr(gestion, '_atomic_update_data', atomic_update)
    scheduling.subscriptions.clear()  # The bank no longer confirms that ledger ID.

    new_preview = preview(scheduling, single)
    rejected = confirm(scheduling, new_preview.json) if new_preview.status_code == 200 else new_preview
    assert rejected.status_code == 409, rejected.json
    assert rejected.json['ok'] is False
    assert stored_line(scheduling)['paymentPlan']['qontoSchedulingOperation']['state'] != 'completed'
    assert scheduling.create.call_count == 1


@pytest.mark.parametrize('last_page', ['other_dossier', 'missing_list'])
def test_every_remote_subscription_page_must_be_verified(scheduling, last_page):
    foreign = {
        'id': 'foreign-subscription', 'direct_debit_mandate_id': scheduling.mandate['id'],
        'client_id': scheduling.mandate['client_id'], 'bank_account_id': scheduling.bank_id,
        'reference': 'another-billing-line - échéance 1/2',
        'initial_collection_date': scheduling.schedule[0]['date'],
        'amount': {'value': '475.00', 'currency': 'EUR'},
        'schedule_type': 'one_off', 'status': 'pending',
    }

    def pages(_mandate_id, *, page, per_page):
        assert _mandate_id == scheduling.mandate['id']
        assert per_page == 100
        if page == 1:
            return {'direct_debit_subscriptions': [], 'meta': {'total_pages': 2, 'next_page': 2}}
        if last_page == 'missing_list':
            return {'meta': {'total_pages': 2}}
        return {'direct_debit_subscriptions': [foreign], 'meta': {'total_pages': 2}}

    scheduling.list_subscriptions.side_effect = pages
    rejected = preview(scheduling)
    assert rejected.status_code == 409, rejected.json
    assert [call.kwargs['page'] for call in scheduling.list_subscriptions.call_args_list] == [1, 2]
    scheduling.create.assert_not_called()
    assert stored_line(scheduling)['paymentPlan'] == {}


@pytest.mark.parametrize('raw_paid', [
    {'value': 'not-an-amount', 'currency': 'EUR'},
    {'value': '0.00', 'currency': 'USD'},
    {'value': '0.004', 'currency': 'EUR'},
])
def test_malformed_bank_paid_amount_is_not_treated_as_zero(scheduling, raw_paid):
    scheduling.invoice['amount_paid'] = raw_paid
    rejected = preview(scheduling)
    assert rejected.status_code == 409, rejected.json
    assert rejected.json['ok'] is False
    scheduling.create.assert_not_called()


def test_concurrent_confirmation_reserves_the_line_before_any_duplicate_post(scheduling):
    selection = confirmed_preview(scheduling)
    second_client = gestion.app.test_client()
    with scheduling.client.session_transaction() as auth:
        copied_auth = dict(auth)
    with second_client.session_transaction() as auth:
        auth.update(copied_auth)
    entered_bank = Event()
    release_bank = Event()

    def held_create(payload):
        entered_bank.set()
        assert release_bank.wait(10), 'Concurrent confirmation did not return promptly'
        return scheduling.record_subscription(payload)

    scheduling.create.side_effect = held_create
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(confirm, scheduling, selection)
        try:
            assert entered_bank.wait(10), 'First confirmation never reached the mocked bank'
            second = pool.submit(second_client.post, SCHEDULE,
                                 json={'selectionToken': selection['selectionToken']})
            rejected = second.result(timeout=5)
            assert rejected.status_code == 409, rejected.json
            assert scheduling.create.call_count == 1
        finally:
            release_bank.set()
        success = first.result(timeout=10)
    assert success.status_code == 200, success.json
    assert scheduling.create.call_count == 2
    assert len(scheduling.subscriptions) == 2
    assert stored_line(scheduling)['paymentPlan']['qontoSchedulingOperation']['state'] == 'completed'
