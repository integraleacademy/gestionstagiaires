import copy
import json
import time
from unittest.mock import patch

import pytest

from elearning_native import a3p, mac_aps, vtc
from elearning_native.content_audit import audit_catalog, audit_course
from elearning_native.lesson_timing import first_pending, lesson_pages
from elearning_native.paths import project_course
from elearning_native.store import NativeElearningStore
from elearning_native.videos import course_videos
from tests.shared_reader_fixtures import published_media_inventory, reader_fixtures
from tests import test_native_elearning_web as web_tests


def test_all_lessons_have_stable_server_plans_without_mutating_courses():
    fixtures = reader_fixtures()
    assert len(fixtures) == 28 + 198 + 96
    for row in fixtures:
        assert len(row['plan']) >= 2, row['id']
        assert len({p['id'] for p in row['plan']}) == len(row['plan']), row['id']
        assert all(p['required_seconds'] in (0, 60, 120, 300) for p in row['plan'])
    course = mac_aps.load_bundled_course('academy-macaps-02')
    before = copy.deepcopy(course)
    for activity in course['sections'][0]['activities']:
        lesson_pages(course, activity)
    assert course == before


def test_video_page_requires_confirmed_viewing_before_next_page():
    pages = [{'id': 'video', 'required_seconds': 0, 'video_id': 'clip'},
             {'id': 'reading', 'required_seconds': 60}]
    assert first_pending(pages, {}, {}) == 0
    assert first_pending(pages, {}, {'clip': {'completed': True}}) == 1
    assert first_pending(pages, {'reading': 60}, {'clip': {'completed': True}}) == 2


def test_audit_exposes_a3p_content_gap_and_excludes_presentiel():
    course = a3p.load_bundled_course('academy-a3p-06', a3p.previous.VERSION)
    course = project_course(course, {'required_minutes': course['required_minutes']})
    report = audit_course(course)
    assert report['required_minutes'] == 3720
    assert report['lessons'] == 18
    assert report['missing_plans'] == 72
    assert report['reading_high'] < 150
    assert report['countdown_minutes'] < 200
    assert report['video_minutes'] == 0
    assert report['priority'] == 'Enrichissement et calibrage nécessaires'
    assert all(s['delivery'] == 'distance' for s in course['sections'])


@pytest.fixture
def case():
    instance = web_tests.NativeElearningWebTests(methodName='runTest')
    instance.setUp()
    try:
        with published_media_inventory():
            yield instance
    finally:
        instance.tearDown()


@pytest.mark.parametrize('provider,course_id,training', [
    (mac_aps, 'academy-macaps-02', 'MAC APS'), (a3p, 'academy-a3p-02', 'A3P'),
    (vtc, 'academy-vtc-a', 'VTC')])
