"""Real authenticated routes, tenant entitlement and CMA copy persistence."""
import copy
import hashlib
import json
import re
import sqlite3
from unittest.mock import patch

import pytest

import elearning_orders
from elearning_native import vtc, vtc_cma as cma
from elearning_native.store import NativeElearningStore
from elearning_native.vtc_ai import VtcAIError
from elearning_native.vtc_cma_web import CORRECTION_UNAVAILABLE
from tests import test_native_elearning_web as web_tests
from tests.test_vtc_cma import fake_grade, full_answers


BASE = "/espace/public-token/elearning/vtc/simulation-cma"


@pytest.fixture
def case():
    fixture = web_tests.NativeElearningWebTests(methodName="runTest")
    fixture.setUp()
    fixture.data["sessions"][0].update(training_type="VTC", aps_native_modules=[
        {"course_id": m["id"], "course_version": m["version"]} for m in vtc.curriculum_manifest()["modules"]])
    fixture._public_login()
    try:
        yield fixture
    finally:
        fixture.tearDown()


def page_config(case, *, url=BASE):
    response = case.client.get(url)
    assert response.status_code == 200, response.text[:1000]
    match = re.search(r'<script type="application/json" id="cmaConfig">(.*?)</script>', response.text, re.S)
    assert match
    return response, json.loads(match[1])


def post(case, config, url, **data):
    return case.client.post(url, json={"version": config["bank"]["version"], **data},
                            headers={"X-Elearning-CSRF": config["csrfToken"]})


def start(case, *, url=BASE):
    _, config = page_config(case, url=url)
    response = post(case, config, config["startUrl"])
    assert response.status_code == 200, response.text[:1000]
    return config, response.json["state"]


def complete(case, *, written=True):
    config, state = start(case)
    for subject in cma.load_bank()["subjects"]:
        letter = subject["id"]
        if letter != "A":
            response = post(case, config, state["urls"]["start_part"], subject=letter)
            assert response.status_code == 200, response.text[:1000]
            state = response.json["state"]
        response = post(case, config, state["urls"]["submit"], subject=letter, revision=0,
                        answers=full_answers(subject, written=written))
        assert response.status_code == 200, response.text[:1000]
        state = response.json["state"]
    return config, state


def test_ui_explains_full_format_and_reveals_only_timed_current_paper(case):
    response, config = page_config(case)
    assert "3 h 50" in response.text and "91 QCM + 16 QRC" in response.text
    assert "105 h" in response.text and "cinq fautes" in response.text
    assert "no-store" in response.headers["Cache-Control"]
    assert all("questions" not in s for s in config["bank"]["subjects"])
    assert not config["preview"]
    config, state = start(case)
    assert state["current_subject"] == "A" and len(state["paper"]["questions"]) == 15
    assert "result" not in state and "rubric" not in json.dumps(state)
    assert "model_response" not in json.dumps(state)
    assert "G-qrc-01" not in json.dumps(state)
    assert cma.load_bank()["subjects"][0]["questions"][0]["explanation"] not in json.dumps(state)
    assert post(case, config, state["urls"]["grade"], subject="A").status_code == 409


def test_qrc_save_resume_and_server_deadline_ignore_client_metadata(case):
    config, state = start(case)
    deadline = state["parts"][0]["deadline"]
    answers = {"A-qrc-01": "La RC circulation couvre les dommages causés avec le véhicule."}
    response = post(case, config, state["urls"]["save"], subject="A", revision=0, answers=answers,
                    deadline=deadline + 900_000, status="submitted", score=20)
    assert response.status_code == 200
    saved = response.json["state"]
    assert saved["parts"][0]["deadline"] == deadline and saved["parts"][0]["status"] == "running"
    _, reloaded = page_config(case, url=BASE + "?attempt=" + state["id"])
    assert reloaded["state"]["answers"] == answers
    assert reloaded["state"]["parts"][0]["deadline"] == deadline
    resumed = post(case, config, config["startUrl"]).json["state"]
    assert resumed["id"] == state["id"] and resumed["parts"][0]["revision"] == 1
    response = post(case, config, state["urls"]["save"], subject="A", revision=0, answers={})
    assert response.status_code == 409 and response.json["code"] == "revision_conflict"
    assert case.client.get(state["urls"]["state"]).json["state"]["answers"] == answers


