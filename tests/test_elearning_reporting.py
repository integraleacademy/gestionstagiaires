"""Real native tracking, immutable assignments and tenant-isolated exports."""
import copy
import io
import json
import sqlite3
from pathlib import Path

import pytest
from pypdf import PdfReader

import app as host
import elearning_orders as learning
import elearning_reporting as reporting
from elearning_native.exams import ExamStore
from elearning_native.store import NativeElearningStore
from test_elearning_orders import latest, submit
from test_manuals_commerce import run
from test_manuals_shop import all_data, login, shop, signup


def report_url(order, person=None):
    return f"/admin/organisme/e-learning/commandes/{order['id']}/stagiaires/{(person or order['learners'][0])['id']}/suivi"


def activated(shop):
    order = submit(shop, free=True)
    run(order)
    return latest(shop)


def seed_course(order):
    """A purchased selection differs from both full course and latest version."""
    root = Path(host.PERSIST_DIR) / "native_elearning"
    course = {"id": "report-fixture", "version": "v1", "title": "La sécurité privée", "mock_exam_id": "module-01",
              "settings": {"mastery_score": 80}, "sections": [
                  {"id": "selected", "title": "La séquence commandée", "activities": [
                      {"id": "read", "title": "Connaître son rôle", "type": "content", "blocks": []},
                      {"id": "question", "title": "Vérifier ses connaissances", "type": "question", "scored": True}]},
                  {"id": "excluded", "title": "Hors commande", "activities": [
                      {"id": "excluded-activity", "title": "Activité exclue", "type": "content", "blocks": []}]}]}
    for version in ("v1", "v2"):
        directory = root / "courses" / course["id"] / version
        directory.mkdir(parents=True)
        (directory / "course.json").write_text(json.dumps({**course, "version": version}))
    (root / "courses" / course["id"] / "current.json").write_text(json.dumps({"version": "v2"}))
    assignment = {"course_id": course["id"], "course_version": "v1", "title": "Module de la commande",
                  "section_ids": ["selected"], "required_minutes": 1}
    def mutate(data):
        stored = next(o for o in data["manual_orders"] if o["id"] == order["id"])
        stored["modules"] = [assignment]
    host._atomic_update_data(mutate, partner_id=order["partner_id"])
    return {**order, "modules": [assignment]}, root


def tracked(root, order, *, version="v1", learner_id=None, session_id=None, complete=True):
    store = NativeElearningStore(root / "tracking.sqlite3")
    access = {"session_id": session_id or "el-" + order["id"], "trainee_id": learner_id or order["learners"][0]["id"],
              "course_id": "report-fixture", "course_version": version}
    tracking = store.start_tracking(access, tab_id="private-tab-nonce", activity_id="read", now_epoch=1_000)
    for epoch in (1_000, 1_015, 1_030):
        store.heartbeat(access, tracking["tracking_session_id"], activity_id="read", visible=True,
                        focused=True, recent_activity=True, media_playing=False, now_epoch=epoch)
    if complete:
        store.complete_activity(access, "read", activity_order=["read", "question"], scored_activity_ids=["question"], mastery_score=80, required_seconds=60)
        store.complete_activity(access, "question", activity_order=["read", "question"], scored_activity_ids=["question"], mastery_score=80, required_seconds=60, answer={"correct": True})
    return store, access, tracking


def database_dump(root):
    with sqlite3.connect(root / "tracking.sqlite3") as db:
        return list(db.iterdump())


def test_activated_access_without_activity_is_not_complete_and_does_not_create_tracking(shop):
    order = activated(shop)
    root = Path(host.PERSIST_DIR) / "native_elearning"
    response = shop["client"].get(report_url(order))
    assert response.status_code == 200, response.text
    assert "Non commencé" in response.text and "0 %" in response.text
    assert "Aucune connexion" in response.text and "Aucun examen blanc" in response.text
    assert not (root / "tracking.sqlite3").exists()
    token = learning.access_token(host, order, order["learners"][0])
    assert token not in response.text and order["learners"][0]["token_hash"] not in response.text
    with shop["client"].session_transaction() as session:
        assert not session.get("public_auth_" + token)


