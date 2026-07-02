import hashlib
import os
import re
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
        }
        calls = []

        def fake_yousign_json(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if method == "POST" and path == "/signature_requests":
                return {"id": "sig-req-1"}
            if path.endswith("/documents"):
                return {"id": "doc-1"}
            if path.endswith("/signers"):
                return {"id": "signer-1", "signature_link": "https://example.test/sign"}
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
                 mock.patch.object(app, "_yousign_json", side_effect=fake_yousign_json):
                state = app.create_yousign_convention_signature(session, trainee, "2ebec35a", "TRN-2E16579A")

        signature_request_call = calls[0]
        self.assertEqual(signature_request_call[1], "/signature_requests")
        self.assertEqual(
            signature_request_call[2]["json"]["external_id"],
            "convocation_2ebec35a_TRN-2E16579A",
        )
        document_call = next(call for call in calls if call[1].endswith("/documents"))
        self.assertEqual(document_call[2]["data"].get("parse_anchors"), "true")
        signer_call = next(call for call in calls if call[1].endswith("/signers"))
        self.assertNotIn("fields", signer_call[2]["json"])
        self.assertEqual(state["external_id"], "convocation_2ebec35a_TRN-2E16579A")
        self.assertEqual(state["status"], "ongoing")

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
        self.assertEqual(state["next_reminder_at"], "")

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

        template_path = app._aps_convention_template_path()
        self.assertEqual(
            os.path.abspath(template_path),
            os.path.abspath(os.path.join(app.app.root_path, "templates_word", "conventionaps.docx")),
        )
        template_hash_before = _file_sha256(template_path)
        template_fixed_text = _docx_text_without_variables(template_path)

        with tempfile.TemporaryDirectory() as tmpdir:
            def fake_run(command, check, capture_output, text, timeout):
                pdf_path = os.path.splitext(command[-1])[0] + ".pdf"
                with open(pdf_path, "wb") as fh:
                    fh.write(b"pdf")
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(app, "YOUSIGN_CONVENTION_DIR", tmpdir), \
                 mock.patch.object(app, "_find_libreoffice_binary", return_value="libreoffice"), \
                 mock.patch.object(app, "_docx_text_contains_yousign_smart_anchor", return_value=True), \
                 mock.patch.object(app.subprocess, "run", side_effect=fake_run), \
                 self.assertLogs(app.app.logger.name, level="INFO") as logs:
                docx_path, pdf_path = app._generate_aps_convention_files(session, trainee, "session-1", "trainee-1")

            generated_fixed_text = _docx_text_without_variables(docx_path)
            generated_xml = _docx_word_xml_text(docx_path)
            pdf_exists = os.path.exists(pdf_path)

        self.assertEqual(template_hash_before, _file_sha256(template_path))
        self.assertTrue(pdf_exists)
        self.assertEqual(template_fixed_text, generated_fixed_text)
        self.assertIn("INTÉGRALE ACADEMY", generated_fixed_text)
        self.assertIn("Convention APS template utilisé :", "\n".join(logs.output))
        self.assertIn(os.path.abspath(template_path), "\n".join(logs.output))
        self.assertIn(f"sha256={template_hash_before}", "\n".join(logs.output))
        self.assertNotRegex(generated_xml, r"Intégrale Academy SAS|93830739683")

    def test_aps_convention_placeholder_replacement_preserves_fixed_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = os.path.join(tmpdir, "convention.docx")
            document = app.Document()
            document.add_paragraph("Entre l’organisme de formation : INTÉGRALE ACADEMY")
            document.add_paragraph("Déclaration d’activité n° 93830600283")
            document.add_paragraph("Stagiaire : {{ nom_identite }}")
            document.add_paragraph("Legacy interdit : ['Nom] ['NumeroDeclarationActivite]")
            document.add_paragraph("Titre article fixe")
            document.save(docx_path)

            app._replace_docx_xml_placeholders(docx_path, {"nom_identite": "DUPONT Jean"})
            generated_text = "\n".join(paragraph.text for paragraph in app.Document(docx_path).paragraphs)

        self.assertIn("Entre l’organisme de formation : INTÉGRALE ACADEMY", generated_text)
        self.assertIn("Déclaration d’activité n° 93830600283", generated_text)
        self.assertIn("Stagiaire : DUPONT Jean", generated_text)
        self.assertIn("Legacy interdit : ['Nom] ['NumeroDeclarationActivite]", generated_text)
        self.assertIn("Titre article fixe", generated_text)
        self.assertNotIn("Intégrale Academy SAS", generated_text)
        self.assertNotIn("93830739683", generated_text)


if __name__ == "__main__":
    unittest.main()