def test_http_timer_expiry_locks_saved_copy_and_opens_next_subject_only_on_start(case):
    config, state = start(case)
    response = post(case, config, state["urls"]["save"], subject="A", revision=0, answers={"A-qrc-01": "Avant échéance"})
    assert response.status_code == 200
    deadline = state["parts"][0]["deadline"]
    with patch("elearning_native.vtc_cma.time.time", return_value=deadline + 1):
        late = post(case, config, state["urls"]["submit"], subject="A", revision=1, answers={"A-qrc-01": "Après échéance"})
    assert late.status_code == 200, late.text
    after = late.json["state"]
    assert after["current_subject"] == "B" and "paper" not in after
    db = cma.CmaStore(case.persist_dir / "native_elearning" / "tracking.sqlite3")
    saved = db.read("session-aps", "trainee-1", state["id"])
    assert saved["parts"]["A"]["answers"]["A-qrc-01"] == "Avant échéance"
    started = post(case, config, state["urls"]["start_part"], subject="B").json["state"]
    assert started["paper"]["id"] == "B"


def test_full_flow_five_qrc_corrections_and_course_progress_unchanged(case):
    # Access to the simulation must not add completion/time to the 105 h modules.
    dbpath = case.persist_dir / "native_elearning" / "tracking.sqlite3"
    before = NativeElearningStore(dbpath).learner_progress("session-aps", "trainee-1")
    frozen = copy.deepcopy(case.data)
    config, state = complete(case)
    assert state["status"] == "submitted"
    assert state["result"]["pending_subjects"] == ["A", "B", "D", "F", "G"]
    assert state["result"]["weighted_average"] is None and state["result"]["passed"] is None
    with patch("elearning_native.vtc_ai.grade_written_work", side_effect=fake_grade) as grade:
        for letter in ["A", "B", "D", "F", "G"]:
            result = post(case, config, state["urls"]["grade"], subject=letter)
            assert result.status_code == 200, result.text[:1000]
            state = result.json["state"]
        assert grade.call_count == 5
        again = post(case, config, state["urls"]["grade"], subject="A")
        assert again.status_code == 200 and grade.call_count == 5
    assert state["result"]["weighted_average"] == 20 and state["result"]["passed"] is True
    assert state["result"]["subjects"][-1]["corrections"][-1]["lesson_links"]
    after = NativeElearningStore(dbpath).learner_progress("session-aps", "trainee-1")
    assert after == before
    assert case.data == frozen
    with sqlite3.connect(dbpath) as db:
        assert db.execute("SELECT count(*) FROM vtc_cma_attempts").fetchone()[0] == 1
    _, reloaded = page_config(case, url=BASE + "?attempt=" + state["id"])
    assert reloaded["state"]["result"]["passed"] is True
    assert case.client.get("/espace/public-token/elearning/exams/vtc-final").status_code == 403


def test_unavailable_ai_preserves_copies_without_mark_and_retry_succeeds(case):
    config, state = complete(case)
    with patch("elearning_native.vtc_ai.grade_written_work", side_effect=VtcAIError("timeout")):
        response = post(case, config, state["urls"]["grade"], subject="A")
    assert response.status_code == 503
    assert response.json["error"] == CORRECTION_UNAVAILABLE
    assert not re.search(r"\bIA\b|OpenAI|ChatGPT|formateur", response.json["error"], re.I)
    result = response.json["state"]["result"]
    assert result["passed"] is None and result["weighted_average"] is None
    assert result["subjects"][0]["score"] is None and result["subjects"][0]["grading_status"] == "unavailable"
    assert result["subjects"][0]["corrections"][-1]["selected"]
    with patch("elearning_native.vtc_ai.grade_written_work", side_effect=fake_grade):
        retried = post(case, config, state["urls"]["grade"], subject="A")
    assert retried.status_code == 200
    assert retried.json["state"]["result"]["subjects"][0]["score"] == 20


