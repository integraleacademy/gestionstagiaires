import unittest

import app


class AdminBillingPaidStatusTests(unittest.TestCase):
    def _rebuild_line(self, invoice_status, **overrides):
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
        existing[line_id].update(overrides)
        return app.buildBillingLinesFromSessions([session], existing)[0]

    def _collections(self, *statuses):
        return [
            {
                "index": index,
                "date": f"2026-{index:02d}-05",
                "amount": 40,
                "status": status,
                "qonto_direct_debit_collection_id": f"collection-{index}",
            }
            for index, status in enumerate(statuses, 1)
        ]

    def test_fully_settled_finalized_invoice_is_exposed_as_paid(self):
        line = self._rebuild_line("finalized")

        self.assertEqual(line["paymentStatus"], "paid")
        self.assertEqual(line["invoiceStatus"], "paid")
        self.assertEqual(line["qonto_invoice"]["payment_status"], "paid")

    def test_paid_amount_does_not_hide_an_unfinalized_draft(self):
        line = self._rebuild_line("draft")

        self.assertEqual(line["paymentStatus"], "paid")
        self.assertEqual(line["invoiceStatus"], "draft")

    def test_stale_paid_badge_with_zero_receipts_reopens_sent_invoice(self):
        line = self._rebuild_line(
            "paid", qonto_amount_paid_cents=0, qonto_remaining_amount_cents=20000,
            sentAt="2026-09-01T10:00:00Z",
        )

        self.assertEqual(line["invoiceStatus"], "sent")
        self.assertEqual(line["paymentStatus"], "unpaid")
        self.assertEqual(line["qonto_status"], "paid")
        self.assertEqual(line["qonto_invoice"]["paid_amount_cents"], 0)
        self.assertEqual(line["qonto_invoice"]["remaining_amount_cents"], 20000)

    def test_returned_collections_reopen_paid_invoice_without_inventing_send_date(self):
        line = self._rebuild_line(
            "paid", paymentMode="sepa_direct_debit",
            directDebitInstallments=self._collections(*(["returned"] * 5)),
        )

        self.assertEqual(line["invoiceStatus"], "finalized")
        self.assertEqual(line["paymentStatus"], "unpaid")
        self.assertEqual(line["qonto_status"], "paid")
        self.assertEqual(line["paid_amount_cents"], 0)
        self.assertEqual(line["remaining_amount_cents"], 20000)

    def test_partially_returned_collections_reopen_paid_invoice_as_partial(self):
        line = self._rebuild_line(
            "paid", paymentMode="sepa_direct_debit",
            directDebitInstallments=self._collections("completed", *(["returned"] * 4)),
        )

        self.assertEqual(line["invoiceStatus"], "finalized")
        self.assertEqual(line["paymentStatus"], "partially_paid")
        self.assertEqual(line["paid_amount_cents"], 4000)
        self.assertEqual(line["remaining_amount_cents"], 16000)

    def test_verified_transfer_can_settle_invoice_after_returned_collections(self):
        line = self._rebuild_line(
            "paid", paymentMode="sepa_direct_debit", qontoRemoteAmountPaidCents=20000,
            directDebitInstallments=self._collections(*(["returned"] * 5)),
            qontoBankTransfers=[{
                "id": "settling-transfer", "amount_cents": 20000,
                "currency": "EUR", "status": "completed", "side": "credit",
                "operation_type": "transfer", "paid_at": "2026-08-01T12:00:00Z",
            }],
        )

        self.assertEqual(line["invoiceStatus"], "paid")
        self.assertEqual(line["paymentStatus"], "paid")
        self.assertEqual(line["paid_amount_cents"], 20000)
        self.assertEqual(line["remaining_amount_cents"], 0)

    def test_reconciliation_preserves_other_document_lifecycle_states(self):
        for status in ("draft", "canceled", "cancelled", "control", "external_generated"):
            with self.subTest(status=status):
                line = self._rebuild_line(status)
                self.assertEqual(line["invoiceStatus"], status)

    def test_sync_paid_remote_invoice_with_all_collections_returned_stays_unpaid(self):
        line = {
            "qontoInvoiceId": "invoice-returned", "invoiceStatus": "paid", "amount": 200,
            "paymentMode": "sepa_direct_debit",
            "directDebitInstallments": self._collections(*(["returned"] * 5)),
        }
        app._apply_qonto_invoice_payment_to_billing_line(line, {
            "id": "invoice-returned", "status": "paid", "total_amount": "200.00",
            "amount_paid": "200.00", "paid_at": "2026-05-05T12:00:00Z",
        })

        self.assertEqual(line["qontoRemoteAmountPaidCents"], 20000)
        self.assertEqual(line["qonto_amount_paid_cents"], 0)
        self.assertEqual(line["qonto_remaining_amount_cents"], 20000)
        self.assertEqual(line["qonto_payment_status"], "unpaid")
        self.assertEqual(line["paymentStatus"], "unpaid")
        self.assertEqual(line["invoiceStatus"], "finalized")
        self.assertEqual(line["qonto_status"], "paid")

    def test_sync_explicit_unsettled_amount_takes_precedence_over_paid_label(self):
        for amount_paid, payment_status in (("0.00", "unpaid"), ("40.00", "partially_paid")):
            with self.subTest(amount_paid=amount_paid):
                line = {"qontoInvoiceId": "invoice-mismatch", "invoiceStatus": "paid", "amount": 200}
                app._apply_qonto_invoice_payment_to_billing_line(line, {
                    "id": "invoice-mismatch", "status": "paid", "total_amount": "200.00",
                    "amount_paid": amount_paid,
                })

                self.assertEqual(line["invoiceStatus"], "finalized")
                self.assertEqual(line["paymentStatus"], payment_status)
                self.assertEqual(line["qonto_status"], "paid")

    def test_status_only_remote_settlement_without_contradictory_collections_is_preserved(self):
        line = {"qontoInvoiceId": "invoice-manual", "invoiceStatus": "sent", "amount": 200}
        app._apply_qonto_invoice_payment_to_billing_line(line, {
            "id": "invoice-manual", "status": "paid", "total_amount": "200.00",
        })

        self.assertEqual(line["paymentStatus"], "paid")
        self.assertEqual(line["invoiceStatus"], "paid")
        self.assertEqual(line["qonto_amount_paid_cents"], 20000)

    def test_sync_paid_amount_does_not_finalize_a_draft(self):
        line = {"qontoInvoiceId": "invoice-draft", "invoiceStatus": "draft", "amount": 200}
        app._apply_qonto_invoice_payment_to_billing_line(line, {
            "id": "invoice-draft", "status": "draft", "total_amount": "200.00",
            "amount_paid": "200.00",
        })

        self.assertEqual(line["invoiceStatus"], "draft")
        self.assertEqual(line["paymentStatus"], "draft")
        self.assertEqual(line["qonto_amount_paid_cents"], 20000)

    def test_storage_normalization_repairs_paid_badge_but_keeps_raw_status(self):
        line = {
            "invoiceStatus": "paid", "qonto_total_amount_cents": 20000,
            "qonto_amount_paid_cents": 0, "qonto_payment_status": "paid",
        }
        app.normalize_qonto_invoice_storage_fields(line)

        self.assertEqual(line["invoiceStatus"], "finalized")
        self.assertEqual(line["qonto_status"], "paid")
        self.assertEqual(line["paymentStatus"], "unpaid")

    def test_storage_normalization_does_not_invent_document_state(self):
        invoice = {"total_amount_cents": 20000, "paid_amount_cents": 20000}
        app.normalize_qonto_invoice_storage_fields(invoice)

        self.assertNotIn("invoiceStatus", invoice)
        self.assertEqual(invoice["paymentStatus"], "paid")


if __name__ == "__main__":
    unittest.main()
