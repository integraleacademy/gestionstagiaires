import copy
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app

BASE = '/api/admin/sessions/S1/afc-documents'
BREVO_TRANSPORT = app.brevo_send_email
CREATE_SIGNATURE = app.create_yousign_convention_signature


@pytest.fixture
def case(monkeypatch, tmp_path):
    trainee = {'id':'T1','first_name':'Camille','last_name':'MARTIN','email':'camille@example.test',
               'phone':'0612345678','training_date_start':'2026-11-18','afc_ran_hours':40}
    training = {'id':'S1','name':'AFC APS + SSIAP 1','training_type':'APS','afc_enabled':True,
                'date_start':'2026-11-16','date_end':'2027-02-15','exam_date':'2027-01-21',
                'ssiap_exam_date':'2027-02-15','trainees':[trainee]}
    data = {'sessions':[training]}
    monkeypatch.setattr(app,'DATA_FILE',str(tmp_path/'data.json'))
    monkeypatch.setattr(app,'load_data',lambda **kw:copy.deepcopy(data))
    monkeypatch.setattr(app,'save_data',Mock())
    monkeypatch.setattr(app,'_atomic_update_data',lambda fn:fn(data))
    monkeypatch.setattr(app,'_automation_partner_module_enabled',lambda:True)
    monkeypatch.setattr(app,'_store_public_file_token',lambda p:'file-token')
    monkeypatch.setattr(app,'_aps_convocation_pdf_is_allowed',lambda p:True)
    def generate(s,t,*args):
        docx,pdf=tmp_path/(t['id']+'.docx'),tmp_path/(t['id']+'.pdf')
        docx.write_bytes(b'docx');pdf.write_bytes(b'PDF TEST')
        return str(docx),str(pdf)
    generators={kind:Mock(side_effect=generate) for kind in ('convention','convocation')}
    for kind,fn in generators.items():monkeypatch.setattr(app,'_generate_aps_'+kind+'_files',fn)
    monkeypatch.setattr(app,'_prepare_yousign_pdf_and_fields',lambda p,**kw:(p,[]))
    signatures=[]
    def signature(s,t,*args,**kwargs):
        state=t.setdefault('convention_signature',{})
        if not state.get('signature_request_id'):
            signatures.append(t['id']);state.update(signature_request_id='SIG-'+t['id'],status='ongoing',signature_link='https://example.test/sign')
        return state
    monkeypatch.setattr(app,'create_yousign_convention_signature',signature)
    def deliver(*args,**kwargs):
        kwargs['trainee'].setdefault('sent_email_history',[]).insert(0,{'to_email':args[0],'subject':args[1],'sent_at':'2026-10-24T18:00:00Z'})
        return {'ok':True,'status_code':201,'message_id':'msg-test'}
    mail=Mock(side_effect=deliver);monkeypatch.setattr(app,'brevo_send_email',mail)
    client=app.app.test_client()
    with client.session_transaction() as cookie:cookie.update(admin_logged_in=True,admin_role='admin')
    return client,data,training,trainee,generators,mail,signatures


def prepared(client,document='convention',action='generate',index=0):
    plan=client.get(BASE,query_string={'document':document,'action':action}).json
    row=plan['rows'][index]
    payload=dict(csrf=plan['csrf'],document=document,action=action,revision=row['revision'],request_id=uuid.uuid4().hex)
    return row,payload


@pytest.mark.parametrize('document,action',[('convention','generate'),('convocation','generate'),('convention','send'),('convocation','send')])
def test_four_actions_and_request_replay(case,document,action):
    client,_,_,trainee,generators,mail,signatures=case
    row,payload=prepared(client,document,action)
    assert row['eligible']
    response=client.post(row['execute_url'],json=payload)
    assert response.status_code==200 and response.json['ok'],response.json
    assert client.post(row['execute_url'],json=payload).json==response.json
    assert mail.call_count==(action=='send')
    assert len(signatures)==(document=='convention' and action=='send')
    assert generators[document].call_count==(not(document=='convention' and action=='send'))
    assert trainee['afc_document_operations'][document]['status']=='done'
    if action=='send':
        key=mail.call_args.kwargs['metadata']['idempotency_key']
        assert len(key)==36 and str(uuid.UUID(key))==key
        assert len(trainee['sent_email_history'])==1
        assert not prepared(client,document,action)[0]['eligible']
    else:
        assert trainee[document+'_aps_pdf_path']


