"""Tenant isolation of native dashboards, written work and assessment exports.

The shared tracking/AI databases contain two synthetic centres. The host's real
partner session guard runs, while load_data returns only the signed-in centre's
administrative records. Central administrators retain the global view.
"""
from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

import app as host
from flask import has_request_context
from elearning_native.production_ai import ProductionAIService
from elearning_native.store import NativeElearningStore
from tests import test_native_elearning_web as native_fixture
from tests.test_aps_production_ai import ANSWERS, PRODUCTION, FakeResponse, envelope, valid_output


class NativeElearningTenantExportTests(unittest.TestCase):
    def setUp(self):
        native_fixture.NativeElearningWebTests.setUp(self)
        activity = self.course["sections"][0]["activities"][0]
        activity.update(production=copy.deepcopy(PRODUCTION), blocks=[])
        activity.pop("academy", None)
        path = (self.persist_dir / "native_elearning" / "courses" /
                self.course["id"] / self.course["version"] / "course.json")
        path.write_text(json.dumps(self.course), encoding="utf-8")
        self.partner_a = {"id": "centre-a-fictif", "name": "OF A fictif", "status": "active",
                          "account_type": "partner", "enabled_modules": ["training_aps"]}
        self.partner_b = {**self.partner_a, "id": "centre-b-fictif", "name": "OF B fictif"}
        self.user_a = {"id": "user-a-fictif", "partner_id": self.partner_a["id"], "role": "partner_admin",
                       "active": True, "email": "a@example.test"}
        self.user_b = {**self.user_a, "id": "user-b-fictif", "partner_id": self.partner_b["id"], "email": "b@example.test"}
        first = self.data["sessions"][0]
        first["partner_id"] = self.partner_a["id"]
        first["trainees"][0]["partner_id"] = self.partner_a["id"]
        second = copy.deepcopy(first)
        second.update(id="session-b-fictive", name="Session OF B fictive", partner_id=self.partner_b["id"])
        second["trainees"][0].update(id="trainee-b-fictif", first_name="Benoit", last_name="Fictif",
                                      public_token="public-b-fictif", partner_id=self.partner_b["id"])
        self.data.update(partners=[self.partner_a, self.partner_b], users=[self.user_a, self.user_b])
        self.data["sessions"].append(second)
        self.tenant_data = {}
        for partner, user, session_obj in ((self.partner_a, self.user_a, first), (self.partner_b, self.user_b, second)):
            self.tenant_data[partner["id"]] = {"partners": [partner], "users": [user], "sessions": [session_obj]}

        def visible_data(*args, **kwargs):
            if has_request_context() and host._is_partner_data_scope_session():
                return self.tenant_data.get(host._current_partner_id(), {"partners": [], "users": [], "sessions": []})
            return self.data

        host.load_data.side_effect = visible_data
        self.auth_patch = patch.object(host, "_load_partner_auth_data", return_value=self.data)
        self.auth_patch.start()
        self.tracking = NativeElearningStore(self.persist_dir / "native_elearning" / "tracking.sqlite3")
        self.ai = ProductionAIService(self.persist_dir / "native_elearning" / "production_ai.sqlite3",
                                      api_key="synthetic-only-key", background=False)
        self.scopes = {}
        for label, sess in (("A", first), ("B", second)):
            access = {"session_id": sess["id"], "trainee_id": sess["trainees"][0]["id"],
                      "course_id": self.course["id"], "course_version": self.course["version"]}
            self.scopes[label] = access
            answers = {**ANSWERS, "analyse": ANSWERS["analyse"] + " PRODUCTION-PRIVEE-OF-" + label}
            self.tracking.record_production(access, "content-1", answers, capture_first=True)
            self.tracking.record_question_attempt(access, "question-1", {"selected": ["REPONSE-PRIVEE-OF-" + label]},
                                                   False, request_id="request-private-" + label)
            job = self.ai.request_analysis(access, PRODUCTION, answers, activity_id="content-1")
            output = valid_output()
            output["summary"] = "ANALYSE-PRIVEE-OF-" + label
            with patch("elearning_native.production_ai.urlopen", return_value=FakeResponse(envelope(output))):
                self.ai._run_job(job["id"])

    def tearDown(self):
        self.ai.shutdown()
        self.auth_patch.stop()
        native_fixture.NativeElearningWebTests.tearDown(self)

    def login_partner(self, user, *, viewer=False):
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session.update(admin_logged_in=True, admin_role="viewer" if viewer else "partner_admin",
                                   partner_id=user["partner_id"], user_id=user["id"], admin_username=user["email"])

    def route(self, suffix, *, api=False):
        return ("/api/admin" if api else "/admin") + f"/elearning/courses/{self.course['id']}/" + suffix

    def assert_dashboard_scope(self, labels):
        response = self.client.get(self.route("live", api=True))
        self.assertEqual(response.status_code, 200, response.text[:200])
        expected = {(self.scopes[label]["session_id"], self.scopes[label]["trainee_id"]) for label in labels}
        data = response.get_json()
        actual = {(row["session_id"], row["trainee_id"]) for row in data["learners"]}
        self.assertEqual(actual, expected)
        self.assertEqual(data["summary"]["learners"], len(expected))
        live = self.client.get(self.route("live"))
        self.assertEqual(live.status_code, 200)
        for label in {"A", "B"} - set(labels):
            self.assertNotIn(self.scopes[label]["trainee_id"], live.text)

    def assert_private_exports_scope(self, visible, hidden):
        routes = (("work.csv", "PRODUCTION-PRIVEE-OF-"),
                  ("attempts.csv", "REPONSE-PRIVEE-OF-"),
                  ("work", "ANALYSE-PRIVEE-OF-"),
                  ("attempts", "REPONSE-PRIVEE-OF-"))
        for suffix, marker in routes:
            with self.subTest(route=suffix):
                response = self.client.get(self.route(suffix))
                self.assertEqual(response.status_code, 200, response.text[:200])
                for label in visible:
                    self.assertIn(marker + label, response.text)
                for label in hidden:
                    self.assertNotIn(marker + label, response.text)
                    self.assertNotIn(self.scopes[label]["trainee_id"], response.text)

    def test_partner_admin_exports_only_its_own_traces_and_ai_feedback(self):
        for user, visible, hidden in ((self.user_a, "A", "B"), (self.user_b, "B", "A")):
            with self.subTest(partner=user["partner_id"]):
                self.login_partner(user)
                self.assert_dashboard_scope([visible])
                self.assert_private_exports_scope([visible], [hidden])

    def test_partner_read_only_account_does_not_gain_cross_tenant_access(self):
        self.login_partner(self.user_a, viewer=True)
        self.assert_dashboard_scope(["A"])
        self.assert_private_exports_scope(["A"], ["B"])

    def test_central_administrator_retains_both_centres(self):
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
            browser_session.update(admin_logged_in=True, admin_role="admin", partner_id=host.INTEGRALE_PARTNER_ID,
                                   admin_username="central@example.test")
        self.assert_dashboard_scope(["A", "B"])
        self.assert_private_exports_scope(["A", "B"], [])


if __name__ == "__main__":
    unittest.main()