def test_legacy_uncertain_cma_result_can_be_finished_by_the_learner(case):
    config, state = complete(case)
    bank = cma.load_bank()
    dbpath = case.persist_dir / "native_elearning" / "tracking.sqlite3"
    # Reproduce a persisted pre-upgrade attempt, without issuing a new
    # uncertain correction through the current grading contract.
    with sqlite3.connect(dbpath) as db:
        saved = json.loads(db.execute("SELECT state_json FROM vtc_cma_attempts WHERE attempt_id=?", (state["id"],)).fetchone()[0])
        answers = copy.deepcopy(saved["parts"]["A"]["answers"])
        for letter in ["A", "B", "D", "F", "G"]:
            part = saved["parts"][letter]
            part["correction"] = cma.grade_subject(bank, letter, part["answers"], qrc_grader=fake_grade)
            part["grading_status"] = "corrected"
        old = saved["parts"]["A"]
        old["correction"].update(status="needs_human_review", minimum_met=None)
        old["correction"]["ai_feedback"].update(status="needs_human_review", needs_human_review=True)
        old.update(grading_status="needs_human_review", grading_error="La correction IA est indisponible.")
        db.execute("UPDATE vtc_cma_attempts SET state_json=? WHERE attempt_id=?", (json.dumps(saved), state["id"]))
    result = case.client.get(state["urls"]["state"]).json["state"]["result"]
    assert result["review_subjects"] == ["A"] and result["passed"] is None
    assert result["subjects"][0]["grading_error"] == CORRECTION_UNAVAILABLE
    with patch("elearning_native.vtc_ai.grade_written_work", side_effect=fake_grade) as grade:
        corrected = post(case, config, state["urls"]["grade"], subject="A")
        assert corrected.status_code == 200, corrected.text
        assert grade.call_count == 1
        assert corrected.json["state"]["result"]["passed"] is True
        assert corrected.json["state"]["result"]["weighted_average"] == 20
        assert corrected.json["state"]["result"]["review_subjects"] == []
        assert post(case, config, state["urls"]["grade"], subject="A").status_code == 200
        assert grade.call_count == 1
    restored = cma.CmaStore(dbpath).read("session-aps", "trainee-1", state["id"])
    assert restored["parts"]["A"]["answers"] == answers


def test_preview_unavailable_correction_uses_neutral_retry_message(case):
    case._admin_login()
    _, config = page_config(case, url="/admin/elearning/vtc/simulation-cma")
    subject = cma.subject_for(cma.load_bank(), "G")
    with patch("elearning_native.vtc_ai.grade_written_work", side_effect=VtcAIError("invalid_response")):
        response = post(case, config, config["previewGradeUrl"], subject="G", answers=full_answers(subject))
    assert response.status_code == 503
    assert response.json["error"] == "La correction est momentanément indisponible. Réessayez dans quelques instants."
    assert not re.search(r"\bIA\b|OpenAI|ChatGPT|formateur", response.json["error"], re.I)


@pytest.mark.parametrize("boundary", ["unassigned", "future", "disabled", "anonymous"])
def test_current_assignment_date_and_auth_are_checked_for_every_read_and_write(case, boundary):
    config, state = start(case)
    current = case.data["sessions"][0]
    if boundary == "unassigned":
        current["aps_native_modules"] = current["aps_native_modules"][:6]
    elif boundary == "future":
        current["date_start"] = "2099-01-01"
    elif boundary == "disabled":
        current["aps_elearning_enabled"] = False
    else:
        with case.client.session_transaction() as browser:
            browser.pop("public_auth_public-token")
    expected = 401 if boundary == "anonymous" else 403
    assert case.client.get(BASE).status_code == expected
    assert case.client.get(state["urls"]["state"]).status_code == expected
    assert post(case, config, state["urls"]["save"], subject="A", revision=0, answers={}).status_code == expected
    assert post(case, config, state["urls"]["grade"], subject="A").status_code == expected