def test_real_progress_pinned_selection_active_time_and_exam_results_are_read_only(shop):
    order, root = seed_course(activated(shop))
    store, access, _ = tracked(root, order)
    # Data for another edition, another enrolment, and another person must not leak.
    tracked(root, order, version="v2")
    tracked(root, order, session_id="el-another-order")
    tracked(root, order, learner_id=order["learners"][1]["id"])
    exam_store = ExamStore(root / "tracking.sqlite3")
    exam_store.save(access["session_id"], access["trainee_id"], {"id": "module-01", "version": "v1"}, "1" * 32,
                    {"score": 23, "total": 30, "percent": 76.7, "passed": True, "corrections": [{"answer": "SECRET-ANSWER"}]})
    exam_store.save(access["session_id"], access["trainee_id"], {"id": "module-01", "version": "v2"}, "2" * 32,
                    {"score": 1, "total": 30, "percent": 3.3, "passed": False})
    before = database_dump(root)
    report = reporting.ProgressReader(host).report(order, order["learners"][0])
    assert report["progress_percent"] == 100
    assert report["total_activities"] == report["completed_activities"] == 2
    assert report["active_seconds"] == 30
    assert report["completed_modules"] == 0 and not report["complete"]
    assert report["modules"][0]["status"] == "awaiting_time"
    assert len(report["connections"]) == len(report["exams"]) == 1
    assert report["exams"][0]["percent"] == 76.7
    html = shop["client"].get(report_url(order))
    assert html.status_code == 200, html.text
    assert "76.7" in html.text and "00 h 00 min 30 s" in html.text
    assert "SECRET-ANSWER" not in html.text and "private-tab-nonce" not in html.text
    assert "Activité exclue" not in html.text
    csv = shop["client"].get(report_url(order) + "/connexions.csv")
    assert csv.status_code == 200 and csv.text.count("Module de la commande") == 1
    pdf = shop["client"].get(report_url(order) + "/attestation.pdf")
    assert pdf.status_code == 200 and pdf.mimetype == "application/pdf"
    text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.data)).pages)
    assert "Relevé de suivi partiel" in text and "00 h 00 min 30 s" in text
    assert "0 / 1" in text and "parcours non terminé" in text
    assert database_dump(root) == before


def test_full_completion_uses_actual_time_and_missing_snapshot_cannot_fall_back(shop):
    order, root = seed_course(activated(shop))
    store, access, tracking = tracked(root, order)
    for epoch in (1_045, 1_060):
        store.heartbeat(access, tracking["tracking_session_id"], activity_id="question", visible=True,
                        focused=True, recent_activity=True, media_playing=False, now_epoch=epoch)
    report = reporting.ProgressReader(host).report(order, order["learners"][0])
    assert report["complete"] and report["completed_modules"] == 1 and report["active_seconds"] == 60
    broken = copy.deepcopy(order)
    broken["modules"][0].pop("course_version")
    report = reporting.ProgressReader(host).report(broken, order["learners"][0])
    assert not report["complete"] and not report["available"] and report["progress_percent"] is None


def test_report_and_exports_are_tenant_scoped_and_require_activation(shop):
    order = submit(shop, free=True)
    url = report_url(order)
    for suffix in ("", "/attestation.pdf", "/connexions.csv"):
        assert shop["client"].get(url + suffix).status_code == 404
    run(order)
    order = latest(shop)
    other = host.app.test_client()
    signup(other, email="other-report@example.test")
    login(other, email="other-report@example.test")
    anonymous = host.app.test_client()
    for suffix in ("", "/attestation.pdf", "/connexions.csv"):
        assert other.get(url + suffix).status_code == 404
        assert anonymous.get(url + suffix).status_code == 302
        assert shop["client"].get(url.replace(order["learners"][0]["id"], "wrong-person") + suffix).status_code == 404
        own = shop["client"].get(url + suffix)
        assert own.status_code == 200
        assert "no-store" in own.headers["Cache-Control"]
        assert own.headers["Referrer-Policy"] == "no-referrer"


def test_csv_prevents_spreadsheet_formula_execution(shop):
    order, root = seed_course(activated(shop))
    tracked(root, order)
    def title(data):
        saved = next(o for o in data["manual_orders"] if o["id"] == order["id"])
        saved["modules"][0]["title"] = "=HYPERLINK(unsafe)"
    host._atomic_update_data(title, partner_id=order["partner_id"])
    result = shop["client"].get(report_url(order) + "/connexions.csv")
    assert "'=HYPERLINK(unsafe)" in result.text


def test_required_video_evidence_cannot_be_replaced_by_legacy_completion(shop):
    order, root = seed_course(activated(shop))
    tracked(root, order)
    path = root / "courses" / "report-fixture" / "v1" / "course.json"
    course = json.loads(path.read_text())
    course["sections"][0]["activities"][0]["blocks"] = [{"id": "video", "type": "video", "video": {
        "id": "video", "required": True, "duration_seconds": 60}}]
    path.write_text(json.dumps(course))
    report = reporting.ProgressReader(host).report(order, order["learners"][0])
    assert report["progress_percent"] == 50 and not report["complete"]
    assert report["modules"][0]["total_videos"] == 1 and report["modules"][0]["completed_videos"] == 0
