import os
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
    def test_quota_blocked_action_stays_scheduled_and_sorted(self):
        dashboard = build_automation_dashboard([], statuses=[{
            "external_id": "QUOTA", "wedof_state": "accepted", "wedof_type": "cpf",
            "wedof_date_start": "2026-09-01", "wedof_date_end": "2026-10-01",
            "entry_training": {
                "status": "quota_blocked", "planned_date": "2026-09-01",
                "planned_time": "18:00", "last_error_code": "wedof_quota_exceeded",
            },
        }])

        self.assertEqual(dashboard["rows"][0]["automation_status"], "quota_blocked")
        self.assertEqual(dashboard["stats"]["planned"], 1)

    def test_retry_pending_stays_planned_and_exposes_the_remote_error(self):
        dashboard = build_automation_dashboard([], statuses=[{
            "external_id": "RETRY", "wedof_state": "accepted", "wedof_type": "cpf",
            "wedof_date_start": "2026-09-01", "wedof_date_end": "2026-10-01",
            "entry_training": {
                "status": "retry_pending", "planned_date": "2026-09-01",
                "planned_time": "18:00", "last_error_code": "wedof_server_error",
                "last_http_status": 503,
                "last_error_message": "L’API WEDOF est temporairement indisponible.",
                "retry_at": "2026-09-02T07:15:00+02:00",
            },
        }])

        row = dashboard["rows"][0]
        self.assertEqual(row["automation_status"], "retry_pending")
        self.assertEqual(row["last_http_status"], 503)
        self.assertEqual(row["retry_at"], "2026-09-02T07:15:00+02:00")
        self.assertEqual(dashboard["stats"]["planned"], 1)

    def test_rows_are_sorted_by_nearest_active_automation(self):
        statuses = [
            {"external_id": "LATER", "wedof_state": "accepted", "wedof_type": "cpf",
             "wedof_date_start": "2026-09-20", "wedof_date_end": "2026-10-20",
             "entry_training": {"status": "planned", "planned_date": "2026-09-20", "planned_time": "18:00"}},
            {"external_id": "SAME-LATE", "wedof_state": "accepted", "wedof_type": "cpf",
             "wedof_date_start": "2026-09-01", "wedof_date_end": "2026-10-01",
             "entry_training": {"status": "planned", "planned_date": "2026-09-01", "planned_time": "19:00"}},
            {"external_id": "DONE", "wedof_state": "accepted", "wedof_type": "cpf",
             "wedof_date_start": "2026-08-01", "wedof_date_end": "2026-08-31",
             "entry_training": {"status": "success", "planned_date": "2026-08-01", "planned_time": "18:00"}},
            {"external_id": "SAME-EARLY", "wedof_state": "accepted", "wedof_type": "cpf",
             "wedof_date_start": "2026-09-01", "wedof_date_end": "2026-10-01",
             "entry_training": {"status": "planned", "planned_date": "2026-09-01", "planned_time": "18:00"}},
        ]

        rows = build_automation_dashboard([], statuses=statuses)["rows"]

        self.assertEqual(
            [row["external_id"] for row in rows],
            ["SAME-EARLY", "SAME-LATE", "LATER", "DONE"],
        )

    def test_rows_without_a_valid_active_schedule_use_a_stable_fallback(self):
        statuses = [
            {"external_id": "Z-NO-DATE", "wedof_state": "accepted", "wedof_type": "cpf",
             "entry_training": {"status": "planned", "planned_date": "invalid", "planned_time": "18:00"}},
            {"external_id": "A-NOT-APPLICABLE", "wedof_state": "serviceDoneValidated", "wedof_type": "cpf"},
            {"external_id": "M-BLOCKED", "wedof_state": "accepted", "wedof_type": "cpf",
             "wedof_date_start": "2026-09-01", "wedof_date_end": "2026-10-01",
             "entry_training": {"status": "planned", "planned_date": "2026-09-01", "planned_time": "18:00"}},
        ]
        exceptions = [{"external_id": "M-BLOCKED", "action": "entry_training", "active": True}]

        rows = build_automation_dashboard([], statuses=statuses, exceptions=exceptions)["rows"]

        self.assertEqual(
            [row["external_id"] for row in rows],
            ["M-BLOCKED", "Z-NO-DATE"],
        )

    def test_rows_with_invalid_or_missing_time_follow_all_valid_schedules(self):
        statuses = [
            {"external_id": "A-INVALID-TIME", "wedof_state": "accepted", "wedof_type": "cpf",
             "entry_training": {"status": "planned", "planned_date": "2026-09-01",
                                "planned_time": "invalid"}},
            {"external_id": "VALID-LATER", "wedof_state": "accepted", "wedof_type": "cpf",
             "entry_training": {"status": "planned", "planned_date": "2026-09-02",
                                "planned_time": "08:15"}},
            {"external_id": "B-MISSING-TIME", "wedof_state": "accepted", "wedof_type": "cpf",
             "entry_training": {"status": "planned", "planned_date": "2026-09-01"}},
        ]

        rows = build_automation_dashboard([], statuses=statuses)["rows"]

        self.assertEqual(
            [row["external_id"] for row in rows],
            ["VALID-LATER", "A-INVALID-TIME", "B-MISSING-TIME"],
        )

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

    def test_service_done_only_includes_declarations_sent_by_gestion_stagiaires(self):
        dashboard = build_automation_dashboard([
            folder("A", "accepted"), folder("T", "inTraining"),
            folder("D", "serviceDoneDeclared"), folder("V", "serviceDoneValidated"),
        ], statuses=[{"external_id": "D", "service_done": {"status": "success"}}])
        self.assertEqual([row["tab"] for row in dashboard["rows"]],
                         ["accepted", "training", "service"])
        self.assertEqual(
            (dashboard["stats"]["accepted"], dashboard["stats"]["training"], dashboard["stats"]["service"]),
            (1, 1, 1),
        )
        self.assertEqual(dashboard["rows"][2]["external_id"], "D")
        self.assertTrue(dashboard["rows"][2]["service_success"])
        self.assertNotIn("V", {row["external_id"] for row in dashboard["rows"]})

    def test_service_done_action_journal_is_durable_proof_of_local_declaration(self):
        dashboard = build_automation_dashboard(
            [folder("LOCAL", "serviceDoneValidated"), folder("REMOTE", "serviceDoneValidated")],
            statuses=[
                {"external_id": "LOCAL", "service_done": {"status": "completed_in_wedof"}},
                {"external_id": "REMOTE", "service_done": {"status": "completed_in_wedof"}},
            ],
            actions=[
                {"external_id": "LOCAL", "action": "service_done", "status": "success"},
                {"external_id": "REMOTE", "action": "service_done", "status": "already_done"},
            ],
        )

        self.assertEqual(dashboard["stats"]["service"], 1)
        self.assertEqual([row["external_id"] for row in dashboard["rows"]], ["LOCAL"])
        self.assertTrue(dashboard["rows"][0]["service_success"])

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
        self.assertNotIn("COMPLETED", rows)
        self.assertFalse(rows["MISSING"]["unlinked_since_tracking_start"])

    def test_dashboard_displays_only_the_current_declared_milestone(self):
        dashboard = build_automation_dashboard(
            [folder("BAD", trainingActionInfo={}), folder("T", "inTraining"), folder("D", "serviceDoneDeclared")],
            statuses=[
                {"external_id": "T"},
                {"external_id": "D", "entry_training": {"status": "success"},
                 "service_done": {"status": "success"}},
            ],
            invoiced_external_ids={"D"},
        )
        rows = {row["external_id"]: row for row in dashboard["rows"]}
        self.assertEqual(rows["BAD"]["tab"], "anomaly")
        self.assertTrue(rows["T"]["entry_success"])
        self.assertFalse(rows["D"]["entry_success"])
        self.assertTrue(rows["D"]["service_success"])
        self.assertTrue(rows["D"]["invoiced"])
        self.assertEqual(rows["D"]["tab"], "invoiced")
        self.assertEqual((dashboard["stats"]["entry_success"], dashboard["stats"]["service_success"]), (1, 1))
        self.assertEqual(dashboard["stats"]["invoiced"], 1)
        self.assertEqual(dashboard["stats"]["service"], 0)

    def test_invoiced_service_done_is_removed_from_service_done_category(self):
        dashboard = build_automation_dashboard(
            [folder("INVOICED", "serviceDoneDeclared"), folder("TO-INVOICE", "serviceDoneValidated")],
            statuses=[
                {"external_id": "INVOICED", "service_done": {"status": "success"}},
                {"external_id": "TO-INVOICE", "service_done": {"status": "success"}},
            ],
            invoiced_external_ids={"INVOICED"},
        )

        rows = {row["external_id"]: row for row in dashboard["rows"]}
        self.assertEqual(rows["INVOICED"]["tab"], "invoiced")
        self.assertEqual(rows["TO-INVOICE"]["tab"], "service")
        self.assertEqual((dashboard["stats"]["service"], dashboard["stats"]["invoiced"]), (1, 1))

    def test_invoiced_kpi_requires_a_generated_cpf_invoice(self):
        data = {
            "sessions": [{
                "id": "S1",
                "trainees": [{"id": "T1"}, {"id": "T2"}, {"id": "T3"}],
            }],
            "wedof_links": [
                {"external_id": "SNAPSHOT", "active": True, "session_id": "S1", "trainee_id": "T1",
                 "cpf_snapshot": {"invoice_status": "sent", "qonto_invoice_number": "F-2026-1"}},
                {"external_id": "DRAFT", "active": True, "session_id": "S1", "trainee_id": "T2",
                 "cpf_snapshot": {"invoice_status": "draft", "qonto_invoice_id": "draft-1"}},
                {"external_id": "BILLING", "active": True, "session_id": "S1", "trainee_id": "T3"},
            ],
            "billing_lines": [{"sessionId": "S1", "traineeId": "T3", "financingType": "CPF",
                               "qontoInvoiceId": "invoice-3", "invoiceStatus": "sent"}],
        }

        self.assertEqual(gestion_app._wedof_invoiced_external_ids(data), {"SNAPSHOT", "BILLING"})


class WedofDashboardViewTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True

    def test_admin_displays_central_quota_origins_alerts_locks_and_recent_requests(self):
        data = {
            "sessions": [], "wedof_links": [], "wedof_automation_status": [],
            "wedof_automation_runs": [{"status": "success"}],
            "wedof_automation_sync": {},
        }
        quota = {
            "enabled": True,
            "timezone": "Europe/Paris",
            "generated_at": "2026-08-24T12:30:00+02:00",
            "periods": {
                "hour": {"used": 12, "limit": 100, "remaining": 88,
                         "utilization_percent": 12.0, "status": "normal",
                         "by_origin": {"crm": 5, "gestionstagiaires": 7}},
                "day": {"used": 451, "limit": 500, "remaining": 49,
                        "utilization_percent": 90.2, "status": "critical",
                        "by_origin": {"crm": 301, "gestionstagiaires": 140,
                                      "gestionstagiaires-webhook": 10}},
                "month": {"used": 6200, "limit": 15000, "remaining": 8800,
                          "utilization_percent": 41.3, "status": "normal",
                          "by_origin": {"crm": 4000, "gestionstagiaires": 2200}},
            },
            "recent_events": [{
                "requested_at": "2026-08-24T12:29:00+02:00",
                "origin": "crm", "operation": "get_registration_folder",
                "method": "GET", "path": "/registrationFolders/:id",
            }],
            "active_leases": [{
                "name": "wedof-global-reconciliation", "owner": "crm-worker",
                "expires_at": "2026-08-24T13:00:00+02:00",
            }],
        }
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
             patch.object(gestion_app, "wedof_quota_snapshot", return_value=quota) as snapshot, \
             patch.object(gestion_app, "WedofClient") as remote:
            response = self.client.get("/admin/wedof")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        for text in (
            "Consommation WEDOF", "Compteur central actif", "451", "sur 500 requêtes",
            "CRM", "Gestion Stagiaires", "Webhooks Gestion Stagiaires",
            "Plafond presque atteint", "wedof-global-reconciliation",
            "Lecture d’un dossier", "/registrationFolders/:id",
            "Cette actualisation ne contacte pas WEDOF",
        ):
            self.assertIn(text, html)
        self.assertNotIn("lease_token", html)
        snapshot.assert_called_once_with(recent_event_limit=20)
        remote.assert_not_called()

    def test_admin_ignores_stale_legacy_flags_without_kill_switch(self):
        data = {
            "sessions": [], "wedof_links": [], "wedof_automation_status": [],
            "wedof_automation_runs": [], "wedof_automation_sync": {},
        }
        env = {
            "WEDOF_AUTOMATION_KILL_SWITCH": "false",
            "WEDOF_AUTOMATION_ENABLED": "false",
            "WEDOF_CRON_ENABLED": "false",
            "WEDOF_DRY_RUN": "true",
            "WEDOF_RECONCILIATION_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
             patch.object(gestion_app, "_admin_wedof_quota_dashboard", return_value={"available": False}):
            response = self.client.get("/admin/wedof")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Automatisation active", html)
        self.assertIn("Déclarations automatiques actives</span><strong>Oui", html)
        self.assertIn("Cron de déclarations autorisé</span><strong>Oui", html)
        self.assertIn("Réconciliation en lecture seule</span><strong>Oui", html)

    def test_admin_explains_a_quota_block_without_hiding_the_due_action(self):
        data = {
            "sessions": [], "wedof_links": [], "wedof_automation_runs": [{"status": "quota_blocked"}],
            "wedof_automation_status": [{
                "external_id": "QUOTA", "wedof_state": "accepted", "wedof_type": "cpf",
                "wedof_date_start": "2026-09-01", "wedof_date_end": "2026-10-01",
                "entry_training": {
                    "status": "quota_blocked", "planned_date": "2026-09-01",
                    "planned_time": "18:00", "last_error_code": "wedof_quota_exceeded",
                },
            }],
        }
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
             patch.object(gestion_app, "_admin_wedof_quota_dashboard", return_value={"available": False}):
            response = self.client.get("/admin/wedof")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Bloquée par le quota WEDOF", html)
        self.assertIn("Nouvelle tentative automatique au prochain passage disponible", html)
        self.assertIn("Automatisations temporairement arrêtées par le quota WEDOF", html)
        self.assertIn("Entrée prévue le 01/09/2026 à 18:00", html)

    def test_compact_dashboard_tabs_counters_badges_and_sidebar(self):
        remote = Mock()
        remote.list_registration_folders.side_effect = [
            [folder("A"), folder("BAD", trainingActionInfo={})],
            [folder("T", "inTraining")],
            [folder("D", "serviceDoneDeclared"), folder("S", "serviceDoneDeclared")], [],
        ]
        data = {"sessions": [],
                "wedof_links": [{"external_id": "D", "active": True,
                                  "cpf_snapshot": {"invoice_status": "sent",
                                                   "qonto_invoice_number": "F-2026-1"}}],
                "wedof_automation_exceptions": [],
                "wedof_automation_status": [
                    {"external_id": "T"},
                    {"external_id": "D", "entry_training": {"status": "success"},
                     "service_done": {"status": "success"}},
                    {"external_id": "S", "service_done": {"status": "success"}},
                ]}
        with patch.object(gestion_app, "WedofClient", return_value=remote), \
             patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]):
            response = self.client.post("/admin/wedof/matching/preview")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        for text in ("Accepté", "En formation", "Service fait déclaré", "Anomalie",
                     "Automatisations prévues", "Services faits", "Facturés",
                     "Entrée en formation déclarée ✅", "Service fait déclaré ✅",
                     "À rattacher localement"):
            self.assertIn(text, html)
        for removed in ("Automatisations bloquées", "Entrées déclarées",
                        "Services faits déclarés", "Dossiers non rattachés localement"):
            self.assertNotIn(removed, html)
        self.assertNotIn("En formation dans WEDOF", html)
        self.assertEqual(html.count("Entrée en formation déclarée ✅"), 1)
        self.assertEqual(html.count("Service fait déclaré ✅"), 1)
        self.assertEqual(html.count("Facturé ✅"), 1)
        self.assertIn('data-wedof-panel="accepted"', html)
        self.assertIn('data-wedof-panel="training"', html)
        self.assertIn('data-wedof-panel="service"', html)
        self.assertIn('data-wedof-panel="invoiced"', html)
        self.assertIn('data-wedof-panel="anomaly"', html)
        for key in ("planned", "accepted", "training", "service", "invoiced", "anomaly"):
            self.assertIn(f'data-wedof-counter="{key}"', html)
        self.assertNotIn('class="wedof-operations"', html)
        self.assertIn('data-wedof-planned="true"', html)
        self.assertIn('data-wedof-invoiced="true"', html)
        self.assertIn("js/admin-wedof-dashboard.js", html)
        dashboard_script = Path("static/js/admin-wedof-dashboard.js").read_text(encoding="utf-8")
        self.assertIn("row.dataset.wedofInvoiced === 'true'", dashboard_script)
        self.assertIn("counter.addEventListener('click'", dashboard_script)
        self.assertIn("table?.scrollIntoView", dashboard_script)
        for key, label in (
            ("consumption", "Consommation WEDOF"),
            ("state", "État des dossiers"),
            ("technical", "Connexion et paramètres techniques"),
            ("requests", "Demandes entrantes WEDOF"),
        ):
            self.assertIn(f'data-wedof-page-tab="{key}"', html)
            self.assertIn(f'data-wedof-page-panel="{key}"', html)
            self.assertIn(label, html)
        self.assertIn("showPageSection(initialSection, {updateUrl: false})", dashboard_script)
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
            self.assertIn("section=state", first.location)
            with self.client.session_transaction() as session:
                self.assertTrue(any("Aucune déclaration ne sera envoyée" in message
                                    for _category, message in session.get("_flashes", [])))
            response = self.client.post("/admin/wedof/automation/unblock",
                                        data={"external_id": "GENERIC-ROUTE", "action": "entry_training"})
            self.assertFalse(data["wedof_automation_blocks"][0]["active"])
            self.assertEqual(response.status_code, 302)
            remote.assert_not_called()

    def test_page_opens_on_consumption_and_allows_direct_section_links(self):
        data = {
            "sessions": [], "wedof_links": [], "wedof_automation_status": [],
            "wedof_automation_runs": [{"status": "success"}], "wedof_automation_sync": {},
        }
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
             patch.object(gestion_app, "_admin_wedof_quota_dashboard", return_value={"available": False}):
            default_html = self.client.get("/admin/wedof").get_data(as_text=True)
            technical_html = self.client.get("/admin/wedof?section=technical").get_data(as_text=True)

        default_tab = default_html.split('id="wedof-page-tab-consumption"', 1)[1].split(">", 1)[0]
        default_panel = default_html.split('id="wedof-page-panel-consumption"', 1)[1].split(">", 1)[0]
        hidden_state = default_html.split('id="wedof-page-panel-state"', 1)[1].split(">", 1)[0]
        technical_tab = technical_html.split('id="wedof-page-tab-technical"', 1)[1].split(">", 1)[0]
        technical_panel = technical_html.split('id="wedof-page-panel-technical"', 1)[1].split(">", 1)[0]
        self.assertIn("is-active", default_tab)
        self.assertNotIn("hidden", default_panel)
        self.assertIn("hidden", hidden_state)
        self.assertIn("is-active", technical_tab)
        self.assertNotIn("hidden", technical_panel)

    def test_block_route_requires_authentication(self):
        anonymous = gestion_app.app.test_client()
        response = anonymous.post("/admin/wedof/automation/block", data={
            "external_id": "GENERIC-AUTH", "action": "entry_training", "reason_code": "other"})
        self.assertIn(response.status_code, {302, 401, 403})

    def test_snapshot_rows_offer_manual_link_without_matching_preview(self):
        statuses = []
        for state in ("accepted", "inTraining", "serviceDoneDeclared", "serviceDoneValidated"):
            row = {"external_id": state, "wedof_state": state, "wedof_type": "cpf",
                   "wedof_date_start": "2026-09-07", "wedof_date_end": "2026-10-09"}
            if state in {"serviceDoneDeclared", "serviceDoneValidated"}:
                row["service_done"] = {"status": "success"}
            statuses.append(row)
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

    def test_transient_failure_notice_shows_exact_status_and_retry_time(self):
        data = {
            "sessions": [], "wedof_links": [], "wedof_automation_status": [],
            "wedof_automation_runs": [{
                "status": "retry_scheduled",
                "last_error_message": "L’API WEDOF est temporairement indisponible.",
                "last_http_status": 503,
                "retry_at": "2026-09-02T07:15:00+02:00",
            }],
            "wedof_automation_sync": {},
        }
        maintenance = {"active": False, "start_time": "05:00", "end_time": "07:00",
                       "timezone": "Europe/Paris"}
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
             patch.object(gestion_app, "is_wedof_maintenance_window", return_value=maintenance):
            html = self.client.get("/admin/wedof").get_data(as_text=True)

        self.assertIn("WEDOF ne répond pas correctement", html)
        self.assertIn("code HTTP 503", html)
        self.assertIn("02/09/2026 à 07h15", html)


if __name__ == "__main__":
    unittest.main()
