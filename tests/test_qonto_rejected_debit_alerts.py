import unittest
from unittest.mock import patch

import app as gestion_app


class QontoRejectedDebitAlertTests(unittest.TestCase):
    def setUp(self):
        self.line = {
            "id": "BL-1", "traineeId": "T-1", "sessionId": "S-1",
            "traineeFirstName": "Alice", "traineeLastName": "Martin",
            "formationName": "Agent de sécurité", "dateStart": "2026-09-01", "dateEnd": "2026-09-30",
            "directDebitInstallments": [{
                "amount": 325.5, "date": "2026-08-15", "due_date": "2026-08-15",
                "status": "scheduled", "qonto_direct_debit_subscription_id": "SUB-1",
            }],
        }
        self.data = {"notifications_admin": []}

    def test_rejection_sends_designed_email_to_both_recipients_and_adds_notification(self):
        event = {
            "id": "COL-1", "direct_debit_subscription_id": "SUB-1",
            "status": "rejected", "status_reason": "Solde insuffisant", "collection_date": "2026-08-15",
        }
        with patch.object(gestion_app, "_billing_lines", return_value=[self.line]), \
             patch.object(gestion_app, "_save_billing_line"), \
             patch.object(gestion_app, "brevo_send_email", return_value=True) as send_email:
            updated = gestion_app._apply_qonto_collection_webhook(self.data, event)

        self.assertTrue(updated)
        send_email.assert_called_once()
        args, kwargs = send_email.call_args
        self.assertEqual(args[0], "cassandre@integraleacademy.com")
        self.assertEqual(kwargs["cc_emails"], ["clement@integraleacademy.com"])
        for expected in ("Alice Martin", "Agent de sécurité", "325,50 €", "15/08/2026", "01/09/2026", "30/09/2026"):
            self.assertIn(expected, args[2])
        notification = self.data["notifications_admin"][0]
        self.assertIn("Prélèvement rejeté", notification["label"])
        self.assertEqual(notification["meta"]["collection_id"], "COL-1")

    def test_duplicate_webhook_does_not_send_duplicate_alert(self):
        installment = self.line["directDebitInstallments"][0]
        with patch.object(gestion_app, "brevo_send_email", return_value=True) as send_email:
            self.assertTrue(gestion_app._notify_rejected_qonto_debit(self.data, self.line, installment, "COL-1"))
            self.assertFalse(gestion_app._notify_rejected_qonto_debit(self.data, self.line, installment, "COL-1"))

        send_email.assert_called_once()
        self.assertEqual(len(self.data["notifications_admin"]), 1)


if __name__ == "__main__":
    unittest.main()
