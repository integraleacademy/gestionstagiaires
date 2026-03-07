import unittest

import app as gestion_app


class AdminNotificationScheduleTests(unittest.TestCase):
    def test_inject_skips_dismissed_schedule_keys(self):
        key = "vtc_exam_results_download|2026-03-07T12:00:00"
        data = {
            "notifications_admin": [],
            "notifications_admin_dismissed_schedule_keys": [key],
        }

        changed = gestion_app._inject_vtc_exam_results_notifications(data)

        self.assertFalse(changed)
        self.assertEqual(data["notifications_admin"], [])


class AdminNotificationDeleteApiTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data

    def test_delete_persists_schedule_key_to_prevent_recreation(self):
        self.data = {
            "notifications_admin": [
                {
                    "id": "ADM-1",
                    "label": "🚘Résultats examen pratique VTC à télécharger",
                    "created_at": "2026-03-07T18:26:00Z",
                    "done": False,
                    "meta": {
                        "kind": "vtc_exam_results_download",
                        "scheduled_at": "2026-03-07T12:00:00",
                    },
                }
            ],
            "notifications_admin_dismissed_schedule_keys": [],
        }

        saved = {"called": 0}

        gestion_app.load_data = lambda: self.data

        def fake_save_data(data):
            saved["called"] += 1

        gestion_app.save_data = fake_save_data

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.post("/api/admin/notifications/ADM-1/delete")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(saved["called"], 1)
        self.assertEqual(self.data["notifications_admin"], [])
        self.assertIn(
            "vtc_exam_results_download|2026-03-07T12:00:00",
            self.data["notifications_admin_dismissed_schedule_keys"],
        )


class VtcCheckNotifyApiTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_send_practice = gestion_app._send_vtc_practice_exam_success_notification

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app._send_vtc_practice_exam_success_notification = self.original_send_practice

    def test_notify_handles_send_errors_without_network_failure(self):
        data = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "Session VTC",
                    "training_type": "VTC",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Maxime",
                            "last_name": "Fournier",
                            "email": "max@example.com",
                            "phone": "0600000000",
                        }
                    ],
                }
            ]
        }

        gestion_app.load_data = lambda: data
        saved = {"called": 0}

        def fake_save_data(_data):
            saved["called"] += 1

        def fake_send(*_args, **_kwargs):
            raise RuntimeError("smtp down")

        gestion_app.save_data = fake_save_data
        gestion_app._send_vtc_practice_exam_success_notification = fake_send

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.post(
            "/api/vtc/check/notify?mode=practice",
            json={
                "items": [
                    {
                        "session_id": "S1",
                        "trainee_id": "T1",
                        "status": "admissible",
                    }
                ]
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["sent"], 0)
        self.assertEqual(payload["failed"], 1)
        self.assertEqual(saved["called"], 1)



if __name__ == "__main__":
    unittest.main()
