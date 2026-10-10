"""Publication gates for real APS long videos; no generated-media substitutes.

Before publication, historical/course checks still run and any completed v6
media are inspected. The complete-catalogue gate skips until v8 is published.
Set APS62_VERIFY_FULL_DECODE=1 for the optional full audio/video decode pass.
"""
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import unittest

from elearning_native.academy import ROOT, curriculum_manifest, load_bundled_course


PREVIOUS_VERSION = '20261007-aps62-v7'
LONG_VERSION = '20261007-aps62-v8'
# Courses and exams from the deployed v7 commit 7ab6d17. Hash includes paths.
V7_CONTENT_SHA256 = 'a147cefafa322b87bb9158e58cb84afe12ec7585eaff22540763559f54bcb42d'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def seconds(timestamp):
    hours, minutes, tail = timestamp.split(':')
    return int(hours) * 3600 + int(minutes) * 60 + float(tail)


def video_blocks(course):
    return [(section['id'], block['video'])
            for section in course['sections']
            for activity in section['activities']
            for block in activity.get('blocks', []) if block.get('video')]


class LongVideoContinuityTests(unittest.TestCase):
    def test_v7_courses_and_exams_are_byte_for_byte_preserved(self):
        files = (sorted((ROOT/'courses').glob(f'*/{PREVIOUS_VERSION}.json'))
                 + sorted((ROOT/'exams'/PREVIOUS_VERSION).glob('*.json')))
        self.assertEqual(len(files), 31)
        digest = hashlib.sha256()
        for path in files:
            digest.update(path.relative_to(ROOT).as_posix().encode() + b'\0'
                          + path.read_bytes() + b'\0')
        self.assertEqual(digest.hexdigest(), V7_CONTENT_SHA256)
        for module in curriculum_manifest()['modules']:
            old = load_bundled_course(module['id'], PREVIOUS_VERSION)
            self.assertIsNotNone(old, module['id'])
            self.assertTrue(all(v['src'].startswith('media/aps62/v5/')
                                for _, v in video_blocks(old)))

    def test_publication_preserves_activity_ids_and_the_3720_minute_budget(self):
        manifest = curriculum_manifest()
        self.assertIn(manifest['version'], (PREVIOUS_VERSION, LONG_VERSION, '20261007-aps62-v9', '20261010-aps62-v10'))
        total = 0
        for module in manifest['modules']:
            with self.subTest(module=module['id']):
                current = load_bundled_course(module['id'])
                old = load_bundled_course(module['id'], PREVIOUS_VERSION)
                self.assertEqual(current['activity_order'], old['activity_order'])
                self.assertEqual(current['planned_minutes'], old['planned_minutes'])
                self.assertEqual(current['required_minutes'], old['required_minutes'])
                for section, previous in zip(current['sections'], old['sections']):
                    self.assertEqual(section['id'], previous['id'])
                    durations = [a['planned_minutes'] for a in section['activities']]
                    self.assertTrue(all(minutes > 0 for minutes in durations))
                    self.assertEqual(sum(durations), sum(a['planned_minutes']
                                     for a in previous['activities']))
                    total += sum(durations)
        self.assertEqual(total, 3720)

    def test_published_v8_requires_all_62_long_videos_and_exact_course_references(self):
        manifest = curriculum_manifest()
        published = manifest['visual_learning']['long_videos_published']
        if not published:
            self.assertEqual(manifest['version'], PREVIOUS_VERSION,
                             'The long-video edition cannot publish a partial render.')
            self.skipTest('Long-video edition has not been published; no completion is claimed.')
        self.assertIn(manifest['version'], (LONG_VERSION, '20261007-aps62-v9', '20261010-aps62-v10'))
        revision = {'20261007-aps62-v8':'v6', '20261007-aps62-v9':'v7', '20261010-aps62-v10':'v8'}[manifest['version']]
        videos = read_json(ROOT/f'video_manifest_{revision}.json')
        scripts = read_json(ROOT/f'video_scripts_{revision}.json')
        self.assertEqual(len(videos), 62)
        self.assertEqual(set(videos), set(scripts))
        observed = []
        for module in manifest['modules']:
            self.assertEqual(module['version'], manifest['version'])
            self.assertIn(PREVIOUS_VERSION, module['previous_versions'])
            course = load_bundled_course(module['id'])
            for sid, video in video_blocks(course):
                observed.append(sid)
                for key in ('src', 'poster', 'captions', 'duration_seconds',
                            'narration_seconds', 'transcript', 'voice', 'rate'):
                    self.assertEqual(video[key], videos[sid][key], (sid, key))
                self.assertTrue(video['required'], sid)
                for key in ('src', 'poster', 'captions'):
                    self.assertIn(video[key], course['assets'], (sid, key))
        self.assertEqual(len(observed), 62)
        self.assertEqual(set(observed), set(videos))


class LongVideoMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT/'video_manifest_v6.json'
        if not path.exists():
            raise unittest.SkipTest('No long-video media have been rendered yet.')
        cls.videos = read_json(path)
        if not cls.videos:
            raise unittest.SkipTest('No long-video media have completed rendering yet.')
        cls.scripts = read_json(ROOT/'video_scripts_v6.json')

    def test_completed_renders_have_real_audio_video_and_faithful_punctuated_captions(self):
        self.assertTrue(set(self.videos).issubset(self.scripts))
        ffprobe = shutil.which('ffprobe')
        self.assertIsNotNone(ffprobe, 'ffprobe is required to verify actual media durations.')
        for sid, video in self.videos.items():
            with self.subTest(dossier=sid):
                self.assertEqual(video['transcript'], self.scripts[sid]['transcript'])
                self.assertEqual((video['voice'], video['rate']), ('fr-FR-HenriNeural', '-2%'))
                self.assertTrue(video['course_only'])
                self.assertTrue(video['animated'])
                self.assertTrue(video['burned_captions'])
                for key in ('duration_seconds', 'narration_seconds'):
                    self.assertTrue(math.isfinite(video[key]))
                    self.assertGreaterEqual(video[key], 300)
                for key, extension in (('src', 'mp4'), ('poster', 'jpg'), ('captions', 'vtt')):
                    self.assertEqual(video[key], f'media/aps62/v6/{sid}.{extension}')
                    asset = ROOT/'assets'/video[key]
                    self.assertTrue(asset.is_file(), str(asset))
                    self.assertGreater(asset.stat().st_size, 0, str(asset))
                media = ROOT/'assets'/video['src']
                result = subprocess.run([ffprobe, '-v', 'error', '-show_streams',
                    '-show_format', '-of', 'json', str(media)], capture_output=True,
                    text=True, check=True, timeout=30)
                info = json.loads(result.stdout)
                self.assertAlmostEqual(float(info['format']['duration']),
                                       video['duration_seconds'], delta=.5)
                streams = {stream['codec_type']: stream for stream in info['streams']}
                self.assertTrue({'video', 'audio'}.issubset(streams))
                for stream_type in ('video', 'audio'):
                    actual = float(streams[stream_type]['duration'])
                    self.assertGreaterEqual(actual, 300)
                    self.assertAlmostEqual(actual, video['duration_seconds'], delta=.75)
                self.assertAlmostEqual(float(streams['audio']['duration']),
                                       video['narration_seconds'], delta=.75)
                self._check_captions_and_chapters(sid, video)

    def _check_captions_and_chapters(self, sid, video):
        caption = (ROOT/'assets'/video['captions']).read_text(encoding='utf-8')
        self.assertTrue(caption.startswith('WEBVTT\n\n'), sid)
        reconstructed, previous_end = [], 0
        for cue in caption.split('\n\n')[1:]:
            if not cue.strip():
                continue
            timing, *lines = cue.strip().splitlines()
            match = re.fullmatch(r'(\d{2}:\d{2}:\d{2}\.\d{3}) --> '
                                 r'(\d{2}:\d{2}:\d{2}\.\d{3})', timing)
            self.assertIsNotNone(match, (sid, timing))
            start, end = map(seconds, match.groups())
            self.assertGreaterEqual(start, previous_end, (sid, timing))
            self.assertGreater(end, start, (sid, timing))
            self.assertLessEqual(end, video['duration_seconds'], (sid, timing))
            self.assertTrue(1 <= len(lines) <= 2, (sid, lines))
            self.assertTrue(all(len(line) <= 44 for line in lines), (sid, lines))
            reconstructed.extend(lines)
            previous_end = end
        self.assertEqual(re.sub(r'\s+', '', ''.join(reconstructed)),
                         re.sub(r'\s+', '', video['transcript']), sid)
        self.assertGreaterEqual(previous_end, video['narration_seconds'] - 1.2,
                                'The narration must not be lengthened with trailing silence.')
        chapters = video['chapters']
        self.assertEqual(len(chapters), len(self.scripts[sid]['scenes']))
        self.assertEqual(chapters[0]['start_seconds'], 0)
        for chapter, scene in zip(chapters, self.scripts[sid]['scenes']):
            self.assertEqual(chapter['title'], scene['title'])
            self.assertGreater(chapter['end_seconds'], chapter['start_seconds'])
        for left, right in zip(chapters, chapters[1:]):
            self.assertEqual(left['end_seconds'], right['start_seconds'])
        self.assertAlmostEqual(chapters[-1]['end_seconds'], video['duration_seconds'], delta=.5)

    @unittest.skipUnless(os.environ.get('APS62_VERIFY_FULL_DECODE') == '1',
                         'Enable APS62_VERIFY_FULL_DECODE=1 for the full media decode pass.')
    def test_all_completed_media_decode_without_audio_or_video_errors(self):
        ffmpeg = shutil.which('ffmpeg')
        self.assertIsNotNone(ffmpeg, 'ffmpeg is required for the full decode pass.')
        for sid, video in self.videos.items():
            with self.subTest(dossier=sid):
                subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-xerror',
                    '-i', str(ROOT/'assets'/video['src']), '-map', '0:v:0', '-map',
                    '0:a:0', '-f', 'null', '-'], capture_output=True, text=True,
                    check=True, timeout=240)


if __name__ == '__main__':
    unittest.main()
