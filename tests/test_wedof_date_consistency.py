import unittest
from unittest.mock import patch

import app as gestion_app
from wedof_links import evaluate_wedof_date_gate, evaluate_wedof_link_date_consistency


class WedofDateConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.link = {"external_id": "W1", "session_id": "S1", "trainee_id": "T1", "active": True,
                     "wedof_date_start": "2026-09-07", "wedof_date_end": "2026-10-09"}
        self.session = {"id": "S1", "date_start": "2026-09-07", "date_end": "2026-10-09"}

    def test_match_mismatches_missing_and_dynamic_recovery(self):
        self.assertTrue(evaluate_wedof_link_date_consistency(self.link, self.session)["date_gate_ok"])
        for key in ("date_start", "date_end"):
            changed = dict(self.session, **{key: "2026-11-01"})
            result = evaluate_wedof_link_date_consistency(self.link, changed)
            self.assertEqual((result["status"], result["block_reason"]),
                             ("date_mismatch", "wedof_local_dates_mismatch"))
        missing = dict(self.link, wedof_date_start=None)
        self.assertEqual(evaluate_wedof_date_gate(missing, self.session),
                         {"allowed": False, "reason": "wedof_dates_unverifiable"})
        self.assertFalse(evaluate_wedof_link_date_consistency(self.link, {"date_end": "2026-10-09"})["date_gate_ok"])
        self.assertTrue(evaluate_wedof_link_date_consistency(self.link, self.session)["date_gate_ok"])

    def test_current_folder_has_priority_and_legacy_aliases_work(self):
        legacy = {"date_debut": "2026-09-07", "date_fin": "2026-10-09"}
        folder = {"trainingActionInfo": {"startDate": "2026-09-08", "endDate": "2026-10-09"}}
        self.assertEqual(evaluate_wedof_link_date_consistency(self.link, legacy, folder)["status"], "date_mismatch")

    def test_linked_session_date_change_requires_confirmation_and_keeps_link(self):
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
        data = {"sessions": [dict(self.session, trainees=[{"id": "T1"}])], "wedof_links": [dict(self.link)]}
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(gestion_app, "save_data") as save:
            rejected = client.post("/api/sessions/S1/update", json={"date_start": "2026-09-08"})
            self.assertEqual(rejected.status_code, 409)
            save.assert_not_called()
            accepted = client.post("/api/sessions/S1/update", json={"date_start": "2026-09-08", "confirm_wedof_date_change": True})
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual((data["wedof_links"][0]["external_id"], data["wedof_links"][0]["session_id"], data["wedof_links"][0]["trainee_id"]), ("W1", "S1", "T1"))
            self.assertIn("1 dossier(s)", accepted.json["message"])


if __name__ == "__main__":
    unittest.main()
