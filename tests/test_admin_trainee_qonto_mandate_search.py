import unittest
from unittest.mock import call, patch

import app as gestion_app


class AdminTraineeQontoMandateSearchTest(unittest.TestCase):
    def setUp(self):
        gestion_app.app.config.update(TESTING=True)
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def test_searches_every_page_by_exact_rum_and_persists_uuid_and_rum(self):
        trainee = {"id": "trainee-1", "first_name": "Anne", "last_name": "Test"}
        data = {"sessions": [{"id": "session-1", "trainees": [trainee]}]}
        first_page = {
            "direct_debit_mandates": [
                {"id": f"00000000-0000-4000-8000-{number:012d}", "rum": f"OTHER-{number}"}
                for number in range(100)
            ],
            "meta": {"current_page": 1, "next_page": 2, "total_pages": 2},
        }
        qonto_uuid = "123e4567-e89b-42d3-a456-426614174000"
        second_page = {
            "direct_debit_mandates": [{
                "id": qonto_uuid,
                "rum": "RUM-EXACT-123",
                "status": "approved",
                "client_id": "client_456",
                "created_at": "2026-07-20T10:00:00Z",
            }],
            "meta": {"current_page": 2, "total_pages": 2},
        }

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data") as save_mock, \
             patch.object(
                 gestion_app,
                 "list_qonto_direct_debit_mandates",
                 side_effect=[first_page, second_page],
             ) as qonto_mock, \
             patch.object(gestion_app, "get_qonto_direct_debit_mandate") as get_mock:
            response = self.client.post(
                "/api/admin/trainees/trainee-1/qonto-mandate/search",
                json={"rum": "RUM-EXACT-123"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["mandate"]["id"], qonto_uuid)
        self.assertEqual(response.get_json()["mandate"]["rum"], "RUM-EXACT-123")
        self.assertEqual(response.get_json()["mandate"]["status"], "active")
        self.assertEqual(
            qonto_mock.call_args_list,
            [call(page=1, per_page=100), call(page=2, per_page=100)],
        )
        get_mock.assert_not_called()
        self.assertEqual(trainee["qonto_direct_debit_mandate_id"], qonto_uuid)
        self.assertEqual(trainee["qonto_mandate_rum"], "RUM-EXACT-123")
        self.assertEqual(trainee["qonto_mandate_client_id"], "client_456")
        save_mock.assert_called_once_with(data)

    def test_returns_business_message_when_no_exact_rum_matches(self):
        trainee = {"id": "trainee-1"}
        data = {"sessions": [{"id": "session-1", "trainees": [trainee]}]}
        response_page = {
            "direct_debit_mandates": [{"id": "some-uuid", "rum": "rum-lowercase"}],
            "meta": {"current_page": 1, "total_pages": 1},
        }
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "list_qonto_direct_debit_mandates", return_value=response_page), \
             patch.object(gestion_app, "get_qonto_direct_debit_mandate") as get_mock:
            response = self.client.post(
                "/api/admin/trainees/trainee-1/qonto-mandate/search",
                json={"rum": "RUM-LOWERCASE"},
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], "Aucun mandat Qonto trouvé avec ce RUM")
        get_mock.assert_not_called()
        self.assertNotIn("qonto_direct_debit_mandate_id", trainee)

    def test_rejects_invalid_rum_without_calling_qonto(self):
        with patch.object(gestion_app, "list_qonto_direct_debit_mandates") as qonto_mock:
            response = self.client.post(
                "/api/admin/trainees/trainee-1/qonto-mandate/search",
                json={"rum": "invalid\nrum"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])
        qonto_mock.assert_not_called()

    def test_recovers_existing_qonto_installments_with_the_mandate(self):
        line = {
            "id": "line-1", "traineeId": "trainee-1", "sessionId": "session-1",
            "financingType": "personal", "amount": 300, "paymentMode": "cash",
        }
        trainee = {"id": "trainee-1", "first_name": "Anne", "last_name": "Test"}
        data = {"sessions": [{"id": "session-1", "trainees": [trainee]}], "billing_lines": [line]}
        mandate = {"id": "mandate-123", "rum": "RUM-123", "status": "active", "client_id": "client-1"}
        subscriptions = {
            "direct_debit_subscriptions": [
                {"id": "sub-2", "direct_debit_mandate_id": "mandate-123", "initial_collection_date": "2026-09-10", "amount": {"value": "150.00"}, "status": "pending"},
                {"id": "sub-1", "direct_debit_mandate_id": "mandate-123", "initial_collection_date": "2026-08-10", "amount": {"value": "150.00"}, "status": "completed"},
            ],
            "meta": {"current_page": 1, "total_pages": 1},
        }

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data"), \
             patch.object(gestion_app, "_billing_lines", return_value=[line]), \
             patch.object(gestion_app, "find_qonto_direct_debit_mandate_by_rum", return_value=mandate), \
             patch.object(gestion_app, "list_qonto_direct_debit_subscriptions", return_value=subscriptions):
            response = self.client.post(
                "/api/admin/trainees/trainee-1/qonto-mandate/search", json={"rum": "RUM-123"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["recovered_installments"], 2)
        self.assertEqual(line["paymentMode"], "sepa_direct_debit")
        self.assertEqual([item["date"] for item in line["directDebitInstallments"]], ["2026-08-10", "2026-09-10"])
        self.assertEqual([item["status"] for item in line["directDebitInstallments"]], ["completed", "scheduled"])


if __name__ == "__main__":
    unittest.main()
