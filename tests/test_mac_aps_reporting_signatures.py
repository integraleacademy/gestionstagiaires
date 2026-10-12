"""MAC APS reports and factual signatures: synthetic learners and FakeYousign."""
from __future__ import annotations

import io
import json
import re
import sqlite3
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pypdf import PdfReader

from elearning_reporting import ProgressReader, certificate_pdf
from elearning_native import mac_aps
from elearning_native.exams import ExamStore
from elearning_native.module_signature_web import capture_module
from elearning_native.module_signatures import ModuleSignatureStore, SignatureError, YousignModuleSignatures, build_evidence
from elearning_native.paths import project_course, project_progress
from elearning_native.store import NativeElearningStore
from elearning_native.videos import course_videos
from test_native_module_signatures import FakeYousign, TENANT, prepare_form, source_values, web


def assignment(course):
    return {"course_id": course["id"], "course_version": course["version"],
            "title": course["title"], "required_minutes": course["required_minutes"],
            "section_ids": [section["id"] for section in course["sections"]]}


def values_for(number="03", *, fraction=1):
    values = source_values()
    course = mac_aps.load_bundled_course("academy-macaps-" + number, mac_aps.VERSION)
    course = project_course(course, assignment(course))
    ledger = {objective["activity_ids"][0]: objective["required_seconds"] * fraction for objective in course["timed_objectives"]}
    answers = {activity["id"]: {"correct": True, "selected_options": ["a"]}
               for section in course["sections"] for activity in section["activities"] if activity.get("scored")}
    video_progress = {activity_id: {video_id: {"completed": True, "duration_seconds": seconds, "watched_seconds": seconds}
                                   for video_id, seconds in requirements.items()}
                      for activity_id, requirements in course_videos(course).items()}
    raw = {"active_seconds": course["required_minutes"] * 60 * fraction,
           "activity_seconds": ledger, "answers": answers, "completed_activity_ids": course["activity_order"],
           "video_progress": video_progress, "assessment_diagnostics": {},
           "started_at": "2026-10-12T09:00:00Z", "updated_at": "2026-10-12T13:00:00Z"}
    values.update(course=course, progress=project_progress(raw, course), attempts=[], cnaps_number="CAR-EXEMPLE-FICTIF")
    values["session_obj"].update(name="MAC APS - données fictives", training_type="MAC APS")
    values["connections"] = [{"created_at": raw["started_at"], "last_seen_at": raw["updated_at"], "ended_at": None,
                               "credited_seconds": raw["active_seconds"], "status": "open"}]
    return values


def seed_progress(root, session_id, learner_id, course, progress):
    """Write test evidence only; application read routes never manufacture it."""
    store = NativeElearningStore(root / "tracking.sqlite3")
    access = {"session_id": session_id, "trainee_id": learner_id, "course_id": course["id"], "course_version": course["version"]}
    tracking = store.start_tracking(access, tab_id="synthetic-only", activity_id=course["activity_order"][0], now_epoch=1791795600)
    with store._connect() as db:
        db.execute("""UPDATE learner_course_progress SET active_seconds=?, activity_seconds_json=?,
                   completed_json=?, answers_json=?, video_progress_json=?, status='passed', score_percent=100
                   WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?""",
                   (progress["active_seconds"], json.dumps(progress.get("activity_seconds") or {}),
                    json.dumps(progress["completed_activity_ids"]), json.dumps(progress.get("answers") or {}),
                    json.dumps(progress.get("video_progress") or {}), *store._key_values(access)))
        db.execute("UPDATE tracking_sessions SET credited_seconds=? WHERE id=?", (progress["active_seconds"], tracking["tracking_session_id"]))
    return access


def reporting_values(tmp_path, *, fraction=1, complement=False):
    root = tmp_path / "native_elearning"
    values = values_for(fraction=fraction)
    person = {**values["trainee"], "activated_at": "2026-10-12T09:00:00Z"}
    order = {"id": "mac-order-fictif", "course_code": "mac-aps", "partner_id": TENANT,
             "group_name": "MAC APS fictif", "modules": [], "learners": [person]}
    for number in ("02", "03", "05"):
        module = values_for(number, fraction=fraction)
        order["modules"].append(assignment(module["course"]))
        seed_progress(root, "el-" + order["id"], person["id"], module["course"], module["progress"])
    if complement:
        course = mac_aps.load_bundled_course("academy-macaps-complement-01", mac_aps.VERSION)
        order["modules"].append(assignment(course))
        seed_progress(root, "el-" + order["id"], person["id"], course,
                      {"active_seconds": 600, "completed_activity_ids": [], "answers": {}, "video_progress": {}})
    return root, order, person, values["provider"]


