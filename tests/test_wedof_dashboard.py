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
                     "Automatisation prévue", "Entrée en formation déclarée ✅",
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


if __name__ == "__main__":
    unittest.main()
