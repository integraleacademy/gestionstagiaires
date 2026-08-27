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
                    "status": "scheduled",
                    "created_at": "2098-12-01T08:00:00Z",
                },
                {
                    "index": 1,
                    "schedule_index": 1,
                    "date": "2099-01-12",
                    "status": "scheduled",
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
                    {"due_date": "2026-08-01", "status": "scheduled"},
                    {"due_date": "2099-02-01", "status": "paid"},
                    {"due_date": "invalid", "status": "scheduled"},
                ]
            },
        }

        self.assertIsNone(
            gestion_app._next_direct_debit_date(
                line, today=datetime.date(2026, 8, 27)
            )
        )

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
