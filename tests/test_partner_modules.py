import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gestion_app


class PartnerModuleTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_file = gestion_app.DATA_FILE
        self.original_backup_dir = gestion_app.BACKUP_DIR
        self.original_persist_dir = gestion_app.PERSIST_DIR
        self.original_super_admins = set(gestion_app.SUPER_ADMIN_USERS)
        gestion_app.PERSIST_DIR = self.temp_dir.name
        gestion_app.DATA_FILE = os.path.join(self.temp_dir.name, "data.json")
        gestion_app.BACKUP_DIR = os.path.join(self.temp_dir.name, "backups")
        os.makedirs(gestion_app.BACKUP_DIR, exist_ok=True)
        self.partner_a = "partner-a-uuid"
        self.partner_b = "partner-b-uuid"
        with open(gestion_app.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "partners": [
                    {"id": self.partner_a, "name": "A", "status": "active", "enabled_modules": ["student_management"]},
                    {"id": self.partner_b, "name": "B", "status": "active", "enabled_modules": ["student_management", "billing", "sales_tracking"]},
                ],
                "users": [],
                "sessions": [
                    {"id": "session-a", "partner_id": self.partner_a, "trainees": [{"id": "ta", "partner_id": self.partner_a}]},
                    {"id": "session-b", "partner_id": self.partner_b, "trainees": [{"id": "tb", "partner_id": self.partner_b}]},
                ],
            }, f)

    def tearDown(self):
        gestion_app.DATA_FILE = self.original_data_file
        gestion_app.BACKUP_DIR = self.original_backup_dir
        gestion_app.PERSIST_DIR = self.original_persist_dir
        gestion_app.SUPER_ADMIN_USERS = self.original_super_admins
        self.temp_dir.cleanup()

    def _login_partner(self, partner_id):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "partner_admin"
            sess["partner_id"] = partner_id
            sess["admin_username"] = f"{partner_id}@example.test"

    def _login_super_admin(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "super_admin"
            sess["partner_id"] = gestion_app.INTEGRALE_PARTNER_ID
            sess["admin_username"] = "super@example.test"

    def test_integrale_gets_all_modules_including_advanced(self):
        data = {"sessions": []}
        self.assertTrue(gestion_app._ensure_multi_partner_payload(data))
        integrale = next(p for p in data["partners"] if p["id"] == gestion_app.INTEGRALE_PARTNER_ID)
        expected = {m["id"] for m in gestion_app.active_module_catalog(include_core=True, include_advanced=True)}
        self.assertEqual(set(integrale["enabled_modules"]), expected)

    def test_normalize_rejects_fake_modules_and_adds_dependencies(self):
        modules = gestion_app.normalize_enabled_modules(["billing", "fake_module"], include_core=True)
        self.assertIn("billing", modules)
        self.assertIn("student_management", modules)
        self.assertIn("system_core", modules)
        self.assertNotIn("fake_module", modules)

    def test_partner_without_billing_cannot_open_billing_direct_url(self):
        self._login_partner(self.partner_a)
        response = self.client.get("/admin/sessions/facturation")
        self.assertEqual(response.status_code, 403)

    def test_partner_without_billing_cannot_call_billing_api(self):
        self._login_partner(self.partner_a)
        response = self.client.get("/api/billing/session/session-a")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "module_not_available")

    def test_partner_without_billing_does_not_see_billing_menu(self):
        self._login_partner(self.partner_a)
        response = self.client.get("/admin/sessions")
        html = response.get_data(as_text=True)
        self.assertNotIn("🧾 Facturation", html)
        self.assertNotIn("Réglages Qonto", html)

    def test_partner_with_sales_sees_sales_card(self):
        self._login_partner(self.partner_b)
        response = self.client.get("/admin/sessions")
        self.assertIn("Suivi des ventes", response.get_data(as_text=True))

    def test_only_super_admin_can_modify_modules(self):
        self._login_partner(self.partner_a)
        response = self.client.post(f"/admin/partners/{self.partner_a}", data={"enabled_modules": ["billing"]})
        self.assertEqual(response.status_code, 403)

    def test_super_admin_updates_only_target_partner_modules(self):
        self._login_super_admin()
        response = self.client.post(f"/admin/partners/{self.partner_a}", data={
            "name": "A", "status": "active", "enabled_modules": ["billing", "fake_module"]
        })
        self.assertEqual(response.status_code, 302)
        data = gestion_app.load_data()
        a = next(p for p in data["partners"] if p["id"] == self.partner_a)
        b = next(p for p in data["partners"] if p["id"] == self.partner_b)
        self.assertIn("billing", a["enabled_modules"])
        self.assertIn("student_management", a["enabled_modules"])
        self.assertNotIn("fake_module", a["enabled_modules"])
        self.assertEqual(set(b["enabled_modules"]), {"student_management", "billing", "sales_tracking", "system_core"})

    def test_assist_mode_respects_target_partner_modules(self):
        self._login_super_admin()
        with self.client.session_transaction() as sess:
            sess["assist_partner_id"] = self.partner_a
        response = self.client.get("/admin/suivi-ventes")
        self.assertEqual(response.status_code, 403)

    def test_partner_scoped_merge_rejects_forged_other_partner_items(self):
        with gestion_app.app.test_request_context("/admin/sessions"):
            gestion_app.session["admin_logged_in"] = True
            gestion_app.session["admin_role"] = "partner_admin"
            gestion_app.session["partner_id"] = self.partner_a
            scoped = gestion_app.load_data()
            scoped["sessions"].append({"id": "forged", "partner_id": self.partner_b, "trainees": []})
            scoped["sessions"].append({"id": "missing", "trainees": [{"id": "tm"}]})
            gestion_app.save_data(scoped)
        with open(gestion_app.DATA_FILE, encoding="utf-8") as f:
            persisted = json.load(f)
        sessions = {s["id"]: s for s in persisted["sessions"]}
        self.assertNotIn("forged", sessions)
        self.assertEqual(sessions["missing"]["partner_id"], self.partner_a)
        self.assertEqual(sessions["session-b"]["partner_id"], self.partner_b)

    def test_invitation_logs_failed_email_without_losing_partner(self):
        self._login_super_admin()
        with patch.object(gestion_app, "_send_partner_invitation_email", return_value=False):
            response = self.client.post("/admin/partners/new", data={
                "name": "C", "contact_first_name": "Camille", "contact_last_name": "Test", "email": "c@example.test", "status": "trial", "enabled_modules": ["sales_tracking"]
            }, follow_redirects=True)
        self.assertIn("invitation n’a pas pu être envoyée", response.get_data(as_text=True))
        data = gestion_app.load_data()
        partner = next(p for p in data["partners"] if p.get("email") == "c@example.test")
        user = next(u for u in data["users"] if u.get("email") == "c@example.test")
        self.assertIn("sales_tracking", partner["enabled_modules"])
        self.assertEqual(user["last_invitation_status"], "failed")
        self.assertTrue(any(log.get("action") == "invitation_failed" for log in data["activity_logs"]))

    def test_configured_super_admin_is_explicit(self):
        gestion_app.ADMIN_USER = "admin@example.test"
        gestion_app.ADMIN_PASSWORD = "secret"
        gestion_app.SUPER_ADMIN_USERS = set()
        response = self.client.post("/admin/login", data={"username": "admin@example.test", "password": "secret", "next": "/admin/partners"})
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["admin_role"], "admin")
        self.assertEqual(self.client.get("/admin/partners").status_code, 403)
        gestion_app.SUPER_ADMIN_USERS = {"admin@example.test"}
        self.client.get("/admin/logout")
        self.client.post("/admin/login", data={"username": "admin@example.test", "password": "secret", "next": "/admin/partners"})
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["admin_role"], "super_admin")

    def test_new_partner_upload_dir_uses_partner_scoped_storage(self):
        with gestion_app.app.test_request_context("/admin/sessions/session-a"):
            gestion_app.session["admin_logged_in"] = True
            gestion_app.session["admin_role"] = "partner_admin"
            gestion_app.session["partner_id"] = self.partner_a
            upload_dir = gestion_app.trainee_upload_dir("session-a", "ta")
        expected = os.path.join(self.temp_dir.name, "partners", self.partner_a, "stagiaires", "session-a", "ta")
        self.assertEqual(os.path.realpath(upload_dir), os.path.realpath(expected))

    def test_partner_cannot_download_other_partner_scoped_file(self):
        owner_dir = os.path.join(self.temp_dir.name, "partners", self.partner_b, "stagiaires", "session-b", "tb")
        os.makedirs(owner_dir, exist_ok=True)
        with open(os.path.join(owner_dir, "proof.pdf"), "wb") as f:
            f.write(b"pdf")
        self._login_partner(self.partner_a)
        response = self.client.get(f"/admin/uploads/partners/{self.partner_b}/stagiaires/session-b/tb/proof.pdf")
        self.assertEqual(response.status_code, 403)
