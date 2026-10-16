"""Synthetic-only evidence, provider failure recovery, PDF and tenant tests.

Every signature-provider call is handled by FakeYousign. No message or signature
is sent by these tests, and no application learner data is loaded.
"""
from __future__ import annotations

import copy
import io
import json
import sqlite3
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, session
from pypdf import PdfReader

from elearning_native import assessment
from elearning_native.module_signature_pdf import duration, render_module_pdf
from elearning_native.module_signature_web import capture_module, register_module_signatures
from elearning_native.module_signatures import (
    ModuleSignatureStore, SignatureError, YousignModuleSignatures, build_evidence, canonical, retention_date, sha256,
)
from elearning_native.paths import project_course
from elearning_native.store import NativeElearningStore


TENANT = "centre-fictif"
COURSE_ID = "academy-aps62-99"


def source_values():
    course = {"id": COURSE_ID, "version": "fixture-v1", "title": "01 · Le cadre de la sécurité privée",
              "required_minutes": 1, "settings": {"mastery_score": 100}, "activity_order": ["lecture", "q1", "atelier"],
              "sections": [{"id": "section-1", "title": "Le rôle et les limites d’intervention", "activities": [
                  {"id": "lecture", "title": "Connaître son rôle", "scored": False, "blocks": []},
                  {"id": "q1", "title": "Quelles actions sont autorisées ?", "scored": True, "blocks": [],
                   "options": [{"id": "a", "text": "Informer et alerter"}, {"id": "b", "text": "Se substituer aux forces de l’ordre"}]},
                  {"id": "atelier", "title": "Identifier la limite de son intervention", "scored": False, "blocks": []},
              ]}]}
    diagnostic = {"attempts": 2, "incorrect_attempts": 1, "first_correct": False, "last_correct": True,
                  "first_answer": ["b"], "last_answer": ["a"], "first_submitted_at": "2026-10-12T09:00:30Z",
                  "last_submitted_at": "2026-10-12T09:00:50Z", "competency": "Limiter son intervention", "revision": "fixture-v1"}
    diagnostics = {"question": {"q1": diagnostic}, "practice": {"atelier": {"item-1": {**diagnostic, "attempts": 1, "incorrect_attempts": 0, "first_correct": True}}}}
    progress = {"module_complete": True, "status": "passed", "active_seconds": 62.2, "required_seconds": 60,
                "progress_percent": 100, "score_percent": 100, "started_at": "2026-10-12T09:00:00Z",
                "completed_at": "2026-10-12T09:01:02.2Z", "updated_at": "2026-10-12T09:01:02.2Z",
                "completed_activity_ids": course["activity_order"], "video_progress": {},
                "answers": {"q1": {"correct": True, "selected_options": ["a"]}, "atelier": {"practice_correct": True}},
                "assessment_diagnostics": diagnostics, "assessment_summary": assessment.summary_for(diagnostics)}
    attempts = [{"id": index, "activity_id": "q1" if index < 3 else "atelier", "item_id": "q1" if index < 3 else "item-1",
                 "kind": "question" if index < 3 else "practice", "attempt_number": index if index < 3 else 1,
                 "answer": {"selected": ["b"] if index == 1 else ["a"]} if index < 3 else "a", "correct": index != 1,
                 "submitted_at": "2026-10-12T09:00:50Z", "competency": "Limiter son intervention", "revision": "fixture-v1"}
                for index in range(1, 4)]
    return {"tenant_id": TENANT, "session_obj": {"id": "session-fictive", "name": "APS · octobre 2026", "date_start": "2026-10-12"},
            "trainee": {"id": "stagiaire-fictif", "first_name": "Camille", "last_name": "Martin", "email": "camille@example.test", "phone": ""},
            "provider": {"name": "Centre de formation fictif", "siret": "DONNEES-FICTIVES", "address": "Adresse de démonstration", "city": "Ville exemple"},
            "course": course, "progress": progress,
            "connections": [{"created_at": "2026-10-12T09:00:00Z", "last_seen_at": "2026-10-12T09:01:02.2Z", "ended_at": None, "credited_seconds": 62.2, "status": "open"}],
            "attempts": attempts, "responsible": {"first_name": "Alix", "last_name": "Durand", "email": "responsable@example.test", "phone": "+33600000000"},
            "cnaps_number": "PRE-EXEMPLE-FICTIF", "session_end": "2026-10-30", "origin": {"kind": "session", "id": "session-fictive"}}


def tiny_pdf(label="Données fictives"):
    from reportlab.pdfgen.canvas import Canvas
    output = io.BytesIO()
    canvas = Canvas(output)
    canvas.drawString(40, 700, label)
    canvas.showPage()
    canvas.save()
    return output.getvalue()


