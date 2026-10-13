"""Content renewal must not regrade history or accept stale browser answers."""
import copy
import html
import json
import sqlite3
import unittest

from elearning_native.academy import ROOT, curriculum_manifest, load_bundled_course
from elearning_native.aps_editorial import REVISION, question_for_history
from elearning_native.practice import grade_practice, public_practice
from elearning_native.videos import course_videos
from elearning_native.web import _b64decode, _evaluate_answer, _sign_access
from tests import test_native_elearning_web as fixture


def activities(course):
    return [a for section in course['sections'] for a in section['activities']]


class EditorialContentTests(unittest.TestCase):
    def test_all_sequences_keep_teaching_and_use_independent_exercises(self):
        prompts = set()
        sequence_count = recall_count = question_count = 0
        for module in curriculum_manifest()['modules']:
            course = load_bundled_course(module['id'])
            raw = json.loads((ROOT / 'courses' / course['id'] / (course['version'] + '.json')).read_text())
            for section, previous in zip(course['sections'], raw['sections']):
                sequence_count += 1
                by_id = {a['id']: a for a in previous['activities']}
                lesson = next(a['academy'] for a in section['activities'] if a.get('academy', {}).get('kind') == 'lesson')
                original = by_id[section['id'] + '-comprendre']['academy']
                self.assertTrue(lesson['intro'])
                self.assertEqual(lesson.get('uniform_diagram'), original.get('uniform_diagram'))
                self.assertFalse({'visual_guide', 'table', 'flow', 'sorting', 'case'} & lesson.keys())
                for ref, old in zip(lesson['lessons'], original['lessons']):
                    # Neither legal teaching nor illustrations disappear when
                    # a previously introduced reference becomes optional.
                    self.assertEqual(ref['paragraphs'], old['paragraphs'])
                    self.assertEqual(ref['diagram'], old['diagram'])
                    self.assertEqual(ref['background'], old.get('practice', {}).get('background', ''))
                    if ref['review_reference']:
                        recall_count += 1
                        self.assertTrue(any(p['kind'] == 'takeaway' for p in ref['paragraphs']))
                reading = json.dumps(lesson, ensure_ascii=False)
                video = next(a for a in section['activities'] if a.get('academy', {}).get('kind') == 'memory')
                transcript = json.dumps(video, ensure_ascii=False)
                for activity in section['activities']:
                    if activity['id'].endswith('-q1'):
                        question_count += 1
                        self.assertNotEqual(activity['prompt'], by_id[activity['id']]['prompt'])
                        for option in activity['options']:
                            correct, _ = _evaluate_answer(activity, {'selected': [option['id']]})
                            self.assertEqual(correct, option['is_correct'])
                    practice = activity.get('practice', {})
                    if practice.get('revision') != REVISION:
                        continue
                    public = public_practice(practice)
                    good, bad = {}, {}
                    for exercise, published in zip(practice['exercises'], public['exercises']):
                        prompt = exercise['prompt']
                        self.assertNotIn(prompt, prompts)
                        prompts.add(prompt)
                        self.assertNotIn(prompt, reading)
                        self.assertNotIn(prompt, transcript)
                        self.assertNotIn('answer', published)
                        self.assertNotIn('explanation', published)
                        self.assertNotIn('branches', published)
                        good[exercise['id']] = exercise['answer']
                        bad[exercise['id']] = next(o['id'] for o in exercise['options'] if o['id'] != exercise['answer'])
                    self.assertTrue(grade_practice(practice, good)['correct'])
                    self.assertFalse(grade_practice(practice, bad)['correct'])
                    # A draft left open before publication cannot be graded
                    # using the new options, even if it bypasses the UI.
                    old = by_id[activity['id']]['practice']
                    legacy = {e['id']: e['answer'] for e in old['exercises']}
                    with self.assertRaises(ValueError):
                        grade_practice(practice, legacy)
        self.assertEqual((sequence_count, question_count, recall_count, len(prompts)), (62, 62, 84, 290))

    def test_history_displays_the_question_actually_answered_for_every_edition(self):
        for module in curriculum_manifest()['modules']:
            for version in [module['version'], *module['previous_versions']]:
                course = load_bundled_course(module['id'], version)
                question = next(a for a in activities(course) if a['id'].endswith('-q1'))
                raw = json.loads((ROOT / 'courses' / course['id'] / (version + '.json')).read_text())
                old = next(a for a in activities(raw) if a['id'] == question['id'])
                history = {'completed_activity_ids': [question['id']], 'answers': {question['id']: {'correct': True}}}
                untouched = copy.deepcopy(history)
                self.assertEqual(question_for_history(question, course, history), old)
                self.assertEqual(history, untouched)
                self.assertIs(question_for_history(question, course, {}), question)
                history['answers'][question['id']]['content_revision'] = REVISION
                self.assertIs(question_for_history(question, course, history), question)


