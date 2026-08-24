import hmac
import hashlib
import json
import os
import tempfile
import unittest

import app as gestion_app


class SecurityPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_file = gestion_app.DATA_FILE
        self.original_backup_dir = gestion_app.BACKUP_DIR
        self.original_persist_dir = gestion_app.PERSIST_DIR
        self.original_docs_token = gestion_app.DOCS_TO_CONTROL_PUBLIC_TOKEN
        self.original_docs_trusted_user_agent = gestion_app.DOCS_TO_CONTROL_TRUSTED_USER_AGENT

        gestion_app.PERSIST_DIR = self.temp_dir.name
        gestion_app.DATA_FILE = os.path.join(self.temp_dir.name, "data.json")
        gestion_app.BACKUP_DIR = os.path.join(self.temp_dir.name, "backups")
        os.makedirs(gestion_app.BACKUP_DIR, exist_ok=True)
        with open(gestion_app.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"sessions": []}, f)

    def tearDown(self):
        gestion_app.DATA_FILE = self.original_data_file
        gestion_app.BACKUP_DIR = self.original_backup_dir
        gestion_app.PERSIST_DIR = self.original_persist_dir
        gestion_app.DOCS_TO_CONTROL_PUBLIC_TOKEN = self.original_docs_token
        gestion_app.DOCS_TO_CONTROL_TRUSTED_USER_AGENT = self.original_docs_trusted_user_agent
        self.temp_dir.cleanup()

    def test_public_home_head_does_not_crash_in_global_session_guard(self):
        response = self.client.head("/")
        self.assertNotEqual(response.status_code, 500)

    def test_secretariat_notifications_without_auth_returns_401_not_name_error(self):
        response = self.client.get("/api/secretariat/notifications")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "auth_required")

    def test_admin_api_requires_authentication(self):
        response = self.client.post("/api/admin/afc/candidates/delete-all")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "auth_required")

    def test_existing_admin_sessions_without_issue_stamp_are_disconnected(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.get("/admin/sessions", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.headers["Location"])
        with self.client.session_transaction() as sess:
            self.assertNotIn("admin_logged_in", sess)

    def test_existing_admin_api_sessions_without_issue_stamp_are_disconnected(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.get("/api/admin/billing-lines")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "session_expired")

    def test_new_authenticated_sessions_receive_issue_stamp(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"
            sess[gestion_app.SESSION_ISSUED_AT_KEY] = "2099-01-01T00:00:00Z"

        response = self.client.get("/admin/sessions", follow_redirects=False)

        self.assertNotEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertIn(gestion_app.SESSION_ISSUED_AT_KEY, sess)

    def test_docs_to_control_requires_admin_or_configured_token(self):
        gestion_app.DOCS_TO_CONTROL_TRUSTED_USER_AGENT = ""
        response = self.client.get("/docs_to_control.json")
        self.assertEqual(response.status_code, 403)

        gestion_app.DOCS_TO_CONTROL_PUBLIC_TOKEN = "external-dashboard-token"
        response = self.client.get("/docs_to_control.json?token=external-dashboard-token")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["ok"], True)

    def test_docs_to_control_allows_legacy_platform_user_agent_without_token(self):
        gestion_app.DOCS_TO_CONTROL_PUBLIC_TOKEN = ""
        gestion_app.DOCS_TO_CONTROL_TRUSTED_USER_AGENT = "plateformegestion/1.0 (+https://plateformegestion.onrender.com)"

        response = self.client.get(
            "/docs_to_control.json",
            headers={"User-Agent": "plateformegestion/1.0 (+https://plateformegestion.onrender.com)"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["ok"], True)

    def test_docs_to_control_token_takes_precedence_over_legacy_user_agent(self):
        gestion_app.DOCS_TO_CONTROL_PUBLIC_TOKEN = "external-dashboard-token"
        gestion_app.DOCS_TO_CONTROL_TRUSTED_USER_AGENT = "plateformegestion/1.0 (+https://plateformegestion.onrender.com)"

        response = self.client.get(
            "/docs_to_control.json",
            headers={"User-Agent": "plateformegestion/1.0 (+https://plateformegestion.onrender.com)"},
        )

        self.assertEqual(response.status_code, 403)

    def test_detokenize_rejects_path_escape(self):
        with self.assertRaises(Exception):
            gestion_app._detokenize_path("../../etc/passwd")

    def test_json_write_creates_non_colliding_backups(self):
        gestion_app.save_data({"sessions": [{"id": "S1"}]})
        gestion_app.save_data({"sessions": [{"id": "S2"}]})
        backups = [name for name in os.listdir(gestion_app.BACKUP_DIR) if name.startswith("data_json.")]
        self.assertGreaterEqual(len(backups), 1)
        self.assertEqual(len(backups), len(set(backups)))

    def test_large_json_backup_uses_hard_link_snapshot_even_over_copy_limit(self):
        original_limit = gestion_app.MAX_JSON_BACKUP_BYTES
        try:
            gestion_app.MAX_JSON_BACKUP_BYTES = 1
            with open(gestion_app.DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({"sessions": [{"id": "S1", "note": "large-enough"}]}, f)

            backup_path = gestion_app._force_backup_snapshot(gestion_app.DATA_FILE, reason="large-file")

            self.assertIsNotNone(backup_path)
            self.assertTrue(os.path.exists(backup_path))
            with open(backup_path, "r", encoding="utf-8") as f:
                self.assertEqual(json.load(f)["sessions"][0]["id"], "S1")
        finally:
            gestion_app.MAX_JSON_BACKUP_BYTES = original_limit

    def test_write_json_creates_single_pre_save_snapshot_per_write(self):
        original_min_interval = gestion_app.BACKUP_MIN_INTERVAL_SECONDS
        original_times = dict(gestion_app._last_backup_times)
        try:
            gestion_app.BACKUP_MIN_INTERVAL_SECONDS = 1
            gestion_app._last_backup_times.clear()

            gestion_app.save_data({"sessions": [{"id": "S1"}]})

            backups = [name for name in os.listdir(gestion_app.BACKUP_DIR) if name.startswith("data_json.")]
            self.assertEqual(len(backups), 1)
            self.assertIn("before-save", backups[0])
        finally:
            gestion_app.BACKUP_MIN_INTERVAL_SECONDS = original_min_interval
            gestion_app._last_backup_times.clear()
            gestion_app._last_backup_times.update(original_times)


class WedofWebhookSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_secret = os.environ.get("WEDOF_WEBHOOK_SECRET")
        self.original_loader = gestion_app._fetch_wedof_folder_details
        self.original_webhook_loader = gestion_app._load_wedof_webhooks
        self.original_save = gestion_app._save_wedof_webhooks
        self.original_salesforce_sender = gestion_app._send_wedof_entry_to_salesforce
        self.saved = []
        gestion_app._fetch_wedof_folder_details = lambda *_: {}
        gestion_app._load_wedof_webhooks = lambda: []
        gestion_app._save_wedof_webhooks = lambda entries: self.saved.append(entries)
        gestion_app._send_wedof_entry_to_salesforce = lambda *_: ({"success": True}, 200)
        os.environ["WEDOF_WEBHOOK_SECRET"] = "secret"

    def tearDown(self):
        if self.original_secret is None:
            os.environ.pop("WEDOF_WEBHOOK_SECRET", None)
        else:
            os.environ["WEDOF_WEBHOOK_SECRET"] = self.original_secret
        gestion_app._fetch_wedof_folder_details = self.original_loader
        gestion_app._load_wedof_webhooks = self.original_webhook_loader
        gestion_app._save_wedof_webhooks = self.original_save
        gestion_app._send_wedof_entry_to_salesforce = self.original_salesforce_sender

    def test_invalid_wedof_signature_is_accepted_and_flagged(self):
        response = self.client.post("/api/webhooks/wedof", json={"id": "x"}, headers={"X-Wedof-Signature": "bad"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.saved)
        self.assertFalse(self.saved[0][0].get("signature_valid"))
        self.assertTrue(self.saved[0][0].get("signature_present"))

    def test_valid_wedof_signature_is_accepted(self):
        body = b'{"id":"x"}'
        signature = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        response = self.client.post(
            "/api/webhooks/wedof",
            data=body,
            content_type="application/json",
            headers={"X-Wedof-Signature": f"sha256={signature}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.saved)
        self.assertTrue(self.saved[0][0].get("signature_valid"))
        self.assertTrue(self.saved[0][0].get("signature_present"))

    def test_valid_wedof_signature_base64_is_accepted(self):
        import base64
        body = b'{"id":"x"}'
        digest = hmac.new(b"secret", body, hashlib.sha256).digest()
        signature = base64.b64encode(digest).decode("ascii")
        response = self.client.post(
            "/api/webhooks/wedof",
            data=body,
            content_type="application/json",
            headers={"X-Wedof-Signature": f"sha256={signature}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.saved)

    def test_valid_wedof_signature_uppercase_hex_is_accepted(self):
        body = b'{"id":"x"}'
        signature = hmac.new(b"secret", body, hashlib.sha256).hexdigest().upper()
        response = self.client.post(
            "/api/webhooks/wedof",
            data=body,
            content_type="application/json",
            headers={"X-Wedof-Signature": f"sha256={signature}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.saved)

    def test_missing_signature_header_is_accepted_for_wedof_compat(self):
        response = self.client.post(
            "/api/webhooks/wedof",
            data=b'{"id":"x"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.saved)
        self.assertFalse(self.saved[0][0].get("signature_present"))

    def test_secret_header_is_accepted(self):
        response = self.client.post(
            "/api/webhooks/wedof",
            data=b'{"id":"x"}',
            content_type="application/json",
            headers={"X-Wedof-Secret": "secret"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.saved)



    def test_valid_wedof_signature_base64_is_accepted(self):
        import base64
        body = b'{"id":"x"}'
        digest = hmac.new(b"secret", body, hashlib.sha256).digest()
        signature = base64.b64encode(digest).decode("ascii")
        response = self.client.post(
            "/api/webhooks/wedof",
            data=body,
            content_type="application/json",
            headers={"X-Wedof-Signature": f"sha256={signature}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.saved)

    def test_valid_wedof_signature_uppercase_hex_is_accepted(self):
        body = b'{"id":"x"}'
        signature = hmac.new(b"secret", body, hashlib.sha256).hexdigest().upper()
        response = self.client.post(
            "/api/webhooks/wedof",
            data=body,
            content_type="application/json",
            headers={"X-Wedof-Signature": f"sha256={signature}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.saved)

    def test_missing_signature_header_is_accepted_for_wedof_compat(self):
        response = self.client.post(
            "/api/webhooks/wedof",
            data=b'{"id":"x"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.saved)

    def test_secret_header_is_accepted(self):
        response = self.client.post(
            "/api/webhooks/wedof",
            data=b'{"id":"x"}',
            content_type="application/json",
            headers={"X-Wedof-Secret": "secret"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.saved)




if __name__ == "__main__":
    unittest.main()
