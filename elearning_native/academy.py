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

ROOT = Path(__file__).parent / 'aps62'


@lru_cache(maxsize=1)
def _manifest():
    return json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))


def curriculum_manifest():
    manifest = copy.deepcopy(_manifest())
    manifest['workbook_count'] = 0
    manifest.setdefault('interactive_workshop_count', 124)
    manifest.setdefault('interaction_revision', REVISION)
    manifest['regulatory_review'] = json.loads((ROOT / 'regulatory_review.json').read_text(encoding='utf-8'))
    return manifest


def curriculum_ids():
    return [item['id'] for item in _manifest()['modules']]


@lru_cache(maxsize=32)
def _course(course_id, version):
    return adapt_course(json.loads((ROOT / 'courses' / course_id / (version + '.json')).read_text(encoding='utf-8')))


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
