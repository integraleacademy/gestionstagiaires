"""Regression coverage: DESP Zoom downloads must not wait for all signers."""
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app as gestion_app


PDF = b"%PDF-1.7\nYousign original signed bytes - do not rewrite\n%%EOF\n"
URL = "/admin/sessions/S-DESP/trainees/desp-kickoff-attendance/signed.pdf"


class DespZoomDownloadRegressionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(gestion_app, "YOUSIGN_DESP_KICKOFF_SIGNED_DIR", self.directory))
        self.state = {
            "status": "ongoing",
            "signature_request_id": "request-desp",
            "signers": [
                {"signer_id": "signer-1", "trainee_id": "T1", "status": "done"},
                {"signer_id": "signer-2", "trainee_id": "T2", "status": "ongoing"},
            ],
        }
        self.session = {
            "id": "S-DESP", "name": "DESP initial test", "training_type": "DIRIGEANT INITIAL",
            "date_start": "2026-09-01", "date_end": "2026-10-16", "trainees": [],
            "desp_kickoff_attendance_signature": self.state,
        }
        self.data = {"sessions": [self.session]}
        self.load = self.stack.enter_context(patch.object(gestion_app, "load_data", return_value=self.data))
        self.save = self.stack.enter_context(patch.object(gestion_app, "save_data"))
        self.configured = self.stack.enter_context(patch.object(gestion_app, "_yousign_is_configured", return_value=True))
        self.remote = self.stack.enter_context(patch.object(gestion_app, "_yousign_json", return_value={"status": "ongoing"}))
        self.download = self.stack.enter_context(patch.object(gestion_app, "_yousign_request", return_value=SimpleNamespace(content=PDF)))
        self.create_request = self.stack.enter_context(patch.object(gestion_app, "create_yousign_desp_kickoff_attendance_signature"))
        self.send_emails = self.stack.enter_context(patch.object(gestion_app, "send_yousign_desp_kickoff_attendance_emails"))
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def tearDown(self):
        self.create_request.assert_not_called()
        self.send_emails.assert_not_called()

    def cached_pdf(self, content=PDF):
        path = Path(self.directory) / "cached-signed.pdf"
        path.write_bytes(content)
        self.state["signed_pdf_path"] = str(path)
        return path

    def assert_pdf_download(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, PDF)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        self.assertIn("no-store", response.headers["Cache-Control"])
        response.close()

    def test_partial_signatures_download_original_current_pdf(self):
        response = self.client.get(URL)
        self.assert_pdf_download(response)
        self.download.assert_called_once_with(
            "GET", "/signature_requests/request-desp/documents/download",
            params={"version": "current", "archive": "false"},
            headers={"Accept": "application/pdf"},
        )
        self.assertEqual(self.state["status"], "ongoing")
        self.assertEqual(self.state["signers"][1]["status"], "ongoing")
        self.assertNotIn("signed_pdf_path", self.state)

    def test_download_does_not_depend_on_stale_local_signer_count(self):
        for signer in self.state["signers"]:
            signer["status"] = "ongoing"
        self.assert_pdf_download(self.client.get(URL))
        self.assertEqual(self.state["status"], "ongoing")

    def test_final_cached_document_works_offline(self):
        self.state["status"] = "done"
        self.cached_pdf()
        self.configured.return_value = False
        self.assert_pdf_download(self.client.get(URL))
        self.remote.assert_not_called()
        self.download.assert_not_called()

    def test_missing_final_archive_is_recovered(self):
        self.state.update(status="done", signed_pdf_path=str(Path(self.directory) / "missing.pdf"))
        self.remote.return_value = {"status": "done"}
        self.assert_pdf_download(self.client.get(URL))
        self.assertEqual(self.download.call_args.kwargs["params"]["version"], "completed")
        self.assertTrue(Path(self.state["signed_pdf_path"]).is_file())
        self.assertEqual(Path(self.state["signed_pdf_path"]).read_bytes(), PDF)
        self.save.assert_called()

    def test_final_recovery_does_not_duplicate_trainee_history(self):
        self.state["status"] = "done"
        self.session["trainees"] = [{"id": "T1", "documents": []}]
        self.remote.return_value = {"status": "done"}
        with patch.object(gestion_app, "append_trainee_history_event") as history:
            self.assert_pdf_download(self.client.get(URL))
        history.assert_not_called()

    def test_missed_completion_webhook_is_reconciled(self):
        self.remote.return_value = {"status": "done"}
        self.assert_pdf_download(self.client.get(URL))
        self.assertEqual(self.state["status"], "done")
        self.assertEqual(self.download.call_args.kwargs["params"]["version"], "completed")
        self.assertTrue(all(signer["status"] == "done" for signer in self.state["signers"]))

    def test_error_status_can_recover_without_new_signature_request(self):
        self.state.update(status="error", last_error="temporary failure")
        self.remote.return_value = {"status": "done"}
        self.assert_pdf_download(self.client.get(URL))
        self.assertEqual(self.state["status"], "done")
        self.assertEqual(self.state["last_error"], "")

    def test_missed_signer_webhook_updates_count_without_marking_everyone_done(self):
        self.state["signers"][0]["status"] = "ongoing"
        self.remote.return_value = {
            "status": "ongoing",
            "signers": [{"id": "signer-1", "status": "done"}, {"id": "signer-2", "status": "ongoing"}],
        }
        self.assertTrue(gestion_app._refresh_yousign_desp_kickoff_status_if_pending(self.session))
        view = gestion_app._desp_kickoff_attendance_view(self.session)
        self.assertEqual(view["signed_count"], 1)
        self.assertFalse(view["is_done"])

    def test_refresh_never_downgrades_confirmed_signer(self):
        self.remote.return_value = {"status": "ongoing", "signers": [{"id": "signer-1", "status": "ongoing"}]}
        gestion_app._refresh_yousign_desp_kickoff_status_if_pending(self.session)
        self.assertEqual(self.state["signers"][0]["status"], "done")

    def test_status_api_failure_still_allows_current_pdf_download(self):
        self.remote.side_effect = RuntimeError("temporary status error")
        self.assert_pdf_download(self.client.get(URL))
        self.assertEqual(self.state["status"], "ongoing")

    def test_partial_download_is_not_served_from_stale_cache(self):
        self.cached_pdf(b"%PDF-1.7\nstale\n%%EOF")
        self.assert_pdf_download(self.client.get(URL))
        self.download.assert_called_once()
        self.assertEqual(self.state["status"], "ongoing")

    def test_invalid_remote_pdf_returns_message_without_false_completion(self):
        self.download.return_value = SimpleNamespace(content=b"PK\x03\x04not-a-pdf")
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/admin/sessions/S-DESP/trainees"))
        self.assertEqual(self.state["status"], "ongoing")
        self.assertFalse(list(Path(self.directory).glob("*.pdf")))
        with self.client.session_transaction() as session:
            self.assertIn("Impossible de télécharger", str(session.get("_flashes")))

    def test_invalid_completed_response_never_overwrites_existing_pdf(self):
        original = gestion_app._download_yousign_desp_kickoff_signed_pdf("request-desp", "S-DESP")
        self.download.return_value = SimpleNamespace(content=b"<html>gateway error</html>")
        with self.assertRaisesRegex(RuntimeError, "PDF valide"):
            gestion_app._download_yousign_desp_kickoff_signed_pdf("request-desp", "S-DESP")
        self.assertEqual(Path(original).read_bytes(), PDF)

    def test_invalid_cached_pdf_is_recovered(self):
        self.state["status"] = "done"
        self.cached_pdf(b"not a PDF")
        self.remote.return_value = {"status": "done"}
        self.assert_pdf_download(self.client.get(URL))
        self.download.assert_called_once()

    def test_path_outside_signed_directory_is_never_served(self):
        outside = self.stack.enter_context(tempfile.TemporaryDirectory())
        path = Path(outside) / "private.pdf"
        path.write_bytes(PDF)
        self.state.update(status="done", signature_request_id="", signed_pdf_path=str(path))
        self.assertEqual(self.client.get(URL).status_code, 404)
        self.download.assert_not_called()

    def test_symlink_outside_signed_directory_is_never_served(self):
        outside = self.stack.enter_context(tempfile.TemporaryDirectory())
        target = Path(outside) / "private.pdf"
        target.write_bytes(PDF)
        link = Path(self.directory) / "link.pdf"
        link.symlink_to(target)
        self.state.update(status="done", signature_request_id="", signed_pdf_path=str(link))
        self.assertEqual(self.client.get(URL).status_code, 404)

    def test_without_yousign_request_returns_404(self):
        self.session.pop("desp_kickoff_attendance_signature")
        self.assertEqual(self.client.get(URL).status_code, 404)
        self.download.assert_not_called()

    def test_other_training_types_are_rejected(self):
        for training in ("APS", "DIRIGEANT VAE", "SSIAP 1"):
            with self.subTest(training=training):
                self.session["training_type"] = training
                self.session["name"] = training
                self.assertEqual(self.client.get(URL).status_code, 404)
        self.download.assert_not_called()

    def test_download_requires_admin_login(self):
        anonymous = gestion_app.app.test_client()
        self.assertIn(anonymous.get(URL).status_code, (302, 401, 403))
        self.load.assert_not_called()
        self.download.assert_not_called()

    def test_read_only_admin_can_download_without_sending(self):
        with self.client.session_transaction() as session:
            session["admin_role"] = "readonly"
        self.assert_pdf_download(self.client.get(URL))

    def test_view_allows_download_before_all_signatures(self):
        view = gestion_app._desp_kickoff_attendance_view(self.session)
        self.assertTrue(view["can_download_pdf"])
        self.assertFalse(view["is_done"])
        self.assertFalse(view["has_signed_pdf"])

    def test_view_does_not_trust_a_missing_cached_path(self):
        self.state.update(status="done", signed_pdf_path=str(Path(self.directory) / "missing.pdf"))
        view = gestion_app._desp_kickoff_attendance_view(self.session)
        self.assertFalse(view["has_signed_pdf"])
        self.assertTrue(view["can_download_pdf"])

    def test_template_shows_download_for_partial_request(self):
        with patch.object(gestion_app, "fetch_cnapsv3_tracking_requests", return_value=([], None)):
            response = self.client.get("/admin/sessions/S-DESP/trainees")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="btnSignedDespKickoffAttendance"', html)
        self.assertIn("Télécharger avec les signatures reçues", html)
        self.assertIn("Aperçu vierge présence Zoom", html)
        self.assertIn("1/2 signature(s)", html)

    def test_completed_request_without_archive_does_not_offer_new_signature_request(self):
        self.state["status"] = "done"
        self.remote.side_effect = RuntimeError("temporarily unavailable")
        with patch.object(gestion_app, "fetch_cnapsv3_tracking_requests", return_value=([], None)):
            response = self.client.get("/admin/sessions/S-DESP/trainees")
        html = response.get_data(as_text=True)
        self.assertIn('id="btnSignedDespKickoffAttendance"', html)
        self.assertNotIn('id="btnSendDespKickoffAttendance"', html)


if __name__ == "__main__":
    unittest.main()
