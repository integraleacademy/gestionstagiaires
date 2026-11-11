import concurrent.futures
import copy
import datetime as dt
import re
import sqlite3
from unittest.mock import patch

import pytest

import app as host
import aps_learning_followup as daily
from elearning_reporting import ProgressReader
from elearning_native.store import NativeElearningStore
from test_aps_session_rollout import aps_case

NOW = dt.datetime(2026, 11, 4, 9, tzinfo=daily.PARIS)


@pytest.fixture
def learner(aps_case):
    training = aps_case.data['sessions'][0]
    training.update(aps_remote_start='2026-11-03', aps_remote_end='2026-11-29', aps_in_person_start='2026-11-30')
    person = training['trainees'][0]
    person.update(email='alice@example.test', first_name='Alice')
    aps_case._admin_login()
    return aps_case, training, person


def test_real_report_matches_detail_and_does_not_change_learning_history(learner):
    case, training, person = learner
    before = copy.deepcopy(case.data)
    report = daily.read_summary(host, training, person)
    assert report['available'] and report['overall_percent'] == 0 and not report['complete']
    assert report['required_seconds'] == report['remaining_seconds'] == 62 * 3600
    assert report['active_seconds'] == 0
    assert case.data == before
    assert not (case.persist_dir / 'native_elearning' / 'tracking.sqlite3').exists()
    response = case.client.get('/admin/sessions/session-aps/e-learning/aps-resume')
    assert response.status_code == 200
    row = response.json['rows'][person['id']]
    assert '00 h 00 min 00 s' in row and 'Hors ligne' in row
    assert case.report_url in row and 'data-aps-elearning-complete-badge' not in row


def test_roster_uses_native_only_from_november_and_keeps_legacy(learner):
    case, training, _ = learner
    with patch.object(host, '_hydrate_missing_trainee_nubs_from_cnaps_tracking'), patch.object(host, 'compute_stats', return_value={}):
        page = case.client.get('/admin/sessions/session-aps/trainees')
        assert page.status_code == 200 and 'data-aps-roster-trainee="trainee-1"' in page.text
        assert 'id="btnImportDigiforma"' not in page.text
        assert 'Attestations e-learning' in page.text and 'Questionnaires de fin d’UV' in page.text
        training['date_start'] = '2026-10-31'
        page = case.client.get('/admin/sessions/session-aps/trainees')
        assert page.status_code == 200 and 'data-aps-roster-trainee=' not in page.text
        assert 'id="btnImportDigiforma"' in page.text


def test_only_completed_activity_and_required_time_get_the_blue_validation():
    person = {'id': 'p'}
    report = {'available': True, 'complete': False, 'progress_percent': 100, 'modules': [], 'remaining_seconds': 60}
    assert daily.summary(report, person, set())['overall_percent'] == 99.9
    assert not daily.summary(report, person, set())['complete']
    report.update(complete=True, remaining_seconds=0)
    assert daily.summary(report, person, set())['overall_percent'] == 100
    report['available'] = False
    assert not daily.summary(report, person, set())['complete']


def test_critical_email_requests_help_instead_of_an_impossible_daily_workload(learner):
    _, training, person = learner
    report = daily.read_summary(host, training, person)
    content = daily.message(host, training, person, report, dt.date(2026, 11, 29))
    assert content['tone'] == 'critical'
    assert '62 h 00 min 00 s par jour' not in content['html']
    assert 'Objectif indicatif par jour' not in content['text']
    assert 'contactez-nous dès aujourd’hui' in content['html']


