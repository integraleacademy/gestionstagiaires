from unittest.mock import patch

import pytest

import app as gestion


def subscription(sid, date, reference='Facture-1 - reprogrammation', **extras):
    return dict(id=sid, direct_debit_mandate_id='mandat', schedule_type='one_off',
                status='scheduled', schedule_next_collection_date=date, reference=reference,
                amount={'value': '367.50', 'currency': 'EUR'}) | extras


def test_same_day_subscriptions_history_dates_and_invoice_scope():
    line = {'id': 'ligne', 'qontoInvoiceNumber': 'Facture-1', 'qonto_direct_debit_mandate_id': 'mandat',
            'directDebitInstallments': [{'qonto_direct_debit_subscription_id': 'mensuel'}]}
    retries = [subscription(sid, '2026-11-10') for sid in ('a', 'b', 'c')]
    monthly = subscription('mensuel', '2026-11-30', 'Autre libellé', schedule_type='monthly',
                           initial_collection_date='2026-09-30')
    other = subscription('autre', '2026-11-10', 'Facture-10 - reprogrammation')
    foreign = subscription('hors-dossier', '2026-11-10', direct_debit_mandate_id='autre')
    cancelled = subscription('annulé', None, status='canceled')
    pages = [{'direct_debit_subscriptions': [other, foreign, *retries], 'meta': {'total_pages': 2}},
             {'direct_debit_subscriptions': [*retries, monthly, cancelled], 'meta': {'total_pages': 2}}]
    def fetch_collections(subscription_id, **_):
        rows = [{'id': 'op-1', 'direct_debit_subscription_id': 'mensuel', 'collection_date': '2026-10-02',
                 'amount': {'value': '367.50'}, 'status': 'declined', 'status_reason_code': 'AM04'}]
        rows.append(dict(rows[0], id='autre-op', direct_debit_subscription_id='autre'))
        return {'direct_debit_collections': rows}
    with patch.object(gestion, 'list_qonto_direct_debit_subscriptions', side_effect=pages), \
         patch.object(gestion, 'list_qonto_direct_debit_collections', side_effect=fetch_collections):
        upcoming, history, changes = gestion._trainee_bank_schedule([line])
    assert [row['id'] for row in upcoming] == ['a', 'b', 'c', 'mensuel']
    assert sum(row['amount_cents'] for row in upcoming if row['date'] == '2026-11-10') == 110250
    assert upcoming[-1]['frequency'] == 'monthly'
    assert [(change['id'], change['kind']) for change in changes] == [('annulé', 'subscription')]
    assert [(row['id'], row['date'], row['reason_code']) for row in history] == [('op-1', '2026-10-02', 'AM04')]


def test_incomplete_pages_do_not_return_zero_or_partial_history():
    with patch.object(gestion, 'list_qonto_direct_debit_subscriptions', return_value={'message': 'invalid'}):
        with pytest.raises(ValueError, match='incomplète'):
            gestion._trainee_bank_schedule([{'qonto_direct_debit_subscription_id': 'sub'}])


def test_bank_route_forbids_partner_and_does_not_call_qonto():
    client = gestion.app.test_client()
    url = '/api/billing/trainee/T/session/S/bank-schedule'
    with patch.object(gestion, '_qonto_request') as remote:
        assert client.get(url).status_code in {302, 401, 403}
        with client.session_transaction() as session:
            session['admin_logged_in'] = True
            session['admin_role'] = 'admin'
        with patch.object(gestion, '_is_partner_data_scope_session', return_value=True):
            assert client.get(url).status_code == 403
        with patch.object(gestion, '_financing_partner_module_enabled', return_value=False):
            assert client.get(url).status_code == 403
        remote.assert_not_called()


