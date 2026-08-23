import unittest
from pathlib import Path
from unittest.mock import patch

import app as gestion_app


class AdminCpfInvoicesViewTests(unittest.TestCase):
    def _data(self):
        return {
            "sessions": [{
                "id": "S-CPF",
                "name": "Session APS septembre",
                "training_type": "APS",
                "date_start": "2026-09-01",
                "date_end": "2026-09-30",
                "trainees": [{
                    "id": "T-CPF",
                    "first_name": "Alice",
                    "last_name": "Martin",
                    "email": "alice@example.fr",
                    "cpf_amount": 3050,
                }],
            }],
            "billing_lines": [],
            "wedof_links": [{
                "active": True,
                "session_id": "S-CPF",
                "trainee_id": "T-CPF",
                "external_id": "421643740630",
                "cpf_snapshot": {
                    "state": "serviceDoneValidated",
                    "billing_state": "billed",
                    "invoice_number": "FL-2026-374",
                    "synced_at": "2026-08-23T12:00:00Z",
                },
            }],
        }

    def test_wedof_invoice_snapshot_is_exposed_without_remote_request(self):
        data = self._data()
        with patch.object(
            gestion_app.WedofClient,
            "get_registration_folder_interactive",
            side_effect=AssertionError("The global view must use the local cache"),
        ), patch.object(
            gestion_app,
            "find_qonto_invoice_by_number",
            side_effect=AssertionError("The global view must not call Qonto on load"),
        ):
            rows = gestion_app._cpf_wedof_invoice_lines(data, [])

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["qontoInvoiceNumber"], "FL-2026-374")
        self.assertEqual(row["cpfWedofExternalId"], "421643740630")
        self.assertEqual(row["amount"], 3050)
        self.assertEqual(row["traineeFirstName"], "Alice")
        self.assertTrue(row["cpfWedofReferenceOnly"])
        self.assertTrue(row["cpfPaymentUnknown"])
        self.assertIn("421643740630", row["cpfWedofUrl"])

    def test_existing_qonto_line_is_deduplicated_and_enriched_from_wedof(self):
        data = self._data()
        existing = {
            "id": "bill-existing",
            "sessionId": "S-CPF",
            "traineeId": "T-CPF",
            "financingType": "CPF",
            "financeurName": "CPF",
            "amount": 3050,
            "qontoInvoiceId": "inv-cpf-1",
            "qontoInvoiceNumber": "FL-2026-374",
            "invoiceStatus": "paid",
            "paymentStatus": "paid",
        }

        rows = gestion_app._cpf_wedof_invoice_lines(data, [existing])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "bill-existing")
        self.assertEqual(rows[0]["qontoInvoiceId"], "inv-cpf-1")
        self.assertEqual(rows[0]["cpfWedofExternalId"], "421643740630")
        self.assertFalse(rows[0]["cpfWedofReferenceOnly"])

    def test_legacy_wedof_invoice_before_billing_rollout_is_included(self):
        data = self._data()
        data["sessions"][0]["date_start"] = "2025-01-10"
        data["sessions"][0]["date_end"] = "2025-02-10"
        data["wedof_links"] = []
        data["sessions"][0]["trainees"][0]["qonto_invoice"] = {
            "qonto_invoice_id": "inv-legacy-cpf",
            "qonto_invoice_number": "F-CPF-2025-1",
            "qonto_invoice_status": "paid",
            "qonto_invoice_amount_paid": 3050,
            "client_name": gestion_app.CPF_QONTO_CLIENT_NAME,
            "amount_ttc": 3050,
        }

        rows = gestion_app._cpf_wedof_invoice_lines(data, [])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["qontoInvoiceId"], "inv-legacy-cpf")
        self.assertEqual(rows[0]["paymentStatus"], "paid")

    def test_inactive_or_unbilled_wedof_links_are_not_invoices(self):
        data = self._data()
        data["wedof_links"][0].update({"active": False})
        self.assertEqual(gestion_app._cpf_wedof_invoice_lines(data, []), [])

        data["wedof_links"][0] = {
            "active": True,
            "session_id": "S-CPF",
            "trainee_id": "T-CPF",
            "external_id": "not-billed",
            "cpf_snapshot": {"state": "inTraining"},
        }
        self.assertEqual(gestion_app._cpf_wedof_invoice_lines(data, []), [])

    def test_billing_api_returns_the_dedicated_cpf_collection(self):
        data = self._data()
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
            flask_session["admin_role"] = "admin"
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_repair_logged_qonto_rejection_retries", return_value=0):
            response = client.get("/api/admin/billing-lines")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("cpf_invoice_lines", payload)
        self.assertEqual(payload["cpf_invoice_lines"][0]["qontoInvoiceNumber"], "FL-2026-374")

    def test_template_contains_the_dedicated_cpf_view(self):
        template = Path("templates/admin_sessions_billing.html").read_text(encoding="utf-8")
        self.assertIn("Factures CPF", template)
        self.assertIn("data-billing-view=\"cpf\"", template)
        self.assertIn("cpf_invoice_lines", template)
        self.assertIn("Toutes les factures CPF Qonto générées via WEDOF", template)


if __name__ == "__main__":
    unittest.main()
