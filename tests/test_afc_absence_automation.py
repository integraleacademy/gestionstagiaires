import unittest

import app as gestion_app


class AfcAbsenceAutomationTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_brevo_send_email = gestion_app.brevo_send_email

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app.brevo_send_email = self.original_brevo_send_email

    def test_mark_absent_sets_rejected_fields_and_sends_notification(self):
        data = {
            "afc": {
                "candidates": [
                    {
                        "id": "AFC-ABS-1",
                        "email": "candidat@example.com",
                        "presence_afc_status": "PRESENT",
                        "decision": "RETENU",
                        "test_francais_reussi": True,
                        "motif_refus": "",
                        "complement_refus": "Autre",
                        "complement_refus_autre": "Commentaire",
                        "notification_status": "NON ENVOYEE",
                    }
                ]
            }
        }
        saved = {}

        gestion_app.load_data = lambda: data

        def fake_save_data(updated):
            saved["data"] = updated

        gestion_app.save_data = fake_save_data
        gestion_app.brevo_send_email = lambda *_args, **_kwargs: True

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.patch(
            "/api/admin/afc/candidates/AFC-ABS-1",
            json={"presence_afc_status": "ABSENT"},
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])

        candidate = payload["candidate"]
        self.assertEqual(candidate["presence_afc_status"], "ABSENT")
        self.assertEqual(candidate["decision"], "NON RETENU")
        self.assertFalse(candidate["test_francais_reussi"])
        self.assertEqual(candidate["motif_refus"], gestion_app.AFC_ABSENCE_REFUSAL_REASON)
        self.assertEqual(candidate["complement_refus"], "")
        self.assertEqual(candidate["complement_refus_autre"], "")
        self.assertEqual(candidate["notification_status"], "ENVOYEE")
        self.assertTrue(candidate["notification_sent_at"])

        saved_candidate = saved["data"]["afc"]["candidates"][0]
        self.assertEqual(saved_candidate["decision"], "NON RETENU")
        self.assertEqual(saved_candidate["motif_refus"], gestion_app.AFC_ABSENCE_REFUSAL_REASON)


if __name__ == "__main__":
    unittest.main()
