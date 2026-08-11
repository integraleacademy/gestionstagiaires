import datetime as dt
import os
import unittest
import runpy
from unittest.mock import patch
from zoneinfo import ZoneInfo

import app as gestion_app
from wedof_automation import (automation_dashboard_state, evaluate_action, is_wedof_maintenance_window,
                              record_maintenance_skip, run_dry_run)
from wedof_service import WedofApiError


def folder(external_id="W1", state="accepted", start="2026-09-07", end="2026-10-09", duration=None):
    info = {"startDate": start, "endDate": end}
    if duration is not None: info["trainingDuration"] = duration
    return {"externalId": external_id, "state": state, "type": "cpf", "trainingActionInfo": info}


class FakeClient:
    def __init__(self, by_state): self.by_state, self.calls = by_state, []
    def list_registration_folders(self, state, limit=100):
        self.calls.append(("GET", state)); return self.by_state.get(state, [])
    def get_registration_folder(self, external_id):
        self.calls.append(("GET", external_id))
        return next(x for values in self.by_state.values() for x in values if x.get("externalId") == external_id)


class FailingClient(FakeClient):
    def __init__(self, by_state, failed): super().__init__(by_state); self.failed = set(failed)
    def list_registration_folders(self, state, limit=100):
        if state in self.failed:
            raise WedofApiError("indisponible", "wedof_timeout", True)
        return super().list_registration_folders(state, limit)