def test_csrf_version_oversize_and_cross_trainee_attempt_are_rejected(case):
    config, state = start(case)
    assert case.client.post(state["urls"]["save"], json={"answers": {}}).status_code == 403
    assert post(case, config, state["urls"]["save"], subject="A", revision=0, answers={}, version="obsolete").status_code == 409
    assert post(case, config, state["urls"]["save"], subject="A", revision=0, answers={"A-qrc-01": "x" * 100_000}).status_code == 413
    other = copy.deepcopy(case.data["sessions"][0]); other["id"] = "other-session"
    other["trainees"][0].update(id="other-trainee", public_token="other-token")
    case.data["sessions"].append(other)
    with case.client.session_transaction() as browser:
        browser["public_auth_other-token"] = True
    url = state["urls"]["state"].replace("public-token", "other-token")
    assert case.client.get(url).status_code == 404
    assert post(case, config, state["urls"]["grade"].replace("public-token", "other-token"), subject="A").status_code == 404
    _, other_config = page_config(case, url=BASE.replace("public-token", "other-token"))
    assert other_config["state"] is None


def test_admin_preview_uses_no_student_database_and_viewer_cannot_invoke_ai(case):
    case._admin_login()
    with patch("elearning_native.vtc_cma_web.cma.CmaStore", side_effect=AssertionError("Preview touched tracking")):
        response, config = page_config(case, url="/admin/elearning/vtc/simulation-cma")
        assert config["preview"]
        assert len(config["bank"]["subjects"]) == 7
        assert "rubric" not in json.dumps(config)
        with patch("elearning_native.vtc_ai.grade_written_work", side_effect=fake_grade) as grade:
            subject = cma.subject_for(cma.load_bank(), "G")
            result = post(case, config, config["previewGradeUrl"], subject="G", answers=full_answers(subject))
            assert result.status_code == 200, result.text
            assert result.json["result"]["score"] == 20
            assert grade.call_count == 1
        with case.client.session_transaction() as browser:
            browser["admin_role"] = "viewer"
        with patch("elearning_native.vtc_ai.grade_written_work", side_effect=AssertionError("Viewer invoked AI")):
            assert post(case, config, config["previewGradeUrl"], subject="G", answers={}).status_code == 403
        assert case.client.get("/admin/elearning/vtc/simulation-cma").status_code == 200
    assert case.saved_data is None


def test_admin_timed_trial_resumes_and_expires_without_touching_learner_records(case):
    case._admin_login()
    path = case.persist_dir / "native_elearning" / "tracking.sqlite3"
    before = path.read_bytes() if path.exists() else None
    config, state = start(case, url="/admin/elearning/vtc/simulation-cma")
    assert all(url.startswith("/api/admin/") for url in state["urls"].values())
    assert state["parts"][0]["deadline"] - state["parts"][0]["started_at"] == 45 * 60
    answers = {"A-qrc-01": "Réponse avant la fin du temps."}
    saved = post(case, config, state["urls"]["save"], subject="A", revision=0, answers=answers)
    assert saved.status_code == 200
    assert post(case, config, config["startUrl"]).json["state"]["id"] == state["id"]
    _, reloaded = page_config(case, url="/admin/elearning/vtc/simulation-cma?attempt=" + state["id"])
    assert reloaded["state"]["answers"] == answers
    assert reloaded["state"]["parts"][0]["deadline"] == state["parts"][0]["deadline"]
    assert post(case, config, state["urls"]["start_part"], subject="B").status_code == 409
    assert post(case, config, state["urls"]["grade"], subject="A").status_code == 409
    with patch("elearning_native.vtc_cma.time.time", return_value=state["parts"][0]["deadline"] + 1):
        late = post(case, config, state["urls"]["submit"], subject="A", revision=1,
                    answers={"A-qrc-01": "Réponse hors délai"})
    assert late.status_code == 200
    assert late.json["state"]["current_subject"] == "B" and "paper" not in late.json["state"]
    with case.client.session_transaction() as browser:
        owner = browser["cma_preview_owner"]
    trial = cma.CmaStore(case.persist_dir / "native_elearning" / "cma_admin_preview.sqlite3").read("admin-preview", owner, state["id"])
    assert trial["parts"]["A"]["answers"] == answers
    assert trial["parts"]["A"]["status"] == "expired"
    assert (path.read_bytes() if path.exists() else None) == before
    assert case.saved_data is None


