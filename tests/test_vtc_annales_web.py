"""Integration coverage for source annales and isolated learner attempts."""
import copy
import json
import re
import sqlite3
import unittest
from unittest.mock import patch

from tests import test_native_elearning_web as native_tests
from elearning_native import annales, vtc
from elearning_native.exams import ExamStore
from elearning_native.store import NativeElearningStore
from elearning_native.web import _b64decode


class VtcAnnalesWebTests(unittest.TestCase):
    setUp = native_tests.NativeElearningWebTests.setUp
    tearDown = native_tests.NativeElearningWebTests.tearDown
    _admin_login = native_tests.NativeElearningWebTests._admin_login
    _public_login = native_tests.NativeElearningWebTests._public_login

    def assign(self, *letters):
        session = self.data['sessions'][0]
        session['training_type'] = 'VTC'
        manifest = {m['id'][-1].upper(): m for m in vtc.curriculum_manifest()['modules']}
        session['aps_native_modules'] = [
            {'course_id': manifest[letter]['id'], 'course_version': manifest[letter]['version']}
            for letter in letters]
        return session

    def exam(self, module='a', *, preview=False, token='public-token'):
        url = f'/admin/elearning/vtc/annales/annales-2021-{module}' if preview else f'/espace/{token}/elearning/vtc/annales/annales-2021-{module}'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.text[:300])
        match = re.search(r'<script type="application/json" id="annalesConfig">(.*?)</script>', response.text, re.S)
        self.assertIsNotNone(match)
        return response, json.loads(match[1])

    @staticmethod
    def correct_answers(config):
        section = annales.load_section(config['exam']['id'])
        return {q['id']: q['answers'] for q in section['questions'] if q['status'] == 'active'}

    def submit(self, config, answers=None, **overrides):
        return self.client.post(config['submitUrl'], json={
            'version': config['exam']['version'], 'attempt_id': config['attemptId'],
            'answers': self.correct_answers(config) if answers is None else answers,
            **overrides}, headers={'X-Elearning-CSRF': config['csrfToken']})

    def test_admin_preview_has_no_tracking_or_answer_keys(self):
        self._admin_login()
        with patch('elearning_native.annales_web.ExamStore', side_effect=AssertionError('preview opened tracking')):
            response, config = self.exam(preview=True)
            self.assertTrue(config['preview'])
            self.assertIn('no-store',response.headers['Cache-Control'])
            self.assertNotIn('accessToken', config)
            for question in config['exam']['questions']:
                for private in ('answers', 'original_answer', 'explanation', 'learning_points', 'sources', 'lesson_refs'):
                    self.assertNotIn(private, question)
            corrected = self.submit(config)
            self.assertEqual(corrected.status_code, 200)
            result = corrected.json['result']
            self.assertEqual(result['percent'], 100)
            self.assertGreater(result['historical_count'], 0)
            self.assertNotIn('attempt_id', result)
        self.assertFalse((self.persist_dir / 'native_elearning' / 'tracking.sqlite3').exists())
        self.assertIsNone(self.saved_data)

    def test_multi_choice_requires_exact_set_and_historical_is_not_scored(self):
        self._admin_login()
        _, config = self.exam(preview=True)
        answers = self.correct_answers(config)
        answers['annales-2021-a-01'] = ['a']  # Police AND gendarmes are expected.
        result = self.submit(config, answers).json['result']
        self.assertEqual(result['total'], config['exam']['scored_count'])
        self.assertEqual(result['score'], result['total'] - 1)
        self.assertFalse(next(q for q in result['corrections'] if q['number'] == 1)['correct'])
        self.assertTrue(all(q['correct'] is None for q in result['corrections'] if q['status'] == 'historical'))
        answers['annales-2021-a-01'] = ['d', 'a']
        self.assertEqual(self.submit(config, answers).json['result']['percent'], 100)
        historical = next(q for q in config['exam']['questions'] if q['status'] == 'historical')
        answers[historical['id']] = ['a']
        self.assertEqual(self.submit(config, answers).status_code, 400)

    def test_csrf_stale_version_and_invalid_answer_types_fail_closed(self):
        self._admin_login()
        _, config = self.exam(preview=True)
        payload = {'version':config['exam']['version'], 'answers':self.correct_answers(config)}
        self.assertEqual(self.client.post(config['submitUrl'], json=payload).status_code, 403)
        self.assertEqual(self.submit(config, version='old-version').status_code, 409)
        good = self.correct_answers(config)
        question = next(iter(good))
        for bad in (None, 'a', ['a','a'], ['unknown'], [{'id':'a'}]):
            with self.subTest(bad=bad):
                answers = dict(good); answers[question] = bad
                self.assertEqual(self.submit(config, answers).status_code, 400)
        self.assertEqual(self.submit(config, {}).status_code, 400)

    def test_anonymous_other_tenant_unassigned_and_future_access_denied(self):
        session = self.assign('A')
        path = '/espace/public-token/elearning/vtc/annales'
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(path+'/annales-2021-a').status_code, 401)
        self._public_login()
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get(path+'/annales-2021-b').status_code, 403)
        self.assertEqual(self.client.get(path+'/annales-2021-c/images/annales-2021-c-20').status_code, 403)
        other = copy.deepcopy(session); other['id']='other-session'
        other['trainees'][0].update(id='other-trainee',public_token='other-token')
        self.data['sessions'].append(other)
        self.assertEqual(self.client.get('/espace/other-token/elearning/vtc/annales/annales-2021-a').status_code,401)
        session['date_start']='2099-01-01'
        self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.client.get(path+'/annales-2021-a').status_code,403)

    def test_prerequisite_blocks_exam_submit_image_and_lesson(self):
        self.assign('A','B','C')
        self._public_login()
        _, config = self.exam('a')
        for path in ('/espace/public-token/elearning/vtc/annales/annales-2021-b',
                     '/espace/public-token/elearning/vtc/notions/B.01',
                     '/espace/public-token/elearning/vtc/annales/annales-2021-c/images/annales-2021-c-20'):
            self.assertEqual(self.client.get(path).status_code,403,path)
        config['submitUrl']='/api/espace/public-token/elearning/vtc/annales/annales-2021-b'
        self.assertEqual(self.submit(config).status_code,403)

    def test_attempt_is_idempotent_and_does_not_complete_course(self):
        self.assign('A')
        self._public_login()
        _, config = self.exam()
        first = self.submit(config)
        self.assertEqual(first.status_code,200,first.text)
        answers = self.correct_answers(config); answers['annales-2021-a-01']=['b']
        second = self.submit(config,answers)
        self.assertEqual(second.json['result'], first.json['result'])
        dbpath = self.persist_dir / 'native_elearning' / 'tracking.sqlite3'
        with sqlite3.connect(dbpath) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM aps_exam_attempts').fetchone()[0],1)
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn('learner_progress',tables)
        self.assertIsNone(self.saved_data)
        reloaded, _ = self.exam()
        self.assertIn('Mes dernières tentatives',reloaded.text)

    def test_attempt_history_is_scoped_to_session_and_trainee(self):
        session = self.assign('A'); self._public_login()
        _, config = self.exam(); self.assertEqual(self.submit(config).status_code,200)
        other=copy.deepcopy(session);other['id']='other-session'
        other['trainees'][0].update(id='other-trainee',public_token='other-token')
        self.data['sessions'].append(other)
        with self.client.session_transaction() as browser_session:
            browser_session['public_auth_other-token']=True
        response, other_config=self.exam(token='other-token')
        self.assertNotIn('Mes dernières tentatives',response.text)
        self.assertNotEqual(config['contextKey'],other_config['contextKey'])
        other_config['attemptId']=config['attemptId']
        self.assertEqual(self.submit(other_config).status_code,200)
        with sqlite3.connect(self.persist_dir/'native_elearning'/'tracking.sqlite3') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM aps_exam_attempts').fetchone()[0],2)

    def test_authenticated_image_and_lesson_resolve_without_keys_in_exam(self):
        self.assign('C');self._public_login()
        response,config=self.exam('c')
        question=next(q for q in config['exam']['questions'] if q.get('image'))
        image=self.client.get(question['image'])
        self.assertEqual(image.status_code,200)
        self.assertEqual(image.mimetype,'image/webp')
        self.assertEqual(image.headers['Cache-Control'],'private, no-store')
        lesson=self.client.get('/espace/public-token/elearning/vtc/notions/C.05')
        self.assertEqual(lesson.status_code,200)
        self.assertIn('vtc-c-05-cours',lesson.text)
        self.assertNotIn('Réponse attendue',response.text)

    def test_existing_learner_keeps_assigned_course_and_all_progress(self):
        session = self.assign('A')
        previous_version = '20261006-vtc-v3-105h'
        session['aps_native_modules'][0]['course_version'] = previous_version
        original_assignment = copy.deepcopy(session)
        database = self.persist_dir / 'native_elearning' / 'tracking.sqlite3'
        store = NativeElearningStore(database)
        with sqlite3.connect(database) as db:
            db.execute('''INSERT INTO learner_course_progress
                (session_id, trainee_id, course_id, course_version, current_activity_id,
                 completed_json, answers_json, active_seconds, score_percent, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                ('session-aps', 'trainee-1', 'academy-vtc-a', previous_version,
                 'vtc-a-01-cours', '["vtc-a-01-cours"]', '{}', 1234.5, 100.0, 'in_progress'))
        before = store.learner_progress('session-aps', 'trainee-1')
        self._public_login()
        response, config = self.exam()
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        notes = self.client.get('/espace/public-token/elearning/vtc/notions/A.01')
        self.assertEqual(notes.status_code, 200)
        player = self.client.get('/espace/public-token/elearning/academy-vtc-a',
                                 query_string={'activity': 'vtc-a-01-cours'})
        player_config = native_tests.NativeElearningWebTests._player_config(player)
        # The course stays pinned even though annales have an independent revision.
        access = json.loads(_b64decode(player_config['accessToken'].split('.')[0]))
        self.assertEqual(access['course_version'], previous_version)
        self.assertTrue(config['exam']['version'].startswith('annales-v1-'))
        self.assertEqual(self.submit(config).status_code, 200)
        self.assertEqual(store.learner_progress('session-aps', 'trainee-1'), before)
        self.assertEqual(session, original_assignment)
        self.assertIsNone(self.saved_data)

    def test_changed_bank_revision_never_reuses_previous_attempt_result(self):
        self.assign('A'); self._public_login()
        _, config = self.exam()
        self.assertEqual(self.submit(config).status_code, 200)
        original = annales.load_section(config['exam']['id'])
        revised = copy.deepcopy(original)
        revised['version'] = 'annales-v1-updated-revision'
        with patch('elearning_native.annales.load_section', return_value=revised):
            self.assertEqual(self.submit(config).status_code, 409)
            response, fresh = self.exam()
            self.assertEqual(fresh['exam']['version'], revised['version'])
            self.assertNotIn('Mes dernières tentatives', response.text)
            # A reused client attempt id is scoped to the new revision.
            fresh['attemptId'] = config['attemptId']
            self.assertEqual(self.submit(fresh).status_code, 200)
        database = self.persist_dir / 'native_elearning' / 'tracking.sqlite3'
        history = ExamStore(database)
        self.assertEqual(len(history.history('session-aps', 'trainee-1', original)), 1)
        self.assertEqual(len(history.history('session-aps', 'trainee-1', revised)), 1)
