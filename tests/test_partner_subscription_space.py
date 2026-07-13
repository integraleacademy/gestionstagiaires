import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gestion_app


class PartnerSubscriptionSpaceTests(unittest.TestCase):
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
                {"id": self.partner_a, "name": "Partenaire A", "status": "active", "enabled_modules": ["cpf"]},
                {"id": self.partner_b, "name": "Partenaire B", "status": "active"},
            ],
            "users": [{"id": "user-a", "partner_id": self.partner_a, "email": "a@example.com", "role": "partner_admin", "active": True}],
            "sessions": [
                {"id": "session-a", "partner_id": self.partner_a, "training_type": "APS", "trainees": [{"id": "old-a", "partner_id": self.partner_a}]},
                {"id": "session-b", "partner_id": self.partner_b, "training_type": "APS", "trainees": []},
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

    def _login_partner(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "partner_admin"
            sess["partner_id"] = self.partner_a
            sess["admin_username"] = "a@example.com"

    def _login_admin(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"
            sess["partner_id"] = gestion_app.INTEGRALE_PARTNER_ID
            sess["admin_username"] = "admin@example.com"

    def _png(self):
        buf = io.BytesIO()
        Image.new("RGB", (12, 12), "green").save(buf, format="PNG")
        buf.seek(0)
        return buf

    def test_partner_updates_own_information_and_persistent_logo(self):
        self._login_partner()
        response = self.client.post(
            "/admin/partner/informations",
            data={"name": "Nouveau Nom", "email": "CONTACT@EXAMPLE.COM", "logo": (self._png(), "logo.png")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        data = gestion_app.load_data()
        partner = next(p for p in data["partners"] if p["id"] == self.partner_a)
        self.assertEqual(partner["name"], "Nouveau Nom")
        self.assertEqual(partner["email"], "contact@example.com")
        self.assertTrue(partner["logo_url"].startswith(f"partners/{self.partner_a}/logos/"))
        self.assertTrue(os.path.exists(os.path.join(gestion_app.PERSIST_DIR, partner["logo_url"])))
        html = self.client.get("/admin/sessions").get_data(as_text=True)
        self.assertIn(partner["logo_url"], html)

    def test_partner_subscription_page_shows_current_subscription_only(self):
        self._login_partner()
        html = self.client.get("/admin/partner/abonnement").get_data(as_text=True)
        self.assertIn("Mon abonnement", html)
        self.assertIn("Module CPF", html)
        self.assertIn("Faites évoluer votre abonnement", html)
        self.assertIn("Factures d’abonnement", html)
        self.assertNotIn("Module CNAPS", html)
        self.assertNotIn("Module Facturation", html)
        self.assertNotIn("Module Suivi des ventes", html)
        self.assertNotIn("Module automatisations", html)
        self.assertNotIn("Non inclus", html)


    def test_partner_subscription_upgrade_page_shows_available_modules(self):
        self._login_partner()
        html = self.client.get("/admin/partner/abonnement/evolution").get_data(as_text=True)
        self.assertIn("Module CNAPS", html)
        self.assertIn("Module CPF", html)
        self.assertIn("Module Facturation", html)
        self.assertIn("Module Suivi des ventes", html)
        self.assertIn("Module formation APS", html)
        self.assertIn("Module automatisations", html)
        self.assertIn("Non inclus", html)


    def test_partner_sessions_dashboard_and_filters_only_show_enabled_trainings(self):
        data = gestion_app.load_data()
        partner = next(p for p in data["partners"] if p["id"] == self.partner_a)
        partner["enabled_modules"] = ["training_aps"]
        data["sessions"].append({
            "id": "session-vtc",
            "partner_id": self.partner_a,
            "training_type": "VTC",
            "date_start": "2026-03-01",
            "trainees": [{"id": "vtc-a", "partner_id": self.partner_a, "created_at": "2026-03-02"}],
        })
        data["sessions"][0]["date_start"] = "2026-02-01"
        data["sessions"][0]["trainees"][0]["created_at"] = "2026-02-02"
        gestion_app.save_data(data)

        self._login_partner()
        html = self.client.get("/admin/sessions").get_data(as_text=True)

        self.assertIn('dashboard-card__label">APS</div>', html)
        self.assertIn('dashboard-card__count">1</div>', html)
        self.assertNotIn('dashboard-card__label">VTC</div>', html)
        self.assertNotIn('dashboard-card__label">DIRIGEANT</div>', html)
        self.assertIn('data-filter-value="aps">APS</button>', html)
        self.assertNotIn('data-filter-value="vtc">VTC</button>', html)
        self.assertNotIn('data-filter-value="dirigeant">DIRIGEANT</button>', html)
        self.assertNotIn('Paiements en espèces</button>', html)
        self.assertIn('dashboard-total-card__count">1</div>', html)

    def test_admin_sessions_filters_keep_cash_payment_for_admins(self):
        self._login_admin()
        html = self.client.get("/admin/sessions").get_data(as_text=True)
        self.assertIn('Paiements en espèces</button>', html)

    def test_trainee_usage_counter_is_incremental_idempotent_and_resettable(self):
        data = gestion_app.load_data()
        partner = next(p for p in data["partners"] if p["id"] == self.partner_a)
        gestion_app.normalize_partner_subscription(data, partner)
        trainee = {"id": "new-a", "partner_id": self.partner_a}
        self.assertTrue(gestion_app.increment_partner_trainee_usage(data, self.partner_a, trainee))
        self.assertFalse(gestion_app.increment_partner_trainee_usage(data, self.partner_a, trainee))
        self.assertEqual(partner["subscription"]["trainee_usage_count"], 2)  # 1 migrated legacy + 1 new
        data["sessions"][0]["trainees"].append(trainee)
        gestion_app.save_data(data)

        self._login_admin()
        response = self.client.post(f"/admin/partners/{self.partner_a}/subscription/reset-usage", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        data = gestion_app.load_data()
        partner = next(p for p in data["partners"] if p["id"] == self.partner_a)
        self.assertEqual(partner["subscription"]["trainee_usage_count"], 0)
        self.assertEqual(len(data["sessions"][0]["trainees"]), 2)
        old_trainee = data["sessions"][0]["trainees"][1]
        self.assertFalse(gestion_app.increment_partner_trainee_usage(data, self.partner_a, old_trainee))
        another = {"id": "after-reset", "partner_id": self.partner_a}
        self.assertTrue(gestion_app.increment_partner_trainee_usage(data, self.partner_a, another))
        self.assertEqual(partner["subscription"]["trainee_usage_count"], 1)

    def test_partner_cannot_reset_usage_counter(self):
        self._login_partner()
        response = self.client.post(f"/admin/partners/{self.partner_a}/subscription/reset-usage")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
