"""Individual, transactional V10 → V12 transitions without invented study time.

The caller must first validate activation, dates, authentication and the current
assignment. Only complete eight-module V10 paths are eligible. Earlier teaching
editions, partial assignments and fully completed paths remain pinned.

Progress rows are copied once, keeping their original JSON, seconds and activity
timestamps. Original tracking sessions/events are never copied. Proven lineage
lets reports include old and new connections once; summaries use the new progress
row only. Old live sessions are ended at their last recorded heartbeat so delayed
requests cannot continue to credit the predecessor after the transaction.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sqlite3

from .importer import CourseImportError
from .paths import assigned_modules, allows_free_module_navigation, path_revision, project_course, project_progress, required_activity_order
from .store import NativeElearningStore, _json_dict, _json_list, _utc_iso
from .videos import course_videos
from .vtc_productions import BASE_VERSION, MODULE_MINUTES, NOTICE, VERSION


TABLE = "vtc_105_transitions"
META_KEY = "vtc_105_transition"
COURSE_IDS = frozenset(f"academy-vtc-{letter}" for letter in "abcdefgh")


def _context(session_obj, trainee):
    if not isinstance(session_obj, dict) or not isinstance(trainee, dict) or not allows_free_module_navigation(session_obj):
        return None
    modules = assigned_modules(session_obj)
    if (len(modules) != 8 or any(not isinstance(item.get("course_id"), str) for item in modules)
            or {item.get("course_id") for item in modules} != COURSE_IDS
            or any(item.get("course_version") != BASE_VERSION for item in modules)):
        return None
    session_id = str(session_obj.get("id") or "")
    trainee_id = str(trainee.get("id") or trainee.get("trainee_id") or "")
    if not session_id or not trainee_id:
        return None
    return session_id, trainee_id, path_revision(session_obj)


def _database_path(tracking_store):
    return Path(getattr(tracking_store, "database_path", tracking_store)).resolve()


def _existing(database_path, key):
    if not database_path.is_file():
        return None
    with sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True, timeout=15) as connection:
        connection.row_factory = sqlite3.Row
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone():
            return None
        row = connection.execute(f"SELECT * FROM {TABLE} WHERE session_id=? AND trainee_id=? AND source_path_hash=?", key).fetchone()
    return dict(row) if row else None


def _ensure_table(connection):
    connection.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        session_id TEXT NOT NULL,
        trainee_id TEXT NOT NULL,
        source_path_hash TEXT NOT NULL,
        source_modules_json TEXT NOT NULL,
        modules_json TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (session_id, trainee_id, source_path_hash)
    )""")


def _view(session_obj, row):
    try:
        source_modules = json.loads(row["source_modules_json"])
        modules = json.loads(row["modules_json"])
        if (not isinstance(source_modules, list) or not isinstance(modules, list)
                or row["status"] not in {"migrated", "completed_preserved"}
                or source_modules != assigned_modules(session_obj)):
            raise ValueError("Transition incohérente.")
        metadata = {key: row[key] for key in ("session_id", "trainee_id", "source_path_hash", "status", "created_at")}
        metadata.update(source_modules=source_modules, modules=modules)
    except (KeyError, ValueError, TypeError):
        raise CourseImportError("La mise à jour du parcours VTC doit être vérifiée par l’équipe pédagogique.") from None
    return {**session_obj, "aps_native_modules": copy.deepcopy(modules), META_KEY: metadata}


def _same_activity(before, after):
    if before == after:
        return True
    # The V12 edition updates only this presentation notice to describe written
    # productions. Questions, answers, lesson text and video evidence must still
    # be byte-for-byte equivalent as parsed data.
    if (not isinstance(after, dict) or before.get("vtc", {}).get("kind") != "supplements"
            or after.get("vtc", {}).get("notice") != NOTICE):
        return False
    normalized = copy.deepcopy(after)
    if "notice" in before["vtc"]:
        normalized["vtc"]["notice"] = before["vtc"]["notice"]
    else:
        normalized["vtc"].pop("notice", None)
    return normalized == before


