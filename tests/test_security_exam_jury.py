"""End-to-end jury workflows use a fake mail provider and in-memory session data."""
import copy
import datetime as dt
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

import app as gestion
import ssiap_exam as exam
from ssiap_exam_reminders import run, schedule

BASE = '/api/admin/sessions/S1/security-exam'
MEMBER = {'id': 'J1', 'first_name': 'Alex', 'last_name': 'JURY', 'role': 'president',
          'email': 'jury@example.test', 'phone': '', 'company': 'Centre exemple'}


@pytest.fixture(params=['APS', 'A3P', 'DESP initial'])
def jury_case(request, monkeypatch):
    future = (dt.datetime.now(ZoneInfo('Europe/Paris')).date() + dt.timedelta(days=30)).isoformat()
    training = {'id': 'S1', 'name': request.param + ' novembre', 'training_type': request.param,
                'exam_date': future, 'date_start': '2026-11-03', 'date_end': '2026-12-01',
                'trainees': [{'id': 'T1', 'first_name': 'Camille', 'last_name': 'EXEMPLE'},
                             {'id': 'T2', 'registration_cancelled': True}]}
    data = {'sessions': [training, {'id': 'FIRE', 'training_type': 'SSIAP 1',
            'ssiap_exam': {'config': {**exam.DEFAULTS, 'jury': [{**MEMBER, 'id': 'J2', 'email': 'existing@example.test'}]}}}]}
    monkeypatch.setattr(gestion, 'load_data', lambda *a, **kw: copy.deepcopy(data))
    monkeypatch.setattr(gestion, 'save_data', Mock())
    monkeypatch.setattr(gestion, '_atomic_update_data', lambda fn: fn(data))
    send = Mock(return_value={'ok': True, 'message_id': 'test-only'})
    monkeypatch.setattr(gestion, 'brevo_send_email', send)
    client = gestion.app.test_client()
    with client.session_transaction() as current:
        current['admin_logged_in'] = True
        current['admin_role'] = 'admin'
    return client, data, training, send


def configure(case):
    client, _, training, send = case
    view = client.get(BASE).json
    config = {**view['config'], 'time': '08:30', 'arrival_time': '08:00', 'end_time': '16:30',
              'jury': [MEMBER], 'instructions': 'Accueil au centre.'}
    response = client.post(BASE, json={'csrf': view['csrf'], 'revision': view['revision'],
                                      'action': 'config', 'config': config})
    assert response.status_code == 200, response.json
    return client.get(BASE).json


def test_save_preview_send_tracking_and_replay(jury_case):
    client, data, training, send = jury_case
    view = configure(jury_case)
    assert view['config']['level'] == training['training_type']
    assert [c['id'] for c in view['candidates']] == ['T1']
    assert any(m['email'] == 'existing@example.test' for m in view['directory'])
    assert training['security_exam']['config']['jury'] == [MEMBER]
    assert 'ssiap_exam' not in training
    send.assert_not_called()
    for kind in ('invitation', 'reminder'):
        preview = client.get(BASE + f'/jury/J1/{kind}/preview')
        assert preview.status_code == 200, preview.json
        content = preview.json
        assert training['training_type'] in content['subject']
        assert 'SSIAP' not in content['html']
        assert '08:30' in content['text'] and 'Accueil au centre.' in content['text']
        payload = {'csrf': view['csrf'], 'preview_token': content['preview_token']}
        assert client.post(BASE + '/mail/send', json=payload).status_code == 200
        assert client.post(BASE + '/mail/send', json=payload).status_code == 409
        assert client.get(BASE).json['mail_status']['J1'][kind]['sent_count'] == 1
    assert send.call_count == 2
    assert send.call_args.kwargs['metadata']['purpose'] == 'security_exam_reminder'
    assert len(training['security_exam']['mail_history']) == 2
    assert not data['sessions'][1]['ssiap_exam'].get('mail_history')


