import hmac
import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import app as gestion_app


class SecurityPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_file = gestion_app.DATA_FILE
        self.original_backup_dir = gestion_app.BACKUP_DIR
        self.original_persist_dir = gestion_app.PERSIST_DIR

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
        self.temp_dir.cleanup()

    def test_admin_api_requires_authentication(self):
        response = self.client.post("/api/admin/afc/candidates/delete-all")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "auth_required")

    def test_docs_to_control_is_public_json(self):
        response = self.client.get("/docs_to_control.json")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["pending_count"], 0)
        self.assertEqual(payload["items"], [])

    def test_docs_to_control_counts_attention_needed_trainees(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "Session 1",
                    "training_type": "A3P",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Ada",
                            "last_name": "Lovelace",
                            "documents": [{"key": "id", "status": "A CONTRÔLER"}],
                        },
                        {
                            "id": "T2",
                            "first_name": "Grace",
                            "last_name": "Hopper",
                            "documents": [{"key": "id", "status": "NON CONFORME"}],
                        },
                    ],
                }
            ]
        }
        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/docs_to_control.json")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["pending_count"], 2)
        reasons = {item["trainee_id"]: item["reasons"] for item in payload["items"]}
        self.assertIn("a_controler", reasons["T1"])
        self.assertIn("non_conforme", reasons["T2"])

    def test_resolve_persist_dir_scores_all_writable_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            low = os.path.join(temp_dir, "low")
            high = os.path.join(temp_dir, "high")
            os.makedirs(low, exist_ok=True)
            os.makedirs(high, exist_ok=True)
            with patch.dict(os.environ, {"PERSIST_DIR": ""}), \
                 patch.object(gestion_app, "_persist_dir_data_score", side_effect=lambda path: {low: 1, high: 42}[path]) as scorer:
                resolved = gestion_app._resolve_persist_dir([low, high])

        self.assertEqual(resolved, high)
        self.assertEqual([call.args[0] for call in scorer.call_args_list], [low, high])

    def test_detokenize_rejects_path_escape(self):
        with self.assertRaises(Exception):
            gestion_app._detokenize_path("../../etc/passwd")

    def test_json_write_creates_non_colliding_backups(self):
        gestion_app.save_data({"sessions": [{"id": "S1"}]})
        gestion_app.save_data({"sessions": [{"id": "S2"}]})
        backups = [name for name in os.listdir(gestion_app.BACKUP_DIR) if name.startswith("data_json.")]
        self.assertGreaterEqual(len(backups), 1)
        self.assertEqual(len(backups), len(set(backups)))


class WedofWebhookSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_secret = os.environ.get("WEDOF_WEBHOOK_SECRET")
        self.original_loader = gestion_app._fetch_wedof_folder_details
        self.original_save = gestion_app._save_wedof_webhooks
        self.saved = []
        gestion_app._fetch_wedof_folder_details = lambda *_: {}
        gestion_app._save_wedof_webhooks = lambda entries: self.saved.append(entries)
        os.environ["WEDOF_WEBHOOK_SECRET"] = "secret"

    def tearDown(self):
        if self.original_secret is None:
            os.environ.pop("WEDOF_WEBHOOK_SECRET", None)
        else:
            os.environ["WEDOF_WEBHOOK_SECRET"] = self.original_secret
        gestion_app._fetch_wedof_folder_details = self.original_loader
        gestion_app._save_wedof_webhooks = self.original_save

    def test_invalid_wedof_signature_is_rejected(self):
        response = self.client.post("/api/webhooks/wedof", json={"id": "x"}, headers={"X-Wedof-Signature": "bad"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.saved, [])

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


if __name__ == "__main__":
    unittest.main()
