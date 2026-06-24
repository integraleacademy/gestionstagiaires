import io
import unittest

import app as gestion_app


class ScotiaLivret2UploadTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_store_file = gestion_app._store_file
        self.original_thread = gestion_app.threading.Thread

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app._store_file = self.original_store_file
        gestion_app.threading.Thread = self.original_thread

    def test_livret2_upload_saves_file_and_redirects_without_waiting_for_email(self):
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
                            "email": "jean@example.com",
                            "phone": "0600000000",
                            "scotia_status": "recevable",
                            "deliverables": {},
                            "vae_action_dates": {},
                        }
                    ],
                }
            ]
        }
        saved_payloads = []
        started_threads = []

        class FakeThread:
            def __init__(self, target, args=(), kwargs=None, daemon=None):
                self.target = target
                self.args = args
                self.kwargs = kwargs or {}
                self.daemon = daemon

            def start(self):
                started_threads.append(
                    {
                        "target": self.target,
                        "args": self.args,
                        "kwargs": self.kwargs,
                        "daemon": self.daemon,
                    }
                )

        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: saved_payloads.append(data)
        gestion_app._store_file = lambda *_args, **_kwargs: "/tmp/uploads/S1/T1/deliverables/livret2.pdf"
        gestion_app.threading.Thread = FakeThread

        with self.client.session_transaction() as sess:
            sess["scotia_logged_in"] = True

        response = self.client.post(
            "/scotia/sessions/S1/stagiaires/T1/livret2/upload",
            data={"file": (io.BytesIO(b"%PDF-1.4 fake"), "livret2.pdf")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(saved_payloads), 1)
        trainee = payload["sessions"][0]["trainees"][0]
        self.assertTrue(trainee["deliverables"]["livret_2"].endswith("uploads/S1/T1/deliverables/livret2.pdf"))
        self.assertIn("livret_2_imported_at", trainee["vae_action_dates"])
        self.assertIn("livret_2_received", trainee["vae_action_dates"])
        self.assertEqual(len(started_threads), 1)
        self.assertIs(started_threads[0]["target"], gestion_app.brevo_send_email)
        self.assertTrue(started_threads[0]["daemon"])

    def test_livret2_upload_accepts_files_up_to_ten_megabytes(self):
        self.assertGreaterEqual(gestion_app.app.config["MAX_CONTENT_LENGTH"], 10 * 1024 * 1024)

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
                            "scotia_status": "recevable",
                            "deliverables": {},
                            "vae_action_dates": {},
                        }
                    ],
                }
            ]
        }

        class FakeThread:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                pass

        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: None
        gestion_app._store_file = lambda *_args, **_kwargs: "/tmp/uploads/S1/T1/deliverables/livret2.pdf"
        gestion_app.threading.Thread = FakeThread

        with self.client.session_transaction() as sess:
            sess["scotia_logged_in"] = True

        six_megabytes = b"%PDF-1.4\n" + (b"0" * (6 * 1024 * 1024))
        response = self.client.post(
            "/scotia/sessions/S1/stagiaires/T1/livret2/upload",
            data={"file": (io.BytesIO(six_megabytes), "livret2.pdf")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 302)
        trainee = payload["sessions"][0]["trainees"][0]
        self.assertTrue(trainee["deliverables"]["livret_2"].endswith("uploads/S1/T1/deliverables/livret2.pdf"))
