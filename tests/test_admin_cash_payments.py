import unittest

import app as gestion_app


class AdminCashPaymentsTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_brevo_send_email = gestion_app.brevo_send_email
        self.data = {
            "sessions": [
                {
                    "id": "S-CASH",
                    "name": "APS Mai",
                    "training_type": "APS",
                    "date_start": "2026-05-20",
                    "date_end": "2026-05-24",
                    "trainees": [
                        {
                            "id": "T-PENDING",
                            "last_name": "DUPONT",
                            "first_name": "Alice",
                            "email": "alice@example.test",
                            "phone": "0600000001",
                            "cash_payment_enabled": True,
                            "cash_payment_amount": "300",
                            "cash_payment_installments": [
                                {"amount": 100, "date": "2026-05-16"},
                            ],
                        },
                        {
                            "id": "T-SETTLED",
                            "last_name": "MARTIN",
                            "first_name": "Bruno",
                            "cash_payment_enabled": True,
                            "cash_payment_amount": "250",
                            "cash_payment_installments": [
                                {"amount": 125, "date": "2026-05-15"},
                                {"amount": 125, "date": "2026-05-17"},
                            ],
                            "cash_payment_settled": True,
                            "cash_payment_settled_date": "2026-05-17",
                            "cash_payment_settled_comment": "Reçu remis",
                        },
                        {
                            "id": "T-NO-CASH",
                            "last_name": "DURAND",
                            "first_name": "Camille",
                        },
                    ],
                },
                {
                    "id": "S-ARCHIVED",
                    "name": "Session archivée",
                    "training_type": "APS",
                    "archived": True,
                    "trainees": [
                        {
                            "id": "T-ARCHIVED",
                            "last_name": "ARCHIVE",
                            "first_name": "Anne",
                            "cash_payment_enabled": True,
                            "cash_payment_amount": "999",
                        }
                    ],
                },
            ]
        }
        gestion_app.load_data = lambda: self.data
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app.brevo_send_email = self.original_brevo_send_email

    def test_dashboard_stats_and_rows_include_cash_details(self):
        response = self.client.get("/admin/sessions/paiement-especes")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Paiement espèces", html)
        self.assertIn("DUPONT Alice", html)
        self.assertIn("MARTIN Bruno", html)
        self.assertIn("300,00 €", html)
        self.assertIn("200,00 €", html)
        self.assertIn("550,00 €", html)
        self.assertIn("350,00 €", html)
        self.assertIn("Reçu remis", html)
        self.assertIn("@page{size:A4 landscape;margin:8mm}", html)
        self.assertIn(".cash-table{width:100%!important;min-width:0!important;table-layout:fixed", html)
        self.assertIn(".cash-table-wrap{overflow:visible!important", html)
        self.assertNotIn("ARCHIVE Anne", html)

    def test_first_day_reminder_lists_only_outstanding_cash_and_is_idempotent(self):
        saved = []
        emails = []
        gestion_app.save_data = lambda data: saved.append(data)
        gestion_app.brevo_send_email = lambda *args, **kwargs: emails.append((args, kwargs)) or {"ok": True}

        result = gestion_app.run_cash_payment_reminders(today=gestion_app.datetime.date(2026, 5, 20))

        self.assertEqual(result, {"checked": 1, "sent": 1, "failed": 0})
        self.assertEqual(len(emails), 1)
        args, kwargs = emails[0]
        self.assertEqual(args[0], "cassandre@integraleacademy.com")
        self.assertEqual(kwargs["cc_emails"], ["clement@integraleacademy.com"])
        self.assertIn("APS Mai", args[1])
        self.assertIn("Alice DUPONT", args[2])
        self.assertIn("200,00 €", args[2])
        self.assertNotIn("Bruno MARTIN", args[2])
        self.assertIn("du 20/05/2026 au 24/05/2026", kwargs["text_content"])
        self.assertEqual(self.data["sessions"][0]["cash_payment_reminder_sent_on"], "2026-05-20")
        self.assertEqual(len(saved), 1)

        second_result = gestion_app.run_cash_payment_reminders(today=gestion_app.datetime.date(2026, 5, 20))
        self.assertEqual(second_result, {"checked": 0, "sent": 0, "failed": 0})
        self.assertEqual(len(emails), 1)

    def test_reminder_is_not_marked_sent_when_email_fails(self):
        gestion_app.save_data = lambda data: None
        gestion_app.brevo_send_email = lambda *args, **kwargs: {"ok": False, "error": "Brevo indisponible"}

        result = gestion_app.run_cash_payment_reminders(today=gestion_app.datetime.date(2026, 5, 20))

        self.assertEqual(result, {"checked": 1, "sent": 0, "failed": 1})
        self.assertNotIn("cash_payment_reminder_sent_on", self.data["sessions"][0])
        self.assertEqual(self.data["sessions"][0]["cash_payment_reminder_last_error"], "Brevo indisponible")

    def test_cash_reminder_cron_rejects_an_invalid_secret(self):
        import os
        original_secret = os.environ.get("CRON_SECRET")
        os.environ["CRON_SECRET"] = "expected-secret"
        try:
            response = self.client.post(
                "/internal/cron/cash-payment-reminders",
                headers={"X-Cron-Secret": "wrong-secret"},
            )
        finally:
            if original_secret is None:
                os.environ.pop("CRON_SECRET", None)
            else:
                os.environ["CRON_SECRET"] = original_secret
        self.assertEqual(response.status_code, 403)
