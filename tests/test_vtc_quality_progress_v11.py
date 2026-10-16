"""A media repair preserves earned results without allowing forged completion."""
import copy
import json
import sqlite3
import time
from unittest.mock import patch

import pytest

from elearning_native.vtc_video_quality import compatible_record, compatible_progress
from elearning_native.videos import videos_complete
from tests import test_native_elearning_web as web_tests

VID = 'vtc-a-01-explanation-v10'
ROW = {'duration_seconds': 12., 'previous_duration_seconds': 10.,
       'previous_chapters': [{'start_seconds': 0., 'end_seconds': 5.}, {'start_seconds': 5., 'end_seconds': 10.}],
       'chapters': [{'start_seconds': 0., 'end_seconds': 7.}, {'start_seconds': 7., 'end_seconds': 12.}]}
DATA = {'lessons': {'A.01': ROW}, 'modules': {}}


@pytest.fixture
def revision():
    with patch('elearning_native.vtc_video_quality.quality_manifest', return_value=DATA), \
            patch('elearning_native.vtc_video_quality.approved_voice_updates', return_value={}):
        yield


def test_completed_predecessor_stays_complete_without_touching_saved_record(revision):
    record = dict(duration_seconds=10., watched_seconds=10., completed=True, completed_at='2026-10-10')
    frozen = copy.deepcopy(record)
    assert videos_complete({VID: record}, {VID: 12.})
    repaired = compatible_record(VID, record, 12.)
    assert repaired == dict(duration_seconds=12., watched_seconds=12., completed=True, completed_at='2026-10-10')
    assert record == frozen


@pytest.mark.parametrize('frontier,expected', [(0, 0), (2.5, 3.5), (5, 7), (7.5, 9.5), (10, 11.5)])
def test_unfinished_prefix_maps_inside_its_chapter_without_granting_completion(revision, frontier, expected):
    record = dict(duration_seconds=10., watched_seconds=frontier, completed=False)
    result = compatible_record(VID, record, 12.)
    assert result['watched_seconds'] == expected
    assert not result['completed']
    assert not videos_complete({VID: record}, {VID: 12.})


@pytest.mark.parametrize('id,duration,record', [
    ('unrelated-video', 12., dict(duration_seconds=10., watched_seconds=10., completed=True)),
    (VID, 13., dict(duration_seconds=10., watched_seconds=10., completed=True)),
    (VID, 12., dict(duration_seconds=9., watched_seconds=9., completed=True)),
    (VID, 12., dict(duration_seconds=10., watched_seconds=3., completed=True)),
    (VID, 12., dict(duration_seconds=10., watched_seconds=float('nan'), completed=True)),
    (VID, 12., dict(duration_seconds=10., watched_seconds=99., completed=True)),
])
def test_unknown_timelines_and_invalid_completion_cannot_unlock(revision, id, duration, record):
    assert not videos_complete({id: record}, {id: duration})


def test_projection_does_not_mutate_training_time_or_other_records(revision):
    saved = {'a': {VID: dict(duration_seconds=10., watched_seconds=5., completed=False), 'other': {'untouched': True}}}
    frozen = copy.deepcopy(saved)
    result = compatible_progress(saved, {'a': {VID: 12.}})
    assert result['a'][VID]['watched_seconds'] == 7.
    assert result['a']['other'] == frozen['a']['other']
    assert saved == frozen


@pytest.mark.parametrize('completed', [False, True])
def test_actual_api_reload_and_receipts_preserve_earned_progress_without_extra_time(revision, completed):
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    try:
        path = case.persist_dir/'native_elearning/courses'/case.course['id']/case.course['version']/'course.json'
        course = json.loads(path.read_text())
        course['settings']['force_navigation'] = False
        course['sections'][0]['activities'][0]['blocks'].insert(0, {
            'id': VID, 'type': 'video', 'video': {'id': VID, 'src': 'media/test.mp4', 'required': True, 'duration_seconds': 12.}})
        path.write_text(json.dumps(course))
        case._public_login()
        url = f"/espace/public-token/elearning/{case.course['id']}"
        case._player_config(case.client.get(url))
        historical = {'content-1': {VID: dict(duration_seconds=10., watched_seconds=10. if completed else 5., completed=completed,
                                             completed_at='2026-10-10' if completed else None)}}
        with sqlite3.connect(case.persist_dir/'native_elearning/tracking.sqlite3') as c:
            c.execute('UPDATE learner_course_progress SET video_progress_json = ?, active_seconds = 123', (json.dumps(historical),))
        config = case._player_config(case.client.get(url))
        initial = config['initialVideoProgress']['content-1'][VID]
        position = 12. if completed else 7.
        assert initial['watched_seconds'] == position
        assert initial['completed'] is completed
        now = [time.time()]
        with patch('elearning_native.store.time.time', side_effect=lambda: now[0]):
            tracking = case._api_post(config['startUrl'], config, activity_id='content-1', tab_id='repair').get_json()['tracking_session_id']
            def ping(pos, seconds, ended=False):
                now[0] += seconds
                return case._api_post(config['heartbeatUrl'], config, tracking_session_id=tracking, activity_id='content-1',
                    visible=True, focused=True, recent_activity=True, media_playing=not ended,
                    videos=[dict(id=VID, position=pos, playing=not ended, ended=ended, rate=1)]).get_json()
            start = ping(position, 0, completed)
            assert start['progress']['active_seconds'] == 123
            assert start['progress']['video_progress']['content-1'][VID]['watched_seconds'] == position
            if not completed:
                rejected = ping(12., 1, True)
                assert not rejected['progress']['video_progress']['content-1'][VID]['completed']
                assert rejected['video_resync'][VID] <= 8.
            else:
                assert start['progress']['video_progress']['content-1'][VID]['completed']
        reloaded = case._player_config(case.client.get(url))
        assert reloaded['initialVideoProgress']['content-1'][VID]['duration_seconds'] == 12.
    finally:
        case.tearDown()
