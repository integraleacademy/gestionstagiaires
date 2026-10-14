"""APS mock-exam time belongs to the assigned module's existing time budget."""
import copy
import json
import sqlite3
import time
import unittest
from unittest.mock import patch

from elearning_native.academy import curriculum_manifest, load_bundled_course
from elearning_native.exams import module_exam_activity_id
from elearning_native.store import NativeElearningStore
from elearning_native.videos import course_videos
from tests import test_native_elearning_exams as exams
from tests import test_native_elearning_web as web


class APSExamTimeTests(unittest.TestCase):
    setUp = web.NativeElearningWebTests.setUp
    tearDown = web.NativeElearningWebTests.tearDown
    _public_login = web.NativeElearningWebTests._public_login
    _admin_login = web.NativeElearningWebTests._admin_login
    _player_config = staticmethod(web.NativeElearningWebTests._player_config)
    _api_post = web.NativeElearningWebTests._api_post
    config = exams.ExamWebTests.config
    post = exams.ExamWebTests.post

    def assign(self, number=1, version=None):
        self.course = load_bundled_course(f'academy-aps62-{number:02d}', version)
        self.data['sessions'][0]['aps_native_modules'] = [{
            'course_id': self.course['id'], 'course_version': self.course['version'],
            'required_minutes': self.course['required_minutes'],
        }]
        self._public_login()
        page = self.client.get(f'/espace/public-token/elearning/exams/module-{number:02d}')
        self.assertEqual(page.status_code, 200)
        return self._player_config(page), self.config(page), page

    def tracking(self, config, when, *, tab='exam', **extra):
        with patch('elearning_native.store.time.time', return_value=when):
            result = self._api_post(config['startUrl'], config, tab_id=tab,
                                    activity_id=config['activityId'], **extra)
        self.assertEqual(result.status_code, 200)
        return result.json['tracking_session_id']

    def ping(self, config, tracking_id, when, **extra):
        payload = dict(tracking_session_id=tracking_id, activity_id=config['activityId'],
                       visible=True, focused=True, recent_activity=True, interaction_age_seconds=0)
        payload.update(extra)
        with patch('elearning_native.store.time.time', return_value=when):
            result = self._api_post(config['heartbeatUrl'], config, **payload)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json

    @property
    def database(self):
        return self.persist_dir / 'native_elearning' / 'tracking.sqlite3'

    def test_all_fifteen_modules_credit_their_own_existing_budget(self):
        now = time.time()
        for number in range(1, 16):
            with self.subTest(module=number):
                cfg, _, page = self.assign(number)
                self.assertIn('Examen blanc et corrigé inclus', page.text)
                self.assertIn('native-elearning-player.js', page.text)
                self.assertEqual(cfg['activityId'], f'aps62-{number:02d}-examen-blanc')
                self.assertEqual(cfg['idleSeconds'], 600)
                self.assertTrue(cfg['continueWhenHidden'])
                tracking = self.tracking(cfg, now)
                self.ping(cfg, tracking, now)
                result = self.ping(cfg, tracking, now + 15)
                self.assertEqual(result['credited_seconds'], 15)
                self.assertEqual(result['progress']['course_id'], self.course['id'])
                self.assertEqual(result['progress']['active_seconds'], 15)
                self.assertEqual(result['progress']['remaining_seconds'], self.course['required_minutes'] * 60 - 15)
                self.assertEqual(result['progress']['completed_activity_ids'], [])
                self.assertEqual(result['progress']['answers'], {})
                self.assertEqual(result['progress']['video_progress'], {})
                with patch('elearning_native.store.time.time', return_value=now + 15):
                    self._api_post(cfg['finishUrl'], cfg, tracking_session_id=tracking, activity_id=cfg['activityId'])
                now += 60

    def test_old_editions_with_exams_keep_their_ids_and_minutes(self):
        covered = 0
        for module in curriculum_manifest()['modules']:
            for version in [module['version'], *module['previous_versions']]:
                course = load_bundled_course(module['id'], version)
                before = copy.deepcopy(course)
                activity = module_exam_activity_id(course)
                if course.get('mock_exam_id'):
                    self.assertTrue(activity)
                    self.assertNotIn(activity, course['activity_order'])
                    covered += 1
                else:
                    self.assertEqual(activity, '')
                self.assertEqual(course, before)
        self.assertGreaterEqual(covered, 165)
        cfg, _, _ = self.assign(version=exams.VERSION)
        now = time.time()
        tracking = self.tracking(cfg, now)
        self.ping(cfg, tracking, now)
        self.assertEqual(self.ping(cfg, tracking, now + 15)['progress']['active_seconds'], 15)

    def test_three_and_a_half_hours_plus_half_hour_exam_reaches_four_hours(self):
        cfg, exam_cfg, _ = self.assign()
        now = time.time()
        tracking = self.tracking(cfg, now)
        answers = {a['id']: {'correct': True, 'selected': ['saved'], 'submitted_at': '2026-10-01T10:00:00Z'}
                   for section in self.course['sections'] for a in section['activities'] if a.get('scored')}
        video = {aid: {vid: {'completed': True, 'watched_seconds': duration, 'duration_seconds': duration}
                      for vid, duration in requirements.items()}
                 for aid, requirements in course_videos(self.course).items()}
        saved = [json.dumps(self.course['activity_order']), json.dumps(answers), json.dumps(video)]
        with sqlite3.connect(self.database) as db:
            db.execute('UPDATE learner_course_progress SET active_seconds=12600, completed_json=?, answers_json=?, video_progress_json=?', saved)
        first = self.ping(cfg, tracking, now)
        self.assertEqual(first['progress']['remaining_seconds'], 1800)
        self.assertFalse(first['progress']['module_complete'])
        for elapsed in range(15, 1801, 15):
            result = self.ping(cfg, tracking, now + elapsed)
        self.assertEqual(result['progress']['active_seconds'], 14400)
        self.assertEqual(result['progress']['required_seconds'], 14400)
        self.assertEqual(result['progress']['remaining_seconds'], 0)
        self.assertTrue(result['progress']['module_complete'])
        # Submitting/retrying awards no duration and never regrades course work.
        self.assertEqual(self.post(exam_cfg).status_code, 200)
        self.assertEqual(self.post(exam_cfg).status_code, 200)
        with sqlite3.connect(self.database) as db:
            row = db.execute('SELECT completed_json, answers_json, video_progress_json, active_seconds FROM learner_course_progress').fetchone()
            self.assertEqual(list(row[:3]), saved)
            self.assertEqual(row[3], 14400)
        reopened = self._player_config(self.client.get('/espace/public-token/elearning/exams/module-01'))
        self.assertEqual(reopened['initialActiveSeconds'], 14400)
        self.assertTrue(reopened['initialModuleComplete'])
        player = self._player_config(self.client.get('/espace/public-token/elearning/academy-aps62-01'))
        self.assertEqual(player['initialActiveSeconds'], 14400)
        self.assertTrue(player['initialModuleComplete'])
        path = self.client.get('/espace/public-token/elearning')
        self.assertEqual(path.status_code, 200)
        self.assertIn('04:00:00', path.text)
        self.assertIn('Temps actif inclus dans ce module.', path.text)
        self._admin_login()
        report = self.client.get('/api/admin/elearning/courses/academy-aps62-01/live')
        self.assertEqual(report.status_code, 200)
        row = report.json['learners'][0]
        self.assertEqual(row['activity_title'], 'Examen blanc du module · questions et corrigé')
        self.assertEqual(row['active_time_label'], '04:00:00')
        exported = self.client.get('/admin/elearning/courses/academy-aps62-01/export.csv')
        self.assertEqual(exported.status_code, 200)
        self.assertIn('04:00:00', exported.text)
        self.assertIn('14400', exported.text)

    def test_exam_and_course_cannot_double_count_even_in_two_tabs(self):
        cfg, _, _ = self.assign()
        course_cfg = self._player_config(self.client.get('/espace/public-token/elearning/academy-aps62-01'))
        now = time.time()
        lesson = self.tracking(course_cfg, now, tab='lesson')
        self.ping(course_cfg, lesson, now)
        exam = self.tracking(cfg, now, tab='exam')
        duplicate = self.ping(cfg, exam, now + 15)
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(duplicate['credited_seconds'], 0)
        self.assertEqual(self.ping(course_cfg, lesson, now + 15)['progress']['active_seconds'], 15)
        with patch('elearning_native.store.time.time', return_value=now + 15):
            self._api_post(course_cfg['finishUrl'], course_cfg, tracking_session_id=lesson, activity_id=course_cfg['activityId'])
        self.ping(cfg, exam, now + 15)
        self.assertEqual(self.ping(cfg, exam, now + 30)['progress']['active_seconds'], 30)

    def test_background_time_continues_until_ten_minutes_and_never_counts_twice(self):
        cfg, _, _ = self.assign()
        now = time.time()
        tracking = self.tracking(cfg, now)
        self.ping(cfg, tracking, now)
        self.assertEqual(self.ping(cfg, tracking, now + 15)['credited_seconds'], 15)
        self.assertEqual(self.ping(cfg, tracking, now + 15)['credited_seconds'], 0)
        hidden = dict(visible=False, focused=False)
        self.ping(cfg, tracking, now + 15, interaction_age_seconds=15, **hidden)
        background = self.ping(cfg, tracking, now + 75, interaction_age_seconds=75, **hidden)
        self.assertTrue(background['active'])
        self.assertEqual(background['progress']['active_seconds'], 75)
        before = self.ping(cfg, tracking, now + 599, interaction_age_seconds=599, **hidden)
        self.assertTrue(before['active'])
        self.assertEqual(before['progress']['active_seconds'], 599)
        idle = self.ping(cfg, tracking, now + 601, interaction_age_seconds=601, recent_activity=False, **hidden)
        self.assertFalse(idle['active'])
        self.assertEqual(idle['credited_seconds'], 1)
        self.assertEqual(idle['progress']['active_seconds'], 600)
        self.assertEqual(self.ping(cfg, tracking, now + 1200, interaction_age_seconds=1200, recent_activity=False)['credited_seconds'], 0)
        resumed = self.ping(cfg, tracking, now + 1200, interaction_age_seconds=0)
        self.assertTrue(resumed['active'])
        self.assertEqual(resumed['credited_seconds'], 0)
        self.assertEqual(self.ping(cfg, tracking, now + 1215, interaction_age_seconds=15)['progress']['active_seconds'], 615)

    def test_navigation_credits_the_last_seconds_even_if_finish_is_late_or_lost(self):
        cfg, _, _ = self.assign()
        course_cfg = self._player_config(self.client.get('/espace/public-token/elearning/academy-aps62-01'))
        self.assertEqual(course_cfg['idleSeconds'], 600)
        self.assertTrue(course_cfg['continueWhenHidden'])
        now = time.time()
        lesson = self.tracking(course_cfg, now, tab='same-tab')
        self.ping(course_cfg, lesson, now)
        # The new page arrives before the old page's pagehide request.
        exam = self.tracking(cfg, now + 8, tab='same-tab')
        continued = self.ping(cfg, exam, now + 8)
        self.assertFalse(continued['duplicate'])
        self.assertTrue(continued['active'])
        self.assertEqual(continued['progress']['active_seconds'], 8)
        self.assertEqual(self.ping(course_cfg, lesson, now + 10)['credited_seconds'], 0)
        with patch('elearning_native.store.time.time', return_value=now + 12):
            late = self._api_post(course_cfg['finishUrl'], course_cfg, tracking_session_id=lesson,
                                  activity_id=course_cfg['activityId'])
        self.assertEqual(late.json['credited_seconds'], 0)
        self.assertEqual(self.ping(cfg, exam, now + 23)['progress']['active_seconds'], 23)
        # A refresh transfers the same budget without waiting 45 seconds.
        refreshed = self.tracking(cfg, now + 25, tab='same-tab')
        result = self.ping(cfg, refreshed, now + 25)
        self.assertTrue(result['active'])
        self.assertEqual(result['progress']['active_seconds'], 25)
        self.assertEqual(self.ping(cfg, exam, now + 40)['credited_seconds'], 0)
        self.assertEqual(self.ping(cfg, refreshed, now + 40)['progress']['active_seconds'], 40)

    def test_long_suspension_and_navigation_do_not_credit_beyond_the_idle_deadline(self):
        cfg, _, _ = self.assign()
        now = time.time()
        first = self.tracking(cfg, now, tab='same-tab')
        self.ping(cfg, first, now)
        second = self.tracking(cfg, now + 3600, tab='same-tab')
        result = self.ping(cfg, second, now + 3600)
        self.assertTrue(result['active'])
        self.assertEqual(result['progress']['active_seconds'], 600)
        self.assertEqual(self.ping(cfg, first, now + 3601)['credited_seconds'], 0)

    def test_navigation_to_another_module_keeps_each_modules_own_seconds(self):
        store = NativeElearningStore(self.database)
        first_access = dict(session_id='navigation', trainee_id='learner', course_id='academy-aps62-01', course_version='v1')
        second_access = {**first_access, 'course_id': 'academy-aps62-02'}
        def start(access, when, tab='same-tab'):
            return store.start_tracking(access, tab_id=tab, activity_id='lesson', now_epoch=when)['tracking_session_id']
        def ping(access, tracking, when):
            return store.heartbeat(access, tracking, activity_id='lesson', now_epoch=when,
                visible=True, focused=True, recent_activity=True, media_playing=False, interaction_age_seconds=0)
        first = start(first_access, 1000)
        ping(first_access, first, 1000)
        second = start(second_access, 1012)
        self.assertTrue(ping(second_access, second, 1012)['active'])
        self.assertEqual(ping(second_access, second, 1027)['progress']['active_seconds'], 15)
        old = ping(first_access, first, 1028)
        self.assertTrue(old['ended'])
        self.assertEqual(old['progress']['active_seconds'], 12)
        duplicate = start(first_access, 1028, tab='other-tab')
        self.assertTrue(ping(first_access, duplicate, 1028)['duplicate'])
        self.assertEqual(ping(first_access, duplicate, 1042)['credited_seconds'], 0)
        self.assertEqual(ping(second_access, second, 1042)['progress']['active_seconds'], 30)

    def test_exam_access_is_scoped_and_assignment_revocation_is_respected(self):
        cfg, _, _ = self.assign()
        wrong = self._api_post(cfg['startUrl'], cfg, tab_id='wrong', activity_id='aps62-02-examen-blanc')
        self.assertEqual(wrong.status_code, 403)
        activity = self.course['activity_order'][0]
        self.assertEqual(self._api_post(f'/api/elearning/v1/activities/{activity}/complete', cfg,
                                       activity_id=cfg['activityId']).status_code, 403)
        self.assertEqual(self.client.post(cfg['startUrl'], json={}).status_code, 403)
        regular = self._player_config(self.client.get('/espace/public-token/elearning/academy-aps62-01'))
        self.assertEqual(self._api_post(regular['startUrl'], regular, tab_id='wrong', activity_id=cfg['activityId']).status_code, 400)
        now = time.time()
        tracking = self.tracking(cfg, now)
        self.data['sessions'][0]['aps_native_modules'] = []
        self.assertEqual(self._api_post(cfg['finishUrl'], cfg, tracking_session_id=tracking, activity_id=cfg['activityId']).status_code, 403)

    def test_preview_has_module_context_without_any_learner_tracking(self):
        self._admin_login()
        with patch('elearning_native.web.NativeElearningStore', side_effect=AssertionError('Preview must not track')):
            page = self.client.get('/admin/elearning/exams/module-01')
            self.assertEqual(page.status_code, 200)
            self.assertIn('4 h', page.text)
            self.assertIn('Retour au module', page.text)
            self.assertNotIn('id="nativeElearningConfig"', page.text)
            self.assertNotIn('native-elearning-player.js', page.text)
            self.assertIn('/courses/academy-aps62-01/preview', self.config(page)['moduleUrl'])
            final = self.client.get('/admin/elearning/exams/final')
            self.assertNotIn('id="nativeElearningConfig"', final.text)
            self.assertNotIn('Examen blanc et corrigé inclus', final.text)

