import copy
import datetime as dt
import hashlib
import json
from html import unescape
from io import BytesIO
from unittest.mock import Mock

import pytest
from pypdf import PdfReader

import app
import uv_questionnaires as uv


@pytest.fixture(autouse=True)
def isolated_uv_database(tmp_path, monkeypatch):
    monkeypatch.setitem(app.app.config, 'UV_QUESTIONNAIRE_DB_PATH',
                        str(tmp_path / 'uv-questionnaires.sqlite3'))


def persisted(training, trainee):
    return uv.stored_trainee(app, training, trainee)


@pytest.fixture
def case(monkeypatch):
    trainee = {'id':'T1','first_name':'Camille','last_name':'MARTIN','public_token':'token-test'}
    training = {'id':'S1','training_type':'APS','name':'APS test','date_start':'2026-10-26',
                'aps_in_person_start':'2026-11-09','date_end':'2026-12-18','trainees':[trainee]}
    data={'sessions':[training]}
    monkeypatch.setattr(app,'load_data',lambda **kwargs:data)
    monkeypatch.setattr(app, '_atomic_update_data', lambda mutate: mutate(data))
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
    client, training, trainee, _ = case
    old = uv.unit('aps', 2, '20261024')
    trainee['uv_questionnaire_attempts'] = {'aps': {'2': dict(
        version='20261024', answers={}, index=0, deadline=1045,
        started_at='2026-10-26T09:00:00')}}
    legacy_before = copy.deepcopy(trainee)
    state = post(client).json
    for q in old['questions']:
        assert state['question']['prompt'] == q['prompt']
        assert 'answer' not in state['question'] and 'explanation' not in state['question']
        state = post(client, 'answer', question_id=q['id'], answer=q['answer']).json
    assert state == {'completed': True, 'score': 20}
    assert persisted(training, trainee)['uv_questionnaires']['aps']['2']['version'] == '20261024'
    assert trainee == legacy_before  # Migration never rewrites the administrative snapshot.
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
    assert persisted(training, trainee)['uv_questionnaires']['a3p']['6']['version'] == '20261026'
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
    client,training,trainee,_=case
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
    saved=persisted(training, trainee)['uv_questionnaires']['aps']['2']
    assert saved['in_class'] and saved['seconds_per_question']==45
    assert b'Bonne r' in client.get(PATH).data
    post(client,'start',in_class='yes')
    post(client,'answer',question_id='q01',answer='A')
    assert persisted(training, trainee)['uv_questionnaires']['aps']['2']==saved


def test_completed_questionnaire_never_uses_the_general_json_writer(case, monkeypatch):
    client, training, trainee, _ = case
    legacy = copy.deepcopy(trainee)
    monkeypatch.setattr(app, '_atomic_update_data', Mock(side_effect=AssertionError(
        'UV answers must never acquire the general JSON writer.')))
    assert complete(client) == {'completed': True, 'score': 20}
    assert trainee == legacy
    saved = persisted(training, trainee)['uv_questionnaires']['aps']['2']
    assert len(saved['answers']) == 20
    assert all(saved['answers'].values())
    assert post(client).json == {'completed': True, 'score': 20}


def test_deadline_survives_reload_and_late_answer_is_not_counted(case,monkeypatch):
    client,training,trainee,_=case
    first=post(client,'start',in_class='yes').json
    monkeypatch.setattr(uv,'clock',lambda:1030)
    assert post(client).json['remaining_ms']==15000
    assert post(client,'start',in_class='yes').json['remaining_ms']==15000
    monkeypatch.setattr(uv,'clock',lambda:1045)
    next_state=post(client,'answer',question_id=first['question']['id'],answer=uv.unit('aps',2)['questions'][0]['answer']).json
    assert next_state['index']==2 and next_state['remaining_ms']==45000
    attempt=persisted(training, trainee)['uv_questionnaire_attempts']['aps']['2']
    assert attempt['answers']['q01']==''
    assert post(client,'answer',question_id='q01',answer='A').json['index']==2


