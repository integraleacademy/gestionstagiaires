"""Final-exam time is additional, scoped and included once in APS reports."""
import copy
import io
import json
import sqlite3
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfReader

from elearning_native.academy import curriculum_manifest, load_bundled_course
from elearning_native.aps_final_time import FINAL_COURSE_ID, FINAL_ACTIVITY_ID, final_time
from elearning_native.store import NativeElearningStore
from elearning_native.videos import course_videos
from elearning_reporting import ProgressReader, certificate_pdf
from tests import test_aps_exam_time as module_tests


class APSFinalTimeTests(unittest.TestCase):
    setUp = module_tests.APSExamTimeTests.setUp
    tearDown = module_tests.APSExamTimeTests.tearDown
    _public_login = module_tests.APSExamTimeTests._public_login
    _admin_login = module_tests.APSExamTimeTests._admin_login
    _player_config = staticmethod(module_tests.APSExamTimeTests._player_config)
    _api_post = module_tests.APSExamTimeTests._api_post
    config = module_tests.APSExamTimeTests.config
    post = module_tests.APSExamTimeTests.post
    tracking = module_tests.APSExamTimeTests.tracking
    ping = module_tests.APSExamTimeTests.ping
    database = module_tests.APSExamTimeTests.database

    def seed(self, version=None):
        version = version or curriculum_manifest()['version']
        session = self.data['sessions'][0]
        session['id'] = 'el-final-order'
        modules = [{'course_id': m['id'], 'course_version': version, 'required_minutes': m['hours'] * 60}
                   for m in curriculum_manifest()['modules']]
        session['aps_native_modules'] = modules
        tracker = NativeElearningStore(self.database)
        for module in modules:
            course = load_bundled_course(module['course_id'], version)
            access = {'session_id': session['id'], 'trainee_id': 'trainee-1',
                      'course_id': course['id'], 'course_version': version}
            tracker.get_progress(access)
            videos = {aid: {vid: {'duration_seconds': duration, 'watched_seconds': duration, 'completed': True}
                           for vid, duration in requirements.items()}
                      for aid, requirements in course_videos(course).items()}
            with sqlite3.connect(self.database) as db:
                db.execute('UPDATE learner_course_progress SET active_seconds=?, completed_json=?, video_progress_json=? '
                           'WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?',
                           (module['required_minutes'] * 60, json.dumps(course['activity_order']), json.dumps(videos),
                            *[access[k] for k in ('session_id', 'trainee_id', 'course_id', 'course_version')]))
        self._public_login()
        return tracker, modules

    def open_final(self):
        page = self.client.get('/espace/public-token/elearning/exams/final')
        self.assertEqual(page.status_code, 200, page.text)
        return self._player_config(page), self.config(page), page

    def test_final_correction_retakes_totals_and_admin_export_preserve_module_budgets(self):
        tracker, modules = self.seed()
        before = tracker.learner_progress('el-final-order', 'trainee-1')
        cfg, exam, page = self.open_final()
        self.assertEqual(cfg['activityId'], FINAL_ACTIVITY_ID)
        self.assertEqual(cfg['idleSeconds'], 600)
        self.assertTrue(cfg['continueWhenHidden'])
        self.assertNotIn('id="nativeRemainingTime"', page.text)
        now = time.time()
        tracking = self.tracking(cfg, now)
        self.ping(cfg, tracking, now)
        for offset in (600, 1200, 1800):
            result = self.ping(cfg, tracking, now + offset)
        self.assertEqual(result['progress']['active_seconds'], 1800)
        self.assertEqual(self.post(exam).status_code, 200)
        self.assertEqual(self.post(exam).status_code, 200)  # retry adds neither time nor attempt
        self.assertEqual(self.ping(cfg, tracking, now + 1815)['progress']['active_seconds'], 1815)
        with patch('elearning_native.store.time.time', return_value=now + 1815):
            self._api_post(cfg['finishUrl'], cfg, tracking_session_id=tracking, activity_id=FINAL_ACTIVITY_ID)
            again, _, _ = self.open_final()
        self.assertEqual(again['initialActiveSeconds'], 1815)
        self.assertEqual([r for r in tracker.learner_progress('el-final-order', 'trainee-1')
                          if r['course_id'] != FINAL_COURSE_ID], before)
        self.assertEqual(sum(m['required_minutes'] for m in modules), 62 * 60)
        path = self.client.get('/espace/public-token/elearning').text
        self.assertIn('62:30:15', path)
        self.assertIn('Examen final et corrigé : 00:30:15', path)
        self._admin_login()
        response = self.client.get('/admin/elearning/exams/final/time')
        self.assertEqual(response.status_code, 200)
        self.assertIn('62:30:15', response.text)
        csv = self.client.get('/admin/elearning/exams/final/time.csv')
        self.assertEqual(csv.status_code, 200)
        self.assertIn('223200.0;1815.0;225015.0', csv.text)
        self.assertIn('no-store', csv.headers['Cache-Control'])
        # A database row from another centre must never appear.
        tracker.start_tracking({'session_id': 'other-centre', 'trainee_id': 'secret-name',
            'course_id': FINAL_COURSE_ID, 'course_version': modules[0]['course_version']},
            tab_id='private', activity_id=FINAL_ACTIVITY_ID)
        self.assertNotIn('secret-name', self.client.get('/admin/elearning/exams/final/time.csv').text)

    def test_final_idle_navigation_duplicates_and_scoped_authorization(self):
        tracker, _ = self.seed('20261004-aps62-v2')
        cfg, _, _ = self.open_final()
        now = time.time()
        first = self.tracking(cfg, now, tab='same-tab')
        self.ping(cfg, first, now)
        result = self.ping(cfg, first, now + 599, visible=False, focused=False, interaction_age_seconds=599)
        self.assertTrue(result['active'])
        self.assertEqual(result['progress']['active_seconds'], 599)
        result = self.ping(cfg, first, now + 600, visible=False, focused=False, interaction_age_seconds=600)
        self.assertFalse(result['active'])
        self.assertEqual(result['progress']['active_seconds'], 600)
        self.assertEqual(self.ping(cfg, first, now + 900, interaction_age_seconds=900)['credited_seconds'], 0)
        self.ping(cfg, first, now + 901)
        other = self.tracking(cfg, now + 902, tab='other-tab')
        self.assertTrue(self.ping(cfg, other, now + 902)['duplicate'])
        # Missing pagehide: navigation settles the final then starts the course.
        course_cfg = self._player_config(self.client.get('/espace/public-token/elearning/academy-aps62-01'))
        course_id = self.tracking(course_cfg, now + 910, tab='same-tab')
        self.assertTrue(self.ping(course_cfg, course_id, now + 910)['active'])
        final_row = next(r for r in tracker.learner_progress('el-final-order', 'trainee-1') if r['course_id'] == FINAL_COURSE_ID)
        self.assertEqual(final_row['active_seconds'], 609)
        self.assertEqual(self.ping(cfg, first, now + 911)['credited_seconds'], 0)
        self.assertEqual(self._api_post(cfg['startUrl'], cfg, tab_id='bad', activity_id='aps62-01-examen-blanc').status_code, 403)
        self.assertEqual(self._api_post('/api/elearning/v1/activities/anything/complete', cfg, activity_id=FINAL_ACTIVITY_ID).status_code, 403)
        self.data['sessions'][0]['aps_native_modules'].pop()
        self.assertEqual(self._api_post(cfg['heartbeatUrl'], cfg, tracking_session_id=first,
                                      activity_id=FINAL_ACTIVITY_ID, interaction_age_seconds=0).status_code, 403)

    def test_final_does_not_unlock_until_each_module_time_is_met(self):
        _, _ = self.seed()
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE learner_course_progress SET active_seconds=14399 WHERE course_id='academy-aps62-01'")
        self.assertEqual(self.client.get('/espace/public-token/elearning/exams/final').status_code, 403)
        self.assertNotIn('Commencer l’examen final', self.client.get('/espace/public-token/elearning').text)

    def test_read_only_purchased_reporting_pdf_and_connections_include_final_once(self):
        tracker, modules = self.seed()
        cfg, _, _ = self.open_final()
        now = time.time()
        tracking = self.tracking(cfg, now)
        self.ping(cfg, tracking, now)
        self.ping(cfg, tracking, now + 90)
        # A different edition/person/order must not enter the total or evidence.
        for key in ({'course_version': 'unassigned'}, {'trainee_id': 'other'}, {'session_id': 'el-other'}):
            access = {'session_id': 'el-final-order', 'trainee_id': 'trainee-1',
                      'course_id': FINAL_COURSE_ID, 'course_version': modules[0]['course_version'], **key}
            tracker.start_tracking(access, tab_id='private', activity_id=FINAL_ACTIVITY_ID)
        order = {'id': 'final-order', 'course_code': 'aps', 'modules': modules}
        person = self.data['sessions'][0]['trainees'][0]
        def dump():
            with sqlite3.connect(self.database) as db:
                return list(db.iterdump())
        before = dump()
        reader = ProgressReader(SimpleNamespace(PERSIST_DIR=str(self.persist_dir)))
        report = reader.report(order, person)
        self.assertEqual(report['active_seconds'], 223290)
        self.assertEqual(report['module_active_seconds'], report['required_seconds'])
        self.assertEqual(report['required_seconds'], 223200)
        self.assertEqual(report['final_exam_time']['active_seconds'], 90)
        self.assertEqual(report['completed_modules'], 15)
        self.assertEqual(len(report['connections']), 1)
        self.assertEqual(report['connections'][0]['course_id'], FINAL_COURSE_ID)
        self.assertEqual(report['connections'][0]['credited_seconds'], 90)
        self.assertEqual(reader.report(order, person, detailed=False)['active_seconds'], 223290)
        pdf = certificate_pdf(report, {'name': 'Centre de test'}, order, person)
        pdf_text = '\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
        self.assertIn('62 h 01 min 30 s', pdf_text)
        self.assertIn('Examen blanc final APS', pdf_text)
        self.assertIn('00 h 01 min 30 s', pdf_text)
        self.assertEqual(dump(), before)
        partial = copy.deepcopy(order)
        partial['modules'].pop()
        self.assertIsNone(reader.report(partial, person)['final_exam_time'])
        mixed = copy.deepcopy(modules)
        mixed[0]['course_version'] = 'other'
        self.assertIsNone(final_time(mixed, []))
