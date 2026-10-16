"""Dataset/integration contracts for the new fictional productions."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from scripts.aps62_v10.practical_cases import (
    PRODUCTIONS, THREAT_CALL_AUDIO, apply_practical_cases, get_production,
)
from scripts.aps62_v10.radio_demonstrations import RADIO_DEMONSTRATIONS, dialogue_text

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'elearning_native/aps62'
ASSETS = BASE / 'assets'


class PracticalContentTests(unittest.TestCase):
    def test_ten_productions_replace_only_existing_transfers_and_preserve_duration(self):
        attached = set()
        for path in sorted((BASE / 'courses').glob('academy-aps62-*/20261007-aps62-v9.json')):
            original = json.loads(path.read_text())
            course = copy.deepcopy(original)
            returned = apply_practical_cases(course)
            self.assertIs(returned, course)
            self.assertEqual(course['activity_order'], original['activity_order'])
            for before_section, after_section in zip(original['sections'], course['sections']):
                self.assertEqual(before_section['planned_minutes'], after_section['planned_minutes'])
                for before, after in zip(before_section['activities'], after_section['activities']):
                    self.assertEqual(before['id'], after['id'])
                    self.assertEqual(before['planned_minutes'], after['planned_minutes'])
                    if 'production' in after:
                        attached.add(before_section['id'])
                        self.assertTrue(after['id'].endswith('-transfert'))
                        self.assertNotIn('practice', after)
                        self.assertEqual(after['academy']['kind'], 'transfer')
                        self.assertFalse(after['scored'])
                    else:
                        self.assertEqual(before, after)
            self.assertEqual(apply_practical_cases(copy.deepcopy(course)), course)
        self.assertEqual(attached, set(PRODUCTIONS))
        self.assertEqual(len(attached), 10)

    def test_missing_target_fails_instead_of_silently_omitting_a_production(self):
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            apply_practical_cases({'sections': [{'id': 'aps62-08-02', 'activities': []}]})

    def test_models_cover_fields_and_fit_the_same_submission_constraints(self):
        for sid, production in PRODUCTIONS.items():
            fields = production['response_fields']
            ids = [x['id'] for x in fields]
            self.assertEqual(len(ids), len(set(ids)), sid)
            self.assertEqual(set(ids), set(production['model_response']), sid)
            self.assertGreaterEqual(len(production['rubric']), 3, sid)
            self.assertFalse(production['trainer_validation'])
            for field in fields:
                model = production['model_response'][field['id']]
                self.assertGreaterEqual(len(model), field['min_chars'], sid)
                self.assertLessEqual(len(model), field['max_chars'], sid)
                self.assertTrue(field['required'], sid)
            for item in production['rubric']:
                self.assertTrue(item['label'] and item['expected'], sid)
            self.assertNotIn('options', production)
            json.dumps(production, ensure_ascii=False)

    def test_copies_do_not_mutate_source_data(self):
        result = get_production('aps62-08-04')
        result['documents'][0]['text'] = 'modified'
        result['model_response']['rapport'] = 'modified'
        self.assertNotEqual(PRODUCTIONS['aps62-08-04']['documents'][0]['text'], 'modified')
        self.assertNotEqual(PRODUCTIONS['aps62-08-04']['model_response']['rapport'], 'modified')

    def test_inputs_are_genuine_documents_not_exposed_model_text(self):
        for sid, production in PRODUCTIONS.items():
            self.assertGreaterEqual(len(production['documents']), 2, sid)
            visible = json.dumps({'brief': production['brief'], 'documents': production['documents']}, ensure_ascii=False)
            for field, model in production['model_response'].items():
                self.assertNotIn(model, visible, (sid, field))
            for doc in production['documents']:
                self.assertTrue(doc['title'] and doc['text'], sid)
                self.assertTrue(all(isinstance(row, list) and len(row) >= 2 for row in doc.get('rows', [])), sid)

    def test_all_62_dialogues_fit_three_bubbles_and_keep_full_narration(self):
        section_ids = set()
        for path in (BASE / 'courses').glob('academy-aps62-*/20261007-aps62-v9.json'):
            section_ids.update(x['id'] for x in json.loads(path.read_text())['sections'])
        self.assertEqual(set(RADIO_DEMONSTRATIONS), section_ids)
        self.assertEqual(len(section_ids), 62)
        for sid, scene in RADIO_DEMONSTRATIONS.items():
            self.assertEqual(len(scene['turns']), 3, sid)
            self.assertTrue(scene['context'], sid)
            for turn in scene['turns']:
                self.assertLessEqual(len(turn['display_text']), 180, sid)
                self.assertTrue(turn['speaker'] and turn['text'], sid)
                self.assertIn(turn['text'], dialogue_text(sid))
                self.assertNotIn('Quelle action proposez-vous', turn['text'], sid)

    def test_plan_image_is_accessible_and_matches_the_document_grid(self):
        document = PRODUCTIONS['aps62-15-05']['documents'][0]
        svg = ASSETS / document['image']
        root = ET.parse(svg).getroot()
        texts = ' '.join(root.itertext())
        self.assertTrue(document['image_alt'])
        for coordinate in document['map']['cells']:
            self.assertIn(coordinate, texts)
        self.assertIn('17 h 03', texts)
        self.assertIn('17 h 05', texts)
        self.assertFalse(root.findall('.//{http://www.w3.org/2000/svg}script'))

    def test_audio_is_real_and_hash_matches_the_provenance(self):
        production = PRODUCTIONS['aps62-12-05']
        audio = ASSETS / production['audio']['src']
        metadata = json.loads(audio.with_suffix('.json').read_text())
        self.assertGreater(audio.stat().st_size, 5000)
        self.assertEqual(hashlib.sha256(audio.read_bytes()).hexdigest(), metadata['audio_sha256'])
        self.assertEqual(metadata['voice'], 'fr-FR-HenriNeural')
        self.assertEqual(metadata['rate'], '-2%')
        self.assertGreater(metadata['duration_seconds'], metadata['caption_end_seconds'])
        self.assertTrue(metadata['qa']['complete_decode'])
        self.assertEqual(production['audio']['transcript'], THREAT_CALL_AUDIO['transcript'])
        self.assertEqual(metadata['transcript'], THREAT_CALL_AUDIO['transcript'])
        self.assertTrue(audio.with_suffix('.vtt').read_text().startswith('WEBVTT'))

    def test_local_outage_does_not_contradict_the_other_posts_entry(self):
        case = PRODUCTIONS['aps62-13-02']
        self.assertIn('panne locale', case['brief'])
        self.assertIn('Logistique 1', case['brief'])
        self.assertIn('11 h 56', json.dumps(case['documents'], ensure_ascii=False))
        self.assertIn('MC-204', case['model_response']['reprise'])
        self.assertIn('12 h 20', case['model_response']['reprise'])


if __name__ == '__main__':
    unittest.main()
