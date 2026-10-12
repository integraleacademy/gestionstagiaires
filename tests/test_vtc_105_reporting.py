"""Real curriculum transition, with one ledger of actual time in OF reports."""
import copy
import sqlite3
from types import SimpleNamespace

from elearning_native import vtc
from elearning_native.paths import project_course
from elearning_native.store import NativeElearningStore
from elearning_native.vtc_105_migration import resolve_session
from elearning_native.vtc_productions import BASE_VERSION, VERSION, MODULE_MINUTES
from elearning_reporting import ProgressReader


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
    assert report['total_activities'] == 8 * 46
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