def test_live_requires_recent_active_nonended_pinned_connection(learner):
    case, training, person = learner
    reader = ProgressReader(host)
    NativeElearningStore(reader.database_path)
    course = daily.source_for(training, person)[0]['modules'][0]
    access = {'session_id': training['id'], 'trainee_id': person['id'], 'course_id': course['course_id'], 'course_version': course['course_version']}
    store = NativeElearningStore(reader.database_path)
    tracking = store.start_tracking(access, tab_id='tab', activity_id='read', now_epoch=NOW.timestamp())
    with sqlite3.connect(reader.database_path) as db:
        db.execute("UPDATE tracking_sessions SET was_active=1,active_until_epoch=?,last_seen_epoch=? WHERE id=?", (NOW.timestamp()+600, NOW.timestamp(), tracking['tracking_session_id']))
        db.execute('UPDATE learner_course_progress SET active_tracking_session_id=?,active_tracking_seen_epoch=?', (tracking['tracking_session_id'],NOW.timestamp()))
    live = daily.live_records(reader, training['id'], NOW)
    assert (person['id'], course['course_id'], course['course_version']) in live
    assert daily.live_records(reader, 'other-session', NOW) == set()
    assert daily.live_records(reader, training['id'], NOW + dt.timedelta(seconds=46)) == set()
    with sqlite3.connect(reader.database_path) as db:
        db.execute('UPDATE tracking_sessions SET was_active=0')
    assert daily.live_records(reader, training['id'], NOW) == set()
    with sqlite3.connect(reader.database_path) as db:
        db.execute("UPDATE tracking_sessions SET was_active=1,ended_at='2026-11-04T08:00:00Z'")
    assert daily.live_records(reader, training['id'], NOW) == set()


@pytest.mark.parametrize('instant,expected', [
    (dt.datetime(2026,11,4,7,59,tzinfo=dt.timezone.utc), False),
    (dt.datetime(2026,11,4,8,0,tzinfo=dt.timezone.utc), True),
    (dt.datetime(2027,7,4,6,59,tzinfo=dt.timezone.utc), False),
    (dt.datetime(2027,7,4,7,0,tzinfo=dt.timezone.utc), True),
])
def test_paris_nine_oclock_in_winter_and_summer(learner, instant, expected):
    case, training, person = learner
    day = instant.astimezone(daily.PARIS).date()
    training.update(date_start=day.isoformat(), aps_remote_start=day.isoformat(), aps_in_person_start=(day+dt.timedelta(days=20)).isoformat())
    with patch.object(host, 'brevo_send_email', return_value={'ok':True}) as send:
        result = daily.run(host, now=instant)
    assert bool(send.call_count) == expected
    assert result['sent'] == int(expected)


@pytest.mark.parametrize('changes,person_changes', [
    ({'date_start':'2026-10-31'}, {}), ({'aps_in_person_start':'2026-11-04'}, {}),
    ({'aps_remote_start':'2026-11-05'}, {}), ({'aps_in_person_start':''}, {}),
    ({'archived':True}, {}), ({'cancelled':True}, {}), ({'partner_id':'another'}, {}),
    ({}, {'registration_cancelled':True}),
])
def test_excluded_learners_are_never_sent(learner, changes, person_changes):
    _, training, person = learner
    training.update(changes)
    person.update(person_changes)
    with patch.object(host, 'brevo_send_email') as send:
        result = daily.run(host, now=NOW)
    assert result['eligible'] == 0
    send.assert_not_called()


def test_daily_delivery_is_durable_per_person_and_preview_keeps_sent_snapshot(learner):
    case, training, person = learner
    with patch.object(host, 'brevo_send_email', return_value={'ok':True, 'message_id':'receipt'}) as send:
        first = daily.run(host, now=NOW)
        second = daily.run(host, now=NOW+dt.timedelta(minutes=5))
        assert first['sent'] == 1 and second['sent'] == 0
        send.assert_called_once()
        assert send.call_args.kwargs['metadata']['idempotency_key']
        assert send.call_args.kwargs['reply_to']['email'] == 'cassandre@integraleacademy.com'
        html = send.call_args.args[2]
        assert 'Bonjour Alice' in html and '30/11/2026' in html and 'Cassandre MENARD' in html
        assert 'mailto:ecole@integraleacademy.com' in html
        receipt = daily.delivery(host, training['id'], person['id'], NOW.date())
        assert receipt['status'] == 'sent' and receipt['message_id'] == 'receipt'
        assert len(person['sent_email_history']) == 1
        person['first_name'] = 'Changed'
        with patch.object(daily, 'clock', return_value=NOW):
            preview = case.client.get(case.report_url + '/mail-du-jour')
        assert preview.status_code == 200 and preview.text == html
        third = daily.run(host, now=NOW+dt.timedelta(days=1))
        assert third['sent'] == 1 and send.call_count == 2
        assert send.call_args.args[2] != html