def database_dump(path):
    with sqlite3.connect(path) as db:
        return list(db.iterdump())


def pdf_text(data):
    return re.sub(r"\s+", " ", " ".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages))


def test_mac_report_pins_final_exam_scope_objective_times_and_excludes_complements(tmp_path):
    root, order, person, _ = reporting_values(tmp_path, complement=True)
    exams = ExamStore(root / "tracking.sqlite3")
    attempts = [
        ("el-" + order["id"], person["id"], "macaps-final", mac_aps.VERSION),
        ("el-" + order["id"], person["id"], "macaps-module-03", mac_aps.VERSION),
        ("el-" + order["id"], person["id"], "final", mac_aps.VERSION),
        ("el-" + order["id"], person["id"], "vtc-final", mac_aps.VERSION),
        ("el-" + order["id"], person["id"], "macaps-final", mac_aps.LEGACY_VERSION),
        ("el-other-order", person["id"], "macaps-final", mac_aps.VERSION),
        ("el-" + order["id"], "other-person", "macaps-final", mac_aps.VERSION),
    ]
    for index, (sid, pid, exam_id, version) in enumerate(attempts, 1):
        exams.save(sid, pid, {"id": exam_id, "version": version}, f"{index:032x}",
                   {"score": 83, "total": 100, "percent": 83, "passed": True,
                    "corrections": [{"answer": "PRIVATE-ANSWER-NOT-FOR-REPORT"}]})
    before = database_dump(root / "tracking.sqlite3")
    report = ProgressReader(SimpleNamespace(PERSIST_DIR=tmp_path)).report(order, person)
    assert report["required_seconds"] == report["active_seconds"] == 840 * 60
    assert report["complete"] and report["completed_modules"] == report["total_modules"] == 3
    assert len(report["complement_modules"]) == len(report["complement_connections"]) == 1
    assert len(report["connections"]) == 3
    assert report["complement_active_time_label"] == "00 h 10 min 00 s"
    assert sum(len(module["timed_objectives"]) for module in report["modules"]) == 10
    assert all(objective["complete"] for module in report["modules"] for objective in module["timed_objectives"])
    assert {exam["id"] for exam in report["exams"]} == {"macaps-final", "macaps-module-03"}
    assert all(exam["version"] == mac_aps.VERSION for exam in report["exams"])
    assert any(exam["title"] == "Examen blanc final MAC APS" for exam in report["exams"])
    assert "PRIVATE-ANSWER" not in json.dumps(report)
    assert database_dump(root / "tracking.sqlite3") == before


def test_old_tracking_schema_does_not_invent_objective_time_or_migrate_on_read(tmp_path):
    root, order, person, _ = reporting_values(tmp_path)
    with sqlite3.connect(root / "tracking.sqlite3") as db:
        db.execute("ALTER TABLE learner_course_progress DROP COLUMN activity_seconds_json")
    before = database_dump(root / "tracking.sqlite3")
    report = ProgressReader(SimpleNamespace(PERSIST_DIR=tmp_path)).report(order, person)
    assert report["active_seconds"] == 840 * 60 and not report["complete"]
    assert report["completed_modules"] == 0
    assert all(objective["active_seconds"] == 0 for module in report["modules"] for objective in module["timed_objectives"])
    assert database_dump(root / "tracking.sqlite3") == before


def test_mac_v1_report_remains_pinned_to_its_five_old_modules(tmp_path):
    _, order, person, _ = reporting_values(tmp_path)
    legacy = mac_aps.curriculum_manifest(mac_aps.LEGACY_VERSION)
    order["modules"] = [{"course_id": module["id"], "course_version": mac_aps.LEGACY_VERSION,
                         "required_minutes": module["planned_minutes"]} for module in legacy["modules"]]
    report = ProgressReader(SimpleNamespace(PERSIST_DIR=tmp_path)).report(order, person)
    assert report["total_modules"] == 5 and report["required_seconds"] == 735 * 60
    assert report["active_seconds"] == 0
    assert report["versions"] == [mac_aps.LEGACY_VERSION]
    assert not report["complete"]


