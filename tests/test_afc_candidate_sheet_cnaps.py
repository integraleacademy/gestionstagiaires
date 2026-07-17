import unittest

import app as gestion_app


class AfcCandidateSheetCnapsTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data

    def test_candidate_sheet_renders_cnaps_title_history_chips(self):
        gestion_app.load_data = lambda: {
            "sessions": [],
            "afc": {
                "candidates": [
                    {
                        "id": "AFC-CNAPS-1",
                        "nom": "DUPONT",
                        "prenom": "Jean",
                        "cnaps_status": "ACCEPTE",
                        "cnaps_status_history": [
                            {"status": "AP SH ACTIF", "date": "2026-10-07"},
                            {"status": "CP SH ACTIF", "date": "2031-06-30"},
                        ],
                    }
                ]
            },
            "positioning_tests": [],
        }
        gestion_app.save_data = lambda *_args, **_kwargs: None

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.get("/admin/afc/candidates/AFC-CNAPS-1")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("afc-cnaps-statuses", html)
        self.assertIn("AP SH ACTIF", html)
        self.assertIn("CP SH ACTIF", html)
        self.assertIn("btnRefreshCnaps", html)


if __name__ == "__main__":
    unittest.main()
