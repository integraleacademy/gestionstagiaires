import hashlib
import os
import re
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

import app


class ApsConvocationGenerationTests(unittest.TestCase):
    def test_yousign_external_id_uses_allowed_characters_without_colons(self):
        external_id = app.make_yousign_external_id("2ebec35a:bad", "TRN-2E16579A/2026")

        self.assertEqual(external_id, "convocation_2ebec35a_bad_TRN-2E16579A_2026")
        self.assertNotIn(":", external_id)

    def test_yousign_signature_request_payload_uses_sanitized_external_id(self):
        session = {"id": "2ebec35a", "training_type": "APS", "name": "Formation APS"}
        trainee = {
            "id": "TRN-2E16579A",
            "email": "stagiaire@example.com",
            "first_name": "Jean",
            "last_name": "Dupont",
            "phone": "06 12 34 56 78",
        }
        calls = []

        def fake_yousign_json(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if method == "POST" and path == "/signature_requests":
                return {"id": "sig-req-1"}
            if path.endswith("/documents"):
                return {"id": "doc-1"}
            if method == "POST" and path.endswith("/signers"):
                return {"id": "signer-1", "signature_link": "https://example.test/sign"}
            if method == "GET" and path.endswith("/signers/signer-1"):
                return {"id": "signer-1", "signature_authentication_mode": "otp_sms", "signature_link": "https://example.test/sign"}
            if path.endswith("/activate"):
                return {"signature_link": "https://example.test/sign"}
            return {}

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "convocation.pdf")
            docx_path = os.path.join(tmpdir, "convocation.docx")
            with open(pdf_path, "wb") as fh:
                fh.write(b"pdf")
            with open(docx_path, "wb") as fh:
                fh.write(b"docx")

            with mock.patch.object(app, "_yousign_is_configured", return_value=True), \
                 mock.patch.object(app, "_generate_aps_convention_files", return_value=(docx_path, pdf_path)), \
                 mock.patch.object(app, "_docx_text_contains_yousign_smart_anchor", return_value=True), \
                 mock.patch.object(app, "_prepare_yousign_pdf_and_fields", return_value=(pdf_path, [{"type": "signature", "page": 1, "x": 100, "y": 200, "width": 160, "height": 60}])), \
                 mock.patch.object(app, "_yousign_json", side_effect=fake_yousign_json):
                state = app.create_yousign_convention_signature(session, trainee, "2ebec35a", "TRN-2E16579A")

        signature_request_call = calls[0]
        self.assertEqual(signature_request_call[1], "/signature_requests")
        self.assertEqual(
            signature_request_call[2]["json"]["external_id"],
            "convocation_2ebec35a_TRN-2E16579A",
        )
        document_call = next(call for call in calls if call[1].endswith("/documents"))
        self.assertEqual(document_call[2]["data"].get("parse_anchors"), "false")
        signer_call = next(call for call in calls if call[1].endswith("/signers"))
        self.assertEqual(signer_call[2]["json"]["fields"][0]["type"], "signature")
        self.assertEqual(signer_call[2]["json"]["fields"][0]["layout"], "detailed")
        self.assertEqual(signer_call[2]["json"]["fields"][0]["date_time_format"], "dd/MM/yyyy")
        self.assertEqual(len(signer_call[2]["json"]["fields"]), 1)
        self.assertEqual(signer_call[2]["json"]["signature_authentication_mode"], "otp_sms")
        self.assertNotEqual(signer_call[2]["json"].get("signature_authentication_mode"), "no_otp")
        self.assertEqual(signer_call[2]["json"]["info"]["phone_number"], "+33612345678")
        self.assertTrue(any(call[0] == "GET" and call[1].endswith("/signers/signer-1") for call in calls))
        self.assertEqual(state["external_id"], "convocation_2ebec35a_TRN-2E16579A")
        self.assertEqual(state["status"], "ongoing")

    def test_force_new_cancels_pending_request_before_creating_another_one(self):
        session = {"id": "2ebec35a", "training_type": "APS", "name": "Formation APS"}
        trainee = {
            "id": "TRN-2E16579A",
            "email": "stagiaire@example.com",
            "first_name": "Jean",
            "last_name": "Dupont",
            "phone": "06 12 34 56 78",
            "convention_signature": {"status": "ongoing", "signature_request_id": "old-req", "signature_link": "https://old.test"},
        }
        calls = []

        def fake_yousign_json(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if path == "/signature_requests/old-req/cancel":
                return {}
            if method == "POST" and path == "/signature_requests":
                return {"id": "new-req"}
            if path.endswith("/documents"):
                return {"id": "doc-1"}
            if method == "POST" and path.endswith("/signers"):
                return {"id": "signer-1", "signature_link": "https://new.test/sign"}
            if method == "GET" and path.endswith("/signers/signer-1"):
                return {"id": "signer-1", "signature_authentication_mode": "otp_sms", "signature_link": "https://new.test/sign"}
            if path.endswith("/activate"):
                return {"signature_link": "https://new.test/sign"}
            return {}

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "convention.pdf")
            docx_path = os.path.join(tmpdir, "convention.docx")
            with open(pdf_path, "wb") as fh:
                fh.write(b"pdf")
            with open(docx_path, "wb") as fh:
                fh.write(b"docx")

            with mock.patch.object(app, "_yousign_is_configured", return_value=True), \
                 mock.patch.object(app, "_generate_aps_convention_files", return_value=(docx_path, pdf_path)), \
                 mock.patch.object(app, "_docx_text_contains_yousign_smart_anchor", return_value=True), \
                 mock.patch.object(app, "_prepare_yousign_pdf_and_fields", return_value=(pdf_path, [{"type": "signature", "page": 1, "x": 100, "y": 200, "width": 160, "height": 60}])), \
                 mock.patch.object(app, "_yousign_json", side_effect=fake_yousign_json):
                state = app.create_yousign_convention_signature(session, trainee, "2ebec35a", "TRN-2E16579A", force_new=True)

        self.assertEqual(calls[0][1], "/signature_requests/old-req/cancel")
        self.assertEqual(state["signature_request_id"], "new-req")
        self.assertEqual(state["signature_link"], "https://new.test/sign")
        self.assertEqual(trainee["convention_signature_history"][0]["signature_request_id"], "old-req")

    def test_signed_convention_can_be_regenerated_from_automation_status(self):
        session = {"id": "session-1", "training_type": "APS", "name": "Formation APS"}
        trainee = {
            "id": "trainee-1",
            "first_name": "Jean",
            "last_name": "Dupont",
            "convention_signature": {"status": "done", "signature_request_id": "signed-req", "signed_at": "2026-07-01T10:00:00Z", "signed_pdf_path": "/tmp/signed.pdf"},
            "convention_aps_status": "signed",
        }

        with app.app.test_request_context():
            status = app._build_trainee_automation_status(session, trainee, "session-1", "trainee-1")

        self.assertEqual(status["convention"]["status"], "signed")
        self.assertTrue(status["convention"]["can_send"])

    def test_force_new_archives_signed_request_before_creating_another_one(self):
        session = {"id": "2ebec35a", "training_type": "APS", "name": "Formation APS"}
        trainee = {
            "id": "TRN-2E16579A",
            "email": "stagiaire@example.com",
            "first_name": "Jean",
            "last_name": "Dupont",
            "phone": "06 12 34 56 78",
            "convention_signature": {"status": "done", "signature_request_id": "signed-req", "signed_at": "2026-07-01T10:00:00Z", "signed_pdf_path": "/tmp/signed.pdf"},
            "convention_aps_status": "signed",
        }
        calls = []

        def fake_yousign_json(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if method == "POST" and path == "/signature_requests":
                return {"id": "new-req"}
            if path.endswith("/documents"):
                return {"id": "doc-1"}
            if method == "POST" and path.endswith("/signers"):
                return {"id": "signer-1", "signature_link": "https://new.test/sign"}
            if method == "GET" and path.endswith("/signers/signer-1"):
                return {"id": "signer-1", "signature_authentication_mode": "otp_sms", "signature_link": "https://new.test/sign"}
            if path.endswith("/activate"):
                return {"signature_link": "https://new.test/sign"}
            return {}

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "convention.pdf")
            docx_path = os.path.join(tmpdir, "convention.docx")
            with open(pdf_path, "wb") as fh:
                fh.write(b"pdf")
            with open(docx_path, "wb") as fh:
                fh.write(b"docx")

            with mock.patch.object(app, "_yousign_is_configured", return_value=True), \
                 mock.patch.object(app, "_generate_aps_convention_files", return_value=(docx_path, pdf_path)), \
                 mock.patch.object(app, "_docx_text_contains_yousign_smart_anchor", return_value=True), \
                 mock.patch.object(app, "_prepare_yousign_pdf_and_fields", return_value=(pdf_path, [{"type": "signature", "page": 1, "x": 100, "y": 200, "width": 160, "height": 60}])), \
                 mock.patch.object(app, "_yousign_json", side_effect=fake_yousign_json):
                state = app.create_yousign_convention_signature(session, trainee, "2ebec35a", "TRN-2E16579A", force_new=True)

        self.assertFalse(any(call[1] == "/signature_requests/signed-req/cancel" for call in calls))
        self.assertEqual(trainee["convention_signature_history"][0]["signature_request_id"], "signed-req")
        self.assertEqual(state["signature_request_id"], "new-req")



    def test_yousign_environment_url_must_match_configured_environment(self):
        with mock.patch.dict(app.os.environ, {
            "YOUSIGN_ENV": "production",
            "YOUSIGN_BASE_URL": "https://api-sandbox.yousign.app/v3",
        }, clear=False):
            with self.assertRaisesRegex(RuntimeError, "ne correspond pas à l’environnement production"):
                app._yousign_base_url()

        with mock.patch.dict(app.os.environ, {
            "YOUSIGN_ENV": "sandbox",
            "YOUSIGN_BASE_URL": "https://api-sandbox.yousign.app/v3",
        }, clear=False):
            self.assertEqual(app._yousign_environment(), "sandbox")

    def test_yousign_production_base_url_is_accepted_without_environment_flag(self):
        with mock.patch.dict(app.os.environ, {
            "YOUSIGN_BASE_URL": "https://api.yousign.app/v3",
        }, clear=True):
            self.assertEqual(app._yousign_environment(), "production")

    def test_yousign_signature_creation_requires_valid_sms_phone(self):
        session = {"id": "2ebec35a", "training_type": "APS", "name": "Formation APS"}
        trainee = {
            "id": "TRN-2E16579A",
            "email": "stagiaire@example.com",
            "first_name": "Jean",
            "last_name": "Dupont",
            "phone": "12345",
        }

        with mock.patch.object(app, "_yousign_is_configured", return_value=True), \
             mock.patch.object(app, "_generate_aps_convention_files") as generate_files:
            with self.assertRaisesRegex(RuntimeError, "numéro de téléphone manquant ou invalide"):
                app.create_yousign_convention_signature(session, trainee, "2ebec35a", "TRN-2E16579A")

        generate_files.assert_not_called()

    def test_generation_does_not_require_every_aps_variable_in_template(self):
        session = {
            "id": "session-1",
            "training_type": "APS",
            "name": "Formation APS",
            "date_start": "2026-07-08",
            "date_end": "2026-08-12",
            "exam_date": "2026-08-13",
        }
        trainee = {
            "id": "trainee-1",
            "email": "stagiaire@example.com",
            "first_name": "Jean",
            "last_name": "Dupont",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "convocationaps.docx")
            with zipfile.ZipFile(template_path, "w") as zf:
                zf.writestr("word/document.xml", "<w:document><w:body>{{prenom}} {{nom}} {{s1|signature|160|60}}</w:body></w:document>")

            output_dir = os.path.join(tmpdir, "generated")

            def fake_render(_template_path, output_docx_path, context):
                self.assertNotEqual(_template_path, template_path)
                self.assertEqual(context["prenom"], "Jean")
                self.assertEqual(context["nom"], "DUPONT")
                os.makedirs(os.path.dirname(output_docx_path), exist_ok=True)
                with zipfile.ZipFile(_template_path) as zin, zipfile.ZipFile(output_docx_path, "w") as zout:
                    xml = zin.read("word/document.xml").decode("utf-8").replace("{{prenom}}", context["prenom"]).replace("{{nom}}", context["nom"])
                    zout.writestr("word/document.xml", xml)

            def fake_run(command, check, capture_output, text, timeout):
                self.assertTrue(check)
                self.assertIn("--convert-to", command)
                docx_path = command[-1]
                pdf_path = os.path.splitext(docx_path)[0] + ".pdf"
                with open(pdf_path, "wb") as fh:
                    fh.write(b"pdf")
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(app, "APS_CONVOCATION_DIR", output_dir), \
                 mock.patch.object(app, "_aps_template_path", return_value=template_path), \
                 mock.patch.object(app, "_render_docx_with_python_template", side_effect=fake_render), \
                 mock.patch.object(app, "_find_libreoffice_binary", return_value="libreoffice"), \
                 mock.patch.object(app.subprocess, "run", side_effect=fake_run):
                docx_path, pdf_path = app._generate_aps_convocation_files(session, trainee, "session-1", "trainee-1")

        self.assertTrue(docx_path.endswith("convocation_aps_trainee-1.docx"))
        self.assertTrue(pdf_path.endswith("convocation_aps_trainee-1.pdf"))

    def test_generation_fails_clearly_without_yousign_smart_anchor(self):
        session = {
            "id": "session-1",
            "training_type": "APS",
            "name": "Formation APS",
            "date_start": "2026-07-08",
            "date_end": "2026-08-12",
            "exam_date": "2026-08-13",
        }
        trainee = {
            "id": "trainee-1",
            "email": "stagiaire@example.com",
            "first_name": "Jean",
            "last_name": "Dupont",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "convocationaps.docx")
            with zipfile.ZipFile(template_path, "w") as zf:
                zf.writestr("word/document.xml", "<w:document><w:body>{{prenom}} {{nom}}</w:body></w:document>")

            with mock.patch.object(app, "_aps_template_path", return_value=template_path):
                with self.assertRaisesRegex(RuntimeError, "Aucune zone de signature trouvée"):
                    app._generate_aps_convocation_files(session, trainee, "session-1", "trainee-1")




