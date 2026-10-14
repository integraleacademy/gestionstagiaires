"""Regression checks for workload enrichment without artificial time credit."""
import copy
import html
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from elearning_native.academy import curriculum_manifest, load_bundled_course
from elearning_native.aps_depth import REVISION
from elearning_native.aps_depth_content import CASES
from elearning_native.aps_editorial import editorial_bank
from elearning_native.aps_workload import summarize
from elearning_native.practice import public_practice, grade_practice
from elearning_native.store import NativeElearningStore
from elearning_native.videos import course_videos
from elearning_native.web import _b64decode, _sign_access
from tests import test_aps_exam_time as fixture
from tests import test_native_elearning_web as web_fixture


def activities(course):
    return [a for s in course['sections'] for a in s['activities']]


def answers(practice):
    return {ex['id']: ex['answer'] if ex['kind'] == 'single' else {r['id']: r['answer'] for r in ex['rows']}
            for ex in practice['exercises']}


class DepthContentTests(unittest.TestCase):
    def test_all_fifteen_budgets_include_exam_without_changing_required_hours(self):
        minutes = [240, 180, 120, 60, 180, 240, 300, 300, 180, 420, 120, 420, 120, 420, 420]
        for module, required in zip(curriculum_manifest()['modules'], minutes):
            course = load_bundled_course(module['id'])
            plan = course['study_plan']
            self.assertEqual(course['required_minutes'], required)
            self.assertEqual(sum(a['planned_minutes'] for a in activities(course)) + plan['exam_minutes'], required)
            self.assertEqual(sum(s['minutes'] for s in plan['steps']), required)
            self.assertEqual(plan['steps'][-1]['kind'], 'exam')
            for aid, videos in course_videos(course).items():
                activity = next(a for a in activities(course) if a['id'] == aid)
                self.assertGreaterEqual(activity['planned_minutes'] * 60, sum(videos.values()))
        self.assertEqual(sum(minutes), 62 * 60)

    def test_every_sequence_has_authored_evidence_and_server_graded_multistep_work(self):
        seen, decisions = set(), 0
        for module in curriculum_manifest()['modules']:
            course = load_bundled_course(module['id'])
            for section in course['sections']:
                seen.add(section['id'])
                lesson = next(a['academy'] for a in section['activities'] if a.get('academy', {}).get('kind') == 'lesson')
                self.assertGreater(len(' '.join(lesson['depth_teaching']['paragraphs']).split()), 70)
                workshop = next(a for a in section['activities'] if a.get('academy', {}).get('kind') == 'workshop')
                practice = workshop['practice']
                self.assertEqual(len(practice['documents']), 3)
                self.assertEqual(len(practice['exercises']), 8)
                self.assertEqual({e['kind'] for e in practice['exercises']}, {'single', 'classify', 'matching', 'order'})
                public = public_practice(practice)
                for exercise in public['exercises']:
                    self.assertNotIn('answer', exercise)
                    self.assertNotIn('explanation', exercise)
                    self.assertNotIn('branches', exercise)
                    self.assertTrue(all('answer' not in row for row in exercise['rows']))
                good = answers(practice)
                self.assertTrue(grade_practice(practice, good)['correct'])
                for ex in practice['exercises'][:5]:
                    decisions += len(ex.get('rows', [])) or 1
                    bad = copy.deepcopy(good[ex['id']])
                    if ex['kind'] == 'single':
                        bad = next(o['id'] for o in ex['options'] if o['id'] != bad)
                    elif ex['kind'] in {'order', 'matching'}:
                        keys = list(bad)
                        bad[keys[0]], bad[keys[1]] = bad[keys[1]], bad[keys[0]]
                    else:
                        key = next(iter(bad))
                        bad[key] = next(o['id'] for o in ex['options'] if o['id'] != bad[key])
                    self.assertFalse(grade_practice(practice, {ex['id']: bad}, step=ex['id'])['correct'])
                old = editorial_bank()['sections'][section['id']]['practices'][workshop['id']]
                self.assertEqual({e['id'] for e in old['exercises']}, {e['id'] for e in practice['exercises'][5:]})
                with self.assertRaises(ValueError):
                    grade_practice(practice, answers(old))
        self.assertEqual(seen, set(CASES))
        self.assertEqual((len(seen), decisions), (62, 868))

    def test_calibration_excludes_partial_history_and_keeps_first_finish_snapshot(self):
        course = load_bundled_course('academy-aps62-01')
        revisions = {a['id']: REVISION for a in activities(course) if a.get('academy', {}).get('kind') == 'workshop'}
        readings = {a['id']: REVISION for a in activities(course) if a.get('academy', {}).get('reading_revision')}
        row = {'assigned_current': True, 'required_seconds': 14400, 'active_seconds': 14400,
            'activity_seconds': {'aps62-01-01-comprendre': 12300, 'aps62-01-examen-blanc': 2100},
            'aps_workload': {'revision': REVISION, 'active_seconds': 3600,
                'activity_seconds': {'aps62-01-01-comprendre': 3600}, 'workshop_revisions': revisions,
                'reading_revisions': readings}}
        report = summarize(course, [row])
        self.assertEqual(report['median_label'], '01:00:00')
        self.assertEqual(report['learners'][0]['total_label'], '04:00:00')
        self.assertEqual(report['learners'][0]['exam_label'], '00:35:00')
        self.assertTrue(report['review'])
        self.assertEqual(report['sample_count'], 1)
        for change in ('missing_time', 'old_workshop', 'old_reading', 'not_assigned', 'partial_module'):
            partial = copy.deepcopy(row)
            if change == 'missing_time': partial['aps_workload']['active_seconds'] += 50
            if change == 'old_workshop': partial['aps_workload']['workshop_revisions'].pop(next(iter(revisions)))
            if change == 'old_reading': partial['aps_workload']['reading_revisions'].pop(next(iter(readings)))
            if change == 'not_assigned': partial['assigned_current'] = False
            if change == 'partial_module': partial['required_seconds'] = 600
            self.assertEqual(summarize(course, [partial])['sample_count'], 0)


