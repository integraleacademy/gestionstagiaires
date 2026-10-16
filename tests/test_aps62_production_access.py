"""Production access boundaries and private teacher/organisation reporting."""
from __future__ import annotations

import copy
import html
import json
import re
import unittest
from unittest.mock import patch

import app as host
import elearning_reporting as reporting
from elearning_native.store import NativeElearningStore
from tests import test_native_elearning_web as native_fixture


def production_fixture():
    return {
        "id": "production-fixture", "title": "Rédiger une transmission",
        "brief": "Décrivez les faits observés et la transmission à réaliser.",
        "documents": [{"title": "Main courante fictive", "text": "09 h 12 : porte ouverte."}],
        "response_fields": [
            {"id": "facts", "label": "Faits observés", "min_chars": 20, "max_chars": 600},
            {"id": "action", "label": "Action proposée", "min_chars": 20, "max_chars": 600},
        ],
        "rubric": [
            {"id": "source", "label": "Je distingue observation et déduction.", "guidance": "Indiquez votre source."},
            {"id": "recipient", "label": "Je précise le destinataire.", "guidance": "Vérifiez la consigne."},
        ],
        "model_response": {"facts": "MODELE-PRIVE : la porte est ouverte à 09 h 12.",
                           "action": "REPERE-PRIVE : prévenir le responsable désigné."},
    }


ANSWERS = {"facts": "À 09 h 12, j'observe que la porte nord est ouverte.",
           "action": "Je préviens le responsable indiqué dans la consigne."}
SELF_REVIEW = {"source": "checked", "recipient": "needs_help"}


