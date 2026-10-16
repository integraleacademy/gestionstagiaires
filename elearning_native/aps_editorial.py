"""Complementary reading, video and practice for every assigned APS edition.

This is a delivery overlay. It never writes to archived editions, assignments,
learner time, scores, completions or video records. Assessment IDs retain their
competency while new exercise/option IDs cannot accept old browser answers.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent / 'aps62'
REVISION = '20261013-aps-varied-practice-v15'


@lru_cache(maxsize=1)
def editorial_bank():
    data = json.loads((ROOT / 'editorial_v15.json').read_text(encoding='utf-8'))
    if data.get('revision') != REVISION or len(data.get('sections', {})) != 62:
        raise ValueError('Incomplete APS editorial review')
    return data


def refine_course(course):
    if course.get('source', {}).get('type') != 'academy-aps62':
        return course
    bank = editorial_bank()
    for index, section in enumerate(course['sections']):
        row = bank['sections'][section['id']]
        for activity in section['activities']:
            lesson = activity.get('academy', {})
            kind = lesson.get('kind')
            if kind == 'lesson':
                lesson['editorial_revision'] = REVISION
                plain = lesson.get('plain_course') or [{}]
                lesson['intro'] = copy.deepcopy(plain[0].get('paragraphs') or [lesson.get('reason', '')])
                # The worked film example belongs to the video. Present each
                # principle once instead of six renderings of the same story.
                lesson['deepening'] = [part for part in lesson.get('deepening', [])
                                       if part['title'] != 'Comparer deux moments de la décision']
                for reference in lesson.get('lessons', []):
                    reference['review_reference'] = bank['first_reference'].get(reference['ref']) != section['id']
                    practice = reference.pop('practice', {})
                    # Keep the additional teaching; only the repeated task is
                    # removed. Previously studied references remain available.
                    reference['background'] = practice.get('background', '')
                if index:
                    lesson.pop('visual_board', None)
                for field in ('visual_guide', 'plain_course', 'case', 'flow', 'table', 'sorting',
                              'extra_case', 'decision', 'pitfall'):
                    lesson.pop(field, None)
            elif kind == 'memory':
                activity['title'] = 'Comprendre avec la vidéo'
            if activity['id'] in row['practices']:
                activity['practice'] = copy.deepcopy(row['practices'][activity['id']])
                activity['title'] = 'À vous de décider · trois situations' if kind == 'workshop' else 'Appliquer dans un autre contexte'
                for field in ('case', 'model', 'choices', 'task', 'criteria'):
                    lesson.pop(field, None)
                lesson['title'] = activity['practice']['title']
            if activity['id'] == section['id'] + '-q1':
                activity.update(copy.deepcopy(row['question']))
                activity['title'] = 'Vérifier avec une situation nouvelle'
                activity['aps_editorial_question'] = REVISION
                activity['question_type'] = 'single_choice'
        # The allocation is unchanged; measured time still comes only from
        # presence tracking. Keep descriptive labels consistent with the menu.
        lesson_activity = next(a for a in section['activities'] if a.get('academy', {}).get('kind') == 'lesson')
        lesson_activity['academy']['pacing'] = [
            {'label': a['title'], 'minutes': a.get('planned_minutes', 0)} for a in section['activities']]
    course['aps_editorial_revision'] = REVISION
    return course


@lru_cache(maxsize=32)
def _archived_questions(course_id, version):
    source = json.loads((ROOT / 'courses' / course_id / (version + '.json')).read_text(encoding='utf-8'))
    return {a['id']: a for s in source['sections'] for a in s['activities'] if a.get('scored')}


def question_for_history(activity, course, progress):
    """A completed old question must still show the prompt actually answered."""
    if not activity.get('aps_editorial_question'):
        return activity
    saved = progress.get('answers', {}).get(activity['id'], {})
    if (activity['id'] in progress.get('completed_activity_ids', [])
            and saved.get('content_revision') != REVISION):
        return copy.deepcopy(_archived_questions(course['id'], course['version']).get(activity['id'], activity))
    return activity
