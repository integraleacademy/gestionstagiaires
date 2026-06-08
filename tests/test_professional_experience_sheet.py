import unittest

import app as gestion_app


class ProfessionalExperienceSheetTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_now_iso = gestion_app._now_iso
        self.payload = {
            "sessions": [{
                "id": "S1",
                "name": "VAE DESP 2026",
                "training_type": "DIRIGEANT VAE",
                "trainees": [{
                    "id": "T1",
                    "public_token": "public-token",
                    "first_name": "Jeanne",
                    "last_name": "Martin",
                    "documents": [],
                }],
            }],
            "notifications_admin": [],
        }
        self.saved = []
        gestion_app.load_data = lambda: self.payload
        gestion_app.save_data = lambda data: self.saved.append(data)
        gestion_app._now_iso = lambda: "2026-06-08T10:30:00Z"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app._now_iso = self.original_now_iso

    def _authenticate_public(self):
        with self.client.session_transaction() as session:
            session["public_auth_public-token"] = True

    def _authenticate_admin(self):
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def _valid_payload(self):
        return {
            "current_situation": "employed",
            "current_situation_other": "",
            "qualification_level": "bac_3",
            "qualification_other": "",
            "qualification_since": "2021-09-01",
            "last_certification": "Licence professionnelle sécurité",
            "experiences": [{
                "job_title": "Responsable sécurité",
                "company_name": "Entreprise Exemple",
                "start_date": "2022-01-03",
                "end_date": "2026-05-31",
                "work_time_percent": "100",
                "contract_type": "cdi",
                "contract_other": "",
                "executive_status": "yes",
            }],
            "validation_name": "Jeanne Martin",
            "validation_date": "2026-06-08",
            "certified": True,
        }

    def test_public_page_does_not_show_pending_review_before_submission(self):
        self._authenticate_public()

        response = self.client.get("/espace/public-token")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        launch = html.split('class="pro-sheet-launch"', 1)[1].split("</button>", 1)[0]
        self.assertIn("Complétez et transmettez votre parcours professionnel.", launch)
        self.assertNotIn("À contrôler", launch)
        self.assertNotIn("pro-sheet-launch-status", launch)

    def test_admin_documents_show_sheet_as_not_deposited_before_submission(self):
        self._authenticate_admin()

        response = self.client.get("/admin/sessions/S1/stagiaires/T1")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        row = html.split('data-doc-key="professional_experience_sheet"', 1)[1].split("</tr>", 1)[0]
        self.assertIn("Fiche expérience professionnelle", row)
        self.assertIn("NON DÉPOSÉ", row)
        self.assertNotIn("A CONTRÔLER", row)
        self.assertIn("La fiche n’a pas encore été transmise.", row)

    def test_public_submission_saves_sheet_with_pending_review_status(self):
        self._authenticate_public()

        response = self.client.post("/espace/public-token/fiche-experience-professionnelle", json=self._valid_payload())

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["message"], "Votre fiche expérience professionnelle a bien été transmise.")
        sheet = self.payload["sessions"][0]["trainees"][0]["professional_experience_sheet"]
        self.assertEqual(sheet["status"], "pending_review")
        self.assertEqual(sheet["status_label"], "À contrôler")
        self.assertEqual(sheet["last_name"], "Martin")
        self.assertEqual(sheet["experiences"][0]["work_time_percent"], 100.0)
        self.assertTrue(self.saved)

    def test_public_submission_validates_required_and_conditional_fields(self):
        self._authenticate_public()
        payload = self._valid_payload()
        payload.update({"current_situation": "other", "current_situation_other": "", "certified": False})

        response = self.client.post("/espace/public-token/fiche-experience-professionnelle", json=payload)

        self.assertEqual(response.status_code, 400)
        errors = response.get_json()["errors"]
        self.assertIn("current_situation_other", errors)
        self.assertIn("certified", errors)
        self.assertNotIn("professional_experience_sheet", self.payload["sessions"][0]["trainees"][0])

    def test_submission_is_restricted_to_vae_training(self):
        self._authenticate_public()
        self.payload["sessions"][0]["training_type"] = "APS"

        response = self.client.post("/espace/public-token/fiche-experience-professionnelle", json=self._valid_payload())

        self.assertEqual(response.status_code, 404)

    def test_admin_page_displays_responses_and_pending_review_status(self):
        self._authenticate_public()
        self.client.post("/espace/public-token/fiche-experience-professionnelle", json=self._valid_payload())
        self._authenticate_admin()

        response = self.client.get("/admin/sessions/S1/stagiaires/T1")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        row = html.split('data-doc-key="professional_experience_sheet"', 1)[1].split("</tr>", 1)[0]
        self.assertIn("Fiche expérience professionnelle", row)
        self.assertIn("A CONTRÔLER", row)
        self.assertIn("Consulter", row)
        self.assertIn("Télécharger le PDF", row)
        self.assertIn("Responsable sécurité", html)

    def test_admin_can_download_generated_pdf(self):
        self._authenticate_public()
        self.client.post("/espace/public-token/fiche-experience-professionnelle", json=self._valid_payload())
        self._authenticate_admin()

        response = self.client.get("/admin/sessions/S1/stagiaires/T1/fiche-experience-professionnelle.pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF"))
        self.assertIn("attachment", response.headers["Content-Disposition"])

    def test_admin_can_delete_sheet(self):
        self._authenticate_public()
        self.client.post("/espace/public-token/fiche-experience-professionnelle", json=self._valid_payload())
        self._authenticate_admin()

        response = self.client.post("/admin/sessions/S1/stagiaires/T1/fiche-experience-professionnelle/delete")

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("professional_experience_sheet", self.payload["sessions"][0]["trainees"][0])


if __name__ == "__main__":
    unittest.main()
