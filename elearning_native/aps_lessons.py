"""Additional reading for every APS edition, without new completion or time credit."""
from __future__ import annotations

import copy

from .aps_lessons_content import LESSONS

REVISION = '20261014-aps-cours-v17'
REFERENCE_TITLES = {
    'Écrire une main courante utile': 'Comprendre une main courante utile',
    'Rédiger un rapport circonstancié': 'Comprendre un rapport circonstancié',
}


def enrich_course(course):
    if course.get('source', {}).get('type') != 'academy-aps62':
        return course
    for section in course['sections']:
        lesson = next(a['academy'] for a in section['activities']
                      if a.get('academy', {}).get('kind') == 'lesson')
        lesson['reading_pages'] = copy.deepcopy(LESSONS[section['id']])
        lesson['reading_revision'] = REVISION
        for reference in lesson.get('lessons', []):
            reference['title'] = REFERENCE_TITLES.get(reference['title'], reference['title'])
    course['aps_reading_revision'] = REVISION
    course['counts']['reading_pages'] = len(course['sections']) * 3
    course['counts']['reading_comparisons'] = len(course['sections'])
    course['counts']['reading_examples'] = len(course['sections'])
    return course
