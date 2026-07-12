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

    def test_public_page_shows_sheet_for_non_vae_training(self):
        self.payload["sessions"][0]["name"] = "A3P Juin 2026"
        self.payload["sessions"][0]["training_type"] = "A3P"
        self.payload["sessions"][0]["date_start"] = "2026-06-09"
        self._authenticate_public()

        response = self.client.get("/espace/public-token")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Fiche expérience professionnelle", html)
        self.assertIn("data-pro-sheet-open", html)
        self.assertIn('id="professionalExperienceModal"', html)
        self.assertIn("professional-experience.js", html)

    def test_public_page_shows_sheet_for_vtc_training_even_when_documents_are_hidden(self):
        self.payload["sessions"][0]["name"] = "VTC Juin 2026"
        self.payload["sessions"][0]["training_type"] = "VTC"
        self.payload["sessions"][0]["date_start"] = "2026-06-09"
        self._authenticate_public()

        response = self.client.get("/espace/public-token")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Fiche expérience professionnelle", html)
        self.assertIn("data-pro-sheet-open", html)
        self.assertIn('id="professionalExperienceModal"', html)

    def test_public_tracking_shows_test_fr_and_cnaps_for_aps(self):
        self.payload["sessions"][0].update({
            "name": "APS Juin 2026",
            "training_type": "APS",
            "date_start": "2026-06-09",
            "date_end": "2026-06-30",
        })
        trainee = self.payload["sessions"][0]["trainees"][0]
        trainee.update({
            "test_fr_status": "validated",
            "cnaps": "ACCEPTÉ",
            "financement_status": "validated",
            "convention_status": "signed",
        })
        self._authenticate_public()

        response = self.client.get("/espace/public-token")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        tracking = html.split('id="trackingTitle"', 1)[1].split('</section>', 1)[0]
        self.assertIn("Test de français", tracking)
        self.assertIn("CNAPS", tracking)
        self.assertIn("ACCEPTÉ", tracking)

    def test_public_tracking_shows_test_fr_and_cnaps_for_a3p(self):
        self.payload["sessions"][0].update({
            "name": "A3P Juin 2026",
            "training_type": "A3P",
            "date_start": "2026-06-09",
            "date_end": "2026-06-30",
        })
        trainee = self.payload["sessions"][0]["trainees"][0]
        trainee.update({
            "test_fr_status": "in_progress",
            "cnaps": "INSTRUCTION",
        })
        self._authenticate_public()

        response = self.client.get("/espace/public-token")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        tracking = html.split('id="trackingTitle"', 1)[1].split('</section>', 1)[0]
        self.assertIn("Test de français", tracking)
        self.assertIn("EN COURS", tracking)
        self.assertIn("CNAPS", tracking)
        self.assertIn("INSTRUCTION", tracking)

    def test_non_vae_training_accepts_sheet_submission(self):
        self.payload["sessions"][0]["name"] = "SSIAP 1 Juin 2026"
        self.payload["sessions"][0]["training_type"] = "SSIAP 1"
        self.payload["sessions"][0]["date_start"] = "2026-06-09"
        self._authenticate_public()

        response = self.client.post(
            "/espace/public-token/fiche-experience-professionnelle",
            json=self._valid_payload(),
        )

        self.assertEqual(response.status_code, 200)
        sheet = self.payload["sessions"][0]["trainees"][0]["professional_experience_sheet"]
        self.assertEqual(sheet["training_type"], "SSIAP 1")
        self.assertEqual(sheet["training_name"], "SSIAP 1 Juin 2026")

    def test_admin_documents_show_sheet_for_non_vae_training(self):
        self.payload["sessions"][0]["name"] = "SST Juin 2026"
        self.payload["sessions"][0]["training_type"] = "SST"
        self.payload["sessions"][0]["date_start"] = "2026-06-09"
        self._authenticate_admin()

        response = self.client.get("/admin/sessions/S1/stagiaires/T1")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        row = html.split('data-doc-key="professional_experience_sheet"', 1)[1].split("</tr>", 1)[0]
        self.assertIn("Fiche expérience professionnelle", row)
        self.assertIn("NON DÉPOSÉ", row)

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
        self.assertEqual(sheet["status"], "A CONTRÔLER")
        self.assertEqual(sheet["status_label"], "A CONTRÔLER")
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

    def test_sheet_requirement_depends_on_training_start_date_for_non_vae(self):
        for start_date, expected in (
            ("2026-06-07", False),
            ("2026-06-08", False),
            ("2026-06-09", True),
            ("", False),
            ("date-invalide", False),
        ):
            with self.subTest(start_date=start_date):
                self.assertEqual(
                    gestion_app._professional_experience_sheet_is_required("APS", start_date),
                    expected,
                )

    def test_sheet_remains_required_for_vae_regardless_of_start_date(self):
        for start_date in ("", "2025-01-01", "2026-06-08", "2026-06-09"):
            with self.subTest(start_date=start_date):
                self.assertTrue(
                    gestion_app._professional_experience_sheet_is_required("DIRIGEANT VAE", start_date)
                )

    def test_training_starting_on_cutoff_date_does_not_show_or_accept_sheet(self):
        self.payload["sessions"][0]["name"] = "APS du 8 juin 2026"
        self.payload["sessions"][0]["training_type"] = "APS"
        self.payload["sessions"][0]["date_start"] = "2026-06-08"
        self._authenticate_public()

        page_response = self.client.get("/espace/public-token")
        submit_response = self.client.post(
            "/espace/public-token/fiche-experience-professionnelle",
            json=self._valid_payload(),
        )

        self.assertEqual(page_response.status_code, 200)
        html = page_response.get_data(as_text=True)
        self.assertNotIn("Fiche expérience professionnelle", html)
        self.assertNotIn('id="professionalExperienceModal"', html)
        self.assertNotIn("professional-experience.js", html)
        self.assertEqual(submit_response.status_code, 404)

    def test_training_starting_before_cutoff_is_unchanged_in_admin_and_completion(self):
        self.payload["sessions"][0]["name"] = "SST antérieur"
        self.payload["sessions"][0]["training_type"] = "SST"
        self.payload["sessions"][0]["date_start"] = "2026-06-07"
        trainee = self.payload["sessions"][0]["trainees"][0]
        gestion_app.ensure_documents_schema_for_trainee(trainee, "SST")
        for document in trainee["documents"]:
            document["status"] = "CONFORME"
            document["file"] = "uploads/document.pdf"
            document["files"] = ["uploads/document.pdf"]

        self.assertTrue(gestion_app.required_docs_are_deposited(trainee, "SST", "2026-06-07"))
        self.assertTrue(gestion_app.dossier_is_complete(trainee, "SST", "2026-06-07"))

        self._authenticate_admin()
        response = self.client.get("/admin/sessions/S1/stagiaires/T1")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            'data-doc-key="professional_experience_sheet"',
            response.get_data(as_text=True),
        )

    def test_future_training_requires_sheet_for_completion(self):
        trainee = self.payload["sessions"][0]["trainees"][0]
        gestion_app.ensure_documents_schema_for_trainee(trainee, "SST")
        for document in trainee["documents"]:
            document["status"] = "CONFORME"
            document["file"] = "uploads/document.pdf"
            document["files"] = ["uploads/document.pdf"]

        self.assertFalse(gestion_app.required_docs_are_deposited(trainee, "SST", "2026-06-09"))
        self.assertFalse(gestion_app.dossier_is_complete(trainee, "SST", "2026-06-09"))

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

        trainee["professional_experience_sheet"] = {"status": "A CONTRÔLER"}
        self.assertTrue(gestion_app.required_docs_are_deposited(trainee, training_type))
        self.assertFalse(gestion_app.dossier_is_complete(trainee, training_type))

        trainee["professional_experience_sheet"]["status"] = "CONFORME"
        self.assertTrue(gestion_app.dossier_is_complete(trainee, training_type))

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
        self.assertIn("CONFORME", row)
        self.assertIn("NON CONFORME", row)
        self.assertIn("Voir et imprimer la fiche", row)
        self.assertNotIn("Consulter", row)
        self.assertNotIn("Responsable sécurité", row)
        self.assertNotIn("Consulter les réponses", html)
        self.assertEqual(html.count('data-doc-key="professional_experience_sheet"'), 1)

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
            json={"status": "CONFORME"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status_label"], "CONFORME")
        sheet = self.payload["sessions"][0]["trainees"][0]["professional_experience_sheet"]
        self.assertEqual(sheet["status"], "CONFORME")
        self.assertEqual(sheet["status_label"], "CONFORME")
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
        self.assertIn("@page{size:A4 portrait;margin:7mm}", html)
        self.assertIn("height:283mm", html)
        self.assertIn("overflow:hidden", html)
        self.assertIn("page-break-inside:avoid", html)

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