class WedofDryRunTests(unittest.TestCase):
    def test_maintenance_window_boundaries_and_no_business_mutation(self):
        paris = ZoneInfo("Europe/Paris")
        expected = [(4, 59, False), (5, 0, True), (6, 10, True), (6, 59, True),
                    (7, 0, False), (7, 5, False)]
        with patch.dict(os.environ, {}, clear=False):
            for hour, minute, active in expected:
                with self.subTest(hour=hour, minute=minute):
                    now = dt.datetime(2026, 8, 9, hour, minute, tzinfo=paris)
                    self.assertEqual(is_wedof_maintenance_window(now)["active"], active)
        statuses = [{"external_id": "KNOWN", "entry_training": {"status": "planned"}}]
        links = [{"external_id": "KNOWN", "active": True}]
        blocks = [{"external_id": "KNOWN", "active": True}]
        sync = {"last_attempt_at": "old", "states": {"accepted": {"last_success_at": "success"}}}
        data = {"wedof_automation_status": statuses, "wedof_links": links,
                "wedof_automation_blocks": blocks, "wedof_automation_sync": sync,
                "wedof_automation_runs": []}
        result = record_maintenance_skip(data, now=dt.datetime(2026, 8, 9, 6, 10, tzinfo=paris))
        self.assertEqual(result["status"], "skipped_maintenance_window")
        self.assertIs(data["wedof_automation_status"], statuses)
        self.assertIs(data["wedof_links"], links)
        self.assertIs(data["wedof_automation_blocks"], blocks)
        self.assertIs(data["wedof_automation_sync"], sync)
        self.assertIsNone(data["wedof_automation_runs"][-1]["technical_error"])
        self.assertNotIn("KNOWN", repr(result))

    def test_maintenance_configuration_disable_invalid_midnight_and_dst(self):
        paris = ZoneInfo("Europe/Paris")
        at_six = dt.datetime(2026, 1, 10, 6, 0, tzinfo=paris)
        for disabled in ("false", "0", "no", "off", " OFF "):
            with patch.dict(os.environ, {"WEDOF_MAINTENANCE_WINDOW_ENABLED": disabled}, clear=False):
                self.assertFalse(is_wedof_maintenance_window(at_six)["active"])
        with patch.dict(os.environ, {"WEDOF_MAINTENANCE_WINDOW_ENABLED": "true",
                                     "WEDOF_MAINTENANCE_START_TIME": "invalid",
                                     "WEDOF_MAINTENANCE_END_TIME": "25:00"}, clear=False):
            result = is_wedof_maintenance_window(at_six)
            self.assertEqual((result["active"], result["start_time"], result["end_time"]),
                             (True, "05:00", "07:00"))
        with patch.dict(os.environ, {"WEDOF_MAINTENANCE_START_TIME": "23:00",
                                     "WEDOF_MAINTENANCE_END_TIME": "02:00"}, clear=False):
            self.assertTrue(is_wedof_maintenance_window(dt.datetime(2026, 1, 1, 23, 30, tzinfo=paris))["active"])
            self.assertTrue(is_wedof_maintenance_window(dt.datetime(2026, 1, 2, 1, 59, tzinfo=paris))["active"])
            self.assertFalse(is_wedof_maintenance_window(dt.datetime(2026, 1, 2, 2, 0, tzinfo=paris))["active"])
        # UTC instants are converted to Paris correctly on either side of DST.
        with patch.dict(os.environ, {"WEDOF_MAINTENANCE_START_TIME": "05:00",
                                     "WEDOF_MAINTENANCE_END_TIME": "07:00"}, clear=False):
            self.assertTrue(is_wedof_maintenance_window(dt.datetime(2026, 1, 10, 5, 10, tzinfo=dt.timezone.utc))["active"])
            self.assertTrue(is_wedof_maintenance_window(dt.datetime(2026, 7, 10, 4, 10, tzinfo=dt.timezone.utc))["active"])

    def test_application_skips_before_client_creation_and_persists_only_run(self):
        canonical = {"wedof_automation_status": [{"external_id": "PRIVATE"}],
                     "wedof_automation_runs": [], "wedof_links": [{"external_id": "PRIVATE"}]}
        def atomic_update(mutator):
            mutator(canonical)
        window = {"active": True, "start_time": "05:00", "end_time": "07:00", "timezone": "Europe/Paris"}
        with patch.object(gestion_app, "is_wedof_maintenance_window", return_value=window), \
             patch.object(gestion_app, "_atomic_update_data", side_effect=atomic_update), \
             patch.object(gestion_app, "WedofClient") as client_class:
            result = gestion_app.run_wedof_automation_dry_run()
        client_class.assert_not_called()
        self.assertEqual(result["status"], "skipped_maintenance_window")
        self.assertEqual(canonical["wedof_automation_status"], [{"external_id": "PRIVATE"}])
        self.assertEqual(canonical["wedof_links"], [{"external_id": "PRIVATE"}])
        self.assertEqual(canonical["wedof_automation_runs"][-1]["status"], "skipped_maintenance_window")

    def test_entry_and_service_schedules_use_wedof_dates_and_paris_times(self):
        paris = ZoneInfo("Europe/Paris")
        entry, payload = evaluate_action(folder(start="2026-09-07"), "entry_training", now=dt.datetime(2026, 9, 7, 18, 1, tzinfo=paris))
        service, service_payload = evaluate_action(folder(state="inTraining", end="2026-10-09", duration=35), "service_done", now=dt.datetime(2026, 10, 9, 23, 1, tzinfo=paris))
        self.assertEqual((entry["status"], entry["planned_time"], payload), ("dry_run_due", "18:00", {"date": "2026-09-07"}))
        self.assertEqual(service["status"], "dry_run_due")
        self.assertEqual(service_payload, {"absenceDuration": 0, "forceMajeureAbsence": False, "date": "2026-10-09", "trainingDuration": 35})

    def test_future_late_unlinked_blocks_and_idempotence(self):
        client = FakeClient({"accepted": [folder("FUTURE", start="2026-09-08"), folder("LATE", start="2026-09-01")], "inTraining": [], "serviceDoneDeclared": [], "serviceDoneValidated": []})
        data = {"wedof_links": [], "wedof_automation_status": [], "wedof_automation_runs": [],
                "wedof_automation_blocks": [{"external_id": "FUTURE", "action": "entry_training", "active": True}]}
        now = dt.datetime(2026, 9, 7, 12, tzinfo=ZoneInfo("Europe/Paris"))
        run_dry_run(client, data, now=now); run_dry_run(client, data, now=now)
        rows = {x["external_id"]: x for x in data["wedof_automation_status"]}
        self.assertEqual(rows["FUTURE"]["entry_training"]["status"], "blocked")
        self.assertEqual(rows["LATE"]["entry_training"]["status"], "dry_run_due_late")
        self.assertEqual(rows["LATE"]["local_link_status"], "unlinked")
        self.assertEqual(len(data["wedof_automation_status"]), 2)
        self.assertTrue(all(method == "GET" for method, _ in client.calls))

    def test_remote_terminal_states_are_read_and_run_history_is_limited(self):
        client = FakeClient({"accepted": [], "inTraining": [], "serviceDoneDeclared": [folder("D", state="serviceDoneDeclared")], "serviceDoneValidated": [folder("V", state="serviceDoneValidated")]})
        data = {"wedof_links": [], "wedof_automation_status": [], "wedof_automation_runs": [{}] * 100}
        summary = run_dry_run(client, data)
        self.assertEqual((summary["service_done_declared"], summary["service_done_validated"]), (1, 1))
        self.assertEqual(len(data["wedof_automation_runs"]), 100)
        rows = {row["external_id"]: row for row in data["wedof_automation_status"]}
        for external_id in ("D", "V"):
            self.assertEqual((rows[external_id]["wedof_date_start"], rows[external_id]["wedof_date_end"]),
                             ("2026-09-07", "2026-10-09"))

    def test_cron_requires_secret_and_explicit_dry_run_but_ignores_mutation_flag(self):
        client = gestion_app.app.test_client()
        with patch.dict(os.environ, {"CRON_SECRET": "secret", "WEDOF_DRY_RUN": "false", "WEDOF_AUTOMATION_ENABLED": "false"}, clear=False):
            self.assertEqual(client.post("/internal/cron/wedof-automation").status_code, 403)
            # Fail-closed now falls back to GET-only simulation instead of rejecting the cron.
            with patch.object(gestion_app, "run_wedof_automation_dry_run", return_value={"ok": True, "mode": "dry_run"}):
                self.assertEqual(client.post("/internal/cron/wedof-automation", headers={"X-Cron-Secret": "secret"}).status_code, 200)
        with patch.dict(os.environ, {"CRON_SECRET": "secret", "WEDOF_DRY_RUN": "true", "WEDOF_AUTOMATION_ENABLED": "false"}, clear=False), patch.object(gestion_app, "run_wedof_automation_dry_run", return_value={"ok": True, "mode": "dry_run"}):
            response = client.post("/internal/cron/wedof-automation", headers={"X-Cron-Secret": "secret"})
            self.assertEqual(response.status_code, 200)

    def test_partial_success_preserves_failed_state_and_updates_other_states(self):
        old = folder("OLD", state="accepted")
        data = {"wedof_links": [], "wedof_automation_status": [{"external_id": "OLD", "wedof_state": "accepted",
                "entry_training": {"status": "planned"}, "service_done": {"status": "not_applicable"}}],
                "wedof_automation_runs": [], "wedof_automation_blocks": []}
        client = FailingClient({"inTraining": [folder("NEW", state="inTraining")],
                                "serviceDoneDeclared": [], "serviceDoneValidated": []}, {"accepted"})
        result = run_dry_run(client, data, now=dt.datetime(2026, 9, 1, tzinfo=ZoneInfo("Europe/Paris")))
        self.assertEqual((result["ok"], result["partial"], result["status"]), (True, True, "partial_success"))
        self.assertEqual(result["state_errors"], {"accepted": "wedof_timeout"})
        self.assertEqual({x["external_id"] for x in data["wedof_automation_status"]}, {"OLD", "NEW"})
        self.assertEqual(data["wedof_automation_runs"][-1]["status"], "partial_success")
        self.assertEqual(data["wedof_automation_sync"]["states"]["accepted"]["status"], "error")

    def test_total_failure_preserves_dashboard_and_records_failed_run(self):
        old_statuses = [{"external_id": "OLD", "wedof_state": "accepted", "entry_training": {"status": "planned"}}]
        data = {"wedof_links": [], "wedof_automation_status": old_statuses.copy(),
                "wedof_automation_runs": [], "wedof_automation_blocks": []}
        result = run_dry_run(FailingClient({}, set(("accepted", "inTraining", "serviceDoneDeclared", "serviceDoneValidated"))), data)
        self.assertEqual((result["ok"], result["partial"], result["status"]), (False, False, "failed"))
        self.assertEqual(data["wedof_automation_status"], old_statuses)
        self.assertEqual(data["wedof_automation_runs"][-1]["status"], "failed")

    def test_admin_and_cron_handle_partial_and_failed_results(self):
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session: flask_session["admin_logged_in"] = True
        env = {"WEDOF_DRY_RUN": "true", "CRON_SECRET": "secret"}
        partial = {"ok": True, "partial": True, "status": "partial_success", "failed_states": ["inTraining"]}
        with patch.dict(os.environ, env, clear=False), patch.object(gestion_app, "run_wedof_automation_dry_run", return_value=partial):
            response = client.post("/admin/wedof/automation/analyze", follow_redirects=True)
            self.assertEqual(response.status_code, 200); self.assertIn("Analyse WEDOF partielle", response.get_data(as_text=True))
            self.assertEqual(client.post("/internal/cron/wedof-automation", headers={"X-Cron-Secret": "secret"}).status_code, 200)
        failed = {"ok": False, "partial": False, "status": "failed", "failed_states": list(("accepted", "inTraining", "serviceDoneDeclared", "serviceDoneValidated"))}
        with patch.dict(os.environ, env, clear=False), patch.object(gestion_app, "run_wedof_automation_dry_run", return_value=failed):
            self.assertEqual(client.post("/internal/cron/wedof-automation", headers={"X-Cron-Secret": "secret"}).status_code, 503)

    def test_admin_cron_and_render_script_treat_maintenance_skip_as_success(self):
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session: flask_session["admin_logged_in"] = True
        skipped = {"ok": True, "partial": False, "status": "skipped_maintenance_window", "mode": "dry_run",
                   "maintenance_window": {"start_time": "05:00", "end_time": "07:00", "timezone": "Europe/Paris"}}
        env = {"WEDOF_DRY_RUN": "true", "CRON_SECRET": "secret"}
        with patch.dict(os.environ, env, clear=False), patch.object(gestion_app, "run_wedof_automation_dry_run", return_value=skipped):
            admin = client.post("/admin/wedof/automation/analyze")
            self.assertEqual((admin.status_code, admin.headers["Location"].endswith("/admin/wedof")), (302, True))
            with client.session_transaction() as flask_session:
                flashes = flask_session.get("_flashes", [])
            self.assertTrue(any(category == "info" and "Analyse WEDOF suspendue entre 05:00 et 07:00" in message
                                for category, message in flashes))
            cron = client.post("/internal/cron/wedof-automation", headers={"X-Cron-Secret": "secret"})
            self.assertEqual(cron.status_code, 200)
            self.assertEqual(cron.get_json(), {"ok": True, "status": "skipped_maintenance_window",
                                               "mode": "dry_run", "next_action": "automatic_retry_on_next_cron"})
        class Response:
            ok = True
            text = '{"ok":true,"status":"skipped_maintenance_window"}'
        with patch.dict(os.environ, {"WEDOF_AUTOMATION_URL": "https://example.invalid/cron",
                                     "CRON_SECRET": "not-a-real-secret"}, clear=False), \
             patch("requests.post", return_value=Response()) as post:
            runpy.run_path("scripts/run_wedof_automation.py", run_name="__main__")
            post.assert_called_once()

    def test_dashboard_global_states_follow_reliable_run_history(self):
        self.assertEqual(automation_dashboard_state({"wedof_links": [{"external_id": "LOCAL"}]}),
                         "never_synchronized")
        cases = [("success", "synchronized"), ("partial_success", "partial_sync"),
                 ("failed", "stale"), ("skipped_maintenance_window", "maintenance_skipped")]
        for last_status, expected in cases:
            data = {"wedof_automation_runs": [{"status": "success"}, {"status": last_status}]}
            self.assertEqual(automation_dashboard_state(data), expected)


if __name__ == "__main__": unittest.main()
