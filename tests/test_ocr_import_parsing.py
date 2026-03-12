import io
import unittest

import app as gestion_app


class OcrTraineeFieldExtractionTests(unittest.TestCase):
    def test_extracts_fields_from_profile_like_text(self):
        ocr_text = """
Nikita Zamolotchikov
INFORMATIONS BIOGRAPHIQUES
Civilité
Monsieur
Date de naissance
21/10/1999
Lieu de naissance
RUSSIE
COORDOONNÉES
Adresse postale
8 PL Cornut Gentille 06400 CANNES
Courriel
zamolotchikov@gmail.com
Téléphone mobile
0676667188
NIVEAU DE FORMATION
Niveau d'études
CAP, BEP... (NIVEAU 3)
""".strip()

        fields = gestion_app._extract_trainee_fields_from_ocr_text(ocr_text)

        self.assertEqual(fields["first_name"], "Nikita")
        self.assertEqual(fields["last_name"], "ZAMOLOTCHIKOV")
        self.assertEqual(fields["birth_date"], "1999-10-21")
        self.assertEqual(fields["birth_city"], "RUSSIE")
        self.assertEqual(fields["email"], "zamolotchikov@gmail.com")
        self.assertEqual(fields["phone"], "+33676667188")
        self.assertEqual(fields["zip_code"], "06400")
        self.assertEqual(fields["city"], "Cannes")

    def test_does_not_use_section_labels_as_name(self):
        ocr_text = """
INFORMATIONS BIOGRAPHIQUES
NIVEAU DE FORMATION
Niveau d'études
CAP BEP
""".strip()

        fields = gestion_app._extract_trainee_fields_from_ocr_text(ocr_text)

        self.assertEqual(fields["first_name"], "")
        self.assertEqual(fields["last_name"], "")


if __name__ == "__main__":
    unittest.main()

class OcrAfcImportParsingTests(unittest.TestCase):
    def test_extracts_candidates_from_afc_like_listing(self):
        ocr_text = """
Candidats
5988355G - 032
BARRY Tidiane
07 44 16 67 86
BARRYTIDIANE2025@GMAIL.COM
Var (83)
Détails de la Candidature
5464627M - 032
BENDJAMA Ilies
06 01 08 57 99
ILIES83310@GMAIL.COM
Var (83)
""".strip()

        candidates = gestion_app._extract_afc_candidates_from_ocr_text(ocr_text)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["identifiant_ft"], "5988355G - 032")
        self.assertEqual(candidates[0]["nom"], "BARRY")
        self.assertEqual(candidates[0]["prenom"], "Tidiane")
        self.assertEqual(candidates[0]["email"], "BARRYTIDIANE2025@GMAIL.COM")
        self.assertEqual(candidates[0]["telephone"], "07 44 16 67 86")


class AfcImageImportApiTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_ocr_extract = gestion_app._ocr_extract_text_from_image
        self.original_cnaps_lookup = gestion_app.fetch_cnaps_status_by_name

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app._ocr_extract_text_from_image = self.original_ocr_extract
        gestion_app.fetch_cnaps_status_by_name = self.original_cnaps_lookup

    def test_import_skips_existing_candidate_by_identifiant(self):
        data = {
            "afc": {
                "candidates": [
                    {
                        "id": "AFC-EXISTING",
                        "identifiant_ft": "5988355G - 032",
                        "nom": "BARRY",
                        "prenom": "Tidiane",
                        "email": "",
                        "telephone": "",
                    }
                ]
            }
        }
        saved = {"count": 0}
        gestion_app.load_data = lambda: data
        gestion_app.save_data = lambda payload: saved.__setitem__("count", saved["count"] + 1)
        gestion_app.fetch_cnaps_status_by_name = lambda *_: "INCONNU"
        gestion_app._ocr_extract_text_from_image = lambda *_: (
            "5988355G - 032\nBARRY Tidiane\n07 44 16 67 86\nbarry@example.com\n"
            "5464627M - 032\nBENDJAMA Ilies\n06 01 08 57 99\nilies@example.com",
            "",
        )

        response = self.client.post(
            "/api/admin/afc/import-from-image",
            data={"file": (io.BytesIO(b"fake-image"), "import.png")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["imported_count"], 1)
        self.assertEqual(payload["skipped_count"], 1)
        self.assertEqual(saved["count"], 1)
        self.assertEqual(len(data["afc"]["candidates"]), 2)


