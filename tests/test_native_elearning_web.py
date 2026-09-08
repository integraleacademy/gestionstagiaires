from __future__ import annotations

import html
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as gestion_app

from elearning_native.integration import register_native_elearning
from elearning_native.importer import CourseCatalog
from elearning_native.web import TrackingError, _evaluate_answer
from tests.test_native_elearning import _write_synthetic_course


register_native_elearning(gestion_app)


class NativeElearningWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.persist_dir = Path(self.temporary.name)
        archive = self.persist_dir / "course.zip"
        _write_synthetic_course(archive)
        self.archive_bytes = archive.read_bytes()
        self.course = CourseCatalog(self.persist_dir / "native_elearning").import_zip(
            archive, archive_source=False
        )
        self.data = {
            "sessions": [
                {
                    "id": "session-aps",
                    "name": "APS septembre",
                    "training_type": "APS",
                    "date_start": "2000-01-01",
                    "date_end": "2099-01-01",
                    "aps_elearning_enabled": True,
                    "aps_native_course_id": self.course["id"],
                    "aps_native_course_version": self.course["version"],
                    "trainees": [
                        {
                            "id": "trainee-1",
                            "public_token": "public-token",
                            "first_name": "Alice",
                            "last_name": "Martin",
                            "documents": [],
                        }
                    ],
                }
            ]
        }
        self.saved_data = None
        self.persist_patch = patch.object(gestion_app, "PERSIST_DIR", str(self.persist_dir))
        self.load_patch = patch.object(
            gestion_app,
            "load_data",
            side_effect=lambda *args, **kwargs: self.data,
        )
        self.save_patch = patch.object(
            gestion_app,
            "save_data",
            side_effect=lambda data: setattr(self, "saved_data", data),
        )
        self.persist_patch.start()
        self.load_patch.start()
        self.save_patch.start()
        self.previous_testing = gestion_app.app.config.get("TESTING")
        self.previous_secure_cookie = gestion_app.app.config.get("SESSION_COOKIE_SECURE")
        gestion_app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = gestion_app.app.test_client()

    def tearDown(self) -> None:
        gestion_app.app.config["TESTING"] = self.previous_testing
        gestion_app.app.config["SESSION_COOKIE_SECURE"] = self.previous_secure_cookie
        self.save_patch.stop()
        self.load_patch.stop()
        self.persist_patch.stop()
        self.temporary.cleanup()

    def _public_login(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["public_auth_public-token"] = True

    def _admin_login(self) -> None:
        with self.client.session_transaction() as browser_session:
            browser_session["admin_logged_in"] = True
            browser_session["admin_role"] = "admin"
            browser_session["admin_username"] = "admin@integraleacademy.com"

    @staticmethod
    def _player_config(response) -> dict:
        page = response.get_data(as_text=True)
        match = re.search(
            r'<script id="nativeElearningConfig" type="application/json">(.*?)</script>',
            page,
            flags=re.DOTALL,
        )
        if match is None:
            raise AssertionError("Configuration du lecteur introuvable")
        return json.loads(html.unescape(match.group(1)))

    def _api_post(self, url: str, config: dict, **payload):
        return self.client.post(
            url,
            json={"access_token": config["accessToken"], **payload},
            headers={"X-Elearning-CSRF": config["csrfToken"]},
        )

    def test_native_player_tracks_completes_scores_and_feeds_live_dashboard(self) -> None:
        self._public_login()
        portal = self.client.get("/espace/public-token")
        self.assertEqual(portal.status_code, 200)
        self.assertIn(
            f"/espace/public-token/elearning/{self.course['id']}",
            portal.get_data(as_text=True),
        )
        self.assertIn("Progression et temps actif enregistrés", portal.get_data(as_text=True))
        player = self.client.get(f"/espace/public-token/elearning/{self.course['id']}")
        self.assertEqual(player.status_code, 200)
        page = player.get_data(as_text=True)
        self.assertIn("Temps actif validé", page)
        self.assertIn("Cours de test", page)
        self.assertNotIn('"is_correct"', page)
        config = self._player_config(player)
        self.assertEqual(config["activityId"], "content-1")

        started = self._api_post(
            config["startUrl"], config, tab_id="browser-tab", activity_id="content-1"
        )
        self.assertEqual(started.status_code, 200)
        tracking_id = started.get_json()["tracking_session_id"]
        heartbeat = self._api_post(
            config["heartbeatUrl"],
            config,
            tracking_session_id=tracking_id,
            activity_id="content-1",
            visible=True,
            focused=True,
            recent_activity=True,
            media_playing=False,
        )
        self.assertEqual(heartbeat.status_code, 200)
        self.assertTrue(heartbeat.get_json()["active"])

        completed = self._api_post(config["completeUrl"], config)
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.get_json()["progress"]["progress_percent"], 33.33)

        first_answer = self._api_post(
            "/api/elearning/v1/activities/question-1/answer",
            config,
            answer={"selected": ["answer-a"]},
        )
        self.assertEqual(first_answer.status_code, 200)
        self.assertTrue(first_answer.get_json()["correct"])

        final_answer = self._api_post(
            "/api/elearning/v1/activities/question-2/answer",
            config,
            answer={"groups": {"group-1": "blank-a"}},
        )
        self.assertEqual(final_answer.status_code, 200)
        final_progress = final_answer.get_json()["progress"]
        self.assertEqual(final_progress["status"], "passed")
        self.assertEqual(final_progress["progress_percent"], 100)
        self.assertEqual(final_progress["score_percent"], 100)

        self._admin_login()
        live_api = self.client.get(f"/api/admin/elearning/courses/{self.course['id']}/live")
        self.assertEqual(live_api.status_code, 200)
        learners = live_api.get_json()["learners"]
        self.assertEqual(len(learners), 1)
        self.assertEqual(learners[0]["trainee_name"], "Alice Martin")
        self.assertEqual(learners[0]["progress_percent"], 100)
        self.assertNotIn("answers", learners[0])
        live_page = self.client.get(f"/admin/elearning/courses/{self.course['id']}/live")
        self.assertEqual(live_page.status_code, 200)
        self.assertIn("Suivi pédagogique en direct", live_page.get_data(as_text=True))
        export = self.client.get(f"/admin/elearning/courses/{self.course['id']}/export.csv")
        self.assertEqual(export.status_code, 200)
        self.assertIn("Alice Martin", export.get_data(as_text=True))
        self.assertIn("Temps actif (secondes)", export.get_data(as_text=True))

    def test_admin_catalog_assigns_course_and_accepts_chunked_zip(self) -> None:
        self._admin_login()
        self.data["sessions"].append(dict(self.data["sessions"][0]))
        catalog_page = self.client.get("/admin/elearning")
        self.assertEqual(catalog_page.status_code, 200)
        self.assertIn("E-learning natif", catalog_page.get_data(as_text=True))
        self.assertEqual(
            catalog_page.get_data(as_text=True).count(
                'action="/admin/sessions/session-aps/elearning/assign"'
            ),
            1,
        )
        with self.client.session_transaction() as browser_session:
            csrf = browser_session["native_elearning_csrf"]

        assigned = self.client.post(
            "/admin/sessions/session-aps/elearning/assign",
            data={"course_id": self.course["id"], "native_elearning_csrf": csrf},
        )
        self.assertEqual(assigned.status_code, 302)
        self.assertEqual(self.saved_data["sessions"][0]["aps_native_course_id"], self.course["id"])

        created = self.client.post(
            "/api/admin/elearning/imports",
            json={"filename": "course.zip", "size": len(self.archive_bytes)},
            headers={"X-Elearning-CSRF": csrf},
        )
        self.assertEqual(created.status_code, 201)
        upload = created.get_json()
        uploaded = self.client.post(
            upload["chunk_url"],
            data=self.archive_bytes,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Elearning-CSRF": csrf,
                "X-Upload-Offset": "0",
            },
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(uploaded.get_json()["received"], len(self.archive_bytes))
        finished = self.client.post(
            upload["complete_url"],
            json={},
            headers={"X-Elearning-CSRF": csrf},
        )
        self.assertEqual(finished.status_code, 200)
        self.assertEqual(finished.get_json()["course"]["id"], self.course["id"])

    def test_free_text_fill_blank_is_scored_without_exposing_the_answer(self) -> None:
        activity = {
            "question_type": "fill_blank",
            "answer_groups": [
                {
                    "id": "group-1",
                    "mode": "text",
                    "answers": [
                        {
                            "id": "answer-1",
                            "text": "proportionnée",
                            "is_correct": True,
                            "match_case": False,
                        }
                    ],
                }
            ],
        }

        correct, stored = _evaluate_answer(
            activity,
            {"groups": {"group-1": "  Proportionnée  "}},
        )
        self.assertTrue(correct)
        self.assertEqual(stored, {"groups": {"group-1": "Proportionnée"}})

        incorrect, _ = _evaluate_answer(
            activity,
            {"groups": {"group-1": "disproportionnée"}},
        )
        self.assertFalse(incorrect)

        with self.assertRaises(TrackingError):
            _evaluate_answer(activity, {"groups": {"group-1": ""}})


if __name__ == "__main__":
    unittest.main()
