import unittest
from pathlib import Path
from unittest.mock import patch

import app as gestion_app


class AdminSessionsApsManualDatesTests(unittest.TestCase):
    def setUp(self):
        self.template = Path("templates/admin_sessions.html").read_text()
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True

    def test_create_and_edit_forms_expose_four_manual_aps_dates(self):
        for field_id in (
            "apsRemoteStart",
            "apsRemoteEnd",
            "apsInPersonStart",
            "apsInPersonEnd",
            "editApsRemoteStart",
            "editApsRemoteEnd",
            "editApsInPersonStart",
            "editApsInPersonEnd",
        ):
            self.assertIn(f'id="{field_id}" type="date"', self.template)
        self.assertEqual(
            self.template.count("Ces quatre dates peuvent être modifiées manuellement."),
            2,
        )

    def test_create_api_persists_the_four_manual_aps_dates(self):
        data = {"sessions": []}
        payload = {
            "name": "APS septembre",
            "training_type": "APS",
            "aps_remote_start": "2026-09-08",
            "aps_remote_end": "2026-09-18",
            "aps_in_person_start": "2026-09-21",
            "aps_in_person_end": "2026-10-12",
            "exam_date": "2026-10-13",
        }

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ) as save_data:
            response = self.client.post("/api/sessions/create", json=payload)

        self.assertEqual(response.status_code, 200)
        saved_session = data["sessions"][0]
        for key in (
            "aps_remote_start",
            "aps_remote_end",
            "aps_in_person_start",
            "aps_in_person_end",
        ):
            self.assertEqual(saved_session[key], payload[key])
        self.assertEqual(saved_session["date_start"], payload["aps_remote_start"])
        self.assertEqual(saved_session["date_end"], payload["aps_in_person_end"])
        save_data.assert_called_once_with(data)


if __name__ == "__main__":
    unittest.main()
