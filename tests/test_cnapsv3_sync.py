import io
import unittest

import app as gestion_app


class DummyResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


class CnapsSyncTests(unittest.TestCase):
    def setUp(self):
        self.original_base = gestion_app.CNAPSV3_BASE_URL
        self.original_token = gestion_app.GESTIONSTAGIAIRE_SYNC_TOKEN
        gestion_app.CNAPSV3_BASE_URL = "https://cnapsv3.onrender.com"
        gestion_app.GESTIONSTAGIAIRE_SYNC_TOKEN = "test-token"

    def tearDown(self):
        gestion_app.CNAPSV3_BASE_URL = self.original_base
        gestion_app.GESTIONSTAGIAIRE_SYNC_TOKEN = self.original_token

    def test_sync_uses_request_id_priority(self):
        calls = []

        def fake_post(url, headers, json, timeout):
            calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return DummyResponse(200)

        ok = gestion_app.sync_cnapsv3_accept_status(
            request_id="123",
            dossier_id="999",
            post_func=fake_post,
            sleep_func=lambda *_: None,
        )

        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["json"], {"request_id": "123"})
        self.assertEqual(calls[0]["headers"]["Content-Type"], "application/json")
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer test-token")

    def test_sync_retries_on_network_errors(self):
        calls = []

        def fake_post(url, headers, json, timeout):
            calls.append(json)
            if len(calls) < 3:
                raise gestion_app.requests.Timeout("timeout")
            return DummyResponse(200)

        sleeps = []
        ok = gestion_app.sync_cnapsv3_accept_status(
            dossier_id="ABC",
            post_func=fake_post,
            sleep_func=lambda delay: sleeps.append(delay),
        )

        self.assertTrue(ok)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [1, 2])

    def test_lookup_success_returns_identifiers(self):
        def fake_post(url, headers, json, timeout):
            self.assertIn("/integrations/gestionstagiaire/cnaps/lookup", url)
            self.assertEqual(headers["Authorization"], "Bearer test-token")
            self.assertEqual(json["first_name"], "John")
            self.assertEqual(json["last_name"], "Doe")
            self.assertEqual(json["email"], "john@example.com")
            return DummyResponse(200, {"request_id": "REQ-1"})

        out = gestion_app.sync_cnapsv3_lookup_identifier(
            "John",
            "Doe",
            email="john@example.com",
            post_func=fake_post,
            sleep_func=lambda *_: None,
        )

        self.assertEqual(out, {"request_id": "REQ-1", "dossier_id": "", "email": ""})

    def test_lookup_success_returns_identifiers_and_email(self):
        out = gestion_app.sync_cnapsv3_lookup_identifier(
            "John",
            "Doe",
            post_func=lambda *args, **kwargs: DummyResponse(200, {"dossier_id": "DOS-1", "email": "john.v3@example.com"}),
            sleep_func=lambda *_: None,
        )

        self.assertEqual(out, {"request_id": "", "dossier_id": "DOS-1", "email": "john.v3@example.com"})

    def test_lookup_404_returns_none(self):
        out = gestion_app.sync_cnapsv3_lookup_identifier(
            "John",
            "Doe",
            post_func=lambda *args, **kwargs: DummyResponse(404),
            sleep_func=lambda *_: None,
        )
        self.assertIsNone(out)

    def test_lookup_409_returns_none(self):
        out = gestion_app.sync_cnapsv3_lookup_identifier(
            "John",
            "Doe",
            post_func=lambda *args, **kwargs: DummyResponse(409),
            sleep_func=lambda *_: None,
        )
        self.assertIsNone(out)


