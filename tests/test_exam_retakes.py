"""Financial and enrolment invariants of the retake workflow (no live services)."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask, session

import exam_retakes as retakes
import exam_retakes_workflow as workflow
from exam_retakes_documents import build_convention


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(retakes,'today',lambda:'2026-10-30')
    monkeypatch.setattr(workflow,'today',lambda:'2026-10-30')
    app=Flask(__name__,template_folder=str(Path('templates').resolve()))
    app.secret_key='isolated-retake-tests'
    app.testing=True
    person={'id':'T1','first_name':'Camille','last_name':'TEST','email':'camille@example.test','phone':'0612345678',
            'address':'10 rue des Tests','zip_code':'83480','city':'Puget-sur-Argens','public_token':'token-t1','birth_date':''}
    source={'id':'SOURCE','name':'APS octobre','training_type':'APS','exam_date':'2026-10-12','trainees':[person]}
    target={'id':'TARGET','name':'APS décembre','training_type':'APS','exam_date':'2026-12-09','trainees':[]}
    data={'sessions':[source,target,{'id':'WRONG','training_type':'A3P','exam_date':'2026-11-02','trainees':[]}]}
    def login(fn):
        from functools import wraps
        @wraps(fn)
        def wrapped(*a,**kw):
            from flask import abort
            if not session.get('admin_logged_in'):abort(401)
            return fn(*a,**kw)
        return wrapped
    def write(fn):
        from functools import wraps
        @wraps(fn)
        def wrapped(*a,**kw):
            from flask import abort
            if session.get('admin_role')=='viewer':abort(403)
            return fn(*a,**kw)
        return wrapped
    import email_design
    result=SimpleNamespace(app=app,PERSIST_DIR=str(tmp_path),INTEGRALE_PARTNER_ID='integrale',
        PUBLIC_STUDENT_PORTAL_BASE='https://academy.example.test',
        admin_login_required=login,admin_write_required=write,
        load_data=lambda **kw:data,find_session=lambda data,sid:next((s for s in data['sessions'] if s['id']==sid),None),
        _session_trainees_list=lambda s:s.get('trainees',[]),_session_get=lambda s,k,d='':s.get(k,d),
        _is_aps_working_day=lambda day:day.weekday()<5,
        afc_schedule=SimpleNamespace(enabled=lambda s:s.get('afc_enabled',False)),_is_wedof_leads_session=lambda s:False,
        _yousign_state=lambda t:t.get('yousign',{}),_automation_document_config=lambda s:{'convention_template':'conventionaps.docx'},
        _normalize_yousign_sms_phone=lambda p:'+33612345678' if p else '',
        _yousign_is_configured=lambda:True,_missing_brevo_config=lambda:[],_qonto_is_configured=lambda:True,
        get_qonto_invoice_iban=lambda:'FR7600000000000000000000000',_qonto_oauth_connected=lambda *a:True,
        _qonto_oauth_has_scope=lambda *a:True,_sanitize_qonto_error=str,_sanitize_yousign_error=str,
        render_academy_email=email_design.render_email,YOUSIGN_SMS_AUTHENTICATION_MODE='otp_sms',
        _extract_yousign_signature_link=lambda p,*a:p.get('signature_link',''),
        _yousign_signature_request_items=lambda p:p if isinstance(p,list) else p.get('data',[]),
        _iter_qonto_invoice_payloads=lambda p:p.get('client_invoices',[]),
        _qonto_invoice_list_has_next_page=lambda *a:False,
        _qonto_invoice_payload=lambda p:p.get('client_invoice',p),
        build_qonto_client_payload=lambda *a,**kw:{'kind':'individual','email':person['email']},
        get_or_create_qonto_billing_client=Mock(return_value={'client':{'id':'client-1'}}),
        brevo_send_email=Mock(return_value={'ok':True,'message_id':'mail-1'}),
        find_session_and_trainee_by_token=lambda d,t:(source,person) if t=='token-t1' else (None,None),
        _public_is_authed=lambda token:session.get('public_token')==token)
    result.app.root_path=str(Path('.').resolve())
    retakes.register(app,result)
    def normalize(invoice,local):
        total=retakes.cents(invoice['total_amount']['value'])
        paid=invoice.get('amount_paid_cents',total if invoice['status']=='paid' else 0)
        return {'qonto_payment_status':'paid' if paid==total else 'partially_paid' if paid else 'unpaid','qonto_amount_paid_cents':paid}
    result.normalize_qonto_invoice_payment_data=normalize
    return result


@pytest.fixture
def client(host):
    client=host.app.test_client()
    with client.session_transaction() as s:s.update(admin_logged_in=True,admin_role='admin')
    return client


def payload(client,**changes):
    initial=client.get('/api/sessions/SOURCE/stagiaires/T1/rattrapages').json
    return dict({'csrf':initial['csrf'],'kind':'APS','target_session':'TARGET','exam_date':'2026-12-09','exam_time':'09:00',
                 'exam_price':'80','day_price':'90','exam_offered':False,'days_offered':False,'no_days':True,'days':[],
                 'location':'54 chemin du Carreou, Puget-sur-Argens','notes':''},**changes)


def saved(host,client,**changes):
    response=client.post('/api/sessions/SOURCE/stagiaires/T1/rattrapages',json=payload(client,**changes))
    assert response.status_code==200,response.json
    return retakes.Store(host).get(response.json['record']['id'])


def providers(host,store,row):
    signature={'status':'draft','id':'signature-1'}
    invoice={'id':'invoice-1','status':'draft','number':'F-2026-1','purchase_order':'RET-'+row['id'],
             'client':{'id':'client-1'},'organization_id':'org-1','total_amount':{'value':f"{row['total_cents']/100:.2f}",'currency':'EUR'}}
    def yousign(method,path,**kwargs):
        if path=='/signature_requests':return copy.deepcopy(signature)
        if path.endswith('/documents'):return {'id':'document-1'}
        if path.endswith('/signers'):
            assert kwargs['json']['signature_authentication_mode']=='otp_sms'
            assert kwargs['json']['fields'][0]['page']>=1
            return {'id':'signer-1'}
        if path.endswith('/activate'):
            signature['status']='ongoing'
            return copy.deepcopy(signature)
        if '/signers/' in path:return {'id':'signer-1','signature_link':'https://yousign.example.test/sign'}
        return copy.deepcopy(signature)
    host._yousign_json=Mock(side_effect=yousign)
    host._yousign_request=Mock(side_effect=lambda *a,**kw:SimpleNamespace(content=store.document(row['id'],'convention').read_bytes()))
    def qonto(method,path,payload=None,**kwargs):
        if path=='/v2/client_invoices':return {'client_invoice':copy.deepcopy(invoice)}
        if path.startswith('/v2/client_invoices/'):return {'client_invoice':copy.deepcopy(invoice)}
        if path=='/v2/payment_links/payment_methods':return {'payment_link_payment_methods':[{'enabled':True,'name':'credit_card'}]}
        if path.startswith('/v2/payment_links'):
            return {'payment_link':{'id':'payment-1','invoice_id':'invoice-1','amount':invoice['total_amount'],'url':'https://pay.qonto.com/retake-1','status':'open'}}
        raise AssertionError((method,path,payload))
    host._qonto_request=Mock(side_effect=qonto)
    host.get_qonto_invoice=Mock(side_effect=lambda _: {'client_invoice':copy.deepcopy(invoice)})
    host.finalize_qonto_invoice=Mock(side_effect=lambda _:invoice.update(status='unpaid'))
    host.fetch_qonto_client_invoice_pdf=Mock(side_effect=lambda _: (store.document(row['id'],'convention').read_bytes(),'invoice.pdf'))
    return signature,invoice


def send(client,row):
    csrf=client.get('/api/sessions/SOURCE/stagiaires/T1/rattrapages').json['csrf']
    return client.post('/api/rattrapages/'+row['id']+'/send',json={'csrf':csrf,'revision':row['revision']})


def test_nearest_matching_exam_and_contract_defaults(host,client):
    host.load_data()['sessions'].extend([{'id':'LATER','name':'Later','training_type':'APS','exam_date':'2027-02-01'},
                                       {'id':'OLD','name':'Old','training_type':'APS','exam_date':'2026-10-01'},
                                       {'id':'TENANT','partner_id':'another','training_type':'APS','exam_date':'2026-11-01'}])
    data=client.get('/api/sessions/SOURCE/stagiaires/T1/rattrapages').json
    default=data['defaults'][0]
    assert [r['id'] for r in default['sessions']]==['TARGET','LATER']
    assert default['prices']['exam_price']=='80.00'
    assert default['prices']['day_price']=='90.00'


def test_saved_individual_contract_has_priority(host,tmp_path):
    from docx import Document
    path=tmp_path/'custom.docx';d=Document();d.add_paragraph("La représentation à l’examen est facturée : 125 € TTC. La journée de rattrapage est facturée : 110 € TTC.");d.save(path)
    data=host.load_data();person=data['sessions'][0]['trainees'][0];person['convention_aps_docx_path']=str(path)
    result=retakes.prices(host,data['sessions'][0],person,'APS')
    assert result['exam_price']=='125.00' and result['day_price']=='110.00'


@pytest.mark.parametrize('changes',[
    {'exam_price':'-1'},{'exam_price':'NaN'},{'exam_price':'Infinity'},{'exam_date':'2026-10-01'},
    {'failed_exam_date':'2026-11-15'},{'failed_exam_date':'not-a-date'},
    {'target_session':'WRONG'},{'no_days':False,'days':[]},
    {'no_days':False,'days':[{'date':'2026-12-10'}]},
    {'no_days':False,'days':[{'date':'2026-11-01'},{'date':'2026-11-01'}]},
    {'no_days':False,'days':[{'date':'2026-11-01','start':'18:00','end':'09:00'}]},
])
def test_invalid_data_never_saved(host,client,changes):
    response=client.post('/api/sessions/SOURCE/stagiaires/T1/rattrapages',json=payload(client,**changes))
    assert response.status_code==400
    assert retakes.Store(host).query()==[]


def test_price_override_and_gifts_are_independent(host,client):
    row=saved(host,client,exam_price='97.45',no_days=False,days=[{'date':'2026-11-02'},{'date':'2026-11-03'}],day_price='80.35',days_offered=True)
    assert row['total_cents']==9745
    assert row['day_cents']==8035 and len(row['days'])==2
    assert row['signature_field']['y']>0
    text='\n'.join(p.extract_text() for p in workflow.PdfReader(retakes.Store(host).document(row['id'],'convention')).pages)
    assert '97,45' in text and 'Offert' in text and '02/11/2026' in text


def test_paid_end_to_end_is_idempotent_and_never_counts_as_enrolment(host,client):
    before=copy.deepcopy(host.load_data())
    row=saved(host,client,no_days=False,days=[{'date':'2026-11-02'}])
    store=retakes.Store(host);signature,invoice=providers(host,store,row)
    assert send(client,row).status_code==200
    row=store.get(row['id']);workflow.process(host,store,row)
    assert row['status']=='signing' and host._qonto_request.call_count==0
    signature['status']='done';workflow.process(host,store,row)
    assert row['status']=='payment' and row['total_cents']==17000
    assert host.brevo_send_email.call_count==2
    message=host.brevo_send_email.call_args
    assert len(message.kwargs['attachments'])==2 and 'https://pay.qonto.com/retake-1' in message.args[2]
    with host.app.test_request_context():assert retakes.roster(host,'TARGET')==[]
    invoice.update(status='paid');workflow.process(host,store,row);workflow.process(host,store,row)
    assert row['status']=='confirmed'
    assert host.brevo_send_email.call_count==3
    creates=[c for c in host._qonto_request.call_args_list if c.args[:2]==('POST','/v2/client_invoices')]
    assert len(creates)==1
    with host.app.test_request_context():assert len(retakes.roster(host,'TARGET'))==1
    assert host.load_data()==before


def test_free_retakes_skip_qonto_entirely(host,client):
    row=saved(host,client,exam_offered=True,no_days=False,days_offered=True,days=[{'date':'2026-11-02'}])
    store=retakes.Store(host);signature,_=providers(host,store,row)
    assert send(client,row).status_code==200
    row=store.get(row['id']);workflow.process(host,store,row);signature['status']='done';workflow.process(host,store,row)
    assert row['status']=='confirmed' and row['payment_status']=='not_required'
    host._qonto_request.assert_not_called();host.get_or_create_qonto_billing_client.assert_not_called()
    assert len(host.brevo_send_email.call_args.kwargs['attachments'])==1


def test_paid_status_with_partial_amount_does_not_confirm(host,client):
    row=saved(host,client);store=retakes.Store(host);signature,invoice=providers(host,store,row)
    send(client,row);row=store.get(row['id']);workflow.process(host,store,row);signature['status']='done';workflow.process(host,store,row)
    invoice.update(status='paid',amount_paid_cents=3000)
    with pytest.raises(retakes.RetakeError,match='partiel'):workflow.process(host,store,row)
    assert row['status']=='payment' and not row['payment_url']
    with host.app.test_request_context():assert retakes.roster(host,'TARGET')==[]


def test_uncertain_invoice_is_recovered_without_new_creation(host,client):
    row=saved(host,client);store=retakes.Store(host);_,invoice=providers(host,store,row)
    row.update(submitted_at=retakes.now(),client_id='client-1',invoice_started=retakes.now())
    host.list_qonto_invoices=Mock(return_value={'client_invoices':[invoice]})
    workflow.ensure_invoice(host,store,row)
    assert row['invoice_id']=='invoice-1'
    assert not any(c.args[:2]==('POST','/v2/client_invoices') for c in host._qonto_request.call_args_list)


def test_uncertain_invoice_not_found_blocks_duplicate(host,client):
    row=saved(host,client);store=retakes.Store(host);providers(host,store,row)
    row.update(submitted_at=retakes.now(),client_id='client-1',invoice_started=retakes.now())
    host.list_qonto_invoices=Mock(return_value={'client_invoices':[]})
    with pytest.raises(retakes.RetakeError,match='aucune seconde'):workflow.ensure_invoice(host,store,row)
    host._qonto_request.assert_not_called()


def test_send_locks_contract_and_checks_revision(host,client):
    row=saved(host,client)
    assert send(client,row).status_code==200
    assert send(client,row).status_code==409
    update=payload(client,id=row['id'],revision=row['revision'],exam_price='1')
    assert client.post('/api/sessions/SOURCE/stagiaires/T1/rattrapages',json=update).status_code==400
    assert retakes.Store(host).get(row['id'])['exam_cents']==8000


def test_duplicate_open_retakes_and_concurrent_lock(host,client):
    row=saved(host,client);store=retakes.Store(host)
    assert client.post('/api/sessions/SOURCE/stagiaires/T1/rattrapages',json=payload(client)).status_code==400
    with store.lock(row['id']):
        assert send(client,row).status_code==409


def test_csrf_roles_and_public_ownership(host,client):
    raw=payload(client);raw['csrf']='wrong'
    assert client.post('/api/sessions/SOURCE/stagiaires/T1/rattrapages',json=raw).status_code==403
    row=saved(host,client);store=retakes.Store(host)
    row['status']='signing';store.save(row)
    path='/espace/token-t1/rattrapages/'+row['id']+'/convention.pdf'
    assert client.get(path).status_code==403
    with client.session_transaction() as s:s['public_token']='token-t1'
    assert client.get(path).status_code==200
    assert client.get(path.replace('token-t1','token-other')).status_code==403
    with client.session_transaction() as s:s['admin_role']='viewer'
    assert send(client,row).status_code==403


def test_webhook_only_queues_provider_verification(host,client):
    row=saved(host,client);store=retakes.Store(host)
    row.update(status='payment',invoice_id='inv-1',request_id='req-1',next_attempt=9999999999);store.save(row)
    assert retakes.notify(host,invoice_id='inv-1')
    assert store.get(row['id'])['status']=='payment'
    assert store.query('next_attempt=0')[0]['id']==row['id']
    assert not retakes.notify(host,invoice_id='unrelated')


def test_pdf_many_days_has_signature_on_last_page(host,client):
    row=saved(host,client,no_days=False,days=[{'date':f'2026-11-{i:02d}','topic':'Révisions détaillées et entraînement aux situations professionnelles.'} for i in range(1,21)])
    reader=workflow.PdfReader(retakes.Store(host).document(row['id'],'convention'))
    assert len(reader.pages)>1
    assert row['signature_field']['page']==len(reader.pages)
    assert 0<row['signature_field']['y']<760


def test_target_changed_after_review_cannot_be_sent(host,client):
    row=saved(host,client)
    host.load_data()['sessions'][1]['partner_id']='other'
    assert send(client,row).status_code==409
    assert retakes.Store(host).get(row['id'])['status']=='draft'


def test_archived_target_blocks_side_effects(host,client):
    row=saved(host,client);store=retakes.Store(host);providers(host,store,row)
    send(client,row);row=store.get(row['id'])
    host.load_data()['sessions'][1]['archived']=True
    with pytest.raises(retakes.RetakeError,match='archivée'):workflow.process(host,store,row)
    host._yousign_json.assert_not_called();host._qonto_request.assert_not_called()


def test_modified_convention_cannot_be_uploaded(host,client):
    row=saved(host,client);store=retakes.Store(host);providers(host,store,row)
    send(client,row);row=store.get(row['id'])
    store.document(row['id'],'convention').write_bytes(b'changed')
    with pytest.raises(retakes.RetakeError,match='a changé'):workflow.process(host,store,row)
    host._yousign_json.assert_not_called()


def test_missing_signed_pdf_is_recovered_before_email(host,client):
    row=saved(host,client);store=retakes.Store(host);signature,_=providers(host,store,row)
    send(client,row);row=store.get(row['id']);workflow.process(host,store,row)
    signature['status']='done';workflow.process(host,store,row)
    store.document(row['id'],'signed').unlink()
    workflow.process(host,store,row)
    assert store.document(row['id'],'signed').is_file()
    assert host._yousign_request.call_count==2
    assert len([c for c in host._qonto_request.call_args_list if c.args[:2]==('POST','/v2/client_invoices')])==1


def test_discounts_are_itemized_in_agreement_email_and_qonto(host,client):
    from exam_retakes_documents import email_content
    row=saved(host,client,exam_price='60',day_price='70',no_days=False,
              days=[{'date':'2026-12-07'},{'date':'2026-12-08'}],failed_exam_details='Épreuve pratique à retravailler')
    items=retakes.line_items(row)
    assert [(i['discount_cents'],i['discount_percent']) for i in items]==[(2000,'25.00'),(4000,'22.22')]
    assert retakes.financial_totals(row)=={'gross_cents':26000,'discount_cents':6000,'offered_cents':0,'total_cents':20000}
    store=retakes.Store(host);pdf=workflow.PdfReader(store.document(row['id'],'convention'))
    content='\n'.join(p.extract_text() for p in pdf.pages)
    assert '12/10/2026' in content and 'Remises commerciales accordées' in content and '60,00 €' in content
    assert len(pdf.pages[0].images)>0
    _,html,text=email_content(host,row,'documents','https://pay.qonto.com/test')
    assert 'Remise de 20,00 € (25 %)' in html and 'Remise de 40,00 € (22,22 %)' in text
    providers(host,store,row);workflow.ensure_invoice(host,store,row)
    call=next(c for c in host._qonto_request.call_args_list if c.args[:2]==('POST','/v2/client_invoices'))
    assert call.args[2]['items'][0]['unit_price']['value']=='60.000000'
    assert call.args[2]['items'][1]['unit_price']['value']=='70.000000'
    assert 'Remise de 40,00 € (22,22 %)' in call.args[2]['items'][1]['description']


def test_offered_and_discounted_components_are_not_counted_twice(host,client):
    row=saved(host,client,exam_price='60',exam_offered=True,day_price='70',no_days=False,days=[{'date':'2026-12-07'},{'date':'2026-12-08'}])
    assert retakes.financial_totals(row)=={'gross_cents':26000,'discount_cents':4000,'offered_cents':8000,'total_cents':14000}
    row['price_reference']={};row['exam_offered']=False
    assert retakes.financial_totals(row)=={'gross_cents':20000,'discount_cents':0,'offered_cents':0,'total_cents':20000}


def test_draft_edit_keeps_its_original_price_reference(host,client,monkeypatch):
    row=saved(host,client)
    monkeypatch.setattr(retakes,'prices',lambda *a:{'exam_price':'200','day_price':'200','source':'Changed'})
    response=client.post('/api/sessions/SOURCE/stagiaires/T1/rattrapages',json=payload(client,id=row['id'],revision=row['revision'],exam_price='60'))
    assert response.status_code==200,response.json
    stored=retakes.Store(host).get(row['id'])
    assert stored['price_reference']['exam_price']=='80.00'
    assert retakes.financial_totals(stored)['discount_cents']==2000


def test_legacy_draft_must_be_reviewed_before_signature(host,client):
    row=saved(host,client);store=retakes.Store(host)
    row.pop('document_version');row.pop('failed_exam_date');store.save(row)
    assert send(client,row).status_code==409
    assert store.get(row['id'])['status']=='draft'
    response=client.post('/api/sessions/SOURCE/stagiaires/T1/rattrapages',json=payload(client,id=row['id'],revision=row['revision']))
    assert response.status_code==200,response.json
    updated=store.get(row['id'])
    assert updated['document_version']==2 and updated['failed_exam_date']=='2026-10-12'
    assert send(client,updated).status_code==200
