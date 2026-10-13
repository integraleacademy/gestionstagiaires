"""Natural narration, illustration delivery and earned viewing stay consistent."""
import copy
import html
import json
import re
import sqlite3
import time
from unittest.mock import patch

import pytest

from elearning_native import academy, aps_media
from elearning_native.video_compatibility import compatible_record, compatible_progress
from elearning_native.videos import videos_complete
from tests import test_native_elearning_web as web_tests

VID = 'aps62-01-01-video'
ROW = dict(duration_seconds=8.7, previous_duration_seconds=10., timeline_scale=.87)


@pytest.fixture
def revision():
    with patch.object(aps_media, 'natural_manifest', return_value={'aps62-01-01': ROW}):
        yield


@pytest.mark.parametrize('completed,frontier,expected,earned', [
    (True, 10, 8.7, True), (False, 5, 4.35, False), (False, 10, 8.2, False),
    (True, 3, 2.61, False), (False, 0, 0, False),
])
def test_only_earned_viewing_survives(revision, completed, frontier, expected, earned):
    record = dict(duration_seconds=10., watched_seconds=frontier, completed=completed,
                  completed_at='2026-10-12', active_seconds=123)
    frozen = copy.deepcopy(record)
    current = compatible_record(VID, record, 8.7)
    assert current['watched_seconds'] == expected
    assert current['completed'] is earned
    assert current['active_seconds'] == 123
    assert videos_complete({VID: record}, {VID: 8.7}) is earned
    assert record == frozen


@pytest.mark.parametrize('vid,duration,frontier,old_duration', [
    ('aps62-99-99-video', 8.7, 10, 10), (VID, 9, 10, 10),
    (VID, 8.7, 9, 9), (VID, 8.7, 99, 10), (VID, 8.7, float('nan'), 10),
])
def test_unknown_or_invalid_records_cannot_unlock(revision, vid, duration, frontier, old_duration):
    record = dict(duration_seconds=old_duration, watched_seconds=frontier, completed=True)
    assert not videos_complete({vid: record}, {vid: duration})


@pytest.mark.parametrize('completed', [False, True])
def test_api_reload_and_heartbeat_preserve_history_without_crediting_time(revision, completed):
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    try:
        path = case.persist_dir/'native_elearning/courses'/case.course['id']/case.course['version']/'course.json'
        course = json.loads(path.read_text())
        course['settings']['force_navigation'] = False
        course['sections'][0]['activities'][0]['blocks'].insert(0, {
            'id': VID, 'type': 'video', 'video': dict(id=VID, src='media/test.mp4', required=True, duration_seconds=8.7)})
        path.write_text(json.dumps(course))
        case._public_login()
        url = f"/espace/public-token/elearning/{case.course['id']}"
        case._player_config(case.client.get(url))
        history = {'content-1': {VID: dict(duration_seconds=10., watched_seconds=10. if completed else 5.,
                                           completed=completed, completed_at='2026-10-12' if completed else None)}}
        with sqlite3.connect(case.persist_dir/'native_elearning/tracking.sqlite3') as db:
            db.execute('UPDATE learner_course_progress SET video_progress_json=?, active_seconds=123', (json.dumps(history),))
        config = case._player_config(case.client.get(url))
        expected = 8.7 if completed else 4.35
        assert config['initialVideoProgress']['content-1'][VID]['watched_seconds'] == expected
        clock = [time.time()]
        with patch('elearning_native.store.time.time', side_effect=lambda: clock[0]):
            tracking = case._api_post(config['startUrl'], config, activity_id='content-1', tab_id='review').get_json()['tracking_session_id']
            def ping(position, elapsed, ended=False):
                clock[0] += elapsed
                return case._api_post(config['heartbeatUrl'], config, tracking_session_id=tracking, activity_id='content-1',
                    visible=True, focused=True, recent_activity=True, media_playing=not ended,
                    videos=[dict(id=VID, position=position, playing=not ended, ended=ended, rate=1)]).get_json()
            start = ping(expected, 0, completed)
            assert start['progress']['active_seconds'] == 123
            assert start['progress']['video_progress']['content-1'][VID]['completed'] is completed
            if not completed:
                attempted = ping(8.7, 1, True)
                assert not attempted['progress']['video_progress']['content-1'][VID]['completed']
                assert attempted['video_resync'][VID] <= 5.35
        reloaded = case._player_config(case.client.get(url))
        assert reloaded['initialVideoProgress']['content-1'][VID]['duration_seconds'] == 8.7
    finally:
        case.tearDown()


def test_all_current_lessons_have_three_distinct_scoped_scenes_and_original_text():
    count = 0
    for cid in academy.curriculum_ids():
        course = academy.load_bundled_course(cid)
        source = json.loads((academy.ROOT/'courses'/cid/(course['version']+'.json')).read_text())
        originals = {a['id']: a for s in source['sections'] for a in s['activities']}
        assert course['planned_minutes'] == source['planned_minutes']
        assert course['required_minutes'] == source['required_minutes']
        for section in course['sections']:
            for activity in section['activities']:
                lesson = activity.get('academy', {})
                if lesson.get('kind') != 'lesson':
                    continue
                count += 1
                illustrations = lesson['illustrations']
                assert set(illustrations) == {'action', 'reason', 'flow'}
                assert len({row['src'] for row in illustrations.values()}) == 3
                for row in illustrations.values():
                    assert row['alt'] and row['caption']
                    assert academy.bundled_asset(cid, course['version'], row['src'])
                for key in ('plain_course', 'reason', 'flow', 'lessons', 'visual_guide'):
                    assert lesson.get(key) == originals[activity['id']]['academy'].get(key)
    assert count == 62


def test_reviewed_manifest_is_complete_and_replaces_only_identical_narrations():
    manifest = aps_media.natural_manifest()
    assert len(manifest) == 62
    count = 0
    for cid in academy.curriculum_ids():
        course = academy.load_bundled_course(cid)
        for section in course['sections']:
            row = manifest[section['id']]
            for activity in section['activities']:
                for block in activity.get('blocks', []):
                    video = block.get('video', {})
                    if video.get('id') != section['id']+'-video':
                        continue
                    count += 1
                    assert video['src'] == row['src']
                    assert video['captions'] in course['assets']
                    assert video['voice'] == 'fr-FR-HenriNeural'
                    assert video['duration_seconds'] == row['duration_seconds']
                    assert video['required']
    assert count == 62


def test_illustrations_use_signed_assets_in_the_actual_player():
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    try:
        case._admin_login()
        response = case.client.get('/admin/elearning/courses/academy-aps62-01/preview',
                                   query_string={'activity':'aps62-01-01-comprendre'})
        assert response.status_code == 200
        assert response.text.count('class="aps-teaching-scene"') == 3
        source = html.unescape(re.search(r'data-aps-image="([^"]+/v13/illustrations/access.webp[^\"]*)"', response.text).group(1))
        assert case.client.get(source).status_code == 200
        assert case.client.get(source.split('?')[0]).status_code == 401
        assert case.client.get(source.replace('/academy-aps62-01/', '/academy-aps62-02/')).status_code == 403
    finally:
        case.tearDown()
