"""The approved D.02 take is published intact and preserves trusted viewing."""
import copy
import hashlib
import html
import json
import re
from unittest.mock import patch

import pytest

from elearning_native import vtc, vtc_video_quality as quality
from elearning_native.paths import project_progress
from tests import test_native_elearning_web as web_tests

VID = 'vtc-d-02-explanation-v10'
AID = 'vtc-d-02-cours'
APPROVED_SHA = 'a9e6aae708388e899694043f90576e5b748b26b7be8a8673b63a3cdb1bed06fc'


def test_published_media_matches_the_approved_take_exactly():
    updates = quality.approved_voice_updates()
    assert set(updates) == quality.LESSONS | set('ABCDEFGH')
    row = updates['D.02']
    assert row['duration_seconds'] == 136.65
    assert row['media_sha256'] == APPROVED_SHA
    for name, checksum in [('src', 'media_sha256'), ('poster', 'poster_sha256'), ('captions', 'captions_sha256')]:
        path = quality.ROOT/'assets'/row[name]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row[checksum]
    settings = [take['speech_settings'] for scene in row['scenes'] for take in scene['spoken_segments']]
    assert len(settings) == 15 and all(s['voice'] == 'fr-FR-HenriNeural' for s in settings)
    assert min(int(s['rate'][:-1]) for s in settings) == -2
    assert max(int(s['rate'][:-1]) for s in settings) == 4


@pytest.mark.parametrize('generation', ['v10', 'v11'])
@pytest.mark.parametrize('completed', [False, True])
def test_both_known_timelines_keep_completion_or_resume_in_the_same_chapter(generation, completed):
    before = quality.quality_manifest()['lessons']['D.02']
    after = quality.approved_voice_updates()['D.02']
    prefix = 'previous_' if generation == 'v10' else ''
    duration, chapters = before[prefix+'duration_seconds'], before[prefix+'chapters']
    chapter = chapters[2]
    watched = duration if completed else (chapter['start_seconds']+chapter['end_seconds'])/2
    record = dict(duration_seconds=duration, watched_seconds=watched,
                  completed=completed, completed_at='2026-10-12' if completed else None)
    frozen = copy.deepcopy(record)
    result = quality.compatible_record(VID, record, after['duration_seconds'])
    assert record == frozen
    assert result['duration_seconds'] == after['duration_seconds']
    assert result['completed'] is completed
    if completed:
        assert result['watched_seconds'] == after['duration_seconds']
        assert result['completed_at'] == '2026-10-12'
    else:
        expected = (after['chapters'][2]['start_seconds']+after['chapters'][2]['end_seconds'])/2
        assert result['watched_seconds'] == pytest.approx(expected, abs=.002)
        assert result['completed_at'] is None
    saved = dict(active_seconds=1234, completed_activity_ids=[], video_progress={AID: {VID: record}})
    projected = project_progress(saved, vtc.load_bundled_course('academy-vtc-d'))
    assert saved['video_progress'][AID][VID] == frozen
    assert projected['active_seconds'] == 1234
    assert projected['video_progress'][AID][VID] == result


def test_unknown_duration_and_incomplete_claim_do_not_gain_completion():
    row = quality.approved_voice_updates()['D.02']
    unknown = dict(duration_seconds=999., watched_seconds=999., completed=True)
    assert quality.compatible_record(VID, unknown, row['duration_seconds']) == unknown
    false_claim = dict(duration_seconds=row['previous_duration_seconds'], watched_seconds=10., completed=True)
    assert quality.compatible_record(VID, false_claim, row['duration_seconds'])['completed'] is False


def test_preview_serves_approved_video_and_captions_with_one_x_controls():
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    try:
        case._admin_login()
        page = case.client.get('/admin/elearning/courses/academy-vtc-d/preview',
                               query_string=dict(version=vtc.REQUIRED_VERSION, activity=AID))
        assert page.status_code == 200
        body = page.get_data(as_text=True)
        url = html.unescape(re.search(r'<source src="([^"]+/media/vtc/v14/lesson-d-02.mp4[^"]*)"', body)[1])
        media = case.client.get(url, headers={'Range': 'bytes=0-31'})
        assert media.status_code == 206 and media.mimetype == 'video/mp4'
        row = quality.approved_voice_updates()['D.02']
        assert media.data == (quality.ROOT/'assets'/row['src']).read_bytes()[:32]
        captions = case.client.get(url.replace('lesson-d-02.mp4', 'lesson-d-02.vtt'))
        assert captions.status_code == 200 and captions.data.startswith(b'WEBVTT')
        config = json.loads(re.search(r'data-video-pacing-config>(.*?)</script>', body, re.S)[1])
        assert config['default_playback_rate'] == 1 and config['allowed_playback_rates'] == [1]
        assert 'data-playback-rate' not in body
        with case.client.session_transaction() as session:
            session.clear()
        assert case.client.get(url).status_code in (401, 403)
    finally:
        case.tearDown()


@pytest.mark.parametrize('mutation', ['preview', 'predecessor', 'voice', 'path'])
def test_unapproved_or_mismatched_replacement_is_rejected(tmp_path, mutation):
    root = quality.ROOT
    data = json.loads((root/'video_voice_v14.json').read_text())
    row = data['lessons']['D.02']
    if mutation == 'preview': row['preview_only'] = True
    elif mutation == 'predecessor': row['previous_duration_seconds'] += 1
    elif mutation == 'voice': row['voice'] = {'fr': 'another-voice'}
    elif mutation == 'path': row['src'] = 'media/vtc/v14/../v11/lesson-d-02.mp4'
    (tmp_path/'video_voice_v14.json').write_text(json.dumps(data))
    for name in ('video_quality_v11.json', 'lesson_videos_v10.json', 'video_pacing_v9.json', 'assets'):
        (tmp_path/name).symlink_to(root/name, target_is_directory=name=='assets')
    quality.quality_manifest.cache_clear()
    quality.approved_voice_updates.cache_clear()
    try:
        with patch.object(quality, 'ROOT', tmp_path), pytest.raises(ValueError, match='VTC voice'):
            quality.approved_voice_updates()
    finally:
        quality.quality_manifest.cache_clear()
        quality.approved_voice_updates.cache_clear()