class CnapsLookupByNameParsingTests(unittest.TestCase):
    def setUp(self):
        self.original_endpoint = gestion_app.CNAPS_LOOKUP_ENDPOINT
        self.original_get = gestion_app.requests.get
        gestion_app.CNAPS_LOOKUP_ENDPOINT = "https://cnaps.example/api"

    def tearDown(self):
        gestion_app.CNAPS_LOOKUP_ENDPOINT = self.original_endpoint
        gestion_app.requests.get = self.original_get

    def test_accept_status_from_cnaps_status_field(self):
        def fake_get(url, params, timeout):
            self.assertEqual(url, "https://cnaps.example/api")
            self.assertEqual(params, {"nom": "LAM ALAM", "prenom": "MOUSTAPHA"})
            return DummyResponse(200, {"cnaps_status": "ACCEPTÉ"})

        gestion_app.requests.get = fake_get
        out = gestion_app.fetch_cnaps_lookup_by_name("Lam Alam", "Moustapha")

        self.assertIsNotNone(out)
        self.assertEqual(out["status"], "ACCEPTÉ")

    def test_accept_status_from_nested_data_payload(self):
        def fake_get(url, params, timeout):
            return DummyResponse(200, {"data": {"status": "ACCEPTE"}})

        gestion_app.requests.get = fake_get
        out = gestion_app.fetch_cnaps_lookup_by_name("Lam Alam", "Moustapha")

        self.assertIsNotNone(out)
        self.assertEqual(out["status"], "ACCEPTE")


class CnapsImportPreSaveLookupTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_store_pdf = gestion_app._store_cnaps_pending_pdf
        self.original_find_identifier = gestion_app._find_cnapsv3_identifier_for_pending
        self.original_lookup = gestion_app.sync_cnapsv3_lookup_identifier
        self.original_accept = gestion_app.sync_cnapsv3_accept_status

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app._store_cnaps_pending_pdf = self.original_store_pdf
        gestion_app._find_cnapsv3_identifier_for_pending = self.original_find_identifier
        gestion_app.sync_cnapsv3_lookup_identifier = self.original_lookup
        gestion_app.sync_cnapsv3_accept_status = self.original_accept

    def _post_save(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        return self.client.post(
            "/api/cnaps/import-pre/save",
            data={
                "pre_number": "PRE-1234-12-12-12345678901",
                "first_name": "John",
                "last_name": "Doe",
                "file": (io.BytesIO(b"%PDF-1.4 fake"), "doc.pdf"),
            },
            content_type="multipart/form-data",
        )

    def _install_common_stubs(self):
        self.data = {
            "sessions": [
                {
                    "id": "S1",
                    "trainees": [
                        {"id": "T1", "first_name": "JOHN", "last_name": "DOE", "email": "john@example.com"}
                    ],
                }
            ],
            "cnaps_pending_imports": [],
        }
        gestion_app.load_data = lambda: self.data
        gestion_app.save_data = lambda data: None
        gestion_app._store_cnaps_pending_pdf = lambda *_: "uploads/cnaps_pending/doc.pdf"
        gestion_app._find_cnapsv3_identifier_for_pending = lambda *_: {"request_id": "", "dossier_id": ""}

    def test_when_missing_identifier_lookup_is_called(self):
        self._install_common_stubs()
        called = {"lookup": 0, "accept": 0}

        def fake_lookup(first_name, last_name, email=None):
            called["lookup"] += 1
            self.assertEqual((first_name, last_name), ("JOHN", "DOE"))
            self.assertEqual(email, "john@example.com")
            return None

        def fake_accept(**kwargs):
            called["accept"] += 1
            return True

        gestion_app.sync_cnapsv3_lookup_identifier = fake_lookup
        gestion_app.sync_cnapsv3_accept_status = fake_accept

        response = self._post_save()
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(called["lookup"], 1)
        self.assertEqual(called["accept"], 0)

    def test_lookup_200_triggers_accept_with_request_id(self):
        self._install_common_stubs()
        accept_args = []

        gestion_app.sync_cnapsv3_lookup_identifier = lambda *_, **__: {"request_id": "REQ-200", "dossier_id": ""}

        def fake_accept(**kwargs):
            accept_args.append(kwargs)
            return True

        gestion_app.sync_cnapsv3_accept_status = fake_accept

        response = self._post_save()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(accept_args), 1)
        self.assertEqual(accept_args[0]["request_id"], "REQ-200")
        self.assertEqual(self.data["cnaps_pending_imports"][0]["cnapsv3_request_id"], "REQ-200")

    def test_lookup_email_is_saved_in_pending_item(self):
        self._install_common_stubs()

        gestion_app.sync_cnapsv3_lookup_identifier = lambda *_, **__: {
            "request_id": "REQ-200",
            "dossier_id": "",
            "email": "john.v3@example.com",
        }
        gestion_app.sync_cnapsv3_accept_status = lambda **kwargs: True

        response = self._post_save()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.data["cnaps_pending_imports"][0]["email"], "john.v3@example.com")

    def test_lookup_409_or_404_does_not_trigger_accept(self):
        for lookup_result in (None, None):
            self._install_common_stubs()
            called = {"accept": 0}

            gestion_app.sync_cnapsv3_lookup_identifier = lambda *_, **__: lookup_result
            gestion_app.sync_cnapsv3_accept_status = lambda **kwargs: called.__setitem__("accept", called["accept"] + 1) or True

            response = self._post_save()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(called["accept"], 0)


class CnapsPendingImportsAdminPageTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_render_template = gestion_app.render_template

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.render_template = self.original_render_template

    def test_pending_items_include_email_field(self):
        data = {
            "cnaps_pending_imports": [
                {
                    "id": "P1",
                    "last_name": "DOE",
                    "first_name": "JOHN",
                    "email": "john.v3@example.com",
                    "pre_number": "PRE-123",
                    "file_name": "doc.pdf",
                    "file_token": "",
                    "created_at": "2026-01-01T10:00:00",
                }
            ]
        }

        gestion_app.load_data = lambda: data
        captured = {}

        def fake_render(template_name, **context):
            captured["template"] = template_name
            captured["context"] = context
            return "ok"

        gestion_app.render_template = fake_render

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.get("/admin/cnaps/import-pre/pending")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["template"], "admin_cnaps_pending_imports.html")
        self.assertEqual(captured["context"]["pending_items"][0]["email"], "john.v3@example.com")


class AdminLivret2UploadTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_store_file = gestion_app._store_file

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app._store_file = self.original_store_file

    def test_zip_extension_is_allowed(self):
        self.assertIn('.zip', gestion_app.ALLOWED_EXT)

    def test_upload_livret2_creates_entry_when_missing(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'documents': [],
                        }
                    ],
                }
            ]
        }

        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: None
        gestion_app._store_file = lambda *args, **kwargs: f"{gestion_app.PERSIST_DIR}/uploads/S1/T1/documents/livret2.zip"

        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True
            sess['admin_role'] = 'admin'

        response = self.client.post(
            '/admin/sessions/S1/stagiaires/T1/documents/livret_2/upload',
            data={'file': (io.BytesIO(b'PK\x03\x04fakezip'), 'livret2.zip')},
            content_type='multipart/form-data',
        )

        self.assertEqual(response.status_code, 302)

        trainee = payload['sessions'][0]['trainees'][0]
        doc = next((d for d in trainee.get('documents', []) if d.get('key') == 'livret_2'), None)
        self.assertIsNotNone(doc)
        self.assertTrue(doc.get('files'))
        self.assertEqual(doc['files'][0], 'uploads/S1/T1/documents/livret2.zip')


