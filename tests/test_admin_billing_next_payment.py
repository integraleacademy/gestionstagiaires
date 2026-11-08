import datetime
import unittest
from pathlib import Path
from unittest.mock import patch

import app as gestion_app


class AdminBillingNextPaymentTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def test_billing_api_exposes_current_reprogrammed_next_debit(self):
        line = {
            "id": "billing-line-1",
            "qontoInvoiceId": "invoice-1",
            "invoiceStatus": "sent",
            "paymentStatus": "unpaid",
            "amount": 1000,
            "directDebitInstallments": [
                {
                    "index": 1,
                    "date": "2099-01-05",
                    "status": "cancelled",
                    "qonto_direct_debit_subscription_id": "original-subscription",
                    "created_at": "2098-12-01T08:00:00Z",
                },
                {
                    "index": 1,
                    "schedule_index": 1,
                    "date": "2099-01-12",
                    "status": "scheduled",
                    "qonto_direct_debit_subscription_id": "retry-subscription",
                    "is_rejection_retry": True,
                    "created_at": "2098-12-02T08:00:00Z",
                },
            ],
        }

        with patch.object(gestion_app, "load_data", return_value={}), \
             patch.object(gestion_app, "_billing_lines", return_value=[line]), \
             patch.object(gestion_app, "_repair_logged_qonto_rejection_retries"), \
             patch.object(gestion_app, "_cpf_wedof_invoice_lines", return_value=[]):
            response = self.client.get("/api/admin/billing-lines")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["lines"][0]["nextDirectDebitDate"], "2099-01-12")
        self.assertNotIn("nextDirectDebitDate", line)

    def test_billing_api_ignores_terminal_and_past_installments(self):
        line = {
            "id": "billing-line-2",
            "sepa_payment_plan": {
                "installments": [
                    {"due_date": "2026-08-01", "status": "scheduled", "qonto_direct_debit_subscription_id": "old"},
                    {"due_date": "2099-02-01", "status": "paid", "qonto_direct_debit_subscription_id": "paid"},
                    {"due_date": "invalid", "status": "scheduled", "qonto_direct_debit_subscription_id": "invalid-date"},
                ]
            },
        }

        self.assertIsNone(
            gestion_app._next_direct_debit_date(
                line, today=datetime.date(2026, 8, 27)
            )
        )

    def test_contractual_schedule_and_signed_mandate_do_not_prove_a_future_debit(self):
        line = {
            "qonto_direct_debit_mandate_id": "signed-mandate",
            "qonto_mandate_status": "active",
            "directDebitInstallments": [{"date": "2099-01-10", "status": "scheduled"}],
        }
        self.assertIsNone(gestion_app._next_direct_debit_date(line))

    def test_unconfirmed_or_inactive_qonto_rows_are_not_future_debits(self):
        base = {
            "date": "2099-01-10", "status": "scheduled",
            "qonto_direct_debit_subscription_id": "subscription",
        }
        for extra in (
            {"tracking_pending_qonto": True},
            {"status": "pending_mandate_signature"},
            {"status": "unknown"},
            {"qonto_subscription_status": "canceled"},
            {"qonto_subscription_status": "pending_mandate_signature"},
            {"qonto_collection_status_raw": "returned"},
        ):
            with self.subTest(extra=extra):
                line = {"directDebitInstallments": [dict(base, **extra)]}
                self.assertIsNone(gestion_app._next_direct_debit_date(line))

    def test_real_collection_due_today_is_included_without_mutating_the_line(self):
        line = {"directDebitInstallments": [{
            "due_date": "2026-11-08", "status": "pending",
            "qonto_direct_debit_collection_id": "collection",
        }]}
        self.assertEqual(
            gestion_app._next_direct_debit_date(line, today=datetime.date(2026, 11, 8)),
            "2026-11-08",
        )
        self.assertNotIn("sepa_payment_plan", line)

    def test_pending_local_edit_keeps_the_original_future_bank_date(self):
        line = {"directDebitInstallments": [{
            "date": "2099-12-20", "status": "scheduled",
            "qonto_direct_debit_subscription_id": "subscription",
            "tracking_pending_qonto": True, "qonto_original_due_date": "2099-12-10",
        }]}
        self.assertEqual(gestion_app._next_direct_debit_date(line), "2099-12-10")

    def test_local_removal_does_not_cancel_a_real_future_bank_debit(self):
        line = {"directDebitInstallments": [{
            "date": "2099-12-10", "status": "scheduled",
            "qonto_direct_debit_subscription_id": "subscription",
            "tracking_removed_at": "2026-11-08T10:00:00Z",
            "excluded_from_schedule_totals": True,
        }]}
        self.assertEqual(gestion_app._next_direct_debit_date(line), "2099-12-10")

    def test_paid_attempt_does_not_hide_another_future_bank_order_in_same_slot(self):
        line = {"directDebitInstallments": [
            {"index": 1, "date": "2026-11-01", "status": "completed",
             "qonto_direct_debit_subscription_id": "paid-subscription"},
            {"index": 1, "date": "2099-12-10", "status": "scheduled",
             "qonto_direct_debit_subscription_id": "still-active-subscription"},
        ]}
        self.assertEqual(gestion_app._next_direct_debit_date(line), "2099-12-10")

    def test_real_returned_collection_supersedes_scheduled_subscription_copy(self):
        line = {"directDebitInstallments": [
            {"date": "2099-12-10", "status": "scheduled",
             "qonto_direct_debit_subscription_id": "subscription"},
            {"date": "2099-12-10", "status": "scheduled",
             "qonto_direct_debit_subscription_id": "subscription",
             "qonto_direct_debit_collection_id": "returned-collection",
             "qonto_collection_status_raw": "returned"},
        ]}
        self.assertIsNone(gestion_app._next_direct_debit_date(line))

    def test_billing_api_explicitly_exposes_absence_of_confirmed_debit(self):
        line = {"id": "contract-only", "directDebitInstallments": [{
            "date": "2099-01-10", "status": "scheduled",
        }]}
        with patch.object(gestion_app, "load_data", return_value={}), \
             patch.object(gestion_app, "_billing_lines", return_value=[line]), \
             patch.object(gestion_app, "_repair_logged_qonto_rejection_retries"), \
             patch.object(gestion_app, "_cpf_wedof_invoice_lines", return_value=[]):
            response = self.client.get("/api/admin/billing-lines")
        self.assertEqual(response.status_code, 200)
        self.assertIn("nextDirectDebitDate", response.get_json()["lines"][0])
        self.assertIsNone(response.get_json()["lines"][0]["nextDirectDebitDate"])

    def test_billing_template_renders_next_date_under_payment_progress(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "templates"
            / "admin_sessions_billing.html"
        ).read_text(encoding="utf-8")

        self.assertIn("Prochain prélèvement prévu le ${escapeHtml(formatBillingDateFr(nextDebit))}", source)
        self.assertIn("${nextDebitLabel}</div>", source)
        self.assertIn("const nextDebit=!isPaid?nextDirectDebitDate(l):''", source)
        self.assertIn(".payment-progress-next", source)


if __name__ == "__main__":
    unittest.main()
