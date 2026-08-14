import unittest

import app as gestion_app


class AfcDocumentsReminderTemplatesTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data

    def test_afc_page_exposes_default_documents_reminder_templates(self):
        gestion_app.load_data = lambda: {"afc": {"candidates": []}}
        gestion_app.save_data = lambda _data: None

        response = self.client.get("/admin/afc")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Relance documents", page)
        self.assertIn("tmplDocumentsReminderEmail", page)
        self.assertIn("tmplDocumentsReminderSms", page)
        self.assertIn("votre dossier AFC est incomplet", page)

    def test_save_endpoint_persists_documents_reminder_templates(self):
        data = {"afc": {"candidates": []}}
        saved = {}
        gestion_app.load_data = lambda: data
        gestion_app.save_data = lambda updated: saved.update(updated)

        response = self.client.post(
            "/api/admin/afc/mail-templates",
            json={
                "documents_reminder_subject": "Objet personnalisé",
                "documents_reminder_email": "Mail pour {{prenom}}",
                "documents_reminder_sms": "SMS pour {{prenom}}",
            },
        )

        self.assertEqual(response.status_code, 200)
        templates = saved["afc"]["mail_templates"]
        self.assertEqual(templates["documents_reminder_subject"], "Objet personnalisé")
        self.assertEqual(templates["documents_reminder_email"], "Mail pour {{prenom}}")
        self.assertEqual(templates["documents_reminder_sms"], "SMS pour {{prenom}}")


if __name__ == "__main__":
    unittest.main()
