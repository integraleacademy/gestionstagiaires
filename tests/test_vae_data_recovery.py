import json
import os
import tempfile
import unittest

import app as gestion_app


class VaeDataRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_vae_data_file = gestion_app.VAE_DATA_FILE
        self.original_backup_dir = gestion_app.BACKUP_DIR

        gestion_app.VAE_DATA_FILE = os.path.join(self.temp_dir.name, "data_vae.json")
        gestion_app.BACKUP_DIR = os.path.join(self.temp_dir.name, "backups")
        os.makedirs(gestion_app.BACKUP_DIR, exist_ok=True)

    def tearDown(self):
        gestion_app.VAE_DATA_FILE = self.original_vae_data_file
        gestion_app.BACKUP_DIR = self.original_backup_dir
        self.temp_dir.cleanup()

    def test_recovers_from_backup_when_file_missing(self):
        backup_payload = {"dossiers": [{"id": "D-1"}]}
        backup_name = "data_vae_json.manual.20260101T120000Z.json"
        with open(os.path.join(gestion_app.BACKUP_DIR, backup_name), "w", encoding="utf-8") as f:
            json.dump(backup_payload, f)

        loaded = gestion_app._vae_load_all()

        self.assertEqual(loaded["dossiers"][0]["id"], "D-1")
        self.assertTrue(os.path.exists(gestion_app.VAE_DATA_FILE))

    def test_recovers_from_backup_when_file_corrupted(self):
        with open(gestion_app.VAE_DATA_FILE, "w", encoding="utf-8") as f:
            f.write("{invalid json")

        backup_payload = {"dossiers": [{"id": "D-2"}]}
        backup_name = "data_vae_json.manual.20260101T130000Z.json"
        with open(os.path.join(gestion_app.BACKUP_DIR, backup_name), "w", encoding="utf-8") as f:
            json.dump(backup_payload, f)

        loaded = gestion_app._vae_load_all()

        self.assertEqual(loaded["dossiers"][0]["id"], "D-2")


if __name__ == "__main__":
    unittest.main()
