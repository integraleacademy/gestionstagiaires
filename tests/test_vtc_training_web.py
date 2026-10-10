"""Free practice stays outside course, time and examination persistence."""
import copy
import json
import re
import sqlite3
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from tests import test_native_elearning_web as native_tests
from elearning_native import vtc, vtc_training_web
from elearning_native.store import NativeElearningStore
from elearning_native.web import _b64decode


class VtcTrainingWebTests(unittest.TestCase):
    tearDown = native_tests.NativeElearningWebTests.tearDown
    _admin_login = native_tests.NativeElearningWebTests._admin_login
    _public_login = native_tests.NativeElearningWebTests._public_login

    def setUp(self):
        native_tests.NativeElearningWebTests.setUp(self)
        self.bank_root = self.persist_dir / 'training'
        self.root_patch = patch.object(vtc_training_web, 'ROOT', self.bank_root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.vtc_course = vtc.load_bundled_course('academy-vtc-a')
        self.ids = [section['activities'][1]['id'] for section in self.vtc_course['sections'][:2]]
        self.training = {'version': self.vtc_course['version'], 'course_id': self.vtc_course['id'],
                         'title': 'Situations complémentaires', 'activities': []}
        for index, aid in enumerate(self.ids):
            self.training['activities'].append({'id': aid, 'title': f'Dossier libre {index + 1}',
                'vtc': {'ref': f'A.0{index + 1}', 'kind': 'dossier'},
                'practice': {'revision': 'training-test-1', 'mode': 'journey', 'adaptive': False,
                    'purpose': 'Vérifier la décision', 'exercises': [
                        {'id': 'free-single', 'kind': 'single', 'prompt': 'Quel choix convient ?',
                         'options': [{'id': 'a', 'text': 'Vérifier'}, {'id': 'b', 'text': 'Attendre'}],
                         'answer': 'a', 'explanation': 'Explication privée de la première question.',
                         'coaching': 'Conseil privé de révision.', 'competency': 'A.01',
                         'consequences': {'b': 'Conséquence privée du choix.'}},
                        {'id': 'free-match', 'kind': 'matching', 'prompt': 'Associez les étapes.',
                         'options': [{'id': 'x', 'text': 'Avant'}, {'id': 'y', 'text': 'Après'}],
                         'rows': [{'id': 'r1', 'text': 'Contrôler', 'answer': 'x'},
                                  {'id': 'r2', 'text': 'Conclure', 'answer': 'y'}],
                         'explanation': 'Explication privée de la deuxième question.'}]}})
        self.write_bank()

    def write_bank(self, bank=None):
        bank = bank or self.training
        path = self.bank_root / bank['version'] / (bank['course_id'] + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(bank), encoding='utf-8')

    def assign(self, version=None, partial=False):
        session = self.data['sessions'][0]
        module = {'course_id': 'academy-vtc-a', 'course_version': version or self.vtc_course['version']}
        if partial:
            module['section_ids'] = [self.vtc_course['sections'][0]['id']]
        session.update(training_type='VTC', aps_native_modules=[module])
        return session

    def page(self, *, admin=False, version=None, activity=None):
        base = '/admin' if admin else '/espace/public-token'
        response = self.client.get(f'{base}/elearning/vtc/entrainement/academy-vtc-a/{activity or self.ids[0]}',
                                   query_string={'version': version} if version else {})
        self.assertEqual(response.status_code, 200, response.text[:300])
        def config(name):
            return json.loads(re.search(fr'<script id="{name}" type="application/json">(.*?)</script>',
                                       response.text, re.S)[1])
        return response, config('nativePreviewConfig'), config('vtcJourneyConfig')

    def post(self, config, answers=None, step='free-single'):
        payload = {'practice_answers': answers if answers is not None else {'free-single': 'a'}}
        if step is not None:
            payload['practice_step'] = step
        return self.client.post(config['answerUrl'], json=payload,
                                headers={'X-Elearning-CSRF': config['csrfToken']})

    def test_admin_has_no_answer_keys_tracking_or_precheck_corrections(self):
        self._admin_login()
        response, config, journey = self.page(admin=True)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertTrue(journey['freePractice'])
        self.assertFalse(journey['completed'])
        self.assertEqual(journey['saved'], {})
        self.assertNotIn('accessToken', config)
        for marker in ('nativeElearningConfig', 'native-elearning-player.js', 'native-elearning-preview.js',
                       'Explication privée', 'Conseil privé', 'Conséquence privée'):
            self.assertNotIn(marker, response.text)
        for exercise in journey['practice']['exercises']:
            self.assertFalse({'answer', 'explanation', 'coaching', 'consequences'} & exercise.keys())
            self.assertTrue(all('answer' not in row for row in exercise.get('rows', [])))
        corrected = self.post(config, {'free-single': 'b'})
        self.assertEqual(corrected.status_code, 200)
        self.assertFalse(corrected.json['correct'])
        self.assertEqual([item['id'] for item in corrected.json['feedback']], ['free-single'])
        self.assertIn('Explication privée de la première', corrected.json['feedback'][0]['explanation'])
        self.assertNotIn('Explication privée de la deuxième', json.dumps(corrected.json, ensure_ascii=False))
        self.assertFalse((self.persist_dir / 'native_elearning' / 'tracking.sqlite3').exists())
        self.assertIsNone(self.saved_data)

    def test_learner_multiple_checks_create_no_tracking_or_attempts(self):
        self.assign(); self._public_login()
        _, config, _ = self.page()
        for _ in range(2):
            self.assertEqual(self.post(config).status_code, 200)
        complete = self.post(config, {'free-single': 'a', 'free-match': {'r1': 'x', 'r2': 'y'}}, step=None)
        self.assertEqual(complete.status_code, 200)
        self.assertTrue(complete.json['correct'])
        self.assertNotIn('progress', complete.json)
        self.assertNotIn('attempt_id', complete.json)
        self.assertFalse((self.persist_dir / 'native_elearning' / 'tracking.sqlite3').exists())
        self.assertIsNone(self.saved_data)

    def test_csrf_viewer_stale_revision_and_invalid_answer_fail_closed(self):
        self._admin_login(); _, config, _ = self.page(admin=True)
        self.assertEqual(self.client.post(config['answerUrl'], json={}).status_code, 403)
        for answers, step in (({}, 'free-single'), ({'free-single': ['a']}, 'free-single'),
                              ({'free-single': 'a'}, 'unknown'),
                              ({'free-match': {'r1': 'x', 'r2': 'x'}}, 'free-match')):
            self.assertEqual(self.post(config, answers, step).status_code, 400)
        for key in ('bank_version', 'revision'):
            stale = copy.deepcopy(config)
            parts = urlsplit(stale['answerUrl']); query = parse_qs(parts.query)
            query[key] = ['obsolete']
            stale['answerUrl'] = urlunsplit(parts._replace(query=urlencode(query, doseq=True)))
            self.assertEqual(self.post(stale).status_code, 409)
        with self.client.session_transaction() as browser:
            browser['admin_role'] = 'viewer'
        response, viewer_config, _ = self.page(admin=True)
        self.assertIn('data-vtc-check disabled', response.text)
        self.assertEqual(self.post(viewer_config).status_code, 403)

    def test_auth_tenant_dates_and_assignment_apply_to_catalog_page_and_api(self):
        current = self.assign()
        base = '/espace/public-token/elearning/vtc/entrainement/academy-vtc-a'
        self.assertEqual(self.client.get(base).status_code, 401)
        self.assertEqual(self.client.get(base + '/' + self.ids[0]).status_code, 401)
        self._public_login(); _, config, _ = self.page()
        other = copy.deepcopy(current); other['id'] = 'other-session'
        other['trainees'][0].update(id='other-trainee', public_token='other-token')
        self.data['sessions'].append(other)
        self.assertEqual(self.client.get(base.replace('public-token', 'other-token')).status_code, 401)
        swapped = {**config, 'answerUrl': config['answerUrl'].replace('public-token', 'other-token')}
        self.assertEqual(self.post(swapped).status_code, 401)
        self.assertEqual(self.client.get(base.replace('academy-vtc-a', 'academy-vtc-b')).status_code, 403)
        current['date_start'] = '2099-01-01'
        self.assertEqual(self.client.get(base).status_code, 403)
        self.assertEqual(self.client.get(base + '/' + self.ids[0]).status_code, 403)
        self.assertEqual(self.post(config).status_code, 403)

    def test_partial_assignment_excludes_unselected_dossiers_and_prerequisites_hold(self):
        session = self.assign(partial=True); self._public_login()
        base = '/espace/public-token/elearning/vtc/entrainement/academy-vtc-a'
        response = self.client.get(base)
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.ids[0], response.text); self.assertNotIn(self.ids[1], response.text)
        self.assertEqual(self.client.get(base + '/' + self.ids[1]).status_code, 404)
        _, config, _ = self.page()
        excluded = {**config, 'answerUrl': config['answerUrl'].replace(self.ids[0], self.ids[1])}
        self.assertEqual(self.post(excluded).status_code, 404)
        session['aps_native_modules'].insert(0, {'course_id': 'academy-vtc-b',
            'course_version': vtc.load_bundled_course('academy-vtc-b')['version']})
        self.assertEqual(self.client.get(base).status_code, 403)
        self.assertEqual(self.client.get(base + '/' + self.ids[0]).status_code, 403)
        self.assertEqual(self.post(config).status_code, 403)

    def test_old_course_uses_supplements_without_changing_saved_progress(self):
        version = '20261006-vtc-v3-105h'
        session = self.assign(version=version); original_session = copy.deepcopy(session)
        database = self.persist_dir / 'native_elearning' / 'tracking.sqlite3'
        store = NativeElearningStore(database)
        with sqlite3.connect(database) as db:
            db.execute('''INSERT INTO learner_course_progress
                (session_id, trainee_id, course_id, course_version, current_activity_id,
                 completed_json, answers_json, active_seconds, score_percent, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                ('session-aps', 'trainee-1', 'academy-vtc-a', version, 'vtc-a-01-cours',
                 '["vtc-a-01-cours"]', '{"legacy":{"correct":true}}', 987.5, 80.0, 'in_progress'))
        before = store.learner_progress('session-aps', 'trainee-1')
        self._public_login(); _, config, journey = self.page()
        self.assertIn(self.training['version'], journey['courseVersion'])
        self.assertEqual(self.post(config).status_code, 200)
        self.assertEqual(store.learner_progress('session-aps', 'trainee-1'), before)
        self.assertEqual(session, original_session)
        self.assertIsNone(self.saved_data)

    def test_assigned_bank_precedes_current_bank_and_admin_version_is_validated(self):
        old = copy.deepcopy(self.training); old['version'] = '20261006-vtc-v3-105h'
        old['activities'][0]['title'] = 'Édition complémentaire affectée'
        self.write_bank(old); self.assign(old['version']); self._public_login()
        response, _, journey = self.page()
        self.assertIn('Édition complémentaire affectée', response.text)
        self.assertTrue(journey['courseVersion'].startswith(old['version']))
        self._admin_login()
        response, _, _ = self.page(admin=True, version=old['version'])
        self.assertIn('Édition complémentaire affectée', response.text)
        path = '/admin/elearning/vtc/entrainement/academy-vtc-a'
        self.assertEqual(self.client.get(path, query_string={'version': '../../manifest'}).status_code, 404)
        self.assertEqual(self.client.get(path.replace('academy-vtc-a', 'academy-aps62')).status_code, 404)

    def test_first_editions_get_new_dossiers_only_for_their_assigned_lessons(self):
        self.ids = ['vtc-a-01-dossier', 'vtc-a-02-dossier']
        for index, activity in enumerate(self.training['activities']):
            activity['id'] = self.ids[index]
            for exercise in activity['practice']['exercises']:
                exercise['competency'] = f'A.0{index + 1}'
        mixed = copy.deepcopy(self.training['activities'][0])
        mixed['id'] = 'vtc-a-mission-1'
        mixed['practice']['exercises'][1]['competency'] = 'A.02'
        self.training['activities'].append(mixed)
        self.write_bank()
        session = self.assign('20261006-vtc-v1', partial=True)
        original = copy.deepcopy(session)
        self._public_login()
        base = '/espace/public-token/elearning/vtc/entrainement/academy-vtc-a'
        response = self.client.get(base)
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.ids[0], response.text)
        self.assertNotIn(self.ids[1], response.text)
        self.assertNotIn(mixed['id'], response.text)
        _, config, _ = self.page()
        self.assertEqual(self.post(config).status_code, 200)
        self.assertEqual(self.client.get(base + '/' + self.ids[1]).status_code, 404)
        self.assertEqual(self.client.get(base + '/' + mixed['id']).status_code, 404)
        self.assertEqual(session, original)
        self.assertFalse((self.persist_dir / 'native_elearning' / 'tracking.sqlite3').exists())
        self.assign('20261006-vtc-v2')
        response = self.client.get(base)
        self.assertIn(self.ids[0], response.text)
        self.assertIn(self.ids[1], response.text)
        self.assertIn(mixed['id'], response.text)

    def test_audio_uses_assigned_asset_signature_and_missing_asset_has_text_fallback(self):
        version = '20261006-vtc-v3-105h'
        old = vtc.load_bundled_course('academy-vtc-a', version)
        asset = next(name for name in old['assets'] if name.startswith('media/vtc/'))
        exercise = self.training['activities'][0]['practice']['exercises'][0]
        exercise.update(audio=asset, transcript=[{'speaker': 'Client', 'text': 'Good morning.'}],
                        translation='Bonjour.')
        self.write_bank(); self.assign(version); self._public_login()
        _, _, journey = self.page()
        audio = journey['practice']['exercises'][0]['audio']
        signed = parse_qs(urlsplit(audio).query)['access'][0]
        access = json.loads(_b64decode(signed.split('.')[0]))
        self.assertEqual(access['course_version'], version)
        self.assertEqual(access['kind'], 'course_asset')
        exercise['audio'] = 'media/vtc/not-in-assigned-edition.mp3'; self.write_bank()
        response, _, journey = self.page()
        public = journey['practice']['exercises'][0]
        self.assertNotIn('audio', public)
        self.assertIn('Good morning.', response.text)
        self.assertIn('ne font pas partie de votre édition', response.text)
        self.assertNotIn('not-in-assigned-edition', response.text)


if __name__ == '__main__':
    unittest.main()
