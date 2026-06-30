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

    def test_qonto_webhook_rejects_invalid_signature(self):
        client = gestion_app.app.test_client()
        with patch.dict(os.environ, {"QONTO_WEBHOOK_SECRET": "webhook-secret"}):
            response = client.post("/api/qonto/webhooks", json={"data": {"id": "inv_123"}}, headers={"X-Qonto-Signature": "bad"})

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
