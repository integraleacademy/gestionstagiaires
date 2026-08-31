import unittest

import app as gestion_app


class AdminMailsCatalogTest(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def test_catalog_only_exposes_previews_built_by_real_email_builders(self):
        response = self.client.get("/admin/outils/mails")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Inscriptions &amp; accès", page)
        self.assertIn("Formation &amp; convocations", page)
        self.assertIn("VTC", page)
        self.assertIn("Hébergement A3P", page)
        self.assertIn("Convention à signer", page)
        self.assertIn("Annulation d’inscription", page)
        self.assertIn("13 modèles vérifiés", page)
        self.assertEqual(page.count("data-mail-preview="), 13)
        self.assertNotIn("Ceci est un aperçu", page)
        self.assertIn("Objet réel :", page)

    def test_catalog_displays_the_exact_subjects_from_email_builders(self):
        response = self.client.get("/admin/outils/mails")

        page = response.get_data(as_text=True)
        expected_subject, _ = gestion_app.build_vtc_practice_convocation_email("Camille", "2026-10-05")
        self.assertIn(expected_subject, page)
        expected_subject, _, _ = gestion_app._build_yousign_signature_link_email(
            {"training_type": "A3P", "date_start": "2026-09-21", "date_end": "2026-11-20"},
            {"first_name": "Camille"},
            "https://gestionstagiaires-r5no.onrender.com/exemple",
        )
        self.assertIn(expected_subject, page)

    def test_preview_buttons_use_full_card_width(self):
        response = self.client.get("/admin/outils/mails")

        page = response.get_data(as_text=True)
        self.assertIn(".mail-open{box-sizing:border-box;width:100%;max-width:100%", page)


if __name__ == "__main__":
    unittest.main()
