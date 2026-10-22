"""Session cards expose only receipts for the current jury, address and exam date."""
import copy
import datetime as dt
import re
from unittest.mock import Mock

import pytest

import app as gestion
import ssiap_exam as exam
from exam_jury_overview import summary


@pytest.fixture
def overview(monkeypatch):
    exam_date = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    training = {
        'id': 'OVERVIEW', 'name': 'APS TEST', 'training_type': 'APS',
        'partner_id': gestion.INTEGRALE_PARTNER_ID, 'exam_date': exam_date,
        'trainees': [{'id': 'T1', 'first_name': 'Camille', 'last_name': 'EXEMPLE'}],
        'security_exam': {'config': {**exam.DEFAULTS, 'date': exam_date, 'time': '08:30',
            'jury': [{'id': 'J1', 'first_name': 'Alex', 'last_name': 'JURY',
                      'email': 'jury@example.test', 'role': 'president'}]}, 'mail_history': []},
    }
    data = {'sessions': [training]}
    monkeypatch.setattr(gestion, 'load_data', lambda *a, **kw: copy.deepcopy(data))
    send = Mock()
    save = Mock()
    monkeypatch.setattr(gestion, 'brevo_send_email', send)
    monkeypatch.setattr(gestion, 'save_data', save)
    client = gestion.app.test_client()
    with client.session_transaction() as current:
        current['admin_logged_in'] = True
        current['admin_role'] = 'admin'
    yield client, training, data
    send.assert_not_called()
    save.assert_not_called()


def receipt(training, kind='invitation', **changes):
    return {'kind': kind, 'jury_id': 'J1', 'to': 'jury@example.test', 'status': 'sent',
            'exam_date': training['exam_date'], 'at': '2026-10-20T07:15:00Z', **changes}


def card_html(client):
    response = client.get('/admin/sessions')
    assert response.status_code == 200
    return re.findall(r'<section class="session-jury".*?</section>', response.get_data(as_text=True), re.S)


@pytest.mark.parametrize('family', ['APS', 'A3P', 'DESP initial', 'SSIAP 1'])
def test_names_and_independent_sent_badges_are_visible_on_session_page(overview, family):
    client, training, _ = overview
    training['training_type'] = training['name'] = family
    if family.startswith('SSIAP'):
        training['ssiap_exam'] = training.pop('security_exam')
    state = exam.state(training)
    state['mail_history'] = [receipt(training)]
    html, = card_html(client)
    assert 'Alex JURY' in html and 'Président du jury' in html
    assert html.count('session-jury__badge--sent') == 1
    assert 'Invitation envoyée le 20/10/2026 à 09:15 (heure de Paris)' in html
    assert 'Rappel J−7' in html and 'Programmé le' in html
    state['mail_history'].append(receipt(training, 'reminder'))
    html, = card_html(client)
    assert html.count('session-jury__badge--sent') == 2


def test_failed_pending_unknown_and_missing_email_are_not_successes(overview):
    client, training, _ = overview
    state = exam.state(training)
    original = state['config']['jury'][0]
    state['config']['jury'] = []
    for index, status in enumerate(('failed', 'sending', 'unknown', 'not_sent', 'missing_email')):
        member = dict(original, id=str(index), first_name='Juré' + str(index), role='member')
        if status == 'missing_email':
            member['email'] = ''
        state['config']['jury'].append(member)
        if status not in ('not_sent', 'missing_email'):
            state['mail_history'].append(receipt(training, jury_id=member['id'], status=status))
    html, = card_html(client)
    assert html.count('class="session-jury__member"') == 5
    for label in ('Invitation : échec', 'Invitation en cours', 'Invitation à vérifier',
                  'Invitation à envoyer', 'E-mail à renseigner'):
        assert label in html
    assert 'session-jury__badge--sent' not in html and '✅' not in html


@pytest.mark.parametrize('change', ['date', 'email', 'member', 'legacy_date'])
def test_old_receipts_do_not_create_success_badges(overview, change):
    client, training, _ = overview
    state = exam.state(training)
    item = receipt(training)
    if change == 'date':
        item['exam_date'] = '2020-01-01'
    elif change == 'email':
        item['to'] = 'previous@example.test'
    elif change == 'member':
        item['jury_id'] = 'REMOVED'
    else:
        item.pop('exam_date')
        item['subject'] = 'Jury - Examen APS du 01/01/2020 à 08:30'
    state['mail_history'] = [item]
    html, = card_html(client)
    assert '✅' not in html and 'Invitation à envoyer' in html


def test_legacy_receipts_require_the_current_date_in_the_subject(overview):
    _, training, _ = overview
    item = receipt(training, to='JURY@example.test')
    item.pop('exam_date')
    item['subject'] = 'Jury - Examen APS du ' + exam.frdate(training['exam_date']) + ' à 08:30'
    exam.state(training)['mail_history'] = [item]
    assert summary(gestion, training)['members'][0]['badges'][0]['state'] == 'sent'
    training['exam_date'] = ''
    assert summary(gestion, training)['members'][0]['badges'][0]['state'] == 'not_sent'


def test_latest_failure_keeps_previous_success_in_details_only(overview):
    _, training, _ = overview
    exam.state(training)['mail_history'] = [receipt(training), receipt(training, status='failed')]
    badge = summary(gestion, training)['members'][0]['badges'][0]
    assert badge['state'] == 'failed' and badge['icon'] != '✅'
    assert 'précédent envoi réussi le 20/10/2026 à 09:15' in badge['detail']


def test_empty_jury_unsupported_sessions_and_partner_isolation(overview):
    client, training, data = overview
    foreign = copy.deepcopy(training)
    foreign.update(id='FOREIGN', partner_id='another-centre', name='FOREIGN')
    foreign['security_exam']['config']['jury'][0]['last_name'] = 'CONFIDENTIEL'
    data['sessions'].append(foreign)
    exam.state(training)['config']['jury'] = []
    html, = card_html(client)
    assert 'Jury à renseigner' in html and 'CONFIDENTIEL' not in html
    assert summary(gestion, foreign) is None
    for family in ('VTC', 'DIRIGEANT VAE', 'MAC APS'):
        training['training_type'] = training['name'] = family
        assert not card_html(client)


def test_read_only_view_and_names_are_escaped(overview):
    client, training, _ = overview
    exam.state(training)['config']['jury'][0]['last_name'] = '<img src=x onerror=alert(1)>'
    with client.session_transaction() as current:
        current['admin_role'] = 'viewer'
    html, = card_html(client)
    assert '&lt;img src=x onerror=alert(1)&gt;' in html and '<img' not in html


def test_incomplete_or_past_reminder_is_not_presented_as_scheduled(overview):
    _, training, _ = overview
    exam.state(training)['config']['time'] = ''
    badge = summary(gestion, training)['members'][0]['badges'][1]
    assert badge['state'] == 'incomplete' and 'à compléter' in badge['detail']
    exam.state(training)['config']['time'] = '08:30'
    training['exam_date'] = '2020-01-01'
    badge = summary(gestion, training)['members'][0]['badges'][1]
    assert badge['state'] == 'not_sent' and 'Échéance passée' in badge['detail']
