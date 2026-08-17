import unittest
from pathlib import Path

import app as gestion_app


class AdminCnapsAcceptedCounterTests(unittest.TestCase):
    def test_server_stats_count_accepted_statuses_and_valid_professional_cards(self):
        stats = gestion_app.compute_stats(
            {
                "training_type": "A3P",
                "trainees": [
                    {"cnaps": "ACCEPTÉ"},
                    {"cnaps": "ACCEPTE"},
                    {"cnaps": "CARTE PROFESSIONNELLE OK"},
                    {"cnaps": "TRANSMIS"},
                ],
            }
        )

        self.assertEqual(stats["cnaps_accepted_count"], 3)

    def test_browser_refresh_keeps_header_counter_aligned_with_visible_rows(self):
        template = Path("templates/admin_trainees.html").read_text(encoding="utf-8")

        self.assertIn("data-cnaps-accepted-count", template)
        self.assertIn("function isCnapsAcceptedForCounter", template)
        self.assertIn("function refreshCnapsAcceptedCount", template)
        self.assertGreaterEqual(template.count("refreshCnapsAcceptedCount();"), 2)


if __name__ == "__main__":
    unittest.main()