def test_readonly_preview_never_sends_or_creates_a_delivery(learner):
    case, _, person = learner
    with patch.object(daily, 'clock', return_value=NOW), patch.object(host, 'brevo_send_email') as send:
        response = case.client.get(case.report_url + '/mail-du-jour')
        page = case.client.get(case.report_url)
    assert response.status_code == 200 and 'Bonjour Alice' in response.text
    assert 'Prévisualiser le mail du jour' in page.text and '09h00' in page.text
    assert 'Retour à tous les stagiaires' in page.text
    assert '/admin/sessions/session-aps/trainees' in page.text
    assert 'Votre formation agent de prévention et de sécurité (APS)' in response.text
    assert re.search(r'<h1[^>]*>Suivi de votre formation e-learning</h1>', response.text)
    assert 'Votre formation agent de prévention' not in response.text.split('Bonjour Alice,', 1)[1]
    assert 'Memoji de Cassandre MENARD' in response.text and 'border-radius:50%' in response.text
    assert 'Responsable commerciale – Intégrale Academy' in response.text
    assert 'href="tel:0422470768"' in response.text
    assert '/static/images/email/cassandre-signature.png' not in response.text
    assert 'Aucun mail de suivi e-learning envoyé' in page.text
    assert '04 87 83 06 16' in response.text and '07 43 58 22 64' in response.text
    assert not daily.ledger_path(host).exists()
    send.assert_not_called()
    anonymous = host.app.test_client()
    assert anonymous.get(case.report_url + '/mail-du-jour').status_code == 302
    with case.client.session_transaction() as auth:
        auth.update(admin_role='partner_admin', partner_id='other')
    assert case.client.get(case.report_url + '/mail-du-jour').status_code == 404
    assert case.client.get('/admin/sessions/session-aps/e-learning/aps-resume').status_code == 404


def test_sent_history_is_scoped_and_opens_original_even_after_the_session(learner):
    case, training, person = learner
    day = NOW.date()
    with patch.object(host, 'brevo_send_email', return_value={'ok': True}) as send:
        assert daily.run(host, now=NOW)['sent'] == 1
        original = send.call_args.args[2]
        assert daily.MAIL_TITLE in send.call_args.kwargs['text_content']
        assert 'Votre formation agent de prévention' not in send.call_args.kwargs['text_content']
    with daily.connect_ledger(host) as db:
        for sid, tid, offset, status, subject in (
            (training['id'], person['id'], -1, 'sent', 'Ancien mail'),
            (training['id'], person['id'], 1, 'uncertain', 'Incertain'),
            (training['id'], person['id'], 2, 'refused', 'Refusé'),
            (training['id'], person['id'], 3, 'sending', 'En cours'),
            ('other-session', person['id'], 1, 'sent', 'Autre session'),
            (training['id'], 'other-id', 1, 'sent', 'Autre élève'),
        ):
            db.execute("""INSERT INTO deliveries(session_id,trainee_id,day,status,recipient,subject,html,text,attempted_at)
                VALUES(?,?,?,?,?,?,?,'','')""", (sid, tid, (day+dt.timedelta(days=offset)).isoformat(), status,
                'original@example.test', subject, '<p>Texte archivé</p>'))
    history_url = case.report_url + '/historique-mails/'
    person.update(first_name='Changé', email='new@example.test')
    with patch.object(daily, 'clock', return_value=NOW+dt.timedelta(days=40)), patch.object(host, 'brevo_send_email') as send:
        report = case.client.get(case.report_url)
        assert report.status_code == 200
        assert '<a href="#historique-mails">Historique mails</a>' in report.text
        section = report.text.split('<section id="historique-mails"', 1)[1].split('</section>', 1)[0]
        assert section.index('04/11/2026 à 09h00') < section.index('Ancien mail')
        assert 'alice@example.test' in section and 'new@example.test' not in section
        assert section.count(history_url) == 2 and section.count('original@example.test') == 1
        assert history_url + day.isoformat() in section
        assert case.client.get(history_url + day.isoformat()).text == original
        assert case.client.get(history_url + '2026-11-03').text == '<p>Texte archivé</p>'
        for absent in ('2026-11-05', '2026-11-06', '2026-11-07', '2026-11-08'):
            assert case.client.get(history_url + absent).status_code == 404
        send.assert_not_called()
    assert host.app.test_client().get(history_url + day.isoformat()).status_code == 302
    with case.client.session_transaction() as auth:
        auth.update(admin_role='partner_admin', partner_id='other')
    assert case.client.get(history_url + day.isoformat()).status_code == 404