class ApsAutomationStatusTests(unittest.TestCase):
    def test_convocation_can_be_generated_before_convention_exists(self):
        session = {"id": "session-1", "training_type": "APS", "name": "Formation APS"}
        trainee = {"id": "trainee-1", "first_name": "Jean", "last_name": "Dupont"}

        with app.app.test_request_context():
            status = app._build_trainee_automation_status(session, trainee, "session-1", "trainee-1")

        self.assertEqual(status["convention"]["status"], "not_generated")
        self.assertEqual(status["convocation"]["status"], "blocked_waiting_convention")
        self.assertTrue(status["convocation"]["can_generate"])
        self.assertFalse(status["convocation"]["can_send"])

    def test_sent_convocation_without_generation_timestamp_is_displayed_as_generated(self):
        session = {"id": "session-1", "training_type": "APS", "name": "Formation APS"}
        trainee = {
            "id": "trainee-1",
            "first_name": "Jean",
            "last_name": "Dupont",
            "convocation_aps_status": "sent",
            "convocation_aps_sent_at": "2026-07-03T08:13:43.852227Z",
            "convocation_aps_pdf_path": "/tmp/convocation.pdf",
            "convention_signature": {
                "status": "done",
                "created_at": "2026-07-03T08:00:00Z",
                "sent_at": "2026-07-03T08:01:00Z",
                "signed_at": "2026-07-03T08:10:00Z",
            },
        }

        with app.app.test_request_context():
            status = app._build_trainee_automation_status(session, trainee, "session-1", "trainee-1")

        generation_step = status["convocation"]["timeline_steps"][1]
        self.assertEqual(status["convocation"]["status"], "sent")
        self.assertEqual(status["convocation"]["generated_at"], "2026-07-03T08:13:43.852227Z")
        self.assertEqual(generation_step["value"], "2026-07-03T08:13:43.852227Z")
        self.assertEqual(generation_step["state"], "done")

