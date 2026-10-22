"""Exercise private agendas through mail previews, actual routes and the J-7 worker."""
import copy
import datetime as dt
import re
from unittest.mock import Mock
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest

import app as gestion
import ssiap_exam as exam
from jury_planning import access_token, agenda
from ssiap_exam_reminders import run


MEMBER = {'id': 'J1', 'first_name': 'Alex', 'last_name': 'JURY', 'role': 'president',
          'email': 'jury@example.test', 'phone': '', 'company': ''}


@pytest.fixture
def planning_case(monkeypatch):
    today = dt.datetime.now(ZoneInfo('Europe/Paris')).date()

    def training(identity, family, offset, **changes):
        date = (today + dt.timedelta(days=offset)).isoformat() if offset is not None else ''
        value = {'id': identity, 'name': family, 'training_type': family,
                 'partner_id': gestion.INTEGRALE_PARTNER_ID, 'exam_date': date,
                 'trainees': [{'id': 'T1', 'first_name': 'Candidat', 'last_name': 'CONFIDENTIEL',
                               'email': 'candidate-private@example.test'}], **changes}
        value[exam.state_key(value)] = {'config': {**exam.DEFAULTS, 'level': family, 'date': date,
            'time': '08:30', 'arrival_time': '08:00', 'end_time': '16:30',
            'location': 'Centre ' + identity, 'address': 'Adresse ' + identity,
            'instructions': 'Accueil au centre.', 'jury': [dict(MEMBER)]}}
        return value

    current = training('CURRENT', 'SSIAP 1', 7)
    # Unordered source, reused contact with another ID and differently cased email.
    later = training('LATER', 'A3P', 30)
    later['security_exam']['config']['jury'][0].update(id='OTHER-ID', email='JURY@example.test')
    next_exam = training('NEXT', 'APS', 14)
    desp = training('DESP', 'DESP initial', 21)
    undated = training('UNDATED', 'SSIAP 2', None)
    unrelated = training('UNRELATED', 'SSIAP 3', 10)
    unrelated['ssiap_exam']['config']['jury'][0].update(email='someone-else@example.test', last_name='AUTRE-JURE')
    partner = training('PARTNER', 'APS', 12, partner_id='other-centre')
    data = {'sessions': [later, current, unrelated, desp, next_exam, undated,
        training('PAST', 'APS', -1), training('ARCHIVED', 'APS', 15, archived=True),
        training('CANCELLED', 'APS', 16, cancelled=True), partner]}
    monkeypatch.setattr(gestion, 'load_data', lambda *a, **kw: copy.deepcopy(data))
    monkeypatch.setattr(gestion, '_atomic_update_data', lambda fn: fn(data))
    monkeypatch.setattr(gestion, 'APP_BASE_URL', 'https://centre.example.test')
    monkeypatch.setattr(gestion.app, 'secret_key', 'test-only-personal-planning-key')
    save = Mock()
    send = Mock(return_value={'ok': True, 'message_id': 'test-only-receipt'})
    monkeypatch.setattr(gestion, 'save_data', save)
    monkeypatch.setattr(gestion, 'brevo_send_email', send)
    client = gestion.app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
        session['admin_role'] = 'admin'
    yield client, data, current, today, send
    save.assert_not_called()


def preview(client, current, kind='invitation'):
    family = 'ssiap-exam' if exam.state_key(current) == 'ssiap_exam' else 'security-exam'
    base = f"/api/admin/sessions/{current['id']}/{family}"
    response = client.get(base + f'/jury/J1/{kind}/preview')
    assert response.status_code == 200, response.json
    return response.json, base


def planning_path(content):
    url = re.search(r'https://centre\.example\.test/jury/planning/[a-f0-9]{64}', content['text']).group()
    return urlsplit(url).path


@pytest.mark.parametrize('family', ['SSIAP 1', 'APS', 'A3P', 'DESP initial'])
@pytest.mark.parametrize('kind', ['invitation', 'reminder'])
def test_each_jury_mail_lists_only_its_other_future_assignments(planning_case, family, kind):
    client, data, current, _, send = planning_case
    state = current.pop('ssiap_exam')
    current['name'] = current['training_type'] = family
    current[exam.state_key(current)] = state
    content, _ = preview(client, current, kind)
    assert 'Voir mes dates de jury' in content['html']
    other_dates = content['text'].split('Vos autres dates de jury')[1].split('Voir mes dates de jury')[0]
    assert other_dates.index('Centre NEXT') < other_dates.index('Centre DESP') < other_dates.index('Centre LATER')
    assert 'Date à confirmer · SSIAP 2' in other_dates
    for excluded in ('CURRENT', 'PAST', 'ARCHIVED', 'CANCELLED', 'PARTNER', 'UNRELATED'):
        assert 'Centre ' + excluded not in other_dates
    assert 'jury@example.test' not in planning_path(content)
    assert 'CONFIDENTIEL' not in content['html'] and 'AUTRE-JURE' not in content['html']
    send.assert_not_called()


