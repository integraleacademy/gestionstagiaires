import datetime
import io
import os
import tempfile
import unittest
from werkzeug.datastructures import FileStorage

import app as gestion_app


class ScotiaAddedDocumentsTests(unittest.TestCase):
    def setUp(self):
        self.original_persist_dir = gestion_app.PERSIST_DIR
        self.original_uploads_dir = gestion_app.UPLOADS_DIR
        self.tmpdir = tempfile.TemporaryDirectory()
        gestion_app.PERSIST_DIR = self.tmpdir.name
        gestion_app.UPLOADS_DIR = os.path.join(self.tmpdir.name, "uploads")
        os.makedirs(gestion_app.UPLOADS_DIR, exist_ok=True)

    def tearDown(self):
        gestion_app.PERSIST_DIR = self.original_persist_dir
        gestion_app.UPLOADS_DIR = self.original_uploads_dir
        self.tmpdir.cleanup()

    def _file(self, filename="document.pdf"):
        return FileStorage(stream=io.BytesIO(b"pdf"), filename=filename)

    def test_append_scotia_added_documents_groups_files_by_current_date(self):
        trainee = {}

        stored_count = gestion_app._append_scotia_added_documents("S1", "T1", trainee, [self._file()])

        today_label = datetime.date.today().strftime("%d/%m/%Y")
        self.assertEqual(stored_count, 1)
        self.assertEqual(len(trainee["scotia_added_documents"]), 1)
        self.assertEqual(trainee["scotia_added_documents"][0]["date"], today_label)
        self.assertEqual(len(trainee["scotia_added_documents"][0]["files"]), 1)
        self.assertTrue(gestion_app._scotia_added_document_token_exists(trainee, trainee["scotia_added_documents"][0]["files"][0]))

    def test_added_documents_trigger_complement_documents_control_category(self):
        payload = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "VAE DESP 2026",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Jean",
                            "last_name": "Dupont",
                            "scotia_status": "complement_requested",
                            "scotia_complementary_documents_review_status": "",
                            "vae_action_dates": {"livret_1_transmitted_scotia": "15/05/2026"},
                            "scotia_added_documents": [{"date": "26/05/2026", "files": ["token-added"]}],
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(items[0]["scotia_dashboard_category"], "complement-docs")

    def test_append_scotia_added_documents_resets_waiting_review_status(self):
        trainee = {
            "scotia_status": "complement_requested",
            "scotia_complementary_documents_review_status": "complement_documents_new_expected",
            "scotia_complementary_documents_reviewed_at": "2026-05-26T09:12:00Z",
            "scotia_complementary_documents_reviewed_at_label": "26/05/2026 à 11h12",
        }

        stored_count = gestion_app._append_scotia_added_documents("S1", "T1", trainee, [self._file()])

        self.assertEqual(stored_count, 1)
        self.assertEqual(trainee["scotia_complementary_documents_review_status"], "")
        self.assertEqual(trainee["scotia_complementary_documents_reviewed_at"], "")
        self.assertEqual(trainee["scotia_complementary_documents_reviewed_at_label"], "")

    def test_raw_scotia_added_documents_trigger_complement_documents_control(self):
        trainee = {
            "scotia_status": "complement_requested",
            "scotia_complementary_documents_review_status": "",
            "scotia_added_documents": [{"date": "26/05/2026", "files": ["token-added"]}],
        }

        self.assertTrue(gestion_app._scotia_complementary_documents_need_control(trainee))

    def test_remove_scotia_added_document_deletes_empty_group(self):
        trainee = {}
        gestion_app._append_scotia_added_documents("S1", "T1", trainee, [self._file()])
        token = trainee["scotia_added_documents"][0]["files"][0]

        removed = gestion_app._remove_scotia_added_document_token(trainee, token)

        self.assertTrue(removed)
        self.assertEqual(trainee["scotia_added_documents"], [])


class ScotiaThreadCommentsTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_now_iso = gestion_app._now_iso
        self.original_brevo_send_email = gestion_app.brevo_send_email

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app._now_iso = self.original_now_iso
        gestion_app.brevo_send_email = self.original_brevo_send_email

    def test_integrale_user_adds_thread_comment_with_french_time_label(self):
        payload = {
            "sessions": [
                {
                    "id": "S1",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [{"id": "T1", "first_name": "Jean", "last_name": "Dupont"}],
                }
            ]
        }
        saved_payloads = []
        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: saved_payloads.append(data)
        gestion_app._now_iso = lambda: "2026-05-15T06:59:00Z"

        with self.client.session_transaction() as sess:
            sess["scotia_logged_in"] = True
            sess["scotia_username"] = "clement@integraleacademy.com"

        response = self.client.post(
            "/api/scotia/sessions/S1/stagiaires/T1/thread-comments",
            json={"comment": "Information côté Intégrale"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["comment"]["author_label"], "Intégrale Academy")
        self.assertEqual(body["comment"]["created_at_label"], "15/05/2026 à 08h59")
        trainee = payload["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["scotia_thread_comments"][0]["content"], "Information côté Intégrale")
        self.assertEqual(trainee["scotia_thread_comments"][0]["author_label"], "Intégrale Academy")
        self.assertEqual(trainee["scotia_thread_comments"][0]["source"], "scotia_dashboard")
        self.assertEqual(len(saved_payloads), 1)


    def test_integrale_comment_from_scotia_page_still_notifies_admin_table(self):
        payload = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "VAE DESP 2026",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Aboubakr-Essedik",
                            "last_name": "ZINI",
                            "vae_status": "livret_1_analysis",
                            "documents": [],
                        }
                    ],
                }
            ],
            "notifications_admin": [],
        }
        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: None
        gestion_app._now_iso = lambda: "2026-06-01T07:25:00Z"

        with self.client.session_transaction() as sess:
            sess["scotia_logged_in"] = True
            sess["scotia_username"] = "clement@integraleacademy.com"

        response = self.client.post(
            "/api/scotia/sessions/S1/stagiaires/T1/thread-comments",
            json={"comment": "Commentaire ajouté depuis la page SCOTIA"},
        )
        self.assertEqual(response.status_code, 200)

        with self.client.session_transaction() as sess:
            sess.clear()
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.get("/admin/sessions/S1/trainees")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-scotia-unread-count="1"', html)
        self.assertIn('class="thread-badge" aria-label="1 commentaire non lu">1</span>', html)

    def test_admin_reply_does_not_notify_admin_table(self):
        payload = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "VAE DESP 2026",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Aboubakr-Essedik",
                            "last_name": "ZINI",
                            "vae_status": "livret_1_analysis",
                            "documents": [],
                        }
                    ],
                }
            ],
            "notifications_admin": [],
        }
        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: None
        gestion_app._now_iso = lambda: "2026-06-01T07:25:00Z"

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.post(
            "/api/sessions/S1/stagiaires/T1/thread-comments",
            json={"comment": "Réponse côté admin"},
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get("/admin/sessions/S1/trainees")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-scotia-unread-count="0"', html)
        self.assertNotIn('class="thread-badge" aria-label="1 commentaire non lu">1</span>', html)


    def test_admin_thread_comment_emails_scotia_with_cassandre_copy_and_dossier_link(self):
        payload = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "VAE DESP 2026",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Alice",
                            "last_name": "Durand",
                            "documents": [],
                        }
                    ],
                }
            ]
        }
        sent_emails = []
        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: None
        gestion_app._now_iso = lambda: "2026-06-01T07:25:00Z"
        gestion_app.brevo_send_email = lambda to, subject, html, **kwargs: sent_emails.append(
            {"to": to, "subject": subject, "html": html, "cc": kwargs.get("cc_emails") or []}
        ) or True

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.post(
            "/api/sessions/S1/stagiaires/T1/thread-comments",
            json={"comment": "Merci de vérifier le bloc 2.\nPièce importante."},
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["email_ok"])
        self.assertEqual(len(sent_emails), 1)
        self.assertEqual(sent_emails[0]["to"], "scotiaformation@gmail.com")
        self.assertEqual(sent_emails[0]["cc"], ["cassandre@integraleacademy.com"])
        self.assertIn("Nouveau commentaire VAE", sent_emails[0]["subject"])
        self.assertIn("DURAND Alice", sent_emails[0]["html"])
        self.assertIn("1 nouveau commentaire concernant le dossier VAE", sent_emails[0]["html"])
        self.assertIn("Merci de vérifier le bloc 2.<br>Pièce importante.", sent_emails[0]["html"])
        self.assertIn("/scotia#dossier-S1-T1", sent_emails[0]["html"])

    def test_scotia_thread_comment_also_emails_scotia_with_cassandre_copy(self):
        payload = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "VAE DESP 2026",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [{"id": "T1", "first_name": "Jean", "last_name": "Dupont"}],
                }
            ]
        }
        sent_emails = []
        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: None
        gestion_app._now_iso = lambda: "2026-06-01T07:25:00Z"
        gestion_app.brevo_send_email = lambda to, subject, html, **kwargs: sent_emails.append(
            {"to": to, "subject": subject, "html": html, "cc": kwargs.get("cc_emails") or []}
        ) or True

        with self.client.session_transaction() as sess:
            sess["scotia_logged_in"] = True
            sess["scotia_username"] = "scotiaformation@gmail.com"

        response = self.client.post(
            "/api/scotia/sessions/S1/stagiaires/T1/thread-comments",
            json={"comment": "Commentaire directement depuis Scotia"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["email_ok"])
        self.assertEqual(len(sent_emails), 1)
        self.assertEqual(sent_emails[0]["to"], "scotiaformation@gmail.com")
        self.assertEqual(sent_emails[0]["cc"], ["cassandre@integraleacademy.com"])
        self.assertIn("DUPONT Jean", sent_emails[0]["html"])
        self.assertIn("Commentaire directement depuis Scotia", sent_emails[0]["html"])

    def test_scotia_user_adds_thread_comment_as_scotia(self):
        payload = {
            "sessions": [
                {
                    "id": "S1",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [{"id": "T1", "first_name": "Jean", "last_name": "Dupont"}],
                }
            ]
        }
        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: None
        gestion_app._now_iso = lambda: "2026-05-15T06:59:00Z"

        with self.client.session_transaction() as sess:
            sess["scotia_logged_in"] = True
            sess["scotia_username"] = "scotiaformation@gmail.com"

        response = self.client.post(
            "/api/scotia/sessions/S1/stagiaires/T1/thread-comments",
            json={"comment": "Info Scotia"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["comment"]["author_label"], "Scotia")

    def test_all_scotia_items_exposes_thread_comments_for_display(self):
        payload = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "VAE DESP 2026",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Jean",
                            "last_name": "Dupont",
                            "vae_action_dates": {"livret_1_transmitted_scotia": "15/05/2026"},
                            "scotia_thread_comments": [
                                {
                                    "content": "Document vérifié",
                                    "author_label": "Scotia",
                                    "created_at": "2026-05-15T06:59:00Z",
                                }
                            ],
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(items[0]["scotia_thread_comments"][0]["content"], "Document vérifié")
        self.assertEqual(items[0]["scotia_thread_comments"][0]["created_at_label"], "15/05/2026 à 08h59")

    def test_scotia_dashboard_counts_scotia_messages_for_integrale_user(self):
        payload = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "VAE DESP 2026",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Jean",
                            "last_name": "Dupont",
                            "vae_action_dates": {"livret_1_transmitted_scotia": "15/05/2026"},
                            "scotia_thread_comments": [
                                {"content": "Premier message", "author_label": "Scotia", "created_at": "2026-05-15T06:59:00Z"},
                                {"content": "Message déjà lu", "author_label": "Scotia", "created_at": "2026-05-15T07:00:00Z", "read_at": "2026-05-15T08:00:00Z"},
                                {"content": "Deuxième message", "author_label": "Scotia", "created_at": "2026-05-15T07:01:00Z"},
                            ],
                        }
                    ],
                }
            ]
        }
        gestion_app.load_data = lambda: payload

        with self.client.session_transaction() as sess:
            sess["scotia_logged_in"] = True
            sess["scotia_username"] = "clement@integraleacademy.com"

        response = self.client.get("/scotia")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Messages à consulter", html)
        self.assertIn("<strong>2</strong><span>messages Scotia à consulter", html)
        self.assertIn('data-filter="messages"', html)
        self.assertIn('data-unread-messages-count="2"', html)

    def test_scotia_dashboard_counts_integrale_messages_for_scotia_user(self):
        payload = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "VAE DESP 2026",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Jean",
                            "last_name": "Dupont",
                            "vae_action_dates": {"livret_1_transmitted_scotia": "15/05/2026"},
                            "scotia_thread_comments": [
                                {"content": "Info IA", "author_label": "Intégrale Academy", "created_at": "2026-05-15T06:59:00Z"},
                            ],
                        }
                    ],
                }
            ]
        }
        gestion_app.load_data = lambda: payload

        with self.client.session_transaction() as sess:
            sess["scotia_logged_in"] = True
            sess["scotia_username"] = "scotiaformation@gmail.com"

        response = self.client.get("/scotia")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("<strong>1</strong><span>message Intégrale Academy à consulter", html)


    def test_scotia_user_deletes_thread_comment(self):
        payload = {
            "sessions": [
                {
                    "id": "S1",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Jean",
                            "last_name": "Dupont",
                            "scotia_thread_comments": [
                                {
                                    "id": "C1",
                                    "content": "Info à supprimer",
                                    "author_label": "Scotia",
                                    "author_party": "scotia",
                                    "created_at": "2026-05-15T06:59:00Z",
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        saved_payloads = []
        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: saved_payloads.append(data)
        gestion_app._now_iso = lambda: "2026-05-15T07:30:00Z"

        with self.client.session_transaction() as sess:
            sess["scotia_logged_in"] = True
            sess["scotia_username"] = "scotiaformation@gmail.com"

        response = self.client.delete("/api/scotia/sessions/S1/stagiaires/T1/thread-comments/C1")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        trainee = payload["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["scotia_thread_comments"], [])
        self.assertEqual(trainee["activity_history"][0]["label"], "Commentaire SCOTIA supprimé")
        self.assertEqual(len(saved_payloads), 1)

class ScotiaDecisionTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_now_iso = gestion_app._now_iso
        self.original_brevo_send_email = gestion_app.brevo_send_email
        self.original_notify_vae_status_change = gestion_app._notify_vae_status_change
        self.data = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "Session VAE",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Jean",
                            "last_name": "Dupont",
                            "email": "jean@example.test",
                            "scotia_status": "recevable",
                            "scotia_livret_2_status": "",
                            "vae_status": "livret_2_analysis",
                            "vae_status_label": "Réception livret 2",
                            "deliverables": {"livret_2": "uploads/S1/T1/livret_2.pdf"},
                            "vae_action_dates": {"livret_2_received": "15/05/2026"},
                        }
                    ],
                }
            ]
        }
        self.saved_payloads = []
        self.notified_statuses = []
        gestion_app.load_data = lambda: self.data
        gestion_app.save_data = lambda data: self.saved_payloads.append(data)
        gestion_app._now_iso = lambda: "2026-05-16T10:00:00Z"
        gestion_app._notify_vae_status_change = lambda trainee, status: self.notified_statuses.append(status)
        with self.client.session_transaction() as sess:
            sess["scotia_logged_in"] = True
            sess["scotia_username"] = "scotiaformation@gmail.com"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app._now_iso = self.original_now_iso
        gestion_app.brevo_send_email = self.original_brevo_send_email
        gestion_app._notify_vae_status_change = self.original_notify_vae_status_change

    def test_livret_2_ok_marks_vae_status_as_livret_2_validated(self):
        response = self.client.post(
            "/api/scotia/sessions/S1/stagiaires/T1/decision",
            json={"decision": "livret_2_ok"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})
        trainee = self.data["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["scotia_livret_2_status"], "livret_2_ok")
        self.assertEqual(trainee["vae_status"], "livret_2_validated")
        self.assertEqual(trainee["vae_status_label"], "Livret 2 validé")
        self.assertEqual(trainee["vae_action_dates"]["livret_2_validated"], "16/05/2026")
        self.assertEqual(self.notified_statuses, ["livret_2_validated"])
        self.assertEqual(len(self.saved_payloads), 1)


class AdminTraineeHistoryAndThreadTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_now_iso = gestion_app._now_iso
        self.original_brevo_send_email = gestion_app.brevo_send_email
        self.payload = {
            "sessions": [
                {
                    "id": "S1",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "Jean",
                            "last_name": "Dupont",
                            "scotia_thread_comments": [
                                {
                                    "id": "C1",
                                    "content": "Merci de compléter ce point",
                                    "author_label": "Scotia",
                                    "author_party": "scotia",
                                    "created_at": "2026-06-01T07:25:00Z",
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        self.saved_payloads = []
        gestion_app.load_data = lambda: self.payload
        gestion_app.save_data = lambda data: self.saved_payloads.append(data)
        gestion_app._now_iso = lambda: "2026-06-01T08:25:00Z"
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app._now_iso = self.original_now_iso
        gestion_app.brevo_send_email = self.original_brevo_send_email

    def test_admin_history_endpoint_exposes_scotia_thread_and_unread_badge_count(self):
        response = self.client.get("/api/sessions/S1/stagiaires/T1/history")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["unread_summary"]["count"], 1)
        self.assertEqual(body["comments"][0]["content"], "Merci de compléter ce point")
        self.assertTrue(body["comments"][0]["can_mark_read"])

    def test_admin_reply_is_added_to_thread_and_activity_history(self):
        response = self.client.post(
            "/api/sessions/S1/stagiaires/T1/thread-comments",
            json={"comment": "Réponse Intégrale"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["comment"]["author_label"], "Intégrale Academy")
        trainee = self.payload["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["scotia_thread_comments"][-1]["content"], "Réponse Intégrale")
        self.assertEqual(trainee["activity_history"][0]["label"], "Commentaire laissé par Intégrale Academy")
        self.assertEqual(len(self.saved_payloads), 1)

    def test_admin_deletes_thread_comment_and_updates_history(self):
        response = self.client.delete("/api/sessions/S1/stagiaires/T1/thread-comments/C1")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        trainee = self.payload["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["scotia_thread_comments"], [])
        self.assertEqual(trainee["activity_history"][0]["label"], "Commentaire SCOTIA supprimé")
        self.assertEqual(trainee["updated_at"], "2026-06-01T08:25:00Z")
        self.assertEqual(len(self.saved_payloads), 1)


if __name__ == "__main__":
    unittest.main()
