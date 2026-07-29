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
        self.assertNotIn("Prélèvements rejetés", body)
        self.assertIn("Conventions en attente de signature", body)
        self.assertIn("👮", body)

    def test_operational_section_count_badges_share_the_key_dates_style(self):
        with mock.patch.object(app, "fetch_cnapsv3_tracking_requests", return_value=([], "indisponible")):
            report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        report["key_dates"] = [{"name": "Examen demain", "detail": "APS"}]

        _subject, body = app.build_daily_recap_email(report)

        badge_style = 'display:inline-block;min-width:22px;padding:7px 9px;background:#4f46e5;color:#fff;border-radius:12px;text-align:center;font-size:12px;font-weight:900'
        visible_section_count = 5  # Dates clés, changements CNAPS, signatures, dossiers incomplets et CNAPS à valider.
        self.assertEqual(body.count(badge_style), visible_section_count)
        self.assertNotIn("background:#eef2ff;color:#4338ca", body)

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

    def test_pending_direct_debit_mandates_are_listed_in_morning_email(self):
        self.data["billing_lines"] = [
            {
                "traineeId": "T1", "traineeFirstName": "Ada", "traineeLastName": "Lovelace",
                "formationName": "APS", "paymentMode": "sepa_direct_debit",
                "dateStart": "2026-07-31", "dateEnd": "2026-08-28",
                "qonto_direct_debit_mandate_id": "mandate-pending", "qonto_mandate_status": "pending",
            },
            {
                "traineeId": "T2", "traineeFirstName": "Grace", "traineeLastName": "Hopper",
                "formationName": "VTC", "paymentMode": "sepa_direct_debit",
                "qonto_direct_debit_mandate_id": "mandate-signed", "qonto_mandate_status": "signed",
            },
        ]

        with mock.patch.object(app, "_billing_lines", return_value=self.data["billing_lines"]):
            report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        self.assertEqual(report["pending_mandates"], [{
            "name": "Ada Lovelace", "detail": "APS · du 31/07/2026 au 28/08/2026 · Signature du mandat en attente",
        }])

        _subject, body = app.build_daily_recap_email(report)
        self.assertIn("Mandats de prélèvement à valider", body)
        self.assertIn("Ada Lovelace", body)
        self.assertIn("du 31/07/2026 au 28/08/2026", body)
        self.assertNotIn("Grace Hopper", body)

    def test_pending_mandate_billing_line_displays_formation_dates(self):
        self.data["sessions"] = []
        self.data["billing_lines"] = [{
            "traineeId": "T1", "traineeFirstName": "Ada", "traineeLastName": "Lovelace",
            "formationName": "APS", "paymentMode": "sepa_direct_debit",
            "dateStart": "2026-07-31", "dateEnd": "2026-08-28",
            "qonto_direct_debit_mandate_id": "mandate-pending", "qonto_mandate_status": "pending",
        }]

        with mock.patch.object(app, "_billing_lines", return_value=self.data["billing_lines"]):
            report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))

        self.assertEqual(report["pending_mandates"][0]["detail"],
                         "APS · du 31/07/2026 au 28/08/2026 · Signature du mandat en attente")

    def test_user_requested_rejection_reason_is_in_french(self):
        self.assertEqual(app._daily_recap_rejection_reason("User requested"), "Rejet demandé par le titulaire")

    def test_empty_operational_sections_are_hidden(self):
        report = app.build_daily_recap_data({"sessions": [], "billing_lines": []}, datetime.date(2026, 7, 27))
        _subject, body = app.build_daily_recap_email(report)
        for title in ("Dates clés", "Suivi des VAE", "Changements CNAPS", "Prélèvements rejetés", "Dossiers incomplets · J-7"):
            self.assertNotIn(title, body)

    def test_key_dates_include_training_and_exam_reminders(self):
        self.data["sessions"] = [
            {"name": "APS été", "training_type": "APS", "date_start": "2026-07-29", "date_end": "2026-08-20", "exam_date": "2026-08-04", "trainees": []},
            {"name": "VTC juillet", "training_type": "VTC", "date_start": "2026-07-01", "date_end": "2026-07-30", "exam_theory_date": "2026-07-29", "trainees": []},
        ]
        report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        self.assertEqual(len(report["key_dates"]), 3)
        _subject, body = app.build_daily_recap_email(report)
        self.assertIn("Dates clés", body)
        self.assertIn("Début de formation demain", body)
        self.assertIn("Examen théorique demain", body)
        self.assertIn("Examen dans 7 jours", body)
        self.assertIn("Pensez à générer les dossiers d’examen", body)
        self.assertIn("Agenda opérationnel", body)
        self.assertIn("Les prochaines échéances à ne pas manquer", body)
        self.assertIn("À préparer aujourd’hui", body)
        self.assertIn("À anticiper", body)

    def test_vae_follow_up_counts_yesterdays_transitions(self):
        self.data["sessions"] = [{
            "training_type": "DIRIGEANT VAE", "date_start": "2026-01-01",
            "trainees": [
                {"created_at": "2026-07-27T10:00:00Z", "vae_action_dates": {"livret_1_validated": "27/07/2026"}},
                {"created_at": "2026-07-20", "vae_action_dates": {"livret_2_validated": "2026-07-27", "diplome_obtenu": "27/07/2026 à 16h30"}},
            ],
        }]
        report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        self.assertEqual(report["vae_follow_up"], {
            "new_requests": 1, "livret_1_validated": 1,
            "livret_2_validated": 1, "certification_obtained": 1,
        })
        _subject, body = app.build_daily_recap_email(report)
        self.assertIn("Suivi des VAE", body)
        self.assertIn("Nouvelles demandes VAE", body)
        self.assertIn("Certifications obtenues", body)

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
        self.assertLess(body.index(">1</span>"), body.index("APS</span>"))

    def test_kpi_hides_empty_comparisons_and_displays_month_objective(self):
        self.data["sales_tracking"] = {"objectives": {"2026": {"months": {"7": 6000}}}}
        report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        _subject, body = app.build_daily_recap_email(report)
        self.assertEqual(report["month_kpi"]["revenue"], 1200)
        self.assertEqual(report["month_kpi"]["progress_ratio"], .2)
        self.assertIn("20% atteint", body)
        self.assertIn("1 200,00 € / 6 000,00 €", body)
        self.assertNotIn("année précédente", body)
        self.assertNotIn("(0,00 €)", body)

    def test_cnaps_pending_matches_enrolled_rows_with_no_annuaire_title(self):
        rows = [
            {"first_name": "Ada", "last_name": "Lovelace", "nub": "1234567", "cnaps_status": "TRANSMIS"},
            {"first_name": "Grace", "last_name": "Hopper", "nub": "7654321", "cnaps_status": "EN COURS"},
        ]
        enriched = [
            {**rows[0], "is_enrolled": True, "enrollment": {"training_type": "APS"}},
            {**rows[1], "is_enrolled": False, "enrollment": {}},
        ]
        self.data["cnaps_public_annuaire_statuses"] = {"LOVELACE|1234567": {"known": False}}
        with mock.patch.object(app, "fetch_cnapsv3_tracking_requests", return_value=(rows, None)), \
             mock.patch.object(app, "enrich_cnaps_tracking_rows_with_enrollment", return_value=enriched):
            report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        self.assertEqual([item["name"] for item in report["cnaps_pending"]], [app._format_trainee_name("Ada", "Lovelace")])
        self.assertIn("Aucun titre CNAPS trouvé", report["cnaps_pending"][0]["detail"])

    def test_cnaps_pending_includes_session_dates_and_taj_warning_after_ten_days(self):
        rows = [{"first_name": "Ada", "last_name": "Lovelace", "nub": "1234567", "cnaps_status": "TRANSMIS"}]
        enriched = [{**rows[0], "is_enrolled": True, "enrollment": {
            "session_name": "APS été", "training_type": "APS",
            "date_start": "2026-07-31", "date_end": "2026-08-28",
        }}]
        self.data["cnaps_public_annuaire_statuses"] = {
            "LOVELACE|1234567": {"known": False, "status_since": "2026-07-18T08:00:00Z"},
        }
        with mock.patch.object(app, "fetch_cnapsv3_tracking_requests", return_value=(rows, None)), \
             mock.patch.object(app, "enrich_cnaps_tracking_rows_with_enrollment", return_value=enriched):
            report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        item = report["cnaps_pending"][0]
        self.assertIn("APS été · APS · du 31/07/2026 au 28/08/2026", item["detail"])
        self.assertTrue(item["taj_suspected"])
        _subject, body = app.build_daily_recap_email(report)
        self.assertIn("Suspicion de TAJ", body)

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
        self.assertEqual(result["delivery_status"], "accepted_by_provider")
        self.assertEqual(len(result["deliveries"]), 4)
        self.assertTrue(all(item["accepted"] for item in result["deliveries"]))
        self.assertEqual(duplicate["reason"], "already_sent")
        self.assertEqual([call[0][0] for call in sent], list(app.DAILY_RECAP_RECIPIENTS))
        self.assertTrue(all("cc_emails" not in call[1] for call in sent))
        self.assertIn("Bonjour Elsa", sent[0][0][2])
        self.assertIn("Puget sur Argens", sent[0][0][2])
        self.assertIn("Aurillac", sent[0][0][2])
        self.assertIn("Bonjour Aurélie", sent[1][0][2])
        self.assertIn("Aurillac", sent[1][0][2])

    def test_personalized_greetings_include_both_weather_locations_for_every_recipient(self):
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
        self.assertIn("Sainte-Marthe", cassandre)
        self.assertIn("30°C", cassandre)
        self.assertIn("Aurillac", cassandre)
        self.assertIn("Bonjour Clément", clement)
        self.assertIn("Aurillac", clement)
        self.assertIn("19°C", clement)

    def test_greeting_uses_nameday_and_weather_visuals(self):
        context = {
            "date": datetime.date(2026, 7, 28), "nameday": "Sainte Sophie",
            "weather": {
                "puget": {"temperature": 32, "description": "la journée sera ensoleillée", "icon": "☀️"},
                "aurillac": {"temperature": 18, "description": "la journée sera pluvieuse", "icon": "🌧️"},
            },
        }
        report = app.build_daily_recap_data(self.data, datetime.date(2026, 7, 27))
        _subject, body = app.build_daily_recap_email(report, recipient="clement@integraleacademy.com", greeting_context=context)
        self.assertIn("Bonjour Clément 👋", body)
        self.assertIn("Nous sommes le mardi 28 juillet et aujourd'hui c'est la Sainte-Sophie !", body)
        self.assertNotIn("🎉", body)
        self.assertIn("☀️", body)
        self.assertIn("🌧️", body)
        expected_quote = app._daily_recap_quote(context["date"])
        self.assertIn(expected_quote["text"], body)
        self.assertIn(expected_quote["author"], body)
        self.assertLess(body.index("Citation du jour"), body.index(expected_quote["text"]))
        self.assertNotIn("la fête du jour", body)

        marthe_context = {**context, "date": datetime.date(2026, 7, 29), "nameday": "Sainte Marthe"}
        marthe_html = app._daily_recap_greeting_html("clement@integraleacademy.com", marthe_context)
        self.assertIn("Nous sommes le mercredi 29 juillet et aujourd'hui c'est la Sainte-Marthe !", marthe_html)
        self.assertNotIn("🎉 Nous sommes le mercredi 29 juillet", marthe_html)

    def test_weather_codes_have_matching_icons(self):
        self.assertEqual(app._daily_recap_weather_icon(0), "☀️")
        self.assertEqual(app._daily_recap_weather_icon(61), "🌧️")
        self.assertEqual(app._daily_recap_weather_icon(95), "⛈️")
        self.assertEqual(app._daily_recap_weather_description(51), "un risque de bruine est prévu")
        self.assertEqual(app._daily_recap_weather_description(61), "des passages pluvieux sont prévus")
        self.assertEqual(app._daily_recap_weather_description(80), "un risque d’averses est prévu")

    def test_weather_fetch_and_card_include_precipitation_probability(self):
        weather_response = mock.Mock()
        weather_response.raise_for_status.return_value = None
        weather_response.json.return_value = {
            "daily": {
                "weather_code": [80],
                "temperature_2m_max": [24.4],
                "precipitation_probability_max": [35],
            }
        }
        with mock.patch.object(app.requests, "get", return_value=weather_response) as request_get:
            context = app.fetch_daily_recap_greeting_context(datetime.date(2026, 7, 30))

        self.assertEqual(context["weather"]["aurillac"]["precipitation_probability"], 35)
        self.assertIn("precipitation_probability_max", request_get.call_args.kwargs["params"]["daily"])
        body = app._daily_recap_greeting_html("clement@integraleacademy.com", context)
        self.assertIn("Risque de précipitations : 35 %", body)
        self.assertIn("Un risque d’averses", body)

    def test_nameday_calendar_is_complete_and_used_without_network(self):
        expected_days = {month: 31 for month in (1, 3, 5, 7, 8, 10, 12)}
        expected_days.update({month: 30 for month in (4, 6, 9, 11)})
        expected_days[2] = 28
        self.assertEqual({month: len(days) for month, days in app.DAILY_RECAP_NAMEDAYS.items()}, expected_days)
        self.assertEqual(app._daily_recap_nameday(datetime.date(2026, 8, 21)), "Christophe")
        self.assertEqual(app._daily_recap_nameday(datetime.date(2026, 7, 29)), "Sainte Marthe")
        self.assertEqual(app._daily_recap_nameday(datetime.date(2028, 2, 29)), "Romain")

        weather_response = mock.Mock()
        weather_response.raise_for_status.return_value = None
        weather_response.json.return_value = {"daily": {"weather_code": [0], "temperature_2m_max": [28], "precipitation_probability_max": [0]}}
        with mock.patch.object(app.requests, "get", return_value=weather_response) as request_get:
            context = app.fetch_daily_recap_greeting_context(datetime.date(2026, 8, 21))
        self.assertEqual(context["nameday"], "Christophe")
        self.assertTrue(all("nominis" not in call.args[0] for call in request_get.call_args_list))

    def test_email_always_displays_calendar_nameday(self):
        report = app.build_daily_recap_data(self.data, datetime.date(2026, 8, 20))
        context = {"date": datetime.date(2026, 8, 21), "nameday": app._daily_recap_nameday(datetime.date(2026, 8, 21)), "weather": {}}
        _subject, body = app.build_daily_recap_email(report, recipient="clement@integraleacademy.com", greeting_context=context)
        self.assertIn("Nous sommes le vendredi 21 août et aujourd'hui c'est la Saint-Christophe !", body)

    def test_endpoint_rejects_bad_secret(self):
        with mock.patch.dict(os.environ, {"CRON_SECRET": "correct"}):
            response = app.app.test_client().post("/internal/cron/daily-recap", headers={"X-Cron-Secret": "wrong"})
        self.assertEqual(response.status_code, 403)

    def test_sales_tracking_preview_renders_tomorrows_email_without_sending(self):
        client = app.app.test_client()
        today = datetime.datetime.now(ZoneInfo("Europe/Paris")).date()
        tomorrow = today + datetime.timedelta(days=1)
        greeting_context = {
            "date": tomorrow, "nameday": "Sainte Catherine",
            "weather": {
                "puget": {"temperature": 31, "description": "la journée sera ensoleillée"},
                "aurillac": {"temperature": 22, "description": "la journée sera nuageuse"},
            },
        }
        self.data["sessions"][0]["trainees"][0]["created_at"] = today.isoformat()
        with client.session_transaction() as browser_session:
            browser_session["admin_logged_in"] = True
        with mock.patch.object(app, "load_data", return_value=self.data), \
             mock.patch.object(app, "fetch_daily_recap_greeting_context", return_value=greeting_context) as fetch_greeting, \
             mock.patch.object(app, "brevo_send_email") as send_email:
            response = client.get("/admin/suivi-ventes/apercu-mail-quotidien")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Récapitulatif de la veille", body)
        self.assertIn("Ada LOVELACE", body)
        self.assertIn("Bonjour Clément", body)
        self.assertIn(f"Nous sommes le {app._daily_recap_display_date(tomorrow)} et aujourd'hui c'est la Sainte-Catherine !", body)
        self.assertIn("Puget sur Argens", body)
        self.assertIn("Aurillac", body)
        self.assertIn("no-store", response.headers["Cache-Control"])
        fetch_greeting.assert_called_once_with(tomorrow)
        send_email.assert_not_called()

    def test_sales_tracking_page_exposes_daily_email_preview(self):
        client = app.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["admin_logged_in"] = True
        with mock.patch.object(app, "load_data", return_value=self.data):
            response = client.get("/admin/suivi-ventes")
        body = response.get_data(as_text=True)
        self.assertIn("Aperçu du mail de demain", body)
        self.assertIn(f"envoi prévu demain, le {app.fr_date((datetime.date.today() + datetime.timedelta(days=1)).isoformat())}, à 08h00", body)
        self.assertIn("/admin/suivi-ventes/apercu-mail-quotidien", body)

    def test_sales_tracking_page_exposes_manual_daily_email_send(self):
        client = app.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["admin_logged_in"] = True
        with mock.patch.object(app, "load_data", return_value=self.data):
            response = client.get("/admin/suivi-ventes")
        body = response.get_data(as_text=True)
        self.assertIn("Envoyer le mail de 08h", body)
        self.assertIn("prévu aujourd’hui aux 4 destinataires personnalisés", body)
        self.assertIn("/admin/suivi-ventes/envoyer-mail-quotidien", body)

    def test_manual_daily_email_endpoint_forces_four_personalized_sends(self):
        client = app.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["admin_logged_in"] = True
        result = {"sent": True, "date": "2026-07-28", "recipients": 4}
        with mock.patch.object(app, "run_daily_recap", return_value=result) as run_recap:
            response = client.post("/admin/suivi-ventes/envoyer-mail-quotidien")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["recipients"], 4)
        run_recap.assert_called_once_with(
            force=True,
            delivery_date=datetime.datetime.now(ZoneInfo("Europe/Paris")).date(),
            request_id=mock.ANY,
        )

    def test_manual_daily_email_returns_traceable_request_id(self):
        client = app.app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["admin_logged_in"] = True
        with mock.patch.object(app, "run_daily_recap", side_effect=lambda **kwargs: {
            "sent": True, "recipients": 4, "request_id": kwargs["request_id"],
        }):
            response = client.post("/admin/suivi-ventes/envoyer-mail-quotidien")
        request_id = response.get_json()["request_id"]
        self.assertRegex(request_id, r"^[0-9a-f]{12}$")

    def test_force_resends_even_when_daily_recap_is_in_history(self):
        now = datetime.datetime(2026, 7, 28, 10, tzinfo=ZoneInfo("Europe/Paris"))
        self.data["daily_recap_sent_dates"] = ["2026-07-27"]
        sent = []
        with mock.patch.object(app, "load_data", return_value=self.data), \
             mock.patch.object(app, "save_data"), \
             mock.patch.object(app, "fetch_daily_recap_greeting_context", return_value={"date": now.date(), "weather": {}}), \
             mock.patch.object(app, "brevo_send_email", side_effect=lambda *args, **kwargs: sent.append(args[0]) or {"ok": True}):
            result = app.run_daily_recap(now=now, force=True)
        self.assertTrue(result["sent"])
        self.assertEqual(sent, list(app.DAILY_RECAP_RECIPIENTS))
        self.assertEqual(self.data["daily_recap_sent_dates"], ["2026-07-27"])

    def test_manual_delivery_details_are_logged_at_render_visible_level(self):
        now = datetime.datetime(2026, 7, 28, 10, tzinfo=ZoneInfo("Europe/Paris"))
        with mock.patch.object(app, "load_data", return_value=self.data), \
             mock.patch.object(app, "save_data"), \
             mock.patch.object(app, "fetch_daily_recap_greeting_context", return_value={"date": now.date(), "weather": {}}), \
             mock.patch.object(app, "brevo_send_email", return_value={"ok": True, "status_code": 201, "message_id": "brevo-123"}), \
             self.assertLogs(app.app.logger, level="WARNING") as captured:
            result = app.run_daily_recap(now=now, force=True, request_id="trace123")

        logs = "\n".join(captured.output)
        self.assertTrue(result["sent"])
        self.assertIn("[DAILY_RECAP] send_start request_id=trace123", logs)
        self.assertIn("[DAILY_RECAP] provider_response request_id=trace123", logs)
        self.assertIn("status_code=201 message_id=brevo-123", logs)
        self.assertIn("[DAILY_RECAP] send_complete request_id=trace123", logs)

    def test_delivery_error_reports_recipients_already_accepted(self):
        now = datetime.datetime(2026, 7, 28, 8, tzinfo=ZoneInfo("Europe/Paris"))
        responses = [
            {"ok": True, "message_id": "brevo-1"},
            {"ok": False, "error": "Adresse rejetée"},
        ]
        with mock.patch.object(app, "load_data", return_value=self.data), \
             mock.patch.object(app, "save_data") as save_data, \
             mock.patch.object(app, "fetch_daily_recap_greeting_context", return_value={"date": now.date(), "weather": {}}), \
             mock.patch.object(app, "brevo_send_email", side_effect=responses):
            result = app.run_daily_recap(now=now)
        self.assertFalse(result["sent"])
        self.assertEqual(result["accepted_recipients"], 1)
        self.assertEqual(result["deliveries"][0]["message_id"], "brevo-1")
        self.assertFalse(result["deliveries"][1]["accepted"])
        save_data.assert_not_called()


if __name__ == "__main__":
    unittest.main()