def test_bank_route_scopes_the_dossier_and_never_saves():
    client = gestion.app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
        session['admin_role'] = 'admin'
    with patch.object(gestion, 'load_data', return_value={}), \
         patch.object(gestion, '_billing_lines_for_trainee_session', return_value=[]) as scope, \
         patch.object(gestion, '_financing_partner_module_enabled', return_value=True), \
         patch.object(gestion, '_qonto_request') as remote, patch.object(gestion, 'save_data') as save:
        response = client.get('/api/billing/trainee/T/session/S/bank-schedule')
        assert response.status_code == 200
        assert response.json['upcoming'] == response.json['history'] == []
        scope.assert_called_once_with({}, 'T', 'S')
        remote.assert_not_called()
        save.assert_not_called()


def test_attached_collection_does_not_import_rest_of_an_external_plan():
    line = {'id': 'L', 'qonto_direct_debit_subscription_id': 'shared',
            'directDebitInstallments': [{'qonto_attachment': True, 'qonto_direct_debit_collection_id': 'attached',
                                         'qonto_direct_debit_subscription_id': 'shared'}]}
    rows = [dict(id=cid, direct_debit_subscription_id='shared', status='completed',
                 amount={'value': '10.00'}, collection_date='2026-11-01') for cid in ('attached', 'other')]
    with patch.object(gestion, 'list_qonto_direct_debit_subscriptions',
                      return_value={'items': [subscription('shared', '2026-11-10')]}), \
         patch.object(gestion, 'list_qonto_direct_debit_collections', return_value={'items': rows}):
        upcoming, history, changes = gestion._trainee_bank_schedule([line])
    assert upcoming == []
    assert [row['id'] for row in history] == ['attached']


def test_statement_dates_are_bijective_and_scoped_to_the_mandate():
    def collection(date, rum='EXACT'):
        return {'date': date, '_account': 'account', '_rum': rum, 'status': 'declined', 'amount_cents': 36750}
    def transaction(tid, date, rum='EXACT'):
        return {'id': tid, 'side': 'credit', 'status': 'declined', 'currency': 'EUR',
                'amount_cents': 36750, 'emitted_at': date+'T08:00:00Z', 'bank_account_id': 'account',
                'direct_debit_collection': {'unique_mandate_reference': rum}}
    history = {str(i): collection(d) for i, d in enumerate(['2020-09-30', '2020-10-01', '2020-10-10', '2020-10-30'])}
    txs = [transaction(str(i), d) for i, d in enumerate(['2020-09-30', '2020-10-02', '2020-10-12', '2020-10-30'])]
    gestion._match_debit_transaction_dates(history, txs + [transaction('other', '2020-10-01', 'OTHER')])
    assert [r['transaction_date'] for r in history.values()] == [
        '2020-09-30', '2020-10-02', '2020-10-12', '2020-10-30']
    ambiguous = {'a': collection('2020-10-10'), 'b': collection('2020-10-10')}
    gestion._match_debit_transaction_dates(ambiguous, txs)
    assert all('transaction_date' not in row for row in ambiguous.values())


def test_scheduled_collections_stay_out_of_history_and_missing_statement_dates_are_honest():
    sub = subscription('monthly', '2999-11-30', schedule_type='monthly', bank_account_id='A')
    def op(cid, status, day):
        return {'id': cid, 'direct_debit_subscription_id': 'monthly', 'collection_date': day,
                'amount': {'value': '367.50'}, 'status': status, 'unique_mandate_reference': 'RUM'}
    ops = [op('old','declined','2020-10-10'), op('future','scheduled','2999-11-30'),
           op('hold','on_hold','2999-11-10'), op('future-cancel','canceled','2999-12-30')]
    with patch.object(gestion, 'list_qonto_direct_debit_subscriptions', return_value={'items': [sub]}), \
         patch.object(gestion, 'list_qonto_direct_debit_collections', return_value={'items': ops}), \
         patch.object(gestion, '_qonto_request', side_effect=ValueError('unavailable')):
        upcoming, history, changes = gestion._trainee_bank_schedule([{'qonto_direct_debit_subscription_id': 'monthly'}])
    assert [row['id'] for row in upcoming] == ['monthly']
    assert [row['id'] for row in history] == ['old']
    assert [(change['id'], change['planned_date']) for change in changes] == [('future-cancel', '2999-12-30')]
    assert history[0]['date'] == '2020-10-10' and 'transaction_date' not in history[0]
    assert '_rum' not in history[0] and '_account' not in history[0]