def test_all_timeouts_finish_and_score_zero(case,monkeypatch):
    client,training,trainee,_=case
    post(client,'start',in_class='yes')
    for i in range(20):
        monkeypatch.setattr(uv,'clock',lambda i=i:1000+(i+1)*45)
        result=post(client).json
    assert result=={'completed':True,'score':0}
    assert len(persisted(training, trainee)['uv_questionnaires']['aps']['2']['answers'])==20


@pytest.mark.parametrize('payload',[{'action':'start'}, {'action':'unknown'}, {'action':'answer','question_id':'q01','answer':'A'}])
def test_invalid_start_does_not_persist(case,payload):
    client,training,trainee,_=case
    assert client.post(PATH,json={'csrf':'csrf-test',**payload}).status_code==400
    assert not persisted(training, trainee).get('uv_questionnaire_attempts')


def test_auth_csrf_dates_and_sst_enforced_on_post(case):
    client,training,trainee,_=case
    assert client.post(PATH,json={'csrf':'wrong','action':'start'}).status_code==403
    assert client.get(PATH.replace('/2','/1')).status_code==404
    training['aps_in_person_start']='2026-11-10'
    assert post(client).status_code==client.get(PATH).status_code==403
    assert app.app.test_client().get(PATH).status_code==302
    admin(client)
    assert client.get('/admin/sessions/S1/stagiaires/T1/questionnaires-uv/1.pdf').status_code==404


def test_cancelled_registration_cannot_answer_a_started_question(case):
    client, training, trainee, _ = case
    first = post(client, 'start', in_class='yes').json
    before = copy.deepcopy(persisted(training, trainee))
    trainee['registration_cancelled'] = True
    response = post(client, 'answer', question_id=first['question']['id'],
                    answer=first['question']['options'][0]['id'])
    assert response.status_code == 403
    assert post(client).status_code == client.get(PATH).status_code == 403
    after = persisted(training, trainee)
    assert after['uv_questionnaire_attempts'] == before['uv_questionnaire_attempts']
    assert after['uv_questionnaire_attempts']['aps']['2']['answers'] == {}


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


def test_on_time_arrival_waiting_for_storage_and_actual_remaining_time(case, monkeypatch):
    client, training, trainee, _ = case
    question = post(client, 'start', in_class='yes').json['question']
    now = [1044.0]
    monkeypatch.setattr(uv, 'clock', lambda: now[0])
    store = uv._store(app)
    original_write = store.mutate

    def slow_write(key, seed, mutate):
        now[0] = 1050.0  # The time limit elapsed while waiting for storage.
        state = original_write(key, seed, mutate)
        now[0] = 1052.0  # Acknowledgement must report the actual time remaining.
        return state

    monkeypatch.setattr(store, 'mutate', slow_write)
    monkeypatch.setattr(uv, '_store', lambda _services: store)
    chosen = question['options'][0]['id']
    state = post(client, 'answer', question_id=question['id'], answer=chosen).json
    assert persisted(training, trainee)['uv_questionnaire_attempts']['aps']['2']['answers'] == {'q01': chosen}
    assert state['index'] == 2 and state['remaining_ms'] == 43000


def test_syncs_do_not_write_and_lost_acknowledgement_cannot_skip_another_question(case, monkeypatch):
    client, training, trainee, _ = case
    store = uv._store(app)
    writer = Mock(wraps=store.mutate)
    monkeypatch.setattr(store, 'mutate', writer)
    monkeypatch.setattr(uv, '_store', lambda _services: store)
    assert post(client).json == {'started': False, 'completed': False}
    writer.assert_not_called()
    q = post(client, 'start', in_class='yes').json['question']
    assert post(client).json['index'] == 1
    assert post(client, 'start', in_class='yes').json['remaining_ms'] == 45000
    assert writer.call_count == 1
    chosen = q['options'][0]['id']
    assert post(client, 'answer', question_id=q['id'], answer=chosen).json['index'] == 2
    monkeypatch.setattr(uv, 'clock', lambda: 1090)
    assert post(client, 'answer', question_id=q['id'], answer=chosen).json['index'] == 2
    assert post(client, 'sync', question_id=q['id']).json['index'] == 2
    assert persisted(training, trainee)['uv_questionnaire_attempts']['aps']['2']['answers'] == {'q01': chosen}


