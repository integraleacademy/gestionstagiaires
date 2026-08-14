import json
from io import BytesIO
import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

import app as gestion_app


class DespBulkDiplomaTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_file = os.path.join(self.temp_dir.name, "data.json")
        self.patchers = [
            patch.object(gestion_app, "DATA_FILE", self.data_file),
            patch.object(gestion_app, "PERSIST_DIR", self.temp_dir.name),
            patch.object(gestion_app, "BACKUP_SNAPSHOT_BEFORE_SAVE", False),
            patch.object(gestion_app, "BACKUP_MIN_INTERVAL_SECONDS", 10**9),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def _write_data(self, payload):
        with open(self.data_file, "w", encoding="utf-8") as output:
            json.dump(payload, output)

    def _read_data(self):
        with open(self.data_file, "r", encoding="utf-8") as source:
            return json.load(source)

    @staticmethod
    def _blank_pdf():
        output = BytesIO()
        pdf = canvas.Canvas(output, pagesize=landscape(A4))
        pdf.drawString(40, 40, "Diplôme DESP")
        pdf.save()
        return output.getvalue()

    def _create_identity_photo(self):
        photo_token = "uploads/DESP-2026/T1/identity.jpg"
        photo_path = os.path.join(self.temp_dir.name, photo_token)
        os.makedirs(os.path.dirname(photo_path), exist_ok=True)
        Image.new("RGB", (350, 450), "#1d4ed8").save(photo_path)
        return photo_token

    def _post_diploma(self, session_id, pdf_bytes):
        return self.client.post(
            f"/api/sessions/{session_id}/diplome/bulk_upload",
            data={
                "send_notifications": "0",
                "files": (BytesIO(pdf_bytes), "Diplome Jean Dupont.pdf"),
            },
            content_type="multipart/form-data",
        )

    def test_desp_detection_covers_initial_and_vae_sessions(self):
        self.assertTrue(gestion_app._is_desp_diploma_session({
            "training_type": "DIRIGEANT INITIAL",
            "name": "Formation DESP",
        }))
        self.assertTrue(gestion_app._is_desp_diploma_session({
            "training_type": "DIRIGEANT VAE",
            "name": "VAE DESP",
        }))
        self.assertFalse(gestion_app._is_desp_diploma_session({
            "training_type": "APS",
            "name": "Formation APS",
        }))

    def test_desp_bulk_import_embeds_identity_photo_before_storing_diploma(self):
        photo_token = self._create_identity_photo()
        self._write_data({
            "sessions": [{
                "id": "DESP-2026",
                "name": "DESP initial 2026",
                "training_type": "DIRIGEANT INITIAL",
                "trainees": [{
                    "id": "T1",
                    "first_name": "Jean",
                    "last_name": "Dupont",
                    "identity_photo": photo_token,
                }],
            }],
        })

        source_pdf = self._blank_pdf()
        response = self._post_diploma("DESP-2026", source_pdf)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["added_count"], 1)
        self.assertEqual(payload["failed"], [])

        saved = self._read_data()
        token = saved["sessions"][0]["trainees"][0]["deliverables"]["diplome"]
        stored_path = os.path.join(self.temp_dir.name, token)
        self.assertTrue(os.path.exists(stored_path))
        with open(stored_path, "rb") as stored_file:
            stored_pdf = stored_file.read()
        self.assertNotEqual(stored_pdf, source_pdf)

        page = PdfReader(BytesIO(stored_pdf)).pages[0]
        xobjects = page["/Resources"].get("/XObject", {})
        image_count = sum(
            1
            for item in xobjects.values()
            if item.get_object().get("/Subtype") == "/Image"
        )
        self.assertGreaterEqual(image_count, 1)

    def test_desp_bulk_import_rejects_diploma_when_identity_photo_is_missing(self):
        self._write_data({
            "sessions": [{
                "id": "DESP-2026",
                "name": "DESP initial 2026",
                "training_type": "DIRIGEANT INITIAL",
                "trainees": [{
                    "id": "T1",
                    "first_name": "Jean",
                    "last_name": "Dupont",
                }],
            }],
        })

        response = self._post_diploma("DESP-2026", self._blank_pdf())

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["added_count"], 0)
        self.assertEqual(len(payload["failed"]), 1)
        self.assertIn("photo d'identité absente", payload["failed"][0]["reason"])
        saved_trainee = self._read_data()["sessions"][0]["trainees"][0]
        self.assertFalse((saved_trainee.get("deliverables") or {}).get("diplome"))

    def test_non_desp_bulk_import_keeps_existing_raw_upload_behavior(self):
        self._write_data({
            "sessions": [{
                "id": "APS-2026",
                "name": "APS 2026",
                "training_type": "APS",
                "trainees": [{
                    "id": "T1",
                    "first_name": "Jean",
                    "last_name": "Dupont",
                }],
            }],
        })

        source_pdf = self._blank_pdf()
        response = self._post_diploma("APS-2026", source_pdf)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["added_count"], 1)
        saved = self._read_data()
        token = saved["sessions"][0]["trainees"][0]["deliverables"]["diplome"]
        with open(os.path.join(self.temp_dir.name, token), "rb") as stored_file:
            self.assertEqual(stored_file.read(), source_pdf)


if __name__ == "__main__":
    unittest.main()
