import datetime
import unittest
from unittest import mock

import app as gestion_app


class AfcCnapsAutoRefreshTests(unittest.TestCase):
    @staticmethod
    def candidate(**overrides):
        candidate = {
            "id": "AFC-CNAPS-1",
            "nom": "DUPONT",
            "prenom": "Alice",
            "cnaps_status": "INCONNU",
            "cnaps_status_history": [],
            "cnaps_status_changed_at": "2026-08-10T08:00:00Z",
            "created_at": "2026-08-10T08:00:00Z",
        }
        candidate.update(overrides)
        return candidate

    def test_refresh_updates_an_existing_non_empty_status_and_history(self):
        candidate = self.candidate()
        data = {"afc": {"candidates": [candidate]}}

        def update(mutator, **_kwargs):
            return mutator(data)

        with (
            mock.patch.object(gestion_app, "CNAPS_LOOKUP_ENDPOINT", "https://cnaps.example/lookup"),
            mock.patch.object(gestion_app, "AFC_CNAPS_REFRESH_REQUEST_DELAY_SECONDS", 0),
            mock.patch.object(gestion_app, "load_data", return_value=data),
            mock.patch.object(gestion_app, "update_data", side_effect=update),
            mock.patch.object(
                gestion_app,
                "fetch_cnaps_lookup_by_name",
                return_value={
                    "status": "TRANSMIS",
                    "statut_cnaps_history": [{"status": "DOSSIER TRANSMIS", "date": "2026-08-17"}],
                },
            ) as lookup,
        ):
            result = gestion_app.run_afc_cnaps_status_refresh(
                datetime.datetime(2026, 8, 17, 16, 0, 0)
            )

        lookup.assert_called_once_with("DUPONT", "Alice")
        self.assertEqual(result["attempted"], 1)
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(candidate["cnaps_status"], "TRANSMIS")
        self.assertEqual(candidate["cnaps_status_changed_at"], "2026-08-17T16:00:00Z")
        self.assertEqual(candidate["cnaps_status_checked_at"], "2026-08-17T16:00:00Z")
        self.assertEqual(candidate["cnaps_status_history"][0]["status"], "DOSSIER TRANSMIS")

    def test_refresh_does_not_repeat_before_the_fifteen_minute_interval(self):
        candidate = self.candidate(cnaps_auto_refresh_attempted_at="2026-08-17T15:50:00Z")
        data = {"afc": {"candidates": [candidate]}}

        with (
            mock.patch.object(gestion_app, "CNAPS_LOOKUP_ENDPOINT", "https://cnaps.example/lookup"),
            mock.patch.object(gestion_app, "AFC_CNAPS_REFRESH_INTERVAL_SECONDS", 900),
            mock.patch.object(gestion_app, "load_data", return_value=data),
            mock.patch.object(gestion_app, "fetch_cnaps_lookup_by_name") as lookup,
        ):
            result = gestion_app.run_afc_cnaps_status_refresh(
                datetime.datetime(2026, 8, 17, 16, 0, 0)
            )

        lookup.assert_not_called()
        self.assertEqual(result["attempted"], 0)
        self.assertEqual(result["skipped_fresh"], 1)

    def test_failed_lookup_never_replaces_the_last_known_status(self):
        candidate = self.candidate(cnaps_status="TRANSMIS")
        data = {"afc": {"candidates": [candidate]}}

        def update(mutator, **_kwargs):
            return mutator(data)

        with (
            mock.patch.object(gestion_app, "CNAPS_LOOKUP_ENDPOINT", "https://cnaps.example/lookup"),
            mock.patch.object(gestion_app, "AFC_CNAPS_REFRESH_REQUEST_DELAY_SECONDS", 0),
            mock.patch.object(gestion_app, "load_data", return_value=data),
            mock.patch.object(gestion_app, "update_data", side_effect=update),
            mock.patch.object(gestion_app, "fetch_cnaps_lookup_by_name", return_value=None),
        ):
            result = gestion_app.run_afc_cnaps_status_refresh(
                datetime.datetime(2026, 8, 17, 16, 0, 0)
            )

        self.assertEqual(result["errors"], 1)
        self.assertEqual(candidate["cnaps_status"], "TRANSMIS")
        self.assertNotIn("cnaps_status_checked_at", candidate)
        self.assertEqual(candidate["cnaps_auto_refresh_attempted_at"], "2026-08-17T16:00:00Z")

    def test_temporary_unknown_answer_does_not_downgrade_a_known_status(self):
        history = [{"status": "DOSSIER TRANSMIS", "date": "2026-08-16"}]
        candidate = self.candidate(cnaps_status="TRANSMIS", cnaps_status_history=history.copy())
        data = {"afc": {"candidates": [candidate]}}

        def update(mutator, **_kwargs):
            return mutator(data)

        with (
            mock.patch.object(gestion_app, "CNAPS_LOOKUP_ENDPOINT", "https://cnaps.example/lookup"),
            mock.patch.object(gestion_app, "AFC_CNAPS_REFRESH_REQUEST_DELAY_SECONDS", 0),
            mock.patch.object(gestion_app, "load_data", return_value=data),
            mock.patch.object(gestion_app, "update_data", side_effect=update),
            mock.patch.object(
                gestion_app,
                "fetch_cnaps_lookup_by_name",
                return_value={"status": "INCONNU", "statut_cnaps_history": []},
            ),
        ):
            result = gestion_app.run_afc_cnaps_status_refresh(
                datetime.datetime(2026, 8, 17, 16, 0, 0)
            )

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(candidate["cnaps_status"], "TRANSMIS")
        self.assertEqual(candidate["cnaps_status_history"], history)
        self.assertEqual(candidate["cnaps_status_checked_at"], "2026-08-17T16:00:00Z")

    def test_archived_and_manual_priority_candidates_are_not_refreshed(self):
        data = {
            "afc": {
                "candidates": [
                    self.candidate(id="ARCHIVED", archived=True),
                    self.candidate(id="PRIORITY", cnaps_priority=True, cnaps_status="ACCEPTE"),
                ]
            }
        }

        with (
            mock.patch.object(gestion_app, "CNAPS_LOOKUP_ENDPOINT", "https://cnaps.example/lookup"),
            mock.patch.object(gestion_app, "load_data", return_value=data),
            mock.patch.object(gestion_app, "fetch_cnaps_lookup_by_name") as lookup,
        ):
            result = gestion_app.run_afc_cnaps_status_refresh()

        lookup.assert_not_called()
        self.assertEqual(result["attempted"], 0)

    def test_existing_monitor_endpoint_runs_the_afc_refresh_cycle(self):
        client = gestion_app.app.test_client()
        call_order = []
        with (
            mock.patch.object(gestion_app, "CNAPS_MONITOR_TOKEN", "secret"),
            mock.patch.object(
                gestion_app,
                "run_afc_cnaps_status_refresh",
                side_effect=lambda: call_order.append("cnaps") or {
                    "status": "done", "attempted": 2, "checked": 2, "updated": 1, "errors": 0,
                },
            ) as afc_refresh,
            mock.patch.object(
                gestion_app,
                "run_afc_documents_reminders",
                side_effect=lambda: call_order.append("reminders") or {
                    "checked": 19, "eligible": 2, "sent": 2, "failed": 0,
                },
            ) as reminders,
            mock.patch.object(
                gestion_app,
                "run_convocation_signature_reminders",
                side_effect=lambda: call_order.append("convention_reminders") or {
                    "checked": 2, "sent": 2, "failed": 0,
                },
            ) as convention_reminders,
            mock.patch.object(
                gestion_app,
                "run_cnaps_public_annuaire_monitor",
                side_effect=lambda: call_order.append("public_annuaire") or {
                    "status": "done", "checked": 3, "notified": 0, "errors": 0,
                },
            ),
        ):
            response = client.post(
                "/internal/jobs/cnaps-public-annuaire-monitor",
                headers={"X-CNAPS-Monitor-Token": "secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["afc"]["updated"], 1)
        self.assertEqual(response.get_json()["afc_documents_reminders"]["sent"], 2)
        self.assertEqual(response.get_json()["convention_signature_reminders"]["sent"], 2)
        afc_refresh.assert_called_once_with()
        reminders.assert_called_once_with()
        convention_reminders.assert_called_once_with()
        self.assertEqual(
            call_order,
            ["cnaps", "reminders", "convention_reminders", "public_annuaire"],
        )

    def test_reminder_failure_does_not_stop_the_existing_cnaps_monitor(self):
        client = gestion_app.app.test_client()
        with (
            mock.patch.object(gestion_app, "CNAPS_MONITOR_TOKEN", "secret"),
            mock.patch.object(
                gestion_app,
                "run_afc_cnaps_status_refresh",
                return_value={"status": "done", "attempted": 0, "checked": 0, "updated": 0, "errors": 0},
            ),
            mock.patch.object(
                gestion_app,
                "run_afc_documents_reminders",
                side_effect=RuntimeError("Brevo indisponible"),
            ),
            mock.patch.object(
                gestion_app,
                "run_convocation_signature_reminders",
                return_value={"checked": 0, "sent": 0, "failed": 0},
            ),
            mock.patch.object(
                gestion_app,
                "run_cnaps_public_annuaire_monitor",
                return_value={"status": "done", "checked": 3, "notified": 0, "errors": 0},
            ) as public_monitor,
        ):
            response = client.post(
                "/internal/jobs/cnaps-public-annuaire-monitor",
                headers={"X-CNAPS-Monitor-Token": "secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "done")
        self.assertEqual(response.get_json()["afc_documents_reminders"]["status"], "failed")
        public_monitor.assert_called_once_with()

    def test_convention_reminder_failure_does_not_stop_the_existing_cnaps_monitor(self):
        client = gestion_app.app.test_client()
        with (
            mock.patch.object(gestion_app, "CNAPS_MONITOR_TOKEN", "secret"),
            mock.patch.object(
                gestion_app,
                "run_afc_cnaps_status_refresh",
                return_value={"status": "done", "attempted": 0, "checked": 0, "updated": 0, "errors": 0},
            ),
            mock.patch.object(
                gestion_app,
                "run_afc_documents_reminders",
                return_value={"checked": 0, "eligible": 0, "sent": 0, "failed": 0},
            ),
            mock.patch.object(
                gestion_app,
                "run_convocation_signature_reminders",
                side_effect=RuntimeError("Brevo indisponible"),
            ),
            mock.patch.object(
                gestion_app,
                "run_cnaps_public_annuaire_monitor",
                return_value={"status": "done", "checked": 3, "notified": 0, "errors": 0},
            ) as public_monitor,
        ):
            response = client.post(
                "/internal/jobs/cnaps-public-annuaire-monitor",
                headers={"X-CNAPS-Monitor-Token": "secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "done")
        self.assertEqual(response.get_json()["convention_signature_reminders"]["status"], "failed")
        public_monitor.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
