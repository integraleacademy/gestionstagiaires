"""Practice grading, retakes, version isolation and learner authorization."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from elearning_native.academy import ROOT, curriculum_manifest, load_bundled_course
from elearning_native.exams import ExamStore, load_exam, public_exam, grade_exam
from tests import test_native_elearning_web as web_tests

VERSION='20261004-aps62-v2'

class ExamDataTests(unittest.TestCase):
    def test_questions_balance_and_grading(self):
        seen=set()
        for module in curriculum_manifest()['modules']:
            exam=load_exam('module-'+module['number'],VERSION)
            self.assertEqual(len(exam['questions']),30)
            for q in exam['questions']:
                self.assertNotIn(q['id'],seen);seen.add(q['id'])
                self.assertEqual(len({o['text'] for o in q['options']}),3)
                self.assertTrue(q['explanation'] and q['sources'])
            public=json.dumps(public_exam(exam))
            self.assertNotIn('"answer"',public)
            self.assertNotIn('explanation',public)
            answers={q['id']:q['answer'] for q in exam['questions']}
            self.assertEqual(grade_exam(exam,answers)['score'],30)
            for q in exam['questions'][:8]:
                answers[q['id']]=next(o['id'] for o in q['options'] if o['id']!=q['answer'])
            self.assertFalse(grade_exam(exam,answers)['passed'])
            with self.assertRaises(ValueError):grade_exam(exam,{})
            with self.assertRaises(ValueError):grade_exam(exam,answers|{'unexpected':'1'})
            with self.assertRaises(ValueError):grade_exam(exam,answers|{exam['questions'][0]['id']:['1']})
        final=load_exam('final',VERSION)
        self.assertEqual(len(final['questions']),100)
        self.assertEqual(len({q['id'] for q in final['questions']}),100)
        self.assertEqual(len({q['module'] for q in final['questions']}),15)
        self.assertIsNone(load_exam('../manifest',VERSION))
        self.assertIsNone(load_exam('final','../../'))

    def test_old_edition_preserved_and_new_capsules_complete(self):
        for module in curriculum_manifest()['modules']:
            old=load_bundled_course(module['id'],'20261003-aps62-v1')
            new=load_bundled_course(module['id'],VERSION)
            self.assertEqual(old['activity_order'],new['activity_order'])
            self.assertEqual(old['required_minutes'],new['required_minutes'])
            self.assertNotIn('mock_exam_id',old)
            self.assertEqual(new['mock_exam_id'],'module-'+module['number'])
            for section in new['sections']:
                video=section['activities'][1]['blocks'][0]['video']
                self.assertEqual(video['voice'],'fr-FR-HenriNeural')
                self.assertTrue(video['burned_captions'])
                self.assertIn('/v2/',video['src'])
                self.assertTrue((ROOT/'assets'/video['src']).is_file())

    def test_retakes_idempotence_and_isolation(self):
        exam=load_exam('module-01',VERSION)
        answers={q['id']:q['answer'] for q in exam['questions']}
        result=grade_exam(exam,answers)
        with tempfile.TemporaryDirectory() as folder:
            store=ExamStore(Path(folder)/'tracking.sqlite3')
            first=store.save('s','a',exam,'a'*32,result)
            repeat=store.save('s','a',exam,'a'*32,result|{'score':0})
            self.assertEqual(first,repeat)
            store.save('s','a',exam,'b'*32,result)
            self.assertEqual(len(store.history('s','a',exam)),2)
            self.assertEqual(store.history('s','b',exam),[])
            self.assertEqual(store.history('other','a',exam),[])
            with self.assertRaises(ValueError):store.save('s','a',exam,'bad',result)

class ExamWebTests(unittest.TestCase):
    setUp=web_tests.NativeElearningWebTests.setUp
    tearDown=web_tests.NativeElearningWebTests.tearDown
    _admin_login=web_tests.NativeElearningWebTests._admin_login
    _public_login=web_tests.NativeElearningWebTests._public_login

    def config(self,response):
        self.assertEqual(response.status_code,200)
        return json.loads(re.search(r'<script type="application/json" id="apsExamConfig">(.*?)</script>',response.get_data(as_text=True),re.S)[1])

    def post(self,config,answers=None,**extra):
        exam=load_exam(config['exam']['id'],VERSION)
        answers=answers if answers is not None else {q['id']:q['answer'] for q in exam['questions']}
        return self.client.post(config['submitUrl'],json={'version':VERSION,'attempt_id':config['attemptId'],'answers':answers,**extra},headers={'X-Elearning-CSRF':config['csrfToken']})

    def assign_first(self):
        session=self.data['sessions'][0]
        session['aps_native_course_id']='academy-aps62-01'
        session['aps_native_course_version']=VERSION

    def test_preview_all_exams_no_tracking_and_csrf(self):
        self.assertEqual(self.client.get('/admin/elearning/exams/module-01').status_code,302)
        self._admin_login()
        with patch('elearning_native.web.ExamStore',side_effect=AssertionError('No tracking in preview')):
            for exam_id in ['module-'+m['number'] for m in curriculum_manifest()['modules']]+['final']:
                config=self.config(self.client.get('/admin/elearning/exams/'+exam_id))
                self.assertEqual(self.post(config).json['result']['percent'],100)
                self.assertEqual(self.post(config,answers={}).status_code,400)
            self.assertEqual(self.client.post(config['submitUrl'],json={}).status_code,403)
        self.assertIsNone(self.saved_data)

    def test_learner_access_retakes_and_unchanged_course_progress(self):
        self.assign_first();self._public_login()
        config=self.config(self.client.get('/espace/public-token/elearning/exams/module-01'))
        self.assertNotIn('answer',config['exam']['questions'][0])
        self.assertEqual(self.post(config).json['result']['score'],30)
        self.assertEqual(self.post(config,version='old').status_code,409)
        second=self.config(self.client.get('/espace/public-token/elearning/exams/module-01'))
        self.assertNotEqual(second['attemptId'],config['attemptId'])
        self.assertEqual(self.post(second).status_code,200)
        store=ExamStore(self.persist_dir/'native_elearning/tracking.sqlite3')
        self.assertEqual(len(store.history('session-aps','trainee-1',load_exam('module-01',VERSION))),2)
        from elearning_native.store import NativeElearningStore
        self.assertEqual(NativeElearningStore(store.path).learner_progress('session-aps','trainee-1'),[])
        self.assertEqual(self.client.get('/espace/public-token/elearning/exams/module-02').status_code,403)
        self.assertEqual(self.client.get('/espace/public-token/elearning/exams/final').status_code,403)
        self.assertEqual(self.client.post('/api/espace/not-my-token/elearning/exams/module-01',json={},headers={'X-Elearning-CSRF':config['csrfToken']}).status_code,404)
        with self.client.session_transaction() as browser:browser.pop('public_auth_public-token')
        self.assertEqual(self.post(config).status_code,401)

    def test_final_locked_when_all_assigned_but_not_completed(self):
        self._public_login()
        self.data['sessions'][0]['aps_native_modules']=[{'course_id':m['id'],'course_version':VERSION} for m in curriculum_manifest()['modules']]
        self.assertEqual(self.client.get('/espace/public-token/elearning/exams/final').status_code,403)

    def test_final_unlocks_full_completed_curriculum_but_rejects_partial_selection(self):
        from elearning_native.videos import course_videos
        self._public_login()
        modules=[{'course_id':m['id'],'course_version':VERSION,'required_minutes':m['hours']*60} for m in curriculum_manifest()['modules']]
        self.data['sessions'][0]['aps_native_modules']=modules
        progress=[]
        for module in modules:
            c=load_bundled_course(module['course_id'],VERSION)
            progress.append({'course_id':c['id'],'course_version':VERSION,'completed_activity_ids':c['activity_order'],
                'active_seconds':c['required_minutes']*60,
                'video_progress':{aid:{vid:{'completed':True,'duration_seconds':duration,'watched_seconds':duration}
                    for vid,duration in requirements.items()} for aid,requirements in course_videos(c).items()}})
        with patch('elearning_native.web.NativeElearningStore.learner_progress',return_value=progress):
            config=self.config(self.client.get('/espace/public-token/elearning/exams/final'))
            self.assertEqual(len(config['exam']['questions']),100)
            self.assertEqual(self.post(config).json['result']['score'],100)
            page=self.client.get('/espace/public-token/elearning').get_data(as_text=True)
            self.assertIn('Commencer l’examen final',page)
            modules[0]['section_ids']=[load_bundled_course(modules[0]['course_id'],VERSION)['sections'][0]['id']]
            self.assertEqual(self.client.get('/espace/public-token/elearning/exams/final').status_code,403)
            self.assertNotIn('Commencer l’examen final',self.client.get('/espace/public-token/elearning').get_data(as_text=True))
