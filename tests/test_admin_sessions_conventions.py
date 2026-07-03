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


    def test_convention_history_dates_are_displayed_in_french_timezone(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "training_type": "APS",
                    "date_start": "2026-09-01",
                    "date_end": "2026-09-15",
                    "trainees": [
                        {
                            "id": "T1",
                            "last_name": "DATES",
                            "first_name": "Delphine",
                            "email": "delphine@example.test",
                            "convention_status": "signing",
                            "convention_signature": {
                                "signature_request_id": "sig-1",
                                "signature_link": "https://sign.example.test/sig-1",
                                "status": "ongoing",
                                "created_at": "2026-07-03T09:50:32.129789Z",
                                "signature_email_sent_at": "2026-07-03T09:51:00Z",
                                "next_reminder_at": "2026-07-05T09:50:32Z",
                                "reminder_count": 0,
                            },
                        }
                    ],
                }
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Créée :</strong> 03/07/2026 à 11h50", html)
        self.assertIn("Envoyée :</strong> 03/07/2026 à 11h51", html)
        self.assertIn("prochaine 05/07/2026 à 11h50", html)
        self.assertNotIn("2026-07-03T09:50:32", html)
        self.assertNotIn("2026-07-05T09:50:32", html)

    def test_conventions_can_filter_by_formation_and_status(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "training_type": "APS",
                    "trainees": [
                        {"last_name": "APS-SOON", "first_name": "Alice", "convention_status": "soon"},
                        {"last_name": "APS-SIGNING", "first_name": "Bruno", "convention_status": "signing"},
                    ],
                },
                {
                    "id": "S-A3P",
                    "training_type": "A3P",
                    "trainees": [
                        {"last_name": "A3P-SOON", "first_name": "Chloé", "convention_status": "soon"},
                    ],
                },
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions?formation=APS&status=signing")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("APS-SIGNING", html)
        self.assertNotIn("APS-SOON", html)
        self.assertNotIn("A3P-SOON", html)
        self.assertIn('option value="APS" selected', html)
        self.assertIn('option value="signing" selected', html)
        self.assertIn("Réinitialiser", html)


if __name__ == "__main__":
    unittest.main()
