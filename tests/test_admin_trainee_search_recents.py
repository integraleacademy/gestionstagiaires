import unittest
from unittest.mock import patch

import app as gestion_app


class AdminTraineeSearchRecentsTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True

        self.fake_data = {
            "sessions": [
                {
                    "id": "S-1",
                    "name": "APS Juin 2026",
                    "training_type": "APS",
                    "trainees": [
                        {
                            "id": f"T-{index}",
                            "first_name": f"Prenom{index}",
                            "last_name": f"Nom{index}",
                            "created_at": f"2026-06-{index:02d}T10:00:00Z",
                        }
                        for index in range(1, 8)
                    ],
                },
                {
                    "id": "S-VAE",
                    "name": "VAE DESP 2026",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "id": "T-VAE",
                            "first_name": "Vae",
                            "last_name": "Recent",
                            "created_at": "2026-06-20T10:00:00Z",
                        }
                    ],
                },
                {
                    "id": "wedof-cpf-edof",
                    "name": "Leads WeDoF CPF/EDOF",
                    "training_type": "CPF/EDOF",
                    "trainees": [
                        {
                            "id": "T-WEDOF",
                            "first_name": "Lead",
                            "last_name": "Recent",
                            "created_at": "2026-06-12T10:00:00Z",
                        }
                    ],
                },
            ]
        }

    def test_empty_search_returns_two_latest_and_two_consulted(self):
        with self.client.session_transaction() as sess:
            sess[gestion_app.ADMIN_RECENT_TRAINEES_SESSION_KEY] = [
                {"session_id": "S-1", "trainee_id": "T-2"},
                {"session_id": "missing", "trainee_id": "missing"},
                {"session_id": "S-1", "trainee_id": "T-6"},
                {"session_id": "S-1", "trainee_id": "T-4"},
            ]

        with patch.object(gestion_app, "load_data", return_value=self.fake_data):
            response = self.client.get("/api/trainees_search?q=")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(
            [item["trainee_id"] for item in payload["latest_registered"]],
            ["T-7", "T-6"],
        )
        self.assertEqual(
            [item["trainee_id"] for item in payload["recent_consulted"]],
            ["T-2", "T-6"],
        )
        self.assertNotIn("T-WEDOF", str(payload))
        self.assertNotIn("T-VAE", [item["trainee_id"] for item in payload["latest_registered"]])

    def test_remember_consultation_deduplicates_and_limits_history(self):
        with gestion_app.app.test_request_context("/"):
            gestion_app.session[gestion_app.ADMIN_RECENT_TRAINEES_SESSION_KEY] = [
                {"session_id": "S-1", "trainee_id": "T-1"},
                {"session_id": "S-1", "trainee_id": "T-2"},
                {"session_id": "S-1", "trainee_id": "T-3"},
            ]

            gestion_app._remember_admin_trainee_consultation("S-1", "T-2")
            gestion_app._remember_admin_trainee_consultation("S-1", "T-4")

            self.assertEqual(
                gestion_app.session[gestion_app.ADMIN_RECENT_TRAINEES_SESSION_KEY],
                [
                    {"session_id": "S-1", "trainee_id": "T-4"},
                    {"session_id": "S-1", "trainee_id": "T-2"},
                ],
            )

    def test_sessions_page_contains_focus_suggestion_sections(self):
        with patch.object(gestion_app, "load_data", return_value={"sessions": []}), patch.object(
            gestion_app, "_load_wedof_webhooks", return_value=[]
        ):
            response = self.client.get("/admin/sessions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("2 derniers inscrits", html)
        self.assertIn("2 derniers dossiers consultés", html)
        self.assertIn("Rechercher une session", html)
        self.assertIn("/api/sessions_search", html)
        self.assertIn('input.addEventListener("focus", loadResults)', html)

    def test_session_search_filters_by_name_and_training(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
                    "name": "APS Juillet 2026",
                    "training_type": "APS",
                    "date_start": "2026-07-01",
                    "date_end": "2026-07-12",
                    "trainees": [{"id": "T-1"}],
                },
                {
                    "id": "S-VTC",
                    "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
                    "name": "VTC Août 2026",
                    "training_type": "VTC",
                    "date_start": "2026-08-01",
                    "date_end": "2026-08-12",
                    "trainees": [],
                },
                {
                    "id": "S-OTHER",
                    "partner_id": "other-partner",
                    "name": "APS autre partenaire",
                    "training_type": "APS",
                },
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/api/sessions_search?q=aps")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["session_id"], "S-APS")
        self.assertEqual(payload["items"][0]["total"], 1)
        self.assertEqual(payload["items"][0]["admin_url"], "/admin/sessions/S-APS/trainees")


if __name__ == "__main__":
    unittest.main()