class EditorialHTTPTests(unittest.TestCase):
    setUp = fixture.NativeElearningWebTests.setUp
    tearDown = fixture.NativeElearningWebTests.tearDown
    _admin_login = fixture.NativeElearningWebTests._admin_login
    _public_login = fixture.NativeElearningWebTests._public_login
    _player_config = staticmethod(fixture.NativeElearningWebTests._player_config)
    _api_post = fixture.NativeElearningWebTests._api_post

    def assign(self):
        self.course = load_bundled_course('academy-aps62-01')
        self.data['sessions'][0].update(aps_native_course_id=self.course['id'], aps_native_course_version=self.course['version'])
        self._public_login()
        response = self.client.get('/espace/public-token/elearning/academy-aps62-01')
        self.assertEqual(response.status_code, 200)
        return self._player_config(response)

    def seed_history(self, completed, answers=None):
        video_progress = {aid: {vid: {'completed': True, 'watched_seconds': duration,
            'duration_seconds': duration, 'ranges': [[0, duration]]} for vid, duration in videos.items()}
            for aid, videos in course_videos(self.course).items()}
        database = self.persist_dir / 'native_elearning' / 'tracking.sqlite3'
        with sqlite3.connect(database) as connection:
            connection.execute('UPDATE learner_course_progress SET completed_json=?, answers_json=?, video_progress_json=?, active_seconds=1234',
                (json.dumps(completed), json.dumps(answers or {}), json.dumps(video_progress)))

    def stored_history(self):
        with sqlite3.connect(self.persist_dir / 'native_elearning' / 'tracking.sqlite3') as connection:
            return connection.execute('SELECT completed_json, answers_json, video_progress_json, active_seconds FROM learner_course_progress').fetchone()

    def test_old_tab_keeps_tracking_but_cannot_submit_a_changed_exercise(self):
        config = self.assign()
        access = json.loads(_b64decode(config['accessToken'].split('.')[0]))
        self.assertEqual(access.pop('aps_editorial_revision'), REVISION)
        with fixture.gestion_app.app.app_context():
            config['accessToken'] = _sign_access(access)
        before = self.stored_history()
        for kind, aid in [('answer', 'aps62-01-01-q1'), ('practice', 'aps62-01-01-atelier'), ('complete', 'aps62-01-01-comprendre')]:
            response = self._api_post(f'/api/elearning/v1/activities/{aid}/{kind}', config)
            self.assertEqual(response.status_code, 409)
            self.assertIn('Rechargez la page', response.get_json()['error'])
        self.assertEqual(self.stored_history(), before)
        response = self._api_post(config['startUrl'], config, tab_id='old-tab', activity_id='aps62-01-01-comprendre')
        self.assertEqual(response.status_code, 200)
        response = self._api_post(config['finishUrl'], config, tracking_session_id=response.get_json()['tracking_session_id'])
        self.assertEqual(response.status_code, 200)

    def test_completed_old_question_and_saved_score_remain_intact(self):
        self.assign()
        raw = json.loads((ROOT / 'courses' / self.course['id'] / (self.course['version'] + '.json')).read_text())
        question = next(a for a in activities(raw) if a['id'] == 'aps62-01-01-q1')
        selected = next(o['id'] for o in question['options'] if o['is_correct'])
        answer = {'correct': True, 'selected': [selected], 'submitted_at': '2026-10-12T12:00:00Z'}
        self.seed_history(self.course['activity_order'], {question['id']: answer})
        before = self.stored_history()
        response = self.client.get('/espace/public-token/elearning/academy-aps62-01?activity=' + question['id'])
        self.assertEqual(response.status_code, 200)
        self.assertIn(question['prompt'], html.unescape(response.text))
        self.assertIn(question['explanation'], html.unescape(response.text))
        config = self._player_config(response)
        again = self._api_post(config['answerUrl'], config, answer={'selected': ['v15-1']})
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.get_json()['already_answered'])
        self.assertEqual(again.get_json()['explanation'], question['explanation'])
        self.assertEqual(self.stored_history(), before)

    def test_new_question_records_its_revision_and_does_not_award_time(self):
        self.assign()
        question = next(a for a in activities(self.course) if a['id'] == 'aps62-01-01-q1')
        self.seed_history(self.course['activity_order'][:self.course['activity_order'].index(question['id'])])
        response = self.client.get('/espace/public-token/elearning/academy-aps62-01?activity=' + question['id'])
        self.assertIn(question['prompt'], html.unescape(response.text))
        self.assertNotIn('"is_correct"', response.text)
        config = self._player_config(response)
        selected = next(o['id'] for o in question['options'] if o['is_correct'])
        result = self._api_post(config['answerUrl'], config, answer={'selected': [selected]})
        self.assertEqual(result.status_code, 200)
        saved = result.get_json()['progress']['answers'][question['id']]
        self.assertEqual(saved['content_revision'], REVISION)
        self.assertEqual(result.get_json()['progress']['active_seconds'], 1234)

    def test_all_new_lesson_templates_render_and_horizon_stays_in_its_video(self):
        self._admin_login()
        for module in curriculum_manifest()['modules']:
            course = load_bundled_course(module['id'])
            for section in course['sections']:
                response = self.client.get(f'/admin/elearning/courses/{course["id"]}/preview',
                    query_string={'activity': section['id'] + '-comprendre'})
                self.assertEqual(response.status_code, 200)
                self.assertIn(REVISION, response.text)
                self.assertNotIn('Le tableau de décision', response.text)
        url = '/admin/elearning/courses/academy-aps62-01/preview'
        for suffix in ['comprendre', 'atelier', 'q1', 'transfert']:
            response = self.client.get(url, query_string={'activity': 'aps62-01-01-' + suffix})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('Horizon', response.text)
        video = self.client.get(url, query_string={'activity': 'aps62-01-01-memoriser'})
        self.assertIn('Horizon', video.text)
        self.assertIn('<video', video.text)


if __name__ == '__main__':
    unittest.main()
