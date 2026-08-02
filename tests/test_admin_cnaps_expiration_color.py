import unittest
from pathlib import Path


class AdminCnapsExpirationColorTests(unittest.TestCase):
    def test_trainee_pages_compare_ap_sh_expiration_to_training_start(self):
        for template_name in ("admin_trainee.html", "admin_trainees.html"):
            with self.subTest(template=template_name):
                template = Path("templates", template_name).read_text(encoding="utf-8")
                self.assertIn('const cardProTrainingStartDate = {{ (session.date_start or "")|tojson }};', template)
                self.assertIn('status === "AP SH ACTIF"', template)
                self.assertIn("expiration < trainingStart", template)
                self.assertIn('? "is-inactive" : cardProActivityColorClass', template)


if __name__ == "__main__":
    unittest.main()
