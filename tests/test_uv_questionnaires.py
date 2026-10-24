import copy
import datetime as dt
from io import BytesIO

import pytest
from pypdf import PdfReader

import app
import uv_questionnaires as uv


@pytest.fixture
def case(monkeypatch):
    trainee = {'id': 'T1', 'first_name': 'Camille', 'last_name': 'MARTIN', 'public_token': 'token-test'}
    training = {'id': 'S1', 'training_type': 'APS', 'name': 'APS test',
                'date_start': '2026-09-01', 'aps_in_person_start': '2026-10-24', 'trainees': [trainee]}
    data = {'sessions': [training]}
    monkeypatch.setattr(app, 'load_data', lambda **kwargs: data)
    monkeypatch.setattr(app, '_atomic_update_data', lambda mutate: mutate(data))
    monkeypatch.setattr(uv, 'today', lambda: dt.date(2026, 10, 24))
    client = app.app.test_client()
    with client.session_transaction() as cookie:
        cookie['public_auth_token-test'] = True
        cookie['uv_questionnaire_csrf'] = 'csrf-test'
    return client, training, trainee, data


def form(number=1):
    return {**{q['id']: q['answer'] for q in uv.unit('aps', number)['questions']},
            'in_class': 'yes', 'csrf': 'csrf-test', 'version': uv.VERSION}


def test_bank_has_all_units_and_20_distinct_questions():
    for course, count in [('aps', 14), ('a3p', 9)]:
        units = uv.bank()['courses'][course]['units']
        assert [r['number'] for r in units] == list(range(1, count+1))
        for row in units:
            assert len(row['questions']) == 20
            assert len({q['prompt'] for q in row['questions']}) == 20
            assert len({q['id'] for q in row['questions']}) == 20
            assert len({q['answer'] for q in row['questions']}) == 3
            for q in row['questions']:
                assert q['answer'] in {o['id'] for o in q['options']}
                assert q['explanation']


@pytest.mark.parametrize('kind,expected', [('APS','aps'),('A3P','a3p'),('APS MAC',''),('MAC A3P',''),('A3P VAE',''),('SSIAP',''),('VTC','')])
def test_course_scope(kind, expected):
    assert uv.course_for({'training_type': kind}) == expected


def test_gate_dates_include_individual_afc_and_exclude_remote_phase(case):
    _, training, trainee, _ = case
    assert uv.available(app, training, trainee)
    training['aps_in_person_start'] = '2026-10-25'
    assert not uv.available(app, training, trainee)
    training.pop('aps_in_person_start')
    assert not uv.available(app, training, trainee)
    training['training_type'] = 'A3P'
    assert uv.available(app, training, trainee)
    training.update(training_type='APS', afc_enabled=True)
    trainee['training_date_start'] = '2026-10-25'
    assert not uv.available(app, training, trainee)
    trainee['training_date_start'] = '2026-10-24'
    assert uv.available(app, training, trainee)
    trainee['registration_cancelled'] = True
    assert not uv.available(app, training, trainee)


def test_no_correction_before_submit_then_score_and_no_overwrite(case):
    client, _, trainee, _ = case
    path = '/espace/token-test/questionnaires-uv/1'
    page = client.get(path)
    assert page.status_code == 200
    assert b'Bonne r' not in page.data
    assert uv.unit('aps', 1)['questions'][0]['explanation'].encode() not in page.data
    values = form()
    values['q01'] = next(o['id'] for o in uv.unit('aps', 1)['questions'][0]['options'] if o['id'] != values['q01'])
    submitted = client.post(path, data=values)
    assert submitted.status_code == 303
    saved = copy.deepcopy(trainee['uv_questionnaires']['aps']['1'])
    assert saved['score'] == 19 and saved['in_class'] is True
    correction = client.get(path)
    assert b'19/20' in correction.data and b'Bonne r' in correction.data
    assert b'name="q01"' not in correction.data
    client.post(path, data=form())
    assert trainee['uv_questionnaires']['aps']['1'] == saved


