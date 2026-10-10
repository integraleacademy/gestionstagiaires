"""The bilingual audio repair must not reset learners or broaden media access."""
import copy
import html
import json
import re
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from elearning_native import vtc
from elearning_native.store import NativeElearningStore
from elearning_native.videos import course_videos, videos_complete
from tests import test_native_elearning_web as web_tests


COURSE = 'academy-vtc-e'
VERSIONS = ('20261007-vtc-v4-visuals', '20261007-vtc-v5-annales', '20261010-vtc-v6-pedagogie')
CAPSULE = 'vtc-e-capsule'
MEDIA = ('media/vtc/v7/lesson-e.mp4', 'media/vtc/v7/lesson-e.vtt')


def original(version, course_id=COURSE):
    return json.loads((vtc.ROOT / 'courses' / course_id / (version + '.json')).read_text())


def capsule(course):
    return next(a for s in course['sections'] for a in s['activities'] if a['id'] == CAPSULE)


@pytest.mark.parametrize('version', VERSIONS)
def test_repair_changes_media_only_without_modifying_frozen_course_or_cache(version):
    path = vtc.ROOT / 'courses' / COURSE / (version + '.json')
    frozen = path.read_bytes()
    frozen_course = original(version)
    before = vtc._repair_english_listening(copy.deepcopy(frozen_course))
    # Exercise the pronunciation layer independently of the later visual repair.
    repaired = vtc._repair_english_narration(copy.deepcopy(before))
    video = capsule(repaired)['blocks'][0]['video']
    previous = capsule(before)['blocks'][0]['video']
    assert (video['src'], video['captions']) == MEDIA
    assert video['voice']['en'] == 'en-GB-RyanNeural'
    assert video['render_revision'] == 7
    assert video['content_sha256'] != previous['content_sha256']
    assert capsule(repaired)['vtc']['transcript'] == video['transcript']
    assert capsule(repaired)['vtc']['bilingual_narration'] is True
    assert video['poster'] == previous['poster']
    assert video['chapters'] == previous['chapters']
    assert video['id'] == previous['id'] == CAPSULE
    assert video['duration_seconds'] == previous['duration_seconds'] == 498.15
    assert course_videos(repaired) == course_videos(before)
    assert set(repaired['assets']) == set(before['assets']) | set(MEDIA)
    assert repaired['counts']['assets'] == len(repaired['assets'])
    expected = copy.deepcopy(before)
    capsule(expected)['blocks'][0]['video'] = copy.deepcopy(video)
    capsule(expected)['vtc']['transcript'] = video['transcript']
    capsule(expected)['vtc']['bilingual_narration'] = True
    expected['assets'] = repaired['assets'][:]
    expected['counts']['assets'] = len(expected['assets'])
    assert repaired == expected
    assert path.read_bytes() == frozen
    assert vtc._course(COURSE, version) == frozen_course
    video['chapters'][0]['start_seconds'] = 123
    repaired['assets'].clear()
    assert capsule(vtc.load_bundled_course(COURSE, version))['blocks'][0]['video']['chapters'] == previous['chapters']
    assert set(MEDIA) <= set(vtc.load_bundled_course(COURSE, version)['assets'])


def test_other_modules_and_older_editions_are_unchanged():
    for module in vtc.curriculum_manifest()['modules']:
        for version in [module['version'], *module['previous_versions']]:
            if module['id'] == COURSE and version in VERSIONS:
                continue
            expected = vtc._repair_video_pacing(vtc._repair_english_listening(original(version, module['id'])))
            assert vtc.load_bundled_course(module['id'], version) == expected
    assert vtc.load_bundled_course(COURSE, 'unreviewed-version') is None


@pytest.mark.parametrize('change', ['version', 'activity', 'id', 'src', 'duration', 'chapters'])
def test_unreviewed_capsules_do_not_receive_replacement(change):
    course = original(VERSIONS[-1])
    activity = capsule(course)
    video = activity['blocks'][0]['video']
    if change == 'version':
        course['version'] = 'unreviewed-version'
    elif change == 'activity':
        activity['id'] = 'another-capsule'
    elif change == 'chapters':
        video['chapters'].pop()
    else:
        field = 'duration_seconds' if change == 'duration' else change
        video[field] = 499 if change == 'duration' else 'different-value'
    before = copy.deepcopy(course)
    assert vtc._repair_english_narration(course) == before


@pytest.mark.parametrize('change', ['duration', 'chapter_boundary'])
def test_replacement_with_changed_timing_is_not_used(change):
    course = original(VERSIONS[-1])
    replacement = copy.deepcopy(vtc._bilingual_video())
    if change == 'duration':
        replacement['duration_seconds'] = 600
    else:
        replacement['chapters'][1]['start_seconds'] += 1
    with patch.object(vtc, '_bilingual_video', return_value=replacement):
        assert vtc._repair_english_narration(copy.deepcopy(course)) == course


