import unittest
from unittest.mock import patch

import app as gestion_app


class WedofIsolationTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True

    def test_admin_sessions_and_search_skip_wedof_leads_session(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "name": "APS MAI 2026",
                    "training_type": "APS",
                    "date_start": "2026-05-01",
                    "date_end": "2026-05-31",
                    "trainees": [
                        {
                            "id": "T-1",
                            "first_name": "Océane",
                            "last_name": "Lassouag",
                            "created_at": "2026-05-02",
                        }
                    ],
                },
                {
                    "id": "wedof-cpf-edof",
                    "name": "Leads WeDoF CPF/EDOF",
                    "training_type": "CPF/EDOF",
                    "trainees": [
                        {
                            "id": "T-WEDOF",
                            "first_name": "Océane",
                            "last_name": "Lassouag",
                            "created_at": "2026-05-02",
                        }
                    ],
                },
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(
            gestion_app, "_load_wedof_webhooks", return_value=[]
        ):
            sessions_resp = self.client.get("/admin/sessions")
            self.assertEqual(sessions_resp.status_code, 200)
            sessions_html = sessions_resp.get_data(as_text=True)
            self.assertIn("APS MAI 2026", sessions_html)
            self.assertNotIn("Leads WeDoF CPF/EDOF", sessions_html)

            search_resp = self.client.get("/api/trainees_search?q=lass")
            self.assertEqual(search_resp.status_code, 200)
            payload = search_resp.get_json()
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["items"][0]["session_id"], "S-APS")

    def test_wedof_webhook_does_not_create_synthetic_training_session(self):
        with patch.object(gestion_app, "_fetch_wedof_folder_details", return_value={}), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
             patch.object(gestion_app, "_save_wedof_webhooks") as save_wedof, \
             patch.object(gestion_app, "load_data") as load_data, \
             patch.object(gestion_app, "save_data") as save_data:
            resp = self.client.post(
                "/api/webhooks/wedof",
                json={"externalId": "CPF-123", "email": "oceane@example.com"},
                headers={"X-Wedof-Event": "cpf.created"},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])
        save_wedof.assert_called_once()
        load_data.assert_not_called()
        save_data.assert_not_called()

    def test_wedof_webhook_sends_to_salesforce_automatically_without_notifying(self):
        salesforce_response = type(
            "SalesforceResponse",
            (),
            {"status_code": 200, "text": "ok", "url": "https://webto.salesforce.com/lead"},
        )()
        payload = {
            "externalId": "CPF-456",
            "attendee": {
                "firstName": "Sara",
                "lastName": "Boukhari",
                "email": "sara@example.com",
                "phoneNumber": "0612345678",
            },
            "trainingActionInfo": {"title": "Formation dirigeant DESP"},
        }

        with patch.object(gestion_app, "_fetch_wedof_folder_details", return_value={}), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
             patch.object(gestion_app, "_save_wedof_webhooks") as save_wedof, \
             patch.object(gestion_app.requests, "post", return_value=salesforce_response) as salesforce_post:
            resp = self.client.post(
                "/api/webhooks/wedof",
                json=payload,
                headers={"X-Wedof-Event": "cpf.created"},
            )

        self.assertEqual(resp.status_code, 200)
        salesforce_post.assert_called_once()
        saved_entry = save_wedof.call_args.args[0][0]
        self.assertTrue(saved_entry["salesforce_sent"])
        self.assertEqual(saved_entry["salesforce_send_count"], 1)
        self.assertFalse(saved_entry["processed"])

    def test_salesforce_payload_uses_bounded_permalink_instead_of_raw_webhook(self):
        salesforce_response = type(
            "SalesforceResponse",
            (),
            {"status_code": 200, "text": "ok", "url": "https://webto.salesforce.com/lead"},
        )()
        entry = {
            "id": "WEDOF-LARGE",
            "raw_payload": "x" * 50000,
            "payload": {
                "permalink": "https://example.test/dossier-123",
                "externalId": "123",
                "attendee": {
                    "firstName": "Sara",
                    "lastName": "Boukhari",
                    "email": "sara@example.com",
                },
                "trainingActionInfo": {"title": "Formation dirigeant DESP"},
            },
        }

        with patch.object(
            gestion_app.requests, "post", return_value=salesforce_response
        ) as salesforce_post:
            result, status = gestion_app._send_wedof_entry_to_salesforce(entry)

        self.assertEqual(status, 200)
        self.assertTrue(result["success"])
        sent_payload = salesforce_post.call_args.kwargs["data"]
        self.assertEqual(
            sent_payload["00NSa00000GcKVx"], "https://example.test/dossier-123"
        )
        self.assertNotIn("00NSa00000KDPOT", sent_payload)
        self.assertNotIn("00NSa00000GcKxN", sent_payload)
        self.assertLess(len(str(sent_payload)), 5000)

    def test_salesforce_payload_sends_selected_date_range_to_desired_dates(self):
        salesforce_response = type(
            "SalesforceResponse",
            (),
            {"status_code": 200, "text": "ok", "url": "https://webto.salesforce.com/lead"},
        )()
        entry = {
            "id": "WEDOF-DATES",
            "payload": {
                "attendee": {
                    "firstName": "Sara",
                    "lastName": "Boukhari",
                    "email": "sara@example.com",
                },
                "trainingActionInfo": {
                    "title": "Formation APS",
                    "sessionStartDate": "2026-09-14T08:30:00+02:00",
                    "sessionEndDate": "2026-10-09T17:00:00+02:00",
                },
            },
        }

        with patch.object(
            gestion_app.requests, "post", return_value=salesforce_response
        ) as salesforce_post:
            result, status = gestion_app._send_wedof_entry_to_salesforce(entry)

        self.assertEqual(status, 200)
        self.assertTrue(result["success"])
        sent_payload = salesforce_post.call_args.kwargs["data"]
        self.assertEqual(
            sent_payload["00NSa00000GcKxN"],
            "Du 14/09/2026 au 09/10/2026",
        )
        self.assertIn(
            "Dates souhaitées: Du 14/09/2026 au 09/10/2026",
            sent_payload["description"],
        )

    def test_salesforce_payload_uses_dates_from_wedof_folder_details(self):
        salesforce_response = type(
            "SalesforceResponse",
            (),
            {"status_code": 200, "text": "ok", "url": "https://webto.salesforce.com/lead"},
        )()
        entry = {
            "id": "WEDOF-FOLDER-DATES",
            "payload": {},
            "wedof_folder_details": {
                "data": {
                    "attendee": {
                        "lastName": "Boukhari",
                        "email": "sara@example.com",
                    },
                    "trainingActionInfo": {
                        "session": {
                            "startDate": "2026-11-02",
                            "endDate": "2026-11-27",
                        }
                    },
                }
            },
        }

        with patch.object(
            gestion_app.requests, "post", return_value=salesforce_response
        ) as salesforce_post:
            result, status = gestion_app._send_wedof_entry_to_salesforce(entry)

        self.assertEqual(status, 200)
        self.assertTrue(result["success"])
        self.assertEqual(
            salesforce_post.call_args.kwargs["data"]["00NSa00000GcKxN"],
            "Du 02/11/2026 au 27/11/2026",
        )

    def test_admin_wedof_keeps_notification_manual_and_shows_automatic_salesforce_status(self):
        entry = {
            "id": "WEDOF-TEST",
            "payload": {
                "attendee": {
                    "firstName": "Sara",
                    "lastName": "Boukhari",
                    "email": "sara@example.com",
                    "phoneNumber": "0612345678",
                },
                "trainingActionInfo": {"title": "Formation dirigeant DESP"},
            },
            "processed": False,
            "salesforce_sent": True,
            "salesforce_sent_at": "2026-06-12T10:00:00Z",
            "salesforce_send_count": 1,
        }

        with patch.object(gestion_app, "_load_wedof_webhooks", return_value=[entry]):
            response = self.client.get("/admin/wedof")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(">Notifier</button>", html)
        self.assertIn("Envoyé automatiquement à Salesforce", html)
        self.assertIn("Renvoyer Salesforce", html)

    def test_admin_wedof_shows_the_selected_training_date_range(self):
        entry = {
            "id": "WEDOF-DATES",
            "payload": {
                "attendee": {"firstName": "Sara", "lastName": "Boukhari"},
                "trainingActionInfo": {
                    "title": "Formation APS",
                    "sessionStartDate": "2026-09-14T08:30:00+02:00",
                    "sessionEndDate": "2026-10-09T17:00:00+02:00",
                },
            },
        }

        with patch.object(gestion_app, "_load_wedof_webhooks", return_value=[entry]):
            response = self.client.get("/admin/wedof")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Dates sélectionnées", html)
        self.assertIn("14/09/2026", html)
        self.assertIn("09/10/2026", html)

    def test_admin_wedof_uses_folder_details_when_dates_are_not_in_webhook(self):
        entry = {
            "id": "WEDOF-FOLDER-DATES",
            "payload": {},
            "wedof_folder_details": {
                "data": {
                    "trainingActionInfo": {
                        "title": "Formation VTC",
                        "session": {
                            "startDate": "2026-11-02",
                            "endDate": "2026-11-27",
                        },
                    }
                }
            },
        }

        with patch.object(gestion_app, "_load_wedof_webhooks", return_value=[entry]):
            response = self.client.get("/admin/wedof")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Formation VTC", html)
        self.assertIn("02/11/2026", html)
        self.assertIn("27/11/2026", html)


if __name__ == "__main__":
    unittest.main()
