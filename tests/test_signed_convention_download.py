import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app as gestion_app


class SignedConventionDownloadTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    @staticmethod
    def _signed_trainee():
        return {
            "id": "T-SIGNED",
            "first_name": "Mikael",
            "last_name": "PETRICCIOLI",
            "convention_signature": {
                "status": "done",
                "signature_request_id": "request-completed-1",
                "signed_at": "2026-09-01T10:00:00Z",
                "signed_pdf_path": "/obsolete-disk/convention-signed.pdf",
                "unsigned_pdf_path": "/obsolete-disk/convention-original.pdf",
            },
        }

    def test_signed_status_links_to_signed_route_when_local_copy_is_missing(self):
        trainee = self._signed_trainee()

        with gestion_app.app.test_request_context():
            status = gestion_app._build_trainee_automation_status(
                {"id": "S-APS", "training_type": "APS"},
                trainee,
                "S-APS",
                trainee["id"],
            )

        download_url = status["convention"]["download_url"]
        self.assertEqual(status["convention"]["status"], "signed")
        self.assertTrue(download_url.endswith("/convention/signed-pdf"))
        self.assertNotIn("original-pdf", download_url)

    def test_signed_route_recovers_missing_pdf_from_yousign_and_serves_it(self):
        trainee = self._signed_trainee()
        data = {
            "sessions": [{
                "id": "S-VAE",
                "training_type": "DIRIGEANT VAE",
                "trainees": [trainee],
            }]
        }

        with tempfile.TemporaryDirectory() as directory:
            signed_dir = os.path.join(directory, "generated_documents", "yousign_signed_conventions")
            os.makedirs(signed_dir, exist_ok=True)
            recovered_path = os.path.join(signed_dir, "convention_formation_aps_t-signed_signee.pdf")

            def recover_signed_pdf(_request_id, _trainee_id):
                with open(recovered_path, "wb") as recovered_pdf:
                    recovered_pdf.write(b"%PDF-1.4\nrecovered signed convention")
                return recovered_path

            with patch.object(gestion_app, "PERSIST_DIR", directory), \
                 patch.object(gestion_app, "YOUSIGN_SIGNED_DIR", signed_dir), \
                 patch.object(gestion_app, "load_data", return_value=data), \
                 patch.object(gestion_app, "save_data") as save_data, \
                 patch.object(gestion_app, "_yousign_is_configured", return_value=True), \
                 patch.object(
                     gestion_app,
                     "_download_yousign_signed_pdf",
                     side_effect=recover_signed_pdf,
                 ) as download_signed_pdf:
                response = self.client.get(
                    "/admin/sessions/S-VAE/stagiaires/T-SIGNED/convention/signed-pdf"
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "application/pdf")
                self.assertTrue(response.data.startswith(b"%PDF-1.4"))
                self.assertIn("convention_formation_aps_t-signed_signee.pdf", response.headers["Content-Disposition"])
                download_signed_pdf.assert_called_once_with("request-completed-1", "T-SIGNED")
                save_data.assert_called_once_with(data)
                self.assertEqual(
                    trainee["convention_signature"]["signed_pdf_path"],
                    recovered_path,
                )

    def test_yousign_download_rejects_an_html_error_page(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(gestion_app, "YOUSIGN_SIGNED_DIR", directory), \
             patch.object(
                 gestion_app,
                 "_yousign_request",
                 return_value=SimpleNamespace(content=b"<!doctype html><title>Error</title>"),
             ):
            with self.assertRaisesRegex(RuntimeError, "PDF signé valide"):
                gestion_app._download_yousign_signed_pdf("request-1", "T-1")

        self.assertEqual(os.listdir(directory) if os.path.isdir(directory) else [], [])


if __name__ == "__main__":
    unittest.main()
