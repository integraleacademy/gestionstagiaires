"""Optional VTC work cannot hold up required learning or erase its evidence."""
import copy
import json
import re
import unittest
from urllib.parse import parse_qs, urlsplit

from elearning_native import vtc
from elearning_native.paths import project_progress, required_activity_order
from elearning_native.store import NativeElearningStore
from elearning_native.videos import course_videos
from elearning_native.vtc_productions import MODULE_MINUTES, VERSION
from tests import test_vtc_production_web as written_fixture


def test_optional_completion_keeps_evidence_and_emits_only_one_module_completion(tmp_path):
    store = NativeElearningStore(tmp_path / 'tracking.sqlite3')
    access = dict(session_id='vtc', trainee_id='learner', course_id='academy-vtc-a', course_version=VERSION)
    course = {'activity_order': ['lesson', 'optional', 'quiz'], 'required_minutes': 1,
              'sections': [{'activities': [{'id': 'lesson'}, {'id': 'optional', 'optional': True},
                                           {'id': 'quiz', 'scored': True}]}]}
    arguments = dict(activity_order=course['activity_order'], required_activity_ids=required_activity_order(course),
                     scored_activity_ids=['quiz'], mastery_score=80, required_seconds=60)
    store.get_progress(access, **arguments)
    with store._connect() as db:
        db.execute('UPDATE learner_course_progress SET active_seconds=60')
    first = store.complete_activity(access, 'lesson', **arguments)
    assert first['current_activity_id'] == 'quiz'
    assert first['progress_percent'] == 50
    finished = store.complete_activity(access, 'quiz', answer={'correct': True}, **arguments)
    assert finished['status'] == 'passed' and finished['progress_percent'] == 100
    copy_answers = {'production_answers': {'response': 'Mon travail conservé'}, 'production_ai_feedback': {'score': 4}}
    optional = store.complete_activity(access, 'optional', answer=copy_answers, **arguments)
    refreshed = store.get_progress(access, **arguments)
    for progress in (optional, refreshed):
        assert progress['progress_percent'] == progress['score_percent'] == 100
        assert set(progress['completed_activity_ids']) == {'lesson', 'optional', 'quiz'}
        assert progress['completed_required_activity_ids'] == ['lesson', 'quiz']
        assert progress['answers']['optional'] == copy_answers
        assert progress['active_seconds'] == 60
        assert progress['completed_at'] == finished['completed_at']
        assert project_progress(progress, course)['module_complete'] is True
    assert sum(event['event_type'] == 'course_completed' for event in store.events_for_learner(access)) == 1
    # Existing courses without an optional flag still require every activity.
    default = store._completion_values(['lesson', 'quiz'], {'quiz': {'correct': True}},
        activity_order=course['activity_order'], scored_activity_ids=['quiz'], mastery_score=80)
    assert default['all_complete'] is False and default['next_activity'] == 'optional'


