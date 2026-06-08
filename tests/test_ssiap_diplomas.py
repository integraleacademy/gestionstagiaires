import json
from io import BytesIO
import os
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader

import app as gestion_app


class SsiapDiplomaTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_file = os.path.join(self.temp_dir.name, "data.json")
        self.lock_file = os.path.join(self.temp_dir.name, "ssiap_diplomas.lock")
        self.patchers = [
            patch.object(gestion_app, "DATA_FILE", self.data_file),
            patch.object(gestion_app, "SSIAP_DIPLOMA_LOCK_FILE", self.lock_file),
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
    def _trainee(trainee_id, first_name, last_name, birth_date, birth_city="Paris"):
        return {
            "id": trainee_id,
            "first_name": first_name,
            "last_name": last_name,
            "birth_date": birth_date,
            "birth_city": birth_city,
            "birth_department": "75" if birth_city else "",
        }

    def test_generates_filled_multipage_pdf_and_persists_unique_numbers(self):
        self._write_data({
            "sessions": [{
                "id": "SSIAP-2026",
                "name": "SSIAP 1 juin 2026",
                "training_type": "SSIAP 1",
                "exam_date": "2026-06-30",
                "trainees": [
                    self._trainee("T1", "jean", "dupont", "1990-02-03"),
                    self._trainee("T2", "élise", "martin", "15/11/1988"),
                ],
            }],
        })

        response = self.client.post("/admin/sessions/SSIAP-2026/ssiap-diplomas")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn("diplomes-SSIAP-1-juin-2026-2026.pdf", response.headers["Content-Disposition"])

        reader = PdfReader(BytesIO(response.data))
        self.assertEqual(len(reader.pages), 2)
        first_page_text = reader.pages[0].extract_text()
        second_page_text = reader.pages[1].extract_text()
        self.assertIn("30/06/2026", first_page_text)
        self.assertIn("Monsieur Jean DUPONT", first_page_text)
        self.assertIn("03/02/1990", first_page_text)
        self.assertIn("Paris (75)", first_page_text)
        self.assertIn("083-8323-1-2026-00001", first_page_text)
        self.assertIn("Monsieur Élise MARTIN", second_page_text)
        self.assertIn("083-8323-1-2026-00002", second_page_text)

        saved = self._read_data()
        trainees = saved["sessions"][0]["trainees"]
        self.assertEqual(trainees[0]["ssiap_diploma_number"], "083-8323-1-2026-00001")
        self.assertEqual(trainees[1]["ssiap_diploma_number"], "083-8323-1-2026-00002")
        self.assertEqual(saved["ssiap_diploma_sequences"]["2026"], 2)

        repeated = self.client.post("/admin/sessions/SSIAP-2026/ssiap-diplomas")
        self.assertEqual(repeated.status_code, 200)
        repeated_saved = self._read_data()
        repeated_numbers = [
            trainee["ssiap_diploma_number"]
            for trainee in repeated_saved["sessions"][0]["trainees"]
        ]
        self.assertEqual(repeated_numbers, [
            "083-8323-1-2026-00001",
            "083-8323-1-2026-00002",
        ])

    def test_pdf_fields_are_aligned_after_template_labels(self):
        pdf = gestion_app._build_ssiap_diplomas_pdf([{
            "exam_date": "28/10/2026",
            "name": "Monsieur Clément VAILLANT",
            "birth_date": "16/09/1993",
            "birth_place": "PUGET-SUR-ARGENS",
            "number": "083-8323-1-2026-00001",
        }])
        page = PdfReader(pdf).pages[0]
        positions = []

        def collect_position(text, _cm, text_matrix, _font, font_size):
            value = text.strip()
            if value:
                positions.append((value, text_matrix[4], text_matrix[5], font_size))

        page.extract_text(visitor_text=collect_position)

        self.assertIn(("28/10/2026", 1445.0, 643.0, 21.0), positions)
        self.assertIn(("28/10/2026", 420.0, 248.0, 21.0), positions)
        self.assertIn(("Monsieur Clément VAILLANT", 1080.0, 568.0, 21.0), positions)
        self.assertIn(("16/09/1993", 1080.0, 531.0, 21.0), positions)
        self.assertIn(("PUGET-SUR-ARGENS", 1080.0, 493.0, 21.0), positions)
        self.assertIn(("Monsieur Clément VAILLANT", 1120.0, 306.0, 21.0), positions)
        self.assertIn(("083-8323-1-2026-00001", 1170.0, 269.0, 21.0), positions)

    def test_birth_place_uses_existing_department_without_network_lookup(self):
        trainee = {
            "birth_city": "SALLANCHES",
            "birth_department": "Haute-Savoie (74)",
        }

        with patch.object(gestion_app.requests, "get") as get_mock:
            label = gestion_app._ssiap_birth_place_label(trainee)

        self.assertEqual(label, "SALLANCHES (74)")
        self.assertEqual(trainee["birth_department"], "74")
        get_mock.assert_not_called()

    def test_birth_place_finds_department_from_official_commune_api(self):
        trainee = {"birth_city": "SALLANCHES"}
        response = unittest.mock.Mock()
        response.json.return_value = [{
            "nom": "Sallanches",
            "codeDepartement": "74",
            "codesPostaux": ["74700"],
        }]
        gestion_app.SSIAP_BIRTH_DEPARTMENT_CACHE.clear()

        with patch.object(gestion_app.requests, "get", return_value=response) as get_mock:
            label = gestion_app._ssiap_birth_place_label(trainee)

        self.assertEqual(label, "SALLANCHES (74)")
        self.assertEqual(trainee["birth_department"], "74")
        get_mock.assert_called_once_with(
            "https://geo.api.gouv.fr/communes",
            params={
                "nom": "SALLANCHES",
                "fields": "nom,codeDepartement,codesPostaux",
                "boost": "population",
            },
            timeout=3,
        )

    def test_birth_place_keeps_foreign_city_without_french_lookup(self):
        trainee = {"birth_city": "BRUXELLES", "birth_country": "Belgique"}

        with patch.object(gestion_app.requests, "get") as get_mock:
            label = gestion_app._ssiap_birth_place_label(trainee)

        self.assertEqual(label, "BRUXELLES")
        get_mock.assert_not_called()

    def test_sequence_continues_for_new_trainee_and_restarts_each_year(self):
        self._write_data({
            "ssiap_diploma_sequences": {"2026": 7},
            "sessions": [
                {
                    "id": "S26",
                    "name": "SSIAP 2026",
                    "training_type": "SSIAP 1",
                    "exam_date": "2026-12-10",
                    "trainees": [self._trainee("T26", "Paul", "Petit", "1992-04-05")],
                },
                {
                    "id": "S27",
                    "name": "SSIAP 2027",
                    "training_type": "SSIAP 1",
                    "ssiap_exam_date": "2027-01-20",
                    "trainees": [self._trainee("T27", "Marc", "Durand", "1985-07-08")],
                },
            ],
        })

        response_2026 = self.client.post("/admin/sessions/S26/ssiap-diplomas")
        response_2027 = self.client.post("/admin/sessions/S27/ssiap-diplomas")

        self.assertEqual(response_2026.status_code, 200)
        self.assertEqual(response_2027.status_code, 200)
        saved = self._read_data()
        self.assertEqual(saved["sessions"][0]["trainees"][0]["ssiap_diploma_number"], "083-8323-1-2026-00008")
        self.assertEqual(saved["sessions"][1]["trainees"][0]["ssiap_diploma_number"], "083-8323-1-2027-00001")

    def test_generates_only_selected_trainee_without_validating_other_rows(self):
        self._write_data({
            "sessions": [{
                "id": "S1",
                "name": "SSIAP 1",
                "training_type": "SSIAP 1",
                "exam_date": "2026-05-15",
                "trainees": [
                    self._trainee("T1", "Jean", "Dupont", "1990-02-03"),
                    self._trainee("T2", "Paul", "Martin", ""),
                ],
            }],
        })

        response = self.client.post("/admin/sessions/S1/trainees/T1/ssiap-diploma")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn("diplome-SSIAP-Monsieur-Jean-DUPONT-2026.pdf", response.headers["Content-Disposition"])
        reader = PdfReader(BytesIO(response.data))
        self.assertEqual(len(reader.pages), 1)
        page_text = reader.pages[0].extract_text()
        self.assertIn("Monsieur Jean DUPONT", page_text)
        self.assertNotIn("Paul MARTIN", page_text)

        trainees = self._read_data()["sessions"][0]["trainees"]
        self.assertEqual(trainees[0]["ssiap_diploma_number"], "083-8323-1-2026-00001")
        self.assertNotIn("ssiap_diploma_number", trainees[1])

    def test_rejects_generation_before_assigning_numbers_when_required_data_is_missing(self):
        self._write_data({
            "sessions": [{
                "id": "S1",
                "name": "SSIAP 1",
                "training_type": "SSIAP 1",
                "exam_date": "2026-05-15",
                "trainees": [self._trainee("T1", "Jean", "Dupont", "")],
            }],
        })

        response = self.client.post("/admin/sessions/S1/ssiap-diplomas")

        self.assertEqual(response.status_code, 400)
        self.assertIn("date de naissance", response.get_data(as_text=True))
        self.assertNotIn("ssiap_diploma_number", self._read_data()["sessions"][0]["trainees"][0])

    def test_rejects_generation_when_birth_place_is_missing(self):
        self._write_data({
            "sessions": [{
                "id": "S1",
                "name": "SSIAP 1",
                "training_type": "SSIAP 1",
                "exam_date": "2026-05-15",
                "trainees": [self._trainee("T1", "Jean", "Dupont", "1990-02-03", "")],
            }],
        })

        response = self.client.post("/admin/sessions/S1/ssiap-diplomas")

        self.assertEqual(response.status_code, 400)
        self.assertIn("lieu de naissance", response.get_data(as_text=True))
        self.assertNotIn("ssiap_diploma_number", self._read_data()["sessions"][0]["trainees"][0])

    def test_ssiap_admin_page_displays_generation_or_view_button(self):
        generated_trainee = self._trainee("T2", "Alice", "Martin", "1991-04-05")
        generated_trainee["ssiap_diploma_number"] = "083-8323-1-2026-00002"
        fake_data = {
            "sessions": [{
                "id": "S1",
                "name": "SSIAP 1",
                "training_type": "SSIAP 1",
                "date_start": "2026-05-01",
                "date_end": "2026-05-15",
                "exam_date": "2026-05-16",
                "trainees": [self._trainee("T1", "Jean", "Dupont", "1990-02-03")],
            }],
        }
        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data"):
            response = self.client.get("/admin/sessions/S1/trainees")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="btnGenerateSsiapDiplomas"', html)
        self.assertIn('/admin/sessions/S1/ssiap-diplomas', html)
        self.assertIn("Générer les diplômes", html)
        self.assertIn('/admin/sessions/S1/trainees/T1/ssiap-diploma', html)
        self.assertIn("🎓 Générer", html)


if __name__ == "__main__":
    unittest.main()