def test_concurrent_jobs_can_claim_only_one_send(learner):
    _, training, person = learner
    content = {'subject':'Daily', 'html':'<p>Daily</p>', 'text':'Daily'}
    # Schema created before concurrency to model the already-running service.
    with daily.connect_ledger(host):
        pass
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: daily.claim(host,training,person,NOW.date(),content,NOW), range(6)))
    assert sum(results) == 1


def test_refused_send_can_retry_but_uncertain_delivery_is_not_replayed(learner):
    case, _, _ = learner
    with patch.object(host, 'brevo_send_email', side_effect=[{'ok':False,'status_code':429}, {'ok':True}]) as send:
        assert daily.run(host, now=NOW)['failed'] == 1
        assert daily.run(host, now=NOW+dt.timedelta(minutes=5))['sent'] == 1
        assert send.call_args_list[0].kwargs['metadata']['idempotency_key'] == send.call_args_list[1].kwargs['metadata']['idempotency_key']
    tomorrow = NOW+dt.timedelta(days=1)
    with patch.object(host,'brevo_send_email',side_effect=TimeoutError) as send:
        assert daily.run(host,now=tomorrow)['uncertain'] == 1
        assert daily.run(host,now=tomorrow+dt.timedelta(minutes=5))['sent'] == 0
        send.assert_called_once()


def test_personalization_changes_with_progress_and_day(learner):
    _, training, person = learner
    report = daily.read_summary(host, training, person)
    early = daily.message(host, training, person, report, NOW.date())
    advanced = daily.message(host, training, person, {**report, 'overall_percent':80,'remaining_seconds':3600}, NOW.date())
    complete = daily.message(host, training, person, {**report,'overall_percent':100,'complete':True,'remaining_seconds':0}, NOW.date())
    assert early['tone'] == 'steady' and advanced['tone'] == 'advanced' and complete['tone'] == 'complete'
    assert 'Bravo' in advanced['html'] and 'Félicitations' in complete['html']
    assert len({daily.message(host,training,person,report,NOW.date()+dt.timedelta(days=i))['html'] for i in range(20)}) == 20


def test_cron_requires_secret_even_if_not_configured(learner, monkeypatch):
    case, _, _ = learner
    monkeypatch.delenv('CRON_SECRET',raising=False)
    assert case.client.post('/internal/cron/aps-daily-followup').status_code == 403
    monkeypatch.setenv('CRON_SECRET','test-secret')
    assert case.client.post('/internal/cron/aps-daily-followup',headers={'X-Cron-Secret':'wrong'}).status_code == 403
    with patch.object(daily,'run',return_value={'ok':True,'sent':0}) as run:
        assert case.client.post('/internal/cron/aps-daily-followup',headers={'X-Cron-Secret':'test-secret'}).status_code == 200
        run.assert_called_once()


