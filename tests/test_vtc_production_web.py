"""Authenticated written-work flow, including preview and strict completion."""
import copy
import json
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
        self.assertIn('Objectif de cet atelier', page.text)
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

    def test_administrator_review_is_csrf_protected_and_persistent(self):
        _,config=self.open()
        self.api.return_value={**FEEDBACK,'needs_human_review':True}
        attempt=self.post(config).json['attempt_id']
        self._admin_login()
        url=f'/api/admin/elearning/vtc/productions/{attempt}/review'
        payload={'outcome':'reviewed','comment':'Réponse relue et expliquée avec le stagiaire ; les points essentiels sont présents.'}
        self.assertEqual(self.client.post(url,json=payload).status_code,403)
        result=self.client.post(url,json=payload,headers={'X-Elearning-CSRF':config['csrfToken']})
        self.assertEqual(result.status_code,200,result.text)
        done=self._api_post('/api/elearning/v1/activities/content-1/complete',config,production_answers=ANSWERS,production_reviewed=True)
        self.assertEqual(done.status_code,200,done.text)
        self.assertEqual(done.json['progress']['answers']['content-1']['review_status'],'trainer_reviewed')

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
