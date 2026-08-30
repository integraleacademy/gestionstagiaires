import unittest
from pathlib import Path


class WedofGlobalNotificationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.admin_sidebar = (root / "templates" / "admin_sidebar.html").read_text(encoding="utf-8")
        cls.base = (root / "templates" / "base.html").read_text(encoding="utf-8")
        cls.sessions = (root / "templates" / "admin_sessions.html").read_text(encoding="utf-8")

    def test_cpf_navigation_items_never_receive_a_wedof_badge(self):
        self.assertIn('admin_cpf_item = {"label":"CPF"', self.admin_sidebar)
        self.assertIn('"badge":""', self.admin_sidebar)
        self.assertNotIn('"badge":wedof_new_requests_count', self.admin_sidebar)

        self.assertIn('sidebar_cpf_item = {"label":"CPF"', self.base)
        self.assertNotIn('"badge":wedof_new_requests_count', self.base)

    def test_sessions_dashboard_has_plain_cpf_navigation_without_alert_count(self):
        self.assertNotIn("cpf-badge-count", self.sessions)
        self.assertNotIn("is-has-request", self.sessions)
        self.assertNotIn("wedof_new_requests_count", self.sessions)


if __name__ == "__main__":
    unittest.main()