def test_mac_specimen_pdf_has_tenant_branding_actual_hours_objectives_and_final(tmp_path):
    root, order, person, provider = reporting_values(tmp_path, fraction=.5, complement=True)
    ExamStore(root / "tracking.sqlite3").save("el-" + order["id"], person["id"],
        {"id": "macaps-final", "version": mac_aps.VERSION}, "a" * 32,
        {"score": 67, "total": 100, "percent": 67, "passed": False})
    report = ProgressReader(SimpleNamespace(PERSIST_DIR=tmp_path)).report(order, person)
    logo = tmp_path / "logo.png"
    Image.new("RGB", (240, 80), (30, 80, 140)).save(logo)
    data = certificate_pdf(report, provider, order, person, specimen=True, logo_path=logo)
    reader = PdfReader(io.BytesIO(data))
    text = pdf_text(data)
    assert report["active_seconds"] == 7 * 3600 and not report["complete"]
    for value in (provider["name"], "MAC APS", "07 h 00 min 00 s", "14 h 00 min 00 s", "parcours non terminé",
                  "Examen blanc final MAC APS", "67 / 100", "Compléments pédagogiques", "Temps actif des compléments",
                  "ni une attestation de stage MAC APS ni une attestation SST", mac_aps.VERSION):
        assert value in text
    for module in report["modules"]:
        for objective in module["timed_objectives"]:
            assert re.sub(r"\s+", " ", objective["title"]) in text
    assert reader.metadata.author == provider["name"]
    assert "Relevé de suivi numérique MAC APS" in reader.metadata.title
    assert any(obj.get_object().get("/Subtype") == "/Image" for page in reader.pages
               for obj in page.get("/Resources", {}).get("/XObject", {}).values())
    for page in reader.pages:
        assert "SPECIMEN" in page.extract_text() and "DONNÉES FICTIVES" in page.extract_text()


def test_mac_signature_freezes_pedagogical_scope_and_real_objective_times(tmp_path):
    values = values_for()
    fake = FakeYousign()
    store = ModuleSignatureStore(tmp_path / "signatures.sqlite3")
    record = store.prepare(build_evidence(**values))
    assert not fake.calls and record["state"] == {} and record["status"] == "prepared"
    evidence = record["evidence"]
    assert evidence["training_label"] == "MAC APS" and evidence["pedagogical_scope"] == "principal"
    assert evidence["regulation"] == {"scope": "pedagogical_support", "automatic_stage_credit": False, "automatic_certificate": False}
    assert evidence["progress"]["timed_objectives"] == values["progress"]["timed_objectives"]
    assert evidence["progress"]["activity_seconds"] == values["progress"]["activity_seconds"]
    assert evidence["retention_until"] == "2029-10-30"
    text = pdf_text(record["pdf"])
    for value in ("Tableau de suivi du parcours numérique", values["provider"]["name"], "MAC APS",
                  "DURÉE CIBLE NUMÉRIQUE", "04 h 00 min 00 s", "Suivi du temps par objectif",
                  "ni une attestation de stage MAC APS ni une attestation SST", "2029-10-30"):
        assert value in text
    assert "Formation APS asynchrone" not in text
    assert "Référence : article 8" not in text
    with store.connect() as db:
        with pytest.raises(sqlite3.IntegrityError, match="Conservation"):
            db.execute("DELETE FROM module_signature_snapshots WHERE id=?", (record["id"],))


def test_mac_signature_rejects_unfinished_objectives_and_complement(tmp_path):
    values = values_for(fraction=.5)
    values["progress"].update(module_complete=True, status="passed", active_seconds=14 * 3600)
    with pytest.raises(SignatureError, match="chaque objectif"):
        build_evidence(**values)
    values = values_for()
    values["course"]["id"] = "academy-macaps-complement-03"
    with pytest.raises(SignatureError, match="principaux"):
        build_evidence(**values)


def test_mac_retention_end_cannot_precede_actual_evidence_or_assigned_end():
    values = values_for()
    values["session_end"] = "2026-10-11"
    with pytest.raises(SignatureError, match="dernières activités"):
        build_evidence(**values)
    values["session_end"] = "2026-10-30"
    values["session_obj"]["date_end"] = "2026-11-01"
    with pytest.raises(SignatureError, match="dernières activités"):
        build_evidence(**values)


