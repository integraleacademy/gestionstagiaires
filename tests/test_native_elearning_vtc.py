"""VTC learner flow, access boundaries, content completeness and exam isolation."""
import copy
import json
import re
import unittest
from unittest.mock import patch

from elearning_native import vtc
from elearning_native.exams import load_exam, public_exam, grade_exam, ExamStore
from elearning_native.practice import grade_practice, public_practice
from elearning_native.videos import course_videos
from tests import test_native_elearning_web as web_tests
from tests.test_native_elearning_practice import correct_answers

VERSION = '20261006-vtc-v2'

class VtcContentTests(unittest.TestCase):
    def test_narrated_edition_keeps_the_original_courses_and_exams_available(self):
        for cid in vtc.curriculum_ids():
            old=vtc.load_bundled_course(cid,'20261006-vtc-v1')
            new=vtc.load_bundled_course(cid,VERSION)
            self.assertEqual(old['activity_order'],new['activity_order'])
            self.assertEqual(old['planned_minutes'],new['planned_minutes'])
            old_video=old['sections'][-1]['activities'][0]['blocks'][0]['video']
            video=new['sections'][-1]['activities'][0]['blocks'][0]['video']
            self.assertFalse(old_video['audio'])
            self.assertTrue(video['audio'])
            self.assertEqual(video['voice'],'fr-FR-HenriNeural')
            self.assertTrue(video['burned_captions'])
            self.assertEqual(old_video['transcript'],video['transcript'])
            self.assertNotEqual(old_video['src'],video['src'])
            self.assertIsNotNone(vtc.bundled_asset(cid,'20261006-vtc-v1',old_video['src']))
            self.assertIsNotNone(load_exam(old['mock_exam_id'],'20261006-vtc-v1'))

    def test_all_lessons_have_accessible_content_and_click_only_practice(self):
        manifest=vtc.curriculum_manifest()
        self.assertEqual(len(manifest['modules']),8)
        self.assertEqual(sum(vtc.load_bundled_course(m['id'],VERSION)['planned_minutes'] for m in manifest['modules']),3600)
        refs=set()
        for module in manifest['modules']:
            course=vtc.load_bundled_course(module['id'],VERSION)
            self.assertEqual(len(course['activity_order']),26)
            self.assertEqual(sum(a['planned_minutes'] for s in course['sections'] for a in s['activities']),course['planned_minutes'])
            for section in course['sections'][:12]:
                lesson,workshop=section['activities']
                data=lesson['vtc'];refs.add(data['ref'])
                self.assertTrue(data['objective'],data['ref'])
                self.assertGreater(sum(len(p['text'].split()) for p in data['paragraphs']),150,data['ref'])
                self.assertEqual(len(data['cards']),3)
                self.assertNotIn('workbook',workshop)
                self.assertEqual({ex['kind'] for ex in workshop['practice']['exercises']},{'single','matching'})
                self.assertTrue(grade_practice(workshop['practice'],correct_answers(workshop['practice']))['correct'])
                exposed=json.dumps(public_practice(workshop['practice']))
                self.assertNotIn('"answer"',exposed)
                self.assertNotIn('"explanation"',exposed)
            self.assertEqual(len(course_videos(course)),1)
            for asset in course['assets']:
                path=vtc.bundled_asset(course['id'],VERSION,asset)
                self.assertIsNotNone(path,asset)
                self.assertGreater(path.stat().st_size,100,asset)
            self.assertIsNone(vtc.bundled_asset(course['id'],VERSION,'../manifest.json'))
            self.assertIsNone(vtc.load_bundled_course(course['id'],'../../'))
        self.assertEqual(len(refs),96)

    def test_exam_coverage_answer_keys_and_curriculum_isolation(self):
        for letter in 'abcdefgh':
            exam=load_exam('vtc-'+letter,VERSION)
            self.assertEqual(len(exam['questions']),30)
            self.assertEqual(len({q['id'] for q in exam['questions']}),30)
            for q in exam['questions']:
                self.assertEqual(len({o['text'] for o in q['options']}),3,q['id'])
                self.assertIn(q['answer'],{o['id'] for o in q['options']})
                self.assertTrue(q['explanation'])
            self.assertEqual(grade_exam(exam,{q['id']:q['answer'] for q in exam['questions']})['score'],30)
            self.assertNotIn('"answer"',json.dumps(public_exam(exam)))
            self.assertIsNone(load_exam('vtc-'+letter,'20261004-aps62-v2'))
        final=load_exam('vtc-final',VERSION)
        self.assertEqual(len(final['questions']),100)
        self.assertEqual(len({q['id'] for q in final['questions']}),100)
        self.assertEqual({q['module'] for q in final['questions']},set('ABCDEFG'))
        self.assertIsNone(load_exam('final',VERSION))
        self.assertIsNone(load_exam('vtc-../../manifest',VERSION))

