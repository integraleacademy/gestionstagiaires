import unittest

import app as gestion_app


class AdminMailsCatalogTest(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def test_catalog_groups_all_mail_families_and_exposes_previews(self):
        response = self.client.get("/admin/outils/mails")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Inscriptions &amp; accès", page)
        self.assertIn("Formation &amp; convocations", page)
        self.assertIn("Paiements &amp; prélèvements", page)
        self.assertIn("Mail hébergement A3P", page)
        self.assertIn("Signature mandat SEPA", page)
        self.assertIn("36 modèles", page)
        self.assertEqual(page.count("data-mail-preview="), 36)

    def test_preview_buttons_use_full_card_width(self):
        response = self.client.get("/admin/outils/mails")

        page = response.get_data(as_text=True)
        self.assertIn(".mail-open{box-sizing:border-box;width:100%;max-width:100%", page)


if __name__ == "__main__":
    unittest.main()
