"""Publication checks for independent VTC v6 assessments and retained editions."""
import collections
import copy
from datetime import datetime
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import unittest
from urllib.parse import urlparse

from elearning_native.exams import grade_exam, public_exam

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('vtc_v6_exams', ROOT / 'scripts/vtc/revision_v6/exams.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
DIRECTORY = ROOT / 'elearning_native/vtc/exams' / BUILDER.VERSION


def correct_text(question):
    return next(option['text'] for option in question['options'] if option['id'] == question['answer'])


def amount(value):
    return f'{value:,}'.replace(',', ' ')


class VtcV6ExamsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exams = {path.stem: json.loads(path.read_text()) for path in DIRECTORY.glob('*.json')}
        cls.final = cls.exams['vtc-final']['questions']
        cls.english = cls.exams['vtc-e']['questions']
        cls.questions = {q['id']: q for q in cls.final + cls.english}

    def test_published_final_is_not_a_module_sample_or_numeric_rewording(self):
        self.assertEqual({'vtc-' + letter for letter in 'abcdefgh'} | {'vtc-final'}, set(self.exams))
        report = BUILDER.validate_new_questions(self.exams)
        self.assertEqual(100, report['new_final_questions'])
        self.assertEqual(30, report['new_english_module_questions'])
        prior = {BUILDER.normal(p, ignore_numbers=True) for p in BUILDER._previous_prompts(ROOT)}
        for q in self.final + self.english:
            self.assertNotIn(BUILDER.normal(q['prompt'], ignore_numbers=True), prior, q['id'])
        module_prompts = {BUILDER.normal(q['prompt']) for eid, ex in self.exams.items() if eid != 'vtc-final' for q in ex['questions']}
        self.assertFalse({BUILDER.normal(q['prompt']) for q in self.final} & module_prompts)
        self.assertEqual(BUILDER.FINAL_DISTRIBUTION, dict(collections.Counter(q['module'] for q in self.final)))
        self.assertTrue(all(q['origin'] == 'pedagogical-original-v6' for q in self.final + self.english))

    def test_all_new_cases_have_resolvable_lessons_three_choices_and_sources(self):
        manifest = json.loads((ROOT / 'elearning_native/vtc/manifest.json').read_text())
        lessons = {lesson['ref'] for m in manifest['modules'] for lesson in m['lessons']}
        expected_refs = {f'E.{i:02d}' for i in range(1, 13)}
        self.assertEqual(expected_refs, {ref for q in self.english for ref in q['lesson_refs']})
        for q in self.final + self.english:
            self.assertEqual(3, len(q['options']))
            self.assertEqual(3, len({o['id'] for o in q['options']}))
            self.assertIn(q['answer'], {o['id'] for o in q['options']})
            self.assertTrue(set(q['lesson_refs']) <= lessons)
            self.assertTrue(all(ref.startswith(q['module'] + '.') for ref in q['lesson_refs']))
            self.assertTrue(q['sources'])
            for source in q['sources']:
                url = urlparse(source['url'])
                self.assertEqual('https', url.scheme)
                self.assertTrue(url.netloc)
                self.assertNotIn(url.path, ('', '/'))
                self.assertGreater(len(source['title']), 15)
            self.assertGreater(len(q['explanation']), 80)
            self.assertFalse({'context', 'image', 'audio'} & q.keys(), 'Standalone exams must include all necessary information in the prompt')
        positions = [next(i for i, o in enumerate(q['options']) if o['id'] == q['answer']) for q in self.english]
        self.assertEqual([10, 10, 10], [positions.count(i) for i in range(3)])

    def test_real_grader_preserves_meaning_after_options_are_reordered(self):
        for eid, exam in self.exams.items():
            self.assertEqual(BUILDER.VERSION, exam['version'])
            result = grade_exam(exam, {q['id']: q['answer'] for q in exam['questions']})
            self.assertEqual(len(exam['questions']), result['score'])
            self.assertEqual(100, result['percent'])
            shuffled = copy.deepcopy(exam)
            for q in shuffled['questions']:
                random.Random(q['id']).shuffle(q['options'])
            new_result = grade_exam(shuffled, {q['id']: q['answer'] for q in exam['questions']})
            self.assertEqual(result['score'], new_result['score'])
            for original, correction in zip(exam['questions'], new_result['corrections']):
                self.assertEqual(original['explanation'], correction['explanation'])
                self.assertEqual(correct_text(original), correct_text(correction))
            answers = {q['id']: q['answer'] for q in exam['questions']}
            first = exam['questions'][0]
            answers[first['id']] = next(o['id'] for o in first['options'] if o['id'] != first['answer'])
            self.assertEqual(len(exam['questions']) - 1, grade_exam(exam, answers)['score'])
            for public in public_exam(exam)['questions']:
                self.assertFalse({'answer', 'explanation', 'sources', 'lesson_refs'} & public.keys())

    def test_worked_financial_and_timeline_answers(self):
        def answer(ref, number):
            return correct_text(self.questions[f'v6-final-{ref.lower()}-{number:02d}'])
        self.assertIn(amount(7500 - 4000) + ' €', answer('b', 2))
        equity_after_payment = (41000 - 3000) - (29000 - 3000)
        self.assertEqual(amount(equity_after_payment) + ' €.', answer('b', 3))
        self.assertIn(amount(9600 - 7100) + ' €', answer('b', 4))
        self.assertIn(str(40 - (52 - 18)) + ' €', answer('b', 5))
        ht = Decimal(121) / Decimal('1.10')
        self.assertEqual(f'{ht:.0f} € HT et {Decimal(121) - ht:.0f} € de TVA.', answer('b', 6))
        self.assertIn(str(900 - 700) + ' €', answer('b', 8))
        self.assertEqual(f'{1650 // 22} courses.', answer('b', 9))
        self.assertIn(amount(24 * 450) + ' €', answer('b', 10))
        self.assertIn(amount(3000 + 24 * 400) + ' €', answer('b', 10))
        self.assertTrue(answer('b', 11).startswith(str(80 + 200) + ' €'))
        self.assertEqual(str(350 + (2400 - 600) - 1900) + ' €.', answer('b', 14))
        self.assertEqual(f'Il passe de {900 // (50 - 30)} à {900 // (45 - 30)} courses.', answer('b', 15))
        self.assertIn(str(78 - 20) + ' €', answer('f', 3))
        self.assertEqual(str(780 - 156 - 24) + ' €.', answer('f', 5))
        self.assertIn(f'{4 / 20 * 100:.0f} % à {6 / 60 * 100:.0f} %', answer('f', 10))
        self.assertEqual(f'{180 // 6} € par client.', answer('f', 12))
        interval = datetime(2026, 10, 10, 0, 5) - datetime(2026, 10, 9, 23, 50)
        self.assertEqual(15, interval.total_seconds() / 60)
        self.assertIn('quinze minutes', answer('g', 5))

    def test_language_keys_do_not_change_roles_negations_or_amount_scope(self):
        expected = {
            'v6-final-e-01': 'La réservation est au nom de Green ; le passager se nomme Cole.',
            'v6-final-e-02': 'Four passengers.',
            'v6-final-e-03': '7:15 a.m.',
            'v6-final-d-09': 'envoyées',
            'v6-module-e-05': 'Midi, et non minuit.',
            'v6-module-e-25': 'Four.',
            'v6-module-e-30': 'Les clients sont en retard mais maintiennent leur besoin de transport.',
        }
        for qid, expected_text in expected.items():
            self.assertEqual(expected_text, correct_text(self.questions[qid]))

    def test_all_45_historical_exam_files_are_byte_identical(self):
        base = ROOT / 'elearning_native/vtc/exams'
        paths = sorted(p for p in base.glob('*/*.json') if p.parent.name in BUILDER.PREVIOUS_EXAM_VERSIONS)
        self.assertEqual(45, len(paths))
        digest = hashlib.sha256()
        for path in paths:
            digest.update(str(path.relative_to(base)).encode())
            digest.update(b'\0')
            digest.update(path.read_bytes())
            digest.update(b'\0')
        self.assertEqual('2205b3e56ece837f8846f120c2960b0958a2e95f79663d1bfbe58ec1b358f961', digest.hexdigest())


if __name__ == '__main__':
    unittest.main()
