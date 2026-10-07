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
    if course.get('interaction_revision') in ('20261006-aps62-v3', '20261006-aps62-v4', '20261006-aps62-v5', '20261007-aps62-v6', '20261007-aps62-v7', '20261007-aps62-v8', '20261007-aps62-v9'):
        return copy.deepcopy(course)
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
    result = {'revision': practice['revision'],
        'title': practice.get('title', ''), 'sequential': bool(practice.get('sequential')),
        'documents': copy.deepcopy(practice.get('documents', [])),
        'journal': bool(practice.get('journal')),
        'exercises': [
        {'id': ex['id'], 'kind': ex['kind'], 'prompt': ex['prompt'],
         'context': ex.get('context', ''), 'branches': copy.deepcopy(ex.get('branches', {})),
         'options': [{'id': opt['id'], 'text': opt['text']} for opt in ex['options']],
         'rows': [{'id': row['id'], 'text': row['text']} for row in ex.get('rows', [])]}
        for ex in practice['exercises']]}
    if practice.get('mode') == 'journey':
        result['mode'] = 'journey'
        result['purpose'] = practice.get('purpose', '')
        result['adaptive'] = bool(practice.get('adaptive'))
        for public, original in zip(result['exercises'], practice['exercises']):
            for key in ('context', 'stage', 'competency', 'documents', 'audio', 'transcript', 'translation', 'map', 'calculator'):
                if key in original:
                    public[key] = copy.deepcopy(original[key])
    elif practice.get('mode') == 'guided':
        result['mode'] = 'guided'
        # Explanations, branches and answer keys are disclosed only after a check.
        for public, original in zip(result['exercises'], practice['exercises']):
            public.pop('branches', None)
            public['stage'] = original.get('stage', '')
    return result


def grade_practice(practice, answers, review_answers=None, *, step=None):
    exercises = practice['exercises']
    if step is not None:
        if practice.get('mode') not in ('journey', 'guided') or not isinstance(step, str):
            raise ValueError('Cette activité se corrige dans son ensemble.')
        exercises = [ex for ex in exercises if ex['id'] == step]
        if len(exercises) != 1:
            raise ValueError('Étape inconnue.')
    if not isinstance(answers, dict) or set(answers) != {ex['id'] for ex in exercises}:
        raise ValueError('Répondez à chaque exercice avant de vérifier.')
    feedback, normalized = [], {}
    for ex in exercises:
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
        if practice.get('mode') == 'journey':
            feedback[-1].update(competency=ex.get('competency', ''),
                               coaching=ex.get('coaching', ''),
                               consequence=ex.get('consequences', {}).get(supplied, '') if isinstance(supplied, str) else '')
    passed = sum(item['correct'] for item in feedback)
    review = []
    review_answers = {} if review_answers is None else review_answers
    if not isinstance(review_answers, dict):
        raise ValueError('Réponses de révision invalides.')
    allowed = {ex['id'] for ex in practice['exercises'] if ex.get('remediation')}
    if not set(review_answers).issubset(allowed):
        raise ValueError('Révision inconnue.')
    review_prompts = set()
    for ex, result in zip(exercises, feedback):
        drill = ex.get('remediation')
        if not drill or (result['correct'] and ex['id'] not in review_answers):
            continue
        if drill['prompt'] in review_prompts:
            continue
        review_prompts.add(drill['prompt'])
        item = {'id': ex['id'], 'lesson': drill['lesson'], 'prompt': drill['prompt'],
                'options': copy.deepcopy(drill['options'])}
        if ex['id'] in review_answers:
            selected = review_answers[ex['id']]
            if not isinstance(selected, str) or selected not in {o['id'] for o in drill['options']}:
                raise ValueError('Choix de révision invalide.')
            item.update(correct=selected == drill['answer'], explanation=drill['explanation'])
        review.append(item)
    return {'correct': passed == len(feedback), 'passed': passed, 'total': len(feedback),
            'review': review,
            'feedback': feedback, 'answers': normalized, 'revision': practice['revision']}
