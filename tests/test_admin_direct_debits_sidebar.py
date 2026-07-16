import unittest

import app as gestion_app


class AdminDirectDebitsSidebarTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        gestion_app.load_data = lambda: {"sessions": [], "partners": []}
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data

    def test_direct_debits_page_uses_admin_sidebar_layout(self):
        response = self.client.get("/admin/billing/direct-debits")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('class="partner-sidebar admin-sidebar"', html)
        self.assertIn("Suivi des prélèvements", html)
        self.assertIn('class="container main-content"', html)
        self.assertIn('href="/admin/sessions/facturation"', html)
