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
                    "convention_signature": {"status": "ongoing", "signature_request_id": "req-1"}, "cnaps_status": "en cours",
                }],
            }],
            "cnaps_status_change_notifications": {
                "ADA|123": {"first_name": "Ada", "last_name": "Lovelace", "signature": "Titre actif", "sent_at": "2026-07-27T09:00:00Z"}
            },
            "billing_lines": [],
        }

    def test_report_contains_all_operational_categories(self):
        with mock.patch.object(app, "fetch_cnapsv3_tracking_requests", return_value=([], "indisponible")):
            report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        self.assertEqual(report["sales"]["revenue"], 1200)
        self.assertEqual(report["sales"]["count"], 1)
        self.assertEqual(len(report["cnaps_changes"]), 1)
        self.assertEqual(len(report["pending_signatures"]), 1)
        self.assertEqual(len(report["incomplete_upcoming"]), 1)
        self.assertEqual(len(report["cnaps_pending"]), 1)
        subject, body = app.build_daily_recap_email(report)
        self.assertEqual(subject, "Récapitulatif de la veille")
        self.assertIn("Chiffre d’affaires de la veille", body)
        self.assertIn("Prélèvements rejetés", body)
        self.assertIn("Conventions en attente de signature", body)
        self.assertIn("👮", body)

    def test_cnaps_pending_only_contains_enrolled_in_progress_trainees(self):
        trainees = self.data["sessions"][0]["trainees"]
        trainees.extend([
            {"first_name": "Grace", "last_name": "Hopper", "cnaps_status": "transmis"},
            {"first_name": "Alan", "last_name": "Turing", "cnaps_status": "validé"},
            {"first_name": "Katherine", "last_name": "Johnson", "cnaps_status": ""},
        ])
        with mock.patch.object(app, "fetch_cnapsv3_tracking_requests", return_value=([], "indisponible")):
            report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        self.assertEqual([item["name"] for item in report["cnaps_pending"]], [app._daily_recap_name(trainees[0])])

    def test_cnaps_pending_uses_enrolled_in_progress_tracking_rows(self):
        rows = [
            {"first_name": "Ada", "last_name": "Lovelace", "cnaps_status": "EN COURS"},
            {"first_name": "Grace", "last_name": "Hopper", "cnaps_status": "EN COURS"},
            {"first_name": "Alan", "last_name": "Turing", "cnaps_status": "ACCEPTE"},
        ]
        enriched = [
            {**rows[0], "is_enrolled": True, "enrollment": {"training_type": "APS"}},
            {**rows[1], "is_enrolled": False, "enrollment": {}},
            {**rows[2], "is_enrolled": True, "enrollment": {"training_type": "APS"}},
        ]
        with mock.patch.object(app, "fetch_cnapsv3_tracking_requests", return_value=(rows, None)), \
             mock.patch.object(app, "enrich_cnaps_tracking_rows_with_enrollment", return_value=enriched):
            report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        self.assertEqual([item["name"] for item in report["cnaps_pending"]], [app._format_trainee_name("Ada", "Lovelace")])

    def test_rejected_debits_are_translated_and_grouped_by_trainee(self):
        self.data["billing_lines"] = [{
            "traineeId": "T1", "traineeFirstName": "Ada", "traineeLastName": "Lovelace",
            "formationName": "APS", "directDebitInstallments": [
                {"status": "rejected", "date": "2026-07-27", "amount": 100, "status_reason": "blocked_account"},
                {"status": "failed", "date": "2026-07-27", "amount": 200, "failureReason": "insufficient_funds"},
            ],
        }]
        with mock.patch.object(app, "_billing_lines", return_value=self.data["billing_lines"]):
            report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        self.assertEqual(len(report["rejected"]), 1)
        self.assertIn("Compte bancaire bloqué", report["rejected"][0]["detail"])
        self.assertIn("Solde insuffisant", report["rejected"][0]["detail"])
        self.assertEqual(report["rejected"][0]["detail"].count("APS"), 2)

    def test_user_requested_rejection_reason_is_in_french(self):
        self.assertEqual(app._daily_recap_rejection_reason("User requested"), "Rejet demandé par le titulaire")

    def test_pending_conventions_match_actionable_yousign_requests(self):
        trainees = self.data["sessions"][0]["trainees"]
        trainees[0]["convention_signature"]["signature_request_id"] = "req-1"
        trainees.append({
            "id": "T2", "first_name": "Ancien", "last_name": "Statut",
            "convention_signature": {"status": "ongoing"},
        })
        with mock.patch.object(app, "fetch_cnapsv3_tracking_requests", return_value=([], "indisponible")):
            report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        self.assertEqual([item["name"] for item in report["pending_signatures"]], [app._format_trainee_name("Ada", "Lovelace")])

    def test_revenue_uses_same_vae_certification_date_as_sales_dashboard(self):
        self.data["sessions"][0]["training_type"] = "DIRIGEANT VAE"
        trainee = self.data["sessions"][0]["trainees"][0]
        trainee.update({
            "created_at": "2026-07-20", "vae_status": "certified",
            "vae_action_dates": {"diplome_obtenu": "2026-07-27"},
            "sales_tracking_amount": 3800,
        })
        with mock.patch.object(app, "fetch_cnapsv3_tracking_requests", return_value=([], "indisponible")):
            report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        self.assertEqual(report["sales"]["revenue"], 3800)

    def test_revenue_has_daily_weekly_monthly_and_yearly_comparisons(self):
        trainees = self.data["sessions"][0]["trainees"]
        for index, created_at in enumerate(("2026-07-26", "2026-07-20", "2026-06-27", "2025-07-27"), start=2):
            trainees.append({
                "id": f"T{index}", "first_name": "Comparatif", "last_name": str(index),
                "created_at": created_at, "sales_tracking_amount": 100 * index, "cnaps_status": "validé",
            })
        report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        self.assertEqual(set(report["comparison_sales"]), {"previous_day", "previous_week", "previous_month", "previous_year"})
        _subject, body = app.build_daily_recap_email(report)
        for label in ("jour précédent", "semaine précédente", "mois précédent", "année précédente"):
            self.assertIn(label, body)
        self.assertIn("APS <span", body)

    def test_delivery_targets_four_recipients_and_is_idempotent(self):
        sent = []
        now = datetime.datetime(2026, 7, 28, 8, tzinfo=ZoneInfo("Europe/Paris"))
        greeting_context = {
            "date": now.date(), "nameday": "Saint Samson",
            "weather": {
                "puget": {"temperature": 31, "description": "la journée sera ensoleillée"},
                "aurillac": {"temperature": 22, "description": "la journée sera nuageuse"},
            },
        }
        with mock.patch.object(app, "load_data", return_value=self.data), \
             mock.patch.object(app, "save_data"), \
             mock.patch.object(app, "fetch_daily_recap_greeting_context", return_value=greeting_context), \
             mock.patch.object(app, "brevo_send_email", side_effect=lambda *args, **kwargs: sent.append((args, kwargs)) or {"ok": True}):
            result = app.run_daily_recap(now=now)
            duplicate = app.run_daily_recap(now=now)
        self.assertTrue(result["sent"])
        self.assertEqual(duplicate["reason"], "already_sent")
        self.assertEqual([call[0][0] for call in sent], list(app.DAILY_RECAP_RECIPIENTS))
        self.assertTrue(all("cc_emails" not in call[1] for call in sent))
        self.assertIn("Bonjour Elsa", sent[0][0][2])
        self.assertIn("Puget sur Argens", sent[0][0][2])
        self.assertIn("Aurillac", sent[0][0][2])
        self.assertIn("Bonjour Aurélie", sent[1][0][2])
        self.assertNotIn("Aurillac", sent[1][0][2])

    def test_personalized_greetings_follow_each_recipient_weather_scope(self):
        context = {
            "date": datetime.date(2026, 7, 29), "nameday": "Sainte Marthe",
            "weather": {
                "puget": {"temperature": 30, "description": "la journée sera ensoleillée"},
                "aurillac": {"temperature": 19, "description": "la journée sera pluvieuse"},
            },
        }
        cassandre = app._daily_recap_greeting("cassandre@integraleacademy.com", context)
        clement = app._daily_recap_greeting("clement@integraleacademy.com", context)
        self.assertIn("Bonjour Cassandre, Nous sommes le mercredi 29 juillet 2026", cassandre)
        self.assertIn("Sainte Marthe", cassandre)
        self.assertIn("30°C", cassandre)
        self.assertNotIn("Aurillac", cassandre)
        self.assertIn("Bonjour Clément", clement)
        self.assertIn("Aurillac", clement)
        self.assertIn("19°C", clement)

    def test_endpoint_rejects_bad_secret(self):
        with mock.patch.dict(os.environ, {"CRON_SECRET": "correct"}):
            response = app.app.test_client().post("/internal/cron/daily-recap", headers={"X-Cron-Secret": "wrong"})
        self.assertEqual(response.status_code, 403)

    def test_sales_tracking_preview_renders_yesterdays_email_without_sending(self):
        client = app.app.test_client()
        yesterday = datetime.datetime.now(ZoneInfo("Europe/Paris")).date() - datetime.timedelta(days=1)
        greeting_context = {
            "date": yesterday + datetime.timedelta(days=1), "nameday": "Saint Samson",
            "weather": {
                "puget": {"temperature": 31, "description": "la journée sera ensoleillée"},
                "aurillac": {"temperature": 22, "description": "la journée sera nuageuse"},
            },
        }
        self.data["sessions"][0]["trainees"][0]["created_at"] = yesterday.isoformat()
        with client.session_transaction() as browser_session:
            browser_session["admin_logged_in"] = True
        with mock.patch.object(app, "load_data", return_value=self.data), \
             mock.patch.object(app, "fetch_daily_recap_greeting_context", return_value=greeting_context) as fetch_greeting, \
             mock.patch.object(app, "brevo_send_email") as send_email:
            response = client.get("/admin/suivi-ventes/apercu-mail-quotidien")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Récapitulatif de la veille", body)
        self.assertIn("Ada Lovelace", body)
        self.assertIn("Bonjour Clément", body)
        self.assertIn("Puget sur Argens", body)
        self.assertIn("Aurillac", body)
        self.assertIn("no-store", response.headers["Cache-Control"])
        fetch_greeting.assert_called_once_with(yesterday + datetime.timedelta(days=1))
        send_email.assert_not_called()

    def test_sales_tracking_page_exposes_daily_email_preview(self):
        client = app.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["admin_logged_in"] = True
        with mock.patch.object(app, "load_data", return_value=self.data):
            response = client.get("/admin/suivi-ventes")
        body = response.get_data(as_text=True)
        self.assertIn("Aperçu du mail de 08h", body)
        self.assertIn("Mail destiné à clement@integraleacademy.com", body)
        self.assertIn("/admin/suivi-ventes/apercu-mail-quotidien", body)


if __name__ == "__main__":
    unittest.main()