def test_admin_timed_trial_requires_csrf_version_role_and_own_session(case):
    case._admin_login()
    config, state = start(case, url="/admin/elearning/vtc/simulation-cma")
    assert case.client.post(config["startUrl"], json={"version": config["bank"]["version"]}).status_code == 403
    assert post(case, config, config["startUrl"], version="obsolete").status_code == 409
    with case.client.session_transaction() as browser:
        browser["admin_role"] = "viewer"
    assert post(case, config, config["startUrl"]).status_code == 403
    for action in ["save", "submit", "start_part", "pause", "resume", "reset", "grade"]:
        assert post(case, config, state["urls"][action], subject="A", revision=0, answers={}).status_code == 403
    with case.client.session_transaction() as browser:
        browser["admin_role"] = "admin"
        browser.pop("cma_preview_owner")
    assert case.client.get(state["urls"]["state"]).status_code == 404
    other = post(case, config, config["startUrl"]).json["state"]
    assert other["id"] != state["id"]
    assert case.client.get(state["urls"]["state"]).status_code == 404
    with case.client.session_transaction() as browser:
        browser.pop("admin_logged_in")
    assert case.client.get(other["urls"]["state"]).status_code in [302, 401, 403]


def test_admin_timed_trial_completes_seven_papers_before_corrections(case):
    case._admin_login()
    config, state = start(case, url="/admin/elearning/vtc/simulation-cma")
    for subject in cma.load_bank()["subjects"]:
        letter = subject["id"]
        if letter != "A":
            state = post(case, config, state["urls"]["start_part"], subject=letter).json["state"]
        assert state["parts"][ord(letter) - ord("A")]["deadline"] - state["server_now"] <= subject["minutes"] * 60
        state = post(case, config, state["urls"]["submit"], subject=letter, revision=0,
                     answers=full_answers(subject)).json["state"]
        if letter != "G":
            assert "result" not in state
    assert state["status"] == "submitted"
    with patch("elearning_native.vtc_ai.grade_written_work", side_effect=fake_grade):
        for letter in ["A", "B", "D", "F", "G"]:
            result = post(case, config, state["urls"]["grade"], subject=letter)
            assert result.status_code == 200
            state = result.json["state"]
    assert state["result"]["weighted_average"] == 20
    assert state["result"]["subjects"][0]["corrections"][0]["lesson_links"][0]["url"].startswith("/admin/")


def test_admin_work_lists_cma_only_learner_without_creating_course_progress(case):
    _, state = start(case)
    dbpath = case.persist_dir / "native_elearning" / "tracking.sqlite3"
    def progress_count():
        with sqlite3.connect(dbpath.as_uri() + "?mode=ro", uri=True) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='learner_course_progress'").fetchone()
            return db.execute("SELECT count(*) FROM learner_course_progress").fetchone()[0] if exists else 0
    assert progress_count() == 0
    case._admin_login()
    response = case.client.get("/admin/elearning/courses/academy-vtc-a/work")
    assert response.status_code == 200, response.text[:1000]
    assert "Alice Martin" in response.text and "Simulations CMA" in response.text
    assert state["id"] in response.text
    assert progress_count() == 0


