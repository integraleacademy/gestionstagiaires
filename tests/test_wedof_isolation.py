import unittest
from unittest.mock import patch

import app as gestion_app


class WedofIsolationTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True

    def test_admin_sessions_and_search_skip_wedof_leads_session(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "name": "APS MAI 2026",
                    "training_type": "APS",
                    "date_start": "2026-05-01",
                    "date_end": "2026-05-31",
                    "trainees": [
                        {
                            "id": "T-1",
                            "first_name": "Océane",
                            "last_name": "Lassouag",
                            "created_at": "2026-05-02",
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
                            "first_name": "Océane",
                            "last_name": "Lassouag",
                            "created_at": "2026-05-02",
                        }
                    ],
                },
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(
            gestion_app, "_load_wedof_webhooks", return_value=[]
        ):
            sessions_resp = self.client.get("/admin/sessions")
            self.assertEqual(sessions_resp.status_code, 200)
            sessions_html = sessions_resp.get_data(as_text=True)
            self.assertIn("APS MAI 2026", sessions_html)
            self.assertNotIn("Leads WeDoF CPF/EDOF", sessions_html)

            search_resp = self.client.get("/api/trainees_search?q=lass")
            self.assertEqual(search_resp.status_code, 200)
            payload = search_resp.get_json()
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["items"][0]["session_id"], "S-APS")

    def test_wedof_webhook_does_not_create_synthetic_training_session(self):
        with patch.object(gestion_app, "_fetch_wedof_folder_details", return_value={}), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
             patch.object(gestion_app, "_save_wedof_webhooks") as save_wedof, \
             patch.object(gestion_app, "load_data") as load_data, \
             patch.object(gestion_app, "save_data") as save_data:
            resp = self.client.post(
                "/api/webhooks/wedof",
                json={"externalId": "CPF-123", "email": "oceane@example.com"},
                headers={"X-Wedof-Event": "cpf.created"},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        save_wedof.assert_called_once()
        load_data.assert_not_called()
        save_data.assert_not_called()


if __name__ == "__main__":
    unittest.main()