@pytest.fixture
def prepared(tmp_path):
    store = ModuleSignatureStore(tmp_path / "signatures.sqlite3")
    evidence = build_evidence(**source_values())
    return store, store.prepare(evidence, actor="administrateur-fictif")


class FakeYousign:
    def __init__(self):
        self.requests = []
        self.docs = []
        self.signers = []
        self.calls = []
        self.downloads = []
        self.fail_after = None
        self.fail_before = None
        self.hidden = set()
        self.bad_download = None
        self.signed_bytes = tiny_pdf("Tableau signe fictif pour test")
        self.proof_bytes = tiny_pdf("Preuve fictive pour test")

    def _yousign_is_configured(self):
        return True

    def _normalize_yousign_sms_phone(self, value):
        return value if str(value or "").startswith("+") else ""

    def _sanitize_yousign_error(self, value):
        return str(value).replace("SECRET", "***")[:800]

    def _yousign_json(self, method, path, **kwargs):
        self.calls.append((method, path, copy.deepcopy(kwargs)))
        if method == "GET":
            if path == "/signature_requests":
                expected = kwargs["params"]["external_id[eq]"]
                return {"data": [] if "create" in self.hidden else copy.deepcopy([r for r in self.requests if r["external_id"] == expected]), "meta": {"next_cursor": None}}
            if path.endswith("/documents"):
                return [] if "document" in self.hidden else copy.deepcopy(self.docs)
            if path.endswith("/signers"):
                return copy.deepcopy([s for s in self.signers if "signer_" + s["info"]["email"] not in self.hidden])
            return copy.deepcopy(self.requests[0])
        assert method == "POST", "No unplanned provider mutations"
        if path == "/signature_requests":
            step = "create"
            result = {**kwargs["json"], "id": "request-1", "status": "draft"}
            destination = self.requests
        elif path.endswith("/documents"):
            step = "document"
            assert kwargs["files"]["file"][1].startswith(b"%PDF-")
            result = {"id": "document-1", "filename": kwargs["files"]["file"][0], "nature": "signable_document",
                      "sha256": sha256(kwargs["files"]["file"][1]), "content_type": "application/pdf", "is_signed": False}
            destination = self.docs
        elif path.endswith("/signers"):
            step = "signer_" + kwargs["json"]["info"]["email"]
            result = {**kwargs["json"], "id": "signer-" + str(len(self.signers) + 1), "status": "initiated"}
            destination = self.signers
        elif path.endswith("/activate"):
            step = "activate"
            result, destination = self.requests[0], None
        else:
            raise AssertionError(path)
        if self.fail_before == step:
            self.fail_before = None
            raise TimeoutError("Échec réseau fictif avant réponse")
        if destination is not None:
            destination.append(copy.deepcopy(result))
        else:
            self.requests[0]["status"] = "ongoing"
        if self.fail_after == step:
            self.fail_after = None
            raise TimeoutError("Réponse perdue après création fictive")
        return copy.deepcopy(result)

    def _yousign_request(self, method, path, **kwargs):
        assert method == "GET"
        self.downloads.append(path)
        if self.bad_download and self.bad_download in path:
            return SimpleNamespace(content=b"<html>Provider failure</html>")
        return SimpleNamespace(content=self.proof_bytes if "/audit_trails/" in path else self.signed_bytes)

    def finish(self, *, both=True):
        self.requests[0].update(status="done", completed_at="2026-10-12T12:00:00Z")
        for index, signer in enumerate(self.signers):
            if both or index == 0:
                signer.update(status="signed", signed_at="2026-10-12T12:00:00Z")


def post_counts(fake):
    result = {}
    for method, path, _ in fake.calls:
        if method == "POST":
            result[path] = result.get(path, 0) + 1
    return result


def test_prepare_is_immutable_and_idempotent_without_sending(prepared):
    store, record = prepared
    second = store.prepare(build_evidence(**source_values()), actor="other-admin")
    assert record["id"] == second["id"]
    assert record["status"] == "prepared" and record["state"] == {}
    assert record["actor"] == "administrateur-fictif"
    assert record["evidence"]["assessment_attempts"][0]["correct"] is False
    assert record["evidence"]["progress"]["assessment_summary"]["first_attempt_score_percent"] == 0
    assert record["pdf_sha256"] == sha256(record["pdf"])
    with store.connect() as db:
        with pytest.raises(sqlite3.IntegrityError, match="figés"):
            db.execute("UPDATE module_signature_snapshots SET pdf=? WHERE id=?", (tiny_pdf("replacement"), record["id"]))
        with pytest.raises(sqlite3.IntegrityError, match="Conservation"):
            db.execute("DELETE FROM module_signature_snapshots WHERE id=?", (record["id"],))
    with pytest.raises(SignatureError, match="introuvable"):
        store.get("autre-organisme", record["id"])


