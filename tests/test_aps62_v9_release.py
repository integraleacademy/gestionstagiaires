"""Release evidence: real media, complete new edition, unchanged learner history."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from elearning_native.academy import ROOT, load_bundled_course, curriculum_manifest
from scripts.aps62_v9.field_videos import courses

VERSION = '20261007-aps62-v9'
PREVIOUS = '20261007-aps62-v8'
V8_HASH = '4d8f5085a25a822010af6ac278533b6eefa81199345fe3bf4822d3826a7b7f81'


def read(path):
    return json.loads(path.read_text())


def seconds(t):
    h, m, s = t.split(':')
    return int(h)*3600+int(m)*60+float(s)


class ImprovedReleaseTests(unittest.TestCase):
    def test_v8_courses_exams_and_progress_identifiers_remain_unchanged(self):
        files = sorted((ROOT/'courses').glob(f'*/{PREVIOUS}.json'))+sorted((ROOT/'exams'/PREVIOUS).glob('*.json'))
        self.assertEqual(len(files), 31)
        h = hashlib.sha256()
        for p in files:
            h.update(p.relative_to(ROOT).as_posix().encode()+b'\0'+p.read_bytes()+b'\0')
        self.assertEqual(h.hexdigest(), V8_HASH)

    def test_complete_published_courses_preserve_guided_work_and_budgets(self):
        manifest = curriculum_manifest()
        if manifest['version'] not in (VERSION, '20261010-aps62-v10', '20261010-aps62-v11'):
            self.assertEqual(manifest['version'], PREVIOUS)
            self.skipTest('New edition is not yet published')
        videos = read(ROOT/'video_manifest_v7.json')
        self.assertEqual(len(videos), 62)
        self.assertEqual(set(videos), set(courses()))
        seen, minutes, practices, journals = [], 0, 0, 0
        for module in manifest['modules']:
            self.assertIn(VERSION, [module['version'], *module.get('previous_versions', [])])
            current = load_bundled_course(module['id'], VERSION)
            previous = load_bundled_course(module['id'], PREVIOUS)
            self.assertEqual(current['interaction_revision'], VERSION)
            self.assertEqual(current['activity_order'], previous['activity_order'])
            self.assertEqual(current['planned_minutes'], previous['planned_minutes'])
            self.assertEqual(current['required_minutes'], previous['required_minutes'])
            for section, old in zip(current['sections'], previous['sections']):
                self.assertEqual(section['id'], old['id'])
                total = sum(a['planned_minutes'] for a in section['activities'])
                self.assertEqual(total, sum(a['planned_minutes'] for a in old['activities']))
                minutes += total
                for activity in section['activities']:
                    self.assertGreater(activity['planned_minutes'], 0)
                    p = activity.get('practice')
                    if p:
                        practices += 1
                        journals += bool(p.get('journal'))
                        self.assertEqual(p['mode'], 'guided')
                        self.assertEqual(p['revision'], VERSION)
                    for block in activity.get('blocks', []):
                        v = block.get('video')
                        if v:
                            seen.append(section['id'])
                            self.assertTrue(v['required'])
                            for key in ('src','poster','captions','duration_seconds','transcript','chapters'):
                                self.assertEqual(v[key], videos[section['id']][key])
                            for key in ('src','poster','captions'):
                                self.assertIn(v[key], current['assets'])
        self.assertEqual((len(seen), len(set(seen)), practices, journals, minutes), (62,62,142,4,3720))

    def test_demonstrations_are_case_specific_and_show_decision_changes(self):
        expected = {'field_observation','field_documents','field_dialogue','field_consequence','field_evolution'}
        rows = courses()
        documents, facts = set(), set()
        for sid, row in rows.items():
            scenes = [s for s in row['scenes'] if s['kind'].startswith('field_')]
            self.assertEqual({s['kind'] for s in scenes}, expected)
            case = row['field_case']
            for field in ('fact','verified_document','evolution','next_decision'):
                self.assertIn(case[field], row['transcript'], (sid, field))
            documents.add(case['verified_document'])
            facts.add(case['fact'])
        self.assertEqual((len(documents), len(facts)), (62,62))


class RenderedVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = ROOT/'video_manifest_v7.json'
        if not p.exists():
            raise unittest.SkipTest('No completed v7 media yet')
        cls.videos = read(p)
        cls.scripts = courses()

    def test_real_audio_video_captions_chapters_and_all_narrated_words(self):
        self.assertIsNotNone(shutil.which('ffprobe'))
        if curriculum_manifest()['version'] == VERSION:
            self.assertEqual(set(self.videos), set(self.scripts))
        for sid, v in self.videos.items():
            with self.subTest(dossier=sid):
                self.assertEqual(v['transcript'], self.scripts[sid]['transcript'])
                self.assertTrue(v['field_demonstrations'])
                for key, ext in (('src','mp4'),('poster','jpg'),('captions','vtt')):
                    self.assertEqual(v[key], f'media/aps62/v7/{sid}.{ext}')
                    self.assertGreater((ROOT/'assets'/v[key]).stat().st_size, 0)
                info = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams',
                    '-show_format','-of','json',str(ROOT/'assets'/v['src'])], timeout=30))
                streams = {s['codec_type']: s for s in info['streams']}
                self.assertTrue({'audio','video'}.issubset(streams))
                for kind in ('audio','video'):
                    actual = float(streams[kind]['duration'])
                    self.assertGreaterEqual(actual, 300)
                    self.assertAlmostEqual(actual, v['duration_seconds'], delta=.75)
                words, last = [], 0
                text = (ROOT/'assets'/v['captions']).read_text()
                self.assertTrue(text.startswith('WEBVTT\n\n'))
                for cue in text.split('\n\n')[1:]:
                    timing, *lines = cue.strip().splitlines()
                    start, end = map(seconds, timing.split(' --> '))
                    self.assertGreaterEqual(start, last)
                    self.assertGreater(end, start)
                    self.assertLessEqual(end, v['duration_seconds'])
                    self.assertTrue(1 <= len(lines) <= 2)
                    self.assertTrue(all(len(line)<=44 for line in lines))
                    words.extend(lines)
                    last = end
                self.assertEqual(re.sub(r'\s+','',''.join(words)), re.sub(r'\s+','',v['transcript']))
                self.assertGreaterEqual(last, v['narration_seconds']-1.2)
                chapters = v['chapters']
                self.assertEqual(len(chapters), len(self.scripts[sid]['scenes']))
                self.assertEqual(chapters[0]['start_seconds'], 0)
                for a,b in zip(chapters,chapters[1:]):
                    self.assertGreater(a['end_seconds'], a['start_seconds'])
                    self.assertEqual(a['end_seconds'], b['start_seconds'])
                self.assertAlmostEqual(chapters[-1]['end_seconds'], v['duration_seconds'], delta=.5)

    @unittest.skipUnless(os.environ.get('APS62_VERIFY_FULL_DECODE') == '1', 'Full decode is an explicit release gate')
    def test_complete_audio_and_video_decode(self):
        for sid,v in self.videos.items():
            with self.subTest(dossier=sid):
                subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-i',str(ROOT/'assets'/v['src']),
                    '-map','0:v:0','-map','0:a:0','-f','null','-'],check=True,capture_output=True,timeout=300)


if __name__ == '__main__':
    unittest.main()
