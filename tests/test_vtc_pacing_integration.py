"""Paced visuals must preserve assignments, immutable media and saved progress."""
import copy
import hashlib
import html
import json
import re
from unittest.mock import patch

import pytest

from elearning_native import vtc
from elearning_native.videos import activity_playback_policy, course_videos, videos_complete
from tests import test_native_elearning_web as web_tests

VERSIONS = ('20261007-vtc-v4-visuals', '20261007-vtc-v5-annales', '20261010-vtc-v6-pedagogie')


def old_course(letter, version):
    return json.loads((vtc.ROOT/'courses'/f'academy-vtc-{letter.lower()}'/(version+'.json')).read_text())


def capsule(course):
    return next(a for s in course['sections'] for a in s['activities'] if a['id'].endswith('-capsule'))


@pytest.mark.parametrize('letter', list('ABCDEFGH'))
@pytest.mark.parametrize('version', VERSIONS)
def test_every_current_capsule_gets_pacing_without_changing_progress_contract(letter, version):
    cid = f'academy-vtc-{letter.lower()}'
    frozen = old_course(letter, version)
    before = vtc.enrich_lessons(vtc._repair_english_listening(vtc._repair_english_narration(copy.deepcopy(frozen))))
    after = vtc.load_bundled_course(cid, version)
    original_video = capsule(before)['blocks'][0]['video']
    video = capsule(after)['blocks'][0]['video']
    assert video['src'] == f'media/vtc/v9/lesson-{letter.lower()}.mp4'
    assert video['default_playback_rate'] == .85
    assert video['allowed_playback_rates'] == [.85, 1]
    assert len(video['learning_pauses']) == {'B': 13, 'D': 14, 'E': 23}.get(letter, 11)
    assert (video['id'], video['duration_seconds'], video['chapters'], video['transcript'], video['captions']) == tuple(
        original_video[key] for key in ('id', 'duration_seconds', 'chapters', 'transcript', 'captions'))
    assert course_videos(after) == course_videos(before)
    for watched, completed in ((125.5, False), (video['duration_seconds'], True)):
        saved = {video['id']: dict(duration_seconds=video['duration_seconds'], watched_seconds=watched,
                                 completed=completed, completed_at='2026-10-10' if completed else None)}
        assert videos_complete(saved, {video['id']: video['duration_seconds']}) is completed
    assert after['activity_order'] == before['activity_order']
    assert after['planned_minutes'] == before['planned_minutes']
    assert [a for s in before['sections'] for a in s['activities'] if a['id'] != video['id']] == [
        a for s in after['sections'] for a in s['activities'] if a['id'] != video['id']]
    assert vtc._course(cid, version) == frozen
    assert old_course(letter, version) == frozen
    policy = activity_playback_policy(after, video['id'])
    assert policy[video['id']]['rates'] == (.85, 1)
    assert len(policy[video['id']]['pauses']) == len(video['learning_pauses'])
    video['learning_pauses'][0]['message'] = 'local edit'
    assert capsule(vtc.load_bundled_course(cid, version))['blocks'][0]['video']['learning_pauses'][0]['message'] != 'local edit'


@pytest.mark.parametrize('letter', list('ABCDEFGH'))
def test_historical_editions_and_cross_course_assets_remain_isolated(letter):
    cid = f'academy-vtc-{letter.lower()}'
    module = next(m for m in vtc.curriculum_manifest()['modules'] if m['id'] == cid)
    for version in module['previous_versions']:
        if version in VERSIONS:
            continue
        before = vtc._repair_english_listening(old_course(letter, version))
        assert vtc.load_bundled_course(cid, version) == before
        assert vtc.bundled_asset(cid, version, f'media/vtc/v9/lesson-{letter.lower()}.mp4') is None
    other = 'b' if letter == 'A' else 'a'
    assert vtc.bundled_asset(cid, VERSIONS[-1], f'media/vtc/v9/lesson-{other}.mp4') is None


