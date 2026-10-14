"""Substantive APS practice and an honest, conserved module study budget.

This delivery overlay never awards seconds or rewrites learner history. Existing
activity IDs and scored questions stay stable; incomplete workshops use the new
answer key, completed workshops remain available as ungraded revision.
"""
from __future__ import annotations

import copy
import hashlib
import math
import random

from .aps_depth_content import CASES
from .videos import activity_videos

REVISION = '20261014-aps-dossiers-v16'
EXAM_MINUTES = {60: 20, 120: 25, 180: 30, 240: 35, 300: 35, 420: 40}


def _exercise(section_id, index, authored):
    item = copy.deepcopy(authored)
    kind = item['kind']
    exercise_id = f'{section_id}-v16-{index + 1}'
    seed = int(hashlib.sha256(exercise_id.encode()).hexdigest(), 16)
    rng = random.Random(seed)
    result = {key: item[key] for key in ('kind', 'prompt', 'explanation')}
    result.update(id=exercise_id, stage=f'Analyse du dossier · étape {index + 1}',
                  context=item.get('context') or 'Croisez les trois pièces du dossier avant de décider. Les documents restent consultables au-dessus de la question.')
    if kind == 'single':
        result['options'] = [{'id': f'{exercise_id}-o{i}', 'text': text} for i, text in enumerate(item['texts'])]
        result['answer'] = result['options'][0]['id']
    else:
        if kind == 'matching':
            categories = [pair[1] for pair in item['pairs']]
            rows = [(pair[0], i) for i, pair in enumerate(item['pairs'])]
        elif kind == 'order':
            categories = [str(i + 1) for i in range(len(item['steps']))]
            rows = [(text, i) for i, text in enumerate(item['steps'])]
        else:
            categories, rows = item['categories'], item['rows']
        result['options'] = [{'id': f'{exercise_id}-o{i}', 'text': text} for i, text in enumerate(categories)]
        result['rows'] = [{'id': f'{exercise_id}-r{i}', 'text': text, 'answer': result['options'][answer]['id']}
                          for i, (text, answer) in enumerate(rows)]
        rng.shuffle(result['rows'])
    if kind != 'order':
        rng.shuffle(result['options'])
    return result


def _budget(course):
    total = int(course['planned_minutes'])
    exam = EXAM_MINUTES[total]
    activities = [a for s in course['sections'] for a in s['activities']]
    # Reserve the actual video length; do not slow films to fit an estimate.
    fixed = {a['id']: math.ceil(sum(activity_videos(a).values()) / 60)
             for a in activities if activity_videos(a)}
    flexible = [a for a in activities if a['id'] not in fixed]
    remaining = total - exam - sum(fixed.values())
    if remaining < len(flexible):
        raise ValueError('APS study budget cannot contain the required activities')
    weights = [({'lesson': 14, 'workshop': 30, 'transfer': 7, 'documents': 10,
                 'journal': 10, 'recap': 1}.get(a.get('academy', {}).get('kind'), 2)) for a in flexible]
    distributable = remaining - len(flexible)
    fractions = [distributable * weight / sum(weights) for weight in weights]
    minutes = [1 + math.floor(value) for value in fractions]
    for index in sorted(range(len(flexible)), key=lambda i: (-(fractions[i] % 1), i))[:remaining - sum(minutes)]:
        minutes[index] += 1
    allocation = {**fixed, **{a['id']: value for a, value in zip(flexible, minutes)}}
    for activity in activities:
        activity['planned_minutes'] = allocation[activity['id']]
    plan = []
    for section in course['sections']:
        section['planned_minutes'] = sum(a['planned_minutes'] for a in section['activities'])
        plan.append({'id': section['id'], 'label': section['title'], 'minutes': section['planned_minutes'], 'kind': 'section'})
        lesson = next(a['academy'] for a in section['activities'] if a.get('academy', {}).get('kind') == 'lesson')
        lesson['pacing'] = [{'label': a['title'], 'minutes': a['planned_minutes']} for a in section['activities']]
        lesson['pacing_note'] = ('Repères de travail indicatifs, sans crédit automatique de temps. '
            f'L’examen blanc et sa correction disposent de {exam} minutes dans les {total} minutes du module, après les séquences.')
    plan.append({'id': course['mock_exam_id'], 'label': 'Examen blanc et correction expliquée', 'minutes': exam, 'kind': 'exam'})
    course['study_plan'] = {'total_minutes': total, 'activities_minutes': total - exam,
        'exam_minutes': exam, 'steps': plan, 'calibration_status': 'À confirmer par les temps observés des apprenants'}


def deepen_course(course):
    if course.get('source', {}).get('type') != 'academy-aps62' or not course.get('mock_exam_id'):
        return course
    for section in course['sections']:
        case = CASES[section['id']]
        for activity in section['activities']:
            academy = activity.get('academy', {})
            if academy.get('kind') == 'lesson':
                academy['depth_teaching'] = {'title': case['title'], 'paragraphs': case['teaching'].split('\n\n')}
                academy['depth_revision'] = REVISION
            if academy.get('kind') == 'workshop':
                prior = activity['practice']
                transfer = copy.deepcopy(prior['exercises'])
                for exercise in transfer:
                    exercise['stage'] = 'Transfert · une situation indépendante'
                activity['practice'] = {'revision': REVISION, 'mode': 'guided', 'sequential': True,
                    'title': case['title'], 'documents': copy.deepcopy(case['documents']),
                    'dossier': True, 'exercises': [_exercise(section['id'], i, ex) for i, ex in enumerate(case['exercises'])]
                        + transfer}
                activity['title'] = 'Dossier à résoudre · ' + case['title']
                academy['title'] = case['title']
    _budget(course)
    course['aps_depth_revision'] = REVISION
    course['counts']['depth_dossiers'] = len(course['sections'])
    course['counts']['depth_decisions'] = sum(len(ex.get('rows', [])) or 1 for s in course['sections']
        for ex in [_exercise(s['id'], i, e) for i, e in enumerate(CASES[s['id']]['exercises'])])
    return course