@pytest.fixture
def brevo_transport(case,monkeypatch):
    """Run the real email adapter with Brevo's UUID contract, entirely offline."""
    calls,accepted=[],set()
    monkeypatch.setattr(app,'brevo_send_email',BREVO_TRANSPORT)
    monkeypatch.setattr(app,'_missing_brevo_config',lambda:[])
    monkeypatch.setattr(app,'_is_blocked_email_recipient',lambda email:False)
    monkeypatch.setattr(app,'BREVO_API_KEY','test-only')
    monkeypatch.setattr(app,'BREVO_SENDER_EMAIL','sender@example.test')
    monkeypatch.setattr(app,'BREVO_SENDER_NAME','Test Academy')
    monkeypatch.setattr(app,'_safe_brevo_log',Mock())
    def provider(url,*,headers,json,timeout):
        assert url=='https://api.brevo.com/v3/smtp/email'
        calls.append(copy.deepcopy(json))
        key=json.get('headers',{}).get('idempotencyKey','')
        try:
            if len(key)>36:
                raise ValueError('Idempotency key exceeds char limit')
            if str(uuid.UUID(key))!=key:
                raise ValueError('Invalid idempotency key')
        except ValueError as exc:
            code,body=400,{'code':'invalid_parameter','message':str(exc)}
        else:
            if key in accepted:
                code,body=400,{'code':'duplicate_parameter','message':'Idempotency key already used'}
            else:
                accepted.add(key)
                code,body=201,{'messageId':'offline-message-'+str(len(accepted))}
        return SimpleNamespace(status_code=code,text=str(body),json=lambda:body)
    monkeypatch.setattr(app.requests,'post',provider)
    return calls,accepted


@pytest.mark.parametrize('document',['convention','convocation'])
@pytest.mark.parametrize('request_format',['hex','hyphenated'])
def test_batch_of_twelve_reaches_real_email_adapter_with_valid_distinct_keys(case,brevo_transport,document,request_format):
    client,_,training,trainee,_,_,signatures=case
    training['trainees']=[dict(copy.deepcopy(trainee),id='T'+str(i),email=f'learner{i}@example.test') for i in range(1,13)]
    calls,accepted=brevo_transport
    plan=client.get(BASE,query_string={'document':document,'action':'send'}).json
    assert len(plan['rows'])==12 and all(row['eligible'] for row in plan['rows'])
    for row in plan['rows']:
        token=uuid.uuid4()
        payload=dict(csrf=plan['csrf'],document=document,action='send',revision=row['revision'],
                     request_id=token.hex if request_format=='hex' else str(token))
        result=client.post(row['execute_url'],json=payload)
        assert result.status_code==200 and result.json['ok'],result.json
        assert client.post(row['execute_url'],json=payload).json==result.json
    assert len(calls)==len(accepted)==12
    assert len(signatures)==(12 if document=='convention' else 0)
    assert all(len(message['headers']['idempotencyKey'])==36 for message in calls)
    assert all(bool(message.get('attachment'))==(document=='convocation') for message in calls)
    assert not any(row['eligible'] for row in client.get(BASE,query_string={'document':document,'action':'send'}).json['rows'])


