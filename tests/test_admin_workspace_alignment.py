import re
import unittest
from pathlib import Path


class AdminWorkspaceAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = Path("static/style.css").read_text(encoding="utf-8")

    def test_admin_header_and_content_share_centered_workspace(self):
        self.assertIn("--admin-workspace-max:1680px", self.css)
        self.assertRegex(
            self.css,
            re.compile(
                r"body\.admin-sidebar-active \.topbar-inner\s*\{[^}]*"
                r"max-width:var\(--admin-workspace-max\)[^}]*"
                r"margin-inline:auto",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.css,
            re.compile(
                r"body\.admin-sidebar-active \.main-content > \.container\s*\{[^}]*"
                r"max-width:var\(--admin-workspace-max\)[^}]*"
                r"margin-inline:auto",
                re.DOTALL,
            ),
        )

    def test_admin_command_search_can_use_available_header_space(self):
        search_rule = re.search(
            r"body\.admin-sidebar-active \.topbar-inner \.command-search\s*\{(?P<rules>[^}]*)\}",
            self.css,
        )
        self.assertIsNotNone(search_rule)
        self.assertIn("flex:1 1 520px", search_rule["rules"])
        self.assertIn("max-width:760px", search_rule["rules"])


if __name__ == "__main__":
    unittest.main()
