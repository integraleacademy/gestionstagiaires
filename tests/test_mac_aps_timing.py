from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from elearning_native import mac_aps
from elearning_native.importer import CourseCatalog, CourseImportError
from elearning_native.mac_aps_timing import completion_blocker
from elearning_native.paths import project_course, project_progress, validate_modules
from elearning_native.store import NativeElearningStore
from tests import test_native_elearning_web as fixtures
from tests.test_native_elearning_mac_aps import grouped_answer


class MacAPSObjectiveTimeTests(unittest.TestCase):
    def test_time_is_credited_to_the_previous_activity_without_overlap(self):
        with tempfile.TemporaryDirectory() as folder:
            store = NativeElearningStore(Path(folder) / 'tracking.sqlite3')
            access = dict(session_id='synthetic', trainee_id='alice',
                          course_id='academy-macaps-05', course_version=mac_aps.VERSION)
            first = store.start_tracking(access, tab_id='one', activity_id='objective-a', now_epoch=1000)['tracking_session_id']
            def beat(tracking, activity, now, **changes):
                flags = dict(visible=True, focused=True, recent_activity=True, media_playing=False,
                             interaction_age_seconds=0, now_epoch=now)
                flags.update(changes)
                return store.heartbeat(access, tracking, activity_id=activity, **flags)
            beat(first, 'objective-a', 1000)
            moved = beat(first, 'objective-b', 1010)
            self.assertEqual(moved['progress']['activity_seconds'], {'objective-a': 10.0})
            following = beat(first, 'objective-b', 1020)
            self.assertEqual(following['progress']['activity_seconds'], {'objective-a': 10.0, 'objective-b': 10.0})
            duplicate = store.start_tracking(access, tab_id='two', activity_id='objective-c', now_epoch=1020)['tracking_session_id']
            self.assertTrue(beat(duplicate, 'objective-c', 1020)['duplicate'])
            blocked = beat(duplicate, 'objective-c', 1030)
            self.assertEqual(blocked['credited_seconds'], 0)
            self.assertNotIn('objective-c', blocked['progress']['activity_seconds'])
            paused = beat(first, 'objective-b', 1030, visible=False, focused=False)
            final = beat(first, 'objective-b', 1100, visible=False, focused=False)
            self.assertEqual(final['progress']['activity_seconds'], paused['progress']['activity_seconds'])
            self.assertEqual(sum(final['progress']['activity_seconds'].values()), final['progress']['active_seconds'])

    def test_time_cannot_be_pooled_in_one_objective_or_inferred_from_a_total(self):
        course = mac_aps.load_bundled_course('academy-macaps-05', mac_aps.VERSION)
        raw = {'completed_activity_ids': course['activity_order'], 'active_seconds': 420 * 60,
               'started_at': '2026-10-12T00:00:00Z'}
        no_ledger = project_progress(raw, course)
        self.assertFalse(no_ledger['module_complete'])
        self.assertEqual(no_ledger['remaining_seconds'], 420 * 60)
        first_id = course['timed_objectives'][0]['activity_ids'][0]
        pooled = project_progress({**raw, 'activity_seconds': {first_id: 420 * 60}}, course)
        self.assertFalse(pooled['objectives_duration_met'])
        self.assertEqual(pooled['remaining_seconds'], 330 * 60)
        ledger = {row['activity_ids'][0]: row['required_seconds'] for row in course['timed_objectives']}
        finished = project_progress({**raw, 'activity_seconds': ledger}, course)
        self.assertTrue(finished['module_complete'])
        self.assertTrue(all(row['complete'] for row in finished['timed_objectives']))

    def test_fixed_duration_and_complete_sequence_selection_preserve_legacy(self):
        course = mac_aps.load_bundled_course('academy-macaps-05', mac_aps.VERSION)
        for minutes in (0, 419, 421, 1000):
            with self.assertRaises(CourseImportError):
                project_course(course, {'required_minutes': minutes})
        self.assertEqual(project_course(course, {'required_minutes': 420})['required_minutes'], 420)
        for sections in ([course['sections'][0]['id']], list(reversed([s['id'] for s in course['sections']]))):
            with self.assertRaises(CourseImportError):
                project_course(course, {'required_minutes': 420, 'section_ids': sections})
        legacy = mac_aps.load_bundled_course('academy-macaps-05', mac_aps.LEGACY_VERSION)
        self.assertEqual(project_course(legacy, {'required_minutes': 0})['required_minutes'], 0)
        self.assertEqual(project_progress({}, legacy)['timed_objectives'], [])
        complement = mac_aps.load_bundled_course('academy-macaps-complement-04', mac_aps.VERSION)
        with self.assertRaises(CourseImportError):
            project_course(complement, {'required_minutes': 420})

    def test_only_the_closing_activity_requires_the_objective_duration(self):
        course = mac_aps.load_bundled_course('academy-macaps-05', mac_aps.VERSION)
        objective = course['timed_objectives'][0]
        self.assertIsNone(completion_blocker(course, {}, objective['activity_ids'][0]))
        self.assertEqual(completion_blocker(course, {}, objective['activity_ids'][-1])['required_seconds'], 90 * 60)
        self.assertIsNone(completion_blocker(course, {'activity_seconds': {
            objective['activity_ids'][0]: objective['required_seconds']}}, objective['activity_ids'][-1]))


