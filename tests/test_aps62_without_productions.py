"""APS writing removal must reach existing assignments as well as previews."""
import copy
import json
import unittest

from elearning_native.academy import ROOT, curriculum_manifest, load_bundled_course
from elearning_native.aps_media import restore_course_voice
from elearning_native.paths import project_course, project_progress
from elearning_native.videos import course_videos
from tests import test_native_elearning_web as fixture


def activities(course):
    return [a for section in course['sections'] for a in section['activities']]


class APSDeliveryTests(unittest.TestCase):
    def test_all_assigned_editions_remove_writing_without_rewriting_sources(self):
        manifest = curriculum_manifest()
        self.assertEqual((manifest['activity_count'], manifest['production_count'],
                          manifest['worked_example_count']), (442, 0, 10))
        for module in manifest['modules']:
            for version in [module['version'], *module['previous_versions']]:
                with self.subTest(module=module['id'], version=version):
                    path = ROOT / 'courses' / module['id'] / (version + '.json')
                    before = path.read_bytes()
                    source = json.loads(before)
                    delivered = load_bundled_course(module['id'], version)
                    retired = {a['id'] for a in activities(source) if a.get('production')}
                    self.assertEqual(delivered['activity_order'], [aid for aid in source['activity_order'] if aid not in retired])
                    self.assertFalse(any(a.get('production') for a in activities(delivered)))
                    self.assertEqual(delivered['required_minutes'], source['required_minutes'])
                    self.assertEqual(delivered['planned_minutes'], source['planned_minutes'])
                    # Current delivery reserves the mock exam inside the same
                    # module budget; archived per-activity estimates predate it.
                    if delivered.get('study_plan'):
                        self.assertEqual(sum(a['planned_minutes'] for a in activities(delivered))
                                         + delivered['study_plan']['exam_minutes'], source['planned_minutes'])
                    else:
                        self.assertEqual([sum(a.get('planned_minutes', 0) for a in s['activities']) for s in delivered['sections']],
                                         [sum(a.get('planned_minutes', 0) for a in s['activities']) for s in source['sections']])
                    # The independent voice repair has a reviewed timeline map;
                    # retiring writing must not add/remove any required video.
                    self.assertEqual(course_videos(delivered), course_videos(restore_course_voice(copy.deepcopy(source))))
                    self.assertNotIn('À vous de produire', json.dumps(delivered, ensure_ascii=False))
                    self.assertEqual(path.read_bytes(), before)

    def test_existing_progress_ignores_retired_steps_but_keeps_time_and_video_rules(self):
        course = load_bundled_course('academy-aps62-01')
        selected = project_course(course, {'section_ids': [course['sections'][1]['id']], 'required_minutes': 57})
        retired = 'aps62-01-02-transfert'
        history = {'completed_activity_ids': selected['activity_order'] + [retired],
                   'answers': {a['id']: {'correct': True} for a in activities(selected) if a.get('scored')},
                   'active_seconds': 0, 'video_progress': {}}
        history['answers'][retired] = {'production_answers': {'dossiers': 'Brouillon historique'}}
        for aid, videos in course_videos(selected).items():
            history['video_progress'][aid] = {vid: {'completed': True, 'watched_seconds': duration,
                'duration_seconds': duration, 'ranges': [[0, duration]]} for vid, duration in videos.items()}
        untouched = copy.deepcopy(history)
        result = project_progress(history, selected)
        self.assertEqual(result['progress_percent'], 100)
        self.assertEqual(result['status'], 'awaiting_time')
        self.assertEqual(result['active_seconds'], 0)
        self.assertNotIn(retired, result['answers'])
        self.assertEqual(history, untouched)
        history['active_seconds'] = 57 * 60
        self.assertEqual(project_progress(history, selected)['status'], 'passed')
        history['video_progress'] = {}
        self.assertLess(project_progress(history, selected)['progress_percent'], 100)


class APSRemovalHTTPTests(unittest.TestCase):
    setUp = fixture.NativeElearningWebTests.setUp
    tearDown = fixture.NativeElearningWebTests.tearDown
    _admin_login = fixture.NativeElearningWebTests._admin_login
    _public_login = fixture.NativeElearningWebTests._public_login
    _player_config = staticmethod(fixture.NativeElearningWebTests._player_config)
    _api_post = fixture.NativeElearningWebTests._api_post

    def test_old_preview_link_opens_the_read_only_example(self):
        self._admin_login()
        response = self.client.get('/admin/elearning/courses/academy-aps62-01/preview',
            query_string={'version': '20261010-aps62-v11', 'activity': 'aps62-01-02-transfert'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('activity=aps62-01-02-comprendre', response.location)
        response = self.client.get(response.location)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Exemple corrigé · Lecture guidée', response.text)
        self.assertIn('Le corrigé expliqué', response.text)
        self.assertNotIn('Production personnelle', response.text)
        self.assertNotIn('apsProductionConfig', response.text)
        self.assertNotIn('<textarea', response.text)

    def test_existing_learner_link_and_submission_cannot_reopen_writing(self):
        assignment = self.data['sessions'][0]
        assignment['aps_native_course_id'] = 'academy-aps62-01'
        assignment['aps_native_course_version'] = '20261012-aps62-v12'
        self._public_login()
        response = self.client.get('/espace/public-token/elearning/academy-aps62-01',
            query_string={'activity': 'aps62-01-02-transfert'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Production personnelle', response.text)
        self.assertNotIn('apsProductionConfig', response.text)
        config = self._player_config(response)
        response = self._api_post('/api/elearning/v1/activities/aps62-01-02-transfert/production', config,
            stage='draft', production_answers={'dossiers': 'Ancien onglet ouvert'})
        self.assertEqual(response.status_code, 404)


if __name__ == '__main__':
    unittest.main()
