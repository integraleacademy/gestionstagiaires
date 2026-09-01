import datetime
import io
import os
import tempfile
import unittest
from unittest.mock import patch

import app as gestion_app
from reportlab.pdfgen import canvas


class ApsElearningTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.saved_data = None

    def _admin_login(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def _public_login(self, token="PUBLIC-TOKEN"):
        with self.client.session_transaction() as sess:
            sess[f"public_auth_{token}"] = True

    @staticmethod
    def _digiforma_pdf_bytes(*, trainee_name="ALICE MARTIN", complete=True):
        output = io.BytesIO()
        pdf = canvas.Canvas(output)
        pdf.drawString(72, 790, "Attestation d'assiduité")
        pdf.drawString(72, 765, f"atteste que : {trainee_name}")
        pdf.drawString(72, 740, "a suivi la formation : TFP APS SEPTEMBRE 2026")
        pdf.drawString(72, 715, "Dates de la formation : du 23 juillet 2026 au 3 septembre 2026.")
        pdf.drawString(72, 690, "Durée de la formation : 62 heures")
        if complete:
            pdf.drawString(72, 665, "Suivi détaillé de l'assiduité e-learning")
        pdf.showPage()
        pdf.drawString(72, 790, "Adresse email utilisée : alice.martin@example.test")
        if complete:
            pdf.drawString(72, 765, "Relevé de connexions à l'extranet")
        pdf.drawString(72, 740, "Fait à Puget-sur-Argens, le 31 août 2026")
        pdf.save()
        return output.getvalue()

    @staticmethod
    def _data(date_start, *, enabled=True, training_type="APS"):
        return {
            "sessions": [
                {
                    "id": "S-APS",
                    "name": "Session APS e-learning",
                    "training_type": training_type,
                    "date_start": date_start,
                    "date_end": date_start,
                    "aps_elearning_enabled": enabled,
                    "trainees": [
                        {
                            "id": "T-APS",
                            "public_token": "PUBLIC-TOKEN",
                            "last_name": "MARTIN",
                            "first_name": "Alice",
                            "aps_elearning_login": "alice.aps",
                            "aps_elearning_password": "Secret-123",
                            "documents": [],
                        }
                    ],
                }
            ]
        }

    def test_session_api_persists_option_only_for_aps(self):
        self._admin_login()
        aps_data = {"sessions": []}

        with patch.object(gestion_app, "load_data", return_value=aps_data), patch.object(
            gestion_app, "save_data", side_effect=lambda data: setattr(self, "saved_data", data)
        ):
            response = self.client.post(
                "/api/sessions/create",
                json={
                    "name": "APS juin",
                    "training_type": "APS",
                    "date_start": "2026-06-15",
                    "aps_elearning_enabled": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.saved_data["sessions"][0]["aps_elearning_enabled"])

        non_aps_data = {"sessions": []}
        with patch.object(gestion_app, "load_data", return_value=non_aps_data), patch.object(
            gestion_app, "save_data", side_effect=lambda data: setattr(self, "saved_data", data)
        ):
            response = self.client.post(
                "/api/sessions/create",
                json={
                    "name": "VTC juin",
                    "training_type": "VTC",
                    "aps_elearning_enabled": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.saved_data["sessions"][0]["aps_elearning_enabled"])

    def test_admin_sessions_cards_show_direct_elearning_checkbox_only_for_aps(self):
        self._admin_login()
        future_start = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        future_end = (datetime.date.today() + datetime.timedelta(days=14)).isoformat()
        data = self._data(future_start)
        data["sessions"][0]["partner_id"] = gestion_app.INTEGRALE_PARTNER_ID
        data["sessions"][0]["date_end"] = future_end
        data["sessions"].append(
            {
                "id": "S-VTC",
                "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
                "name": "Session VTC",
                "training_type": "VTC",
                "date_start": future_start,
                "date_end": future_end,
                "aps_elearning_enabled": True,
                "trainees": [],
            }
        )

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "_load_wedof_webhooks", return_value=[]
        ):
            response = self.client.get("/admin/sessions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-aps-elearning-toggle="S-APS"', html)
        self.assertNotIn('data-aps-elearning-toggle="S-VTC"', html)
        self.assertRegex(
            html,
            r'data-aps-elearning-toggle="S-APS"\s+checked',
        )
        self.assertIn("🎓 E-learning", html)

    def test_admin_trainee_credentials_are_available_only_for_enabled_aps_session(self):
        self._admin_login()
        data = self._data("2026-06-15")

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.get("/admin/sessions/S-APS/stagiaires/T-APS")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Identifiants e-learning APS", html)
        self.assertIn('id="editApsElearningLogin"', html)
        self.assertIn('id="editApsElearningPassword"', html)
        self.assertIn("Suivi du e-learning", html)
        self.assertIn("Importer le relevé complet", html)
        self.assertIn("TABLEAU DE SUIVI DE LA FORMATION À DISTANCE", html)
        self.assertIn('disabled aria-disabled="true">⬇️ Télécharger le tableau (PDF)', html)

        data["sessions"][0]["aps_elearning_enabled"] = False
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.get("/admin/sessions/S-APS/stagiaires/T-APS")
        self.assertNotIn("Identifiants e-learning APS", response.get_data(as_text=True))
        self.assertNotIn("Suivi du e-learning", response.get_data(as_text=True))

    def test_complete_digiforma_pdf_is_imported_and_downloadable(self):
        self._admin_login()
        data = self._data("2026-07-23")
        data["sessions"][0]["date_end"] = "2026-09-03"
        data["sessions"][0]["aps_remote_start"] = "2026-07-23"
        data["sessions"][0]["aps_remote_end"] = "2026-09-03"
        pdf_bytes = self._digiforma_pdf_bytes()

        with tempfile.TemporaryDirectory() as directory, patch.object(
            gestion_app, "PERSIST_DIR", directory
        ), patch.object(
            gestion_app, "UPLOADS_DIR", os.path.join(directory, "uploads")
        ), patch.object(
            gestion_app, "load_data", return_value=data
        ), patch.object(gestion_app, "save_data"):
            response = self.client.post(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/digiforma/upload",
                data={"digiforma_pdf": (io.BytesIO(pdf_bytes), "attestation-digiforma.pdf")},
                content_type="multipart/form-data",
            )

            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.endswith("#apsElearningTrackingSection"))
            tracking = data["sessions"][0]["trainees"][0]["aps_elearning_tracking"]
            self.assertEqual(tracking["page_count"], 2)
            self.assertEqual(tracking["report_issued_date"], "2026-08-31")
            self.assertEqual(tracking["digiforma_identifier"], "alice.martin@example.test")
            self.assertEqual(tracking["planned_duration"], "62 heures")
            self.assertEqual(tracking["remote_start"], "2026-07-23")
            self.assertEqual(tracking["remote_end"], "2026-09-03")
            self.assertTrue(os.path.isfile(gestion_app._detokenize_path(tracking["file"])))

            page = self.client.get("/admin/sessions/S-APS/stagiaires/T-APS")
            self.assertEqual(page.status_code, 200)
            html = page.get_data(as_text=True)
            self.assertIn("Relevé complet importé", html)
            self.assertIn("Télécharger l’attestation Digiforma", html)
            self.assertIn("Télécharger le tableau (PDF)", html)

            download = self.client.get(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/digiforma"
            )
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.data, pdf_bytes)
            self.assertIn("attachment", download.headers.get("Content-Disposition", ""))

    def test_incomplete_digiforma_pdf_is_rejected(self):
        self._admin_login()
        data = self._data("2026-07-23")
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ) as save_data:
            response = self.client.post(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/digiforma/upload",
                data={
                    "digiforma_pdf": (
                        io.BytesIO(self._digiforma_pdf_bytes(complete=False)),
                        "attestation-incomplete.pdf",
                    )
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        save_data.assert_not_called()
        self.assertFalse(data["sessions"][0]["trainees"][0].get("aps_elearning_tracking", {}).get("file"))

    def test_digiforma_pdf_for_another_trainee_is_rejected(self):
        self._admin_login()
        data = self._data("2026-07-23")
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ) as save_data:
            response = self.client.post(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/digiforma/upload",
                data={
                    "digiforma_pdf": (
                        io.BytesIO(self._digiforma_pdf_bytes(trainee_name="ELSA DUQUESNE")),
                        "mauvais-stagiaire.pdf",
                    )
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        save_data.assert_not_called()

    def test_digiforma_routes_are_unavailable_outside_aps(self):
        self._admin_login()
        data = self._data("2026-07-23", training_type="VTC")
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ) as save_data:
            upload = self.client.post(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/digiforma/upload",
                data={
                    "digiforma_pdf": (
                        io.BytesIO(self._digiforma_pdf_bytes()),
                        "attestation-digiforma.pdf",
                    )
                },
                content_type="multipart/form-data",
            )
            table = self.client.get(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/tableau-suivi.pdf"
            )

        self.assertEqual(upload.status_code, 404)
        self.assertEqual(table.status_code, 404)
        save_data.assert_not_called()

    def test_tracking_table_context_is_fully_completed(self):
        session_obj = self._data("2026-07-23")["sessions"][0]
        session_obj.update({
            "date_end": "2026-09-03",
            "aps_remote_start": "2026-07-23",
            "aps_remote_end": "2026-09-03",
        })
        trainee = session_obj["trainees"][0]
        trainee.update({
            "birth_date": "1994-03-12",
            "pre_number": "PRE-083-2026-09-01-12345678901",
            "aps_elearning_tracking": {
                "file": "uploads/S-APS/T-APS/aps_elearning_tracking/report.pdf",
                "original_name": "attestation-digiforma.pdf",
                "page_count": 7,
                "report_issued_date": "2026-08-31",
                "digiforma_identifier": "alice.martin@example.test",
                "planned_duration": "62 heures",
            },
        })

        context = gestion_app._aps_elearning_tracking_context(session_obj, trainee)

        self.assertEqual(context["formation_session"], "Session APS e-learning")
        self.assertEqual(context["remote_period"], "du 23/07/2026 au 03/09/2026")
        self.assertEqual(context["remote_duration"], "62 heures")
        self.assertEqual(context["birth_date"], "12/03/1994")
        self.assertEqual(context["cnaps_number"], "PRE-083-2026-09-01-12345678901")
        self.assertEqual(context["digiforma_identifier"], "alice.martin@example.test")
        self.assertEqual(context["report_page_range"], "de la page 1 à la page 7")
        self.assertEqual(context["report_page_count_label"], "7 pages")
        self.assertNotIn("{{", " ".join(context.values()))

    def test_tracking_table_pdf_download_uses_generated_file(self):
        self._admin_login()
        data = self._data("2026-07-23")
        data["sessions"][0]["trainees"][0]["aps_elearning_tracking"] = {
            "file": "uploads/S-APS/T-APS/aps_elearning_tracking/report.pdf",
            "original_name": "attestation-digiforma.pdf",
            "page_count": 2,
        }
        generated = io.BytesIO(b"%PDF-generated-table")

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "_build_aps_elearning_tracking_table_pdf", return_value=generated
        ) as build_pdf:
            response = self.client.get(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/tableau-suivi.pdf"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"%PDF-generated-table")
        self.assertIn("attachment", response.headers.get("Content-Disposition", ""))
        build_pdf.assert_called_once()

    def test_trainee_api_saves_credentials_only_when_aps_elearning_is_enabled(self):
        self._admin_login()
        data = self._data("2026-06-15")

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/api/sessions/S-APS/stagiaires/T-APS/update",
                json={
                    "aps_elearning_login": "nouveau-login",
                    "aps_elearning_password": "nouveau-password",
                },
            )

        self.assertEqual(response.status_code, 200)
        trainee = data["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["aps_elearning_login"], "nouveau-login")
        self.assertEqual(trainee["aps_elearning_password"], "nouveau-password")

        data["sessions"][0]["aps_elearning_enabled"] = False
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/api/sessions/S-APS/stagiaires/T-APS/update",
                json={
                    "aps_elearning_login": "doit-etre-ignore",
                    "aps_elearning_password": "doit-etre-ignore",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(trainee["aps_elearning_login"], "nouveau-login")
        self.assertEqual(trainee["aps_elearning_password"], "nouveau-password")

    def test_public_space_hides_credentials_before_first_training_day(self):
        self._public_login()
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        data = self._data(tomorrow.isoformat())

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.get("/espace/PUBLIC-TOKEN")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(f"Accès disponible le {tomorrow.strftime('%d/%m/%Y')}", html)
        self.assertNotIn("alice.aps", html)
        self.assertNotIn("Secret-123", html)
        self.assertNotIn("Accéder au e-learning", html)

    def test_public_space_shows_credentials_and_copy_actions_from_first_day(self):
        self._public_login()
        data = self._data(datetime.date.today().isoformat())

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.get("/espace/PUBLIC-TOKEN")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("alice.aps", html)
        self.assertIn("Secret-123", html)
        self.assertIn('data-copy-target="apsElearningLogin"', html)
        self.assertIn('data-copy-target="apsElearningPassword"', html)
        self.assertIn('href="https://ediser.elmg.net/"', html)

    def test_public_space_does_not_show_aps_card_for_vtc_or_disabled_session(self):
        self._public_login()
        for training_type, enabled in (("VTC", True), ("APS", False)):
            data = self._data(datetime.date.today().isoformat(), enabled=enabled, training_type=training_type)
            with patch.object(gestion_app, "load_data", return_value=data), patch.object(
                gestion_app, "save_data"
            ):
                response = self.client.get("/espace/PUBLIC-TOKEN")
            html = response.get_data(as_text=True)
            self.assertNotIn("Espace e-learning APS", html)
            self.assertNotIn("alice.aps", html)
            self.assertNotIn("Secret-123", html)


if __name__ == "__main__":
    unittest.main()
