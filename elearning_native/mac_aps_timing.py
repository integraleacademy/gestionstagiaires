"""Server-recorded time for each objective of the MAC APS 14-hour edition.

The edition is a pedagogical resource. These counters do not constitute a
regulatory authorization to deliver the MAC APS stage remotely.
"""
from __future__ import annotations

import math
from typing import Any, Mapping


TIMED_VERSION = "20261012-macaps-v2"
FIXED_MINUTES = {
    "academy-macaps-02": 180,
    "academy-macaps-03": 240,
    "academy-macaps-05": 420,
}


def is_timed_key(course_id: str, version: str) -> bool:
    return version == TIMED_VERSION and course_id in FIXED_MINUTES


def is_timed_course(course: Mapping[str, Any]) -> bool:
    return is_timed_key(str(course.get("id") or ""), str(course.get("version") or ""))


def objective_progress(course: Mapping[str, Any], progress: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not is_timed_course(course):
        return []
    ledger = progress.get("activity_seconds") or {}
    if not isinstance(ledger, Mapping):
        ledger = {}
    completed = set(progress.get("completed_activity_ids") or [])
    rows = []
    for objective in course.get("timed_objectives") or []:
        activity_ids = [str(value) for value in objective.get("activity_ids") or []]
        active_seconds = 0.0
        for activity_id in activity_ids:
            value = ledger.get(activity_id, 0)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                active_seconds += max(0.0, float(value))
        required_seconds = int(objective["required_seconds"])
        remaining_seconds = max(0, math.ceil(required_seconds - active_seconds))
        duration_met = remaining_seconds == 0
        rows.append({
            "id": str(objective["id"]), "title": str(objective["title"]),
            "activity_ids": activity_ids,
            "active_seconds": math.floor(active_seconds * 100) / 100,
            "required_seconds": required_seconds, "remaining_seconds": remaining_seconds,
            "duration_met": duration_met,
            "complete": duration_met and bool(activity_ids) and set(activity_ids).issubset(completed),
        })
    return rows


def completion_blocker(course: Mapping[str, Any], progress: Mapping[str, Any], activity_id: str) -> dict[str, Any] | None:
    """The closing questionnaire cannot validate an objective prematurely.

    Reading, revisiting earlier activities and heartbeats remain available while
    the learner studies the objective. No client-supplied duration is accepted.
    """
    for objective in objective_progress(course, progress):
        if (objective["activity_ids"] and objective["activity_ids"][-1] == activity_id
                and not objective["duration_met"]):
            return objective
    return None