@pytest.mark.parametrize('last_question', [False, True])
def test_on_time_answer_survives_another_tab_expiring_first(case, monkeypatch, last_question):
    client, training, trainee, _ = case
    questions = uv.unit('aps', 2)['questions']
    state = post(client, 'start', in_class='yes').json
    if last_question:
        for q in questions[:-1]:
            state = post(client, 'answer', question_id=q['id'], answer=q['answer']).json
    q = questions[-1] if last_question else questions[0]
    assert state['question']['id'] == q['id']
    now = [1044.0]
    monkeypatch.setattr(uv, 'clock', lambda: now[0])
    store = uv._store(app)
    original_write = store.mutate
    monkeypatch.setattr(uv, '_store', lambda _services: store)

    def timeout_before_answer(key, seed, mutate):
        now[0] = 1045.0
        monkeypatch.setattr(store, 'mutate', original_write)
        expired = post(client, 'sync', question_id=q['id']).json
        assert expired['completed'] is last_question
        return original_write(key, seed, mutate)

    monkeypatch.setattr(store, 'mutate', timeout_before_answer)
    res = post(client, 'answer', question_id=q['id'], answer=q['answer'])
    assert res.status_code == 200
    attempt = persisted(training, trainee)['uv_questionnaire_attempts']['aps']['2']
    assert attempt['answers'][q['id']] == q['answer']
    if last_question:
        assert res.json == {'completed': True, 'score': 20}
        assert persisted(training, trainee)['uv_questionnaires']['aps']['2']['score'] == 20
    replayed = post(client, 'answer', question_id=q['id'], answer=q['options'][0]['id']).json
    original = res.json
    if not last_question:
        # Replaying must preserve the question and its deadline, while each
        # independent HTTP request reports its own processing duration.
        assert replayed.pop('server_processing_ms') >= 0
        assert original.pop('server_processing_ms') >= 0
    assert replayed == original


@pytest.mark.parametrize('finished', [False, True])
def test_reset_one_uv_and_reject_old_tabs_and_duplicate_reset(case, finished, monkeypatch):
    from bs4 import BeautifulSoup
    client, training, trainee, _ = case
    monkeypatch.setattr(app, 'save_data', lambda *_args, **_kwargs: None)
    if finished:
        complete(client)
    else:
        post(client, 'start', in_class='yes')
    other_uv = PATH.rsplit('/', 1)[0] + '/3'
    client.post(other_uv, json={'action': 'start', 'csrf': 'csrf-test', 'in_class': 'yes'})
    other_progress = persisted(training, trainee)['uv_questionnaire_attempts']['aps']['3']
    other_trainee = copy.deepcopy(dict(persisted(training, trainee), id='T2', public_token='token-T2'))
    training['trainees'].append(other_trainee)
    with client.session_transaction() as cookie:
        cookie['public_auth_token-T2'] = True
    peer_q = uv.unit('aps', 3)['questions'][0]
    assert client.post('/espace/token-T2/questionnaires-uv/3', json={
        'action': 'answer', 'csrf': 'csrf-test', 'question_id': peer_q['id'],
        'answer': peer_q['answer']}).status_code == 200
    peer_progress = persisted(training, other_trainee)['uv_questionnaire_attempts']
    sheet = '/admin/sessions/S1/stagiaires/T1'
    reset = sheet + '/questionnaires-uv/2/reinitialiser'
    assert client.post(reset).status_code == 302
    assert 'Remettre à zéro' not in client.get(PATH).text
    admin(client)
    form = BeautifulSoup(client.get(sheet).data, 'html.parser').find('form', action=reset)
    assert form and 'Remettre à zéro' in form.text and 'Camille' in form['data-confirmation']
    params = {item['name']: item['value'] for item in form.find_all('input')}
    assert client.post(reset, data={**params, 'csrf': ''}).status_code == 403
    assert client.get(reset).status_code == 405
    with client.session_transaction() as auth:
        auth['admin_role'] = 'viewer'
    assert client.post(reset, data=params).status_code == 403
    assert not BeautifulSoup(client.get(sheet).data, 'html.parser').find('form', action=reset)
    with client.session_transaction() as auth:
        auth.update(admin_role='partner_admin', partner_id='another-training-centre')
    assert client.post(reset, data=params).status_code == 404
    with client.session_transaction() as auth:
        auth.pop('partner_id')
    admin(client)
    receipt = client.post(reset, data=params, follow_redirects=True)
    opened = BeautifulSoup(receipt.data, 'html.parser').select_one('details#questionnaires-uv[open]')
    assert opened and 'Le questionnaire UV 02 a été remis à zéro.' in opened.text
    assert '2' not in persisted(training, trainee)['uv_questionnaire_attempts']['aps']
    assert not persisted(training, trainee).get('uv_questionnaires', {}).get('aps', {}).get('2')
    assert client.get(sheet + '/questionnaires-uv/2.pdf?mode=answers').status_code == 404
    generation = persisted(training, trainee)['uv_questionnaire_resets']['aps']['2']
    assert post(client, 'sync', generation=generation).json['started'] is False
    assert post(client, 'start', in_class='yes', generation=generation).json['index'] == 1
    assert post(client, 'answer', question_id='q01', answer='1').json == {'reset': True}
    assert post(client, 'start', in_class='yes').status_code == 409
    assert client.post(reset, data=params).status_code == 303
    assert persisted(training, trainee)['uv_questionnaire_attempts']['aps']['2']['answers'] == {}
    assert persisted(training, trainee)['uv_questionnaire_attempts']['aps']['3'] == other_progress
    assert persisted(training, other_trainee)['uv_questionnaire_attempts'] == peer_progress


