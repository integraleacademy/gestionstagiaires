"""Reading gates use server time, survive resuming, and preserve old completions."""
import json
import re
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from flask import Flask, render_template

from elearning_native.academy import curriculum_ids, load_bundled_course
from elearning_native.lesson_timing import lesson_pages
from elearning_native.store import NativeElearningStore, TrackingError


class LessonPlanTests(unittest.TestCase):
    def test_every_aps_lesson_matches_the_actual_reader_pages(self):
        app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
        tiers = Counter()
        lessons = 0
        with app.app_context():
            for course_id in curriculum_ids():
                course = load_bundled_course(course_id)
                for section in course['sections']:
                    for activity in section['activities']:
                        pages = lesson_pages(course, activity)
                        if activity.get('academy', {}).get('kind') != 'lesson':
                            self.assertEqual(pages, [])
                            continue
                        rendered = render_template('_aps62_activity.html', course=course, activity=activity)
                        count = len(re.findall(r'<[^>]+\bdata-aps-lesson-page\b', rendered))
                        self.assertEqual(len(pages), count, activity['id'])
                        self.assertEqual(len({page['id'] for page in pages}), count)
                        tiers.update(page['required_seconds'] for page in pages)
                        lessons += 1
        self.assertEqual(lessons, 62)
        self.assertEqual(set(tiers), {60, 120, 300})

    def test_other_training_is_unchanged_and_old_aps_editions_are_covered(self):
        course = load_bundled_course('academy-aps62-01', '20261003-aps62-v1')
        activity = course['sections'][0]['activities'][0]
        self.assertTrue(lesson_pages(course, activity))
        self.assertEqual(lesson_pages({'id': 'academy-vtc-01'}, activity), [])


class LessonTimingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / 'tracking.sqlite3'
        self.store = NativeElearningStore(self.path)
        self.access = {'session_id': 'session', 'trainee_id': 'learner',
                       'course_id': 'academy-aps62-01', 'course_version': '20261012-aps62-v12'}
        self.pages = [{'id': 'short', 'required_seconds': 60},
                      {'id': 'course', 'required_seconds': 120},
                      {'id': 'case', 'required_seconds': 300}]
        self.now = 1000.0
        self.tracking = self.start('one')

    def tearDown(self):
        self.temporary.cleanup()

    def start(self, tab):
        return self.store.start_tracking(self.access, tab_id=tab, activity_id='lesson', now_epoch=self.now)['tracking_session_id']

    def tick(self, seconds=0, page='short', **changes):
        self.now += seconds
        args = dict(activity_id='lesson', visible=True, focused=True, recent_activity=True,
                    media_playing=False, interaction_age_seconds=0, lesson_pages=self.pages,
                    lesson_page_id=page, now_epoch=self.now)
        args.update(changes)
        return self.store.heartbeat(self.access, self.tracking, **args)

    def read(self, page, seconds):
        self.tick(page=page)
        for _ in range(seconds // 15):
            result = self.tick(15, page)
        return result

    def finish_lesson(self, requirements=None):
        return self.store.complete_activity(self.access, 'lesson', activity_order=['lesson', 'next'],
            scored_activity_ids=[], mastery_score=80, lesson_requirements=self.pages if requirements is None else requirements)

    def test_no_skipping_and_each_page_requires_its_own_time(self):
        self.tick()
        with self.assertRaises(TrackingError):
            self.tick(page='case')
        with self.assertRaises(TrackingError):
            self.finish_lesson()
        self.read('short', 60)
        result = self.tick(page='course')
        self.assertEqual(result['progress']['lesson_seconds']['lesson'], {'short': 60})
        self.read('course', 120)
        with self.assertRaises(TrackingError):
            self.finish_lesson()
        result = self.read('case', 300)
        self.assertEqual(result['progress']['active_seconds'], 480)
        self.assertEqual(result['progress']['lesson_seconds']['lesson'], {'short': 60, 'course': 120, 'case': 300})
        self.assertIn('lesson', self.finish_lesson()['completed_activity_ids'])

    def test_hidden_unfocused_and_idle_time_cannot_unlock_reading(self):
        self.tick()
        self.tick(5, visible=False)
        result = self.tick(120, visible=False)
        self.assertEqual(result['progress']['lesson_seconds']['lesson']['short'], 5)
        self.assertFalse(result['lesson_active'])
        result = self.tick(20, focused=False)
        self.assertEqual(result['progress']['lesson_seconds']['lesson']['short'], 5)
        self.tick()
        self.tick(5, recent_activity=False, interaction_age_seconds=600)
        result = self.tick(120, recent_activity=False, interaction_age_seconds=720)
        self.assertEqual(result['progress']['lesson_seconds']['lesson']['short'], 10)

    def test_reloading_resumes_saved_seconds_and_does_not_duplicate_them(self):
        self.read('short', 30)
        self.store.finish_tracking(self.access, self.tracking, activity_id='lesson', now_epoch=self.now + 5)
        self.now += 10
        self.store = NativeElearningStore(self.path)
        self.tracking = self.start('one')
        result = self.tick()
        self.assertEqual(result['progress']['lesson_seconds']['lesson']['short'], 35)
        result = self.read('short', 30)
        self.assertEqual(result['progress']['lesson_seconds']['lesson']['short'], 65)
        self.tick(page='course')
        self.tick(page='short')  # Revisiting a validated page stays available.

    def test_navigation_settles_previous_tab_without_double_credit(self):
        self.tick()
        old = self.tracking
        self.now += 10
        self.tracking = self.start('one')
        result = self.tick()
        self.assertEqual(result['progress']['lesson_seconds']['lesson']['short'], 10)
        late = self.store.finish_tracking(self.access, old, activity_id='lesson', now_epoch=self.now)
        self.assertEqual(late['credited_seconds'], 0)

    def test_duplicate_tabs_cannot_accumulate_parallel_reading(self):
        self.tick()
        first = self.tracking
        self.tracking = self.start('two')
        result = self.tick(10)
        self.assertTrue(result['duplicate'])
        self.assertFalse(result['lesson_active'])
        self.tracking = first
        result = self.tick(5)
        self.assertEqual(result['progress']['lesson_seconds']['lesson']['short'], 15)

    def test_absence_cannot_credit_more_than_the_short_presence_lease(self):
        self.tick()
        result = self.tick(600)
        self.assertEqual(result['progress']['lesson_seconds']['lesson']['short'], 20)
        with self.assertRaises(TrackingError):
            self.tick(page='course')

    def test_unknown_page_is_rejected_and_history_is_not_fabricated(self):
        with self.assertRaises(TrackingError):
            self.tick(page='made-up')
        completed = self.finish_lesson(requirements=[])  # Completion before this feature existed.
        self.assertEqual(completed['lesson_seconds'], {})
        result = self.finish_lesson()
        self.assertIn('lesson', result['completed_activity_ids'])
        self.assertEqual(result['lesson_seconds'], {})
        self.tick(page='case')  # All pages can be reviewed immediately.


from tests import test_native_elearning_web as web_tests


class LessonTimingWebTests(unittest.TestCase):
    setUp = web_tests.NativeElearningWebTests.setUp
    tearDown = web_tests.NativeElearningWebTests.tearDown
    _admin_login = web_tests.NativeElearningWebTests._admin_login
    _public_login = web_tests.NativeElearningWebTests._public_login
    _player_config = staticmethod(web_tests.NativeElearningWebTests._player_config)
    _api_post = web_tests.NativeElearningWebTests._api_post

    def test_real_aps_reader_gates_api_navigation_and_resumes(self):
        course = load_bundled_course('academy-aps62-01')
        session = self.data['sessions'][0]
        session.update(aps_native_course_id=course['id'], aps_native_course_version=course['version'])
        self._public_login()
        url = f"/espace/public-token/elearning/{course['id']}"
        config = self._player_config(self.client.get(url))
        pages = config['lessonPages']
        self.assertEqual([page['required_seconds'] for page in pages[:4]], [60, 120, 120, 300])
        self.assertEqual(self._api_post(config['completeUrl'], config).status_code, 409)
        next_activity = course['activity_order'][1]
        skipped = self._player_config(self.client.get(url, query_string={'activity': next_activity}))
        self.assertEqual(skipped['activityId'], config['activityId'])
        now = time.time()
        with patch('elearning_native.store.time.time', side_effect=lambda: now):
            tracking = self._api_post(config['startUrl'], config, tab_id='test-tab', activity_id=config['activityId']).json['tracking_session_id']

            def tick(page):
                return self._api_post(config['heartbeatUrl'], config,
                    tracking_session_id=tracking, activity_id=config['activityId'], lesson_page_id=page['id'],
                    visible=True, focused=True, recent_activity=True, media_playing=False)

            self.assertEqual(tick(pages[1]).status_code, 409)
            tick(pages[0])
            now += 15
            result = tick(pages[0])
            self.assertEqual(result.status_code, 200)
            resumed = self._player_config(self.client.get(url))
            self.assertEqual(resumed['initialLessonSeconds'][pages[0]['id']], 15)
            for index, page in enumerate(pages):
                tick(page)
                remaining = page['required_seconds'] - (15 if index == 0 else 0)
                for _ in range(remaining // 15):
                    now += 15
                    self.assertEqual(tick(page).status_code, 200)
            response = self._api_post(config['completeUrl'], config)
            self.assertEqual(response.status_code, 200)
            self.assertIn(config['activityId'], response.json['progress']['completed_activity_ids'])
            review = self._player_config(self.client.get(url, query_string={'activity': config['activityId']}))
            self.assertTrue(review['activityCompleted'])
            self.assertEqual(self._player_config(self.client.get(url))['activityId'], next_activity)

    def test_aps_admin_preview_does_not_create_tracking_or_a_gate(self):
        self._admin_login()
        with patch('elearning_native.web.NativeElearningStore', side_effect=AssertionError('Preview must not track')):
            response = self.client.get('/admin/elearning/courses/academy-aps62-01/preview')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('nativeElearningConfig', response.get_data(as_text=True))
        self.assertNotIn('native-elearning-player.js', response.get_data(as_text=True))
