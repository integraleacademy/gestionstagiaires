import unittest
from unittest.mock import patch

import app as gestion_app


class QontoOAuthRoutesTest(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()

    def test_qonto_oauth_ping_is_registered_as_get(self):
        response = self.client.get("/api/qonto/oauth/ping")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "route": "qonto_oauth_ping"})

    def test_qonto_oauth_callback_missing_code_redirects_to_error(self):
        response = self.client.get("/api/qonto/oauth/callback")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/qonto?oauth=error")

    def test_qonto_oauth_callback_exchanges_code_and_redirects_to_success(self):
        token_payload = {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
            "scope": "offline_access client.read",
        }
        saved = {}

        with patch.object(gestion_app, "_exchange_qonto_oauth_token", return_value=token_payload) as exchange, \
             patch.object(gestion_app, "load_data", return_value={}) as load_data, \
             patch.object(gestion_app, "save_data", side_effect=lambda data: saved.update(data)):
            response = self.client.get("/api/qonto/oauth/callback?code=abc123")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/qonto?oauth=success")
        exchange.assert_called_once()
        self.assertEqual(
            exchange.call_args.args[0]["redirect_uri"],
            gestion_app.QONTO_OAUTH_REDIRECT_URI,
        )
        load_data.assert_called_once()
        self.assertEqual(saved["qonto_oauth"]["access_token"], "access-token")
        self.assertEqual(saved["qonto_oauth"]["refresh_token"], "refresh-token")
        self.assertEqual(saved["qonto_oauth"]["environment"], "production")
        self.assertIn("expires_at", saved["qonto_oauth"])


if __name__ == "__main__":
    unittest.main()
