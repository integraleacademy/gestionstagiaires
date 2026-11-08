import os
import tempfile
import unittest
from unittest import mock

import app as gestion_app


class VtcConvocationAutomationTests(unittest.TestCase):
    def setUp(self):
        self.session = {
            "id": "S-VTC",
            "training_type": "VTC",
            "name": "Chauffeur VTC",
            "date_start": "2026-09-01",
            "date_end": "2026-09-30",
            "exam_theory_date": "2026-10-02",
            "practice_training_date": "2026-10-12",
            "exam_practice_date": "2026-10-20",
        }
        self.trainee = {
            "id": "T-1",
            "first_name": "Camille",
            "last_name": "Martin",
            "email": "camille@example.test",
            "phone": "0600000000",
        }

    def test_vtc_context_exposes_practice_training_and_exam_dates(self):
        context = gestion_app._build_aps_convocation_context(self.session, self.trainee)

        self.assertEqual(context["date_formation_pratique"], "12/10/2026")
        self.assertEqual(context["date_formation_pratique_vtc"], "12/10/2026")
        self.assertEqual(context["date_examen_theorique"], "02/10/2026")
        self.assertEqual(context["date_examen_pratique"], "20/10/2026")

    def test_theory_success_generates_and_attaches_vtc_convocation(self):
        with tempfile.TemporaryDirectory() as directory:
            docx_path = os.path.join(directory, "convocation.docx")
            pdf_path = os.path.join(directory, "convocation.pdf")
            open(docx_path, "wb").write(b"docx")
            open(pdf_path, "wb").write(b"pdf")
            with mock.patch.object(gestion_app, "_generate_aps_convocation_files", return_value=(docx_path, pdf_path)), \
                 mock.patch.object(gestion_app, "brevo_send_email", return_value=True) as send_email, \
                 mock.patch.object(gestion_app, "brevo_send_sms", return_value=True):
                result = gestion_app._send_vtc_theory_exam_notification(self.session, self.trainee)

        self.assertTrue(result["email_ok"])
        self.assertEqual(send_email.call_args.kwargs["attachments"][0]["content"], "cGRm")
        self.assertEqual(self.trainee["convocation_aps_status"], "sent")
        self.assertEqual(self.trainee["convocation_aps_pdf_path"], pdf_path)

    def test_signing_convention_never_sends_vtc_convocation(self):
        with mock.patch.object(gestion_app, "_generate_aps_convocation_files") as generate:
            sent = gestion_app._send_convocation_after_convention_signed(
                self.session, self.trainee, "S-VTC", "T-1"
            )

        self.assertFalse(sent)
        generate.assert_not_called()

    def test_signature_does_not_schedule_or_expire_vtc_convocation(self):
        self.session.update(
            date_end="2000-09-11",
            practice_training_date="2099-12-23",
            trainees=[self.trainee],
        )
        with mock.patch.object(gestion_app.threading, "Timer") as timer:
            gestion_app._schedule_convocation_after_convention_signed(
                self.session, self.trainee, "S-VTC", "T-1"
            )
        timer.assert_not_called()
        self.assertFalse(self.trainee.get("convocation_auto_scheduled_at"))

        # Data recorded by older versions can still contain a signature-triggered timer.
        self.trainee["convocation_auto_scheduled_at"] = "2000-09-10T10:05:00Z"
        with mock.patch.object(gestion_app, "_send_convocation_after_convention_signed") as send:
            changed = gestion_app._process_due_convocation_after_convention_signed(
                {"sessions": [self.session]}
            )
        self.assertFalse(changed)
        send.assert_not_called()
        self.assertFalse(self.trainee.get("convocation_auto_last_error"))

    def test_dashboard_shows_theory_wait_with_an_old_signature_expiry(self):
        self.trainee.update(
            convention_legacy_signed_at="2026-09-10T10:00:00Z",
            convocation_auto_last_error="Envoi automatique expiré : session terminée le 11/09/2026.",
        )
        self.session["trainees"] = [self.trainee]
        with gestion_app.app.test_request_context("/"):
            dashboard = gestion_app._build_automations_dashboard({"sessions": [self.session]})
            row = dashboard["rows"][0]
            self.assertEqual(dashboard["stats"]["errors"], 0)
            self.assertEqual(row["error"], "")
            self.assertEqual(row["convocation_label"], "En attente de la théorie")
            self.assertEqual(row["block_reason"], "En attente de réussite à l’examen théorique")

            self.trainee["convocation_aps_last_error"] = "Échec d’envoi de la convocation pratique."
            dashboard = gestion_app._build_automations_dashboard({"sessions": [self.session]})
            self.assertEqual(dashboard["stats"]["errors"], 1)
            self.assertEqual(dashboard["rows"][0]["error"], self.trainee["convocation_aps_last_error"])

    def test_automation_waits_for_theory_instead_of_convention(self):
        with gestion_app.app.test_request_context("/"):
            status = gestion_app._build_trainee_automation_status(
                self.session, self.trainee, "S-VTC", "T-1"
            )

        self.assertTrue(status["has_convocation"])
        self.assertEqual(
            [step["label"] for step in status["timeline"]],
            ["Convention envoyée", "Convention signée", "Convocation"],
        )
        self.assertEqual(status["total_documents"], 3)
        self.assertFalse(status["convocation"]["can_generate"])
        self.assertEqual(status["convocation"]["block_reason"], "En attente de réussite à l’examen théorique")
        self.assertEqual(status["convocation"]["timeline_steps"][0]["label"], "Examen théorique")


if __name__ == "__main__":
    unittest.main()
