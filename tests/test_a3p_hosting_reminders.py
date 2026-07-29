import datetime
import unittest

import app as gestion_app


class A3PHostingReminderTests(unittest.TestCase):
    def setUp(self):
        self.original_send = gestion_app.brevo_send_email

    def tearDown(self):
        gestion_app.brevo_send_email = self.original_send

    @staticmethod
    def data(hosting_status="unknown", created_at="2026-08-30T10:00:00+00:00"):
        return {"sessions": [{"id": "S1", "name": "A3P septembre", "training_type": "A3P", "date_start": "2026-09-28", "date_end": "2026-11-20", "trainees": [{"id": "T1", "first_name": "Alice", "last_name": "Martin", "email": "alice@example.com", "created_at": created_at, "hosting_status": hosting_status}]}]}

    def test_sends_the_day_after_registration_and_records_stage(self):
        data = self.data()
        sent = []
        gestion_app.brevo_send_email = lambda *args, **kwargs: sent.append((args, kwargs)) or {"ok": True}

        changed = gestion_app._send_a3p_hosting_reminders(data, datetime.date(2026, 8, 31))

        self.assertTrue(changed)
        self.assertEqual(len(sent), 1)
        self.assertIn("registration", data["sessions"][0]["trainees"][0]["a3p_hosting_reminders"])
        self.assertEqual(sent[0][1]["metadata"]["stage"], "registration")

    def test_stops_all_reminders_when_public_status_is_reserved(self):
        data = self.data(hosting_status="reserved")
        gestion_app.brevo_send_email = lambda *args, **kwargs: self.fail("mail should not be sent")

        changed = gestion_app._send_a3p_hosting_reminders(data, datetime.date(2026, 9, 21))

        self.assertFalse(changed)

    def test_only_sessions_starting_from_september_2026_are_eligible(self):
        data = self.data()
        data["sessions"][0]["date_start"] = "2026-08-31"
        gestion_app.brevo_send_email = lambda *args, **kwargs: self.fail("mail should not be sent")

        self.assertFalse(gestion_app._send_a3p_hosting_reminders(data, datetime.date(2026, 8, 10)))
        self.assertEqual(gestion_app._build_a3p_hosting_dashboard(data)["stats"]["eligible"], 0)

    def test_email_contains_booking_details_and_link(self):
        subject, html_body, text_body = gestion_app.build_a3p_hosting_email("Alice", self.data()["sessions"][0])

        self.assertIn("28/09/2026", subject)
        self.assertIn("54 chemin du Carreou", html_body)
        self.assertIn(gestion_app.A3P_HOSTING_BOOKING_URL, html_body)
        self.assertIn("tarifs", text_body.lower())
        self.assertIn("Vous êtes inscrit(e) en formation", html_body)
        self.assertIn("réserver l’hébergement au sein de notre centre de formation", html_body)
        self.assertIn("dortoir collectif, douches, cuisine équipée", html_body)
        self.assertIn("300 euros pour toute la durée de la formation", html_body)
        self.assertIn("enveloppe portant votre nom et prénom", html_body)
        self.assertNotIn("vous ne recevrez plus de rappel d’hébergement", html_body)
        self.assertIn("Vous êtes inscrit(e) en formation", text_body)
        self.assertIn("300 euros pour toute la durée de la formation", text_body)


if __name__ == "__main__":
    unittest.main()