class ApsConvocationEmailTests(unittest.TestCase):
    def test_convocation_email_matches_convention_visual_style_and_escapes_values(self):
        subject, html_body = app._build_aps_convocation_email(
            "Jean <script>",
            "2026-10-05",
            "2026-11-11",
        )

        self.assertEqual(subject, "Convocation formation APS - Intégrale Academy")
        self.assertIn("Convocation formation APS", html_body)
        self.assertIn("background:#0b2f5b", html_body)
        self.assertIn("box-shadow:0 8px 24px", html_body)
        self.assertIn("background:#f7faff;border:1px solid #dbeafe", html_body)
        self.assertIn("Accéder à mon espace stagiaire", html_body)
        self.assertIn("Jean &lt;script&gt;", html_body)
        self.assertNotIn("Jean <script>", html_body)
        self.assertIn("du 05/10/2026 au 11/11/2026", html_body)
        self.assertIn("Convocation officielle en pièce jointe", html_body)
        self.assertIn("Nous avons bien reçu votre Convention de formation signée et nous vous en remercions.", html_body)

class YousignSignatureEmailTests(unittest.TestCase):
    def test_signature_email_html_escapes_values_and_uses_button(self):
        html_body = app.build_signature_email_html(
            "Jean <script>",
            "APS & Sécurité",
            "01/07/2026 au 05/07/2026",
            "https://sign.example.test/?token=abc&name=<bad>",
        )

        self.assertIn("Signer ma convention", html_body)
        self.assertIn("Intégrale Academy", html_body)
        self.assertIn("Formation :", html_body)
        self.assertIn("Jean &lt;script&gt;", html_body)
        self.assertIn("APS &amp; Sécurité", html_body)
        self.assertNotIn("Jean <script>", html_body)
        self.assertIn("https://sign.example.test/?token=abc&amp;name=&lt;bad&gt;", html_body)

    def test_signature_email_uses_long_training_label_from_training_type(self):
        session = {"name": "APS TEST", "training_type": "APS", "date_start": "2026-09-01", "date_end": "2026-10-01"}
        trainee = {"first_name": "Clement"}

        _subject, html_body, text_body = app._build_yousign_signature_link_email(session, trainee, "https://sign.example.test/sign")

        self.assertIn("Agent de Prévention et de Sécurité (APS)", html_body)
        self.assertIn("Agent de Prévention et de Sécurité (APS)", text_body)
        self.assertNotIn("APS TEST", html_body)
        self.assertNotIn("APS TEST", text_body)

    def test_signature_email_send_uses_html_and_text_payload(self):
        session = {"name": "Formation APS", "date_start": "2026-07-01", "date_end": "2026-07-05"}
        trainee = {"id": "trainee-1", "email": "stagiaire@example.com", "first_name": "Jean"}
        sent_payload = {}

        def fake_post(_url, headers=None, json=None, timeout=None):
            sent_payload.update(json or {})
            return mock.Mock(status_code=202, text="{}")

        with mock.patch.object(app, "BREVO_API_KEY", "key"), \
             mock.patch.object(app.requests, "post", side_effect=fake_post):
            ok = app.send_yousign_signature_link_email(session, trainee, "https://sign.example.test/sign")

        self.assertTrue(ok)
        self.assertEqual(sent_payload["sender"]["name"], "Intégrale Academy")
        self.assertEqual(sent_payload["subject"], "Votre convention de formation est à signer")
        self.assertIn("htmlContent", sent_payload)
        self.assertIn("textContent", sent_payload)
        self.assertIn("Signer ma convention", sent_payload["htmlContent"])
        self.assertIn("https://sign.example.test/sign", sent_payload["textContent"])

