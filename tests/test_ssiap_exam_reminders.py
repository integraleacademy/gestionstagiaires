import copy
import datetime as dt
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

import ssiap_exam as exam
from ssiap_exam_reminders import run, schedule


def clock(day='2026-10-21', hour=9, minute=0):
    return dt.datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=ZoneInfo('Europe/Paris'))


@pytest.fixture
def setup():
    member = {'id':'J1', 'first_name':'Alex', 'last_name':'JURY', 'role':'member',
              'email':'jury@example.test', 'company':'Structure exemple', 'phone':''}
    config = {**exam.DEFAULTS, 'date':'2026-10-28', 'time':'08:30', 'arrival_time':'08:00', 'end_time':'16:30', 'jury':[member]}
    training = {'id':'S1', 'training_type':'SSIAP 1', 'ssiap_exam':{'config':config},
                'trainees':[{'id':'T1'}, {'id':'T2', 'registration_cancelled':True}]}
    data = {'sessions':[training]}
    lock = threading.RLock()
    def atomic(fn):
        with lock:
            return fn(data)
    send = Mock(return_value={'ok':True,'message_id':'test-delivery'})
    services = SimpleNamespace(load_data=lambda **kw:copy.deepcopy(data), _atomic_update_data=atomic,
        find_session=lambda current, key:next((s for s in current['sessions'] if s['id']==key), None),
        _session_trainees_list=lambda s:s.get('trainees',[]),
        _trainee_registration_is_cancelled=lambda t:t.get('registration_cancelled',False),
        INTEGRALE_PARTNER_ID='internal', APP_BASE_URL='https://centre.example.test',
        brevo_send_email=send, app=SimpleNamespace(logger=Mock(), secret_key='test-only-jury-planning-secret'))
    return services, data, training, config, member, send


def test_exact_j7_shared_template_durable_history_and_no_duplicates(setup):
    services, data, training, config, member, send = setup
    assert run(services, now=clock('2026-10-20'))['processed'] == 0
    assert run(services, now=clock())['emails_accepted'] == 1
    assert run(services, now=clock(hour=10))['processed'] == 0
    assert run(services, now=clock('2026-10-22'))['processed'] == 0
    from jury_planning import mail_context
    expected = exam.build_mail(training,config,member,'reminder',1,services.APP_BASE_URL+'/static/logo-integrale.png',
        today=clock().date(), planning=mail_context(services, data, training, member, today=clock().date()))
    assert send.call_args.args == (expected['to'],expected['subject'],expected['html'])
    assert send.call_args.kwargs['text_content'] == expected['text']
    assert send.call_args.kwargs['reply_to'] == expected['reply_to']
    entry = training['ssiap_exam']['mail_history'][0]
    assert entry['source']=='automatic_j7' and entry['status']=='sent' and entry['exam_date']=='2026-10-28'
    assert entry['scheduled_for']=='2026-10-21' and entry['message_id']=='test-delivery'
    assert schedule(services, training, now=clock())['members']['J1']['status']=='sent'
    assert exam.mail_status(training,member)['reminder']['sent_count']==1
    assert send.call_count==1


@pytest.mark.parametrize('exam_date,utc_before,utc_due', [
    ('2026-10-28','2026-10-21T06:59:00+00:00','2026-10-21T07:00:00+00:00'),
    ('2027-01-07','2026-12-31T07:59:00+00:00','2026-12-31T08:00:00+00:00'),
    ('2028-03-07','2028-02-29T07:59:00+00:00','2028-02-29T08:00:00+00:00'),
])
def test_paris_calendar_midnight_year_leap_day_and_dst(setup,exam_date,utc_before,utc_due):
    services,_,training,config,_,send=setup
    config['date']=exam_date
    assert run(services,now=dt.datetime.fromisoformat(utc_before))['processed']==0
    assert run(services,now=dt.datetime.fromisoformat(utc_due))['processed']==1
    assert send.call_count==1


@pytest.mark.parametrize('change',['archived','partner','no_candidates','excluded','no_email','no_time','no_date','afc_aps_date','unsaved'])
def test_unready_or_out_of_scope_exams_never_send(setup,change):
    services,_,training,config,member,send=setup
    if change=='archived':training['archived']=True
    elif change=='partner':training['partner_id']='other'
    elif change=='no_candidates':training['trainees']=[]
    elif change=='excluded':training['ssiap_exam']['candidates']={'T1':{'included':False}}
    elif change=='no_email':member['email']=''
    elif change=='no_time':config['time']=''
    elif change=='no_date':config['date']=''
    elif change=='afc_aps_date':
        training.update(training_type='AFC',exam_date=config['date']);config.pop('date')
    elif change=='unsaved':training['ssiap_exam'].pop('config')
    assert run(services,now=clock())['processed']==0
    send.assert_not_called()


