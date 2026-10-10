"""Regression checks for progressive production drafts and private self-review."""
from __future__ import annotations

import copy
import html
import json
import re
import unittest

from elearning_native.store import NativeElearningStore
from tests import test_native_elearning_web as native_fixture


PRODUCTION = {
    "id": "draft-review-fixture", "title": "Rédiger une transmission",
    "brief": "Rédigez votre constat et la transmission au poste de contrôle.",
    "documents": [{"title": "Notes brutes fictives", "text": "09 h 12 : porte nord ouverte."}],
    "response_fields": [
        {"id": "facts", "label": "Constat", "min_chars": 20, "max_chars": 600},
        {"id": "action", "label": "Transmission", "min_chars": 20, "max_chars": 600},
    ],
    "rubric": [
        {"id": "source", "label": "CRITERE-SOURCE-PRIVE", "expected": "Distinguer le constat de la déduction."},
        {"id": "recipient", "label": "CRITERE-DESTINATAIRE-PRIVE", "expected": "Préciser qui reçoit le message."},
    ],
    "model_response": {"facts": "MODELE-PRIVE : je constate la porte nord ouverte à 09 h 12.",
                       "action": "REPERE-PRIVE : je transmets ce constat au poste de contrôle."},
}
FIRST = {"facts": "À 09 h 12, je constate que la porte nord est ouverte.",
         "action": "Je transmets ce constat au poste de contrôle par radio."}
REVISED = {**FIRST, "action": "Je transmets au poste de contrôle le lieu, l'heure et le constat."}
PARTIAL = {"source": "needs_help", "recipient": ""}
COMPLETE = {"source": "needs_help", "recipient": "checked"}