class VtcWebTests(unittest.TestCase):
    tearDown=web_tests.NativeElearningWebTests.tearDown
    _admin_login=web_tests.NativeElearningWebTests._admin_login
    _public_login=web_tests.NativeElearningWebTests._public_login
    _player_config=staticmethod(web_tests.NativeElearningWebTests._player_config)
    _api_post=web_tests.NativeElearningWebTests._api_post

    def setUp(self):
        web_tests.NativeElearningWebTests.setUp(self)
        session=self.data['sessions'][0]
        session.update(training_type='VTC',name='Chauffeur VTC',aps_native_course_id='academy-vtc-a',aps_native_course_version=VERSION)

    def test_catalog_and_every_preview_render_without_writing_or_tracking(self):
        self.assertEqual(self.client.get('/admin/elearning/vtc').status_code,302)
        self._admin_login()
        page=self.client.get('/admin/elearning/vtc')
        self.assertEqual(page.status_code,200)
        self.assertIn('96',page.get_data(as_text=True))
        with patch('elearning_native.web.NativeElearningStore',side_effect=AssertionError('Preview must not track')):
            for cid in vtc.curriculum_ids():
                for aid in vtc.load_bundled_course(cid,VERSION)['activity_order']:
                    response=self.client.get(f'/admin/elearning/courses/{cid}/preview?activity={aid}&version={VERSION}')
                    self.assertEqual(response.status_code,200,aid)
                    body=response.get_data(as_text=True)
                    self.assertNotIn('<textarea',body,aid)
                    self.assertNotIn('"answer":',body,aid)
                    self.assertIn('href="/admin/elearning/vtc"',body)
        self.assertIsNone(self.saved_data)

    def test_learner_portal_enabled_dates_and_module_boundaries(self):
        self._public_login()
        self.assertIn('Accéder à mon parcours VTC',self.client.get('/espace/public-token').get_data(as_text=True))
        first='/espace/public-token/elearning/academy-vtc-a'
        self.assertEqual(self.client.get(first).status_code,200)
        self.assertEqual(self.client.get('/espace/public-token/elearning/academy-aps62-01').status_code,403)
        self.assertEqual(self.client.get('/espace/public-token/elearning/academy-vtc-b').status_code,403)
        self.data['sessions'][0]['aps_elearning_enabled']=False
        self.assertEqual(self.client.get(first).status_code,403)
        self.data['sessions'][0].update(aps_elearning_enabled=True,date_start='2099-01-01')
        self.assertEqual(self.client.get(first).status_code,403)

    def test_both_editions_keep_their_own_media_and_learner_assignment(self):
        self._admin_login()
        base='/admin/elearning/courses/academy-vtc-a/preview?activity=vtc-a-capsule&version='
        old=self.client.get(base+'20261006-vtc-v1').get_data(as_text=True)
        new=self.client.get(base+VERSION).get_data(as_text=True)
        self.assertIn('Cette version ne comporte pas de narration audio.',old)
        self.assertIn('capsule narrée et sous-titrée',new)
        self.assertNotIn('Cette version ne comporte pas de narration audio.',new)
        self._public_login()
        self.data['sessions'][0]['aps_native_course_version']='20261006-vtc-v1'
        response=self.client.get('/espace/public-token/elearning/academy-vtc-a')
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.data['sessions'][0]['aps_native_course_version'],'20261006-vtc-v1')

    def test_workshop_must_be_correct_before_completion(self):
        self._public_login()
        course=vtc.load_bundled_course('academy-vtc-a',VERSION)
        lesson,workshop=course['sections'][0]['activities']
        url='/espace/public-token/elearning/academy-vtc-a'
        config=self._player_config(self.client.get(url))
        self.assertEqual(self._api_post(config['completeUrl'],config).status_code,200)
        config=self._player_config(self.client.get(url+'?activity='+workshop['id']))
        answers=correct_answers(workshop['practice'])
        wrong=copy.deepcopy(answers)
        wrong['q1']=next(o['id'] for o in workshop['practice']['exercises'][0]['options'] if o['id']!=answers['q1'])
        self.assertEqual(self._api_post(config['completeUrl'],config,practice_answers=wrong).status_code,400)
        self.assertTrue(self._api_post(config['practiceUrl'],config,practice_answers=answers).json['correct'])
        saved=self._api_post(config['completeUrl'],config,practice_answers=answers)
        self.assertEqual(saved.status_code,200)
        self.assertIn(workshop['id'],saved.json['progress']['completed_activity_ids'])
        self.assertEqual(saved.json['progress']['active_seconds'],0)

    def test_vtc_composer_persists_pinned_courses_without_enabling_other_sessions(self):
        self._admin_login()
        response=self.client.get('/admin/sessions/session-aps/elearning')
        body=response.get_data(as_text=True)
        self.assertIn('id="vtcAddPath"',body)
        self.assertNotIn('id="aps62AddPath"',body)
        config=json.loads(re.search(r'<script id="nativePathConfig" type="application/json">(.*?)</script>',body,re.S)[1])
        modules=[{'course_id':m['id'],'course_version':VERSION,'required_minutes':vtc.load_bundled_course(m['id'],VERSION)['planned_minutes']} for m in vtc.curriculum_manifest()['modules']]
        response=self.client.post(config['saveUrl'],json={'revision':config['revision'],'title':'VTC complet','modules':modules},headers={'X-Elearning-CSRF':config['csrfToken']})
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(self.saved_data['sessions'][0]['aps_native_modules']),8)
        self.assertEqual(sum(m['required_minutes'] for m in response.json['modules']),3600)
        self.assertEqual(self.client.post(config['saveUrl'],json={'revision':config['revision'],'title':'Stale','modules':[]},headers={'X-Elearning-CSRF':config['csrfToken']}).status_code,409)

    def test_vtc_exam_and_final_gate_use_only_vtc_progress(self):
        self._public_login()
        module=self.client.get('/espace/public-token/elearning/exams/vtc-a')
        self.assertEqual(module.status_code,200)
        config=json.loads(re.search(r'<script type="application/json" id="apsExamConfig">(.*?)</script>',module.get_data(as_text=True),re.S)[1])
        exam=load_exam('vtc-a',VERSION)
        response=self.client.post(config['submitUrl'],json={'version':VERSION,'attempt_id':config['attemptId'],'answers':{q['id']:q['answer'] for q in exam['questions']}},headers={'X-Elearning-CSRF':config['csrfToken']})
        self.assertEqual(response.json['result']['score'],30)
        self.assertEqual(self.client.get('/espace/public-token/elearning/exams/module-01').status_code,403)
        self.assertEqual(self.client.get('/espace/public-token/elearning/exams/vtc-final').status_code,403)
        modules=[{'course_id':m['id'],'course_version':VERSION,'required_minutes':vtc.load_bundled_course(m['id'],VERSION)['planned_minutes']} for m in vtc.curriculum_manifest()['modules']]
        self.data['sessions'][0]['aps_native_modules']=modules
        self.assertEqual(self.client.get('/espace/public-token/elearning/exams/vtc-final').status_code,403)
        progress=[]
        for m in modules:
            c=vtc.load_bundled_course(m['course_id'],VERSION)
            progress.append({'course_id':c['id'],'course_version':VERSION,'completed_activity_ids':c['activity_order'],'active_seconds':m['required_minutes']*60,
              'video_progress':{aid:{vid:{'completed':True,'duration_seconds':duration,'watched_seconds':duration} for vid,duration in videos.items()} for aid,videos in course_videos(c).items()}})
        with patch('elearning_native.web.NativeElearningStore.learner_progress',return_value=progress):
            self.assertEqual(self.client.get('/espace/public-token/elearning/exams/vtc-final').status_code,200)
            path=self.client.get('/espace/public-token/elearning').get_data(as_text=True)
            self.assertIn('Commencer l’examen final',path)
            self.assertIn('Les sept matières théoriques VTC',path)
            modules[0]['section_ids']=[vtc.load_bundled_course('academy-vtc-a',VERSION)['sections'][0]['id']]
            self.assertEqual(self.client.get('/espace/public-token/elearning/exams/vtc-final').status_code,403)