class APS62ProductionAccessTests(unittest.TestCase):
    # Reuse the isolated native HTTP fixture without inheriting its unrelated tests.
    tearDown = native_fixture.NativeElearningWebTests.tearDown
    _public_login = native_fixture.NativeElearningWebTests._public_login
    _admin_login = native_fixture.NativeElearningWebTests._admin_login
    _api_post = native_fixture.NativeElearningWebTests._api_post
    _preview_config = native_fixture.NativeElearningWebTests._preview_config
    _player_config = staticmethod(native_fixture.NativeElearningWebTests._player_config)

    def setUp(self):
        native_fixture.NativeElearningWebTests.setUp(self)
        first = self.course["sections"][0]["activities"][0]
        first.update(production=production_fixture(), blocks=[])
        # Production rendering must not depend on an unrelated legacy academy block.
        first.pop("academy", None)
        second = copy.deepcopy(first)
        second.update(id="production-next", title="Production suivante")
        self.course["sections"][0]["activities"].insert(1, second)
        self.course["activity_order"].insert(1, second["id"])
        self.course_path = (self.persist_dir / "native_elearning" / "courses" /
                            self.course["id"] / self.course["version"] / "course.json")
        self._save_course()

    def _save_course(self):
        self.course_path.write_text(json.dumps(self.course), encoding="utf-8")

    def _open(self, client=None, token="public-token", activity="content-1"):
        client = client or self.client
        with client.session_transaction() as session:
            session["public_auth_" + token] = True
        response = client.get(f"/espace/{token}/elearning/{self.course['id']}",
                              query_string={"activity": activity})
        self.assertEqual(response.status_code, 200, response.text)
        return response, self._player_config(response)

    @staticmethod
    def _production_config(response):
        match = re.search(r'<script id="apsProductionConfig" type="application/json">(.*?)</script>',
                          response.text, flags=re.DOTALL)
        if not match:
            raise AssertionError("Configuration de production introuvable")
        return json.loads(html.unescape(match.group(1)))

    def _post(self, config, *, activity="content-1", stage="compare", answers=None, **extra):
        return self._api_post(f"/api/elearning/v1/activities/{activity}/production", config,
                              stage=stage, production_answers=answers or ANSWERS, **extra)

    def _rows(self):
        return NativeElearningStore(self.persist_dir / "native_elearning" / "tracking.sqlite3").live_progress(self.course["id"])

    def test_learner_production_requires_csrf_and_a_current_browser_session(self):
        _, config = self._open()
        url = "/api/elearning/v1/activities/content-1/production"
        payload = {"access_token": config["accessToken"], "stage": "compare", "production_answers": ANSWERS}
        for headers in ({}, {"X-Elearning-CSRF": "incorrect"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.client.post(url, json=payload, headers=headers).status_code, 403)
        with self.client.session_transaction() as session:
            session.pop("public_auth_public-token")
        self.assertEqual(self.client.post(url, json=payload,
            headers={"X-Elearning-CSRF": config["csrfToken"]}).status_code, 401)
        self.assertEqual(self._rows()[0]["answers"], {})

    def test_comparison_and_completion_cannot_skip_an_activity(self):
        _, config = self._open()
        for stage in ("draft", "compare"):
            with self.subTest(stage=stage):
                response = self._post(config, activity="production-next", stage=stage)
                self.assertEqual(response.status_code, 409)
                self.assertNotIn("MODELE-PRIVE", response.text)
        complete = self._api_post("/api/elearning/v1/activities/production-next/complete", config,
                                  production_answers=ANSWERS, production_self_review=SELF_REVIEW)
        self.assertEqual(complete.status_code, 409)
        page, _ = self._open(activity="production-next")
        self.assertIn('data-activity-id="content-1"', page.text)
        row = self._rows()[0]
        self.assertEqual(row["answers"], {})
        self.assertEqual(row["completed_activity_ids"], [])

    def test_draft_and_comparison_cannot_bypass_required_video(self):
        # Disable sequence ordering: the video rule must independently protect access.
        self.course["settings"]["force_navigation"] = False
        self.course["sections"][0]["activities"][0]["blocks"] = [{"id": "required-video", "type": "video",
            "video": {"id": "required-video", "required": True, "duration_seconds": 60, "src": "media/test.mp4"}}]
        self._save_course()
        _, config = self._open()
        for stage in ("draft", "compare"):
            self.assertEqual(self._post(config, activity="production-next", stage=stage).status_code, 409)
        self.assertEqual(self._rows()[0]["answers"], {})

    def test_invalid_activity_and_revoked_assignment_do_not_store_work(self):
        _, config = self._open()
        for activity in ("absent", "question-1"):
            self.assertEqual(self._post(config, activity=activity).status_code, 404)
        self.data["sessions"][0]["aps_elearning_enabled"] = False
        self.assertEqual(self._post(config).status_code, 403)
        self.assertEqual(self._rows()[0]["answers"], {})

    def test_signed_access_is_bound_to_browser_and_ignores_forged_identity(self):
        second = {"id": "trainee-2", "public_token": "second-token", "first_name": "Boris", "last_name": "Durand", "documents": []}
        self.data["sessions"][0]["trainees"].append(second)
        _, first_config = self._open()
        other = host.app.test_client()
        _, second_config = self._open(other, "second-token")
        url = "/api/elearning/v1/activities/content-1/production"
        borrowed = other.post(url, json={"access_token": first_config["accessToken"],
            "stage": "compare", "production_answers": ANSWERS},
            headers={"X-Elearning-CSRF": second_config["csrfToken"]})
        self.assertEqual(borrowed.status_code, 401)
        saved = self._post(first_config, trainee_id="trainee-2", session_id="other-session")
        self.assertEqual(saved.status_code, 200)
        rows = {row["trainee_id"]: row for row in self._rows()}
        self.assertEqual(rows["trainee-1"]["answers"]["content-1"]["production_answers"], ANSWERS)
        self.assertEqual(rows["trainee-2"]["answers"], {})
        other_page, _ = self._open(other, "second-token")
        self.assertNotIn("MODELE-PRIVE", other_page.text)
        self.assertEqual(self._production_config(other_page)["saved"], {})

    def test_preview_reveals_repere_only_after_valid_submission_without_tracking(self):
        self._admin_login()
        with patch("elearning_native.web.NativeElearningStore", side_effect=AssertionError("Preview must not track")):
            page, config = self._preview_config("content-1")
            self.assertNotIn("MODELE-PRIVE", page)
            self.assertNotIn("REPERE-PRIVE", page)
            self.assertEqual(self.client.post(config["answerUrl"], json={"production_answers": ANSWERS}).status_code, 403)
            result = self.client.post(config["answerUrl"], json={"production_answers": ANSWERS},
                                      headers={"X-Elearning-CSRF": config["csrfToken"]})
            self.assertEqual(result.status_code, 200)
            self.assertIn("MODELE-PRIVE", result.text)
            self.assertIn("no-store", result.headers["Cache-Control"])
        self.assertIsNone(self.saved_data)
        self.assertFalse((self.persist_dir / "native_elearning" / "tracking.sqlite3").exists())

    def test_viewer_can_read_preview_but_cannot_reveal_or_submit_production(self):
        self._admin_login()
        with self.client.session_transaction() as session:
            session["admin_role"] = "viewer"
        page, config = self._preview_config("content-1")
        self.assertRegex(page, r'<button[^>]*type="submit"[^>]*disabled[^>]*>Comparer')
        self.assertNotIn("MODELE-PRIVE", page)
        response = self.client.post(config["answerUrl"], json={"production_answers": ANSWERS},
                                    headers={"X-Elearning-CSRF": config["csrfToken"]})
        self.assertEqual(response.status_code, 403)
        self.assertFalse((self.persist_dir / "native_elearning" / "tracking.sqlite3").exists())

    def test_production_lifecycle_keeps_first_response_and_freezes_completed_work(self):
        page, config = self._open()
        self.assertNotIn("feedback", self._production_config(page)["production"])
        initial_score = self._rows()[0]["score_percent"]
        complete_url = "/api/elearning/v1/activities/content-1/complete"
        early = self._api_post(complete_url, config, production_answers=ANSWERS,
                               production_self_review=SELF_REVIEW)
        self.assertEqual(early.status_code, 400)
        self.assertEqual(self._rows()[0]["completed_activity_ids"], [])
        first = {**ANSWERS, "facts": "PREMIER-ESSAI : je constate une porte ouverte à 09 h 12."}
        draft = self._post(config, stage="draft", answers=first)
        self.assertEqual(draft.status_code, 200)
        self.assertNotIn("feedback", draft.get_json())
        saved = self._rows()[0]["answers"]["content-1"]
        self.assertTrue(saved["production_draft"])
        self.assertNotIn("production_first_answers", saved)
        self.assertNotIn("production_feedback_seen", saved)
        self.assertEqual(self._api_post(complete_url, config, production_answers=first,
            production_self_review=SELF_REVIEW).status_code, 400)
        compared = self._post(config, answers=first)
        self.assertEqual(compared.status_code, 200)
        self.assertIn("MODELE-PRIVE", compared.text)
        self.assertIn("no-store", compared.headers["Cache-Control"])
        reloaded, _ = self._open()
        self.assertIn("feedback", self._production_config(reloaded)["production"])
        revised = {**ANSWERS, "facts": "ESSAI-REVISE : je constate que la porte nord est ouverte à 09 h 12."}
        self.assertEqual(self._post(config, stage="draft", answers=revised).status_code, 200)
        saved = self._rows()[0]["answers"]["content-1"]
        self.assertEqual(saved["production_first_answers"], first)
        self.assertEqual(saved["production_answers"], revised)
        self.assertEqual(self._rows()[0]["completed_activity_ids"], [])
        finished = self._api_post(complete_url, config, production_answers=revised,
                                  production_self_review=SELF_REVIEW)
        self.assertEqual(finished.status_code, 200, finished.text)
        row = self._rows()[0]
        saved = row["answers"]["content-1"]
        self.assertFalse(saved["production_draft"])
        self.assertTrue(saved["needs_trainer_help"])
        self.assertEqual(saved["production_self_review"], SELF_REVIEW)
        self.assertEqual(saved["production_first_answers"], first)
        self.assertEqual(saved["review_status"], "self_reviewed")
        self.assertNotIn("correct", saved)
        self.assertEqual(row["score_percent"], initial_score)
        self.assertEqual(row["completed_activity_ids"], ["content-1"])
        immutable = copy.deepcopy(saved)
        for stage in ("draft", "compare"):
            self.assertEqual(self._post(config, stage=stage, answers=ANSWERS).status_code, 200)
        self.assertEqual(self._api_post(complete_url, config, production_answers=ANSWERS,
            production_self_review={"source": "checked", "recipient": "checked"}).status_code, 200)
        self.assertEqual(self._rows()[0]["answers"]["content-1"], immutable)

    def test_admin_work_shows_private_draft_first_submission_and_help_request(self):
        _, config = self._open()
        first = {**ANSWERS, "facts": "PREMIERE-REPONSE : à 09 h 12, la porte est ouverte."}
        self.assertEqual(self._post(config, answers=first).status_code, 200)
        final = {**ANSWERS, "facts": "VERSION-REVISEE : à 09 h 12, la porte nord est ouverte. <script>evil()</script>"}
        self.assertEqual(self._post(config, stage="draft", answers=final).status_code, 200)
        work_url = f"/admin/elearning/courses/{self.course['id']}/work"
        self.assertEqual(self.client.get(work_url).status_code, 302)
        self._admin_login()
        draft = self.client.get(work_url)
        self.assertEqual(draft.status_code, 200)
        self.assertIn("Brouillon", draft.text)
        self.assertIn("PREMIERE-REPONSE", draft.text)
        self.assertIn("VERSION-REVISEE", draft.text)
        self.assertNotIn("<script>evil()</script>", draft.text)
        self.assertIn("&lt;script&gt;evil()&lt;/script&gt;", draft.text)
        # The live dashboard never returns private production text or corrections.
        live = self.client.get(f"/api/admin/elearning/courses/{self.course['id']}/live")
        self.assertEqual(live.status_code, 200)
        self.assertNotIn("VERSION-REVISEE", live.text)
        self.assertNotIn("answers", live.get_json()["learners"][0])
        complete = self._api_post("/api/elearning/v1/activities/content-1/complete", config,
                                  production_answers=final, production_self_review=SELF_REVIEW)
        self.assertEqual(complete.status_code, 200, complete.text)
        work = self.client.get(work_url)
        self.assertIn("Production avec autoévaluation", work.text)
        self.assertIn("Aide du formateur souhaitée", work.text)
        self.assertIn("Vérifié par le stagiaire", work.text)
        self.assertIn("PREMIERE-REPONSE", work.text)
        self.assertIn("VERSION-REVISEE", work.text)
        exported = self.client.get(work_url + ".csv")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("Faits observés", exported.text)
        self.assertIn("VERSION-REVISEE", exported.text)
        self.assertNotIn("MODELE-PRIVE", exported.text)


# The commercial fixture runs both local JSON and the tenant PostgreSQL adapter.
from test_manuals_shop import shop, signup, login  # noqa: E402, F401
from test_elearning_reporting import activated, seed_course, tracked, report_url, database_dump  # noqa: E402


def test_organisation_production_reporting_is_pinned_private_and_read_only(shop):
    order, root = seed_course(activated(shop))
    for version in ("v1", "v2"):
        path = root / "courses" / "report-fixture" / version / "course.json"
        course = json.loads(path.read_text())
        course["sections"][0]["activities"][0]["production"] = production_fixture()
        path.write_text(json.dumps(course))
    store, access, _ = tracked(root, order, complete=False)
    for marker, overrides in (
        ("MON-TRAVAIL", {}), ("AUTRE-VERSION", {"version": "v2"}),
        ("AUTRE-COMMANDE", {"session_id": "el-another-order"}),
        ("AUTRE-STAGIAIRE", {"learner_id": order["learners"][1]["id"]}),
    ):
        _, scoped_access, _ = tracked(root, order, complete=False, **overrides)
        store.record_production(scoped_access, "read", {**ANSWERS, "facts": marker + " : des faits décrits avec leur source."}, compared=True)
    before = database_dump(root)
    report = reporting.ProgressReader(host).report(order, order["learners"][0])
    written = report["modules"][0]["sections"][0]["activities"][0]["production"]
    assert written["draft"] is True
    assert "MON-TRAVAIL" in written["responses"][0]["text"]
    assert "AUTRE-" not in json.dumps(report)
    assert "MODELE-PRIVE" not in json.dumps(report)
    assert "production" not in json.dumps(reporting.ProgressReader(host).report(order, order["learners"][0], detailed=False))
    own = shop["client"].get(report_url(order))
    assert own.status_code == 200
    assert "MON-TRAVAIL" in own.text and "AUTRE-" not in own.text
    assert "Brouillon" in own.text and "MODELE-PRIVE" not in own.text
    assert "no-store" in own.headers["Cache-Control"]
    assert database_dump(root) == before
    # A separate organism cannot retrieve work even with the exact order/person URL.
    other = host.app.test_client()
    signup(other, email="other-production@example.test")
    login(other, email="other-production@example.test")
    for suffix in ("", "/attestation.pdf", "/connexions.csv"):
        denied = other.get(report_url(order) + suffix)
        assert denied.status_code == 404 and "MON-TRAVAIL" not in denied.text
    assert database_dump(root) == before


def test_organisation_report_shows_self_review_and_help_without_awarding_grade(shop):
    order, root = seed_course(activated(shop))
    path = root / "courses" / "report-fixture" / "v1" / "course.json"
    course = json.loads(path.read_text())
    course["sections"][0]["activities"][0]["production"] = production_fixture()
    path.write_text(json.dumps(course))
    store, access, _ = tracked(root, order, complete=False)
    store.record_production(access, "read", ANSWERS, compared=True)
    store.complete_activity(access, "read", activity_order=["read", "question"],
        scored_activity_ids=["question"], mastery_score=80, required_seconds=60,
        answer={"production_answers": ANSWERS, "production_self_review": SELF_REVIEW,
                "production_draft": False, "review_status": "self_reviewed", "needs_trainer_help": True})
    before = database_dump(root)
    report = reporting.ProgressReader(host).report(order, order["learners"][0])
    module = report["modules"][0]
    production = module["sections"][0]["activities"][0]["production"]
    assert not production["draft"]
    assert [criterion["needs_help"] for criterion in production["review"]] == [False, True]
    assert module["score_percent"] is None and not report["complete"]
    response = shop["client"].get(report_url(order))
    assert response.status_code == 200
    assert "Aide" in response.text and "formateur" in response.text
    assert ANSWERS["action"] in response.text
    assert "MODELE-PRIVE" not in response.text
    assert database_dump(root) == before