class ProductionDraftReviewTests(unittest.TestCase):
    # Reuse the isolated web setup without inheriting unrelated test cases.
    tearDown = native_fixture.NativeElearningWebTests.tearDown
    _public_login = native_fixture.NativeElearningWebTests._public_login
    _admin_login = native_fixture.NativeElearningWebTests._admin_login
    _api_post = native_fixture.NativeElearningWebTests._api_post
    _player_config = staticmethod(native_fixture.NativeElearningWebTests._player_config)

    def setUp(self):
        native_fixture.NativeElearningWebTests.setUp(self)
        self.course["sections"][0]["activities"][0].update(
            production=copy.deepcopy(PRODUCTION), blocks=[])
        path = (self.persist_dir / "native_elearning" / "courses" /
                self.course["id"] / self.course["version"] / "course.json")
        path.write_text(json.dumps(self.course), encoding="utf-8")
        self._public_login()
        self.page, self.config = self._open()

    def _open(self):
        response = self.client.get(f"/espace/public-token/elearning/{self.course['id']}",
                                   query_string={"activity": "content-1"})
        self.assertEqual(response.status_code, 200, response.text)
        return response, self._player_config(response)

    @staticmethod
    def _production_config(page):
        match = re.search(r'<script id="apsProductionConfig" type="application/json">(.*?)</script>',
                          page.text, flags=re.DOTALL)
        if not match:
            raise AssertionError("Configuration de production introuvable")
        return json.loads(html.unescape(match.group(1)))

    def _row(self):
        database = self.persist_dir / "native_elearning" / "tracking.sqlite3"
        return NativeElearningStore(database).live_progress(self.course["id"])[0]

    def _saved(self):
        return self._row()["answers"].get("content-1", {})

    def _post(self, *, stage="draft", answers=None, **extra):
        return self._api_post("/api/elearning/v1/activities/content-1/production", self.config,
                              stage=stage, production_answers=FIRST if answers is None else answers,
                              **extra)

    def _compare(self):
        response = self._post(stage="compare")
        self.assertEqual(response.status_code, 200, response.text)
        return copy.deepcopy(self._saved())

    def test_self_review_cannot_reveal_feedback_or_replace_draft_before_comparison(self):
        self.assertEqual(self._post(answers={"facts": "Début du brouillon"}).status_code, 200)
        before = copy.deepcopy(self._saved())
        for stage in ("draft", "compare"):
            with self.subTest(stage=stage):
                response = self._post(stage=stage, production_self_review=PARTIAL)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn("feedback", response.get_json())
                self.assertEqual(self._saved(), before)
        page, _ = self._open()
        self.assertNotIn("feedback", self._production_config(page)["production"])
        for secret in ("MODELE-PRIVE", "CRITERE-SOURCE-PRIVE", "CRITERE-DESTINATAIRE-PRIVE"):
            self.assertNotIn(secret, page.text)
        self.assertNotIn("production_self_review", self._saved())
        self.assertEqual(self._row()["completed_activity_ids"], [])

    def test_partial_review_and_revised_text_are_restored_without_completing(self):
        first = self._compare()
        response = self._post(answers=REVISED, production_self_review=PARTIAL)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("feedback", response.get_json())
        self.assertIn("no-store", response.headers["Cache-Control"])
        page, _ = self._open()
        restored = self._production_config(page)
        self.assertEqual(restored["saved"]["production_answers"], REVISED)
        self.assertEqual(restored["saved"]["production_self_review"], PARTIAL)
        self.assertEqual(restored["saved"]["production_first_answers"], FIRST)
        self.assertEqual(restored["saved"]["production_first_submitted_at"],
                         first["production_first_submitted_at"])
        self.assertTrue(restored["saved"]["production_draft"])
        self.assertIn("feedback", restored["production"])
        self.assertFalse(restored["completed"])
        self.assertEqual(self._row()["completed_activity_ids"], [])

    def test_omitted_review_preserves_it_and_explicit_empty_values_clear_it(self):
        first = self._compare()
        self.assertEqual(self._post(production_self_review=PARTIAL).status_code, 200)
        for stage in ("draft", "compare"):
            with self.subTest(stage=stage):
                self.assertEqual(self._post(stage=stage, answers=REVISED).status_code, 200)
                self.assertEqual(self._saved()["production_self_review"], PARTIAL)
        empty = {"source": "", "recipient": ""}
        self.assertEqual(self._post(production_self_review=empty).status_code, 200)
        page, _ = self._open()
        self.assertEqual(self._production_config(page)["saved"]["production_self_review"], empty)
        self.assertEqual(self._saved()["production_first_answers"], FIRST)
        self.assertEqual(self._saved()["production_first_submitted_at"], first["production_first_submitted_at"])

    def test_invalid_reviews_are_atomic_and_incomplete_review_cannot_finish(self):
        self._compare()
        self.assertEqual(self._post(production_self_review=PARTIAL).status_code, 200)
        before = copy.deepcopy(self._saved())
        invalid = [None, [], {}, {"source": "checked"},
                   {**PARTIAL, "extra": "checked"},
                   {"source": True, "recipient": ""},
                   {"source": ["checked"], "recipient": ""},
                   {"source": "validated", "recipient": ""}]
        for supplied in invalid:
            with self.subTest(supplied=supplied):
                response = self._post(answers=REVISED, production_self_review=supplied)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(self._saved(), before)
        response = self._api_post("/api/elearning/v1/activities/content-1/complete", self.config,
                                  production_answers=REVISED, production_self_review=PARTIAL)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._saved(), before)
        self.assertEqual(self._row()["completed_activity_ids"], [])

    def test_blank_criteria_are_not_reported_verified_and_completed_review_is_frozen(self):
        self._compare()
        self.assertEqual(self._post(production_self_review=PARTIAL).status_code, 200)
        self._admin_login()
        report = self.client.get(f"/admin/elearning/courses/{self.course['id']}/work")
        self.assertEqual(report.status_code, 200, report.text)
        self.assertIn("CRITERE-SOURCE-PRIVE", report.text)
        self.assertIn("Aide du formateur souhaitée", report.text)
        self.assertNotIn("CRITERE-DESTINATAIRE-PRIVE", report.text)
        self.assertNotIn("Vérifié par le stagiaire", report.text)
        response = self._api_post("/api/elearning/v1/activities/content-1/complete", self.config,
                                  production_answers=REVISED, production_self_review=COMPLETE)
        self.assertEqual(response.status_code, 200, response.text)
        completed = copy.deepcopy(self._saved())
        self.assertEqual(completed["production_self_review"], COMPLETE)
        self.assertFalse(completed["production_draft"])
        self.assertTrue(completed["needs_trainer_help"])
        self.assertEqual(completed["review_status"], "self_reviewed")
        self.assertNotIn("correct", completed)
        for stage in ("draft", "compare"):
            with self.subTest(stage=stage):
                self.assertEqual(self._post(stage=stage, production_self_review={
                    "source": "", "recipient": ""}).status_code, 200)
                self.assertEqual(self._saved(), completed)


if __name__ == "__main__":
    unittest.main()
