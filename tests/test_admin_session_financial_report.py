import datetime
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from jinja2 import ChoiceLoader, DictLoader

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

    def test_report_displays_payment_details_and_keeps_cpf_separate(self):
        template = Path("templates/admin_session_financial_report.html").read_text(encoding="utf-8")

        self.assertIn('role="progressbar"', template)
        self.assertIn("invoice.payment_percentage", template)
        self.assertIn("Encaissements hors CPF", template)
        self.assertIn('class="financial-card__cpf-logo" src="/templates/cpf.jpg" alt="Logo CPF"', template)
        self.assertIn("personnel et autres financeurs", template)
        self.assertIn("Le CPF est suivi séparément", template)
        self.assertNotIn("Reste à encaisser CPF", template)

    def _render_report(self, report):
        # Exercise the real page independently of the shared navigation shell.
        environment = gestion_app.app.jinja_env.overlay(loader=ChoiceLoader([
            DictLoader({"base.html": "{% block content %}{% endblock %}"}),
            gestion_app.app.jinja_env.loader,
        ]))
        with gestion_app.app.test_request_context():
            return environment.get_template("admin_session_financial_report.html").render(
                session={**self.session, "date_end": "2026-10-01"}, report=report,
            )

    @staticmethod
    def _card_text(html, modifier):
        return re.search(
            rf'<article class="financial-card [^"]*{modifier}[^"]*">(.*?)</article>',
            html, re.DOTALL,
        ).group(1)

    def test_render_external_unknown_is_not_reported_as_an_unpaid_balance(self):
        lines = [{"traineeId": "trainee-1", "invoiceStatus": "external_generated", "amount": 600}]
        with patch.object(gestion_app, "_billing_lines_for_session", return_value=lines):
            report = gestion_app._session_financial_report({}, self.session)
        html = self._render_report(report)

        # The personal 600 remains unverified, while the other-financier 200 is
        # still a known balance. The CPF 1000 must not enter either KPI.
        self.assertIn("200,00 €", self._card_text(html, "financial-card--balance"))
        self.assertIn("600,00 € de solde restent à vérifier", html)
        self.assertIn("Paiement à vérifier", html)
        self.assertIn("Facture existante · ne pas recréer", html)
        self.assertNotIn("Non payé", html)
        self.assertNotIn("Générer facture", html)

    def test_render_paid_external_invoice_shows_a_settled_personal_balance(self):
        self.session["trainees"][0]["other_amount"] = 0
        self.session["trainees"][0]["training_price"] = 1600
        lines = [{
            "traineeId": "trainee-1", "invoiceStatus": "external_generated", "amount": 600,
            "amountPaid": 600,
        }]
        with patch.object(gestion_app, "_billing_lines_for_session", return_value=lines):
            report = gestion_app._session_financial_report({}, self.session)
        html = self._render_report(report)

        self.assertIn("600,00 €", self._card_text(html, "financial-card--paid"))
        self.assertIn("0,00 €", self._card_text(html, "financial-card--balance"))
        summary = re.search(r'<tr class="financial-summary-row".*?</tr>', html, re.DOTALL).group(0)
        self.assertIn("Soldé hors CPF", summary)
        self.assertIn("Créée ailleurs", summary)
        self.assertNotIn("Paiement à vérifier", summary)
        self.assertIn('class="financial-details-row" id="financial-detail-1" hidden', html)

    def test_render_cpf_only_dossier_does_not_claim_a_local_invoice_is_due(self):
        self.session["trainees"][0].update({
            "cpf_amount": 1800, "personal_amount": 0, "other_amount": 0,
        })
        with patch.object(gestion_app, "_billing_lines_for_session", return_value=[]):
            report = gestion_app._session_financial_report({}, self.session)
        html = self._render_report(report)

        self.assertIn("0,00 €", self._card_text(html, "financial-card--balance"))
        summary = re.search(r'<tr class="financial-summary-row".*?</tr>', html, re.DOTALL).group(0)
        self.assertIn("Suivi CPF séparé", summary)
        self.assertIn("Aucun montant attendu ici", summary)
        self.assertNotIn("À facturer", summary)

    def test_cpf_summary_uses_wedof_payments_and_keeps_unknown_amounts_separate(self):
        self.session["trainees"] = [
            {"id": "paid", "first_name": "Alice", "last_name": "Martin", "cpf_amount": 1000},
            {"id": "pending", "first_name": "Benoit", "last_name": "Petit", "cpf_amount": 700},
            {"id": "unknown", "first_name": "Camille", "last_name": "Robert", "cpf_amount": 400},
        ]
        data = {"sessions": [self.session], "wedof_links": [
            {"active": True, "session_id": "session-1", "trainee_id": "paid", "external_id": "CPF-1",
             "cpf_snapshot": {"invoice_number": "F-1", "invoice_status": "paid"}},
            {"active": True, "session_id": "session-1", "trainee_id": "pending", "external_id": "CPF-2",
             "cpf_snapshot": {"invoice_number": "F-2", "invoice_status": "unpaid"}},
            {"active": True, "session_id": "session-1", "trainee_id": "unknown", "external_id": "CPF-3",
             "cpf_snapshot": {"invoice_number": "F-3", "billing_state": "billed"}},
        ]}
        with patch.object(gestion_app, "_billing_lines_for_session", return_value=[]):
            report = gestion_app._session_financial_report(data, self.session)

        cpf = report["cpf_payments"]
        self.assertEqual(cpf["totals"], {"paid": 1000, "remaining": 700, "unverified": 400})
        self.assertEqual([row["status"] for row in cpf["rows"]], ["paid", "pending", "unknown"])
        html = self._render_report(report)
        block = re.search(r'<details class="financial-funding">.*?</details>', html, re.DOTALL).group(0)
        self.assertIn("1 000,00 € reçus", block)
        self.assertIn("700,00 € restant à recevoir", block)
        self.assertIn("Paiement à vérifier", block)
        for previous_label in ("Prix des formations", "Financement personnel prévu", "Autres financeurs prévus"):
            self.assertNotIn(previous_label, block)

    def test_cpf_partial_payment_is_counted_once_and_does_not_change_personal_totals(self):
        lines = [
            {"traineeId": "trainee-1", "sessionId": "session-1", "financingType": "CPF",
             "qontoInvoiceId": "cpf-invoice", "qontoInvoiceNumber": "CPF-F-1", "invoiceStatus": "sent",
             "paymentStatus": "partially_paid", "amount": 1000,
             "qonto_total_amount_cents": 100000, "qonto_amount_paid_cents": 25000},
            {"traineeId": "trainee-1", "sessionId": "session-1", "financingType": "PERSONNEL",
             "invoiceStatus": "external_generated", "amount": 600, "amountPaid": 600},
        ]
        data = {"sessions": [self.session], "wedof_links": [
            {"active": True, "session_id": "session-1", "trainee_id": "trainee-1", "external_id": "CPF-1",
             "cpf_snapshot": {"invoice_number": "CPF-F-1", "invoice_status": "sent"}},
            {"active": True, "session_id": "other-session", "trainee_id": "trainee-1", "external_id": "CPF-OTHER",
             "cpf_snapshot": {"invoice_number": "F-OTHER", "invoice_status": "paid"}},
        ]}
        with patch.object(gestion_app, "_billing_lines_for_session", return_value=lines):
            report = gestion_app._session_financial_report(data, self.session)
        self.assertEqual(report["cpf_payments"]["totals"], {"paid": 250, "remaining": 750, "unverified": 0})
        self.assertEqual(report["cpf_payments"]["rows"][0]["status"], "partial")
        self.assertEqual(report["totals"]["personal_paid"], 600)
        self.assertEqual(report["totals"]["remaining"], 0)
        self.assertIn("600,00 €", self._card_text(self._render_report(report), "financial-card--paid"))

    def test_cpf_missing_cancelled_or_unverified_payments_do_not_become_unpaid(self):
        for extra in ({}, {"invoiceStatus": "cancelled"}, {"paymentStatus": "control"},
                      {"paymentStatus": "paid", "qonto_amount_paid_cents": None}):
            with self.subTest(extra=extra):
                line = {"traineeId": "trainee-1", "sessionId": "session-1", "financingType": "CPF",
                        "qontoInvoiceId": "cpf-1", "invoiceStatus": "sent", "paymentStatus": "unknown",
                        "amount": 1000, **extra}
                with patch.object(gestion_app, "_billing_lines_for_session", return_value=[line]):
                    report = gestion_app._session_financial_report({}, self.session)
                self.assertEqual(report["cpf_payments"]["totals"], {"paid": 0, "remaining": 0, "unverified": 1000})
                self.assertFalse(report["cpf_payments"]["rows"][0]["known"])

    def test_cpf_summary_ignores_inactive_links_and_cancelled_registrations(self):
        self.session["trainees"].append({
            "id": "cancelled", "first_name": "Annule", "last_name": "Test", "cpf_amount": 900,
            "registration_cancelled": True,
        })
        data = {"sessions": [self.session], "wedof_links": [
            {"active": False, "session_id": "session-1", "trainee_id": "trainee-1",
             "cpf_snapshot": {"invoice_number": "F-INACTIVE", "invoice_status": "paid"}},
        ]}
        with patch.object(gestion_app, "_billing_lines_for_session", return_value=[]):
            cpf = gestion_app._session_financial_report(data, self.session)["cpf_payments"]
        self.assertEqual(len(cpf["rows"]), 1)
        self.assertEqual(cpf["totals"], {"paid": 0, "remaining": 0, "unverified": 1000})

    def test_cpf_summary_is_read_only_and_empty_without_cpf(self):
        self.session["trainees"][0]["cpf_amount"] = 0
        data = {"sessions": [self.session]}
        with patch.object(gestion_app, "save_data", side_effect=AssertionError("No writes")), \
             patch.object(gestion_app.WedofClient, "get_registration_folder_interactive", side_effect=AssertionError("No remote refresh")), \
             patch.object(gestion_app, "find_qonto_invoice_by_number", side_effect=AssertionError("No Qonto request")):
            report = gestion_app._session_financial_report(data, self.session)
        self.assertEqual(report["cpf_payments"]["rows"], [])
        self.assertIn("Aucun financement CPF dans cette session.", self._render_report(report))

    def test_same_cpf_invoice_cannot_be_counted_for_two_trainees(self):
        self.session["trainees"].append({
            "id": "trainee-2", "first_name": "Paul", "last_name": "Martin", "cpf_amount": 1000,
        })
        lines = [{
            "traineeId": trainee_id, "sessionId": "session-1", "financingType": "CPF",
            "qontoInvoiceId": "duplicate", "invoiceStatus": "paid", "paymentStatus": "paid",
            "amount": 1000, "qonto_amount_paid_cents": 100000,
        } for trainee_id in ("trainee-1", "trainee-2")]
        with patch.object(gestion_app, "_billing_lines_for_session", return_value=lines):
            cpf = gestion_app._session_financial_report({}, self.session)["cpf_payments"]
        self.assertEqual(cpf["totals"], {"paid": 0, "remaining": 0, "unverified": 2000})

    def test_next_direct_debit_date_is_the_first_future_actionable_installment(self):
        line = {
            "directDebitInstallments": [
                {"date": "2026-08-20", "status": "scheduled"},
                {"date": "2026-09-01", "status": "completed"},
                {"due_date": "2026-09-12", "status": "scheduled"},
                {"date": "2026-10-01", "status": "pending"},
            ]
        }

        self.assertEqual(
            gestion_app._next_direct_debit_date(line, today=datetime.date(2026, 8, 26)),
            "2026-09-12",
        )

    def test_next_direct_debit_date_ignores_terminal_invalid_and_past_entries(self):
        line = {
            "directDebitInstallments": [
                {"date": "not-a-date", "status": "scheduled"},
                {"date": "2026-08-25", "status": "pending"},
                {"date": "2026-09-02", "status": "returned"},
                {"date": "2026-09-03", "status": "cancelled"},
            ]
        }

        self.assertIsNone(
            gestion_app._next_direct_debit_date(line, today=datetime.date(2026, 8, 26))
        )

    def test_next_direct_debit_date_uses_current_reprogrammed_attempt(self):
        line = {
            "directDebitInstallments": [
                {
                    "index": 1,
                    "date": "2026-09-01",
                    "status": "scheduled",
                    "created_at": "2026-08-01T08:00:00Z",
                },
                {
                    "index": 1,
                    "schedule_index": 1,
                    "date": "2026-09-10",
                    "status": "scheduled",
                    "is_rejection_retry": True,
                    "created_at": "2026-08-02T08:00:00Z",
                },
            ]
        }

        self.assertEqual(
            gestion_app._next_direct_debit_date(line, today=datetime.date(2026, 8, 26)),
            "2026-09-10",
        )
        self.assertNotIn("sepa_payment_plan", line)

    def test_next_direct_debit_date_supports_canonical_plan_alias(self):
        line = {
            "sepa_payment_plan": {
                "installments": [
                    {"due_date": "2026-09-12", "status": "scheduled"},
                ]
            }
        }

        self.assertEqual(
            gestion_app._next_direct_debit_date(line, today=datetime.date(2026, 8, 26)),
            "2026-09-12",
        )

    def test_report_exposes_and_renders_next_direct_debit_date(self):
        lines = [{
            "traineeId": "trainee-1",
            "qontoInvoiceId": "invoice-1",
            "invoiceStatus": "sent",
            "amount": 600,
            "qonto_total_amount_cents": 60000,
            "qonto_amount_paid_cents": 25000,
            "qonto_remaining_amount_cents": 35000,
            "directDebitInstallments": [
                {"date": "2099-09-12", "status": "scheduled"},
            ],
        }]
        with patch.object(gestion_app, "_billing_lines_for_session", return_value=lines):
            invoice = gestion_app._session_financial_report({}, self.session)["rows"][0]["invoices"][0]

        self.assertEqual(invoice["next_direct_debit_date"], "2099-09-12")
        template = Path("templates/admin_session_financial_report.html").read_text(encoding="utf-8")
        self.assertIn("Prochain prélèvement prévu le", template)
        self.assertIn("invoice.next_direct_debit_date", template)


if __name__ == "__main__":
    unittest.main()
