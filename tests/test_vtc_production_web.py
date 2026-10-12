"""Authenticated written-work flow, including preview and strict completion."""
import copy
import json
import time
from pathlib import Path

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
import unittest
from unittest.mock import patch

import app as host
from elearning_native.store import NativeElearningStore
from elearning_native.vtc_ai import VtcAIError
from tests import test_native_elearning_web as fixture
from tests.test_vtc_production_work import ASSIGNMENT, ANSWERS, FEEDBACK


class VtcProductionWebTests(unittest.TestCase):
    tearDown = fixture.NativeElearningWebTests.tearDown
    _admin_login = fixture.NativeElearningWebTests._admin_login
    _public_login = fixture.NativeElearningWebTests._public_login
    _api_post = fixture.NativeElearningWebTests._api_post
    _player_config = staticmethod(fixture.NativeElearningWebTests._player_config)
    _preview_config = fixture.NativeElearningWebTests._preview_config

    def setUp(self):
        fixture.NativeElearningWebTests.setUp(self)
        self.course['training_label'] = 'VTC'
        self.course['sections'][0]['activities'][0].update(
            production=copy.deepcopy(ASSIGNMENT), blocks=[], vtc={'kind': 'production', 'module': 'A'})
        target = self.persist_dir/'native_elearning'/'courses'/self.course['id']/self.course['version']/'course.json'
        target.write_text(json.dumps(self.course))
        self.data['sessions'][0]['training_type'] = 'VTC'
        self.grader = patch('elearning_native.vtc_ai.grade_written_work', return_value=copy.deepcopy(FEEDBACK))
        self.api = self.grader.start()
        self.addCleanup(self.grader.stop)

    def open(self):
        self._public_login()
        page = self.client.get(f'/espace/public-token/elearning/{self.course["id"]}')
        self.assertEqual(page.status_code, 200, page.text)
        return page, self._player_config(page)

    def post(self, config, **extra):
        return self._api_post('/api/elearning/v1/activities/content-1/production', config,
            stage='correct', production_answers=ANSWERS, **extra)

    def test_complete_lifecycle_requires_real_correction_and_acknowledgement(self):
        page, config = self.open()
        self.assertIn('vtc-production.js', page.text)
        self.assertNotIn('MODÈLE PRIVÉ', page.text)
        self.assertIn('Repère pour progresser dans cet atelier', page.text)
        self.assertIn('Cette production est facultative.', page.text)
        self.assertIn('sans rédiger ni demander de correction', page.text)
        url='/api/elearning/v1/activities/content-1/complete'
        early=self._api_post(url,config,production_answers=ANSWERS,production_reviewed=True,score=20)
        self.assertEqual(early.status_code,400)
        corrected=self.post(config)
        self.assertEqual(corrected.status_code,200,corrected.text)
        self.assertEqual(self.api.call_count,1)
        missing=self._api_post(url,config,production_answers=ANSWERS)
        self.assertEqual(missing.status_code,400)
        done=self._api_post(url,config,production_answers=ANSWERS,production_reviewed=True)
        self.assertEqual(done.status_code,200,done.text)
        self.assertIn('content-1',done.json['progress']['completed_activity_ids'])
        self.assertEqual(done.json['progress']['active_seconds'],0)
        self.assertFalse(done.json['progress']['answers']['content-1']['production_draft'])
        self.assertEqual(self.post(config).status_code,409)

    def test_preview_is_corrected_without_any_learner_tracking(self):
        self._admin_login()
        with patch('elearning_native.web.NativeElearningStore',side_effect=AssertionError('preview must not track')):
            page, config=self._preview_config()
            result=self.client.post(config['answerUrl'],json={'production_answers':ANSWERS},headers={'X-Elearning-CSRF':config['csrfToken']})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json['feedback']['score'],18)
        self.assertFalse((self.persist_dir/'native_elearning'/'tracking.sqlite3').exists())

    def test_csrf_revocation_and_viewer_protect_ai_calls(self):
        _,config=self.open()
        raw={'access_token':config['accessToken'],'stage':'correct','production_answers':ANSWERS}
        self.assertEqual(self.client.post('/api/elearning/v1/activities/content-1/production',json=raw).status_code,403)
        self.data['sessions'][0]['aps_elearning_enabled']=False
        self.assertEqual(self.post(config).status_code,403)
        self.assertEqual(self.api.call_count,0)
        self._admin_login()
        with self.client.session_transaction() as state:state['admin_role']='viewer'
        _,preview=self._preview_config()
        result=self.client.post(preview['answerUrl'],json={'production_answers':ANSWERS},headers={'X-Elearning-CSRF':preview['csrfToken']})
        self.assertEqual(result.status_code,403)
        self.assertEqual(self.api.call_count,0)

    def test_provider_error_does_not_complete_and_keeps_original_copy(self):
        _,config=self.open()
        self.api.side_effect=VtcAIError('unavailable')
        result=self.post(config)
        self.assertEqual(result.status_code,503)
        self.assertNotIn('score',result.json)
        rows=NativeElearningStore(self.persist_dir/'native_elearning'/'tracking.sqlite3').learner_progress('session-aps','trainee-1')
        self.assertEqual(rows[0]['answers']['content-1']['production_first_answers'],ANSWERS)
        self.assertEqual(rows[0]['completed_activity_ids'],[])

    def test_retired_manual_review_keeps_csrf_scope_and_the_existing_result(self):
        _, config = self.open()
        attempt = self.post(config).json['attempt_id']
        store = NativeElearningStore(self.persist_dir/'native_elearning'/'tracking.sqlite3')
        with store._connect() as db:
            before = dict(db.execute('SELECT * FROM vtc_written_attempts WHERE id=?', (attempt,)).fetchone())
        self._admin_login()
        url = f'/api/admin/elearning/vtc/productions/{attempt}/review'
        payload = {'outcome': 'reviewed', 'comment': 'Cette action ne doit plus changer les résultats existants.'}
        self.assertEqual(self.client.post(url, json=payload).status_code, 403)
        result = self.client.post(url, json=payload, headers={'X-Elearning-CSRF': config['csrfToken']})
        self.assertEqual(result.status_code, 410, result.text)
        self.assertNotRegex(result.json['error'], r'(?i)formateur|ChatGPT|OpenAI|\bIA\b')
        with store._connect() as db:
            self.assertEqual(dict(db.execute('SELECT * FROM vtc_written_attempts WHERE id=?', (attempt,)).fetchone()), before)
        done = self._api_post('/api/elearning/v1/activities/content-1/complete', config, production_answers=ANSWERS, production_reviewed=True)
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json['progress']['answers']['content-1']['review_status'], 'ai_feedback_read')

    def test_unverified_output_is_retryable_without_a_grade_or_trainer_instruction(self):
        _, config = self.open()
        self.api.return_value = {**FEEDBACK, 'needs_human_review': True}
        result = self.post(config)
        self.assertEqual(result.status_code, 503, result.text)
        self.assertNotIn('score', result.json)
        self.assertNotRegex(result.json['error'], r'(?i)formateur|ChatGPT|OpenAI|\bIA\b')
        store = NativeElearningStore(self.persist_dir/'native_elearning'/'tracking.sqlite3')
        row = store.learner_progress('session-aps', 'trainee-1')[0]
        self.assertEqual(row['completed_activity_ids'], [])
        self.assertEqual(row['answers']['content-1']['production_first_answers'], ANSWERS)
        self.api.return_value = FEEDBACK
        with patch('elearning_native.vtc_production_work.time.time', return_value=time.time() + 10):
            retried = self.post(config)
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertFalse(retried.json['cached'])
        self.assertEqual([attempt['status'] for attempt in retried.json['history']], ['corrected', 'failed'])

    def test_administrator_cannot_review_a_copy_outside_the_current_centre(self):
        _, config = self.open()
        attempt = self.post(config).json['attempt_id']
        self._admin_login()
        self.data['sessions'] = []
        result = self.client.post(f'/api/admin/elearning/vtc/productions/{attempt}/review',
            json={'outcome': 'reviewed', 'comment': 'Ce retour ne doit pas modifier la copie d’un autre centre.'},
            headers={'X-Elearning-CSRF': config['csrfToken']})
        self.assertEqual(result.status_code, 404)
        with NativeElearningStore(self.persist_dir/'native_elearning'/'tracking.sqlite3')._connect() as db:
            self.assertEqual(db.execute('SELECT status FROM vtc_written_attempts WHERE id=?', (attempt,)).fetchone()[0], 'corrected')

    def test_vtc_production_cannot_use_the_separate_aps_analysis_endpoints(self):
        _, config = self.open()
        for action in ('production-analysis', 'production-analyses'):
            result = self._api_post(f'/api/elearning/v1/activities/content-1/{action}', config, production_answers=ANSWERS)
            self.assertEqual(result.status_code, 404)
        self.assertEqual(self.api.call_count, 0)


