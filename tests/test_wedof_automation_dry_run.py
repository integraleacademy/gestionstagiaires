import datetime as dt
import os
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import app as gestion_app
from wedof_automation import evaluate_action, run_dry_run
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

    def test_cron_requires_secret_and_explicit_dry_run_but_ignores_mutation_flag(self):
        client = gestion_app.app.test_client()
        with patch.dict(os.environ, {"CRON_SECRET": "secret", "WEDOF_DRY_RUN": "false", "WEDOF_AUTOMATION_ENABLED": "false"}, clear=False):
            self.assertEqual(client.post("/internal/cron/wedof-automation").status_code, 403)
            self.assertEqual(client.post("/internal/cron/wedof-automation", headers={"X-Cron-Secret": "secret"}).status_code, 409)
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


if __name__ == "__main__": unittest.main()
