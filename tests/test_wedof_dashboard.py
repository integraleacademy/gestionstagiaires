import unittest
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

    def test_unlinked_folder_stays_automatable(self):
        row = build_automation_dashboard([folder("A")])["rows"][0]
        self.assertEqual(row["tab"], "accepted")
        self.assertTrue(row["automation_planned"])
        self.assertEqual(row["association"], "À rattacher localement")

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
        self.assertIn("admin-sidebar", html)
        self.assertNotIn("Règle de rapprochement</th>", html)
        for method in ("post", "put", "patch", "delete"):
            getattr(remote, method).assert_not_called()

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
        self.assertIn("<strong>—</strong>", html)
        self.assertNotIn("Accepté <span>0</span>", html)

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
        self.assertIn("Accepté <span>0</span>", html)
        self.assertIn("<strong>0</strong><span>Accepté</span>", html)


if __name__ == "__main__":
    unittest.main()
