"""Existing narrated resources enrich MAC lessons without resetting learners."""
import copy
import hashlib
import html
import re
from unittest.mock import patch

from elearning_native import mac_aps
from elearning_native.paths import project_progress
from elearning_native.videos import course_videos
from tests import test_native_elearning_mac_aps as mac_web_tests


def reset_courses():
    mac_aps._course.cache_clear()


def test_all_28_lessons_have_a_video_and_selected_assets_are_scoped():
    manifest = mac_aps.curriculum_manifest()
    assert (manifest['lesson_video_count'], manifest['lessons_with_video'], manifest['video_count']) == (22, 28, 24)
    seen = set()
    for course_id in mac_aps.curriculum_ids():
        course = mac_aps.load_bundled_course(course_id)
        for section in course['sections']:
            activity = section['activities'][0]
            if activity.get('macaps', {}).get('kind') != 'lesson':
                continue
            videos = [b['video'] for b in activity['blocks'] if b.get('video')]
            assert len(videos) == 1
            video = videos[0]
            assert not video['required'] and video['lesson_explainer']
            assert video['burned_captions'] and video['voice'] == 'fr-FR-HenriNeural'
            assert video['duration_seconds'] >= 300 and video['transcript'] and video['learning_purpose']
            for field in ('src', 'poster', 'captions'):
                assert mac_aps.bundled_asset(course_id, mac_aps.VERSION, video[field]).is_file()
            seen.add(video['src'])
        assert mac_aps.bundled_asset(course_id, mac_aps.VERSION, 'media/aps62/v9/aps62-10-07.mp4') is None
        assert mac_aps.bundled_asset(course_id, mac_aps.LEGACY_VERSION, next(iter(seen))) is None
        assert mac_aps.bundled_asset(course_id, mac_aps.VERSION, '../aps62/manifest.json') is None
    assert len(seen) == 22


def test_enrichment_preserves_every_required_step_and_earned_progress():
    reset_courses()
    try:
        with patch.object(mac_aps, '_lesson_videos', return_value={}):
            before = {cid: mac_aps.load_bundled_course(cid) for cid in mac_aps.curriculum_ids()}
        reset_courses()
        for cid, prior in before.items():
            current = mac_aps.load_bundled_course(cid)
            assert current['activity_order'] == prior['activity_order']
            assert current['timed_objectives'] == prior['timed_objectives']
            assert current['required_minutes'] == prior['required_minutes']
            assert course_videos(current) == course_videos(prior)
            saved = {'active_seconds': 1725, 'activity_seconds': {prior['activity_order'][0]: 600},
                     'completed_activity_ids': prior['activity_order'][:4], 'answers': {}, 'video_progress': {}}
            original_saved = copy.deepcopy(saved)
            assert project_progress(saved, current) == project_progress(saved, prior)
            assert saved == original_saved
            # Remove only the added, optional video block: the rest must match.
            stripped = copy.deepcopy(current)
            stripped['assets'] = prior['assets']
            stripped['counts']['assets'] = prior['counts']['assets']
            for section in stripped['sections']:
                for activity in section['activities']:
                    activity['blocks'] = [b for b in activity.get('blocks', [])
                                          if not b.get('video', {}).get('source_video_id')]
                    if 'blocks' not in next(a for s in prior['sections'] for a in s['activities'] if a['id'] == activity['id']):
                        activity.pop('blocks')
            assert stripped == prior
    finally:
        reset_courses()


def test_compact_summary_release_retains_audio_and_old_media():
    for number, entry in mac_aps._media()['videos'].items():
        assert (entry['subtitle_font_pixels'], entry['subtitle_bottom_margin_pixels'], entry['subtitle_band_pixels']) == (38, 22, 128)
        assert entry['audio_preserved'] and entry['visual_sync']
        assert entry['audio_packet_sha256']
        path = mac_aps.ROOT/'assets'/entry['src']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['video_sha256']
        for revision in ('v1', 'v2', 'v3'):
            assert mac_aps.bundled_asset('academy-macaps-'+number, mac_aps.LEGACY_VERSION,
                                        f'media/mac-aps/{revision}/module-{number}.mp4').is_file()


def test_preview_renders_selected_video_with_signed_mac_access_and_one_caption_layer():
    case = mac_web_tests.MacAPSWebTests(methodName='runTest')
    case.setUp()
    try:
        case._admin_login()
        response = case.client.get('/admin/elearning/courses/academy-macaps-02/preview',
                                  query_string={'activity': 'macaps-02-01-cours', 'version': mac_aps.VERSION})
        assert response.status_code == 200
        assert 'Relier les principes républicains' in response.text
        assert 'Vidéo explicative' in response.text
        assert 'data-required-video=' not in response.text
        assert '<track kind="captions"' not in response.text
        media_url = html.unescape(re.search(r'<source src="([^"]+)"', response.text).group(1))
        assert '/academy-macaps-02/' in media_url and '/aps62-05-01.mp4?' in media_url
        ranged = case.client.get(media_url, headers={'Range': 'bytes=0-255'})
        assert ranged.status_code == 206 and len(ranged.data) == 256
        assert case.client.get(media_url.split('?')[0]).status_code == 401
        assert case.client.get(media_url.replace('/academy-macaps-02/', '/academy-macaps-03/')).status_code == 403
        assert case.client.get(media_url.replace('aps62-05-01.mp4', 'aps62-10-07.mp4')).status_code == 404
    finally:
        case.tearDown()
