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

    def test_extracts_fields_from_admin_profile_screenshot_like_text(self):
        ocr_text = """
Apprenant
VIDAUBAN (83550)
Civilité
Madame
Nom de famille
INES
Prénom
Angelique
Deuxième prénom
Non renseigné
Email
angievoyage@gmail.com
Téléphone portable
0666842042
Adresse
71 Traverse De la chapelle 83550 VIDAUBAN
Nom de naissance
Non renseigné
Date de naissance
26/09/1992
Lieu de naissance
Beuvry (62)
""".strip()

        fields = gestion_app._extract_trainee_fields_from_ocr_text(ocr_text)

        self.assertEqual(fields["first_name"], "Angelique")
        self.assertEqual(fields["last_name"], "INES")
        self.assertEqual(fields["birth_date"], "1992-09-26")
        self.assertEqual(fields["birth_city"], "Beuvry (62)")
        self.assertEqual(fields["email"], "angievoyage@gmail.com")
        self.assertEqual(fields["phone"], "+33666842042")
        self.assertEqual(fields["address"], "71 Traverse De la chapelle 83550 VIDAUBAN")
        self.assertEqual(fields["zip_code"], "83550")
        self.assertEqual(fields["city"], "Vidauban")

    def test_does_not_confuse_nom_with_prenom_and_cleans_prefix_noise(self):
        ocr_text = """
Nom de famille
PRÉNOM
Prénom
• Ines
Date de naissance
Lieu de naissance
• 26/09/1992
Email
angievoyage@gmail.com
Téléphone portable
+33666842042
Adresse
fa 71 Traverse De la chapelle 83550 VIDAUBAN
""".strip()

        fields = gestion_app._extract_trainee_fields_from_ocr_text(ocr_text)

        self.assertNotEqual(fields["last_name"], "PRÉNOM")
        self.assertEqual(fields["first_name"], "Ines")
        self.assertEqual(fields["birth_date"], "1992-09-26")
        self.assertEqual(fields["birth_city"], "")
        self.assertEqual(fields["address"], "71 Traverse De la chapelle 83550 VIDAUBAN")

    def test_uses_next_prenom_candidate_when_first_equals_last_name(self):
        ocr_text = """
Nom de famille
INES
Prénom
INES
Angelique
Date de naissance
26/09/1992
Lieu de naissance
Beuvry (62)
""".strip()

        fields = gestion_app._extract_trainee_fields_from_ocr_text(ocr_text)

        self.assertEqual(fields["last_name"], "INES")
        self.assertEqual(fields["first_name"], "Angelique")
        self.assertEqual(fields["birth_city"], "Beuvry (62)")

    def test_handles_two_column_order_without_using_second_name_label(self):
        ocr_text = """
Nom de famille
Prénom
INES
Deuxième prénom
Angelique
Troisième prénom
Date de naissance
Lieu de naissance
26/09/1992
Beuvry (62)
""".strip()

        fields = gestion_app._extract_trainee_fields_from_ocr_text(ocr_text)

        self.assertEqual(fields["last_name"], "INES")
        self.assertEqual(fields["first_name"], "Angelique")
        self.assertEqual(fields["birth_date"], "1992-09-26")
        self.assertEqual(fields["birth_city"], "Beuvry (62)")

    def test_ignores_non_renseigne_noise_for_first_name_and_cleans_birth_city_prefix(self):
        ocr_text = """
Nom de famille
INES
Prénom
Da Non Renseigné
Angelique
Date de naissance
26/09/1992
Lieu de naissance
# Beuvry (62)
""".strip()

        fields = gestion_app._extract_trainee_fields_from_ocr_text(ocr_text)

        self.assertEqual(fields["last_name"], "INES")
        self.assertEqual(fields["first_name"], "Angelique")
        self.assertEqual(fields["birth_city"], "Beuvry (62)")


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


