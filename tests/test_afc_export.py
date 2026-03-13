import unittest

import app as gestion_app


class AfcExportTemplateTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data

    def tearDown(self):
        gestion_app.load_data = self.original_load_data

    def test_export_row_columns_are_aligned_and_include_dates(self):
        gestion_app.load_data = lambda: {
            "afc": {
                "export_title": "Export test",
                "dates_formation": "",
                "candidates": [
                    {
                        "id": "AFC-1",
                        "presence_afc_status": "PRESENT",
                        "date_icop": "2026-04-01",
                        "identifiant_ft": "5479898L - 032",
                        "nom": "TAYFER",
                        "prenom": "Marc",
                        "cnaps_status": "ACCEPTÉ",
                        "test_francais_reussi": True,
                        "decision": "RETENU",
                        "motif_refus": "",
                        "complement_refus": "",
                        "modules": {
                            "formation_technique": 54,
                            "remise_niveau": 45,
                            "soutien_personnalise": 21,
                            "paf": 393,
                        },
                        "dates_formation": "01/04/2026 au 30/04/2026",
                    }
                ],
            }
        }

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.get("/admin/afc/export")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("<td>2026-04-01</td>", html)
        self.assertIn("<td>5479898L - 032</td>", html)
        self.assertIn("<td>513</td>", html)
        self.assertIn("<td>01/04/2026 au 30/04/2026</td>", html)

        self.assertLess(html.index("<td>2026-04-01</td>"), html.index("<td>5479898L - 032</td>"))
        self.assertLess(html.index("<td>513</td>"), html.index("<td>01/04/2026 au 30/04/2026</td>"))


if __name__ == "__main__":
    unittest.main()
