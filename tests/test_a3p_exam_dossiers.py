import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import app as gestion_app


class A3pExamDossierTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"
        self.a3p_session = {
            "id": "A3P-1", "name": "A3P été", "training_type": "A3P",
            "date_start": "2026-08-03", "date_end": "2026-09-25", "exam_date": "2026-09-28",
            "trainees": [{"id": "T1", "first_name": "alice", "last_name": "martin", "city": "Nice"}],
        }

    def test_admin_page_only_displays_exam_dossier_button_for_a3p(self):
        aps = {**self.a3p_session, "id": "APS-1", "name": "APS été", "training_type": "APS"}
        with patch.object(gestion_app, "load_data", return_value={"sessions": [self.a3p_session, aps]}), \
             patch.object(gestion_app, "save_data"):
            a3p_html = self.client.get("/admin/sessions/A3P-1/trainees").get_data(as_text=True)
            aps_html = self.client.get("/admin/sessions/APS-1/trainees").get_data(as_text=True)
        self.assertIn('id="btnA3pExamDossier"', a3p_html)
        self.assertIn("Dossiers d’examen en cours de création", a3p_html)
        self.assertNotIn('id="btnA3pExamDossier"', aps_html)

    def test_config_prefills_session_dates_and_rejects_non_a3p(self):
        aps = {**self.a3p_session, "id": "APS-1", "training_type": "APS", "name": "APS"}
        with patch.object(gestion_app, "load_data", return_value={"sessions": [self.a3p_session, aps]}):
            response = self.client.get("/api/admin/sessions/A3P-1/a3p-exam-dossiers")
            forbidden = self.client.get("/api/admin/sessions/APS-1/a3p-exam-dossiers")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["training_start_date"], "2026-08-03")
        self.assertEqual(response.get_json()["exam_date"], "2026-09-28")
        self.assertEqual(forbidden.status_code, 400)

    def test_context_exposes_all_word_variables(self):
        context = gestion_app._a3p_exam_context(
            self.a3p_session["trainees"][0],
            {"training_start_date": "2026-08-03", "training_end_date": "2026-09-25", "exam_date": "2026-09-28", "epi_training_date": "2026-08-14"},
        )
        self.assertEqual(context["nom_complet"], "Alice MARTIN")
        self.assertEqual(context["periode_formation"], "03/08/2026 au 25/09/2026")
        self.assertEqual(context["date_formation_epi"], "14/08/2026")

    def test_prepared_word_copy_contains_editable_epi_date_variable(self):
        source = os.path.join(gestion_app.app.root_path, "templates_word", "docexamena3p.docx")
        with tempfile.TemporaryDirectory() as temp_dir:
            prepared = gestion_app._prepare_a3p_exam_template(source, os.path.join(temp_dir, "prepared.docx"))
            with zipfile.ZipFile(prepared) as archive:
                xml = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("{{ date_formation_epi }}", xml)
        self.assertNotIn("22 avril 2026", xml)


if __name__ == "__main__":
    unittest.main()
