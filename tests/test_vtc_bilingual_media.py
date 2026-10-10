"""Language and caption checks for the published bilingual lesson, without TTS."""
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1] / 'elearning_native/vtc'


def read(name):
    return json.loads((ROOT / name).read_text())


def compact(text):
    return re.sub(r'\s+', '', text)


def seconds(value):
    hours, minutes, remainder = value.split(':')
    return int(hours) * 3600 + int(minutes) * 60 + float(remainder)


class BilingualMediaTests(unittest.TestCase):
    def setUp(self):
        self.media = read('video_english_bilingual_v7.json')

    def test_all_english_examples_use_the_english_voice(self):
        original = read('video_scripts_v4.json')['E']['scenes']
        scenes = self.media['language_segments']
        self.assertEqual(len(scenes), len(original))
        self.assertEqual(self.media['voice']['en'], 'en-GB-RyanNeural')
        # Bare grammar words must also switch voice, not just quoted sentences.
        bare = {1: ['be', 'I am, you are, he is, she is, we are, they are'],
                3: ['do', 'does'], 4: ['morning/evening', 'a.m./p.m.', 'at', 'on'],
                7: ['please'], 11: ['would you like', 'be'],
                13: ['faster', 'shorter', 'more comfortable', 'than'],
                17: ['will', 'I’ll']}
        for index, parts in enumerate(scenes):
            with self.subTest(scene=index):
                text = ''.join(p['text'] for p in parts)
                english = [p['lang'] == 'en' for p in parts for _ in p['text']]
                self.assertTrue(all(p['lang'] in ('fr', 'en') for p in parts))
                for quote in re.finditer('«[^»]+»', text):
                    self.assertTrue(all(english[quote.start():quote.end()]))
                if index % 2 == 0:
                    self.assertTrue(all(english[:text.index('. ') + 1]))
                for phrase in bare.get(index, []):
                    matches = list(re.finditer(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', text))
                    self.assertTrue(matches, phrase)
                    for match in matches:
                        self.assertTrue(all(english[match.start():match.end()]), phrase)
                if index not in (1, 4):
                    self.assertEqual(text, original[index]['text'])
                # The compacted timing explanation retains every English example.
                if index == 4:
                    self.assertEqual(re.findall('«[^»]+»', text),
                                     re.findall('«[^»]+»', original[index]['text']))
        self.assertEqual(len(self.media['transcript'].split('\n\n')), 24)
        self.assertEqual(compact(self.media['transcript']),
                         compact(''.join(p['text'] for row in scenes for p in row)))

    def test_english_is_not_sped_up_and_original_checkpoints_are_retained(self):
        original = read('video_manifest_v4.json')['E']
        self.assertEqual(self.media['chapters'], original['chapters'])
        self.assertEqual(self.media['duration_seconds'], original['duration_seconds'])
        self.assertEqual(len(self.media['scene_audio']), 24)
        total = 0
        for index, (scene, chapter) in enumerate(zip(self.media['scene_audio'], original['chapters'])):
            self.assertEqual(scene['scene'], index)
            self.assertEqual(scene['english_tempo'], 1)
            self.assertGreater(scene['english_seconds'], 0)
            self.assertGreaterEqual(scene['french_tempo'], 1)
            self.assertLessEqual(scene['french_tempo'], 1.12)
            end = original['duration_seconds'] if index == 23 else chapter['end_seconds']
            self.assertAlmostEqual(scene['duration_seconds'], end - chapter['start_seconds'], places=6)
            total += scene['duration_seconds']
        self.assertAlmostEqual(total, original['duration_seconds'], places=6)

    def test_captions_cover_the_complete_narration_without_overlap_or_overflow(self):
        vtt = (ROOT / 'assets' / self.media['captions']).read_text()
        self.assertTrue(vtt.startswith('WEBVTT\n\n'))
        texts, previous_end = [], 0
        for block in vtt.strip().split('\n\n')[1:]:
            timing, *lines = block.splitlines()
            start, end = map(seconds, timing.split(' --> '))
            self.assertGreaterEqual(start, previous_end)
            self.assertGreater(end, start)
            self.assertLessEqual(end, self.media['duration_seconds'])
            self.assertLessEqual(len(lines), 2)
            self.assertTrue(lines and all(len(line) <= 44 for line in lines))
            self.assertTrue(any(start >= chapter['start_seconds'] - .002
                                and end <= chapter['end_seconds'] + .05
                                for chapter in self.media['chapters']))
            previous_end = end
            texts.extend(lines)
        self.assertEqual(compact(''.join(texts)), compact(self.media['transcript']))


if __name__ == '__main__':
    unittest.main()
