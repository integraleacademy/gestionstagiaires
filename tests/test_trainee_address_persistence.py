import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gestion_app


class TraineeAddressPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"
        self.saved_data = None

    @staticmethod
    def _data():
        return {
            "sessions": [
                {
                    "id": "S-ADDR",
                    "name": "Session adresse",
                    "training_type": "VTC",
                    "date_start": "2026-09-01",
                    "trainees": [
                        {
                            "id": "T-ADDR",
                            "last_name": "DUPONT",
                            "first_name": "Alice",
                            "documents": [],
                        }
                    ],
                }
            ]
        }

    def test_backend_save_preserves_initial_street_number(self):
        data = self._data()
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data", side_effect=lambda saved: setattr(self, "saved_data", copy.deepcopy(saved))
        ):
            response = self.client.post(
                "/api/sessions/S-ADDR/stagiaires/T-ADDR/update",
                json={"address": "  650 Route d’Aumont  ", "zip_code": "15130", "city": "Arpajon-sur-Cère"},
            )

        self.assertEqual(response.status_code, 200)
        trainee = self.saved_data["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["address"], "650 Route d’Aumont")
        self.assertEqual(trainee["zip_code"], "15130")
        self.assertEqual(trainee["city"], "Arpajon-sur-Cère")

    def test_reloaded_trainee_keeps_saved_initial_number(self):
        data = self._data()
        data["sessions"][0]["trainees"][0].update(
            {"address": "4 ter Avenue de la République", "zip_code": "75011", "city": "Paris"}
        )
        with patch.object(gestion_app, "load_data", return_value=data):
            response = self.client.get("/admin/sessions/S-ADDR/stagiaires/T-ADDR")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("4 ter Avenue de la République", html)
        self.assertIn("75011", html)
        self.assertIn("Paris", html)
