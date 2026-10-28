import unittest
from unittest.mock import Mock, patch

import app as gestion_app


class SsiapBirthDepartmentTests(unittest.TestCase):
    def setUp(self):
        self.cache = patch.dict(gestion_app.SSIAP_BIRTH_DEPARTMENT_CACHE, {}, clear=True)
        self.cache.start()
        self.addCleanup(self.cache.stop)
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def lookup(self, city, communes, country="France"):
        response = Mock()
        response.json.return_value = communes
        with patch.object(gestion_app.requests, "get", return_value=response):
            result = self.client.get("/admin/ssiap/birth-department", query_string={
                "city": city, "country": country,
            })
        self.assertEqual(result.status_code, 200)
        return result.get_json()["department"]

    def test_maubeuge_is_resolved_and_success_is_cached(self):
        self.assertEqual(self.lookup("MAUBEUGE", [{"nom": "Maubeuge", "codeDepartement": "59"}]), "59")
        with patch.object(gestion_app.requests, "get") as get:
            self.assertEqual(gestion_app._lookup_birth_department_code("maubeuge"), "59")
        get.assert_not_called()

    def test_accents_hyphens_corsica_and_overseas_codes(self):
        for city, official, code in [
            ("EVRY COURCOURONNES", "Évry-Courcouronnes", "91"),
            ("ajaccio", "Ajaccio", "2A"),
            ("BASTIA", "Bastia", "2B"),
            ("FORT DE FRANCE", "Fort-de-France", "972"),
        ]:
            with self.subTest(city=city):
                self.assertEqual(self.lookup(city, [{"nom": official, "codeDepartement": code}]), code)

    def test_homonyms_and_partial_matches_are_not_guessed(self):
        cases = [
            ("Saint-Sauveur", [
                {"nom": "Saint-Sauveur", "codeDepartement": "31"},
                {"nom": "Saint-Sauveur", "codeDepartement": "60"},
            ]),
            ("Saint", [{"nom": "Saint-Denis", "codeDepartement": "93"}]),
            ("Inconnue", []),
            ("Paris", {"error": "bad payload"}),
        ]
        for city, communes in cases:
            with self.subTest(city=city):
                self.assertEqual(self.lookup(city, communes), "")

    def test_explicit_department_suffix_does_not_pollute_unqualified_cache(self):
        communes = [
            {"nom": "Saint-Sauveur", "codeDepartement": "31"},
            {"nom": "Saint-Sauveur", "codeDepartement": "60"},
        ]
        self.assertEqual(self.lookup("Saint-Sauveur (60)", communes), "60")
        self.assertEqual(self.lookup("Saint-Sauveur", communes), "")

    def test_foreign_or_invalid_city_does_not_call_french_api(self):
        with patch.object(gestion_app.requests, "get") as get:
            for city, country in [("Paris", "États-Unis"), ("", "France"), ("M", "France"), ("M" * 121, "France")]:
                result = self.client.get("/admin/ssiap/birth-department", query_string={"city": city, "country": country})
                self.assertEqual(result.get_json()["department"], "")
        get.assert_not_called()

    def test_lookup_requires_admin_authentication(self):
        with patch.object(gestion_app.requests, "get") as get:
            response = gestion_app.app.test_client().get(
                "/admin/ssiap/birth-department?city=Maubeuge", headers={"Accept": "application/json"},
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login?", response.headers["Location"])
        get.assert_not_called()

    def test_temporary_api_failure_allows_retry(self):
        with patch.object(gestion_app.requests, "get", side_effect=gestion_app.requests.Timeout):
            response = self.client.get("/admin/ssiap/birth-department?city=Maubeuge")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["department"], "")
        self.assertEqual(self.lookup("Maubeuge", [{"nom": "Maubeuge", "codeDepartement": "59"}]), "59")

    def save_diploma(self, department="", city="Maubeuge", country="France", lookup="59"):
        trainee = {"id": "T1", "first_name": "Jean", "last_name": "Dupont", "birth_city": "Paris", "birth_department": "75"}
        data = {"sessions": [{"id": "S1", "training_type": "SSIAP 1", "trainees": [trainee]}]}
        with patch.object(gestion_app, "load_data", return_value=data), \
                patch.object(gestion_app, "save_data") as save, \
                patch.object(gestion_app, "_lookup_birth_department_code", return_value=lookup) as find:
            response = self.client.post("/admin/sessions/S1/trainees/T1/ssiap-diploma-info", data={
                "first_name": "Jean", "last_name": "Dupont", "civility": "Monsieur",
                "birth_date": "1990-01-01", "exam_date": "2026-10-28",
                "birth_city": city, "birth_country": country, "birth_department": department,
            })
        self.assertEqual(response.status_code, 302)
        save.assert_called_once_with(data)
        self.assertEqual(trainee["birth_department"], "75")
        self.assertEqual(trainee["birth_city"], "Paris")
        return trainee, find

    def test_save_resolves_missing_department_even_before_browser_lookup_finishes(self):
        trainee, find = self.save_diploma()
        self.assertEqual(trainee["ssiap_diploma_birth_department"], "59")
        find.assert_called_once_with("MAUBEUGE")
        self.assertEqual(trainee["ssiap_diploma_birth_city"], "MAUBEUGE")
        self.assertEqual(gestion_app._ssiap_birth_place_label(trainee), "MAUBEUGE (59)")

    def test_manual_department_is_preserved(self):
        trainee, find = self.save_diploma(department="60", city="Saint-Sauveur")
        self.assertEqual(trainee["ssiap_diploma_birth_department"], "60")
        find.assert_not_called()

    def test_foreign_birth_does_not_inherit_original_french_department(self):
        trainee, find = self.save_diploma(city="Bruxelles", country="Belgique")
        self.assertEqual(trainee["ssiap_diploma_birth_department"], "")
        self.assertEqual(gestion_app._ssiap_birth_place_label(trainee), "BRUXELLES")
        find.assert_not_called()

    def test_ambiguous_birth_does_not_inherit_previous_city_department(self):
        trainee, _ = self.save_diploma(city="Saint-Sauveur", lookup="")
        self.assertEqual(trainee["ssiap_diploma_birth_department"], "")
        with patch.object(gestion_app, "_lookup_birth_department_code", return_value=""):
            self.assertEqual(gestion_app._ssiap_birth_place_label(trainee), "SAINT-SAUVEUR")


if __name__ == "__main__":
    unittest.main()
