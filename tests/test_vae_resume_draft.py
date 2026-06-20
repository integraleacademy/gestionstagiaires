import os
import tempfile
import unittest
from unittest.mock import patch

import app as gestion_app


class VaeResumeDraftTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.original_vae_data_file = gestion_app.VAE_DATA_FILE
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        gestion_app.VAE_DATA_FILE = os.path.join(self.tmp.name, "data_vae.json")
        self.data = {
            "sessions": [{
                "id": "S-VAE",
                "training_type": "DIRIGEANT VAE",
                "date_start": "2026-07-01",
                "trainees": [{
                    "id": "T-VAE",
                    "token": "tok-vae",
                    "first_name": "Nora",
                    "last_name": "DRAFT",
                    "candidate_sheet_saved_at": "2026-01-01T10:00:00",
                    "documents": [
                        {"key": "id", "files": ["id.pdf"]},
                        {"key": "photo", "files": ["photo.png"]},
                        {"key": "carte_vitale_doc", "files": ["vitale.pdf"]},
                        {"key": "candidate_info_sheet", "status": "A CONTRÔLER"},
                        {"key": "highest_diploma", "files": ["diplome.pdf"]},
                        {"key": "cv", "files": ["cv.pdf"]},
                    ],
                }],
            }],
        }
        gestion_app.load_data = lambda: self.data
        gestion_app.save_data = lambda payload: None

    def tearDown(self):
        gestion_app.VAE_DATA_FILE = self.original_vae_data_file
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        self.tmp.cleanup()

    def test_vae_new_reopens_existing_draft_for_candidate(self):
        dossier = gestion_app._vae_default_dossier("D-DRAFT")
        dossier["meta"] = {"session_id": "S-VAE", "trainee_id": "T-VAE", "trainee_token": "tok-vae"}
        dossier["candidat"]["nom_naissance"] = "DRAFT"
        gestion_app._vae_save_all({"dossiers": [dossier]})

        with patch.object(gestion_app, "_send_vae_admin_notification", return_value=True), \
             patch.object(gestion_app, "required_docs_are_deposited", return_value=True):
            response = self.client.get("/vae/nouveau/tok-vae", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/vae/D-DRAFT"))
        dossiers = gestion_app._vae_load_all()["dossiers"]
        self.assertEqual(len(dossiers), 1)
        self.assertEqual(dossiers[0]["candidat"]["nom_naissance"], "DRAFT")


if __name__ == "__main__":
    unittest.main()
