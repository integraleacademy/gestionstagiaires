from __future__ import annotations

import copy
import hashlib
import html
import json
import os
import re
import time
import unittest
from collections import Counter
from unittest.mock import patch

from elearning_native import mac_aps
from elearning_native.exams import grade_exam, load_exam, public_exam
from elearning_native.importer import CourseCatalog, CourseImportError
from elearning_native.paths import path_revision, project_course, project_progress, validate_modules
from elearning_native.web import TrackingError, _evaluate_answer
from tests import test_native_elearning_web as fixtures


def grouped_answer(activity, correct=True):
    return {"groups": {group["id"]: next(option["id"] for option in group["answers"]
                                          if bool(option["is_correct"]) == correct)
                       for group in activity["answer_groups"]}}


class MacAPSLegacyContentTests(unittest.TestCase):
    def test_complete_curriculum_and_stage_scope_are_separate(self):
        manifest = mac_aps.curriculum_manifest(mac_aps.LEGACY_VERSION)
        self.assertEqual((len(manifest["modules"]), manifest["lesson_count"], manifest["case_count"]), (5, 28, 28))
        self.assertEqual((manifest["inline_question_count"], manifest["decision_count"], manifest["exam_question_count"]), (84, 84, 250))
        self.assertEqual(sum(m["regulatory_minutes"] for m in manifest["modules"]), 2040)
        self.assertEqual(manifest["regulatory_review"]["stage_minutes_with_documented_first_aid_exemption"], 1620)
        self.assertIn("31 décembre 2025", manifest["regulatory_review"]["distance_status"])
        self.assertEqual(len(manifest["regulatory_review"]["initial_assessment"]), 10)
        for cid in mac_aps.curriculum_ids(mac_aps.LEGACY_VERSION):
            course = mac_aps.load_bundled_course(cid, mac_aps.LEGACY_VERSION)
            self.assertFalse(course["regulation"]["automatic_stage_credit"])
            self.assertFalse(course["regulation"]["automatic_certificate"])
            self.assertGreater(course["planned_minutes"], 0)
            self.assertEqual(project_progress({}, course)["active_seconds"], 0)
            self.assertFalse(project_progress({}, course)["module_complete"])

    def test_lessons_have_developed_text_and_distinct_decisions(self):
        lessons = mac_aps._lessons(mac_aps.LEGACY_VERSION)
        self.assertEqual(len({l["id"] for l in lessons}), 28)
        self.assertEqual(len({l["title"] for l in lessons}), 28)
        for lesson in lessons:
            prose = " ".join(p for section in lesson["sections"] for p in section["paragraphs"])
            prose += " " + " ".join(lesson["example"]["paragraphs"])
            self.assertGreaterEqual(len(prose.split()), 350, lesson["id"])
            self.assertTrue(lesson.get("table") or lesson.get("flow"))
            self.assertGreaterEqual(len(lesson["takeaways"]), 3)
            self.assertTrue(all(url.startswith("https://") for url in lesson["source_urls"]))
            self.assertEqual(len(lesson["scenario"]["steps"]), 3)
            self.assertEqual(len(lesson["quiz"]), 3)
        for cid in mac_aps.curriculum_ids(mac_aps.LEGACY_VERSION):
            course = mac_aps.load_bundled_course(cid, mac_aps.LEGACY_VERSION)
            self.assertEqual(len(set(course["activity_order"])), len(course["activity_order"]))
            for section in course["sections"]:
                if section["activities"][0].get("macaps", {}).get("kind") != "lesson":
                    continue
                self.assertEqual([a["macaps"]["kind"] for a in section["activities"]], ["lesson", "application", "quiz", "recap"])
                for question in section["activities"][1:3]:
                    self.assertTrue(_evaluate_answer(question, grouped_answer(question))[0])
                    self.assertFalse(_evaluate_answer(question, grouped_answer(question, False))[0])
                    with self.assertRaises(TrackingError):
                        _evaluate_answer(question, {"groups": {}})

    def test_exam_banks_are_independent_balanced_and_graded_on_server(self):
        ids, prompts = set(), set()
        for eid in ["macaps-module-" + n for n in ("01", "02", "03", "04", "05")] + ["macaps-final"]:
            exam = load_exam(eid, mac_aps.LEGACY_VERSION)
            self.assertEqual(len(exam["questions"]), 100 if eid == "macaps-final" else 30)
            for question in exam["questions"]:
                self.assertNotIn(question["id"], ids)
                self.assertNotIn(question["prompt"].strip().casefold(), prompts)
                ids.add(question["id"]); prompts.add(question["prompt"].strip().casefold())
                self.assertEqual(len(question["options"]), 4)
                self.assertEqual(len({o["text"] for o in question["options"]}), 4)
                self.assertTrue(question["explanation"])
                self.assertTrue(question["sources"])
            answers = {q["id"]: q["answer"] for q in exam["questions"]}
            self.assertEqual(grade_exam(exam, answers)["percent"], 100)
            for public in public_exam(exam)["questions"]:
                self.assertEqual(set(public), {"id", "prompt", "options"})
            positions = Counter(q["answer"] for q in exam["questions"])
            self.assertLessEqual(max(positions.values()) - min(positions.values()), 2)
        final = load_exam("macaps-final", mac_aps.LEGACY_VERSION)
        self.assertEqual(sorted(Counter(q["module"] for q in final["questions"]).values()), [15, 15, 20, 20, 30])
        for correct, passed in ((79, False), (80, True)):
            answers = {q["id"]: q["answer"] if i < correct else next(o["id"] for o in q["options"] if o["id"] != q["answer"])
                       for i, q in enumerate(final["questions"])}
            self.assertEqual(grade_exam(final, answers)["passed"], passed)

    def test_versions_are_immutable_and_asset_paths_are_scoped(self):
        course = mac_aps.load_bundled_course("academy-macaps-01", mac_aps.LEGACY_VERSION)
        course["sections"].clear()
        self.assertTrue(mac_aps.load_bundled_course("academy-macaps-01", mac_aps.LEGACY_VERSION)["sections"])
        self.assertIsNone(mac_aps.load_bundled_course("academy-macaps-01", "unknown"))
        self.assertIsNone(load_exam("macaps-final", "unknown"))
        self.assertIsNone(mac_aps.bundled_asset("academy-macaps-01", mac_aps.LEGACY_VERSION, "../../lessons.json"))

    def test_all_published_videos_have_real_media_and_captions(self):
        videos = [mac_aps._video(number) for number in ("01", "02", "03", "04", "05")]
        if not all(videos) and os.environ.get("MACAPS_REQUIRE_MEDIA") != "1":
            self.skipTest("The release verification requires media after rendering.")
        self.assertTrue(all(videos))
        for number, video in zip(("01", "02", "03", "04", "05"), videos):
            self.assertEqual(video["voice"], "fr-FR-HenriNeural")
            self.assertTrue(video["burned_captions"])
            self.assertGreaterEqual(video["duration_seconds"], 300)
            self.assertGreaterEqual(video["narration_seconds"], 300)
            for key in ("src", "poster", "captions"):
                self.assertTrue(mac_aps.bundled_asset("academy-macaps-" + number, mac_aps.LEGACY_VERSION, video[key]).is_file())
            mp4 = mac_aps.bundled_asset("academy-macaps-" + number, mac_aps.LEGACY_VERSION, video["src"])
            self.assertEqual(hashlib.sha256(mp4.read_bytes()).hexdigest(), video["video_sha256"])