class VtcOptionalWebTests(unittest.TestCase):
    tearDown = written_fixture.VtcProductionWebTests.tearDown
    _public_login = written_fixture.VtcProductionWebTests._public_login
    _player_config = staticmethod(written_fixture.VtcProductionWebTests._player_config)
    _api_post = written_fixture.VtcProductionWebTests._api_post

    def setUp(self):
        written_fixture.VtcProductionWebTests.setUp(self)
        self.course['sections'][0]['activities'][0]['optional'] = True
        tail = copy.deepcopy(self.course['sections'][0]['activities'][0])
        tail['id'] = 'optional-tail'
        self.course['sections'][0]['activities'].append(tail)
        self.course['activity_order'].append(tail['id'])
        target = self.persist_dir / 'native_elearning' / 'courses' / self.course['id'] / self.course['version'] / 'course.json'
        target.write_text(json.dumps(self.course))
        self._public_login()

    def test_skip_and_resume_allow_required_tracking_and_completion_without_a_copy(self):
        url = '/espace/public-token/elearning/' + self.course['id']
        # A saved resume pointing at an optional workshop chooses required work.
        initial = self._player_config(self.client.get(url))
        self.assertEqual(initial['activityId'], 'question-1')
        page = self.client.get(url, query_string={'activity': 'content-1'})
        optional = self._player_config(page)
        self.assertTrue(optional['activityOptional'])
        self.assertIn('Valider cet atelier', page.text)
        self.assertIn('Passer cet atelier facultatif →', page.text)
        skip_url = re.search(r'id="vtcOptionalSkip" href="([^"]+)"', page.text)[1].replace('&amp;', '&')
        self.assertEqual(parse_qs(urlsplit(skip_url).query)['activity'], ['question-1'])
        after_skip = self._player_config(self.client.get(skip_url))
        self.assertEqual(after_skip['activityId'], 'question-1')
        tracking = self._api_post(after_skip['startUrl'], after_skip, activity_id='question-1', tab_id='optional-skip')
        self.assertEqual(tracking.status_code, 200, tracking.text)
        first = self._api_post(after_skip['answerUrl'], after_skip, answer={'selected': ['answer-a']})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json['progress']['progress_percent'], 50)
        final_page = self.client.get(url, query_string={'activity': 'question-2'})
        final_config = self._player_config(final_page)
        self.assertTrue(final_config['isLastActivity'])
        result = self._api_post(final_config['answerUrl'], final_config, answer={'groups': {'group-1': 'blank-a'}})
        self.assertEqual(result.status_code, 200, result.text)
        progress = result.json['progress']
        self.assertTrue(progress['module_complete'])
        self.assertEqual(progress['progress_percent'], 100)
        self.assertEqual(progress['completed_activity_ids'], ['question-1', 'question-2'])
        self.assertEqual(self.api.call_count, 0)
        tail_page = self.client.get(url, query_string={'activity': 'optional-tail'})
        self.assertIn('id="vtcOptionalSkip" href="/espace/public-token/elearning"', tail_page.text)
        # Voluntary validation of a workshop still requires an actual correction.
        refused = self._api_post(optional['completeUrl'], optional)
        self.assertEqual(refused.status_code, 400)

    def test_full_v12_path_and_final_open_with_no_optional_production(self):
        session = self.data['sessions'][0]
        session['aps_native_modules'] = [
            {'course_id': 'academy-vtc-' + letter.lower(), 'course_version': VERSION, 'required_minutes': minutes}
            for letter, minutes in MODULE_MINUTES.items()]
        store = NativeElearningStore(self.persist_dir / 'native_elearning' / 'tracking.sqlite3')
        for module in session['aps_native_modules']:
            course = vtc.load_bundled_course(module['course_id'], VERSION)
            access = dict(session_id=session['id'], trainee_id='trainee-1',
                          course_id=course['id'], course_version=VERSION)
            store.get_progress(access)
            answers = {a['id']: {'correct': True} for s in course['sections'] for a in s['activities'] if a.get('scored')}
            videos = {aid: {vid: {'duration_seconds': duration, 'watched_seconds': duration, 'completed': True}
                            for vid, duration in required.items()} for aid, required in course_videos(course).items()}
            with store._connect() as db:
                db.execute('''UPDATE learner_course_progress SET completed_json=?, answers_json=?, video_progress_json=?,
                    active_seconds=?, started_at='2026-10-01T08:00:00Z'
                    WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?''',
                    (json.dumps(required_activity_order(course)), json.dumps(answers), json.dumps(videos),
                     module['required_minutes'] * 60, *store._key_values(access)))
        path = self.client.get('/espace/public-token/elearning')
        self.assertEqual(path.status_code, 200, path.text)
        self.assertIn('336 / 336', path.text)
        self.assertIn('4 productions facultatives', path.text)
        final_id = vtc.curriculum_manifest()['final_exam_id']
        final_url = '/espace/public-token/elearning/exams/' + final_id
        self.assertEqual(self.client.get(final_url).status_code, 200)
        with store._connect() as db:
            db.execute('UPDATE learner_course_progress SET active_seconds=active_seconds-60 WHERE course_id=?', ('academy-vtc-a',))
        self.assertEqual(self.client.get(final_url).status_code, 403)
