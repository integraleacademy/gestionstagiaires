import unittest

import app as gestion_app


class VaeAdminEmailNotificationTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_brevo_send_email = gestion_app.brevo_send_email
        self.original_brevo_send_sms = gestion_app.brevo_send_sms

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


if __name__ == "__main__":
    unittest.main()
