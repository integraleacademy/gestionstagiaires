import io
import unittest

from flask import render_template

import app as gestion_app


class DummyResponse:
    def __init__(self, status_code, body=None, headers=None, url="https://cnapsv3.example/api/a-traiter"):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = headers or {"Content-Type": "application/json"}
        self.url = url

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
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
                            'public_token': 'public-token',
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


class ScotiaItemsTests(unittest.TestCase):
    def test_all_scotia_items_exposes_livret_transmission_dates_separately(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'vae_action_dates': {
                                'livret_1_transmitted_scotia': '10/05/2026',
                                'livret_2_transmitted_scotia': '12/05/2026',
                            },
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['livret_1_sent_at'], '10/05/2026')
        self.assertEqual(items[0]['livret_2_sent_at'], '12/05/2026')
        self.assertEqual(items[0]['vae_sent_at'], '12/05/2026')

    def test_all_scotia_items_includes_livret_1_validated_without_scotia_transmission(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'vae_status': 'livret_1_validated',
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['vae_sent_at'], '')
        self.assertEqual(items[0]['scotia_status'], 'recevable')

    def test_all_scotia_items_includes_livret_1_validated_label_without_scotia_transmission(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'vae_status_label': 'Livret 1 validé',
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['scotia_status'], 'recevable')

    def test_all_scotia_items_includes_legacy_validated_vae_status_without_scotia_transmission(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'vae_status': 'validated',
                            'financement_status': 'validated',
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['scotia_status'], 'recevable')

    def test_all_scotia_items_includes_unaccented_livret_2_todo_label_without_scotia_transmission(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'vae_status_label': 'Livret 2 a completer',
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['scotia_status'], 'recevable')

    def test_all_scotia_items_includes_livret_2_todo_even_when_scotia_hidden(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Emanuel',
                            'last_name': 'CHIAVETTA',
                            'vae_status': 'livret_2_todo',
                            'vae_status_label': 'Livret 2 à compléter',
                            'scotia_hidden': True,
                            'vae_action_dates': {
                                'livret_1_received': '01/05/2026',
                                'livret_1_transmitted_scotia': '02/05/2026',
                                'livret_1_validated': '03/05/2026',
                                'financement_validated': '04/05/2026',
                            },
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['trainee_id'], 'T1')
        self.assertEqual(items[0]['scotia_status'], 'recevable')

    def test_all_scotia_items_includes_hidden_livret_1_analysis_when_transmitted_to_scotia(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Michael',
                            'last_name': 'BELLANGER',
                            'vae_status': 'livret_1_analysis',
                            'vae_status_label': "Livret 1 en cours d'analyse",
                            'scotia_hidden': True,
                            'vae_action_dates': {
                                'livret_1_received': '14/03/2026',
                                'livret_1_transmitted_scotia': '15/03/2026',
                            },
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['trainee_id'], 'T1')
        self.assertEqual(items[0]['livret_1_sent_at'], '15/03/2026')
        self.assertEqual(items[0]['scotia_status'], '')

    def test_all_scotia_items_keeps_hidden_for_non_transmitted_non_validated_livret_1(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'vae_status': 'livret_1_analysis',
                            'scotia_hidden': True,
                            'vae_action_dates': {
                                'livret_1_received': '02/05/2026',
                            },
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(items, [])

    def test_all_scotia_items_excludes_certified_vae_status(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'vae_status': 'certified',
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(items, [])

    def test_all_scotia_items_excludes_certified_vae_inferred_from_action_dates(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'vae_status': 'livret_2_todo',
                            'vae_action_dates': {
                                'livret_1_transmitted_scotia': '02/05/2026',
                                'diplome_obtenu': '12/05/2026',
                            },
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(items, [])

    def test_all_scotia_items_excludes_certification_obtenue_label(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'vae_status_label': 'Certification obtenue',
                            'vae_action_dates': {
                                'livret_1_transmitted_scotia': '02/05/2026',
                            },
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(items, [])

    def test_all_scotia_items_excludes_certified_vae_even_when_scotia_hidden_and_transmitted(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Vakerifa',
                            'last_name': 'SOUMAHORO',
                            'vae_status': 'certified',
                            'vae_status_label': 'Diplôme obtenu',
                            'scotia_hidden': True,
                            'vae_action_dates': {
                                'livret_1_received': '01/05/2026',
                                'livret_1_transmitted_scotia': '02/05/2026',
                                'livret_1_validated': '03/05/2026',
                                'financement_validated': '04/05/2026',
                                'livret_2_received': '05/05/2026',
                                'livret_2_transmitted_scotia': '06/05/2026',
                                'livret_2_validated': '07/05/2026',
                                'financement_l2_validated': '08/05/2026',
                                'jury_date': '09/05/2026',
                                'diplome_obtenu': '10/05/2026',
                            },
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(items, [])

    def test_all_scotia_items_excludes_certified_vae_even_when_force_visible(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'vae_status': 'certified',
                            'scotia_force_visible': True,
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(items, [])

    def test_all_scotia_items_excludes_non_recevable_scotia_status(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'vae_status': 'livret_1_analysis',
                            'scotia_status': 'non_recevable',
                            'vae_action_dates': {
                                'livret_1_transmitted_scotia': '15/03/2026',
                            },
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(items, [])

    def test_all_scotia_items_excludes_non_recevable_even_when_livret_1_validated(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'vae_status': 'livret_1_validated',
                            'scotia_status': 'non_recevable',
                        }
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload)

        self.assertEqual(items, [])

    def test_scotia_dashboard_displays_livret_2_transmission_date(self):
        item = {
            'session_id': 'S1',
            'session_name': 'VAE DESP 2026',
            'trainee_id': 'T1',
            'first_name': 'Jean',
            'last_name': 'Dupont',
            'email': 'jean@example.com',
            'phone': '0600000000',
            'vae_sent_at': '12/05/2026',
            'livret_1_sent_at': '10/05/2026',
            'livret_2_sent_at': '12/05/2026',
            'scotia_force_visible': False,
            'scotia_status': 'recevable',
            'scotia_processed_at': '',
            'scotia_comment': '',
            'scotia_livret_2_status': '',
            'scotia_livret_2_processed_at': '',
            'documents': [],
            'prerequis_interview_sheet': '',
            'complementary_documents': [],
            'deliverables': {'livret_2': 'uploads/S1/T1/livret2.pdf'},
            'attestation_recevabilite_imported_at': '',
            'livret_2_imported_at': '',
            'candidate_sheet_available': False,
            'vae_dossier_id': '',
            'vae_justificatifs': [],
        }

        with gestion_app.app.test_request_context('/scotia'):
            html = render_template('scotia_dashboard.html', items=[item])

        self.assertIn('L1 transmis le : 10/05/2026', html)
        self.assertIn('L2 transmis le : 12/05/2026', html)

    def test_all_scotia_items_can_include_archived_dashboard_items(self):
        payload = {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Valide',
                            'scotia_status': 'recevable',
                            'scotia_livret_2_status': 'livret_2_ok',
                            'deliverables': {'livret_2': 'uploads/l2.pdf'},
                            'vae_action_dates': {'livret_1_transmitted_scotia': '01/05/2026'},
                        },
                        {
                            'id': 'T2',
                            'first_name': 'Lea',
                            'last_name': 'Diplome',
                            'vae_status': 'certified',
                        },
                        {
                            'id': 'T3',
                            'first_name': 'Noe',
                            'last_name': 'Refuse',
                            'scotia_status': 'non_recevable',
                            'vae_action_dates': {'livret_1_transmitted_scotia': '02/05/2026'},
                        },
                    ],
                }
            ]
        }

        items = gestion_app._all_scotia_items(payload, include_archived=True)

        categories = {item['trainee_id']: item['scotia_archive_category'] for item in items}
        self.assertEqual(categories['T1'], 'l2-validated')
        self.assertEqual(categories['T2'], 'certified')
        self.assertEqual(categories['T3'], 'non-recevable')

    def test_scotia_dashboard_displays_archived_summary_cards(self):
        items = [
            {
                'session_id': 'S1',
                'session_name': 'VAE DESP 2026',
                'trainee_id': 'T1',
                'first_name': 'Jean',
                'last_name': 'Valide',
                'email': '',
                'phone': '',
                'vae_sent_at': '12/05/2026',
                'livret_1_sent_at': '10/05/2026',
                'livret_2_sent_at': '12/05/2026',
                'scotia_force_visible': False,
                'scotia_status': 'recevable',
                'scotia_processed_at': '',
                'scotia_comment': '',
                'scotia_livret_2_status': 'livret_2_ok',
                'scotia_livret_2_processed_at': '',
                'documents': [],
                'prerequis_interview_sheet': '',
                'complementary_documents': [],
                'added_document_groups': [],
                'scotia_thread_comments': [],
                'deliverables': {'livret_2': 'uploads/S1/T1/livret2.pdf'},
                'attestation_recevabilite_imported_at': '',
                'livret_2_imported_at': '',
                'candidate_sheet_available': False,
                'vae_dossier_id': '',
                'vae_justificatifs': [],
                'vae_status_key': 'livret_2_validated',
                'vae_status_label': 'Livret 2 validé',
                'scotia_archive_category': 'l2-validated',
                'is_scotia_archive': True,
            },
            {
                'session_id': 'S1',
                'session_name': 'VAE DESP 2026',
                'trainee_id': 'T2',
                'first_name': 'Lea',
                'last_name': 'Diplome',
                'email': '',
                'phone': '',
                'vae_sent_at': '',
                'livret_1_sent_at': '',
                'livret_2_sent_at': '',
                'scotia_force_visible': False,
                'scotia_status': 'recevable',
                'scotia_processed_at': '',
                'scotia_comment': '',
                'scotia_livret_2_status': '',
                'scotia_livret_2_processed_at': '',
                'documents': [],
                'prerequis_interview_sheet': '',
                'complementary_documents': [],
                'added_document_groups': [],
                'scotia_thread_comments': [],
                'deliverables': {},
                'attestation_recevabilite_imported_at': '',
                'livret_2_imported_at': '',
                'candidate_sheet_available': False,
                'vae_dossier_id': '',
                'vae_justificatifs': [],
                'vae_status_key': 'certified',
                'vae_status_label': 'Diplôme obtenu',
                'scotia_archive_category': 'certified',
                'is_scotia_archive': True,
            },
            {
                'session_id': 'S1',
                'session_name': 'VAE DESP 2026',
                'trainee_id': 'T3',
                'first_name': 'Noe',
                'last_name': 'Refuse',
                'email': '',
                'phone': '',
                'vae_sent_at': '',
                'livret_1_sent_at': '',
                'livret_2_sent_at': '',
                'scotia_force_visible': False,
                'scotia_status': 'non_recevable',
                'scotia_processed_at': '',
                'scotia_comment': '',
                'scotia_livret_2_status': '',
                'scotia_livret_2_processed_at': '',
                'documents': [],
                'prerequis_interview_sheet': '',
                'complementary_documents': [],
                'added_document_groups': [],
                'scotia_thread_comments': [],
                'deliverables': {},
                'attestation_recevabilite_imported_at': '',
                'livret_2_imported_at': '',
                'candidate_sheet_available': False,
                'vae_dossier_id': '',
                'vae_justificatifs': [],
                'vae_status_key': 'livret_1_analysis',
                'vae_status_label': 'Livret 1 en cours d\'analyse',
                'scotia_archive_category': 'non-recevable',
                'is_scotia_archive': True,
            },
        ]

        with gestion_app.app.test_request_context('/scotia'):
            html = render_template('scotia_dashboard.html', items=items)

        self.assertIn('Dossiers traités', html)
        self.assertIn('Livrets 2 validés', html)
        self.assertIn('Certifiés', html)
        self.assertIn('Non recevables', html)
        self.assertIn('data-filter="l2-validated"', html)
        self.assertIn('data-filter="certified"', html)
        self.assertIn('data-filter="non-recevable"', html)
        self.assertIn('<span>Livret 2</span>', html)
        self.assertIn('href="/scotia/uploads/uploads/S1/T1/livret2.pdf" target="_blank" rel="noopener">voir</a>', html)
        self.assertIn('href="/scotia/uploads/uploads/S1/T1/livret2.pdf" download>Télécharger</a>', html)


class ScotiaComplementDocumentsReviewTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_now_iso = gestion_app._now_iso
        self.original_now_paris_label = gestion_app._now_paris_label

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app._now_iso = self.original_now_iso
        gestion_app._now_paris_label = self.original_now_paris_label

    def _login_scotia(self):
        with self.client.session_transaction() as sess:
            sess['scotia_logged_in'] = True

    def _payload(self):
        return {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'scotia_status': 'complement_requested',
                            'vae_status': 'complement_requested',
                            'vae_status_label': 'Demande de complément en cours',
                            'documents': [
                                {
                                    'key': 'complementary_documents',
                                    'label': 'Documents complémentaires',
                                    'file': 'uploads/S1/T1/public_documents/complement.pdf',
                                    'files': ['uploads/S1/T1/public_documents/complement.pdf'],
                                }
                            ],
                            'vae_action_dates': {
                                'livret_1_transmitted_scotia': '10/05/2026',
                                'complementary_documents_received': '16/05/2026 à 14h35',
                            },
                        }
                    ],
                }
            ]
        }

    def test_complement_documents_conform_returns_to_livret_1_validation_with_french_timestamp(self):
        payload = self._payload()
        saved_payloads = []
        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: saved_payloads.append(data)
        gestion_app._now_iso = lambda: '2026-05-16T12:45:00Z'
        gestion_app._now_paris_label = lambda: '16/05/2026 à 14h45'
        self._login_scotia()

        response = self.client.post(
            '/api/scotia/sessions/S1/stagiaires/T1/decision',
            json={'decision': 'complement_documents_conform'},
        )

        self.assertEqual(response.status_code, 200)
        trainee = payload['sessions'][0]['trainees'][0]
        self.assertEqual(trainee['scotia_status'], '')
        self.assertEqual(trainee['vae_status'], 'livret_1_analysis')
        self.assertEqual(trainee['scotia_complementary_documents_review_status'], 'complement_documents_conform')
        self.assertEqual(trainee['scotia_complementary_documents_reviewed_at_label'], '16/05/2026 à 14h45')
        self.assertEqual(trainee['vae_action_dates']['complementary_documents_reviewed_at'], '16/05/2026 à 14h45')
        self.assertEqual(trainee['vae_action_dates']['livret_1_analysis_at'], '16/05/2026 à 14h45')
        self.assertEqual(len(saved_payloads), 1)

    def test_new_complement_expected_moves_back_to_waiting_bucket(self):
        payload = self._payload()
        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: None
        gestion_app._now_iso = lambda: '2026-05-16T12:45:00Z'
        gestion_app._now_paris_label = lambda: '16/05/2026 à 14h45'
        self._login_scotia()

        response = self.client.post(
            '/api/scotia/sessions/S1/stagiaires/T1/decision',
            json={'decision': 'complement_documents_new_expected'},
        )

        self.assertEqual(response.status_code, 200)
        trainee = payload['sessions'][0]['trainees'][0]
        self.assertEqual(trainee['scotia_status'], 'complement_requested')
        self.assertEqual(trainee['scotia_complementary_documents_review_status'], 'complement_documents_new_expected')
        self.assertEqual(trainee['vae_action_dates']['complement_requested_at'], '16/05/2026 à 14h45')

        items = gestion_app._all_scotia_items(payload)
        with gestion_app.app.test_request_context('/scotia'):
            html = render_template('scotia_dashboard.html', items=items)

        self.assertIn('En attente documents complémentaires', html)
        self.assertNotIn('complément de dossier à consulter', html)
        self.assertNotIn('Commentaire SCOTIA', html)

    def test_scotia_dashboard_shows_control_buttons_without_scotia_comment(self):
        item = {
            'session_id': 'S1',
            'session_name': 'VAE DESP 2026',
            'trainee_id': 'T1',
            'first_name': 'Jean',
            'last_name': 'Dupont',
            'email': '',
            'phone': '',
            'vae_sent_at': '12/05/2026',
            'livret_1_sent_at': '10/05/2026',
            'livret_2_sent_at': '',
            'scotia_force_visible': False,
            'scotia_status': 'complement_requested',
            'scotia_processed_at': '',
            'scotia_comment': 'Ancien commentaire',
            'scotia_livret_2_status': '',
            'scotia_livret_2_processed_at': '',
            'documents': [],
            'prerequis_interview_sheet': '',
            'complementary_documents': ['uploads/S1/T1/public_documents/complement.pdf'],
            'complementary_documents_received_at': '16/05/2026 à 14h35',
            'scotia_complementary_documents_review_status': '',
            'scotia_complementary_documents_reviewed_at': '',
            'added_document_groups': [],
            'scotia_thread_comments': [],
            'deliverables': {},
            'attestation_recevabilite_imported_at': '',
            'livret_2_imported_at': '',
            'candidate_sheet_available': False,
            'vae_dossier_id': '',
            'vae_justificatifs': [],
        }

        with gestion_app.app.test_request_context('/scotia'):
            html = render_template('scotia_dashboard.html', items=[item])

        self.assertIn('Rechercher une personne', html)
        self.assertIn('id="scotia-search-input"', html)
        self.assertIn('placeholder="Nom ou prénom..."', html)
        self.assertIn('data-search-name="Jean Dupont Dupont Jean"', html)
        self.assertIn('applyScotiaFilters', html)
        self.assertIn('Documents à contrôler', html)
        self.assertIn('Conformes', html)
        self.assertIn('Non conforme', html)
        self.assertIn('Nouveau complément attendu', html)
        self.assertIn('16/05/2026 à 14h35 (heure française)', html)
        self.assertNotIn('Commentaire SCOTIA', html)
        self.assertNotIn('Ancien commentaire', html)


class ScotiaComplementDocumentsReviewTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_now_iso = gestion_app._now_iso
        self.original_now_paris_label = gestion_app._now_paris_label
        self.original_store_file = gestion_app._store_file
        self.original_notify_scotia_complementary_documents = gestion_app._notify_scotia_complementary_documents

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app._now_iso = self.original_now_iso
        gestion_app._now_paris_label = self.original_now_paris_label
        gestion_app._store_file = self.original_store_file
        gestion_app._notify_scotia_complementary_documents = self.original_notify_scotia_complementary_documents

    def _login_scotia(self):
        with self.client.session_transaction() as sess:
            sess['scotia_logged_in'] = True

    def _payload(self):
        return {
            'sessions': [
                {
                    'id': 'S1',
                    'name': 'VAE DESP 2026',
                    'training_type': 'DIRIGEANT VAE',
                    'trainees': [
                        {
                            'id': 'T1',
                            'first_name': 'Jean',
                            'last_name': 'Dupont',
                            'public_token': 'public-token',
                            'scotia_status': 'complement_requested',
                            'vae_status': 'complement_requested',
                            'vae_status_label': 'Demande de complément en cours',
                            'documents': [
                                {
                                    'key': 'complementary_documents',
                                    'label': 'Documents complémentaires',
                                    'file': 'uploads/S1/T1/public_documents/complement.pdf',
                                    'files': ['uploads/S1/T1/public_documents/complement.pdf'],
                                }
                            ],
                            'vae_action_dates': {
                                'livret_1_transmitted_scotia': '10/05/2026',
                                'complementary_documents_received': '16/05/2026 à 14h35',
                            },
                        }
                    ],
                }
            ]
        }

    def test_complement_documents_conform_returns_to_livret_1_validation_with_french_timestamp(self):
        payload = self._payload()
        saved_payloads = []
        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: saved_payloads.append(data)
        gestion_app._now_iso = lambda: '2026-05-16T12:45:00Z'
        gestion_app._now_paris_label = lambda: '16/05/2026 à 14h45'
        self._login_scotia()

        response = self.client.post(
            '/api/scotia/sessions/S1/stagiaires/T1/decision',
            json={'decision': 'complement_documents_conform'},
        )

        self.assertEqual(response.status_code, 200)
        trainee = payload['sessions'][0]['trainees'][0]
        self.assertEqual(trainee['scotia_status'], '')
        self.assertEqual(trainee['vae_status'], 'livret_1_analysis')
        self.assertEqual(trainee['scotia_complementary_documents_review_status'], 'complement_documents_conform')
        self.assertEqual(trainee['scotia_complementary_documents_reviewed_at_label'], '16/05/2026 à 14h45')
        self.assertEqual(trainee['vae_action_dates']['complementary_documents_reviewed_at'], '16/05/2026 à 14h45')
        self.assertEqual(trainee['vae_action_dates']['livret_1_analysis_at'], '16/05/2026 à 14h45')
        self.assertEqual(len(saved_payloads), 1)

    def test_new_complement_expected_moves_back_to_waiting_bucket(self):
        payload = self._payload()
        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: None
        gestion_app._now_iso = lambda: '2026-05-16T12:45:00Z'
        gestion_app._now_paris_label = lambda: '16/05/2026 à 14h45'
        self._login_scotia()

        response = self.client.post(
            '/api/scotia/sessions/S1/stagiaires/T1/decision',
            json={'decision': 'complement_documents_new_expected'},
        )

        self.assertEqual(response.status_code, 200)
        trainee = payload['sessions'][0]['trainees'][0]
        self.assertEqual(trainee['scotia_status'], 'complement_requested')
        self.assertEqual(trainee['scotia_complementary_documents_review_status'], 'complement_documents_new_expected')
        self.assertEqual(trainee['vae_action_dates']['complement_requested_at'], '16/05/2026 à 14h45')

        items = gestion_app._all_scotia_items(payload)
        with gestion_app.app.test_request_context('/scotia'):
            html = render_template('scotia_dashboard.html', items=items)

        self.assertIn('En attente documents complémentaires', html)
        self.assertNotIn('complément de dossier à consulter', html)
        self.assertNotIn('Commentaire SCOTIA', html)

    def test_public_space_allows_new_upload_after_new_complement_expected(self):
        payload = self._payload()
        trainee = payload['sessions'][0]['trainees'][0]
        trainee['scotia_complementary_documents_review_status'] = 'complement_documents_new_expected'
        trainee['scotia_complementary_documents_reviewed_at_label'] = '16/05/2026 à 14h45'
        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: None

        with self.client.session_transaction() as sess:
            sess['public_auth_public-token'] = True

        response = self.client.get('/espace/public-token')

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Nouveaux compléments attendus', html)
        self.assertIn('/espace/public-token/documents/complementary_documents/upload', html)
        self.assertIn('Déposer un document complémentaire', html)

    def test_added_documents_hide_new_complement_expected_public_label(self):
        payload = self._payload()
        trainee = payload['sessions'][0]['trainees'][0]
        trainee['scotia_complementary_documents_review_status'] = 'complement_documents_new_expected'
        trainee['scotia_complementary_documents_reviewed_at_label'] = '16/05/2026 à 14h45'
        trainee['scotia_added_documents'] = [{'date': '26/05/2026', 'files': ['uploads/S1/T1/scotia_added_documents/document.pdf']}]
        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: None

        with self.client.session_transaction() as sess:
            sess['public_auth_public-token'] = True

        response = self.client.get('/espace/public-token')

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn('Nouveaux compléments attendus', html)
        self.assertNotIn('/espace/public-token/documents/complementary_documents/upload', html)
        self.assertTrue(gestion_app._scotia_complementary_documents_need_control(trainee))
        self.assertFalse(gestion_app._public_complementary_documents_upload_expected(trainee))

    def test_public_new_upload_after_new_complement_expected_moves_to_consult_bucket(self):
        payload = self._payload()
        trainee = payload['sessions'][0]['trainees'][0]
        trainee['scotia_complementary_documents_review_status'] = 'complement_documents_new_expected'
        trainee['scotia_complementary_documents_reviewed_at_label'] = '16/05/2026 à 14h45'
        saved_payloads = []
        stored_path = gestion_app.os.path.join(
            gestion_app.PERSIST_DIR,
            'uploads',
            'S1',
            'T1',
            'public_documents',
            'new-complement.pdf',
        )
        gestion_app.load_data = lambda: payload
        gestion_app.save_data = lambda data: saved_payloads.append(data)
        gestion_app._store_file = lambda *_args, **_kwargs: stored_path
        gestion_app._notify_scotia_complementary_documents = lambda *_args, **_kwargs: True
        gestion_app._now_paris_label = lambda: '17/05/2026 à 09h12'

        with self.client.session_transaction() as sess:
            sess['public_auth_public-token'] = True

        response = self.client.post(
            '/espace/public-token/documents/complementary_documents/upload',
            data={'files': (io.BytesIO(b'%PDF-1.4 new'), 'new-complement.pdf')},
            content_type='multipart/form-data',
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(trainee['scotia_complementary_documents_review_status'], '')
        self.assertEqual(trainee['vae_action_dates']['complementary_documents_received'], '17/05/2026 à 09h12')
        self.assertIn('uploads/S1/T1/public_documents/new-complement.pdf', trainee['scotia_complementary_documents'])
        self.assertGreaterEqual(len(saved_payloads), 1)

        items = gestion_app._all_scotia_items(payload)
        with gestion_app.app.test_request_context('/scotia'):
            html = render_template('scotia_dashboard.html', items=items)

        self.assertIn('complément de dossier à consulter', html)
        self.assertIn('Documents à contrôler', html)


    def test_scotia_dashboard_shows_control_buttons_without_scotia_comment(self):
        item = {
            'session_id': 'S1',
            'session_name': 'VAE DESP 2026',
            'trainee_id': 'T1',
            'first_name': 'Jean',
            'last_name': 'Dupont',
            'email': '',
            'phone': '',
            'vae_sent_at': '12/05/2026',
            'livret_1_sent_at': '10/05/2026',
            'livret_2_sent_at': '',
            'scotia_force_visible': False,
            'scotia_status': 'complement_requested',
            'scotia_processed_at': '',
            'scotia_comment': 'Ancien commentaire',
            'scotia_livret_2_status': '',
            'scotia_livret_2_processed_at': '',
            'documents': [],
            'prerequis_interview_sheet': '',
            'complementary_documents': ['uploads/S1/T1/public_documents/complement.pdf'],
            'complementary_documents_received_at': '16/05/2026 à 14h35',
            'scotia_complementary_documents_review_status': '',
            'scotia_complementary_documents_reviewed_at': '',
            'added_document_groups': [],
            'scotia_thread_comments': [],
            'deliverables': {},
            'attestation_recevabilite_imported_at': '',
            'livret_2_imported_at': '',
            'candidate_sheet_available': False,
            'vae_dossier_id': '',
            'vae_justificatifs': [],
        }

        with gestion_app.app.test_request_context('/scotia'):
            html = render_template('scotia_dashboard.html', items=[item])

        self.assertIn('Documents à contrôler', html)
        self.assertIn('Conformes', html)
        self.assertIn('Non conforme', html)
        self.assertIn('Nouveaux compléments attendus', html)
        self.assertIn('16/05/2026 à 14h35 (heure française)', html)
        self.assertNotIn('Commentaire SCOTIA', html)
        self.assertNotIn('Ancien commentaire', html)


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


class ScotiaDashboardFilterCategoryTests(unittest.TestCase):
    def _base_item(self, **overrides):
        item = {
            'session_id': 'S1',
            'session_name': 'VAE DESP 2026',
            'trainee_id': 'T1',
            'first_name': 'Jean',
            'last_name': 'Dupont',
            'email': '',
            'phone': '',
            'vae_sent_at': '12/05/2026',
            'livret_1_sent_at': '10/05/2026',
            'livret_2_sent_at': '',
            'scotia_force_visible': False,
            'scotia_status': 'complement_requested',
            'scotia_processed_at': '',
            'scotia_comment': '',
            'scotia_livret_2_status': '',
            'scotia_livret_2_processed_at': '',
            'documents': [],
            'prerequis_interview_sheet': '',
            'complementary_documents': ['uploads/S1/T1/public_documents/complement.pdf'],
            'complementary_documents_received_at': '16/05/2026 à 14h35',
            'scotia_complementary_documents_review_status': '',
            'scotia_complementary_documents_reviewed_at': '',
            'added_document_groups': [],
            'scotia_thread_comments': [],
            'deliverables': {},
            'attestation_recevabilite_imported_at': '',
            'livret_2_imported_at': '',
            'candidate_sheet_available': False,
            'vae_dossier_id': '',
            'vae_justificatifs': [],
            'vae_status_key': 'complement_requested',
            'vae_status_label': 'Demande de complément en cours',
            'scotia_archive_category': '',
            'is_scotia_archive': False,
        }
        item.update(overrides)
        return item

    def test_complement_documents_stat_matches_rendered_filter_category(self):
        item = self._base_item()
        item['scotia_dashboard_category'] = gestion_app._scotia_dashboard_category(item)

        with gestion_app.app.test_request_context('/scotia'):
            html = render_template('scotia_dashboard.html', items=[item])

        self.assertEqual(item['scotia_dashboard_category'], 'complement-docs')
        self.assertIn('<strong>1</strong><span>complément de dossier à consulter', html)
        self.assertIn('data-filter="complement-docs"', html)
        self.assertIn('data-category="complement-docs"', html)

    def test_added_documents_hide_new_expected_button_in_control_actions(self):
        item = self._base_item(
            added_document_groups=[{'date': '26/05/2026', 'files': ['uploads/S1/T1/scotia_added_documents/document.pdf']}],
        )
        item['scotia_dashboard_category'] = gestion_app._scotia_dashboard_category(item)

        with gestion_app.app.test_request_context('/scotia'):
            html = render_template('scotia_dashboard.html', items=[item])

        self.assertEqual(item['scotia_dashboard_category'], 'complement-docs')
        self.assertIn('Documents à contrôler', html)
        self.assertIn('Conformes', html)
        self.assertIn('Non conforme', html)
        self.assertNotIn('Nouveaux compléments attendus</button>', html)

    def test_precomputed_dashboard_category_drives_count_and_dom_category(self):
        item = self._base_item(
            scotia_dashboard_category='complements',
            scotia_complementary_documents_review_status='complement_documents_new_expected',
        )

        with gestion_app.app.test_request_context('/scotia'):
            html = render_template('scotia_dashboard.html', items=[item])

        self.assertIn('<strong>0</strong><span>compléments de dossier à consulter', html)
        self.assertIn('<strong>1</strong><span>En attente documents complémentaires', html)
        self.assertIn('data-category="complements"', html)

    def test_livret_1_action_is_counted_in_actions_to_do(self):
        item = self._base_item(
            scotia_status='',
            complementary_documents=[],
            scotia_dashboard_category='l1-action',
            vae_status_key='livret_1_analysis',
            vae_status_label="Livret 1 en cours d'analyse",
        )

        with gestion_app.app.test_request_context('/scotia'):
            html = render_template('scotia_dashboard.html', items=[item])

        self.assertIn('<strong>1</strong><span>Livrets 1 à valider', html)
        self.assertIn('1 action à mener', html)
        self.assertIn('data-category="l1-action"', html)


class CnapsTrackingTests(unittest.TestCase):
    def setUp(self):
        self.original_base = gestion_app.CNAPSV3_BASE_URL
        self.original_token = gestion_app.os.environ.get("CNAPSV3_API_TOKEN")
        gestion_app.CNAPSV3_BASE_URL = "https://cnapsv3.example"
        gestion_app.os.environ["CNAPSV3_API_TOKEN"] = "tracking-token"
        gestion_app._cnapsv3_tracking_cache.update({"expires_at": 0.0, "rows": [], "error": None})

    def tearDown(self):
        gestion_app.CNAPSV3_BASE_URL = self.original_base
        if self.original_token is None:
            gestion_app.os.environ.pop("CNAPSV3_API_TOKEN", None)
        else:
            gestion_app.os.environ["CNAPSV3_API_TOKEN"] = self.original_token
        gestion_app._cnapsv3_tracking_cache.update({"expires_at": 0.0, "rows": [], "error": None})

    def test_tracking_requests_are_normalized_from_a_traiter_payload(self):
        calls = []

        def fake_get(url, headers, timeout):
            calls.append({"url": url, "headers": headers, "timeout": timeout})
            return DummyResponse(200, {
                "demandes": [
                    {"nom": "DOE", "prenom": "Jane", "nub": "NUB123", "statut_cnaps": "transmis", "created_at": "2026-07-15T08:00:00Z"},
                    {"last_name": "SMITH", "first_name": "John", "numero_nub": "NUB456", "status": "TRANSMIS", "date_creation": "16/07/2026"},
                    {"nom": "DUPONT", "prenom": "clément", "nub": "NUB789", "statut": "TRANSMIS", "date_depot": "2026-07-20"},
                ]
            })

        rows, error = gestion_app.fetch_cnapsv3_tracking_requests(get_func=fake_get)

        self.assertIsNone(error)
        self.assertEqual(calls[0]["url"], "https://cnapsv3.example/api/a-traiter")
        self.assertEqual(calls[0]["headers"], {"Accept": "application/json", "Authorization": "Bearer tracking-token"})
        self.assertEqual(calls[0]["timeout"], 10)
        self.assertEqual(rows, [
            {"last_name": "DOE", "first_name": "Jane", "nub": "NUB123", "cnaps_status": "transmis"},
            {"last_name": "SMITH", "first_name": "John", "nub": "NUB456", "cnaps_status": "TRANSMIS"},
            {"last_name": "DUPONT", "first_name": "Clément", "nub": "NUB789", "cnaps_status": "TRANSMIS"},
        ])

    def test_tracking_requests_keep_new_rows_and_all_transmitted_rows(self):
        def fake_get(url, headers, timeout):
            return DummyResponse(200, {
                "requests": [
                    {"nom": "KEEP", "prenom": "Since", "nub": "NUB1", "statut_cnaps": "Transmis", "created_at": "2026-07-15T00:00:00Z"},
                    {"nom": "OLD", "prenom": "Before", "nub": "NUB2", "statut_cnaps": "TRANSMIS", "created_at": "2026-07-14T23:59:59Z"},
                    {"nom": "NEW", "prenom": "Other", "nub": "NUB3", "statut_cnaps": "ACCEPTE", "created_at": "2026-07-16T00:00:00Z"},
                    {"nom": "MISSING", "prenom": "Date", "nub": "NUB4", "statut_cnaps": "ACCEPTE"},
                ]
            })

        rows, error = gestion_app.fetch_cnapsv3_tracking_requests(get_func=fake_get)

        self.assertIsNone(error)
        self.assertEqual([row["last_name"] for row in rows], ["KEEP", "OLD", "NEW"])



    def test_tracking_returns_empty_list_on_401(self):
        rows, error = gestion_app.fetch_cnapsv3_tracking_requests(
            get_func=lambda *_, **__: DummyResponse(401, {"detail": "unauthorized"})
        )
        self.assertEqual(rows, [])
        self.assertIn("authentification", error)

    def test_tracking_returns_empty_list_on_html_response(self):
        rows, error = gestion_app.fetch_cnapsv3_tracking_requests(
            get_func=lambda *_, **__: DummyResponse(200, "<html>login</html>", headers={"Content-Type": "text/html"})
        )
        self.assertEqual(rows, [])
        self.assertIn("non JSON", error)

    def test_tracking_returns_empty_list_on_invalid_json(self):
        rows, error = gestion_app.fetch_cnapsv3_tracking_requests(
            get_func=lambda *_, **__: DummyResponse(200, ValueError("bad json"))
        )
        self.assertEqual(rows, [])
        self.assertIn("JSON invalide", error)

    def test_tracking_returns_empty_list_on_timeout(self):
        def fake_get(*_, **__):
            raise gestion_app.requests.Timeout("timeout")

        rows, error = gestion_app.fetch_cnapsv3_tracking_requests(get_func=fake_get)
        self.assertEqual(rows, [])
        self.assertIn("timeout", error)

    def test_tracking_returns_empty_list_without_token(self):
        gestion_app.os.environ.pop("CNAPSV3_API_TOKEN", None)
        called = {"value": False}

        def fake_get(*_, **__):
            called["value"] = True
            return DummyResponse(200, {"requests": []})

        rows, error = gestion_app.fetch_cnapsv3_tracking_requests(get_func=fake_get)
        self.assertEqual(rows, [])
        self.assertFalse(called["value"])
        self.assertIn("CNAPSV3_API_TOKEN", error)

    def test_tracking_rejects_login_final_url(self):
        rows, error = gestion_app.fetch_cnapsv3_tracking_requests(
            get_func=lambda *_, **__: DummyResponse(200, {"requests": []}, url="https://cnapsv3.example/login")
        )
        self.assertEqual(rows, [])
        self.assertIn("connexion", error)


    def test_tracking_default_get_uses_short_server_cache(self):
        calls = []
        original_get = gestion_app.requests.get

        def fake_default_get(url, headers, timeout):
            calls.append({"url": url, "headers": headers, "timeout": timeout})
            return DummyResponse(200, {"requests": [{"nom": "CACHE", "prenom": "Hit", "nub": "NUB-C"}]})

        gestion_app.requests.get = fake_default_get
        try:
            rows_1, error_1 = gestion_app.fetch_cnapsv3_tracking_requests()
            rows_2, error_2 = gestion_app.fetch_cnapsv3_tracking_requests()
        finally:
            gestion_app.requests.get = original_get

        self.assertIsNone(error_1)
        self.assertIsNone(error_2)
        self.assertEqual(rows_1, rows_2)
        self.assertEqual(len(calls), 1)

    def test_tracking_page_renders_table(self):
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        original_fetch = gestion_app.fetch_cnapsv3_tracking_requests
        gestion_app.fetch_cnapsv3_tracking_requests = lambda: ([{
            "last_name": "DOE",
            "first_name": "Jane",
            "nub": "NUB123",
            "cnaps_status": "ACCEPTE",
        }], None)
        try:
            response = client.get("/admin/sessions/suivi-cnaps")
        finally:
            gestion_app.fetch_cnapsv3_tracking_requests = original_fetch

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Suivi CNAPS", html)
        self.assertIn("<th>NOM</th>", html)
        self.assertIn("<th>Prénom</th>", html)
        self.assertIn("<th>NUB</th>", html)
        self.assertIn("<th>Inscription formation</th>", html)
        self.assertIn("<th>Statut</th>", html)
        self.assertNotIn("Statut Carte pro", html)
        self.assertNotIn("data-card-pro-refresh", html)
        self.assertIn("Rechercher une personne", html)
        self.assertIn("data-delete-cnaps-row", html)
        self.assertIn("DOE", html)
        self.assertIn("NUB123", html)

    def test_tracking_page_forces_chiocca_ap_sh_active_by_name_and_nub(self):
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        original_fetch = gestion_app.fetch_cnapsv3_tracking_requests
        gestion_app.fetch_cnapsv3_tracking_requests = lambda: ([{
            "last_name": "CHIOCCA",
            "first_name": "Laurine",
            "nub": "1079213",
            "cnaps_status": "INCONNU",
        }], None)
        try:
            response = client.get("/admin/sessions/suivi-cnaps")
        finally:
            gestion_app.fetch_cnapsv3_tracking_requests = original_fetch

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-nom="CHIOCCA"', html)
        self.assertIn('data-nub="1079213"', html)
        self.assertIn('normalizedLastName==="CHIOCCA"&&normalizedNub==="1079213"', html)
        self.assertIn('validite_titre:"ACTIF"', html)

    def test_cnaps_public_annuaire_notifies_when_unknown_becomes_active(self):
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        data = {"cnaps_status_change_notifications": {}}
        saved = []
        sent = []
        original_fetch = gestion_app.fetch_cnaps_public_annuaire
        original_load = gestion_app.load_data
        original_save = gestion_app.save_data
        original_email = gestion_app.brevo_send_email
        gestion_app.fetch_cnaps_public_annuaire = lambda nom, nub: {
            "activite": "Autorisation préalable - Surveillance humaine ou gardiennage",
            "validite_titre": "ACTIF",
            "results": [{"activite": "Autorisation préalable - Surveillance humaine ou gardiennage", "validite_titre": "ACTIF"}],
        }
        gestion_app.load_data = lambda: data
        gestion_app.save_data = lambda payload: saved.append(payload.copy())
        gestion_app.brevo_send_email = lambda *args, **kwargs: sent.append({"args": args, "kwargs": kwargs}) or {"ok": True}
        try:
            response = client.get("/api/cnaps_public_annuaire?nom=DOE&prenom=Jane&nub=1234567&previous_status=INCONNU")
        finally:
            gestion_app.fetch_cnaps_public_annuaire = original_fetch
            gestion_app.load_data = original_load
            gestion_app.save_data = original_save
            gestion_app.brevo_send_email = original_email

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["notification_sent"])
        self.assertEqual(sent[0]["args"][0], "cassandre@integraleacademy.com")
        self.assertIn("Changement de statut CNAPS", sent[0]["args"][1])
        self.assertEqual(sent[0]["kwargs"]["cc_emails"], ["elsa@integraleacademy.com", "clement@integraleacademy.com"])
        self.assertTrue(saved)
        self.assertIn("DOE|1234567", data["cnaps_status_change_notifications"])

    def test_cnaps_public_annuaire_does_not_notify_duplicate_signature(self):
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        signature = "Autorisation préalable - Surveillance humaine ou gardiennage • ACTIF"
        data = {"cnaps_status_change_notifications": {"DOE|1234567": {"signature": signature}}}
        sent = []
        original_fetch = gestion_app.fetch_cnaps_public_annuaire
        original_load = gestion_app.load_data
        original_save = gestion_app.save_data
        original_email = gestion_app.brevo_send_email
        gestion_app.fetch_cnaps_public_annuaire = lambda nom, nub: {
            "activite": "Autorisation préalable - Surveillance humaine ou gardiennage",
            "validite_titre": "ACTIF",
            "results": [{"activite": "Autorisation préalable - Surveillance humaine ou gardiennage", "validite_titre": "ACTIF"}],
        }
        gestion_app.load_data = lambda: data
        gestion_app.save_data = lambda payload: self.fail("save_data should not be called for duplicate notification")
        gestion_app.brevo_send_email = lambda *args, **kwargs: sent.append(args) or {"ok": True}
        try:
            response = client.get("/api/cnaps_public_annuaire?nom=DOE&prenom=Jane&nub=1234567&previous_status=INCONNU")
        finally:
            gestion_app.fetch_cnaps_public_annuaire = original_fetch
            gestion_app.load_data = original_load
            gestion_app.save_data = original_save
            gestion_app.brevo_send_email = original_email

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["notification_sent"])
        self.assertEqual(sent, [])

    def test_tracking_delete_persists_and_filters_refresh(self):
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        data = {"sessions": [], "cnaps_tracking_deleted_keys": []}
        saved = []
        original_fetch = gestion_app.fetch_cnapsv3_tracking_requests
        original_load = gestion_app.load_data
        original_save = gestion_app.save_data
        gestion_app.fetch_cnapsv3_tracking_requests = lambda: ([{
            "last_name": "Doe",
            "first_name": "Jane",
            "nub": "NUB123",
            "cnaps_status": "ACCEPTE",
        }], None)
        gestion_app.load_data = lambda: data
        gestion_app.save_data = lambda payload: saved.append(payload.copy())
        try:
            delete_response = client.post("/api/admin/cnaps-tracking/delete", json={
                "last_name": "Doe",
                "first_name": "Jane",
                "nub": "NUB123",
            })
            page_response = client.get("/admin/sessions/suivi-cnaps")
        finally:
            gestion_app.fetch_cnapsv3_tracking_requests = original_fetch
            gestion_app.load_data = original_load
            gestion_app.save_data = original_save

        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.get_json()["ok"], True)
        self.assertIn("DOE|JANE|NUB123", data["cnaps_tracking_deleted_keys"])
        self.assertTrue(saved)
        html = page_response.get_data(as_text=True)
        self.assertNotIn("NUB123", html)


if __name__ == "__main__":
    unittest.main()