def _compatible_courses(modules):
    """Never infer compatibility between two unrelated activity or video banks."""
    from . import vtc
    courses, targets = {}, []
    try:
        for module in modules:
            course_id = module["course_id"]
            before = vtc.load_bundled_course(course_id, BASE_VERSION)
            after = vtc.load_bundled_course(course_id, VERSION)
            if not before or not after:
                return None
            source_sections = [section["id"] for section in before["sections"]]
            selected = module.get("section_ids")
            if selected is None:
                selected = source_sections
            if (not isinstance(selected, list) or len(selected) != len(source_sections)
                    or any(not isinstance(value, str) for value in selected)
                    or set(selected) != set(source_sections)):
                return None
            if set(source_sections) != {section["id"] for section in after["sections"]}:
                return None
            old_activities = {activity["id"]: activity for section in before["sections"] for activity in section.get("activities", [])}
            new_activities = {activity["id"]: activity for section in after["sections"] for activity in section.get("activities", [])}
            if (not old_activities or any(not _same_activity(activity, new_activities.get(activity_id)) for activity_id, activity in old_activities.items())
                    or course_videos(before) != course_videos(after)):
                return None
            added = [activity for activity_id, activity in new_activities.items() if activity_id not in old_activities]
            if len(added) != 4 or any(not activity.get("production") for activity in added):
                return None
            target = {**copy.deepcopy(module), "course_version": VERSION,
                      "section_ids": list(selected), "required_minutes": MODULE_MINUTES[course_id[-1].upper()]}
            courses[course_id] = (project_course(before, module), project_course(after, target))
            targets.append(target)
    except (CourseImportError, OSError, KeyError, ValueError, TypeError):
        return None
    return courses, targets


def _untouched_target(row):
    return (not row["started_at"] and not row["completed_at"] and not row["active_tracking_session_id"]
            and not float(row["active_seconds"] or 0) and not _json_list(row["completed_json"])
            and not _json_dict(row["answers_json"]) and not _json_dict(row["video_progress_json"]))


def _copy_progress(connection, source, target_course):
    # Copy all schema columns, including future additive learner evidence fields.
    copied = dict(source)
    productions = {activity["id"] for section in target_course["sections"]
                   for activity in section.get("activities", []) if activity.get("production")}
    completed, answers = _json_list(source["completed_json"]), _json_dict(source["answers_json"])
    # V10 had no authored V12 productions. An unexpected old key must never turn
    # into evidence for a newly introduced assignment; the old row retains it.
    if productions.intersection(completed):
        completed = [activity_id for activity_id in completed if activity_id not in productions]
        copied["completed_json"] = json.dumps(completed, ensure_ascii=False)
    if productions.intersection(answers):
        answers = {activity_id: value for activity_id, value in answers.items() if activity_id not in productions}
        copied["answers_json"] = json.dumps(answers, ensure_ascii=False)
    scored = [activity["id"] for section in target_course["sections"]
              for activity in section.get("activities", []) if activity.get("scored")]
    completion = NativeElearningStore._completion_values(
        completed, answers,
        activity_order=target_course["activity_order"], scored_activity_ids=scored,
        required_activity_ids=required_activity_order(target_course),
        mastery_score=float(target_course.get("settings", {}).get("mastery_score", 80)),
        active_seconds=float(source["active_seconds"] or 0),
        required_seconds=int(target_course["required_minutes"]) * 60,
        video_requirements=course_videos(target_course), video_progress=_json_dict(source["video_progress_json"]),
    )
    copied.update(course_version=VERSION, current_activity_id=completion["next_activity"],
                  status=completion["status"], score_percent=completion["score"], completed_at=None,
                  active_tracking_session_id=None, active_tracking_seen_epoch=None)
    if not source["started_at"] and not float(source["active_seconds"] or 0) and not completed:
        copied["status"] = "not_started"
    columns = list(copied)
    # Column names originate exclusively from SQLite's existing schema.
    quoted = ",".join('"' + column.replace('"', '""') + '"' for column in columns)
    connection.execute(f"INSERT INTO learner_course_progress ({quoted}) VALUES ({','.join('?' for _ in columns)})",
                       [copied[column] for column in columns])


