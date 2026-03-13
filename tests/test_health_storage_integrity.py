import json
import os
import tempfile
import unittest

import app as gestion_app


class HealthStorageIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_file = gestion_app.DATA_FILE
        self.original_vae_data_file = gestion_app.VAE_DATA_FILE
        self.original_backup_dir = gestion_app.BACKUP_DIR
        self.original_uploads_dir = gestion_app.UPLOADS_DIR

        gestion_app.DATA_FILE = os.path.join(self.temp_dir.name, "data.json")
        gestion_app.VAE_DATA_FILE = os.path.join(self.temp_dir.name, "data_vae.json")
        gestion_app.BACKUP_DIR = os.path.join(self.temp_dir.name, "backups")
        gestion_app.UPLOADS_DIR = os.path.join(self.temp_dir.name, "uploads")
        os.makedirs(gestion_app.BACKUP_DIR, exist_ok=True)
        os.makedirs(gestion_app.UPLOADS_DIR, exist_ok=True)

    def tearDown(self):
        gestion_app.DATA_FILE = self.original_data_file
        gestion_app.VAE_DATA_FILE = self.original_vae_data_file
        gestion_app.BACKUP_DIR = self.original_backup_dir
        gestion_app.UPLOADS_DIR = self.original_uploads_dir
        self.temp_dir.cleanup()

    def test_health_endpoint_reports_all_storage_files(self):
        with open(gestion_app.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"sessions": []}, f)
        with open(gestion_app.VAE_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"dossiers": []}, f)

        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("files", payload)
        self.assertTrue(payload["files"]["data"]["valid_json"])
        self.assertTrue(payload["files"]["vae"]["valid_json"])
        self.assertEqual(payload["files"]["data"]["required_key"], "sessions")
        self.assertEqual(payload["files"]["vae"]["required_key"], "dossiers")

    def test_integrity_endpoint_marks_recoverable_when_backup_exists(self):
        with open(gestion_app.DATA_FILE, "w", encoding="utf-8") as f:
            f.write("{broken")

        with open(os.path.join(gestion_app.BACKUP_DIR, "data_json.manual.20260101T120000Z.json"), "w", encoding="utf-8") as f:
            json.dump({"sessions": []}, f)

        response = self.client.get("/api/health/storage-integrity")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload["data"]["valid_json"])
        self.assertTrue(payload["data"]["recoverable_from_backup"])
        self.assertTrue(payload["uploads_dir"]["exists"])


if __name__ == "__main__":
    unittest.main()