@pytest.mark.parametrize("change", [
    {"cnaps_number": ""}, {"cnaps_number": "NUB 00000"}, {"session_end": ""},
    {"responsible": {"first_name": "A", "last_name": "B", "email": "camille@example.test"}},
    {"responsible": {"first_name": "", "last_name": "B", "email": "other@example.test"}},
])
def test_required_identity_two_recipients_and_retention_date(change):
    values = source_values()
    values.update(change)
    with pytest.raises(SignatureError):
        build_evidence(**values)


@pytest.mark.parametrize("status,complete", [("awaiting_time", False), ("failed", True), ("in_progress", False)])
def test_unfinished_or_failed_module_cannot_generate_signature_table(status, complete):
    values = source_values()
    values["progress"].update(status=status, module_complete=complete)
    with pytest.raises(SignatureError, match="Terminez"):
        build_evidence(**values)


def test_retention_is_three_years_from_end_including_leap_day():
    assert retention_date("2028-02-29") == "2031-02-28"
    assert retention_date("2026-10-30") == "2029-10-30"


def test_pdf_contains_actual_first_failure_final_result_connections_and_empty_signature_fields(prepared):
    _, record = prepared
    pages = PdfReader(io.BytesIO(record["pdf"])).pages
    text = " ".join(page.extract_text() for page in pages)
    assert len(pages) >= 4
    for required in ("Camille Martin", "Alix Durand", "PRE-EXEMPLE-FICTIF", "2029-10-30", "Premier essai enregistré",
                     "après correction : 100 %", "Questions - essais enregistrés : 2; erreurs avant correction : 1", "Ateliers - essais enregistrés : 1", "Erreur",
                     "Non enregistrée", "00 h 01 min 02,20 s"):
        assert required in text
    assert record["source_hash"] in text and record["id"] in text
    assert "Signature confirmée" not in text
    for role in ("learner", "responsible"):
        field = record["fields"][role]
        assert field["page"] == len(pages)
        assert 0 < field["x"] < float(pages[-1].mediabox.width) - field["width"]
        assert 0 < field["y"] < float(pages[-1].mediabox.height) - field["height"]
    assert record["fields"]["learner"]["x"] + record["fields"]["learner"]["width"] < record["fields"]["responsible"]["x"]
    assert duration(.6) == "00 h 00 min 00,60 s"


def test_long_pdf_keeps_all_attempts_and_connections_without_inventing_history(tmp_path):
    values = source_values()
    values["attempts"] = [{**values["attempts"][0], "id": index, "answer": "Réponse-" + str(index), "attempt_number": index} for index in range(1, 126)]
    values["connections"] = [{**values["connections"][0], "created_at": "Connexion-" + str(index), "credited_seconds": .6} for index in range(1, 76)]
    record = ModuleSignatureStore(tmp_path / "long.sqlite3").prepare(build_evidence(**values))
    pages = PdfReader(io.BytesIO(record["pdf"])).pages
    text = " ".join(page.extract_text() for page in pages)
    assert "Réponse-125" in text and "Connexion-75" in text
    assert "00 h 00 min 45 s" in text
    assert record["fields"]["learner"]["page"] == len(pages)


def test_sending_uses_two_real_otp_signers_and_never_resends(prepared):
    store, record = prepared
    fake = FakeYousign()
    signer = YousignModuleSignatures(fake, store)
    result = signer.send(TENANT, record["id"], actor="admin")
    assert result["status"] == "ongoing" and "two_signatures_confirmed_at" not in result["state"]
    assert len(fake.requests) == 1 and len(fake.docs) == 1 and len(fake.signers) == 2
    assert {s["signature_authentication_mode"] for s in fake.signers} == {"otp_email", "otp_sms"}
    assert {s["info"]["email"] for s in fake.signers} == {"camille@example.test", "responsable@example.test"}
    assert all(s["signature_level"] == "electronic_signature" for s in fake.signers)
    original_counts = post_counts(fake)
    signer.send(TENANT, record["id"], actor="admin")
    assert post_counts(fake) == original_counts
    assert all("/sign" != path[-5:] for _, path, _ in fake.calls)


