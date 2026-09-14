import unittest

import app as gestion_app


class VaeAdminEmailNotificationTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.client.testing = True
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_brevo_send_email = gestion_app.brevo_send_email
        self.original_brevo_send_sms = gestion_app.brevo_send_sms
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app.brevo_send_email = self.original_brevo_send_email
        gestion_app.brevo_send_sms = self.original_brevo_send_sms

    def test_public_vae_desp_submission_emails_cassandre(self):
        data = {
            "sessions": [
                {
                    "id": "S-VAE",
                    "name": gestion_app.PUBLIC_VAE_DESP_SESSION_NAME,
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [],
                }
            ],
            "notifications_admin": [],
        }
        sent_emails = []

        gestion_app.load_data = lambda: data
        gestion_app.save_data = lambda _data: None
        gestion_app.brevo_send_email = lambda to, subject, html, **kwargs: sent_emails.append(
            {"to": to, "subject": subject, "html": html}
        ) or True
        gestion_app.brevo_send_sms = lambda *_args, **_kwargs: True

        response = self.client.post(
            "/vae-desp",
            json={
                "last_name": "Dupont",
                "first_name": "Alice",
                "birth_date": "1990-01-01",
                "email": "alice@example.com",
                "email_confirm": "alice@example.com",
                "phone": "0600000000",
                "eligibility_confirmed": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        cassandre_emails = [email for email in sent_emails if email["to"] == "cassandre@integraleacademy.com"]
        self.assertEqual(len(cassandre_emails), 1)
        self.assertIn("Nouvelle demande", cassandre_emails[0]["subject"])
        self.assertIn("Alice DUPONT", cassandre_emails[0]["html"])

    def test_vae_status_change_emails_cassandre_even_without_student_email(self):
        sent_emails = []
        gestion_app.brevo_send_email = lambda to, subject, html, **kwargs: sent_emails.append(
            {"to": to, "subject": subject, "html": html}
        ) or True

        trainee = {
            "id": "T-VAE",
            "first_name": "Bob",
            "last_name": "Martin",
            "email": "",
            "public_token": "TOKEN",
        }

        gestion_app._notify_vae_status_change(trainee, "livret_1_analysis")

        self.assertEqual([email["to"] for email in sent_emails], ["cassandre@integraleacademy.com"])
        self.assertIn("Changement de statut VAE", sent_emails[0]["subject"])
        self.assertIn("Bob MARTIN", sent_emails[0]["html"])

    def _configure_jury_update(self, *, status="livret_2_validated", jury_date=""):
        trainee = {
            "id": "T-VAE-JURY",
            "first_name": "Milla",
            "last_name": "Test",
            "email": "milla@example.com",
            "public_token": "TOKEN-JURY",
            "vae_status": status,
            "vae_status_label": gestion_app.vae_status_view(status)["label"],
            "vae_jury_date": jury_date,
            "vae_action_dates": {},
        }
        data = {
            "sessions": [{
                "id": "S-VAE-JURY",
                "name": "Session VAE",
                "training_type": "DIRIGEANT VAE",
                "trainees": [trainee],
                "vae_live_notifications": [],
            }],
            "notifications_admin": [],
        }
        sent_emails = []
        gestion_app.load_data = lambda: data
        gestion_app.save_data = lambda _data: None
        gestion_app.brevo_send_email = lambda to, subject, html, **kwargs: sent_emails.append(
            {"to": to, "subject": subject, "html": html}
        ) or True
        gestion_app.brevo_send_sms = lambda *_args, **_kwargs: True
        return trainee, sent_emails

    def _student_jury_emails(self, sent_emails):
        return [email for email in sent_emails if email["to"] == "milla@example.com"]

    def test_setting_jury_status_and_date_sends_date_once(self):
        _trainee, sent_emails = self._configure_jury_update()

        response = self.client.post(
            "/api/sessions/S-VAE-JURY/stagiaires/T-VAE-JURY/update",
            json={"vae_status": "jury", "vae_jury_date": "2026-10-15"},
        )

        self.assertEqual(response.status_code, 200)
        student_emails = self._student_jury_emails(sent_emails)
        self.assertEqual(len(student_emails), 1)
        self.assertIn("15/10/2026", student_emails[0]["html"])
        self.assertNotIn("DD/MM/YYYY", student_emails[0]["html"])

    def test_setting_date_for_existing_jury_status_sends_updated_date_once(self):
        _trainee, sent_emails = self._configure_jury_update(status="jury")

        response = self.client.post(
            "/api/sessions/S-VAE-JURY/stagiaires/T-VAE-JURY/update",
            json={"vae_status": "jury", "vae_jury_date": "2026-11-03"},
        )

        self.assertEqual(response.status_code, 200)
        student_emails = self._student_jury_emails(sent_emails)
        self.assertEqual(len(student_emails), 1)
        self.assertIn("03/11/2026", student_emails[0]["html"])

    def test_unchanged_or_cleared_jury_date_does_not_send_email(self):
        trainee, sent_emails = self._configure_jury_update(status="jury", jury_date="2026-11-03")

        unchanged = self.client.post(
            "/api/sessions/S-VAE-JURY/stagiaires/T-VAE-JURY/update",
            json={"vae_status": "jury", "vae_jury_date": "2026-11-03"},
        )
        cleared = self.client.post(
            "/api/sessions/S-VAE-JURY/stagiaires/T-VAE-JURY/update",
            json={"vae_status": "jury", "vae_jury_date": ""},
        )

        self.assertEqual(unchanged.status_code, 200)
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(trainee["vae_jury_date"], "")
        self.assertEqual(self._student_jury_emails(sent_emails), [])


if __name__ == "__main__":
    unittest.main()
