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
        launch = html.split('data-pro-sheet-open', 1)[1].split("</button>", 1)[0]
        self.assertIn("Obligatoire", launch)
        self.assertIn("Complétez et transmettez votre parcours professionnel.", launch)
        self.assertIn("À compléter", launch)
        self.assertIn("needs-attention", html.split('data-pro-sheet-open', 1)[0].split("<button", 1)[-1])
        self.assertNotIn("À contrôler", launch)

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
        payload.update({
            "current_situation": "other",
            "current_situation_other": "",
            "qualification_since": "",
            "last_certification": "",
            "certified": False,
        })
        payload["experiences"] = [{}]

        response = self.client.post("/espace/public-token/fiche-experience-professionnelle", json=payload)

        self.assertEqual(response.status_code, 400)
        errors = response.get_json()["errors"]
        self.assertIn("current_situation_other", errors)
        self.assertIn("qualification_since", errors)
        self.assertIn("last_certification", errors)
        self.assertIn("experiences.0.job_title", errors)
        self.assertIn("experiences.0.company_name", errors)
        self.assertIn("experiences.0.start_date", errors)
        self.assertIn("experiences.0.end_date", errors)
        self.assertIn("experiences.0.work_time_percent", errors)
        self.assertIn("experiences.0.contract_type", errors)
        self.assertIn("experiences.0.executive_status", errors)
        self.assertIn("certified", errors)
        self.assertNotIn("professional_experience_sheet", self.payload["sessions"][0]["trainees"][0])

    def test_submission_is_restricted_to_vae_training(self):
        self._authenticate_public()
        self.payload["sessions"][0]["training_type"] = "APS"

        response = self.client.post("/espace/public-token/fiche-experience-professionnelle", json=self._valid_payload())

        self.assertEqual(response.status_code, 404)

    def test_second_public_submission_is_rejected_without_overwriting_sheet(self):
        self._authenticate_public()
        first_payload = self._valid_payload()
        self.client.post("/espace/public-token/fiche-experience-professionnelle", json=first_payload)

        second_payload = self._valid_payload()
        second_payload["last_certification"] = "Nouvelle valeur interdite"
        response = self.client.post("/espace/public-token/fiche-experience-professionnelle", json=second_payload)

        self.assertEqual(response.status_code, 409)
        self.assertIn("déjà été transmise", response.get_json()["message"])
        sheet = self.payload["sessions"][0]["trainees"][0]["professional_experience_sheet"]
        self.assertEqual(sheet["last_certification"], first_payload["last_certification"])

    def test_sheet_is_mandatory_for_vae_document_completion(self):
        trainee = self.payload["sessions"][0]["trainees"][0]
        training_type = self.payload["sessions"][0]["training_type"]
        gestion_app.ensure_documents_schema_for_trainee(trainee, training_type)
        for document in trainee["documents"]:
            document["status"] = "CONFORME"
            document["file"] = "uploads/document.pdf"
            document["files"] = ["uploads/document.pdf"]

        self.assertFalse(gestion_app.required_docs_are_deposited(trainee, training_type))
        self.assertFalse(gestion_app.dossier_is_complete(trainee, training_type))

        trainee["professional_experience_sheet"] = {"status": "pending_review"}
        self.assertTrue(gestion_app.required_docs_are_deposited(trainee, training_type))
        self.assertFalse(gestion_app.dossier_is_complete(trainee, training_type))

        trainee["professional_experience_sheet"]["status"] = "validated"
        self.assertTrue(gestion_app.dossier_is_complete(trainee, training_type))

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
        self.assertIn("VALIDÉ", row)
        self.assertIn("NON CONFORME", row)
        self.assertIn("Télécharger le PDF", row)
        self.assertNotIn("Consulter", row)
        self.assertNotIn("Responsable sécurité", row)

    def test_public_page_shows_file_sent_after_submission(self):
        self._authenticate_public()
        self.client.post("/espace/public-token/fiche-experience-professionnelle", json=self._valid_payload())

        response = self.client.get("/espace/public-token")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        launch = html.split('class="pro-sheet-launch', 1)[1].split("</button>", 1)[0]
        self.assertIn("Fichier envoyé", launch)
        self.assertIn("disabled", launch)
        self.assertIn('aria-disabled="true"', launch)
        self.assertIn("Elle ne peut plus être modifiée.", launch)
        self.assertNotIn("data-pro-sheet-open", launch)
        self.assertNotIn("À contrôler", launch)
        self.assertNotIn("needs-attention", launch)
        self.assertNotIn('id="professionalExperienceModal"', html)

    def test_admin_can_update_sheet_status(self):
        self._authenticate_public()
        self.client.post("/espace/public-token/fiche-experience-professionnelle", json=self._valid_payload())
        self._authenticate_admin()

        response = self.client.post(
            "/api/sessions/S1/stagiaires/T1/fiche-experience-professionnelle/status",
            json={"status": "validated"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status_label"], "Validé")
        sheet = self.payload["sessions"][0]["trainees"][0]["professional_experience_sheet"]
        self.assertEqual(sheet["status"], "validated")
        self.assertEqual(sheet["status_label"], "Validé")
        self.assertEqual(sheet["reviewed_at"], "2026-06-08T10:30:00Z")

    def test_admin_can_open_printable_html_sheet(self):
        self._authenticate_public()
        self.client.post("/espace/public-token/fiche-experience-professionnelle", json=self._valid_payload())
        self._authenticate_admin()

        response = self.client.get("/admin/sessions/S1/stagiaires/T1/fiche-experience-professionnelle")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/html")
        html = response.get_data(as_text=True)
        self.assertIn("Fiche expérience professionnelle", html)
        self.assertIn("Responsable sécurité", html)
        self.assertIn("Entreprise Exemple", html)
        self.assertIn("Imprimer la fiche", html)
        self.assertIn("@media print", html)

    def test_legacy_pdf_url_redirects_to_printable_html_sheet(self):
        self._authenticate_public()
        self.client.post("/espace/public-token/fiche-experience-professionnelle", json=self._valid_payload())
        self._authenticate_admin()

        response = self.client.get("/admin/sessions/S1/stagiaires/T1/fiche-experience-professionnelle.pdf")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/fiche-experience-professionnelle"))

    def test_admin_can_delete_sheet(self):
        self._authenticate_public()
        self.client.post("/espace/public-token/fiche-experience-professionnelle", json=self._valid_payload())
        self._authenticate_admin()

        response = self.client.post("/admin/sessions/S1/stagiaires/T1/fiche-experience-professionnelle/delete")

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("professional_experience_sheet", self.payload["sessions"][0]["trainees"][0])


if __name__ == "__main__":
    unittest.main()