class ApsConvocationSchedulingTests(unittest.TestCase):
    def test_convention_signature_schedules_convocation_five_minutes_later(self):
        session = {"id": "session-1", "training_type": "APS", "trainees": []}
        trainee = {"id": "trainee-1", "convention_signature": {"status": "ongoing"}}
        trainees = [trainee]
        session["trainees"] = trainees
        data = {"sessions": [session]}
        started = []

        class FakeTimer:
            def __init__(self, delay, function, args=()):
                self.delay = delay
                self.function = function
                self.args = args
                self.daemon = False

            def start(self):
                started.append(self)

        app._aps_convocation_auto_send_timers.clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            signed_pdf = os.path.join(tmpdir, "signed.pdf")
            with open(signed_pdf, "wb") as fh:
                fh.write(b"pdf")

            with mock.patch.object(app, "_download_yousign_signed_pdf", return_value=signed_pdf), \
                 mock.patch.object(app, "_store_public_file_token", return_value="token.pdf"), \
                 mock.patch.object(app.threading, "Timer", FakeTimer):
                app._mark_yousign_convention_signed(data, session, trainees, trainee, "sig-req-1")

        self.assertEqual(len(started), 1)
        self.assertEqual(started[0].delay, 5 * 60)
        self.assertEqual(started[0].args, ("session-1", "trainee-1"))
        self.assertTrue(started[0].daemon)
        self.assertIn("convocation_auto_scheduled_at", trainee)
        self.assertFalse(trainee.get("convocation_aps_sent_at"))
        app._aps_convocation_auto_send_timers.clear()


