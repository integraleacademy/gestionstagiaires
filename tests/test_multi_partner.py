import datetime
import sys
from pathlib import Path
import json
import os
import tempfile
import unittest
from werkzeug.security import generate_password_hash

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


    def test_healthz_bypasses_data_auth_password_and_background_work(self):
        originals = {
            "load_data": gestion_app.load_data,
            "check_password_hash": gestion_app.werkzeug_security.check_password_hash,
            "vtc": gestion_app._send_vtc_credentials_missing_reminders,
            "vae": gestion_app._send_vae_relance_reminders,
            "docs": gestion_app._send_docs_relance_reminders,
            "exam": gestion_app._inject_vtc_exam_results_notifications,
        }

        def fail(*_args, **_kwargs):
            raise AssertionError("healthz must not trigger heavy work")

        gestion_app.load_data = fail
        gestion_app.werkzeug_security.check_password_hash = fail
        gestion_app._send_vtc_credentials_missing_reminders = fail
        gestion_app._send_vae_relance_reminders = fail
        gestion_app._send_docs_relance_reminders = fail
        gestion_app._inject_vtc_exam_results_notifications = fail
        try:
            response = self.client.get("/healthz")
        finally:
            gestion_app.load_data = originals["load_data"]
            gestion_app.werkzeug_security.check_password_hash = originals["check_password_hash"]
            gestion_app._send_vtc_credentials_missing_reminders = originals["vtc"]
            gestion_app._send_vae_relance_reminders = originals["vae"]
            gestion_app._send_docs_relance_reminders = originals["docs"]
            gestion_app._inject_vtc_exam_results_notifications = originals["exam"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["ok"], True)

    def test_partner_user_only_loads_own_sessions_and_trainees(self):
        with gestion_app.app.test_request_context("/admin/sessions"):
            gestion_app.session["admin_logged_in"] = True
            gestion_app.session["admin_role"] = "partner_admin"
            gestion_app.session["partner_id"] = self.partner_a
            data = gestion_app.load_data()
        self.assertEqual([s["id"] for s in data["sessions"]], ["session-a"])
        self.assertEqual(data["sessions"][0]["trainees"][0]["id"], "trainee-a")


    def test_partner_sessions_page_hides_integrale_only_tools(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "partner_admin"
            sess["partner_id"] = self.partner_a

        response = self.client.get("/admin/sessions")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn("Secrétariat", html)
        self.assertNotIn("Paiement espèces", html)
        self.assertNotIn("Contrôles VTC", html)
        self.assertNotIn(">SCOTIA<", html)
        self.assertNotIn("Tests de positionnement", html)
        self.assertNotIn("FT Refusé", html)
        self.assertNotIn(">AFC<", html)


    def test_admin_sessions_page_hides_exact_duplicate_sessions(self):
        data = gestion_app.load_data()
        data["sessions"] = [
            {"id": "dup-1", "partner_id": self.partner_a, "name": "testadmin", "training_type": "APS", "date_start": "2026-11-02", "date_end": "2026-12-17", "trainees": []},
            {"id": "dup-2", "partner_id": self.partner_a, "name": " testadmin ", "training_type": "aps", "date_start": "2026-11-02", "date_end": "2026-12-17", "trainees": []},
            {"id": "other", "partner_id": self.partner_a, "name": "Autre session", "training_type": "APS", "date_start": "2026-11-02", "date_end": "2026-12-17", "trainees": []},
        ]
        gestion_app.save_data(data)
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "partner_admin"
            sess["partner_id"] = self.partner_a

        response = self.client.get("/admin/sessions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertEqual(html.count('class="card session-card'), 2)
        self.assertEqual(html.count('>testadmin</h2>'), 1)
        self.assertIn('>Autre session</h2>', html)

    def test_create_session_reuses_existing_exact_duplicate(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "partner_admin"
            sess["partner_id"] = self.partner_a

        payload = {
            "name": "testadmin",
            "training_type": "APS",
            "date_start": "2026-11-02",
            "date_end": "2026-12-17",
            "exam_date": "2026-12-18",
        }
        first = self.client.post("/api/sessions/create", json=payload)
        second = self.client.post("/api/sessions/create", json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json().get("deduplicated"))
        self.assertEqual(first.get_json().get("id"), second.get_json().get("id"))
        persisted = gestion_app.load_data()
        created = [s for s in persisted["sessions"] if s.get("name") == "testadmin"]
        self.assertEqual(len(created), 1)

    def test_partner_cannot_access_integrale_only_tools_directly(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "partner_admin"
            sess["partner_id"] = self.partner_a

        forbidden_paths = [
            "/admin/gestion-secretariat",
            "/admin/sessions/paiement-especes",
            "/admin/test-positionnement",
            "/admin/afc",
            "/scotia/login",
        ]
        for path in forbidden_paths:
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers.get("Location"), "/admin/sessions")

        api_response = self.client.post("/api/vtc/check/notify", json={})
        self.assertEqual(api_response.status_code, 403)
        self.assertEqual(api_response.get_json().get("error"), "partner_space_forbidden")

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

    def test_super_admin_can_delete_partner_and_all_scoped_data(self):
        data = gestion_app.load_data()
        data.setdefault("users", []).append({"id": "user-a", "partner_id": self.partner_a, "email": "a@example.com"})
        data.setdefault("invitations", []).append({"id": "invite-a", "partner_id": self.partner_a})
        data.setdefault("positioning_tests", []).append({"id": "test-a", "partner_id": self.partner_a})
        data.setdefault("notifications_admin", []).append({"id": "notif-a", "partner_id": self.partner_a})
        data.setdefault("activity_logs", []).append({"id": "log-a", "partner_id": self.partner_a, "action": "old"})
        data.setdefault("notifications_admin_dismissed_schedule_keys", []).append(f"{self.partner_a}:session-a")
        gestion_app.save_data(data)
        partner_storage = gestion_app.get_partner_storage_path(self.partner_a, "documents")
        with open(os.path.join(partner_storage, "document.txt"), "w", encoding="utf-8") as f:
            f.write("document partenaire")

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "super_admin"
            sess["assist_partner_id"] = self.partner_a
            sess["assist_started_at"] = "2026-01-01T00:00:00Z"

        response = self.client.post(f"/admin/partners/{self.partner_a}/delete")

        self.assertEqual(response.status_code, 302)
        with open(gestion_app.DATA_FILE, encoding="utf-8") as f:
            persisted = json.load(f)
        self.assertNotIn(self.partner_a, [p.get("id") for p in persisted.get("partners", [])])
        for key, items in persisted.items():
            if isinstance(items, list):
                self.assertFalse(
                    any(isinstance(item, dict) and item.get("partner_id") == self.partner_a for item in items),
                    key,
                )
        self.assertIn(self.partner_b, [p.get("id") for p in persisted.get("partners", [])])
        self.assertIn("session-b", [s.get("id") for s in persisted.get("sessions", [])])
        self.assertFalse(os.path.exists(os.path.join(self.temp_dir.name, "partners", self.partner_a)))
        self.assertTrue(any(log.get("action") == "partner_deleted" and log.get("resource_id") == self.partner_a for log in persisted.get("activity_logs", [])))
        with self.client.session_transaction() as sess:
            self.assertNotIn("assist_partner_id", sess)

    def test_integrale_partner_cannot_be_deleted(self):
        data = gestion_app.load_data()
        data["partners"].append({"id": gestion_app.INTEGRALE_PARTNER_ID, "name": "Intégrale", "status": "active"})
        gestion_app.save_data(data)
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "super_admin"

        response = self.client.post(f"/admin/partners/{gestion_app.INTEGRALE_PARTNER_ID}/delete")

        self.assertEqual(response.status_code, 400)

    def test_super_admin_only_can_open_partners_page(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "partner_admin"
            sess["partner_id"] = self.partner_a
        self.assertEqual(self.client.get("/admin/partners").status_code, 403)
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["admin_logged_in"] = True
            sess["admin_role"] = "super_admin"
            sess["platform_role"] = "super_admin"
            sess["partner_id"] = gestion_app.INTEGRALE_PARTNER_ID
        self.assertEqual(self.client.get("/admin/partners").status_code, 200)

    def test_partner_space_uses_partner_logo_only(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "partner_admin"
            sess["partner_id"] = self.partner_a
        html = self.client.get("/admin/sessions").get_data(as_text=True)
        self.assertIn("/static/iaconnectpartenaires.png", html)
        self.assertIn("IA Connect Partenaires", html)
        self.assertIn("height:112px", html)
        self.assertIn("height:88px", html)
        self.assertNotIn('src="/static/icone.png"', html)

    def test_partner_invitation_email_uses_connect_branding(self):
        html = gestion_app._partner_invitation_mail_html(
            {"first_name": "Alice"},
            {"name": "Partenaire A"},
            "https://example.com/activate-account?token=abc",
        )

        self.assertIn("/static/iaconnectpartenaires.png", html)
        self.assertIn("max-height:144px", html)
        self.assertIn("Intégrale Connect Partenaires", html)
        self.assertIn("background:#f97316", html)
        self.assertNotIn("/static/logo-integrale.png", html)
        self.assertNotIn('alt="Intégrale Academy"', html)

    def test_partner_support_email_uses_only_large_partner_logo(self):
        with gestion_app.app.test_request_context("/admin/partner/aide-support"):
            gestion_app.session["admin_email"] = "contact@example.com"
            html = gestion_app._partner_support_mail_html(
                {"name": "Partenaire A", "email": "fallback@example.com"},
                "support",
                "Tableau de bord",
                "problème convention",
                "TEST",
            )

        self.assertIn("/static/iaconnectpartenaires.png", html)
        self.assertIn("max-height:144px", html)
        self.assertIn("Intégrale Connect Partenaires", html)
        self.assertNotIn("/static/logo-integrale.png", html)
        self.assertNotIn('alt="Intégrale Academy"', html)

    def test_integrale_admin_space_keeps_integrale_logo(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"
            sess["partner_id"] = gestion_app.INTEGRALE_PARTNER_ID
        html = self.client.get("/admin/sessions").get_data(as_text=True)
        self.assertIn("/static/icone.png", html)
        self.assertIn("height:80px", html)
        self.assertIn("height:64px", html)
        self.assertNotIn("/static/iaconnectpartenaires.png", html)

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

    def test_admin_sessions_page_hides_other_partner_sessions(self):
        data = gestion_app.load_data()
        data["sessions"].append({
            "id": "integrale-session",
            "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
            "name": "Session Intégrale",
            "training_type": "APS",
            "trainees": [],
        })
        gestion_app.save_data(data)

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"
            sess["partner_id"] = gestion_app.INTEGRALE_PARTNER_ID

        response = self.client.get("/admin/sessions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Session Intégrale", html)
        self.assertNotIn("Partenaire A", html)
        self.assertNotIn(">A<", html)
        self.assertNotIn(">B<", html)

    def test_partner_session_create_attaches_session_to_partner(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "partner_admin"
            sess["partner_id"] = self.partner_a

        response = self.client.post(
            "/api/sessions/create",
            json={"name": "Session partenaire", "training_type": "APS"},
        )

        self.assertEqual(response.status_code, 200)
        session_id = response.get_json()["id"]
        with open(gestion_app.DATA_FILE, encoding="utf-8") as f:
            persisted = json.load(f)
        created = next(s for s in persisted["sessions"] if s["id"] == session_id)
        self.assertEqual(created["partner_id"], self.partner_a)

    def test_super_admin_assist_session_create_attaches_session_to_assisted_partner(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"
            sess["platform_role"] = "super_admin"
            sess["partner_id"] = gestion_app.INTEGRALE_PARTNER_ID
            sess["assist_partner_id"] = self.partner_b

        response = self.client.post(
            "/api/sessions/create",
            json={"name": "Session assistée", "training_type": "VTC"},
        )

        self.assertEqual(response.status_code, 200)
        session_id = response.get_json()["id"]
        with open(gestion_app.DATA_FILE, encoding="utf-8") as f:
            persisted = json.load(f)
        created = next(s for s in persisted["sessions"] if s["id"] == session_id)
        self.assertEqual(created["partner_id"], self.partner_b)

    def test_partner_storage_path_rejects_traversal(self):
        path = gestion_app.get_partner_storage_path(self.partner_a, "stagiaires")
        self.assertTrue(path.startswith(os.path.realpath(os.path.join(self.temp_dir.name, "partners", self.partner_a))))
        with self.assertRaises(ValueError):
            gestion_app.get_partner_storage_path("../../etc", "stagiaires")
        with self.assertRaises(ValueError):
            gestion_app.get_partner_storage_path(self.partner_a, "../secret")

    def test_static_admin_login_tolerates_render_whitespace_and_email_case(self):
        original_admin_user = gestion_app.ADMIN_USER
        original_admin_password = gestion_app.ADMIN_PASSWORD
        try:
            gestion_app.ADMIN_USER = " Admin@Example.com "
            gestion_app.ADMIN_PASSWORD = " Secret1234 "
            response = self.client.post(
                "/admin/login",
                data={"username": "admin@example.com", "password": "Secret1234", "next": "/admin/sessions"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["Location"], "/admin/sessions")
        finally:
            gestion_app.ADMIN_USER = original_admin_user
            gestion_app.ADMIN_PASSWORD = original_admin_password


    def test_static_admin_login_takes_priority_over_partner_same_email(self):
        original_admin_user = gestion_app.ADMIN_USER
        original_admin_password = gestion_app.ADMIN_PASSWORD
        try:
            gestion_app.ADMIN_USER = "admin@example.com"
            gestion_app.ADMIN_PASSWORD = "AdminPassword123"
            data = gestion_app.load_data()
            data["users"].append({
                "id": "partner-admin-same-email",
                "partner_id": self.partner_a,
                "email": "admin@example.com",
                "role": "partner_admin",
                "active": True,
                "password_hash": gestion_app._hash_password("PartnerPassword123"),
            })
            gestion_app.save_data(data)

            response = self.client.post(
                "/admin/login",
                data={"username": "admin@example.com", "password": "AdminPassword123", "next": "/admin/sessions"},
            )

            self.assertEqual(response.status_code, 302)
            with self.client.session_transaction() as sess:
                self.assertEqual(sess["admin_role"], "admin")
                self.assertEqual(sess["platform_role"], "super_admin")
                self.assertEqual(sess["partner_id"], gestion_app.INTEGRALE_PARTNER_ID)
                self.assertNotIn("user_id", sess)
        finally:
            gestion_app.ADMIN_USER = original_admin_user
            gestion_app.ADMIN_PASSWORD = original_admin_password

    def test_partner_login_with_password_hash_opens_requested_admin_page(self):
        data = gestion_app.load_data()
        data["users"].append({
            "id": "user-a",
            "partner_id": self.partner_a,
            "email": "Admin@Example.com",
            "role": "partner_admin",
            "active": True,
            "password_hash": gestion_app._hash_password("Password1234"),
        })
        gestion_app.save_data(data)
        response = self.client.post(
            "/admin/login",
            data={"username": "admin@example.com", "password": "Password1234", "next": "/admin/sessions"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/sessions")
        with self.client.session_transaction() as sess:
            self.assertTrue(sess["admin_logged_in"])
            self.assertEqual(sess["admin_role"], "partner_admin")
            self.assertEqual(sess["partner_id"], self.partner_a)



    def test_partner_login_rejects_unsafe_scrypt_hash_without_verifying_it(self):
        data = gestion_app.load_data()
        data["users"].append({
            "id": "user-a",
            "partner_id": self.partner_a,
            "email": "admin@example.com",
            "role": "partner_admin",
            "active": True,
            "password_hash": "scrypt:1073741824:8:1$salt$digest",
        })
        gestion_app.save_data(data)
        response = self.client.post(
            "/admin/login",
            data={"username": "admin@example.com", "password": "Password1234", "next": "/admin/sessions"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("error=invalid", response.headers["Location"])


    def test_partner_login_rejects_excessive_pbkdf2_without_verifying_it(self):
        data = gestion_app.load_data()
        data["users"].append({
            "id": "user-a",
            "partner_id": self.partner_a,
            "email": "admin@example.com",
            "role": "partner_admin",
            "active": True,
            "password_hash": "pbkdf2:sha256:600001$salt$digest",
        })
        gestion_app.save_data(data)
        original = gestion_app.werkzeug_security.check_password_hash
        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("unsafe PBKDF2 must be rejected before Werkzeug verification")
        gestion_app.werkzeug_security.check_password_hash = fail_if_called
        try:
            response = self.client.post(
                "/admin/login",
                data={"username": "admin@example.com", "password": "Password1234", "next": "/admin/sessions"},
            )
        finally:
            gestion_app.werkzeug_security.check_password_hash = original
        self.assertEqual(response.status_code, 302)
        self.assertIn("error=invalid", response.headers["Location"])

    def test_partner_login_skips_background_tasks_during_authentication(self):
        data = gestion_app.load_data()
        data["users"].append({
            "id": "user-a",
            "partner_id": self.partner_a,
            "email": "admin@example.com",
            "role": "partner_admin",
            "active": True,
            "password_hash": gestion_app._hash_password("Password1234"),
        })
        gestion_app.save_data(data)
        original = gestion_app._send_docs_relance_reminders
        def fail_if_called(_data):
            raise AssertionError("background task should not run during login")
        gestion_app._send_docs_relance_reminders = fail_if_called
        try:
            response = self.client.post(
                "/admin/login",
                data={"username": "admin@example.com", "password": "Password1234", "next": "/admin/sessions"},
            )
        finally:
            gestion_app._send_docs_relance_reminders = original
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/sessions")

    def test_partner_login_accepts_werkzeug_password_hash(self):
        data = gestion_app.load_data()
        data["users"].append({
            "id": "user-a",
            "partner_id": self.partner_a,
            "email": "admin@example.com",
            "role": "partner_admin",
            "active": True,
            "password_hash": generate_password_hash("Password1234"),
        })
        gestion_app.save_data(data)
        response = self.client.post(
            "/admin/login",
            data={"username": "admin@example.com", "password": "Password1234", "next": "/admin/sessions"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/sessions")

    def test_partner_login_preserves_password_spaces(self):
        data = gestion_app.load_data()
        data["users"].append({
            "id": "user-a",
            "partner_id": self.partner_a,
            "email": "admin@example.com",
            "role": "partner_admin",
            "active": True,
            "password_hash": gestion_app._hash_password(" Password1234 "),
        })
        gestion_app.save_data(data)
        response = self.client.post(
            "/admin/login",
            data={"username": "admin@example.com", "password": " Password1234 ", "next": "/admin/sessions"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/admin/sessions")

    def test_partner_login_failure_displays_visible_error(self):
        data = gestion_app.load_data()
        data["users"].append({
            "id": "user-a",
            "partner_id": self.partner_a,
            "email": "admin@example.com",
            "role": "partner_admin",
            "active": True,
            "password_hash": gestion_app._hash_password("Password1234"),
        })
        gestion_app.save_data(data)
        response = self.client.post(
            "/admin/login",
            data={"username": "admin@example.com", "password": "wrong", "next": "/admin/sessions"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Identifiant ou mot de passe incorrect", response.get_data(as_text=True))

    def test_unactivated_partner_login_displays_activation_message(self):
        data = gestion_app.load_data()
        data["users"].append({
            "id": "user-a",
            "partner_id": self.partner_a,
            "email": "admin@example.com",
            "role": "partner_admin",
            "active": True,
            "password_hash": "",
        })
        gestion_app.save_data(data)
        response = self.client.post(
            "/admin/login",
            data={"username": "admin@example.com", "password": "Password1234", "next": "/admin/sessions"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("pas encore activé", response.get_data(as_text=True))

class PartnerAuthFlowTests(MultiPartnerIsolationTests):
    def _seed_partner_user(self, status="active", active=True, password="Password1234", email="admin@example.com"):
        data = gestion_app.load_data()
        for p in data["partners"]:
            if p["id"] == self.partner_a:
                p["status"] = status
        user = {"id": "user-a", "partner_id": self.partner_a, "email": email, "role": "partner_admin", "active": active, "password_hash": gestion_app._hash_password(password) if password is not None else ""}
        data["users"] = [user]
        gestion_app.save_data(data)
        return user

    def test_activation_persists_password_hash_after_reload(self):
        data = gestion_app.load_data()
        data["users"].append({"id": "user-a", "partner_id": self.partner_a, "email": "admin@example.com", "role": "partner_admin", "active": True, "password_hash": ""})
        token = gestion_app._create_invitation(data, "user-a", self.partner_a)
        gestion_app.save_data(data)
        response = self.client.post("/activate-account", data={"token": token, "password": "Password1234", "confirm": "Password1234"})
        self.assertEqual(response.status_code, 302)
        reloaded = gestion_app.load_data()
        user = gestion_app._find_user_by_email(reloaded, "admin@example.com")
        invitation = reloaded["invitations"][-1]
        self.assertTrue(user["password_hash"])
        self.assertEqual(user["role"], "partner_admin")
        self.assertEqual(user["partner_id"], self.partner_a)
        self.assertTrue(invitation["used_at"])

    def test_partner_login_exact_email_sets_expected_session(self):
        user = self._seed_partner_user(email="admin@example.com")
        response = self.client.post("/admin/login", data={"username": "admin@example.com", "password": "Password1234", "next": "/admin/sessions"})
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["user_id"], user["id"])
            self.assertEqual(sess["admin_role"], "partner_admin")
            self.assertEqual(sess["partner_id"], self.partner_a)

    def test_partner_login_email_case_insensitive(self):
        self._seed_partner_user(email="Admin@Example.com")
        response = self.client.post("/admin/login", data={"username": "ADMIN@example.COM", "password": "Password1234", "next": "/admin/sessions"})
        self.assertEqual(response.status_code, 302)

    def test_partner_login_rejects_bad_password(self):
        self._seed_partner_user()
        response = self.client.post("/admin/login", data={"username": "admin@example.com", "password": "WrongPassword1", "next": "/admin/sessions"}, follow_redirects=True)
        self.assertIn("Identifiant ou mot de passe incorrect", response.get_data(as_text=True))

    def test_partner_login_rejects_missing_password_hash(self):
        self._seed_partner_user(password=None)
        response = self.client.post("/admin/login", data={"username": "admin@example.com", "password": "Password1234", "next": "/admin/sessions"}, follow_redirects=True)
        self.assertIn("pas encore activé", response.get_data(as_text=True))

    def test_partner_login_rejects_inactive_user(self):
        self._seed_partner_user(active=False)
        response = self.client.post("/admin/login", data={"username": "admin@example.com", "password": "Password1234", "next": "/admin/sessions"}, follow_redirects=True)
        self.assertIn("désactivé", response.get_data(as_text=True))

    def test_partner_login_rejects_suspended_partner(self):
        self._seed_partner_user(status="suspended")
        response = self.client.post("/admin/login", data={"username": "admin@example.com", "password": "Password1234", "next": "/admin/sessions"}, follow_redirects=True)
        self.assertIn("suspendu", response.get_data(as_text=True))

    def test_partner_login_rejects_archived_partner(self):
        self._seed_partner_user(status="archived")
        response = self.client.post("/admin/login", data={"username": "admin@example.com", "password": "Password1234", "next": "/admin/sessions"}, follow_redirects=True)
        self.assertIn("archivé", response.get_data(as_text=True))

    def test_partner_login_accepts_active_and_trial_statuses(self):
        for status in ("active", "trial"):
            with self.subTest(status=status):
                self.client = gestion_app.app.test_client()
                self._seed_partner_user(status=status)
                response = self.client.post("/admin/login", data={"username": "admin@example.com", "password": "Password1234", "next": "/admin/sessions"})
                self.assertEqual(response.status_code, 302)

    def test_static_admin_login_still_works(self):
        original_admin_user = gestion_app.ADMIN_USER
        original_admin_password = gestion_app.ADMIN_PASSWORD
        try:
            gestion_app.ADMIN_USER = "admin"
            gestion_app.ADMIN_PASSWORD = "Password1234"
            response = self.client.post("/admin/login", data={"username": "admin", "password": "Password1234", "next": "/admin/sessions"})
            self.assertEqual(response.status_code, 302)
        finally:
            gestion_app.ADMIN_USER = original_admin_user
            gestion_app.ADMIN_PASSWORD = original_admin_password

    def test_no_leak_between_two_partners_after_partner_login(self):
        self._seed_partner_user()
        self.client.post("/admin/login", data={"username": "admin@example.com", "password": "Password1234", "next": "/admin/sessions"})
        with gestion_app.app.test_request_context("/admin/sessions"):
            gestion_app.session["admin_logged_in"] = True
            gestion_app.session["admin_role"] = "partner_admin"
            gestion_app.session["partner_id"] = self.partner_a
            scoped = gestion_app.load_data()
        self.assertEqual([s["id"] for s in scoped["sessions"]], ["session-a"])
        self.assertEqual(scoped["sessions"][0]["trainees"][0]["id"], "trainee-a")