@pytest.mark.parametrize("step", ["create", "document", "signer_camille@example.test", "signer_responsable@example.test", "activate"])
def test_lost_response_recovers_exact_remote_objects_without_duplicates(prepared, step):
    store, record = prepared
    fake = FakeYousign()
    fake.fail_after = step
    service = YousignModuleSignatures(fake, store)
    with pytest.raises(SignatureError):
        service.send(TENANT, record["id"])
    resumed = service.send(TENANT, record["id"])
    assert resumed["status"] == "ongoing"
    assert len(fake.requests) == 1 and len(fake.docs) == 1 and len(fake.signers) == 2
    assert post_counts(fake)["/signature_requests"] == 1
    assert post_counts(fake)["/signature_requests/request-1/documents"] == 1
    assert post_counts(fake)["/signature_requests/request-1/signers"] == 2
    assert post_counts(fake)["/signature_requests/request-1/activate"] == 1


@pytest.mark.parametrize("step", ["create", "document", "signer_camille@example.test", "signer_responsable@example.test"])
def test_uncertain_missing_remote_result_blocks_duplicate_creation(prepared, step):
    store, record = prepared
    fake = FakeYousign()
    fake.fail_after = step
    service = YousignModuleSignatures(fake, store)
    with pytest.raises(SignatureError):
        service.send(TENANT, record["id"])
    before = post_counts(fake)
    fake.hidden.add(step)
    with pytest.raises(SignatureError, match="incertain"):
        service.send(TENANT, record["id"])
    assert post_counts(fake) == before
    fake.hidden.clear()
    assert service.send(TENANT, record["id"])["status"] == "ongoing"


def test_concurrent_send_has_one_durable_lease(prepared):
    store, record = prepared
    fake = FakeYousign()
    with store.lease(TENANT, record["id"]):
        with pytest.raises(SignatureError, match="déjà en cours"):
            YousignModuleSignatures(fake, store).send(TENANT, record["id"])
    assert fake.calls == []


def test_done_provider_request_without_both_signatures_never_becomes_signed(prepared):
    store, record = prepared
    fake = FakeYousign()
    service = YousignModuleSignatures(fake, store)
    service.send(TENANT, record["id"])
    fake.finish(both=False)
    with pytest.raises(SignatureError, match="deux signatures"):
        service.refresh(TENANT, record["id"])
    current = store.get(TENANT, record["id"])
    assert current["status"] == "ongoing"
    assert not current["state"].get("two_signatures_confirmed_at") and fake.downloads == []


def test_changed_signer_or_foreign_request_cannot_be_accepted(prepared):
    store, record = prepared
    fake = FakeYousign()
    service = YousignModuleSignatures(fake, store)
    service.send(TENANT, record["id"])
    fake.finish()
    fake.signers[1]["id"] = "another-signer"
    with pytest.raises(SignatureError, match="identité"):
        service.refresh(TENANT, record["id"])
    fake.requests[0]["external_id"] = "another-table"
    with pytest.raises(SignatureError, match="correspond pas"):
        service.refresh(TENANT, record["id"])
    assert fake.downloads == []


def test_signed_downloads_and_individual_proofs_are_archived_once_and_immutable(prepared):
    store, record = prepared
    fake = FakeYousign()
    service = YousignModuleSignatures(fake, store)
    service.send(TENANT, record["id"])
    fake.finish()
    signed = service.refresh(TENANT, record["id"])
    assert signed["status"] == "signed"
    assert store.artifact(TENANT, record["id"], "tableau-signe") == fake.signed_bytes
    assert len(fake.downloads) == 3
    service.refresh(TENANT, record["id"])
    assert len(fake.downloads) == 3
    with store.connect() as db:
        events = [r[0] for r in db.execute("SELECT event FROM module_signature_events WHERE snapshot_id=?", (record["id"],))]
        assert events.count("two_signatures_confirmed") == 1 and events.count("archive_complete") == 1
        with pytest.raises(sqlite3.IntegrityError, match="Conservation"):
            db.execute("DELETE FROM module_signature_artifacts WHERE snapshot_id=?", (record["id"],))
    zipped = zipfile.ZipFile(io.BytesIO(store.archive(TENANT, record["id"])))
    assert set(zipped.namelist()) == {"tableau-original.pdf", "tableau-signe.pdf", "preuve-learner.pdf", "preuve-responsible.pdf",
                                     "traces-figees.json", "journal-signature.json", "empreintes-sha256.json"}
    hashes = json.loads(zipped.read("empreintes-sha256.json"))
    assert all(sha256(zipped.read(name)) == digest for name, digest in hashes.items())


def test_failed_artifact_retrieval_stays_pending_and_resumes_without_new_signatures(prepared):
    store, record = prepared
    fake = FakeYousign()
    service = YousignModuleSignatures(fake, store)
    service.send(TENANT, record["id"])
    fake.finish()
    fake.bad_download = "/signers/signer-2/"
    waiting = service.refresh(TENANT, record["id"])
    assert waiting["status"] == "signed_pending_archive"
    assert waiting["state"]["two_signatures_confirmed_at"]
    assert store.artifact(TENANT, record["id"], "preuve-responsible") is None
    posts = post_counts(fake)
    fake.bad_download = None
    assert service.refresh(TENANT, record["id"])["status"] == "signed"
    assert len(fake.downloads) == 4 and post_counts(fake) == posts


