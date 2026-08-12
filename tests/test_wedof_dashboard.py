import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app as gestion_app
from wedof_automation import build_automation_dashboard


def folder(external_id, state="accepted", **changes):
    value = {"externalId": external_id, "state": state, "type": "cpf",
             "attendee": {"firstName": "Ada", "lastName": "Lovelace"},
             "trainingActionInfo": {"startDate": "2026-09-07", "endDate": "2026-10-09"}}
    value.update(changes)
    return value


class WedofDashboardUnitTests(unittest.TestCase):
    def test_active_block_is_an_immediate_overlay_and_recomputes_counters(self):
        dashboard = build_automation_dashboard([], statuses=[{
            "external_id": "GENERIC-LATE", "wedof_state": "accepted", "wedof_type": "cpf",
            "wedof_date_start": "2026-08-01", "wedof_date_end": "2026-08-10",
            "entry_training": {"status": "dry_run_due_late", "planned_date": "2026-08-01"},
        }], exceptions=[{"external_id": "GENERIC-LATE", "action": "both", "active": True,
                        "reason_code": "postponed", "comment": "Nouvelle date attendue",
                        "created_at": "2026-08-11T10:00:00+02:00"}])
        row = dashboard["rows"][0]
        self.assertEqual(row["automation_status"], "blocked")
        self.assertEqual(row["underlying_automation_status"], "dry_run_due_late")
        self.assertEqual(row["automation_action"], "entry_training")
        self.assertFalse(row["automation_planned"])
        self.assertEqual(row["tab"], "anomaly")
        self.assertEqual((dashboard["stats"]["planned"], dashboard["stats"]["blocked"]), (0, 1))

    def test_local_associations_dates_and_orphans_are_explicit(self):
        links = [
            {"external_id": "AUTO", "active": True, "session_id": "S1", "trainee_id": "T1",
             "source": "automatic_exact_match", "wedof_date_start": "2026-09-01", "wedof_date_end": "2026-09-30"},
            {"external_id": "ORPHAN", "active": True, "session_id": "MISSING", "trainee_id": "T2",
             "source": "manual_admin"},
        ]
        associations = gestion_app._wedof_links_for_display({
            "sessions": [{"id": "S1", "name": "APS SEPTEMBRE 2026",
                          "trainees": [{"id": "T1", "first_name": "Stéphane", "last_name": "BERTIN"}]}],
            "wedof_links": links,
        })
        rows = {row["external_id"]: row for row in build_automation_dashboard(
            [], links=links,
            statuses=[{"external_id": "AUTO", "wedof_state": "accepted", "entry_training": {"status": "planned"}},
                      {"external_id": "ORPHAN", "wedof_state": "accepted", "entry_training": {"status": "planned"}},
                      {"external_id": "FREE", "wedof_state": "accepted", "entry_training": {"status": "planned"}}],
            local_associations=associations)["rows"]}
        self.assertEqual((rows["AUTO"]["session"], rows["AUTO"]["trainee"]),
                         ("APS SEPTEMBRE 2026", "Stéphane BERTIN"))
        self.assertEqual(rows["AUTO"]["association"], "Association automatique fiable")
        self.assertEqual((rows["AUTO"]["session_id"], rows["AUTO"]["trainee_id"]), ("S1", "T1"))
        self.assertEqual((rows["AUTO"]["wedof_date_start"], rows["AUTO"]["wedof_date_end"]),
                         ("2026-09-01", "2026-09-30"))
        self.assertTrue(rows["ORPHAN"]["association_orphan"])
        self.assertIn("session introuvable", rows["ORPHAN"]["association"])
        self.assertEqual((rows["FREE"]["session"], rows["FREE"]["trainee"]),
                         ("Non rattachée", "Non rattaché"))

    def test_status_dates_override_remote_then_link_dates_are_fallback(self):
        row = build_automation_dashboard(
            [folder("A")],
            links=[{"external_id": "A", "active": True, "wedof_date_start": "2026-08-01",
                    "wedof_date_end": "2026-08-31"}],
            statuses=[{"external_id": "A", "wedof_date_start": "2026-07-01",
                       "wedof_date_end": "2026-07-31"}],
        )["rows"][0]
        self.assertEqual((row["wedof_date_start"], row["wedof_date_end"]), ("2026-07-01", "2026-07-31"))

    def test_classification_follows_remote_state(self):
        dashboard = build_automation_dashboard([
            folder("A", "accepted"), folder("T", "inTraining"),
            folder("D", "serviceDoneDeclared"), folder("V", "serviceDoneValidated"),
        ])
        self.assertEqual([row["tab"] for row in dashboard["rows"]],
                         ["accepted", "training", "service", "service"])
        self.assertEqual((dashboard["stats"]["accepted"], dashboard["stats"]["training"], dashboard["stats"]["service"]), (1, 1, 2))
        self.assertEqual(
            [row["automation_status"] for row in dashboard["rows"][2:]],
            ["completed_in_wedof", "completed_in_wedof"],
        )
        self.assertTrue(all(not row["automation_planned"] for row in dashboard["rows"][2:]))

    def test_unlinked_folder_stays_automatable(self):
        row = build_automation_dashboard([folder("A")])["rows"][0]
        self.assertEqual(row["tab"], "accepted")
        self.assertTrue(row["automation_planned"])
        self.assertEqual(row["association"], "À rattacher localement")

    def test_unlinked_counter_only_tracks_trainings_starting_june_2026(self):
        dashboard = build_automation_dashboard([
            folder("BEFORE", trainingActionInfo={"startDate": "2026-05-31", "endDate": "2026-06-30"}),
            folder("BOUNDARY", trainingActionInfo={"startDate": "2026-06-01", "endDate": "2026-06-30"}),
            folder("AFTER"),
            folder("TRAINING", "inTraining"),
            folder("COMPLETED", "serviceDoneDeclared"),
            folder("MISSING", trainingActionInfo={"endDate": "2026-06-30"}),
        ], links=[{"external_id": "AFTER", "active": True}])

        rows = {row["external_id"]: row for row in dashboard["rows"]}
        self.assertEqual(dashboard["stats"]["unlinked"], 2)
        self.assertFalse(rows["BEFORE"]["unlinked_since_tracking_start"])
        self.assertTrue(rows["BOUNDARY"]["unlinked_since_tracking_start"])
        self.assertFalse(rows["AFTER"]["unlinked_since_tracking_start"])
        self.assertTrue(rows["TRAINING"]["unlinked_since_tracking_start"])
        self.assertFalse(rows["COMPLETED"]["unlinked_since_tracking_start"])
        self.assertFalse(rows["MISSING"]["unlinked_since_tracking_start"])

    def test_anomalies_and_successes_come_from_server_data(self):
        dashboard = build_automation_dashboard(
            [folder("BAD", trainingActionInfo={}), folder("T", "inTraining"), folder("D", "serviceDoneDeclared")],
            statuses=[
                {"external_id": "T", "entry_training": {"status": "success"}},
                {"external_id": "D", "service_done": {"status": "success"}},
            ],
        )
        self.assertEqual(dashboard["rows"][0]["tab"], "anomaly")
        self.assertTrue(dashboard["rows"][1]["entry_success"])
        self.assertTrue(dashboard["rows"][2]["service_success"])


class WedofDashboardViewTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True

    def test_compact_dashboard_tabs_counters_badges_and_sidebar(self):
        remote = Mock()
        remote.list_registration_folders.side_effect = [
            [folder("A"), folder("BAD", trainingActionInfo={})],
            [folder("T", "inTraining")], [folder("D", "serviceDoneDeclared")], [],
        ]
        data = {"sessions": [], "wedof_links": [], "wedof_automation_exceptions": [],
                "wedof_automation_status": [
                    {"external_id": "T", "entry_training": {"status": "success"}},
                    {"external_id": "D", "service_done": {"status": "success"}},
                ]}
        with patch.object(gestion_app, "WedofClient", return_value=remote), \
             patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]):
            response = self.client.post("/admin/wedof/matching/preview")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        for text in ("Accepté", "En formation", "Service fait déclaré", "Anomalie",
                     "Simulation prévue", "Entrée en formation déclarée ✅",
                     "Service fait déclaré ✅", "À rattacher localement", "Dossiers non rattachés localement"):
            self.assertIn(text, html)
        self.assertIn('data-wedof-panel="accepted"', html)
        self.assertIn('data-wedof-panel="training"', html)
        self.assertIn('data-wedof-panel="service"', html)
        self.assertIn('data-wedof-panel="anomaly"', html)
        self.assertIn('data-wedof-counter="accepted"', html)
        self.assertIn('data-wedof-counter="planned"', html)
        self.assertIn('data-wedof-counter="unlinked"', html)
        self.assertIn('data-wedof-planned="true"', html)
        self.assertIn('data-wedof-entry-success="true"', html)
        self.assertIn('data-wedof-service-success="true"', html)
        self.assertIn('data-wedof-unlinked="true"', html)
        self.assertIn("js/admin-wedof-dashboard.js", html)
        dashboard_script = Path("static/js/admin-wedof-dashboard.js").read_text(encoding="utf-8")
        self.assertIn("row.dataset.wedofEntrySuccess === 'true'", dashboard_script)
        self.assertIn("row.dataset.wedofServiceSuccess === 'true'", dashboard_script)
        self.assertIn("row.dataset.wedofUnlinked === 'true'", dashboard_script)
        self.assertIn("counter.addEventListener('click'", dashboard_script)
        self.assertIn("table?.scrollIntoView", dashboard_script)
        self.assertIn("admin-sidebar", html)
        self.assertIn("css/admin-wedof.css", html)
        self.assertIn("Pilotage des dossiers CPF", html)
        self.assertNotIn("Règle de rapprochement</th>", html)
        for method in ("post", "put", "patch", "delete"):
            getattr(remote, method).assert_not_called()

    def test_blocked_snapshot_shows_only_reactivation_and_terminal_rows_have_no_block_button(self):
        data = {"sessions": [], "wedof_links": [], "wedof_automation_runs": [{"status": "success"}],
                "wedof_automation_status": [
                    {"external_id": "GENERIC-LATE", "wedof_state": "accepted", "wedof_type": "cpf",
                     "wedof_date_start": "2026-08-01", "wedof_date_end": "2026-08-10",
                     "entry_training": {"status": "dry_run_due_late"}},
                    {"external_id": "GENERIC-DONE", "wedof_state": "serviceDoneValidated", "wedof_type": "cpf"}],
                "wedof_automation_blocks": [{"external_id": "GENERIC-LATE", "action": "entry_training",
                    "active": True, "reason_code": "no_show", "created_at": "2026-08-11T10:00:00+02:00"}]}
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]):
            html = self.client.get("/admin/wedof").get_data(as_text=True)
        self.assertIn("Automatisation bloquée", html)
        self.assertIn("Réactiver l’automatisation", html)
        self.assertIn("Stagiaire non présenté", html)
        self.assertNotIn("En retard — prête en mode test", html)
        self.assertNotIn("Bloquer l’automatisation", html)

    def test_block_and_unblock_routes_are_idempotent_local_operations_with_flashes(self):
        data = {"wedof_automation_status": [{"external_id": "GENERIC-ROUTE", "wedof_state": "accepted"}],
                "wedof_automation_blocks": []}

        def atomic(mutator):
            return mutator(data)

        form = {"external_id": "GENERIC-ROUTE", "action": "entry_training",
                "reason_code": "other", "comment": "Contrôle administratif"}
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_atomic_update_data", side_effect=atomic), \
             patch.object(gestion_app, "WedofClient") as remote:
            first = self.client.post("/admin/wedof/automation/block", data=form, follow_redirects=False)
            second = self.client.post("/admin/wedof/automation/block", data=form, follow_redirects=False)
            self.assertEqual(len(data["wedof_automation_blocks"]), 1)
            self.assertTrue(data["wedof_automation_blocks"][0]["active"])
            self.assertIn("tab=anomaly", first.location)
            with self.client.session_transaction() as session:
                self.assertTrue(any("Aucune déclaration ne sera envoyée" in message
                                    for _category, message in session.get("_flashes", [])))
            response = self.client.post("/admin/wedof/automation/unblock",
                                        data={"external_id": "GENERIC-ROUTE", "action": "entry_training"})
            self.assertFalse(data["wedof_automation_blocks"][0]["active"])
            self.assertEqual(response.status_code, 302)
            remote.assert_not_called()

    def test_block_route_requires_authentication(self):
        anonymous = gestion_app.app.test_client()
        response = anonymous.post("/admin/wedof/automation/block", data={
            "external_id": "GENERIC-AUTH", "action": "entry_training", "reason_code": "other"})
        self.assertIn(response.status_code, {302, 401, 403})

    def test_snapshot_rows_offer_manual_link_without_matching_preview(self):
        statuses = [
            {"external_id": state, "wedof_state": state, "wedof_type": "cpf",
             "wedof_date_start": "2026-09-07", "wedof_date_end": "2026-10-09"}
            for state in ("accepted", "inTraining", "serviceDoneDeclared", "serviceDoneValidated")
        ]
        statuses.extend([
            {"external_id": "OTHER", "wedof_state": "accepted", "wedof_type": "other"},
            {"external_id": "", "wedof_state": "accepted", "wedof_type": "cpf"},
        ])
        data = {"sessions": [], "wedof_links": [], "wedof_automation_status": statuses,
                "wedof_automation_runs": [{"status": "success"}], "wedof_automation_sync": {}}
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]):
            html = self.client.get("/admin/wedof").get_data(as_text=True)
        self.assertEqual(html.count("Associer manuellement</button>"), 4)
        self.assertNotIn('data-external-id="OTHER"', html)
        self.assertIn('id="wedof-manual-modal"', html)
        self.assertEqual(html.count("js/wedof-manual-links.js"), 1)
        self.assertIn('data-date-start="2026-09-07"', html)
        self.assertIn('id="wedof-unlinked-count"', html)

    def test_manual_session_suggestions_only_include_trainee_enrolments(self):
        data = {"sessions": [
            {"id": "S1", "name": "APS SEPTEMBRE", "date_start": "2026-09-01",
             "trainees": [{"id": "T1", "first_name": "Alexandre", "last_name": "Sanseverino",
                            "email": "alexandre@example.fr", "phone": "07 67 39 74 89"}]},
            {"id": "S2", "name": "VTC OCTOBRE", "date_start": "2026-10-01",
             "trainees": [{"id": "T2", "first_name": "Autre", "last_name": "Personne",
                            "email": "autre@example.fr"}]},
        ]}
        with patch.object(gestion_app, "load_data", return_value=data):
            response = self.client.get(
                "/admin/wedof/matching/manual/sessions",
                query_string={"suggest_for_trainee": "1", "email": "ALEXANDRE@example.fr",
                              "phone": "+33 7 67 39 74 89", "first_name": "Alexandre",
                              "last_name": "Sanseverino"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"], [{
            "id": "S1", "name": "APS SEPTEMBRE", "training_type": "",
            "date_start": "2026-09-01", "date_end": None, "archived": False,
            "suggested_trainee": {"id": "T1", "first_name": "Alexandre", "last_name": "Sanseverino",
                                  "email": "alexandre@example.fr", "phone": "07 67 39 74 89"},
        }])

    def test_manual_session_search_remains_available_without_identity_match(self):
        data = {"sessions": [{"id": "S1", "name": "APS SEPTEMBRE", "date_start": "2026-09-01",
                              "trainees": []}]}
        with patch.object(gestion_app, "load_data", return_value=data):
            response = self.client.get("/admin/wedof/matching/manual/sessions?q=APS")
        self.assertEqual([item["id"] for item in response.get_json()["items"]], ["S1"])

    def test_french_date_filter_is_safe(self):
        self.assertEqual(gestion_app.format_date_fr("2026-09-07"), "07/09/2026")
        self.assertEqual(gestion_app.format_date_fr("2026-09-07T12:00:00+02:00"), "07/09/2026")
        self.assertEqual(gestion_app.format_date_fr(None), "—")
        self.assertEqual(gestion_app.format_date_fr("invalid"), "—")

    def test_never_synchronized_uses_dashes_and_explains_empty_snapshot(self):
        data = {"sessions": [], "wedof_links": [], "wedof_automation_status": [],
                "wedof_automation_runs": [], "wedof_automation_sync": {}}
        maintenance = {"active": False, "start_time": "05:00", "end_time": "07:00",
                       "timezone": "Europe/Paris"}
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
             patch.object(gestion_app, "is_wedof_maintenance_window", return_value=maintenance):
            html = self.client.get("/admin/wedof").get_data(as_text=True)
        self.assertIn("Données WEDOF non encore synchronisées.", html)
        self.assertIn("Lancez une première analyse après la fenêtre d’indisponibilité WEDOF.", html)
        self.assertRegex(html, r'data-wedof-counter="accepted"[^>]*>\s*<strong>—</strong>')

    def test_successful_empty_snapshot_displays_real_zero(self):
        data = {"sessions": [], "wedof_links": [], "wedof_automation_status": [],
                "wedof_automation_runs": [{"status": "success", "started_at": "2026-08-09T07:05:00+02:00",
                                             "finished_at": "2026-08-09T07:05:01+02:00"}],
                "wedof_automation_sync": {"states": {state: {"last_success_at": "2026-08-09T07:05:00+02:00"}
                                                       for state in ("accepted", "inTraining", "serviceDoneDeclared", "serviceDoneValidated")}}}
        maintenance = {"active": False, "start_time": "05:00", "end_time": "07:00",
                       "timezone": "Europe/Paris"}
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
             patch.object(gestion_app, "is_wedof_maintenance_window", return_value=maintenance):
            html = self.client.get("/admin/wedof").get_data(as_text=True)
        self.assertNotIn("Données WEDOF non encore synchronisées.", html)
        self.assertRegex(html, r'data-wedof-counter="accepted"[^>]*>\s*<strong>0</strong>\s*<span>Acceptés</span>')


if __name__ == "__main__":
    unittest.main()