def test_link_opens_anonymous_current_agenda_and_exposes_no_other_people(planning_case):
    client, data, current, _, send = planning_case
    content, _ = preview(client, current)
    path = planning_path(content)
    anonymous = gestion.app.test_client()
    response = anonymous.get(path)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Alex JURY' in html and '4 dates à venir' in html
    assert 'Centre CURRENT' in html and 'Centre LATER' in html and 'Centre UNDATED' in html
    assert 'Accueil du jury : 08:00' in html and 'Fin prévisionnelle : 16:30' in html
    assert 'Adresse NEXT' in html and 'Accueil au centre.' in html
    for excluded in ('Centre PARTNER', 'Centre UNRELATED', 'CONFIDENTIEL', 'candidate-private',
                     'AUTRE-JURE', 'someone-else@example.test', '/admin/', 'mail_history'):
        assert excluded not in html
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert 'no-store' in response.headers['Cache-Control']
    assert 'noindex' in response.headers['X-Robots-Tag']
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    send.assert_not_called()


def test_same_link_reflects_date_location_removal_and_cancellation(planning_case):
    client, data, current, today, send = planning_case
    content, _ = preview(client, current)
    path = planning_path(content)
    later = data['sessions'][0]
    later['exam_date'] = (today + dt.timedelta(days=60)).isoformat()
    later['security_exam']['config']['location'] = 'NOUVEAU LIEU'
    next(s for s in data['sessions'] if s['id'] == 'NEXT')['cancelled'] = True
    next(s for s in data['sessions'] if s['id'] == 'DESP')['security_exam']['config']['jury'] = []
    html = gestion.app.test_client().get(path).get_data(as_text=True)
    assert 'NOUVEAU LIEU' in html and 'Centre NEXT' not in html and 'Centre DESP' not in html
    assert '2 dates à venir' in html
    for training in data['sessions']:
        training['archived'] = True
    html = gestion.app.test_client().get(path).get_data(as_text=True)
    assert 'Aucune date à venir pour le moment' in html and 'class="exam"' not in html
    send.assert_not_called()


@pytest.mark.parametrize('token', ['not-a-token', '0' * 64, 'a' * 63])
def test_invalid_links_do_not_disclose_dates_or_names(planning_case, token):
    response = gestion.app.test_client().get('/jury/planning/' + token)
    assert response.status_code == 404
    html = response.get_data(as_text=True)
    assert 'Alex JURY' not in html and 'Centre CURRENT' not in html
    assert 'no-store' in response.headers['Cache-Control']


def test_tokens_are_recipient_scoped_and_old_address_loses_access(planning_case):
    client, data, current, _, send = planning_case
    content, _ = preview(client, current)
    path = planning_path(content)
    assert access_token(gestion, 'JURY@example.test') == path.rsplit('/', 1)[1]
    assert access_token(gestion, 'someone-else@example.test') != path.rsplit('/', 1)[1]
    for training in data['sessions']:
        for member in exam.settings(training)['jury']:
            if member['email'].casefold() == 'jury@example.test':
                member['email'] = 'new-address@example.test'
    assert gestion.app.test_client().get(path).status_code == 404
    send.assert_not_called()


def test_page_escapes_names_locations_and_instructions(planning_case):
    _, _, current, _, _ = planning_case
    config = exam.state(current)['config']
    config.update(location='<script>alert(1)</script>', instructions='<img src=x onerror=alert(1)>')
    response = gestion.app.test_client().get('/jury/planning/' + access_token(gestion, MEMBER['email']))
    html = response.get_data(as_text=True)
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html and '<script>' not in html
    assert '&lt;img src=x onerror=alert(1)&gt;' in html and '<img src=x' not in html


def test_send_preserves_preview_and_rejects_a_changed_other_date(planning_case):
    client, data, current, today, send = planning_case
    content, base = preview(client, current)
    csrf = client.get(base).json['csrf']
    payload = {'csrf': csrf, 'preview_token': content['preview_token']}
    data['sessions'][0]['exam_date'] = (today + dt.timedelta(days=40)).isoformat()
    assert client.post(base + '/mail/send', json=payload).status_code == 409
    send.assert_not_called()
    updated, _ = preview(client, current)
    assert planning_path(updated) == planning_path(content)
    payload['preview_token'] = updated['preview_token']
    assert client.post(base + '/mail/send', json=payload).status_code == 200
    assert send.call_args.args[2] == updated['html']
    assert send.call_args.kwargs['text_content'] == updated['text']
    assert client.post(base + '/mail/send', json=payload).status_code == 409
    assert send.call_count == 1


def test_automatic_j7_mail_also_contains_live_planning_link(planning_case):
    _, data, current, today, send = planning_case
    now = dt.datetime.combine(today, dt.time(9), ZoneInfo('Europe/Paris'))
    assert run(gestion, now=now)['emails_accepted'] == 1
    text = send.call_args.kwargs['text_content']
    assert 'Vos autres dates de jury' in text and 'Centre NEXT' in text
    path = planning_path({'text': text})
    assert gestion.app.test_client().get(path).status_code == 200
    assert run(gestion, now=now)['emails_accepted'] == 0
    assert send.call_count == 1


def test_today_is_included_and_past_dates_are_excluded(planning_case):
    _, data, current, today, _ = planning_case
    exam.state(current)['config']['date'] = today.isoformat()
    items = agenda(gestion, data, MEMBER['email'], today=today)['upcoming']
    assert items[0]['session_id'] == 'CURRENT' and items[0]['date'] == today.isoformat()
    assert all(item['session_id'] != 'PAST' for item in items)
