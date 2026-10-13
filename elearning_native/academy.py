"""Read-only, versioned Academy curriculum shipped with the application.

No import, migration or session assignment occurs when opening the catalogue.
Old course versions and learner records remain owned by the existing store.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from .practice import REVISION, adapt_course
from .aps_illustrations import illustrate_course
from .aps_media import restore_course_voice
from .aps_editorial import refine_course

ROOT = Path(__file__).parent / 'aps62'
DELIVERY_REVISION = '20261012-aps-sans-production-personnelle'


def _without_personal_productions(course):
    """Retire writing steps for every assigned edition, without changing history.

    Their source documents and worked answers become reading material in the
    same dossier. The study budget is retained; no learner time is manufactured.
    """
    redirects = {}
    examples = 0
    for section in course['sections']:
        retired = [a for a in section['activities'] if a.get('production')]
        if not retired:
            continue
        remaining = [a for a in section['activities'] if not a.get('production')]
        lesson = next(a for a in remaining if a.get('academy', {}).get('kind') == 'lesson')
        worked = lesson['academy'].setdefault('worked_examples', [])
        for activity in retired:
            production = activity['production']
            worked.append({
                'id': activity['id'],
                'title': production['title'],
                'fiction_notice': production.get('fiction_notice', ''),
                'documents': copy.deepcopy(production.get('documents', [])),
                'audio': copy.deepcopy(production.get('audio')),
                'answers': [
                    {'label': field['label'].removeprefix('Votre ').removeprefix('Vos '),
                     'text': production.get('model_response', {}).get(field['id'], '')}
                    for field in production.get('response_fields', [])
                    if production.get('model_response', {}).get(field['id'])
                ],
                'points': [item['expected'] for item in production.get('rubric', []) if item.get('expected')],
            })
            lesson['planned_minutes'] += activity.get('planned_minutes', 0)
            redirects[activity['id']] = lesson['id']
            examples += 1
        section['activities'] = remaining
        if 'pacing' in lesson['academy']:
            lesson['academy']['pacing'] = [
                {'label': a['title'] + (' · exemples corrigés inclus' if a is lesson else ''),
                 'minutes': a.get('planned_minutes', 0)} for a in remaining
            ]
    course['activity_order'] = [a['id'] for s in course['sections'] for a in s['activities']]
    if 'required_activity_ids' in course:
        course['required_activity_ids'] = [aid for aid in course['required_activity_ids'] if aid not in redirects]
    course['counts']['activities'] = len(course['activity_order'])
    course['counts']['productions'] = 0
    course['counts']['worked_examples'] = examples
    course['retired_activity_redirects'] = redirects
    course['delivery_revision'] = DELIVERY_REVISION
    return course


@lru_cache(maxsize=1)
def _manifest():
    return json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))


def curriculum_manifest():
    manifest = copy.deepcopy(_manifest())
    manifest['workbook_count'] = 0
    manifest.setdefault('interactive_workshop_count', 124)
    manifest.setdefault('interaction_revision', REVISION)
    manifest['regulatory_review'] = json.loads((ROOT / 'regulatory_review.json').read_text(encoding='utf-8'))
    courses = [_course(item['id'], item['version']) for item in manifest['modules']]
    for item, course in zip(manifest['modules'], courses):
        item['activities'] = len(course['activity_order'])
    manifest['activity_count'] = sum(len(course['activity_order']) for course in courses)
    manifest['production_count'] = 0
    manifest['visual_learning']['practical_productions'] = 0
    manifest['worked_example_count'] = sum(course['counts']['worked_examples'] for course in courses)
    manifest['delivery_revision'] = DELIVERY_REVISION
    return manifest


def curriculum_ids():
    return [item['id'] for item in _manifest()['modules']]


@lru_cache(maxsize=32)
def _course(course_id, version):
    course = _without_personal_productions(adapt_course(json.loads(
        (ROOT / 'courses' / course_id / (version + '.json')).read_text(encoding='utf-8'))))
    return illustrate_course(restore_course_voice(refine_course(course)))


def load_bundled_course(course_id, version=None):
    item = next((item for item in _manifest()['modules'] if item['id'] == course_id), None)
    if item is None:
        return None
    version = version or item['version']
    if version not in [item['version'], *item.get('previous_versions', [])]:
        return None
    return copy.deepcopy(_course(course_id, version))


def bundled_asset(course_id, version, name):
    course = load_bundled_course(course_id, version)
    if course is None or name not in course.get('assets', []):
        return None
    root = (ROOT / 'assets').resolve()
    path = (root / name).resolve()
    return path if root in path.parents and path.is_file() else None
