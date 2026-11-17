"""Reviewed standard enrolments and persistent list preferences, with no external calls."""
import copy
import json
from unittest.mock import Mock

import app
from integrale_edof_invoices import find_local_invoice
from test_integrale_edof_dashboard import site
from test_edof_enrolment import prepare, BASE, HEADERS


def test_reviewed_form_uses_standard_creation_and_convention_workflow(monkeypatch):
    fields = {'folder_id':'100000','state':'accepted','first_name':'Anne','last_name':'Exemple',
              'title':'Formation VTC','session_start_date':'2027-01-04','session_end_date':'2027-02-04',
              'total_incl':'1500.00','birth_date':'1988-02-12','email':'anne@example.invalid'}
    training = {'id':'s1','name':'VTC janvier','training_type':'VTC','date_start':'2027-01-04',
                'date_end':'2027-02-04','trainees':[]}
    data = {'sessions':[training]}
    monkeypatch.setattr(app,'load_data',lambda *a,**kw:copy.deepcopy(data))
    monkeypatch.setattr(app,'_atomic_update_data',lambda fn:fn(data))
    monkeypatch.setattr(app,'save_data',Mock(side_effect=AssertionError('Must save atomically')))
    monkeypatch.setattr(app,'_apply_pending_cnaps_imports_for_trainee',Mock())
    monkeypatch.setattr(app,'increment_partner_trainee_usage',Mock())
    monkeypatch.setattr(app,'_automation_is_enabled',lambda _:True)
    monkeypatch.setattr(app,'_automation_document_config',lambda _:{'slug':'vtc'})
    mail,sms=Mock(),Mock()
    monkeypatch.setattr(app,'brevo_send_email',mail)
    monkeypatch.setattr(app,'brevo_send_sms',sms)
    monkeypatch.setitem(app.app.extensions,'edof_registration_prefill',lambda folder,sid:fields)
    client=app.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True,admin_role='admin')
    payload={**fields,'phone':'0699999999','city':'Paris','edof_folder':'100000','send_access':False}
    response=client.post('/api/sessions/s1/trainees/create',json=payload)
    assert response.status_code==200,response.json
    result=response.json
    assert result['convention_preview_url'] and result['convention_financing_url'] and result['convention_signature_url']
    trainee=training['trainees'][0]
    assert trainee['phone']=='0699999999' and trainee['city']=='PARIS'
    assert trainee['training_price']=='1500.00' and trainee['financing_type']=='CPF'
    assert trainee['documents'] and len(data['wedof_links'])==1
    assert client.post('/api/sessions/s1/trainees/create',json=payload).status_code==409
    assert len(training['trainees'])==1
    mail.assert_not_called();sms.assert_not_called()


def test_registration_hide_is_reversible_scoped_and_does_not_change_folder(site):
    from bs4 import BeautifulSoup
    prepare(site)
    before=site.local.read_text()
    url=BASE+'/registration-preference'
    page=lambda tab:BeautifulSoup(site.client.get('/admin/edof-test?group=training&tab='+tab).text,'html.parser')
    assert page('to_register').select_one('[data-edof-folder="100000"]')
    assert site.client.post(url,data={'csrf':'bad','ignore':'1'},headers=HEADERS).status_code==403
    assert site.client.post(url,data={'csrf':site.csrf,'ignore':'1'},headers=HEADERS).json['ignored']
    assert not page('to_register').select_one('[data-edof-folder="100000"]')
    assert page('association_ignored').select_one('[data-edof-folder="100000"] input[checked]')
    assert site.local.read_text()==before
    assert not site.client.post(url,data={'csrf':site.csrf},headers=HEADERS).json['ignored']
    assert page('to_register').select_one('[data-edof-folder="100000"]')
    with site.client.session_transaction() as session:session['admin_role']='viewer'
    assert site.client.post(url,data={'csrf':site.csrf,'ignore':'1'},headers=HEADERS).status_code==403


def test_invoice_lookup_uses_exact_folder_and_never_another_cpf_invoice():
    data={'sessions':[{'id':'s','trainees':[{'id':'t'}]}],
          'wedof_links':[{'active':True,'external_id':'100000','session_id':'s','trainee_id':'t'}],
          'billing_lines':[{'sessionId':'s','traineeId':'t','financingType':'CPF','financingRef':'wedof:999999',
                            'invoiceStatus':'issued','qontoInvoiceId':'wrong'}]}
    assert find_local_invoice(data,'100000','integrale')==''
    data['billing_lines'].append({**data['billing_lines'][0],'financingRef':'wedof:100000','qontoInvoiceId':'correct'})
    assert find_local_invoice(data,'100000','integrale')=='correct'
    data['sessions'][0]['partner_id']='other'
    assert find_local_invoice(data,'100000','integrale')==''
