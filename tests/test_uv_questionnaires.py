import copy
import datetime as dt
import hashlib
from html import unescape
from io import BytesIO
from unittest.mock import Mock

import pytest
from pypdf import PdfReader

import app
import uv_questionnaires as uv


@pytest.fixture
def case(monkeypatch):
    trainee = {'id':'T1','first_name':'Camille','last_name':'MARTIN','public_token':'token-test'}
    training = {'id':'S1','training_type':'APS','name':'APS test','date_start':'2026-10-26',
                'aps_in_person_start':'2026-11-09','date_end':'2026-12-18','trainees':[trainee]}
    data={'sessions':[training]}
    monkeypatch.setattr(app,'load_data',lambda **kwargs:data)
    monkeypatch.setattr(app,'_atomic_update_data',lambda mutate:mutate(data))
    monkeypatch.setattr(uv,'today',lambda:dt.date(2026,11,9))
    monkeypatch.setattr(uv,'clock',lambda:1000.0)
    client=app.app.test_client()
    with client.session_transaction() as cookie:
        cookie['public_auth_token-test']=True
        cookie['uv_questionnaire_csrf']='csrf-test'
    return client,training,trainee,data


PATH='/espace/token-test/questionnaires-uv/2'


def post(client,action='sync',**kw):
    return client.post(PATH,json=dict(csrf='csrf-test',action=action,**kw))


def complete(client,wrong=False):
    state=post(client,'start',in_class='yes').json
    for i,q in enumerate(uv.unit('aps',2)['questions']):
        answer=next(o['id'] for o in q['options'] if o['id']!=q['answer']) if wrong and i==0 else q['answer']
        assert state['question']['id']==q['id']
        state=post(client,'answer',question_id=q['id'],answer=answer).json
    return state


def admin(client):
    with client.session_transaction() as cookie:cookie.update(admin_logged_in=True,admin_role='admin')


def test_bank_preserved_but_sst_unavailable():
    for course,count in [('aps',14),('a3p',9)]:
        units=uv.bank()['courses'][course]['units']
        assert len(units)==count
        assert uv.unit(course,1) is None
        for row in units[1:]:
            assert len(row['questions'])==20
            assert len({q['id'] for q in row['questions']})==20
            assert len({q['prompt'] for q in row['questions']})==20
            for q in row['questions']:assert q['answer'] in {o['id'] for o in q['options']}


def test_revised_content_and_archived_bank_are_consistent():
    archived = uv.BANK_DIR / '20261024.json'
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == '637281afeb89bcd5dbf6dceda0794a64776bdc725f33b840bff6ef09fd80ec2f'
    assert uv.VERSION == uv.bank()['version'] == '20261026'
    revised = []
    examples = []
    active_count = 0
    for course, data in uv.bank()['courses'].items():
        for row in data['units']:
            if not uv.unit(course, row['number']):
                continue
            active_count += len(row['questions'])
            changed = [q for q in row['questions'] if q.get('revised_in') == uv.VERSION]
            assert len(changed) == (20 if (course, row['number']) == ('a3p', 6) else 8)
            revised.extend(changed)
            for q in changed:
                assert len(q['options']) in (2, 4)
                assert len({o['text'].strip().casefold() for o in q['options']}) == len(q['options'])
                assert len({o['id'] for o in q['options']}) == len(q['options'])
                assert q['explanation'].strip()
                if q.get('editorial_origin'):
                    examples.append((course, row['number'], q['id']))
    assert active_count == 420 and len(revised) == 180
    assert examples == [('a3p', 6, f'q{i:02}') for i in range(1, 8)]


def test_old_attempt_finishes_with_its_original_questions_and_correction(case):
    client, _, trainee, _ = case
    old = uv.unit('aps', 2, '20261024')
    trainee['uv_questionnaire_attempts'] = {'aps': {'2': dict(
        version='20261024', answers={}, index=0, deadline=1045,
        started_at='2026-10-26T09:00:00')}}
    state = post(client).json
    for q in old['questions']:
        assert state['question']['prompt'] == q['prompt']
        assert 'answer' not in state['question'] and 'explanation' not in state['question']
        state = post(client, 'answer', question_id=q['id'], answer=q['answer']).json
    assert state == {'completed': True, 'score': 20}
    assert trainee['uv_questionnaires']['aps']['2']['version'] == '20261024'
    page = client.get(PATH).text
    assert old['questions'][0]['explanation'] in page
    assert uv.unit('aps', 2)['questions'][0]['explanation'] not in page
    admin(client)
    response = client.get('/admin/sessions/S1/stagiaires/T1/questionnaires-uv/2.pdf?mode=answers')
    text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(response.data)).pages)
    assert old['questions'][0]['prompt'] in text
    assert 'Score : 20/20' in text


