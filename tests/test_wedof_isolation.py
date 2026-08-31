import json
import re
import unittest
from unittest.mock import patch

import app as gestion_app


class WedofIsolationTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True

    def test_admin_sessions_and_search_skip_wedof_leads_session(self):
        today = gestion_app.datetime.date.today()
        session_name = f"APS TEST {today.year}"
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
                    "name": session_name,
                    "training_type": "APS",
                    "date_start": (today - gestion_app.datetime.timedelta(days=7)).isoformat(),
                    "date_end": (today + gestion_app.datetime.timedelta(days=7)).isoformat(),
                    "trainees": [
                        {
                            "id": "T-1",
                            "first_name": "Océane",
                            "last_name": "Lassouag",
                            "created_at": today.isoformat(),
                        }
                    ],
                },
                {
                    "id": "wedof-cpf-edof",
                    "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
                    "name": "Leads WeDoF CPF/EDOF",
                    "training_type": "CPF/EDOF",
                    "trainees": [
                        {
                            "id": "T-WEDOF",
                            "first_name": "Océane",
                            "last_name": "Lassouag",
                            "created_at": today.isoformat(),
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
            self.assertIn(session_name, sessions_html)
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
             patch.object(
                 gestion_app, "_send_wedof_entry_to_salesforce",
                 return_value=({"success": True}, 200),
             ), \
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

        def relay_to_crm(entry):
            entry["crm_sent"] = True
            entry["crm_sent_at"] = "2026-08-24T20:03:00Z"
            entry["crm_send_count"] = 1
            return {"success": True}, 200

        with patch.dict(
                 gestion_app.os.environ,
                 {"WEDOF_WEBHOOK_SECRET": "webhook-secret"}, clear=False,
             ), \
             patch.object(gestion_app, "_fetch_wedof_folder_details", return_value={}), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
             patch.object(gestion_app, "_save_wedof_webhooks") as save_wedof, \
             patch.object(
                 gestion_app, "_send_wedof_entry_to_crm",
                 side_effect=relay_to_crm,
             ) as crm_relay, \
             patch.object(gestion_app.requests, "post", return_value=salesforce_response) as salesforce_post:
            resp = self.client.post(
                "/api/webhooks/wedof",
                json=payload,
                headers={
                    "X-Wedof-Event": "cpf.created",
                    "X-Wedof-Secret": "webhook-secret",
                },
            )

        self.assertEqual(resp.status_code, 200)
        salesforce_post.assert_called_once()
        crm_relay.assert_called_once()
        saved_entry = save_wedof.call_args.args[0][0]
        self.assertTrue(saved_entry["salesforce_sent"])
        self.assertEqual(saved_entry["salesforce_send_count"], 1)
        self.assertTrue(saved_entry["crm_sent"])
        self.assertEqual(saved_entry["crm_send_count"], 1)
        self.assertFalse(saved_entry["processed"])

    def test_embedded_folder_updates_cache_without_any_wedof_get(self):
        payload = {
            "event": "registrationFolder.updated",
            "registrationFolder": {
                "externalId": "CPF-CACHED-1",
                "type": "cpf",
                "state": "accepted",
                "attendee": {
                    "firstName": "Sara",
                    "lastName": "Boukhari",
                    "email": "sara@example.com",
                },
                "trainingActionInfo": {
                    "startDate": "2026-09-07",
                    "endDate": "2026-10-09",
                    "title": "APS",
                },
            },
        }
        canonical = {
            "wedof_links": [],
            "wedof_folder_cache": [],
            "wedof_automation_status": [],
        }

        def atomic_update(mutator):
            return mutator(canonical)

        with patch.dict(
                 gestion_app.os.environ,
                 {"WEDOF_WEBHOOK_SECRET": "webhook-secret"}, clear=False,
             ), \
             patch.object(gestion_app, "_fetch_wedof_folder_details") as fetch, \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
             patch.object(gestion_app, "_save_wedof_webhooks"), \
             patch.object(
                 gestion_app, "_send_wedof_entry_to_salesforce",
                 return_value=({"success": True}, 200),
             ), \
             patch.object(
                 gestion_app, "_send_wedof_entry_to_crm",
                 return_value=({"success": True}, 200),
             ), \
             patch.object(gestion_app, "_atomic_update_data", side_effect=atomic_update):
            response = self.client.post(
                "/api/webhooks/wedof",
                json=payload,
                headers={
                    "X-Wedof-Delivery": "delivery-cache-1",
                    "X-Wedof-Secret": "webhook-secret",
                },
            )

        self.assertEqual(response.status_code, 200)
        fetch.assert_not_called()
        self.assertEqual(
            canonical["wedof_folder_cache"][0]["external_id"], "CPF-CACHED-1",
        )
        self.assertEqual(
            canonical["wedof_automation_status"][0]["external_id"],
            "CPF-CACHED-1",
        )

    def test_untrusted_webhook_can_never_spend_wedof_quota(self):
        with patch.dict(
                 gestion_app.os.environ,
                 {"WEDOF_WEBHOOK_SECRET": "webhook-secret"}, clear=False,
             ), \
             patch.object(gestion_app, "_fetch_wedof_folder_details") as fetch, \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
             patch.object(gestion_app, "_save_wedof_webhooks"), \
             patch.object(
                 gestion_app, "_send_wedof_entry_to_salesforce",
                 return_value=({"success": True}, 200),
             ), \
             patch.object(gestion_app, "_atomic_update_data") as atomic_update:
            response = self.client.post(
                "/api/webhooks/wedof",
                json={"registrationFolderId": "CPF-UNTRUSTED"},
                headers={"X-Wedof-Signature": "invalid"},
            )

        self.assertEqual(response.status_code, 200)
        fetch.assert_not_called()
        atomic_update.assert_not_called()

    def test_duplicate_webhook_is_acknowledged_before_targeted_get(self):
        with patch.object(gestion_app, "_fetch_wedof_folder_details") as fetch, \
             patch.object(
                 gestion_app, "_load_wedof_webhooks",
                 return_value=[{"delivery_id": "delivery-duplicate"}],
             ), \
             patch.object(gestion_app, "_save_wedof_webhooks") as save, \
             patch.object(gestion_app, "_send_wedof_entry_to_salesforce") as salesforce:
            response = self.client.post(
                "/api/webhooks/wedof",
                json={"registrationFolderId": "CPF-42"},
                headers={"X-Wedof-Delivery": "delivery-duplicate"},
            )

        self.assertEqual(response.get_json(), {"ok": True, "duplicate": True})
        fetch.assert_not_called()
        save.assert_not_called()
        salesforce.assert_not_called()

    def test_trusted_duplicate_repairs_a_missing_crm_relay_without_salesforce(self):
        entry = {
            "id": "WEDOF-OLD",
            "delivery_id": "delivery-old",
            "payload": {"registrationFolderId": "CPF-OLD"},
            "raw_payload": '{"registrationFolderId":"CPF-OLD"}',
            "signature_valid": True,
        }

        def relay_to_crm(stored_entry):
            stored_entry["crm_sent"] = True
            return {"success": True}, 200

        with patch.dict(
                 gestion_app.os.environ,
                 {"WEDOF_WEBHOOK_SECRET": "webhook-secret"}, clear=False,
             ), \
             patch.object(
                 gestion_app, "_load_wedof_webhooks", return_value=[entry],
             ), \
             patch.object(gestion_app, "_save_wedof_webhooks") as save, \
             patch.object(
                 gestion_app, "_send_wedof_entry_to_crm",
                 side_effect=relay_to_crm,
             ) as crm_relay, \
             patch.object(gestion_app, "_send_wedof_entry_to_salesforce") as salesforce:
            response = self.client.post(
                "/api/webhooks/wedof",
                json={"registrationFolderId": "CPF-OLD"},
                headers={
                    "X-Wedof-Delivery": "delivery-old",
                    "X-Wedof-Secret": "webhook-secret",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "ok": True, "duplicate": True, "crm_relayed": True,
        })
        crm_relay.assert_called_once_with(entry)
        save.assert_called_once_with([entry])
        salesforce.assert_not_called()

    def test_crm_relay_sends_cached_folder_without_an_extra_wedof_request(self):
        crm_response = type(
            "CrmResponse",
            (),
            {
                "status_code": 200,
                "text": '{"ok":true,"processed":true}',
                "json": lambda self: {"ok": True, "processed": True},
            },
        )()
        entry = {
            "id": "WEDOF-CRM",
            "delivery_id": "delivery-crm",
            "event": "registrationFolder.created",
            "payload": {"registrationFolderId": "CPF-CRM"},
            "raw_payload": '{"registrationFolderId":"CPF-CRM"}',
            "wedof_folder_details": {
                "externalId": "CPF-CRM",
                "type": "cpf",
                "state": "accepted",
                "attendee": {
                    "firstName": "Moustapha",
                    "lastName": "Diouf",
                    "email": "moustapha@example.com",
                },
            },
        }

        with patch.dict(
                 gestion_app.os.environ,
                 {
                     "CRM_WEDOF_WEBHOOK_URL": "https://crm.example.test/api/webhooks/wedof",
                     "CRM_WEDOF_WEBHOOK_SECRET": "relay-secret",
                 }, clear=False,
             ), \
             patch.object(
                 gestion_app.requests, "post", return_value=crm_response,
             ) as crm_post:
            result, status = gestion_app._send_wedof_entry_to_crm(entry)

        self.assertEqual(status, 200)
        self.assertTrue(result["success"])
        self.assertTrue(entry["crm_sent"])
        self.assertEqual(entry["crm_send_count"], 1)
        crm_post.assert_called_once()
        request_call = crm_post.call_args
        self.assertEqual(
            request_call.args[0],
            "https://crm.example.test/api/webhooks/wedof",
        )
        self.assertEqual(
            json.loads(request_call.kwargs["data"].decode("utf-8"))["externalId"],
            "CPF-CRM",
        )
        self.assertEqual(
            request_call.kwargs["headers"]["X-Wedof-Secret"],
            "relay-secret",
        )
        self.assertEqual(
            request_call.kwargs["headers"]["X-Wedof-Delivery"],
            "gestionstagiaires:delivery-crm",
        )
        self.assertNotIn(
            "X-Wedof-Signature", request_call.kwargs["headers"],
        )

    def test_admin_can_relay_an_existing_wedof_entry_to_crm(self):
        entry = {"id": "WEDOF-EXISTING", "payload": {"externalId": "CPF-1"}}

        def relay_to_crm(stored_entry):
            stored_entry["crm_sent"] = True
            stored_entry["crm_send_count"] = 1
            return {"success": True, "crm_sent": True}, 200

        with patch.object(
                 gestion_app, "_load_wedof_webhooks", return_value=[entry],
             ), \
             patch.object(gestion_app, "_save_wedof_webhooks") as save, \
             patch.object(
                 gestion_app, "_send_wedof_entry_to_crm",
                 side_effect=relay_to_crm,
             ):
            response = self.client.post(
                "/api/send-to-crm/WEDOF-EXISTING",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        save.assert_called_once_with([entry])

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
            "crm_sent": True,
            "crm_sent_at": "2026-06-12T10:00:01Z",
            "crm_send_count": 1,
        }

        with patch.object(gestion_app, "_load_wedof_webhooks", return_value=[entry]):
            response = self.client.get("/admin/wedof")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("1 nouvelle demande", html)
        cpf_navigation = next(
            link
            for link in re.findall(r'<a[^>]+href="/admin/wedof"[^>]*>.*?</a>', html, re.DOTALL)
            if "CPF" in link
        )
        self.assertNotIn("partner-sidebar__badge", cpf_navigation)
        self.assertIn(">Notifier</button>", html)
        self.assertIn("Envoyé à Salesforce le", html)
        self.assertIn("Renvoyer Salesforce", html)
        self.assertIn("Envoyé au CRM le", html)
        self.assertIn("Renvoyer au CRM", html)

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
