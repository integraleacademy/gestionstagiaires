from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "admin_sessions.html"
BASE = ROOT / "templates" / "base.html"


class AdminSessionsHomepageTestMessageTests(unittest.TestCase):
    def test_temporary_message_and_marker_are_removed_everywhere(self):
        homepage = TEMPLATE.read_text(encoding="utf-8")
        base = BASE.read_text(encoding="utf-8")

        self.assertNotIn("ceci est un test", homepage)
        self.assertNotIn("homepage-test-message", homepage)
        self.assertNotIn("ceci est un test", base)
        self.assertNotIn("homepage-test-message", base)

    def test_homepage_header_structure_is_preserved(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        header_start = html.index('<div class="page-head">')
        title_start = html.index("<h1", header_start)
        subtitle_start = html.index(
            "Pilotage des formations, stagiaires et outils administratifs.",
            title_start,
        )
        actions_start = html.index('<div class="admin-actions"', subtitle_start)

        self.assertLess(header_start, title_start)
        self.assertLess(title_start, subtitle_start)
        self.assertLess(subtitle_start, actions_start)
        self.assertIn(">Sessions</h1>", html[title_start:subtitle_start])


if __name__ == "__main__":
    unittest.main()
