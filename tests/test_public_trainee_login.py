import unittest
from unittest.mock import patch

import app as gestion_app


class PublicTraineeLoginTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.data = {
            "sessions": [
                {
                    "id": "S1",
                    "trainees": [
                        {
                            "id": "T1",
                            "last_name": "LAVAUX",
                            "first_name": "Jason",
                            "birth_date": "1999-08-19",
                            "public_token": "PUBLIC-TOKEN",
                        }
                    ],
                }
            ]
        }

    def test_birth_to_ddmmyyyy_keeps_public_ddmmyyyy_when_day_starts_with_19(self):
        self.assertEqual(gestion_app._birth_to_ddmmyyyy("19081999"), "19081999")

    def test_birth_to_ddmmyyyy_accepts_compact_yyyymmdd_storage(self):
        self.assertEqual(gestion_app._birth_to_ddmmyyyy("19990819"), "19081999")

    def test_global_login_accepts_birthdays_on_day_19(self):
        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/espacestagiaire",
                data={"last_name": "LAVAUX", "birth": "19081999"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/espace/PUBLIC-TOKEN", response.headers["Location"])
