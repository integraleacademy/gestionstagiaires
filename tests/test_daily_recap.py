import datetime
import os
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

import app


class DailyRecapTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "sessions": [{
                "id": "S1", "training_type": "APS", "date_start": "2026-07-31",
                "trainees": [{
                    "id": "T1", "first_name": "Ada", "last_name": "Lovelace",
                    "created_at": "2026-07-27T12:00:00Z", "sales_tracking_amount": 1200,
                    "convention_signature": {"status": "ongoing"}, "cnaps_status": "transmis",
                }],
            }],
            "cnaps_status_change_notifications": {
                "ADA|123": {"first_name": "Ada", "last_name": "Lovelace", "signature": "Titre actif", "sent_at": "2026-07-27T09:00:00Z"}
            },
            "billing_lines": [],
        }

    def test_report_contains_all_operational_categories(self):
        report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        self.assertEqual(report["sales"]["revenue"], 1200)
        self.assertEqual(report["sales"]["count"], 1)
        self.assertEqual(len(report["cnaps_changes"]), 1)
        self.assertEqual(len(report["pending_signatures"]), 1)
        self.assertEqual(len(report["incomplete_upcoming"]), 1)
        self.assertEqual(len(report["cnaps_pending"]), 1)
        subject, body = app.build_daily_recap_email(report)
        self.assertEqual(subject, "Récapitulatif de la veille")
        self.assertIn("Chiffre d’affaires", body)
        self.assertIn("Prélèvements rejetés", body)

    def test_delivery_targets_four_recipients_and_is_idempotent(self):
        sent = []
        now = datetime.datetime(2026, 7, 28, 8, tzinfo=ZoneInfo("Europe/Paris"))
        with mock.patch.object(app, "load_data", return_value=self.data), \
             mock.patch.object(app, "save_data"), \
             mock.patch.object(app, "brevo_send_email", side_effect=lambda *args, **kwargs: sent.append((args, kwargs)) or {"ok": True}):
            result = app.run_daily_recap(now=now)
            duplicate = app.run_daily_recap(now=now)
        self.assertTrue(result["sent"])
        self.assertEqual(duplicate["reason"], "already_sent")
        self.assertEqual(sent[0][0][0], "elsa@integraleacademy.com")
        self.assertEqual(sent[0][1]["cc_emails"], list(app.DAILY_RECAP_RECIPIENTS[1:]))

    def test_endpoint_rejects_bad_secret(self):
        with mock.patch.dict(os.environ, {"CRON_SECRET": "correct"}):
            response = app.app.test_client().post("/internal/cron/daily-recap", headers={"X-Cron-Secret": "wrong"})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