def test_relaunch_after_old_key_rejection_reuses_existing_yousign_request(case,brevo_transport,monkeypatch):
    client,_,_,trainee,_,_,_=case
    trainee['convention_signature']={'signature_request_id':'existing-signature','signature_link':'https://example.test/sign-existing',
                                    'status':'ongoing','unsigned_pdf_path':'existing.pdf'}
    trainee['afc_document_operations']={'convention':{'id':str(uuid.uuid4()),'action':'send','phase':'delivery','status':'failed',
                                                     'result':{'ok':False,'message':'Idempotency key exceeds char limit'}}}
    monkeypatch.setattr(app,'create_yousign_convention_signature',CREATE_SIGNATURE)
    yousign=Mock(side_effect=AssertionError('An existing signature request must be reused'))
    monkeypatch.setattr(app,'_yousign_json',yousign)
    row,payload=prepared(client,'convention','send')
    assert row['eligible']
    assert client.post(row['execute_url'],json=payload).json['ok']
    assert not yousign.called
    assert trainee['convention_signature']['signature_request_id']=='existing-signature'
    assert trainee['convention_signature']['signature_email_sent_at']
    assert len(brevo_transport[0])==len(brevo_transport[1])==1
    assert 'https://example.test/sign-existing' in brevo_transport[0][0]['htmlContent']
    assert not prepared(client,'convention','send')[0]['eligible']


def test_prepare_is_read_only_and_uses_individual_dates(case):
    client,data,_,trainee,generators,mail,signatures=case
    before=copy.deepcopy(data)
    row,payload=prepared(client)
    assert data==before and not mail.called and not signatures
    assert not any(fn.called for fn in generators.values())
    trainee['training_date_start']='2026-11-20'
    result=client.post(row['execute_url'],json=payload).json
    assert not result['ok'] and 'changé' in result['message']
    assert not any(fn.called for fn in generators.values())


@pytest.mark.parametrize('change,document,action,reason',[
    ({'registration_cancelled':True},'convention','send','annulée'),
    ({'convention_status':'signed'},'convention','generate','signée'),
    ({'convocation_aps_sent_at':'2026-10-24'},'convocation','send','envoyée'),
    ({'email':''},'convocation','send','e-mail'),
    ({'phone':''},'convention','send','Téléphone'),
    ({'convention_signature':{'signature_request_id':'sig','status':'ongoing','signature_link':'https://example.test/sign'}},'convention','generate','signature'),
])
def test_exclusions(case,change,document,action,reason):
    client,_,_,trainee,_,mail,_=case
    trainee.update(change)
    row,_=prepared(client,document,action)
    assert not row['eligible'] and reason in row['reason']
    assert not mail.called


def test_afc_only_auth_viewer_csrf_and_invalid_action(case):
    client,_,training,_,_,mail,_=case
    row,payload=prepared(client)
    assert client.post(row['execute_url'],json={**payload,'csrf':'bad'}).status_code==403
    assert client.post(row['execute_url'],json={**payload,'action':'delete'}).status_code==400
    training.update(afc_enabled=False,name='APS')
    assert client.get(BASE,query_string={'document':'convention','action':'generate'}).status_code==404
    assert client.post(row['execute_url'],json=payload).status_code==404
    training.update(afc_enabled=True)
    with client.session_transaction() as cookie:cookie['admin_role']='viewer'
    assert client.post(row['execute_url'],json=payload).status_code==403
    assert client.get(BASE,query_string={'document':'convention','action':'generate'}).status_code==403
    with client.session_transaction() as cookie:cookie.clear()
    assert client.post(row['execute_url'],json=payload).status_code==401
    assert not mail.called


def test_failed_email_preserves_signature_and_retry_reuses_it(case):
    client,_,_,trainee,_,mail,signatures=case
    mail.side_effect=None;mail.return_value={'ok':False,'status_code':400,'error':'Adresse refusée'}
    row,payload=prepared(client,'convention','send')
    assert not client.post(row['execute_url'],json=payload).json['ok']
    assert trainee['convention_signature']['signature_request_id']=='SIG-T1'
    assert not trainee['convention_signature'].get('signature_email_sent_at')
    mail.return_value={'ok':True,'status_code':201}
    row,payload=prepared(client,'convention','send')
    assert client.post(row['execute_url'],json=payload).json['ok']
    assert signatures==['T1'] and mail.call_count==2


def test_uncertain_email_is_not_automatically_repeated(case):
    client,_,_,trainee,_,mail,_=case
    mail.side_effect=None;mail.return_value={'ok':False,'status_code':None,'error':'Timeout'}
    row,payload=prepared(client,'convocation','send')
    assert not client.post(row['execute_url'],json=payload).json['ok']
    assert trainee['afc_document_operations']['convocation']['status']=='uncertain'
    client.post(row['execute_url'],json=payload)
    assert mail.call_count==1
    assert not prepared(client,'convocation','send')[0]['eligible']


