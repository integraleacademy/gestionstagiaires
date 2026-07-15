import unittest

import app as gestion_app


class CnapsPublicAnnuaireTests(unittest.TestCase):
    def test_extracts_all_annuaire_rows_for_same_nub(self):
        payload = {
            "resultats": [
                {
                    "nom": "LARDJANE",
                    "prenom": "Zinedine",
                    "nub": "1000731",
                    "activite": "Autorisation préalable - Surveillance humaine ou gardiennage",
                    "dateValiditeTitre": "07/10/2026",
                    "validiteTitre": "ACTIF",
                },
                {
                    "nom": "LARDJANE",
                    "prenom": "Zinedine",
                    "nub": "1000731",
                    "activite": "Carte professionnelle - Surveillance humaine ou gardiennage",
                    "dateValiditeTitre": "30/06/2031",
                    "validiteTitre": "ACTIF",
                },
            ]
        }

        rows = gestion_app._extract_cnaps_public_annuaire_results(payload)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["activite"], "Autorisation préalable - Surveillance humaine ou gardiennage")
        self.assertEqual(rows[1]["activite"], "Carte professionnelle - Surveillance humaine ou gardiennage")
        self.assertTrue(all(row["validite_titre"] == "ACTIF" for row in rows))

    def test_fetch_requests_enough_rows_to_include_all_titles(self):
        original_endpoint = gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT
        original_post = gestion_app.requests.post
        captured = {}

        class DummyResponse:
            status_code = 200

            def json(self):
                return {
                    "resultats": [
                        {
                            "activite": "Autorisation préalable - Surveillance humaine ou gardiennage",
                            "validiteTitre": "ACTIF",
                        },
                        {
                            "activite": "Carte professionnelle - Surveillance humaine ou gardiennage",
                            "validiteTitre": "ACTIF",
                        },
                    ]
                }

        def fake_post(url, json, headers, timeout):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            captured["timeout"] = timeout
            return DummyResponse()

        gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT = "https://cnaps.example/annuaire"
        gestion_app.requests.post = fake_post
        try:
            result = gestion_app.fetch_cnaps_public_annuaire("lardjane", "1000731")
        finally:
            gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT = original_endpoint
            gestion_app.requests.post = original_post

        self.assertEqual(captured["json"]["nom"], "LARDJANE")
        self.assertEqual(captured["json"]["nub"], "1000731")
        self.assertEqual(captured["json"]["size"], 100)
        self.assertEqual(captured["json"]["limit"], 100)
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][1]["activite"], "Carte professionnelle - Surveillance humaine ou gardiennage")


if __name__ == "__main__":
    unittest.main()
