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
                    "vae_action_dates": {
                        "livret_1_received": "20/06/2026",
                        "livret_1_validated": "21/06/2026",
                        "financement_validated": "22/06/2026",
                        "livret_2_received": "23/06/2026",
                        "livret_2_validated": "24/06/2026",
                        "financement_l2_validated": "25/06/2026",
                        "jury_date": "26/06/2026",
                        "diplome_obtenu": "27/06/2026",
                        "livret_1_transmitted_scotia": "20/06/2026",
                        "livret_2_transmitted_scotia": "23/06/2026",
                    },
                    "vae_jury_date": "2026-07-01",
                    "livret_1_transmitted_scotia_at": "2026-06-20T09:00:00Z",
                    "livret_2_transmitted_scotia_at": "2026-06-23T09:00:00Z",
                    "scotia_force_visible": True,
                    "scotia_status": "recevable",
                    "scotia_processed_at": "2026-06-21T09:00:00Z",
                    "scotia_processed_at_label": "21/06/2026 à 09h00",
                    "scotia_livret_2_status": "livret_2_ok",
                    "scotia_livret_2_processed_at": "2026-06-24T09:00:00Z",
                    "scotia_livret_2_processed_at_label": "24/06/2026 à 09h00",
                    "scotia_complementary_documents_review_status": "complement_documents_new_expected",
                    "scotia_complementary_documents_reviewed_at": "2026-06-22T09:00:00Z",
                    "scotia_complementary_documents_reviewed_at_label": "22/06/2026 à 09h00",
                    "scotia_complementary_documents_received_at": "2026-06-22T10:00:00Z",
                    "scotia_added_documents": [{"date": "22/06/2026", "files": ["token-added"]}],
                    "scotia_complementary_documents": ["token-comp"],
                    "complementary_documents": ["token-comp"],
                    "scotia_hidden": True,
                    "scotia_hidden_at": "2026-06-21T10:00:00Z",
                    "vae_relances_state": {"livret_1": {"sent_at": "2026-06-10T09:00:00Z"}},
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
        self.assertFalse(trainee["scotia_force_visible"])
        for key in (
            "vae_jury_date",
            "livret_1_transmitted_scotia_at",
            "livret_2_transmitted_scotia_at",
            "scotia_status",
            "scotia_processed_at",
            "scotia_processed_at_label",
            "scotia_livret_2_status",
            "scotia_livret_2_processed_at",
            "scotia_livret_2_processed_at_label",
            "scotia_complementary_documents_review_status",
            "scotia_complementary_documents_reviewed_at",
            "scotia_complementary_documents_reviewed_at_label",
            "scotia_complementary_documents_received_at",
            "scotia_added_documents",
            "scotia_complementary_documents",
            "complementary_documents",
            "scotia_hidden",
            "scotia_hidden_at",
            "vae_relances_state",
        ):
            self.assertNotIn(key, trainee)
        self.assertEqual(trainee["activity_history"][0]["label"], "Livret 1 réinitialisé")

    def test_livret_1_scotia_transmission_does_not_promote_vae_status(self):
        trainee = self.data["sessions"][0]["trainees"][0]
        trainee["vae_status"] = "livret_1_analysis"
        trainee["vae_status_label"] = "Livret 1 en cours d'analyse"
        trainee["vae_action_dates"] = {
            "livret_1_received": "20/06/2026",
            # Donnée historique incohérente : la transmission SCOTIA ne doit pas
            # transformer le statut affiché en certification obtenue.
            "diplome_obtenu": "27/06/2026",
        }

        response = self.client.post(
            "/api/sessions/S-VAE/stagiaires/T-VAE/update",
            json={
                "vae_action_dates": {
                    "livret_1_received": "20/06/2026",
                    "diplome_obtenu": "27/06/2026",
                    "livret_1_transmitted_scotia": "08/07/2026",
                },
                "send_vae_notification": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(trainee["vae_status"], "livret_1_analysis")
        self.assertEqual(trainee["vae_status_label"], "Livret 1 en cours d'analyse")
        self.assertEqual(trainee["vae_action_dates"]["livret_1_transmitted_scotia"], "08/07/2026")

    def test_livret_1_scotia_transmission_without_diploma_date_keeps_vae_status(self):
        trainee = self.data["sessions"][0]["trainees"][0]
        trainee["vae_status"] = "livret_1_analysis"
        trainee["vae_status_label"] = "Livret 1 en cours d'analyse"
        trainee["vae_action_dates"] = {"livret_1_received": "20/06/2026"}

        response = self.client.post(
            "/api/sessions/S-VAE/stagiaires/T-VAE/update",
            json={
                "vae_action_dates": {
                    "livret_1_received": "20/06/2026",
                    "livret_1_transmitted_scotia": "08/07/2026",
                },
                "send_vae_notification": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(trainee["vae_status"], "livret_1_analysis")
        self.assertEqual(trainee["vae_status_label"], "Livret 1 en cours d'analyse")
        self.assertNotIn("diplome_obtenu", trainee["vae_action_dates"])
        self.assertEqual(trainee["vae_action_dates"]["livret_1_transmitted_scotia"], "08/07/2026")


if __name__ == "__main__":
    unittest.main()
