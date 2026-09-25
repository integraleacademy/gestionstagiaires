"""Mandatory viewing: real API requests, forged playback, resume and media scope."""
import copy
import html
import json
import re
import time
from unittest.mock import patch

import pytest

from elearning_native.importer import CourseCatalog, CourseImportError
from elearning_native.videos import ACADEMY_VIDEOS
from tests import test_native_elearning_web as web_tests


@pytest.fixture
def lesson():
    case = web_tests.NativeElearningWebTests(methodName="runTest")
    case.setUp()
    course_file = case.persist_dir / "native_elearning/courses" / case.course["id"] / case.course["version"] / "course.json"
    course = json.loads(course_file.read_text())
    course["settings"]["force_navigation"] = False
    course["sections"][0]["activities"][0]["blocks"].insert(0, {
        "id": "required-video", "type": "video", "video": {
            "id": "required-video", "src": "media/test.mp4", "required": True, "duration_seconds": 8,
        },
    })
    course_file.write_text(json.dumps(course))
    case.course = course
    case._public_login()
    case.player_url = f"/espace/public-token/elearning/{case.course['id']}"
    case.config = case._player_config(case.client.get(case.player_url))
    case.clock = [time.time()]
    with patch("elearning_native.store.time.time", side_effect=lambda: case.clock[0]):
        case.tracking = case._api_post(case.config["startUrl"], case.config, activity_id="content-1", tab_id="tab-one").get_json()["tracking_session_id"]
        try:
            yield case
        finally:
            case.tearDown()


def heartbeat(case, position, *, seconds=0, playing=True, ended=False, visible=True, rate=1, tracking=None):
    case.clock[0] += seconds
    return case._api_post(case.config["heartbeatUrl"], case.config,
        tracking_session_id=tracking or case.tracking, activity_id="content-1", visible=visible,
        focused=visible, recent_activity=True, media_playing=playing,
        videos=[{"id": "required-video", "position": position, "playing": playing, "ended": ended, "rate": rate}])


def video_state(response):
    return response.get_json()["progress"]["video_progress"]["content-1"]["required-video"]


def test_no_skip_by_button_direct_url_api_or_fake_ended(lesson):
    c = lesson
    assert c.config["requiredVideos"] == {"required-video": 8}
    assert c._api_post(c.config["completeUrl"], c.config).status_code == 409
    later = c.client.get(c.player_url, query_string={"activity": "question-1"})
    assert c._player_config(later)["activityId"] == "content-1"
    response = c._api_post("/api/elearning/v1/activities/question-1/answer", c.config, answer={"selected": ["answer-a"]})
    assert response.status_code == 409
    assert c._api_post(c.config["startUrl"], c.config, tab_id="skip", activity_id="question-1").status_code == 409
    heartbeat(c, 0)
    jumped = heartbeat(c, 8, seconds=1, playing=False, ended=True)
    assert not video_state(jumped)["completed"]
    assert video_state(jumped)["watched_seconds"] == 0
    assert jumped.get_json()["video_resync"] == {"required-video": 0}
    assert c._api_post(c.config["completeUrl"], c.config).status_code == 409


def test_complete_video_unlocks_only_after_watching_and_explicit_completion(lesson):
    c = lesson
    heartbeat(c, 0)
    assert video_state(heartbeat(c, 4, seconds=4))["watched_seconds"] == 4
    assert c._api_post(c.config["completeUrl"], c.config).status_code == 409
    end = heartbeat(c, 8, seconds=4, playing=False, ended=True)
    assert video_state(end)["completed"] is True
    assert video_state(end)["watched_seconds"] == 8
    complete = c._api_post(c.config["completeUrl"], c.config)
    assert complete.status_code == 200
    assert "content-1" in complete.get_json()["progress"]["completed_activity_ids"]
    later = c.client.get(c.player_url, query_string={"activity": "question-1"})
    assert c._player_config(later)["activityId"] == "question-1"
    # Reload preserves the server's completion, independent of browser storage.
    again = c._player_config(c.client.get(c.player_url, query_string={"activity": "content-1"}))
    assert again["initialVideoProgress"]["content-1"]["required-video"]["completed"] is True


