"""Exam scores, retakes and time remain tied to their recorded edition."""
from elearning_exam_reporting import activity_exam_seconds, exam_groups


def test_exam_time_never_uses_the_module_total_or_another_activity():
    progress = {"active_seconds": 14400, "activity_seconds": {"lesson": 13000, "exam": 1400}}
    assert activity_exam_seconds(progress, "exam") == 1400
    assert activity_exam_seconds(progress, "missing") is None
    assert activity_exam_seconds(progress, "") is None


def test_missing_and_invalid_exam_times_are_not_replaced_with_zero():
    for value in (None, -1, float("nan"), float("inf"), "invalid"):
        assert activity_exam_seconds({"activity_seconds": {"exam": value}}, "exam") is None
    assert activity_exam_seconds({"activity_seconds": {"exam": 0}}, "exam") == 0


def test_retakes_keep_all_scores_and_use_the_latest_result():
    report = {"exam_catalogue": [{"id": "module-01", "version": "v1", "title": "Module 1", "active_seconds": 1400}],
        "exams": [
            {"id": "module-01", "version": "v1", "score": 27, "total": 30, "percent": 90, "passed": True, "pass_percent": 80, "date_label": "15/10/2026 à 09:00"},
            {"id": "module-01", "version": "v1", "score": 18, "total": 30, "percent": 60, "passed": False, "pass_percent": 80, "date_label": "14/10/2026 à 09:00"}]}
    group, = exam_groups(report)
    assert group["active_seconds"] == 1400
    assert [attempt["number"] for attempt in group["attempts"]] == [1, 2]
    assert [attempt["result_label"] for attempt in group["attempts"]] == ["À retravailler", "Réussi"]
    assert group["latest"]["score_label"] == "27 / 30\n90 %"
    assert all("active_seconds" not in attempt for attempt in group["attempts"])


def test_editions_keep_separate_scores_and_durations():
    report = {"exam_catalogue": [{"id": "module-01", "version": "v2", "title": "Module 1", "active_seconds": 1800}],
              "exams": [{"id": "module-01", "version": "v1", "score": 23, "total": 30, "percent": 76.7, "passed": False}]}
    groups = {g["version"]: g for g in exam_groups(report)}
    assert groups["v1"]["active_seconds"] is None
    assert groups["v1"]["latest"]["score_label"] == "23 / 30\n76,7 %"
    assert groups["v2"]["active_seconds"] == 1800 and not groups["v2"]["attempts"]
    assert groups["v2"]["latest"]["result_label"] == "En cours"


def test_unstarted_exams_do_not_add_empty_pages():
    assert exam_groups({"exam_catalogue": [{"id": "final", "version": "v1", "active_seconds": None}]}) == []
    assert exam_groups({}) == []


def test_public_specimen_percentages_are_not_mislabelled_as_raw_scores():
    group, = exam_groups({"exams": [{"module": "Cadre légal", "score": 90, "questions": 30, "status": "Réussi", "date": "14/10/2026"}]})
    assert group["latest"]["score_label"] == "90 %"
    assert group["active_seconds"] is None
