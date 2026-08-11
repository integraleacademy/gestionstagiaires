import unittest
from pathlib import Path
from unittest.mock import patch

import app as gestion_app


class AdminSessionFinancialReportTests(unittest.TestCase):
    def setUp(self):
        self.session = {
            "id": "session-1",
            "name": "APS Septembre",
            "training_type": "APS",
            "date_start": "2026-09-01",
            "trainees": [
                {
                    "id": "trainee-1",
                    "last_name": "dupont",
                    "first_name": "lea",
                    "training_price": 1800,
                    "cpf_amount": 1000,
                    "personal_amount": 600,
                    "other_amount": 200,
                }
            ],
        }

    def test_report_rolls_up_funding_gap_and_known_payment(self):
        lines = [{
            "traineeId": "trainee-1",
            "qontoInvoiceId": "invoice-1",
            "qontoInvoiceNumber": "FAC-2026-42",
            "invoiceStatus": "sent",
            "amount": 600,
            "qonto_total_amount_cents": 60000,
            "qonto_amount_paid_cents": 25000,
            "qonto_remaining_amount_cents": 35000,
            "qonto_payment_status": "partially_paid",
        }]
        with patch.object(gestion_app, "_billing_lines_for_session", return_value=lines):
            report = gestion_app._session_financial_report({}, self.session)

        row = report["rows"][0]
        self.assertEqual((row["cpf"], row["personal"], row["other"], row["funding"]), (1000, 600, 200, 1800))
        self.assertEqual(row["gap"], 0)
        self.assertEqual(row["paid"], 250)
        self.assertEqual(report["totals"]["paid"], 250)
        self.assertEqual(report["totals"]["remaining"], 350)
        self.assertEqual(report["totals"]["cpf_remaining"], 1000)
        self.assertEqual(report["totals"]["other_remaining"], 200)
        self.assertEqual(row["invoices"][0]["number"], "FAC-2026-42")
        self.assertEqual(row["invoices"][0]["payment_percentage"], 41.7)

    def test_external_invoice_payment_is_explicitly_unknown(self):
        lines = [{
            "traineeId": "trainee-1",
            "invoiceStatus": "external_generated",
            "amount": 600,
        }]
        with patch.object(gestion_app, "_billing_lines_for_session", return_value=lines):
            report = gestion_app._session_financial_report({}, self.session)

        self.assertTrue(report["rows"][0]["payment_unknown"])
        self.assertTrue(report["rows"][0]["invoices"][0]["external"])
        self.assertEqual(report["unknown_payment_count"], 1)

    def test_external_invoice_keeps_a_known_payment_amount(self):
        lines = [{
            "traineeId": "trainee-1", "invoiceStatus": "external_generated", "amount": 600,
            "paid_amount_cents": 60000, "total_amount_cents": 60000, "remaining_amount_cents": 0,
        }]
        with patch.object(gestion_app, "_billing_lines_for_session", return_value=lines):
            report = gestion_app._session_financial_report({}, self.session)

        self.assertTrue(report["rows"][0]["invoices"][0]["payment_known"])
        self.assertEqual(report["rows"][0]["paid"], 600)
        self.assertEqual(report["unknown_payment_count"], 0)

    def test_external_invoice_uses_manual_payment_from_trainee_financial_summary(self):
        lines = [{
            "traineeId": "trainee-1", "invoiceStatus": "external_generated", "amount": 600,
            "amountPaid": 600,
        }]
        with patch.object(gestion_app, "_billing_lines_for_session", return_value=lines):
            report = gestion_app._session_financial_report({}, self.session)

        invoice = report["rows"][0]["invoices"][0]
        self.assertTrue(invoice["payment_known"])
        self.assertEqual(invoice["paid"], 600)
        self.assertEqual(invoice["payment_status"], "paid")
        self.assertEqual(report["unknown_payment_count"], 0)

    def test_cash_payment_without_invoice_is_visible_in_report(self):
        trainee = self.session["trainees"][0]
        trainee.update({
            "cash_payment_enabled": True,
            "cash_payment_amount": 600,
            "cash_payment_settled": True,
        })
        with patch.object(gestion_app, "_billing_lines_for_session", return_value=[]):
            report = gestion_app._session_financial_report({}, self.session)

        row = report["rows"][0]
        self.assertEqual(row["paid"], 600)
        self.assertTrue(row["invoices"][0]["payment_known"])
        self.assertEqual(row["invoices"][0]["payment_status"], "partially_paid")

    def test_report_uses_the_full_available_width(self):
        template = Path("templates/admin_session_financial_report.html").read_text(encoding="utf-8")

        self.assertIn("body.endpoint-admin-session-financial-report > .container", template)
        self.assertIn("body.endpoint-admin-session-financial-report .app-shell", template)
        self.assertIn("width:100%;max-width:none;box-sizing:border-box", template)

    def test_report_exposes_trainee_link_and_cash_payment_details(self):
        trainee = self.session["trainees"][0]
        trainee.update({"cash_payment_enabled": True, "cash_payment_amount": "600"})

        with patch.object(gestion_app, "_billing_lines_for_session", return_value=[]):
            row = gestion_app._session_financial_report({}, self.session)["rows"][0]

        self.assertEqual(row["trainee_id"], "trainee-1")
        self.assertTrue(row["cash_payment_enabled"])
        self.assertEqual(row["cash_payment_amount"], 600)
        self.assertFalse(row["cash_payment_settled"])

        template = Path("templates/admin_session_financial_report.html").read_text(encoding="utf-8")
        self.assertIn("admin_trainee_page", template)
        self.assertIn("À payer en espèces", template)

    def test_report_displays_payment_progress_and_separate_remaining_kpis(self):
        template = Path("templates/admin_session_financial_report.html").read_text(encoding="utf-8")

        self.assertIn('role="progressbar"', template)
        self.assertIn("invoice.payment_percentage", template)
        self.assertIn("Reste à encaisser CPF", template)
        self.assertIn('class="financial-card__cpf-logo" src="/templates/cpf.jpg" alt="Logo CPF"', template)
        self.assertIn("Reste à encaisser autres", template)
        self.assertIn("Financement personnel uniquement", template)


if __name__ == "__main__":
    unittest.main()
