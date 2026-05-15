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

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app._now_iso = self.original_now_iso

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
        self.assertEqual(len(saved_payloads), 1)

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


if __name__ == "__main__":
    unittest.main()
