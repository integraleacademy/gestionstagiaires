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
        self.assertIn("Nouveau prélèvement en cours de transmission", template)
        self.assertIn("Nouveau prélèvement mis en place avec succès", template)
        self.assertIn("Nouveau prélèvement suite à rejet", template)
        self.assertIn("Rejet traité", template)
        self.assertIn("finance-line--retry", template)
        self.assertIn("logicalInstallmentsForLine", template)
        self.assertIn("Plan contractuel", template)
        self.assertIn("Tentative précédente · non comptabilisée", template)
        self.assertIn("montantTotalEcheancier", template)

    def test_endpoint_keeps_rejection_as_treated_and_adds_a_distinct_retry(self):
        direct_alias_installment = {
            "amount": 325.5,
            "date": "2026-08-05",
            "due_date": "2026-08-05",
            "status": "failed",
            "failureReason": "insufficient_funds",
            "qonto_direct_debit_subscription_id": "SUB-OLD",
        }
        canonical_installment = dict(direct_alias_installment)
        line = {
            "id": "line-1",
            "traineeId": "trainee-1",
            "sessionId": "session-1",
            "traineeFirstName": "Anthony",
            "traineeLastName": "Urbanik",
            "paymentMode": "sepa_direct_debit",
            "qontoClientId": "client-1",
            "qonto_direct_debit_mandate_id": "mandate-1",
            "qonto_mandate_status": "active",
            # Reproduce the production bug: JSON loading creates two distinct
            # list objects for the legacy alias and the canonical SEPA plan.
            "directDebitInstallments": [direct_alias_installment],
            "sepa_payment_plan": {"installments": [canonical_installment]},
        }
        rejection_notification = {
            "id": "notification-1",
            "label": "🔴 Prélèvement rejeté — Anthony Urbanik — 325,50 €",
            "done": False,
            "meta": {
                "kind": "qonto_direct_debit_rejected",
                "trainee_id": "trainee-1",
                "session_id": "session-1",
                "scheduled_date": "2026-08-05",
                "amount": 325.5,
            },
        }
        data = {"billing_lines": [line], "notifications_admin": [rejection_notification]}

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
                "subscriptionId": "SUB-OLD",
                "dueDate": "2026-08-05",
                "collectionDate": "2099-09-15",
            })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        payload = create_mock.call_args.args[0]
        self.assertEqual(payload["initial_collection_date"], "2099-09-15")
        self.assertEqual(payload["amount"], {"value": "325.50", "currency": "EUR"})
        installments = line["directDebitInstallments"]
        self.assertIs(installments, line["sepa_payment_plan"]["installments"])
        self.assertEqual(len(installments), 2)
        original, retry = installments
        self.assertEqual(original["status"], "failed")
        self.assertEqual(original["qonto_direct_debit_subscription_id"], "SUB-OLD")
        self.assertTrue(original["rejection_treated"])
        self.assertTrue(original["excluded_from_schedule_totals"])
        self.assertEqual(original["replaced_by_direct_debit_subscription_id"], "SUB-NEW")
        self.assertEqual(original["reprogramming_history"][0]["qonto_direct_debit_subscription_id"], "SUB-OLD")
        self.assertTrue(retry["is_rejection_retry"])
        self.assertEqual(retry["status"], "scheduled")
        self.assertEqual(retry["date"], "2099-09-15")
        self.assertEqual(retry["qonto_direct_debit_subscription_id"], "SUB-NEW")
        self.assertEqual(line["sepa_payment_plan"]["total_due"], 325.5)
        self.assertEqual(line["qontoPaymentGlobalStatus"], "Rejet traité")
        self.assertEqual(response.get_json()["subscriptionIds"], ["SUB-NEW"])
        self.assertTrue(rejection_notification["done"])
        self.assertIn("Rejet traité", rejection_notification["label"])
        self.assertEqual(rejection_notification["meta"]["rejection_status"], "treated")
        self.assertEqual(rejection_notification["meta"]["replacement_subscription_id"], "SUB-NEW")

    def test_endpoint_reschedules_multiple_debits_with_custom_amounts(self):
        installments = [
            {"amount": 100, "date": "2026-07-01", "status": "failed", "qonto_direct_debit_subscription_id": "OLD-1"},
            {"amount": 200, "date": "2026-08-01", "status": "rejected", "qonto_direct_debit_subscription_id": "OLD-2"},
        ]
        line = {
            "id": "line-1", "qontoClientId": "client-1",
            "qonto_direct_debit_mandate_id": "mandate-1",
            "qonto_mandate_status": "active",
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
        self.assertEqual([item["amount"] for item in installments[:2]], [100, 200])
        self.assertEqual([item["amount"] for item in installments[2:]], [75.25, 150.0])
        self.assertTrue(all(item["rejection_treated"] for item in installments[:2]))
        self.assertTrue(all(item["is_rejection_retry"] for item in installments[2:]))
        self.assertEqual(installments[0]["reprogramming_history"][0]["amount"], 100)
        self.assertEqual(line["sepa_payment_plan"]["total_due"], 225.25)
        self.assertEqual(line["sepa_payment_plan"]["remaining_installments"], 2)

    def test_endpoint_does_not_reprogram_an_already_treated_rejection(self):
        installment = {
            "amount": 100, "date": "2026-07-01", "status": "failed",
            "rejection_treated": True, "rejection_treated_at": "2026-08-11T08:00:00Z",
            "qonto_direct_debit_subscription_id": "OLD-1",
        }
        line = {
            "id": "line-1", "qontoClientId": "client-1",
            "qonto_direct_debit_mandate_id": "mandate-1",
            "directDebitInstallments": [installment],
        }
        with patch.object(gestion_app, "load_data", return_value={"billing_lines": [line]}), \
             patch.object(gestion_app, "_billing_lines", return_value=[line]), \
             patch.object(gestion_app, "create_qonto_direct_debit_subscription") as create_mock:
            response = self.client.post("/api/billing/reschedule-rejected-debit", json={
                "lineId": "line-1", "installmentIndex": 0, "collectionDate": "2099-10-20",
            })

        self.assertEqual(response.status_code, 400)
        self.assertIn("déjà été traité", response.get_json()["error"])
        create_mock.assert_not_called()

    def test_endpoint_rejects_an_empty_batch(self):
        with patch.object(gestion_app, "load_data", return_value={"billing_lines": []}):
            response = self.client.post("/api/billing/reschedule-rejected-debit", json={
                "collectionDate": "2099-10-20", "items": [],
            })
        self.assertEqual(response.status_code, 400)
        self.assertIn("Sélectionnez", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
