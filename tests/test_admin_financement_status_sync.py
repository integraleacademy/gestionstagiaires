import unittest
from unittest.mock import patch

import app as gestion_app


class AdminFinancementStatusSyncTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def test_admin_trainees_marks_financement_green_from_manual_validation(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "name": "APS TEST",
                    "training_type": "APS",
                    "date_start": "2026-09-01",
                    "date_end": "2026-10-01",
                    "trainees": [
                        {
                            "id": "T1",
                            "last_name": "VAILLANT",
                            "first_name": "Clément",
                            "financement_status": "soon",
                            "financing_validation_manual_mode": "manual",
                            "financing_validation_manual_status": "validated",
                            "documents": [],
                        }
                    ],
                }
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data"):
            response = self.client.get("/admin/sessions/S-APS/trainees")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('<option value="validated" selected>🟢</option>', html)
        self.assertEqual(fake_data["sessions"][0]["trainees"][0]["financement_status"], "validated")

    def test_admin_trainee_finance_widget_syncs_validated_status(self):
        template = gestion_app.app.jinja_loader.get_source(
            gestion_app.app.jinja_env,
            "admin_trainee.html",
        )[0]

        self.assertIn("function syncFinancementStatusIfValidated(state)", template)
        self.assertIn("updateTrainee({financement_status:'validated'})", template)
        self.assertIn("financing_validation_manual_status:'validated', financement_status:'validated'", template)


if __name__ == "__main__":
    unittest.main()
