import datetime
import unittest
from unittest import mock

import app


class ConventionSignatureReminderTests(unittest.TestCase):
    def test_french_sending_window_observes_daylight_saving_time(self):
        self.assertFalse(app._convention_reminders_allowed_now(datetime.datetime(2026, 7, 27, 5, 59)))
        self.assertTrue(app._convention_reminders_allowed_now(datetime.datetime(2026, 7, 27, 6, 0)))
        self.assertFalse(app._convention_reminders_allowed_now(datetime.datetime(2026, 7, 27, 18, 0)))
        self.assertFalse(app._convention_reminders_allowed_now(datetime.datetime(2026, 1, 27, 6, 59)))
        self.assertTrue(app._convention_reminders_allowed_now(datetime.datetime(2026, 1, 27, 7, 0)))

    def test_reminder_email_uses_the_designed_signature_template(self):
        subject, html_body, text_body = app._build_yousign_signature_reminder_email(
            {"training_type": "APS", "date_start": "2026-09-01", "date_end": "2026-10-27"},
            {"first_name": "Arthur"},
            "https://example.test/sign",
        )

        self.assertIn("Rappel", subject)
        self.assertIn("Rappel de signature", html_body)
        self.assertIn("Signer ma convention", html_body)
        self.assertIn("logo-integrale.png", html_body)
        self.assertIn("https://example.test/sign", text_body)

    def test_successful_reminder_sends_email_and_sms_then_schedules_next_day(self):
        trainee = {
            "id": "trainee-1",
            "first_name": "Arthur",
            "email": "arthur@example.test",
            "phone": "+33612345678",
            "convention_signature": {
                "status": "ongoing",
                "signature_request_id": "request-1",
                "signature_link": "https://example.test/sign",
                "reminder_count": 7,
            },
        }
        data = {"sessions": [{"id": "session-1", "training_type": "APS", "trainees": [trainee]}]}

        with mock.patch.object(app, "_convention_reminders_allowed_now", return_value=True), \
             mock.patch.object(app, "load_data", return_value=data), \
             mock.patch.object(app, "save_data") as save_data, \
             mock.patch.object(app, "brevo_send_email", return_value=True) as send_email, \
             mock.patch.object(app, "brevo_send_sms", return_value=True) as send_sms, \
             mock.patch.object(app, "_now_iso", return_value="2026-07-27T08:00:00Z"):
            ok, _ = app.send_convocation_signature_reminder("trainee-1")

        self.assertTrue(ok)
        send_email.assert_called_once()
        send_sms.assert_called_once()
        save_data.assert_called_once_with(data)
        state = trainee["convention_signature"]
        self.assertEqual(state["reminder_count"], 8)
        self.assertEqual(state["next_reminder_at"], "2026-07-28T08:00:00Z")


if __name__ == "__main__":
    unittest.main()
