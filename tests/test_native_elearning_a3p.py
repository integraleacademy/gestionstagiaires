from __future__ import annotations
import copy
import os
import hashlib
import json
import re
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from elearning_native import a3p
from elearning_native.exams import load_exam, public_exam, grade_exam
from elearning_native.importer import CourseCatalog, CourseImportError
from elearning_native.paths import project_course, validate_modules, path_revision
from tests import test_native_elearning_web as fixtures


class A3PContentTests(unittest.TestCase):
    def test_every_lesson_is_present_assessed_and_sourced(self):
        m = a3p.curriculum_manifest()
        self.assertEqual((m['lesson_count'], m['reading_page_count'], m['question_count']), (94, 336, 242))
        refs, prompts, ids = set(), set(), set()
        for cid in a3p.curriculum_ids():
            course = a3p.load_bundled_course(cid)
            self.assertTrue(course['preview_only'])
            self.assertEqual(course['required_minutes'], 0)
            self.assertEqual(course['planned_minutes'], 0)
            self.assertEqual(course['counts']['required_videos'], 0)
            for section in course['sections'][:-1]:
                lesson = section['activities'][0]['a3p']
                self.assertNotIn(lesson['ref'], refs)
                refs.add(lesson['ref'])
                self.assertTrue(lesson['objective'])
                self.assertTrue(lesson['pages'])
                self.assertTrue(all(p['components'] and 1 <= p['page'] <= 400 for p in lesson['pages']))
                self.assertTrue(any(a['scored'] for a in section['activities']))
                for question in section['activities'][1:]:
                    self.assertNotIn(question['prompt'], prompts)
                    prompts.add(question['prompt'])
                    self.assertNotIn(question['id'], ids)
                    ids.add(question['id'])
                    self.assertEqual(sum(o['is_correct'] for o in question['options']), 1)
                    self.assertEqual(len({o['text'] for o in question['options']}), 3)
                    self.assertTrue(question['explanation'])
            case = course['sections'][-1]['activities'][0]['a3p']['case']
            self.assertEqual(len(case['tasks']), 4)
            self.assertTrue(case['example'])
            self.assertEqual(len(case['steps']), 3)
            self.assertTrue(all(0 <= step['answer'] < len(step['options']) for step in case['steps']))
        self.assertEqual(len(refs), 94)
        self.assertEqual(len(ids), 242)

    def test_exams_are_balanced_graded_and_do_not_leak_answers(self):
        final = load_exam('a3p-final', a3p.VERSION)
        self.assertEqual(len(final['questions']), 100)
        self.assertEqual(len({q['id'] for q in final['questions']}), 100)
        self.assertEqual(sorted(Counter(q['module'] for q in final['questions']).values()), [12]*4 + [13]*4)
        for exam_id in ['a3p-final', *['a3p-module-' + uv for uv in a3p.MODULES]]:
            exam = load_exam(exam_id, a3p.VERSION)
            if exam_id != 'a3p-final':
                self.assertEqual(len(exam['questions']), 30)
            public = public_exam(exam)
            for q in public['questions']:
                self.assertEqual(set(q), {'id', 'prompt', 'options'})
                self.assertTrue(all(set(o) == {'id', 'text'} for o in q['options']))
            correct = {q['id']: q['answer'] for q in exam['questions']}
            result = grade_exam(exam, correct)
            self.assertEqual(result['percent'], 100)
            wrong = {q['id']: next(o['id'] for o in q['options'] if o['id'] != q['answer']) for q in exam['questions']}
            self.assertEqual(grade_exam(exam, wrong)['percent'], 0)
            with self.assertRaises(ValueError):
                grade_exam(exam, {})
        self.assertIsNone(load_exam('a3p-final', 'unknown'))
        self.assertIsNone(load_exam('a3p-module-01', a3p.VERSION))

    def test_video_metadata_and_assets_when_built(self):
        manifest = a3p.curriculum_manifest()
        if os.environ.get('A3P_REQUIRE_MEDIA') == '1':
            self.assertEqual(manifest['video_count'], 8)
        for uv in a3p.MODULES:
            video = a3p._video(uv)
            if not video:
                continue
            self.assertEqual(video['voice'], 'fr-FR-HenriNeural')
            self.assertTrue(video['burned_captions'])
            self.assertGreater(video['duration_seconds'], 120)
            self.assertEqual(video['chapters'][0]['start_seconds'], 0)
            self.assertLessEqual(video['chapters'][-1]['end_seconds'], video['duration_seconds'] + .5)
            cid = 'academy-a3p-' + uv
            for key in ('src', 'poster', 'captions'):
                path = a3p.bundled_asset(cid, a3p.VERSION, video[key])
                self.assertTrue(path and path.is_file())
            self.assertIsNone(a3p.bundled_asset(cid, a3p.VERSION, '../../manual.json'))
            self.assertIsNone(a3p.bundled_asset(cid, 'unknown', video['src']))
            self.assertEqual(hashlib.sha256(a3p.bundled_asset(cid, a3p.VERSION, video['src']).read_bytes()).hexdigest(), video['video_sha256'])

    def test_versions_and_cached_content_cannot_be_mutated(self):
        c = a3p.load_bundled_course('academy-a3p-02')
        c['sections'].clear()
        self.assertTrue(a3p.load_bundled_course('academy-a3p-02')['sections'])
        self.assertIsNone(a3p.load_bundled_course('academy-a3p-02', '../../unknown'))
        self.assertIsNone(a3p.load_bundled_course('academy-a3p-01'))

    def test_regulatory_minutes_are_not_learner_credit(self):
        review = a3p.curriculum_manifest()['regulatory_review']
        self.assertEqual(sum(r['minimum_minutes'] for r in review['eligible_objectives'] if r['annex']=='II'), 1620)
        self.assertEqual(sum(r['minimum_minutes'] for r in review['eligible_objectives'] if r['annex']=='XI'), 7830)
        self.assertEqual(review['certifying_minutes'], 0)
        for cid in a3p.curriculum_ids():
            with self.assertRaises(CourseImportError):
                project_course(a3p.load_bundled_course(cid), {'required_minutes': 60})


