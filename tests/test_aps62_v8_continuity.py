"""Do not apply the legacy response-mode conversion to the long-video edition."""
import json
import unittest

from elearning_native.academy import ROOT
from elearning_native.practice import adapt_course, grade_practice, public_practice


class LongVideoPracticeContinuityTests(unittest.TestCase):
    def test_v8_preserves_all_142_guided_workshops_and_step_correction(self):
        courses = sorted((ROOT/'courses').glob('*/20261007-aps62-v7.json'))
        self.assertEqual(len(courses), 15)
        practice_count = journal_count = 0
        for path in courses:
            # The publisher carries the v7 interactions into a new version.
            # Reproduce that version change before publication without creating
            # course files, fake media or changing the global catalogue.
            expected = json.loads(path.read_text(encoding='utf-8'))
            expected['version'] = expected['interaction_revision'] = '20261007-aps62-v8'
            for section in expected['sections']:
                for activity in section['activities']:
                    if activity.get('practice'):
                        activity['practice']['revision'] = '20261007-aps62-v8'
            with self.subTest(course=expected['id']):
                adapted = adapt_course(expected)
                self.assertEqual(adapted, expected)
                self.assertIsNot(adapted, expected)
                for section in adapted['sections']:
                    for activity in section['activities']:
                        practice = activity.get('practice')
                        if not practice:
                            continue
                        practice_count += 1
                        journal_count += bool(practice.get('journal'))
                        public = public_practice(practice)
                        self.assertEqual(public['mode'], 'guided')
                        self.assertEqual(public['revision'], '20261007-aps62-v8')
                        self.assertTrue(public['sequential'])
                        for exercise in public['exercises']:
                            self.assertNotIn('answer', exercise)
                            self.assertNotIn('explanation', exercise)
                            self.assertNotIn('branches', exercise)
                        # Losing guided mode used to reject this normal action
                        # with "Cette activité se corrige dans son ensemble".
                        first = practice['exercises'][0]
                        answer = (first['answer'] if first['kind'] == 'single'
                                  else {row['id']: row['answer'] for row in first['rows']})
                        result = grade_practice(practice, {first['id']: answer}, step=first['id'])
                        self.assertTrue(result['correct'])
                        self.assertEqual(result['revision'], '20261007-aps62-v8')
        self.assertEqual((practice_count, journal_count), (142, 4))


if __name__ == '__main__':
    unittest.main()
