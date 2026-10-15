"""The full APS path must remain readable with or without final-exam time."""
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

import elearning_reporting as reporting


@pytest.mark.parametrize("detailed", [True, False])
@pytest.mark.parametrize("missing_course", [False, True])
@pytest.mark.parametrize("final_seconds", [None, 0, 125.5])
def test_full_aps_report_keeps_final_time_separate(monkeypatch, tmp_path, detailed,
                                                missing_course, final_seconds):
    person = {"id": "learner", "activated_at": "2026-10-01T10:00:00Z"}
    assignments = [{"course_id": f"academy-aps62-{i:02d}", "course_version": "v1",
                    "title": f"Module {i}", "required_minutes": 1} for i in range(1, 16)]
    order = {"id": "order", "course_code": "aps", "modules": assignments, "learners": [person]}
    progress = [{"course_id": item["course_id"], "course_version": "v1", "active_seconds": 10}
                for item in assignments]
    if final_seconds is not None:
        progress.append({"course_id": "academy-aps62-final", "course_version": "v1",
                         "active_seconds": final_seconds})
    # Another edition's exam time must never enter this purchased path.
    progress.append({"course_id": "academy-aps62-final", "course_version": "v2",
                     "active_seconds": 9999})
    before = copy.deepcopy((order, progress))
    reader = reporting.ProgressReader.__new__(reporting.ProgressReader)
    reader.database_path = tmp_path / "tracking.sqlite3"
    reader.ai_path = tmp_path / "production_ai.sqlite3"

    def course(assignment):
        if missing_course and assignment is assignments[0]:
            raise reporting.CourseImportError("Missing snapshot")
        return {"id": assignment["course_id"], "version": "v1", "title": assignment["title"],
                "activity_order": ["read"], "sections": [{"id": "section", "activities": [
                    {"id": "read", "title": "Lecture"}]}]}

    def rows(table, session_id, learner_id):
        assert (session_id, learner_id) == ("el-order", "learner")
        return progress if table == "progress" else []

    def projected(row, course):
        return {"completed_activity_ids": [], "completed_required_activities": 0,
                "required_activity_count": 1, "optional_activity_count": 0,
                "active_seconds": row["active_seconds"], "required_seconds": 60,
                "remaining_seconds": 50, "module_complete": False, "progress_percent": 0,
                "status": "in_progress", "completed_video_count": 0, "required_video_count": 0}

    monkeypatch.setattr(reader, "course", course)
    monkeypatch.setattr(reader, "rows", rows)
    monkeypatch.setattr(reporting, "project_progress", projected)
    monkeypatch.setattr(reporting, "read_transition_session", lambda session, *_: session)
    monkeypatch.setattr(reporting, "lineage_versions", lambda *_: ["v1"])
    report = reader.report(order, person, detailed=detailed)
    final = next(exam for exam in report["exam_catalogue"] if exam["id"] == "final")
    assert final["active_seconds"] == final_seconds
    assert report["module_active_seconds"] == 150
    assert report["active_seconds"] == 150 + (final_seconds or 0)
    assert report["required_seconds"] == 900
    assert report["available"] is not missing_course
    assert not report["complete"]
    assert len(report["modules"]) == 15

    # Exercise the same reader through the actual group roster entry point.
    monkeypatch.setattr(reporting, "ProgressReader", lambda _: reader)
    monkeypatch.setattr(reporting.learning, "entitled", lambda _: True)
    group = {"orders": [order], "learners": [{**person, "order_id": order["id"]}]}
    summary = reporting.group_progress(SimpleNamespace(), group)[person["id"]]
    assert summary["active_time_label"] == report["active_time_label"]
    assert summary["total_modules"] == 15
    assert (order, progress) == before
    assert not Path(reader.database_path).exists()
