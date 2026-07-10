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



    def test_public_student_portal_base_rewrites_legacy_render_host(self):
        self.assertEqual(
            gestion_app._normalize_public_student_portal_base("https://gestionstagiaires-r5no.onrender.com/"),
            "https://gestionstagiaires-test-v2.onrender.com",
        )

    def test_public_student_portal_base_keeps_current_target_host(self):
        self.assertEqual(
            gestion_app._normalize_public_student_portal_base("https://gestionstagiaires-test-v2.onrender.com/"),
            "https://gestionstagiaires-test-v2.onrender.com",
        )

    def test_404_unknown_space_token_links_to_global_login(self):
        with patch.object(gestion_app, "load_data", return_value=self.data):
            response = self.client.get("/espace/UNKNOWN-TOKEN", follow_redirects=False)

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 404)
        self.assertIn('href="/espacestagiaire"', body)
        self.assertNotIn('/espace/UNKNOWN-TOKEN/login', body)

    def test_404_known_space_token_links_to_token_login(self):
        with patch.object(gestion_app, "load_data", return_value=self.data):
            response = self.client.get("/espace/PUBLIC-TOKEN/does-not-exist", follow_redirects=False)

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 404)
        self.assertIn('href="/espace/PUBLIC-TOKEN/login"', body)

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

    def test_birth_to_ddmmyyyy_accepts_iso_and_single_digit_french(self):
        self.assertEqual(gestion_app._birth_to_ddmmyyyy("2004-01-08"), "08012004")
        self.assertEqual(gestion_app._birth_to_ddmmyyyy("08/01/2004"), "08012004")
        self.assertEqual(gestion_app._birth_to_ddmmyyyy("08-01-2004"), "08012004")
        self.assertEqual(gestion_app._birth_to_ddmmyyyy("8/1/2004"), "08012004")

    def test_global_login_homonyms_different_birth_dates_redirects_right_trainee(self):
        data = {
            "sessions": [{"id": "S1", "trainees": [
                {"id": "T1", "last_name": "BONELLO", "birth_date": "2004-01-08", "public_token": "TOKEN-0801"},
                {"id": "T2", "last_name": "BONELLO", "birth_date": "2005-02-09", "public_token": "TOKEN-0902"},
            ]}]
        }
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(gestion_app, "save_data"):
            response = self.client.post(
                "/espacestagiaire",
                data={"last_name": " bonello ", "birth": "08/01/2004"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/espace/TOKEN-0801", response.headers["Location"])

    def test_global_login_duplicate_same_name_and_birth_shows_multiple_message(self):
        data = {
            "sessions": [{"id": "S1", "trainees": [
                {"id": "T1", "last_name": "BONELLO", "birth_date": "2004-01-08", "public_token": "TOKEN-1"},
                {"id": "T2", "last_name": "BONELLO", "birth_date": "08/01/2004", "public_token": "TOKEN-2"},
            ]}]
        }
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(gestion_app, "save_data"):
            response = self.client.post(
                "/espacestagiaire",
                data={"last_name": "BONELLO", "birth": "08012004"},
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Plusieurs dossiers correspondent", response.get_data(as_text=True))