class DepthTrackingTests(unittest.TestCase):
    def test_ledger_survives_navigation_duplicates_idle_and_first_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = NativeElearningStore(Path(directory) / 'tracking.sqlite3')
            access = dict(session_id='test-session', trainee_id='test-learner', course_id='academy-aps62-01',
                          course_version='test-version', aps_depth_revision=REVISION)
            first = tracker.start_tracking(access, tab_id='tab', activity_id='lesson', now_epoch=1000)['tracking_session_id']
            def ping(tid, aid, when, age=0):
                return tracker.heartbeat(access, tracking_session_id=tid, activity_id=aid, now_epoch=when,
                    visible=True, focused=True, media_playing=False, recent_activity=age < 600, interaction_age_seconds=age)
            ping(first, 'lesson', 1000)
            ping(first, 'lesson', 1060)
            second = tracker.start_tracking(access, tab_id='tab', activity_id='workshop', now_epoch=1065)['tracking_session_id']
            ping(second, 'workshop', 1065)
            ping(second, 'workshop', 1100)
            progress = tracker.learner_progress('test-session', 'test-learner')[0]
            self.assertEqual(progress['activity_seconds'], {'lesson': 65, 'workshop': 35})
            self.assertEqual(progress['active_seconds'], 100)
            tracker.complete_activity(access, 'lesson', activity_order=['lesson', 'workshop'], scored_activity_ids=[],
                mastery_score=80, required_seconds=14400, answer={'reading_revision': REVISION})
            tracker.complete_activity(access, 'workshop', activity_order=['lesson', 'workshop'], scored_activity_ids=[],
                mastery_score=80, required_seconds=14400, answer={'practice_revision': REVISION})
            before = tracker.learner_progress('test-session', 'test-learner')[0]
            self.assertEqual(before['aps_workload']['active_seconds'], 100)
            self.assertEqual(before['aps_workload']['reading_revisions'], {'lesson': REVISION})
            ping(second, 'workshop', 2000, 900)
            after = tracker.learner_progress('test-session', 'test-learner')[0]
            self.assertEqual(after['active_seconds'], 700)
            self.assertEqual(sum(after['activity_seconds'].values()), 700)
            self.assertEqual(after['aps_workload'], before['aps_workload'])
            self.assertEqual(after['status'], 'awaiting_time')


