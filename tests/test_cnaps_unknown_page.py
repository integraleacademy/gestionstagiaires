import unittest

import app as gestion_app


class CnapsUnknownPageTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data

    def tearDown(self):
        gestion_app.load_data = self.original_load_data

    def test_collects_only_active_trainees_with_unknown_cnaps_status(self):
        data = {
            "sessions": [
                {
                    "id": "S-ACTIVE",
                    "name": "APS mai",
                    "training_type": "APS",
                    "date_start": "2026-05-01",
                    "date_end": "2026-05-31",
                    "trainees": [
                        {
                            "id": "T-UNKNOWN",
                            "first_name": "alice",
                            "last_name": "martin",
                            "cnaps": "INCONNU",
                        },
                        {
                            "id": "T-BLANK",
                            "first_name": "bruno",
                            "last_name": "durand",
                            "cnaps": "",
                        },
                        {
                            "id": "T-OK",
                            "first_name": "claire",
                            "last_name": "bernard",
                            "cnaps": "ACCEPTÉ",
                        },
                    ],
                },
                {
                    "id": "S-ARCHIVED",
                    "name": "APS archivée",
                    "training_type": "APS",
                    "archived": True,
                    "trainees": [
                        {
                            "id": "T-ARCHIVED",
                            "first_name": "denis",
                            "last_name": "petit",
                            "cnaps": "INCONNU",
                        }
                    ],
                },
            ]
        }

        with gestion_app.app.test_request_context("/admin/sessions/cnaps-inconnu"):
            rows = gestion_app._collect_cnaps_unknown_trainees(data)

        self.assertEqual([row["trainee_id"] for row in rows], ["T-BLANK", "T-UNKNOWN"])
        self.assertTrue(all(row["cnaps"] == "INCONNU" for row in rows))
        self.assertTrue(all("/admin/sessions/" in row["admin_url"] for row in rows))

    def test_page_lists_unknown_trainee_and_excludes_accepted(self):
        data = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "Session APS",
                    "training_type": "APS",
                    "date_start": "2026-05-01",
                    "date_end": "2026-05-10",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Alice",
                            "last_name": "Martin",
                            "cnaps": "INCONNU",
                            "email": "alice@example.com",
                        },
                        {
                            "id": "T2",
                            "first_name": "Claire",
                            "last_name": "Bernard",
                            "cnaps": "ACCEPTÉ",
                        },
                    ],
                }
            ],
            "notifications_admin": [],
        }
        gestion_app.load_data = lambda: data

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.get("/admin/sessions/cnaps-inconnu")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("CNAPS inconnu", html)
        self.assertIn("MARTIN Alice", html)
        self.assertIn("alice@example.com", html)
        self.assertNotIn("BERNARD Claire", html)