def test_dry_run_never_reserves_or_sends_and_late_activation_never_catches_up(setup):
    services,data,training,_,_,send=setup
    before=copy.deepcopy(data)
    assert run(services,now=clock(),dry_run=True)['due']==1
    assert data==before
    assert run(services,now=clock('2026-10-22'))['processed']==0
    assert schedule(services,training,now=clock('2026-10-22'))['members']['J1']['status']=='missed'
    send.assert_not_called()


def test_two_workers_and_duplicate_email_deliver_once(setup):
    services,_,training,config,member,send=setup
    config['jury'].append({**member,'id':'J2','email':member['email'].upper()})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:run(services,now=clock()),range(2)))
    assert sum(r['emails_accepted'] for r in results)==1
    assert send.call_count==1
    assert len(training['ssiap_exam']['mail_history'])==1


@pytest.mark.parametrize('status',['sent','sending','unknown','failed'])
def test_manual_message_on_due_day_prevents_automatic_duplicate(setup,status):
    services,_,training,config,member,send=setup
    training['ssiap_exam']['mail_history']=[{'kind':'reminder','to':member['email'],'jury_id':member['id'],
        'exam_date':config['date'],'at':clock(hour=8).isoformat(),'source':'manual','status':status}]
    assert run(services,now=clock())['processed']==0
    send.assert_not_called()


def test_earlier_manual_reminder_does_not_cancel_j7_and_reschedule_gets_new_delivery(setup):
    services,_,training,config,member,send=setup
    training['ssiap_exam']['mail_history']=[{'kind':'reminder','to':member['email'],'jury_id':member['id'],
        'subject':'Rappel - Examen SSIAP 1 du 28/10/2026 à 08:30',
        'at':clock('2026-10-18').isoformat(),'status':'sent'}]
    assert run(services,now=clock())['processed']==1
    key=send.call_args.kwargs['metadata']['idempotency_key']
    config['date']='2026-11-05'
    assert run(services,now=clock('2026-10-29'))['processed']==1
    assert key!=send.call_args.kwargs['metadata']['idempotency_key']


def test_explicit_refusal_retries_after_thirty_minutes_with_same_key(setup):
    services,_,training,_,_,send=setup
    send.side_effect=[{'ok':False,'status_code':429},{'ok':True,'message_id':'retry-delivery'}]
    assert run(services,now=clock())['failed']==1
    assert run(services,now=clock(minute=29))['processed']==0
    assert run(services,now=clock(minute=30))['emails_accepted']==1
    assert len(training['ssiap_exam']['mail_history'])==2
    assert send.call_args_list[0].kwargs['metadata']['idempotency_key']==send.call_args_list[1].kwargs['metadata']['idempotency_key']


def test_retry_is_bounded_and_unknown_delivery_is_never_repeated(setup):
    services,_,training,_,_,send=setup
    send.return_value={'ok':False,'status_code':429,'error':'Too many requests'}
    for hour in (9,10,11): assert run(services,now=clock(hour=hour))['processed']==1
    assert run(services,now=clock(hour=12))['processed']==0
    training['ssiap_exam']['mail_history']=[]
    send.side_effect=TimeoutError('provider response lost')
    assert run(services,now=clock(hour=13))['failed']==1
    assert training['ssiap_exam']['mail_history'][0]['status']=='unknown'
    assert run(services,now=clock(hour=14))['processed']==0


def test_changed_address_between_read_and_reservation_is_not_sent(setup):
    services,_,_,_,member,send=setup
    atomic=services._atomic_update_data
    def concurrent_change(fn):
        member['email']='new@example.test'
        return atomic(fn)
    services._atomic_update_data=concurrent_change
    assert run(services,now=clock())['processed']==0
    send.assert_not_called()


def test_brevo_uuid_is_valid_stable_and_scoped_to_exam_and_recipient(setup):
    import uuid
    services,_,training,config,member,send=setup
    run(services,now=clock())
    key=send.call_args.kwargs['metadata']['idempotency_key']
    assert str(uuid.UUID(key)) == key
    training['ssiap_exam']['mail_history']=[]
    member['email']=member['email'].upper()
    run(services,now=clock())
    assert send.call_args.kwargs['metadata']['idempotency_key']==key
    training['ssiap_exam']['mail_history']=[]
    member['email']='another@example.test'
    run(services,now=clock())
    assert send.call_args.kwargs['metadata']['idempotency_key']!=key


@pytest.mark.parametrize('result', [
    {'ok':False,'status_code':400,'error':'Invalid idempotency key'},
    {'ok':False,'status_code':401,'error':'Key not found'},
    {'ok':False,'status_code':403,'error':'IP not authorized'},
    {'ok':False,'not_sent':True,'error':'Configuration Brevo incomplète'},
])
def test_permanent_refusal_is_recorded_and_not_retried(setup,result):
    services,_,training,_,_,send=setup
    send.return_value=result
    assert run(services,now=clock())['failed']==1
    entry=training['ssiap_exam']['mail_history'][0]
    assert entry['error']==result['error']
    assert entry['status_code']==result.get('status_code')
    assert entry['not_sent'] is True and entry['retryable'] is False
    assert run(services,now=clock(hour=10))['processed']==0
    assert send.call_count==1
    services.app.logger.warning.assert_called_once()