class ScotiaLivret2ResetTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_safe_remove_file = gestion_app._safe_remove_file

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app._safe_remove_file = self.original_safe_remove_file

    def test_reset_livret2_removes_file_status_and_dates(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'deliverables': {'livret_2': 'uploads/S1/T1/deliverables/livret2.pdf'},
                            'scotia_livret_2_status': 'livret_2_review',
                            'scotia_livret_2_processed_at': '2026-05-12T09:00:00',
                            'vae_action_dates': {
                                'livret_2_imported_at': '12/05/2026',
                                'livret_2_received': '12/05/2026',
                                'livret_1_validated': '10/05/2026',
                            },
                        }
                    ],
                }
            ]
        }
        removed_paths = []
        saved_payloads = []

        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: saved_payloads.append(data)
        gestion_app._safe_remove_file = lambda path: removed_paths.append(path)

        with self.client.session_transaction() as sess:
            sess['scotia_logged_in'] = True

        response = self.client.post('/scotia/sessions/S1/stagiaires/T1/livret2/reset')

        self.assertEqual(response.status_code, 302)
        trainee = payload['sessions'][0]['trainees'][0]
        self.assertNotIn('livret_2', trainee['deliverables'])
        self.assertEqual(trainee['scotia_livret_2_status'], '')
        self.assertEqual(trainee['scotia_livret_2_processed_at'], '')
        self.assertNotIn('livret_2_imported_at', trainee['vae_action_dates'])
        self.assertNotIn('livret_2_received', trainee['vae_action_dates'])
        self.assertEqual(trainee['vae_action_dates']['livret_1_validated'], '10/05/2026')
        self.assertEqual(len(removed_paths), 1)
        self.assertTrue(removed_paths[0].endswith('uploads/S1/T1/deliverables/livret2.pdf'))
        self.assertEqual(len(saved_payloads), 1)


class TestFrImportTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_store_file = gestion_app._store_file

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app._store_file = self.original_store_file

    def _login_admin(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def test_import_test_fr_pdf_sets_validated_status(self):
        self._login_admin()
        data = {
            "sessions": [
                {
                    "id": "S1",
                    "training_type": "APS",
                    "trainees": [{"id": "T1", "first_name": "John", "last_name": "Doe"}],
                }
            ]
        }
        gestion_app.load_data = lambda: data
        gestion_app.save_data = lambda _: None

        stored_path = gestion_app.os.path.join(
            gestion_app.PERSIST_DIR,
            "uploads",
            "S1",
            "T1",
            "test_fr",
            "test_fr.pdf",
        )

        def fake_store_file(*_args, **_kwargs):
            gestion_app.os.makedirs(gestion_app.os.path.dirname(stored_path), exist_ok=True)
            with open(stored_path, "wb") as f:
                f.write(b"%PDF-1.4 test")
            return stored_path

        gestion_app._store_file = fake_store_file

        response = self.client.post(
            "/admin/sessions/S1/stagiaires/T1/test-fr/import",
            data={"file": (io.BytesIO(b"%PDF-1.4 fake"), "test_francais.pdf")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 302)
        trainee = data["sessions"][0]["trainees"][0]
        self.assertEqual(trainee.get("test_fr_status"), "validated")
        self.assertTrue((trainee.get("test_fr_file_token") or "").endswith("test_fr.pdf"))
        self.assertTrue(trainee.get("test_fr_imported_at"))

    def test_docs_zip_includes_imported_test_fr_pdf(self):
        self._login_admin()
        test_token = "uploads/test_fr/john_doe_test.pdf"
        full_path = gestion_app.os.path.join(gestion_app.PERSIST_DIR, test_token)
        gestion_app.os.makedirs(gestion_app.os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(b"%PDF-1.4 zip")

        data = {
            "sessions": [
                {
                    "id": "S1",
                    "training_type": "APS",
                    "trainees": [
                        {
                            "id": "T1",
                            "first_name": "John",
                            "last_name": "Doe",
                            "documents": [],
                            "test_fr_file_token": test_token,
                        }
                    ],
                }
            ]
        }
        gestion_app.load_data = lambda: data
        gestion_app.save_data = lambda _: None

        response = self.client.get("/admin/sessions/S1/stagiaires/T1/documents.zip")

        self.assertEqual(response.status_code, 200)
        zf = gestion_app.zipfile.ZipFile(io.BytesIO(response.data))
        self.assertIn("Test de français John Doe.pdf", zf.namelist())


if __name__ == "__main__":
    unittest.main()