def test_access_control_scope_validation_and_changed_preview(jury_case):
    client, _, training, send = jury_case
    view = configure(jury_case)
    payload = {'action': 'config', 'config': view['config'], 'revision': view['revision'], 'csrf': view['csrf']}
    assert client.post(BASE, json={**payload, 'csrf': 'wrong'}).status_code == 403
    assert client.post(BASE, json={**payload, 'config': {**view['config'], 'level': 'SSIAP 1'}}).status_code == 400
    preview = client.get(BASE + '/jury/J1/invitation/preview').json
    training['exam_date'] = (dt.date.fromisoformat(training['exam_date']) + dt.timedelta(days=1)).isoformat()
    assert client.post(BASE + '/mail/send', json={'csrf': view['csrf'], 'preview_token': preview['preview_token']}).status_code == 409
    assert client.post(BASE, json={**payload, 'expected_date': view['config']['date']}).status_code == 409
    assert client.get(BASE.replace('security-exam', 'ssiap-exam')).status_code == 404
    assert client.get(BASE.replace('S1', 'FIRE')).status_code == 404
    with client.session_transaction() as current:
        current['admin_role'] = 'viewer'
    assert client.get(BASE).json['read_only']
    assert client.post(BASE, json=payload).status_code == 403
    assert client.post(BASE + '/mail/send', json={'csrf': view['csrf'], 'preview_token': preview['preview_token']}).status_code == 403
    training['partner_id'] = 'different-centre'
    assert client.get(BASE).status_code == 404
    send.assert_not_called()


def test_j7_uses_existing_cron_once_and_isolated_history(jury_case):
    _, data, training, send = jury_case
    configure(jury_case)
    due = dt.date.fromisoformat(training['exam_date']) - dt.timedelta(days=7)
    now = dt.datetime.combine(due, dt.time(9), ZoneInfo('Europe/Paris'))
    before = copy.deepcopy(data)
    assert run(gestion, now=now, dry_run=True)['due'] == 1
    assert data == before
    assert run(gestion, now=now - dt.timedelta(minutes=1))['processed'] == 0
    assert run(gestion, now=now)['emails_accepted'] == 1
    assert run(gestion, now=now + dt.timedelta(hours=1))['processed'] == 0
    assert schedule(gestion, training, now=now)['members']['J1']['status'] == 'sent'
    assert training['training_type'] in send.call_args.args[1]
    assert training['security_exam']['mail_history'][0]['source'] == 'automatic_j7'
    assert send.call_count == 1


def test_calendar_and_jury_date_stay_in_sync(jury_case):
    client, _, training, send = jury_case
    view = configure(jury_case)
    label = training['training_type']
    if label == 'DESP initial':
        training['exam_date'] = '2027-03-16'
        assert client.get(BASE).json['config']['date'] == '2027-03-16'
        return
    calendar_url = '/api/admin/sessions/S1/' + label.lower() + '-exam-dossiers'
    calendar = client.get(calendar_url).json
    assert calendar['exam_date'] == view['config']['date']
    response = client.post(calendar_url, json={**calendar, 'exam_date': '2027-03-16', 'epi_training_date': '2026-11-05'})
    assert response.status_code == 200, response.json
    assert client.get(BASE).json['config']['date'] == '2027-03-16'
    stale = {'action': 'config', 'csrf': view['csrf'], 'revision': view['revision'], 'config': view['config']}
    assert client.post(BASE, json=stale).status_code == 409
    view = client.get(BASE).json
    assert client.post(BASE, json={**stale, 'revision': view['revision'], 'config': {**view['config'], 'date': '2027-04-20'}}).status_code == 200
    assert client.get(calendar_url).json['exam_date'] == '2027-04-20'
    assert training['exam_date'] == '2027-04-20'
    stale_calendar = {**calendar, 'exam_date': '2027-03-16', 'epi_training_date': '2026-11-05', 'selected_trainee_ids': ['T1']}
    assert client.post(calendar_url + '/generate', json=stale_calendar).status_code == 409
    send.assert_not_called()


def test_unrelated_saves_preserve_jury_and_history(jury_case):
    _, data, training, _ = jury_case
    configure(jury_case)
    training['security_exam']['mail_history'] = [{'status': 'sent', 'to': MEMBER['email']}]
    stale = {'sessions': [{k: v for k, v in training.items() if k != 'security_exam'}]}
    exam.preserve_state(stale, data)
    assert stale['sessions'][0]['security_exam'] == training['security_exam']
    assert stale['ssiap_jury_directory'] == data['ssiap_jury_directory']


@pytest.mark.parametrize('label', ['DESP VAE', 'DIRIGEANT VAE', 'MAC APS', 'VTC', 'SSIAP 1', 'AFC APS SSIAP'])
def test_non_initial_or_other_training_has_no_security_jury(label):
    assert not exam.security_exam_jury.level({'training_type': label})


def test_paris_exam_requires_its_own_address():
    config = exam.settings({'training_type': 'DESP initial', 'name': 'DESP PARIS'})
    assert config['location'] == 'Intégrale Academy – Paris'
    assert config['address'] == ''
