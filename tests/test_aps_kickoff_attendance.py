import unittest
from unittest.mock import patch

import app as gestion_app


class ApsKickoffAttendanceTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

        self.data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "name": "TFP APS septembre 2026",
                    "training_type": "APS",
                    "date_start": "2026-09-07",
                    "date_end": "2026-10-09",
                    "aps_in_person_start": "2026-09-18",
                    "trainees": [
                        {"id": "T2", "last_name": "zola", "first_name": "zoé", "documents": []},
                        {"id": "T1", "last_name": "bernard", "first_name": "alice", "documents": []},
                        {
                            "id": "T3",
                            "last_name": "annulé",
                            "first_name": "stagiaire",
                            "registration_cancelled": True,
                            "documents": [],
                        },
                    ],
                },
                {
                    "id": "S-A3P",
                    "name": "Session A3P",
                    "training_type": "A3P",
                    "date_start": "2026-09-01",
                    "trainees": [],
                },
            ]
        }

    def test_print_sheet_uses_first_in_person_day_and_active_trainees(self):
        with patch.object(gestion_app, "load_data", return_value=self.data):
            response = self.client.get(
                "/admin/sessions/S-APS/trainees/aps-kickoff-attendance/print?autoprint=1"
            )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Feuille de présence", html)
        self.assertIn("Réunion de démarrage et présentation du e-learning", html)
        self.assertIn("18/09/2026", html)
        self.assertIn("Intégrale Sécurité Formations", html)
        self.assertIn("54 chemin du Carreou", html)
        self.assertIn("83480 PUGET-SUR-ARGENS", html)
        self.assertIn("08h30 à 10h30", html)
        self.assertNotIn("Heure d’arrivée", html)
        self.assertIn("Cassandre MENARD", html)
        self.assertIn("Clément VAILLANT", html)
        self.assertIn("Cachet et signature du centre de formation", html)
        self.assertIn("Tampon d’Intégrale Sécurité Formations", html)
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("BERNARD", html)
        self.assertIn("ZOLA", html)
        self.assertNotIn("ANNULÉ", html)
        self.assertLess(html.index("BERNARD"), html.index("ZOLA"))
        self.assertIn("window.print()", html)

    def test_print_sheet_is_not_available_for_a3p(self):
        with patch.object(gestion_app, "load_data", return_value=self.data):
            response = self.client.get(
                "/admin/sessions/S-A3P/trainees/aps-kickoff-attendance/print"
            )

        self.assertEqual(response.status_code, 404)

    def test_admin_button_is_visible_only_for_aps(self):
        with (
            patch.object(gestion_app, "load_data", return_value=self.data),
            patch.object(gestion_app, "save_data"),
            patch.object(gestion_app, "fetch_cnapsv3_tracking_requests", return_value=([], None)),
        ):
            aps_html = self.client.get("/admin/sessions/S-APS/trainees").get_data(as_text=True)
            a3p_html = self.client.get("/admin/sessions/S-A3P/trainees").get_data(as_text=True)

        self.assertIn('id="btnPrintApsKickoffAttendance"', aps_html)
        self.assertIn("Feuille de présence e-learning", aps_html)
        self.assertNotIn('id="btnPrintApsKickoffAttendance"', a3p_html)


if __name__ == "__main__":
    unittest.main()
