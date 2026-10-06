"""New edition: content integrity, targeted remediation and progression gate."""
import copy
import json
import unittest
from unittest.mock import patch

from elearning_native.academy import curriculum_manifest, load_bundled_course
from elearning_native.importer import CourseCatalog
from elearning_native.practice import grade_practice, public_practice
from tests.test_native_elearning_practice import correct_answers
from tests import test_native_elearning_web as web_tests


class EnrichmentTests(unittest.TestCase):
    def test_all_cases_have_distinct_missions_documents_and_unseen_review(self):
        manifest = curriculum_manifest()
        missions, drills = set(), set()
        for module in manifest['modules']:
            current = load_bundled_course(module['id'])
            old = load_bundled_course(module['id'], '20261004-aps62-v2')
            self.assertEqual(len(old['activity_order']), module['hours'] * 7)
            self.assertFalse(old['settings'].get('require_correct_answers'))
            self.assertTrue(current['settings']['require_correct_answers'])
            self.assertEqual(current['introduction'], old['introduction'])
            for section in current['sections']:
                activities = section['activities']
                self.assertEqual(len(activities), 9)
                self.assertTrue(activities[0]['academy']['deepening'])
                mission = activities[2]['practice']
                missions.add(activities[2]['academy']['case'])
                self.assertTrue(mission['sequential'])
                self.assertEqual(len(mission['exercises']), 5)
                docs, journal = activities[6]['practice'], activities[7]['practice']
                self.assertEqual(len(docs['documents']), 3)
                self.assertEqual(len(journal['exercises']), 6)
                self.assertTrue(journal['journal'])
                drills.add(mission['exercises'][1]['remediation']['prompt'])
                self.assertNotEqual(mission['exercises'][1]['remediation']['prompt'], activities[2]['academy']['case'])
                self.assertNotIn('repere-1', [e['id'] for e in activities[5]['practice']['exercises']])
                for activity in activities:
                    if not activity.get('practice'):
                        continue
                    practice = activity['practice']
                    public = json.dumps(public_practice(practice))
                    self.assertNotIn('"answer"', public)
                    self.assertNotIn('"remediation"', public)
                    self.assertTrue(grade_practice(practice, correct_answers(practice))['correct'])
                    for ex in practice['exercises']:
                        self.assertEqual(len({o['text'] for o in ex['options']}), len(ex['options']))
        self.assertEqual(len(missions), 62)
        self.assertEqual(len(drills), 62)

    def test_reviews_only_target_errors_and_are_marked_on_the_server(self):
        p = load_bundled_course('academy-aps62-01')['sections'][0]['activities'][2]['practice']
        answers = correct_answers(p)
        self.assertEqual(grade_practice(p, answers)['review'], [])
        wrong = {**answers, 'decision': next(o['id'] for o in p['exercises'][1]['options'] if o['id'] != answers['decision'])}
        result = grade_practice(p, wrong)
        self.assertFalse(result['correct'])
        self.assertEqual([r['id'] for r in result['review']], ['decision'])
        self.assertNotIn('answer', result['review'][0])
        self.assertNotIn('correct', result['review'][0])
        drill = p['exercises'][1]['remediation']
        reviewed = grade_practice(p, wrong, {'decision': drill['answer']})
        self.assertTrue(reviewed['review'][0]['correct'])
        self.assertFalse(reviewed['correct'], 'a review never bypasses the original exercise')
        for value in [[], {'unknown': '1'}, {'decision': True}, {'decision': 'unknown'}]:
            with self.assertRaises(ValueError):
                grade_practice(p, wrong, value)

    def test_regulatory_totals_evidence_and_explicit_limits(self):
        review = curriculum_manifest()['regulatory_review']
        self.assertEqual(sum(m['ministry_minutes'] for m in review['modules']), 3720)
        self.assertEqual(sum(m['adef_minutes'] for m in review['modules']), 3030)
        self.assertEqual(review['modules'][11]['coverage'], 'Complément requis')
        for module in review['modules']:
            course = load_bundled_course(module['id'], review['edition'])
            for evidence in module['evidence']:
                self.assertIn(evidence['section'] + '-comprendre', course['activity_order'])


class EnrichmentWebTests(unittest.TestCase):
    setUp = web_tests.NativeElearningWebTests.setUp
    tearDown = web_tests.NativeElearningWebTests.tearDown
    _admin_login = web_tests.NativeElearningWebTests._admin_login
    _public_login = web_tests.NativeElearningWebTests._public_login
    _player_config = staticmethod(web_tests.NativeElearningWebTests._player_config)
    _api_post = web_tests.NativeElearningWebTests._api_post

    def test_incorrect_question_cannot_unlock_the_next_activity(self):
        course = copy.deepcopy(self.course)
        real = load_bundled_course('academy-aps62-01')['sections'][0]['activities'][3]
        activity = course['sections'][0]['activities'][0]
        activity.update({k: copy.deepcopy(v) for k, v in real.items() if k != 'id'})
        course['settings']['require_correct_answers'] = True
        original = CourseCatalog.load_course
        def load(catalog, ident, version=None):
            return copy.deepcopy(course) if ident == course['id'] else original(catalog, ident, version)
        self._public_login()
        with patch.object(CourseCatalog, 'load_course', load):
            config = self._player_config(self.client.get(f"/espace/public-token/elearning/{course['id']}"))
            good = [o['id'] for o in activity['options'] if o['is_correct']]
            bad = [o['id'] for o in activity['options'] if not o['is_correct']][:1]
            response = self._api_post(config['answerUrl'], config, answer={'selected': bad})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json['retry_required'])
            self.assertNotIn(activity['id'], response.json['progress']['completed_activity_ids'])
            self.assertNotIn(activity['id'], response.json['progress']['answers'])
            correct = self._api_post(config['answerUrl'], config, answer={'selected': good})
            self.assertTrue(correct.json['correct'])
            self.assertIn(activity['id'], correct.json['progress']['completed_activity_ids'])

    def test_catalog_shows_limits_and_current_counts_without_changing_assignments(self):
        self._admin_login()
        response = self.client.get('/admin/elearning')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('558 activités', page)
        self.assertIn('Complément requis', page)
        self.assertIn('50 h 30', page)
        self.assertIsNone(self.saved_data)
