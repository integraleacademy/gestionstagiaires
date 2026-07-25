import unittest
from unittest.mock import patch

import app as gestion_app


class AdminTraineeQontoMandateSearchTest(unittest.TestCase):
    def setUp(self):
        gestion_app.app.config.update(TESTING=True)
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def test_searches_qonto_and_persists_mandate_on_trainee(self):
        trainee = {"id": "trainee-1", "first_name": "Anne", "last_name": "Test"}
        data = {"sessions": [{"id": "session-1", "trainees": [trainee]}]}
        qonto_response = {
            "direct_debit_mandate": {
                "id": "mandate_123",
                "status": "approved",
                "client_id": "client_456",
                "created_at": "2026-07-20T10:00:00Z",
            }
        }

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data") as save_mock, \
             patch.object(gestion_app, "get_qonto_direct_debit_mandate", return_value=qonto_response) as qonto_mock:
            response = self.client.post(
                "/api/admin/trainees/trainee-1/qonto-mandate/search",
                json={"mandate_id": "mandate_123"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["mandate"]["status"], "active")
        qonto_mock.assert_called_once_with("mandate_123")
        self.assertEqual(trainee["qonto_direct_debit_mandate_id"], "mandate_123")
        self.assertEqual(trainee["qonto_mandate_client_id"], "client_456")
        save_mock.assert_called_once_with(data)

    def test_rejects_invalid_mandate_number_without_calling_qonto(self):
        with patch.object(gestion_app, "get_qonto_direct_debit_mandate") as qonto_mock:
            response = self.client.post(
                "/api/admin/trainees/trainee-1/qonto-mandate/search",
                json={"mandate_id": "mandate avec espaces"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])
        qonto_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
