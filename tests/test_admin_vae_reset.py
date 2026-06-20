import os
import tempfile
import unittest
from unittest.mock import patch

import app as gestion_app


class AdminVaeResetTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.original_vae_data_file = gestion_app.VAE_DATA_FILE
        gestion_app.VAE_DATA_FILE = os.path.join(self.tmp.name, "data_vae.json")
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.data = {
            "sessions": [{
                "id": "S-VAE",
                "training_type": "DIRIGEANT VAE",
                "trainees": [{
                    "id": "T-VAE",
                    "first_name": "Nora",
                    "last_name": "REFUS",
                    "vae_status": "livret_1_analysis",
                    "vae_status_label": "Livret 1 en cours d'analyse",
                    "vae_action_dates": {"livret_1_received": "20/06/2026"},
                    "vae_jury_date": "2026-07-01",
                    "documents": [],
                }],
            }],
        }
        gestion_app.load_data = lambda: self.data
        gestion_app.save_data = lambda payload: None
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.VAE_DATA_FILE = self.original_vae_data_file
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        self.tmp.cleanup()

    def test_admin_trainee_page_shows_reset_button_for_existing_vae_dossier(self):
        vae_data = {"dossiers": [{
            **gestion_app._vae_default_dossier("D-VAE"),
            "meta": {"session_id": "S-VAE", "trainee_id": "T-VAE"},
            "statut_dossier": "soumis",
        }]}
        gestion_app._vae_save_all(vae_data)

        response = self.client.get("/admin/sessions/S-VAE/stagiaires/T-VAE")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Réinitialiser le livret 1", html)
        self.assertIn("Confirmez-vous la réinitialisation du livret 1", html)
        self.assertIn("/admin/sessions/S-VAE/stagiaires/T-VAE/vae-dossier/D-VAE/reset", html)

    def test_admin_can_reset_vae_dossier_content_and_status(self):
        upload_dir = gestion_app._vae_upload_dir("D-VAE")
        fp = os.path.join(upload_dir, "preuve.pdf")
        with open(fp, "wb") as f:
            f.write(b"pdf")
        dossier = gestion_app._vae_default_dossier("D-VAE")
        dossier.update({
            "statut_dossier": "soumis",
            "candidat": {**dossier["candidat"], "nom_naissance": "REFUS", "prenoms": "Nora"},
            "experiences": [{"date_debut": "2020", "duree": "3 ans", "description": "Direction"}],
            "justificatifs_experience": [{"id": "J1", "name": "preuve.pdf", "token": gestion_app._tokenize_path(fp)}],
            "meta": {"session_id": "S-VAE", "trainee_id": "T-VAE", "trainee_token": "tok"},
        })
        gestion_app._vae_save_all({"dossiers": [dossier]})

        with patch.object(gestion_app, "_send_vae_admin_notification", return_value=True):
            response = self.client.post(
                "/admin/sessions/S-VAE/stagiaires/T-VAE/vae-dossier/D-VAE/reset",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        reset = gestion_app._vae_load_all()["dossiers"][0]
        self.assertEqual(reset["id"], "D-VAE")
        self.assertEqual(reset["meta"], {"session_id": "S-VAE", "trainee_id": "T-VAE", "trainee_token": "tok"})
        self.assertEqual(reset["statut_dossier"], "brouillon")
        self.assertEqual(reset["candidat"]["nom_naissance"], "")
        self.assertEqual(reset["experiences"], [{"date_debut": "", "duree": "", "description": ""}])
        self.assertEqual(reset["justificatifs_experience"], [])
        self.assertFalse(os.path.exists(fp))
        trainee = self.data["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["vae_status"], "livret_1_todo")
        self.assertEqual(trainee["vae_status_label"], "Livret 1 à compléter")
        self.assertEqual(trainee["vae_action_dates"], {})
        self.assertNotIn("vae_jury_date", trainee)
        self.assertEqual(trainee["activity_history"][0]["label"], "Livret 1 réinitialisé")


if __name__ == "__main__":
    unittest.main()
