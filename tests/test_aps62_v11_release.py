"""Release gates for calmer videos, intact content and immutable learner editions."""
import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import unittest

from elearning_native.academy import ROOT, curriculum_manifest, load_bundled_course
from scripts.aps62_v10.video_content import courses

VERSION = '20261010-aps62-v11'
PREVIOUS = '20261010-aps62-v10'
V10_HASH = 'e1d9300554e4bd2f6be8bcc876e6880d30af46fd310a27194d1be10addb38647'


def read(path):
    return json.loads(path.read_text())


def seconds(value):
    h, m, s = value.split(':')
    return int(h)*3600 + int(m)*60 + float(s)


def learning_content(course):
    """Exclude only deliberate edition, video timing and budget presentation fields."""
    value = copy.deepcopy(course)
    for key in ('version', 'interaction_revision', 'assets'):
        value.pop(key, None)
    for section in value['sections']:
        section['activities'][0]['academy'].pop('pacing', None)
        for activity in section['activities']:
            activity.pop('planned_minutes', None)
            if activity.get('practice'):
                activity['practice'].pop('revision', None)
            for block in activity.get('blocks', []):
                if block.get('video'):
                    block['video'] = {'required': block['video'].get('required'),
                                      'transcript': block['video']['transcript']}
    return value