def test_yesterday_delta_reports_time_even_without_completed_activity_and_prompts_restart(learner):
    _, training, person = learner
    report = daily.read_summary(host, training, person)
    first_point = daily.message(host, training, person, {**report, 'active_seconds': 3600,
                                'active_time_label': '01 h 00 min 00 s'}, NOW.date())
    assert 'Votre temps de suivi enregistré à ce jour' in first_point['html']
    assert 'Depuis le point d’hier' not in first_point['html']
    with patch.object(host, 'brevo_send_email', return_value={'ok': True}):
        daily.run(host, now=NOW)
    day = NOW.date() + dt.timedelta(days=1)
    advanced = daily.message(host, training, person, {**report, 'active_seconds': 3600}, day)
    assert '01 h 00 min 00 s de suivi' in advanced['html']
    assert 'Votre progression depuis hier est prise en compte' in advanced['html']
    idle = daily.message(host, training, person, report, day)
    assert 'Aucune nouvelle activité ni durée de suivi' in idle['html']
    assert 'prochain créneau de travail' in idle['html']
    assert daily.progress_since_yesterday(host, training, person, report, day)['advanced'] is False
    assert daily.progress_since_yesterday(host, training, person, report, day + dt.timedelta(days=1)) is None
    assert daily.progress_since_yesterday(host, training, person, {**report, 'versions':['changed']}, day) is None


def test_existing_ledger_migration_preserves_receipts(learner):
    _, training, person = learner
    path = daily.ledger_path(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE deliveries(session_id TEXT, trainee_id TEXT, day TEXT, status TEXT, recipient TEXT, subject TEXT, html TEXT, text TEXT, attempted_at TEXT, sent_at TEXT, message_id TEXT, attempts INTEGER, PRIMARY KEY(session_id,trainee_id,day))')
        db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (training['id'],person['id'],NOW.date().isoformat(),'sent','test@example.org','Old','<p>Old</p>','Old','','','msg',1))
    assert daily.progress_since_yesterday(host, training, person, daily.read_summary(host,training,person), NOW.date()+dt.timedelta(days=1)) is None
    with daily.connect_ledger(host):
        pass
    assert daily.delivery(host, training['id'], person['id'], NOW.date())['html'] == '<p>Old</p>'
    with patch.object(host, 'brevo_send_email') as send:
        assert daily.run(host, now=NOW)['sent'] == 0
        send.assert_not_called()


@pytest.mark.parametrize('delta', [None,
    {'advanced': True, 'seconds': 3986, 'time_label': '01 h 06 min 26 s', 'activities': 1},
    {'advanced': False, 'seconds': 0, 'time_label': '00 h 00 min 00 s', 'activities': 0},
])
def test_low_progress_six_days_before_deadline_never_receives_congratulations(learner, delta):
    _, training, person = learner
    training.update(aps_remote_start='2026-11-03', aps_remote_end='2026-11-15', aps_in_person_start='2026-11-16')
    report = {**daily.read_summary(host, training, person), 'overall_percent': 16.5,
              'remaining_seconds': 50 * 3600 + 43 * 60 + 43, 'active_seconds': 52513,
              'active_time_label': '14 h 35 min 13 s'}
    peers = {str(i): {**report, 'overall_percent': value, 'complete': value == 100}
             for i, value in enumerate((100, 100, 80, 85))}
    with patch.object(daily, 'progress_since_yesterday', return_value=delta):
        content = daily.message(host, training, person, report, dt.date(2026, 11, 10), cohort=peers)
    assert content['tone'] == 'critical' and 'ALERTE CRITIQUE' in content['subject']
    for body in (content['html'], content['text']):
        assert '16,5 %' in body and '50 h 43 min 43 s' in body
        assert '6 jours, aujourd’hui inclus' in body and 'plus de 8 heures par jour' in body
        assert '15/11/2026' in body and '16/11/2026' in body
        assert '2 ont validé leur parcours à 100 % et 2 autres ont atteint au moins 80 %' in body
        assert 'progression médiane est de 92,5 %' in body
        assert 'contactez-nous dès aujourd’hui' in body
        assert not any(praise in body.lower() for praise in ('bravo', 'félicitations', 'belle avancée', 'chaque étape compte'))
    if delta and delta['advanced']:
        assert 'ne suffit pas à lever l’alerte' in content['text']
        assert '01 h 06 min 26 s' in content['text']
        assert content['html'].index('Vous avez pris du retard') < content['html'].index('Depuis le point d’hier')
        assert 'background:#eaf7f0' not in content['html']
    elif delta:
        assert 'Le délai se réduit sans que le travail restant diminue' in content['text']


