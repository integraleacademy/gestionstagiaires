"""VTC modules open independently while progress and access rules still apply."""
import copy
import hashlib
import html
import json
import re
import time
from unittest.mock import patch

import pytest

import app as host
import elearning_orders
from elearning_native import a3p, vtc
from elearning_native.academy import curriculum_manifest as aps_manifest
from elearning_native.exams import load_exam
from elearning_native.store import NativeElearningStore
from elearning_native.videos import course_videos
from tests import test_native_elearning_web as web_tests


BASE = "/espace/public-token/elearning"


def assignments(manifest):
    return [
        {
            "course_id": module["id"],
            "course_version": module["version"],
            "required_minutes": module.get("planned_minutes", int(module.get("hours", 0) * 60)),
        }
        for module in manifest["modules"]
    ]


@pytest.fixture
def case():
    # Reuse setup helpers without inheriting and rerunning unrelated web tests.
    instance = web_tests.NativeElearningWebTests(methodName="runTest")
    instance.setUp()
    instance.data["sessions"][0].update(
        training_type="VTC", name="Chauffeur VTC", aps_native_modules=assignments(vtc.curriculum_manifest())
    )
    instance._public_login()
    try:
        yield instance
    finally:
        instance.tearDown()


def tracking_store(case):
    return NativeElearningStore(case.persist_dir / "native_elearning" / "tracking.sqlite3")


def learner_rows(case, session_id="session-aps", trainee_id="trainee-1"):
    return {row["course_id"]: row for row in tracking_store(case).learner_progress(session_id, trainee_id)}


def player(case, course_id, base=BASE, **query):
    response = case.client.get(f"{base}/{course_id}", query_string=query)
    assert response.status_code == 200, response.text[:500]
    return case._player_config(response)


def module_cards(response):
    assert response.status_code == 200, response.text[:500]
    return re.findall(r'<article class="([^"]*\bnp-learner-module\b[^"]*)">(.*?)</article>', response.text, re.S)


def exam_config(response):
    assert response.status_code == 200, response.text[:500]
    match = re.search(r'id="apsExamConfig">(.*?)</script>', response.text, re.S)
    assert match
    return json.loads(html.unescape(match.group(1)))


@pytest.mark.parametrize("training_type", ["VTC", "Chauffeur VTC"])
def test_all_eight_assigned_vtc_modules_are_linked_before_any_completion(case, training_type):
    case.data["sessions"][0]["training_type"] = training_type
    before = copy.deepcopy(case.data)
    response = case.client.get(BASE)
    cards = module_cards(response)
    assert len(cards) == 8
    for letter, (classes, body) in zip("abcdefgh", cards):
        assert "is-locked" not in classes
        assert f'href="{BASE}/academy-vtc-{letter}"' in body
        assert f'href="{BASE}/exams/vtc-{letter}"' in body
        assert "Module verrouillé" not in body
    assert "0 / 8" in response.text
    assert "Commencer l’examen final" not in response.text
    assert learner_rows(case) == {}
    assert case.data == before
    assert case.saved_data is None