def test_cancelled_during_generation_prevents_email(case):
    client,_,_,trainee,generators,mail,_=case
    generate=generators['convocation'].side_effect
    def cancel(*args):
        paths=generate(*args);trainee['registration_cancelled']=True;return paths
    generators['convocation'].side_effect=cancel
    row,payload=prepared(client,'convocation','send')
    result=client.post(row['execute_url'],json=payload).json
    assert not result['ok'] and not mail.called


def test_second_request_during_generation_does_not_duplicate_delivery(case):
    client,_,_,trainee,generators,mail,_=case
    row,payload=prepared(client,'convocation','send')
    generate=generators['convocation'].side_effect
    def concurrent_request(*args):
        duplicate=client.post(row['execute_url'],json={**payload,'request_id':uuid.uuid4().hex})
        assert duplicate.status_code==202 and duplicate.json['pending']
        return generate(*args)
    generators['convocation'].side_effect=concurrent_request
    assert client.post(row['execute_url'],json=payload).json['ok']
    assert generators['convocation'].call_count==1 and mail.call_count==1
    assert trainee['afc_document_operations']['convocation']['status']=='done'


def test_webhook_and_unrelated_edits_survive_delivery(case):
    client,_,_,trainee,_,mail,_=case
    deliver=mail.side_effect
    def webhook(*args,**kwargs):
        trainee['notes']='Concurrent update'
        trainee['convention_signature'].update(status='done',signed_at='2026-10-24',signed_pdf_path='/keep/signed.pdf')
        return deliver(*args,**kwargs)
    mail.side_effect=webhook
    row,payload=prepared(client,'convention','send')
    assert client.post(row['execute_url'],json=payload).json['ok']
    assert trainee['notes']=='Concurrent update'
    assert trainee['convention_signature']['status']=='done'
    assert trainee['convention_signature']['signed_pdf_path']=='/keep/signed.pdf'
    assert trainee['convention_signature']['signature_email_sent_at']


def test_one_failure_does_not_prevent_next_learner(case):
    client,_,training,trainee,generators,mail,_=case
    training['trainees'].append(dict(trainee,id='T2',first_name='Alex',email='alex@example.test'))
    original=generators['convocation'].side_effect
    def generate(s,t,*args):
        if t['id']=='T1':raise RuntimeError('Test PDF failure')
        return original(s,t,*args)
    generators['convocation'].side_effect=generate
    for index,expected in [(0,False),(1,True)]:
        row,payload=prepared(client,'convocation','send',index)
        assert client.post(row['execute_url'],json=payload).json['ok'] is expected
    assert mail.call_count==1 and mail.call_args.args[0]=='alex@example.test'


def test_buttons_only_on_writable_afc_session(case):
    client,_,training,_,_,_,_=case
    html=client.get('/admin/sessions/S1/trainees').text
    assert 'id="afc-documents"' in html
    assert html.count('data-afc-document=')==4
    training.update(afc_enabled=False,name='APS')
    assert 'id="afc-documents"' not in client.get('/admin/sessions/S1/trainees').text
    training.update(afc_enabled=True)
    with client.session_transaction() as cookie:cookie['admin_role']='viewer'
    assert 'id="afc-documents"' not in client.get('/admin/sessions/S1/trainees').text


@pytest.mark.parametrize('document',['convention','convocation'])
def test_completed_generation_is_reused_until_content_changes_or_file_is_missing(case,document):
    client,_,_,trainee,generators,mail,_=case
    row,payload=prepared(client,document)
    assert client.post(row['execute_url'],json=payload).json['ok']
    again,_=prepared(client,document)
    assert not again['eligible'] and 'Déjà générée' in again['reason']
    assert client.post(row['execute_url'],json={**payload,'request_id':uuid.uuid4().hex}).json['skipped']
    assert generators[document].call_count==1 and not mail.called
    trainee['training_date_start']='2026-11-20'
    assert prepared(client,document)[0]['eligible']
    trainee['training_date_start']='2026-11-18'
    from pathlib import Path
    Path(trainee[document+'_aps_pdf_path']).unlink()
    assert prepared(client,document)[0]['eligible']


