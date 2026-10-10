import copy
import json
import unittest

from elearning_native.practice import grade_practice, public_practice
from elearning_native.vtc_adaptive import select_activity


def exercise(ref, n):
    return {'id': f'{ref}-{n}', 'kind': 'single', 'competency': ref,
            'prompt': f'Situation {ref}, cas {n}', 'options': [{'id': 'a', 'text': 'Oui'}, {'id': 'b', 'text': 'Non'}],
            'answer': 'a', 'explanation': 'Le document confirme cette décision.'}


def fixture():
    refs = [f'A.{i:02}' for i in range(1, 13)]
    prior = [{'id': f'case-{n}', 'practice': {'revision': 'v6', 'mode': 'journey',
              'exercises': [exercise(ref, n) for ref in refs]}} for n in range(2)]
    review = {'id': 'review', 'practice': {'revision': 'v6', 'mode': 'journey',
              'selection_strategy': 'competency_review_v1', 'exercises': [exercise(ref, 'review') for ref in refs]}}
    course = {'id': 'academy-vtc-a', 'sections': [{'activities': [*prior, review]}]}
    progress = {'completed_activity_ids': [a['id'] for a in prior], 'answers': {
        a['id']: {'practice_diagnostics': {ex['id']: {'first_correct': True, 'correct': True}
                 for ex in a['practice']['exercises']}} for a in prior}}
    return course, review, progress


class AdaptiveTests(unittest.TestCase):
    def test_confirmed_skills_reduce_review_and_keep_spaced_controls(self):
        course, review, progress = fixture()
        original = copy.deepcopy((course, review, progress))
        selected = select_activity(course, review, progress)
        self.assertEqual(len(selected['practice']['exercises']), 4)
        self.assertEqual(selected['practice']['selection_summary']['mastered_count'], 12)
        self.assertEqual((course, review, progress), original)
        public = json.dumps(public_practice(selected['practice']))
        self.assertNotIn('"answer"', public)
        self.assertNotIn('"explanation"', public)
        self.assertIn('selection_summary', public)

    def test_correction_of_an_error_does_not_count_as_first_attempt_mastery(self):
        course, review, progress = fixture()
        for i in range(1, 9):
            progress['answers']['case-1']['practice_diagnostics'][f'A.{i:02}-1']['first_correct'] = False
        selected = select_activity(course, review, progress)
        self.assertEqual(len(selected['practice']['exercises']), 8)
        self.assertEqual(selected['practice']['selection_summary']['weak_refs'], [f'A.{i:02}' for i in range(1, 9)])

    def test_no_evidence_and_incomplete_activities_never_skip_questions(self):
        course, review, progress = fixture()
        for empty in ({}, {**progress, 'completed_activity_ids': []}):
            self.assertEqual(len(select_activity(course, review, empty)['practice']['exercises']), 12)

    def test_repeated_copy_is_only_one_piece_of_evidence(self):
        course, review, progress = fixture()
        first, second = course['sections'][0]['activities'][:2]
        for a, b in zip(first['practice']['exercises'], second['practice']['exercises']):
            b['prompt'] = a['prompt']
        self.assertEqual(len(select_activity(course, review, progress)['practice']['exercises']), 12)

    def test_plan_stable_during_review_and_server_rejects_omissions_and_extra_questions(self):
        course, review, progress = fixture()
        selected = select_activity(course, review, progress)
        expected = {ex['id']: ex['answer'] for ex in selected['practice']['exercises']}
        progress['answers']['review'] = {'practice_diagnostics': {'A.01-review': {'first_correct': False, 'correct': False}}}
        self.assertEqual(select_activity(course, review, progress), selected)
        self.assertTrue(grade_practice(selected['practice'], expected)['correct'])
        with self.assertRaises(ValueError):
            grade_practice(selected['practice'], dict(list(expected.items())[:1]))
        with self.assertRaises(ValueError):
            grade_practice(selected['practice'], {**expected, 'invented': 'a'})
        skipped = next(ex for ex in review['practice']['exercises'] if ex['id'] not in expected)
        with self.assertRaises(ValueError):
            grade_practice(selected['practice'], {skipped['id']: 'a'}, step=skipped['id'])

    def test_other_editions_and_aps_unchanged(self):
        course, review, progress = fixture()
        del review['practice']['selection_strategy']
        self.assertIs(select_activity(course, review, progress), review)
        review['practice']['selection_strategy'] = 'competency_review_v1'
        course['id'] = 'academy-aps62-01'
        self.assertIs(select_activity(course, review, progress), review)


if __name__ == '__main__':
    unittest.main()
