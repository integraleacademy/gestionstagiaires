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

    def test_global_login_accepts_birth_name_alias(self):
        self.data["sessions"][0]["trainees"][0]["last_name"] = "DUPONT"
        self.data["sessions"][0]["trainees"][0]["nom_naissance"] = "BONELLO"
        self.data["sessions"][0]["trainees"][0]["birth_date"] = "1979-10-29"

        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/espacestagiaire",
                data={"last_name": "BONELLO", "birth": "29101979"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/espace/PUBLIC-TOKEN", response.headers["Location"])

    def test_global_login_accepts_old_french_keys(self):
        data = {
            "sessions": [
                {
                    "id": "S1",
                    "stagiaires": [
                        {
                            "id": "T1",
                            "nom": "BONELLO",
                            "prenom": "Alice",
                            "date_naissance": "1979-10-29",
                            "public_token": "PUBLIC-TOKEN",
                        }
                    ],
                }
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/espacestagiaire",
                data={"last_name": "BONELLO", "birth": "29101979"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/espace/PUBLIC-TOKEN", response.headers["Location"])

    def test_token_login_accepts_same_identity_aliases_as_global_login(self):
        self.data["sessions"][0]["trainees"][0]["last_name"] = "DUPONT"
        self.data["sessions"][0]["trainees"][0]["nom_naissance"] = "BONELLO"
        self.data["sessions"][0]["trainees"][0]["birth_date"] = "1979-10-29"

        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/espace/PUBLIC-TOKEN/login",
                data={"last_name": "BONELLO", "birth": "29101979"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/espace/PUBLIC-TOKEN", response.headers["Location"])

    def test_global_login_accepts_us_style_stored_birth_date(self):
        self.data["sessions"][0]["trainees"][0]["last_name"] = "BONELLO"
        self.data["sessions"][0]["trainees"][0]["birth_date"] = "10/29/1979"

        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/espacestagiaire",
                data={"last_name": "bonello", "birth": "29101979"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/espace/PUBLIC-TOKEN", response.headers["Location"])

    def test_global_login_accepts_alternate_birth_date_key(self):
        del self.data["sessions"][0]["trainees"][0]["birth_date"]
        self.data["sessions"][0]["trainees"][0]["last_name"] = "BONELLO"
        self.data["sessions"][0]["trainees"][0]["dateNaissance"] = "1979-10-29"

        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/espacestagiaire",
                data={"last_name": "BONELLO", "birth": "29/10/1979"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/espace/PUBLIC-TOKEN", response.headers["Location"])

    def test_global_login_failure_logs_debug_summary(self):
        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(
            gestion_app, "save_data"
        ), self.assertLogs(gestion_app.app.logger.name, level="WARNING") as logs:
            response = self.client.post(
                "/espacestagiaire",
                data={"last_name": "BONELLO", "birth": "01011970"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        output = "\n".join(logs.output)
        self.assertIn("[PUBLIC_GLOBAL_LOGIN_FAIL]", output)
        self.assertIn("input_last_norm", output)
        self.assertIn("trainees_count", output)
