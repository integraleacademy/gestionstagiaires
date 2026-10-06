"""Click-only APS practice, shared by preview and authoritative completion.

The archived editions stay intact. A response-mode adaptation retains their
activity/version IDs, scores, video requirements and completed learner work.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

REVISION = '20261006-sans-redaction'


@lru_cache(maxsize=1)
def _bank():
    return json.loads((Path(__file__).parent / 'aps62/practice_bank.json').read_text())


def _learning_text(value):
    """Remove learner writing instructions, not professional reporting concepts."""
    replacements = {
        'Simulation écrite': 'Simulation interactive',
        'simulation écrite': 'simulation interactive',
        'Produire une réponse professionnelle et analyser une variante.':
            'Choisir une réponse professionnelle et analyser une variante.',
        'Rédigez les premières phrases de votre appel.':
            'Repérez les informations prioritaires à transmettre pendant l’appel.',
        'Réécrivez « vous n’aviez qu’à lire le panneau » pour conserver une relation professionnelle.':
            'Quelle formulation respectueuse peut remplacer « vous n’aviez qu’à lire le panneau » ?',
        'Réécrivez l’alerte et sa confirmation de réception.':
            'Repérez les éléments utiles de l’alerte et de sa confirmation de réception.',
        'Comment rédiger sans combler les trous de mémoire ?':
            'Quelle formulation choisir pour signaler les souvenirs incertains ?',
    }
    if isinstance(value, dict):
        return {k: _learning_text(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_learning_text(v) for v in value]
    if isinstance(value, str):
        for before, after in replacements.items():
            value = value.replace(before, after)
    return value


def adapt_course(course):
    if course.get('source', {}).get('type') != 'academy-aps62':
        return course
    course = _learning_text(course)
    total = 0
    for section in course['sections']:
        for activity in section['activities']:
            academy = activity.get('academy', {})
            if activity['id'] in _bank():
                activity.pop('workbook', None)
                activity['practice'] = _learning_text(copy.deepcopy(_bank()[activity['id']]))
                academy.pop('task', None)
                academy.pop('criteria', None)
                academy.pop('choices', None)
                activity['title'] = ('Atelier interactif · choisir, classer et associer'
                    if academy['kind'] == 'workshop' else 'Nouvelle situation · choisir la bonne réponse')
                total += 1
            if academy.get('kind') == 'recap':
                academy['instruction'] = ('Retrouvez mentalement la décision et les limites du dossier, '
                    'puis consultez les repères pour vérifier. Vous pouvez refaire les ateliers pour réviser.')
    course['counts']['workbooks'] = 0
    course['counts']['interactive_workshops'] = total
    course['interaction_revision'] = REVISION
    return course


def public_practice(practice):
    """Explicit public fields: answer keys and explanations stay server-side."""
    return {'revision': practice['revision'], 'exercises': [
        {'id': ex['id'], 'kind': ex['kind'], 'prompt': ex['prompt'],
         'options': [{'id': opt['id'], 'text': opt['text']} for opt in ex['options']],
         'rows': [{'id': row['id'], 'text': row['text']} for row in ex.get('rows', [])]}
        for ex in practice['exercises']]}


def grade_practice(practice, answers):
    if not isinstance(answers, dict) or set(answers) != {ex['id'] for ex in practice['exercises']}:
        raise ValueError('Répondez à chaque exercice avant de vérifier.')
    feedback, normalized = [], {}
    for ex in practice['exercises']:
        supplied = answers[ex['id']]
        options = {opt['id']: opt['text'] for opt in ex['options']}
        expected = ex['answer'] if ex['kind'] == 'single' else {row['id']: row['answer'] for row in ex['rows']}
        if ex['kind'] == 'single':
            if not isinstance(supplied, str) or supplied not in options:
                raise ValueError('Choisissez une proposition pour chaque question.')
            correction = [options[expected]]
        else:
            if (not isinstance(supplied, dict) or set(supplied) != set(expected)
                    or any(not isinstance(v, str) or v not in options for v in supplied.values())):
                raise ValueError('Complétez toutes les cartes avec les propositions disponibles.')
            if ex['kind'] in {'order', 'matching'} and len(set(supplied.values())) != len(supplied):
                raise ValueError('Utilisez chaque étape ou association une seule fois.')
            correction = [row['text'] + ' → ' + options[row['answer']] for row in ex['rows']]
        normalized[ex['id']] = copy.deepcopy(supplied)
        feedback.append({'id': ex['id'], 'correct': supplied == expected,
                         'explanation': ex['explanation'], 'correction': correction})
    passed = sum(item['correct'] for item in feedback)
    return {'correct': passed == len(feedback), 'passed': passed, 'total': len(feedback),
            'feedback': feedback, 'answers': normalized, 'revision': practice['revision']}
