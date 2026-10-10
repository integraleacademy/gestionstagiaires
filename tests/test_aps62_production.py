import copy
import unittest
from elearning_native.production import public_production, normalize_production, normalize_self_review


class ProductionValidationTests(unittest.TestCase):
    def setUp(self):
        self.production = {'id':'case', 'title':'Dossier', 'brief':'Consigne',
            'response_fields':[{'id':'report', 'label':'Compte rendu', 'required':True, 'min_chars':20, 'max_chars':100},
                               {'id':'question', 'label':'Question', 'required':False, 'max_chars':100}],
            'rubric':[{'id':'facts', 'label':'Faits', 'expected':'Ne pas inventer'}],
            'model_response':{'report':'Réponse réservée à la comparaison'}, 'secret':'not public'}

    def test_public_dossier_has_no_solution_before_comparison(self):
        shown = public_production(self.production)
        self.assertNotIn('model_response', shown)
        self.assertNotIn('rubric', shown)
        self.assertNotIn('secret', shown)
        self.assertEqual(public_production(self.production, reveal=True)['feedback']['model_response'], self.production['model_response'])
        shown['response_fields'][0]['label']='changed'
        self.assertEqual(self.production['response_fields'][0]['label'], 'Compte rendu')

    def test_partial_draft_is_allowed_but_comparison_requires_a_complete_response(self):
        self.assertEqual(normalize_production(self.production, {'report':' début '}, draft=True), {'report':'début','question':''})
        for answers in ({}, {'report':'trop court'}, {'report':'Observation précise et factuelle.'}):
            with self.assertRaises(ValueError):
                normalize_production(self.production, answers)
        self.assertEqual(normalize_production(self.production, {'report':'Observation précise et factuelle.', 'question':''})['question'], '')

    def test_payload_rejects_unknown_fields_types_and_excessive_size(self):
        for answers in (None, [], {'unknown':'x'}, {'report':[]}, {'report':True}, {'report':'x'*101}):
            with self.subTest(answers=answers), self.assertRaises(ValueError):
                normalize_production(self.production, answers, draft=True)
        many=copy.deepcopy(self.production)
        many['response_fields']=[{'id':str(i),'label':'Texte','max_chars':6000} for i in range(5)]
        with self.assertRaises(ValueError):
            normalize_production(many,{str(i):'x'*5000 for i in range(5)})

    def test_self_review_requires_each_real_criterion_without_grading(self):
        for bad in (None, {}, {'facts':True}, {'facts':[]}, {'facts':'passed'}, {'facts':'checked','extra':'checked'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_self_review(self.production,bad)
        for value in ('checked','needs_help'):
            self.assertEqual(normalize_self_review(self.production, {'facts':value}), {'facts':value})


class MatchingOrderTests(unittest.TestCase):
    def test_matching_display_is_shuffled_without_changing_grading_ids(self):
        from unittest.mock import patch
        from elearning_native.practice import public_practice, grade_practice
        exercise = {'id':'match', 'kind':'matching', 'prompt':'Associer',
                    'options':[{'id':'a','text':'Alpha'},{'id':'b','text':'Bravo'}],
                    'rows':[{'id':'one','text':'Premier','answer':'a'}, {'id':'two','text':'Second','answer':'b'}],
                    'explanation':'Deux associations.'}
        practice={'revision':'test', 'exercises':[exercise]}
        before=copy.deepcopy(practice)
        with patch('elearning_native.practice.secrets.SystemRandom.shuffle', side_effect=lambda rows: rows.reverse()):
            shown=public_practice(practice)
        self.assertEqual([o['id'] for o in shown['exercises'][0]['options']], ['b','a'])
        self.assertEqual(practice,before)
        self.assertNotIn('answer',shown['exercises'][0]['rows'][0])
        self.assertTrue(grade_practice(practice,{'match':{'one':'a','two':'b'}})['correct'])