class VtcProductionDisplayTests(unittest.TestCase):
    def environment(self):
        return Environment(loader=ChoiceLoader([
            DictLoader({'base.html': '{% block content %}{% endblock %}',
                        'manuals/layout.html': '{% block content %}{% endblock %}'}),
            FileSystemLoader(Path(__file__).resolve().parents[1] / 'templates'),
        ]), autoescape=True)

    def test_nonconfirmed_feedback_hides_old_score_comments_and_instructions(self):
        template = self.environment().get_template('_vtc_work_feedback.html')
        variants = [
            {**FEEDBACK, 'needs_human_review': True},
            {**FEEDBACK, 'human_review_reasons': ['Sollicitez le formateur et le correcteur IA.']},
            {**FEEDBACK, 'criteria': [{**FEEDBACK['criteria'][0], 'status': 'uncertain'}, FEEDBACK['criteria'][1]]},
            {**FEEDBACK, 'criteria': [{**FEEDBACK['criteria'][0], 'points': 99}, FEEDBACK['criteria'][1]]},
            {**FEEDBACK, 'criteria': [{**FEEDBACK['criteria'][0], 'points': True}, FEEDBACK['criteria'][1]]},
            {**FEEDBACK, 'score': 19},
        ]
        for value in variants:
            with self.subTest(value=value):
                rendered = template.render(ai_feedback=value, feedback_completed=False)
                self.assertIn('Correction à relancer', rendered)
                self.assertNotIn('18 / 20', rendered)
                self.assertNotIn(FEEDBACK['summary'], rendered)
                self.assertNotRegex(rendered, r'(?i)formateur|ChatGPT|OpenAI|\bIA\b')

    def test_historical_decision_is_displayed_only_for_a_completed_workshop(self):
        template = self.environment().get_template('_vtc_work_feedback.html')
        archived = {**FEEDBACK, 'status': 'trainer_reviewed', 'score': 8,
                    'human_review_reasons': ['Ancien doute.'],
                    'trainer_review': {'outcome': 'reviewed', 'comment': 'Ancienne décision conservée.'}}
        incomplete = template.render(ai_feedback=archived, feedback_completed=False)
        self.assertIn('Correction à relancer', incomplete)
        self.assertNotIn('8 / 20', incomplete)
        complete = template.render(ai_feedback=archived, feedback_completed=True)
        self.assertIn('Résultat conservé de cet atelier terminé', complete)
        self.assertIn('8 / 20', complete)
        self.assertIn('Ancienne décision conservée.', complete)
        self.assertNotIn('Correction à relancer', complete)
        self.assertNotIn('Ancien doute.', complete)
        # An inconsistent old automatic result does not invalidate completion.
        preserved = template.render(ai_feedback={**FEEDBACK, 'needs_human_review': True}, feedback_completed=True)
        self.assertIn('Atelier terminé · résultat conservé', preserved)
        self.assertNotIn('18 / 20', preserved)

    def test_shared_followup_templates_keep_aps_labels_and_remove_vtc_manual_actions(self):
        environment = self.environment()
        production = {'draft': True, 'ai_feedback': {**FEEDBACK, 'needs_human_review': True},
                      'responses': [], 'first_responses': [], 'review': [{'label': 'Communication', 'needs_help': True}]}
        activity = {'title': 'Ma production', 'completed': False, 'optional': True, 'production': production}
        module = {'title': 'Module A', 'available': True, 'progress_percent': 0,
                  'sections': [{'title': 'Séquence', 'activities': [activity]}]}
        report = {'available': True, 'progress_percent': 0, 'modules': [module],
                  'exams': [], 'cma_attempts': [], 'connections': []}
        work = {'activity_id': 'copy-1', 'title': 'Ma production', 'production': True, 'draft': True,
                'ai_feedback': production['ai_feedback'], 'ai_attempt_id': 'old-attempt',
                'self_review': production['review'], 'ai_history': []}
        initial = {'course': {'id': 'academy-vtc-a', 'title': 'Module A'},
                   'learners': [{'written_work': [work], 'completed_activity_ids': [], 'cma_attempts': []}]}
        for code in ('vtc', 'aps'):
            with self.subTest(code=code):
                values = {'is_vtc': code == 'vtc', 'initial': initial, 'work_count': 1, 'cma_count': 0,
                          'config': {}, 'session': {'admin_role': 'admin'}, 'url_for': lambda *args, **kwargs: '/test',
                          'order': {'id': 'order-1', 'course_code': code}, 'course': {},
                          'person': {'id': 'learner-1'}, 'group': None, 'report': report}
                for name in ('admin_native_elearning_work.html', 'manuals/elearning_progress.html'):
                    with self.subTest(template=name):
                        rendered = environment.get_template(name).render(**values)
                        if code == 'vtc':
                            self.assertIn('Point à retravailler', rendered)
                            self.assertIn('Correction à relancer', rendered)
                            self.assertNotRegex(rendered, r'(?i)formateur|ChatGPT|OpenAI|\bIA\b')
                            self.assertNotIn('data-vtc-review-form', rendered)
                            self.assertNotIn('vtc-work-review.js', rendered)
                            self.assertNotIn('18 / 20', rendered)
                        else:
                            self.assertIn('Aide du formateur souhaitée', rendered)
                            self.assertIn('validation du formateur', rendered)