class MacAPSObjectiveWebTests(unittest.TestCase):
    setUp = fixtures.NativeElearningWebTests.setUp
    tearDown = fixtures.NativeElearningWebTests.tearDown
    _public_login = fixtures.NativeElearningWebTests._public_login
    _admin_login = fixtures.NativeElearningWebTests._admin_login
    _player_config = staticmethod(fixtures.NativeElearningWebTests._player_config)
    _api_post = fixtures.NativeElearningWebTests._api_post

    def assign(self, numbers=('05',)):
        session = self.data['sessions'][0]
        session['training_type'] = 'MAC APS'
        courses = [mac_aps.load_bundled_course('academy-macaps-' + number, mac_aps.VERSION) for number in numbers]
        session['aps_native_modules'] = validate_modules([
            {'course_id': c['id'], 'course_version': c['version'], 'required_minutes': c['required_minutes']}
            for c in courses], CourseCatalog(self.persist_dir / 'native_elearning'))
        return courses

    def test_api_closure_requires_objective_time_and_rejects_future_heartbeat(self):
        course = self.assign()[0]
        self._public_login()
        config = self._player_config(self.client.get('/espace/public-token/elearning/' + course['id']))
        objective = course['timed_objectives'][0]
        closing_id = objective['activity_ids'][-1]
        closing = next(a for s in course['sections'] for a in s['activities'] if a['id'] == closing_id)
        store = NativeElearningStore(self.persist_dir / 'native_elearning/tracking.sqlite3')
        with store._transaction() as connection:
            connection.execute('UPDATE learner_course_progress SET completed_json = ?, active_seconds = ? WHERE course_id = ?',
                               (json.dumps(objective['activity_ids'][:-1]), 99999, course['id']))
        response = self._api_post('/api/elearning/v1/activities/' + closing_id + '/answer', config, answer=grouped_answer(closing))
        self.assertEqual(response.status_code, 409)
        self.assertIn('temps actif', response.json['error'])
        self.assertNotIn(closing_id, response.json['progress']['completed_activity_ids'])
        future = course['timed_objectives'][1]['activity_ids'][0]
        forged = self._api_post(config['heartbeatUrl'], config, activity_id=future, tracking_session_id='forged',
                                visible=True, focused=True, recent_activity=True, media_playing=False)
        self.assertEqual(forged.status_code, 409)
        with store._transaction() as connection:
            connection.execute('UPDATE learner_course_progress SET activity_seconds_json = ? WHERE course_id = ?',
                               (json.dumps({objective['activity_ids'][0]: objective['required_seconds']}), course['id']))
        response = self._api_post('/api/elearning/v1/activities/' + closing_id + '/answer', config, answer=grouped_answer(closing))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['correct'])
        self.assertTrue(response.json['progress']['timed_objectives'][0]['complete'])

    def test_complements_are_authorized_separately_and_do_not_write_tracking(self):
        self.assign(('02', '03', '05'))
        self._public_login()
        course_id = 'academy-macaps-complement-04'
        url = '/espace/public-token/elearning/mac-aps/complements/' + course_id
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Ressources complémentaires', response.text)
        self.assertNotIn('id="nativeElearningConfig"', response.text)
        self.assertNotIn('nativeActiveTimer', response.text)
        self.assertFalse((self.persist_dir / 'native_elearning/tracking.sqlite3').exists())
        self.assertEqual(self.client.get(url.replace('public-token', 'other-token')).status_code, 302)
        self.data['sessions'][0]['aps_native_modules'] = []
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_new_and_legacy_final_use_their_assigned_edition(self):
        self.assign(('02', '03', '05'))
        self._public_login()
        page = self.client.get('/espace/public-token/elearning')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Examen blanc final', page.text)
        self.assertIn('14:00:00', page.text)
        self.assertIn('Hors des 14 heures', page.text)
        self.assertEqual(self.client.get('/espace/public-token/elearning/exams/macaps-final').status_code, 403)
        legacy_courses = [mac_aps.load_bundled_course(cid, mac_aps.LEGACY_VERSION) for cid in mac_aps.curriculum_ids(mac_aps.LEGACY_VERSION)]
        self.data['sessions'][0]['aps_native_modules'] = [
            {'course_id': c['id'], 'course_version': c['version'], 'required_minutes': c['planned_minutes']}
            for c in legacy_courses]
        page = self.client.get('/espace/public-token/elearning')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Les 5 parties de votre édition MAC APS', page.text)
        self.assertNotIn('Hors des 14 heures', page.text)

    def test_final_opens_after_all_objectives_and_saves_current_exam_only(self):
        from elearning_native.exams import ExamStore
        from elearning_native.videos import course_videos
        courses = self.assign(('02', '03', '05'))
        self._public_login()
        store = NativeElearningStore(self.persist_dir / 'native_elearning/tracking.sqlite3')
        for course in courses:
            access = dict(session_id='session-aps', trainee_id='trainee-1',
                          course_id=course['id'], course_version=course['version'])
            store.start_tracking(access, tab_id='synthetic-final', activity_id=course['activity_order'][0], now_epoch=1000)
            ledger = {o['activity_ids'][0]: o['required_seconds'] for o in course['timed_objectives']}
            videos = {aid: {vid: {'completed': True, 'duration_seconds': seconds, 'watched_seconds': seconds}
                            for vid, seconds in requirements.items()}
                      for aid, requirements in course_videos(course).items()}
            with store._transaction() as db:
                db.execute('''UPDATE learner_course_progress SET completed_json=?, active_seconds=?,
                           activity_seconds_json=?, video_progress_json=? WHERE course_id=?''',
                           (json.dumps(course['activity_order']), course['required_minutes'] * 60,
                            json.dumps(ledger), json.dumps(videos), course['id']))
        response = self.client.get('/espace/public-token/elearning/exams/macaps-final')
        self.assertEqual(response.status_code, 200)
        exam = mac_aps.load_exam('macaps-final', mac_aps.VERSION)
        with self.client.session_transaction() as browser_session:
            csrf = browser_session['native_elearning_csrf']
        before = [row['active_seconds'] for row in store.learner_progress('session-aps', 'trainee-1')]
        result = self.client.post('/api/espace/public-token/elearning/exams/macaps-final',
            json={'version': mac_aps.VERSION, 'attempt_id': 'a' * 32,
                  'answers': {q['id']: q['answer'] for q in exam['questions']}},
            headers={'X-Elearning-CSRF': csrf})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['result']['score'], 100)
        self.assertTrue(all(c['lesson_links'] for c in result.json['result']['corrections']))
        self.assertEqual(before, [row['active_seconds'] for row in store.learner_progress('session-aps', 'trainee-1')])
        exams = ExamStore(self.persist_dir / 'native_elearning/tracking.sqlite3')
        self.assertEqual(len(exams.history('session-aps', 'trainee-1', exam)), 1)
        self.assertEqual(exams.history('session-aps', 'trainee-1', mac_aps.load_exam('macaps-final', mac_aps.LEGACY_VERSION)), [])


if __name__ == '__main__':
    unittest.main()