@pytest.mark.parametrize("tampering", ["different-id", "different-hash", "attachment", "no-hash", "wrong-filename"])
def test_recovery_refuses_replaced_or_unverified_remote_document(prepared, tampering):
    store, record = prepared
    fake = FakeYousign()
    fake.fail_before = "signer_camille@example.test"
    service = YousignModuleSignatures(fake, store)
    with pytest.raises(SignatureError):
        service.send(TENANT, record["id"])
    doc = fake.docs[0]
    if tampering == "different-id": doc["id"] = "replacement-id"
    if tampering == "different-hash": doc["sha256"] = "0" * 64
    if tampering == "attachment": doc["nature"] = "attachment"
    if tampering == "no-hash": doc.pop("sha256")
    if tampering == "wrong-filename": doc["filename"] = "another-table.pdf"
    before = post_counts(fake)
    with pytest.raises(SignatureError):
        service.send(TENANT, record["id"])
    assert post_counts(fake) == before and fake.signers == []


def test_lost_upload_requires_matching_original_hash_before_first_document_id_is_known(prepared):
    store, record = prepared
    fake = FakeYousign()
    fake.fail_after = "document"
    service = YousignModuleSignatures(fake, store)
    with pytest.raises(SignatureError):
        service.send(TENANT, record["id"])
    assert not store.get(TENANT, record["id"])["state"].get("document_id")
    assert "filename" in fake.docs[0] and "name" not in fake.docs[0]
    fake.docs[0]["sha256"] = "0" * 64
    with pytest.raises(SignatureError, match="empreinte"):
        service.send(TENANT, record["id"])
    assert fake.signers == []


def test_archiving_requires_the_original_document_id_but_accepts_signed_byte_hash(prepared):
    store, record = prepared
    fake = FakeYousign()
    service = YousignModuleSignatures(fake, store)
    service.send(TENANT, record["id"])
    fake.finish()
    fake.docs[0].update(id="foreign-document", sha256=sha256(fake.signed_bytes), is_signed=True)
    with pytest.raises(SignatureError, match="remplacé"):
        service.refresh(TENANT, record["id"])
    assert fake.downloads == []
    fake.docs[0]["id"] = "document-1"
    assert service.refresh(TENANT, record["id"])["status"] == "signed"


@pytest.mark.parametrize("changed", ["name", "phone", "otp"])
def test_changed_signer_identity_or_authentication_is_not_accepted(prepared, changed):
    store, record = prepared
    fake = FakeYousign()
    service = YousignModuleSignatures(fake, store)
    service.send(TENANT, record["id"])
    fake.finish()
    if changed == "name": fake.signers[1]["info"]["last_name"] = "AnotherPerson"
    if changed == "phone": fake.signers[1]["info"]["phone_number"] = "+33799999999"
    if changed == "otp": fake.signers[1]["signature_authentication_mode"] = "no_otp"
    with pytest.raises(SignatureError):
        service.refresh(TENANT, record["id"])
    assert fake.downloads == []


def test_expired_request_can_be_reissued_once_with_same_facts_and_new_explicit_send(prepared):
    store, record = prepared
    with pytest.raises(SignatureError, match="clôturée"):
        store.reissue(TENANT, record["id"])
    with store.lease(TENANT, record["id"]) as owner:
        store.save_state(record["id"], owner, {}, "expired")
    replacement = store.reissue(TENANT, record["id"], actor="new-admin")
    repeated = store.reissue(TENANT, record["id"], actor="new-admin")
    assert replacement["id"] == repeated["id"] != record["id"]
    assert replacement["status"] == "prepared" and replacement["state"] == {}
    assert replacement["evidence"]["reissued_from"] == record["id"]
    for fact in ("progress", "assessment_attempts", "connections", "learner", "responsible", "course", "retention_until"):
        assert replacement["evidence"][fact] == record["evidence"][fact]
    assert store.get(TENANT, record["id"])["status"] == "expired"
    fake = FakeYousign()
    assert YousignModuleSignatures(fake, store).send(TENANT, replacement["id"])["status"] == "ongoing"
    assert len(fake.requests) == 1