def test_unrelated_save_cannot_erase_an_answer_or_restore_a_reset(tmp_path, monkeypatch):
    data_file = tmp_path / 'data.json'
    monkeypatch.setattr(app, 'PERSIST_DIR', str(tmp_path))
    monkeypatch.setattr(app, 'DATA_FILE', str(data_file))
    monkeypatch.setattr(app, 'BACKUP_DIR', str(tmp_path / 'backups'))
    person = {'id': 'T1', 'public_token': 'token-test'}
    data = {'sessions': [{'id': 'S1', 'training_type': 'APS', 'date_start': '2026-10-26',
                          'aps_in_person_start': '2026-11-09', 'trainees': [person]}]}
    app.save_data(data)
    unchanged_json = data_file.read_bytes()
    stale = json.loads(unchanged_json)
    client = app.app.test_client()
    with client.session_transaction() as cookie:
        cookie.update({'public_auth_token-test': True, 'uv_questionnaire_csrf': 'csrf-test',
                       'uv_reset_csrf': 'reset-test', 'admin_logged_in': True, 'admin_role': 'admin'})
    monkeypatch.setattr(uv, 'today', lambda: dt.date(2026, 11, 10))
    assert post(client, 'start', in_class='yes').status_code == 200
    q = uv.unit('aps', 2)['questions'][0]
    assert post(client, 'answer', question_id=q['id'], answer=q['answer']).status_code == 200
    # The real HTTP handlers save only to SQLite, even when the JSON needs normalization.
    assert data_file.read_bytes() == unchanged_json
    stale['sessions'][0]['trainees'][0]['first_name'] = 'Maya'
    app.save_data(stale)
    saved = app._load_valid_json_payload(str(data_file))
    training = saved['sessions'][0]
    person = training['trainees'][0]
    assert not person.get('uv_questionnaire_attempts')
    assert persisted(training, person)['uv_questionnaire_attempts']['aps']['2']['answers'] == {q['id']: q['answer']}
    assert person['first_name'] == 'Maya'
    assert client.post('/admin/sessions/S1/stagiaires/T1/questionnaires-uv/2/reinitialiser',
                       data={'csrf': 'reset-test', 'generation': ''}).status_code == 303
    app.save_data(saved)
    latest_training = app._load_valid_json_payload(str(data_file))['sessions'][0]
    latest = persisted(latest_training, latest_training['trainees'][0])
    assert latest['uv_questionnaire_resets']['aps']['2']
    assert '2' not in latest['uv_questionnaire_attempts']['aps']
    assert post(client, 'start', in_class='yes').status_code == 409