class MacAPSWebTests(unittest.TestCase):
    setUp = fixtures.NativeElearningWebTests.setUp
    tearDown = fixtures.NativeElearningWebTests.tearDown
    _admin_login = fixtures.NativeElearningWebTests._admin_login
    _public_login = fixtures.NativeElearningWebTests._public_login
    _player_config = staticmethod(fixtures.NativeElearningWebTests._player_config)
    _api_post = fixtures.NativeElearningWebTests._api_post

    def csrf(self):
        with self.client.session_transaction() as session:
            return session["native_elearning_csrf"]

    def assign(self, numbers=("01",)):
        session = self.data["sessions"][0]
        session["training_type"] = "MAC APS"
        courses = [mac_aps.load_bundled_course("academy-macaps-" + number, mac_aps.LEGACY_VERSION) for number in numbers]
        session["aps_native_modules"] = validate_modules([
            {"course_id": course["id"], "course_version": course["version"], "required_minutes": course["planned_minutes"]}
            for course in courses], CourseCatalog(self.persist_dir / "native_elearning"))
        return courses

    def preview(self, course, activity=None):
        return self.client.get("/admin/elearning/courses/" + course["id"] + "/preview",
                               query_string={"version": course["version"], **({"activity": activity} if activity else {})})

    def test_catalog_and_all_activity_templates_render_without_tracking(self):
        self._admin_login()
        with patch("elearning_native.web.NativeElearningStore", side_effect=AssertionError("Preview started tracking")):
            response = self.client.get("/admin/elearning/mac-aps")
            self.assertEqual(response.status_code, 200)
            self.assertIn("100 questions", response.text)
            self.assertIn("31 décembre 2025", response.text)
            self.assertIn("Actualisation · MAC APS", response.text)
            for cid in mac_aps.curriculum_ids(mac_aps.LEGACY_VERSION):
                course = mac_aps.load_bundled_course(cid, mac_aps.LEGACY_VERSION)
                for activity in course["activity_order"]:
                    response = self.preview(course, activity)
                    self.assertEqual(response.status_code, 200, activity)
                    self.assertIn("macaps-course", response.text)
                    self.assertNotIn("nativeActiveTimer", response.text)
                    self.assertNotIn('id="nativeElearningConfig"', response.text)
                    self.assertNotIn('is_correct', response.text)
        self.assertIsNone(self.saved_data)

    def test_radio_card_questions_use_native_grading_and_csrf(self):
        self._admin_login()
        course = mac_aps.load_bundled_course("academy-macaps-01", mac_aps.LEGACY_VERSION)
        for question in course["sections"][0]["activities"][1:3]:
            response = self.preview(course, question["id"])
            self.assertIn('class="mac-choice-group"', response.text)
            self.assertNotIn(question["explanation"], response.text)
            config = json.loads(re.search(r'<script id="nativePreviewConfig" type="application/json">(.*?)</script>', response.text, re.S)[1])
            payload = {"answer": grouped_answer(question)}
            self.assertEqual(self.client.post(config["answerUrl"], json=payload).status_code, 403)
            result = self.client.post(config["answerUrl"], json=payload, headers={"X-Elearning-CSRF": self.csrf()})
            self.assertEqual(result.status_code, 200)
            self.assertTrue(result.json["correct"])
            self.assertEqual(result.json["explanation"], question["explanation"])
            self.assertFalse((self.persist_dir / "native_elearning/tracking.sqlite3").exists())

    def test_mac_aps_session_composer_and_learner_portal(self):
        self._admin_login()
        self.data["sessions"][0]["training_type"] = "MAC APS"
        response = self.client.get("/admin/sessions/session-aps/elearning")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="macapsAddPath"', response.text)
        course = mac_aps.load_bundled_course("academy-macaps-01", mac_aps.LEGACY_VERSION)
        response = self.client.post("/api/admin/sessions/session-aps/elearning/path", json={
            "revision": path_revision(self.data["sessions"][0]), "title": "MAC APS · Révision",
            "modules": [{"course_id": course["id"], "course_version": course["version"], "required_minutes": course["planned_minutes"]}]},
            headers={"X-Elearning-CSRF": self.csrf()})
        self.assertEqual(response.status_code, 200)
        self._public_login()
        self.assertIn("Accéder à mon parcours MAC APS", self.client.get("/espace/public-token").text)
        response = self.client.get("/espace/public-token/elearning")
        self.assertEqual(response.status_code, 200)
        self.assertIn("MAC APS", response.text)
        self.assertIn("module-01.webp", response.text)
        self.assertEqual(self.client.get("/espace/public-token/elearning/exams/macaps-module-01").status_code, 200)
        self.assertEqual(self.client.get("/espace/public-token/elearning/exams/macaps-final").status_code, 403)

    def test_incorrect_application_cannot_unlock_or_award_time(self):
        course = self.assign(("01", "02"))[0]
        self._public_login()
        response = self.client.get("/espace/public-token/elearning/" + course["id"])
        config = self._player_config(response)
        lesson, application, quiz, recap = course["sections"][0]["activities"]
        self.assertEqual(self._api_post("/api/elearning/v1/activities/" + lesson["id"] + "/complete", config).status_code, 200)
        blocked = self._api_post("/api/elearning/v1/activities/" + recap["id"] + "/complete", config)
        self.assertEqual(blocked.status_code, 409)
        result = self._api_post("/api/elearning/v1/activities/" + application["id"] + "/answer", config, answer=grouped_answer(application, False))
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json["retry_required"])
        self.assertNotIn(application["id"], result.json["progress"]["completed_activity_ids"])
        self.assertEqual(result.json["progress"]["active_seconds"], 0)
        result = self._api_post("/api/elearning/v1/activities/" + application["id"] + "/answer", config, answer=grouped_answer(application))
        self.assertTrue(result.json["correct"])
        self.assertIn(application["id"], result.json["progress"]["completed_activity_ids"])
        self.assertEqual(self.client.get("/espace/public-token/elearning/academy-macaps-02").status_code, 403)

    def test_final_corrections_link_to_the_right_curriculum(self):
        self._admin_login()
        self.client.get("/admin/elearning/mac-aps")
        exam = load_exam("macaps-final", mac_aps.LEGACY_VERSION)
        response = self.client.post("/api/admin/elearning/exams/macaps-final?version=" + mac_aps.LEGACY_VERSION, json={
            "version": mac_aps.LEGACY_VERSION, "answers": {q["id"]: q["answer"] for q in exam["questions"]}},
            headers={"X-Elearning-CSRF": self.csrf()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["result"]["score"], 100)
        for correction in response.json["result"]["corrections"]:
            self.assertTrue(correction["lesson_links"])
            self.assertTrue(all("academy-macaps-" in link["url"] for link in correction["lesson_links"]))

    def test_anonymous_other_learner_and_unknown_versions_are_denied(self):
        self.assertEqual(self.client.get("/admin/elearning/mac-aps").status_code, 302)
        self.assertEqual(self.client.post("/api/admin/elearning/exams/macaps-final", json={}).status_code, 401)
        self.assign(); self._public_login()
        self.assertEqual(self.client.get("/espace/other-token/elearning/academy-macaps-01").status_code, 302)
        self.assertEqual(self.client.get("/espace/public-token/elearning/academy-macaps-05").status_code, 403)
        self._admin_login()
        self.assertEqual(self.client.get("/admin/elearning/courses/academy-macaps-01/preview?version=unknown").status_code, 404)

    def test_video_range_is_authorized_and_cannot_be_completed_by_click(self):
        video = mac_aps._video("01")
        if not video:
            self.skipTest("Video is checked after media generation.")
        self._admin_login()
        course = mac_aps.load_bundled_course("academy-macaps-01", mac_aps.LEGACY_VERSION)
        response = self.preview(course, "macaps-01-video")
        src = html.unescape(re.search(r'<source src="([^"]+)"', response.text)[1])
        part = self.client.get(src, headers={"Range": "bytes=0-1023"})
        self.assertEqual(part.status_code, 206)
        self.assertEqual(len(part.data), 1024)
        with self.client.session_transaction() as session:
            session.pop("admin_logged_in", None)
        self.assertEqual(self.client.get(src).status_code, 401)
        projected = project_course(course, {"required_minutes": 0})
        progress = project_progress({"completed_activity_ids": course["activity_order"], "active_seconds": 99999}, projected)
        self.assertFalse(progress["module_complete"])
        self.assertNotIn("macaps-01-video", progress["completed_activity_ids"])

    def test_video_slow_playback_uses_elapsed_time_and_rejects_fast_forward(self):
        if not mac_aps._video("01"):
            self.skipTest("Video is checked after media generation.")
        course = self.assign()[0]
        self.data["sessions"][0]["aps_native_modules"] = validate_modules([{
            "course_id": course["id"], "course_version": course["version"],
            "section_ids": ["macaps-01-synthese"], "required_minutes": 0,
        }], CourseCatalog(self.persist_dir / "native_elearning"))
        self._public_login()
        response = self.client.get("/espace/public-token/elearning/" + course["id"])
        self.assertIn('data-video-rate="macaps-01-video"', response.text)
        config = self._player_config(response)
        clock = [time.time()]
        with patch("elearning_native.store.time.time", side_effect=lambda: clock[0]):
            start = self._api_post(config["startUrl"], config, activity_id=config["activityId"], tab_id="macaps-video-test")
            self.assertEqual(start.status_code, 200)
            tracking = start.json["tracking_session_id"]

            def heartbeat(position, seconds=0, rate=.85):
                clock[0] += seconds
                result = self._api_post(config["heartbeatUrl"], config,
                    tracking_session_id=tracking, activity_id=config["activityId"],
                    visible=True, focused=True, recent_activity=True, media_playing=True,
                    videos=[{"id": "macaps-01-video", "position": position, "playing": True, "ended": False, "rate": rate}])
                self.assertEqual(result.status_code, 200)
                return result.json

            heartbeat(0)
            progress = heartbeat(3.4, seconds=4)["progress"]
            self.assertAlmostEqual(progress["video_progress"]["macaps-01-video"]["macaps-01-video"]["watched_seconds"], 3.4)
            self.assertEqual(progress["active_seconds"], 4)
            rejected = heartbeat(11.4, seconds=4, rate=2)
            self.assertEqual(rejected["video_resync"], {"macaps-01-video": 3.4})
            self.assertFalse(rejected["progress"]["video_progress"]["macaps-01-video"]["macaps-01-video"]["completed"])
            self.assertEqual(self._api_post(config["completeUrl"], config).status_code, 409)


if __name__ == "__main__":
    unittest.main()
