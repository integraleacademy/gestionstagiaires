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

    def test_expands_a_recurring_qonto_subscription_into_every_month(self):
        line = {
            "id": "line-1", "traineeId": "trainee-1", "sessionId": "session-1",
            "financingType": "personal", "amount": 3475, "paymentMode": "cash",
        }
        subscriptions = {"direct_debit_subscriptions": [{
            "id": "sub-recurring", "direct_debit_mandate_id": "mandate-123",
            "initial_collection_date": "2026-06-05", "end_date": "2026-10-05",
            "amount": {"value": "695.00"}, "status": "pending", "schedule_type": "monthly",
        }]}

        with patch.object(gestion_app, "list_qonto_direct_debit_subscriptions", return_value=subscriptions):
            recovered = gestion_app._recover_qonto_installments_for_mandate(line, "mandate-123")

        self.assertEqual(recovered, 5)
        self.assertEqual(
            [item["date"] for item in line["directDebitInstallments"]],
            ["2026-06-05", "2026-07-05", "2026-08-05", "2026-09-05", "2026-10-05"],
        )
        self.assertEqual([item["amount"] for item in line["directDebitInstallments"]], [695.0] * 5)
        self.assertTrue(all(item["status"] == "scheduled" for item in line["directDebitInstallments"]))

    def test_restores_missing_recurring_occurrences_and_keeps_future_rows_after_rejection(self):
        line = {"amount": 3475, "paymentMode": "cash"}
        subscriptions = {"direct_debit_subscriptions": [{
            "id": "sub-recurring", "direct_debit_mandate_id": "mandate-123",
            "initial_collection_date": "2026-06-05", "amount": {"value": "695.00"},
            "status": "rejected", "schedule_type": "monthly",
        }]}

        with patch.object(gestion_app, "list_qonto_direct_debit_subscriptions", return_value=subscriptions):
            recovered = gestion_app._recover_qonto_installments_for_mandate(line, "mandate-123")

        self.assertEqual(recovered, 5)
        self.assertEqual(
            [item["status"] for item in line["directDebitInstallments"]],
            ["failed", "scheduled", "scheduled", "scheduled", "scheduled"],
        )
        self.assertEqual(line["sepa_payment_plan"]["total_due"], 3475)

    def test_webhook_rejection_only_updates_the_matching_recurring_occurrence(self):
        installments = [
            {"date": "2026-06-05", "status": "scheduled", "qonto_direct_debit_subscription_id": "sub-1"},
            {"date": "2026-07-05", "status": "scheduled", "qonto_direct_debit_subscription_id": "sub-1"},
            {"date": "2026-08-05", "status": "scheduled", "qonto_direct_debit_subscription_id": "sub-1"},
        ]
        line = {"paymentMode": "sepa_direct_debit", "directDebitInstallments": installments}
        data = {"billing_lines": [line]}
        event = {
            "id": "collection-1", "direct_debit_subscription_id": "sub-1",
            "collection_date": "2026-06-05", "status": "rejected", "status_reason": "blocked_account",
        }

        with patch.object(gestion_app, "_billing_lines", return_value=[line]), \
             patch.object(gestion_app, "_save_billing_line"):
            updated = gestion_app._apply_qonto_collection_webhook(data, event)

        self.assertTrue(updated)
        self.assertEqual([item["status"] for item in installments], ["failed", "scheduled", "scheduled"])
        self.assertEqual(installments[0]["failureReason"], "blocked_account")

    def test_sync_matches_collections_by_date_for_a_recurring_subscription(self):
        installments = [
            {"date": "2026-06-05", "due_date": "2026-06-05", "amount": 695, "status": "scheduled", "qonto_direct_debit_subscription_id": "sub-1"},
            {"date": "2026-07-05", "due_date": "2026-07-05", "amount": 695, "status": "scheduled", "qonto_direct_debit_subscription_id": "sub-1"},
            {"date": "2026-08-05", "due_date": "2026-08-05", "amount": 695, "status": "scheduled", "qonto_direct_debit_subscription_id": "sub-1"},
        ]
        line = {"paymentMode": "sepa_direct_debit", "directDebitInstallments": installments}
        collections = {"direct_debit_collections": [
            {"id": "col-paid", "collection_date": "2026-06-05", "status": "completed"},
            {"id": "col-rejected", "collection_date": "2026-07-05", "status": "rejected", "status_reason": "blocked_account"},
        ]}

        with patch.object(gestion_app, "list_qonto_direct_debit_collections", return_value=collections):
            gestion_app._sync_qonto_direct_debit_line(line)

        self.assertEqual([item["status"] for item in installments], ["completed", "failed", "scheduled"])
        self.assertEqual(installments[1]["failureReason"], "blocked_account")

    def test_sync_recovers_retry_created_by_the_previous_alias_bug(self):
        installments = [
            {"index": 1, "date": "2026-07-05", "due_date": "2026-07-05", "amount": 600, "status": "completed", "qonto_direct_debit_subscription_id": "sub-1"},
            {"index": 2, "date": "2026-08-05", "due_date": "2026-08-05", "amount": 600, "status": "failed", "failureReason": "insufficient_funds", "qonto_direct_debit_subscription_id": "sub-2"},
            {"index": 3, "date": "2026-09-05", "due_date": "2026-09-05", "amount": 600, "status": "scheduled", "qonto_direct_debit_subscription_id": "sub-3"},
        ]
        line = {
            "id": "line-1", "paymentMode": "sepa_direct_debit",
            "qonto_direct_debit_mandate_id": "mandate-123", "qonto_mandate_status": "active",
            "directDebitInstallments": installments,
            "sepa_payment_plan": {"installments": installments},
        }
        subscriptions = {"direct_debit_subscriptions": [{
            "id": "sub-retry", "direct_debit_mandate_id": "mandate-123",
            "initial_collection_date": "2026-08-12", "amount": {"value": "600.00"},
            "status": "pending",
            "reference": "bill_42a418abb669 - reprogrammation échéance 2/3",
            "created_at": "2026-08-11T08:00:00Z",
        }]}

        with patch.object(gestion_app, "list_qonto_direct_debit_subscriptions", return_value=subscriptions):
            recovered = gestion_app._recover_missing_qonto_rejection_retries(line, "mandate-123")

        self.assertEqual(recovered, 1)
        self.assertEqual(len(installments), 4)
        original, retry = installments[1], installments[-1]
        self.assertTrue(original["rejection_treated"])
        self.assertEqual(original["replaced_by_direct_debit_subscription_id"], "sub-retry")
        self.assertTrue(retry["is_rejection_retry"])
        self.assertEqual(retry["schedule_index"], 2)
        self.assertEqual(retry["schedule_total"], 3)
        self.assertEqual(retry["date"], "2026-08-12")
        self.assertEqual(retry["qonto_direct_debit_subscription_id"], "sub-retry")
        self.assertEqual(line["sepa_payment_plan"]["total_due"], 1800)
        self.assertEqual(line["sepa_payment_plan"]["remaining_installments"], 2)
        self.assertEqual(line["qontoPaymentGlobalStatus"], "Rejet traité")

        with patch.object(gestion_app, "list_qonto_direct_debit_subscriptions", return_value=subscriptions):
            self.assertEqual(gestion_app._recover_missing_qonto_rejection_retries(line, "mandate-123"), 0)

    def test_logged_alias_loss_is_repaired_and_its_notification_is_resolved(self):
        installment = {
            "index": 5, "date": "2026-08-05", "due_date": "2026-08-05",
            "amount": 600, "status": "failed", "failureReason": "insufficient_funds",
            "qonto_direct_debit_subscription_id": "sub-old",
        }
        line = {
            "id": "line-1", "traineeId": "trainee-1", "sessionId": "session-1",
            "traineeFirstName": "Anthony", "traineeLastName": "Urbanik",
            "paymentMode": "sepa_direct_debit", "qonto_direct_debit_mandate_id": "mandate-123",
            "qonto_mandate_status": "active", "directDebitInstallments": [installment],
            "sepa_payment_plan": {"installments": [installment]},
            "logs": [{
                "action": "Prélèvement rejeté reprogrammé", "result": "success",
                "qonto_id": "sub-retry",
            }],
        }
        notification = {
            "id": "notification-1", "done": False, "label": "Prélèvement rejeté",
            "meta": {
                "kind": "qonto_direct_debit_rejected", "trainee_id": "trainee-1",
                "session_id": "session-1", "scheduled_date": "2026-08-05", "amount": 600,
            },
        }
        data = {"billing_lines": [line], "notifications_admin": [notification]}
        subscriptions = {"direct_debit_subscriptions": [{
            "id": "sub-retry", "direct_debit_mandate_id": "mandate-123",
            "initial_collection_date": "2026-08-12", "amount": {"value": "600.00"},
            "status": "pending", "reference": "bill_42 - reprogrammation échéance 5/7",
        }]}

        with patch.object(gestion_app, "list_qonto_direct_debit_subscriptions", return_value=subscriptions), \
             patch.object(gestion_app, "save_data") as save_mock:
            repaired = gestion_app._repair_logged_qonto_rejection_retries(data, [line])

        self.assertEqual(repaired, 1)
        self.assertTrue(notification["done"])
        self.assertIn("Rejet traité", notification["label"])
        self.assertEqual(notification["meta"]["replacement_subscription_id"], "sub-retry")
        self.assertEqual(len(data["billing_lines"][0]["directDebitInstallments"]), 2)
        save_mock.assert_called_once_with(data)


if __name__ == "__main__":
    unittest.main()
