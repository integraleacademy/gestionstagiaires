import json
import unittest

from elearning_native.academy import ROOT, curriculum_manifest, load_bundled_course
from elearning_native.practice import grade_practice, public_practice
from scripts.aps62_v6.content import courses
from tests import test_native_elearning_web as web_tests


class GuidedContentTests(unittest.TestCase):
    def test_all_dossiers_are_visual_and_missions_use_concrete_choices(self):
        seen, practices, journals = set(), 0, 0
        for module in curriculum_manifest()['modules']:
            course = load_bundled_course(module['id'])
            previous = load_bundled_course(module['id'], '20261006-aps62-v5')
            self.assertEqual(course['activity_order'], previous['activity_order'])
            self.assertEqual(course['planned_minutes'], previous['planned_minutes'])
            for section in course['sections']:
                seen.add(section['id'])
                visual = section['activities'][0]['academy']['visual_guide']
                self.assertTrue(all(visual[k] for k in ('situation','action','why','mistake')))
                self.assertEqual(len(visual['terms']), 3)
                for activity in section['activities']:
                    if not activity.get('practice'):
                        continue
                    practice = activity['practice']; practices += 1
                    journals += bool(practice.get('journal'))
                    self.assertEqual(practice['mode'], 'guided')
                    public = public_practice(practice)
                    self.assertEqual(public['mode'], 'guided')
                    self.assertNotIn('answer', public['exercises'][0])
                    self.assertNotIn('branches', public['exercises'][0])
                    self.assertNotIn('explanation', public['exercises'][0])
                    if activity['academy']['kind'] == 'workshop':
                        self.assertEqual(len(practice['exercises']), 3)
                        for exercise in practice['exercises']:
                            self.assertEqual(len(exercise['options']), 2)
                            self.assertNotIn('Le poste doit maintenant', exercise['context'])
                            self.assertNotIn('fait établi', exercise['prompt'])
        self.assertEqual(len(seen), 62)
        self.assertEqual((practices, journals), (142, 4))

    def test_partial_correction_cannot_complete_the_activity(self):
        practice = load_bundled_course('academy-aps62-01')['sections'][0]['activities'][2]['practice']
        first = practice['exercises'][0]
        answer = {first['id']:first['answer']}
        self.assertTrue(grade_practice(practice, answer, step=first['id'])['correct'])
        with self.assertRaises(ValueError):
            grade_practice(practice, answer)
        with self.assertRaises(ValueError):
            grade_practice(practice, answer, step='unknown')
        wrong = next(o['id'] for o in first['options'] if o['id'] != first['answer'])
        result = grade_practice(practice, {first['id']:wrong}, step=first['id'])
        self.assertFalse(result['correct'])
        self.assertTrue(result['feedback'][0]['explanation'])
        self.assertTrue(result['review'])
        all_answers = {e['id']:e['answer'] for e in practice['exercises']}
        self.assertTrue(grade_practice(practice, all_answers)['correct'])

    def test_all_long_video_scripts_are_substantive_and_course_only(self):
        scripts = courses()
        self.assertEqual(len(scripts), 62)
        self.assertEqual(scripts, json.loads((ROOT/'video_scripts_v6.json').read_text()))
        for row in scripts.values():
            self.assertGreaterEqual(len(row['transcript'].split()), 1000)
            self.assertGreaterEqual(len(row['scenes']), 12)
            self.assertNotRegex(row['transcript'].lower(), r'mettez.*pause|choisissez|répondez|à vous de décider')


class GuidedWebTests(unittest.TestCase):
    setUp = web_tests.NativeElearningWebTests.setUp
    tearDown = web_tests.NativeElearningWebTests.tearDown
    _admin_login = web_tests.NativeElearningWebTests._admin_login

    def test_public_page_contains_the_visuals_and_only_one_visible_question(self):
        self._admin_login()
        url = '/admin/elearning/courses/academy-aps62-01/preview'
        page = self.client.get(url, query_string={'activity':'aps62-01-01-comprendre'}).get_data(as_text=True)
        self.assertIn('aps-visual-scene', page)
        self.assertIn('Comparer les deux choix', page)
        self.assertNotIn('Fait de la situation', page)
        self.assertIn('Un exemple pour comprendre', page)
        page = self.client.get(url, query_string={'activity':'aps62-01-01-atelier'}).get_data(as_text=True)
        self.assertIn('Une seule question à la fois.', page)
        self.assertIn('js/aps62-guided.js', page)
        self.assertIn('data-exercise-id="decision" data-kind="single" hidden', page)
        self.assertIn('data-exercise-id="evolution" data-kind="single" hidden', page)
        self.assertNotIn('"answer":', page)


if __name__ == '__main__':
    unittest.main()
