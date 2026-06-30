import os
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
                 mock.patch.object(app, "_generate_aps_convocation_files", return_value=(docx_path, pdf_path)), \
                 mock.patch.object(app, "_yousign_json", side_effect=fake_yousign_json):
                state = app.create_yousign_convocation_signature(session, trainee, "2ebec35a", "TRN-2E16579A")

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


if __name__ == "__main__":
    unittest.main()