class YousignStatusRefreshTests(unittest.TestCase):
    def test_refresh_pending_convention_marks_done_from_yousign(self):
        session = {"id": "session-1", "training_type": "APS", "trainees": []}
        trainee = {
            "id": "trainee-1",
            "convention_signature": {
                "status": "ongoing",
                "signature_request_id": "sig-req-1",
                "signature_link": "https://example.test/sign",
            },
        }
        trainees = [trainee]
        session["trainees"] = trainees
        data = {"sessions": [session]}

        app._aps_convocation_auto_send_timers.clear()
        with tempfile.TemporaryDirectory() as tmpdir:
            signed_pdf = os.path.join(tmpdir, "signed.pdf")
            with open(signed_pdf, "wb") as fh:
                fh.write(b"pdf")

            with mock.patch.object(app, "_yousign_is_configured", return_value=True), \
                 mock.patch.object(app, "_yousign_json", return_value={"id": "sig-req-1", "status": "done"}), \
                 mock.patch.object(app, "_download_yousign_signed_pdf", return_value=signed_pdf), \
                 mock.patch.object(app, "_store_public_file_token", return_value="token.pdf"), \
                 mock.patch.object(app, "_send_convocation_after_convention_signed", return_value=True):
                changed = app._refresh_yousign_convention_status_if_pending(data, session, trainees, trainee)

        self.assertTrue(changed)
        state = trainee["convention_signature"]
        self.assertEqual(state["status"], "done")
        self.assertEqual(state["signed_pdf_token"], "token.pdf")
        self.assertEqual(trainee["convention_aps_status"], "signed")
        self.assertEqual(trainee["convention_status"], "signed")
        self.assertEqual(state["next_reminder_at"], "")

    def test_sync_convention_status_from_signed_yousign_state(self):
        trainee = {
            "convention_status": "soon",
            "convention_signature": {
                "status": "done",
                "signature_request_id": "sig-req-1",
            },
        }

        changed = app._sync_convention_status_from_yousign(trainee)

        self.assertTrue(changed)
        self.assertEqual(trainee["convention_status"], "signed")

    def test_yousign_webhook_accepts_signer_done_event(self):
        payload = {"event_name": "signer.done", "data": {"signature_request": {"id": "sig-req-1"}}}
        self.assertEqual(app._yousign_signature_request_status(payload), "")
        self.assertIn("signer.done", {"signature_request.done", "signature_request.completed", "signer.done", "signer.completed"})