@pytest.mark.parametrize('change', [lambda x: x.pop('q20'), lambda x: x.update(q01='999'), lambda x: x.pop('in_class'), lambda x: x.update(version='old')])
def test_invalid_submission_does_not_persist(case, change):
    client, _, trainee, _ = case
    values = form(); change(values)
    response = client.post('/espace/token-test/questionnaires-uv/1', data=values)
    assert response.status_code == 400
    assert 'uv_questionnaires' not in trainee
    assert b'Bonne r' not in response.data


def test_public_auth_csrf_and_date_are_enforced_on_post(case):
    client, training, trainee, _ = case
    path = '/espace/token-test/questionnaires-uv/1'
    values = form(); values['csrf'] = 'wrong'
    assert client.post(path, data=values).status_code == 403
    training['aps_in_person_start'] = '2026-10-25'
    assert client.get(path).status_code == client.post(path, data=form()).status_code == 403
    assert 'uv_questionnaires' not in trainee
    assert client.get('/espace/another-token/questionnaires-uv/1').status_code == 302
    assert app.app.test_client().get(path).status_code == 302


def test_atomic_save_rechecks_cancelled_registration(case, monkeypatch):
    client, _, trainee, data = case
    def update(mutate):
        trainee['registration_cancelled'] = True
        return mutate(data)
    monkeypatch.setattr(app, '_atomic_update_data', update)
    assert client.post('/espace/token-test/questionnaires-uv/1', data=form()).status_code == 409
    assert 'uv_questionnaires' not in trainee


def test_admin_preview_and_pdf_are_private_and_include_completed_answers(case):
    client, training, trainee, _ = case
    path = '/admin/sessions/S1/stagiaires/T1/questionnaires-uv/1'
    assert client.get(path).status_code == 302
    client.post('/espace/token-test/questionnaires-uv/1', data=form())
    with client.session_transaction() as cookie:
        cookie['admin_logged_in'] = True
        cookie['admin_role'] = 'admin'
    page = client.get(path)
    assert page.status_code == 200 and b'20/20' in page.data
    assert client.get(path.replace('T1', 'another')).status_code == 404
    blank = client.get(path+'.pdf')
    assert blank.status_code == 200 and blank.mimetype == 'application/pdf'
    blank_text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(blank.data)).pages)
    assert 'Bonne réponse' not in blank_text
    assert 'Camille MARTIN' in blank_text
    assert all(f'{i:02}.' in blank_text for i in range(1,21))
    completed = client.get(path+'.pdf?mode=answers')
    text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(completed.data)).pages)
    assert 'Score : 20/20' in text and 'Bonne réponse' in text
    assert 'no-store' in completed.headers['Cache-Control']


def test_unsupported_session_direct_urls_are_not_available(case):
    client, training, _, _ = case
    training['training_type'] = 'VTC'
    assert client.get('/espace/token-test/questionnaires-uv/1').status_code == 404


def test_portal_and_admin_show_uv_cards_and_afc_specific_label(case, monkeypatch):
    client, training, trainee, _ = case
    monkeypatch.setattr(app, 'save_data', lambda data: None)
    trainee.update(documents=[], public_has_logged_in=True)
    training.update(date_end='2026-12-31', exam_date='2027-01-04', ssiap_exam_date='2027-01-05', afc_enabled=True)
    page=client.get('/espace/token-test')
    assert page.status_code == 200
    assert 'Formation sécurité France Travail Agent de prévention et de sécurité (APS) + SSIAP 1 + SST + Habilitation électrique'.encode() in page.data
    assert 'Financement validé'.encode() not in page.data
    assert b'questionnaires-uv/14' in page.data
    with client.session_transaction() as cookie:
        cookie.update(admin_logged_in=True,admin_role='admin')
    admin=client.get('/admin/sessions/S1/stagiaires/T1')
    assert admin.status_code == 200
    assert b'questionnaires-uv/14.pdf' in admin.data
    training.update(afc_enabled=False,training_type='A3P',name='A3P test')
    a3p=client.get('/admin/sessions/S1/stagiaires/T1')
    assert a3p.status_code == 200
    assert b'attestation-conducteur-a3p/preview' in a3p.data
    assert b'attestation-stu-a3p/preview' in a3p.data
    assert b'questionnaires-uv/9.pdf' in a3p.data
    assert b'questionnaires-uv/14.pdf' not in a3p.data