def test_real_learners_cannot_skip_reading_or_validate_early_and_can_resume(case, provider, course_id, training):
    course = provider.load_bundled_course(course_id, a3p.enriched.VERSION) if training == 'A3P' else provider.load_bundled_course(course_id)
    case.data['sessions'][0].update(training_type=training, aps_native_modules=[{
        'course_id': course['id'], 'course_version': course['version'], 'required_minutes': course['required_minutes']}])
    case._public_login()
    url = '/espace/public-token/elearning/' + course_id
    config = case._player_config(case.client.get(url))
    pages = config['lessonPages']
    assert pages
    assert case._api_post(config['completeUrl'], config).status_code == 409
    now = time.time()
    with patch('elearning_native.store.time.time', side_effect=lambda: now):
        tracking = case._api_post(config['startUrl'], config, tab_id='reader', activity_id=config['activityId']).json['tracking_session_id']

        def tick(page):
            return case._api_post(config['heartbeatUrl'], config, tracking_session_id=tracking,
                activity_id=config['activityId'], lesson_page_id=page['id'], visible=True,
                focused=True, recent_activity=True, media_playing=False)

        assert tick(pages[-1]).status_code == 409
        # An optional explainer adds no artificial waiting time. Required VTC
        # viewing cannot be replaced by a reading timer or a forged page jump.
        if pages[0].get('video_id'):
            assert tick(pages[1]).status_code == 409
            # Seed previously earned viewing to isolate the reading control.
            # The separate video tracking suite verifies how these records are earned.
            videos = course_videos(course)[config['activityId']]
            viewed = {config['activityId']: {vid: {'completed': True, 'duration_seconds': seconds,
                'watched_seconds': seconds, 'max_position': seconds} for vid, seconds in videos.items()}}
            store = NativeElearningStore(case.persist_dir / 'native_elearning/tracking.sqlite3')
            with store._transaction() as connection:
                connection.execute('UPDATE learner_course_progress SET video_progress_json=?', (json.dumps(viewed),))
        page = next(p for p in pages if p['required_seconds'])
        assert tick(page).status_code == 200
        now += 15
        assert tick(page).status_code == 200
        resumed = case._player_config(case.client.get(url))
        assert resumed['initialLessonSeconds'][page['id']] == 15
        assert case._api_post(config['completeUrl'], config).status_code == 409
        for item in pages:
            if not item['required_seconds']:
                continue
            assert tick(item).status_code == 200
            remaining = item['required_seconds'] - (15 if item['id'] == page['id'] else 0)
            for _ in range(remaining // 15):
                now += 15
                assert tick(item).status_code == 200
        completed = case._api_post(config['completeUrl'], config)
        assert completed.status_code == 200
        assert config['activityId'] in completed.json['progress']['completed_activity_ids']
        review = case._player_config(case.client.get(url, query_string={'activity': config['activityId']}))
        assert review['activityCompleted']


def test_finished_legacy_activity_is_not_reset(case):
    course = mac_aps.load_bundled_course('academy-macaps-02', mac_aps.LEGACY_VERSION)
    case.data['sessions'][0].update(training_type='MAC APS', aps_native_modules=[{
        'course_id': course['id'], 'course_version': course['version'], 'required_minutes': course['required_minutes']}])
    case._public_login()
    url = '/espace/public-token/elearning/' + course['id']
    config = case._player_config(case.client.get(url))
    access = {'session_id': 'session-aps', 'trainee_id': 'trainee-1',
              'course_id': course['id'], 'course_version': course['version']}
    store = NativeElearningStore(case.persist_dir / 'native_elearning/tracking.sqlite3')
    store.complete_activity(access, config['activityId'], activity_order=course['activity_order'],
                            scored_activity_ids=[], mastery_score=80)
    review = case._player_config(case.client.get(url, query_string={'activity': config['activityId']}))
    assert review['activityCompleted']
    assert review['initialLessonSeconds'] == {}


def test_preview_is_free_and_audit_is_admin_only(case):
    audit_url = '/admin/elearning/calibrage/contenus'
    assert case.client.get(audit_url).status_code == 302
    case._admin_login()
    for cid in ('academy-macaps-02', 'academy-a3p-02', 'academy-vtc-a'):
        with patch('elearning_native.web.NativeElearningStore', side_effect=AssertionError('Preview must not track')):
            page = case.client.get('/admin/elearning/courses/' + cid + '/preview', query_string={'activity':'a3p-v4-ii-01-01-cours'} if cid.startswith('academy-a3p-') else {})
        assert page.status_code == 200
        assert 'nativeElearningConfig' not in page.text
        assert 'data-aps-lesson-page' in page.text
    audit_catalog.cache_clear()
    response = case.client.get(audit_url)
    assert response.status_code == 200
    assert 'Essais apprenants à réaliser' in response.text
    assert '157 h 30 prévues' in response.text
    assert len(audit_catalog()) == 34
    assert not (case.persist_dir / 'native_elearning/tracking.sqlite3').exists()
