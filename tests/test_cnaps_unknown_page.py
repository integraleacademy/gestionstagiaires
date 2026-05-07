import unittest

import app as gestion_app


class CnapsUnknownPageTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data

    def tearDown(self):
        gestion_app.load_data = self.original_load_data

    def test_collects_only_aps_and_a3p_active_trainees_with_unknown_cnaps_status(self):
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
                    "id": "S-A3P",
                    "name": "A3P mai",
                    "training_type": "A3P",
                    "date_start": "2026-05-01",
                    "date_end": "2026-05-31",
                    "trainees": [
                        {
                            "id": "T-A3P",
                            "first_name": "emma",
                            "last_name": "arnaud",
                            "cnaps": "UNKNOWN",
                        }
                    ],
                },
                {
                    "id": "S-VTC",
                    "name": "VTC mai",
                    "training_type": "VTC",
                    "trainees": [
                        {
                            "id": "T-VTC",
                            "first_name": "victor",
                            "last_name": "vtc",
                            "cnaps": "INCONNU",
                        }
                    ],
                },
                {
                    "id": "S-VAE",
                    "name": "VAE DESP mai",
                    "training_type": "VAE DESP",
                    "trainees": [
                        {
                            "id": "T-VAE",
                            "first_name": "valerie",
                            "last_name": "vae",
                            "cnaps": "INCONNU",
                        }
                    ],
                },
                {
                    "id": "S-DIRIGEANT",
                    "name": "DIRIGEANT mai",
                    "training_type": "DIRIGEANT",
                    "trainees": [
                        {
                            "id": "T-DIRIGEANT",
                            "first_name": "diane",
                            "last_name": "dirigeant",
                            "cnaps": "INCONNU",
                        }
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

        self.assertEqual([row["trainee_id"] for row in rows], ["T-A3P", "T-BLANK", "T-UNKNOWN"])
        self.assertTrue(all(row["cnaps"] == "INCONNU" for row in rows))
        self.assertTrue(all("/admin/sessions/" in row["admin_url"] for row in rows))

    def test_page_lists_aps_unknown_trainee_and_excludes_other_training_types(self):
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
                },
                {
                    "id": "S2",
                    "name": "Session VTC",
                    "training_type": "VTC",
                    "trainees": [
                        {
                            "id": "T3",
                            "first_name": "Victor",
                            "last_name": "Vtc",
                            "cnaps": "INCONNU",
                        },
                    ],
                },
                {
                    "id": "S3",
                    "name": "Session dirigeant",
                    "training_type": "DIRIGEANT",
                    "trainees": [
                        {
                            "id": "T4",
                            "first_name": "Diane",
                            "last_name": "Dirigeant",
                            "cnaps": "INCONNU",
                        },
                    ],
                },
                {
                    "id": "S4",
                    "name": "Session VAE DESP",
                    "training_type": "VAE DESP",
                    "trainees": [
                        {
                            "id": "T5",
                            "first_name": "Valerie",
                            "last_name": "Vae",
                            "cnaps": "INCONNU",
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
        self.assertNotIn("VTC Victor", html)
        self.assertNotIn("DIRIGEANT Diane", html)
        self.assertNotIn("VAE Valerie", html)
