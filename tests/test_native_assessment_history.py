from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from elearning_native.store import NativeElearningStore, TrackingError
from elearning_native.paths import project_progress
from elearning_native.assessment import describe_history, history_for


class AssessmentHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'tracking.sqlite3'
        self.store = NativeElearningStore(self.path)
        self.access = dict(session_id='session', trainee_id='trainee', course_id='course', course_version='v1')
        self.options = dict(activity_order=['q'], scored_activity_ids=['q'], mastery_score=80)

    def tearDown(self):
        self.tmp.cleanup()

    def complete(self, *, request_id='correct-0001'):
        return self.store.complete_activity(self.access, 'q', **self.options,
            answer={'selected': ['right'], 'correct': True},
            assessment_attempt={'answer': {'selected': ['right']}, 'correct': True, 'request_id': request_id})

    def test_error_survives_correction_and_never_unlocks_or_awards_time(self):
        self.store.record_question_attempt(self.access, 'q', {'selected': ['wrong']}, False, request_id='wrong-0001')
        before = self.store.get_progress(self.access, **self.options)
        self.assertEqual(before['completed_activity_ids'], [])
        self.assertEqual(before['answers'], {})
        self.assertEqual(before['active_seconds'], 0)
        self.assertEqual(before['assessment_summary']['first_attempt_score_percent'], 0)
        final = self.complete()
        self.assertEqual(final['score_percent'], 100)
        self.assertEqual(final['assessment_summary']['first_attempt_score_percent'], 0)
        self.assertEqual(final['assessment_summary']['attempt_count'], 2)
        self.assertEqual(final['assessment_summary']['incorrect_attempt_count'], 1)
        history = self.store.assessment_history(self.access)
        self.assertEqual([item['correct'] for item in history], [False, True])
        self.assertEqual(history[0]['answer'], {'selected': ['wrong']})
        reopened = NativeElearningStore(self.path)
        self.assertEqual(reopened.assessment_history(self.access), history)

    def test_idempotent_retries_and_out_of_order_replays(self):
        first = self.store.record_question_attempt(self.access, 'q', {'selected': ['x']}, False, request_id='request-one')
        self.store.record_question_attempt(self.access, 'q', {'selected': ['y']}, False, request_id='request-two')
        replay = self.store.record_question_attempt(self.access, 'q', {'selected': ['x']}, False, request_id='request-one')
        self.assertEqual(replay['id'], first['id'])
        self.assertEqual(len(self.store.assessment_history(self.access)), 2)
        with self.assertRaises(TrackingError):
            self.store.record_question_attempt(self.access, 'q', {'selected': ['changed']}, False, request_id='request-one')
        with self.assertRaises(TrackingError):
            self.store.record_question_attempt(self.access, 'q', {}, False, request_id=['invalid'])
        self.assertEqual(len(self.store.assessment_history(self.access)), 2)

    def test_concurrent_checks_are_exactly_once_and_completed_work_stays_immutable(self):
        def submit(_):
            return NativeElearningStore(self.path).record_question_attempt(
                self.access, 'q', {'selected': ['x']}, False, request_id='same-network-request')
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(submit, range(4)))
        self.assertEqual(len({item['id'] for item in results}), 1)
        self.complete()
        self.complete(request_id='second-completion')
        self.store.record_question_attempt(self.access, 'q', {'selected': ['x']}, False, request_id='late-wrong-answer')
        self.assertEqual(len(self.store.assessment_history(self.access)), 2)

    def test_every_owner_and_course_version_has_an_isolated_history(self):
        self.store.record_question_attempt(self.access, 'q', {}, False)
        for field in self.access:
            with self.subTest(field=field):
                other = self.access | {field: 'different'}
                self.assertEqual(self.store.assessment_history(other), [])

    def test_guided_and_classic_exercise_choices_persist_before_completion(self):
        def result(choice, correct):
            return {'answers': {'exercise': choice}, 'revision': 'r1', 'correct': correct,
                    'feedback': [{'id': 'exercise', 'correct': correct, 'competency': 'Alerter'}],
                    'passed': int(correct), 'total': 1}
        self.store.record_practice_result(self.access, 'workshop', result('wrong', False))
        self.store.record_practice_result(self.access, 'workshop', result('wrong', False))
        self.store.record_practice_result(self.access, 'workshop', result('right', True))
        # Full confirmation is not a fresh answer to every step.
        self.store.record_practice_result(self.access, 'workshop', result('right', True))
        history = self.store.assessment_history(self.access)
        self.assertEqual([item['answer'] for item in history], ['wrong', 'right'])
        progress = self.store.get_progress(self.access)
        self.assertEqual(progress['completed_activity_ids'], [])
        self.assertEqual(progress['assessment_summary']['practice']['first_attempt_score_percent'], 0)
        self.assertEqual(progress['assessment_summary']['practice']['attempt_count'], 2)
        self.assertIsNone(progress['assessment_summary']['first_attempt_score_percent'])

    def test_projection_excludes_deselected_questions_without_erasing_evidence(self):
        self.store.record_question_attempt(self.access, 'q', {}, False)
        self.store.record_question_attempt(self.access, 'hidden', {}, True)
        progress = self.store.get_progress(self.access)
        course = {'activity_order': ['q'], 'sections': [{'activities': [{'id': 'q', 'scored': True}]}]}
        projected = project_progress(progress, course)
        self.assertEqual(projected['assessment_summary']['assessed_items'], 1)
        self.assertEqual(projected['assessment_summary']['first_attempt_score_percent'], 0)
        self.assertEqual(len(self.store.assessment_history(self.access)), 2)

    def test_historical_completed_answers_do_not_fabricate_an_initial_score(self):
        final = self.store.complete_activity(self.access, 'q', **self.options, answer={'correct': True})
        self.assertEqual(final['score_percent'], 100)
        self.assertIsNone(final['assessment_summary']['first_attempt_score_percent'])
        self.assertEqual(self.store.assessment_history(self.access), [])

    def test_capture_before_ai_keeps_original_work_without_claiming_feedback_was_seen(self):
        self.store.record_production(self.access, 'written', {'report': 'Initial text'}, capture_first=True)
        self.store.record_production(self.access, 'written', {'report': 'Improved text'}, compared=True)
        saved = self.store.get_progress(self.access)['answers']['written']
        self.assertEqual(saved['production_first_answers']['report'], 'Initial text')
        self.assertEqual(saved['production_answers']['report'], 'Improved text')
        self.assertTrue(saved['production_feedback_seen'])

    def test_history_can_be_captured_on_the_same_sqlite_read_transaction(self):
        self.store.record_question_attempt(self.access, 'q', {'selected': ['bad']}, False)
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute('BEGIN')
            self.assertEqual(history_for(connection, self.access)[0]['answer'], {'selected': ['bad']})
        course = {'sections': [{'title': 'Dossier', 'activities': [{'id': 'q', 'title': 'Qui prévenir ?',
                  'question_type': 'single_choice', 'options': [{'id': 'bad', 'text': 'Un passant'}]}]}]}
        display = describe_history(course, self.store.assessment_history(self.access))
        self.assertEqual(display[0]['answer_text'], 'Un passant')