class A3PWebTests(unittest.TestCase):
    setUp = fixtures.NativeElearningWebTests.setUp
    tearDown = fixtures.NativeElearningWebTests.tearDown
    _admin_login = fixtures.NativeElearningWebTests._admin_login
    _public_login = fixtures.NativeElearningWebTests._public_login

    def csrf(self):
        with self.client.session_transaction() as s:
            return s['native_elearning_csrf']

    def preview(self, cid='academy-a3p-02', activity=None):
        args={'version':a3p.VERSION}
        if activity:
            args['activity']=activity
        response=self.client.get('/admin/elearning/courses/'+cid+'/preview', query_string=args)
        self.assertEqual(response.status_code,200)
        return response.text

    def test_catalog_and_all_lesson_pages_render_without_tracking(self):
        self._admin_login()
        with patch('elearning_native.web.NativeElearningStore', side_effect=AssertionError('preview wrote tracking')):
            page=self.client.get('/admin/elearning/a3p')
            self.assertEqual(page.status_code,200)
            self.assertIn('242',page.text)
            self.assertIn('94',page.text)
            self.assertIn('157 h 30',page.text)
            self.assertNotIn('Composer le parcours',page.text)
            self.assertNotIn('Importer un cours',page.text)
            self.assertIn('Protection des personnes · A3P',self.client.get('/admin/elearning').text)
            for cid in a3p.curriculum_ids():
                course=a3p.load_bundled_course(cid)
                for section in course['sections']:
                    activity=section['activities'][0]
                    html=self.preview(cid,activity['id'])
                    self.assertIn('aucune heure certifiante',html)
                    self.assertNotIn('nativeActiveTimer',html)
                    self.assertNotIn('nativeElearningConfig',html)
                    self.assertNotIn('native-elearning-player.js',html)
            self.assertIsNone(self.saved_data)
        self.assertFalse((self.persist_dir/'native_elearning/tracking.sqlite3').exists())

    def test_questions_exams_csrf_and_correction_links(self):
        self._admin_login()
        course=a3p.load_bundled_course('academy-a3p-02')
        question=course['sections'][0]['activities'][1]
        page=self.preview(course['id'],question['id'])
        self.assertNotIn('is_correct',page)
        self.assertNotIn(question['explanation'],page)
        config=json.loads(re.search(r'<script id="nativePreviewConfig" type="application/json">(.*?)</script>',page,re.S).group(1))
        answer={'answer':{'selected':[next(o['id'] for o in question['options'] if o['is_correct'])]}}
        self.assertEqual(self.client.post(config['answerUrl'],json=answer).status_code,403)
        response=self.client.post(config['answerUrl'],json=answer,headers={'X-Elearning-CSRF':self.csrf()})
        self.assertTrue(response.json['correct'])
        self.assertEqual(response.json['explanation'],question['explanation'])
        exam=load_exam('a3p-final',a3p.VERSION)
        page=self.client.get('/admin/elearning/exams/a3p-final')
        self.assertEqual(page.status_code,200)
        payload={'version':a3p.VERSION,'answers':{q['id']:q['answer'] for q in exam['questions']}}
        response=self.client.post('/api/admin/elearning/exams/a3p-final',json=payload,headers={'X-Elearning-CSRF':self.csrf()})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['result']['score'],100)
        for correction in response.json['result']['corrections']:
            self.assertTrue(correction['lesson_links'])
            self.assertIn('/academy-a3p-',correction['lesson_links'][0]['url'])
        self.assertFalse((self.persist_dir/'native_elearning/tracking.sqlite3').exists())

    def test_assignment_is_rejected_on_both_admin_paths(self):
        self._admin_login()
        self.preview()
        before=copy.deepcopy(self.data)
        s=self.data['sessions'][0]
        module={'course_id':'academy-a3p-02','course_version':a3p.VERSION,'required_minutes':60}
        response=self.client.post('/api/admin/sessions/session-aps/elearning/path',json={'revision':path_revision(s),'title':'Test A3P','modules':[module]},headers={'X-Elearning-CSRF':self.csrf()})
        self.assertEqual(response.status_code,400)
        self.assertIn('certificateur',response.json['error'])
        response=self.client.post('/admin/sessions/session-aps/elearning/assign',data={'course_id':'academy-a3p-02','native_elearning_csrf':self.csrf()})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.data,before)
        catalog=CourseCatalog(self.persist_dir/'native_elearning')
        with self.assertRaises(CourseImportError):
            validate_modules([module],catalog)

    def test_anonymous_and_stale_or_forged_assignments_cannot_open_resources(self):
        self.assertEqual(self.client.get('/admin/elearning/a3p').status_code,302)
        self.assertEqual(self.client.get('/admin/elearning/courses/academy-a3p-02/preview').status_code,302)
        self.assertEqual(self.client.post('/api/admin/elearning/exams/a3p-final',json={}).status_code,401)
        self._public_login()
        s=self.data['sessions'][0]
        s['aps_native_course_id']='academy-a3p-02'
        s['aps_native_course_version']=a3p.VERSION
        self.assertIn(self.client.get('/espace/public-token/elearning/academy-a3p-02').status_code,(403,404))
        self.assertEqual(self.client.get('/espace/public-token/elearning/exams/a3p-final').status_code,404)
        self._admin_login()
        self.assertEqual(self.client.get('/admin/elearning/courses/academy-a3p-02/preview?version=unknown').status_code,404)

if __name__=='__main__':
    unittest.main()
