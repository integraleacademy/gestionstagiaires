import unittest

import app as gestion_app


class DummyResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = str(body)

    def json(self):
        return self._body


class HebergementStatusLookupTests(unittest.TestCase):
    def setUp(self):
        self.original_endpoint = gestion_app.HEBERGEMENT_STATUS_ENDPOINT
        self.original_get = gestion_app.requests.get
        gestion_app.HEBERGEMENT_STATUS_ENDPOINT = "https://assistance.example/lookup_hebergement.json"

    def tearDown(self):
        gestion_app.HEBERGEMENT_STATUS_ENDPOINT = self.original_endpoint
        gestion_app.requests.get = self.original_get

    def test_returns_reserved_for_explicit_reserved_flag(self):
        gestion_app.requests.get = lambda *args, **kwargs: DummyResponse(200, {"reserved": True})

        out = gestion_app.fetch_hebergement_status("charles.debouvry@gmail.com")

        self.assertEqual(out, "reserved")

    def test_returns_reserved_when_matching_record_is_nested(self):
        gestion_app.requests.get = lambda *args, **kwargs: DummyResponse(
            200,
            {
                "items": [
                    {
                        "nom": "DEBOUVRY",
                        "prenom": "Charles",
                        "email": "charles.debouvry@gmail.com",
                        "session": "Du 30 mars au 2 juin 2026",
                        "mode": "Espèces",
                    }
                ]
            },
        )

        out = gestion_app.fetch_hebergement_status("charles.debouvry@gmail.com")

        self.assertEqual(out, "reserved")

    def test_returns_reserved_when_name_and_session_match_even_without_email_match(self):
        gestion_app.requests.get = lambda *args, **kwargs: DummyResponse(
            200,
            {
                "items": [
                    {
                        "nom": "DEBOUVRY",
                        "prenom": "Charles",
                        "mail": "charles.debouvry+autre@gmail.com",
                        "session": "Du 30 mars au 2 juin 2026",
                        "mode_paiement": "",
                    }
                ]
            },
        )

        out = gestion_app.fetch_hebergement_status(
            "charles.debouvry@gmail.com",
            last_name="DEBOUVRY",
            first_name="Charles",
            session_date_start="2026-03-30",
            session_date_end="2026-06-02",
        )

        self.assertEqual(out, "reserved")

    def test_lookup_sends_mail_name_and_session_params_for_assistance_backend(self):
        captured = {}

        def fake_get(_url, params, timeout):
            captured["params"] = params
            return DummyResponse(200, {"status": "inconnu"})

        gestion_app.requests.get = fake_get

        gestion_app.fetch_hebergement_status(
            "charles.debouvry@gmail.com",
            last_name="DEBOUVRY",
            first_name="Charles",
            session_date_start="2026-03-30",
            session_date_end="2026-06-02",
        )

        self.assertEqual(captured["params"]["email"], "charles.debouvry@gmail.com")
        self.assertEqual(captured["params"]["mail"], "charles.debouvry@gmail.com")
        self.assertEqual(captured["params"]["nom"], "DEBOUVRY")
        self.assertEqual(captured["params"]["prenom"], "Charles")
        self.assertEqual(captured["params"]["session"], "Du 30 mars au 2 juin 2026")

    def test_keeps_unknown_when_lookup_payload_has_no_reservation(self):
        gestion_app.requests.get = lambda *args, **kwargs: DummyResponse(200, {"status": "inconnu"})

        out = gestion_app.fetch_hebergement_status("charles.debouvry@gmail.com")

        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
