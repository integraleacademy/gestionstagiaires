import datetime
import re
import unittest
from unittest.mock import patch

import app as gestion_app


class AdminSessionsSsiapTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def test_ssiap_is_counted_in_dashboard_total_and_available_as_filter(self):
        current_year = datetime.date.today().year
        fake_data = {
            "sessions": [
                {
                    "id": "S-SSIAP",
                    "name": f"SSIAP 1 {current_year}",
                    "training_type": "SSIAP 1",
                    "date_start": f"{current_year}-06-01",
                    "date_end": f"{current_year}-06-15",
                    "trainees": [
                        {"id": "T-SSIAP-1", "created_at": f"{current_year}-05-10"},
                        {"id": "T-SSIAP-2", "created_at": f"{current_year}-05-11"},
                    ],
                },
                {
                    "id": "S-APS",
                    "name": f"APS {current_year}",
                    "training_type": "APS",
                    "date_start": f"{current_year}-03-01",
                    "date_end": f"{current_year}-03-15",
                    "trainees": [
                        {"id": "T-APS-1", "created_at": f"{current_year}-02-10"},
                    ],
                },
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(
            gestion_app, "_load_wedof_webhooks", return_value=[]
        ):
            response = self.client.get("/admin/sessions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertRegex(
            html,
            re.compile(
                r'dashboard-card--ssiap[^>]*data-dashboard-filter="ssiap".*?'
                r'dashboard-card__label">SSIAP</div>\s*'
                r'<div class="dashboard-card__count">2</div>',
                re.DOTALL,
            ),
        )
        self.assertIn(
            'class="filter-btn filter-btn--ssiap" data-filter-group="training" '
            'data-filter-value="ssiap">SSIAP</button>',
            html,
        )
        self.assertIn("training-ssiap", html)
        self.assertIn(
            '<button class="training-choice" data-training="SSIAP">SSIAP</button>',
            html,
        )
        self.assertIn('if(v.startsWith("SSIAP")) return "SSIAP";', html)
        self.assertRegex(
            html,
            re.compile(
                r'dashboard-total-card__label">TOTAL STAGIAIRES</div>\s*'
                r'<div class="dashboard-total-card__count">3</div>'
            ),
        )


if __name__ == "__main__":
    unittest.main()
