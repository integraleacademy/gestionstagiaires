"""Read-only, versioned Academy curriculum shipped with the application.

No import, migration or session assignment occurs when opening the catalogue.
Old course versions and learner records remain owned by the existing store.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent / 'aps62'


@lru_cache(maxsize=1)
def _manifest():
    return json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))


def curriculum_manifest():
    return copy.deepcopy(_manifest())


def curriculum_ids():
    return [item['id'] for item in _manifest()['modules']]


@lru_cache(maxsize=32)
def _course(course_id, version):
    return json.loads((ROOT / 'courses' / course_id / (version + '.json')).read_text(encoding='utf-8'))


def load_bundled_course(course_id, version=None):
    item = next((item for item in _manifest()['modules'] if item['id'] == course_id), None)
    if item is None or (version is not None and version != item['version']):
        return None
    return copy.deepcopy(_course(course_id, item['version']))


def bundled_asset(course_id, version, name):
    course = load_bundled_course(course_id, version)
    if course is None or name not in course.get('assets', []):
        return None
    root = (ROOT / 'assets').resolve()
    path = (root / name).resolve()
    return path if root in path.parents and path.is_file() else None