def test_legacy_generated_documents_survive_reload_and_are_not_repeated(case):
    client,_,_,trainee,generators,_,_=case
    row,payload=prepared(client)
    assert client.post(row['execute_url'],json=payload).json['ok']
    trainee['afc_document_operations']['convention'].pop('revision')
    assert not prepared(client)[0]['eligible']
    assert generators['convention'].call_count==1
    trainee['updated_at']='2099-01-01T00:00:00Z'
    assert prepared(client)[0]['eligible']


@pytest.mark.parametrize('document,action',[('convention','generate'),('convocation','generate'),('convocation','send')])
def test_restart_during_preparation_can_resume_safely(case,document,action):
    client,_,_,trainee,generators,mail,_=case
    row,payload=prepared(client,document,action)
    generate=generators[document].side_effect
    generators[document].side_effect=SystemExit('Simulated process shutdown')
    with pytest.raises(SystemExit):client.post(row['execute_url'],json=payload)
    assert trainee['afc_document_operations'][document]['status']=='running'
    assert trainee['afc_document_operations'][document]['phase']=='preparing'
    assert prepared(client,document,action)[0]['eligible']
    generators[document].side_effect=generate
    response=client.post(row['execute_url'],json=payload)
    assert response.json['ok'] and generators[document].call_count==2
    assert mail.call_count==(action=='send')


@pytest.mark.parametrize('document',['convention','convocation'])
def test_restart_during_delivery_never_resends(case,document):
    client,_,_,trainee,_,mail,_=case
    row,payload=prepared(client,document,'send')
    mail.side_effect=SystemExit('Provider accepted but process stopped before saving its response')
    with pytest.raises(SystemExit):client.post(row['execute_url'],json=payload)
    assert trainee['afc_document_operations'][document]['phase']=='delivery'
    result=client.post(row['execute_url'],json=payload).json
    assert not result['ok'] and 'vérifiez' in result['message']
    assert trainee['afc_document_operations'][document]['status']=='uncertain'
    assert mail.call_count==1


def test_restart_during_signature_creation_never_creates_a_second_request(case,monkeypatch):
    client,_,_,trainee,_,mail,_=case
    create=Mock(side_effect=SystemExit('Yousign response lost'))
    monkeypatch.setattr(app,'create_yousign_convention_signature',create)
    row,payload=prepared(client,'convention','send')
    with pytest.raises(SystemExit):client.post(row['execute_url'],json=payload)
    result=client.post(row['execute_url'],json=payload).json
    assert not result['ok'] and create.call_count==1 and not mail.called
    assert trainee['afc_document_operations']['convention']['status']=='uncertain'


def test_temporary_store_failure_returns_retryable_json(case,monkeypatch):
    client,data,_,_,generators,mail,_=case
    row,payload=prepared(client)
    mutate=Mock(side_effect=OSError('Temporarily unavailable'))
    monkeypatch.setattr(app,'_atomic_update_data',mutate)
    response=client.post(row['execute_url'],json=payload)
    assert response.status_code==503 and response.json['retryable']
    assert not generators['convention'].called and not mail.called
    monkeypatch.setattr(app,'_atomic_update_data',lambda fn:fn(data))
    assert client.post(row['execute_url'],json=payload).json['ok']


def test_csrf_expiration_returns_recoverable_code_without_mutating(case):
    client,data,_,_,generators,mail,_=case
    row,payload=prepared(client)
    before=copy.deepcopy(data)
    with client.session_transaction() as cookie:cookie.pop('afc_documents_csrf')
    result=client.post(row['execute_url'],json=payload)
    assert result.status_code==403 and result.json['code']=='csrf_expired'
    assert data==before and not generators['convention'].called and not mail.called
    fresh=client.get(BASE,query_string={'document':'convention','action':'generate'}).json
    assert client.post(row['execute_url'],json={**payload,'csrf':fresh['csrf']}).json['ok']