def test_a3p_new_questions_true_false_and_four_choices_are_graded(case):
    client, training, trainee, _ = case
    training['training_type'] = 'A3P'
    path = '/espace/token-test/questionnaires-uv/6'
    def submit(action='sync', **kwargs):
        return client.post(path, json=dict(csrf='csrf-test', action=action, **kwargs))
    questions = uv.unit('a3p', 6)['questions']
    assert len(questions[5]['options']) == 2
    assert all(len(q['options']) == 4 for i,q in enumerate(questions) if i != 5)
    state = submit('start', in_class='yes').json
    # Reject an option that exists on other questions but not on this one,
    # without advancing, and count a deliberate wrong true/false response.
    for i, q in enumerate(questions):
        assert state['question']['options'] == q['options']
        assert set(state['question']) == {'id', 'prompt', 'options'}
        if i == 5:
            assert submit('answer', question_id=q['id'], answer='4').status_code == 400
            assert submit().json['index'] == 6
            answer = next(o['id'] for o in q['options'] if o['id'] != q['answer'])
        else:
            answer = q['answer']
        state = submit('answer', question_id=q['id'], answer=answer).json
    assert state == {'completed': True, 'score': 19}
    assert trainee['uv_questionnaires']['a3p']['6']['version'] == '20261026'
    assert questions[5]['explanation'] in unescape(client.get(path).text)


@pytest.mark.parametrize('kind,expected',[('APS','aps'),('A3P','a3p'),('APS MAC',''),('MAC A3P',''),('A3P VAE',''),('SST',''),('SSIAP','')])
def test_course_scope(kind,expected):
    assert uv.course_for({'training_type':kind})==expected


@pytest.mark.parametrize('start,expected',[('2026-10-25',False),('2026-10-26',True),('2026-11-01',True),('',False),('invalid',False)])
def test_cohort_boundary_applies_to_every_route(case,start,expected):
    client,training,trainee,_=case
    training['date_start']=start
    assert bool(uv.view(app,training,trainee))==expected
    assert client.get(PATH).status_code==(200 if expected else 404)
    assert post(client).status_code==(200 if expected else 404)
    admin(client)
    for suffix in ('','.pdf'):
        response=client.get('/admin/sessions/S1/stagiaires/T1/questionnaires-uv/2'+suffix)
        assert response.status_code==(200 if expected else 404)


def test_gate_dates_and_afc_original_session_not_later_individual_start(case):
    _,training,trainee,_=case
    assert uv.available(app,training,trainee)
    training['aps_in_person_start']='2026-11-10'
    assert not uv.available(app,training,trainee)
    training.pop('aps_in_person_start')
    assert not uv.available(app,training,trainee)
    training['training_type']='A3P'
    assert uv.available(app,training,trainee)
    training.update(training_type='APS',afc_enabled=True)
    trainee['training_date_start']='2026-11-10'
    assert not uv.available(app,training,trainee)
    trainee['training_date_start']='2026-11-09'
    assert uv.available(app,training,trainee)
    training['date_start']='2026-10-25'
    assert not uv.view(app,training,trainee)
    training['date_start']='2026-10-26';trainee['registration_cancelled']=True
    assert not uv.available(app,training,trainee)


def test_single_question_no_answers_leaked_and_final_score_is_immutable(case):
    client,_,trainee,_=case
    page=client.get(PATH)
    assert page.status_code==200
    for q in uv.unit('aps',2)['questions']:
        assert q['prompt'].encode() not in page.data
        assert q['explanation'].encode() not in page.data
    assert post(client).json['started'] is False
    first=post(client,'start',in_class='yes').json
    assert first['index']==1 and first['remaining_ms']==45000
    assert 'answer' not in first['question'] and 'explanation' not in first['question']
    result=complete(client,wrong=True)
    assert result=={'completed':True,'score':19}
    saved=copy.deepcopy(trainee['uv_questionnaires']['aps']['2'])
    assert saved['in_class'] and saved['seconds_per_question']==45
    assert b'Bonne r' in client.get(PATH).data
    post(client,'start',in_class='yes')
    post(client,'answer',question_id='q01',answer='A')
    assert trainee['uv_questionnaires']['aps']['2']==saved


def test_deadline_survives_reload_and_late_answer_is_not_counted(case,monkeypatch):
    client,_,trainee,_=case
    first=post(client,'start',in_class='yes').json
    monkeypatch.setattr(uv,'clock',lambda:1030)
    assert post(client).json['remaining_ms']==15000
    assert post(client,'start',in_class='yes').json['remaining_ms']==15000
    monkeypatch.setattr(uv,'clock',lambda:1045)
    next_state=post(client,'answer',question_id=first['question']['id'],answer=uv.unit('aps',2)['questions'][0]['answer']).json
    assert next_state['index']==2 and next_state['remaining_ms']==45000
    attempt=trainee['uv_questionnaire_attempts']['aps']['2']
    assert attempt['answers']['q01']==''
    assert post(client,'answer',question_id='q01',answer='A').json['index']==2


def test_all_timeouts_finish_and_score_zero(case,monkeypatch):
    client,_,trainee,_=case
    post(client,'start',in_class='yes')
    for i in range(20):
        monkeypatch.setattr(uv,'clock',lambda i=i:1000+(i+1)*45)
        result=post(client).json
    assert result=={'completed':True,'score':0}
    assert len(trainee['uv_questionnaires']['aps']['2']['answers'])==20


