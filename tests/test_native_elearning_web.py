from __future__ import annotations

import html
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app as gestion_app

from elearning_native.integration import register_native_elearning
from elearning_native.importer import CourseCatalog
from elearning_native.paths import assigned_modules, path_revision, project_course, project_progress
from elearning_native.store import NativeElearningStore
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
        def mutate_test_data(mutator):
            result = mutator(self.data)
            self.saved_data = self.data
            return result
        self.atomic_patch = patch.object(gestion_app, "_atomic_update_data", side_effect=mutate_test_data)
        self.atomic_patch.start()
        self.previous_testing = gestion_app.app.config.get("TESTING")
        self.previous_secure_cookie = gestion_app.app.config.get("SESSION_COOKIE_SECURE")
        gestion_app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = gestion_app.app.test_client()

    def tearDown(self) -> None:
        gestion_app.app.config["TESTING"] = self.previous_testing
        gestion_app.app.config["SESSION_COOKIE_SECURE"] = self.previous_secure_cookie
        self.save_patch.stop()
        self.atomic_patch.stop()
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
        if url == config.get("heartbeatUrl"):
            payload.setdefault("interaction_age_seconds", 0)
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
            '/espace/public-token/elearning"',
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
                'href="/admin/sessions/session-aps/elearning"'
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

    def _second_course(self, course_id="course-second", extra_section=True):
        archive = self.persist_dir / "second.zip"
        _write_synthetic_course(archive, course_id=course_id, extra_section=extra_section)
        return CourseCatalog(self.persist_dir / "native_elearning").import_zip(archive, archive_source=False)

    def _module(self, course, sections=None, title=""):
        return {"course_id": course["id"], "course_version": course["version"], "title": title,
                "section_ids": sections or [section["id"] for section in course["sections"]]}

    def _save_path(self, modules, **extra):
        self._admin_login()
        self.client.get("/admin/sessions/session-aps/elearning")
        with self.client.session_transaction() as browser_session:
            csrf = browser_session["native_elearning_csrf"]
        return self.client.post("/api/admin/sessions/session-aps/elearning/path",
            json={"modules": modules, "title": "Parcours APS complet", "revision": path_revision(self.data["sessions"][0]), **extra},
            headers={"X-Elearning-CSRF": csrf})

    def test_composes_multiple_modules_and_orders_selected_sequences(self):
        second = self._second_course()
        response = self._save_path([self._module(second, ["section-2", "section-1"], "Deuxième module"), self._module(self.course)])
        self.assertEqual(response.status_code, 200)
        saved = self.data["sessions"][0]["aps_native_modules"]
        self.assertEqual([item["course_id"] for item in saved], [second["id"], self.course["id"]])
        self.assertEqual(saved[0]["section_ids"], ["section-2", "section-1"])
        self._public_login()
        dashboard = self.client.get("/espace/public-token/elearning")
        self.assertEqual(dashboard.status_code, 200)
        page = dashboard.get_data(as_text=True)
        self.assertIn("Parcours APS complet", page)
        self.assertIn("Temps actif cumulé", page)
        self.assertIn("Deuxième module", page)
        self.assertNotIn('"is_correct"', page)
        config = self._player_config(self.client.get(f"/espace/public-token/elearning/{second['id']}"))
        self.assertEqual(config["activityId"], "content-2")
        self.assertEqual(config["endUrl"], f"/espace/public-token/elearning/{self.course['id']}")
        self.assertEqual(config["endLabel"], "Module suivant")
        catalog_page = self.client.get("/admin/elearning").get_data(as_text=True)
        self.assertIn("2 modules", catalog_page)
        self.assertIn("3 séquences", catalog_page)
        self.assertIn("7 activités", catalog_page)

    def test_path_validation_is_atomic_and_rejects_stale_editor(self):
        invalid_cases = [None, "bad", [None], [self._module(self.course)] * 2,
                         [self._module(self.course, ["unknown"])],
                         [{**self._module(self.course), "section_ids": []}],
                         [{**self._module(self.course), "section_ids": ["section-1", "section-1"]}],
                         [{**self._module(self.course), "course_version": "missing"}],
                         [{**self._module(self.course), "title": "a" * 181}]]
        invalid_cases.extend([[{**self._module(self.course), "required_minutes": value}]
                              for value in (-1, 60001, True, "240", 1.5, None)])
        for modules in invalid_cases:
            with self.subTest(modules=modules):
                before = json.dumps(self.data, sort_keys=True)
                response = self._save_path(modules)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(json.dumps(self.data, sort_keys=True), before)
        response = self._save_path([self._module(self.course)], revision="stale")
        self.assertEqual(response.status_code, 409)
        self.assertIsNone(self.saved_data)

    def test_minimum_duration_unlocks_next_module_only_at_four_hours(self):
        second = self._second_course()
        modules = [{**self._module(self.course), "required_minutes": 240}, self._module(second)]
        saved = self._save_path(modules)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.get_json()["modules"][0]["required_minutes"], 240)
        with self.client.session_transaction() as browser_session:
            browser_session.pop("admin_logged_in", None)
        self._public_login()
        next_url = f"/espace/public-token/elearning/{second['id']}"
        self.assertEqual(self.client.get(next_url).status_code, 403)
        page = self.client.get("/espace/public-token/elearning").get_data(as_text=True)
        self.assertIn("04:00:00", page)
        self.assertIn("Module verrouillé", page)
        self.assertNotIn(f'href="{next_url}"', page)
        config = self._player_config(self.client.get(f"/espace/public-token/elearning/{self.course['id']}"))
        self.assertEqual(config["idleSeconds"], 300)
        self.assertEqual(config["initialRemainingSeconds"], 14400)
        self._api_post(config["completeUrl"], config)
        self._api_post("/api/elearning/v1/activities/question-1/answer", config, answer={"selected": ["answer-a"]})
        result = self._api_post("/api/elearning/v1/activities/question-2/answer", config,
                                answer={"groups": {"group-1": "blank-a"}}, active_seconds=14400)
        progress = result.get_json()["progress"]
        self.assertEqual(progress["progress_percent"], 100)
        self.assertEqual(progress["status"], "awaiting_time")
        self.assertFalse(progress["module_complete"])
        self.assertIsNone(progress["completed_at"])

        tracking = NativeElearningStore(self.persist_dir / "native_elearning" / "tracking.sqlite3")
        # Existing study history: 3:59:59, followed by one real server interval.
        with tracking._connect() as connection:
            connection.execute("UPDATE learner_course_progress SET active_seconds = 14399")
        self.assertEqual(self.client.get(next_url).status_code, 403)
        baseline = time.time()
        with patch("elearning_native.store.time.time", return_value=baseline):
            started = self._api_post(config["startUrl"], config, tab_id="duration", activity_id="question-2").get_json()
            signals = dict(tracking_session_id=started["tracking_session_id"], activity_id="question-2",
                           visible=True, focused=True, recent_activity=True, media_playing=False)
            heartbeat = self._api_post(config["heartbeatUrl"], config, **signals).get_json()
        self.assertEqual(heartbeat["progress"]["required_seconds"], 14400)  # cached access keeps the requirement
        self.assertEqual(heartbeat["progress"]["remaining_seconds"], 1)
        self.assertFalse(heartbeat["progress"]["module_complete"])
        with patch("elearning_native.store.time.time", return_value=baseline + 1):
            progress = self._api_post(config["heartbeatUrl"], config, **signals).get_json()["progress"]
        self.assertEqual(progress["active_seconds"], 14400)
        self.assertTrue(progress["module_complete"])
        self.assertEqual(progress["status"], "passed")
        self.assertIsNotNone(progress["completed_at"])
        second_config = self._player_config(self.client.get(next_url))
        self.assertEqual(second_config["initialActiveSeconds"], 0)  # first module's time is not transferred
        self._admin_login()
        live = self.client.get(f"/api/admin/elearning/courses/{self.course['id']}/live").get_json()["learners"][0]
        self.assertEqual(live["required_time_label"], "04:00:00")
        self.assertTrue(live["duration_met"])
        # A stricter requirement re-locks even a previously issued signed access.
        modules[0]["required_minutes"] = 241
        self.assertEqual(self._save_path(modules).status_code, 200)
        self.assertEqual(self.client.get(next_url).status_code, 403)
        self.assertEqual(self._api_post(second_config["startUrl"], second_config, tab_id="stale", activity_id="content-1").status_code, 403)
        live = self.client.get(f"/api/admin/elearning/courses/{self.course['id']}/live").get_json()["learners"][0]
        self.assertEqual(live["remaining_seconds"], 60)
        self.assertEqual(live["status"], "awaiting_time")
        self.assertIsNone(live["completed_at"])

    def test_duration_alone_is_insufficient_and_missing_predecessor_fails_closed(self):
        second = self._second_course()
        self._save_path([{**self._module(self.course), "required_minutes": 240}, self._module(second)])
        self._public_login()
        self.client.get(f"/espace/public-token/elearning/{self.course['id']}")
        tracking = NativeElearningStore(self.persist_dir / "native_elearning" / "tracking.sqlite3")
        with tracking._connect() as connection:
            connection.execute("UPDATE learner_course_progress SET active_seconds = 14400")
        self.assertEqual(self.client.get(f"/espace/public-token/elearning/{second['id']}").status_code, 403)
        self.data["sessions"][0]["aps_native_modules"][0]["course_version"] = "missing"
        self.assertEqual(self.client.get(f"/espace/public-token/elearning/{second['id']}").status_code, 403)

    def test_heartbeat_requires_inactivity_age_and_video_does_not_bypass_timeout(self):
        self._public_login()
        config = self._player_config(self.client.get(f"/espace/public-token/elearning/{self.course['id']}"))
        started = self._api_post(config["startUrl"], config, tab_id="idle", activity_id="content-1").get_json()
        signals = dict(tracking_session_id=started["tracking_session_id"], activity_id="content-1",
                       visible=True, focused=True, recent_activity=True, media_playing=True)
        for value in (None, -1, "0", True, float("inf"), float("nan")):
            with self.subTest(value=value):
                response = self._api_post(config["heartbeatUrl"], config, **signals, interaction_age_seconds=value)
                self.assertEqual(response.status_code, 409)
        response = self._api_post(config["heartbeatUrl"], config, **signals, interaction_age_seconds=300)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["active"])

    def test_excluded_sequences_and_removed_modules_cannot_be_used(self):
        second = self._second_course()
        self._save_path([self._module(second, ["section-2"])])
        self._public_login()
        denied = self.client.get(f"/espace/public-token/elearning/{self.course['id']}")
        self.assertEqual(denied.status_code, 403)
        config = self._player_config(self.client.get(f"/espace/public-token/elearning/{second['id']}?activity=question-1"))
        self.assertEqual(config["activityId"], "content-2")
        excluded = self._api_post("/api/elearning/v1/activities/question-1/answer", config, answer={"selected": ["answer-a"]})
        self.assertEqual(excluded.status_code, 400)
        self._save_path([])
        removed = self._api_post(config["startUrl"], config, tab_id="tab", activity_id="content-2")
        self.assertEqual(removed.status_code, 403)
        self.assertEqual(assigned_modules(self.data["sessions"][0]), [])
        self.assertNotIn("aps_native_course_id", self.data["sessions"][0])

    def test_existing_progress_survives_selection_removal_and_reassignment(self):
        second = self._second_course()
        self._save_path([self._module(second)])
        self._public_login()
        config = self._player_config(self.client.get(f"/espace/public-token/elearning/{second['id']}"))
        self.assertEqual(self._api_post(config["completeUrl"], config).status_code, 200)
        self.assertEqual(self._api_post("/api/elearning/v1/activities/question-1/answer", config, answer={"selected": ["answer-a"]}).status_code, 200)
        self._save_path([self._module(second, ["section-2"])])
        stale = self._api_post(config["startUrl"], config, tab_id="tab", activity_id="content-1")
        self.assertEqual(stale.status_code, 409)
        config = self._player_config(self.client.get(f"/espace/public-token/elearning/{second['id']}"))
        completed = self._api_post(config["completeUrl"], config)
        self.assertEqual(completed.get_json()["progress"]["progress_percent"], 100)
        self._save_path([])
        self._save_path([self._module(second)])
        store = NativeElearningStore(self.persist_dir / "native_elearning" / "tracking.sqlite3")
        # Use the configured DB location from the route factory.
        rows = store.learner_progress("session-aps", "trainee-1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]["completed_activity_ids"]), {"content-1", "question-1", "content-2"})
        projected = project_progress(rows[0], second)
        self.assertEqual(projected["progress_percent"], 75)
        self.assertEqual(projected["status"], "in_progress")
        self.assertTrue(projected["answers"]["question-1"]["correct"])

    def test_path_dashboard_does_not_start_modules_and_keeps_pinned_versions(self):
        old_version = self.course["version"]
        self._save_path([self._module(self.course)])
        new_course = self._second_course("course-test", extra_section=True)
        self.assertNotEqual(new_course["version"], old_version)
        self._public_login()
        dashboard = self.client.get("/espace/public-token/elearning")
        self.assertEqual(dashboard.status_code, 200)
        self.assertNotIn("Séquence complémentaire", dashboard.get_data(as_text=True))
        builder = self.client.get("/admin/sessions/session-aps/elearning")
        match = re.search(r'<script id="nativePathConfig" type="application/json">(.*?)</script>', builder.get_data(as_text=True), flags=re.DOTALL)
        config = json.loads(match.group(1))
        self.assertEqual(config["modules"][0]["course_version"], old_version)
        self.assertNotIn('"is_correct"', match.group(1))
        store = NativeElearningStore(self.persist_dir / "native_elearning" / "tracking.sqlite3")
        self.assertEqual(store.learner_progress("session-aps", "trainee-1"), [])

    def test_path_security_requires_admin_csrf_and_learner_authorization(self):
        url = "/api/admin/sessions/session-aps/elearning/path"
        self.assertEqual(self.client.post(url, json={}).status_code, 401)
        self._admin_login()
        self.assertEqual(self.client.post(url, json={}).status_code, 403)
        self.client.get("/admin/sessions/session-aps/elearning")
        with self.client.session_transaction() as browser_session:
            browser_session["admin_role"] = "viewer"
            csrf = browser_session["native_elearning_csrf"]
        self.assertEqual(self.client.post(url, json={}, headers={"X-Elearning-CSRF": csrf}).status_code, 403)
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        self.assertEqual(self.client.get("/espace/public-token/elearning").status_code, 302)
        self._public_login()
        self.data["sessions"][0]["date_start"] = "2099-01-01"
        self.assertEqual(self.client.get("/espace/public-token/elearning").status_code, 403)
        self.data["sessions"][0]["date_start"] = "2000-01-01"
        self.data["sessions"][0]["aps_elearning_enabled"] = False
        self.assertEqual(self.client.get("/espace/public-token/elearning").status_code, 403)

    def test_heartbeat_uses_bounded_access_cache_and_save_invalidates_it(self):
        self._public_login()
        config = self._player_config(self.client.get(f"/espace/public-token/elearning/{self.course['id']}"))
        started = self._api_post(config["startUrl"], config, tab_id="tab", activity_id="content-1").get_json()
        with patch.object(gestion_app, "load_data", side_effect=AssertionError("Unexpected data.json read")):
            heartbeat = self._api_post(config["heartbeatUrl"], config, activity_id="content-1",
                                       tracking_session_id=started["tracking_session_id"], visible=True, focused=True, recent_activity=True)
        self.assertEqual(heartbeat.status_code, 200)
        self._save_path([])
        heartbeat = self._api_post(config["heartbeatUrl"], config, activity_id="content-1",
                                   tracking_session_id=started["tracking_session_id"], visible=True, focused=True, recent_activity=True)
        self.assertEqual(heartbeat.status_code, 403)

    def test_path_save_uses_canonical_storage_and_preserves_other_sessions(self):
        data_file = self.persist_dir / "administrative-data.json"
        canonical = json.loads(json.dumps(self.data))
        canonical["sessions"].append({"id": "unrelated", "name": "Ne pas modifier", "training_type": "VTC"})
        canonical["sessions"][0]["note_added_concurrently"] = "À conserver"
        data_file.write_text(json.dumps(canonical), encoding="utf-8")
        self.atomic_patch.stop()
        try:
            with patch.object(gestion_app, "DATA_FILE", str(data_file)), patch.object(gestion_app, "_partner_postgres_active", return_value=False):
                response = self._save_path([self._module(self.course)])
            self.assertEqual(response.status_code, 200)
            persisted = json.loads(data_file.read_text(encoding="utf-8"))
            self.assertEqual(persisted["sessions"][0]["aps_native_modules"][0]["course_id"], self.course["id"])
            self.assertEqual(persisted["sessions"][0]["note_added_concurrently"], "À conserver")
            self.assertEqual(persisted["sessions"][1]["name"], "Ne pas modifier")
        finally:
            self.atomic_patch.start()

    def test_concurrent_path_update_is_rejected_inside_storage_lock(self):
        data_file = self.persist_dir / "administrative-data.json"
        canonical = json.loads(json.dumps(self.data))
        canonical["sessions"][0]["aps_native_path_title"] = "Modifié dans un autre onglet"
        before = json.dumps(canonical)
        data_file.write_text(before, encoding="utf-8")
        self.atomic_patch.stop()
        try:
            with patch.object(gestion_app, "DATA_FILE", str(data_file)), patch.object(gestion_app, "_partner_postgres_active", return_value=False):
                response = self._save_path([self._module(self.course)])
            self.assertEqual(response.status_code, 409)
            self.assertEqual(data_file.read_text(encoding="utf-8"), before)
        finally:
            self.atomic_patch.start()

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
