from __future__ import annotations
import copy
import hashlib
import html
import json
import os
import re
import unittest
from collections import Counter
from unittest.mock import patch
from elearning_native import a3p
from elearning_native.exams import load_exam, public_exam, grade_exam
from elearning_native.importer import CourseCatalog, CourseImportError
from elearning_native.paths import project_course, validate_modules, path_revision, course_outline, project_progress
from elearning_native.web import _evaluate_answer, TrackingError
from tests import test_native_elearning_web as fixtures


class A3PContentTests(unittest.TestCase):
    def test_every_lesson_has_a_readable_learning_sequence(self):
        m=a3p.curriculum_manifest()
        self.assertEqual((m['lesson_count'],m['question_count']),(95,245))
        refs=set();questions=0
        for cid in a3p.curriculum_ids():
            c=a3p.load_bundled_course(cid)
            self.assertFalse(c['preview_only'])
            self.assertEqual(len(c['activity_order']),len(set(c['activity_order'])))
            for s in c['sections']:
                if s['activities'][0].get('a3p',{}).get('kind')!='lesson':continue
                a=s['activities'];ref=a[0]['a3p']['ref'];refs.add(ref)
                self.assertEqual([x['a3p']['kind'] for x in a],['lesson','application','quiz','recap'])
                self.assertTrue(a[0]['a3p']['pages'])
                self.assertTrue(a[1]['a3p']['example']['paragraphs'])
                self.assertTrue(a[3]['a3p']['points'])
                self.assertEqual(len({x['title'] for x in a}),4)
                self.assertNotIn('Vérifier mes connaissances',str(a))
                quiz=a[2];questions+=len(quiz['answer_groups'])
                answers={g['id']:next(o['id'] for o in g['answers'] if o['is_correct']) for g in quiz['answer_groups']}
                self.assertTrue(_evaluate_answer(quiz,{'groups':answers})[0])
                group=quiz['answer_groups'][-1]
                answers[group['id']]=next(o['id'] for o in group['answers'] if not o['is_correct'])
                self.assertFalse(_evaluate_answer(quiz,{'groups':answers})[0])
                with self.assertRaises(TrackingError):_evaluate_answer(quiz,{'groups':{}})
        self.assertEqual(len(refs),95);self.assertEqual(questions,245)

    def test_distance_scope_and_minima_cannot_include_non_rows(self):
        m=a3p.curriculum_manifest();r=m['regulatory_review']
        self.assertEqual(sum(x['planned_minutes'] for x in m['modules']),9450)
        self.assertEqual(sum(x['minimum_minutes'] for x in r['eligible_objectives'] if x['annex']=='II'),1620)
        self.assertEqual(sum(x['minimum_minutes'] for x in r['eligible_objectives'] if x['annex']=='XI'),7830)
        self.assertEqual(len(r['eligible_objectives']),40)
        for row in r['eligible_objectives']:
            self.assertTrue(row['lesson_refs'])
            self.assertTrue(all(a3p._mode(ref)=='distance' for ref in row['lesson_refs']))
        for cid in a3p.curriculum_ids():
            c=a3p.load_bundled_course(cid)
            projected=project_course(c,{'required_minutes':c['required_minutes']})
            self.assertTrue(all(s['delivery']=='distance' for s in projected['sections']))
            self.assertEqual(project_progress({},projected)['active_seconds'],0)
            self.assertFalse(project_progress({},projected)['module_complete'])
            self.assertEqual([s['id'] for s in course_outline(c)['sections']],[s['id'] for s in projected['sections']])
            with self.assertRaises(CourseImportError):project_course(c,{'required_minutes':0})
            with self.assertRaises(CourseImportError):project_course(c,{'required_minutes':c['required_minutes'],'section_ids':[c['sections'][-1]['id']]})
            if len(projected['sections'])>1:
                with self.assertRaises(CourseImportError):project_course(c,{'required_minutes':c['required_minutes'],'section_ids':[projected['sections'][0]['id']]})
        self.assertEqual(a3p._mode('06.12'),'presentiel')
        self.assertEqual(a3p._mode('06.27'),'complement')
        self.assertEqual(a3p._mode('09.01'),'presentiel')
        self.assertEqual(a3p._mode('09.15'),'distance')

    def test_exams_are_balanced_graded_and_do_not_leak_answers(self):
        final=load_exam('a3p-final',a3p.VERSION)
        self.assertEqual(len(final['questions']),100)
        self.assertEqual(sorted(Counter(q['module'] for q in final['questions']).values()),[12]*4+[13]*4)
        for eid in ['a3p-final',*['a3p-module-'+uv for uv in a3p.MODULES]]:
            exam=load_exam(eid,a3p.VERSION)
            self.assertEqual(len(exam['questions']),100 if eid=='a3p-final' else 30)
            for q in public_exam(exam)['questions']:self.assertEqual(set(q),{'id','prompt','options'})
            self.assertEqual(grade_exam(exam,{q['id']:q['answer'] for q in exam['questions']})['percent'],100)
            self.assertEqual(grade_exam(exam,{q['id']:next(o['id'] for o in q['options'] if o['id']!=q['answer']) for q in exam['questions']})['percent'],0)
        self.assertIsNone(load_exam('a3p-final','unknown'))

    def test_versions_and_media_are_preserved(self):
        old=a3p.load_bundled_course('academy-a3p-02',a3p.legacy.VERSION)
        self.assertTrue(old['preview_only']);self.assertEqual(old['sections'][0]['activities'][1]['id'],'a3p-q-001')
        c=a3p.load_bundled_course('academy-a3p-02');c['sections'].clear()
        self.assertTrue(a3p.load_bundled_course('academy-a3p-02')['sections'])
        for uv in a3p.MODULES:
            v=a3p._video(uv)
            if not v:continue
            self.assertEqual(v['voice'],'fr-FR-HenriNeural');self.assertTrue(v['burned_captions'])
            for version in [a3p.VERSION,a3p.legacy.VERSION]:
                for k in ('src','poster','captions'):self.assertTrue(a3p.bundled_asset('academy-a3p-'+uv,version,v[k]).is_file())
            self.assertEqual(hashlib.sha256(a3p.bundled_asset('academy-a3p-'+uv,a3p.VERSION,v['src']).read_bytes()).hexdigest(),v['video_sha256'])
        self.assertIsNone(a3p.bundled_asset('academy-a3p-02',a3p.VERSION,'../../manual.json'))


