import unittest

import app as gestion_app


class RequiredDocsForDirigeantTests(unittest.TestCase):
    def _doc_keys(self, training_type: str):
        return [doc.get("key") for doc in gestion_app.required_docs_for_training(training_type)]

    def test_dirigeant_initial_requires_highest_diploma(self):
        keys = self._doc_keys("DIRIGEANT INITIAL")

        self.assertIn("highest_diploma", keys)

    def test_dirigeant_initial_requires_updated_cv_and_desp_exam_sworn_statement(self):
        docs = gestion_app.required_docs_for_training("DIRIGEANT INITIAL")
        by_key = {doc.get("key"): doc for doc in docs}

        self.assertIn("cv", by_key)
        self.assertEqual(by_key["cv"].get("label"), "CV à jour")
        self.assertIn("desp_exam_sworn_statement", by_key)

    def test_dirigeant_vae_does_not_require_desp_exam_sworn_statement(self):
        keys = self._doc_keys("DIRIGEANT VAE")

        self.assertNotIn("desp_exam_sworn_statement", keys)

    def test_dirigeant_label_requires_highest_diploma(self):
        keys = self._doc_keys("DIRIGEANT")

        self.assertIn("highest_diploma", keys)

    def test_dirigeant_vae_still_requires_cv_and_highest_diploma(self):
        keys = self._doc_keys("DIRIGEANT VAE")

        self.assertIn("cv", keys)
        self.assertIn("highest_diploma", keys)

    def test_dirigeant_vae_no_bac_does_not_block_on_prerequis_interview_sheet_for_step_1(self):
        trainee = {
            "no_bac_diploma": True,
            "candidate_sheet_saved_at": "2026-01-01T10:00:00",
            "professional_experience_sheet": {"status": "A CONTRÔLER"},
            "documents": [
                {"key": "id", "files": ["id.pdf"]},
                {"key": "photo", "files": ["photo.png"]},
                {"key": "carte_vitale_doc", "files": ["vitale.pdf"]},
                {"key": "candidate_info_sheet", "status": "A CONTRÔLER"},
                {"key": "highest_diploma", "files": ["diplome.pdf"]},
                {"key": "cv", "files": ["cv.pdf"]},
                # volontairement absent: prerequis_interview_sheet
            ],
        }

        self.assertTrue(gestion_app.required_docs_are_deposited(trainee, "DIRIGEANT VAE"))

    def test_afc_session_adds_ssiap_medical_certificate(self):
        trainee = {"afc_medical_required": True}
        keys = [doc.get("key") for doc in gestion_app.required_docs_for_training("APS", trainee)]
        self.assertIn("certificat_medical_ssiap_afc", keys)


    def test_ssiap_replaces_cnaps_with_medical_and_optional_first_aid(self):
        docs = gestion_app.required_docs_for_training("SSIAP 1")
        by_key = {doc.get("key"): doc for doc in docs}

        self.assertNotIn("cnaps_doc", by_key)
        self.assertEqual(
            by_key["certificat_medical_ssiap"].get("label"),
            "Certificat médical de moins de 3 mois à la date de l'examen, selon le modèle officiel",
        )
        self.assertEqual(
            by_key["certificat_medical_ssiap"].get("template_url_endpoint"),
            "public_ssiap_medical_certificate_template",
        )
        self.assertTrue(by_key["attestation_secourisme_ssiap"].get("optional"))

    def test_ssiap_optional_first_aid_does_not_block_completion(self):
        trainee = {
            "documents": [
                {"key": "id", "status": "CONFORME", "files": ["id.pdf"]},
                {"key": "photo", "status": "CONFORME", "files": ["photo.png"]},
                {"key": "carte_vitale_doc", "status": "CONFORME", "files": ["vitale.pdf"]},
                {"key": "certificat_medical_ssiap", "status": "CONFORME", "files": ["certificat.pdf"]},
            ]
        }

        self.assertTrue(gestion_app.dossier_is_complete(trainee, "SSIAP 1"))
        self.assertTrue(gestion_app.required_docs_are_deposited(trainee, "SSIAP 1"))

    def test_subtract_months_for_ssiap_window(self):
        self.assertEqual(gestion_app._subtract_months("2026-07-15", 3), "2026-04-15")


if __name__ == "__main__":
    unittest.main()
