"""No-writing APS replacement: content, grading, access and progress continuity."""
import copy
import json
import re
import unittest
from unittest.mock import patch

from elearning_native.academy import ROOT, curriculum_manifest, load_bundled_course
from elearning_native.importer import CourseCatalog
from elearning_native.practice import grade_practice, public_practice
from elearning_native.videos import course_videos
from tests import test_native_elearning_web as web_tests


def correct_answers(practice):
    return {ex['id']: ex['answer'] if ex['kind'] == 'single'
            else {row['id']: row['answer'] for row in ex['rows']}
            for ex in practice['exercises']}


class PracticeContentTests(unittest.TestCase):
    def test_all_versions_keep_progress_identity_and_remove_writing(self):
        manifest = curriculum_manifest()
        self.assertEqual(manifest['workbook_count'], 0)
        self.assertEqual(manifest['interactive_workshop_count'], 248)
        for module in manifest['modules']:
            for version in [module['version'], *module['previous_versions']]:
                with self.subTest(module=module['id'], version=version):
                    raw = json.loads((ROOT / 'courses' / module['id'] / (version + '.json')).read_text())
                    course = load_bundled_course(module['id'], version)
                    self.assertEqual(course['version'], raw['version'])
                    self.assertEqual(course['activity_order'], raw['activity_order'])
                    self.assertEqual(course['assets'], raw['assets'])
                    self.assertEqual(course['required_minutes'], raw['required_minutes'])
                    self.assertEqual(course['settings'], raw['settings'])
                    self.assertEqual(course_videos(course), course_videos(raw))
                    for before, after in zip(raw['sections'], course['sections']):
                        for old, new in zip(before['activities'], after['activities']):
                            self.assertEqual((old['scored'], old['planned_minutes']), (new['scored'], new['planned_minutes']))
                            self.assertNotIn('workbook', new)
                            if old.get('workbook') or old.get('practice'):
                                self.assertIn('practice', new)
                                self.assertNotIn('task', new['academy'])
                                result = grade_practice(new['practice'], correct_answers(new['practice']))
                                self.assertTrue(result['correct'])
                                public = json.dumps(public_practice(new['practice']))
                                self.assertNotIn('"answer"', public)
                                self.assertNotIn('"explanation"', public)
                    self.assertEqual(course['counts']['interactive_workshops'], raw['counts'].get('interactive_workshops', raw['counts']['workbooks']))

    def test_incomplete_unknown_duplicate_and_wrong_answers(self):
        practice = load_bundled_course('academy-aps62-01', '20261004-aps62-v2')['sections'][0]['activities'][2]['practice']
        answers = correct_answers(practice)
        for value in [None, [], {}, {**answers, 'extra': 'x'}, {**answers, 'decision': True},
                      {**answers, 'decision': '__unknown__'},
                      {**answers, 'ordre': {r['id']: '1' for r in practice['exercises'][3]['rows']}}]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    grade_practice(practice, value)
        wrong = copy.deepcopy(answers)
        wrong['decision'] = next(o['id'] for o in practice['exercises'][0]['options'] if o['id'] != answers['decision'])
        result = grade_practice(practice, wrong)
        self.assertFalse(result['correct'])
        self.assertEqual(result['passed'], 3)
        self.assertTrue(result['feedback'][0]['correction'])
        self.assertEqual(answers, correct_answers(practice))


