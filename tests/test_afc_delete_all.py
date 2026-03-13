import unittest

import app as gestion_app


class AfcDeleteAllCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data

    def test_delete_all_candidates_clears_afc_bucket(self):
        data = {
            "afc": {
                "candidates": [
                    {"id": "AFC-1", "nom": "DUPONT", "prenom": "Jean"},
                    {"id": "AFC-2", "nom": "MARTIN", "prenom": "Lea"},
                ]
            }
        }
        saved_snapshots = []

        gestion_app.load_data = lambda: data

        def fake_save_data(updated_data):
            saved_snapshots.append(list(updated_data["afc"]["candidates"]))

        gestion_app.save_data = fake_save_data

        response = self.client.post("/api/admin/afc/candidates/delete-all")
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body, {"ok": True, "deleted": 2})
        self.assertEqual(data["afc"]["candidates"], [])
        self.assertGreaterEqual(len(saved_snapshots), 1)
        self.assertEqual(saved_snapshots[-1], [])

    def test_admin_afc_page_contains_delete_all_button(self):
        gestion_app.load_data = lambda: {"afc": {"candidates": []}}

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.get("/admin/afc")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Supprimer toutes les lignes", html)
        self.assertIn("/api/admin/afc/candidates/delete-all", html)


if __name__ == "__main__":
    unittest.main()
