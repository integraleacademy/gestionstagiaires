import copy
from unittest.mock import Mock
import pytest
import app
import afc_schedule

@pytest.fixture
def case(monkeypatch):
    training = {'id':'AFC1', 'name':'AFC APS + SSIAP', 'training_type':'APS',
                'date_start':'2026-11-16','date_end':'2027-02-15',
                'exam_date':'2027-01-21','ssiap_exam_date':'2027-02-15', 'trainees':[]}
    candidate = {'id':'AFC-C1','nom':'MARTIN','prenom':'Émilie','email':'emilie@example.test',
                 'telephone':'0601020304','identifiant_ft':'1234567', 'cnaps_status':'INCONNU'}
    data = {'sessions':[training], 'afc':{'candidates':[candidate,dict(candidate,id='ARCH',archived=True)]}}
    monkeypatch.setattr(app,'load_data',lambda *a,**kw:copy.deepcopy(data))
    monkeypatch.setattr(app,'_atomic_update_data',lambda fn:fn(data))
    monkeypatch.setattr(app,'save_data',Mock())
    mail=Mock();monkeypatch.setattr(app,'brevo_send_email',mail)
    client=app.app.test_client()
    with client.session_transaction() as s:
        s['admin_logged_in']=True;s['admin_role']='admin'
    return client,data,training,mail

def test_independent_juries_dates_and_candidates(case):
    client,data,training,mail=case
    training['trainees']=[{'id':'T1','first_name':'Camille','last_name':'TEST'}]
    for family,date,level in [('security','2027-01-21','APS'),('ssiap','2027-02-15','SSIAP 1')]:
        url=f'/api/admin/sessions/AFC1/{family}-exam'
        view=client.get(url).json
        assert view['config']['date']==date
        assert view['config']['level']==level
        assert [t['id'] for t in view['candidates']]==['T1']
        config={**view['config'],'time':'09:00','jury':[{'id':family,'first_name':'Alex','last_name':'JURY','email':'jury@example.test','role':'president','phone':'','company':''}]}
        response=client.post(url,json={'csrf':view['csrf'],'revision':view['revision'],'action':'config','config':config})
        assert response.status_code==200,response.json
        preview=client.get(url+f'/jury/{family}/invitation/preview')
        assert preview.status_code==200,preview.json
    assert training['security_exam']['config']['jury'][0]['id']=='security'
    assert training['ssiap_exam']['config']['jury'][0]['id']=='ssiap'
    assert '_exam_family' not in training
    mail.assert_not_called()

def test_import_search_creation_and_duplicate(case):
    client,data,training,mail=case
    url='/api/admin/sessions/AFC1/afc-candidates'
    response=client.get(url+'?q=emilie')
    assert response.status_code==200
    assert [c['id'] for c in response.json['candidates']]==['AFC-C1']
    create='/api/sessions/AFC1/trainees/create'
    payload={'afc_candidate_id':'AFC-C1','send_access':False,'training_date_start':'2026-11-23','training_date_end':'2028-01-01'}
    response=client.post(create,json=payload)
    assert response.status_code==200,response.json
    saved=training['trainees'][0]
    assert saved['last_name']=='MARTIN' and saved['email']=='emilie@example.test'
    assert saved['afc_candidate_id']=='AFC-C1'
    assert saved['training_date_end']==''
    assert afc_schedule.effective_session(training,saved)['date_end']=='2027-02-15'
    assert client.get(url).json['candidates'][0]['already_enrolled']
    assert client.post(create,json=payload).status_code in (400,409)
    assert len(training['trainees'])==1
    mail.assert_not_called()
    training['name']='APS';training['afc_enabled']=False
    assert client.get(url).status_code==404
    assert client.post(create,json=payload).status_code in (400,409)

def test_rendered_afc_modals_have_unique_ids(case):
    import re
    client,data,training,mail=case
    response=client.get('/admin/sessions/AFC1/trainees?openCreateTrainee=1')
    assert response.status_code==200
    html=response.get_data(as_text=True)
    ids=re.findall(r'\bid="([^"]+)"',html)
    # Inline JS also contains dynamic IDs; inspect only actual HTML tags.
    from html.parser import HTMLParser
    class IDs(HTMLParser):
        def __init__(self): super().__init__();self.ids=[]
        def handle_starttag(self,tag,attrs):
            if 'id' in dict(attrs): self.ids.append(dict(attrs)['id'])
    parser=IDs();parser.feed(html);ids=parser.ids
    assert len(ids)==len(set(ids)),[i for i in ids if ids.count(i)>1]
    for expected in ('apsJuryMailDialog','ssiapExamMailDialog','btnA3pExamDossier','btnSsiapExam'):
        assert expected in ids

def test_two_reminders_for_same_juror_on_same_day(case):
    import datetime as dt
    from zoneinfo import ZoneInfo
    import ssiap_exam as exam
    from ssiap_exam_reminders import run
    client,data,training,mail=case
    training['trainees']=[{'id':'T1','first_name':'Camille','last_name':'TEST'}]
    training['ssiap_exam_date']=training['exam_date']='2027-01-21'
    member={'id':'J1','first_name':'Alex','last_name':'JURY','email':'jury@example.test','role':'president','phone':'','company':''}
    for family in ('security','ssiap'):
        url=f'/api/admin/sessions/AFC1/{family}-exam'
        view=client.get(url).json
        response=client.post(url,json={'csrf':view['csrf'],'revision':view['revision'],'action':'config',
                        'config':{**view['config'],'time':'09:00','jury':[member]}})
        assert response.status_code==200,response.json
    mail.return_value={'ok':True,'message_id':'test-only'}
    now=dt.datetime(2027,1,14,9,tzinfo=ZoneInfo('Europe/Paris'))
    assert run(app,now=now,dry_run=True)['due']==2
    assert run(app,now=now)['emails_accepted']==2
    assert run(app,now=now)['processed']==0
    assert len(training['security_exam']['mail_history'])==1
    assert len(training['ssiap_exam']['mail_history'])==1
