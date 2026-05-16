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

    def test_notify_accepts_whitespace_wrapped_identifiers(self):
        data = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "Session VTC",
                    "training_type": "VTC",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Jeremy",
                            "last_name": "Cauvin",
                            "email": "jeremy@example.com",
                            "phone": "0600000001",
                        }
                    ],
                }
            ]
        }

        gestion_app.load_data = lambda: data
        saved = {"called": 0}

        def fake_save_data(_data):
            saved["called"] += 1

        def fake_send(_session, trainee):
            trainee["vtc_practice_exam_sent_at"] = "2026-01-01T00:00:00Z"
            trainee["vtc_practice_result"] = "success"
            trainee["vtc_practice_result_label"] = "réussite examen pratique"
            return {"email_ok": True, "sms_ok": True, "sent_at": trainee["vtc_practice_exam_sent_at"]}

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
                        "session_id": " S1 ",
                        "trainee_id": " T1 ",
                        "status": "admissible",
                    }
                ]
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["sent"], 1)
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(saved["called"], 1)

    def test_notify_falls_back_to_cmar_id_when_trainee_id_missing(self):
        data = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "Session VTC",
                    "training_type": "VTC",
                    "trainees": [
                        {
                            "id": "",
                            "first_name": "Maxime",
                            "last_name": "Fournier",
                            "email": "max@example.com",
                            "phone": "0600000000",
                            "vtc_cmar_id": "00007391",
                        }
                    ],
                }
            ]
        }

        gestion_app.load_data = lambda: data
        saved = {"called": 0}

        def fake_save_data(_data):
            saved["called"] += 1

        def fake_send(_session, trainee):
            trainee["vtc_practice_exam_sent_at"] = "2026-01-01T00:00:00Z"
            trainee["vtc_practice_result"] = "success"
            trainee["vtc_practice_result_label"] = "réussite examen pratique"
            return {"email_ok": True, "sms_ok": True, "sent_at": trainee["vtc_practice_exam_sent_at"]}

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
                        "trainee_id": "",
                        "cmar_id": "00007391",
                        "status": "admissible",
                    }
                ]
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["sent"], 1)
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(saved["called"], 1)

    def test_notify_falls_back_to_session_lookup_when_session_id_missing(self):
        data = {
            "sessions": [
                {
                    "id": "",
                    "name": "Session VTC Janvier",
                    "training_type": "VTC",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Jeremy",
                            "last_name": "Cauvin",
                            "email": "jeremy@example.com",
                            "phone": "0600000001",
                            "vtc_cmar_id": "00000955",
                        }
                    ],
                }
            ]
        }

        gestion_app.load_data = lambda: data
        saved = {"called": 0}

        def fake_save_data(_data):
            saved["called"] += 1

        def fake_send(_session, trainee):
            trainee["vtc_practice_exam_sent_at"] = "2026-01-01T00:00:00Z"
            trainee["vtc_practice_result"] = "success"
            trainee["vtc_practice_result_label"] = "réussite examen pratique"
            return {"email_ok": True, "sms_ok": True, "sent_at": trainee["vtc_practice_exam_sent_at"]}

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
                        "session_id": "",
                        "session_name": "Session VTC Janvier",
                        "trainee_id": "T1",
                        "cmar_id": "00000955",
                        "status": "admissible",
                    }
                ]
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["sent"], 1)
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(saved["called"], 1)

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


class VtcPracticeExamTemplateTests(unittest.TestCase):
    def test_practice_exam_success_templates_format_exam_date(self):
        subject, html = gestion_app.build_vtc_practice_exam_success_email("Maxime", "2026-02-23")
        sms = gestion_app.build_vtc_practice_exam_success_sms("Maxime", "2026-02-23")

        self.assertIn("Félicitations", subject)
        self.assertIn("23/02/2026", html)
        self.assertIn("23/02/2026", sms)


class VaeStatusNotificationTests(unittest.TestCase):
    def setUp(self):
        self.original_send_email = gestion_app.brevo_send_email

    def tearDown(self):
        gestion_app.brevo_send_email = self.original_send_email

    def test_certified_status_sends_email_notification(self):
        sent_payload = {}

        def fake_send_email(to_email, subject, html_content, **kwargs):
            sent_payload["to_email"] = to_email
            sent_payload["subject"] = subject
            sent_payload["html_content"] = html_content
            sent_payload["trainee_id"] = (kwargs.get("trainee") or {}).get("id")
            return True

        gestion_app.brevo_send_email = fake_send_email
        trainee = {
            "id": "T1",
            "first_name": "Alice",
            "email": "alice@example.com",
            "public_link": "https://espace.exemple/espace/token",
            "phone_followups": [],
        }

        gestion_app._notify_vae_status_change(trainee, "certified")

        self.assertEqual(sent_payload["to_email"], "alice@example.com")
        self.assertIn("diplôme", sent_payload["subject"].lower())
        self.assertIn("Diplôme obtenu", sent_payload["html_content"])
        self.assertIn("Laisser un avis Google", sent_payload["html_content"])
        self.assertEqual(sent_payload["trainee_id"], "T1")
        self.assertEqual(len(trainee["phone_followups"]), 1)
        self.assertIn("Mail VAE - Diplôme obtenu", trainee["phone_followups"][0]["details"])


class ScotiaLivret2DecisionNotificationTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data

    def test_livret_2_ok_adds_admin_notification(self):
        data = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "Session VAE",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Alice",
                            "last_name": "Durand",
                            "email": "alice@example.com",
                            "scotia_status": "recevable",
                            "deliverables": {"livret_2": "uploads/S1/T1/livret2.pdf"},
                        }
                    ],
                }
            ],
            "notifications_admin": [],
        }
        saved = {"called": 0}
        gestion_app.load_data = lambda: data

        def fake_save_data(_data):
            saved["called"] += 1

        gestion_app.save_data = fake_save_data

        with self.client.session_transaction() as sess:
            sess["scotia_logged_in"] = True

        response = self.client.post(
            "/api/scotia/sessions/S1/stagiaires/T1/decision",
            json={"decision": "livret_2_ok"},
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(saved["called"], 1)
        trainee = data["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["scotia_livret_2_status"], "livret_2_ok")
        self.assertEqual(len(data["notifications_admin"]), 1)
        notification = data["notifications_admin"][0]
        self.assertIn("Livret 2 validé", notification["label"])
        self.assertIn("Alice DURAND", notification["label"])
        self.assertEqual(notification["meta"]["kind"], "scotia_livret_2_decision")
        self.assertEqual(notification["meta"]["decision"], "livret_2_ok")
