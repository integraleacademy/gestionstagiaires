"""Regression checks for the reviewed v6 teaching transformation.

Use immutable v4/v5 inputs, independently inspect answers, and keep the legal
examples distinct from the numeric examples. No network is required by tests.
"""
import copy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('vtc_v6_content', ROOT / 'scripts/vtc/revision_v6/content.py')
CONTENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTENT)
VERSIONS = ('20261007-vtc-v4-visuals', '20261007-vtc-v5-annales')


def activities(course):
    return {a['id']: a for s in course['sections'] for a in s['activities']}


def singles(value):
    if isinstance(value, dict):
        if value.get('kind') == 'single' and 'options' in value and 'answer' in value:
            yield value
        else:
            for key, child in value.items():
                if key != 'annales_notes':
                    yield from singles(child)
    elif isinstance(value, list):
        for child in value:
            yield from singles(child)


def correct_text(question):
    return next(o['text'] for o in question['options'] if o['id'] == question['answer'])


class VtcV6ContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.originals = {}
        cls.revised = {}
        for version in VERSIONS:
            for letter in 'abcdefgh':
                path = ROOT / f'elearning_native/vtc/courses/academy-vtc-{letter}/{version}.json'
                source = json.loads(path.read_text())
                cls.originals[version, letter] = source
                cls.revised[version, letter] = CONTENT.enrich_course(source)

    def test_transform_is_pure_idempotent_and_preserves_historical_notes(self):
        for key, source in self.originals.items():
            with self.subTest(version=key[0], module=key[1]):
                snapshot = copy.deepcopy(source)
                revised = CONTENT.enrich_course(source)
                self.assertEqual(source, snapshot)
                self.assertIsNot(revised, source)
                self.assertEqual(CONTENT.enrich_course(revised), revised)
                old = activities(source)
                new = activities(revised)
                self.assertEqual(list(new), list(old))
                self.assertEqual(revised['activity_order'], source['activity_order'])
                for id_, activity in old.items():
                    self.assertEqual(activity.get('vtc', {}).get('annales_notes'), new[id_].get('vtc', {}).get('annales_notes'))

    def test_retained_answer_keys_meanings_and_option_ids_survive_revision(self):
        for key, source in self.originals.items():
            old = activities(source)
            new = activities(self.revised[key])
            for id_, activity in old.items():
                if id_ == 'vtc-b-01-dossier':
                    continue  # Explicit replacement with seven different cases.
                questions = {q['id']: q for q in singles(new[id_])}
                for before in singles(activity):
                    with self.subTest(version=key[0], activity=id_, question=before['id']):
                        after = questions[before['id']]
                        self.assertEqual(after['answer'], before['answer'])
                        self.assertEqual(correct_text(after), correct_text(before))
                        self.assertEqual([o['id'] for o in after['options']], [o['id'] for o in before['options']])
        for course in self.revised.values():
            for q in singles(course):
                self.assertIn(q['answer'], {o['id'] for o in q['options']}, q['id'])
                self.assertEqual(len(q['options']), len({o['text'].casefold() for o in q['options']}), q['id'])

    def test_all_96_safety_and_service_decisions_have_distinct_contextual_feedback(self):
        checked = 0
        for letter in ('c', 'h'):
            old = activities(self.originals[VERSIONS[1], letter])
            new = activities(self.revised[VERSIONS[1], letter])
            for id_, activity in old.items():
                if not id_.endswith('-dossier'):
                    continue
                for before in activity['practice']['exercises'][:4]:
                    after = next(q for q in new[id_]['practice']['exercises'] if q['id'] == before['id'])
                    old_wrong = [o['text'] for o in before['options'] if o['id'] != before['answer']]
                    new_wrong = [o for o in after['options'] if o['id'] != after['answer']]
                    self.assertTrue(all(o['text'] not in old_wrong for o in new_wrong), before['id'])
                    feedback = [after['consequences'][o['id']] for o in new_wrong]
                    self.assertEqual(len(set(feedback)), 2)
                    self.assertTrue(all(len(text) > 30 and text != after['explanation'] for text in feedback))
                    checked += 1
        self.assertEqual(checked, 96)

    def test_sensitive_lessons_teach_limits_actors_and_correct_the_refusal_example(self):
        revised = activities(self.revised[VERSIONS[1], 'a'])
        a06 = revised['vtc-a-06-cours']['vtc']
        text = json.dumps(a06, ensure_ascii=False)
        for phrase in ('225-2', 'trois ans', '45 000', 'cinq ans', '75 000', 'Défenseur des droits', '3928', 'ne remplace pas une plainte'):
            self.assertIn(phrase, text)
        q06 = {q['id']: q for q in revised['vtc-a-06-dossier']['practice']['exercises']}
        self.assertEqual(correct_text(q06['v6-a06-sanctions']), 'Trois ans d’emprisonnement et 45 000 € d’amende.')
        self.assertIn('3928', correct_text(q06['v6-a06-orientation']))
        self.assertIn('ne retient pas le cas aggravé', q06['v6-a06-sanctions']['context'])
        a07 = revised['vtc-a-07-cours']['vtc']
        self.assertIn('si la conductrice refuse', a07['deepening']['example'])
        self.assertNotIn('si la conductrice accepte', a07['deepening']['example'])
        text = json.dumps(a07, ensure_ascii=False)
        for phrase in ('sans répétition', 'pression grave', 'acte sexuel non consenti', 'bucco-anaux', 'révocable'):
            self.assertIn(phrase, text)
        self.assertIn('https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000054724663', {s['url'] for s in a07['reviewed_sources']})
        new_questions = [q for q in singles(self.revised[VERSIONS[1], 'a']) if q['id'].startswith('v6-')]
        self.assertEqual(len(new_questions), 3)
        self.assertTrue(all(q['required_core'] and q['sources'] for q in new_questions))

    def test_b01_compares_actual_structures_and_uses_correct_financial_scopes(self):
        course = self.revised[VERSIONS[1], 'b']
        revised = activities(course)
        questions = revised['vtc-b-01-dossier']['practice']['exercises']
        self.assertEqual([q['id'] for q in questions], [f'v6-b01-{n:02d}' for n in range(1, 8)])
        self.assertIn('vtc-b-01-dossier', course['content_revision']['replacement_activities'])
        self.assertEqual(correct_text(questions[0]), 'EURL ou SASU.')
        self.assertIn('indépendante', correct_text(questions[1]))
        self.assertIn('assimilée salariée', correct_text(questions[1]))
        direct, rental = Decimal(48000) - 15000, Decimal(48000) - 29000
        answer = correct_text(questions[2])
        self.assertIn(f'{int(direct):,}'.replace(',', ' '), answer)
        self.assertIn(f'{int(rental):,}'.replace(',', ' '), answer)
        self.assertNotIn('salaires nets', answer)
        self.assertTrue(questions[2]['documents'])
        self.assertIn('salaires nets', questions[2]['consequences'][next(o['id'] for o in questions[2]['options'] if 'salaires nets' in o['text'])])
        ht = (Decimal(48000) / Decimal('1.10')).quantize(Decimal('.01'))
        self.assertEqual(ht, Decimal('43636.36'))
        self.assertIn('43 636,36', questions[6]['explanation'])
        self.assertIn('base identique', correct_text(questions[6]))
        lesson = revised['vtc-b-01-cours']['vtc']
        self.assertEqual(lesson['visual_table']['headers'][1:], ['Entreprise individuelle', 'EURL', 'SASU'])
        self.assertIn('certaines EURL', json.dumps(lesson, ensure_ascii=False))

    def test_optional_restored_variants_are_also_revised_without_touching_annales(self):
        source = copy.deepcopy(self.originals[VERSIONS[1], 'c'])
        first = activities(source)['vtc-c-01-dossier']
        restored = copy.deepcopy(first['practice']['exercises'][0])
        restored['id'] = 'restored-test-variant'
        restored['restored_variant'] = True
        first['free_practice'] = {'exercises': [restored]}
        revised = CONTENT.enrich_course(source)
        variant = activities(revised)['vtc-c-01-dossier']['free_practice']['exercises'][0]
        self.assertEqual(variant['id'], restored['id'])
        self.assertTrue(variant['restored_variant'])
        self.assertEqual(correct_text(variant), correct_text(restored))
        self.assertNotEqual(variant['options'], restored['options'])

    def test_generic_feedback_and_g_deepening_are_replaced(self):
        paragraphs = []
        for letter in 'abcdefgh':
            course = self.revised[VERSIONS[1], letter]
            text = json.dumps(course, ensure_ascii=False)
            self.assertNotIn('Reporter toute décision sans traiter le problème', text)
            self.assertNotIn('Ce choix ne résout pas correctement la situation.', text)
            if letter == 'g':
                for a in activities(course).values():
                    if a.get('vtc', {}).get('kind') == 'lesson':
                        paragraphs.append(a['vtc']['deepening']['paragraphs'][1])
        self.assertEqual(len(set(paragraphs)), 12)
        self.assertTrue(all(not p.startswith('Le bon réflexe consiste à vérifier les informations qui peuvent changer') for p in paragraphs))


if __name__ == '__main__':
    unittest.main()
