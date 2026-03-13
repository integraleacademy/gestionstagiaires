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


if __name__ == "__main__":
    unittest.main()