@pytest.mark.parametrize('change', ['duration', 'chapters', 'transcript', 'source', 'pause', 'asset'])
def test_mismatched_media_or_pause_manifest_is_not_applied(change):
    course = vtc._repair_english_narration(old_course('E', VERSIONS[-1]))
    manifests = copy.deepcopy(vtc._pacing_manifests())
    media = manifests[0]['modules']['E']
    if change == 'duration': media['duration_seconds'] += 2
    if change == 'chapters': media['chapters'][0]['end_seconds'] += 1
    if change == 'transcript': media['transcript'] += ' Extra.'
    if change == 'source': media['source_video'] = 'another-source.mp4'
    if change == 'asset': media['src'] = 'media/vtc/v9/../other.mp4'
    if change == 'pause': manifests[1]['modules']['E']['pauses'][0]['at_seconds'] = float('nan')
    with patch.object(vtc, '_pacing_manifests', return_value=manifests):
        assert vtc._repair_video_pacing(copy.deepcopy(course)) == course


def test_all_media_and_pauses_are_bound_to_the_unchanged_narration():
    manifest, pauses = vtc._pacing_manifests()
    visual = json.loads((vtc.ROOT/'video_visuals_v9.json').read_text())
    assert set(manifest['modules']) == set('ABCDEFGH')
    for letter, video in manifest['modules'].items():
        assert hashlib.sha256((vtc.ROOT/'assets'/video['src']).read_bytes()).hexdigest() == video['file_sha256']
        assert hashlib.sha256((vtc.ROOT/'assets'/video['source_video']).read_bytes()).hexdigest() == video['source_file_sha256']
        assert abs(video['actual_duration_seconds'] - video['duration_seconds']) <= .05
        assert video['audio_provenance']['mode'] == 'encoded-packet-copy'
        assert len(video['visual_reveals']) == 24
        for index, (chapter, scene, reveals, text) in enumerate(zip(video['chapters'], visual['modules'][letter]['scenes'],
                video['visual_reveals'], video['transcript'].split('\n\n'))):
            assert len(scene['points']) == len(reveals['points']) == 3
            times = [point['at_seconds'] for point in reveals['points']]
            assert times == sorted(times)
            assert chapter['start_seconds'] <= min(times) <= max(times) < chapter['end_seconds']
            assert all(point['anchor_text'] in text for point in scene['points'])
        for pause in pauses['modules'][letter]['pauses']:
            quiet = pause['verified_silence']
            assert quiet['start'] < pause['at_seconds'] < pause['chapter_end_seconds'] < quiet['end']
            assert pause['duration_seconds'] in (4, 5)
    assert sum(len(m['pauses']) for m in pauses['modules'].values()) == 105
    english_route = json.dumps(visual['modules']['E']['scenes'][12]['points'], ensure_ascii=False)
    assert 'thirty minutes' in english_route and 'twenty minutes' not in english_route


def test_preview_contains_slow_pacing_and_serves_corrected_media_only_with_access():
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    try:
        case._admin_login()
        for letter in 'abcdefgh':
            response = case.client.get(f'/admin/elearning/courses/academy-vtc-{letter}/preview',
                query_string={'version': VERSIONS[-1], 'activity': f'vtc-{letter}-capsule'})
            assert response.status_code == 200
            body = response.get_data(as_text=True)
            assert 'native-video-pacing.js' in body
            assert '0.85' in body and 'learning_pauses' in body
            url = html.unescape(re.search(r'<source src="([^"]+lesson-'+letter+r'\.mp4[^"]*)"', body)[1])
            assert f'/media/vtc/v9/lesson-{letter}.mp4' in url
            media = case.client.get(url, headers={'Range': 'bytes=0-31'})
            assert media.status_code == 206 and len(media.data) == 32
        with case.client.session_transaction() as session:
            session.pop('admin_logged_in')
        assert case.client.get(url).status_code == 401
    finally:
        case.tearDown()
