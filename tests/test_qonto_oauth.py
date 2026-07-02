import os
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import app as gestion_app


class QontoOauthTests(unittest.TestCase):
    def setUp(self):
        gestion_app.app.config.update(TESTING=True, SERVER_NAME="gestion.test")
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def test_admin_connect_redirects_to_qonto_production_with_secure_state_and_scope(self):
        env = {
            "QONTO_OAUTH_CLIENT_ID": "client-id",
            "QONTO_OAUTH_CLIENT_SECRET": "client-secret",
            "QONTO_OAUTH_ENV": "production",
        }
        with patch.dict(os.environ, env, clear=False):
            response = self.client.get("/admin/qonto/connect")

        self.assertEqual(response.status_code, 302)
        location = response.headers["Location"]
        parsed = urlparse(location)
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", "https://oauth.qonto.com/oauth2/auth")
        qs = parse_qs(parsed.query)
        self.assertEqual(qs["client_id"], ["client-id"])
        self.assertEqual(qs["redirect_uri"], [gestion_app.QONTO_OAUTH_REDIRECT_URI])
        self.assertEqual(qs["response_type"], ["code"])
        self.assertEqual(qs["scope"], [gestion_app.QONTO_OAUTH_SCOPE])
        self.assertTrue(qs.get("state", [""])[0])
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["qonto_oauth_state"], qs["state"][0])

    def test_oauth_status_does_not_expose_tokens(self):
        data = {"qonto_oauth": {"connected": True, "access_token": "access-secret", "refresh_token": "refresh-secret", "expires_at": 9999999999, "scope": gestion_app.QONTO_OAUTH_SCOPE, "environment": "production"}}
        with patch.object(gestion_app, "load_data", return_value=data):
            response = self.client.get("/api/qonto/oauth/status")
        payload = response.get_json()
        self.assertTrue(payload["connected"])
        serialized = response.get_data(as_text=True)
        self.assertNotIn("access-secret", serialized)
        self.assertNotIn("refresh-secret", serialized)
        self.assertTrue(payload["has_access_token"])
        self.assertTrue(payload["has_refresh_token"])
        self.assertEqual(payload["scopes"], gestion_app.QONTO_OAUTH_SCOPE.split())
        self.assertEqual(payload["message"], "OAuth Qonto : connecté production")

    def test_oauth_status_flags_sandbox_token_as_incompatible(self):
        data = {"qonto_oauth": {"connected": True, "refresh_token": "refresh-secret", "environment": "sandbox"}}
        with patch.object(gestion_app, "load_data", return_value=data):
            response = self.client.get("/api/qonto/oauth/status")
        payload = response.get_json()
        self.assertFalse(payload["connected"])
        self.assertTrue(payload["incompatible"])
        self.assertEqual(payload["message"], "OAuth Qonto : connecté sandbox, incompatible avec production")

    def test_admin_reset_qonto_oauth_tokens_clears_sensitive_fields(self):
        data = {"qonto_oauth": {"connected": True, "access_token": "access", "refresh_token": "refresh", "expires_at": 123, "scope": "a b", "scopes": ["a"], "environment": "sandbox"}}
        saved = []
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(gestion_app, "save_data", side_effect=saved.append):
            response = self.client.post("/admin/qonto/oauth/reset")
        self.assertEqual(response.status_code, 302)
        settings = data["qonto_oauth"]
        for key in ("access_token", "refresh_token", "expires_at", "scope", "scopes", "environment"):
            self.assertNotIn(key, settings)
        self.assertFalse(settings["connected"])
        self.assertTrue(saved)

    def test_sepa_request_uses_refreshed_oauth_bearer_header_only(self):
        data = {"qonto_oauth": {"connected": True, "access_token": "old-token", "refresh_token": "refresh-token", "expires_at": 1, "environment": "production"}}
        saved = []
        token_response = {"access_token": "new-token", "refresh_token": "new-refresh", "expires_in": 3600, "token_type": "bearer"}
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data", side_effect=saved.append), \
             patch.dict(os.environ, {"QONTO_OAUTH_CLIENT_ID": "cid", "QONTO_OAUTH_CLIENT_SECRET": "csecret", "QONTO_LOGIN": "login", "QONTO_SECRET_KEY": "api-secret"}, clear=False), \
             patch.object(gestion_app, "_exchange_qonto_oauth_token", return_value=token_response) as exchange, \
             patch.object(gestion_app.requests, "request") as req:
            req.return_value.ok = True
            req.return_value.status_code = 200
            req.return_value.text = '{"direct_debit_mandates": []}'
            req.return_value.headers = {}
            gestion_app.list_qonto_direct_debit_mandates("client_123")

        exchange.assert_called_once()
        headers = req.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer new-token")
        self.assertNotIn("login:api-secret", headers.values())
        self.assertEqual(data["qonto_oauth"]["refresh_token"], "new-refresh")

    def test_sepa_setup_requires_oauth_connection_message(self):
        with patch.object(gestion_app, "load_data", return_value={"qonto_oauth": {}}):
            with self.assertRaisesRegex(gestion_app.QontoConfigurationError, gestion_app.QONTO_OAUTH_REQUIRED_MESSAGE):
                gestion_app._setup_qonto_direct_debit_for_line({"qontoClientId": "client_123"}, {"mode": "sepa_direct_debit", "schedule": [{"date": "2026-07-10", "amount": 100}], "installments": 1})


if __name__ == "__main__":
    unittest.main()
