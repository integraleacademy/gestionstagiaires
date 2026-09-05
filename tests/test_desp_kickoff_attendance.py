import os
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch

from pypdf import PdfReader

import app as gestion_app


class DespKickoffAttendanceTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

        self.data = {
            "sessions": [
                {
                    "id": "S-DESP",
                    "name": "DESP initial octobre 2026",
                    "training_type": "DIRIGEANT INITIAL",
                    "date_start": "2026-10-01",
                    "date_end": "2026-11-06",
                    "dirigeant_remote_start": "2026-09-28",
                    "dirigeant_remote_end": "2026-10-16",
                    "trainees": [
                        {
                            "id": "T2",
                            "last_name": "zola",
                            "first_name": "zoé",
                            "email": "zoe@example.test",
                            "phone": "06 22 33 44 55",
                            "documents": [],
                        },
                        {
                            "id": "T1",
                            "last_name": "bernard",
                            "first_name": "alice",
                            "email": "alice@example.test",
                            "phone": "06 11 22 33 44",
                            "documents": [],
                        },
                        {
                            "id": "T3",
                            "last_name": "annulé",
                            "first_name": "stagiaire",
                            "registration_cancelled": True,
                            "documents": [],
                        },
                    ],
                },
                {
                    "id": "S-APS",
                    "name": "APS octobre 2026",
                    "training_type": "APS",
                    "date_start": "2026-10-01",
                    "trainees": [],
                },
                {
                    "id": "S-VAE",
                    "name": "DESP VAE",
                    "training_type": "DIRIGEANT VAE",
                    "date_start": "2026-10-01",
                    "trainees": [],
                },
            ]
        }

    def test_preview_is_a_collective_zoom_sheet_with_official_validation(self):
        with patch.object(gestion_app, "load_data", return_value=self.data):
            response = self.client.get(
                "/admin/sessions/S-DESP/trainees/desp-kickoff-attendance/preview.pdf"
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"%PDF"))
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(response.data)).pages)
        self.assertIn("28/09/2026", text)
        self.assertIn("08h30 à 10h30", text)
        self.assertIn("Visioconférence ZOOM", text)
        self.assertIn("BERNARD Alice", text)
        self.assertIn("ZOLA Zoé", text)
        self.assertNotIn("ANNULÉ", text)
        self.assertIn("Cassandre MENARD", text)
        self.assertIn("Clément VAILLANT", text)
        self.assertIn("CACHET ET SIGNATURE DU CENTRE DE FORMATION", text)

        _pdf, fields = gestion_app._build_desp_kickoff_attendance_pdf(
            self.data["sessions"][0]
        )
        self.assertEqual(set(fields), {"T1", "T2"})
        self.assertEqual(fields["T1"][0]["page"], 1)
        self.assertEqual(fields["T2"][0]["page"], 1)
        self.assertNotEqual(fields["T1"][0]["y"], fields["T2"][0]["y"])

    def test_preview_is_restricted_to_desp_initial(self):
        with patch.object(gestion_app, "load_data", return_value=self.data):
            aps_response = self.client.get(
                "/admin/sessions/S-APS/trainees/desp-kickoff-attendance/preview.pdf"
            )
            vae_response = self.client.get(
                "/admin/sessions/S-VAE/trainees/desp-kickoff-attendance/preview.pdf"
            )

        self.assertEqual(aps_response.status_code, 404)
        self.assertEqual(vae_response.status_code, 404)

    def test_admin_buttons_are_visible_only_for_desp_initial(self):
        with (
            patch.object(gestion_app, "load_data", return_value=self.data),
            patch.object(gestion_app, "save_data"),
            patch.object(gestion_app, "fetch_cnapsv3_tracking_requests", return_value=([], None)),
        ):
            desp_html = self.client.get("/admin/sessions/S-DESP/trainees").get_data(as_text=True)
            aps_html = self.client.get("/admin/sessions/S-APS/trainees").get_data(as_text=True)

        self.assertIn('id="btnPreviewDespKickoffAttendance"', desp_html)
        self.assertIn('id="btnSendDespKickoffAttendance"', desp_html)
        self.assertIn("Envoyer la présence via Yousign", desp_html)
        self.assertNotIn('id="btnPreviewDespKickoffAttendance"', aps_html)
        self.assertNotIn('id="btnSendDespKickoffAttendance"', aps_html)

    def test_yousign_request_has_one_signer_and_one_field_per_trainee(self):
        session_obj = self.data["sessions"][0]
        calls = []
        signer_index = 0

        def fake_yousign_json(method, path, **kwargs):
            nonlocal signer_index
            calls.append((method, path, kwargs))
            if method == "POST" and path == "/signature_requests":
                return {"id": "desp-request-1"}
            if method == "POST" and path.endswith("/documents"):
                return {"id": "desp-document-1"}
            if method == "POST" and path.endswith("/signers"):
                signer_index += 1
                return {"id": f"desp-signer-{signer_index}"}
            if method == "POST" and path.endswith("/activate"):
                return {
                    "signers": [
                        {"id": "desp-signer-1", "signature_link": "https://sign.test/1"},
                        {"id": "desp-signer-2", "signature_link": "https://sign.test/2"},
                    ]
                }
            if method == "GET" and "/signers/" in path:
                signer_id = path.rsplit("/", 1)[-1]
                return {"id": signer_id, "signature_link": f"https://sign.test/{signer_id[-1]}"}
            return {}

        with tempfile.TemporaryDirectory() as directory, patch.object(
            gestion_app, "YOUSIGN_DESP_KICKOFF_DIR", directory
        ), patch.object(
            gestion_app, "_yousign_is_configured", return_value=True
        ), patch.object(
            gestion_app, "_yousign_json", side_effect=fake_yousign_json
        ):
            state = gestion_app.create_yousign_desp_kickoff_attendance_signature(
                session_obj,
                "S-DESP",
            )

        signer_calls = [call for call in calls if call[0] == "POST" and call[1].endswith("/signers")]
        self.assertEqual(len(signer_calls), 2)
        self.assertEqual(signer_calls[0][2]["json"]["info"]["phone_number"], "+33611223344")
        self.assertEqual(signer_calls[1][2]["json"]["info"]["phone_number"], "+33622334455")
        self.assertEqual(signer_calls[0][2]["json"]["fields"][0]["document_id"], "desp-document-1")
        self.assertNotEqual(
            signer_calls[0][2]["json"]["fields"][0]["y"],
            signer_calls[1][2]["json"]["fields"][0]["y"],
        )
        self.assertEqual(state["status"], "ongoing")
        self.assertEqual(len(state["signers"]), 2)
        self.assertTrue(state["provider_signature_embedded"])
        self.assertEqual(state["meeting_location"], "Visioconférence ZOOM")

    def test_yousign_preflight_rejects_missing_contact_before_api_creation(self):
        session_obj = self.data["sessions"][0]
        session_obj["trainees"][0]["phone"] = ""

        with patch.object(
            gestion_app, "_yousign_is_configured", return_value=True
        ), patch.object(gestion_app, "_yousign_json") as yousign_json:
            with self.assertRaisesRegex(RuntimeError, "téléphone mobile"):
                gestion_app.create_yousign_desp_kickoff_attendance_signature(
                    session_obj,
                    "S-DESP",
                )

        yousign_json.assert_not_called()

    def test_send_route_creates_request_emails_every_signer_and_saves(self):
        state = {
            "status": "ongoing",
            "signature_request_id": "desp-request-1",
            "signers": [],
        }

        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(
            gestion_app,
            "create_yousign_desp_kickoff_attendance_signature",
            return_value=state,
        ) as create_request, patch.object(
            gestion_app,
            "send_yousign_desp_kickoff_attendance_emails",
            return_value=(2, []),
        ) as send_emails, patch.object(gestion_app, "save_data") as save_data:
            response = self.client.post(
                "/admin/sessions/S-DESP/trainees/desp-kickoff-attendance/yousign"
            )

        self.assertEqual(response.status_code, 302)
        create_request.assert_called_once()
        send_emails.assert_called_once_with(self.data["sessions"][0], state)
        save_data.assert_called_once()

    def test_signer_webhook_updates_partial_progress_without_closing_request(self):
        session_obj = self.data["sessions"][0]
        session_obj["desp_kickoff_attendance_signature"] = {
            "status": "ongoing",
            "signature_request_id": "desp-request-1",
            "signers": [
                {"signer_id": "signer-1", "status": "ongoing"},
                {"signer_id": "signer-2", "status": "ongoing"},
            ],
        }
        payload = {
            "event_name": "signer.done",
            "event_id": "event-1",
            "data": {
                "signature_request": {"id": "desp-request-1", "status": "ongoing"},
                "signer": {"id": "signer-1"},
            },
        }

        with patch.object(gestion_app, "_verify_yousign_webhook_signature", return_value=True), patch.object(
            gestion_app, "load_data", return_value=self.data
        ), patch.object(gestion_app, "save_data") as save_data:
            response = self.client.post("/webhooks/yousign", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["document_type"], "desp_kickoff")
        self.assertEqual(response.get_json()["status"], "partially_signed")
        self.assertEqual(
            session_obj["desp_kickoff_attendance_signature"]["status"],
            "ongoing",
        )
        self.assertEqual(
            session_obj["desp_kickoff_attendance_signature"]["signers"][0]["status"],
            "done",
        )
        save_data.assert_called_once()

    def test_signature_request_done_webhook_finalizes_collective_sheet(self):
        session_obj = self.data["sessions"][0]
        session_obj["desp_kickoff_attendance_signature"] = {
            "status": "ongoing",
            "signature_request_id": "desp-request-1",
            "signers": [],
        }
        payload = {
            "event_name": "signature_request.done",
            "event_id": "event-final",
            "data": {
                "signature_request": {
                    "id": "desp-request-1",
                    "status": "done",
                }
            },
        }

        with patch.object(gestion_app, "_verify_yousign_webhook_signature", return_value=True), patch.object(
            gestion_app, "load_data", return_value=self.data
        ), patch.object(gestion_app, "save_data") as save_data, patch.object(
            gestion_app, "_mark_yousign_desp_kickoff_signed"
        ) as mark_signed:
            response = self.client.post("/webhooks/yousign", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["document_type"], "desp_kickoff")
        mark_signed.assert_called_once_with(
            session_obj,
            "desp-request-1",
            "event-final",
        )
        save_data.assert_called_once()


if __name__ == "__main__":
    unittest.main()
