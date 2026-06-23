import json
from io import BytesIO
import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pypdf import PdfReader
from reportlab.lib.units import mm

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
            patch.object(gestion_app, "PERSIST_DIR", self.temp_dir.name),
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
            "ssiap_exam_status": "certified",
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
        self.assertEqual(json.loads(response.headers["X-SSIAP-Diploma-Numbers"]), {
            "T1": "083-8323-1-2026-00001",
            "T2": "083-8323-1-2026-00002",
        })

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

    def test_restores_clement_accent_in_generated_diploma_variables(self):
        self._write_data({
            "sessions": [{
                "id": "S1",
                "name": "SSIAP 1",
                "training_type": "SSIAP 1",
                "exam_date": "2026-10-28",
                "trainees": [
                    self._trainee("T1", "Clement", "Vaillant", "1993-09-16", "Sallanches"),
                ],
            }],
        })

        response = self.client.post("/admin/sessions/S1/ssiap-diplomas")

        self.assertEqual(response.status_code, 200)
        page_text = PdfReader(BytesIO(response.data)).pages[0].extract_text()
        self.assertEqual(page_text.count("Monsieur Clément VAILLANT"), 2)
        self.assertNotIn("Monsieur Clement VAILLANT", page_text)

    def test_diploma_override_also_restores_clement_accent(self):
        trainee = self._trainee("T1", "Jean", "Vaillant", "1993-09-16")
        trainee["ssiap_diploma_first_name"] = "Clement"

        self.assertEqual(
            gestion_app._ssiap_diploma_display_name(trainee),
            "Monsieur Clément VAILLANT",
        )

    def test_diploma_row_resolves_identity_photo_for_pdf(self):
        photo_dir = os.path.join(self.temp_dir.name, "uploads", "S1", "T1")
        os.makedirs(photo_dir, exist_ok=True)
        photo_path = os.path.join(photo_dir, "identity.jpg")
        Image.new("RGB", (70, 90), "#336699").save(photo_path)
        trainee = self._trainee("T1", "jean", "dupont", "1990-02-03")
        trainee["identity_photo"] = "uploads/S1/T1/identity.jpg"

        row = gestion_app._ssiap_diploma_row({"exam_date": "2026-06-30"}, trainee)

        self.assertEqual(row["photo_path"], photo_path)

    def test_pdf_draws_identity_photo_at_official_size_in_top_right_corner(self):
        photo_path = os.path.join(self.temp_dir.name, "identity.jpg")
        Image.new("RGB", (70, 90), "#336699").save(photo_path)

        with patch.object(gestion_app, "_draw_pdf_cover_image", wraps=gestion_app._draw_pdf_cover_image) as draw_mock:
            pdf = gestion_app._build_ssiap_diplomas_pdf([{
                "exam_date": "28/10/2026",
                "name": "Monsieur Clément VAILLANT",
                "birth_date": "16/09/1993",
                "birth_place": "PUGET-SUR-ARGENS",
                "number": "083-8323-1-2026-00001",
                "photo_path": photo_path,
            }])

        page = PdfReader(pdf).pages[0]
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
        draw_mock.assert_called_once()
        _canvas, called_path, x, y, width, height = draw_mock.call_args.args
        self.assertEqual(called_path, photo_path)
        self.assertAlmostEqual(width, 35 * mm, places=4)
        self.assertAlmostEqual(height, 45 * mm, places=4)
        self.assertAlmostEqual(x, page_width - (12 * mm) - (35 * mm), places=4)
        self.assertAlmostEqual(y, page_height - (12 * mm) - (45 * mm), places=4)
        page_text = page.extract_text()
        self.assertIn("28/10/2026", page_text)
        self.assertIn("Monsieur Clément VAILLANT", page_text)
        self.assertIn("083-8323-1-2026-00001", page_text)

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

        path_operations = [
            (operator, [float(value) for value in operands])
            for operands, operator in page.get_contents().operations
            if operator in {b"m", b"l", b"h", b"f", b"f*"}
        ]
        self.assertEqual(
            path_operations,
            [
                (b"m", [530.3906, 516.551]),
                (b"l", [533.3372, 516.551]),
                (b"l", [537.1257, 513.1831]),
                (b"l", [533.7581, 513.1831]),
                (b"h", []),
                (b"f*", []),
            ],
        )

        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
        self.assertAlmostEqual(page_width, 841.8898, places=3)
        self.assertAlmostEqual(page_height, 595.2756, places=3)
        self.assertGreater(page_width, page_height)

        scale_x = page_width / 2000
        scale_y = page_height / 1414
        expected_positions = [
            ("28/10/2026", 1445, 771, 21),
            ("28/10/2026", 420, 1166, 21),
            ("Monsieur Clément VAILLANT", 1080, 846, 21),
            ("16/09/1993", 1080, 883, 21),
            ("PUGET-SUR-ARGENS", 1080, 921, 21),
            ("Monsieur Clément VAILLANT", 1120, 1108, 21),
            ("083-8323-1-2026-00001", 1170, 1145, 21),
        ]
        for text, x, y_from_top, font_size in expected_positions:
            expected = (
                text,
                x * scale_x,
                page_height - (y_from_top * scale_y),
                font_size * scale_y,
            )
            match = next(
                position
                for position in positions
                if position[0] == text
                and abs(position[1] - expected[1]) < 0.01
                and abs(position[2] - expected[2]) < 0.01
            )
            self.assertAlmostEqual(match[3], expected[3], places=4)

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

    def test_deleting_trainee_releases_sole_diploma_number_for_api_route(self):
        self._assert_deleting_trainee_releases_sole_diploma_number(
            "/api/sessions/S1/trainees/T1/delete"
        )

    def test_deleting_trainee_releases_sole_diploma_number_for_admin_route(self):
        self._assert_deleting_trainee_releases_sole_diploma_number(
            "/admin/sessions/S1/stagiaires/T1/delete"
        )

    def _assert_deleting_trainee_releases_sole_diploma_number(self, delete_url):
        deleted_trainee = self._trainee("T1", "Jean", "Dupont", "1990-02-03")
        deleted_trainee["ssiap_diploma_number"] = "083-8323-1-2026-00001"
        self._write_data({
            "ssiap_diploma_sequences": {"2026": 1},
            "sessions": [{
                "id": "S1",
                "name": "SSIAP 1",
                "training_type": "SSIAP 1",
                "exam_date": "2026-06-30",
                "trainees": [deleted_trainee],
            }],
        })

        delete_response = self.client.post(delete_url)

        self.assertIn(delete_response.status_code, (200, 302))
        saved = self._read_data()
        self.assertEqual(saved["sessions"][0]["trainees"], [])
        self.assertNotIn("2026", saved["ssiap_diploma_sequences"])

        saved["sessions"][0]["trainees"].append(
            self._trainee("T2", "Paul", "Martin", "1991-04-05")
        )
        self._write_data(saved)

        diploma_response = self.client.post("/admin/sessions/S1/ssiap-diplomas")

        self.assertEqual(diploma_response.status_code, 200)
        replacement = self._read_data()["sessions"][0]["trainees"][0]
        self.assertEqual(
            replacement["ssiap_diploma_number"],
            "083-8323-1-2026-00001",
        )

    def test_deleting_highest_diploma_number_rewinds_sequence_to_remaining_number(self):
        first = self._trainee("T1", "Jean", "Dupont", "1990-02-03")
        first["ssiap_diploma_number"] = "083-8323-1-2026-00001"
        second = self._trainee("T2", "Paul", "Martin", "1991-04-05")
        second["ssiap_diploma_number"] = "083-8323-1-2026-00002"
        self._write_data({
            "ssiap_diploma_sequences": {"2026": 2},
            "sessions": [{
                "id": "S1",
                "name": "SSIAP 1",
                "training_type": "SSIAP 1",
                "exam_date": "2026-06-30",
                "trainees": [first, second],
            }],
        })

        response = self.client.post("/api/sessions/S1/trainees/T2/delete")

        self.assertEqual(response.status_code, 200)
        saved = self._read_data()
        self.assertEqual(saved["ssiap_diploma_sequences"]["2026"], 1)

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
        self.assertEqual(json.loads(response.headers["X-SSIAP-Diploma-Numbers"]), {
            "T1": "083-8323-1-2026-00001",
        })
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

    def test_ssiap_admin_page_displays_exam_statuses_and_diploma_actions(self):
        pending = self._trainee("T1", "Jean", "Dupont", "1990-02-03")
        pending["ssiap_exam_status"] = "pending_results"
        certified = self._trainee("T2", "Alice", "Martin", "1991-04-05")
        generated = self._trainee("T3", "Paul", "Durand", "1988-06-07")
        generated["ssiap_diploma_number"] = "083-8323-1-2026-00002"
        failed = self._trainee("T4", "Luc", "Petit", "1987-08-09")
        failed["ssiap_exam_status"] = "failed"
        fake_data = {
            "sessions": [{
                "id": "S1",
                "name": "SSIAP 1",
                "training_type": "SSIAP 1",
                "date_start": "2026-05-01",
                "date_end": "2026-05-15",
                "exam_date": "2026-05-16",
                "trainees": [pending, certified, generated, failed],
            }],
        }
        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data"):
            response = self.client.get("/admin/sessions/S1/trainees")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(">Examen</th>", html)
        self.assertIn("En attente résultat", html)
        self.assertIn("Certifié", html)
        self.assertIn("Ajourné", html)
        self.assertNotIn(">Test Français</th>", html)
        self.assertNotIn(">CNAPS</th>", html)
        self.assertIn('id="btnGenerateSsiapDiplomas"', html)
        self.assertIn("Générer les diplômes certifiés", html)
        self.assertIn('class="ssiap-diploma-generation-form"', html)
        self.assertIn('data-ssiap-view-url="/admin/sessions/S1/trainees/T2/ssiap-diploma"', html)
        self.assertIn('response.headers.get("X-SSIAP-Diploma-Numbers")', html)
        self.assertIn("updateSsiapDiplomaDisplay(traineeId, number)", html)
        self.assertIn('/admin/sessions/S1/trainees/T2/ssiap-diploma', html)
        self.assertIn("🎓 Générer", html)
        self.assertIn('/admin/sessions/S1/trainees/T3/ssiap-diploma', html)
        self.assertIn("👁️ Voir le diplôme", html)
        self.assertIn("Modifier infos diplôme", html)
        self.assertIn("width:220px", html)
        self.assertIn("width:200px", html)
        self.assertIn('class="sel ssiap-exam-select ssiap-exam-pending_results"', html)

    def test_rejects_diploma_generation_for_non_certified_trainee(self):
        trainee = self._trainee("T1", "Jean", "Dupont", "1990-02-03")
        trainee["ssiap_exam_status"] = "failed"
        self._write_data({
            "sessions": [{
                "id": "S1",
                "name": "SSIAP 1",
                "training_type": "SSIAP 1",
                "exam_date": "2026-05-15",
                "trainees": [trainee],
            }],
        })

        response = self.client.post("/admin/sessions/S1/trainees/T1/ssiap-diploma")

        self.assertEqual(response.status_code, 400)
        self.assertIn("uniquement pour un stagiaire certifié", response.get_data(as_text=True))
        self.assertNotIn("ssiap_diploma_number", self._read_data()["sessions"][0]["trainees"][0])

    def test_views_an_existing_diploma_without_allocating_a_new_number(self):
        trainee = self._trainee("T1", "Jean", "Dupont", "1990-02-03")
        trainee["ssiap_diploma_number"] = "083-8323-1-2026-00004"
        self._write_data({
            "sessions": [{
                "id": "S1",
                "name": "SSIAP 1",
                "training_type": "SSIAP 1",
                "exam_date": "2026-05-15",
                "trainees": [trainee],
            }],
        })

        response = self.client.get("/admin/sessions/S1/trainees/T1/ssiap-diploma")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn("inline", response.headers["Content-Disposition"])
        page_text = PdfReader(BytesIO(response.data)).pages[0].extract_text()
        self.assertIn("083-8323-1-2026-00004", page_text)
        self.assertEqual(
            self._read_data()["sessions"][0]["trainees"][0]["ssiap_diploma_number"],
            "083-8323-1-2026-00004",
        )

    def test_updates_diploma_overrides_used_by_the_pdf(self):
        trainee = self._trainee("T1", "Jean", "Dupont", "1990-02-03")
        self._write_data({
            "sessions": [{
                "id": "S1",
                "name": "SSIAP 1",
                "training_type": "SSIAP 1",
                "exam_date": "2026-05-15",
                "trainees": [trainee],
            }],
        })

        response = self.client.post(
            "/admin/sessions/S1/trainees/T1/ssiap-diploma-info",
            data={
                "civility": "Madame",
                "first_name": "Clement",
                "last_name": "Durand",
                "birth_date": "1992-09-08",
                "birth_city": "Toulon",
                "birth_department": "83",
                "birth_country": "France",
                "exam_date": "2026-06-20",
            },
        )

        self.assertEqual(response.status_code, 302)
        saved = self._read_data()["sessions"][0]["trainees"][0]
        self.assertEqual(saved["ssiap_diploma_first_name"], "Clément")
        generated = self.client.post("/admin/sessions/S1/trainees/T1/ssiap-diploma")
        self.assertEqual(generated.status_code, 200)
        page_text = PdfReader(BytesIO(generated.data)).pages[0].extract_text()
        self.assertIn("Madame Clément DURAND", page_text)
        self.assertIn("08/09/1992", page_text)
        self.assertIn("Toulon (83)", page_text)
        self.assertIn("20/06/2026", page_text)


if __name__ == "__main__":
    unittest.main()