def seed_tracking(path, access, course):
    store = NativeElearningStore(path)
    started = store.start_tracking(access, tab_id="synthetic", activity_id="lecture", now_epoch=1791795600)
    with store._connect() as db:
        for option, correct, number in ((["b"], False, 1), (["a"], True, 2)):
            assessment.record_attempt(db, access, activity_id="q1", item_id="q1", kind="question", answer=option,
                correct=correct, submitted_at=f"2026-10-12T09:00:{number * 20}Z", request_id="request-" + str(number))
        db.execute("""UPDATE learner_course_progress SET active_seconds=62.2,completed_json=?,answers_json=?,status='passed',score_percent=100
            WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?""",
            (json.dumps(course["activity_order"]), json.dumps(source_values()["progress"]["answers"]), *store._key_values(access)))
        db.execute("UPDATE tracking_sessions SET credited_seconds=62.2 WHERE id=?", (started["tracking_session_id"],))
    return store


def test_capture_selects_only_matching_pinned_module_and_preserves_database(tmp_path):
    values = source_values()
    course = values["course"]
    access = {"session_id": "session-fictive", "trainee_id": "stagiaire-fictif", "course_id": COURSE_ID, "course_version": "fixture-v1"}
    path = tmp_path / "tracking.sqlite3"
    store = seed_tracking(path, access, course)
    for foreign in ({**access, "course_version": "other-version"}, {**access, "trainee_id": "other-person"}, {**access, "session_id": "other-session"}):
        seed_tracking(path, foreign, course)
    with store._connect() as db:
        before = list(db.iterdump())
    progress, connections, attempts = capture_module(path, access, course)
    with store._connect() as db:
        after = list(db.iterdump())
    assert before == after
    assert progress["module_complete"] and progress["active_seconds"] == 62.2
    assert len(connections) == 1 and len(attempts) == 2
    assert progress["assessment_summary"]["first_attempt_score_percent"] == 0
    assert attempts[0]["correct"] is False and attempts[1]["correct"] is True


@pytest.fixture
def web(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(repo / "templates"), static_folder=str(repo / "static"))
    app.config.update(SECRET_KEY="synthetic-only", TESTING=True)
    app.add_url_rule("/admin/login", endpoint="admin_login", view_func=lambda: "login")
    values = source_values()
    person = {**values["trainee"], "partner_id": TENANT, "activated_at": "2026-10-12T09:00:00Z"}
    assignment = {"course_id": COURSE_ID, "course_version": "fixture-v1", "required_minutes": 1}
    sess = {**values["session_obj"], "partner_id": TENANT, "training_type": "APS", "date_end": "2026-10-30", "trainees": [person], "aps_native_modules": [assignment]}
    order = {"id": "order-fictif", "partner_id": TENANT, "order_type": "elearning", "status": "confirmed", "course_code": "aps",
             "total_cents": 0, "free_snapshot": True, "modules": [assignment], "learners": [person], "date_end": "2026-10-30"}
    provider = {**values["provider"], "id": TENANT, "contact_first_name": "Alix", "contact_last_name": "Durand", "contact_email": "responsable@example.test"}
    data = {"partners": [provider, {"id": "other-centre", "name": "Other"}], "sessions": [sess], "manual_orders": [order]}
    fake = FakeYousign()
    host = SimpleNamespace(app=app, PERSIST_DIR=tmp_path, INTEGRALE_PARTNER_ID="internal", _current_partner_id=lambda: session.get("partner_id"),
        load_data=lambda run_background_tasks=False: copy.deepcopy(data), find_session=lambda d, sid: next((s for s in d["sessions"] if s["id"] == sid), None),
        _session_trainees_list=lambda s: s.get("trainees", []), _trainee_registration_is_cancelled=lambda p: p.get("registration_cancelled") is True,
        **{name: getattr(fake, name) for name in ("_yousign_is_configured", "_yousign_json", "_yousign_request", "_sanitize_yousign_error", "_normalize_yousign_sms_phone")})
    register_module_signatures(host)
    course = values["course"]
    root = tmp_path / "native_elearning"
    coursepath = root / "courses" / COURSE_ID / "fixture-v1"
    coursepath.mkdir(parents=True)
    (coursepath / "course.json").write_text(json.dumps(course), encoding="utf-8")
    for sid in (sess["id"], "el-" + order["id"]):
        seed_tracking(root / "tracking.sqlite3", {"session_id": sid, "trainee_id": person["id"], "course_id": COURSE_ID, "course_version": "fixture-v1"}, course)
    client = app.test_client()
    with client.session_transaction() as browser_session:
        browser_session.update(admin_logged_in=True, admin_role="admin", partner_id=TENANT, admin_username="synthetic-admin")
    base = f"/admin/elearning/signatures-modules/sessions/{sess['id']}/stagiaires/{person['id']}"
    store = ModuleSignatureStore(root / "module_signatures.sqlite3")
    return SimpleNamespace(app=app, client=client, host=host, fake=fake, data=data, person=person, sess=sess, order=order, store=store, base=base)


