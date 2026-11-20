from copy import deepcopy

import pytest

import app
import platform_jury
import ssiap_exam


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('JURY_SYNC_TOKEN', 'fixture-key')
    training = {'id': 'target', 'training_type': 'APS', 'name': 'APS',
                'exam_date': '2027-02-04', 'date_start': '2027-01-02', 'date_end': '2027-02-03'}
    data = {'sessions': [training, {**training, 'id': 'other-partner', 'partner_id': 'external'}]}
    monkeypatch.setattr(app, '_atomic_update_data', lambda fn: fn(data))
    client = app.app.test_client()
    member = {'id': 'J-1', 'first_name': 'Camille', 'last_name': 'Exemple', 'phone': '+33600000000', 'email': 'jury@example.test'}
    selector = {'source_id': 'source', 'level': 'APS', 'date_start': training['date_start'],
                'date_end': training['date_end'], 'exam_date': training['exam_date']}
    def post(key='fixture-key'):
        return client.post('/api/integrations/plateformegestion/jury-confirmations',
                           json={'member': member, 'session': selector}, headers={'Authorization': 'Bearer ' + key})
    return data, training, selector, member, post


def test_sync_creates_actual_exam_member_once_and_protects_other_partners(setup):
    data, training, _, _, post = setup
    before = deepcopy(data)
    assert post('wrong').status_code == 403
    assert data == before
    assert post().json == {'ok': True, 'session_id': 'target'}
    after = deepcopy(data)
    assert post().status_code == 200 and after == data
    member, = ssiap_exam.settings(training)['jury']
    assert member['role'] == 'member' and member['last_name'] == 'EXEMPLE'
    assert ssiap_exam.jury_directory(data, app.INTEGRALE_PARTNER_ID)[0]['id'] == member['id']
    assert 'security_exam' not in data['sessions'][1]


def test_sync_preserves_existing_member_and_configuration(setup):
    _, training, _, person, post = setup
    member = {**person, 'id': 'local', 'role': 'president', 'company': 'Entreprise', 'phone': ''}
    training['security_exam'] = {'config': {'jury': [member], 'time': '08:00'}, 'revision': 2, 'mail_history': ['kept']}
    assert post().status_code == 200
    state = training['security_exam']
    assert state['config']['jury'] == [{**member, 'phone': person['phone']}]
    assert state['revision'] == 3 and state['config']['time'] == '08:00' and state['mail_history'] == ['kept']


def test_distinguishes_ambiguous_sessions_and_the_two_afc_exams(setup):
    data, training, selector, _, post = setup
    data['sessions'].append({**training, 'id': 'another'})
    assert post().status_code == 409
    assert all('security_exam' not in s for s in data['sessions'])
    training.update(afc_enabled=True, ssiap_exam_date='2027-02-05')
    selector.update(afc=True, level='SSIAP 1', exam_date='2027-02-05', target_id='target')
    assert post().status_code == 200
    assert training['ssiap_exam']['config']['jury'] and 'security_exam' not in training
    from exam_jury_overview import summary
    confirmed, = summary(app, training)['members']
    assert confirmed['confirmed'] and confirmed['exam_label'] == 'SSIAP 1'


def test_domain_scoped_shared_key(monkeypatch):
    monkeypatch.delenv('JURY_SYNC_TOKEN', raising=False)
    monkeypatch.setenv('AFC_ATTENDANCE_SYNC_TOKEN', 'fixture-only')
    assert platform_jury.integration_key() != 'fixture-only'
    assert len(platform_jury.integration_key()) == 64


def test_afc_confirmations_are_independent_for_the_same_juror(setup):
    _, training, selector, _, post = setup
    from exam_jury_overview import summary
    training.update(afc_enabled=True, ssiap_exam_date='2027-02-15')
    selector.update(afc=True, target_id='target', level='APS', exam_date='2027-02-15')
    assert post().status_code == 409
    assert 'ssiap_exam' not in training and 'security_exam' not in training
    selector['exam_date'] = training['exam_date']
    assert post().status_code == 200
    aps, ssiap = summary(app, training)['exams']
    assert aps['label'] == 'APS' and aps['members'][0]['confirmed']
    assert ssiap['label'] == 'SSIAP 1' and ssiap['members'] == []
    selector.update(level='SSIAP 1', exam_date='2027-02-15')
    assert post().status_code == 200
    assert post().status_code == 200
    for exam in summary(app, training)['exams']:
        member, = exam['members']
        assert member['confirmed'] and member['name'] == 'Camille EXEMPLE'
