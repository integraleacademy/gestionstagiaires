import unittest
from unittest.mock import patch

import app as gestion_app
from wedof_links import evaluate_wedof_link_date_consistency


class WedofDateConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.link = {"external_id": "WEDOF-TEST-001", "session_id": "S1", "trainee_id": "T1", "active": True,
                     "wedof_date_start": "2026-09-07", "wedof_date_end": "2026-10-09"}
        self.session = {"id": "S1", "date_start": "2026-09-07", "date_end": "2026-10-09"}

    def test_comparison_is_informational_and_has_no_gate_or_block_reason(self):
        matching = evaluate_wedof_link_date_consistency(self.link, self.session)
        differing = evaluate_wedof_link_date_consistency(
            self.link, dict(self.session, date_start="2026-09-08")
        )
        unverifiable = evaluate_wedof_link_date_consistency(self.link, {"id": "S1"})
        self.assertEqual((matching["dates_differ"], differing["dates_differ"], unverifiable["dates_differ"]),
                         (False, True, None))
        for result in (matching, differing, unverifiable):
            self.assertTrue(result["informational_only"])
            self.assertNotIn("date_gate_ok", result)
            self.assertNotIn("block_reason", result)

    def test_current_wedof_folder_drives_remote_dates(self):
        folder = {"trainingActionInfo": {"startDate": "2026-09-08", "endDate": "2026-10-09"}}
        result = evaluate_wedof_link_date_consistency(self.link, self.session, folder)
        self.assertEqual(result["wedof_date_start"], "2026-09-08")
        self.assertTrue(result["dates_differ"])

    def test_local_date_change_keeps_link_and_stored_wedof_dates(self):
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
        data = {"sessions": [dict(self.session, trainees=[{"id": "T1"}])], "wedof_links": [dict(self.link)]}
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(gestion_app, "save_data"):
            response = client.post("/api/sessions/S1/update", json={
                "date_start": "2026-09-08", "confirm_wedof_date_change": True,
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["wedof_links"], [self.link])
        self.assertEqual(data["wedof_links"][0]["wedof_date_start"], "2026-09-07")
        self.assertNotIn("blocked", response.get_data(as_text=True).lower())
        self.assertIn("dates WEDOF", response.json["message"])


if __name__ == "__main__":
    unittest.main()
