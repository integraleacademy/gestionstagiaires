from copy import deepcopy
from unittest.mock import patch

import app as host


def debit(date, cid='', status='scheduled', **extra):
    return {'date': date, 'amount': 367.5, 'status': status,
            'qonto_direct_debit_subscription_id': 'monthly', 'qonto_direct_debit_collection_id': cid, **extra}


def test_review_is_idempotent_scoped_and_preserves_unpaid_rows_then_rearms():
    rows = [debit('2026-09-30', 'A', 'failed'), debit('2026-10-30', 'B', 'declined')]
    line = {'id':'line','paymentMode':'sepa_direct_debit','financingType':'PERSONNEL','directDebitInstallments':rows,
            'qonto_direct_debit_mandate_id':'mandat','qonto_mandate_status':'active'}
    data = {'billing_lines':[deepcopy(line)],'notifications_admin':[{'meta':{'kind':'qonto_direct_debit_rejected',
             'billing_line_id':'line','collection_id':'A'}}]}
    client = host.app.test_client()
    with client.session_transaction() as s:
        s.update(admin_logged_in=True, admin_role='admin')
    url='/api/billing/trainee/T/session/S/acknowledge-rejections'
    def submit(keys):
        return client.post(url,json={'rejections':{'line':keys}})
    with patch.object(host,'_atomic_update_data',side_effect=lambda fn:fn(data)), \
         patch.object(host,'_billing_lines_for_trainee_session',return_value=[line]), \
         patch.object(host,'_financing_partner_module_enabled',return_value=True), \
         patch.object(host,'_qonto_request',side_effect=AssertionError('no bank writes')) as remote:
        stale = deepcopy(line)
        assert submit(['collection:unknown']).status_code == 409
        assert submit(['collection:A','collection:B']).status_code == 200
        assert data['notifications_admin'][0]['done']
        assert submit(['collection:A','collection:B']).status_code == 200
        assert len(line['logs']) == 1
        assert host._reviewed_debit_rejections(line)['pending'] == []
        assert host._qonto_payment_global_status(line) == 'Rejet traité'
        assert len(host._effective_sepa_installments(line)) == 2
        assert host._paid_sepa_collections(line) == []
        host._save_billing_line(data,stale)
        assert set(data['billing_lines'][0]['reviewedDebitRejections']) == {'collection:A','collection:B'}
        rows.append(debit('2026-10-30', 'NEW','failed'))
        assert host._reviewed_debit_rejections(line)['pending'] == ['collection:NEW']
        assert host._qonto_payment_global_status(line) == 'Rejeté'
        assert submit(['collection:A','collection:B']).status_code == 200
        assert host._reviewed_debit_rejections(line)['pending'] == ['collection:NEW']
        remote.assert_not_called()


def test_signed_bank_proof_scoped_to_dossier_before_regular_sync():
    line={'id':'L','financingType':'PERSONNEL','directDebitInstallments':[]}
    client=host.app.test_client()
    with client.session_transaction() as s:
        s.update(admin_logged_in=True,admin_role='admin')
    with patch.object(host,'load_data',return_value={}), patch.object(host,'_atomic_update_data',side_effect=lambda fn:fn({})), \
         patch.object(host,'_billing_lines_for_trainee_session',return_value=[line]), patch.object(host,'_financing_partner_module_enabled',return_value=True), \
         patch.object(host,'_trainee_bank_schedule',return_value=([],[{'id':'Q','status':'declined'}])):
        base='/api/billing/trainee/T/session/S/'
        proof=client.get(base+'bank-schedule').json['rejectionProof']
        payload={'bankProof':proof,'rejections':{'L':['collection:Q']}}
        assert client.post(base.replace('/T/','/other/')+'acknowledge-rejections',json=payload).status_code == 409
        assert client.post(base+'acknowledge-rejections',json=payload).status_code == 200
        assert host._reviewed_debit_rejections(line)['treated']==['collection:Q']


def test_initial_schedule_prefers_original_rows_over_a_stale_count_and_survives_edits():
    rows=[debit('2026-'+m+'-30') for m in ['09','10','11','12']]
    line={'id':'L','amountTTC':1470,'directDebitInstallments':rows+[debit('2026-11-10',is_rejection_retry=True)],
          'paymentPlan':{'installments':5}}
    data={'billing_lines':[]}
    host._save_billing_line(data,line)
    original=deepcopy(data['billing_lines'][0]['initialDebitSchedule'])
    assert [r['date'] for r in original]==[r['date'] for r in rows]
    line['paymentPlan']={'schedule':[{'date':'2027-01-01','amount':1470}]}
    line['directDebitInstallments']=[]
    host._save_billing_line(data,line)
    assert data['billing_lines'][0]['initialDebitSchedule']==original


def test_legacy_rejection_stays_reviewed_when_bank_adds_its_id_once():
    row=debit('2026-09-30',status='failed')
    old=host._debit_rejection_key(row)
    records={old:{'at':'2026-10-01'}}
    row['qonto_direct_debit_collection_id']='FIRST'
    records=host._bind_legacy_debit_reviews(records,[row])
    assert 'collection:FIRST' in records
    row['qonto_direct_debit_collection_id']='SECOND'
    assert 'collection:SECOND' not in host._bind_legacy_debit_reviews(records,[row])