class CnapsPdfNameExtractionTests(unittest.TestCase):
    def test_extracts_name_from_cnaps_phrase_with_par_and_nee(self):
        cnaps_text = """
Vu la demande présentée le 27 mars 2026 par Franck PLET, né(e) le 16/02/1970 à Versailles
en vue d'obtenir une autorisation préalable d’entrée en formation.
""".strip()

        last_name, first_name = gestion_app._extract_name_from_cnaps_text(cnaps_text)

        self.assertEqual(last_name, "PLET")
        self.assertEqual(first_name, "FRANCK")

    def test_prefers_name_from_sentence_containing_numero(self):
        cnaps_text = """
Ce brouillon mentionne est délivrée à Ines Angelique, né(e) le 26/09/1992.
Article 1 : Une autorisation préalable comportant le numéro 2026-0024376-PRE-SH-1055859
est délivrée à Franck PLET, né(e) le 16/02/1970 à Versailles.
""".strip()

        last_name, first_name = gestion_app._extract_name_from_cnaps_text(cnaps_text)

        self.assertEqual(last_name, "PLET")
        self.assertEqual(first_name, "FRANCK")


class AfcEmailNormalizationTests(unittest.TestCase):
    def test_removes_leading_separator_in_local_part(self):
        candidate = gestion_app._extract_afc_candidates_from_ocr_text(
            "5988355G - 032\nCHABAUD David\n_chabauddavid313@gmail.com"
        )[0]

        self.assertEqual(candidate["email"], "chabauddavid313@gmail.com")

    def test_dedup_key_uses_normalized_email(self):
        dedup_key = gestion_app._afc_candidate_dedup_key({"email": "_test.user@gmail.com"})

        self.assertEqual(dedup_key, "email:test.user@gmail.com")


class CnapsImportPreApiMatchingTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_extract_pdf_text = gestion_app._extract_pdf_text
        self.original_build_haystacks = gestion_app._build_pdf_search_haystacks
        self.original_extract_pre = gestion_app._extract_pre_from_text
        self.original_extract_name = gestion_app._extract_name_from_cnaps_text

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app._extract_pdf_text = self.original_extract_pdf_text
        gestion_app._build_pdf_search_haystacks = self.original_build_haystacks
        gestion_app._extract_pre_from_text = self.original_extract_pre
        gestion_app._extract_name_from_cnaps_text = self.original_extract_name

    def test_does_not_override_explicit_extracted_name_with_text_fallback(self):
        data = {
            "sessions": [
                {
                    "id": "S1",
                    "archived": False,
                    "training_type": "VTC",
                    "date_start": "2026-03-07",
                    "date_end": "2026-05-04",
                    "trainees": [
                        {"id": "T1", "last_name": "INES", "first_name": "Angelique"},
                    ],
                }
            ],
            "cnaps_pending_imports": [],
        }
        gestion_app.load_data = lambda: data
        gestion_app._extract_pdf_text = lambda *_: "contenu pdf"
        gestion_app._build_pdf_search_haystacks = lambda *_: (" INES ANGELIQUE ", "")
        gestion_app._extract_pre_from_text = lambda *_: "2026-0024376-PRE-SH-1055859"
        gestion_app._extract_name_from_cnaps_text = lambda *_: ("PLET", "FRANCK")

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True

        response = self.client.post(
            "/api/cnaps/import-pre",
            data={"file": (io.BytesIO(b"%PDF-1.4 fake"), "agrement.pdf")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertFalse(payload["matches"][0]["match_found"])
        self.assertEqual(payload["matches"][0]["last_name"], "PLET")
        self.assertEqual(payload["matches"][0]["first_name"], "FRANCK")

    def test_matches_aps_enrolment_when_candidate_is_also_in_an_ineligible_formation(self):
        data = {
            "sessions": [
                {
                    "id": "VTC-1",
                    "training_type": "VTC",
                    "trainees": [{"id": "T-VTC", "last_name": "DOE", "first_name": "John"}],
                },
                {
                    "id": "APS-1",
                    "training_type": "APS",
                    "date_start": "2026-03-07",
                    "date_end": "2026-05-04",
                    "trainees": [{"id": "T-APS", "last_name": "DOE", "first_name": "John"}],
                },
            ],
            "cnaps_pending_imports": [],
        }
        gestion_app.load_data = lambda: data
        gestion_app._extract_pdf_text = lambda *_: "contenu pdf"
        gestion_app._build_pdf_search_haystacks = lambda *_: ("", "")
        gestion_app._extract_pre_from_text = lambda *_: "2026-0024376-PRE-SH-1055859"
        gestion_app._extract_name_from_cnaps_text = lambda *_: ("DOE", "JOHN")

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True

        response = self.client.post(
            "/api/cnaps/import-pre",
            data={"file": (io.BytesIO(b"%PDF-1.4 fake"), "agrement.pdf")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        match = response.get_json()["matches"][0]
        self.assertTrue(match["match_found"])
        self.assertEqual(match["session_id"], "APS-1")
        self.assertEqual(match["trainee_id"], "T-APS")


class CnapsPendingImportEligibilityTests(unittest.TestCase):
    def test_pending_import_waits_for_aps_or_a3p_and_is_consumed_once(self):
        pending = {
            "id": "CPN-1",
            "last_name": "DOE",
            "first_name": "JOHN",
            "pre_number": "2026-0024376-PRE-SH-1055859",
            "file_token": "uploads/cnaps_pending/doc.pdf",
        }
        data = {"cnaps_pending_imports": [pending]}
        trainee = {"id": "T1", "last_name": "DOE", "first_name": "John", "documents": []}

        applied = gestion_app._apply_pending_cnaps_imports_for_trainee(
            data, {"training_type": "VTC"}, trainee
        )
        self.assertEqual(applied, 0)
        self.assertEqual(data["cnaps_pending_imports"], [pending])

        applied = gestion_app._apply_pending_cnaps_imports_for_trainee(
            data, {"training_type": "APS"}, trainee
        )
        self.assertEqual(applied, 1)
        self.assertEqual(data["cnaps_pending_imports"], [])
        self.assertEqual(trainee["pre_number"], "2026-0024376-PRE-SH-1055859")


class AfcBulkNotifyApiTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_brevo_send_email = gestion_app.brevo_send_email

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app.brevo_send_email = self.original_brevo_send_email

    def test_notify_pending_skips_already_sent_and_updates_pending(self):
        data = {
            "afc": {
                "mail_templates": {
                    "retained": "Bonjour {{prenom}}",
                    "rejected": "Au revoir {{prenom}}",
                },
                "candidates": [
                    {
                        "id": "AFC-1",
                        "email": "sent@example.com",
                        "prenom": "Deja",
                        "decision": "RETENU",
                        "notification_status": "ENVOYEE",
                        "presence_afc_status": "A_CONVOQUER",
                    },
                    {
                        "id": "AFC-2",
                        "email": "pending@example.com",
                        "prenom": "Nouveau",
                        "decision": "RETENU",
                        "notification_status": "NON ENVOYEE",
                        "presence_afc_status": "A_CONVOQUER",
                    },
                ],
            }
        }
        saved = {"count": 0}
        sent = []
        gestion_app.load_data = lambda: data
        gestion_app.save_data = lambda payload: saved.__setitem__("count", saved["count"] + 1)
        gestion_app.brevo_send_email = lambda to_email, *_: sent.append(to_email) or True

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.post("/api/admin/afc/candidates/notify-pending")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["notified"], 1)
        self.assertEqual(payload["skipped"], 1)
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(sent, ["pending@example.com"])
        self.assertEqual(saved["count"], 1)
        self.assertEqual(data["afc"]["candidates"][1]["notification_status"], "ENVOYEE")
        self.assertTrue(data["afc"]["candidates"][1].get("notification_sent_at"))

    def test_notify_pending_counts_failures_without_saving(self):
        data = {
            "afc": {
                "mail_templates": {
                    "retained": "Bonjour {{prenom}}",
                    "rejected": "Au revoir {{prenom}}",
                },
                "candidates": [
                    {
                        "id": "AFC-1",
                        "email": "",
                        "prenom": "SansMail",
                        "decision": "NON RETENU",
                        "notification_status": "NON ENVOYEE",
                        "presence_afc_status": "A_CONVOQUER",
                    }
                ],
            }
        }
        saved = {"count": 0}
        gestion_app.load_data = lambda: data
        gestion_app.save_data = lambda payload: saved.__setitem__("count", saved["count"] + 1)
        gestion_app.brevo_send_email = lambda *_: True

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.post("/api/admin/afc/candidates/notify-pending")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["notified"], 0)
        self.assertEqual(payload["skipped"], 0)
        self.assertEqual(payload["failed"], 1)
        self.assertEqual(saved["count"], 0)
