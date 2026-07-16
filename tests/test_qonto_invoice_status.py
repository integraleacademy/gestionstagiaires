import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import Mock, patch

import app as gestion_app


class QontoInvoiceStatusTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "sessions": [
                {
                    "id": "S1",
                    "trainees": [
                        {
                            "id": "T1",
                            "qonto_invoice": {
                                "qonto_invoice_id": "inv_123",
                                "qonto_invoice_number": "F-001",
                                "qonto_invoice_status": "sent",
                            },
                        }
                    ],
                }
            ]
        }
        self.saved = []

    def test_sync_qonto_invoice_status_updates_payment_fields(self):
        remote = {
            "client_invoice": {
                "id": "inv_123",
                "number": "F-001",
                "status": "paid",
                "paid_at": "2026-06-29T10:15:00Z",
                "amount_paid": {"value": "1200.50", "currency": "EUR"},
            }
        }
        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(gestion_app, "save_data", side_effect=self.saved.append), patch.object(gestion_app, "get_qonto_invoice", return_value=remote):
            invoice = gestion_app.syncQontoInvoiceStatus("inv_123")

        self.assertEqual(invoice["qonto_invoice_status"], "paid")
        self.assertEqual(invoice["qonto_invoice_paid_at"], "2026-06-29T10:15:00Z")
        self.assertEqual(invoice["qonto_invoice_amount_paid"], 1200.50)
        self.assertEqual(len(self.saved), 1)

    def test_qonto_webhook_verifies_signature_and_updates_local_invoice(self):
        secret = "webhook-secret"
        body = {
            "event": "v1/client-invoices.updated",
            "data": {
                "id": "inv_123",
                "status": "paid",
                "paid_at": "2026-06-29T11:30:00Z",
                "amount_paid": "950",
            },
        }
        raw = json.dumps(body).encode("utf-8")
        signature = "sha256=" + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        client = gestion_app.app.test_client()
        with patch.dict(os.environ, {"QONTO_WEBHOOK_SECRET": secret}), patch.object(gestion_app, "load_data", return_value=self.data), patch.object(gestion_app, "save_data", side_effect=self.saved.append):
            response = client.post("/api/qonto/webhooks", data=raw, headers={"Content-Type": "application/json", "X-Qonto-Signature": signature})

        self.assertEqual(response.status_code, 200)
        invoice = self.data["sessions"][0]["trainees"][0]["qonto_invoice"]
        self.assertEqual(invoice["qonto_invoice_status"], "paid")
        self.assertEqual(invoice["qonto_invoice_paid_at"], "2026-06-29T11:30:00Z")
        self.assertEqual(invoice["qonto_invoice_amount_paid"], 950.0)
        self.assertEqual(len(self.saved), 1)


    def test_missing_qonto_billing_invoice_marks_line_to_control(self):
        data = {
            "sessions": [{"id": "S1", "name": "APS NOVEMBRE 2026", "date_start": "2026-11-01", "date_end": "2026-11-05", "trainees": [{"id": "T1", "first_name": "Clement", "last_name": "VAILLANT", "personal_amount": 1200}]}],
            "billing_lines": [{
                "id": gestion_app._billing_line_id("S1", "T1", "PERSONNEL", "legacy"),
                "traineeId": "T1", "sessionId": "S1", "financingType": "PERSONNEL", "financingRef": "legacy",
                "amount": 1200, "invoiceStatus": "draft", "paymentStatus": "unpaid",
                "qontoInvoiceId": "inv_deleted", "qontoInvoiceNumber": "F-2026-001-PROFORMA",
                "invoiceGeneratedAt": "2026-06-29T10:00:00Z", "invoicePdfUrl": "https://qonto.test/inv"
            }]
        }
        line = gestion_app._find_billing_line(data, data["billing_lines"][0]["id"])
        with patch.object(gestion_app, "get_qonto_invoice", side_effect=gestion_app.QontoNotFoundError("Qonto HTTP 404: not found")):
            did_reset, message = gestion_app._sync_billing_line_with_qonto(data, line)

        self.assertTrue(did_reset)
        self.assertIn("à contrôler", message)
        saved_line = gestion_app._find_billing_line(data, data["billing_lines"][0]["id"])
        self.assertFalse(saved_line.get("qontoInvoiceId"))
        self.assertFalse(saved_line.get("qontoInvoiceNumber"))
        self.assertFalse(saved_line.get("invoiceGeneratedAt"))
        self.assertEqual(saved_line["invoiceStatus"], "control")
        self.assertEqual(saved_line["paymentStatus"], "control")
        self.assertIn("introuvable", saved_line.get("syncWarning", ""))

    def test_billing_lines_keep_direct_debit_schedule_from_persisted_line(self):
        line_id = gestion_app._billing_line_id("S1", "T1", "PERSONNEL", "legacy")
        data = {
            "sessions": [{
                "id": "S1",
                "name": "APS NOVEMBRE 2026",
                "date_start": "2026-11-01",
                "date_end": "2026-11-05",
                "trainees": [{"id": "T1", "first_name": "Clement", "last_name": "VAILLANT", "personal_amount": 900}],
            }],
            "billing_lines": [{
                "id": line_id,
                "traineeId": "T1",
                "sessionId": "S1",
                "financingType": "PERSONNEL",
                "financingRef": "legacy",
                "amount": 900,
                "invoiceStatus": "draft",
                "paymentStatus": "unpaid",
                "qontoInvoiceId": "inv_123",
                "paymentMode": "sepa_direct_debit",
                "paymentPlan": {"mode": "sepa_direct_debit", "installments": 3},
                "directDebitInstallments": [
                    {"date": "2026-07-10", "amount": 300, "status": "scheduled"},
                    {"date": "2026-08-10", "amount": 300, "status": "scheduled"},
                    {"date": "2026-09-10", "amount": 300, "status": "scheduled"},
                ],
                "qontoPaymentGlobalStatus": "Mandat à signer",
                "qonto_direct_debit_mandate_id": "mandate_123",
                "sign_url": "https://qonto.test/sign",
                "mandateStatus": "pending",
            }],
        }

        line = gestion_app._find_billing_line(data, line_id)

        self.assertEqual(line["paymentMode"], "sepa_direct_debit")
        self.assertEqual(line["paymentPlan"]["installments"], 3)
        self.assertEqual(len(line["directDebitInstallments"]), 3)
        self.assertEqual(line["qontoPaymentGlobalStatus"], "Mandat à signer")
        self.assertEqual(line["qonto_direct_debit_mandate_id"], "mandate_123")


    def test_mark_external_billing_line_blocks_qonto_generation(self):
        line_id = gestion_app._billing_line_id("S1", "T1", "PERSONNEL", "legacy")
        data = {
            "sessions": [{
                "id": "S1",
                "name": "VTC",
                "training_type": "VTC",
                "date_start": "2026-11-01",
                "date_end": "2026-11-05",
                "trainees": [{"id": "T1", "first_name": "Clement", "last_name": "VAILLANT", "personal_amount": 1500}],
            }],
            "billing_lines": [{
                "id": line_id,
                "traineeId": "T1",
                "sessionId": "S1",
                "financingType": "PERSONNEL",
                "financingRef": "legacy",
                "amount": 1500,
                "invoiceStatus": "not_invoiced",
                "paymentStatus": "not_applicable",
                "logs": [],
            }],
        }
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data", side_effect=self.saved.append):
            response = client.post("/api/billing/mark-external", json={"lineId": line_id, "note": "Pennylane F-42"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["line"]["invoiceStatus"], "external_generated")
        self.assertEqual(payload["line"]["paymentStatus"], "not_applicable")
        self.assertEqual(payload["line"]["externalInvoiceNote"], "Pennylane F-42")
        self.assertTrue(payload["line"].get("externalInvoiceMarkedAt"))
        self.assertEqual(len(self.saved), 1)
        ok, result = gestion_app._create_invoice_for_billing_line(data, payload["line"])
        self.assertFalse(ok)
        self.assertTrue(result.get("ignored"))

    def test_billing_dashboard_total_to_invoice_excludes_external_lines(self):
        template = os.path.join(os.path.dirname(__file__), "..", "templates", "admin_sessions_billing.html")
        with open(template, encoding="utf-8") as fh:
            source = fh.read()

        self.assertIn("const notGenerated=filtered.filter(l=>!hasInvoice(l)), total=notGenerated.reduce", source)
        self.assertIn("['Total à facturer',fmtMoney(total)]", source)
        self.assertIn("['Montant non généré',fmtMoney(total)]", source)

    def test_billing_invoice_download_streams_qonto_pdf_inline(self):
        line_id = gestion_app._billing_line_id("S1", "T1", "CPF", "legacy")
        data = {
            "sessions": [{"id": "S1", "name": "Session", "trainees": [{"id": "T1", "first_name": "Ada", "last_name": "Lovelace", "cpf_amount": 1200}]}],
            "billing_lines": [{
                "id": line_id,
                "traineeId": "T1",
                "sessionId": "S1",
                "financingType": "CPF",
                "financingRef": "legacy",
                "qontoInvoiceId": "inv_123",
                "qontoInvoiceNumber": "F-001",
                "logs": [],
            }]
        }
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_find_billing_line", return_value=data["billing_lines"][0]), \
             patch.object(gestion_app, "save_data", side_effect=self.saved.append), \
             patch.object(gestion_app, "download_qonto_invoice_pdf", return_value=(b"%PDF-1.4 fake", "application/pdf")):
            response = client.get(f"/api/admin/billing-lines/{line_id}/download-invoice")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn("inline", response.headers.get("Content-Disposition", ""))
        self.assertEqual(response.data, b"%PDF-1.4 fake")
        self.assertTrue(data["billing_lines"][0].get("invoiceDownloadedAt"))

    def test_billing_invoice_download_uses_existing_public_url(self):
        line_id = gestion_app._billing_line_id("S1", "T1", "CPF", "legacy")
        data = {
            "sessions": [{"id": "S1", "name": "Session", "trainees": [{"id": "T1", "first_name": "Ada", "last_name": "Lovelace", "cpf_amount": 1200}]}],
            "billing_lines": [{
                "id": line_id,
                "traineeId": "T1",
                "sessionId": "S1",
                "financingType": "CPF",
                "financingRef": "legacy",
                "qontoInvoiceId": "inv_123",
                "invoicePdfUrl": "https://qonto.test/invoice.pdf",
            }]
        }
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_find_billing_line", return_value=data["billing_lines"][0]):
            response = client.get(f"/api/admin/billing-lines/{line_id}/download-invoice")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://qonto.test/invoice.pdf")


    def test_qonto_invoice_download_falls_back_to_invoice_public_url_after_404(self):
        not_found_response = Mock(ok=False, status_code=404, content=b'{"error":"Not found"}', text='{"error":"Not found"}')
        not_found_response.headers = {"Content-Type": "application/json"}
        pdf_response = Mock(ok=True, status_code=200, content=b"%PDF-1.4 fallback")
        pdf_response.headers = {"Content-Type": "application/pdf"}

        with patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "get_qonto_headers", return_value={"Authorization": "login:secret"}), \
             patch.object(gestion_app, "_qonto_base_url", return_value="https://qonto.test"), \
             patch.object(gestion_app, "get_qonto_invoice", return_value={"client_invoice": {"id": "inv_123", "public_url": "https://qonto.test/inv_123.pdf"}}), \
             patch.object(gestion_app.requests, "get", side_effect=[not_found_response, pdf_response]) as mocked_get:
            pdf_bytes, content_type = gestion_app.download_qonto_invoice_pdf("inv_123")

        self.assertEqual(pdf_bytes, b"%PDF-1.4 fallback")
        self.assertEqual(content_type, "application/pdf")
        self.assertEqual(mocked_get.call_args_list[0].args[0], "https://qonto.test/v2/client_invoices/inv_123/download")
        self.assertEqual(mocked_get.call_args_list[1].args[0], "https://qonto.test/inv_123.pdf")

    def test_qonto_webhook_rejects_invalid_signature(self):
        client = gestion_app.app.test_client()
        with patch.dict(os.environ, {"QONTO_WEBHOOK_SECRET": "webhook-secret"}):
            response = client.post("/api/qonto/webhooks", json={"data": {"id": "inv_123"}}, headers={"X-Qonto-Signature": "bad"})

        self.assertEqual(response.status_code, 401)

    def test_billing_lines_reuse_trainee_level_qonto_invoice(self):
        data = {"sessions": [{"id": "S1", "training_type": "APS", "date_start": "2026-09-01", "date_end": "2026-10-01", "trainees": [{
            "id": "T1", "first_name": "Clement", "last_name": "Vaillant", "personal_amount": 1,
            "qonto_invoice": {"qonto_invoice_id": "inv_admin", "qonto_invoice_number": "F-ADMIN", "qonto_invoice_status": "finalized", "amount_ttc": 1, "created_at": "2026-06-30T10:00:00Z"}
        }]}]}
        lines = gestion_app._billing_lines(data)

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["qontoInvoiceId"], "inv_admin")
        self.assertEqual(lines[0]["qontoInvoiceNumber"], "F-ADMIN")
        self.assertEqual(lines[0]["invoiceStatus"], "finalized")
        self.assertEqual(lines[0]["paymentStatus"], "unpaid")

    def test_billing_qonto_generation_updates_existing_client_missing_billing_address(self):
        line = {
            "id": "bill_test",
            "traineeId": "T1",
            "sessionId": "S1",
            "financingType": "PERSONNEL",
            "amount": 4300,
            "clientName": "Alice Dupont",
            "traineeFirstName": "Alice",
            "traineeLastName": "Dupont",
            "traineeEmail": "alice@example.test",
            "clientAddress": "47 allée des cistes",
            "clientZipCode": "83520",
            "clientCity": "Roquebrune sur Argens",
            "dateStart": "2026-07-15",
            "dateEnd": "2026-10-28",
            "formationName": "APS",
            "sessionName": "APS",
            "vatRate": 0,
            "invoiceStatus": "not_invoiced",
            "paymentStatus": "not_applicable",
        }
        data = {"billing_lines": [line], "sessions": []}
        existing_client = {"client": {"id": "client_123", "email": "alice@example.test"}}
        updated_client = {"client": {"id": "client_123", "billing_address": {"street_address": "47 allée des cistes", "zip_code": "83520", "city": "Roquebrune sur Argens", "country_code": "FR"}}}

        with patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "get_qonto_invoice_iban", return_value="FR7612345678901234567890123"), \
             patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data", side_effect=self.saved.append), \
             patch.object(gestion_app, "search_qonto_client", return_value=existing_client), \
             patch.object(gestion_app, "update_qonto_client", return_value=updated_client) as update_client, \
             patch.object(gestion_app, "create_qonto_invoice", return_value={"client_invoice": {"id": "inv_123", "number": "F-123"}}), \
             patch.object(gestion_app, "_setup_qonto_direct_debit_for_line"):
            ok, result = gestion_app._create_invoice_for_billing_line(data, line, {})

        self.assertTrue(ok)
        update_client.assert_called_once()
        payload = update_client.call_args.args[1]
        self.assertEqual(payload["address_line_1"], "47 allée des cistes")
        self.assertEqual(payload["zip_code"], "83520")
        self.assertEqual(payload["city"], "Roquebrune sur Argens")
        self.assertEqual(result["line"]["qontoInvoiceId"], "inv_123")


