"""Versioned A3P preparation resources. Not assignable as TFP distance hours.

The legal eligibility of an objective is separate from the certificate body's
approval of the delivery mode. Keep this edition in administrator preview.
"""
from __future__ import annotations
import copy
import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent / 'a3p_resources'
VERSION = '20261010-a3p-v1'
NOTICE = ('Préparation pédagogique A3P · aperçu administrateur. Aucune heure certifiante ni validation '
          'pratique. Selon les informations ADEF consultées le 10/10/2026, seuls les TFP APS et DSP '
          'comportent des séquences autorisées à distance. L’ouverture A3P nécessite la confirmation '
          'écrite du certificateur et la validation du dispositif par l’organisme de formation.')
MODULES = {
    '02': ('Cadre juridique et déontologie', 'Qualifier une demande, poser une limite et justifier une décision.', ['Qualifier les faits', 'Vérifier le droit', 'Décider dans ses limites', 'Rendre compte']),
    '03': ('Gestion des conflits', 'Prévenir l’escalade et adapter sa communication à la situation.', ['Observer', 'Écouter', 'Poser une limite', 'Organiser le relais']),
    '04': ('Consignes et transmissions', 'Transformer des observations en informations opérationnelles fiables.', ['Recueillir', 'Hiérarchiser', 'Transmettre', 'Confirmer']),
    '05': ('Prévention du risque terroriste', 'Repérer une situation préoccupante, se protéger et alerter.', ['Observer les faits', 'Réduire l’exposition', 'Alerter', 'Faciliter les secours']),
    '06': ('Protection physique des personnes', 'Préparer une mission et coordonner l’accompagnement dans ses limites.', ['Analyser le besoin', 'Préparer les options', 'Briefer l’équipe', 'Réévaluer']),
    '07': ('Techniques professionnelles et capacités', 'Identifier les exigences physiques, techniques et informationnelles du métier.', ['Évaluer les risques', 'Préparer le cadre', 'S’exercer avec un formateur', 'Débriefer']),
    '08': ('Gestion des risques et situations dégradées', 'Adapter l’organisation face aux risques du site, du transport ou d’un événement.', ['Identifier les dangers', 'Prévoir une alternative', 'Coordonner la réponse', 'Actualiser les consignes']),
    '09': ('Secourisme tactique d’urgence', 'Comprendre les priorités et préparer une transmission aux secours.', ['Considérer la menace', 'Protéger et alerter', 'Agir dans ses compétences', 'Réévaluer et transmettre']),
}


