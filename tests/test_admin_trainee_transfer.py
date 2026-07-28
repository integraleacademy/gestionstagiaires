import unittest

import app


class AdminTraineeTransferTests(unittest.TestCase):
    def test_transfer_rekeys_billing_line_and_keeps_invoice_and_debits(self):
        old_id = app._billing_line_id("source", "trainee-1", "PERSONNEL", "legacy")
        data = {
            "billing_lines": [{
                "id": old_id,
                "traineeId": "trainee-1",
                "sessionId": "source",
                "financingType": "PERSONNEL",
                "financingRef": "legacy",
                "invoiceStatus": "sent",
                "qontoInvoiceId": "invoice-123",
                "qonto_direct_debit_mandate_id": "mandate-123",
                "directDebitInstallments": [{"amount": 100, "status": "scheduled"}],
            }]
        }

        count = app._transfer_trainee_billing_lines(data, "trainee-1", "source", "target")

        self.assertEqual(count, 1)
        line = data["billing_lines"][0]
        self.assertEqual(
            line["id"],
            app._billing_line_id("target", "trainee-1", "PERSONNEL", "legacy"),
        )
        self.assertEqual(line["sessionId"], "target")
        self.assertEqual(line["invoiceStatus"], "sent")
        self.assertEqual(line["qontoInvoiceId"], "invoice-123")
        self.assertEqual(line["qonto_direct_debit_mandate_id"], "mandate-123")
        self.assertEqual(line["directDebitInstallments"][0]["status"], "scheduled")
        self.assertEqual(line["billingHistory"][-1]["action"], "trainee_transferred")

    def test_transfer_only_moves_matching_trainee_and_source_session(self):
        data = {"billing_lines": [
            {"id": "keep-other", "traineeId": "other", "sessionId": "source", "financingType": "PERSONNEL"},
            {"id": "keep-target", "traineeId": "trainee-1", "sessionId": "another", "financingType": "PERSONNEL"},
        ]}

        count = app._transfer_trainee_billing_lines(data, "trainee-1", "source", "target")

        self.assertEqual(count, 0)
        self.assertEqual([line["id"] for line in data["billing_lines"]], ["keep-other", "keep-target"])

    def test_transfer_without_persisted_billing_lines_is_safe(self):
        data = {}

        self.assertEqual(
            app._transfer_trainee_billing_lines(data, "trainee-1", "source", "target"),
            0,
        )
        self.assertNotIn("billing_lines", data)


if __name__ == "__main__":
    unittest.main()
