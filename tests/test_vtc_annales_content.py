"""Publication gates for full PDF coverage, answer semantics and immutable editions."""
import copy
import hashlib
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from elearning_native import annales

ROOT = Path(__file__).resolve().parents[1] / 'elearning_native/vtc'
VERSION = '20261007-vtc-v5-annales'
EXPECTED = {'annales-2020': (7, 107), 'annales-2021': (7, 107), 'annales-2022': (7, 107),
            'sujet-2023-a': (1, 15), 'sujet-2023-b': (1, 18), 'sujet-2023-c': (1, 20),
            'sujet-2023-d': (1, 10), 'sujet-2023-e': (1, 20)}
# Aggregate digest includes relative filenames and exact file bytes. Pinned
# learner editions must not acquire even seemingly harmless content changes.
IMMUTABLE = {
    '20261006-vtc-v1': 'd8cfd8dcf455e8c11f1d2fedfd92755a56780e8759e9218a90a1a19f2b95366b',
    '20261006-vtc-v2': '96bc8ba5fe3315af0ba7cf400613ea966f08328d67b68b7e4248c1a7051498a6',
    '20261006-vtc-v3-105h': 'a71b384894990af00cc607760695f2790bcb69fa88bd1bef0704e84534a80ed1',
    '20261007-vtc-v4-visuals': '54c6f873b28af5e4f35471d3368c5227dcf859a01f1507a405c84e16b9f99fcc',
}


class AnnalesContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.documents = annales.sources()
        cls.sections = [s for d in cls.documents for s in d['sections']]
        cls.questions = [q for s in cls.sections for q in s['questions']]

    def test_all_eight_pdfs_and_every_expected_section_are_present(self):
        self.assertEqual(EXPECTED, {d['id']: (len(d['sections']), sum(len(s['questions']) for s in d['sections'])) for d in self.documents})
        self.assertEqual(26, len(self.sections))
        self.assertEqual(404, annales.validate_bank())
        self.assertEqual(404, len({q['id'] for q in self.questions}))
        self.assertEqual(26, len({s['id'] for s in self.sections}))
        self.assertEqual(8, len({d['source_filename'] for d in self.documents}))
        self.assertEqual(8, len({d['source_sha256'] for d in self.documents}))
        for doc in self.documents:
            self.assertRegex(doc['source_sha256'], r'^[a-f0-9]{64}$')
            self.assertTrue(doc['source_filename'].lower().endswith('.pdf'))
            for section in doc['sections']:
                self.assertIn(section['module'], 'ABCDEFG')
                self.assertEqual(list(range(1, len(section['questions']) + 1)), [q['number'] for q in section['questions']])
                for q in section['questions']:
                    self.assertGreater(q['page'], 0)
                    self.assertIn(q['original_kind'], ('qcm', 'qrc'))
                    self.assertTrue(q['prompt'].strip())
                    self.assertNotRegex(q['prompt'], r'(?i)copie de candidat|référence copie')

    def test_full_corrections_and_multiple_choice_are_graded_identically(self):
        multiple = 0
        for section in self.sections:
            answers = {q['id']: list(reversed(q['answers'])) for q in section['questions'] if q['status'] == 'active'}
            result = annales.grade(section, answers)
            self.assertEqual(len(answers), result['score'])
            self.assertEqual(len(answers), result['total'])
            self.assertEqual(len(section['questions']) - len(answers), result['historical_count'])
            for q, correction in zip(section['questions'], result['corrections']):
                self.assertEqual(q['answers'], correction['answers'])
                self.assertEqual(q['explanation'], correction['explanation'])
                self.assertEqual(q['learning_points'], correction['learning_points'])
                self.assertEqual(len(q['answers']), len(set(q['answers'])))
                self.assertTrue(set(q['answers']) <= {o['id'] for o in q['options']})
                if q['kind'] == 'single':
                    self.assertEqual(1, len(q['answers']))
                if q['status'] == 'historical':
                    self.assertIsNone(correction['correct'])
                    self.assertTrue(q['update_note'])
                elif len(q['answers']) > 1:
                    multiple += 1
                    self.assertEqual('multiple', q['kind'])
                    partial = copy.deepcopy(answers)
                    partial[q['id']] = q['answers'][:-1]
                    self.assertEqual(result['score'] - 1, annales.grade(section, partial)['score'])
                    wrong = next((o['id'] for o in q['options'] if o['id'] not in q['answers']), None)
                    if wrong:
                        partial[q['id']] = q['answers'] + [wrong]
                        self.assertEqual(result['score'] - 1, annales.grade(section, partial)['score'])
            public = annales.public_section(section)
            for question in public['questions']:
                self.assertFalse({'answers', 'explanation', 'learning_points', 'update_note', 'original_answer'} & question.keys())
        self.assertGreater(multiple, 40)

    def test_invalid_correction_and_image_paths_fail_publication(self):
        for changes in ({'kind': 'essay'}, {'kind': 'single', 'answers': ['a', 'b']},
                        {'answers': ['a', 'a']}, {'image': '../manifest.json'},
                        {'image': 'media/vtc/annales/../../../../manifest.json'},
                        {'image': 'media/vtc/annales/missing.png'}):
            documents = copy.deepcopy(self.documents)
            documents[0]['sections'][0]['questions'][0].update(changes)
            with patch('elearning_native.annales._sources', return_value=documents):
                with self.assertRaises(ValueError):
                    annales.validate_bank()
        image_questions = [q for q in self.questions if q.get('image')]
        self.assertTrue(image_questions)
        assets = (ROOT / 'assets/media/vtc/annales').resolve()
        for q in image_questions:
            path = (ROOT / 'assets' / q['image']).resolve()
            self.assertIn(assets, path.parents)
            self.assertTrue(path.is_file())
            self.assertIn(path.suffix.lower(), ('.png', '.jpg', '.jpeg', '.webp'))

    def test_every_question_is_taught_in_actual_v5_lessons(self):
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        refs = {lesson['ref'] for module in manifest['modules'] for lesson in module['lessons']}
        self.assertEqual(96, len(refs))
        self.assertEqual(VERSION, manifest['version'])
        taught = {}
        for module in manifest['modules']:
            self.assertEqual(VERSION, module['version'])
            self.assertIn('20261007-vtc-v4-visuals', module['previous_versions'])
            course = json.loads((ROOT / 'courses' / module['id'] / (VERSION + '.json')).read_text())
            for section in course['sections']:
                for activity in section['activities']:
                    lesson = activity.get('vtc', {})
                    if lesson.get('kind') == 'lesson':
                        taught[lesson['ref']] = {n['id']: n for n in lesson.get('annales_notes', [])}
        self.assertEqual(refs, set(taught))
        for q in self.questions:
            self.assertTrue(set(q['lesson_refs']) <= refs, q['id'])
            self.assertTrue(q['lesson_refs'], q['id'])
            for ref in q['lesson_refs']:
                self.assertIn(q['id'], taught[ref], (q['id'], ref))
                note = taught[ref][q['id']]
                self.assertEqual(q['learning_points'], note['learning_points'])
                self.assertEqual(q['status'], note['status'])
                self.assertEqual(q['update_note'], note['update_note'])
                self.assertTrue(all(str(point).strip() for point in note['learning_points']))

    def test_older_course_and_exam_editions_are_byte_identical(self):
        for version, expected in IMMUTABLE.items():
            paths = sorted([*ROOT.glob(f'courses/*/{version}.json'), *ROOT.glob(f'exams/{version}/*.json')])
            self.assertEqual(17, len(paths))
            digest = hashlib.sha256()
            for path in paths:
                digest.update(str(path.relative_to(ROOT)).encode())
                digest.update(b'\0')
                digest.update(path.read_bytes())
                digest.update(b'\0')
            self.assertEqual(expected, digest.hexdigest(), version)


