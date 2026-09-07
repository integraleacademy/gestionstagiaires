import io
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
        self.assertIn("/convention/signed-pdf", download_url)
        self.assertIn("download=1", download_url)
        self.assertNotIn("original-pdf", download_url)

    def test_signed_status_keeps_download_button_when_request_id_is_missing(self):
        trainee = {
            "id": "T-LEGACY-STATE",
            "first_name": "Mikael",
            "last_name": "PETRICCIOLI",
            "convention_aps_signed_at": "2026-07-21T08:27:00Z",
            "convention_signature": {},
        }

        with gestion_app.app.test_request_context():
            status = gestion_app._build_trainee_automation_status(
                {"id": "S-APS", "training_type": "APS"},
                trainee,
                "S-APS",
                trainee["id"],
            )

        self.assertEqual(status["convention"]["status"], "signed")
        self.assertIn("/convention/signed-pdf", status["convention"]["download_url"])
        self.assertIn("download=1", status["convention"]["download_url"])
        self.assertNotIn("download=1", status["convention"]["view_url"])
        self.assertTrue(status["convention"]["can_import_signed_pdf"])
        self.assertIn("/convention/signed-pdf/upload", status["convention"]["signed_pdf_upload_url"])

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

    def test_signed_route_recovers_lost_request_id_from_external_id(self):
        trainee = {
            "id": "T-SIGNED",
            "first_name": "Mikael",
            "last_name": "PETRICCIOLI",
            "convention_aps_signed_at": "2026-07-21T08:27:00Z",
            "convention_signature": {},
        }
        data = {
            "sessions": [{
                "id": "S-VAE",
                "training_type": "DIRIGEANT VAE",
                "trainees": [trainee],
            }]
        }
        recovered_request = {
            "id": "request-found-by-external-id",
            "external_id": gestion_app.make_yousign_external_id("S-VAE", "T-SIGNED"),
            "status": "done",
            "completed_at": "2026-07-21T08:27:00Z",
        }

        with tempfile.TemporaryDirectory() as directory:
            signed_dir = os.path.join(directory, "generated_documents", "yousign_signed_conventions")
            os.makedirs(signed_dir, exist_ok=True)
            recovered_path = os.path.join(signed_dir, "convention_formation_aps_t-signed_signee.pdf")

            def recover_signed_pdf(_request_id, _trainee_id):
                with open(recovered_path, "wb") as recovered_pdf:
                    recovered_pdf.write(b"%PDF-1.4\nrecovered by external id")
                return recovered_path

            with patch.object(gestion_app, "PERSIST_DIR", directory), \
                 patch.object(gestion_app, "YOUSIGN_SIGNED_DIR", signed_dir), \
                 patch.object(gestion_app, "load_data", return_value=data), \
                 patch.object(gestion_app, "save_data") as save_data, \
                 patch.object(gestion_app, "_yousign_is_configured", return_value=True), \
                 patch.object(
                     gestion_app,
                     "_find_completed_yousign_convention_request",
                     return_value=recovered_request,
                 ) as find_request, \
                 patch.object(
                     gestion_app,
                     "_download_yousign_signed_pdf",
                     side_effect=recover_signed_pdf,
                 ) as download_signed_pdf:
                response = self.client.get(
                    "/admin/sessions/S-VAE/stagiaires/T-SIGNED/convention/signed-pdf?download=1"
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "application/pdf")
                self.assertTrue(response.data.startswith(b"%PDF-1.4"))
                self.assertIn("attachment", response.headers["Content-Disposition"])
                find_request.assert_called_once_with("S-VAE", "T-SIGNED", trainee)
                download_signed_pdf.assert_called_once_with(
                    "request-found-by-external-id",
                    "T-SIGNED",
                )
                save_data.assert_called_once_with(data)
                self.assertEqual(
                    trainee["convention_signature"]["signature_request_id"],
                    "request-found-by-external-id",
                )

    def test_external_id_lookup_uses_done_filter_and_latest_match(self):
        external_id = gestion_app.make_yousign_external_id("S-APS", "T-1")
        payload = {
            "data": [
                {"id": "older", "external_id": external_id, "status": "done", "completed_at": "2026-07-20T10:00:00Z"},
                {"id": "latest", "external_id": external_id, "status": "done", "completed_at": "2026-07-21T10:00:00Z"},
                {"id": "ongoing", "external_id": external_id, "status": "ongoing", "completed_at": "2026-07-22T10:00:00Z"},
            ]
        }

        with patch.object(gestion_app, "_yousign_json", return_value=payload) as yousign_json:
            result = gestion_app._find_completed_yousign_convention_request("S-APS", "T-1")

        self.assertEqual(result["id"], "latest")
        yousign_json.assert_called_once_with(
            "GET",
            "/signature_requests",
            params={
                "external_id[eq]": external_id,
                "status[eq]": "done",
                "limit": 100,
            },
        )

    def test_legacy_yousign_lookup_verifies_signer_email(self):
        trainee = {
            "id": "T-OLD",
            "first_name": "Mikael",
            "last_name": "PETRICCIOLI",
            "email": "mikaelpetriccioli@gmail.com",
            "convention_aps_signed_at": "2026-07-21T08:27:00Z",
            "convention_signature": {},
        }
        external_id = gestion_app.make_yousign_external_id("S-APS", "T-OLD")
        legacy_request = {
            "id": "legacy-request",
            "name": "Convention formation - APS - Mikael PETRICCIOLI",
            "status": "done",
            "completed_at": "2026-07-21T08:27:00Z",
        }

        def yousign_response(_method, path, **kwargs):
            if path.endswith("/signers"):
                return {"data": [{"info": {"email": "mikaelpetriccioli@gmail.com"}}]}
            params = kwargs["params"]
            if "external_id[eq]" in params:
                self.assertEqual(params["external_id[eq]"], external_id)
                return {"data": []}
            self.assertEqual(params["q"], "Mikael PETRICCIOLI")
            self.assertEqual(params["status[eq]"], "done")
            self.assertEqual(params["source[in]"], "public_api,app")
            return {"data": [legacy_request]}

        with patch.object(gestion_app, "_yousign_json", side_effect=yousign_response):
            result = gestion_app._find_completed_yousign_convention_request(
                "S-APS",
                "T-OLD",
                trainee,
            )

        self.assertEqual(result["id"], "legacy-request")

    def test_legacy_yousign_lookup_scans_date_for_generic_request_name(self):
        trainee = {
            "id": "T-OLD",
            "first_name": "Mikael",
            "last_name": "PETRICCIOLI",
            "email": "mikaelpetriccioli@gmail.com",
            "convention_aps_signed_at": "2026-07-21T08:27:00Z",
            "convention_signature": {},
        }
        generic_request = {
            "id": "generic-request",
            "name": "Signature du dossier stagiaire",
            "status": "done",
            "completed_at": "2026-07-21T08:27:00Z",
        }

        def yousign_response(_method, path, **kwargs):
            if path.endswith("/signers"):
                return {"data": [{"info": {"email": "mikaelpetriccioli@gmail.com"}}]}
            if path.endswith("/documents"):
                return {"data": [{"name": "Convention de formation professionnelle.pdf"}]}
            params = kwargs["params"]
            if "external_id[eq]" in params or "q" in params:
                return {"data": []}
            self.assertEqual(params["status[eq]"], "done")
            self.assertEqual(params["source[in]"], "public_api,app")
            self.assertEqual(params["completed_at[between]"], "2026-07-19,2026-07-23")
            return {"data": [generic_request]}

        with patch.object(gestion_app, "_yousign_json", side_effect=yousign_response):
            result = gestion_app._find_completed_yousign_convention_request(
                "S-APS",
                "T-OLD",
                trainee,
            )

        self.assertEqual(result["id"], "generic-request")

    def test_missing_legacy_pdf_records_visible_recovery_error(self):
        trainee = {
            "id": "T-OLD",
            "email": "mikaelpetriccioli@gmail.com",
            "convention_legacy_signed": True,
            "convention_legacy_signed_at": "2026-07-21T08:27:00Z",
            "convention_signature": {"status": "done", "legacy_signed": True},
        }
        data = {
            "sessions": [{
                "id": "S-APS",
                "training_type": "APS",
                "trainees": [trainee],
            }]
        }

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data") as save_data, \
             patch.object(gestion_app, "_yousign_is_configured", return_value=True), \
             patch.object(gestion_app, "_find_completed_yousign_convention_request", return_value={}):
            response = self.client.get(
                "/admin/sessions/S-APS/stagiaires/T-OLD/convention/signed-pdf"
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("ancien logiciel", trainee["convention_signature"]["signed_pdf_recovery_error"])
        save_data.assert_called_once_with(data)

    def test_admin_can_import_and_then_download_a_legacy_signed_pdf(self):
        trainee = {
            "id": "T-OLD",
            "convention_legacy_signed": True,
            "convention_legacy_signed_at": "2026-07-21T08:27:00Z",
            "convention_signature": {
                "status": "done",
                "legacy_signed": True,
                "signed_pdf_recovery_error": "Document introuvable",
            },
        }
        data = {
            "sessions": [{
                "id": "S-APS",
                "training_type": "APS",
                "trainees": [trainee],
            }]
        }

        with tempfile.TemporaryDirectory() as directory:
            signed_dir = os.path.join(directory, "generated_documents", "yousign_signed_conventions")
            with patch.object(gestion_app, "PERSIST_DIR", directory), \
                 patch.object(gestion_app, "YOUSIGN_SIGNED_DIR", signed_dir), \
                 patch.object(gestion_app, "load_data", return_value=data), \
                 patch.object(gestion_app, "save_data") as save_data:
                response = self.client.post(
                    "/admin/sessions/S-APS/stagiaires/T-OLD/convention/signed-pdf/upload",
                    data={
                        "signed_pdf": (
                            io.BytesIO(b"%PDF-1.4\nlegacy signed convention"),
                            "convention-signee.pdf",
                        )
                    },
                    content_type="multipart/form-data",
                )

                self.assertEqual(response.status_code, 302)
                signed_path = trainee["convention_signature"]["signed_pdf_path"]
                self.assertTrue(os.path.isfile(signed_path))
                self.assertEqual(trainee["convention_signature"]["signed_pdf_source"], "manual_upload")
                self.assertNotIn("signed_pdf_recovery_error", trainee["convention_signature"])
                save_data.assert_called_once_with(data)

                download = self.client.get(
                    "/admin/sessions/S-APS/stagiaires/T-OLD/convention/signed-pdf?download=1"
                )

                self.assertEqual(download.status_code, 200)
                self.assertEqual(download.mimetype, "application/pdf")
                self.assertIn("attachment", download.headers["Content-Disposition"])

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
            self.assertEqual(os.listdir(directory), [])


if __name__ == "__main__":
    unittest.main()
