"""Acceptance checks for actual media, caption fidelity and versioned access."""
import json
import re
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from elearning_native import vtc
from tests import test_native_elearning_web as web_tests

VERSION='20261007-vtc-v4-visuals'
BASE='20261006-vtc-v3-105h'
ROOT=Path(__file__).resolve().parents[1]/'elearning_native/vtc'


class VisualMediaTests(unittest.TestCase):
    def test_real_video_durations_audio_and_lossless_caption_text(self):
        videos=json.loads((ROOT/'video_manifest_v4.json').read_text())
        self.assertEqual(set(videos),set('ABCDEFGH'))
        for letter, video in videos.items():
            with self.subTest(module=letter):
                probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(ROOT/'assets'/video['src'])]))
                measured=float(probe['format']['duration'])
                self.assertGreaterEqual(measured,300)
                self.assertAlmostEqual(measured,video['duration_seconds'],delta=.2)
                self.assertAlmostEqual(measured,video['narration_seconds'],delta=.4)
                self.assertEqual({s['codec_type'] for s in probe['streams']},{'audio','video'})
                self.assertEqual(video['voice'],'fr-FR-HenriNeural')
                self.assertEqual(len(video['chapters']),24)
                self.assertNotRegex(video['transcript'],r'(?i)(faites une pause|mettez.{0,10}pause)')
                vtt=(ROOT/'assets'/video['captions']).read_text()
                blocks=vtt.strip().split('\n\n')[1:]
                texts=[];previous=0
                def seconds(t):
                    h,m,s=t.split(':');return int(h)*3600+int(m)*60+float(s)
                for block in blocks:
                    timing,*lines=block.splitlines();start,end=map(seconds,timing.split(' --> '))
                    self.assertGreater(end,start)
                    self.assertGreaterEqual(start,previous-.001)
                    self.assertLessEqual(end,measured+.05)
                    self.assertLessEqual(len(lines),2)
                    self.assertTrue(all(len(line)<=44 for line in lines))
                    previous=end;texts.extend(lines)
                # Includes every comma, apostrophe, period and question mark.
                self.assertEqual(re.sub(r'\s+','',''.join(texts)),re.sub(r'\s+','',video['transcript']))

    def test_visuals_and_105_hour_plan_are_complete_without_migrating_old_editions(self):
        manifest=vtc.curriculum_manifest()
        self.assertEqual(manifest['version'],VERSION)
        refs=set();table_count=0
        for m in manifest['modules']:
            current=vtc.load_bundled_course(m['id'],VERSION)
            old=vtc.load_bundled_course(m['id'],BASE)
            self.assertEqual(current['activity_order'],old['activity_order'])
            self.assertEqual(sum(a['planned_minutes'] for s in current['sections'] for a in s['activities']),m['planned_minutes'])
            for s in current['sections'][:12]:
                lesson=s['activities'][0]['vtc'];refs.add(lesson['ref'])
                self.assertEqual(len(lesson['visual_steps']),3)
                self.assertTrue(all(x['title'] and x['text'] for x in lesson['visual_steps']))
                if lesson.get('visual_table'):
                    table_count+=1;t=lesson['visual_table']
                    self.assertTrue(all(len(row)==len(t['headers']) for row in t['rows']))
            for path in current['assets']:
                self.assertIsNotNone(vtc.bundled_asset(m['id'],VERSION,path),path)
            newvideo=current['sections'][-1]['activities'][0]['blocks'][0]['video']
            oldvideo=old['sections'][-1]['activities'][0]['blocks'][0]['video']
            self.assertGreaterEqual(newvideo['duration_seconds'],300)
            self.assertLess(oldvideo['duration_seconds'],100)
            self.assertIsNotNone(vtc.bundled_asset(m['id'],BASE,oldvideo['src']))
            self.assertIsNotNone(vtc.load_exam(m['mock_exam_id'],BASE))
        self.assertEqual(len(refs),96);self.assertEqual(table_count,32)
        self.assertEqual(sum(m['planned_minutes'] for m in manifest['modules']),6300)


class VisualWebTests(unittest.TestCase):
    setUp=web_tests.NativeElearningWebTests.setUp
    tearDown=web_tests.NativeElearningWebTests.tearDown
    _admin_login=web_tests.NativeElearningWebTests._admin_login

    def test_every_visual_lesson_and_new_video_renders_in_preview_without_tracking(self):
        self._admin_login()
        with patch('elearning_native.web.NativeElearningStore',side_effect=AssertionError('Preview must not track')):
            for cid in vtc.curriculum_ids():
                course=vtc.load_bundled_course(cid,VERSION)
                activities=[s['activities'][0] for s in course['sections'][:12]]+[course['sections'][-1]['activities'][0]]
                for a in activities:
                    response=self.client.get(f'/admin/elearning/courses/{cid}/preview',query_string={'version':VERSION,'activity':a['id']})
                    self.assertEqual(response.status_code,200)
                    page=response.get_data(as_text=True)
                    self.assertNotIn('<textarea',page)
                    if a['vtc']['kind']=='lesson':
                        self.assertIn('vtc-method-flow',page)
                        self.assertEqual(page.count('class="vtc-method-symbol"'),3)
                    else:
                        self.assertIn('/media/vtc/v4/lesson-',page)
                        self.assertIn('leçon continue',page)
                        self.assertNotIn('Faites une pause',page)
        self.assertIsNone(self.saved_data)


if __name__=='__main__':unittest.main()
