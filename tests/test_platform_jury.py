from copy import deepcopy
from unittest.mock import Mock

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


def test_versioned_name_correction_follows_existing_link_and_preserves_the_exam(setup):
    data, training, selector, person, post = setup
    member = {**person, 'id':'local', 'last_name':'EXEMPLE', 'role':'president', 'company':'Entreprise'}
    training['security_exam'] = {'config':{'jury':[member], 'time':'08:00'}, 'mail_history':['receipt']}
    assert post().status_code == 200
    selector.update(target_id=training['id'], exam_date='2027-08-19')
    person.update(first_name='Anne-Marie', last_name='Dupré', name_version=10, phone='123')
    assert post().json['name_version'] == 10
    state = training['security_exam']
    changed, = state['config']['jury']
    assert changed == {**member, 'first_name':'Anne-Marie', 'last_name':'DUPRÉ', 'phone':'+33600000000'}
    assert state['config']['time'] == '08:00' and state['mail_history'] == ['receipt']
    assert state['platform_confirmations'] == {'source/J-1':'local'}
    saved = deepcopy(data)
    person.update(first_name='Ancien', name_version=9)
    assert post().json['name_version'] == 10 and data == saved


def test_edit_in_organisation_et_jury_retries_only_explicit_linked_name_changes(setup, monkeypatch):
    data, training, _, _, post = setup
    assert post().status_code == 200
    monkeypatch.setattr(app, 'load_data', lambda **kwargs:deepcopy(data))
    transmit = Mock(side_effect=platform_jury.requests.Timeout())
    monkeypatch.setattr(platform_jury.requests, 'post', transmit)
    client = app.app.test_client()
    with client.session_transaction() as auth:
        auth.update(admin_logged_in=True, admin_role='admin', ssiap_exam_csrf='fixture-csrf')
    endpoint = '/api/admin/sessions/target/security-exam'
    config = deepcopy(ssiap_exam.settings(training))
    config['jury'][0].update(first_name='Camille-Anne', last_name='du pré')
    payload = {'action':'config','csrf':'fixture-csrf','config':config,'revision':training['security_exam']['revision']}
    result = client.post(endpoint, json=payload)
    assert result.status_code == 200 and result.json['jury_names_pending']
    source = 'source/J-1'
    state = training['security_exam']
    event = state['platform_name_outbox'][source]
    assert event['first_name'] == 'Camille-Anne' and event['last_name'] == 'DU PRÉ'
    assert event['session_id'] == 'source' and event['member_id'] == 'J-1'
    assert transmit.call_args.kwargs['json'] == {k:v for k,v in event.items() if k != 'last_attempt'}
    assert transmit.call_args.kwargs['headers'] == {'Authorization':'Bearer fixture-key'}
    transmit.side_effect = None
    transmit.return_value.json.return_value = {'ok':True,'name_version':event['name_version']}
    platform_jury.retry_name_edits(app, data, 10)
    assert not state['platform_name_outbox']
    transmit.reset_mock()
    payload['revision'] = state['revision']
    payload['config']['jury'][0]['company'] = 'Nouvelle entreprise'
    assert client.post(endpoint, json=payload).status_code == 200
    transmit.assert_not_called()
