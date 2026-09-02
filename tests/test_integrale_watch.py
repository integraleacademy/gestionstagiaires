import datetime
import copy
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import app as gestion_app


class IntegraleWatchTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.today = datetime.datetime.now(ZoneInfo("Europe/Paris")).date()
        self.data = {
            "sessions": [
                {
                    "id": "SESSION-APS",
                    "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
                    "name": "APS septembre",
                    "training_type": "APS",
                    "trainees": [
                        {
                            "id": "T-ALICE",
                            "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
                            "first_name": "Alice",
                            "last_name": "Active",
                            "created_at": self.today.isoformat(),
                            "sales_tracking_amount": 1650,
                        },
                        {
                            "id": "T-SECRET",
                            "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
                            "first_name": "Camille",
                            "last_name": "Annulée",
                            "email": "camille@example.test",
                            "created_at": self.today.isoformat(),
                            "sales_tracking_amount": 9999,
                            "registration_cancelled": True,
                        },
                    ],
                },
                {
                    "id": "SESSION-A3P",
                    "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
                    "name": "A3P septembre",
                    "training_type": "A3P",
                    "trainees": [
                        {
                            "id": "T-BOB",
                            "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
                            "first_name": "Bob",
                            "last_name": "Vente",
                            "created_at": self.today.isoformat(),
                            "sales_tracking_amount": 4200,
                        }
                    ],
                },
            ],
            "sales_tracking": {
                "objectives": {
                    str(self.today.year): {
                        "annual": 250000,
                        "months": {str(self.today.month): 10000},
                    }
                }
            },
            "integrale_watch": {"pairing_codes": [], "devices": []},
            "activity_logs": [],
            "partners": [],
            "users": [],
        }
        with self.client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
            flask_session["admin_role"] = "admin"
            flask_session["admin_username"] = "admin@example.test"
            flask_session["partner_id"] = gestion_app.INTEGRALE_PARTNER_ID
        with gestion_app._integrale_watch_pairing_attempts_lock:
            gestion_app._integrale_watch_pairing_attempts.clear()

    def _atomic_update(self, mutator):
        return mutator(self.data)

    def _pair_watch(self):
        with patch.object(gestion_app, "_atomic_update_data", side_effect=self._atomic_update):
            generated = self.client.post("/api/admin/integrale-watch/pairing-code")
            self.assertEqual(generated.status_code, 200)
            code = generated.get_json()["code"]

            paired = self.client.post(
                "/api/watch/v1/pair",
                json={"code": code, "device_name": "Apple Watch Ultra 2"},
            )
        self.assertEqual(paired.status_code, 200)
        return paired.get_json()["token"]

    def test_dashboard_payload_contains_only_aggregated_kpis(self):
        payload = gestion_app._build_integrale_watch_dashboard(self.data, today=self.today)

        self.assertEqual(payload["today"]["revenue_cents"], 585000)
        self.assertEqual(payload["today"]["sales_count"], 2)
        self.assertEqual(payload["month"]["objective_cents"], 1000000)
        self.assertEqual(payload["month"]["progress_percent"], 58.5)
        self.assertEqual(
            [(item["label"], item["sales_count"], item["revenue_cents"]) for item in payload["trainings"]],
            [("A3P", 1, 420000), ("APS", 1, 165000)],
        )
        serialized = str(payload)
        self.assertNotIn("Alice", serialized)
        self.assertNotIn("Camille", serialized)
        self.assertNotIn("camille@example.test", serialized)

    def test_admin_page_explains_pairing_and_lists_devices(self):
        self.data["integrale_watch"]["devices"].append({
            "id": "WATCH-1",
            "name": "Apple Watch Ultra 2",
            "created_at": "2026-09-02T12:00:00Z",
            "revoked_at": "",
            "token_hash": "not-rendered",
            "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
        })
        with patch.object(gestion_app, "load_data", return_value=self.data):
            response = self.client.get("/admin/integrale-watch")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Jumeler une montre", html)
        self.assertIn("Apple Watch Ultra 2", html)
        self.assertNotIn("not-rendered", html)

    def test_one_time_pairing_issues_only_a_hashed_device_token(self):
        token = self._pair_watch()

        self.assertTrue(token.startswith("iw_"))
        self.assertEqual(len(self.data["integrale_watch"]["devices"]), 1)
        device = self.data["integrale_watch"]["devices"][0]
        self.assertEqual(device["name"], "Apple Watch Ultra 2")
        self.assertNotEqual(device["token_hash"], token)
        self.assertEqual(device["token_hash"], gestion_app._hash_token(token))
        self.assertEqual(self.data["integrale_watch"]["pairing_codes"], [])

    def test_pairing_code_cannot_be_reused(self):
        with patch.object(gestion_app, "_atomic_update_data", side_effect=self._atomic_update):
            generated = self.client.post("/api/admin/integrale-watch/pairing-code")
            code = generated.get_json()["code"]
            first = self.client.post("/api/watch/v1/pair", json={"code": code})
            second = self.client.post("/api/watch/v1/pair", json={"code": code})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.get_json()["error"], "pairing_code_invalid")
        self.assertEqual(len(self.data["integrale_watch"]["devices"]), 1)

    def test_stale_business_save_preserves_the_canonical_watch_revocation(self):
        canonical_watch = {
            "pairing_codes": [],
            "devices": [{
                "id": "WATCH-REVOKED",
                "token_hash": "canonical-hash",
                "revoked_at": "2026-09-02T12:00:00Z",
            }],
        }
        canonical = {"sessions": [], "integrale_watch": canonical_watch}
        stale = {"sessions": [{"id": "NEW-BUSINESS-DATA"}], "integrale_watch": {"devices": []}}
        written = {}

        def capture_write(_path, payload, _lock, payload_transform=None):
            merged = payload_transform(copy.deepcopy(payload)) if payload_transform else payload
            written.update(merged)

        with patch.object(gestion_app, "_load_valid_json_payload", return_value=canonical), patch.object(
            gestion_app, "_write_json_with_backups", side_effect=capture_write
        ):
            gestion_app.save_data(stale)

        self.assertEqual(written["sessions"], stale["sessions"])
        self.assertEqual(written["integrale_watch"], canonical_watch)

    def test_dashboard_requires_active_bearer_token_and_revoke_is_immediate(self):
        unauthorized = self.client.get("/api/watch/v1/dashboard")
        self.assertEqual(unauthorized.status_code, 401)
        self.assertIn("Bearer", unauthorized.headers.get("WWW-Authenticate", ""))

        token = self._pair_watch()
        device_id = self.data["integrale_watch"]["devices"][0]["id"]
        with patch.object(gestion_app, "load_data", return_value=self.data):
            authorized = self.client.get(
                "/api/watch/v1/dashboard",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(authorized.get_json()["today"]["sales_count"], 2)
        self.assertIn("no-store", authorized.headers.get("Cache-Control", ""))

        with patch.object(gestion_app, "_atomic_update_data", side_effect=self._atomic_update):
            revoked = self.client.post(f"/api/admin/integrale-watch/devices/{device_id}/revoke")
        self.assertEqual(revoked.status_code, 200)

        with patch.object(gestion_app, "load_data", return_value=self.data):
            rejected = self.client.get(
                "/api/watch/v1/dashboard",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(rejected.status_code, 401)

    def test_pairing_admin_endpoints_are_not_available_to_viewers(self):
        anonymous = gestion_app.app.test_client()
        response = anonymous.post("/api/admin/integrale-watch/pairing-code")
        self.assertEqual(response.status_code, 401)

        viewer = gestion_app.app.test_client()
        with viewer.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
            flask_session["admin_role"] = "viewer"
            flask_session["partner_id"] = gestion_app.INTEGRALE_PARTNER_ID
        response = viewer.post("/api/admin/integrale-watch/pairing-code")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
