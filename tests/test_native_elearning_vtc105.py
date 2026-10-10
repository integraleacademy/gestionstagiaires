"""105-hour edition: coherent programme, authenticated media and resumable decisions."""
import copy
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from elearning_native import vtc
from elearning_native.practice import grade_practice, public_practice
from tests import test_native_elearning_web as web_tests
from tests.test_native_elearning_practice import correct_answers

VERSION = '20261006-vtc-v3-105h'

def activities(course):
    return [a for s in course['sections'] for a in s['activities']]

def script_config(response, name):
    return json.loads(re.search(r'<script[^>]*id="'+name+r'"[^>]*>(.*?)</script>', response.get_data(as_text=True), re.S)[1])

class Vtc105ContentTests(unittest.TestCase):
    def test_duration_content_and_every_answer_key(self):
        manifest=vtc.curriculum_manifest()
        self.assertIn(VERSION, manifest['exam_versions'])
        self.assertTrue(all(VERSION in [m['version'], *m.get('previous_versions', [])] for m in manifest['modules']))
        pinned = [vtc.load_bundled_course(m['id'], VERSION) for m in manifest['modules']]
        self.assertEqual([c['planned_minutes']//60 for c in pinned], [14,16,14,11,15,14,11,10])
        self.assertEqual(sum(c['planned_minutes'] for c in pinned),6300)
        self.assertEqual(manifest['duration_status'],'programme_previsionnel')
        refs=set(); exercises=0
        for module in manifest['modules']:
            course=vtc.load_bundled_course(module['id'],VERSION)
            self.assertEqual(len(activities(course)),42)
            self.assertEqual(sum(a['planned_minutes'] for a in activities(course)),course['planned_minutes'])
            self.assertEqual(sum(d['minutes'] for d in course['duration_breakdown']),course['planned_minutes'])
            for section in course['sections'][:12]:
                lesson, workshop, dossier=section['activities']
                refs.add(lesson['vtc']['ref'])
                self.assertTrue(lesson['vtc']['deepening'])
                self.assertEqual(dossier['practice']['mode'],'journey')
            for a in activities(course):
                self.assertNotIn('workbook',a)
                p=a.get('practice')
                if not p: continue
                expected=correct_answers(p)
                self.assertTrue(grade_practice(p,expected)['correct'],a['id'])
                public=json.dumps(public_practice(p))
                for secret in ['"answer"','"explanation"','"coaching"','"consequences"']:
                    self.assertNotIn(secret,public,a['id'])
                for e in p['exercises']:
                    exercises+=1
                    self.assertEqual(len({o['text'] for o in e['options']}),len(e['options']),e['id'])
                    if p.get('mode')=='journey':
                        self.assertTrue(grade_practice(p,{e['id']:expected[e['id']]},step=e['id'])['correct'])
                        self.assertIn(e['competency'].split('.')[0],set('ABCDEFGH'))
        self.assertEqual(len(refs),96)
        self.assertEqual(exercises,sum(vtc.load_bundled_course(m['id'],VERSION)['counts']['exercises'] for m in manifest['modules']))
        self.assertEqual(exercises,2360)  # This pinned edition remains immutable.

    def test_audio_and_partial_grading_boundaries(self):
        root=Path(vtc.__file__).parent/'vtc'
        listening=json.loads((root/'listening_manifest_v3.json').read_text())
        self.assertEqual(len(listening),48)
        course=vtc.load_bundled_course('academy-vtc-e',VERSION)
        mp3=[a for a in course['assets'] if a.endswith('.mp3')]
        # A corrected dialogue can retain its historical file in the asset registry.
        # The course still references exactly 48 distinct listening recordings.
        listening_sources={e['audio'] for section in course['sections']
                           for activity in section['activities']
                           for e in activity.get('practice',{}).get('exercises',[])
                           if e.get('audio')}
        self.assertEqual(len(listening_sources),48)
        self.assertTrue(listening_sources.issubset(set(mp3)))
        for name in mp3:
            self.assertGreater(vtc.bundled_asset(course['id'],VERSION,name).stat().st_size,10000)
        self.assertGreater(sum(a['duration_seconds'] for a in listening.values()),1800)
        p=course['sections'][0]['activities'][2]['practice']
        expected=correct_answers(p);first=p['exercises'][0]['id']
        with self.assertRaises(ValueError):grade_practice(p,{first:expected[first]})
        with self.assertRaises(ValueError):grade_practice(p,expected,step='unknown')
        with self.assertRaises(ValueError):grade_practice(p,expected,step=first)
        old=course['sections'][0]['activities'][1]['practice']
        with self.assertRaises(ValueError):grade_practice(old,correct_answers(old),step=old['exercises'][0]['id'])

class Vtc105WebTests(unittest.TestCase):
    tearDown=web_tests.NativeElearningWebTests.tearDown
    _admin_login=web_tests.NativeElearningWebTests._admin_login
    _public_login=web_tests.NativeElearningWebTests._public_login
    _player_config=staticmethod(web_tests.NativeElearningWebTests._player_config)
    _api_post=web_tests.NativeElearningWebTests._api_post

    def setUp(self):
        web_tests.NativeElearningWebTests.setUp(self)
        self.data['sessions'][0].update(training_type='VTC',name='VTC 105 h',aps_native_course_id='academy-vtc-a',aps_native_course_version=VERSION)

    def test_all_current_previews_render_without_writing_or_tracking(self):
        self._admin_login()
        with patch('elearning_native.web.NativeElearningStore',side_effect=AssertionError('Preview must not track')):
            for cid in vtc.curriculum_ids():
                for a in activities(vtc.load_bundled_course(cid,VERSION)):
                    response=self.client.get(f'/admin/elearning/courses/{cid}/preview',query_string={'activity':a['id'],'version':VERSION})
                    self.assertEqual(response.status_code,200,a['id'])
                    body=response.get_data(as_text=True)
                    self.assertNotIn('<textarea',body)
                    self.assertNotIn('"answer":',body)
                    if a.get('practice',{}).get('mode')=='journey':
                        config=script_config(response,'vtcJourneyConfig')
                        self.assertEqual(config['courseVersion'],VERSION)
                        self.assertEqual(len(config['practice']['exercises']),len(a['practice']['exercises']))
        self.assertIsNone(self.saved_data)

    def test_wrong_decisions_survive_resume_and_cannot_bypass_completion(self):
        self._public_login()
        url='/espace/public-token/elearning/academy-vtc-a'
        lesson, workshop, dossier=vtc.load_bundled_course('academy-vtc-a',VERSION)['sections'][0]['activities']
        # A later dossier cannot be graded ahead of required work.
        config=self._player_config(self.client.get(url))
        blocked=config['practiceUrl'].replace(lesson['id'],dossier['id'])
        self.assertEqual(self._api_post(blocked,config,practice_answers={}).status_code,409)
        self.assertEqual(self._api_post(config['completeUrl'],config).status_code,200)
        config=self._player_config(self.client.get(url,query_string={'activity':workshop['id']}))
        self.assertEqual(self._api_post(config['completeUrl'],config,practice_answers=correct_answers(workshop['practice'])).status_code,200)
        response=self.client.get(url,query_string={'activity':dossier['id']})
        config=self._player_config(response)
        p=dossier['practice']; answers=correct_answers(p);ex=p['exercises'][0];eid=ex['id']
        wrong=next(o['id'] for o in ex['options'] if o['id']!=answers[eid])
        for _ in range(2):
            response=self._api_post(config['practiceUrl'],config,practice_step=eid,practice_answers={eid:wrong})
            self.assertFalse(response.json['correct'])
            self.assertEqual(len(response.json['feedback']),1)
        page=self.client.get(url,query_string={'activity':dossier['id']})
        state=script_config(page,'vtcJourneyConfig')
        saved=state['saved'];diag=saved['practice_diagnostics'][eid]
        self.assertEqual(saved['practice_answers'][eid],wrong)
        self.assertFalse(diag['first_correct']);self.assertEqual(diag['attempts'],1)
        self.assertIn(ex['competency'],state['weakRefs'])
        self.assertEqual(self._api_post(config['completeUrl'],config,practice_step=eid,practice_answers={eid:answers[eid]}).status_code,400)
        self.assertEqual(self._api_post(config['practiceUrl'],config,practice_step=eid,practice_answers={eid:answers[eid]}).status_code,200)
        self.assertTrue(self._api_post(config['practiceUrl'],config,practice_answers=answers).json['correct'])
        completed=self._api_post(config['completeUrl'],config,practice_answers=answers)
        self.assertEqual(completed.status_code,200)
        progress=completed.json['progress']
        self.assertIn(dossier['id'],progress['completed_activity_ids'])
        self.assertEqual(progress['active_seconds'],0)
        saved=copy.deepcopy(progress['answers'][dossier['id']])
        self.assertFalse(saved['practice_diagnostics'][eid]['first_correct'])
        self.assertEqual(saved['practice_diagnostics'][eid]['attempts'],2)
        self.assertFalse(saved['practice_draft'])
        self._api_post(config['practiceUrl'],config,practice_step=eid,practice_answers={eid:wrong})
        again=script_config(self.client.get(url,query_string={'activity':dossier['id']}),'vtcJourneyConfig')['saved']
        self.assertEqual(again,saved)

    def test_preview_audio_stays_signed_and_preview_grading_never_saves(self):
        self._admin_login()
        course=vtc.load_bundled_course('academy-vtc-e',VERSION)
        dossier=course['sections'][0]['activities'][2]
        response=self.client.get('/admin/elearning/courses/academy-vtc-e/preview',query_string={'activity':dossier['id'],'version':VERSION})
        config=script_config(response,'nativePreviewConfig')
        journey=script_config(response,'vtcJourneyConfig')
        audio=next(e['audio'] for e in journey['practice']['exercises'] if e.get('audio'))
        self.assertTrue(audio.startswith('/elearning/assets/academy-vtc-e/'))
        self.assertIn('access=',audio)
        self.assertEqual(self.client.get(audio,headers={'Range':'bytes=0-99'}).status_code,206)
        first=dossier['practice']['exercises'][0]
        with patch('elearning_native.web.NativeElearningStore',side_effect=AssertionError('Preview must not save')):
            payload={'practice_step':first['id'],'practice_answers':{first['id']:first['answer']}}
            self.assertEqual(self.client.post(config['answerUrl'],json=payload).status_code,403)
            result=self.client.post(config['answerUrl'],json=payload,headers={'X-Elearning-CSRF':config['csrfToken']})
            self.assertTrue(result.json['correct'])
        with self.client.session_transaction() as session:session.clear()
        self.assertIn(self.client.get(audio).status_code,[302,401,403])