def resolve_session(session_obj, trainee, tracking_store, *, migrate=True):
    """Return the effective individual path; never mutate administrative records.

    ``migrate=False`` accepts either a NativeElearningStore or a database Path and
    performs only a read-only lookup of an already committed transition. It never
    creates SQLite, a schema, an activity or a progress row.
    """
    key = _context(session_obj, trainee)
    if key is None:
        return session_obj
    database_path = _database_path(tracking_store)
    existing = _existing(database_path, key)
    if existing:
        return _view(session_obj, existing)
    if not migrate:
        return session_obj
    modules = assigned_modules(session_obj)
    compatible = _compatible_courses(modules)
    if compatible is None:
        return session_obj
    courses, targets = compatible
    tracking_store = tracking_store if hasattr(tracking_store, "_transaction") else NativeElearningStore(database_path)
    with tracking_store._transaction() as connection:
        _ensure_table(connection)
        existing = connection.execute(f"SELECT * FROM {TABLE} WHERE session_id=? AND trainee_id=? AND source_path_hash=?", key).fetchone()
        if existing:
            return _view(session_obj, dict(existing))
        source_rows = {row["course_id"]: row for row in connection.execute(
            "SELECT * FROM learner_course_progress WHERE session_id=? AND trainee_id=? AND course_version=?",
            (*key[:2], BASE_VERSION)) if row["course_id"] in COURSE_IDS}
        completed = all(course_id in source_rows and project_progress(
            NativeElearningStore._serialize_progress(source_rows[course_id]), pair[0])["module_complete"]
            for course_id, pair in courses.items())
        created_at = _utc_iso()
        status = "completed_preserved" if completed else "migrated"
        if not completed:
            target_rows = list(connection.execute(
                "SELECT * FROM learner_course_progress WHERE session_id=? AND trainee_id=? AND course_version=?",
                (*key[:2], VERSION)))
            if any(row["course_id"] in COURSE_IDS and not _untouched_target(row) for row in target_rows):
                # A previous unrecorded/manual transition cannot be merged safely.
                return {**session_obj, META_KEY: {
                    "status": "manual_review", "reason": "target_progress_exists", "source_path_hash": key[2],
                    "session_id": key[0], "trainee_id": key[1],
                }}
            for course_id, source in source_rows.items():
                connection.execute("DELETE FROM learner_course_progress WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?",
                                   (*key[:2], course_id, VERSION))
                _copy_progress(connection, source, courses[course_id][1])
            # This is only a closure of recorded activity, never additional time.
            for module in modules:
                course_id = module["course_id"]
                connection.execute("""UPDATE tracking_sessions SET status='ended', ended_at=COALESCE(ended_at,last_seen_at),
                    was_active=0, was_duplicate=0, active_until_epoch=0, video_samples_json='{}'
                    WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=? AND status!='ended'""",
                    (*key[:2], course_id, BASE_VERSION))
                connection.execute("""UPDATE learner_course_progress
                    SET active_tracking_session_id=NULL, active_tracking_seen_epoch=NULL
                    WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?""",
                    (*key[:2], course_id, BASE_VERSION))
        row = {
            "session_id": key[0], "trainee_id": key[1], "source_path_hash": key[2], "status": status,
            "created_at": created_at, "source_modules_json": json.dumps(modules, ensure_ascii=False),
            "modules_json": json.dumps(modules if completed else targets, ensure_ascii=False),
        }
        connection.execute(f"INSERT INTO {TABLE} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
    return _view(session_obj, row)


def read_transition_session(session_obj, trainee, database_path):
    return resolve_session(session_obj, trainee, database_path, migrate=False)


def lineage_versions(session_view, course_id):
    """Versions whose unique original connections belong to the current module."""
    current = next((module for module in assigned_modules(session_view) if module.get("course_id") == course_id), None)
    if current is None:
        return []
    versions = [str(current.get("course_version") or "")]
    transition = session_view.get(META_KEY, {})
    if transition.get("status") == "migrated" and versions == [VERSION]:
        source = next((module for module in transition.get("source_modules", []) if module.get("course_id") == course_id), None)
        target = next((module for module in transition.get("modules", []) if module.get("course_id") == course_id), None)
        if source and target == current and source.get("course_version") == BASE_VERSION:
            versions.append(BASE_VERSION)
    return versions


def current_progress_rows(session_view, rows):
    """Hide only proven predecessor duplicates; retain other learners/history."""
    transition = session_view.get(META_KEY, {})
    if transition.get("status") != "migrated":
        return list(rows)
    hidden = {(module["course_id"], BASE_VERSION) for module in assigned_modules(session_view)
              if lineage_versions(session_view, module.get("course_id")) == [VERSION, BASE_VERSION]}
    return [row for row in rows if not (
        str(row.get("session_id")) == str(transition.get("session_id"))
        and str(row.get("trainee_id")) == str(transition.get("trainee_id"))
        and (row.get("course_id"), row.get("course_version")) in hidden)]
