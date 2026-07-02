import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

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
            "sessions": [{"id": "S1", "name": "APS NOVEMBRE 2026", "date_start": "2026-11-01", "date_end": "2026-11-05", "trainees": [{"id": "T1", "first_name": "Clement", "last_name": "VAILLANT", "cpf_amount": 1200}]}],
            "billing_lines": [{
                "id": gestion_app._billing_line_id("S1", "T1", "CPF", "legacy"),
                "traineeId": "T1", "sessionId": "S1", "financingType": "CPF", "financingRef": "legacy",
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

    def test_qonto_webhook_rejects_invalid_signature(self):
        client = gestion_app.app.test_client()
        with patch.dict(os.environ, {"QONTO_WEBHOOK_SECRET": "webhook-secret"}):
            response = client.post("/api/qonto/webhooks", json={"data": {"id": "inv_123"}}, headers={"X-Qonto-Signature": "bad"})

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
