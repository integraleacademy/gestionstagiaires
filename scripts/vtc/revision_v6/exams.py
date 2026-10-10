"""Build independent VTC v6 exams without modifying courses or older editions.

The final is an authored assessment, not a sample of the module exams. Its
15/15/14/14/14/14/14 distribution preserves the earlier pedagogical balance;
it is deliberately not presented as the official weighted admission score.
Run this file directly or call build() from the edition builder.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import runpy
import unicodedata

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE_VERSION = '20261007-vtc-v5-annales'
VERSION = '20261010-vtc-v6-pedagogie'
FINAL_DISTRIBUTION = {'A': 15, 'B': 15, 'C': 14, 'D': 14, 'E': 14, 'F': 14, 'G': 14}


def normal(text, *, ignore_numbers=False):
    value = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().casefold()
    if ignore_numbers:
        value = re.sub(r'\d+(?:[.,]\d+)?', '#', value)
    return re.sub(r'[^a-z0-9#]+', '', value)


def authored_cases():
    cases = {}
    for filename in ('exam_cases_ab.py', 'exam_cases_cd.py', 'exam_cases_ef.py', 'exam_cases_g.py'):
        for letter, rows in runpy.run_path(str(HERE / filename))['CASES'].items():
            if letter in cases:
                raise ValueError('Matière répétée : ' + letter)
            cases[letter] = rows
    english = runpy.run_path(str(HERE / 'exam_english_module.py'))['CASES']
    references = runpy.run_path(str(HERE / 'exam_references.py'))['REFERENCES']
    return cases, english, references


def _questions(rows, prefix, references):
    result = []
    for number, row in enumerate(rows, 1):
        ref, prompt, correct, wrong1, wrong2, explanation, source_keys = row
        # Keep position-balanced stored data as well as the reader's shuffling.
        # Stable choice IDs identify meaning; answer keys never depend on display.
        correct_slot = (number - 1) % 3
        texts = [wrong1, wrong2]
        texts.insert(correct_slot, correct)
        options = [{'id': f'choice-{hashlib.sha256(text.encode()).hexdigest()[:12]}', 'text': text} for text in texts]
        result.append({
            'id': f'{prefix}-{number:02d}', 'prompt': prompt, 'options': options,
            'answer': options[correct_slot]['id'], 'explanation': explanation,
            'module': ref[0], 'lesson_refs': [ref],
            'sources': [{'title': references[key][0], 'url': references[key][1]} for key in source_keys],
            'origin': 'pedagogical-original-v6',
        })
    return result


def make_new_questions():
    cases, english, references = authored_cases()
    if {letter: len(rows) for letter, rows in cases.items()} != FINAL_DISTRIBUTION:
        raise ValueError('Répartition finale incorrecte')
    if len(english) != 30:
        raise ValueError('Le module anglais doit compter 30 questions')
    final = []
    for letter, rows in cases.items():
        final.extend(_questions(rows, f'v6-final-{letter.lower()}', references))
    # A fixed mix of modules makes the saved final reproducible, with no copied
    # module-exam items. The reader independently shuffles choice order.
    final.sort(key=lambda q: hashlib.sha256(('vtc-v6-final:' + q['id']).encode()).hexdigest())
    return final, _questions(english, 'v6-module-e', references)


def _normalise_sources(exam):
    for q in exam['questions']:
        converted = []
        for source in q.get('sources', []):
            if isinstance(source, dict):
                converted.append(source)
            elif isinstance(source, (list, tuple)) and len(source) == 2:
                converted.append({'title': source[0], 'url': source[1]})
            else:
                converted.append(source)
        q['sources'] = converted


def _refine_retained(exam):
    """Narrow distractor repairs; stable answer IDs and explanations stay aligned."""
    replacements = {
        'Le nombre d’étoiles de l’hôtel comme seule garantie du paiement.':
            'Le bénéfice prévisionnel seul, sans tenir compte des dates des flux bancaires.',
        'Retirer la description du trajet pour simplifier le premier écran.':
            'Présenter les frais obligatoires uniquement dans une FAQ facultative après le choix du trajet.',
    }
    changed = []
    for q in exam['questions']:
        for option in q['options']:
            if option['id'] != q['answer'] and option['text'] in replacements:
                option['text'] = replacements[option['text']]
                changed.append(q['id'])
    return changed


def _previous_prompts(root):
    course_root = root / 'elearning_native/vtc'
    prompts = set()
    for path in (course_root / 'courses').glob('*/*.json'):
        course = json.loads(path.read_text())
        for section in course['sections']:
            for activity in section['activities']:
                prompts.update(q['prompt'] for q in activity.get('practice', {}).get('exercises', []))
    for path in (course_root / 'annales').glob('*.json'):
        for section in json.loads(path.read_text())['sections']:
            prompts.update(q['prompt'] for q in section['questions'])
    for path in (course_root / 'exams').glob('*/*.json'):
        if path.parent.name != VERSION:
            prompts.update(q['prompt'] for q in json.loads(path.read_text())['questions'])
    return prompts


def validate_new_questions(exams, root=ROOT):
    manifest = json.loads((root / 'elearning_native/vtc/manifest.json').read_text())
    refs = {lesson['ref'] for module in manifest['modules'] for lesson in module['lessons']}
    final = exams['vtc-final']['questions']
    modules = [q for key, exam in exams.items() if key != 'vtc-final' for q in exam['questions']]
    prior = _previous_prompts(root)
    exact = {normal(text) for text in prior}
    numeric = {normal(text, ignore_numbers=True) for text in prior}
    fresh = final + exams['vtc-e']['questions']
    if len({q['id'] for q in fresh}) != 130 or len({normal(q['prompt']) for q in fresh}) != 130:
        raise ValueError('La nouvelle banque doit contenir 130 questions différentes')
    for q in fresh:
        if normal(q['prompt']) in exact or normal(q['prompt'], ignore_numbers=True) in numeric:
            raise ValueError('Énoncé repris ou simple variante chiffrée : ' + q['id'])
    if {normal(q['prompt']) for q in final} & {normal(q['prompt']) for q in modules}:
        raise ValueError('Le final recopie un examen de module')
    for key, exam in exams.items():
        expected = 100 if key == 'vtc-final' else 30
        if len(exam['questions']) != expected:
            raise ValueError(f'{key} : nombre de questions incorrect')
        if len({normal(q['prompt']) for q in exam['questions']}) != expected:
            raise ValueError(f'{key} : doublon dans l’examen')
        for q in exam['questions']:
            option_ids = {o['id'] for o in q['options']}
            if (len(option_ids) != len(q['options']) or q['answer'] not in option_ids or
                    len({' '.join(o['text'].split()).casefold() for o in q['options']}) != len(q['options'])):
                raise ValueError('Choix invalides : ' + q['id'])
            if not q['lesson_refs'] or not set(q['lesson_refs']) <= refs:
                raise ValueError('Leçon inconnue : ' + q['id'])
            if len(q['explanation']) < 70:
                raise ValueError('Correction insuffisante : ' + q['id'])
    return {'new_final_questions': len(final), 'new_english_module_questions': 30,
            'final_module_overlap': 0, 'new_prompt_overlap_with_previous_content': 0,
            'numeric_only_prompt_variants': 0, 'distribution': FINAL_DISTRIBUTION}


def build(root=ROOT):
    root = Path(root)
    directory = root / 'elearning_native/vtc/exams'
    final_questions, english_questions = make_new_questions()
    exams = {}
    refinements = []
    for letter in 'abcdefgh':
        eid = 'vtc-' + letter
        exam = copy.deepcopy(json.loads((directory / BASE_VERSION / (eid + '.json')).read_text()))
        exam['version'] = VERSION
        if letter == 'e':
            exam['questions'] = english_questions
            exam['title'] = 'Anglais VTC · 30 échanges professionnels'
            exam['notice'] = 'Entraînement pédagogique original en anglais. Choisissez la réponse correspondant exactement à la situation. Ce questionnaire ne reproduit pas la notation de l’examen officiel.'
            exam['construction'] = {'origin': '30 échanges originaux distincts des annales et du final', 'reviewed_on': '2026-10-10'}
        _normalise_sources(exam)
        refinements.extend(_refine_retained(exam))
        exams[eid] = exam
    exams['vtc-final'] = {
        'id': 'vtc-final', 'version': VERSION, 'training_label': 'VTC',
        'title': 'VTC · Examen blanc final : 100 situations inédites', 'pass_percent': 80,
        'questions': final_questions,
        'notice': '100 situations pédagogiques originales, distinctes des examens de module et des annales. Les données et échanges sont fictifs. Les références servent à réviser les règles et notions mobilisées. Le seuil de 80 % et la répartition par matière sont pédagogiques ; ils ne reproduisent pas les coefficients, les QRC écrites ni la notation de l’examen officiel.',
        'construction': {'origin': 'authored-independent-final-v6', 'reviewed_on': '2026-10-10',
                         'module_counts': FINAL_DISTRIBUTION,
                         'rationale': 'Répartition pédagogique conservée : A et B 15, C à G 14. Aucun tirage dans la banque des examens de module.',
                         'source_scenarios': 'Situations et textes originaux, références externes pour les règles et compétences.'},
    }
    report = validate_new_questions(exams, root)
    report['retained_module_distractors_revised'] = refinements
    target = directory / VERSION
    target.mkdir(parents=True, exist_ok=True)
    for eid, exam in exams.items():
        (target / (eid + '.json')).write_text(json.dumps(exam, ensure_ascii=False, indent=2) + '\n')
    return report


build_exams = build

if __name__ == '__main__':
    print(json.dumps(build(), ensure_ascii=False, indent=2))