if __name__ == '__main__':
    unittest.main()


class AssessmentHTTPTests(unittest.TestCase):
    """Use real native routes/authentication and only synthetic course data."""

    def setUp(self):
        from tests.test_native_elearning_web import NativeElearningWebTests
        NativeElearningWebTests.setUp(self)
        self._fixture = NativeElearningWebTests
        course_path = (self.persist_dir / 'native_elearning' / 'courses' /
                       self.course['id'] / self.course['version'] / 'course.json')
        course = json.loads(course_path.read_text())
        course['settings']['require_correct_answers'] = True
        course_path.write_text(json.dumps(course))
        NativeElearningWebTests._public_login(self)
        page = self.client.get('/espace/public-token/elearning/'+self.course['id'])
        config = NativeElearningWebTests._player_config(page)
        self.assertEqual(self.post(config['completeUrl'], config).status_code, 200)
        page = self.client.get('/espace/public-token/elearning/'+self.course['id']+'?activity=question-1')
        self.config = NativeElearningWebTests._player_config(page)
        self.native_store = NativeElearningStore(self.persist_dir/'native_elearning'/'tracking.sqlite3')
        self.access = dict(session_id='session-aps', trainee_id='trainee-1',
                           course_id=self.course['id'], course_version=self.course['version'])

    def post(self, url, config, **payload):
        return self.client.post(url, json={'access_token': config['accessToken'], **payload},
                                headers={'X-Elearning-CSRF': config['csrfToken']})

    def tearDown(self):
        self._fixture.tearDown(self)

    def test_wrong_then_correct_preserves_both_answers_and_exposes_teacher_history(self):
        config = self.config
        for _ in range(2):
            response = self.post(config['answerUrl'], config, answer={'selected': ['answer-b']}, request_id='first-check')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json['retry_required'])
            self.assertNotIn('question-1', response.json['progress']['completed_activity_ids'])
        self.assertEqual(len(self.native_store.assessment_history(self.access)), 1)
        correct = self.post(config['answerUrl'], config, answer={'selected': ['answer-a']}, request_id='second-check')
        self.assertEqual(correct.status_code, 200)
        summary = correct.json['progress']['assessment_summary']
        self.assertEqual(summary['first_attempt_score_percent'], 0)
        self.assertEqual(summary['attempt_count'], 2)
        self.assertEqual(correct.json['progress']['answers']['question-1']['correct'], True)
        self._fixture._admin_login(self)
        page = self.client.get('/admin/elearning/courses/'+self.course['id']+'/attempts')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Réponses et erreurs avant correction', page.text)
        self.assertIn('Non', page.text)
        csv = self.client.get('/admin/elearning/courses/'+self.course['id']+'/attempts.csv')
        self.assertEqual(csv.status_code, 200)
        self.assertIn(';Non;À revoir;', csv.text)

    def test_invalid_csrf_and_locked_questions_never_record_attempts(self):
        denied = self.client.post(self.config['answerUrl'], json={
            'access_token': self.config['accessToken'], 'answer': {'selected': ['answer-b']}})
        self.assertEqual(denied.status_code, 403)
        locked = self.post('/api/elearning/v1/activities/question-2/answer', self.config,
                           answer={'groups': {'group-1': 'blank-a'}})
        self.assertEqual(locked.status_code, 409)
        self.assertEqual(self.native_store.assessment_history(self.access), [])