def test_browser_retries_the_same_choice_after_disconnect_lost_receipt_and_reload(case):
    import os
    import shutil
    from pathlib import Path
    from urllib.parse import urlsplit

    playwright = pytest.importorskip('playwright.sync_api')
    client, training, trainee, _ = case
    posted = []
    delayed = []
    page_errors = []

    def handle(route):
        req = route.request
        url = urlsplit(req.url)
        if url.hostname != 'uv.test':
            return route.abort()
        payload = req.post_data_json if req.method == 'POST' else None
        if payload and payload['action'] == 'answer':
            posted.append((payload['question_id'], payload['answer']))
            if len(posted) == 1:  # The first copy never reached Flask.
                return route.abort()
        res = client.open(url.path, method=req.method, json=payload)
        if payload and payload['action'] == 'answer':
            if len(posted) == 3:  # Flask committed, but its reply was lost.
                return route.abort()
            if len(posted) == 5:
                delayed.append((route, res))
                return
        route.fulfill(status=res.status_code, content_type=res.content_type, body=res.data)

    with playwright.sync_playwright() as driver:
        executable = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH') or shutil.which('chromium') or driver.chromium.executable_path
        if not Path(executable).exists():
            pytest.skip('Chromium indisponible')
        browser = driver.chromium.launch(executable_path=executable, args=['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'])
        page = browser.new_page()
        page.on('pageerror', lambda error: page_errors.append(str(error)))
        page.route('**/*', handle)
        page.clock.install()
        page.goto('https://uv.test' + PATH)
        page.locator('#uq-in-class').check()
        page.locator('#uq-start').click()
        questions = uv.unit('aps', 2)['questions']

        def select_question(i):
            question = questions[i]
            playwright.expect(page.locator('#uq-question')).to_have_text(question['prompt'])
            page.locator('label.uq-option').first.click()
            page.locator('#uq-next').click()
            return question['id'], question['options'][0]['id']

        first = select_question(0)
        playwright.expect(page.locator('#uq-error')).to_be_visible()
        page.locator('#uq-retry').click()
        second = select_question(1)
        playwright.expect(page.locator('#uq-error')).to_be_visible()
        page.reload()
        third = select_question(2)
        playwright.expect(page.locator('#uq-status')).to_contain_text('Enregistrement')
        page.clock.fast_forward(17500)
        playwright.expect(page.locator('#uq-error')).to_be_hidden()
        route, result = delayed.pop()
        route.fulfill(status=result.status_code, content_type=result.content_type, body=result.data)
        playwright.expect(page.locator('#uq-question')).to_have_text(questions[3]['prompt'])
        assert posted == [first, first, second, second, third]
        assert persisted(training, trainee)['uv_questionnaire_attempts']['aps']['2']['answers'] == dict([first, second, third])
        assert not page_errors
        browser.close()


def _advancing_uv_clock(monkeypatch):
    """Move wall and processing clocks together without changing pytest's clock."""
    from types import SimpleNamespace

    now = [1000.0]
    monkeypatch.setattr(uv, 'clock', lambda: now[0])
    monkeypatch.setattr(uv, 'time', SimpleNamespace(
        time=lambda: now[0], monotonic=lambda: now[0]))
    return now


def _delay_next_uv_response(monkeypatch, now, seconds):
    """Model work after the answer commits but before Flask emits its reply."""
    store = uv._store(app)
    original = store.mutate
    delay = [seconds]

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        now[0] += delay[0]
        delay[0] = 0
        return result

    monkeypatch.setattr(store, 'mutate', mutate)
    monkeypatch.setattr(uv, '_store', lambda _services: store)


def _run_questionnaire_timer_script(script, scenario):
    """Run the shipped JS with a pending fetch and a controlled monotonic clock."""
    import shutil
    import subprocess

    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js indisponible')
    harness = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const {source, scenario} = JSON.parse(fs.readFileSync(0, 'utf8'));