@lru_cache(maxsize=1)
def _manual():
    return json.loads((ROOT / 'manual.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def _questions():
    lessons = {l['ref']: l for l in _manual()['lessons']}
    result = []
    for index, line in enumerate((ROOT / 'questions.txt').read_text(encoding='utf-8').splitlines()):
        if not line.strip():
            continue
        ref, prompt, correct, wrong1, wrong2, explanation = line.split('|')
        lesson = lessons[ref]
        texts = [correct, wrong1, wrong2]
        shift = index % 3
        texts = texts[shift:] + texts[:shift]
        options = [{'id': chr(97 + i), 'text': text} for i, text in enumerate(texts)]
        result.append({'id': f'a3p-q-{index + 1:03}', 'prompt': prompt, 'options': options,
                       'answer': next(o['id'] for o in options if o['text'] == correct),
                       'explanation': explanation, 'module': 'UV ' + ref[:2], 'lesson_refs': [ref],
                       'sources': [f"Manuel A3P, leçon {ref}, p. {', '.join(map(str, lesson['source_pages']))}"]})
    return result


def curriculum_ids():
    return ['academy-a3p-' + uv for uv in MODULES]


def _video(uv):
    path = ROOT / 'assets' / 'media' / 'a3p' / 'v1' / ('uv-' + uv + '.json')
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None


def bundled_asset(course_id, version, name):
    course = load_bundled_course(course_id, version)
    if course is None or name not in course.get('assets', []):
        return None
    root = (ROOT / 'assets').resolve()
    path = (root / name).resolve()
    return path if root in path.parents and path.is_file() else None


def curriculum_manifest():
    manual = _manual()
    review = json.loads((ROOT / 'regulatory_review.json').read_text(encoding='utf-8'))
    modules = []
    for uv, (title, objective, flow) in MODULES.items():
        lessons = [l for l in manual['lessons'] if l['ref'].startswith(uv + '.')]
        modules.append({'id': 'academy-a3p-' + uv, 'uv': uv, 'title': title,
                        'objective': objective, 'flow': flow, 'version': VERSION,
                        'video_minutes': round((_video(uv) or {}).get('duration_seconds', 0) / 60, 1),
                        'lesson_count': len(lessons), 'lessons': [
                            {'ref': l['ref'], 'title': l['title'], 'activity': 'a3p-' + l['ref'].replace('.', '-') + '-cours'} for l in lessons],
                        'question_count': sum(q['module'] == 'UV ' + uv for q in _questions()),
                        'exam_id': 'a3p-module-' + uv})
    return {'version': VERSION, 'training_label': 'A3P', 'preview_only': True, 'notice': NOTICE,
            'modules': modules, 'lesson_count': len(manual['lessons']), 'question_count': len(_questions()),
            'reading_page_count': sum(len(l['pages']) for l in manual['lessons']),
            'case_count': len(MODULES), 'video_count': sum(bool(_video(uv)) for uv in MODULES),
            'video_minutes': round(sum((_video(uv) or {}).get('duration_seconds', 0) for uv in MODULES) / 60, 1), 'final_exam_id': 'a3p-final', 'regulatory_review': review}


@lru_cache(maxsize=8)
def _course(uv):
    title, objective, flow = MODULES[uv]
    cases = json.loads((ROOT / 'cases.json').read_text(encoding='utf-8'))
    sections = []
    for lesson in (l for l in _manual()['lessons'] if l['ref'].startswith(uv + '.')):
        ref = lesson['ref']
        prefix = 'a3p-' + ref.replace('.', '-')
        course_activity = {'id': prefix + '-cours', 'title': lesson['title'], 'type': 'content',
                           'scored': False, 'blocks': [], 'a3p': {
                               'kind': 'lesson', 'ref': ref, 'objective': lesson['objective'],
                               'pages': lesson['pages'], 'source_pages': lesson['source_pages'],
                               'practice_notice': uv in {'03', '05', '06', '07', '08', '09'}}}
        questions = []
        for q in (q for q in _questions() if ref in q['lesson_refs']):
            questions.append({'id': q['id'], 'type': 'question', 'question_type': 'single_choice',
                              'title': 'Vérifier mes connaissances · ' + ref, 'prompt': q['prompt'],
                              'scored': True, 'explanation': q['explanation'],
                              'options': [{**o, 'is_correct': o['id'] == q['answer']} for o in q['options']]})
        sections.append({'id': prefix, 'title': ref + ' · ' + lesson['title'],
                         'activities': [course_activity, *questions]})
    sections.append({'id': 'a3p-' + uv + '-atelier', 'title': 'Étude de cas · UV ' + uv,
                     'activities': [{'id': 'a3p-' + uv + '-cas', 'title': cases[uv]['title'],
                                     'type': 'content', 'scored': False, 'blocks': [],
                                     'a3p': {'kind': 'case', 'case': cases[uv], 'flow': flow}}]})
    video = _video(uv)
    assets = []
    if video:
        assets = [video[key] for key in ('src', 'poster', 'captions')]
        sections[0]['activities'][0]['blocks'].append(
            {'id': video['id'], 'type': 'video', 'html': '', 'children': [], 'video': video})
    activities = [a for s in sections for a in s['activities']]
    return {'id': 'academy-a3p-' + uv, 'version': VERSION, 'format_version': 1,
            'title': 'A3P · UV ' + uv + ' · ' + title, 'training_label': 'A3P',
            'preview_only': True, 'required_minutes': 0, 'planned_minutes': 0,
            'description': objective, 'source': {'type': 'academy-a3p', 'sha256': _manual()['source']['text_sha256']},
            'mock_exam_id': 'a3p-module-' + uv, 'assets': assets, 'import_warnings': [],
            'theme': {'main_color': '#135846', 'button_color': '#135846', 'text_color': '#172f29'},
            'settings': {'mastery_score': 80, 'require_correct_answers': True},
            'introduction': [], 'sections': sections, 'activity_order': [a['id'] for a in activities],
            'counts': {'sections': len(sections), 'activities': len(activities),
                       'scored_activities': sum(bool(a['scored']) for a in activities), 'assets': len(assets), 'required_videos': 0}}


def load_bundled_course(course_id, version=None):
    if course_id not in curriculum_ids() or version not in (None, VERSION):
        return None
    return copy.deepcopy(_course(course_id.rsplit('-', 1)[1]))


def _spread(questions, count):
    """Cover the whole bank, including the final lessons of a module."""
    return [questions[i * len(questions) // count] for i in range(count)]


def load_exam(exam_id, version):
    if version != VERSION:
        return None
    if exam_id == 'a3p-final':
        questions = []
        for index, uv in enumerate(MODULES):
            questions.extend(_spread([q for q in _questions() if q['module'] == 'UV ' + uv], 13 if index < 4 else 12))
        title = 'A3P · Examen blanc transversal · 100 questions'
    elif re.fullmatch(r'a3p-module-0[2-9]', str(exam_id)):
        uv = exam_id[-2:]
        questions = _spread([q for q in _questions() if q['module'] == 'UV ' + uv], 30)
        title = 'A3P · UV ' + uv + ' · ' + MODULES[uv][0]
    else:
        return None
    return copy.deepcopy({'id': exam_id, 'version': VERSION, 'title': title,
                          'training_label': 'A3P', 'pass_percent': 80,
                          'notice': 'Entraînement pédagogique : seuil interne de 80 %, sans valeur d’examen officiel ni validation pratique. ' + NOTICE,
                          'questions': questions})