class A3PWebTests(unittest.TestCase):
    setUp=fixtures.NativeElearningWebTests.setUp
    tearDown=fixtures.NativeElearningWebTests.tearDown
    _admin_login=fixtures.NativeElearningWebTests._admin_login
    _public_login=fixtures.NativeElearningWebTests._public_login
    _player_config=staticmethod(fixtures.NativeElearningWebTests._player_config)
    _api_post=fixtures.NativeElearningWebTests._api_post

    def csrf(self):
        with self.client.session_transaction() as s:return s['native_elearning_csrf']

    def preview(self,cid='academy-a3p-02',activity=None):
        args={'version':a3p.VERSION}
        if activity:args['activity']=activity
        r=self.client.get('/admin/elearning/courses/'+cid+'/preview',query_string=args)
        self.assertEqual(r.status_code,200);return r.text

    def test_catalog_and_all_lesson_pages_render_without_tracking(self):
        self._admin_login()
        with patch('elearning_native.web.NativeElearningStore',side_effect=AssertionError('preview wrote tracking')):
            page=self.client.get('/admin/elearning/a3p')
            self.assertEqual(page.status_code,200)
            for text in ('245','95','157 h 30','Répondre au QCM'):self.assertIn(text,page.text)
            for text in ('ADEF','suspendue','certificateur'):self.assertNotIn(text,page.text)
            for cid in a3p.curriculum_ids():
                c=a3p.load_bundled_course(cid)
                for s in c['sections']:
                    for activity in s['activities']:
                        page=self.preview(cid,activity['id'])
                        self.assertIn(activity['title'].replace('’','’').split(' · ')[0],page)
                        self.assertNotIn('nativeActiveTimer',page)
                        self.assertNotIn('nativeElearningConfig',page)
                        self.assertNotIn('Vérifier mes connaissances',page)
            self.assertIsNone(self.saved_data)

    def test_grouped_quiz_csrf_feedback_and_correction_links(self):
        self._admin_login();c=a3p.load_bundled_course('academy-a3p-02');q=c['sections'][0]['activities'][2]
        page=self.preview(c['id'],q['id'])
        self.assertNotIn('is_correct',page);self.assertNotIn(q['explanation'],page)
        config=json.loads(re.search(r'<script id="nativePreviewConfig" type="application/json">(.*?)</script>',page,re.S).group(1))
        answer={'answer':{'groups':{g['id']:next(o['id'] for o in g['answers'] if o['is_correct']) for g in q['answer_groups']}}}
        self.assertEqual(self.client.post(config['answerUrl'],json=answer).status_code,403)
        r=self.client.post(config['answerUrl'],json=answer,headers={'X-Elearning-CSRF':self.csrf()});self.assertTrue(r.json['correct'])
        self.assertEqual(r.json['explanation'],q['explanation'])
        exam=load_exam('a3p-final',a3p.VERSION)
        r=self.client.post('/api/admin/elearning/exams/a3p-final',json={'version':a3p.VERSION,'answers':{q['id']:q['answer'] for q in exam['questions']}},headers={'X-Elearning-CSRF':self.csrf()})
        self.assertEqual(r.status_code,200);self.assertEqual(r.json['result']['score'],100)
        self.assertTrue(all(c['lesson_links'] for c in r.json['result']['corrections']))

    def test_video_private_range(self):
        if not a3p._video('02'):self.skipTest('Media checked on CI')
        self._admin_login();page=self.preview(activity='a3p-02-video')
        src=html.unescape(re.search(r'<source src="([^"]+)"',page,re.S).group(1))
        r=self.client.get(src,headers={'Range':'bytes=0-1023'});self.assertEqual(r.status_code,206);self.assertEqual(len(r.data),1024)
        with self.client.session_transaction() as s:s.pop('admin_logged_in')
        self.assertEqual(self.client.get(src).status_code,401)

    def assign(self,uv='02'):
        s=self.data['sessions'][0];s['training_type']='A3P'
        c=a3p.load_bundled_course('academy-a3p-'+uv)
        module={'course_id':c['id'],'course_version':c['version'],'required_minutes':c['required_minutes']}
        s['aps_native_modules']=validate_modules([module],CourseCatalog(self.persist_dir/'native_elearning'))
        return c

    def test_a3p_assignment_composer_and_learner_scope(self):
        self._admin_login();s=self.data['sessions'][0];s['training_type']='A3P'
        self.preview();c=a3p.load_bundled_course('academy-a3p-06')
        module={'course_id':c['id'],'course_version':c['version'],'required_minutes':c['required_minutes']}
        r=self.client.post('/api/admin/sessions/session-aps/elearning/path',json={'revision':path_revision(s),'title':'A3P','modules':[module]},headers={'X-Elearning-CSRF':self.csrf()})
        self.assertEqual(r.status_code,200)
        page=self.client.get('/admin/sessions/session-aps/elearning');self.assertIn('a3pAddPath',page.text)
        self._public_login();page=self.client.get('/espace/public-token/elearning/academy-a3p-06')
        self.assertEqual(page.status_code,200);self.assertIn('nativeElearningConfig',page.text)
        self.assertNotIn('06.12 ·',page.text);self.assertNotIn('06.27 ·',page.text)
        self.assertEqual(self.client.get('/espace/public-token/elearning/academy-a3p-06?activity=a3p-06-12-cours').status_code,404)
        self.assertEqual(self.client.get('/espace/public-token/elearning/exams/a3p-module-06').status_code,200)
        self.assertEqual(self.client.get('/espace/public-token/elearning/exams/a3p-final').status_code,403)

    def test_wrong_quiz_cannot_unlock_next_fraction_or_credit_time(self):
        c=self.assign();self._public_login()
        response=self.client.get('/espace/public-token/elearning/academy-a3p-02');config=self._player_config(response)
        for aid in ('a3p-02-01-cours','a3p-02-01-application'):
            r=self._api_post('/api/elearning/v1/activities/'+aid+'/complete',config)
            self.assertEqual(r.status_code,200)
        q=c['sections'][0]['activities'][2]
        wrong={g['id']:next(o['id'] for o in g['answers'] if not o['is_correct']) for g in q['answer_groups']}
        r=self._api_post('/api/elearning/v1/activities/'+q['id']+'/answer',config,answer={'groups':wrong})
        self.assertEqual(r.status_code,200);self.assertTrue(r.json['retry_required'])
        self.assertNotIn(q['id'],r.json['progress']['completed_activity_ids'])
        self.assertEqual(r.json['progress']['active_seconds'],0)
        correct={g['id']:next(o['id'] for o in g['answers'] if o['is_correct']) for g in q['answer_groups']}
        r=self._api_post('/api/elearning/v1/activities/'+q['id']+'/answer',config,answer={'groups':correct})
        self.assertTrue(r.json['correct']);self.assertIn(q['id'],r.json['progress']['completed_activity_ids'])

    def test_anonymous_and_old_editions_remain_protected(self):
        self.assertEqual(self.client.get('/admin/elearning/a3p').status_code,302)
        self.assertEqual(self.client.post('/api/admin/elearning/exams/a3p-final',json={}).status_code,401)
        with self.assertRaises(CourseImportError):project_course(a3p.load_bundled_course('academy-a3p-02',a3p.legacy.VERSION),{'required_minutes':1500})
        self._admin_login();self.assertEqual(self.client.get('/admin/elearning/courses/academy-a3p-02/preview?version=unknown').status_code,404)

if __name__=='__main__':unittest.main()
