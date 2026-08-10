import unittest
from pathlib import Path
from unittest.mock import patch

import app as gestion_app


class AdminTraineeRescheduleDebitTests(unittest.TestCase):
    def setUp(self):
        gestion_app.app.config.update(TESTING=True)
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def test_finance_card_exposes_action_only_when_a_debit_is_rejected(self):
        template = Path("templates/admin_trainee.html").read_text(encoding="utf-8")

        self.assertIn("rescheduleAction:c.nombreRejets>0", template)
        self.assertIn("Reprogrammer un prélèvement", template)
        self.assertIn("data-reschedule-rejected-debit", template)
        self.assertIn("/api/billing/reschedule-rejected-debit", template)
        self.assertIn("data-rejected-debit-check", template)
        self.assertIn("data-rejected-debit-amount", template)
        self.assertIn("Reprogrammer la sélection", template)

    def test_endpoint_replaces_rejected_subscription_and_keeps_its_history(self):
        installment = {
            "amount": 325.5,
            "date": "2026-08-05",
            "due_date": "2026-08-05",
            "status": "failed",
            "failureReason": "insufficient_funds",
            "qonto_direct_debit_subscription_id": "SUB-OLD",
        }
        line = {
            "id": "line-1",
            "paymentMode": "sepa_direct_debit",
            "qontoClientId": "client-1",
            "qonto_direct_debit_mandate_id": "mandate-1",
            "qonto_mandate_status": "active",
            "directDebitInstallments": [installment],
        }
        data = {"billing_lines": [line]}

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_billing_lines", return_value=[line]), \
             patch.object(gestion_app, "_ensure_qonto_oauth_ready"), \
             patch.object(gestion_app, "get_qonto_bank_account_id", return_value="bank-1"), \
             patch.object(gestion_app, "create_qonto_direct_debit_subscription", return_value={"direct_debit_subscription": {"id": "SUB-NEW"}}) as create_mock, \
             patch.object(gestion_app, "_save_billing_line"), \
             patch.object(gestion_app, "save_data"):
            response = self.client.post("/api/billing/reschedule-rejected-debit", json={
                "lineId": "line-1",
                "installmentIndex": 0,
                "collectionDate": "2099-09-15",
            })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        payload = create_mock.call_args.args[0]
        self.assertEqual(payload["initial_collection_date"], "2099-09-15")
        self.assertEqual(payload["amount"], {"value": "325.50", "currency": "EUR"})
        self.assertEqual(installment["status"], "scheduled")
        self.assertEqual(installment["qonto_direct_debit_subscription_id"], "SUB-NEW")
        self.assertEqual(installment["reprogramming_history"][0]["qonto_direct_debit_subscription_id"], "SUB-OLD")

    def test_endpoint_reschedules_multiple_debits_with_custom_amounts(self):
        installments = [
            {"amount": 100, "date": "2026-07-01", "status": "failed", "qonto_direct_debit_subscription_id": "OLD-1"},
            {"amount": 200, "date": "2026-08-01", "status": "rejected", "qonto_direct_debit_subscription_id": "OLD-2"},
        ]
        line = {
            "id": "line-1", "qontoClientId": "client-1",
            "qonto_direct_debit_mandate_id": "mandate-1",
            "directDebitInstallments": installments,
        }
        data = {"billing_lines": [line]}
        responses = [
            {"direct_debit_subscription": {"id": "NEW-1"}},
            {"direct_debit_subscription": {"id": "NEW-2"}},
        ]
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_billing_lines", return_value=[line]), \
             patch.object(gestion_app, "_ensure_qonto_oauth_ready"), \
             patch.object(gestion_app, "get_qonto_bank_account_id", return_value="bank-1"), \
             patch.object(gestion_app, "create_qonto_direct_debit_subscription", side_effect=responses) as create_mock, \
             patch.object(gestion_app, "_save_billing_line"), \
             patch.object(gestion_app, "save_data"):
            response = self.client.post("/api/billing/reschedule-rejected-debit", json={
                "collectionDate": "2099-10-20",
                "items": [
                    {"lineId": "line-1", "installmentIndex": 0, "amount": 75.25},
                    {"lineId": "line-1", "installmentIndex": 1, "amount": 150},
                ],
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["count"], 2)
        self.assertEqual(create_mock.call_count, 2)
        self.assertEqual(create_mock.call_args_list[0].args[0]["amount"]["value"], "75.25")
        self.assertEqual(create_mock.call_args_list[1].args[0]["amount"]["value"], "150.00")
        self.assertEqual([item["amount"] for item in installments], [75.25, 150.0])
        self.assertEqual(installments[0]["reprogramming_history"][0]["amount"], 100)

    def test_endpoint_rejects_an_empty_batch(self):
        with patch.object(gestion_app, "load_data", return_value={"billing_lines": []}):
            response = self.client.post("/api/billing/reschedule-rejected-debit", json={
                "collectionDate": "2099-10-20", "items": [],
            })
        self.assertEqual(response.status_code, 400)
        self.assertIn("Sélectionnez", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
