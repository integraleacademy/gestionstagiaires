from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "admin_sessions.html"
BASE = ROOT / "templates" / "base.html"


class AdminSessionsHomepageTestMessageTests(unittest.TestCase):
    def test_message_is_rendered_in_homepage_header_before_actions(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        header_start = html.index('<div class="page-head">')
        actions_start = html.index('<div class="admin-actions"', header_start)
        message_start = html.index('ceci est un test', header_start)

        self.assertLess(header_start, message_start)
        self.assertLess(message_start, actions_start)
        self.assertIn('class="muted homepage-test-message"', html[header_start:actions_start])

    def test_message_is_limited_to_admin_sessions_homepage(self):
        homepage = TEMPLATE.read_text(encoding="utf-8")
        base = BASE.read_text(encoding="utf-8")

        self.assertEqual(homepage.count('ceci est un test'), 1)
        self.assertNotIn('ceci est un test', base)


if __name__ == "__main__":
    unittest.main()
