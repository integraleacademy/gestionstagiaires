import unittest

import app as gestion_app


class AdminDirectDebitsSidebarTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_load_wedof_webhooks = gestion_app._load_wedof_webhooks
        gestion_app.load_data = lambda: {"sessions": [], "partners": []}
        gestion_app._load_wedof_webhooks = lambda: [
            {"id": "cpf-new", "processed": False},
            {"id": "cpf-done", "processed": True},
        ]
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app._load_wedof_webhooks = self.original_load_wedof_webhooks

    def test_direct_debits_page_uses_admin_sidebar_layout(self):
        response = self.client.get("/admin/billing/direct-debits")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('class="partner-sidebar admin-sidebar"', html)
        self.assertIn("Suivi des prélèvements", html)
        self.assertIn('class="container main-content"', html)
        self.assertIn('href="/admin/sessions/facturation"', html)
        self.assertIn('aria-label="CPF"', html)
        self.assertIn('>1</span>', html)
        self.assertIn("partner-sidebar__collapse--collapsed", html)
        self.assertIn('aria-label="Déployer la barre"', html)

    def test_rejected_installment_aliases_are_used_by_dashboard(self):
        response = self.client.get("/admin/billing/direct-debits")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("'returned','refunded'", html)
        self.assertIn("failureReason||it.status_reason||it.rejectReason", html)
        self.assertIn("it.date||it.due_date", html)
        self.assertIn("Rejet traité", html)
        self.assertIn("Nouveau prélèvement suite à rejet", html)
        self.assertIn("b-treated", html)
        self.assertIn("b-retry", html)
        self.assertIn("d.status==='rejected'", html)
        self.assertNotIn("d.status==='rejected'||!!d.failureReason", html)
        # An installment rejection must take precedence over a stale paid
        # status stored on the parent invoice.
        rejected_check = html.index("if(rejected)return")
        paid_check = html.index("if(['paid','settled'", rejected_check)
        self.assertLess(rejected_check, paid_check)
