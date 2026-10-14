"""Reading enrichment reaches existing assignments without new writing or credit."""
import copy
import html
import unittest
from flask import render_template

from elearning_native.academy import curriculum_manifest, load_bundled_course
from elearning_native.aps_lessons import REVISION
from elearning_native.aps_workload import summarize
from tests import test_aps62_depth as fixture


class ReadingContentTests(unittest.TestCase):
    def test_reading_reaches_all_assigned_editions(self):
        manifest = curriculum_manifest()
        seen = set()
        self.assertEqual((manifest['reading_page_count'], manifest['reading_comparison_count'],
                          manifest['reading_example_count']), (186, 62, 62))
        for module in manifest['modules']:
            for version in [module['version'], *module['previous_versions']]:
                course = load_bundled_course(module['id'], version)
                self.assertEqual(course['aps_reading_revision'], REVISION)
                for section in course['sections']:
                    seen.add(section['id'])
                    lesson = next(a['academy'] for a in section['activities']
                                  if a.get('academy', {}).get('kind') == 'lesson')
                    pages = lesson['reading_pages']
                    self.assertEqual([p['kind'] for p in pages], ['explanation', 'comparison', 'example'])
                    self.assertTrue(pages[0]['paragraphs'])
                    self.assertTrue(all(len(row) == 3 for row in pages[1]['rows']))
                    self.assertTrue(pages[2]['reasoning'])
                    self.assertTrue(pages[2]['takeaway'])
                    self.assertFalse(any(a.get('production') for a in section['activities']))
                    self.assertFalse(any(a.get('workbook') for a in section['activities']))
        self.assertEqual(len(seen), 62)

    def test_old_calibration_snapshot_is_preserved_and_excluded(self):
        course = load_bundled_course('academy-aps62-01')
        record = {'assigned_current': True, 'required_seconds': 14400,
            'active_seconds': 3615, 'activities_completed': True,
            'activity_seconds': {'aps62-01-01-comprendre': 3615},
            'aps_workload': {'revision': '20261014-aps-dossiers-v16', 'active_seconds': 3615,
                'activity_seconds': {'aps62-01-01-comprendre': 3615},
                'workshop_revisions': {a['id']: '20261014-aps-dossiers-v16'
                    for s in course['sections'] for a in s['activities']
                    if a.get('academy', {}).get('kind') == 'workshop'}}}
        before = copy.deepcopy(record)
        report = summarize(course, [record])
        self.assertEqual(report['sample_count'], 0)
        self.assertIn('révision antérieure', report['learners'][0]['reason'])
        self.assertEqual(report['learners'][0]['total_label'], '01:00:15')
        self.assertEqual(record, before)


class ReadingHTTPTests(unittest.TestCase):
    setUp = fixture.DepthHTTPTests.setUp
    tearDown = fixture.DepthHTTPTests.tearDown
    _admin_login = fixture.DepthHTTPTests._admin_login
    database = fixture.DepthHTTPTests.database

    def test_all_lessons_render_read_only_with_accessible_comparisons(self):
        self._admin_login()
        for module in curriculum_manifest()['modules']:
            course = load_bundled_course(module['id'])
            for section in course['sections']:
                lesson = next(a for a in section['activities'] if a.get('academy', {}).get('kind') == 'lesson')
                page = self.client.get(f"/admin/elearning/courses/{course['id']}/preview?activity={lesson['id']}")
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.text.count('data-aps-reading='), 3)
                self.assertIn(lesson['academy']['reading_pages'][0]['title'], html.unescape(page.text))
                self.assertIn('<caption>', page.text)
                self.assertIn('scope="row"', page.text)
                self.assertIn('css/aps62-depth.css', page.text)
                self.assertNotIn('<textarea', page.text)
                self.assertNotIn('apsProductionConfig', page.text)
                self.assertNotIn('contenteditable=', page.text)
        self.assertFalse(self.database.exists(), 'admin previews must never create learner records')

    def test_oldest_edition_gets_reading_styles_and_report_is_easy_to_find(self):
        self._admin_login()
        module = curriculum_manifest()['modules'][0]
        course = load_bundled_course(module['id'], min(module['previous_versions']))
        page = self.client.get(f"/admin/elearning/courses/{course['id']}/preview", query_string={'version': course['version']})
        self.assertEqual(page.status_code, 200)
        self.assertIn('data-aps-reading="explanation"', page.text)
        self.assertIn('css/aps62-depth.css', page.text)
        # Render the real APS catalogue partial without loading unrelated VTC
        # media, intentionally absent from this sparse checkout.
        with fixture.web_fixture.gestion_app.app.test_request_context('/admin/elearning'):
            catalog = render_template('_aps62_catalog.html', academy_manifest=curriculum_manifest(),
                academy_courses=[load_bundled_course(m['id']) for m in curriculum_manifest()['modules']])
        hero = catalog.split('class="aps-catalog-hero"', 1)[1].split('</section>', 1)[0]
        self.assertIn('/admin/elearning/calibrage', hero)
        self.assertIn('Rapport de calibrage des durées', hero)
        live = self.client.get('/admin/elearning/courses/academy-aps62-01/live')
        self.assertEqual(live.status_code, 200)
        self.assertIn('Rapport de calibrage', live.text)
        self.assertNotIn('>Travaux écrits</a>', live.text)


class ReadingCompletionTests(unittest.TestCase):
    setUp = fixture.DepthHTTPTests.setUp
    tearDown = fixture.DepthHTTPTests.tearDown
    _public_login = fixture.DepthHTTPTests._public_login
    _player_config = staticmethod(fixture.DepthHTTPTests._player_config)
    _api_post = fixture.DepthHTTPTests._api_post

    def test_new_reading_records_revision_without_credit_and_old_completion_is_unchanged(self):
        from elearning_native.web import _b64decode, _sign_access
        import json
        import sqlite3
        course = load_bundled_course('academy-aps62-01')
        self.data['sessions'][0].update(aps_native_course_id=course['id'], aps_native_course_version=course['version'])
        self._public_login()
        page = self.client.get('/espace/public-token/elearning/academy-aps62-01')
        config = self._player_config(page)
        result = self._api_post(config['completeUrl'], config)
        self.assertEqual(result.status_code, 200)
        progress = result.get_json()['progress']
        aid = config['activityId']
        self.assertEqual(progress['answers'][aid], {'reading_revision': REVISION})
        self.assertEqual(progress['active_seconds'], 0)
        self.assertEqual(progress['score_percent'], 0)
        # A page opened before enrichment cannot mark the new reading complete.
        access = json.loads(_b64decode(config['accessToken'].split('.')[0]))
        access['aps_reading_revision'] = 'old-reading'
        with fixture.web_fixture.gestion_app.app.app_context():
            stale = {**config, 'accessToken': _sign_access(access)}
        self.assertEqual(self._api_post(config['completeUrl'], stale).status_code, 409)
        # Reopening already completed historical reading does not relabel it.
        db = self.persist_dir / 'native_elearning' / 'tracking.sqlite3'
        with sqlite3.connect(db) as connection:
            connection.execute('UPDATE learner_course_progress SET answers_json=?, active_seconds=3615', ('{}',))
        again = self._api_post(config['completeUrl'], config)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.get_json()['progress']['answers'], {})
        self.assertEqual(again.get_json()['progress']['active_seconds'], 3615)


if __name__ == '__main__':
    unittest.main()