class BillingStartDateFilterTests(unittest.TestCase):
    def test_billing_lines_include_only_sessions_starting_from_june_2026(self):
        sessions = [
            {
                "id": "S-MAY",
                "name": "APS MAI 2026",
                "date_start": "2026-05-31",
                "date_end": "2026-06-04",
                "trainees": [{"id": "T-MAY", "first_name": "Alice", "last_name": "Avant", "personal_amount": 100}],
            },
            {
                "id": "S-JUNE",
                "name": "APS JUIN 2026",
                "date_start": "2026-06-01",
                "date_end": "2026-06-05",
                "trainees": [{"id": "T-JUNE", "first_name": "Bruno", "last_name": "Debut", "personal_amount": 200}],
            },
            {
                "id": "S-FR",
                "nom": "APS JUIN FR 2026",
                "date_debut": "01/06/2026",
                "date_fin": "05/06/2026",
                "trainees": [{"id": "T-FR", "first_name": "Camille", "last_name": "France", "personal_amount": 300}],
            },
        ]

        lines = gestion_app.buildBillingLinesFromSessions(sessions)

        self.assertEqual({line["sessionId"] for line in lines}, {"S-JUNE", "S-FR"})
        self.assertTrue(all(line["dateStart"] >= "2026-06-01" for line in lines))


if __name__ == "__main__":
    unittest.main()