@pytest.mark.parametrize('version', VERSIONS)
def test_new_assets_are_allowlisted_only_for_the_reviewed_english_editions(tmp_path, version):
    # Tiny fixture files exercise authorization separately from media validation.
    for name in MEDIA:
        path = tmp_path / 'assets' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
    vtc._manifest()
    vtc._bilingual_video()
    # Keep the frozen loader rooted at the real courses, change only asset root.
    with patch.object(vtc, 'ROOT', tmp_path), patch.object(vtc, '_course', side_effect=lambda cid, ver: original_from_disk(cid, ver)):
        for name in MEDIA:
            assert vtc.bundled_asset(COURSE, version, name) == tmp_path / 'assets' / name
            assert vtc.bundled_asset('academy-vtc-a', version, name) is None
            assert vtc.bundled_asset(COURSE, '20261006-vtc-v3-105h', name) is None
            assert vtc.bundled_asset(COURSE, 'unknown', name) is None
        assert vtc.bundled_asset(COURSE, version, 'media/vtc/v7/../v7/lesson-e.mp4') is None


REAL_ROOT = Path(vtc.__file__).parent / 'vtc'


def original_from_disk(course_id, version):
    return json.loads((REAL_ROOT / 'courses' / course_id / (version + '.json')).read_text())


@pytest.mark.parametrize('version', VERSIONS)
@pytest.mark.parametrize('watched', [120.0, 498.15])
def test_existing_partial_and_completed_progress_survives_media_repair(tmp_path, version, watched):
    before = original(version)
    database = tmp_path / 'tracking.sqlite3'
    store = NativeElearningStore(database)
    access = {'session_id': 's1', 'trainee_id': 't1', 'course_id': COURSE, 'course_version': version}
    options = dict(activity_order=before['activity_order'], scored_activity_ids=[], mastery_score=80,
                   video_requirements=course_videos(before))
    store.get_progress(access, **options)
    complete = watched == 498.15
    saved_video = {CAPSULE: {CAPSULE: {'duration_seconds': 498.15, 'watched_seconds': watched,
                                    'completed': complete, 'completed_at': '2026-10-08T12:00:00Z' if complete else None}}}
    completed_ids = before['activity_order'] if complete else before['activity_order'][:-1]
    # Represent a database saved before the application starts serving v7 media.
    with sqlite3.connect(database) as connection:
        connection.execute('UPDATE learner_course_progress SET video_progress_json = ?, completed_json = ?, active_seconds = ?',
                           (json.dumps(saved_video), json.dumps(completed_ids), watched))
    old_progress = store.get_progress(access, **options)
    repaired = vtc.load_bundled_course(COURSE, version)
    options['video_requirements'] = course_videos(repaired)
    after = store.get_progress(access, **options)
    assert after == old_progress
    assert after['video_progress'] == saved_video
    assert videos_complete(saved_video[CAPSULE], course_videos(repaired)[CAPSULE]) is complete
    if complete:
        assert after['status'] == 'passed'
    else:
        # A learner can resume at the old frontier without any reset or credit jump.
        now = time.time()
        tracking = store.start_tracking(access, tab_id='resumed', activity_id=CAPSULE, now_epoch=now)
        for position, elapsed in ((watched, 0), (watched + 4, 4)):
            result = store.heartbeat(access, tracking['tracking_session_id'], activity_id=CAPSULE,
                                     visible=True, focused=True, recent_activity=True, media_playing=True,
                                     now_epoch=now + elapsed, video_requirements=options['video_requirements'][CAPSULE],
                                     video_samples=[{'id': CAPSULE, 'position': position, 'playing': True, 'rate': 1}])
        assert result['progress']['video_progress'][CAPSULE][CAPSULE]['watched_seconds'] == watched + 4
        assert not result['progress']['video_progress'][CAPSULE][CAPSULE]['completed']


def test_preview_serves_new_video_and_captions_with_authenticated_range_access():
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    try:
        case._admin_login()
        response = case.client.get(f'/admin/elearning/courses/{COURSE}/preview',
                                   query_string={'version': VERSIONS[-1], 'activity': CAPSULE})
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        video_url = html.unescape(re.search(r'<source src="([^"]+lesson-e\.mp4[^\"]*)"', body).group(1))
        assert '/media/vtc/v9/lesson-e.mp4' in video_url
        assert '/media/vtc/v7/lesson-e.vtt' in body
        assert '/media/vtc/v9/lesson-e.jpg' in body
        assert 'par une voix britannique' in body
        assert 'he is, she is' in body
        partial = case.client.get(video_url, headers={'Range': 'bytes=0-15'})
        assert partial.status_code == 206 and len(partial.data) == 16
        assert partial.mimetype == 'video/mp4'
        with case.client.session_transaction() as session:
            session.pop('admin_logged_in')
        assert case.client.get(video_url).status_code == 401
    finally:
        case.tearDown()
