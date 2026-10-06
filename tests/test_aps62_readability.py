"""Meaningful caption/content checks for the immutable beginner-friendly edition."""
import json
from pathlib import Path
import re
import unittest

from scripts.aps62_v5.captions import make_cues, wrap_caption
from scripts.aps62_v5.content import courses
from elearning_native.academy import ROOT, curriculum_manifest, load_bundled_course


class CaptionTests(unittest.TestCase):
    def test_punctuation_survives_word_boundary_service(self):
        source = "L'agent observe les faits. Il alerte, puis explique la situation."
        tokens = ["L'agent", 'observe', 'les', 'faits', 'Il', 'alerte', 'puis', 'explique', 'la', 'situation']
        words = [dict(text=word, offset=i*4500000, duration=4000000) for i, word in enumerate(tokens)]
        cues = make_cues(source, words)
        self.assertEqual(' '.join(c['text'].replace('\n', ' ') for c in cues), source)
        self.assertTrue(cues[0]['text'].endswith('.'))
        self.assertTrue(all(len(c['text'].splitlines()) <= 2 for c in cues))
        self.assertTrue(all(max(map(len, c['text'].splitlines())) <= 44 for c in cues))
        self.assertTrue(all(a['end'] <= b['start'] for a, b in zip(cues, cues[1:])))

    def test_missing_or_changed_speech_is_rejected(self):
        with self.assertRaises(ValueError):
            make_cues('Il ne touche pas le câble.', [dict(text='Il touche le câble', offset=0, duration=10000000)])

    def test_wrap_refuses_overflow_instead_of_clipping(self):
        self.assertIsNone(wrap_caption('x'*45))
        self.assertIsNone(wrap_caption('mot '*40))


class ReadabilityTests(unittest.TestCase):
    def test_all_modules_use_the_course_videos_and_defined_words(self):
        authored = courses()
        videos = json.loads((ROOT/'video_manifest_v5.json').read_text())
        self.assertEqual(set(videos), set(authored))
        self.assertEqual(curriculum_manifest()['version'], '20261006-aps62-v5')
        for module in curriculum_manifest()['modules']:
            course = load_bundled_course(module['id'])
            old = load_bundled_course(module['id'], '20261006-aps62-v4')
            self.assertEqual(course['planned_minutes'], old['planned_minutes'])
            self.assertEqual(course['activity_order'], old['activity_order'])
            for section, old_section in zip(course['sections'], old['sections']):
                acts = section['activities']
                self.assertEqual(len(acts[0]['academy']['plain_course']), 3)
                # Reference lessons remain complete, including the legal caveats.
                for ref, previous in zip(acts[0]['academy']['lessons'], old_section['activities'][0]['academy']['lessons']):
                    self.assertEqual(' '.join(p['text'] for p in ref['paragraphs']),
                                     ' '.join(p['text'] for p in previous['paragraphs']))
                self.assertNotIn('EXEMPLE EXPLIQUÉ', [p['left'] for p in acts[4]['pairs']])
                self.assertEqual(len(acts[1]['academy']['cards']), 3)
                self.assertTrue(all(len(c['back'].split()) < 24 for c in acts[1]['academy']['cards']))
                video = acts[1]['blocks'][0]['video']
                self.assertTrue(video['course_only'])
                self.assertEqual(video['voice'], 'fr-FR-HenriNeural')
                self.assertEqual(video['rate'], '-2%')
                self.assertEqual(video['transcript'], videos[section['id']]['transcript'])
                self.assertNotRegex(video['transcript'].lower(), r'pause|à vous de décider|ou bien :|choisissez|répondez')
                caption = (ROOT/'assets'/video['captions']).read_text()
                for cue in caption.split('\n\n')[1:]:
                    if not cue.strip():
                        continue
                    lines = cue.strip().splitlines()[1:]
                    self.assertLessEqual(len(lines), 2)
                    self.assertTrue(all(len(line) <= 44 for line in lines))


if __name__ == '__main__':
    unittest.main()
