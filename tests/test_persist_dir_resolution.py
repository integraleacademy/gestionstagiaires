import json
import os
import tempfile
import unittest

import app as gestion_app


class PersistDirResolutionTests(unittest.TestCase):
    def test_scores_directory_with_existing_stagiaire_and_vae_data(self):
        with tempfile.TemporaryDirectory() as empty_dir, tempfile.TemporaryDirectory() as data_dir:
            with open(os.path.join(data_dir, "data.json"), "w", encoding="utf-8") as f:
                json.dump({"sessions": [{"id": "S1"}]}, f)
            with open(os.path.join(data_dir, "data_vae.json"), "w", encoding="utf-8") as f:
                json.dump({"dossiers": [{"id": "D1"}]}, f)

            self.assertGreater(
                gestion_app._persist_dir_data_score(data_dir),
                gestion_app._persist_dir_data_score(empty_dir),
            )

    def test_scores_backups_when_main_file_is_missing(self):
        with tempfile.TemporaryDirectory() as empty_dir, tempfile.TemporaryDirectory() as backup_dir_root:
            backups = os.path.join(backup_dir_root, "backups")
            os.makedirs(backups, exist_ok=True)
            with open(os.path.join(backups, "data_json.manual.20260101T120000Z.json"), "w", encoding="utf-8") as f:
                json.dump({"sessions": [{"id": "S1"}]}, f)

            self.assertGreater(
                gestion_app._persist_dir_data_score(backup_dir_root),
                gestion_app._persist_dir_data_score(empty_dir),
            )

    def test_default_resolution_prefers_var_data_when_writable(self):
        original_probe = gestion_app._is_writable_directory
        probes = []

        def fake_probe(path):
            probes.append(path)
            return path in {"/var/data", "/data"}

        gestion_app._is_writable_directory = fake_probe
        original = os.environ.get("PERSIST_DIR")
        os.environ.pop("PERSIST_DIR", None)
        try:
            self.assertEqual(gestion_app._resolve_persist_dir(), "/var/data")
            self.assertEqual(probes, ["/var/data"])
        finally:
            gestion_app._is_writable_directory = original_probe
            if original is not None:
                os.environ["PERSIST_DIR"] = original

    def test_bootstrap_copies_json_db_and_uploads_without_overwriting(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as persist_dir:
            original_file = gestion_app.__file__
            gestion_app.__file__ = os.path.join(source_dir, "app.py")
            try:
                with open(os.path.join(source_dir, "data.json"), "w", encoding="utf-8") as f:
                    json.dump({"sessions": [{"id": "legacy"}]}, f)
                with open(os.path.join(source_dir, "legacy.db"), "wb") as f:
                    f.write(b"legacy-db")
                os.makedirs(os.path.join(source_dir, "uploads", "S1", "T1"), exist_ok=True)
                with open(os.path.join(source_dir, "uploads", "S1", "T1", "piece.pdf"), "wb") as f:
                    f.write(b"pdf")
                with open(os.path.join(persist_dir, "data.json"), "w", encoding="utf-8") as f:
                    json.dump({"sessions": [{"id": "persist"}]}, f)

                gestion_app._bootstrap_persistent_storage(persist_dir)

                with open(os.path.join(persist_dir, "data.json"), encoding="utf-8") as f:
                    self.assertEqual(json.load(f)["sessions"][0]["id"], "persist")
                self.assertTrue(os.path.exists(os.path.join(persist_dir, "legacy.db")))
                self.assertTrue(os.path.exists(os.path.join(persist_dir, "uploads", "S1", "T1", "piece.pdf")))
                self.assertTrue(os.path.isdir(os.path.join(persist_dir, "generated_documents", "convocations_aps")))
            finally:
                gestion_app.__file__ = original_file

    def test_configured_persist_dir_still_wins(self):
        with tempfile.TemporaryDirectory() as configured_dir:
            original = os.environ.get("PERSIST_DIR")
            os.environ["PERSIST_DIR"] = configured_dir
            try:
                self.assertEqual(gestion_app._resolve_persist_dir(), configured_dir)
            finally:
                if original is None:
                    os.environ.pop("PERSIST_DIR", None)
                else:
                    os.environ["PERSIST_DIR"] = original


if __name__ == "__main__":
    unittest.main()