def test_module_h_tracks_time_and_navigation_preserves_existing_results(case):
    first = player(case, "academy-vtc-a")
    course_a = vtc.load_bundled_course("academy-vtc-a")
    completed_ids = course_a["activity_order"][:2]
    saved_videos = {
        completed_ids[0]: {
            vid: {"duration_seconds": duration, "watched_seconds": duration, "completed": True,
                  "completed_at": "2026-10-01T12:00:00Z"}
            for vid, duration in course_videos(course_a)[completed_ids[0]].items()
        }
    }
    saved_answers = {completed_ids[1]: {"practice_answers": {"q1": "a"}, "practice_correct": True}}
    with tracking_store(case)._connect() as db:
        db.execute(
            """UPDATE learner_course_progress SET current_activity_id=?, completed_json=?, answers_json=?,
               active_seconds=137, video_progress_json=?, status='in_progress'
               WHERE session_id='session-aps' AND trainee_id='trainee-1' AND course_id='academy-vtc-a'""",
            (course_a["activity_order"][2], json.dumps(completed_ids), json.dumps(saved_answers), json.dumps(saved_videos)),
        )
    player(case, "academy-vtc-a")  # Normalize the displayed projection before comparing history.
    before_a = learner_rows(case)["academy-vtc-a"]
    before_assignment = copy.deepcopy(case.data)
    config = player(case, "academy-vtc-h")
    assert not config["initialModuleComplete"]
    assert config["initialRemainingSeconds"] > 0
    clock = [time.time()]
    with patch("elearning_native.store.time.time", side_effect=lambda: clock[0]):
        started = case._api_post(config["startUrl"], config, activity_id=config["activityId"], tab_id="module-h")
        assert started.status_code == 200, started.text
        signals = dict(tracking_session_id=started.json["tracking_session_id"], activity_id=config["activityId"],
                       visible=True, focused=True, recent_activity=True, media_playing=False)
        assert case._api_post(config["heartbeatUrl"], config, **signals).status_code == 200
        clock[0] += 15
        heartbeat = case._api_post(config["heartbeatUrl"], config, **signals)
        assert heartbeat.status_code == 200, heartbeat.text
        assert heartbeat.json["progress"]["active_seconds"] == 15
        assert heartbeat.json["progress"]["completed_activity_ids"] == []
        assert not heartbeat.json["progress"]["module_complete"]
        finished = case._api_post(config["finishUrl"], config, **signals)
        assert finished.status_code == 200, finished.text
    assert case.client.get(BASE).status_code == 200
    resumed_a = player(case, "academy-vtc-a")
    resumed_h = player(case, "academy-vtc-h")
    assert resumed_a["initialActiveSeconds"] == 137
    assert resumed_h["initialActiveSeconds"] == 15
    after_a = learner_rows(case)["academy-vtc-a"]
    for field in ("course_version", "current_activity_id", "completed_activity_ids", "answers", "active_seconds", "video_progress"):
        assert after_a[field] == before_a[field], field
    assert case.data == before_assignment
    assert first["initialActiveSeconds"] == 0


def test_open_module_h_keeps_its_internal_activity_and_video_requirements(case):
    course = vtc.load_bundled_course("academy-vtc-h")
    first_id, later_id = course["activity_order"][:2]
    config = player(case, course["id"], activity=later_id)
    assert config["activityId"] == first_id
    assert config["requiredVideos"]
    for url, payload in (
        (config["startUrl"], {"activity_id": later_id, "tab_id": "skip-activity"}),
        (f"/api/elearning/v1/activities/{later_id}/complete", {}),
        (config["completeUrl"], {"active_seconds": 999999, "videos_completed": True}),
    ):
        denied = case._api_post(url, config, **payload)
        assert denied.status_code == 409, denied.text
    row = learner_rows(case)["academy-vtc-h"]
    assert row["completed_activity_ids"] == []
    assert row["active_seconds"] == 0
    assert not player(case, course["id"])["initialModuleComplete"]


def test_module_h_exam_can_be_taken_but_never_unlocks_the_final_or_completes_courses(case):
    config = exam_config(case.client.get(BASE + "/exams/vtc-h"))
    exam = load_exam("vtc-h", config["exam"]["version"])
    response = case.client.post(config["submitUrl"], json={
        "version": exam["version"], "attempt_id": config["attemptId"],
        "answers": {question["id"]: question["answer"] for question in exam["questions"]},
    }, headers={"X-Elearning-CSRF": config["csrfToken"]})
    assert response.status_code == 200, response.text
    assert response.json["result"]["score"] == len(exam["questions"])
    assert learner_rows(case) == {}
    assert case.client.get(BASE + "/exams/vtc-final").status_code == 403
    final_submit = case.client.post("/api/espace/public-token/elearning/exams/vtc-final", json={
        "version": exam["version"], "attempt_id": config["attemptId"], "answers": {},
    }, headers={"X-Elearning-CSRF": config["csrfToken"]})
    assert final_submit.status_code == 403
    assert "Commencer l’examen final" not in case.client.get(BASE).text