@pytest.mark.parametrize('day,percent,hours,tone', [
    ('2026-11-03', 0, 62, 'steady'),  # First day is not automatically a failure.
    ('2026-11-10', 80, 10, 'advanced'),
    ('2026-11-10', 60, 25, 'steady'),  # A planned intensive pace is not a delay.
    ('2026-11-10', 16.5, 30, 'urgent'),
    ('2026-11-10', 16.5, 51, 'critical'),
    ('2026-11-14', 80, 8, 'urgent'),
    ('2026-11-14', 95, 20, 'critical'),  # Activities alone cannot hide hours owed.
    ('2026-11-15', 99.9, 0, 'urgent'),  # Still incomplete on the final day.
    ('2026-11-16', 99.9, 0, 'critical'),
])
def test_tone_reflects_deadline_and_hours_even_with_high_activity_progress(learner, day, percent, hours, tone):
    _, training, person = learner
    training.update(aps_remote_start='2026-11-03', aps_remote_end='2026-11-15', aps_in_person_start='2026-11-16')
    report = {**daily.read_summary(host, training, person), 'overall_percent': percent, 'remaining_seconds': hours * 3600}
    content = daily.message(host, training, person, report, dt.date.fromisoformat(day))
    assert content['tone'] == tone
    if tone in ('behind', 'urgent', 'critical'):
        assert 'Bravo' not in content['text'] and 'Félicitations' not in content['text']


def test_earlier_remote_deadline_is_respected_and_missing_dates_are_not_invented(learner):
    _, training, person = learner
    report = daily.read_summary(host, training, person)
    training.update(aps_remote_end='2026-11-12', aps_in_person_start='2026-11-16')
    state = daily.assessment(training, report, dt.date(2026, 11, 10))
    assert state['days'] == 3 and state['deadline'] == dt.date(2026, 11, 12)
    content = daily.message(host, training, person, report, dt.date(2026, 11, 13))
    assert 'L’échéance est dépassée' in content['html']
    assert 'Il reste 1 jour' not in content['text']
    training['aps_remote_end'] = '2026-11-30'
    assert daily.assessment(training, report, dt.date(2026, 11, 10))['deadline'] == dt.date(2026, 11, 15)
    training.update(aps_remote_end='', aps_in_person_start='')
    content = daily.message(host, training, person, report, dt.date(2026, 11, 10))
    assert 'doit être confirmée' in content['text'] and 'Objectif indicatif par jour' not in content['text']
    assert content['tone'] == 'steady'


def test_short_future_session_does_not_alarm_before_access_opens(learner):
    _, training, person = learner
    report = daily.read_summary(host, training, person)
    training.update(aps_remote_start='2026-11-12', aps_remote_end='2026-11-12', aps_in_person_start='2026-11-13')
    content = daily.message(host, training, person, report, dt.date(2026, 11, 11))
    assert content['tone'] == 'steady' and 'ALERTE' not in content['subject']
    assert 'La période de formation n’a pas encore commencé' in content['text']
    assert 'Objectif indicatif par jour' not in content['text']


