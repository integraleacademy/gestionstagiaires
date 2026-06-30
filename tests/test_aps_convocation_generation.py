import os
import tempfile
import unittest
from unittest import mock

import app


class ApsConvocationGenerationTests(unittest.TestCase):
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
            with open(template_path, "wb") as fh:
                fh.write(b"official word template with only some placeholders")

            output_dir = os.path.join(tmpdir, "generated")

            def fake_render(_template_path, output_docx_path, context):
                self.assertEqual(_template_path, template_path)
                self.assertEqual(context["prenom"], "Jean")
                self.assertEqual(context["nom"], "DUPONT")
                os.makedirs(os.path.dirname(output_docx_path), exist_ok=True)
                with open(output_docx_path, "wb") as fh:
                    fh.write(b"docx")

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


if __name__ == "__main__":
    unittest.main()
