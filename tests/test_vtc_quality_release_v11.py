"""Current VTC media is complete, isolated and preserves earned results."""
import copy
import html
import json
import re
import sqlite3
import time
from unittest.mock import patch

import pytest

from elearning_native import vtc, vtc_video_quality as quality
from elearning_native.paths import project_progress
from elearning_native.videos import course_videos
from tests import test_native_elearning_web as web_tests


def videos(course):
    return {b['video']['id']: b['video'] for s in course['sections'] for a in s['activities']
            for b in a.get('blocks', []) if b.get('video')}


def test_equal_predecessor_duration_never_hides_a_changed_resume_timeline():
    data = quality.quality_manifest()
    for row in [*data['lessons'].values(), *data['modules'].values()]:
        if row['duration_seconds'] == row['previous_duration_seconds']:
            bounds = lambda chapters: [(c['start_seconds'], c['end_seconds']) for c in chapters]
            assert bounds(row['chapters']) == bounds(row['previous_chapters'])


@pytest.mark.parametrize('letter', list('abcdefgh'))
@pytest.mark.parametrize('version', sorted(quality.VERSIONS))
def test_current_media_preserves_obligations_and_completed_progress(letter, version):
    cid = 'academy-vtc-' + letter
    with patch.object(vtc, 'repair_video_quality', side_effect=lambda c: c):
        before = vtc.load_bundled_course(cid, version)
    after = vtc.load_bundled_course(cid, version)
    frozen = copy.deepcopy(after)
    prior, current = videos(before), videos(after)
    assert prior.keys() == current.keys()
    assert after['activity_order'] == before['activity_order']
    assert after['planned_minutes'] == before['planned_minutes']
    assert after['version'] == before['version']
    for vid, video in current.items():
        revision = 14 if vid == 'vtc-d-02-explanation-v10' else 11
        assert video['src'].startswith(f'media/vtc/v{revision}/')
        assert video['render_revision'] == revision
        assert video['required'] is prior[vid]['required']
        assert video['default_playback_rate'] == 1
        assert video['allowed_playback_rates'] == [1]
        assert len(video['presentation']['scenes']) == len(prior[vid]['chapters'])
        for key in ('src', 'poster', 'captions'):
            assert vtc.bundled_asset(cid, version, video[key])
            other = 'academy-vtc-' + ('b' if letter == 'a' else 'a')
            assert vtc.bundled_asset(other, version, video[key]) is None
            assert vtc.bundled_asset(cid, '20261006-vtc-v3-105h', video[key]) is None
    completed_at = '2026-10-10T14:00:00Z'
    saved = dict(completed_activity_ids=before['activity_order'], active_seconds=1234,
                 video_progress={aid: {vid: dict(completed=True, watched_seconds=d,
                      duration_seconds=d, completed_at=completed_at) for vid, d in required.items()}
                      for aid, required in course_videos(before).items()})
    old_saved = copy.deepcopy(saved)
    projected = project_progress(saved, after)
    assert projected['completed_activity_ids'] == before['activity_order']
    assert projected['active_seconds'] == 1234
    assert saved == old_saved
    for aid, required in course_videos(after).items():
        for vid, duration in required.items():
            record = projected['video_progress'][aid][vid]
            assert record['completed'] and record['duration_seconds'] == duration
            assert record['watched_seconds'] == duration and record['completed_at'] == completed_at
    assert quality.repair_course(after) == frozen
    assert vtc.load_bundled_course(cid, version) == frozen


@pytest.mark.parametrize('mutation', ['missing', 'revision', 'source', 'previous', 'chapter', 'scene', 'point', 'cue', 'pause', 'file'])
def test_quality_manifest_rejects_partial_or_mismatched_delivery(tmp_path, mutation):
    data = copy.deepcopy(quality.quality_manifest())
    assert len(data['lessons']) == 96 and len(data['modules']) == 8
    row = data['lessons']['A.01']
    if mutation == 'missing': del data['lessons']['H.12']
    elif mutation == 'revision': data['revision'] = 12
    elif mutation == 'source': row['source_sha256'] = '0' * 64
    elif mutation == 'previous': row['previous_duration_seconds'] += 1
    elif mutation == 'chapter': row['chapters'][0] = None
    elif mutation == 'scene': row['presentation']['scenes'][0] = None
    elif mutation == 'point': row['presentation']['scenes'][0]['points'][0] = None
    elif mutation == 'cue': row['presentation']['captions'][0]['start'] = float('nan')
    elif mutation == 'pause': row['learning_pauses'][0]['at_seconds'] = float('nan')
    elif mutation == 'file': row['src'] = 'media/vtc/v11/../v10/lesson-a-01.mp4'
    (tmp_path/'video_quality_v11.json').write_text(json.dumps(data))
    for name in ('lesson_videos_v10.json', 'video_pacing_v9.json'):
        (tmp_path/name).symlink_to(quality.ROOT/name)
    (tmp_path/'assets').symlink_to(quality.ROOT/'assets', target_is_directory=True)
    quality.quality_manifest.cache_clear()
    try:
        with patch.object(quality, 'ROOT', tmp_path), pytest.raises(ValueError, match='VTC quality'):
            quality.quality_manifest()
    finally:
        quality.quality_manifest.cache_clear()


