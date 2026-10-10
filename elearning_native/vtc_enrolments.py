"""Version pinning for new VTC people without migrating any existing account.

The marker is written only by the administrative creation endpoint. Resolving a
learner's session creates a view, never changes the session, roster or progress.
Partner purchases already carry an immutable curriculum snapshot of their own.
"""
from __future__ import annotations

import copy
import re

from .importer import CourseImportError
from .paths import assigned_modules
from .vtc_lesson_videos import COURSE_VERSION, REQUIRED_VERSION

MARKER = 'vtc_lesson_video_version'
COURSE_ID = re.compile(r'academy-vtc-[a-h]')


def mark_new_vtc_enrolment(session_obj, trainee):
    """Call only when a new administrative trainee is created, never on transfer."""
    if 'VTC' in str(session_obj.get('training_type') or session_obj.get('type_formation') or '').upper():
        trainee.setdefault(MARKER, REQUIRED_VERSION)


def _refs(section):
    return frozenset(str(activity.get('vtc', {}).get('ref'))
                     for activity in section.get('activities', [])
                     if re.fullmatch(r'[A-H]\.\d{2}', str(activity.get('vtc', {}).get('ref'))))


def _map_sections(course_id, source_version, selected):
    from . import vtc
    try:
        before = vtc.load_bundled_course(course_id, source_version)
        after = vtc.load_bundled_course(course_id, REQUIRED_VERSION)
    except (OSError, ValueError, TypeError) as exc:
        raise CourseImportError('Le parcours VTC ne peut pas être résolu. Contactez l’équipe pédagogique.') from exc
    if not before or not after:
        raise CourseImportError('La version du parcours VTC est introuvable.')
    old = {section['id']: section for section in before['sections']}
    new = {section['id']: section for section in after['sections']}
    if (not isinstance(selected, list) or not selected
            or any(not isinstance(sid, str) or sid not in old for sid in selected)
            or len(selected) != len(set(selected))):
        raise CourseImportError('La sélection de séquences VTC est invalide ; elle doit être vérifiée.')
    mapped = []
    for sid in selected:
        if sid in new:
            mapped.append(sid)
            continue
        refs = _refs(old[sid])
        matches = [candidate for candidate, section in new.items() if refs and _refs(section) == refs]
        if len(matches) != 1:
            raise CourseImportError('Une ancienne séquence VTC ne correspond pas à la nouvelle édition.')
        mapped.append(matches[0])
    if len(mapped) != len(set(mapped)):
        raise CourseImportError('Plusieurs séquences VTC correspondent à la même séquence de la nouvelle édition.')
    if set(selected) == set(old):
        # A complete old programme stays complete. Add newer sections before the
        # next existing target section, preserving the selected sections' order.
        target_order = list(new)
        for index, sid in enumerate(target_order):
            if sid in mapped:
                continue
            following = next((other for other in target_order[index+1:] if other in mapped), None)
            mapped.insert(mapped.index(following) if following else len(mapped), sid)
    return mapped


def effective_learner_session(session_obj, trainee):
    """Preserve old versions; let newly created VTC people use their marked edition.

    Empty historical VTC version fields meant the then-current v6 catalogue;
    resolve them explicitly to v6 instead of silently upgrading old accounts.
    Explicit empty paths remain empty, and other training families are untouched.
    """
    modules = assigned_modules(session_obj)
    updated = []
    changed = False
    for module in modules:
        course_id = str(module.get('course_id') or '')
        if not COURSE_ID.fullmatch(course_id):
            updated.append(module)
            continue
        current = module.get('course_version') or COURSE_VERSION
        target = REQUIRED_VERSION if trainee.get(MARKER) == REQUIRED_VERSION else current
        item = copy.deepcopy(module)
        item['course_version'] = target
        if target != current and item.get('section_ids') is not None:
            item['section_ids'] = _map_sections(course_id, current, item['section_ids'])
        changed = changed or item != module
        updated.append(item)
    if not changed:
        return session_obj
    return {**session_obj, 'aps_native_modules': updated}