class PacedEditionTests(unittest.TestCase):
    def test_assigned_v10_courses_and_exams_are_preserved_byte_for_byte(self):
        paths = sorted((ROOT/'courses').glob('*/' + PREVIOUS + '.json')) + sorted((ROOT/'exams'/PREVIOUS).glob('*.json'))
        self.assertEqual(len(paths), 31)
        digest = hashlib.sha256()
        for path in paths:
            digest.update(path.relative_to(ROOT).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
        self.assertEqual(digest.hexdigest(), V10_HASH)

    def test_catalogue_is_complete_and_no_learning_content_is_lost(self):
        manifest = curriculum_manifest()
        if manifest['version'] != VERSION:
            self.assertEqual(manifest['version'], PREVIOUS)
            self.skipTest('All paced media are required before advancing the catalogue')
        videos = read(ROOT/'video_manifest_v9.json')
        self.assertEqual(set(videos), set(courses()))
        self.assertEqual(read(ROOT/'video_scripts_v9.json'), courses())
        self.assertEqual(manifest['visual_learning']['paced_long_videos'], 62)
        self.assertEqual(manifest['production_count'], 10)
        self.assertEqual(manifest['interactive_workshop_count'], 132)
        seen = set()
        minutes = activities = 0
        for module in manifest['modules']:
            self.assertIn(PREVIOUS, module['previous_versions'])
            current = load_bundled_course(module['id'])
            previous = load_bundled_course(module['id'], PREVIOUS)
            self.assertEqual(current['version'], VERSION)
            self.assertEqual(learning_content(current), learning_content(previous))
            for section, old in zip(current['sections'], previous['sections']):
                duration = sum(a['planned_minutes'] for a in section['activities'])
                self.assertEqual(duration, sum(a['planned_minutes'] for a in old['activities']))
                minutes += duration
                for activity in section['activities']:
                    activities += 1
                    self.assertGreater(activity['planned_minutes'], 0)
                    for block in activity.get('blocks', []):
                        video = block.get('video')
                        if video:
                            seen.add(section['id'])
                            self.assertTrue(video['required'])
                            for key, expected in videos[section['id']].items():
                                self.assertEqual(video[key], expected)
                            self.assertGreaterEqual(activity['planned_minutes'], math.ceil(video['duration_seconds']/60))
            for asset in current['assets']:
                self.assertTrue((ROOT/'assets'/asset).is_file(), asset)
        self.assertEqual((len(seen), activities, minutes), (62, 452, 3720))
        for path in (ROOT/'exams'/PREVIOUS).glob('*.json'):
            previous, current = read(path), read(ROOT/'exams'/VERSION/path.name)
            previous['version'] = VERSION
            self.assertEqual(current, previous)


class PacedMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT/'video_manifest_v9.json'
        if not path.exists():
            raise unittest.SkipTest('No paced v9 media rendered yet')
        cls.videos = read(path)
        cls.scripts = courses()

    def test_new_media_are_real_complete_and_keep_every_spoken_word(self):
        self.assertIsNotNone(shutil.which('ffprobe'))
        if curriculum_manifest()['version'] == VERSION:
            self.assertEqual(set(self.videos), set(self.scripts))
        for sid, video in self.videos.items():
            with self.subTest(video=sid):
                self.assertEqual(video['transcript'], self.scripts[sid]['transcript'])
                self.assertEqual(video['render_revision'], 9)
                self.assertTrue(video['pacing'])
                self.assertGreaterEqual(video['narration_seconds'], 300)
                self.assertTrue(video['field_demonstrations'])
                for key, ext in (('src','mp4'), ('poster','jpg'), ('captions','vtt')):
                    self.assertEqual(video[key], f'media/aps62/v9/{sid}.{ext}')
                    self.assertGreater((ROOT/'assets'/video[key]).stat().st_size, 0)
                media = ROOT/'assets'/video['src']
                info = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(media)], timeout=30))
                streams = {s['codec_type']:s for s in info['streams']}
                self.assertTrue({'audio','video'}.issubset(streams))
                for kind in ('audio','video'):
                    self.assertAlmostEqual(float(streams[kind]['duration']), video['duration_seconds'], delta=.75)
                words = []
                caption_count = fast_caption_count = 0
                last_end = 0
                for cue in (ROOT/'assets'/video['captions']).read_text().split('\n\n')[1:]:
                    if not cue.strip():
                        continue
                    timing, *lines = cue.strip().splitlines()
                    start, end = map(seconds, timing.split(' --> '))
                    self.assertGreaterEqual(start, last_end)
                    self.assertGreater(end, start)
                    self.assertLessEqual(end, video['duration_seconds'])
                    self.assertTrue(1 <= len(lines) <= 2)
                    self.assertTrue(all(len(line) <= 44 for line in lines))
                    self.assertLessEqual(len(' '.join(lines))/(end-start), 22.05, (sid,timing,lines))
                    caption_count += 1
                    fast_caption_count += len(' '.join(lines))/(end-start) > 20
                    words.extend(lines)
                    last_end = end
                self.assertLessEqual(fast_caption_count/caption_count, .05)
                self.assertEqual(re.sub(r'\s+', '', ''.join(words)), re.sub(r'\s+', '', video['transcript']))
                self.assertEqual(len(video['chapters']), len(self.scripts[sid]['scenes']))
                chapters = video['chapters']
                self.assertEqual(chapters[0]['start_seconds'], 0)
                for chapter, scene in zip(chapters, self.scripts[sid]['scenes']):
                    self.assertEqual(chapter['title'], scene['title'])
                    self.assertLess(chapter['start_seconds'], chapter['end_seconds'])
                for first, second in zip(chapters, chapters[1:]):
                    self.assertAlmostEqual(first['end_seconds'], second['start_seconds'], delta=.05)
                pacing = video['pacing']
                self.assertEqual(pacing['tempo'], .87)
                self.assertTrue(pacing['pitch_preserved'])
                self.assertTrue(pacing['all_words_preserved'])
                self.assertTrue(pacing['word_aligned_visuals'])
                self.assertGreater(pacing['added_pause_seconds'], 0)
                self.assertGreater(video['narration_seconds'], pacing['source_narration_seconds']/.87)
                self.assertEqual(len(pacing['scenes']), len(chapters))
                self.assertEqual(pacing['captions']['count'], caption_count)
                self.assertEqual(pacing['captions']['over_20_count'], fast_caption_count)
                self.assertEqual(pacing['captions']['over_22_count'], 0)
                for scene in pacing['scenes']:
                    if scene['kind'] == 'glossary':
                        self.assertGreaterEqual(scene['end_seconds'] - scene['reveal_seconds']['term_2'], 7.999)
                    if scene['kind'] == 'field_dialogue':
                        turns = [scene['reveal_seconds']['turn_' + str(i)] for i in range(3)]
                        self.assertEqual(turns, sorted(turns))
                        self.assertTrue(all(scene['start_seconds'] <= v < scene['end_seconds'] for v in turns))
                for pause in pacing['pauses']:
                    self.assertGreater(pause['added_seconds'], 0)
                    actual_gap = pause['existing_gap_seconds'] + pause['added_seconds']
                    if 'chapter_transition' in pause['reasons']:
                        self.assertGreaterEqual(actual_gap, 2.499)
                    if 'before_correction' in pause['reasons']:
                        self.assertGreaterEqual(actual_gap, 3.999)
                # Decode actual audio, so metadata alone cannot certify pauses.
                measured = subprocess.run(['ffmpeg','-nostdin','-hide_banner','-i',str(media),
                    '-vn','-af','silencedetect=noise=-35dB:d=0.25','-f','null','-'],
                    capture_output=True, text=True, check=True, timeout=60).stderr
                silences = [(float(end)-float(length), float(end)) for end,length in
                    re.findall(r'silence_end: ([0-9.]+) \| silence_duration: ([0-9.]+)', measured)]
                for pause in pacing['pauses']:
                    middle = (pause['start_seconds'] + pause['end_seconds'])/2
                    silence = next(((a,b) for a,b in silences if a <= middle <= b), None)
                    self.assertIsNotNone(silence, (sid, 'Missing actual silence', pause))
                    self.assertGreaterEqual(silence[1]-silence[0], pause['target_gap_seconds']-.2,
                                            (sid, 'Actual pause shorter than target', pause, silence))
                if os.environ.get('APS62_VERIFY_V11_FULL_DECODE') == '1':
                    subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-threads','1','-i',str(media),'-f','null','-'], capture_output=True, check=True, timeout=240)


if __name__ == '__main__':
    unittest.main()
