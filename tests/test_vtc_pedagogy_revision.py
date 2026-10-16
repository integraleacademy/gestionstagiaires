"""Version-building checks; never rewrite learner course files during tests."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('vtc_improve_pedagogy', ROOT / 'scripts/vtc/annales/improve_pedagogy.py')
PEDAGOGY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PEDAGOGY)
V4 = '20261007-vtc-v4-visuals'


def activities(course):
    return [a for s in course['sections'] for a in s.get('activities', [])]


def exercises(course):
    return [ex for a in activities(course) for ex in a.get('practice', {}).get('exercises', [])]


class PedagogyRevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.originals = [json.loads(path.read_text()) for path in sorted((ROOT / 'elearning_native/vtc/courses').glob(f'*/{V4}.json'))]
        cls.courses = copy.deepcopy(cls.originals)
        cls.audits = [PEDAGOGY.improve_course(course) for course in cls.courses]

    def test_redundancy_removed_per_dossier_without_changing_retained_ids(self):
        self.assertEqual(381, sum(a['removed_duplicates'] for a in self.audits))
        for before, after in zip(self.originals, self.courses):
            old_activities = {a['id']: a for a in activities(before)}
            for activity in activities(after):
                practice = activity.get('practice', {})
                new = practice.get('exercises', [])
                old = old_activities[activity['id']].get('practice', {}).get('exercises', [])
                old_ids = {ex['id'] for ex in old}
                self.assertTrue({ex['id'] for ex in new}.issubset(old_ids))
                if practice.get('mode') == 'journey':
                    signatures = [PEDAGOGY.exercise_signature(ex) for ex in new]
                    self.assertEqual(len(signatures), len(set(signatures)))
                else:
                    self.assertEqual([ex['id'] for ex in old], [ex['id'] for ex in new])
            self.assertEqual(len(exercises(after)), after['counts']['exercises'])
            self.assertEqual(sum(len(ex.get('rows', [])) or 1 for ex in exercises(after)), after['counts']['decisions'])

    def test_method_tasks_are_grounded_in_each_lesson(self):
        self.assertEqual(84, sum(a['specific_methods'] for a in self.audits))
        for course in self.courses:
            lessons = {a['vtc']['ref']: a['vtc'] for a in activities(course) if a.get('vtc', {}).get('kind') == 'lesson'}
            for ex in exercises(course):
                if ex.get('kind') != 'order':
                    continue
                self.assertNotEqual('Retrouvez l’ordre des opérations dans cette procédure pédagogique.', ex['prompt'])
                lesson = lessons[ex['competency']]
                expected = {f'r{i}': (f'{s["title"]} : {s["text"]}', f'p{i}') for i, s in enumerate(lesson['visual_steps'])}
                self.assertEqual(expected, {row['id']: (row['text'], row['answer']) for row in ex['rows']})
                self.assertNotEqual([row['answer'] for row in ex['rows']], [o['id'] for o in ex['options']])
                self.assertIn(lesson['title'], ex['prompt'])

    def test_b_distractors_and_numeric_feedback_are_actionable(self):
        b = next(c for c in self.courses if c['id'] == 'academy-vtc-b')
        self.assertEqual(63, sum(a['replaced_distractors'] for a in self.audits))
        numeric_feedback = []
        for ex in exercises(b):
            if ex['kind'] != 'single':
                continue
            option_ids = {o['id'] for o in ex['options']}
            self.assertIn(ex['answer'], option_ids)
            self.assertEqual(option_ids, set(ex['consequences']))
            for option in ex['options']:
                if option['id'] != ex['answer']:
                    self.assertNotIn(option['text'], PEDAGOGY.DISTRACTORS)
                self.assertIn(ex['explanation'], ex['consequences'][option['id']])
            numeric_feedback.extend(v for v in ex['consequences'].values() if v.startswith('Votre valeur est'))
        self.assertGreater(len(numeric_feedback), 100)
        self.assertTrue(all('du résultat attendu.' in value for value in numeric_feedback))

    def test_improvement_is_idempotent_and_preserves_versions_and_duration(self):
        for original, course in zip(self.originals, self.courses):
            previous = copy.deepcopy(course)
            audit = PEDAGOGY.improve_course(course)
            self.assertEqual(previous, course)
            self.assertEqual(0, audit['removed_duplicates'])
            self.assertEqual(0, audit['specific_methods'])
            self.assertEqual(0, audit['replaced_distractors'])
            for key in original:
                if key not in {'sections', 'counts'}:
                    self.assertEqual(original[key], course[key])

    def test_h_has_thirty_independent_valid_scenarios_covering_all_lessons(self):
        data = json.loads((ROOT / 'scripts/vtc/annales/exam-h-independent.json').read_text())
        questions = data['questions']
        prior = {PEDAGOGY._normal(ex['prompt']) for course in self.originals for ex in exercises(course)}
        for path in (ROOT / f'elearning_native/vtc/exams/{V4}').glob('*.json'):
            prior.update(PEDAGOGY._normal(q['prompt']) for q in json.loads(path.read_text())['questions'])
        self.assertEqual(30, len(questions))
        self.assertEqual(30, len({q['id'] for q in questions}))
        self.assertEqual({f'H.{i:02d}' for i in range(1, 13)}, {ref for q in questions for ref in q['lesson_refs']})
        correct_positions = []
        for q in questions:
            self.assertNotIn(PEDAGOGY._normal(q['prompt']), prior)
            self.assertEqual('H', q['module'])
            self.assertEqual(3, len(q['options']))
            self.assertEqual(3, len({o['id'] for o in q['options']}))
            self.assertEqual(3, len({o['text'] for o in q['options']}))
            correct_positions.append([o['id'] for o in q['options']].index(q['answer']))
            self.assertGreater(len(q['explanation']), 100)
            self.assertTrue(q['sources'])
            for source in q['sources']:
                url = urlparse(source['url'])
                self.assertEqual('https', url.scheme)
                self.assertTrue(url.netloc.endswith('.gouv.fr') or url.netloc == 'www.cnil.fr')
                self.assertNotEqual('/', url.path)
                self.assertTrue(source['title'])
        self.assertEqual([10, 10, 10], [correct_positions.count(i) for i in range(3)])


if __name__ == '__main__':
    unittest.main()
