"""Readable VTC presentation uses the same authorized player as the media."""
import copy
import json
import re
from unittest.mock import patch

import pytest

from elearning_native import vtc
from elearning_native.vtc_lesson_videos import COURSE_VERSION, REQUIRED_VERSION
from tests import test_native_elearning_web as web_tests


PRESENTATION = {
    'scenes': [{'start': 0, 'end': 30, 'title': 'Repère lisible',
                'points': [{'label': 'Principe', 'text': '<script>texte pédagogique</script>', 'at_seconds': 2}]}],
    'captions': [{'start': 0, 'end': 2, 'text': 'Douze points sur vingt.'}],
}


def companion_payload(body):
    match = re.search(r'<script type="application/json" data-vtc-video-presentation>(.*?)</script>',
                      body, flags=re.DOTALL)
    assert match
    return json.loads(match[1])


@pytest.mark.parametrize('version', [COURSE_VERSION, REQUIRED_VERSION])
@pytest.mark.parametrize('kind', ['lesson', 'module'])
def test_authorized_vtc_previews_render_readable_metadata_for_lessons_and_syntheses(version, kind):
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    try:
        original_load = vtc.load_bundled_course
        course = original_load('academy-vtc-a', version)
        selected = next(activity for section in course['sections'] for activity in section['activities']
                        if any(bool(block.get('video', {}).get('lesson_explainer')) == (kind == 'lesson')
                               and block.get('video') for block in activity.get('blocks', [])))
        for block in selected['blocks']:
            if block.get('video'):
                block['video']['presentation'] = copy.deepcopy(PRESENTATION)

        def load(course_id, requested_version=None):
            if course_id == course['id'] and requested_version in (None, version):
                return copy.deepcopy(course)
            return original_load(course_id, requested_version)

        case._admin_login()
        with patch.object(vtc, 'load_bundled_course', side_effect=load):
            response = case.client.get('/admin/elearning/courses/academy-vtc-a/preview',
                                       query_string={'activity': selected['id'], 'version': version})
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert companion_payload(body) == PRESENTATION
        assert '<script>texte pédagogique</script>' not in body
        assert 'vtc-video-companion.js' in body
        assert 'data-video-reader-expand aria-expanded="false"' in body
        assert 'Repères synchronisés avec la vidéo' in body
        assert 'aria-live="off" data-video-companion hidden' in body
        assert 'data-video-pacing-config' in body and '0,85×' in body
        assert 'nativeElearningConfig' not in body
    finally:
        case.tearDown()


def test_learner_companion_is_authorized_and_does_not_relax_required_viewing():
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    try:
        original_load = vtc.load_bundled_course

        def load(course_id, version=None):
            course = original_load(course_id, version)
            if course and course_id == 'academy-vtc-a':
                for section in course['sections']:
                    for activity in section['activities']:
                        for block in activity.get('blocks', []):
                            if block.get('video'):
                                block['video']['presentation'] = copy.deepcopy(PRESENTATION)
            return course

        case.data['sessions'][0].update(training_type='VTC', aps_native_course_id='academy-vtc-a',
                                       aps_native_course_version=REQUIRED_VERSION)
        with patch.object(vtc, 'load_bundled_course', side_effect=load):
            anonymous = case.client.get('/espace/public-token/elearning/academy-vtc-a')
            assert 'data-vtc-video-presentation' not in anonymous.get_data(as_text=True)
            case._public_login()
            response = case.client.get('/espace/public-token/elearning/academy-vtc-a')
            assert response.status_code == 200
            assert companion_payload(response.get_data(as_text=True)) == PRESENTATION
            config = case._player_config(response)
            assert config['requiredVideos']
            assert case._api_post(config['completeUrl'], config).status_code == 409
            other_course = case.client.get('/espace/public-token/elearning/academy-vtc-b')
            assert other_course.status_code in (403, 404)
            assert 'data-vtc-video-presentation' not in other_course.get_data(as_text=True)
    finally:
        case.tearDown()


def test_non_vtc_player_does_not_load_the_companion():
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    try:
        case._public_login()
        page = case.client.get('/espace/public-token/elearning/' + case.course['id'])
        assert page.status_code == 200
        body = page.get_data(as_text=True)
        assert 'vtc-video-companion.js' not in body
        assert 'data-vtc-video-reader' not in body
    finally:
        case.tearDown()
