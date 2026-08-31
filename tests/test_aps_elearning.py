import datetime
import unittest
from unittest.mock import patch

import app as gestion_app


class ApsElearningTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.saved_data = None

    def _admin_login(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def _public_login(self, token="PUBLIC-TOKEN"):
        with self.client.session_transaction() as sess:
            sess[f"public_auth_{token}"] = True

    @staticmethod
    def _data(date_start, *, enabled=True, training_type="APS"):
        return {
            "sessions": [
                {
                    "id": "S-APS",
                    "name": "Session APS e-learning",
                    "training_type": training_type,
                    "date_start": date_start,
                    "date_end": date_start,
                    "aps_elearning_enabled": enabled,
                    "trainees": [
                        {
                            "id": "T-APS",
                            "public_token": "PUBLIC-TOKEN",
                            "last_name": "MARTIN",
                            "first_name": "Alice",
                            "aps_elearning_login": "alice.aps",
                            "aps_elearning_password": "Secret-123",
                            "documents": [],
                        }
                    ],
                }
            ]
        }

    def test_session_api_persists_option_only_for_aps(self):
        self._admin_login()
        aps_data = {"sessions": []}

        with patch.object(gestion_app, "load_data", return_value=aps_data), patch.object(
            gestion_app, "save_data", side_effect=lambda data: setattr(self, "saved_data", data)
        ):
            response = self.client.post(
                "/api/sessions/create",
                json={
                    "name": "APS juin",
                    "training_type": "APS",
                    "date_start": "2026-06-15",
                    "aps_elearning_enabled": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.saved_data["sessions"][0]["aps_elearning_enabled"])

        non_aps_data = {"sessions": []}
        with patch.object(gestion_app, "load_data", return_value=non_aps_data), patch.object(
            gestion_app, "save_data", side_effect=lambda data: setattr(self, "saved_data", data)
        ):
            response = self.client.post(
                "/api/sessions/create",
                json={
                    "name": "VTC juin",
                    "training_type": "VTC",
                    "aps_elearning_enabled": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.saved_data["sessions"][0]["aps_elearning_enabled"])

    def test_admin_sessions_cards_show_direct_elearning_checkbox_only_for_aps(self):
        self._admin_login()
        future_start = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        future_end = (datetime.date.today() + datetime.timedelta(days=14)).isoformat()
        data = self._data(future_start)
        data["sessions"][0]["partner_id"] = gestion_app.INTEGRALE_PARTNER_ID
        data["sessions"][0]["date_end"] = future_end
        data["sessions"].append(
            {
                "id": "S-VTC",
                "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
                "name": "Session VTC",
                "training_type": "VTC",
                "date_start": future_start,
                "date_end": future_end,
                "aps_elearning_enabled": True,
                "trainees": [],
            }
        )

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "_load_wedof_webhooks", return_value=[]
        ):
            response = self.client.get("/admin/sessions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-aps-elearning-toggle="S-APS"', html)
        self.assertNotIn('data-aps-elearning-toggle="S-VTC"', html)
        self.assertRegex(
            html,
            r'data-aps-elearning-toggle="S-APS"\s+checked',
        )
        self.assertIn("🎓 E-learning", html)

    def test_admin_trainee_credentials_are_available_only_for_enabled_aps_session(self):
        self._admin_login()
        data = self._data("2026-06-15")

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.get("/admin/sessions/S-APS/stagiaires/T-APS")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Identifiants e-learning APS", html)
        self.assertIn('id="editApsElearningLogin"', html)
        self.assertIn('id="editApsElearningPassword"', html)

        data["sessions"][0]["aps_elearning_enabled"] = False
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.get("/admin/sessions/S-APS/stagiaires/T-APS")
        self.assertNotIn("Identifiants e-learning APS", response.get_data(as_text=True))

    def test_trainee_api_saves_credentials_only_when_aps_elearning_is_enabled(self):
        self._admin_login()
        data = self._data("2026-06-15")

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/api/sessions/S-APS/stagiaires/T-APS/update",
                json={
                    "aps_elearning_login": "nouveau-login",
                    "aps_elearning_password": "nouveau-password",
                },
            )

        self.assertEqual(response.status_code, 200)
        trainee = data["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["aps_elearning_login"], "nouveau-login")
        self.assertEqual(trainee["aps_elearning_password"], "nouveau-password")

        data["sessions"][0]["aps_elearning_enabled"] = False
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/api/sessions/S-APS/stagiaires/T-APS/update",
                json={
                    "aps_elearning_login": "doit-etre-ignore",
                    "aps_elearning_password": "doit-etre-ignore",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(trainee["aps_elearning_login"], "nouveau-login")
        self.assertEqual(trainee["aps_elearning_password"], "nouveau-password")

    def test_public_space_hides_credentials_before_first_training_day(self):
        self._public_login()
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        data = self._data(tomorrow.isoformat())

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.get("/espace/PUBLIC-TOKEN")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(f"Accès disponible le {tomorrow.strftime('%d/%m/%Y')}", html)
        self.assertNotIn("alice.aps", html)
        self.assertNotIn("Secret-123", html)
        self.assertNotIn("Accéder au e-learning", html)

    def test_public_space_shows_credentials_and_copy_actions_from_first_day(self):
        self._public_login()
        data = self._data(datetime.date.today().isoformat())

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.get("/espace/PUBLIC-TOKEN")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("alice.aps", html)
        self.assertIn("Secret-123", html)
        self.assertIn('data-copy-target="apsElearningLogin"', html)
        self.assertIn('data-copy-target="apsElearningPassword"', html)
        self.assertIn('href="https://ediser.elmg.net/"', html)

    def test_public_space_does_not_show_aps_card_for_vtc_or_disabled_session(self):
        self._public_login()
        for training_type, enabled in (("VTC", True), ("APS", False)):
            data = self._data(datetime.date.today().isoformat(), enabled=enabled, training_type=training_type)
            with patch.object(gestion_app, "load_data", return_value=data), patch.object(
                gestion_app, "save_data"
            ):
                response = self.client.get("/espace/PUBLIC-TOKEN")
            html = response.get_data(as_text=True)
            self.assertNotIn("Espace e-learning APS", html)
            self.assertNotIn("alice.aps", html)
            self.assertNotIn("Secret-123", html)


if __name__ == "__main__":
    unittest.main()
