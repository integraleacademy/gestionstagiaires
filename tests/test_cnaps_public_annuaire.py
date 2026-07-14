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


if __name__ == "__main__":
    unittest.main()
