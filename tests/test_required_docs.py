import unittest

import app as gestion_app


class RequiredDocsForDirigeantTests(unittest.TestCase):
    def _doc_keys(self, training_type: str):
        return [doc.get("key") for doc in gestion_app.required_docs_for_training(training_type)]

    def test_dirigeant_initial_requires_highest_diploma(self):
        keys = self._doc_keys("DIRIGEANT INITIAL")

        self.assertIn("highest_diploma", keys)

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


if __name__ == "__main__":
    unittest.main()