let now = 0, intervalId = 0;
const intervals = new Map(), elements = new Map(), requests = [];
class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.listeners = {};
    this.style = {setProperty() {}}; this.classList = {toggle() {}};
    this.textContent = ''; this.hidden = false; this.disabled = false;
  }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  fire(name) { this.listeners[name]?.({preventDefault() {}}); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute() {}
  focus() {}
}
const element = id => {
  if (!elements.has(id)) elements.set(id, new Element());
  return elements.get(id);
};
const descendants = node => [node, ...(node.children || []).flatMap(descendants)];
element('uv-experience').dataset = {endpoint:'/uv-test', csrf:'csrf', seconds:'45', generation:''};
const document = {
  getElementById: element,
  createElement: tag => new Element(tag),
  createTextNode: text => ({textContent:text}),
  querySelector: () => descendants(element('uq-options')).find(node => node.checked),
  addEventListener() {}, hidden:false
};
const context = {
  document, performance:{now:() => now}, AbortController,
  sessionStorage:{getItem:() => null, setItem() {}, removeItem() {}},
  window:{addEventListener() {}, location:{reload() {}, assign() {}}},
  setTimeout:() => 1, clearTimeout() {},
  setInterval:callback => { intervals.set(++intervalId, callback); return intervalId; },
  clearInterval:id => intervals.delete(id),
  fetch:(_url, options) => new Promise(resolve => requests.push({
    payload:JSON.parse(options.body), resolve
  }))
};
const flush = () => new Promise(resolve => setImmediate(resolve));
const advance = ms => { now += ms; for (const tick of [...intervals.values()]) tick(); };
async function deliver(data, elapsed = 0) {
  const request = requests.shift();
  if (!request) throw new Error('No pending questionnaire request');
  advance(elapsed);
  request.resolve({status:200, ok:true, redirected:false, json:async () => data});
  await flush();
  return request.payload;
}
function chooseFirst() {
  const input = descendants(element('uq-options')).find(node => node.tagName === 'input');
  input.checked = true; input.fire('change');
  element('uq-form').fire('submit');
}
(async () => {
  vm.runInNewContext(source, context, {timeout:2000});
  await deliver(scenario.initial);
  element('uq-in-class').checked = true;
  element('uq-start').fire('click');
  await deliver(scenario.started);
  chooseFirst();
  await deliver(scenario.answered, scenario.roundtrip_ms);
  const displayed = Number(element('uq-seconds').textContent);
  advance(scenario.wait_after_delivery_ms);
  const nearDeadline = Number(element('uq-seconds').textContent);
  chooseFirst();
  const submitted = requests[0]?.payload;
  process.stdout.write(JSON.stringify({displayed, nearDeadline, submitted}));
})().catch(error => { process.stderr.write(error.stack); process.exitCode = 1; });
'''
    completed = subprocess.run([node, '-e', harness], input=json.dumps({
        'source': script, 'scenario': scenario}), text=True, capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.parametrize('processing_seconds', [0, 12])
def test_timer_matches_server_after_delayed_reply_without_counting_processing_twice(
        case, monkeypatch, processing_seconds):
    """A delayed reply must not show time the real server no longer permits."""
    import math
    from pathlib import Path

    client, training, trainee, _ = case
    now = _advancing_uv_clock(monkeypatch)
    initial = post(client).json
    started = post(client, 'start', in_class='yes').json
    q1 = started['question']
    _delay_next_uv_response(monkeypatch, now, processing_seconds)
    answered = post(client, 'answer', question_id=q1['id'], answer=q1['options'][0]['id']).json
    deadline = persisted(training, trainee)['uv_questionnaire_attempts']['aps']['2']['deadline']

    # The HTTP body is already computed. Its delivery now takes another 17.5s;
    # the server deadline keeps elapsing during this return trip.
    now[0] += 17.5
    remaining = (deadline - now[0]) * 1000
    scenario = dict(initial=initial, started=started, answered=answered,
                    roundtrip_ms=(processing_seconds + 17.5) * 1000,
                    wait_after_delivery_ms=remaining - 1500)
    source = (Path(__file__).parents[1] / 'static/js/uv-questionnaire.js').read_text()
    observation = _run_questionnaire_timer_script(source, scenario)
    assert observation['displayed'] == math.ceil(remaining / 1000)
    assert observation['nearDeadline'] == 2
    q2 = answered['question']
    submitted = observation['submitted']
    assert submitted['action'] == 'answer'
    assert submitted['question_id'] == q2['id']

    # At the same instant on the advancing server clock, that visible choice
    # is still on time and must be persisted, not converted to a timeout.
    now[0] = deadline - 1.5
    response = post(client, 'answer', question_id=q2['id'], answer=submitted['answer'])
    assert response.status_code == 200 and not response.json.get('answer_expired')
    saved = persisted(training, trainee)['uv_questionnaire_attempts']['aps']['2']['answers']
    assert saved[q2['id']] == submitted['answer']


@pytest.mark.parametrize('processing_seconds', [0, 12])
def test_browser_delayed_reply_keeps_visible_timer_within_the_server_deadline(
        case, monkeypatch, processing_seconds):
    import math
    import os
    import shutil
    from pathlib import Path
    from urllib.parse import urlsplit

    playwright = pytest.importorskip('playwright.sync_api')
    client, training, trainee, _ = case
    now = _advancing_uv_clock(monkeypatch)
    held = []
    answers = []
    errors = []

    def handle(route):
        req = route.request
        url = urlsplit(req.url)
        if url.hostname != 'uv.test':
            return route.abort()
        payload = req.post_data_json if req.method == 'POST' else None
        response = client.open(url.path, method=req.method, json=payload)
        if payload and payload['action'] == 'answer':
            answers.append(response.json)
            if len(answers) == 1:
                held.append((route, response))
                return
        route.fulfill(status=response.status_code, content_type=response.content_type, body=response.data)

    with playwright.sync_playwright() as driver:
        executable = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH') or shutil.which('chromium') or driver.chromium.executable_path
        if not Path(executable).exists():
            pytest.skip('Chromium indisponible')
        browser = driver.chromium.launch(executable_path=executable, args=['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'])
        page = browser.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/*', handle)
        page.clock.install(time=dt.datetime(2026, 11, 18, tzinfo=dt.timezone.utc))
        page.goto('https://uv.test' + PATH)
        page.locator('#uq-in-class').check()
        playwright.expect(page.locator('#uq-start')).to_be_enabled()
        page.clock.pause_at(dt.datetime(2026, 11, 18, 0, 1, tzinfo=dt.timezone.utc))
        page.locator('#uq-start').click()
        questions = uv.unit('aps', 2)['questions']
        playwright.expect(page.locator('#uq-question')).to_have_text(questions[0]['prompt'])
        _delay_next_uv_response(monkeypatch, now, processing_seconds)
        page.locator('label.uq-option').first.click()
        page.locator('#uq-next').click()
        playwright.expect(page.locator('#uq-status')).to_contain_text('Enregistrement')
        # Keep servicing Playwright events until Flask has produced the held
        # response; the saving indicator alone precedes that HTTP event.
        for _ in range(100):
            if held:
                break
            page.wait_for_timeout(10)
        assert held
        deadline = persisted(training, trainee)['uv_questionnaire_attempts']['aps']['2']['deadline']

        now[0] += 17.5
        # Both clocks advance: unlike the old retry test, Flask's deadline
        # really loses this return-trip time while its reply is held.
        page.clock.fast_forward(int((processing_seconds + 17.5) * 1000))
        route, response = held.pop()
        route.fulfill(status=response.status_code, content_type=response.content_type, body=response.data)
        playwright.expect(page.locator('#uq-question')).to_have_text(questions[1]['prompt'])
        remaining = (deadline - now[0]) * 1000
        playwright.expect(page.locator('#uq-seconds')).to_have_text(str(math.ceil(remaining / 1000)))

        now[0] = deadline - 1.5
        page.clock.fast_forward(int(remaining - 1500))
        playwright.expect(page.locator('#uq-seconds')).to_have_text('2')
        page.locator('label.uq-option').first.click()
        page.locator('#uq-next').click()
        playwright.expect(page.locator('#uq-question')).to_have_text(questions[2]['prompt'])
        assert not answers[-1].get('answer_expired')
        saved = persisted(training, trainee)['uv_questionnaire_attempts']['aps']['2']['answers']
        assert saved[questions[1]['id']] == questions[1]['options'][0]['id']
        assert not errors
        browser.close()
