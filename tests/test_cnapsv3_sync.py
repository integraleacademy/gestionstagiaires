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


if __name__ == "__main__":
    unittest.main()