def prepare_form(client):
    with client.session_transaction() as browser_session:
        token = browser_session["module_signatures_csrf"]
    return {"csrf_token": token, "cnaps_number": "PRE-FICTIF", "session_end": "2026-10-30",
            "responsible_first_name": "Alix", "responsible_last_name": "Durand", "responsible_email": "responsable@example.test"}


def displayed_prepare_fields(html):
    from html.parser import HTMLParser

    class FormParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.active, self.fields = False, None

        def handle_starttag(self, tag, attributes):
            attrs = dict(attributes)
            if tag == "form" and self.fields is None and "prepare-form" in attrs.get("class", "").split():
                self.active, self.fields = True, {}
            if self.active and tag == "input" and attrs.get("name"):
                self.fields[attrs["name"]] = attrs.get("value", "")

        def handle_endtag(self, tag):
            if tag == "form":
                self.active = False

    parser = FormParser()
    parser.feed(html)
    assert parser.fields is not None
    return parser.fields


def test_admin_ui_prepare_review_then_explicit_send(web):
    assert web.app.config["NATIVE_MODULE_SIGNATURES_ENABLED"] is True
    page = web.client.get(web.base)
    assert page.status_code == 200 and "Préparer le tableau" in page.get_data(as_text=True)
    assert web.fake.calls == []
    submitted = web.client.post(web.base + "/modules/" + COURSE_ID + "/preparer", data=prepare_form(web.client))
    assert submitted.status_code == 303 and web.fake.calls == []
    record = web.store.list_for(TENANT, web.sess["id"], web.person["id"])[0]
    page = web.client.get(web.base)
    assert "responsable@example.test" in page.get_data(as_text=True)
    path = "/admin/elearning/signatures-modules/tableaux/" + record["id"]
    assert web.client.get(path + ".pdf").data.startswith(b"%PDF-")
    assert web.client.get(path + "/signe.pdf").status_code == 404
    assert web.client.post(path + "/envoyer", data=prepare_form(web.client)).status_code == 400
    assert web.fake.calls == []
    assert web.client.post(path + "/envoyer", data={**prepare_form(web.client), "confirm_send": "yes"}).status_code == 303
    assert len(web.fake.signers) == 2


def test_scope_csrf_viewer_and_cancelled_registration_guards(web):
    web.client.get(web.base)
    target = web.base + "/modules/" + COURSE_ID + "/preparer"
    assert web.client.post(target, data={}).status_code == 400
    with web.client.session_transaction() as browser_session:
        browser_session["admin_role"] = "viewer"
    assert web.client.post(target, data=prepare_form(web.client)).status_code == 403
    with web.client.session_transaction() as browser_session:
        browser_session["admin_role"] = "admin"
    web.data["sessions"][0]["trainees"][0]["registration_cancelled"] = True
    assert web.client.post(target, data=prepare_form(web.client)).status_code == 403
    with web.client.session_transaction() as browser_session:
        browser_session["partner_id"] = "other-centre"
    assert web.client.get(web.base).status_code == 404
    assert web.fake.calls == []


def test_archived_documents_remain_tenant_scoped_after_origin_is_removed(web):
    web.client.get(web.base)
    web.client.post(web.base + "/modules/" + COURSE_ID + "/preparer", data=prepare_form(web.client))
    record = web.store.list_for(TENANT, web.sess["id"], web.person["id"])[0]
    url = "/admin/elearning/signatures-modules/tableaux/" + record["id"]
    web.data["sessions"].clear()
    assert web.client.get(url + ".pdf").status_code == 200
    assert web.client.get(url + "/archive.zip").status_code == 200
    with web.client.session_transaction() as browser_session:
        browser_session["partner_id"] = "other-centre"
    assert web.client.get(url + ".pdf").status_code == 404
    assert web.client.get(url + "/archive.zip").status_code == 404


def test_of_only_account_uses_its_purchased_access_and_cannot_open_crm_session(web):
    with web.client.session_transaction() as browser_session:
        browser_session["manuals_only"] = True
    assert web.client.get(web.base).status_code == 403
    order_url = f"/admin/elearning/signatures-modules/commandes/{web.order['id']}/stagiaires/{web.person['id']}"
    assert web.client.get(order_url).status_code == 200
    assert web.client.post(order_url + "/modules/" + COURSE_ID + "/preparer", data=prepare_form(web.client)).status_code == 303
    assert len(web.store.list_for(TENANT, "el-" + web.order["id"], web.person["id"])) == 1
    web.data["manual_orders"][0]["status"] = "cancelled"
    assert web.client.post(order_url + "/modules/" + COURSE_ID + "/preparer", data=prepare_form(web.client)).status_code == 403
    assert web.fake.calls == []


