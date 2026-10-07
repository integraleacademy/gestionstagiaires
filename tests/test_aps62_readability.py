"""Meaningful caption/content checks for the immutable beginner-friendly edition."""
import json
from pathlib import Path
import re
import unittest

from scripts.aps62_v5.captions import make_cues, wrap_caption
from scripts.aps62_v5.content import courses
from elearning_native.academy import ROOT, curriculum_manifest, load_bundled_course
from tests import test_native_elearning_web as web_tests


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
        manifest = curriculum_manifest()
        self.assertIn(manifest['version'], ('20261007-aps62-v7', '20261007-aps62-v8', '20261007-aps62-v9'))
        # Keep testing the published short-video edition after the long-video
        # edition becomes current. Existing assignments must remain readable.
        for version in dict.fromkeys(('20261007-aps62-v7', manifest['version'])):
            video_revision = {'20261007-aps62-v7':'v5', '20261007-aps62-v8':'v6', '20261007-aps62-v9':'v7'}[version]
            videos = json.loads((ROOT/f'video_manifest_{video_revision}.json').read_text())
            self.assertEqual(set(videos), set(authored))
            for module in manifest['modules']:
                with self.subTest(version=version, module=module['id']):
                    course = load_bundled_course(module['id'], version)
                    old = load_bundled_course(module['id'], '20261006-aps62-v4')
                    self.assertIsNotNone(course)
                    self._assert_readable_course(course, old, videos)

    def _assert_readable_course(self, course, old, videos):
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
            # References to workers' breaks are course material, not a request
            # to interrupt playback. Only forbid learner-facing instructions.
            self.assertNotRegex(video['transcript'].lower(),
                                r'mettez[^.!?]*pause|à vous de décider|ou bien :|choisissez|répondez')
            caption = (ROOT/'assets'/video['captions']).read_text()
            for cue in caption.split('\n\n')[1:]:
                if not cue.strip():
                    continue
                lines = cue.strip().splitlines()[1:]
                self.assertLessEqual(len(lines), 2)
                self.assertTrue(all(len(line) <= 44 for line in lines))


class ReadabilityWebTests(unittest.TestCase):
    setUp = web_tests.NativeElearningWebTests.setUp
    tearDown = web_tests.NativeElearningWebTests.tearDown
    _admin_login = web_tests.NativeElearningWebTests._admin_login

    def test_word_help_and_video_label_survive_the_public_view_boundary(self):
        self._admin_login()
        url = '/admin/elearning/courses/academy-aps62-01/preview'
        for activity in ('comprendre', 'q1', 'atelier'):
            response = self.client.get(url, query_string={'activity': 'aps62-01-01-' + activity})
            self.assertEqual(response.status_code, 200)
            page = response.get_data(as_text=True)
            self.assertIn('class="aps-word-help"', page)
            self.assertIn('Besoin d’aide avec les mots du cours ?', page)
            self.assertIn('Travail confié à l&#39;agent, dans des limites précises.', page)
        video = self.client.get(url, query_string={'activity': 'aps62-01-01-memoriser'}).get_data(as_text=True)
        self.assertIn('Revoir les mots du cours', video)
        self.assertIn('Un agent de sécurité protège des personnes et des biens.', video)
        self.assertNotIn('Mettez la vidéo en pause', video)


if __name__ == '__main__':
    unittest.main()
