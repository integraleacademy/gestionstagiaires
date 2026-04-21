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

    def test_email_match_has_priority_with_normalized_email(self):
        gestion_app.requests.get = lambda *args, **kwargs: DummyResponse(
            200,
            {
                "items": [
                    {
                        "nom": "Autre",
                        "prenom": "Personne",
                        "email": "  Charles.Debouvry@GMAIL.com  ",
                        "session": "Session différente",
                    }
                ]
            },
        )

        out = gestion_app.fetch_hebergement_status(
            " charles.debouvry@gmail.com ",
            last_name="DEBOUVRY",
            first_name="Charles",
            session_name="Du 30 mars au 2 juin 2026",
        )

        self.assertEqual(out, "reserved")

    def test_does_not_match_on_name_only_when_session_differs(self):
        gestion_app.requests.get = lambda *args, **kwargs: DummyResponse(
            200,
            {
                "items": [
                    {
                        "nom": "  débouvry ",
                        "prenom": "charles",
                        "mail": "charles.debouvry+autre@gmail.com",
                        "session": "Du 1 avril au 3 juin 2026",
                    }
                ]
            },
        )

        out = gestion_app.fetch_hebergement_status(
            "charles.debouvry@gmail.com",
            last_name=" DEBOUVRY ",
            first_name=" Charles ",
            session_date_start="2026-03-30",
            session_date_end="2026-06-02",
        )

        self.assertIsNone(out)

    def test_session_date_fallback_handles_iso_and_extra_spaces(self):
        gestion_app.requests.get = lambda *args, **kwargs: DummyResponse(
            200,
            {
                "items": [
                    {
                        "nom": "débouvry",
                        "prenom": "  charles  ",
                        "mail": "charles.debouvry+autre@gmail.com",
                        "date_start": "2026-03-30",
                        "date_end": "2026-06-02",
                    }
                ]
            },
        )

        out = gestion_app.fetch_hebergement_status(
            "charles.debouvry@gmail.com",
            last_name=" DÉBOUVRY ",
            first_name="  Charles ",
            session_date_start="2026-03-30",
            session_date_end="2026-06-02",
        )

        self.assertEqual(out, "reserved")

    def test_lookup_uses_email_query_param_when_email_is_available(self):
        captured = {}

        def fake_get(url, timeout):
            captured["url"] = url
            return DummyResponse(200, {"status": "inconnu"})

        gestion_app.requests.get = fake_get

        gestion_app.fetch_hebergement_status(
            "charles.debouvry@gmail.com",
            last_name="DEBOUVRY",
            first_name="Charles",
            session_date_start="2026-03-30",
            session_date_end="2026-06-02",
        )

        self.assertEqual(
            captured["url"],
            "https://assistance.example/lookup_hebergement.json?email=charles.debouvry%40gmail.com",
        )

    def test_lookup_falls_back_to_nom_prenom_when_email_is_missing(self):
        captured = {}

        def fake_get(url, timeout):
            captured["url"] = url
            return DummyResponse(200, {"status": "inconnu"})

        gestion_app.requests.get = fake_get

        gestion_app.fetch_hebergement_status(
            "",
            last_name="DEBOUVRY",
            first_name="Charles",
            session_date_start="2026-03-30",
            session_date_end="2026-06-02",
        )

        self.assertEqual(
            captured["url"],
            "https://assistance.example/lookup_hebergement.json?nom=DEBOUVRY&prenom=Charles",
        )

    def test_lookup_is_not_called_without_email_or_nom_prenom(self):
        called = {"value": False}

        def fake_get(url, timeout):
            called["value"] = True
            return DummyResponse(200, {"status": "inconnu"})

        gestion_app.requests.get = fake_get

        out = gestion_app.fetch_hebergement_status("", last_name="", first_name="")

        self.assertIsNone(out)
        self.assertFalse(called["value"])

    def test_keeps_unknown_when_lookup_payload_has_no_reservation(self):
        gestion_app.requests.get = lambda *args, **kwargs: DummyResponse(200, {"status": "inconnu"})

        out = gestion_app.fetch_hebergement_status("charles.debouvry@gmail.com")

        self.assertIsNone(out)


class RefreshExternalApiTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_cnaps_lookup = gestion_app.fetch_cnaps_status_by_name
        self.original_hebergement_lookup = gestion_app.fetch_hebergement_status

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app.fetch_cnaps_status_by_name = self.original_cnaps_lookup
        gestion_app.fetch_hebergement_status = self.original_hebergement_lookup

    def test_refresh_external_updates_cnaps_and_hosting_for_a3p(self):
        data = {
            "sessions": [
                {
                    "id": "S-A3P",
                    "name": "A3P MARS 2026",
                    "training_type": "A3P",
                    "date_start": "2026-03-30",
                    "date_end": "2026-06-02",
                    "trainees": [
                        {
                            "id": "T-CHARLES",
                            "last_name": "DEBOUVRY",
                            "first_name": "Charles",
                            "email": "charles.debouvry@gmail.com",
                            "cnaps": "INCONNU",
                            "hosting_status": "unknown",
                        }
                    ],
                }
            ]
        }
        saved = {"count": 0}
        seen = {}

        gestion_app.load_data = lambda: data
        gestion_app.save_data = lambda payload: saved.__setitem__("count", saved["count"] + 1)
        gestion_app.fetch_cnaps_status_by_name = lambda *_: "ACCEPTÉ"

        def fake_hebergement_lookup(email, **kwargs):
            seen["email"] = email
            seen["kwargs"] = kwargs
            return "reserved"

        gestion_app.fetch_hebergement_status = fake_hebergement_lookup

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.post("/api/sessions/S-A3P/stagiaires/T-CHARLES/refresh-external")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["cnaps_status"], "ACCEPTÉ")
        self.assertEqual(payload["hosting_status"], "reserved")
        self.assertEqual(data["sessions"][0]["trainees"][0]["hosting_status"], "reserved")
        self.assertEqual(saved["count"], 1)
        self.assertEqual(seen["email"], "charles.debouvry@gmail.com")
        self.assertEqual(seen["kwargs"]["last_name"], "DEBOUVRY")
        self.assertEqual(seen["kwargs"]["first_name"], "Charles")
        self.assertEqual(seen["kwargs"]["session_name"], "A3P MARS 2026")


class AdminTraineesPageHostingTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_hebergement_lookup = gestion_app.fetch_hebergement_status
        self.original_render_template = gestion_app.render_template

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app.fetch_hebergement_status = self.original_hebergement_lookup
        gestion_app.render_template = self.original_render_template

    def test_admin_trainees_refreshes_hosting_on_render_for_a3p(self):
        data = {
            "sessions": [
                {
                    "id": "S-A3P",
                    "name": "A3P MARS 2026",
                    "training_type": "A3P",
                    "date_start": "2026-03-30",
                    "date_end": "2026-06-02",
                    "trainees": [
                        {
                            "id": "T-CHARLES",
                            "last_name": "DEBOUVRY",
                            "first_name": "Charles",
                            "email": "charles.debouvry@gmail.com",
                            "cnaps": "INCONNU",
                            "hosting_status": "unknown",
                        }
                    ],
                }
            ]
        }
        saved = {"count": 0}
        seen = {}
        rendered = {}

        gestion_app.load_data = lambda: data
        gestion_app.save_data = lambda payload: saved.__setitem__("count", saved["count"] + 1)

        def fake_hebergement_lookup(email, **kwargs):
            seen["email"] = email
            seen["kwargs"] = kwargs
            return "reserved"

        def fake_render(template_name, **context):
            rendered["template_name"] = template_name
            rendered["context"] = context
            return "ok"

        gestion_app.fetch_hebergement_status = fake_hebergement_lookup
        gestion_app.render_template = fake_render

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.get("/admin/sessions/S-A3P/trainees")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(rendered["template_name"], "admin_trainees.html")
        self.assertEqual(saved["count"], 1)
        self.assertEqual(seen["email"], "charles.debouvry@gmail.com")
        self.assertEqual(seen["kwargs"]["last_name"], "DEBOUVRY")
        self.assertEqual(seen["kwargs"]["first_name"], "Charles")
        self.assertEqual(seen["kwargs"]["session_name"], "A3P MARS 2026")
        self.assertEqual(data["sessions"][0]["trainees"][0]["hosting_status"], "reserved")
        self.assertEqual(rendered["context"]["trainees"][0]["hosting_status"], "reserved")

    def test_admin_trainees_marks_dossier_incomplete_for_afc_when_ssiap_medical_is_missing(self):
        data = {
            "sessions": [
                {
                    "id": "S-APS-AFC",
                    "name": "APS AFC AVRIL 2026",
                    "training_type": "APS",
                    "trainees": [
                        {
                            "id": "T-1",
                            "last_name": "DUPONT",
                            "first_name": "Alice",
                            "dossier_status": "complete",
                            "birth_date": "1990-01-01",
                            "birth_city": "Paris",
                            "birth_country": "France",
                            "nationality": "Française",
                            "address": "1 rue de test",
                            "zip_code": "75001",
                            "city": "Paris",
                            "carte_vitale": "123456789012345",
                            "pre_number": "PRE-013-2029-07-25-20240908920",
                            "documents": [
                                {"key": "id", "status": "CONFORME", "file": "id.pdf", "files": ["id.pdf"]},
                                {"key": "photo", "status": "CONFORME", "file": "photo.png", "files": ["photo.png"]},
                                {"key": "carte_vitale_doc", "status": "CONFORME", "file": "vitale.pdf", "files": ["vitale.pdf"]},
                                {"key": "cnaps_doc", "status": "CONFORME", "file": "cnaps.pdf", "files": ["cnaps.pdf"]},
                            ],
                        }
                    ],
                }
            ]
        }
        rendered = {}

        def fake_render(template_name, **context):
            rendered["template_name"] = template_name
            rendered["context"] = context
            return "ok"

        gestion_app.load_data = lambda: data
        gestion_app.save_data = lambda payload: None
        gestion_app.render_template = fake_render

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.get("/admin/sessions/S-APS-AFC/trainees")

        self.assertEqual(response.status_code, 200)
        trainee = data["sessions"][0]["trainees"][0]
        self.assertTrue(trainee["afc_medical_required"])
        self.assertEqual(trainee["dossier_status"], "incomplete")
        doc_keys = [doc.get("key") for doc in trainee.get("documents", [])]
        self.assertIn("certificat_medical_ssiap_afc", doc_keys)
        self.assertEqual(rendered["context"]["trainees"][0]["dossier_status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
