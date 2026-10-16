"""Separate APS final-exam time; never replace a module's required time."""
from __future__ import annotations

FINAL_COURSE_ID = "academy-aps62-final"
FINAL_ACTIVITY_ID = "aps62-final-examen-blanc"
FINAL_TITLE = "Examen blanc final APS · questions et corrigé"
MODULE_IDS = frozenset(f"academy-aps62-{number:02d}" for number in range(1, 16))


def tracking_course(version):
    """Time-only context, unavailable through the course catalogue/player."""
    return {"id": FINAL_COURSE_ID, "version": version, "title": FINAL_TITLE,
            "mock_exam_id": "final", "required_minutes": 0, "sections": [],
            "activity_order": [], "settings": {}, "training_label": "APS"}


def final_time(assignments, progress_rows):
    """Read only the final belonging to this full, pinned APS curriculum."""
    modules = [item for item in assignments if item.get("course_id") in MODULE_IDS]
    versions = {item.get("course_version") for item in modules}
    if ({item["course_id"] for item in modules} != MODULE_IDS
            or len(versions) != 1 or not next(iter(versions))):
        return None
    version = next(iter(versions))
    row = next((item for item in progress_rows
                if (item.get("course_id"), item.get("course_version")) == (FINAL_COURSE_ID, version)), {})
    return {"course_id": FINAL_COURSE_ID, "version": version, "title": FINAL_TITLE,
            "active_seconds": max(0.0, float(row.get("active_seconds") or 0)),
            "started_at": row.get("started_at"), "updated_at": row.get("updated_at")}
