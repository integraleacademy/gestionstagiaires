import unittest
from unittest.mock import patch

import app as gestion_app


class VaeLivret2ShippingNoteTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.trainee = {
            "id": "T-VAE",
            "last_name": "TEST",
            "first_name": "Vae",
            "birth_date": "1990-01-01",
            "public_token": "TOKEN-VAE",
            "vae_status": "livret_2_todo",
            "documents": [],
        }
        self.data = {
            "sessions": [
                {
                    "id": "S-VAE",
                    "name": "VAE DESP 2026",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [self.trainee],
                }
            ]
        }
        with self.client.session_transaction() as browser_session:
            browser_session["admin_logged_in"] = True

    def render_space(self):
        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(
            gestion_app, "save_data"
        ):
            return self.client.get("/espace/TOKEN-VAE")

    def test_vae_livret2_step_displays_no_staples_note(self):
        response = self.render_space()
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("envoyez le Livret 2 et toutes ses pièces justificatives sans agrafes", html)
        self.assertIn('role="note"', html)
        self.assertIn("54 chemin du Carreou", html)

    def test_note_is_not_rendered_outside_vae(self):
        self.data["sessions"][0]["training_type"] = "APS"

        response = self.render_space()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("sans agrafes", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
