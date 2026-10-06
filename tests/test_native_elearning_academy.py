"""Bundled curriculum integrity and historical learner/admin boundaries."""
import copy
import html
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from elearning_native.academy import ROOT, curriculum_manifest, load_bundled_course
from elearning_native.importer import CourseCatalog, CourseImportError
from tests import test_native_elearning_web as web_tests


class AcademyCatalogueTests(unittest.TestCase):
    def test_complete_curriculum_and_media(self):
        manifest = curriculum_manifest()
        self.assertEqual(sum(m['hours'] for m in manifest['modules']), 62)
        with tempfile.TemporaryDirectory() as temporary:
            catalog = CourseCatalog(temporary)
            activities = []
            for module in manifest['modules']:
                course = catalog.load_course(module['id'], module['version'])
                self.assertEqual(course['planned_minutes'], module['hours'] * 60)
                self.assertEqual(course['required_minutes'], course['planned_minutes'])
                for section in course['sections']:
                    self.assertEqual(sum(a['planned_minutes'] for a in section['activities']), 60)
                    activities.extend(section['activities'])
                    lesson = section['activities'][0]['academy']
                    self.assertTrue(all(ref['practice']['case'] for ref in lesson['lessons']))
                    pairs = section['activities'][4]['pairs']
                    self.assertEqual(len({p['left'] for p in pairs}), 3)
                    self.assertEqual(len({p['right'] for p in pairs}), 3)
                for asset in course['assets']:
                    self.assertTrue(catalog.asset_path(course['id'], course['version'], asset).is_file(), asset)
                with self.assertRaises(CourseImportError):
                    catalog.load_course(module['id'], 'unknown-version')
            self.assertEqual(len(activities), 434)
            self.assertEqual(sum(bool(a.get('workbook')) for a in activities), 0)
            self.assertEqual(sum(bool(a.get('practice')) for a in activities), 124)
            self.assertEqual(sum(bool(a['scored']) for a in activities), 124)
            self.assertEqual(len({a['id'] for a in activities}), 434)
        videos = json.loads((ROOT / 'video_manifest.json').read_text())
        self.assertEqual(len(videos), 62)
        self.assertTrue(all(v['duration_seconds'] > 30 and v['transcript'] for v in videos.values()))


class AcademyWebTests(unittest.TestCase):
    setUp = web_tests.NativeElearningWebTests.setUp
    tearDown = web_tests.NativeElearningWebTests.tearDown
    _admin_login = web_tests.NativeElearningWebTests._admin_login
    _public_login = web_tests.NativeElearningWebTests._public_login
    _player_config = staticmethod(web_tests.NativeElearningWebTests._player_config)
    _api_post = web_tests.NativeElearningWebTests._api_post

    def test_every_activity_renders_and_media_requires_session(self):
        self._admin_login()
        self.data['sessions'] = []
        with patch('elearning_native.web.NativeElearningStore', side_effect=AssertionError('Preview must not track')):
            for module in curriculum_manifest()['modules']:
                course = load_bundled_course(module['id'])
                for activity in course['activity_order']:
                    with self.subTest(activity=activity):
                        response = self.client.get(f"/admin/elearning/courses/{course['id']}/preview",
                            query_string={'version': course['version'], 'activity': activity})
                        self.assertEqual(response.status_code, 200)
                        page = response.get_data(as_text=True)
                        self.assertNotIn('nativeElearningConfig', page)
                        self.assertNotIn('<textarea', page)
                        self.assertNotIn('apsReflection', page)
                        if activity == 'aps62-01-01-memoriser':
                            caption = html.unescape(re.search(r'<track[^>]+src="([^"]+)"', page).group(1))
                            video = html.unescape(re.search(r'<source src="([^"]+)"', page).group(1))
            self.assertTrue(self.client.get(caption).data.startswith(b'WEBVTT'))
            media = self.client.get(video, headers={'Range': 'bytes=0-99'})
            self.assertEqual(media.status_code, 206)
            self.assertEqual(len(media.data), 100)
            with self.client.session_transaction() as browser:
                browser.pop('admin_logged_in')
            self.assertEqual(self.client.get(video).status_code, 401)
        self.assertIsNone(self.saved_data)

    def test_written_work_validation_persistence_and_private_review(self):
        # Place the real Academy workshop first in the isolated synthetic course,
        # so this test targets writing rather than repeating the video tests.
        # The archived raw edition is used only to verify historical work stays
        # readable. Learner-facing bundled courses now use click-only practice.
        workshop = json.loads((ROOT / 'courses/academy-aps62-01/20261004-aps62-v2.json').read_text())['sections'][0]['activities'][2]
        course = copy.deepcopy(self.course)
        activity = course['sections'][0]['activities'][0]
        activity.update({key: workshop[key] for key in ('academy', 'workbook')})
        original = CourseCatalog.load_course
        def load(catalog, course_id, version=None):
            return copy.deepcopy(course) if course_id == course['id'] else original(catalog, course_id, version)
        self._public_login()
        with patch.object(CourseCatalog, 'load_course', load):
            player = f"/espace/public-token/elearning/{course['id']}"
            config = self._player_config(self.client.get(player))
            self.assertEqual(self._api_post(config['completeUrl'], config).status_code, 400)
            self.assertEqual(self._api_post(config['completeUrl'], config, reflection='x' * 12001).status_code, 400)
            reflection = '=TEST <script>alert(1)</script>\n' + ('Je décris les faits et les limites de mon intervention. ' * 5)
            result = self._api_post(config['completeUrl'], config, reflection=reflection)
            self.assertEqual(result.status_code, 200)
            answer = result.json['progress']['answers'][activity['id']]
            self.assertEqual(answer['reflection'], reflection.strip())
            self.assertNotIn('correct', answer)
            repeat = self._api_post(config['completeUrl'], config, reflection='Un autre texte ' * 20)
            self.assertEqual(repeat.json['progress']['answers'][activity['id']], answer)
            work_url = f"/admin/elearning/courses/{course['id']}/work"
            self.assertEqual(self.client.get(work_url).status_code, 302)
            self._admin_login()
            page = self.client.get(work_url).get_data(as_text=True)
            self.assertIn('Alice Martin', page)
            self.assertIn('&lt;script&gt;', page)
            self.assertNotIn('<script>alert(1)</script>', page)
            export = self.client.get(work_url + '.csv').get_data(as_text=True)
            self.assertIn("'=TEST", export)
            live = self.client.get(f"/api/admin/elearning/courses/{course['id']}/live").json
            self.assertNotIn('answers', live['learners'][0])
            self.assertNotIn('written_work', live['learners'][0])