def test_pause_reload_and_rewind_keep_only_the_continuously_watched_prefix(lesson):
    c = lesson
    heartbeat(c, 0)
    paused = heartbeat(c, 3, seconds=3, playing=False)
    assert video_state(paused)["watched_seconds"] == 3
    assert video_state(heartbeat(c, 3, seconds=100, playing=False))["watched_seconds"] == 3
    c._api_post(c.config["finishUrl"], c.config, tracking_session_id=c.tracking, activity_id="content-1")
    reloaded = c._player_config(c.client.get(c.player_url))
    assert reloaded["initialVideoProgress"]["content-1"]["required-video"]["watched_seconds"] == 3
    c.tracking = c._api_post(c.config["startUrl"], c.config, activity_id="content-1", tab_id="reload").get_json()["tracking_session_id"]
    heartbeat(c, 1)  # Replay an already viewed portion.
    assert video_state(heartbeat(c, 3, seconds=2))["watched_seconds"] == 3
    assert video_state(heartbeat(c, 8, seconds=5, playing=False, ended=True))["completed"] is True


def test_hidden_double_speed_duplicate_and_rapid_requests_cannot_earn_video(lesson):
    c = lesson
    heartbeat(c, 0)
    hidden = heartbeat(c, 4, seconds=4, visible=False)
    assert video_state(hidden)["watched_seconds"] == 0
    heartbeat(c, 0)
    fast = heartbeat(c, 4, seconds=2, rate=2)
    assert video_state(fast)["watched_seconds"] == 0
    heartbeat(c, 0)
    other = c._api_post(c.config["startUrl"], c.config, activity_id="content-1", tab_id="other").get_json()["tracking_session_id"]
    assert heartbeat(c, 0, tracking=other).get_json()["duplicate"] is True
    assert video_state(heartbeat(c, 8, seconds=8, tracking=other, ended=True))["watched_seconds"] == 0
    # Even hundreds of client requests cannot create real viewing time.
    heartbeat(c, 0)
    for _ in range(30):
        result = heartbeat(c, 8, ended=True)
        assert not video_state(result)["completed"]
    assert c._api_post(c.config["completeUrl"], c.config).status_code == 409


def test_old_completion_does_not_bypass_new_required_video(lesson):
    c = lesson
    database = c.persist_dir / "native_elearning/tracking.sqlite3"
    import sqlite3
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE learner_course_progress SET completed_json = ?", (json.dumps(c.course["activity_order"]),))
    page = c._player_config(c.client.get(c.player_url, query_string={"activity": "question-2"}))
    assert page["activityId"] == "content-1"
    assert page["activityCompleted"] is False
    assert page["initialModuleComplete"] is False


def test_network_jitter_does_not_accumulate_lost_viewing_time(lesson):
    c = lesson
    heartbeat(c, 0)
    # Alternating network latency must not discard 0.35 s at every heartbeat.
    for position, elapsed in [(2, 2.35), (4, 1.65), (6, 2.35), (8, 1.65)]:
        result = heartbeat(c, position, seconds=elapsed, playing=position < 8, ended=position == 8)
        assert not result.get_json()["video_resync"]
        assert video_state(result)["watched_seconds"] == position
    assert video_state(result)["completed"] is True