def test_organisation_real_order_resolver_scopes_history_and_revocation(case):
    host = web_tests.gestion_app
    person = {"id": "partner-learner", "first_name": "Camille", "last_name": "Test",
              "email": "camille@example.test", "activated_at": "2000-01-01T00:00:00Z"}
    order = {"id": "vtc-order", "order_type": "elearning", "status": "received", "partner_id": "centre-vtc",
             "course_code": "vtc", "group_name": "VTC organisme", "free_snapshot": True, "total_cents": 0,
             "modules": [{"course_id": m["id"], "course_version": m["version"]} for m in vtc.curriculum_manifest()["modules"]], "learners": [person]}
    token = elearning_orders.access_token(host, order, person)
    person["token_hash"] = hashlib.sha256(token.encode()).hexdigest()
    case.data.update(partners=[{"id": "centre-vtc", "name": "Centre VTC test", "status": "active"}], manual_orders=[order])
    with case.client.session_transaction() as browser:
        browser["public_auth_" + token] = True
    frozen = copy.deepcopy(case.data)
    config, state = start(case, url=BASE.replace("public-token", token))
    db = cma.CmaStore(case.persist_dir / "native_elearning" / "tracking.sqlite3")
    assert db.history("el-vtc-order", "partner-learner")[0]["id"] == state["id"]
    assert db.history("session-aps", "trainee-1") == []
    order["status"] = "cancelled"
    assert case.client.get(state["urls"]["state"]).status_code == 404
    assert post(case, config, state["urls"]["save"], subject="A", revision=0, answers={}).status_code == 404
    order["status"] = "received"
    case.data["partners"][0]["status"] = "disabled"
    assert case.client.get(state["urls"]["state"]).status_code == 404
    case.data["partners"][0]["status"] = "active"
    assert case.data == frozen


@pytest.mark.parametrize('admin', [False, True])
def test_clock_pause_resume_and_real_reset_are_persisted_and_protected(case, admin):
    url = BASE
    if admin:
        case._admin_login()
        url = '/admin/elearning/vtc/simulation-cma'
    config, state = start(case, url=url)
    response, _ = page_config(case, url=url)
    assert 'Examen en conditions réelles' in response.text
    assert 'Remettre à zéro' in response.text and 'Valider mes réponses' in response.text
    assert 'sans pause' not in response.text and 'Tester les conditions' not in response.text
    for action in ('pause', 'resume', 'reset'):
        endpoint = state['urls'][action]
        assert case.client.post(endpoint, json={'subject': 'A', 'revision': 0}).status_code == 403
        assert post(case, config, endpoint, subject='A', revision=0, answers={}, version='obsolete').status_code == 409
    now = state['parts'][0]['started_at'] + 120
    answers = {'A-qrc-01': 'La copie à retrouver demain.'}
    with patch('elearning_native.vtc_cma.time.time', return_value=now):
        response = post(case, config, state['urls']['pause'], subject='A', revision=0, answers=answers, remaining_seconds=999999)
    assert response.status_code == 200, response.text
    paused = response.json['state']
    assert paused['parts'][0]['remaining_seconds'] == 2580
    assert paused['answers'] == answers and paused['parts'][0]['status'] == 'paused'
    with patch('elearning_native.vtc_cma.time.time', return_value=now + 86400):
        _, page = page_config(case, url=url + '?attempt=' + state['id'])
        assert page['state']['parts'][0]['status'] == 'paused'
        assert page['state']['parts'][0]['remaining_seconds'] == 2580
        assert post(case, config, config['startUrl']).json['state']['parts'][0]['status'] == 'paused'
        response = post(case, config, state['urls']['resume'], subject='A', revision=1)
        assert response.status_code == 200, response.text
        resumed = response.json['state']
        assert resumed['parts'][0]['deadline'] == now + 86400 + 2580
        reset = post(case, config, state['urls']['reset'], subject='A', revision=2)
        assert reset.status_code == 200, reset.text
        assert reset.json['state']['answers'] == {}
        assert reset.json['state']['parts'][0]['remaining_seconds'] == 2700
        assert reset.json['state']['parts'][0]['status'] == 'paused'
        assert 'result' not in reset.json['state']
