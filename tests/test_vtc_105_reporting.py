"""Real curriculum transition, with one ledger of actual time in OF reports."""
import copy
import io
import json
import sqlite3
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

from elearning_native import vtc
from elearning_native.paths import project_course
from elearning_native.store import NativeElearningStore
from elearning_native.vtc_105_migration import resolve_session
from elearning_native.vtc_productions import BASE_VERSION, VERSION, MODULE_MINUTES
from elearning_native.videos import course_videos
from elearning_reporting import ProgressReader, certificate_pdf


def full_order():
    modules = []
    for letter in 'abcdefgh':
        course = vtc.load_bundled_course('academy-vtc-' + letter, BASE_VERSION)
        modules.append({'course_id': course['id'], 'course_version': BASE_VERSION,
                        'title': course['title'], 'section_ids': [s['id'] for s in course['sections']],
                        'required_minutes': course['planned_minutes']})
    return {'id': 'purchase-105', 'course_code': 'vtc', 'modules': modules}


def virtual_session(order):
    return {'id': 'el-' + order['id'], 'training_type': 'VTC',
            'aps_native_path_title': 'Mon parcours VTC', 'aps_native_modules': order['modules']}


def track(store, access, epoch):
    tracking = store.start_tracking(access, tab_id='tab-' + str(epoch), activity_id='vtc-a-capsule', now_epoch=epoch)
    for at in (epoch, epoch + 15, epoch + 30):
        store.heartbeat(access, tracking['tracking_session_id'], activity_id='vtc-a-capsule',
                        visible=True, focused=True, recent_activity=True, media_playing=False, now_epoch=at)


def test_real_105_hour_transition_preserves_time_and_connections_in_read_only_report(tmp_path):
    order, person = full_order(), {'id': 'learner-105'}
    original = copy.deepcopy(order)
    root = tmp_path / 'native_elearning'
    store = NativeElearningStore(root / 'tracking.sqlite3')
    access = {'session_id': 'el-' + order['id'], 'trainee_id': person['id'],
              'course_id': 'academy-vtc-a', 'course_version': BASE_VERSION}
    track(store, access, 1000)
    view = resolve_session(virtual_session(order), person, store)
    assert {m['course_version'] for m in view['aps_native_modules']} == {VERSION}
    assert sum(m['required_minutes'] for m in view['aps_native_modules']) == 6300
    track(store, {**access, 'course_version': VERSION}, 2000)
    track(store, {**access, 'trainee_id': 'another-learner'}, 3000)
    track(store, {**access, 'course_version': 'unassigned-edition'}, 4000)
    with store._connect() as db:
        before = db.execute('SELECT COUNT(*) FROM learner_course_progress').fetchone()[0]
        connections = db.execute('SELECT COUNT(*) FROM tracking_sessions').fetchone()[0]
    report = ProgressReader(SimpleNamespace(PERSIST_DIR=str(tmp_path))).report(order, person)
    assert order == original
    assert report['available'] is True
    assert report['required_seconds'] == 105 * 3600
    assert report['active_seconds'] == 60
    assert report['total_activities'] == 8 * 42
    assert report['optional_activity_count'] == 32
    assert report['completed_activities'] == 0
    assert report['complete'] is False
    assert len(report['connections']) == 2
    assert sum(c['credited_seconds'] for c in report['connections']) == 60
    assert {m['version'] for m in report['modules']} == {VERSION}
    with store._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM learner_course_progress').fetchone()[0] == before
        assert db.execute('SELECT COUNT(*) FROM tracking_sessions').fetchone()[0] == connections


def test_unopened_report_does_not_create_database_or_migrate_purchased_path(tmp_path):
    order = full_order()
    report = ProgressReader(SimpleNamespace(PERSIST_DIR=str(tmp_path))).report(order, {'id': 'not-opened'})
    assert not (tmp_path / 'native_elearning' / 'tracking.sqlite3').exists()
    assert {m['version'] for m in report['modules']} == {BASE_VERSION}
    assert report['active_seconds'] == 0


def test_105_hour_assignments_enforce_work_minutes_without_crediting_time():
    for letter, minutes in MODULE_MINUTES.items():
        course = vtc.load_bundled_course('academy-vtc-' + letter.lower(), VERSION)
        selection = {'course_id': course['id'], 'course_version': VERSION,
                     'section_ids': [s['id'] for s in course['sections']], 'required_minutes': 1}
        assert project_course(course, selection)['required_minutes'] == minutes