@pytest.mark.parametrize('payload',[{'action':'start'}, {'action':'unknown'}, {'action':'answer','question_id':'q01','answer':'A'}])
def test_invalid_start_does_not_persist(case,payload):
    client,_,trainee,_=case
    assert client.post(PATH,json={'csrf':'csrf-test',**payload}).status_code==400
    assert not trainee.get('uv_questionnaire_attempts')


def test_auth_csrf_dates_and_sst_enforced_on_post(case):
    client,training,trainee,_=case
    assert client.post(PATH,json={'csrf':'wrong','action':'start'}).status_code==403
    assert client.get(PATH.replace('/2','/1')).status_code==404
    training['aps_in_person_start']='2026-11-10'
    assert post(client).status_code==client.get(PATH).status_code==403
    assert app.app.test_client().get(PATH).status_code==302
    admin(client)
    assert client.get('/admin/sessions/S1/stagiaires/T1/questionnaires-uv/1.pdf').status_code==404


def test_atomic_save_rechecks_cancelled_registration(case,monkeypatch):
    client,_,trainee,data=case
    def update(mutate):
        trainee['registration_cancelled']=True
        return mutate(data)
    monkeypatch.setattr(app,'_atomic_update_data',update)
    assert post(client,'start',in_class='yes').status_code==409
    assert not trainee.get('uv_questionnaire_attempts')


def test_admin_pdf_blank_and_correction(case):
    client,_,_,_=case
    path='/admin/sessions/S1/stagiaires/T1/questionnaires-uv/2'
    assert client.get(path).status_code==302
    complete(client);admin(client)
    assert client.get(path).status_code==200
    assert client.get(path.replace('T1','other')).status_code==404
    blank=client.get(path+'.pdf')
    assert all(page.images for page in PdfReader(BytesIO(blank.data)).pages)
    text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(blank.data)).pages)
    assert 'Bonne réponse' not in text and 'Camille MARTIN' in text
    assert "Questionnaire de fin d'UV" in text and 'Evaluation formative' in text
    assert all(f'{i:02}.' in text for i in range(1,21))
    completed=client.get(path+'.pdf?mode=answers')
    text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(completed.data)).pages)
    assert 'Score : 20/20' in text and 'Bonne réponse' in text
    assert 'no-store' in completed.headers['Cache-Control']


def test_portal_admin_closed_accordions_and_sst_hidden(case,monkeypatch):
    from bs4 import BeautifulSoup
    client,training,trainee,_=case
    monkeypatch.setattr(app,'save_data',lambda data:None)
    trainee.update(documents=[],public_has_logged_in=True)
    training.update(exam_date='2027-01-04',ssiap_exam_date='2027-01-05',afc_enabled=True)
    admin(client)
    for path in ('/espace/token-test','/admin/sessions/S1/stagiaires/T1'):
        page=client.get(path);assert page.status_code==200
        details=BeautifulSoup(page.data,'html.parser').select_one('details#questionnaires-uv')
        assert details and 'open' not in details.attrs
        assert 'Evaluation formative' in details.text
        assert len(details.select('.uvhub-unit'))==13
        assert not details.select('a[href$="/1"],a[href$="/1.pdf"]')
    training['date_start']='2026-10-25'
    for path in ('/espace/token-test','/admin/sessions/S1/stagiaires/T1'):
        assert 'id="questionnaires-uv"' not in client.get(path).text


def test_hidden_until_answering_available_but_admin_can_try_demo(case,monkeypatch):
    client,training,trainee,_=case
    monkeypatch.setattr(app,'save_data',lambda data:None)
    training['aps_in_person_start']='2026-11-10'
    trainee.update(documents=[],public_has_logged_in=True)
    assert 'id="questionnaires-uv"' not in client.get('/espace/token-test').text
    demo='/admin/sessions/S1/stagiaires/T1/questionnaires-uv/2/tester'
    assert client.get(demo).status_code==302
    admin(client)
    page=client.get('/admin/sessions/S1/stagiaires/T1')
    assert 'uvhub--admin' in page.text and 'Tester le questionnaire' in page.text
    before=copy.deepcopy(trainee)
    mutate=Mock()
    monkeypatch.setattr(app,'_atomic_update_data',mutate)
    response=client.get(demo)
    assert response.status_code==200 and 'data-demo="true"' in response.text
    assert 'uq-demo-data' in response.text and 'Aucune réponse ni note' in response.text
    assert trainee==before and not mutate.called
    assert client.post(demo).status_code==405
    assert client.get(demo.replace('/2/','/1/')).status_code==404
    training['aps_in_person_start']='2026-11-09'
    assert 'id="questionnaires-uv"' in client.get('/espace/token-test').text
    trainee['registration_cancelled']=True
    assert 'id="questionnaires-uv"' not in client.get('/espace/token-test').text
