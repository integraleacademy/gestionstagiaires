import datetime
import sys
from pathlib import Path
import json
import os
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gestion_app


class MultiPartnerIsolationTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_file = gestion_app.DATA_FILE
        self.original_backup_dir = gestion_app.BACKUP_DIR
        self.original_persist_dir = gestion_app.PERSIST_DIR
        self.original_uploads_dir = gestion_app.UPLOADS_DIR
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
                {"id": self.partner_a, "name": "Partenaire A", "status": "active"},
                {"id": self.partner_b, "name": "Partenaire B", "status": "active"},
            ],
            "users": [],
            "sessions": [
                {"id": "session-a", "partner_id": self.partner_a, "name": "A", "trainees": [{"id": "trainee-a", "partner_id": self.partner_a, "first_name": "Alice"}]},
                {"id": "session-b", "partner_id": self.partner_b, "name": "B", "trainees": [{"id": "trainee-b", "partner_id": self.partner_b, "first_name": "Bob"}]},
            ],
        }
        with open(gestion_app.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def tearDown(self):
        gestion_app.DATA_FILE = self.original_data_file
        gestion_app.BACKUP_DIR = self.original_backup_dir
        gestion_app.PERSIST_DIR = self.original_persist_dir
        gestion_app.UPLOADS_DIR = self.original_uploads_dir
        self.temp_dir.cleanup()

    def test_partner_user_only_loads_own_sessions_and_trainees(self):
        with gestion_app.app.test_request_context("/admin/sessions"):
            gestion_app.session["admin_logged_in"] = True
            gestion_app.session["admin_role"] = "partner_admin"
            gestion_app.session["partner_id"] = self.partner_a
            data = gestion_app.load_data()
        self.assertEqual([s["id"] for s in data["sessions"]], ["session-a"])
        self.assertEqual(data["sessions"][0]["trainees"][0]["id"], "trainee-a")

    def test_partner_scoped_save_cannot_delete_other_partner_data(self):
        with gestion_app.app.test_request_context("/admin/sessions"):
            gestion_app.session["admin_logged_in"] = True
            gestion_app.session["admin_role"] = "partner_admin"
            gestion_app.session["partner_id"] = self.partner_a
            scoped = gestion_app.load_data()
            scoped["sessions"] = []
            gestion_app.save_data(scoped)
        with open(gestion_app.DATA_FILE, encoding="utf-8") as f:
            persisted = json.load(f)
        self.assertIn("session-b", [s["id"] for s in persisted["sessions"]])
        self.assertNotIn("session-a", [s["id"] for s in persisted["sessions"]])

    def test_super_admin_only_can_open_partners_page(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "partner_admin"
            sess["partner_id"] = self.partner_a
        self.assertEqual(self.client.get("/admin/partners").status_code, 403)
        with self.client.session_transaction() as sess:
            sess["admin_role"] = "super_admin"
        self.assertEqual(self.client.get("/admin/partners").status_code, 200)

    def test_invitation_expires_and_is_single_use(self):
        data = gestion_app.load_data()
        user_id = "user-a"
        data["users"].append({"id": user_id, "partner_id": self.partner_a, "email": "a@example.com", "active": True})
        token = gestion_app._create_invitation(data, user_id, self.partner_a)
        data["invitations"][-1]["expires_at"] = (datetime.datetime.utcnow() - datetime.timedelta(hours=1)).isoformat() + "Z"
        gestion_app.save_data(data)
        response = self.client.post("/activate-account", data={"token": token, "password": "Password1234", "confirm": "Password1234"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invitation expir", response.get_data(as_text=True))

        data = gestion_app.load_data()
        token = gestion_app._create_invitation(data, user_id, self.partner_a)
        gestion_app.save_data(data)
        response = self.client.post("/activate-account", data={"token": token, "password": "Password1234", "confirm": "Password1234"})
        self.assertEqual(response.status_code, 302)
        response = self.client.post("/activate-account", data={"token": token, "password": "Password1234", "confirm": "Password1234"})
        self.assertIn("déjà utilisée", response.get_data(as_text=True))

    def test_existing_data_is_attached_to_integrale_partner(self):
        with open(gestion_app.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"sessions": [{"id": "legacy", "trainees": [{"id": "legacy-trainee"}]}]}, f)
        data = gestion_app.load_data()
        self.assertEqual(data["sessions"][0]["partner_id"], gestion_app.INTEGRALE_PARTNER_ID)
        self.assertEqual(data["sessions"][0]["trainees"][0]["partner_id"], gestion_app.INTEGRALE_PARTNER_ID)

    def test_partner_storage_path_rejects_traversal(self):
        path = gestion_app.get_partner_storage_path(self.partner_a, "stagiaires")
        self.assertTrue(path.startswith(os.path.realpath(os.path.join(self.temp_dir.name, "partners", self.partner_a))))
        with self.assertRaises(ValueError):
            gestion_app.get_partner_storage_path("../../etc", "stagiaires")
        with self.assertRaises(ValueError):
            gestion_app.get_partner_storage_path(self.partner_a, "../secret")
