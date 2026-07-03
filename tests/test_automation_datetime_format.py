import unittest

import app as gestion_app


class AutomationDateTimeFormatTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