@pytest.mark.parametrize('code',[408,500,502,None])
def test_uncertain_provider_response_preserves_reason_without_retry(setup,code):
    services,_,training,_,_,send=setup
    send.return_value={'ok':False,'status_code':code,'error':'Provider response unavailable'}
    run(services,now=clock())
    entry=training['ssiap_exam']['mail_history'][0]
    assert entry['status']=='unknown' and entry['not_sent'] is False
    assert entry['error']=='Provider response unavailable'
    assert run(services,now=clock(hour=10))['processed']==0
    assert send.call_count==1


def test_reminder_reaches_brevo_transport_with_uuid_and_saves_refusal(setup):
    """Exercise the real transport against the documented UUID contract, offline."""
    import ast
    import re
    import uuid
    from pathlib import Path
    from typing import Any, Dict, List, Optional
    services,_,training,_,_,_=setup
    module=ast.parse((Path(__file__).parents[1]/'app.py').read_text())
    function=next(node for node in module.body if isinstance(node,ast.FunctionDef) and node.name=='brevo_send_email')
    payloads=[]
    def provider(url,*,headers,json,timeout):
        assert url=='https://api.brevo.com/v3/smtp/email'
        payloads.append(json)
        try:
            uuid.UUID(json['headers']['idempotencyKey'])
            code,body=201,{'messageId':'contract-test-accepted'}
        except ValueError:
            code,body=400,{'message':'Invalid idempotency key'}
        return SimpleNamespace(status_code=code,text=str(body),json=lambda:body)
    namespace=dict(Optional=Optional,List=List,Dict=Dict,Any=Any,re=re,
        requests=SimpleNamespace(post=provider),_missing_brevo_config=lambda:[],
        _is_blocked_email_recipient=lambda email:False,BREVO_API_KEY='test-only',
        BREVO_SENDER_EMAIL='sender@example.test',BREVO_SENDER_NAME='Test',
        _safe_brevo_log=Mock(),_now_iso=lambda:clock().isoformat(),
        has_request_context=lambda:False,_brevo_no_credit_detected=lambda text:False)
    exec(compile(ast.Module(body=[function],type_ignores=[]),'app.py','exec'),namespace)
    transport=namespace['brevo_send_email']
    old_key='ssiap-j7-'+exam.digest(['S1','2026-10-28','jury@example.test'])
    assert transport('jury@example.test','Test','<p>Test</p>',metadata={'idempotency_key':old_key})['status_code']==400
    services.brevo_send_email=transport
    assert run(services,now=clock())['emails_accepted']==1
    entry=training['ssiap_exam']['mail_history'][0]
    assert entry['message_id']=='contract-test-accepted' and entry['error']==''
    assert payloads[-1]['replyTo']['email']==exam.DEFAULTS['contact_email']
    assert len(payloads)==2


@pytest.mark.parametrize('result,expected',[
    ({'ok':False,'status_code':400,'error':'Invalid request'},'failed'),
    ({'ok':False,'error':'Provider timeout'},'unknown'),
    ({'ok':True,'message_id':'accepted'},'sent'),
])
def test_manual_jury_route_keeps_exact_delivery_result_and_duplicate_lock(setup,result,expected):
    from flask import Flask
    services,_,training,config,_,send=setup
    config['date']=(dt.datetime.now(dt.timezone.utc).date()+dt.timedelta(days=7)).isoformat()
    app=Flask(__name__)
    app.secret_key='test-only'
    services.app=app
    services.admin_login_required=lambda fn:fn
    services.admin_write_required=lambda fn:fn
    services._now_iso=lambda:clock().isoformat()
    exam.register(app,services)
    client=app.test_client()
    with client.session_transaction() as session:
        session['ssiap_exam_csrf']='test-csrf'
    base='/api/admin/sessions/S1/ssiap-exam'
    preview=client.get(base+'/jury/J1/reminder/preview')
    assert preview.status_code==200
    payload={'csrf':'test-csrf','preview_token':preview.json['preview_token']}
    send.return_value=result
    response=client.post(base+'/mail/send',json=payload)
    assert response.status_code==(200 if expected=='sent' else 502)
    entry=training['ssiap_exam']['mail_history'][0]
    assert entry['status']==expected and entry['error']==result.get('error','')
    assert response.json['error']==entry['error']
    assert client.post(base+'/mail/send',json=payload).status_code==409
    assert send.call_count==1


def test_provider_error_redacts_api_key_and_control_characters():
    from ssiap_exam_mail import delivery_outcome
    outcome=delivery_outcome({'ok':False,'status_code':401,'error':'Rejected xkeysib-secret_123\r\nvalue'})
    assert 'secret_123' not in outcome['error'] and '\n' not in outcome['error']
    assert outcome['retryable'] is False

