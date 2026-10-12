"""HTTP boundaries for APS AI feedback, with an isolated mock provider service.

The host's signed learner token, session nonce, CSRF check, assigned course and
tracking store are real. No live learner data or external API is used.
"""
from __future__ import annotations

import copy
import html
import json
import re
import unittest
from unittest.mock import Mock, patch

import app as host
from elearning_native.production_ai import ProductionAIService
from elearning_native.store import NativeElearningStore
from tests import test_native_elearning_web as native_fixture
from tests.test_aps_production_ai import ANSWERS, PRODUCTION


class APSProductionAIWebTests(unittest.TestCase):
    _public_login = native_fixture.NativeElearningWebTests._public_login
    _admin_login = native_fixture.NativeElearningWebTests._admin_login
    _api_post = native_fixture.NativeElearningWebTests._api_post
    _player_config = staticmethod(native_fixture.NativeElearningWebTests._player_config)

    def setUp(self):
        native_fixture.NativeElearningWebTests.setUp(self)
        self.course["sections"][0]["activities"][0].update(production=copy.deepcopy(PRODUCTION), blocks=[])
        self.course["sections"][0]["activities"][0].pop("academy", None)
        second = copy.deepcopy(self.course["sections"][0]["activities"][0])
        second.update(id="production-next", title="Autre production")
        self.course["sections"][0]["activities"].insert(1, second)
        self.course["activity_order"].insert(1, second["id"])
        self.course_path = (self.persist_dir / "native_elearning" / "courses" /
                            self.course["id"] / self.course["version"] / "course.json")
        self._save_course()
        self.now = 1800000000.0
        self.service = ProductionAIService(self.persist_dir / "native_elearning" / "production_ai.sqlite3",
                                          api_key="synthetic-test-key", background=False, clock=lambda: self.now)
        self.mock_service = Mock(spec=ProductionAIService)
        self.mock_service.configured = True
        self.mock_service.request_analysis.side_effect = self.service.request_analysis
        self.mock_service.list_analyses.side_effect = self.service.list_analyses
        self.mock_service.get_analysis.side_effect = self.service.get_analysis
        self.previous_service = host.app.config.get("NATIVE_ELEARNING_PRODUCTION_AI_SERVICE")
        host.app.config["NATIVE_ELEARNING_PRODUCTION_AI_SERVICE"] = self.mock_service
        self.network_guard = patch("elearning_native.production_ai.urlopen", side_effect=AssertionError("No external API in HTTP tests"))
        self.network_guard.start()

    def tearDown(self):
        self.network_guard.stop()
        if self.previous_service is None:
            host.app.config.pop("NATIVE_ELEARNING_PRODUCTION_AI_SERVICE", None)
        else:
            host.app.config["NATIVE_ELEARNING_PRODUCTION_AI_SERVICE"] = self.previous_service
        self.service.shutdown()
        native_fixture.NativeElearningWebTests.tearDown(self)

    def _save_course(self):
        self.course_path.write_text(json.dumps(self.course), encoding="utf-8")

    @staticmethod
    def _ai_config(response):
        match = re.search(r'<script id="apsProductionAIConfig" type="application/json">(.*?)</script>',
                          response.text, flags=re.DOTALL)
        if match is None:
            raise AssertionError("AI configuration was not rendered")
        return json.loads(html.unescape(match.group(1)))

    def _open(self, client=None, token="public-token"):
        client = client or self.client
        with client.session_transaction() as browser_session:
            browser_session["public_auth_" + token] = True
        response = client.get(f"/espace/{token}/elearning/{self.course['id']}")
        self.assertEqual(response.status_code, 200)
        return response, self._ai_config(response)

    def _preview(self, client=None):
        client = client or self.client
        response = client.get(f"/admin/elearning/courses/{self.course['id']}/preview",
                              query_string={"activity": "content-1", "version": self.course["version"]})
        self.assertEqual(response.status_code, 200)
        return response, self._ai_config(response)

    def _post(self, config, *, client=None, create=True, activity=None, **payload):
        client = client or self.client
        url = config["analysisUrl" if create else "historyUrl"]
        if activity:
            url = url.replace("/activities/content-1/", "/activities/" + activity + "/")
        if create:
            payload.setdefault("production_answers", ANSWERS)
        return client.post(url, json={"access_token": config.get("accessToken", ""),
                                     "version": config.get("version", ""), **payload},
                           headers={"X-Elearning-CSRF": config["csrfToken"]})

    def _rows(self):
        return NativeElearningStore(self.persist_dir / "native_elearning" / "tracking.sqlite3").live_progress(self.course["id"])

    def _finish_first_activity(self, config, answers=ANSWERS):
        review = {row["id"]: "checked" for row in PRODUCTION["rubric"]}
        compare = self._api_post("/api/elearning/v1/activities/content-1/production", config,
                                 stage="compare", production_answers=answers)
        self.assertEqual(compare.status_code, 200)
        complete = self._api_post("/api/elearning/v1/activities/content-1/complete", config,
                                  production_answers=answers, production_self_review=review)
        self.assertEqual(complete.status_code, 200, complete.text[:300])

    def test_rendered_configuration_and_http_require_csrf_and_current_session(self):
        page, config = self._open()
        self.assertTrue(config["configured"])
        self.assertEqual(config["version"], self.course["version"])
        self.assertIn("aps62-production-ai.js", page.text)
        self.assertIn("note indicative", page.text)
        for url in (config["analysisUrl"], config["historyUrl"]):
            for headers in ({}, {"X-Elearning-CSRF": "wrong"}):
                with self.subTest(url=url, headers=headers):
                    response = self.client.post(url, json={"access_token": config["accessToken"],
                        "production_answers": ANSWERS}, headers=headers)
                    self.assertEqual(response.status_code, 403)
        with self.client.session_transaction() as browser_session:
            browser_session.pop("public_auth_public-token")
        self.assertEqual(self._post(config).status_code, 401)
        self.assertEqual(self._post(config, create=False).status_code, 401)
        self.mock_service.request_analysis.assert_not_called()
        self.assertEqual(self._rows()[0]["answers"], {})

    def test_nonce_and_signed_course_access_cannot_be_borrowed_or_forged(self):
        self.data["sessions"][0]["trainees"].append({"id": "trainee-2", "public_token": "second-token", "documents": []})
        _, config = self._open()
        second = host.app.test_client()
        _, other_config = self._open(second, "second-token")
        borrowed = {**config, "csrfToken": other_config["csrfToken"]}
        self.assertEqual(self._post(borrowed, client=second).status_code, 401)
        forged = {**config, "accessToken": config["accessToken"] + "tampered"}
        self.assertEqual(self._post(forged).status_code, 401)
        response = self._post(config, trainee_id="trainee-2", session_id="forged-session",
                              course_id="forged-course", course_version="forged-version")
        self.assertEqual(response.status_code, 202)
        accepted = self.mock_service.request_analysis.call_args.args[0]
        self.assertEqual((accepted["trainee_id"], accepted["session_id"], accepted["course_id"], accepted["course_version"]),
                         ("trainee-1", "session-aps", self.course["id"], self.course["version"]))
        rows = {row["trainee_id"]: row for row in self._rows()}
        self.assertEqual(rows["trainee-2"]["answers"], {})
        with self.client.session_transaction() as browser_session:
            browser_session["native_elearning_nonce"] = "new-browser-nonce"
        self.assertEqual(self._post(config, create=False).status_code, 401)

    def test_prerequisites_required_video_unknown_activity_and_revoked_assignment(self):
        _, config = self._open()
        for create in (True, False):
            self.assertEqual(self._post(config, create=create, activity="production-next").status_code, 409)
            for activity in ("unknown", "question-1"):
                self.assertEqual(self._post(config, create=create, activity=activity).status_code, 404)
        self.course["settings"]["force_navigation"] = False
        self.course["sections"][0]["activities"][0]["blocks"] = [{"id": "required-video", "type": "video",
            "video": {"id": "required-video", "required": True, "duration_seconds": 60, "src": "media/test.mp4"}}]
        self._save_course()
        self.assertEqual(self._post(config, activity="production-next").status_code, 409)
        self.data["sessions"][0]["aps_elearning_enabled"] = False
        self.assertEqual(self._post(config).status_code, 403)
        self.mock_service.request_analysis.assert_not_called()
        self.assertEqual(self._rows()[0]["answers"], {})

    def test_first_text_is_saved_before_enqueue_and_feedback_is_not_marked_seen(self):
        _, config = self._open()
        initial = copy.deepcopy(self._rows()[0])

        def enqueue_after_capture(*args, **kwargs):
            saved = self._rows()[0]["answers"]["content-1"]
            self.assertEqual(saved["production_answers"], ANSWERS)
            self.assertEqual(saved["production_first_answers"], ANSWERS)
            self.assertFalse(saved.get("production_feedback_seen"))
            return self.service.request_analysis(*args, **kwargs)

        self.mock_service.request_analysis.side_effect = enqueue_after_capture
        first = self._post(config)
        self.assertEqual(first.status_code, 202)
        job = first.get_json()["analysis"]
        self.assertEqual(job["status"], "queued")
        again = self._post(config)
        self.assertEqual(again.get_json()["analysis"]["id"], job["id"])
        self.assertTrue(again.get_json()["analysis"]["cached"])
        self.assertEqual(self._rows()[0]["score_percent"], initial["score_percent"])
        self.assertEqual(self._rows()[0]["completed_activity_ids"], [])
        self.mock_service.request_analysis.side_effect = self.service.request_analysis
        revised = {**ANSWERS, "analyse": ANSWERS["analyse"] + " Je précise la source de cette observation."}
        updated = self._post(config, production_answers=revised)
        self.assertEqual(updated.status_code, 202)
        stored = self._rows()[0]["answers"]["content-1"]
        self.assertEqual(stored["production_first_answers"], ANSWERS)
        self.assertEqual(stored["production_answers"], revised)
        self.assertFalse(stored.get("production_feedback_seen"))

    def test_completed_production_is_immutable_but_original_can_be_analysed(self):
        _, config = self._open()
        self._finish_first_activity(config)
        original = copy.deepcopy(self._rows()[0])
        changed = {**ANSWERS, "suite": ANSWERS["suite"] + " Modification après validation."}
        self.assertEqual(self._post(config, production_answers=changed).status_code, 409)
        self.mock_service.request_analysis.assert_not_called()
        self.assertEqual(self._post(config).status_code, 202)
        after = self._rows()[0]
        for key in ("answers", "completed_activity_ids", "score_percent"):
            self.assertEqual(after[key], original[key])

    def test_history_scopes_learner_course_version_and_requested_activity(self):
        self.data["sessions"][0]["trainees"].append({"id": "trainee-2", "public_token": "second-token", "documents": []})
        _, config = self._open()
        first_id = self._post(config).get_json()["analysis"]["id"]
        history = self._post(config, create=False, analysis_id=first_id)
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.get_json()["analysis"]["id"], first_id)
        second = host.app.test_client()
        _, other_config = self._open(second, "second-token")
        self.assertEqual(self._post(other_config, client=second, create=False).get_json()["history"], [])
        self.assertEqual(self._post(other_config, client=second, create=False, analysis_id=first_id).status_code, 404)
        self._finish_first_activity(config)
        self.assertEqual(self._post(config, create=False, activity="production-next", analysis_id=first_id).status_code, 404)
        self.assertEqual(self._post(config, create=False, analysis_id="unknown-id").status_code, 404)
        # Even if a newly assigned version is valid, an old signed token cannot
        # route an existing analysis through that different course version.
        new_course = copy.deepcopy(self.course)
        new_course["version"] = "version-new"
        new_path = self.course_path.parent.parent / "version-new" / "course.json"
        new_path.parent.mkdir()
        new_path.write_text(json.dumps(new_course), encoding="utf-8")
        self.data["sessions"][0]["aps_native_course_version"] = "version-new"
        self.assertEqual(self._post(config, create=False).status_code, 403)

    def test_invalid_json_or_answers_never_enqueue_an_analysis(self):
        _, config = self._open()
        for answers in (None, [], {}, {"analyse": "court", "suite": "court"}, {**ANSWERS, "unknown": "extra"}):
            with self.subTest(answers=answers):
                self.assertEqual(self._post(config, production_answers=answers).status_code, 400)
        for value in (["invalid"], "invalid", 42):
            response = self.client.post(config["analysisUrl"], json=value,
                headers={"X-Elearning-CSRF": config["csrfToken"]})
            self.assertEqual(response.status_code, 400)
        self.mock_service.request_analysis.assert_not_called()
        self.assertEqual(self._rows()[0]["answers"], {})

    def test_failed_job_has_no_grade_and_retry_is_explicit_and_rate_limited(self):
        _, config = self._open()
        first = self._post(config)
        job_id = first.get_json()["analysis"]["id"]
        with patch("elearning_native.production_ai.urlopen", side_effect=TimeoutError("private provider detail")) as provider:
            self.service._run_job(job_id)
            failed = self._post(config, create=False, analysis_id=job_id).get_json()["analysis"]
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error_code"], "timeout")
            self.assertIsNone(failed["feedback"])
            self.assertNotIn("private provider detail", json.dumps(failed))
            cached = self._post(config)
            self.assertEqual(cached.status_code, 200)
            self.assertEqual(cached.get_json()["analysis"]["status"], "failed")
            limited = self._post(config, retry=True)
            self.assertEqual(limited.status_code, 429)
            self.assertEqual(limited.get_json()["code"], "retry_wait")
            self.assertEqual(limited.headers["Retry-After"], "60")
            self.now += 61
            restarted = self._post(config, retry=True)
            self.assertEqual(restarted.status_code, 202)
            self.assertEqual(restarted.get_json()["analysis"]["id"], job_id)
            self.assertEqual(restarted.get_json()["analysis"]["revision"], 1)
            self.assertEqual(provider.call_count, 1)

    def test_preview_is_authenticated_versioned_and_does_not_track_learners(self):
        url = f"/api/admin/elearning/courses/{self.course['id']}/preview/activities/content-1/production-analysis"
        self.assertEqual(self.client.post(url, json={}).status_code, 401)
        self._admin_login()
        with patch("elearning_native.web.NativeElearningStore", side_effect=AssertionError("Preview must not track a learner")):
            page, config = self._preview()
            self.assertIn("version=" + self.course["version"], config["analysisUrl"])
            self.assertEqual(config["accessToken"], "")
            self.assertTrue(config["configured"])
            self.assertEqual(self.client.post(config["analysisUrl"], json={"production_answers": ANSWERS}).status_code, 403)
            response = self._post(config)
            self.assertEqual(response.status_code, 202)
            preview_id = response.get_json()["analysis"]["id"]
            access = self.mock_service.request_analysis.call_args.args[0]
            self.assertEqual(access["session_id"], "admin-preview")
            self.assertEqual(access["course_version"], self.course["version"])
            self.assertNotIn("admin@", json.dumps(access))
            self.assertEqual(self._post(config, create=False, analysis_id=preview_id).status_code, 200)
            invalid = self.client.post(config["analysisUrl"], data="{broken", content_type="application/json",
                                       headers={"X-Elearning-CSRF": config["csrfToken"]})
            self.assertEqual(invalid.status_code, 400)
            with self.client.session_transaction() as browser_session:
                browser_session.pop("native_elearning_nonce")
            self.assertEqual(self._post(config).status_code, 401)
        self.assertIsNone(self.saved_data)
        self.assertFalse((self.persist_dir / "native_elearning" / "tracking.sqlite3").exists())

    def test_preview_viewer_cannot_request_and_other_admin_browser_cannot_read_history(self):
        self._admin_login()
        _, config = self._preview()
        job_id = self._post(config).get_json()["analysis"]["id"]
        other = host.app.test_client()
        with other.session_transaction() as browser_session:
            browser_session.update(admin_logged_in=True, admin_role="admin")
        _, other_config = self._preview(other)
        self.assertEqual(self._post(other_config, client=other, create=False, analysis_id=job_id).status_code, 404)
        with self.client.session_transaction() as browser_session:
            browser_session["admin_role"] = "viewer"
        page, viewer_config = self._preview()
        self.assertFalse(viewer_config["configured"])
        self.assertRegex(page.text, r'<button[^>]*data-ai-request[^>]*disabled')
        self.assertEqual(self._post(viewer_config).status_code, 403)
        # The host's global read-only guard also rejects history POSTs; its GET
        # reporting view remains the supported route for read-only reviewers.
        self.assertEqual(self._post(viewer_config, create=False, analysis_id=job_id).status_code, 403)
        with self.client.session_transaction() as browser_session:
            browser_session.pop("admin_logged_in")
        self.assertEqual(self._post(viewer_config, create=False).status_code, 401)


if __name__ == "__main__":
    unittest.main()