@pytest.mark.parametrize('letter,activity', [('e', 'vtc-e-07-cours'), ('h', 'vtc-h-11-cours'), ('d', 'vtc-d-capsule')])
def test_real_preview_serves_revision_and_accessible_companion_without_tracking(letter, activity):
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    try:
        case._admin_login()
        with patch('elearning_native.web.NativeElearningStore', side_effect=AssertionError('Preview must not track')):
            page = case.client.get(f'/admin/elearning/courses/academy-vtc-{letter}/preview',
                    query_string=dict(version=vtc.REQUIRED_VERSION, activity=activity))
        assert page.status_code == 200
        body = page.get_data(as_text=True)
        assert 'data-vtc-video-reader' in body and 'Agrandir la lecture' in body
        assert 'Repères synchronisés avec la vidéo' in body
        assert 'data-playback-rate' not in body and 'data-video-pacing-config' in body
        url = html.unescape(re.search(r'<source src="([^"]+/media/vtc/v11/[^"]+)"', body)[1])
        media = case.client.get(url, headers={'Range': 'bytes=0-31'})
        assert media.status_code == 206 and len(media.data) == 32
        assert media.mimetype == 'video/mp4'
        with case.client.session_transaction() as session:
            session.clear()
        assert case.client.get(url).status_code in (401, 403)
        assert case.saved_data is None
    finally:
        case.tearDown()


def test_predeployment_tab_is_paused_for_reload_without_changing_saved_progress():
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    try:
        case.data['sessions'][0].update(training_type='VTC', aps_native_course_id='academy-vtc-a',
                                       aps_native_course_version=vtc.REQUIRED_VERSION)
        case._public_login()
        clock = [time.time()]
        with patch('elearning_native.store.time.time', side_effect=lambda: clock[0]):
            with patch.object(vtc, 'repair_video_quality', side_effect=lambda c: c):
                config = case._player_config(case.client.get('/espace/public-token/elearning/academy-vtc-a'))
                aid = config['activityId']
                vid, old_duration = next(iter(config['requiredVideos'].items()))
                tracking = case._api_post(config['startUrl'], config, activity_id=aid, tab_id='old-page').json['tracking_session_id']
                def ping(position):
                    return case._api_post(config['heartbeatUrl'], config, tracking_session_id=tracking,
                        activity_id=aid, visible=True, focused=True, recent_activity=True, media_playing=True,
                        videos=[dict(id=vid, position=position, rate=.85, playing=True, ended=False)])
                assert ping(0).status_code == 200
                clock[0] += 4
                assert ping(3.4).status_code == 200
            def saved():
                with sqlite3.connect(case.persist_dir/'native_elearning/tracking.sqlite3') as conn:
                    return conn.execute('SELECT video_progress_json, active_seconds FROM learner_course_progress').fetchone()
            before = saved()
            clock[0] += 4
            rejected = ping(6.8)
            assert rejected.status_code == 409
            assert 'Rechargez' in rejected.get_data(as_text=True)
            assert saved() == before
            finished = case._api_post(config['finishUrl'], config, activity_id=aid, tracking_session_id=tracking)
            assert finished.status_code == 200
            assert saved()[0] == before[0]  # No new viewing from the obsolete tab.
            # Closing the session may credit its usual bounded interactive tail;
            # the media migration itself never adds training time.
            after_finish = saved()
            assert before[1] <= after_finish[1] <= before[1] + 4
            fresh = case._player_config(case.client.get('/espace/public-token/elearning/academy-vtc-a'))
            expected = quality.compatible_record(vid, json.loads(before[0])[aid][vid], fresh['requiredVideos'][vid])
            assert fresh['initialVideoProgress'][aid][vid] == expected
            assert saved()[1] == after_finish[1]
            resumed = case._api_post(fresh['startUrl'], fresh, activity_id=aid, tab_id='reloaded-page')
            assert resumed.status_code == 200
            first_heartbeat = case._api_post(fresh['heartbeatUrl'], fresh,
                tracking_session_id=resumed.json['tracking_session_id'], activity_id=aid,
                visible=True, focused=True, recent_activity=True, media_playing=True,
                videos=[dict(id=vid, position=expected['watched_seconds'], rate=1, playing=True, ended=False)])
            assert first_heartbeat.status_code == 200
            assert not first_heartbeat.json['duplicate'] and first_heartbeat.json['active']
    finally:
        case.tearDown()
