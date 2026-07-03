import unittest

import app as gestion_app


class DummyResponse:
    status_code = 202
    text = "{}"


class EmailBlocklistTests(unittest.TestCase):
    def setUp(self):
        self.original_api_key = gestion_app.BREVO_API_KEY
        self.original_post = gestion_app.requests.post
        gestion_app.BREVO_API_KEY = "test-key"

    def tearDown(self):
        gestion_app.BREVO_API_KEY = self.original_api_key
        gestion_app.requests.post = self.original_post

    def test_blocked_main_recipient_is_not_sent(self):
        calls = []
        gestion_app.requests.post = lambda *args, **kwargs: calls.append(kwargs) or DummyResponse()

        ok = gestion_app.brevo_send_email(
            " clement@integraleacademy.com ",
            "Sujet",
            "<p>Bonjour</p>",
        )

        self.assertFalse(ok)
        self.assertEqual(calls, [])

    def test_blocked_cc_recipient_is_removed_before_send(self):
        calls = []

        def fake_post(*args, **kwargs):
            calls.append(kwargs["json"])
            return DummyResponse()

        gestion_app.requests.post = fake_post

        ok = gestion_app.brevo_send_email(
            "secretariat@example.com",
            "Sujet",
            "<p>Bonjour</p>",
            cc_emails=["clement@integraleacademy.com", " autre@example.com "],
        )

        self.assertTrue(ok)
        self.assertEqual(calls[0]["to"], [{"email": "secretariat@example.com"}])
        self.assertEqual(calls[0]["cc"], [{"email": "autre@example.com"}])
        self.assertNotIn("clement@integraleacademy.com", str(calls[0]))
