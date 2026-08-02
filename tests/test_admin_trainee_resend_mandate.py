import unittest
from pathlib import Path
from unittest.mock import patch

import app as gestion_app


class AdminTraineeResendMandateTest(unittest.TestCase):
    def setUp(self):
        gestion_app.app.config.update(TESTING=True)
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def test_admin_trainee_shows_resend_action_only_for_pending_mandate(self):
        template = Path("templates/admin_trainee.html").read_text(encoding="utf-8")

        self.assertIn("function lineHasPendingMandate(line)", template)
        self.assertIn("Renvoyer le mandat de prélèvement", template)
        self.assertIn("lineHasPendingMandate(l) && !readOnly", template)
        self.assertIn("data-mandate=", template)

    def test_resend_endpoint_sends_the_existing_signature_link(self):
        line = {
            "id": "line-1",
            "traineeEmail": "stagiaire@example.com",
            "sign_url": "https://example.test/sign/mandate-1",
            "qonto_direct_debit_mandate_id": "mandate-1",
            "qonto_mandate_status": "pending",
        }
        data = {"billing_lines": [line]}

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_billing_lines", return_value=[line]), \
             patch.object(gestion_app, "save_data") as save_mock, \
             patch.object(gestion_app, "_send_qonto_mandate_link", return_value=True) as send_mock:
            response = self.client.post("/api/billing/resend-mandate", json={"lineId": "line-1"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        send_mock.assert_called_once_with(line)
        save_mock.assert_called_once_with(data)


if __name__ == "__main__":
    unittest.main()
