import os
import unittest
from unittest.mock import patch

import app as gestion_app


class AdminQontoBankAccountsTest(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()

    def _login_admin(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def test_route_requires_admin_login(self):
        response = self.client.get("/api/admin/qonto/bank-accounts")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["ok"], False)


    def test_route_rejects_viewer_admin_role(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "viewer"

        response = self.client.get("/api/admin/qonto/bank-accounts")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["ok"], False)

    def test_route_returns_only_safe_organization_and_masked_bank_accounts(self):
        self._login_admin()
        qonto_payload = {
            "organization": {
                "id": "org_123",
                "name": "Intégrale Academy",
                "oauth_secret": "must-not-leak",
                "bank_accounts": [
                    {
                        "id": "ba_main",
                        "iban": "FR76 3000 6000 0112 3456 7890 189",
                        "name": "Compte principal",
                        "status": "active",
                        "main": True,
                        "bic": "TRZOFR21XXX",
                    }
                ],
            },
            "access_token": "must-not-leak",
        }

        with patch.dict(os.environ, {"QONTO_LOGIN": "login", "QONTO_SECRET_KEY": "secret"}), \
             patch.object(gestion_app, "_qonto_request", return_value=qonto_payload) as request_mock:
            response = self.client.get("/api/admin/qonto/bank-accounts")

        self.assertEqual(response.status_code, 200)
        request_mock.assert_called_once_with("GET", "/v2/organization")
        body = response.get_json()
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["organization"], {"id": "org_123", "name": "Intégrale Academy"})
        self.assertEqual(
            body["bank_accounts"],
            [
                {
                    "id": "ba_main",
                    "iban": "FR76********0189",
                    "name": "Compte principal",
                    "status": "active",
                    "main": True,
                }
            ],
        )
        serialized = response.get_data(as_text=True)
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("3000", serialized)
        self.assertNotIn("TRZOFR21XXX", serialized)


if __name__ == "__main__":
    unittest.main()