def test_cohort_is_anonymous_comparable_and_excludes_self_unavailable_and_cancelled(learner):
    _, training, person = learner
    report = {**daily.read_summary(host, training, person), 'overall_percent': 50, 'remaining_seconds': 3600}
    for key in ('finished', 'advanced', 'middle', 'cancelled', 'unavailable', 'different', 'failed'):
        training['trainees'].append({**person, 'id': key, 'first_name': 'PRIVATE-' + key,
                                     'registration_cancelled': key == 'cancelled'})
    reports = {
        person['id']: report,
        'finished': {**report, 'complete': True, 'overall_percent': 100},
        'advanced': {**report, 'overall_percent': 80},
        'middle': {**report, 'overall_percent': 70},
        'unavailable': {**report, 'available': False, 'overall_percent': 0},
        'different': {**report, 'versions': ['other-version'], 'overall_percent': 0},
    }
    def read(_host, _training, peer, **kwargs):
        if peer['id'] == 'failed':
            raise sqlite3.OperationalError('temporary read failure')
        return reports[peer['id']]
    with patch.object(daily, 'read_summary', side_effect=read) as read_mock:
        cohort = daily.cohort_reports(host, training, NOW.date())
    assert read_mock.call_count == 7
    assert 'cancelled' not in cohort and 'failed' not in cohort
    assert daily.cohort_comparison(cohort, person, report) == {'count': 3, 'median': 80, 'completed': 1, 'advanced': 1}
    content = daily.message(host, training, person, report, NOW.date(), cohort=cohort)
    assert content['tone'] == 'behind'
    for body in (content['html'], content['text']):
        assert '3 autres stagiaires' in body and 'progression médiane est de 80 %' in body
        assert 'PRIVATE-' not in body and person['email'] not in body
    cohort.pop('middle')
    assert daily.cohort_comparison(cohort, person, report) is None
    assert 'Où en est votre groupe' not in daily.message(host, training, person, report, NOW.date(), cohort=cohort)['text']


def test_group_cannot_downgrade_a_deadline_alert_or_alarm_a_completed_learner(learner):
    _, training, person = learner
    report = {**daily.read_summary(host, training, person), 'overall_percent': 40}
    peers = {str(i): {**report, 'overall_percent': 0} for i in range(3)}
    day = dt.date(2026, 11, 29)
    assert daily.message(host, training, person, report, day, cohort=peers)['tone'] == 'critical'
    report.update(complete=True, overall_percent=100, remaining_seconds=0)
    content = daily.message(host, training, person, report, day, cohort=peers)
    assert content['tone'] == 'complete' and 'ALERTE' not in content['subject']
    assert 'Félicitations' in content['text'] and 'aucun rattrapage' in content['text']
    assert 'Où en est votre groupe' not in content['text']


def test_preview_and_dispatch_use_same_cohort_once_and_preserve_sent_snapshot(learner):
    case, training, person = learner
    report = {**daily.read_summary(host, training, person), 'overall_percent': 50, 'remaining_seconds': 3600}
    for i in range(3):
        training['trainees'].append({**person, 'id': 'peer-' + str(i), 'first_name': 'Peer',
                                     'email': f'peer-{i}@example.test'})
    def read(_host, _training, peer, **kwargs):
        return report if peer['id'] == person['id'] else {**report, 'overall_percent': 80}
    with patch.object(daily, 'read_summary', side_effect=read) as read_mock, \
         patch.object(daily, 'clock', return_value=NOW), \
         patch.object(host, 'brevo_send_email', return_value={'ok': True}) as send:
        preview = case.client.get(case.report_url + '/mail-du-jour')
        assert preview.status_code == 200 and '3 autres stagiaires' in preview.text
        assert read_mock.call_count == 4
        send.assert_not_called()
        read_mock.reset_mock()
        assert daily.run(host, now=NOW)['sent'] == 4
        assert read_mock.call_count == 4  # One report per person, not N squared.
        assert send.call_args_list[0].args[2] == preview.text
        report.update(overall_percent=100, complete=True, remaining_seconds=0)
        assert case.client.get(case.report_url + '/mail-du-jour').text == preview.text
        assert daily.run(host, now=NOW)['sent'] == 0
        assert send.call_count == 4


def test_unavailable_report_cannot_generate_alarm_or_a_delivery(learner):
    _, training, person = learner
    report = {**daily.read_summary(host, training, person), 'available': False, 'overall_percent': None}
    with pytest.raises(ValueError):
        daily.message(host, training, person, report, NOW.date())
    with patch.object(daily, 'read_summary', return_value=report), patch.object(host, 'brevo_send_email') as send:
        result = daily.run(host, now=NOW)
    assert result['failed'] == 1 and result['sent'] == 0
    assert not daily.ledger_path(host).exists()
    send.assert_not_called()