def test_finite_recurrence_reserves_only_unissued_and_unsettled_collections():
    sub = subscription('monthly', '2026-12-04', schedule_type='monthly', schedule_total_collection_count=4)
    ops = [dict(id=str(i), direct_debit_subscription_id='monthly', collection_date='2026-10-04',
                status=status, amount={'value': value})
           for i, (status, value) in enumerate([('completed', '367.50'), ('declined', '367.50'), ('on_hold', '200.00')])]
    with patch.object(gestion, 'list_qonto_direct_debit_subscriptions', return_value={'items': [sub]}), \
         patch.object(gestion, 'list_qonto_direct_debit_collections', return_value={'items': ops + [ops[-1]]}):
        upcoming, history, changes = gestion._trainee_bank_schedule([{'qonto_direct_debit_subscription_id': 'monthly'}])
    assert [(r['remaining_count'], r['remaining_cents']) for r in upcoming] == [(2, 56750)]
    assert len(history) == 2
    assert [r['id'] for r in upcoming[0]['open_collections']] == ['2']


def test_one_off_is_not_still_programmed_once_its_collection_is_returned():
    sub = subscription('once', None, status='in_progress')
    row = dict(id='attempt', direct_debit_subscription_id='once', collection_date='2026-10-04',
               status='returned', amount={'value': '539.50'})
    with patch.object(gestion, 'list_qonto_direct_debit_subscriptions', return_value={'items': [sub]}), \
         patch.object(gestion, 'list_qonto_direct_debit_collections', return_value={'items': [row]}):
        upcoming, history, changes = gestion._trainee_bank_schedule([{'qonto_direct_debit_subscription_id': 'once'}])
    assert upcoming == []
    assert history[0]['status'] == 'returned'


def test_cancellations_use_the_actual_action_date_on_both_sides_of_the_planned_date():
    sub = subscription('series', None, status='canceled', schedule_type='monthly',
                       initial_collection_date='2020-10-01')
    line = {'qonto_direct_debit_subscription_id': 'series'}
    past = dict(id='past', direct_debit_subscription_id='series', collection_date='2020-12-01',
                status='canceled', amount={'value': '367.50'}, updated_at='2020-12-03T10:00:00Z')
    future = dict(past, id='future', collection_date='2999-01-01', cancelled_at='2020-11-30T09:42:00Z')
    with patch.object(gestion, 'list_qonto_direct_debit_subscriptions', return_value={'items': [sub]}), \
         patch.object(gestion, 'list_qonto_direct_debit_collections', return_value={'items': [past, future, past]}):
        upcoming, history, changes = gestion._trainee_bank_schedule([line])

    assert upcoming == history == []
    assert [(c['kind'], c['id'], c['date'], c['planned_date']) for c in changes] == [
        ('subscription', 'series', None, None),
        ('collection', 'past', None, '2020-12-01'),
        ('collection', 'future', '2020-11-30T09:42:00Z', '2999-01-01'),
    ]
    assert changes[0]['frequency'] == 'monthly'
    assert [c['subscription_id'] for c in changes[1:]] == ['series', 'series']


def test_bank_statement_matches_keep_local_day_and_only_sourced_time():
    def match(stamp):
        history = {'C': {'date': '2026-11-08', '_account': 'A', '_rum': 'RUM',
                         'status': 'completed', 'amount_cents': 100}}
        transaction = {'id': 'T', 'side': 'credit', 'status': 'completed', 'currency': 'EUR',
                       'amount_cents': 100, 'settled_at': stamp, 'bank_account_id': 'A',
                       'direct_debit_collection': {'unique_mandate_reference': 'RUM'}}
        gestion._match_debit_transaction_dates(history, [transaction])
        return history['C']

    late = match('2026-11-07T23:30:00Z')
    assert late['transaction_date'] == '2026-11-08'
    assert late['transaction_at'] == '2026-11-08T00:30:00+01:00'
    day = match('2026-11-08')
    assert day['transaction_date'] == '2026-11-08'
    assert 'transaction_at' not in day
