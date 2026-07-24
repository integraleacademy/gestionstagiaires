import unittest
import unittest.mock

import app as gestion_app


class AutomationDateTimeFormatTests(unittest.TestCase):
    def test_reset_trainee_automations_removes_every_automation_state(self):
        trainee = {
            "id": "T1",
            "convention_signature": {
                "status": "done",
                "signature_request_id": "req_123",
                "unsigned_pdf_path": "/tmp/convention.pdf",
                "signed_pdf_path": "/tmp/convention-signed.pdf",
            },
            "convention_aps_status": "signed",
            "convocation_aps_status": "sent",
            "convocation_aps_pdf_path": "/tmp/convocation.pdf",
            "attestation_entree_aps_sent_at": "2026-07-03T08:13:43Z",
            "attestation_fin_aps_sent_at": "2026-07-03T08:13:43Z",
            "convention_auto_last_error": "ancienne erreur",
            "other_field": "à conserver",
        }

        with unittest.mock.patch.object(gestion_app, "_yousign_is_configured", return_value=False):
            gestion_app._reset_trainee_automations(trainee)

        self.assertEqual(trainee["other_field"], "à conserver")
        self.assertIn("updated_at", trainee)
        for key in gestion_app.AUTOMATION_TRAINEE_FIELDS:
            self.assertNotIn(key, trainee)

    def test_fr_datetime_converts_utc_iso_to_paris_display(self):
        self.assertEqual(
            gestion_app.fr_datetime("2026-07-03T09:35:45.602126Z"),
            "03/07/2026 à 11h35",
        )

    def test_automation_status_formats_dates_and_times_in_french(self):
        trainee = {
            "id": "T1",
            "email": "test@example.com",
            "convention_aps_status": "signed",
            "convocation_aps_status": "sent",
            "convocation_aps_generated_at": "2026-07-03T08:13:43.852227Z",
            "convocation_aps_sent_at": "2026-07-03T08:13:43.852227Z",
            "convocation_aps_pdf_path": "/tmp/convocation.pdf",
            "convention_signature": {
                "status": "done",
                "created_at": "2026-07-03T09:35:45.602126Z",
                "signature_email_sent_at": "2026-07-03T09:35:45.694431Z",
                "signed_at": "2026-07-03T08:08:38.737981Z",
                "signature_request_id": "req_123",
                "unsigned_pdf_path": "/tmp/convention.pdf",
            },
        }

        with gestion_app.app.test_request_context():
            status = gestion_app._build_trainee_automation_status({}, trainee, "S1", "T1")

        self.assertEqual(status["convention"]["timeline_steps"][0]["value"], "03/07/2026 à 11h35")
        self.assertEqual(status["convention"]["timeline_steps"][1]["value"], "03/07/2026 à 11h35")
        self.assertEqual(status["convention"]["timeline_steps"][2]["value"], "Signée le 03/07/2026 à 10h08")
        self.assertEqual(status["convocation"]["timeline_steps"][1]["value"], "03/07/2026 à 10h13")
        self.assertEqual(status["convocation"]["timeline_steps"][2]["value"], "Envoyée le 03/07/2026 à 10h13")


    def test_vae_admin_automation_keeps_convention_sent_and_signed_steps(self):
        trainee = {
            "id": "T-VAE",
            "email": "vae@example.com",
            "convention_signature": {
                "status": "done",
                "signature_request_id": "req_vae",
                "unsigned_pdf_path": "/tmp/convention-vae.pdf",
                "signed_at": "2026-07-03T08:08:38.737981Z",
            },
        }
        session = {"training_type": "DIRIGEANT VAE", "name": "VAE DESP 2026"}

        with gestion_app.app.test_request_context():
            status = gestion_app._build_trainee_automation_status(session, trainee, "S-VAE", "T-VAE")

        self.assertEqual([step["label"] for step in status["timeline"]], ["Convention envoyée", "Convention signée"])
        self.assertEqual(status["ready_documents"], 2)
        self.assertEqual(status["total_documents"], 2)
        self.assertEqual(status["progress_percent"], 100)


    def test_aps_automation_splits_convention_sent_and_signed_steps(self):
        trainee = {
            "id": "T-APS",
            "email": "aps@example.com",
            "convention_signature": {
                "status": "active",
                "signature_request_id": "req_aps",
                "unsigned_pdf_path": "/tmp/convention-aps.pdf",
                "signature_email_sent_at": "2026-07-03T09:35:45.694431Z",
            },
        }
        session = {"training_type": "APS", "name": "APS 2026"}

        with gestion_app.app.test_request_context():
            status = gestion_app._build_trainee_automation_status(session, trainee, "S-APS", "T-APS")

        self.assertEqual(
            [step["label"] for step in status["timeline"]],
            ["Convention envoyée", "Convention signée", "Convocation", "Attestation entrée", "Attestation sortie"],
        )
        self.assertEqual([step["state"] for step in status["timeline"][:3]], ["complete", "pending", "blocked"])
        self.assertEqual(status["ready_documents"], 1)
        self.assertEqual(status["total_documents"], 5)
        self.assertEqual(status["progress_percent"], 20)

    def test_conventions_dashboard_includes_not_generated_conventions(self):
        captured = {}
        data = {
            "sessions": [
                {
                    "id": "S1",
                    "training_type": "A3P",
                    "date_start": "2026-11-01",
                    "date_end": "2026-12-01",
                    "trainees": [
                        {
                            "id": "generated",
                            "first_name": "Generated",
                            "last_name": "Convention",
                            "email": "generated@example.com",
                            "convention_signature": {"unsigned_pdf_path": "/tmp/convention.pdf"},
                        },
                        {
                            "id": "not-generated",
                            "first_name": "Missing",
                            "last_name": "Convention",
                            "email": "missing@example.com",
                        },
                    ],
                }
            ]
        }

        def fake_render_template(template_name, **context):
            captured.update(context)
            return "OK"

        with unittest.mock.patch.object(gestion_app, "load_data", return_value=data), \
             unittest.mock.patch.object(gestion_app, "render_template", side_effect=fake_render_template):
            client = gestion_app.app.test_client()
            with client.session_transaction() as sess:
                sess["admin_logged_in"] = True
            response = client.get("/admin/sessions/conventions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["trainee_id"] for row in captured["rows"]], ["generated", "not-generated"])
        self.assertEqual(captured["stats"]["total"], 2)


if __name__ == "__main__":
    unittest.main()
