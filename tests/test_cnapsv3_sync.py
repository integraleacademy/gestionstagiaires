import unittest

import app as gestion_app


class DummyResponse:
    def __init__(self, status_code):
        self.status_code = status_code


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


if __name__ == "__main__":
    unittest.main()
