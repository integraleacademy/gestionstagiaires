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