def test_new_preparation_defaults_prefer_current_of_contact_over_old_snapshot(web):
    web.client.get(web.base)
    web.client.post(web.base + "/modules/" + COURSE_ID + "/preparer", data=prepare_form(web.client))
    previous = web.store.list_for(TENANT, web.sess["id"], web.person["id"])[0]
    web.data["partners"][0].update(contact_first_name="Nouveau", contact_last_name="Responsable", contact_email="nouveau@example.test", phone="+33700000000")
    html = web.client.get(web.base).get_data(as_text=True)
    assert 'name="responsible_first_name" autocomplete="given-name" value="Nouveau"' in html
    assert 'name="responsible_email" autocomplete="email" value="nouveau@example.test"' in html
    assert web.store.get(TENANT, previous["id"])["evidence"]["responsible"]["email"] == "responsable@example.test"


def test_new_contact_without_phone_never_inherits_previous_signers_sms_number(web):
    web.client.get(web.base)
    old_form = {**prepare_form(web.client), "responsible_phone": "+33600000000"}
    prepare_url = web.base + "/modules/" + COURSE_ID + "/preparer"
    web.client.post(prepare_url, data=old_form)
    previous = web.store.list_for(TENANT, web.sess["id"], web.person["id"])[0]
    web.data["partners"][0].update(contact_first_name="Nouveau", contact_last_name="Responsable",
                                   contact_email="nouveau@example.test", phone="")
    html = web.client.get(web.base).get_data(as_text=True)
    fields = displayed_prepare_fields(html)
    assert fields["responsible_first_name"] == "Nouveau"
    assert fields["responsible_email"] == "nouveau@example.test"
    assert fields["responsible_phone"] == ""
    web.client.post(prepare_url, data=fields)
    current = next(record for record in web.store.list_for(TENANT, web.sess["id"], web.person["id"])
                   if record["id"] != previous["id"])
    assert current["evidence"]["responsible"]["phone"] == ""
    web.client.post("/admin/elearning/signatures-modules/tableaux/" + current["id"] + "/envoyer",
                    data={**prepare_form(web.client), "confirm_send": "yes"})
    signer = next(person for person in web.fake.signers if person["info"]["email"] == "nouveau@example.test")
    assert signer["signature_authentication_mode"] == "otp_email"
    assert not signer["info"].get("phone_number")
    assert web.store.get(TENANT, previous["id"])["evidence"]["responsible"]["phone"] == "+33600000000"


def test_previous_contact_is_reused_only_as_whole_block_when_current_block_is_empty(web):
    web.client.get(web.base)
    web.client.post(web.base + "/modules/" + COURSE_ID + "/preparer",
                    data={**prepare_form(web.client), "responsible_phone": "+33600000000"})
    web.data["partners"][0].update(contact_first_name="", contact_last_name="", contact_email="", email="", phone="")
    fields = displayed_prepare_fields(web.client.get(web.base).get_data(as_text=True))
    assert {key: fields["responsible_" + key] for key in ("first_name", "last_name", "email", "phone")} == {
        "first_name": "Alix", "last_name": "Durand", "email": "responsable@example.test", "phone": "+33600000000"}


def test_reissue_web_action_is_explicit_scoped_and_never_sends(web):
    web.client.get(web.base)
    web.client.post(web.base + "/modules/" + COURSE_ID + "/preparer", data=prepare_form(web.client))
    previous = web.store.list_for(TENANT, web.sess["id"], web.person["id"])[0]
    with web.store.lease(TENANT, previous["id"]) as owner:
        web.store.save_state(previous["id"], owner, {}, "expired")
    action = "/admin/elearning/signatures-modules/tableaux/" + previous["id"] + "/reediter"
    assert "Rééditer ce tableau" in web.client.get(web.base).get_data(as_text=True)
    assert web.client.post(action, data={}).status_code == 400
    for _ in range(2):
        assert web.client.post(action, data=prepare_form(web.client)).status_code == 303
    records = web.store.list_for(TENANT, web.sess["id"], web.person["id"])
    assert len(records) == 2 and web.fake.calls == []
    with web.client.session_transaction() as browser_session:
        browser_session["partner_id"] = "other-centre"
    assert web.client.post(action, data=prepare_form(web.client)).status_code == 404


def test_unauthenticated_requests_redirect_before_reading_learner(web):
    with web.client.session_transaction() as browser_session:
        browser_session.clear()
    assert web.client.get(web.base).status_code == 302
    assert web.fake.calls == []
