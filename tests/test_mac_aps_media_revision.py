"""A visual-only MAC APS release keeps course identities and earned viewing intact."""
from __future__ import annotations

import copy
import html
import json
import re
from unittest.mock import patch

import pytest

from elearning_native import mac_aps
from elearning_native.paths import project_progress
from elearning_native.videos import course_videos
from tests import test_native_elearning_web as web_tests
from tests.test_mac_aps_v2_curriculum import teaching_graph


@pytest.fixture
def media_manifests():
    original = {'revision': '20261012-mac-aps-v1', 'videos': {
        number: json.loads((mac_aps.ROOT / 'assets' / 'media' / 'mac-aps' / 'v1' /
                            f'module-{number}.json').read_text())
        for number in ('01', '02', '03', '04', '05')
    }}
    revised = copy.deepcopy(original)
    revised['revision'] = '20261012-mac-aps-v2'
    for number, entry in revised['videos'].items():
        entry.update(render_revision='20261012-mac-aps-v2', video_sha256='f' * 64,
                     caption_cues=entry['caption_cues'] + 1)
        for key, extension in (('src', '.mp4'), ('poster', '.jpg'), ('captions', '.vtt')):
            entry[key] = f'media/mac-aps/v2/module-{number}' + extension
    mac_aps._course.cache_clear()
    mac_aps._complement.cache_clear()
    try:
        yield original, revised
    finally:
        mac_aps._course.cache_clear()
        mac_aps._complement.cache_clear()


def all_courses():
    keys = [(cid, version) for version in mac_aps.SUPPORTED_VERSIONS
            for cid in mac_aps.curriculum_ids(version)]
    keys += [(row['id'], mac_aps.VERSION) for row in mac_aps._plan()['complements']]
    return {key: mac_aps.load_bundled_course(*key) for key in keys}


def video_rows(course):
    # This release replaces the five summaries. Optional APS revision videos
    # have their own unchanged media and are covered by lesson-video tests.
    return [block['video'] for section in course['sections'] for activity in section['activities']
            for block in activity.get('blocks', []) if re.fullmatch(
                r'macaps-0[1-5]-video', block.get('video', {}).get('id', ''))]


def test_visual_revision_preserves_teaching_graph_snapshot_and_progress(media_manifests):
    original, revised = media_manifests
    snapshot_path = mac_aps.ROOT / 'versions' / mac_aps.LEGACY_VERSION / 'snapshot.json'
    snapshot_bytes = snapshot_path.read_bytes()
    snapshot = copy.deepcopy(mac_aps._legacy())
    with patch.object(mac_aps, '_media', return_value=original):
        before = all_courses()
        assert {cid: before[(cid, mac_aps.LEGACY_VERSION)] for cid in mac_aps.curriculum_ids(mac_aps.LEGACY_VERSION)} == snapshot['courses']
    # Ignore any accidental teaching or tracking fields in the replacement manifest.
    for entry in revised['videos'].values():
        entry.update(duration_seconds=1, transcript='must not replace teaching text',
                     id='must-not-replace-id', course_version='other', title='must not replace title',
                     required=False, default_playback_rate=2)
    mac_aps._course.cache_clear()
    mac_aps._complement.cache_clear()
    with patch.object(mac_aps, '_media', return_value=revised):
        after = all_courses()
        for key, prior in before.items():
            current = after[key]
            assert teaching_graph(current) == teaching_graph(prior)
            assert course_videos(current) == course_videos(prior)
            assert set(prior['assets']).issubset(current['assets'])
            assert current['counts']['assets'] == len(current['assets'])
            for old_video, new_video in zip(video_rows(prior), video_rows(current)):
                assert new_video['src'] == old_video['src'].replace('/v1/', '/v2/')
                assert new_video['poster'] == old_video['poster'].replace('/v1/', '/v2/')
                assert new_video['captions'] == old_video['captions'].replace('/v1/', '/v2/')
                assert new_video['video_sha256'] == 'f' * 64
                assert all(new_video[field] in current['assets'] for field in ('src', 'poster', 'captions'))
            for finished in (False, True):
                requirements = course_videos(prior)
                progress = {
                    'active_seconds': 1234.5,
                    'activity_seconds': {prior['activity_order'][0]: 1234.5},
                    'started_at': '2026-10-12T08:00:00+00:00',
                    'completed_activity_ids': list(prior['activity_order']),
                    'video_progress': {aid: {vid: {
                        'duration_seconds': duration,
                        'watched_seconds': duration if finished else duration / 2,
                        'completed': finished,
                        'completed_at': '2026-10-12T08:07:00+00:00' if finished else None,
                    } for vid, duration in videos.items()} for aid, videos in requirements.items()},
                }
                saved = copy.deepcopy(progress)
                assert project_progress(progress, current) == project_progress(progress, prior)
                assert progress == saved
        # Returned structures cannot alter either the frozen snapshot or the manifest.
        detached = mac_aps.load_bundled_course('academy-macaps-02', mac_aps.LEGACY_VERSION)
        video_rows(detached)[0]['src'] = 'changed'
        assert video_rows(mac_aps.load_bundled_course('academy-macaps-02', mac_aps.LEGACY_VERSION))[0]['src'].startswith('media/mac-aps/v2/')
    assert mac_aps._legacy() == snapshot
    assert snapshot_path.read_bytes() == snapshot_bytes


@pytest.mark.parametrize('changed', ['src', 'render_revision'])
def test_unreviewed_or_cross_module_replacements_are_rejected(media_manifests, changed):
    _, revised = media_manifests
    revised['videos']['02'][changed] = ('media/mac-aps/v2/module-03.mp4' if changed == 'src' else 'unknown')
    with patch.object(mac_aps, '_media', return_value=revised):
        with pytest.raises(ValueError, match='Reviewed MAC APS media is invalid'):
            mac_aps.load_bundled_course('academy-macaps-02', mac_aps.LEGACY_VERSION)


def test_old_and_corrected_media_keep_signed_course_authorization(media_manifests, tmp_path):
    _, revised = media_manifests
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    try:
        case._admin_login()
        with patch.object(mac_aps, '_media', return_value=revised):
            page = case.client.get('/admin/elearning/courses/academy-macaps-02/preview',
                                   query_string={'activity': 'macaps-02-video', 'version': mac_aps.LEGACY_VERSION})
            assert page.status_code == 200
            media_url = html.unescape(re.search(r'<source src="([^"]+)"', page.text).group(1))
            assert '/media/mac-aps/v2/module-02.mp4?' in media_url
            assert '<track kind="captions"' not in page.text
            for revision in ('v1', 'v2'):
                asset = tmp_path / 'assets' / 'media' / 'mac-aps' / revision / 'module-02.mp4'
                asset.parent.mkdir(parents=True, exist_ok=True)
                asset.write_bytes(('fictional-' + revision).encode())
            # Only the asset root is replaced; the authenticated route remains real.
            with patch.object(mac_aps, 'ROOT', tmp_path):
                assert case.client.get(media_url).data == b'fictional-v2'
                assert case.client.get(media_url.replace('/v2/', '/v1/')).data == b'fictional-v1'
                assert case.client.get(media_url.split('?')[0]).status_code == 401
                assert case.client.get(media_url.replace('/academy-macaps-02/', '/academy-macaps-03/')).status_code == 403
                assert case.client.get(media_url.replace('module-02.mp4', 'module-03.mp4')).status_code == 404
    finally:
        case.tearDown()
