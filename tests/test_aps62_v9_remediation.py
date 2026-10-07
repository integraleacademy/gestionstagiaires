"""Regression checks for the authored practice bank and its integration contract."""
import copy
import json
from collections import Counter
from pathlib import Path
import unittest

from scripts.aps62_v9.remediation import (
    apply_remediation, EXTRA_COUNTS, MAIN_IDS, REVISION, SECTIONS, _banks,
)

ROOT = Path(__file__).resolve().parents[1]


def source_courses():
    paths = sorted((ROOT / 'elearning_native/aps62/courses').glob('*/20261007-aps62-v8.json'))
    if len(paths) != 15:
        raise AssertionError('The 15 unchanged v8 sources are required for this migration test')
    return [json.loads(path.read_text(encoding='utf-8')) for path in paths]


def practices(course):
    return [a for s in course['sections'] for a in s['activities'] if a.get('practice')]


def length_rank(item):
    answer = next(o['text'] for o in item['options'] if o['id'] == item['answer'])
    others = [len(o['text']) for o in item['options'] if o['id'] != item['answer']]
    return 'shortest' if len(answer) < min(others) else 'longest' if len(answer) > max(others) else 'middle'


class APS62V9RemediationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = source_courses()
        cls.courses = [apply_remediation(copy.deepcopy(course)) for course in cls.sources]
        cls.activities = [a for c in cls.courses for a in practices(c)]
        cls.drills = [e['remediation'] for a in cls.activities for e in a['practice']['exercises']]
        cls.main = [e for a in cls.activities if a['id'].endswith('-atelier') for e in a['practice']['exercises']]

    def test_complete_explicit_bank(self):
        bank, distractors, answers, rows, _, _ = _banks()
        self.assertEqual(set(bank), set(SECTIONS) | set(EXTRA_COUNTS))
        self.assertEqual(len(rows), 384)
        self.assertEqual(len(self.activities), 142)
        self.assertEqual(len(self.main), 186)
        self.assertEqual(len(self.drills), 384)

    def test_each_case_and_its_choices_are_distinct(self):
        self.assertEqual(len({d['prompt'] for d in self.drills}), 384)
        for drill in self.drills:
            self.assertEqual(len(drill['options']), 3)
            self.assertEqual(len({o['text'] for o in drill['options']}), 3)
            self.assertEqual(sum(o['id'] == drill['answer'] for o in drill['options']), 1)
            self.assertTrue(drill['explanation'])
            self.assertTrue(drill['lesson'])
            correct = next(o['text'] for o in drill['options'] if o['id'] == drill['answer'])
            self.assertNotIn(correct, drill['lesson'])
            self.assertNotEqual(drill['explanation'], drill['lesson'])

    def test_preserves_navigation_context_and_document_tasks(self):
        for old, new in zip(self.sources, self.courses):
            self.assertEqual(old['activity_order'], new['activity_order'])
            self.assertEqual(old['required_minutes'], new['required_minutes'])
            self.assertEqual(old['planned_minutes'], new['planned_minutes'])
            for before, after in zip(practices(old), practices(new)):
                self.assertEqual(before['id'], after['id'])
                self.assertEqual(before['academy'], after['academy'])
                bp, ap = before['practice'], after['practice']
                self.assertEqual(bp.get('documents'), ap.get('documents'))
                self.assertEqual(bp.get('journal'), ap.get('journal'))
                self.assertEqual(ap['mode'], 'guided')
                self.assertTrue(ap['sequential'])
                self.assertEqual(ap['revision'], REVISION)
                for left, right in zip(bp['exercises'], ap['exercises']):
                    for field in ('id', 'kind', 'stage', 'context', 'prompt', 'answer', 'rows', 'items', 'categories'):
                        self.assertEqual(left.get(field), right.get(field), (before['id'], left['id'], field))
                    if before['id'].endswith('-atelier'):
                        self.assertTrue({o['id'] for o in left['options']} <= {o['id'] for o in right['options']})
                        self.assertEqual(len(right['options']), 3)
                    elif 'options' in left:
                        self.assertEqual(left['options'], right['options'])

    def test_four_journals_keep_their_document_work(self):
        journals = [a for a in self.activities if a['practice'].get('journal')]
        self.assertEqual([a['id'] for a in journals], [
            'aps62-08-03-journal', 'aps62-08-05-journal',
            'aps62-13-01-journal', 'aps62-13-02-journal',
        ])
        self.assertEqual([len(a['practice']['exercises']) for a in journals], [5, 5, 4, 4])
        for activity in journals:
            drills = [e['remediation'] for e in activity['practice']['exercises']]
            self.assertEqual(len(drills), len({d['prompt'] for d in drills}))
            self.assertGreaterEqual(len(activity['practice']['documents']), 2)
        followup = next(a for a in journals if a['id'] == 'aps62-08-05-journal')
        prompts = [e['remediation']['prompt'] for e in followup['practice']['exercises']]
        self.assertIn('PN-42', prompts[0])
        self.assertIn('17 h 08', prompts[1])
        self.assertIn('maintenance', prompts[2].lower())
        self.assertIn('20 h 10', prompts[3])
        self.assertIn('21 h 20', prompts[4])

    def test_balanced_answer_positions_without_teaching_order_cycle(self):
        for items, expected in ((self.drills, 128), (self.main, 62)):
            positions = [next(i for i, o in enumerate(item['options']) if o['id'] == item['answer']) for item in items]
            self.assertEqual(Counter(positions), Counter({0: expected, 1: expected, 2: expected}))
            self.assertNotEqual(positions[:18], [0, 1, 2] * 6)
            # A per-activity constant pattern would make correction trivial.
            self.assertGreater(len({tuple(positions[i:i+3]) for i in range(0, len(positions), 3)}), 15)

    def test_no_systematic_longest_or_shortest_answer_shortcut(self):
        for items in (self.drills, self.main):
            ranks = Counter(length_rank(item) for item in items)
            self.assertLessEqual(ranks['longest'] / len(items), .45)
            self.assertLessEqual(ranks['shortest'] / len(items), .45)

    def test_repeated_application_is_identical(self):
        for course in self.courses:
            again = copy.deepcopy(course)
            returned = apply_remediation(again)
            self.assertIs(returned, again)
            self.assertEqual(course, again)

    def test_missing_exercise_is_rejected_before_mutation(self):
        course = copy.deepcopy(self.sources[0])
        practices(course)[0]['practice']['exercises'].pop()
        before = copy.deepcopy(course)
        with self.assertRaisesRegex(ValueError, 'IDs/order'):
            apply_remediation(course)
        self.assertEqual(course, before)

    def test_missing_activity_is_rejected_before_mutation(self):
        course = copy.deepcopy(self.sources[0])
        section = course['sections'][0]
        section['activities'] = [a for a in section['activities'] if not a['id'].endswith('-transfert')]
        before = copy.deepcopy(course)
        with self.assertRaisesRegex(ValueError, 'Incomplete module'):
            apply_remediation(course)
        self.assertEqual(course, before)

    def test_unknown_exercise_is_rejected_before_mutation(self):
        course = copy.deepcopy(self.sources[0])
        practices(course)[0]['practice']['exercises'][0]['id'] = 'not-authored'
        before = copy.deepcopy(course)
        with self.assertRaises(ValueError):
            apply_remediation(course)
        self.assertEqual(course, before)


if __name__ == '__main__':
    unittest.main()
