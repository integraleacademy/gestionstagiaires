"""Version-pinned session paths; imported courses remain immutable."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping

from .importer import CourseCatalog, CourseImportError


MAX_PATH_MODULES = 100


def assigned_modules(session_obj: Mapping[str, Any]) -> List[Dict[str, Any]]:
    # An explicit empty path must not fall back to the old single-course field.
    if isinstance(session_obj.get("aps_native_modules"), list):
        return [dict(item) for item in session_obj["aps_native_modules"] if isinstance(item, Mapping)]
    if session_obj.get("aps_native_course_id"):
        return [{
            "course_id": str(session_obj["aps_native_course_id"]),
            "course_version": str(session_obj.get("aps_native_course_version") or ""),
        }]
    return []


def path_revision(session_obj: Mapping[str, Any]) -> str:
    raw = {"title": session_obj.get("aps_native_path_title") or "", "modules": assigned_modules(session_obj)}
    return hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def project_course(course: Mapping[str, Any], module: Mapping[str, Any]) -> Dict[str, Any]:
    """Select/order sequences without changing activity IDs, content or answers."""
    by_id = {str(section["id"]): section for section in course.get("sections") or []}
    section_ids = module.get("section_ids")
    if section_ids is None:
        section_ids = list(by_id)
    if (not isinstance(section_ids, list) or not section_ids
            or any(not isinstance(value, str) for value in section_ids)
            or len(set(section_ids)) != len(section_ids)
            or any(value not in by_id for value in section_ids)):
        raise CourseImportError("Séquences invalides : choisissez au moins une séquence par module.")
    sections = [by_id[value] for value in section_ids]
    activities = [activity for section in sections for activity in section.get("activities") or []]
    if not activities:
        raise CourseImportError("Le module doit contenir au moins une activité.")
    return {
        **course,
        "title": str(module.get("title") or course.get("title") or "Module"),
        "sections": sections,
        "activity_order": [str(activity["id"]) for activity in activities],
        "counts": {**course.get("counts", {}), "sections": len(sections),
                   "activities": len(activities),
                   "scored_activities": sum(bool(activity.get("scored")) for activity in activities)},
    }


def validate_modules(raw: Any, catalog: CourseCatalog) -> List[Dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > MAX_PATH_MODULES:
        raise CourseImportError(f"Le parcours doit contenir au maximum {MAX_PATH_MODULES} modules.")
    validated = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("course_id"), str):
            raise CourseImportError("Module invalide.")
        course_id = item["course_id"]
        if course_id in seen:
            raise CourseImportError("Un même module ne peut apparaître qu’une fois dans le parcours.")
        seen.add(course_id)
        version = item.get("course_version")
        if version is not None and not isinstance(version, str):
            raise CourseImportError("Version de module invalide.")
        course = catalog.load_course(course_id, version or None)
        title = item.get("title", "")
        if not isinstance(title, str) or len(title) > 180:
            raise CourseImportError("Le titre du module est limité à 180 caractères.")
        projected = project_course(course, item)
        validated.append({
            "course_id": course["id"], "course_version": course["version"],
            "title": title.strip(),
            "section_ids": [str(section["id"]) for section in projected["sections"]],
        })
    return validated


def course_outline(course: Mapping[str, Any]) -> Dict[str, Any]:
    """Only descriptive metadata may be sent to the path composer/browser."""
    return {
        "course_id": course["id"], "course_version": course["version"], "title": course["title"],
        "sections": [{
            "id": str(section["id"]), "title": str(section.get("title") or "Séquence"),
            "activities": [{"title": str(activity.get("title") or "Activité"),
                            "scored": bool(activity.get("scored"))}
                           for activity in section.get("activities") or []],
        } for section in course.get("sections") or []],
    }


def project_progress(progress: Mapping[str, Any], course: Mapping[str, Any]) -> Dict[str, Any]:
    """Compute completion against the current selection, retaining stored history."""
    order = course.get("activity_order") or []
    completed = set(progress.get("completed_activity_ids") or []) & set(order)
    scored = [activity["id"] for section in course.get("sections") or []
              for activity in section.get("activities") or [] if activity.get("scored")]
    answers = {key: value for key, value in (progress.get("answers") or {}).items() if key in order}
    correct = sum(bool(answers.get(key, {}).get("correct")) for key in scored)
    score = round(correct / len(scored) * 100, 2) if scored else 100.0
    finished = bool(order) and len(completed) == len(order)
    status = ("passed" if score >= float(course.get("settings", {}).get("mastery_score", 80)) else "failed") if finished else (
        "in_progress" if progress.get("started_at") else "not_started"
    )
    return {
        **progress, "answers": answers, "completed_activity_ids": [key for key in order if key in completed],
        "progress_percent": round(len(completed) / len(order) * 100, 2) if order else 0,
        "score_percent": score, "correct_answers": correct, "scored_activities": len(scored),
        "status": status, "active_seconds": float(progress.get("active_seconds") or 0),
        "completed_at": progress.get("completed_at") if finished else None,
    }
