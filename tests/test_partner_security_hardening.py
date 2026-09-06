import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gestion_app


class PartnerSecurityHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_file = gestion_app.DATA_FILE
        self.original_backup_dir = gestion_app.BACKUP_DIR
        self.original_persist_dir = gestion_app.PERSIST_DIR
        self.original_uploads_dir = gestion_app.UPLOADS_DIR
        self.original_secret = gestion_app.app.secret_key
        gestion_app.app.secret_key = "partner-security-test-secret"
        gestion_app.PERSIST_DIR = self.temp_dir.name
        gestion_app.DATA_FILE = os.path.join(self.temp_dir.name, "data.json")
        gestion_app.BACKUP_DIR = os.path.join(self.temp_dir.name, "backups")
        gestion_app.UPLOADS_DIR = os.path.join(self.temp_dir.name, "uploads")
        os.makedirs(gestion_app.BACKUP_DIR, exist_ok=True)
        os.makedirs(gestion_app.UPLOADS_DIR, exist_ok=True)
        self.partner_a = "partner-a-uuid"
        self.partner_b = "partner-b-uuid"
        payload = {
            "partners": [
                {"id": gestion_app.INTEGRALE_PARTNER_ID, "name": "Intégrale", "status": "active"},
                {"id": self.partner_a, "name": "Partenaire A", "status": "active", "internal_notes": "secret A"},
                {"id": self.partner_b, "name": "Partenaire B", "status": "active", "internal_notes": "secret B"},
            ],
            "users": [
                {
                    "id": "user-a", "partner_id": self.partner_a,
                    "email": "a@example.com", "role": "partner_admin", "active": True,
                    "password_hash": gestion_app._hash_password("Password1234"),
                },
                {
                    "id": "user-b", "partner_id": self.partner_b,
                    "email": "b@example.com", "role": "partner_admin", "active": True,
                    "password_hash": gestion_app._hash_password("Password1234"),
                },
            ],
            "sessions": [
                {
                    "id": "session-a", "partner_id": self.partner_a, "name": "A",
                    "trainees": [{"id": "trainee-a", "partner_id": self.partner_a, "first_name": "Alice"}],
                },
                {
                    "id": "session-b", "partner_id": self.partner_b, "name": "B",
                    "trainees": [{"id": "trainee-b", "partner_id": self.partner_b, "first_name": "Bob"}],
                },
            ],
            "invitations": [
                {"id": "invite-a", "partner_id": self.partner_a, "token_encrypted": "secret-token"},
            ],
            "activity_logs": [],
            "unknown_future_collection": [
                {"id": "unknown-a", "partner_id": self.partner_a, "secret": "must-not-leak"},
            ],
            "unknown_future_secret": {"api_key": "must-not-leak"},
            "qonto_oauth": {"access_token": "must-not-leak"},
        }
        with open(gestion_app.DATA_FILE, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        # Complete one-time schema normalization before assertions that count
        # disk reads or writes.
        gestion_app.load_data(run_background_tasks=False)
        gestion_app._partner_login_attempts.clear()
        self.client = gestion_app.app.test_client()

    def tearDown(self):
        gestion_app._partner_login_attempts.clear()
        gestion_app.DATA_FILE = self.original_data_file
        gestion_app.BACKUP_DIR = self.original_backup_dir
        gestion_app.PERSIST_DIR = self.original_persist_dir
        gestion_app.UPLOADS_DIR = self.original_uploads_dir
        gestion_app.app.secret_key = self.original_secret
        self.temp_dir.cleanup()

    def _set_partner_session(self, partner_id=None, role="partner_admin"):
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["admin_logged_in"] = True
            sess["admin_role"] = role
            sess["partner_id"] = partner_id or self.partner_a

    def test_partner_view_is_deny_by_default_and_strips_credentials(self):
        with gestion_app.app.test_request_context("/admin/sessions"):
            gestion_app.session["admin_logged_in"] = True
            gestion_app.session["admin_role"] = "partner_admin"
            gestion_app.session["partner_id"] = self.partner_a
            scoped = gestion_app.load_data(run_background_tasks=False)

        self.assertEqual([item["id"] for item in scoped["partners"]], [self.partner_a])
        self.assertEqual([item["id"] for item in scoped["sessions"]], ["session-a"])
        self.assertNotIn("password_hash", scoped["users"][0])
        self.assertNotIn("internal_notes", scoped["partners"][0])
        self.assertEqual(scoped["invitations"], [])
        self.assertNotIn("qonto_oauth", scoped)
        self.assertNotIn("unknown_future_secret", scoped)
        self.assertNotIn("unknown_future_collection", scoped)

    def test_partner_view_drops_mismatched_nested_trainee(self):
        data = gestion_app.load_data(run_background_tasks=False)
        session_a = next(item for item in data["sessions"] if item["id"] == "session-a")
        session_a["trainees"].append({
            "id": "misfiled-b", "partner_id": self.partner_b, "first_name": "Secret B",
        })

        scoped = gestion_app._filter_data_for_partner(data, self.partner_a)

        trainee_ids = [item["id"] for item in scoped["sessions"][0]["trainees"]]
        self.assertEqual(trainee_ids, ["trainee-a"])

    def test_external_viewer_is_still_confined_to_partner_routes(self):
        self._set_partner_session(role="viewer")
        response = self.client.get("/admin/test-positionnement", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/sessions")

    def test_external_admin_role_cookie_is_invalidated(self):
        self._set_partner_session(role="admin")
        response = self.client.get("/admin/partners", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.headers["Location"])
        with self.client.session_transaction() as sess:
            self.assertNotIn("admin_logged_in", sess)

    def test_partner_user_with_platform_role_cannot_login(self):
        data = gestion_app.load_data(run_background_tasks=False)
        data["users"][0]["role"] = "admin"
        gestion_app.save_data(data)
        response = self.client.post(
            "/admin/login",
            data={"username": "a@example.com", "password": "Password1234", "next": "/admin/partners"},
            follow_redirects=False,
        )
        self.assertIn("error=invalid", response.headers["Location"])
        with self.client.session_transaction() as sess:
            self.assertNotIn("admin_logged_in", sess)

    def test_failed_partner_login_does_not_rewrite_store(self):
        with mock.patch("app.save_data") as save_data:
            response = self.client.post(
                "/admin/login",
                data={"username": "a@example.com", "password": "wrong", "next": "/admin/sessions"},
            )
        self.assertEqual(response.status_code, 302)
        save_data.assert_not_called()

    def test_oversized_credentials_are_rejected_before_auth_store_load(self):
        with mock.patch(
            "app._load_partner_auth_data",
            side_effect=AssertionError("oversized credentials must not load auth data"),
        ):
            response = self.client.post(
                "/admin/login",
                data={"username": "x" * 321, "password": "y", "next": "/admin/sessions"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("error=invalid", response.headers["Location"])

    def test_repeated_failed_logins_reuse_small_auth_index(self):
        gestion_app._partner_auth_index_cache.update({
            "path": "", "fingerprint": None, "users": [], "partners": [], "invitations": [],
        })
        with mock.patch(
            "app._load_valid_json_payload", wraps=gestion_app._load_valid_json_payload,
        ) as loader:
            for _ in range(2):
                response = self.client.post(
                    "/admin/login",
                    data={"username": "missing@example.com", "password": "wrong", "next": "/admin/sessions"},
                )
                self.assertEqual(response.status_code, 302)
        self.assertEqual(loader.call_count, 1)

    def test_invalid_activation_does_not_run_full_business_loader(self):
        with mock.patch.object(
            gestion_app, "load_data", side_effect=AssertionError("full loader must not run")
        ):
            response = self.client.post(
                "/activate-account",
                data={
                    "token": "invalid-token",
                    "password": "Password1234",
                    "confirm": "Password1234",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Invitation invalide", response.get_data(as_text=True))

    def test_rate_limit_short_circuits_before_json_load(self):
        with mock.patch.object(gestion_app, "PARTNER_LOGIN_MAX_ATTEMPTS", 3):
            with gestion_app.app.test_request_context(
                "/admin/login", method="POST", headers={"X-Forwarded-For": "203.0.113.10"},
            ):
                for _ in range(3):
                    self.assertFalse(gestion_app._partner_login_is_rate_limited("attacker@example.com"))
            with mock.patch("app._load_partner_auth_data", side_effect=AssertionError("rate limited request must not load auth data")):
                response = self.client.post(
                    "/admin/login",
                    data={"username": "attacker@example.com", "password": "wrong", "next": "/admin/sessions"},
                    headers={"X-Forwarded-For": "203.0.113.10"},
                )
        self.assertEqual(response.status_code, 302)
        self.assertIn("error=rate_limited", response.headers["Location"])

    def test_external_next_url_is_rejected(self):
        response = self.client.post(
            "/admin/login",
            data={
                "username": "a@example.com", "password": "Password1234",
                "next": "https://evil.example/steal",
            },
        )
        self.assertEqual(response.headers["Location"], "/admin/sessions")

    def test_request_cache_parses_json_only_once(self):
        with gestion_app.app.test_request_context("/admin/sessions"):
            gestion_app.session["admin_logged_in"] = True
            gestion_app.session["admin_role"] = "partner_admin"
            gestion_app.session["partner_id"] = self.partner_a
            with mock.patch("app._load_valid_json_payload", wraps=gestion_app._load_valid_json_payload) as loader:
                first = gestion_app.load_data(run_background_tasks=False)
                second = gestion_app.load_data(run_background_tasks=False)
            self.assertIs(first, second)
            self.assertEqual(loader.call_count, 1)
            self.assertEqual(gestion_app.g.load_data_disk_read_count, 1)

    def test_concurrent_partner_saves_preserve_both_tenants(self):
        barrier = threading.Barrier(2)
        errors = []
        original_writer = gestion_app._write_json_with_backups

        def synchronized_writer(*args, **kwargs):
            barrier.wait(timeout=5)
            return original_writer(*args, **kwargs)

        def save_for(partner_id, expected_session_id, new_name):
            try:
                with gestion_app.app.test_request_context("/api/sessions/save", method="POST"):
                    gestion_app.session["admin_logged_in"] = True
                    gestion_app.session["admin_role"] = "partner_admin"
                    gestion_app.session["partner_id"] = partner_id
                    scoped = gestion_app.load_data(run_background_tasks=False)
                    target = next(item for item in scoped["sessions"] if item["id"] == expected_session_id)
                    target["name"] = new_name
                    gestion_app.save_data(scoped)
            except Exception as exc:  # pragma: no cover - assertion reports it
                errors.append(exc)

        with mock.patch("app._write_json_with_backups", side_effect=synchronized_writer):
            threads = [
                threading.Thread(target=save_for, args=(self.partner_a, "session-a", "A updated")),
                threading.Thread(target=save_for, args=(self.partner_b, "session-b", "B updated")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertFalse(errors)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        with open(gestion_app.DATA_FILE, encoding="utf-8") as handle:
            persisted = json.load(handle)
        names = {item["id"]: item["name"] for item in persisted["sessions"]}
        self.assertEqual(names["session-a"], "A updated")
        self.assertEqual(names["session-b"], "B updated")

    def test_partner_cannot_download_another_tenants_file(self):
        own_root = gestion_app.get_partner_storage_path(self.partner_a, "stagiaires")
        other_root = gestion_app.get_partner_storage_path(self.partner_b, "stagiaires")
        own_path = os.path.join(own_root, "own.pdf")
        other_path = os.path.join(other_root, "other.pdf")
        for path, value in ((own_path, b"own"), (other_path, b"other")):
            with open(path, "wb") as handle:
                handle.write(value)
        own_token = gestion_app._tokenize_path(own_path)
        other_token = gestion_app._tokenize_path(other_path)
        self._set_partner_session()

        self.assertEqual(self.client.get(f"/admin/uploads/{own_token}").status_code, 200)
        self.assertEqual(self.client.get(f"/admin/uploads/{other_token}").status_code, 404)
        self.assertEqual(self.client.get(f"/admin/uploads/{other_token}/download").status_code, 404)

    def test_partner_upload_path_cannot_escape_its_tenant_directory(self):
        other_root = gestion_app.get_partner_storage_path(self.partner_b, "stagiaires")
        other_path = os.path.join(other_root, "secret.pdf")
        with open(other_path, "wb") as handle:
            handle.write(b"partner-b-secret")
        self._set_partner_session()

        response = self.client.get(
            f"/admin/uploads/partners/{self.partner_a}/../{self.partner_b}/stagiaires/secret.pdf"
        )

        self.assertEqual(response.status_code, 404)

    def test_partner_keeps_access_to_referenced_legacy_upload_only(self):
        own_token = "uploads/session-a/trainee-a/documents/own.pdf"
        other_token = "uploads/session-b/trainee-b/documents/other.pdf"
        for token, value in ((own_token, b"own-legacy"), (other_token, b"other-legacy")):
            path = os.path.join(self.temp_dir.name, token)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(value)
        data = gestion_app.load_data(run_background_tasks=False)
        data["sessions"][0]["trainees"][0]["documents"] = [{"file": own_token}]
        data["sessions"][1]["trainees"][0]["documents"] = [{"file": other_token}]
        gestion_app.save_data(data)
        self._set_partner_session()

        self.assertEqual(self.client.get(f"/admin/uploads/{own_token}").status_code, 200)
        self.assertEqual(self.client.get(f"/admin/uploads/{other_token}").status_code, 404)

    def test_global_qonto_and_wedof_credentials_are_blocked_for_partner(self):
        self._set_partner_session()
        for path in ("/admin/qonto", "/admin/wedof"):
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/admin/sessions")
        response = self.client.get("/api/qonto/status", headers={"Accept": "application/json"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "tenant_integration_not_configured")


class PartnerInvitationIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_file = gestion_app.DATA_FILE
        self.original_backup_dir = gestion_app.BACKUP_DIR
        self.original_persist_dir = gestion_app.PERSIST_DIR
        self.original_secret = gestion_app.app.secret_key
        gestion_app.app.secret_key = "invitation-idempotency-secret"
        gestion_app.PERSIST_DIR = self.temp_dir.name
        gestion_app.DATA_FILE = os.path.join(self.temp_dir.name, "data.json")
        gestion_app.BACKUP_DIR = os.path.join(self.temp_dir.name, "backups")
        os.makedirs(gestion_app.BACKUP_DIR, exist_ok=True)
        with open(gestion_app.DATA_FILE, "w", encoding="utf-8") as handle:
            json.dump({"partners": [], "users": [], "sessions": [], "invitations": [], "activity_logs": []}, handle)
        gestion_app.load_data(run_background_tasks=False)
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "super_admin"
            sess["platform_role"] = "super_admin"
            sess["partner_id"] = gestion_app.INTEGRALE_PARTNER_ID

    def tearDown(self):
        gestion_app.DATA_FILE = self.original_data_file
        gestion_app.BACKUP_DIR = self.original_backup_dir
        gestion_app.PERSIST_DIR = self.original_persist_dir
        gestion_app.app.secret_key = self.original_secret
        self.temp_dir.cleanup()

    def _create_partner_without_email(self):
        data = gestion_app.load_data(run_background_tasks=False)
        partner_id = "partner-invite"
        user_id = "user-invite"
        data["partners"].append({"id": partner_id, "name": "Invite", "email": "invite@example.com", "status": "active"})
        data["users"].append({
            "id": user_id, "partner_id": partner_id, "email": "invite@example.com",
            "role": "partner_admin", "active": True, "password_hash": "",
        })
        gestion_app._create_invitation(data, user_id, partner_id)
        gestion_app.save_data(data)
        return partner_id

    def test_repeated_send_triggers_only_one_network_call(self):
        partner_id = self._create_partner_without_email()
        with mock.patch("app._send_partner_invitation_email", return_value={"ok": True, "message_id": "mid", "status_code": 201}) as sender:
            self.client.post(f"/admin/partners/{partner_id}/send-invitation")
            second = self.client.post(f"/admin/partners/{partner_id}/send-invitation", follow_redirects=True)
        self.assertEqual(sender.call_count, 1)
        self.assertIn("aucun doublon", second.get_data(as_text=True))
        data = gestion_app.load_data(run_background_tasks=False)
        invitation = gestion_app._active_partner_invitation(data, partner_id)
        self.assertEqual(invitation["delivery_state"], "sent")
        self.assertEqual(invitation["send_attempt_count"], 1)

    def test_failed_send_is_also_rate_limited(self):
        partner_id = self._create_partner_without_email()
        failure = {"ok": False, "error": "Brevo unavailable", "status_code": 503}
        with mock.patch("app._send_partner_invitation_email", return_value=failure) as sender:
            self.client.post(f"/admin/partners/{partner_id}/send-invitation")
            second = self.client.post(
                f"/admin/partners/{partner_id}/send-invitation", follow_redirects=True
            )

        self.assertEqual(sender.call_count, 1)
        self.assertIn("patientez", second.get_data(as_text=True).lower())

    def test_partner_creation_is_durable_before_email_network_call(self):
        observed = {}

        def inspect_persisted_state(_user, partner, _raw_token):
            with open(gestion_app.DATA_FILE, encoding="utf-8") as handle:
                persisted = json.load(handle)
            observed["partner"] = any(item.get("id") == partner["id"] for item in persisted.get("partners", []))
            observed["invitation_state"] = next(
                item["delivery_state"] for item in persisted.get("invitations", [])
                if item.get("partner_id") == partner["id"]
            )
            return {"ok": True, "message_id": "mid", "status_code": 201}

        with mock.patch("app._send_partner_invitation_email", side_effect=inspect_persisted_state):
            response = self.client.post(
                "/admin/partners/new",
                data={"name": "Nouveau", "email": "new@example.com", "max_users": "5", "status": "trial"},
            )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(observed["partner"])
        self.assertEqual(observed["invitation_state"], "sending")


if __name__ == "__main__":
    unittest.main()
