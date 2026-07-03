import unittest
from unittest.mock import patch

import app as gestion_app


class ConventionFinancingTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def test_convention_financing_endpoint_persists_amounts_before_preview(self):
        fake_data = {
            "sessions": [{
                "id": "S-APS",
                "training_type": "APS",
                "trainees": [{"id": "T1", "first_name": "Ada", "last_name": "Lovelace"}],
            }]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data") as save_data:
            response = self.client.post(
                "/api/sessions/S-APS/stagiaires/T1/convention/financing",
                json={
                    "training_price": "1650",
                    "cpf_amount": "1650",
                    "personal_amount": "",
                    "other_amount": "0",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["ok"], True)
        trainee = fake_data["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["training_price"], "1650")
        self.assertEqual(trainee["cpf_amount"], "1650")
        self.assertEqual(trainee["personal_amount"], "")
        self.assertEqual(trainee["other_amount"], "0")
        save_data.assert_called_once_with(fake_data)

    def test_create_trainee_response_exposes_financing_save_url(self):
        with open("templates/admin_sessions.html", encoding="utf-8") as fh:
            sessions_template = fh.read()
        with open("templates/admin_trainees.html", encoding="utf-8") as fh:
            trainees_template = fh.read()

        self.assertIn("convention_financing_url", sessions_template)
        self.assertIn("convention_financing_url", trainees_template)
