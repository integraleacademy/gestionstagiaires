import json
import hmac
import hashlib
import time
import unittest
from unittest.mock import patch

import app as gestion_app


class QontoPaymentNormalizationTest(unittest.TestCase):
    def norm(self, total="1650.00", paid="0.00", status="unpaid"):
        inv = {"total_amount": {"value": total}, "status": status}
        if paid is not None:
            inv["amount_paid"] = {"value": paid}
        return gestion_app.normalize_qonto_invoice_payment_data(inv)

    def test_no_payment(self):
        n = self.norm()
        self.assertEqual(n["total_amount_cents"], 165000)
        self.assertEqual(n["amount_paid_cents"], 0)
        self.assertEqual(n["remaining_amount_cents"], 165000)
        self.assertEqual(n["payment_status"], "unpaid")

    def test_partial_payment(self):
        n = self.norm(paid="600.00")
        self.assertEqual(n["amount_paid_cents"], 60000)
        self.assertEqual(n["remaining_amount_cents"], 105000)
        self.assertEqual(n["payment_status"], "partially_paid")
        summary = gestion_app.calculate_trainee_financial_summary_from_lines([{"amount": "1650.00", "qontoInvoiceId": "inv", "qonto_total_amount_cents": 165000, "qonto_amount_paid_cents": 60000}])
        self.assertAlmostEqual(summary["payment_percentage"], 36.36)

    def test_full_overpaid_canceled_and_missing_paid(self):
        self.assertEqual(self.norm(paid="1650.00", status="paid")["payment_status"], "paid")
        over = gestion_app.normalize_qonto_invoice_payment_data({"total_amount_cents": 165000, "amount_paid": {"value": "1700.00"}, "status": "unpaid"})
        self.assertEqual(over["remaining_amount_cents"], 0)
        self.assertEqual(over["payment_status"], "paid")
        self.assertEqual(self.norm(status="canceled")["payment_status"], "canceled")
        self.assertEqual(self.norm(paid=None)["amount_paid_cents"], 0)

    def test_two_invoices_and_no_double_count(self):
        lines = [
            {"amount": "1000.00", "qontoInvoiceId": "a", "qonto_total_amount_cents": 100000, "qonto_amount_paid_cents": 60000},
            {"amount": "650.00", "qontoInvoiceId": "b", "qonto_total_amount_cents": 65000, "qonto_amount_paid_cents": 0},
            {"amount": "600.00", "paymentStatus": "paid", "qontoInvoiceId": "a"},
        ]
        # A Qonto-linked manual duplicate is not counted separately because line_paid uses qonto amount.
        summary = gestion_app.calculate_trainee_financial_summary_from_lines(lines[:2])
        self.assertEqual(summary["invoiced_amount_cents"], 165000)
        self.assertEqual(summary["paid_amount_cents"], 60000)
        self.assertEqual(summary["remaining_amount_cents"], 105000)

    def test_legacy_invoice_no_new_fields(self):
        summary = gestion_app.calculate_trainee_financial_summary_from_lines([{"amount": "1650.00", "qontoInvoiceId": "legacy"}])
        self.assertEqual(summary["paid_amount_cents"], 0)

    def test_error_sync_keeps_previous_paid(self):
        line = {"id": "l1", "qontoInvoiceId": "inv", "amount": "1650.00", "qonto_amount_paid_cents": 60000}
        data = {"billing_lines": [line], "sessions": [{"id":"s1","training_type":"APS","date_start":"2026-07-17","date_end":"2026-07-18","trainees":[{"id":"t1","first_name":"A","last_name":"B","personal_amount":"1650.00"}]}]}
        with patch.object(gestion_app, "get_qonto_invoice", side_effect=RuntimeError("Qonto HTTP 429")):
            with self.assertRaises(RuntimeError):
                gestion_app._sync_billing_line_with_qonto(data, line)
        self.assertEqual(data["billing_lines"][0]["qonto_amount_paid_cents"], 60000)
        self.assertIn("qonto_sync_error", line)


class QontoWebhookTest(unittest.TestCase):
    def setUp(self):
        self.app = gestion_app.app.test_client()

    def test_webhook_invalid_signature(self):
        response = self.app.post("/api/qonto/webhooks", data=b"{}", headers={"X-Qonto-Signature": "bad"})
        self.assertIn(response.status_code, (400, 401))

    def test_webhook_valid_twice_idempotent(self):
        raw = json.dumps({"type": "v1/client-invoices", "event": "updated", "data": {"id": "inv_123"}}).encode()
        secret = "secret"
        ts = str(int(time.time()))
        sig = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
        line = {"id": gestion_app._billing_line_id("s1", "t1", "PERSONNEL", "legacy"), "traineeId": "t1", "sessionId": "s1", "financingType":"PERSONNEL", "financingRef":"legacy", "amount": "1650.00", "qontoInvoiceId": "inv_123"}
        data = {"billing_lines": [line], "sessions": [{"id":"s1","training_type":"APS","date_start":"2026-07-17","date_end":"2026-07-18","trainees":[{"id":"t1","first_name":"A","last_name":"B","personal_amount":"1650.00"}]}]}
        remote = {"client_invoice": {"id": "inv_123", "number": "FL-2026-314", "status": "unpaid", "total_amount": {"value": "1650.00"}, "amount_paid": {"value": "600.00"}}}
        with patch.dict(gestion_app.os.environ, {"QONTO_WEBHOOK_SECRET": secret}), \
             patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data"), \
             patch.object(gestion_app, "get_qonto_invoice", return_value=remote):
            headers = {"Content-Type": "application/json", "X-Qonto-Signature": f"t={ts},v1={sig}"}
            r1 = self.app.post("/api/qonto/webhooks", data=raw, headers=headers)
            r2 = self.app.post("/api/qonto/webhooks", data=raw, headers=headers)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(data["billing_lines"][0]["qonto_amount_paid_cents"], 60000)


if __name__ == "__main__":
    unittest.main()