def test_each_sequence_video_must_be_watched_independently(lesson):
    c = lesson
    course = copy.deepcopy(c.course)
    question = copy.deepcopy(course["sections"][0]["activities"][1])
    question["id"] = "question-next-sequence"
    course["sections"].append({"id": "next-sequence", "title": "Séquence suivante", "activities": [
        {"id": "content-next-sequence", "title": "Vidéo suivante", "type": "content", "blocks": [
            {"id": "second-video", "type": "video", "video": {"id": "second-video", "required": True,
             "src": "media/second.mp4", "duration_seconds": 4}}]}, question]})
    course["activity_order"].extend(["content-next-sequence", "question-next-sequence"])
    location = c.persist_dir / "native_elearning/courses" / course["id"] / course["version"] / "course.json"
    location.write_text(json.dumps(course))
    heartbeat(c, 0)
    assert video_state(heartbeat(c, 8, seconds=8, playing=False, ended=True))["completed"]
    assert c._api_post(c.config["completeUrl"], c.config).status_code == 200
    c._api_post(c.config["finishUrl"], c.config, tracking_session_id=c.tracking, activity_id="content-1")
    next_page = c.client.get(c.player_url, query_string={"activity": "question-next-sequence"})
    cfg = c._player_config(next_page)
    assert cfg["activityId"] == "content-next-sequence"
    assert cfg["requiredVideos"] == {"second-video": 4}
    assert c._api_post(cfg["completeUrl"], cfg).status_code == 409
    tracking = c._api_post(cfg["startUrl"], cfg, activity_id=cfg["activityId"], tab_id="next").get_json()["tracking_session_id"]
    def second_heartbeat(position, elapsed=0):
        c.clock[0] += elapsed
        return c._api_post(cfg["heartbeatUrl"], cfg, tracking_session_id=tracking,
            activity_id=cfg["activityId"], visible=True, focused=True, recent_activity=True, media_playing=position < 4,
            videos=[{"id": "second-video", "position": position, "playing": position < 4, "ended": position == 4, "rate": 1}])
    second_heartbeat(0)
    second_heartbeat(4, 1)
    assert c._api_post(cfg["completeUrl"], cfg).status_code == 409
    second_heartbeat(0)
    second_heartbeat(4, 4)
    assert c._api_post(cfg["completeUrl"], cfg).status_code == 200
    assert c._player_config(c.client.get(c.player_url, query_string={"activity": "question-next-sequence"}))["activityId"] == "question-next-sequence"


def test_bundled_approved_video_is_version_bound_and_uses_authenticated_range_requests(lesson):
    c = lesson
    entry = ACADEMY_VIDEOS[0]
    course = copy.deepcopy(c.course)
    course.update(id=entry["course_id"], version=entry["course_version"])
    course["sections"][0]["activities"][0].update(id=entry["activity_id"], blocks=[])
    course["activity_order"][0] = entry["activity_id"]
    location = c.persist_dir / "native_elearning/courses" / course["id"] / course["version"] / "course.json"
    location.parent.mkdir(parents=True)
    original = json.dumps(course)
    location.write_text(original)
    catalog = CourseCatalog(c.persist_dir / "native_elearning")
    enriched = catalog.load_course(course["id"], course["version"])
    video = enriched["sections"][0]["activities"][0]["blocks"][0]["video"]
    assert video["duration_seconds"] == 99.44 and video["required"]
    assert location.read_text() == original
    assert len(catalog.load_course(course["id"], course["version"])["sections"][0]["activities"][0]["blocks"]) == 1
    with pytest.raises(CourseImportError):
        catalog.asset_path(c.course["id"], c.course["version"], video["src"])
    c._admin_login()
    page = c.client.get(f"/admin/elearning/courses/{course['id']}/preview", query_string={"version": course["version"], "activity": entry["activity_id"]})
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Visionnage obligatoire pour les stagiaires" in body
    assert "data-required-video" not in body  # Preview stays freely navigable.
    media = html.unescape(re.search(r'<source src="([^"]+)"', body).group(1))
    partial = c.client.get(media, headers={"Range": "bytes=0-15"})
    assert partial.status_code == 206 and len(partial.data) == 16
    assert partial.mimetype == "video/mp4"
    with c.client.session_transaction() as session:
        session.pop("admin_logged_in")
    assert c.client.get(media).status_code == 401
