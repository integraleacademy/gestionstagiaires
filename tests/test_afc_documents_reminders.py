import datetime
import os
import unittest

import app as gestion_app


class AfcDocumentsRemindersTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_email = gestion_app.brevo_send_email
        self.original_sms = gestion_app.brevo_send_sms
        self.original_cnaps_lookup = gestion_app.fetch_cnaps_lookup_by_name
        self.data = {"afc": {"candidates": []}}
        gestion_app.load_data = lambda: self.data
        gestion_app.save_data = lambda _data: None
        gestion_app.fetch_cnaps_lookup_by_name = lambda *_args, **_kwargs: {
            "status": "INCONNU",
            "statut_cnaps_history": [],
        }
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app.brevo_send_email = self.original_email
        gestion_app.brevo_send_sms = self.original_sms
        gestion_app.fetch_cnaps_lookup_by_name = self.original_cnaps_lookup

    @staticmethod
    def candidate(**overrides):
        candidate = {
            "id": "AFC-REMINDER-1",
            "nom": "DUPONT",
            "prenom": "Alice",
            "email": "alice@example.test",
            "telephone": "06 01 02 03 04",
            "cnaps_status": "INCONNU",
            "cnaps_status_history": [],
            "cnaps_status_changed_at": "2026-08-10T08:00:00Z",
            "created_at": "2026-08-10T08:00:00Z",
            "presence_afc_status": "CONVOQUE",
        }
        candidate.update(overrides)
        return candidate

    def configure_successful_delivery(self):
        self.email_calls = []
        self.sms_calls = []
        gestion_app.brevo_send_email = (
            lambda *args, **kwargs: self.email_calls.append((args, kwargs))
            or {"ok": True, "message_id": "mail-1", "error": ""}
        )
        gestion_app.brevo_send_sms = (
            lambda *args, **kwargs: self.sms_calls.append((args, kwargs)) or True
        )

    def test_automatic_reminder_waits_two_full_days_then_sends_both_channels(self):
        candidate = self.candidate()
        self.data["afc"]["candidates"] = [candidate]
        self.configure_successful_delivery()

        early = gestion_app.run_afc_documents_reminders(
            datetime.datetime(2026, 8, 12, 7, 59, 59),
            refresh_cnaps=False,
        )
        due = gestion_app.run_afc_documents_reminders(
            datetime.datetime(2026, 8, 12, 8, 0, 0),
            refresh_cnaps=False,
        )

        self.assertEqual(early["sent"], 0)
        self.assertEqual(due, {"checked": 1, "eligible": 1, "sent": 1, "failed": 0})
        self.assertEqual(len(self.email_calls), 1)
        self.assertEqual(len(self.sms_calls), 1)
        self.assertEqual(self.email_calls[0][1]["metadata"]["purpose"], "afc_documents_reminder")
        self.assertEqual(candidate["documents_reminder_history"][0]["source"], "automatic")
        self.assertEqual(candidate["documents_reminder_history"][0]["sent_at"], "2026-08-12T08:00:00Z")

    def test_successful_reminder_repeats_only_after_three_full_days(self):
        candidate = self.candidate(
            documents_reminder_history=[{
                "sent_at": "2026-08-12T08:00:00Z",
                "source": "automatic",
                "email_status": "ACCEPTE",
                "sms_status": "ACCEPTE",
            }]
        )
        self.data["afc"]["candidates"] = [candidate]
        self.configure_successful_delivery()

        too_soon = gestion_app.run_afc_documents_reminders(
            datetime.datetime(2026, 8, 15, 7, 59, 59),
            refresh_cnaps=False,
        )
        due = gestion_app.run_afc_documents_reminders(
            datetime.datetime(2026, 8, 15, 8, 0, 0),
            refresh_cnaps=False,
        )

        self.assertEqual(too_soon["sent"], 0)
        self.assertEqual(due["sent"], 1)
        self.assertEqual(len(candidate["documents_reminder_history"]), 2)

    def test_delayed_worker_catches_up_an_overdue_reminder(self):
        candidate = self.candidate(
            documents_reminder_history=[{
                "sent_at": "2026-08-14T09:30:00Z",
                "source": "automatic",
                "email_status": "ACCEPTE",
                "sms_status": "ACCEPTE",
            }]
        )
        self.data["afc"]["candidates"] = [candidate]
        self.configure_successful_delivery()

        result = gestion_app.run_afc_documents_reminders(
            datetime.datetime(2026, 8, 18, 12, 51, 0),
            refresh_cnaps=False,
        )

        self.assertEqual(result, {"checked": 1, "eligible": 1, "sent": 1, "failed": 0})
        self.assertEqual(candidate["documents_reminder_history"][-1]["sent_at"], "2026-08-18T12:51:00Z")

    def test_next_reminder_date_uses_initial_delay_then_latest_success(self):
        candidate = self.candidate()

        initial_next = gestion_app._afc_documents_reminder_next_at(candidate)
        self.assertEqual(initial_next, datetime.datetime(2026, 8, 12, 8, 0, 0))

        candidate["documents_reminder_history"] = [{
            "sent_at": "2026-08-14T09:30:00Z",
            "source": "manual",
            "email_status": "ACCEPTE",
            "sms_status": "ACCEPTE",
        }]
        repeated_next = gestion_app._afc_documents_reminder_next_at(candidate)
        self.assertEqual(repeated_next, datetime.datetime(2026, 8, 17, 9, 30, 0))

        candidate["cnaps_status"] = "TRANSMIS"
        self.assertIsNone(gestion_app._afc_documents_reminder_next_at(candidate))

    def test_automatic_reminders_stop_when_cnaps_has_progressed_or_title_is_active(self):
        transmitted = self.candidate(id="AFC-TRANSMIS", cnaps_status="TRANSMIS")
        active_title = self.candidate(
            id="AFC-ACTIF",
            cnaps_status="INCONNU",
            cnaps_status_history=[{"status": "AP SH ACTIF", "date": "2027-08-10"}],
        )
        self.data["afc"]["candidates"] = [transmitted, active_title]
        gestion_app.brevo_send_email = lambda *_args, **_kwargs: self.fail("No email expected")
        gestion_app.brevo_send_sms = lambda *_args, **_kwargs: self.fail("No SMS expected")

        result = gestion_app.run_afc_documents_reminders(
            datetime.datetime(2026, 8, 20, 8, 0, 0),
            refresh_cnaps=False,
        )

        self.assertEqual(result, {"checked": 2, "eligible": 0, "sent": 0, "failed": 0})

    def test_automatic_reminders_do_not_send_outside_french_daytime_hours(self):
        candidate = self.candidate()
        self.data["afc"]["candidates"] = [candidate]
        self.configure_successful_delivery()

        result = gestion_app.run_afc_documents_reminders(
            datetime.datetime(2026, 8, 12, 3, 0, 0),
            refresh_cnaps=False,
        )

        self.assertEqual(result, {"checked": 0, "eligible": 0, "sent": 0, "failed": 0})
        self.assertEqual(self.email_calls, [])
        self.assertEqual(self.sms_calls, [])

    def test_cron_refreshes_cnaps_before_sending_and_stops_if_documents_arrived(self):
        candidate = self.candidate()
        self.data["afc"]["candidates"] = [candidate]
        gestion_app.fetch_cnaps_lookup_by_name = lambda *_args, **_kwargs: {
            "status": "TRANSMIS",
            "statut_cnaps_history": [],
        }
        gestion_app.brevo_send_email = lambda *_args, **_kwargs: self.fail("No email expected")
        gestion_app.brevo_send_sms = lambda *_args, **_kwargs: self.fail("No SMS expected")

        result = gestion_app.run_afc_documents_reminders(datetime.datetime(2026, 8, 20, 8, 0, 0))

        self.assertEqual(result["sent"], 0)
        self.assertEqual(candidate["cnaps_status"], "TRANSMIS")
        self.assertEqual(candidate["cnaps_status_changed_at"], "2026-08-20T08:00:00Z")

    def test_manual_endpoint_sends_immediately_and_counts_for_the_history(self):
        candidate = self.candidate(
            cnaps_status="ACCEPTE",
            cnaps_status_changed_at="2026-08-14T07:00:00Z",
            created_at="2026-08-14T07:00:00Z",
        )
        self.data["afc"]["candidates"] = [candidate]
        self.configure_successful_delivery()

        response = self.client.post("/api/admin/afc/candidates/AFC-REMINDER-1/documents-reminder")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["email_status"], "ACCEPTE")
        self.assertEqual(body["sms_status"], "ACCEPTE")
        self.assertEqual(candidate["documents_reminder_history"][0]["source"], "manual")

    def test_failed_delivery_does_not_add_a_successful_reminder_date(self):
        candidate = self.candidate()
        self.data["afc"]["candidates"] = [candidate]
        gestion_app.brevo_send_email = lambda *_args, **_kwargs: {"ok": False, "error": "Brevo indisponible"}
        gestion_app.brevo_send_sms = lambda *_args, **_kwargs: False

        result = gestion_app.run_afc_documents_reminders(
            datetime.datetime(2026, 8, 12, 8, 0, 0),
            refresh_cnaps=False,
        )

        self.assertEqual(result["failed"], 1)
        self.assertEqual(candidate.get("documents_reminder_history"), [])
        self.assertIn("Brevo indisponible", candidate["documents_reminder_last_error"])

    def test_a_second_automatic_run_is_skipped_while_one_is_in_progress(self):
        self.assertTrue(gestion_app._afc_documents_reminders_lock.acquire(blocking=False))
        try:
            result = gestion_app.run_afc_documents_reminders(
                datetime.datetime(2026, 8, 18, 12, 0, 0),
                refresh_cnaps=False,
            )
        finally:
            gestion_app._afc_documents_reminders_lock.release()

        self.assertEqual(result, {
            "checked": 0,
            "eligible": 0,
            "sent": 0,
            "failed": 0,
            "status": "already_running",
        })

    def test_afc_line_displays_manual_button_and_french_reminder_dates(self):
        candidate = self.candidate(
            documents_reminder_history=[{
                "sent_at": "2026-08-14T09:30:00Z",
                "source": "manual",
                "email_status": "ACCEPTE",
                "sms_status": "ACCEPTE",
            }]
        )
        self.data["afc"]["candidates"] = [candidate]

        original_utc_datetime = gestion_app._afc_utc_datetime
        gestion_app._afc_utc_datetime = lambda value=None: (
            original_utc_datetime(value)
            if value is not None
            else datetime.datetime(2026, 8, 15, 8, 0, 0)
        )
        try:
            response = self.client.get("/admin/afc")
            page = response.get_data(as_text=True)
        finally:
            gestion_app._afc_utc_datetime = original_utc_datetime

        self.assertEqual(response.status_code, 200)
        self.assertIn("Relances documents", page)
        self.assertIn("14/08/2026", page)
        self.assertIn("Prochaine relance", page)
        self.assertIn("17/08/2026", page)
        self.assertIn("data-send-documents-reminder", page)
        self.assertIn("Automatique après 2 jours, puis tous les 3 jours", page)

    def test_cnaps_status_change_resets_the_waiting_since_timestamp(self):
        candidate = self.candidate()
        self.data["afc"]["candidates"] = [candidate]

        response = self.client.patch(
            "/api/admin/afc/candidates/AFC-REMINDER-1",
            json={"cnaps_status": "TRANSMIS"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(candidate["cnaps_status"], "TRANSMIS")
        self.assertNotEqual(candidate["cnaps_status_changed_at"], "2026-08-10T08:00:00Z")

    def test_cron_endpoint_rejects_an_invalid_secret(self):
        original_secret = os.environ.get("CRON_SECRET")
        os.environ["CRON_SECRET"] = "expected-secret"
        try:
            response = self.client.post(
                "/internal/cron/afc-documents-reminders",
                headers={"X-Cron-Secret": "wrong-secret"},
            )
        finally:
            if original_secret is None:
                os.environ.pop("CRON_SECRET", None)
            else:
                os.environ["CRON_SECRET"] = original_secret
        self.assertEqual(response.status_code, 403)

    def test_render_blueprint_declares_the_hourly_afc_reminder_job(self):
        with open("render.yaml", encoding="utf-8") as blueprint_file:
            blueprint = blueprint_file.read()

        marker = "name: gestionstagiaires-afc-documents-reminders"
        self.assertIn(marker, blueprint)
        reminder_job = blueprint.split(marker, 1)[1].split("\n  - type:", 1)[0]
        self.assertIn('schedule: "0 * * * *"', reminder_job)
        self.assertIn("python scripts/run_afc_documents_reminders.py", reminder_job)
        self.assertIn("/internal/cron/afc-documents-reminders", reminder_job)


if __name__ == "__main__":
    unittest.main()
