import unittest
from pathlib import Path
from unittest.mock import patch

import app as gestion_app


class AdminTraineeCpfQontoInvoiceTests(unittest.TestCase):
    def _data(self, *, status="finalized", paid=0, paid_at=""):
        return {
            "sessions": [{
                "id": "S-CPF",
                "name": "Session APS",
                "training_type": "APS",
                "date_start": "2026-09-01",
                "date_end": "2026-09-30",
                "trainees": [{
                    "id": "T-CPF",
                    "first_name": "Alice",
                    "last_name": "Martin",
                    "cpf_amount": 3050,
                    "personal_amount": 1150,
                    "qonto_invoice": {
                        "qonto_invoice_id": "inv_cpf_3050",
                        "qonto_invoice_number": "F-CPF-2026-42",
                        "qonto_invoice_status": status,
                        "qonto_invoice_amount_paid": paid,
                        "qonto_invoice_paid_at": paid_at,
                        "qonto_invoice_url": "https://qonto.example/inv_cpf_3050",
                        "client_name": gestion_app.CPF_QONTO_CLIENT_NAME,
                        "amount_ttc": 3050,
                        "created_at": "2026-08-12T09:30:00Z",
                    },
                }],
            }],
            "billing_lines": [],
        }

    def test_existing_wedof_qonto_cpf_invoice_is_exposed_as_paid(self):
        data = self._data(status="paid", paid=3050, paid_at="2026-08-13T10:15:00Z")

        lines = gestion_app._billing_lines(data)
        cpf_line = next(line for line in lines if line["financingType"] == "CPF")

        self.assertEqual(cpf_line["qontoInvoiceId"], "inv_cpf_3050")
        self.assertEqual(cpf_line["qontoInvoiceNumber"], "F-CPF-2026-42")
        self.assertEqual(cpf_line["qonto_invoice"]["total_amount_cents"], 305000)
        self.assertEqual(cpf_line["qonto_invoice"]["paid_amount_cents"], 305000)
        self.assertEqual(cpf_line["qonto_invoice"]["payment_status"], "paid")
        self.assertEqual(cpf_line["paidAt"], "2026-08-13T10:15:00Z")

        summary = gestion_app.calculate_trainee_financial_summary(
            data["sessions"][0]["trainees"][0], lines
        )
        cpf_bucket = summary["by_financer"]["CPF"]
        self.assertTrue(cpf_bucket["qonto_tracked"])
        self.assertEqual(cpf_bucket["invoiced_amount_cents"], 305000)
        self.assertEqual(cpf_bucket["paid_amount_cents"], 305000)
        self.assertEqual(cpf_bucket["remaining_amount_cents"], 0)
        self.assertEqual(cpf_bucket["payment_status"], "paid")
        self.assertEqual(summary["cpf_invoice_entries"][0]["invoice_id"], "inv_cpf_3050")
        # CPF visibility must not inflate the platform-collected personal totals.
        self.assertEqual(summary["planned_total_cents"], 115000)
        self.assertEqual(summary["paid_total_cents"], 0)

    def test_cpf_line_is_not_created_without_an_existing_invoice(self):
        data = self._data()
        trainee = data["sessions"][0]["trainees"][0]
        trainee.pop("qonto_invoice")
        trainee["personal_amount"] = 0

        self.assertEqual(gestion_app._billing_lines(data), [])

    def test_personal_legacy_invoice_is_not_mistaken_for_cpf(self):
        data = self._data()
        trainee = data["sessions"][0]["trainees"][0]
        trainee["cpf_amount"] = 1150
        trainee["qonto_invoice"].update({
            "client_name": "Alice Martin",
            "amount_ttc": 1150,
        })

        lines = gestion_app._billing_lines(data)

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["financingType"], "PERSONNEL")
        self.assertEqual(lines[0]["qontoInvoiceId"], "inv_cpf_3050")

    def test_trainee_endpoint_refreshes_cpf_payment_from_qonto(self):
        data = self._data()
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
            flask_session["admin_role"] = "admin"

        remote_invoice = {
            "client_invoice": {
                "id": "inv_cpf_3050",
                "number": "F-CPF-2026-42",
                "status": "paid",
                "total_amount": {"value": "3050.00"},
                "amount_paid": {"value": "3050.00"},
                "paid_at": "2026-08-13T10:15:00Z",
            }
        }
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data") as save_data, \
             patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "get_qonto_invoice", return_value=remote_invoice):
            response = client.get("/api/billing/trainee/T-CPF/session/S-CPF")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        cpf_line = next(line for line in payload["lines"] if line["financingType"] == "CPF")
        cpf_bucket = payload["financial_summary"]["by_financer"]["CPF"]
        self.assertEqual(cpf_line["qonto_invoice"]["payment_status"], "paid")
        self.assertEqual(cpf_line["qonto_invoice"]["paid_amount_cents"], 305000)
        self.assertEqual(cpf_line["paidAt"], "2026-08-13T10:15:00Z")
        self.assertEqual(cpf_bucket["payment_status"], "paid")
        self.assertEqual(cpf_bucket["remaining_amount_cents"], 0)
        save_data.assert_called_once_with(data)

    def test_template_shows_cpf_invoice_and_keeps_it_read_only(self):
        template = (Path(__file__).parents[1] / "templates" / "admin_trainee.html").read_text()

        self.assertIn("Visualiser la facture", template)
        self.assertIn("Facture payée", template)
        self.assertIn("Payée le", template)
        self.assertIn("qonto_tracked", template)
        self.assertIn("!isCpfQontoLine(line)&&!lineHasGeneratedInvoice(line)", template)
        self.assertIn("const cpfTrackingOnly = isCpfQontoLine(l);", template)


if __name__ == "__main__":
    unittest.main()
