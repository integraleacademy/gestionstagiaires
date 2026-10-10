"""Complete explainers, versioned obligations, access control and real learner API."""
import copy
import html
import json
import re
import time
from unittest.mock import patch

import pytest

import elearning_orders
from elearning_native import vtc, vtc_training_web
from elearning_native import vtc_lesson_videos as lessons
from elearning_native.paths import project_progress
from elearning_native.videos import activity_playback_policy, course_videos
from tests import test_native_elearning_web as web_tests


def activities(course):
    return [a for section in course['sections'] for a in section['activities']]


@pytest.mark.parametrize('letter', 'abcdefgh')
def test_complete_collection_is_additive_for_existing_and_required_for_new(letter):
    cid = 'academy-vtc-' + letter
    old = vtc.load_bundled_course(cid, lessons.COURSE_VERSION)
    new = vtc.load_bundled_course(cid)
    frozen = json.loads((vtc.ROOT/'courses'/cid/(lessons.COURSE_VERSION+'.json')).read_text())
    assert new['version'] == lessons.REQUIRED_VERSION
    assert len(course_videos(new)) == 13
    assert len(course_videos(old)) == 1
    assert new['activity_order'] == old['activity_order'] == frozen['activity_order']
    assert new['planned_minutes'] == old['planned_minutes'] == frozen['planned_minutes']
    for before, after in zip(activities(old), activities(new)):
        assert before['vtc'] == after['vtc']
        if before['vtc'].get('kind') != 'lesson':
            assert before == after
            continue
        v1, v2 = before['blocks'][0]['video'], after['blocks'][0]['video']
        assert v1['required'] is False and v2['required'] is True
        assert {**v1, 'required': True} == v2
        assert v2['default_playback_rate'] == .85
        assert len(v2['chapters']) in (4, 5)
        assert all(p['duration_seconds'] in (4, 5) for p in v2['learning_pauses'])
        assert activity_playback_policy(new, after['id'])[v2['id']]['rates'] == (.85, 1)
        assert not activity_playback_policy(old, before['id'])
        assert vtc.bundled_asset(cid, new['version'], v2['src'])
        other = 'b' if letter == 'a' else 'a'
        assert vtc.bundled_asset('academy-vtc-'+other, new['version'], v2['src']) is None
    saved = {'completed_activity_ids': old['activity_order'], 'active_seconds': 600,
             'video_progress': {aid: {vid: {'completed': True, 'duration_seconds': duration,
                                           'watched_seconds': duration}
                                      for vid, duration in requirements.items()}
                                for aid, requirements in course_videos(old).items()}}
    assert project_progress(saved, old)['completed_activity_ids'] == old['activity_order']
    assert len(project_progress(saved, new)['completed_activity_ids']) == len(new['activity_order']) - 12
    assert vtc._course(cid, lessons.COURSE_VERSION) == frozen
    assert lessons.enrich_lessons(copy.deepcopy(old)) == old


def test_new_registration_curriculum_and_associated_resources_use_complete_edition():
    assigned = elearning_orders.curriculum('vtc')
    assert len(assigned) == 8
    assert {m['course_version'] for m in assigned} == {lessons.REQUIRED_VERSION}
    manifest = vtc.curriculum_manifest()
    assert manifest['video_count'] == 104 and manifest['lesson_video_count'] == 96
    for module in manifest['modules']:
        course = vtc.load_bundled_course(module['id'])
        assert vtc_training_web._bank(course)['version'] == lessons.REQUIRED_VERSION
        assert vtc.load_exam(module['mock_exam_id'], lessons.REQUIRED_VERSION)['version'] == lessons.REQUIRED_VERSION
    assert len(vtc.load_exam('vtc-final', lessons.REQUIRED_VERSION)['questions']) == 100


