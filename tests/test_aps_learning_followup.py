import concurrent.futures
import copy
import datetime as dt
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
        training['date_start'] = '2026-10-31'
        page = case.client.get('/admin/sessions/session-aps/trainees')
        assert page.status_code == 200 and 'data-aps-roster-trainee=' not in page.text


def test_only_completed_activity_and_required_time_get_the_blue_validation():
    person = {'id': 'p'}
    report = {'available': True, 'complete': False, 'progress_percent': 100, 'modules': [], 'remaining_seconds': 60}
    assert daily.summary(report, person, set())['overall_percent'] == 99.9
    assert not daily.summary(report, person, set())['complete']
    report.update(complete=True, remaining_seconds=0)
    assert daily.summary(report, person, set())['overall_percent'] == 100
    report['available'] = False
    assert not daily.summary(report, person, set())['complete']


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
    assert not daily.ledger_path(host).exists()
    send.assert_not_called()
    anonymous = host.app.test_client()
    assert anonymous.get(case.report_url + '/mail-du-jour').status_code == 302
    with case.client.session_transaction() as auth:
        auth.update(admin_role='partner_admin', partner_id='other')
    assert case.client.get(case.report_url + '/mail-du-jour').status_code == 404
    assert case.client.get('/admin/sessions/session-aps/e-learning/aps-resume').status_code == 404


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
    assert early['tone'] == 'behind' and advanced['tone'] == 'advanced' and complete['tone'] == 'complete'
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