class DepthHTTPTests(unittest.TestCase):
    setUp = fixture.APSExamTimeTests.setUp
    tearDown = fixture.APSExamTimeTests.tearDown
    _public_login = fixture.APSExamTimeTests._public_login
    _admin_login = fixture.APSExamTimeTests._admin_login
    _player_config = staticmethod(fixture.APSExamTimeTests._player_config)
    _api_post = fixture.APSExamTimeTests._api_post
    assign = fixture.APSExamTimeTests.assign
    config = fixture.APSExamTimeTests.config
    database = fixture.APSExamTimeTests.database

    def test_all_dossiers_render_with_selects_and_preview_never_records_learner_work(self):
        self._admin_login()
        for module in curriculum_manifest()['modules']:
            course = load_bundled_course(module['id'])
            for section in course['sections']:
                workshop = next(a for a in section['activities'] if a.get('academy', {}).get('kind') == 'workshop')
                page = self.client.get(f"/admin/elearning/courses/{course['id']}/preview?activity={workshop['id']}")
                self.assertEqual(page.status_code, 200)
                self.assertIn('apsDossierDocuments', page.text)
                self.assertIn('data-kind="matching"', page.text)
                self.assertIn('Examen blanc et correction expliquée', html.unescape(page.text))
                self.assertIn('css/aps62-depth.css', page.text)
                public = json.loads(re.search(r'id="apsPracticeConfig" type="application/json">(.*?)</script>', page.text, re.S)[1])
                self.assertNotIn('explanation', public['practice']['exercises'][0])
        self.assertFalse(self.database.exists())

    def seed_completed(self, seconds=3615):
        self.assign()
        video = {aid: {vid: {'completed': True, 'watched_seconds': duration, 'duration_seconds': duration}
                      for vid, duration in requirements.items()} for aid, requirements in course_videos(self.course).items()}
        saved = {a['id']: {'correct': True, 'selected': ['old-choice'], 'submitted_at': '2026-10-13T12:00:00Z'}
                 for a in activities(self.course) if a.get('scored')}
        saved['aps62-01-01-atelier'] = {'practice_revision': 'previous-revision', 'practice_answers': {'old': 'old'}}
        # Create the row through the public context, then seed only this test DB.
        self.client.get('/espace/public-token/elearning/academy-aps62-01')
        with sqlite3.connect(self.database) as db:
            db.execute('UPDATE learner_course_progress SET completed_json=?, answers_json=?, video_progress_json=?, active_seconds=?',
                (json.dumps(self.course['activity_order']), json.dumps(saved), json.dumps(video), seconds))
        return saved

    def test_old_completed_work_and_time_remain_and_exam_is_reachable_before_four_hours(self):
        saved = self.seed_completed()
        last = self.course['activity_order'][-1]
        page = self.client.get('/espace/public-token/elearning/academy-aps62-01?activity=' + last)
        self.assertEqual(page.status_code, 200)
        config = self._player_config(page)
        self.assertTrue(config['endUrl'].endswith('/exams/module-01'))
        self.assertEqual(config['initialActiveSeconds'], 3615)
        self.assertIn('25 %', page.text)
        self.assertIn('Module à terminer', html.unescape(page.text))
        button = re.search(r'<button[^>]+id="nativeActionButton"[^>]*>', page.text)[0]
        self.assertNotIn(' disabled', button)
        workshop = self.client.get('/espace/public-token/elearning/academy-aps62-01?activity=aps62-01-01-atelier')
        self.assertIn('réponses d’origine sont conservées', html.unescape(workshop.text))
        with sqlite3.connect(self.database) as db:
            row = db.execute('SELECT answers_json, active_seconds, completed_json, aps_workload_json FROM learner_course_progress').fetchone()
        self.assertEqual(json.loads(row[0]), saved)
        self.assertEqual(row[1], 3615)
        self.assertEqual(json.loads(row[2]), self.course['activity_order'])
        self.assertEqual(json.loads(row[3]), {})

    def test_stale_tab_cannot_grade_new_workshop(self):
        self.assign()
        page = self.client.get('/espace/public-token/elearning/academy-aps62-01')
        cfg = self._player_config(page)
        access = json.loads(_b64decode(cfg['accessToken'].split('.')[0]))
        access.pop('aps_depth_revision')
        with web_fixture.gestion_app.app.app_context(): cfg['accessToken'] = _sign_access(access)
        response = self._api_post('/api/elearning/v1/activities/aps62-01-01-atelier/practice', cfg, practice_answers={})
        self.assertEqual(response.status_code, 409)
        self.assertIn('Rechargez la page', response.json['error'])

    def test_calibration_report_is_tenant_scoped_read_only_and_does_not_invent_history(self):
        self.seed_completed()
        tracker = NativeElearningStore(self.database)
        tracker.get_progress(dict(session_id='other-centre', trainee_id='SECRET-OTHER',
            course_id=self.course['id'], course_version=self.course['version']))
        with sqlite3.connect(self.database) as db:
            before = db.execute('SELECT * FROM learner_course_progress ORDER BY session_id').fetchall()
        self._admin_login()
        response = self.client.get('/admin/elearning/calibrage')
        self.assertEqual(response.status_code, 200)
        self.assertIn('01:00:15', response.text)
        self.assertIn('aucun temps reconstitué', html.unescape(response.text))
        self.assertNotIn('SECRET-OTHER', response.text)
        self.assertIn('no-store', response.headers['Cache-Control'])
        export = self.client.get('/admin/elearning/calibrage.csv')
        self.assertEqual(export.status_code, 200)
        self.assertNotIn('SECRET-OTHER', export.text)
        self.assertIn(';205;35;240;;3615.0;', export.text)
        with sqlite3.connect(self.database) as db:
            after = db.execute('SELECT * FROM learner_course_progress ORDER BY session_id').fetchall()
        self.assertEqual(after, before)
