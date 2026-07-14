import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gestion_app


class PartnerInvitationEmailTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_file = gestion_app.DATA_FILE
        self.original_backup_dir = gestion_app.BACKUP_DIR
        self.original_persist_dir = gestion_app.PERSIST_DIR
        self.original_secret = gestion_app.app.secret_key
        self.original_api_key = gestion_app.BREVO_API_KEY
        self.original_sender = gestion_app.BREVO_SENDER_EMAIL
        self.original_sender_name = gestion_app.BREVO_SENDER_NAME
        self.original_app_base_url = gestion_app.APP_BASE_URL
        self.env_patch = mock.patch.dict(os.environ, {"APP_ENV": "test", "APP_BASE_URL": "https://test.example.com/", "ENABLE_TEST_ACTIVATION_LINK": "true"}, clear=False)
        self.env_patch.start()
        gestion_app.app.secret_key = "test-secret"
        gestion_app.PERSIST_DIR = self.temp_dir.name
        gestion_app.DATA_FILE = os.path.join(self.temp_dir.name, "data.json")
        gestion_app.BACKUP_DIR = os.path.join(self.temp_dir.name, "backups")
        os.makedirs(gestion_app.BACKUP_DIR, exist_ok=True)
        self.partner_id = "partner-1"
        self.user_id = "user-1"
        data = {"partners": [{"id": self.partner_id, "name": "Test", "email": "admin@example.com", "status": "trial", "created_at": "2026-07-12T00:00:00Z"}], "users": [{"id": self.user_id, "partner_id": self.partner_id, "email": "admin@example.com", "role": "partner_admin", "active": True}], "sessions": [], "invitations": []}
        raw = gestion_app._create_invitation(data, self.user_id, self.partner_id)
        self.raw = raw
        gestion_app.save_data(data)
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "super_admin"

    def tearDown(self):
        self.env_patch.stop()
        gestion_app.DATA_FILE = self.original_data_file
        gestion_app.BACKUP_DIR = self.original_backup_dir
        gestion_app.PERSIST_DIR = self.original_persist_dir
        gestion_app.app.secret_key = self.original_secret
        gestion_app.BREVO_API_KEY = self.original_api_key
        gestion_app.BREVO_SENDER_EMAIL = self.original_sender
        gestion_app.BREVO_SENDER_NAME = self.original_sender_name
        gestion_app.APP_BASE_URL = self.original_app_base_url
        self.temp_dir.cleanup()

    def test_clear_error_when_api_key_missing(self):
        gestion_app.BREVO_API_KEY = ""
        result = gestion_app._send_partner_invitation_email({"id": self.user_id, "email": "admin@example.com"}, {"id": self.partner_id, "name": "Test"}, self.raw)
        self.assertFalse(result["ok"])
        self.assertIn("BREVO_API_KEY", result["error"])

    def test_clear_error_when_sender_missing(self):
        gestion_app.BREVO_API_KEY = "key"
        gestion_app.BREVO_SENDER_EMAIL = ""
        result = gestion_app._send_partner_invitation_email({"id": self.user_id, "email": "admin@example.com"}, {"id": self.partner_id, "name": "Test"}, self.raw)
        self.assertFalse(result["ok"])
        self.assertIn("BREVO_SENDER_EMAIL", result["error"])

    def test_brevo_failure_does_not_claim_success_and_keeps_invitation(self):
        gestion_app.BREVO_API_KEY = "key"
        gestion_app.BREVO_SENDER_EMAIL = "sender@example.com"
        gestion_app.BREVO_SENDER_NAME = "Sender"
        with mock.patch("app.requests.post") as post:
            post.return_value.status_code = 401
            post.return_value.text = '{"message":"unauthorized"}'
            post.return_value.json.return_value = {"message": "unauthorized"}
            response = self.client.post(f"/admin/partners/{self.partner_id}/send-invitation", follow_redirects=True)
        html = response.get_data(as_text=True)
        self.assertIn("n’a pas pu être envoyé", html)
        data = gestion_app.load_data()
        self.assertEqual(len([i for i in data["invitations"] if not i.get("cancelled_at")]), 1)
        self.assertEqual(data["invitations"][0]["last_send_status"], "échoué")


    def test_activation_url_rewrites_legacy_render_host(self):
        with mock.patch.dict(os.environ, {"APP_BASE_URL": "https://gestionstagiaires-test-v2.onrender.com"}, clear=False):
            activation_url = gestion_app._activation_url(self.raw)
        self.assertTrue(activation_url.startswith("https://gestionstagiaires-r5no.onrender.com/activate-account?token="))
        self.assertNotIn("gestionstagiaires-test-v2.onrender.com", activation_url)

    def test_resend_invitation_reuses_existing_link_and_test_url(self):
        gestion_app.BREVO_API_KEY = "key"
        gestion_app.BREVO_SENDER_EMAIL = "sender@example.com"
        gestion_app.BREVO_SENDER_NAME = "Sender"
        with mock.patch("app.requests.post") as post:
            post.return_value.status_code = 201
            post.return_value.text = '{"messageId":"mid"}'
            post.return_value.json.return_value = {"messageId": "mid"}
            self.client.post(f"/admin/partners/{self.partner_id}/send-invitation")
        payload = post.call_args.kwargs["json"]
        self.assertIn("https://test.example.com/activate-account?token=", payload["textContent"])
        data = gestion_app.load_data()
        self.assertEqual(len([i for i in data["invitations"] if not i.get("cancelled_at")]), 1)
        self.assertEqual(data["invitations"][0]["last_send_status"], "réussi")


    def test_resend_with_unreadable_token_generates_new_invitation(self):
        gestion_app.BREVO_API_KEY = "key"
        gestion_app.BREVO_SENDER_EMAIL = "sender@example.com"
        gestion_app.BREVO_SENDER_NAME = "Sender"
        data = gestion_app.load_data()
        data["invitations"][0]["token_encrypted"] = "unreadable-token"
        gestion_app.save_data(data)
        with mock.patch("app.requests.post") as post:
            post.return_value.status_code = 201
            post.return_value.text = '{"messageId":"mid"}'
            post.return_value.json.return_value = {"messageId": "mid"}
            response = self.client.post(f"/admin/partners/{self.partner_id}/send-invitation", follow_redirects=True)
        html = response.get_data(as_text=True)
        self.assertIn("Invitation envoyée", html)
        data = gestion_app.load_data()
        active_invitations = [i for i in data["invitations"] if not i.get("cancelled_at")]
        cancelled_invitations = [i for i in data["invitations"] if i.get("cancelled_at")]
        self.assertEqual(len(active_invitations), 1)
        self.assertEqual(len(cancelled_invitations), 1)
        self.assertEqual(active_invitations[0]["last_send_status"], "réussi")
        self.assertIn("https://test.example.com/activate-account?token=", post.call_args.kwargs["json"]["textContent"])


    def test_send_invitation_replaces_expired_invitation(self):
        gestion_app.BREVO_API_KEY = "key"
        gestion_app.BREVO_SENDER_EMAIL = "sender@example.com"
        gestion_app.BREVO_SENDER_NAME = "Sender"
        data = gestion_app.load_data()
        data["invitations"][0]["expires_at"] = "2020-01-01T00:00:00Z"
        gestion_app.save_data(data)
        with mock.patch("app.requests.post") as post:
            post.return_value.status_code = 201
            post.return_value.text = '{"messageId":"mid"}'
            post.return_value.json.return_value = {"messageId": "mid"}
            self.client.post(f"/admin/partners/{self.partner_id}/send-invitation")
        data = gestion_app.load_data()
        active_invitations = [i for i in data["invitations"] if not i.get("cancelled_at") and not i.get("used_at")]
        self.assertEqual(len(active_invitations), 2)
        self.assertNotEqual(active_invitations[-1]["expires_at"], "2020-01-01T00:00:00Z")
        sent_token = post.call_args.kwargs["json"]["textContent"].split("token=", 1)[1]
        self.assertIs(gestion_app._find_invitation_by_raw_token(data, sent_token), active_invitations[-1])

    def test_activate_account_accepts_invitation_missing_hash_when_encrypted_token_matches(self):
        data = gestion_app.load_data()
        data["invitations"][0]["token_hash"] = ""
        gestion_app.save_data(data)
        response = self.client.post(
            f"/activate-account?token={self.raw}",
            data={"password": "Password123", "confirm": "Password123"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        data = gestion_app.load_data()
        self.assertTrue(data["users"][0]["password_hash"])
        self.assertTrue(data["invitations"][0]["used_at"])
        self.assertEqual(data["invitations"][0]["token_hash"], gestion_app._hash_token(self.raw))

    def test_manual_link_inaccessible_to_partner_user(self):
        with self.client.session_transaction() as sess:
            sess["admin_role"] = "partner_admin"
            sess["partner_id"] = self.partner_id
        self.assertEqual(self.client.get(f"/admin/partners/{self.partner_id}/activation-link").status_code, 403)

    def test_no_token_or_api_key_in_logs(self):
        gestion_app.BREVO_API_KEY = "secret-api-key"
        gestion_app.BREVO_SENDER_EMAIL = "sender@example.com"
        gestion_app.BREVO_SENDER_NAME = "Sender"
        with self.assertLogs(gestion_app.app.logger, level="INFO") as logs, mock.patch("app.requests.post") as post:
            post.return_value.status_code = 400
            post.return_value.text = '{"message":"bad sender"}'
            post.return_value.json.return_value = {"message": "bad sender"}
            gestion_app._send_partner_invitation_email({"id": self.user_id, "email": "admin@example.com"}, {"id": self.partner_id, "name": "Test"}, self.raw)
        joined = "\n".join(logs.output)
        self.assertNotIn(self.raw, joined)
        self.assertNotIn("secret-api-key", joined)
        self.assertIn("bad sender", joined)


if __name__ == "__main__":
    unittest.main()
