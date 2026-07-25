from pathlib import Path
import unittest


class AdminTraineeQuickNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = Path("templates/admin_trainee.html").read_text(encoding="utf-8")

    def test_header_links_to_main_dossier_sections(self):
        for section_id in (
            "automationHub",
            "documentsSection",
            "miscDocumentsSection",
            "certificatesSection",
            "phoneRelanceSection",
            "conventionFinancementSection",
        ):
            with self.subTest(section_id=section_id):
                self.assertIn(f'data-open-section="{section_id}"', self.template)

    def test_every_quick_navigation_target_exists(self):
        targets = (
            "automationHub",
            "documentsSection",
            "miscDocumentsSection",
            "certificatesSection",
            "phoneRelanceSection",
            "conventionFinancementSection",
        )
        for section_id in targets:
            with self.subTest(section_id=section_id):
                self.assertIn(f'id="{section_id}"', self.template)


if __name__ == "__main__":
    unittest.main()