if __name__ == '__main__':
    unittest.main()

class AnnalesEditionTests(unittest.TestCase):
    def test_new_exams_are_independent_from_workshops_and_have_valid_review_paths(self):
        from elearning_native.exams import grade_exam, public_exam
        from elearning_native.practice import grade_practice
        from tests.test_native_elearning_practice import correct_answers
        import unicodedata
        def normal(text):
            return re.sub(r'[^a-z0-9]+','',unicodedata.normalize('NFKD',text).encode('ascii','ignore').decode().lower())
        courses=[json.loads(p.read_text()) for p in ROOT.glob(f'courses/*/{VERSION}.json')]
        workshop_prompts=set();refs=set();exercises=0
        for course in courses:
            for section in course['sections']:
                for activity in section['activities']:
                    if activity.get('vtc',{}).get('kind')=='lesson':refs.add(activity['vtc']['ref'])
                    if activity.get('practice'):
                        practice=activity['practice']
                        self.assertTrue(grade_practice(practice,correct_answers(practice))['correct'],activity['id'])
                        exercises+=len(practice['exercises'])
                        workshop_prompts.update(normal(e['prompt']) for e in practice['exercises'])
        self.assertEqual(1979,exercises)
        docs={q['id']:q for d in annales.sources() for s in d['sections'] for q in s['questions']}
        exams=list((ROOT/'exams'/VERSION).glob('*.json'));self.assertEqual(9,len(exams))
        for path in exams:
            exam=json.loads(path.read_text());questions=exam['questions']
            self.assertEqual(100 if exam['id']=='vtc-final' else 30,len(questions))
            self.assertEqual(len(questions),len({normal(q['prompt']) for q in questions}))
            self.assertFalse({normal(q['prompt']) for q in questions}&workshop_prompts,exam['id'])
            self.assertEqual(100,grade_exam(exam,{q['id']:q['answer'] for q in questions})['percent'])
            for q in questions:
                self.assertTrue(q['lesson_refs']);self.assertTrue(set(q['lesson_refs'])<=refs)
                self.assertEqual(len(q['options']),len({o['text'] for o in q['options']}))
                if q.get('source_question_id'):
                    original=docs[q['source_question_id']]
                    self.assertEqual('active',original['status'])
                    self.assertEqual([q['answer']],original['answers'])
                if exam['id']=='vtc-final':self.assertIn(q['module'],'ABCDEFG')
            for q in public_exam(exam)['questions']:
                self.assertFalse({'answer','explanation','lesson_refs','sources'}&q.keys())
