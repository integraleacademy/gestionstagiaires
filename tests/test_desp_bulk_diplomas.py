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
    def _blank_pdf(text="Diplôme DESP"):
        output = BytesIO()
        pdf = canvas.Canvas(output, pagesize=landscape(A4))
        pdf.drawString(40, 40, text)
        pdf.save()
        return output.getvalue()

    def _create_identity_photo(self):
        photo_token = "uploads/DESP-2026/T1/identity.jpg"
        photo_path = os.path.join(self.temp_dir.name, photo_token)
        os.makedirs(os.path.dirname(photo_path), exist_ok=True)
        Image.new("RGB", (350, 450), "#1d4ed8").save(photo_path)
        return photo_token

    def _post_diploma(
        self,
        session_id,
        pdf_bytes,
        filename="Diplome Jean Dupont.pdf",
        send_notifications=False,
    ):
        return self.client.post(
            f"/api/sessions/{session_id}/diplome/bulk_upload",
            data={
                "send_notifications": "1" if send_notifications else "0",
                "files": (BytesIO(pdf_bytes), filename),
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

    def test_vae_diploma_matches_name_inside_pdf_and_appears_on_admin_and_public_trainee(self):
        photo_token = self._create_identity_photo()
        self._write_data({
            "sessions": [{
                "id": "DESP-2026",
                "name": "VAE DESP 2026",
                "training_type": "DIRIGEANT VAE",
                "trainees": [{
                    "id": "T1",
                    "first_name": "Jean",
                    "last_name": "Dupont",
                    "identity_photo": photo_token,
                    "public_token": "public-jean",
                }],
            }],
        })

        response = self._post_diploma(
            "DESP-2026",
            self._blank_pdf("Diplôme DESP attribué à Jean Dupont"),
            filename="diplome-desp.pdf",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["added_count"], 1)
        saved = self._read_data()
        token = saved["sessions"][0]["trainees"][0]["deliverables"]["diplome"]

        trainee_page = self.client.get("/admin/sessions/DESP-2026/stagiaires/T1")
        self.assertEqual(trainee_page.status_code, 200)
        page_html = trainee_page.get_data(as_text=True)
        self.assertIn("Importé", page_html)
        self.assertIn(token, page_html)

        public_page = self.client.get("/espace/public-jean")
        self.assertEqual(public_page.status_code, 200)
        public_html = public_page.get_data(as_text=True)
        self.assertIn("Télécharger mon diplôme DESP", public_html)
        self.assertIn(f"/espace/public-jean/download/{token}", public_html)

    def test_diploma_is_persisted_before_notifications_are_sent(self):
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
                    "email": "jean.dupont@example.com",
                    "identity_photo": photo_token,
                }],
            }],
        })
        observed_persistence = []

        def fake_email(*args, **kwargs):
            trainee = self._read_data()["sessions"][0]["trainees"][0]
            observed_persistence.append(bool((trainee.get("deliverables") or {}).get("diplome")))
            return False

        with patch.object(gestion_app, "brevo_send_email", side_effect=fake_email), patch.object(
            gestion_app,
            "brevo_send_sms",
            return_value=False,
        ):
            response = self._post_diploma(
                "DESP-2026",
                self._blank_pdf(),
                send_notifications=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["added_count"], 1)
        self.assertEqual(observed_persistence, [True])

    def test_vae_parchemin_bulk_import_still_persists_on_admin_trainee(self):
        photo_token = self._create_identity_photo()
        self._write_data({
            "sessions": [{
                "id": "DESP-2026",
                "name": "VAE DESP 2026",
                "training_type": "DIRIGEANT VAE",
                "trainees": [{
                    "id": "T1",
                    "first_name": "Jean",
                    "last_name": "Dupont",
                    "identity_photo": photo_token,
                    "public_token": "public-jean",
                }],
            }],
        })

        response = self.client.post(
            "/api/sessions/DESP-2026/parchemin/bulk_upload",
            data={
                "send_notifications": "0",
                "files": (
                    BytesIO(self._blank_pdf("Diplôme DESP attribué à Jean Dupont")),
                    "parchemin.pdf",
                ),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["added_count"], 1)
        saved = self._read_data()
        token = saved["sessions"][0]["trainees"][0]["deliverables"]["parchemin"]
        trainee_page = self.client.get("/admin/sessions/DESP-2026/stagiaires/T1")
        self.assertEqual(trainee_page.status_code, 200)
        self.assertIn(token, trainee_page.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
