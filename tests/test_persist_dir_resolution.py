import json
import os
import tempfile
import unittest
from pathlib import Path

import app as gestion_app


class PersistDirResolutionTests(unittest.TestCase):
    def test_publish_workflow_provides_a_writable_test_persist_dir(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "notion-work-publish.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "PERSIST_DIR: ${{ runner.temp }}/gestionstagiaires-persist",
            workflow,
        )
        self.assertIn("pytest -q", workflow)

        network_guard = (
            Path(__file__).resolve().parent / "conftest.py"
        ).read_text(encoding="utf-8")
        self.assertIn("block_external_network", network_guard)
        self.assertIn("socket.socket", network_guard)

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
