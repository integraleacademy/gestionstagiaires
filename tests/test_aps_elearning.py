import datetime
import hashlib
import io
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import app as gestion_app
from pypdf import PdfReader
from reportlab.pdfgen import canvas


class ApsElearningTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.saved_data = None

    def _admin_login(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"
            sess["admin_username"] = "admin@integraleacademy.com"

    def _public_login(self, token="PUBLIC-TOKEN"):
        with self.client.session_transaction() as sess:
            sess[f"public_auth_{token}"] = True

    @staticmethod
    def _digiforma_pdf_bytes(
        *,
        trainee_name="ALICE MARTIN",
        complete=True,
        completion_rate=100,
        effective_duration="62 heures",
        completed_paths=8,
        completed_evaluations=8,
    ):
        output = io.BytesIO()
        pdf = canvas.Canvas(output)
        pdf.drawString(72, 790, "Attestation d'assiduité")
        pdf.drawString(72, 765, f"atteste que : {trainee_name}")
        pdf.drawString(72, 740, "a suivi la formation : TFP APS SEPTEMBRE 2026")
        pdf.drawString(72, 715, "Dates de la formation : du 23 juillet 2026 au 3 septembre 2026.")
        pdf.drawString(72, 690, "Durée de la formation : 62 heures")
        if complete:
            pdf.drawString(72, 665, "Suivi détaillé de l'assiduité e-learning")
            pdf.drawString(72, 640, f"Durée effectivement suivie sur la plateforme : {effective_duration}")
            pdf.drawString(72, 615, f"taux de réalisation de {completion_rate} %")
            pdf.drawString(72, 590, "Durée totale de connexion à l'extranet : 62h")
            pdf.drawString(72, 565, "Nombre de jour(s) d'accès à l'extranet : 8")
            y = 535
            for index in range(1, 9):
                status = "Statut Terminé Progression 100 %" if index <= completed_paths else "Statut En cours Progression 0 %"
                pdf.drawString(72, y, f"Parcours {index} — Bloc {index} {status}")
                y -= 22
        pdf.showPage()
        pdf.drawString(72, 790, "Adresse email utilisée : alice.martin@example.test")
        if complete:
            pdf.drawString(72, 765, "Relevé de connexions à l'extranet")
            y = 735
            for index in range(1, 9):
                result = "100% 1 passage" if index <= completed_evaluations else "0% 0 passage"
                pdf.drawString(72, y, f"Evaluation Parcours {index}")
                pdf.drawString(90, y - 14, result)
                pdf.drawString(72, y - 28, "Total 7 heures 45 minutes")
                y -= 50
            pdf.drawString(72, 315, "P1M1 P2M1 P3M1 P4M1 P5M1 P6M1 P7M1 P8M1")
            pdf.drawString(72, 290, "Total 62 heures")
        pdf.drawString(72, 255, "Fait à Puget-sur-Argens, le 31 août 2026")
        pdf.save()
        return output.getvalue()

    @staticmethod
    def _complete_tracking(**overrides):
        tracking = {
            "file": "uploads/S-APS/T-APS/aps_elearning_tracking/report.pdf",
            "original_name": "attestation-digiforma.pdf",
            "page_count": 2,
            "report_issued_date": "2026-08-31",
            "digiforma_identifier": "alice.martin@example.test",
            "planned_duration": "62 heures",
            "effective_duration": "62 heures",
            "completion_rate": 100,
            "connection_duration": "62h",
            "connection_log_total": "62 heures",
            "access_days": 8,
            "paths_total": 8,
            "paths_completed": 8,
            "evaluations_total": 8,
            "evaluations_completed": 8,
            "module_fraction_count": 8,
            "file_sha256": "a" * 64,
        }
        tracking.update(overrides)
        return tracking

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
                            "email": "alice.martin@example.test",
                            "phone": "06 12 34 56 78",
                            "birth_date": "1994-03-12",
                            "pre_number": "PRE-083-2026-09-01-12345678901",
                            "aps_elearning_login": "https://ediser.elmg.net/access/alice-aps",
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

    def test_admin_trainee_link_is_available_only_for_enabled_aps_session(self):
        self._admin_login()
        data = self._data("2026-06-15")

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.get("/admin/sessions/S-APS/stagiaires/T-APS")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Lien e-learning APS", html)
        self.assertRegex(html, r'id="editApsElearningLogin"\s+type="url"')
        self.assertIn(
            'value="https://ediser.elmg.net/access/alice-aps"',
            html,
        )
        self.assertNotIn('id="editApsElearningPassword"', html)
        self.assertIn("Suivi du e-learning", html)
        self.assertIn("Importer le relevé complet", html)
        self.assertNotIn("Tout remettre à zéro", html)
        self.assertIn("TABLEAU DE SUIVI DE LA FORMATION À DISTANCE", html)
        self.assertIn('disabled aria-disabled="true">⬇️ Dossier CNAPS non disponible', html)

        data["sessions"][0]["aps_elearning_enabled"] = False
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.get("/admin/sessions/S-APS/stagiaires/T-APS")
        self.assertNotIn("Lien e-learning APS", response.get_data(as_text=True))
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
            self.assertEqual(tracking["effective_duration"], "62 heures")
            self.assertEqual(tracking["completion_rate"], 100)
            self.assertEqual(tracking["connection_duration"], "62h")
            self.assertEqual(tracking["connection_log_total"], "62 heures")
            self.assertEqual(tracking["access_days"], 8)
            self.assertEqual(tracking["paths_completed"], 8)
            self.assertEqual(tracking["paths_total"], 8)
            self.assertEqual(tracking["evaluations_completed"], 8)
            self.assertEqual(tracking["evaluations_total"], 8)
            self.assertEqual(tracking["module_fraction_count"], 8)
            self.assertEqual(tracking["file_sha256"], hashlib.sha256(pdf_bytes).hexdigest())
            self.assertEqual(tracking["remote_start"], "2026-07-23")
            self.assertEqual(tracking["remote_end"], "2026-09-03")
            self.assertTrue(os.path.isfile(gestion_app._detokenize_path(tracking["file"])))

            page = self.client.get("/admin/sessions/S-APS/stagiaires/T-APS")
            self.assertEqual(page.status_code, 200)
            html = page.get_data(as_text=True)
            self.assertIn("Dossier contrôlé et signable", html)
            self.assertIn("Télécharger l’attestation Digiforma", html)
            self.assertIn("Tout remettre à zéro", html)
            self.assertIn(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/reset",
                html,
            )
            self.assertIn("Le lien e-learning APS restera inchangé", html)
            self.assertIn("Télécharger le dossier CNAPS complet", html)
            self.assertIn("Envoyer à signer avec Yousign", html)
            self.assertIn("Contrôles automatiques validés", html)
            self.assertIn("tampon et la signature de Clément Vaillant sont intégrés", html)

            download = self.client.get(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/digiforma"
            )
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.data, pdf_bytes)
            self.assertIn("attachment", download.headers.get("Content-Disposition", ""))

    def test_admin_can_reset_all_aps_elearning_data_and_files(self):
        self._admin_login()
        data = self._data("2026-07-23")
        trainee = data["sessions"][0]["trainees"][0]

        with tempfile.TemporaryDirectory() as directory:
            uploads_dir = os.path.join(directory, "uploads")
            tracking_dir = os.path.join(
                uploads_dir,
                "S-APS",
                "T-APS",
                gestion_app.APS_ELEARNING_TRACKING_FOLDER,
            )
            generated_dir = os.path.join(directory, "generated", "aps-elearning")
            signed_dir = os.path.join(directory, "generated", "aps-elearning-signed")
            os.makedirs(tracking_dir, exist_ok=True)
            os.makedirs(generated_dir, exist_ok=True)
            os.makedirs(signed_dir, exist_ok=True)

            report_path = os.path.join(tracking_dir, "report.pdf")
            source_pdf_path = os.path.join(generated_dir, "tableau_current.pdf")
            source_docx_path = os.path.join(generated_dir, "tableau_current.docx")
            clean_pdf_path = os.path.join(generated_dir, "tableau_current_clean.pdf")
            clean_docx_path = os.path.join(generated_dir, "tableau_current_clean.docx")
            package_path = os.path.join(generated_dir, "tableau_current_dossier_complet.pdf")
            signed_path = os.path.join(
                signed_dir,
                "tableau_suivi_foad_cnaps_T-APS_signe.pdf",
            )
            old_package_path = os.path.join(generated_dir, "tableau_old_dossier_complet.pdf")
            outside_path = os.path.join(directory, "ne-pas-supprimer.pdf")
            managed_paths = (
                report_path,
                source_pdf_path,
                source_docx_path,
                clean_pdf_path,
                clean_docx_path,
                package_path,
                signed_path,
                old_package_path,
            )
            for path in (*managed_paths, outside_path):
                with open(path, "wb") as target:
                    target.write(b"test")

            trainee["aps_elearning_tracking"] = self._complete_tracking(
                file="uploads/S-APS/T-APS/aps_elearning_tracking/report.pdf",
            )
            trainee["aps_elearning_signature"] = {
                "status": "done",
                "signature_request_id": "foad-request-current",
                "source_pdf_with_anchors_path": source_pdf_path,
                "unsigned_docx_path": source_docx_path,
                "unsigned_pdf_path": package_path,
                "signed_pdf_path": signed_path,
            }
            trainee["aps_elearning_signature_history"] = [
                {
                    "status": "canceled",
                    "unsigned_pdf_path": old_package_path,
                    "signed_pdf_path": outside_path,
                }
            ]
            trainee["aps_elearning_force_override"] = {"active": True}
            trainee["aps_elearning_force_override_history"] = [{"active": False}]
            trainee["aps_elearning_signature_issues"] = ["test"]
            trainee["aps_elearning_signature_ready"] = False
            trainee["aps_elearning_signature_allowed"] = True
            trainee["aps_elearning_force_active"] = True

            with patch.object(gestion_app, "PERSIST_DIR", directory), patch.object(
                gestion_app, "UPLOADS_DIR", uploads_dir
            ), patch.object(
                gestion_app, "YOUSIGN_APS_ELEARNING_DIR", generated_dir
            ), patch.object(
                gestion_app, "YOUSIGN_APS_ELEARNING_SIGNED_DIR", signed_dir
            ), patch.object(
                gestion_app, "load_data", return_value=data
            ), patch.object(gestion_app, "save_data") as save_data:
                response = self.client.post(
                    "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/reset"
                )

            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.endswith("#apsElearningTrackingSection"))
            for key in gestion_app.APS_ELEARNING_RESET_FIELDS:
                self.assertNotIn(key, trainee)
            self.assertEqual(
                trainee["aps_elearning_login"],
                "https://ediser.elmg.net/access/alice-aps",
            )
            self.assertTrue(all(not os.path.exists(path) for path in managed_paths))
            self.assertTrue(os.path.isfile(outside_path))
            self.assertEqual(
                trainee["activity_history"][0]["label"],
                "Suivi e-learning APS remis à zéro",
            )
            self.assertIn("8 fichier(s) local(aux) supprimé(s)", trainee["activity_history"][0]["details"])
            save_data.assert_called_once_with(data)

    def test_reset_cancels_pending_yousign_request_before_clearing(self):
        self._admin_login()
        data = self._data("2026-07-23")
        trainee = data["sessions"][0]["trainees"][0]
        trainee["aps_elearning_tracking"] = self._complete_tracking()
        trainee["aps_elearning_signature"] = {
            "status": "ongoing",
            "signature_request_id": "foad-request-pending",
        }

        with tempfile.TemporaryDirectory() as directory, patch.object(
            gestion_app, "PERSIST_DIR", directory
        ), patch.object(
            gestion_app, "UPLOADS_DIR", os.path.join(directory, "uploads")
        ), patch.object(
            gestion_app, "YOUSIGN_APS_ELEARNING_DIR", os.path.join(directory, "generated")
        ), patch.object(
            gestion_app, "YOUSIGN_APS_ELEARNING_SIGNED_DIR", os.path.join(directory, "signed")
        ), patch.object(
            gestion_app, "_yousign_is_configured", return_value=True
        ), patch.object(
            gestion_app, "_cancel_yousign_aps_elearning_signature"
        ) as cancel_signature, patch.object(
            gestion_app, "load_data", return_value=data
        ), patch.object(gestion_app, "save_data") as save_data:
            response = self.client.post(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/reset"
            )

        self.assertEqual(response.status_code, 302)
        cancel_signature.assert_called_once_with(trainee, "other")
        self.assertNotIn("aps_elearning_tracking", trainee)
        self.assertNotIn("aps_elearning_signature", trainee)
        save_data.assert_called_once_with(data)

    def test_reset_keeps_data_if_pending_yousign_cannot_be_cancelled(self):
        self._admin_login()
        data = self._data("2026-07-23")
        trainee = data["sessions"][0]["trainees"][0]
        trainee["aps_elearning_tracking"] = self._complete_tracking()
        trainee["aps_elearning_signature"] = {
            "status": "ongoing",
            "signature_request_id": "foad-request-pending",
        }

        with patch.object(gestion_app, "_yousign_is_configured", return_value=True), patch.object(
            gestion_app,
            "_cancel_yousign_aps_elearning_signature",
            side_effect=RuntimeError("annulation Yousign indisponible"),
        ) as cancel_signature, patch.object(
            gestion_app, "load_data", return_value=data
        ), patch.object(gestion_app, "save_data") as save_data:
            response = self.client.post(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/reset"
            )

        self.assertEqual(response.status_code, 302)
        cancel_signature.assert_called_once_with(trainee, "other")
        self.assertIn("aps_elearning_tracking", trainee)
        self.assertIn("aps_elearning_signature", trainee)
        save_data.assert_not_called()

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

    def test_structurally_complete_but_unfinished_report_is_blocked_from_signature(self):
        pdf_bytes = self._digiforma_pdf_bytes(
            completion_rate=28.49,
            effective_duration="17h40",
            completed_paths=1,
            completed_evaluations=1,
        )
        metadata = gestion_app._extract_digiforma_attendance_metadata(pdf_bytes)
        issues = gestion_app._aps_elearning_report_completion_issues(metadata)

        self.assertEqual(metadata["completion_rate"], 28.49)
        self.assertEqual(metadata["effective_duration"], "17h40")
        self.assertEqual(metadata["paths_completed"], 1)
        self.assertEqual(metadata["evaluations_completed"], 1)
        self.assertTrue(any("progression Digiforma incomplète" in issue for issue in issues))
        self.assertTrue(any("durée effectivement suivie inférieure" in issue for issue in issues))
        self.assertTrue(any("parcours Digiforma non terminés" in issue for issue in issues))
        self.assertTrue(any("questionnaires non validés" in issue for issue in issues))

    def test_admin_can_force_and_revoke_an_unfinished_report(self):
        self._admin_login()
        data = self._data("2026-07-23")
        pdf_bytes = self._digiforma_pdf_bytes(
            completion_rate=28.49,
            effective_duration="17h40",
            completed_paths=1,
            completed_evaluations=1,
        )

        with tempfile.TemporaryDirectory() as directory, patch.object(
            gestion_app, "PERSIST_DIR", directory
        ), patch.object(
            gestion_app, "UPLOADS_DIR", os.path.join(directory, "uploads")
        ), patch.object(
            gestion_app, "load_data", return_value=data
        ), patch.object(gestion_app, "save_data"):
            upload = self.client.post(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/digiforma/upload",
                data={"digiforma_pdf": (io.BytesIO(pdf_bytes), "attestation-inachevee.pdf")},
                content_type="multipart/form-data",
            )
            self.assertEqual(upload.status_code, 302)

            blocked_page = self.client.get("/admin/sessions/S-APS/stagiaires/T-APS")
            blocked_html = blocked_page.get_data(as_text=True)
            self.assertIn(">⚠ Forcer</button>", blocked_html)
            self.assertIn("Signature et téléchargement du dossier CNAPS bloqués", blocked_html)

            force = self.client.post(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/force",
                data={"action": "enable"},
            )
            self.assertEqual(force.status_code, 302)

            trainee = data["sessions"][0]["trainees"][0]
            tracking = trainee["aps_elearning_tracking"]
            override = trainee["aps_elearning_force_override"]
            self.assertTrue(override["active"])
            self.assertEqual(override["forced_by"], "admin@integraleacademy.com")
            self.assertEqual(override["report_sha256"], hashlib.sha256(pdf_bytes).hexdigest())
            self.assertGreaterEqual(len(override["issues"]), 4)
            self.assertEqual(
                gestion_app._require_aps_elearning_signature_ready(trainee)["file_sha256"],
                tracking["file_sha256"],
            )

            context = gestion_app._aps_elearning_tracking_context(data["sessions"][0], trainee)
            self.assertIn("FORÇAGE ADMINISTRATIF", context["compliance_status"])
            self.assertIn("RELEVÉ INCOMPLET", context["compliance_status"])
            self.assertIn("28.49 %", context["compliance_detail"])
            self.assertIn("admin@integraleacademy.com", context["force_authorization"])
            self.assertIn("SIGNATURE AVEC FORÇAGE", context["signature_instruction"])

            forced_page = self.client.get("/admin/sessions/S-APS/stagiaires/T-APS")
            forced_html = forced_page.get_data(as_text=True)
            self.assertIn("Forçage actif · dossier incomplet", forced_html)
            self.assertIn("Télécharger le dossier forcé", forced_html)
            self.assertIn("Envoyer à signer (forcé)", forced_html)
            self.assertIn("Annuler le forçage", forced_html)

            revoke = self.client.post(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/force",
                data={"action": "disable"},
            )
            self.assertEqual(revoke.status_code, 302)
            self.assertFalse(trainee["aps_elearning_force_override"]["active"])
            self.assertEqual(trainee["aps_elearning_force_override"]["revoked_by"], "admin@integraleacademy.com")
            with self.assertRaisesRegex(ValueError, "Utilisez le bouton « Forcer »"):
                gestion_app._require_aps_elearning_signature_ready(trainee)

    def test_force_override_does_not_cover_a_new_anomaly(self):
        trainee = self._data("2026-07-23")["sessions"][0]["trainees"][0]
        tracking = self._complete_tracking(
            completion_rate=28.49,
            effective_duration="17h40",
            paths_completed=1,
            evaluations_completed=1,
        )
        trainee["aps_elearning_tracking"] = tracking
        issues = gestion_app._aps_elearning_signature_issues(trainee, tracking)
        trainee["aps_elearning_force_override"] = {
            "active": True,
            "forced_at": "2026-09-01T10:00:00+02:00",
            "forced_by": "admin@integraleacademy.com",
            "report_sha256": tracking["file_sha256"],
            "issues": issues,
        }

        self.assertEqual(
            gestion_app._require_aps_elearning_signature_ready(trainee)["file_sha256"],
            tracking["file_sha256"],
        )
        trainee["birth_date"] = ""
        with self.assertRaisesRegex(ValueError, "date de naissance"):
            gestion_app._require_aps_elearning_signature_ready(trainee)

    def test_replacing_digiforma_report_archives_force_override(self):
        self._admin_login()
        data = self._data("2026-07-23")
        trainee = data["sessions"][0]["trainees"][0]
        old_pdf = self._digiforma_pdf_bytes(
            completion_rate=28.49,
            effective_duration="17h40",
            completed_paths=1,
            completed_evaluations=1,
        )
        new_pdf = self._digiforma_pdf_bytes()

        with tempfile.TemporaryDirectory() as directory, patch.object(
            gestion_app, "PERSIST_DIR", directory
        ), patch.object(
            gestion_app, "UPLOADS_DIR", os.path.join(directory, "uploads")
        ), patch.object(
            gestion_app, "load_data", return_value=data
        ), patch.object(gestion_app, "save_data"):
            old_path = os.path.join(directory, "uploads", "S-APS", "T-APS", "aps_elearning_tracking", "old.pdf")
            os.makedirs(os.path.dirname(old_path), exist_ok=True)
            with open(old_path, "wb") as old_report:
                old_report.write(old_pdf)
            old_tracking = self._complete_tracking(
                file=gestion_app._tokenize_path(old_path),
                file_sha256=hashlib.sha256(old_pdf).hexdigest(),
                completion_rate=28.49,
                effective_duration="17h40",
                paths_completed=1,
                evaluations_completed=1,
            )
            trainee["aps_elearning_tracking"] = old_tracking
            trainee["aps_elearning_force_override"] = {
                "active": True,
                "forced_at": "2026-09-01T10:00:00+02:00",
                "forced_by": "admin@integraleacademy.com",
                "report_sha256": old_tracking["file_sha256"],
                "issues": gestion_app._aps_elearning_signature_issues(trainee, old_tracking),
            }

            response = self.client.post(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/digiforma/upload",
                data={"digiforma_pdf": (io.BytesIO(new_pdf), "attestation-finale.pdf")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("aps_elearning_force_override", trainee)
        archive = trainee["aps_elearning_force_override_history"]
        self.assertEqual(archive[-1]["archive_reason"], "digiforma_report_replaced")
        self.assertEqual(trainee["aps_elearning_tracking"]["completion_rate"], 100)

    def test_digiforma_file_integrity_is_rechecked_before_generation(self):
        pdf_bytes = self._digiforma_pdf_bytes()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            gestion_app, "PERSIST_DIR", directory
        ):
            report_path = os.path.join(directory, "report.pdf")
            with open(report_path, "wb") as report_file:
                report_file.write(pdf_bytes)
            tracking = self._complete_tracking(
                file="report.pdf",
                file_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
            )

            self.assertEqual(
                gestion_app._require_aps_elearning_report_file(tracking),
                report_path,
            )
            with open(report_path, "ab") as report_file:
                report_file.write(b"tampered")
            with self.assertRaisesRegex(ValueError, "a changé depuis son import"):
                gestion_app._require_aps_elearning_report_file(tracking)

    def test_complete_package_appends_every_digiforma_page(self):
        with tempfile.TemporaryDirectory() as directory:
            cover_path = os.path.join(directory, "cover.pdf")
            annex_path = os.path.join(directory, "annex.pdf")
            output_path = os.path.join(directory, "complete.pdf")
            for path, page_count in ((cover_path, 2), (annex_path, 3)):
                generated = canvas.Canvas(path)
                for page_number in range(1, page_count + 1):
                    generated.drawString(72, 790, f"{os.path.basename(path)} page {page_number}")
                    generated.showPage()
                generated.save()

            gestion_app._combine_aps_elearning_tracking_pdf(cover_path, annex_path, output_path)
            reader = PdfReader(output_path)

        self.assertEqual(len(reader.pages), 5)
        self.assertEqual(
            reader.metadata.title,
            "Tableau de suivi de la formation à distance - dossier probatoire CNAPS",
        )

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
            "aps_elearning_tracking": self._complete_tracking(
                page_count=7,
            ),
        })

        context = gestion_app._aps_elearning_tracking_context(session_obj, trainee)

        self.assertEqual(context["formation_session"], "Session APS e-learning")
        self.assertEqual(context["remote_period"], "du 23/07/2026 au 03/09/2026")
        self.assertEqual(context["remote_duration"], "62 heures")
        self.assertEqual(context["birth_date"], "12/03/1994")
        self.assertEqual(context["cnaps_number"], "PRE-083-2026-09-01-12345678901")
        self.assertEqual(context["digiforma_identifier"], "alice.martin@example.test")
        self.assertEqual(context["report_page_range"], "pages 3 à 9 du dossier signé")
        self.assertEqual(context["report_page_count_label"], "7 pages")
        self.assertEqual(context["effective_duration"], "62 heures")
        self.assertEqual(context["completion_rate"], "100 %")
        self.assertEqual(context["paths_status"], "8 / 8 terminés")
        self.assertEqual(context["evaluations_status"], "8 / 8 validées")
        self.assertEqual(context["compliance_status"], "PARCOURS COMPLET - 100 % - SIGNATURE AUTORISÉE")
        self.assertEqual(context["compliance_detail"], "Aucune anomalie détectée par les contrôles automatiques.")
        self.assertEqual(context["force_authorization"], "Aucun forçage administratif nécessaire.")
        self.assertIn("À SIGNER APRÈS CONTRÔLE", context["signature_instruction"])
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

    def test_tracking_template_contains_trainee_anchor_and_provider_assets(self):
        anchors = gestion_app._docx_yousign_smart_anchors(
            gestion_app.APS_ELEARNING_TRACKING_TEMPLATE,
            signer_index=1,
        )
        with zipfile.ZipFile(gestion_app.APS_ELEARNING_TRACKING_TEMPLATE) as template_zip:
            media = [name for name in template_zip.namelist() if name.startswith("word/media/")]
            document_xml = template_zip.read("word/document.xml").decode("utf-8")

        self.assertEqual(anchors, ["{{s1|signature|160|60}}"])
        self.assertGreaterEqual(len(media), 3)
        self.assertIn("{{ compliance_detail }}", document_xml)
        self.assertIn("{{ force_authorization }}", document_xml)
        self.assertIn("{{ signature_instruction }}", document_xml)

    def test_yousign_pdf_anchor_exposes_the_marker_top(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = os.path.join(directory, "anchor.pdf")
            generated_pdf = canvas.Canvas(pdf_path, pagesize=(595.304, 841.89))
            generated_pdf.setFont("Helvetica", 9)
            generated_pdf.drawString(126, 227.589, "{{s1|signature|160|60}}")
            generated_pdf.save()

            anchors = gestion_app._detect_yousign_pdf_anchors(pdf_path, signer_index=1)

        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0]["y"], 554)
        self.assertEqual(anchors[0]["marker_y"], 605)

    def test_yousign_request_uses_the_trainee_anchor(self):
        session_obj = self._data("2026-07-23")["sessions"][0]
        trainee = session_obj["trainees"][0]
        trainee["aps_elearning_tracking"] = self._complete_tracking()
        calls = []

        def fake_yousign_json(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if method == "POST" and path == "/signature_requests":
                return {"id": "foad-request-1"}
            if path.endswith("/documents"):
                return {"id": "foad-document-1"}
            if method == "POST" and path.endswith("/signers"):
                return {"id": "foad-signer-1", "signature_link": "https://example.test/foad-sign"}
            if method == "GET" and path.endswith("/signers/foad-signer-1"):
                return {"id": "foad-signer-1", "signature_link": "https://example.test/foad-sign"}
            if path.endswith("/activate"):
                return {"signature_link": "https://example.test/foad-sign"}
            return {}

        with tempfile.TemporaryDirectory() as directory:
            docx_path = os.path.join(directory, "tableau.docx")
            pdf_path = os.path.join(directory, "tableau.pdf")
            with open(docx_path, "wb") as generated_docx:
                generated_docx.write(b"docx")
            with open(pdf_path, "wb") as generated_pdf:
                generated_pdf.write(b"pdf")
            anchors = [{
                "type": "signature",
                "page": 2,
                "x": 110,
                "y": 554,
                "marker_y": 605,
                "width": 160,
                "height": 60,
            }]
            with patch.object(gestion_app, "_yousign_is_configured", return_value=True), patch.object(
                gestion_app,
                "_generate_aps_elearning_tracking_signature_files",
                return_value=(docx_path, pdf_path, pdf_path, anchors),
            ), patch.object(
                gestion_app,
                "_yousign_json",
                side_effect=fake_yousign_json,
            ), patch.object(gestion_app, "_yousign_environment", return_value="sandbox"):
                state = gestion_app.create_yousign_aps_elearning_tracking_signature(
                    session_obj,
                    trainee,
                    "S-APS",
                    "T-APS",
                )

        signer_call = next(call for call in calls if call[1].endswith("/signers"))
        request_call = next(call for call in calls if call[1] == "/signature_requests")
        self.assertEqual(request_call[2]["json"]["external_id"], "aps_foad_S-APS_T-APS")
        self.assertEqual(signer_call[2]["json"]["fields"][0]["page"], 2)
        self.assertEqual(signer_call[2]["json"]["fields"][0]["x"], 110)
        self.assertEqual(signer_call[2]["json"]["fields"][0]["y"], 605)
        self.assertEqual(signer_call[2]["json"]["fields"][0]["layout"], "detailed")
        self.assertEqual(signer_call[2]["json"]["info"]["phone_number"], "+33612345678")
        self.assertTrue(state["provider_signature_embedded"])
        self.assertTrue(state["signed_package_includes_digiforma_annex"])
        self.assertEqual(state["report_sha256"], "a" * 64)
        self.assertFalse(state["forced_incomplete_report"])
        self.assertEqual(state["force_override"], {})
        self.assertEqual(state["status"], "ongoing")

    def test_admin_can_send_tracking_table_to_yousign(self):
        self._admin_login()
        data = self._data("2026-07-23")
        trainee = data["sessions"][0]["trainees"][0]
        trainee["aps_elearning_tracking"] = {
            "file": "uploads/S-APS/T-APS/aps_elearning_tracking/report.pdf",
            "original_name": "attestation-digiforma.pdf",
            "page_count": 2,
        }

        def fake_create(session_obj, target, session_id, trainee_id, force_new=False):
            target["aps_elearning_signature"] = {
                "status": "ongoing",
                "signature_request_id": "foad-request-1",
                "signature_link": "https://example.test/foad-sign",
            }
            return target["aps_elearning_signature"]

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ) as save_data, patch.object(
            gestion_app,
            "create_yousign_aps_elearning_tracking_signature",
            side_effect=fake_create,
        ) as create_signature, patch.object(
            gestion_app,
            "send_yousign_aps_elearning_signature_email",
            return_value=True,
        ) as send_email:
            response = self.client.post(
                "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/tableau-suivi/yousign"
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("#apsElearningTrackingSection"))
        create_signature.assert_called_once()
        send_email.assert_called_once_with(
            data["sessions"][0],
            trainee,
            "https://example.test/foad-sign",
        )
        save_data.assert_called_once()

    def test_signed_tracking_table_is_downloadable(self):
        self._admin_login()
        data = self._data("2026-07-23")
        trainee = data["sessions"][0]["trainees"][0]
        with tempfile.TemporaryDirectory() as directory:
            signed_path = os.path.join(directory, "tableau-signe.pdf")
            with open(signed_path, "wb") as signed_pdf:
                signed_pdf.write(b"%PDF-signed-foad")
            trainee["aps_elearning_signature"] = {
                "status": "done",
                "signed_at": "2026-09-01T10:00:00Z",
                "signed_pdf_path": signed_path,
            }
            with patch.object(gestion_app, "load_data", return_value=data), patch.object(
                gestion_app, "YOUSIGN_APS_ELEARNING_SIGNED_DIR", directory
            ):
                response = self.client.get(
                    "/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/tableau-suivi/yousign/signed.pdf"
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"%PDF-signed-foad")
        self.assertIn("attachment", response.headers.get("Content-Disposition", ""))

    def test_yousign_webhook_routes_tracking_signature_without_touching_convention(self):
        data = self._data("2026-07-23")
        trainee = data["sessions"][0]["trainees"][0]
        trainee["aps_elearning_signature"] = {
            "status": "ongoing",
            "signature_request_id": "foad-request-1",
        }
        payload = {
            "event_name": "signature_request.done",
            "event_id": "event-1",
            "data": {"signature_request": {"id": "foad-request-1", "status": "done"}},
        }

        with patch.object(gestion_app, "_verify_yousign_webhook_signature", return_value=True), patch.object(
            gestion_app, "load_data", return_value=data
        ), patch.object(gestion_app, "save_data") as save_data, patch.object(
            gestion_app, "_mark_yousign_aps_elearning_tracking_signed"
        ) as mark_tracking, patch.object(
            gestion_app, "_mark_yousign_convention_signed"
        ) as mark_convention:
            response = self.client.post("/webhooks/yousign", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["document_type"], "aps_elearning")
        mark_tracking.assert_called_once()
        mark_convention.assert_not_called()
        save_data.assert_called_once()

    def test_trainee_api_saves_link_only_when_aps_elearning_is_enabled(self):
        self._admin_login()
        data = self._data("2026-06-15")

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/api/sessions/S-APS/stagiaires/T-APS/update",
                json={
                    "aps_elearning_login": "https://ediser.elmg.net/access/nouveau-lien",
                    "aps_elearning_password": "doit-etre-ignore",
                },
            )

        self.assertEqual(response.status_code, 200)
        trainee = data["sessions"][0]["trainees"][0]
        self.assertEqual(
            trainee["aps_elearning_login"],
            "https://ediser.elmg.net/access/nouveau-lien",
        )
        self.assertNotIn("aps_elearning_password", trainee)

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            invalid = self.client.post(
                "/api/sessions/S-APS/stagiaires/T-APS/update",
                json={"aps_elearning_login": "pas-un-lien"},
            )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(
            invalid.get_json()["error"],
            "aps_elearning_link_invalid",
        )
        self.assertEqual(
            trainee["aps_elearning_login"],
            "https://ediser.elmg.net/access/nouveau-lien",
        )

        data["sessions"][0]["aps_elearning_enabled"] = False
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/api/sessions/S-APS/stagiaires/T-APS/update",
                json={
                    "aps_elearning_login": "https://ediser.elmg.net/access/doit-etre-ignore"
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            trainee["aps_elearning_login"],
            "https://ediser.elmg.net/access/nouveau-lien",
        )

    def test_public_space_hides_link_before_first_training_day(self):
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
        self.assertNotIn("https://ediser.elmg.net/access/alice-aps", html)
        self.assertNotIn("Accéder au e-learning", html)
        self.assertNotIn('id="apsElearningPassword"', html)

    def test_public_space_shows_personal_link_from_first_day(self):
        self._public_login()
        data = self._data(datetime.date.today().isoformat())

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.get("/espace/PUBLIC-TOKEN")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(
            'href="https://ediser.elmg.net/access/alice-aps"',
            html,
        )
        self.assertIn("Accéder au e-learning", html)
        self.assertNotIn('data-copy-target="apsElearningLogin"', html)
        self.assertNotIn('data-copy-target="apsElearningPassword"', html)
        self.assertNotIn('id="apsElearningPassword"', html)

    def test_public_space_does_not_make_legacy_login_clickable(self):
        self._public_login()
        data = self._data(datetime.date.today().isoformat())
        data["sessions"][0]["trainees"][0]["aps_elearning_login"] = "alice.aps"

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.get("/espace/PUBLIC-TOKEN")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Le lien enregistré n’est pas valide", html)
        self.assertNotIn('href="alice.aps"', html)
        self.assertNotIn("Accéder au e-learning", html)

    def test_public_space_does_not_show_aps_card_for_vtc_or_disabled_session(self):
        self._public_login()
        for training_type, enabled in (("VTC", True), ("APS", False)):
            data = self._data(
                datetime.date.today().isoformat(),
                enabled=enabled,
                training_type=training_type,
            )
            with patch.object(gestion_app, "load_data", return_value=data), patch.object(
                gestion_app, "save_data"
            ):
                response = self.client.get("/espace/PUBLIC-TOKEN")
            html = response.get_data(as_text=True)
            self.assertNotIn("Espace e-learning APS", html)
            self.assertNotIn("https://ediser.elmg.net/access/alice-aps", html)
            self.assertNotIn('id="apsElearningPassword"', html)


if __name__ == "__main__":
    unittest.main()