def test_mac_signed_state_requires_both_signatures_and_all_archived_artifacts(tmp_path):
    store = ModuleSignatureStore(tmp_path / "signatures.sqlite3")
    record = store.prepare(build_evidence(**values_for()))
    fake = FakeYousign()
    service = YousignModuleSignatures(fake, store)
    sent = service.send(TENANT, record["id"], actor="synthetic-admin")
    assert sent["status"] == "ongoing"
    assert fake.requests[0]["external_id"] == "native-mac-aps-module-" + record["id"]
    assert fake.requests[0]["name"].startswith("Suivi MAC APS")
    assert fake.docs[0]["filename"] == "tableau-mac-aps-module-" + record["id"] + ".pdf"
    fake.finish()
    fake.bad_download = "signer-2/audit_trails"
    pending = service.refresh(TENANT, record["id"])
    assert pending["status"] == "signed_pending_archive" and pending["state"]["two_signatures_confirmed_at"]
    assert not pending["state"].get("archived_at")
    fake.bad_download = None
    signed = service.refresh(TENANT, record["id"])
    assert signed["status"] == "signed" and signed["state"]["archived_at"]
    archive = zipfile.ZipFile(io.BytesIO(store.archive(TENANT, record["id"])))
    assert {"tableau-signe.pdf", "preuve-learner.pdf", "preuve-responsible.pdf", "traces-figees.json"}.issubset(archive.namelist())
    assert json.loads(archive.read("traces-figees.json"))["regulation"]["automatic_stage_credit"] is False
    with pytest.raises(SignatureError, match="introuvable"):
        store.archive("another-tenant", record["id"])
    with store.connect() as db:
        with pytest.raises(sqlite3.IntegrityError, match="Conservation"):
            db.execute("DELETE FROM module_signature_artifacts WHERE snapshot_id=?", (record["id"],))


@pytest.fixture
def mac_web(web):
    values = values_for()
    selected = assignment(values["course"])
    web.sess.update(training_type="MAC APS", name="Session MAC APS fictive", aps_native_modules=[selected])
    web.order.update(course_code="mac-aps", modules=[selected], total_cents=6000, unit_cents=6000, free_snapshot=False,
                     commerce={"invoice_id": "invoice-fictive", "invoice_status": "paid", "payment_status": "paid",
                               "paid_cents": 6000, "remaining_cents": 0})
    root = Path(web.host.PERSIST_DIR) / "native_elearning"
    for sid in (web.sess["id"], "el-" + web.order["id"]):
        seed_progress(root, sid, web.person["id"], values["course"], values["progress"])
    return web


def test_mac_signature_order_and_session_paths_are_scoped_and_send_is_explicit(mac_web):
    web = mac_web
    order_url = f"/admin/elearning/signatures-modules/commandes/{web.order['id']}/stagiaires/{web.person['id']}"
    course_id = "academy-macaps-03"
    assert "MAC APS" in web.client.get("/admin/elearning/signatures-modules").text
    for base in (web.base, order_url):
        page = web.client.get(base)
        assert page.status_code == 200 and "ni une attestation SST" in page.text
    target = order_url + "/modules/" + course_id + "/preparer"
    assert web.client.post(target, data={}).status_code == 400
    assert web.client.post(target, data=prepare_form(web.client)).status_code == 303
    records = web.store.list_for(TENANT, "el-" + web.order["id"], web.person["id"])
    assert len(records) == 1 and not web.fake.calls
    record = records[0]
    snapshot_url = "/admin/elearning/signatures-modules/tableaux/" + record["id"]
    assert web.client.get(snapshot_url + ".pdf").status_code == 200
    assert "tableau-mac-aps-" in web.client.get(snapshot_url + ".pdf").headers["Content-Disposition"]
    assert web.client.post(snapshot_url + "/envoyer", data=prepare_form(web.client)).status_code == 400
    assert not web.fake.calls
    web.order["modules"] = [{**web.order["modules"][0], "course_version": mac_aps.LEGACY_VERSION}]
    assert web.client.post(snapshot_url + "/envoyer", data={**prepare_form(web.client), "confirm_send": "yes"}).status_code == 403
    assert not web.fake.calls
    web.data["manual_orders"] = []
    assert web.client.get(snapshot_url + "/archive.zip").status_code == 200
    with web.client.session_transaction() as browser_session:
        browser_session["partner_id"] = "other-centre"
    assert web.client.get(snapshot_url + ".pdf").status_code == 404
    assert web.client.get(snapshot_url + "/archive.zip").status_code == 404


def test_mac_capture_preserves_activity_ledger_with_no_other_edition_or_session(tmp_path):
    root, order, person, _ = reporting_values(tmp_path)
    values = values_for("05")
    access = {"session_id": "el-" + order["id"], "trainee_id": person["id"],
              "course_id": values["course"]["id"], "course_version": mac_aps.VERSION}
    seed_progress(root, "el-other-order", person["id"], values["course"], values["progress"])
    before = database_dump(root / "tracking.sqlite3")
    progress, connections, _ = capture_module(root / "tracking.sqlite3", access, values["course"])
    assert progress["module_complete"] and len(progress["timed_objectives"]) == 8
    assert progress["activity_seconds"] == values["progress"]["activity_seconds"]
    assert len(connections) == 1
    assert database_dump(root / "tracking.sqlite3") == before