@pytest.mark.parametrize(('optional_state', 'remaining_seconds'), [
    ('missing', 0), ('saved', 60), ('completed', 0),
])
def test_optional_vtc_productions_keep_evidence_but_do_not_count_toward_completion(
        tmp_path, optional_state, remaining_seconds):
    """Read the real eight-module curriculum against historical ledger evidence."""
    order = full_order()
    for assignment in order['modules']:
        assignment['course_version'] = VERSION
        assignment['required_minutes'] = MODULE_MINUTES[assignment['course_id'][-1].upper()]
    person = {'id': 'learner-optional', 'first_name': 'Camille', 'last_name': 'Martin',
              'email': 'camille@example.test'}
    store = NativeElearningStore(tmp_path / 'native_elearning' / 'tracking.sqlite3')
    optional_titles, saved_work = [], {}
    for index, assignment in enumerate(order['modules']):
        course = vtc.load_bundled_course(assignment['course_id'], VERSION)
        activities = [a for section in course['sections'] for a in section['activities']]
        productions = [a for a in activities if a.get('optional') is True]
        assert len(productions) == 4
        optional_titles.extend(a['title'] for a in productions)
        completed = [a['id'] for a in activities if a.get('optional') is not True]
        answers = {a['id']: {'correct': True} for a in activities if a.get('scored')}
        for activity in productions:
            if optional_state == 'missing':
                continue
            fields = activity['production']['response_fields']
            answers[activity['id']] = {
                'production_answers': {f['id']: 'Ma réponse conservée : ' + f['label'] for f in fields},
                'production_first_answers': {f['id']: 'Ma première réponse : ' + f['label'] for f in fields},
                'production_draft': optional_state == 'saved',
                'production_ai_feedback': {'score': 4 if optional_state == 'saved' else 16,
                                           'max_score': 20, 'needs_human_review': optional_state == 'saved'},
                'production_self_review': {activity['production']['rubric'][0]['id']: 'needs_help'},
            }
            saved_work[activity['title']] = answers[activity['id']]
            if optional_state == 'completed':
                completed.append(activity['id'])
        videos = {activity_id: {video_id: {'duration_seconds': duration, 'watched_seconds': duration,
                                         'completed': True} for video_id, duration in requirements.items()}
                  for activity_id, requirements in course_videos(course).items()}
        access = {'session_id': 'el-' + order['id'], 'trainee_id': person['id'],
                  'course_id': course['id'], 'course_version': VERSION}
        store.get_progress(access)
        active_seconds = assignment['required_minutes'] * 60 - (remaining_seconds if index == 0 else 0)
        with store._connect() as db:
            db.execute('''UPDATE learner_course_progress SET completed_json=?, answers_json=?,
                video_progress_json=?, active_seconds=?, started_at=?, updated_at=?
                WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?''',
                (json.dumps(completed), json.dumps(answers), json.dumps(videos), active_seconds,
                 '2026-10-01T08:00:00Z', '2026-10-12T12:00:00Z', *store._key_values(access)))
    with store._connect() as db:
        before = list(db.iterdump())

    reader = ProgressReader(SimpleNamespace(PERSIST_DIR=str(tmp_path)))
    report = reader.report(order, person)
    assert report['available'] is True
    assert report['total_activities'] == report['completed_activities'] == 336
    assert report['optional_activity_count'] == 32
    assert report['progress_percent'] == 100
    assert report['required_seconds'] == 105 * 3600
    assert report['active_seconds'] == 105 * 3600 - remaining_seconds
    assert report['complete'] is (remaining_seconds == 0)
    assert report['completed_modules'] == (7 if remaining_seconds else 8)
    assert report['modules'][0]['status'] == ('awaiting_time' if remaining_seconds else 'passed')

    reported_work = []
    for module in report['modules']:
        assert module['total_activities'] == module['completed_activities'] == 42
        assert module['optional_activity_count'] == 4
        assert module['progress_percent'] == 100
        assert module['score_percent'] == (100 if module['total_questions'] else None)
        assert module['completed_videos'] == module['total_videos']
        for section in module['sections']:
            required_rows = [row for row in section['activities'] if not row['optional']]
            optional_rows = [row for row in section['activities'] if row['optional']]
            assert section['completed'] == section['total'] == len(required_rows)
            assert section['optional_activity_count'] == len(optional_rows)
            reported_work.extend(optional_rows)
    assert [row['title'] for row in reported_work] == optional_titles
    for row in reported_work:
        assert row['completed'] is (optional_state == 'completed')
        if optional_state == 'missing':
            assert 'production' not in row
            continue
        saved = saved_work[row['title']]
        work = row['production']
        assert [field['text'] for field in work['responses']] == list(saved['production_answers'].values())
        assert [field['text'] for field in work['first_responses']] == list(saved['production_first_answers'].values())
        assert work['ai_feedback'] == saved['production_ai_feedback']
        assert work['draft'] is saved['production_draft']
        assert work['review'][0]['needs_help'] is True

    compact = reader.report(order, person, detailed=False)
    for key in ('progress_percent', 'total_activities', 'completed_activities', 'optional_activity_count',
                'complete', 'completed_modules', 'required_seconds', 'active_seconds'):
        assert compact[key] == report[key]
    if optional_state == 'missing':
        document = PdfReader(io.BytesIO(certificate_pdf(report, {'name': 'Centre VTC exemple'}, order, person)))
        text = '\n'.join(page.extract_text() for page in document.pages)
        assert 'Parcours e-learning terminé' in text
        assert '336 / 336' in text and '105 h 00 min 00 s' in text
        assert 'ACTIVITÉS OBLIGATOIRES TERMINÉES' in text
    with store._connect() as db:
        assert list(db.iterdump()) == before