@pytest.mark.parametrize("boundary", ["unassigned", "before_start", "disabled", "logged_out"])
def test_vtc_module_access_and_api_still_require_assignment_dates_and_authentication(case, boundary):
    config = player(case, "academy-vtc-h")
    current = case.data["sessions"][0]
    if boundary == "unassigned":
        current["aps_native_modules"] = current["aps_native_modules"][:-1]
    elif boundary == "before_start":
        current["date_start"] = "2099-01-01"
    elif boundary == "disabled":
        current["aps_elearning_enabled"] = False
    else:
        with case.client.session_transaction() as browser:
            browser.pop("public_auth_public-token")
    page_status = 302 if boundary == "logged_out" else 403
    api_status = 401 if boundary == "logged_out" else 403
    assert case.client.get(BASE + "/academy-vtc-h").status_code == page_status
    assert case.client.get(BASE + "/exams/vtc-h").status_code == page_status
    rejected = case._api_post(config["startUrl"], config, activity_id=config["activityId"], tab_id="denied")
    assert rejected.status_code == api_status, rejected.text
    assert case._api_post(config["completeUrl"], config).status_code == api_status
    assert learner_rows(case)["academy-vtc-h"]["completed_activity_ids"] == []


@pytest.mark.parametrize("training_type", ["APS", "A3P"])
def test_aps_and_a3p_keep_their_previous_module_prerequisite(case, training_type):
    manifest = aps_manifest() if training_type == "APS" else a3p.curriculum_manifest()
    modules = assignments(manifest)[:2]
    case.data["sessions"][0].update(training_type=training_type, aps_native_modules=modules)
    first, second = modules
    cards = module_cards(case.client.get(BASE))
    assert len(cards) == 2
    assert "is-locked" not in cards[0][0]
    assert "is-locked" in cards[1][0]
    assert f'href="{BASE}/{first["course_id"]}"' in cards[0][1]
    assert f'href="{BASE}/{second["course_id"]}"' not in cards[1][1]
    assert case.client.get(BASE + "/" + second["course_id"]).status_code == 403
    first_player = player(case, first["course_id"])
    assert not first_player["initialModuleComplete"]
    assert first_player["initialRemainingSeconds"] > 0


def test_organisation_token_uses_real_vtc_resolver_and_preserves_payment_and_tenant_boundaries(case):
    person = {"id": "partner-learner", "first_name": "Camille", "last_name": "Test",
              "email": "camille@example.test", "activated_at": "2000-01-01T00:00:00Z"}
    order = {"id": "vtc-order", "order_type": "elearning", "status": "received", "partner_id": "centre-vtc",
             "course_code": "vtc", "group_name": "VTC organisme", "free_snapshot": True, "total_cents": 0,
             "modules": assignments(vtc.curriculum_manifest()), "learners": [person]}
    token = elearning_orders.access_token(host, order, person)
    person["token_hash"] = hashlib.sha256(token.encode()).hexdigest()
    case.data.update(partners=[{"id": "centre-vtc", "name": "Centre VTC test", "status": "active"}],
                     manual_orders=[order])
    with case.client.session_transaction() as browser:
        browser["public_auth_" + token] = True
    base = f"/espace/{token}/elearning"
    frozen = copy.deepcopy(case.data)
    cards = module_cards(case.client.get(base))
    assert len(cards) == 8 and all("is-locked" not in classes for classes, _ in cards)
    config = player(case, "academy-vtc-h", base=base)
    started = case._api_post(config["startUrl"], config, activity_id=config["activityId"], tab_id="organisation-h")
    assert started.status_code == 200, started.text
    assert "academy-vtc-h" in learner_rows(case, "el-vtc-order", "partner-learner")
    assert learner_rows(case) == {}
    assert case.data == frozen
    assert host.app.test_client().get(base + "/academy-vtc-h").status_code == 302
    order["status"] = "cancelled"
    assert case.client.get(base + "/academy-vtc-h").status_code == 404
    assert case._api_post(config["startUrl"], config, activity_id=config["activityId"], tab_id="revoked").status_code == 404
    order["status"] = "received"
    case.data["partners"][0]["status"] = "disabled"
    assert case.client.get(base).status_code == 404
