"""Required VTC learning and optional work must remain separate and authoritative."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from elearning_native import vtc
from elearning_native.practice import grade_practice, public_practice
from elearning_native.store import NativeElearningStore
from tests import test_native_elearning_web as web_tests
from tests.test_native_elearning_practice import correct_answers
from tests.test_native_elearning_vtc105 import script_config

VERSION = '20261010-vtc-v6-pedagogie'
BASE = '20261007-vtc-v5-annales'
DATA = Path(vtc.__file__).parent / 'vtc'


def activities(course):
    return [a for s in course['sections'] for a in s['activities']]


class PathContentTests(unittest.TestCase):
    def test_lighter_path_preserves_lessons_notes_and_all_listening_supports(self):
        manifest = vtc.curriculum_manifest()
        total = optional = 0
        for module in manifest['modules']:
            course = vtc.load_bundled_course(module['id'], VERSION)
            before = vtc.load_bundled_course(module['id'], BASE)
            old_lessons = {a['id']: a['vtc'].get('annales_notes', []) for a in activities(before) if a.get('vtc', {}).get('kind') == 'lesson'}
            self.assertEqual(course['activity_order'], before['activity_order'])
            self.assertEqual(course['required_minutes'], 0)
            self.assertEqual(sum(a['planned_minutes'] for a in activities(course)), course['planned_minutes'])
            bank = json.loads((DATA / 'training' / VERSION / (course['id'] + '.json')).read_text())
            extras = {a['id']: a for a in bank['activities']}
            for a in activities(course):
                if a['id'] in old_lessons:
                    self.assertEqual(a['vtc'].get('annales_notes', []), old_lessons[a['id']])
                p = a.get('practice')
                if not p:
                    continue
                self.assertTrue(grade_practice(p, correct_answers(p))['correct'], a['id'])
                self.assertNotIn('"answer"', json.dumps(public_practice(p)))
                if a['id'].endswith('-dossier'):
                    self.assertLessEqual(len(p['exercises']), 8)
                total += len(p['exercises'])
                if a['id'] in extras:
                    extra = extras[a['id']]['practice']
                    self.assertFalse({e['id'] for e in p['exercises']} & {e['id'] for e in extra['exercises']})
                    self.assertTrue(grade_practice(extra, correct_answers(extra))['correct'])
                    optional += len(extra['exercises'])
            if module['letter'] == 'E':
                audios = {ex['audio'] for a in activities(course) for ex in a.get('practice', {}).get('exercises', []) if ex.get('audio')}
                self.assertEqual(len(audios), 48)
                self.assertTrue(audios <= set(course['assets']))
                self.assertTrue(all(vtc.bundled_asset(course['id'], VERSION, audio) for audio in audios))
        self.assertGreaterEqual(total, 1100)
        self.assertLessEqual(total, 1400)
        self.assertEqual(total, manifest['exercise_count'])
        self.assertEqual(optional, manifest['free_exercise_count'])
        self.assertGreater(optional, 500)
        self.assertEqual(sum(m['planned_minutes'] for m in manifest['modules']), manifest['planned_minutes'])


class AdaptiveWebTests(unittest.TestCase):
    tearDown = web_tests.NativeElearningWebTests.tearDown
    _public_login = web_tests.NativeElearningWebTests._public_login
    _player_config = staticmethod(web_tests.NativeElearningWebTests._player_config)
    _api_post = web_tests.NativeElearningWebTests._api_post

    def setUp(self):
        web_tests.NativeElearningWebTests.setUp(self)
        self.course = vtc.load_bundled_course('academy-vtc-a', VERSION)
        self.data['sessions'][0].update(training_type='VTC', aps_native_course_id=self.course['id'], aps_native_course_version=VERSION)
        self.access = {'session_id': 'session-aps', 'trainee_id': 'trainee-1', 'course_id': self.course['id'], 'course_version': VERSION}
        self.store = NativeElearningStore(self.persist_dir / 'native_elearning/tracking.sqlite3')
        self._public_login()

    def seed_successful_prior_learning(self):
        for a in activities(self.course):
            if a['id'].endswith('-revision'):
                return a
            answer = None
            if a.get('practice'):
                answer = {'practice_answers': correct_answers(a['practice']), 'practice_correct': True,
                          'practice_diagnostics': {ex['id']: {'first_correct': True, 'correct': True, 'competency': ex.get('competency', ''), 'attempts': 1}
                                                   for ex in a['practice']['exercises']}}
            self.store.complete_activity(self.access, a['id'], activity_order=self.course['activity_order'], scored_activity_ids=[], mastery_score=80, answer=answer)
        raise AssertionError('Review missing')

    def test_actual_page_and_completion_use_the_same_stable_server_selection(self):
        review = self.seed_successful_prior_learning()
        url = '/espace/public-token/elearning/academy-vtc-a?activity=' + review['id']
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        config = self._player_config(page)
        journey = script_config(page, 'vtcJourneyConfig')
        selected_ids = {ex['id'] for ex in journey['practice']['exercises']}
        self.assertEqual(len(selected_ids), 4)
        answers = {k: v for k, v in correct_answers(review['practice']).items() if k in selected_ids}
        complete = config['completeUrl']
        self.assertEqual(self._api_post(complete, config, practice_answers={}).status_code, 400)
        self.assertEqual(self._api_post(complete, config, practice_answers=dict(list(answers.items())[:1]), selected_ids=list(selected_ids)).status_code, 400)
        result = self._api_post(config['practiceUrl'], config, practice_answers=answers)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json['correct'])
        again = script_config(self.client.get(url), 'vtcJourneyConfig')
        self.assertEqual({ex['id'] for ex in again['practice']['exercises']}, selected_ids)
        done = self._api_post(complete, config, practice_answers=answers)
        self.assertEqual(done.status_code, 200)
        self.assertIn(review['id'], done.json['progress']['completed_activity_ids'])
        saved = copy.deepcopy(done.json['progress']['answers'][review['id']])
        self.assertEqual(set(saved['practice_answers']), selected_ids)
        self.assertEqual(done.json['progress']['active_seconds'], 0)
        self.assertEqual(script_config(self.client.get(url), 'vtcJourneyConfig')['saved'], saved)


class CurrentEditionPreviewTests(unittest.TestCase):
    setUp = web_tests.NativeElearningWebTests.setUp
    tearDown = web_tests.NativeElearningWebTests.tearDown
    _admin_login = web_tests.NativeElearningWebTests._admin_login

    def test_all_current_activities_render_without_tracking_or_answer_keys(self):
        self._admin_login()
        count = 0
        with patch('elearning_native.web.NativeElearningStore', side_effect=AssertionError('Preview must not track')):
            for cid in vtc.curriculum_ids():
                course = vtc.load_bundled_course(cid, VERSION)
                for aid in course['activity_order']:
                    response = self.client.get(f'/admin/elearning/courses/{cid}/preview?version={VERSION}&activity={aid}')
                    self.assertEqual(response.status_code, 200, aid)
                    self.assertNotIn('"answer":', response.text, aid)
                    self.assertNotIn('"consequences":', response.text, aid)
                    self.assertIn('Entraînement libre du module', response.text, aid)
                    count += 1
        self.assertEqual(count, 336)
        self.assertIsNone(self.saved_data)


if __name__ == '__main__':
    unittest.main()