class PracticeWebTests(unittest.TestCase):
    setUp = web_tests.NativeElearningWebTests.setUp
    tearDown = web_tests.NativeElearningWebTests.tearDown
    _admin_login = web_tests.NativeElearningWebTests._admin_login
    _public_login = web_tests.NativeElearningWebTests._public_login
    _player_config = staticmethod(web_tests.NativeElearningWebTests._player_config)
    _api_post = web_tests.NativeElearningWebTests._api_post

    def fixture_course(self):
        course = copy.deepcopy(self.course)
        workshop = load_bundled_course('academy-aps62-01')['sections'][0]['activities'][2]
        activity = course['sections'][0]['activities'][0]
        activity.update({key: copy.deepcopy(workshop[key]) for key in ('academy', 'practice', 'title')})
        original = CourseCatalog.load_course
        def load(catalog, course_id, version=None):
            return copy.deepcopy(course) if course_id == course['id'] else original(catalog, course_id, version)
        return course, activity, patch.object(CourseCatalog, 'load_course', load)

    def test_practice_is_corrected_without_progress_then_completed_without_writing(self):
        course, activity, loader = self.fixture_course()
        answers = correct_answers(activity['practice'])
        self._public_login()
        with loader:
            response = self.client.get(f"/espace/public-token/elearning/{course['id']}")
            page = response.get_data(as_text=True)
            self.assertNotIn('<textarea', page)
            self.assertIn('Aucune rédaction', page)
            config = self._player_config(response)
            self.assertEqual(self._api_post(config['completeUrl'], config, reflection='A' * 500).status_code, 400)
            self.assertEqual(self._api_post(config['practiceUrl'], config).status_code, 400)
            wrong = {**answers, 'decision': next(o['id'] for o in activity['practice']['exercises'][0]['options'] if o['id'] != answers['decision'])}
            self.assertFalse(self._api_post(config['practiceUrl'], config, practice_answers=wrong).json['correct'])
            self.assertEqual(self._api_post(config['completeUrl'], config, practice_answers=wrong).status_code, 400)
            marked = self._api_post(config['practiceUrl'], config, practice_answers=answers)
            self.assertTrue(marked.json['correct'])
            self.assertIn('no-store', marked.headers['Cache-Control'])
            check = self._player_config(self.client.get(f"/espace/public-token/elearning/{course['id']}"))
            self.assertFalse(check['activityCompleted'])
            self.assertEqual(check['initialActiveSeconds'], 0)
            saved = self._api_post(config['completeUrl'], config, practice_answers=answers)
            self.assertEqual(saved.status_code, 200)
            progress = saved.json['progress']
            self.assertEqual(progress['completed_activity_ids'], [activity['id']])
            self.assertEqual(progress['active_seconds'], 0)
            answer = progress['answers'][activity['id']]
            self.assertEqual(answer['practice_answers'], answers)
            self.assertEqual(answer['review_status'], 'auto_corrected')
            self.assertNotIn('reflection', answer)
            self.assertNotIn('correct', answer)
            repeated = self._api_post(config['completeUrl'], config, practice_answers=wrong)
            self.assertEqual(repeated.json['progress']['answers'][activity['id']], answer)
            self.assertEqual(self.client.post(config['practiceUrl'], json={'access_token': config['accessToken'], 'practice_answers': answers}).status_code, 403)

    def test_prior_written_completion_survives_and_remains_readable(self):
        course, activity, loader = self.fixture_course()
        practice = activity.pop('practice')
        activity['workbook'] = {'min_chars': 20, 'max_chars': 12000}
        self._public_login()
        with loader:
            url = f"/espace/public-token/elearning/{course['id']}?activity={activity['id']}"
            config = self._player_config(self.client.get(url))
            old = self._api_post(config['completeUrl'], config, reflection='Un ancien travail déjà terminé et conservé.').json['progress']
            activity.pop('workbook')
            activity['practice'] = practice
            page = self.client.get(url)
            config = self._player_config(page)
            self.assertTrue(config['activityCompleted'])
            self.assertNotIn('<textarea', page.get_data(as_text=True))
            repeated = self._api_post(config['completeUrl'], config).json['progress']
            self.assertEqual(repeated['answers'], old['answers'])
            self.assertEqual(repeated['completed_activity_ids'], old['completed_activity_ids'])
            self.assertEqual(repeated['active_seconds'], old['active_seconds'])

    def test_preview_correction_and_access_boundaries(self):
        course = load_bundled_course('academy-aps62-01')
        activity = course['sections'][0]['activities'][2]
        url = f"/admin/elearning/courses/{course['id']}/preview?version={course['version']}&activity={activity['id']}"
        self.assertEqual(self.client.get(url).status_code, 302)
        self._admin_login()
        with patch('elearning_native.web.NativeElearningStore', side_effect=AssertionError('Preview must not track')):
            page = self.client.get(url).get_data(as_text=True)
            config = json.loads(re.search(r'<script id="nativePreviewConfig" type="application/json">(.*?)</script>', page, re.S).group(1))
            body = {'practice_answers': correct_answers(activity['practice'])}
            self.assertEqual(self.client.post(config['answerUrl'], json=body).status_code, 403)
            result = self.client.post(config['answerUrl'], json=body, headers={'X-Elearning-CSRF': config['csrfToken']})
            self.assertTrue(result.json['correct'])
            with self.client.session_transaction() as session:
                session['admin_role'] = 'viewer'
            self.assertEqual(self.client.post(config['answerUrl'], json=body, headers={'X-Elearning-CSRF': config['csrfToken']}).status_code, 403)
        self.assertIsNone(self.saved_data)
