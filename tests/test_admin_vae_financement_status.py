import unittest
from unittest.mock import patch

import app as gestion_app


class AdminVaeFinancementStatusTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def test_admin_trainees_marks_financement_green_from_vae_action(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-VAE",
                    "name": "Dirigeant VAE",
                    "training_type": "DIRIGEANT VAE",
                    "date_start": "2026-09-01",
                    "date_end": "2026-10-01",
                    "trainees": [
                        {
                            "id": "T1",
                            "last_name": "VAILLANT",
                            "first_name": "Clément",
                            "financement_status": "soon",
                            "vae_status": "livret_1_validated",
                            "vae_action_dates": {"financement_validated": "22/06/2026"},
                            "documents": [],
                        }
                    ],
                }
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data"):
            response = self.client.get("/admin/sessions/S-VAE/trainees")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('<option value="validated" selected>🟢</option>', html)
        self.assertEqual(fake_data["sessions"][0]["trainees"][0]["financement_status"], "validated")


if __name__ == "__main__":
    unittest.main()