@pytest.mark.parametrize('change', ['missing', 'stale', 'path', 'pause', 'chapter'])
def test_required_edition_fails_closed_if_media_is_incomplete_or_mismatched(change):
    manifest = copy.deepcopy(lessons.lesson_manifest())
    if change == 'missing': manifest.pop('A.01')
    elif change == 'stale': manifest['A.01']['source_sha256'] = '0'*64
    elif change == 'path': manifest['A.01']['src'] = 'media/vtc/v10/../outside.mp4'
    elif change == 'pause': manifest['A.01']['learning_pauses'][0] = None
    elif change == 'chapter': manifest['A.01']['chapters'][0]['start_seconds'] = -0.5
    with patch.object(lessons, 'lesson_manifest', return_value=manifest):
        with pytest.raises(ValueError, match='incomplete or stale'):
            vtc.load_bundled_course('academy-vtc-a', lessons.REQUIRED_VERSION)
        old = vtc.load_bundled_course('academy-vtc-a', lessons.COURSE_VERSION)
        assert len(course_videos(old)) == 1
        assert not activities(old)[0]['blocks']


@pytest.mark.parametrize('version,mandatory', [(lessons.COURSE_VERSION, False), (lessons.REQUIRED_VERSION, True)])
def test_actual_learner_page_enforces_only_assigned_video_and_serves_authorized_assets(version, mandatory):
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    try:
        case.data['sessions'][0].update(training_type='VTC', aps_native_course_id='academy-vtc-a',
                                       aps_native_course_version=version)
        case._public_login()
        page = case.client.get('/espace/public-token/elearning/academy-vtc-a')
        assert page.status_code == 200
        body = page.get_data(as_text=True)
        config = case._player_config(page)
        assert config['activityId'] == 'vtc-a-01-cours'
        assert bool(config['requiredVideos']) is mandatory
        assert 'Lire la transcription de cette leçon' in body and 'data-video-pacing-config' in body
        assert '0,85×' in body
        url = html.unescape(re.search(r'<source src="([^"]+lesson-a-01\.mp4[^"]*)"', body)[1])
        media = case.client.get(url, headers={'Range': 'bytes=0-31'})
        assert media.status_code == 206 and len(media.data) == 32
        complete = case._api_post(config['completeUrl'], config)
        assert complete.status_code == (409 if mandatory else 200)
        if mandatory:
            video_id, duration = next(iter(config['requiredVideos'].items()))
            clock = [time.time()]
            with patch('elearning_native.store.time.time', side_effect=lambda: clock[0]):
                tracking = case._api_post(config['startUrl'], config, activity_id=config['activityId'], tab_id='new-learner').json['tracking_session_id']
                def ping(position, playing=True, ended=False):
                    return case._api_post(config['heartbeatUrl'], config, tracking_session_id=tracking,
                        activity_id=config['activityId'], visible=True, focused=True, recent_activity=True,
                        media_playing=playing, videos=[dict(id=video_id, position=position, rate=.85,
                                                          playing=playing, ended=ended)])
                ping(0)
                clock[0] += 1
                forged = ping(duration, False, True)
                assert not forged.json['progress']['video_progress'][config['activityId']][video_id]['completed']
                ping(0)
                position = 0
                for pause in lessons.lesson_manifest()['A.01']['learning_pauses'] + [dict(at_seconds=duration, duration_seconds=0)]:
                    target = pause['at_seconds']
                    while position < target:
                        step = min(3.4, target-position)
                        clock[0] += step/.85
                        position = min(target, position+step)
                        response = ping(position, position < target, position == duration)
                        assert response.status_code == 200 and not response.json['video_resync']
                    clock[0] += pause['duration_seconds']
                    if position < duration: ping(position)
                assert response.json['progress']['video_progress'][config['activityId']][video_id]['completed']
                assert case._api_post(config['completeUrl'], config).status_code == 200
        with case.client.session_transaction() as session:
            session.clear()
        assert case.client.get(url).status_code in (401, 403)
    finally:
        case.tearDown()