def _docx_word_xml_text(path):
    with zipfile.ZipFile(path) as zf:
        parts = [
            name for name in zf.namelist()
            if name.startswith("word/") and name.endswith(".xml")
        ]
        return "\n".join(zf.read(name).decode("utf-8", errors="ignore") for name in parts)


def _docx_text_without_variables(path):
    xml = _docx_word_xml_text(path)
    xml = re.sub(r"\{\{[^{}]+\}\}", "", xml)
    return re.sub(r"\s+", " ", xml)


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class ApsConventionGenerationTests(unittest.TestCase):
    def test_yousign_signature_anchor_detection_accepts_pipe_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "conventionaps.docx")
            document = app.Document()
            document.add_paragraph("Signature du contrat de formation")
            document.add_paragraph("Pour le stagiaire")
            document.add_paragraph("Signature")
            document.add_paragraph("{{s1|signature|160|60}}")
            document.save(template_path)

            anchors = app._docx_yousign_smart_anchors(template_path, signer_index=1)

        self.assertIn("{{s1|signature|160|60}}", anchors)

    def test_yousign_pdf_is_cleaned_after_anchor_detection(self):
        from reportlab.pdfgen import canvas

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "anchor.pdf")
            c = canvas.Canvas(pdf_path, pagesize=(595, 842))
            c.drawString(100, 200, "{{s1|signature|160|60}}")
            c.save()

            clean_path, anchors = app._prepare_yousign_pdf_and_fields(pdf_path, signer_index=1)
            clean_text = "\n".join(page.extract_text() or "" for page in app.PdfReader(clean_path).pages)

        self.assertEqual(anchors[0]["type"], "signature")
        self.assertEqual(anchors[0]["width"], 160)
        self.assertEqual(anchors[0]["height"], 60)
        self.assertNotIn("{{s1|signature|160|60}}", clean_text)

    def test_aps_convention_generation_uses_only_production_word_template(self):
        session = {
            "id": "session-1",
            "training_type": "APS",
            "name": "Formation APS",
            "date_start": "2026-07-08",
            "date_end": "2026-08-12",
        }
        trainee = {
            "id": "trainee-1",
            "email": "stagiaire@example.com",
            "first_name": "Jean",
            "last_name": "Dupont",
            "zip_code": "83480",
            "city": "Puget-sur-Argens",
            "personal_amount": "300",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            app_root = os.path.join(tmpdir, "app")
            template_dir = os.path.join(app_root, "templates_word")
            os.makedirs(template_dir)
            source_template_path = app._aps_convention_template_path()
            template_path = os.path.join(template_dir, "conventionaps.docx")
            shutil.copyfile(source_template_path, template_path)
            document = app.Document(template_path)
            document.add_paragraph("Signature du contrat de formation")
            document.add_paragraph("Pour le stagiaire")
            document.add_paragraph("Signature")
            document.add_paragraph("{{s1|signature|160|60}}")
            document.save(template_path)
            self.assertEqual(
                os.path.abspath(template_path),
                os.path.abspath(os.path.join(app_root, "templates_word", "conventionaps.docx")),
            )
            template_hash_before = _file_sha256(template_path)
            template_fixed_text = _docx_text_without_variables(template_path)

            def fake_run(command, check, capture_output, text, timeout):
                pdf_path = os.path.splitext(command[-1])[0] + ".pdf"
                with open(pdf_path, "wb") as fh:
                    fh.write(b"pdf")
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(app, "YOUSIGN_CONVENTION_DIR", tmpdir), \
                 mock.patch.object(app.app, "root_path", app_root), \
                 mock.patch.object(app, "_find_libreoffice_binary", return_value="libreoffice"), \
                 mock.patch.object(app.subprocess, "run", side_effect=fake_run), \
                 self.assertLogs(app.app.logger.name, level="INFO") as logs:
                docx_path, pdf_path = app._generate_aps_convention_files(session, trainee, "session-1", "trainee-1")

            generated_fixed_text = _docx_text_without_variables(docx_path)
            generated_xml = _docx_word_xml_text(docx_path)
            generated_anchors = app._docx_yousign_smart_anchors(docx_path, signer_index=1)
            pdf_exists = os.path.exists(pdf_path)
            template_hash_after = _file_sha256(template_path)

        self.assertEqual(template_hash_before, template_hash_after)
        self.assertTrue(pdf_exists)
        self.assertIn("{{s1|signature|160|60}}", generated_anchors)
        self.assertIn("INTÉGRALE ACADEMY", template_fixed_text)
        self.assertIn("INTÉGRALE ACADEMY", generated_fixed_text)
        self.assertIn("93830600283", generated_fixed_text)
        self.assertIn("Convention APS template utilisé :", "\n".join(logs.output))
        self.assertIn("Variables convention APS attendues :", "\n".join(logs.output))
        self.assertIn("Variables convention APS remplacées :", "\n".join(logs.output))
        self.assertIn("Variables convention APS sans valeur :", "\n".join(logs.output))
        self.assertIn("Variables restantes après remplacement : ['{{s1|signature|160|60}}']", "\n".join(logs.output))
        self.assertIn("Ancres Yousign détectées : ['{{s1|signature|160|60}}']", "\n".join(logs.output))
        self.assertIn("Zones de signature détectées dans la convention APS : ['{{s1|signature|160|60}}']", "\n".join(logs.output))
        self.assertIn(os.path.abspath(template_path), "\n".join(logs.output))
        self.assertIn(f"sha256={template_hash_before}", "\n".join(logs.output))
        self.assertNotRegex(generated_xml, r"Intégrale Academy SAS|93830739683")


    def test_aps_convention_period_variables_use_admin_session_aps_dates(self):
        session = {
            "training_type": "APS",
            "name": "APS TEST",
            "date_start": "2026-09-01",
            "date_end": "2026-10-01",
            "aps_remote_start": "2026-09-01",
            "aps_remote_end": "2026-09-11",
            "aps_in_person_start": "2026-09-14",
            "aps_in_person_end": "2026-10-01",
            "periode_elearning": "ancienne période e-learning",
            "periode_presentiel": "ancienne période présentiel",
        }
        trainee = {
            "first_name": "Jean",
            "last_name": "Dupont",
            "periode_elearning": "période stagiaire e-learning",
            "periode_presentiel": "période stagiaire présentiel",
        }

        replacements = app._aps_convention_replacements(session, trainee)

        self.assertEqual(replacements["periode_formation"], "du 01/09/2026 au 01/10/2026")
        self.assertEqual(replacements["periode_elearning"], "du 01/09/2026 au 11/09/2026")
        self.assertEqual(replacements["periode_presentiel"], "du 14/09/2026 au 01/10/2026")

    def test_aps_convention_empty_personal_amount_is_zero(self):
        replacements = app._aps_convention_replacements(
            {"training_type": "APS", "training_price": "1650"},
            {"first_name": "Jean", "last_name": "Dupont", "personal_amount": ""},
        )

        self.assertEqual(replacements["montant_financement_personnel"], "0")
        self.assertEqual(replacements["montant_financement_personnel_eur"], "0 €")
        self.assertEqual(replacements["montant_personnel"], "0")
        self.assertEqual(replacements["montant_personnel_eur"], "0 €")

    def test_aps_convention_replaces_all_business_variables_from_real_template(self):
        session = {
            "id": "session-1",
            "training_type": "APS",
            "name": "Agent de prévention et de sécurité",
            "date_start": "2026-07-08",
            "date_end": "2026-08-12",
            "h_elearning": "14",
            "h_presentiel": "161",
            "h_total": "175",
            "lieu_formation": "Puget-sur-Argens",
            "lieu_examen": "Puget-sur-Argens",
        }
        trainee = {
            "id": "trainee-1",
            "civilite": "Monsieur",
            "email": "stagiaire@example.com",
            "phone": "0600000000",
            "first_name": "Jean",
            "last_name": "Dupont",
            "address": "1 rue de la Paix",
            "zip_code": "83480",
            "city": "Puget-sur-Argens",
            "training_price": "1650",
            "cpf_amount": "1000",
            "personal_amount": "650",
            "other_amount": "0",
            "espace_stagiaire_url": "https://example.test/espace/token",
        }
        forbidden_remaining = [
            "{{ nom_complet }}", "{{ code_postal }}", "{{ formation_nom }}", "{{ h_total }}",
            "{{ periode_formation }}", "{{ lieu_formation }}", "{{ montant_formation_eur }}",
            "{{ montant_cpf_eur }}", "{{ montant_personnel_eur }}",
            "{{ montant_financement_personnel_eur }}", "{{ date_jour }}", "{{ prenom }}",
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            app_root = os.path.join(tmpdir, "app")
            template_dir = os.path.join(app_root, "templates_word")
            os.makedirs(template_dir)
            source_template_path = app._aps_convention_template_path()
            template_path = os.path.join(template_dir, "conventionaps.docx")
            shutil.copyfile(source_template_path, template_path)
            template_placeholders = app._docx_business_placeholders(template_path)
            self.assertIn("{{s1|signature|160|60}}", template_placeholders)

            def fake_run(command, check, capture_output, text, timeout):
                pdf_path = os.path.splitext(command[-1])[0] + ".pdf"
                with open(pdf_path, "wb") as fh:
                    fh.write(b"pdf")
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(app, "YOUSIGN_CONVENTION_DIR", tmpdir), \
                 mock.patch.object(app.app, "root_path", app_root), \
                 mock.patch.object(app, "_find_libreoffice_binary", return_value="libreoffice"), \
                 mock.patch.object(app.subprocess, "run", side_effect=fake_run):
                docx_path, _ = app._generate_aps_convention_files(session, trainee, "session-1", "trainee-1")

            remaining = app._docx_business_placeholders(docx_path)
            generated_xml = _docx_word_xml_text(docx_path)

        self.assertEqual(["{{s1|signature|160|60}}"], remaining)
        for variable in forbidden_remaining:
            self.assertNotIn(variable, generated_xml)
        self.assertIn("INTÉGRALE ACADEMY", generated_xml)
        self.assertIn("93830600283", generated_xml)
        self.assertNotIn("Intégrale Academy SAS", generated_xml)
        self.assertNotIn("93830739683", generated_xml)

    def test_aps_convention_placeholder_replacement_preserves_fixed_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "convention.docx")
            document = app.Document()
            document.add_paragraph("Entre l’organisme de formation : INTÉGRALE ACADEMY")
            document.add_paragraph("Déclaration d’activité n° 93830600283")
            document.add_paragraph("Stagiaire : {{ nom_identite }}")
            document.add_paragraph("Signature : {{s1|signature|160|60}}")
            document.add_paragraph("Legacy interdit : ['Nom] ['NumeroDeclarationActivite]")
            document.add_paragraph("Titre article fixe")
            document.save(docx_path)

            app._replace_docx_xml_placeholders(docx_path, {"nom_identite": "DUPONT Jean"})
            generated_text = "\n".join(paragraph.text for paragraph in app.Document(docx_path).paragraphs)
            generated_anchors = app._docx_yousign_smart_anchors(docx_path, signer_index=1)

        self.assertIn("Entre l’organisme de formation : INTÉGRALE ACADEMY", generated_text)
        self.assertIn("Déclaration d’activité n° 93830600283", generated_text)
        self.assertIn("Stagiaire : DUPONT Jean", generated_text)
        self.assertIn("Signature : {{s1|signature|160|60}}", generated_text)
        self.assertIn("{{s1|signature|160|60}}", generated_anchors)
        self.assertIn("Legacy interdit : ['Nom] ['NumeroDeclarationActivite]", generated_text)
        self.assertIn("Titre article fixe", generated_text)
        self.assertNotIn("Intégrale Academy SAS", generated_text)
        self.assertNotIn("93830739683", generated_text)


if __name__ == "__main__":
    unittest.main()
