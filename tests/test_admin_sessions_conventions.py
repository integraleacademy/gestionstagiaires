import unittest
from unittest.mock import patch

import app as gestion_app


class AdminSessionsConventionsTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def test_conventions_include_vae_from_financement_validated_status(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "training_type": "APS",
                    "date_start": "2026-09-01",
                    "date_end": "2026-09-15",
                    "trainees": [
                        {
                            "last_name": "CLASSIQUE",
                            "first_name": "Claire",
                            "convention_status": "soon",
                        }
                    ],
                },
                {
                    "id": "S-VAE",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "last_name": "AVANT",
                            "first_name": "Alice",
                            "convention_status": "soon",
                            "vae_status": "livret_1_validated",
                        },
                        {
                            "last_name": "SEUIL",
                            "first_name": "Bruno",
                            "convention_status": "soon",
                            "vae_status": "financement_validated",
                        },
                        {
                            "last_name": "APRES",
                            "first_name": "Chloé",
                            "convention_status": "signing",
                            "vae_status": "jury",
                        },
                        {
                            "last_name": "SIGNEE",
                            "first_name": "Diane",
                            "convention_status": "signed",
                            "vae_status": "certified",
                        },
                    ],
                },
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("CLASSIQUE", html)
        self.assertIn("SEUIL", html)
        self.assertIn("APRES", html)
        self.assertNotIn("AVANT", html)
        self.assertNotIn("SIGNEE", html)
        self.assertIn("Les VAE sont incluses à partir du statut", html)

    def test_conventions_use_vae_label_and_action_dates_to_apply_threshold(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-VAE",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "last_name": "LIBELLE",
                            "first_name": "Emma",
                            "convention_status": "soon",
                            "vae_status_label": "Financement validé",
                        },
                        {
                            "last_name": "ACTION",
                            "first_name": "Farah",
                            "convention_status": "soon",
                            "vae_status": "livret_1_validated",
                            "vae_action_dates": {
                                "financement_validated": "12/06/2026"
                            },
                        },
                    ],
                }
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("LIBELLE", html)
        self.assertIn("ACTION", html)


if __name__ == "__main__":
    unittest.main()
