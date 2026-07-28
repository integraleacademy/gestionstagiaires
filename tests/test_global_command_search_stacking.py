import re
import unittest
from pathlib import Path


class GlobalCommandSearchStackingTests(unittest.TestCase):
    def test_topbar_stays_above_sticky_trainee_columns(self):
        css = Path("static/style.css").read_text(encoding="utf-8")

        topbar = re.search(r"\.topbar\s*\{(?P<rules>[^}]*)\}", css)
        sticky_header = re.search(
            r"#traineesTable thead th:nth-child\(1\),\s*"
            r"#traineesTable thead th:nth-child\(2\)\s*\{(?P<rules>[^}]*)\}",
            css,
        )

        self.assertIsNotNone(topbar)
        self.assertIsNotNone(sticky_header)
        topbar_z_index = int(re.search(r"z-index:\s*(\d+)", topbar["rules"]).group(1))
        sticky_z_index = int(
            re.search(r"z-index:\s*(\d+)", sticky_header["rules"]).group(1)
        )

        self.assertGreater(topbar_z_index, sticky_z_index)


if __name__ == "__main__":
    unittest.main()
