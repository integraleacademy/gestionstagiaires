import unittest

import app


class AdminBillingPaidStatusTests(unittest.TestCase):
    def _rebuild_line(self, invoice_status):
        session = {
            "id": "session-aps-novembre-2026",
            "name": "APS NOVEMBRE 2026",
            "training_type": "APS",
            "date_start": "2026-11-03",
            "date_end": "2026-12-08",
            "trainees": [{
                "id": "trainee-megane",
                "first_name": "Megane",
                "last_name": "Beraud",
                "personal_amount": 200,
            }],
        }
        line_id = app._billing_line_id(
            session["id"],
            "trainee-megane",
            "PERSONNEL",
            "legacy",
        )
        existing = {
            line_id: {
                "id": line_id,
                "sessionId": session["id"],
                "traineeId": "trainee-megane",
                "financingType": "PERSONNEL",
                "financingRef": "legacy",
                "amount": 200,
                "qontoInvoiceId": "invoice-paid",
                "qontoInvoiceNumber": "FL-2026-327",
                "invoiceStatus": invoice_status,
                "paymentStatus": "paid",
                "qonto_total_amount_cents": 20000,
                "qonto_amount_paid_cents": 20000,
                "qonto_remaining_amount_cents": 0,
                "qonto_payment_status": "paid",
                "qonto_status": invoice_status,
            }
        }
        return app.buildBillingLinesFromSessions([session], existing)[0]

    def test_fully_settled_finalized_invoice_is_exposed_as_paid(self):
        line = self._rebuild_line("finalized")

        self.assertEqual(line["paymentStatus"], "paid")
        self.assertEqual(line["invoiceStatus"], "paid")
        self.assertEqual(line["qonto_invoice"]["payment_status"], "paid")

    def test_paid_amount_does_not_hide_an_unfinalized_draft(self):
        line = self._rebuild_line("draft")

        self.assertEqual(line["paymentStatus"], "paid")
        self.assertEqual(line["invoiceStatus"], "draft")


if __name__ == "__main__":
    unittest.main()
