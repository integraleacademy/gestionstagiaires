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
        today = datetime.date.today()
        current_year = today.year
        date_start = today + datetime.timedelta(days=7)
        date_end = today + datetime.timedelta(days=21)
        fake_data = {
            "sessions": [
                {
                    "id": "S-SSIAP",
                    "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
                    "name": f"SSIAP 1 {current_year}",
                    "training_type": "SSIAP 1",
                    "date_start": date_start.isoformat(),
                    "date_end": date_end.isoformat(),
                    "trainees": [
                        {"id": "T-SSIAP-1", "created_at": today.isoformat()},
                        {"id": "T-SSIAP-2", "created_at": today.isoformat()},
                    ],
                },
                {
                    "id": "S-APS",
                    "partner_id": gestion_app.INTEGRALE_PARTNER_ID,
                    "name": f"APS {current_year}",
                    "training_type": "APS",
                    "date_start": date_start.isoformat(),
                    "date_end": date_end.isoformat(),
                    "trainees": [
                        {"id": "T-APS-1", "created_at": today.isoformat()},
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

    def test_dirigeant_session_modal_shows_dates_in_expected_order(self):
        fake_data = {"sessions": []}

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(
            gestion_app, "_load_wedof_webhooks", return_value=[]
        ):
            response = self.client.get("/admin/sessions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        create_modal = html[
            html.index('<div class="modal-backdrop" id="createSessionModal"') : html.index(
                '<!-- MODALE CREATION STAGIAIRE'
            )
        ]
        expected_order = [
            'id="dateStartField"',
            'id="dateEndField"',
            'id="dirigeantInPersonStartField"',
            'id="dirigeantInPersonEndField"',
            'id="dirigeantRemoteStartField"',
            'id="dirigeantRemoteEndField"',
        ]
        positions = [create_modal.index(marker) for marker in expected_order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(
            'const ids = ["DirigeantInPersonStartField", "DirigeantInPersonEndField", '
            '"DirigeantRemoteStartField", "DirigeantRemoteEndField"];',
            html,
        )
        self.assertIn('setFieldVisible("dateEndField", true);', html)
        self.assertIn('setFieldVisible("editDateEndField", true);', html)
        self.assertIn('if(dateEndField) dateEndField.style.display = "";', html)

    def test_ssiap_summary_displays_red_ssiap_1_badge(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-SSIAP",
                    "name": "SSIAP 1 OCTOBRE 2026",
                    "training_type": "SSIAP 1",
                    "date_start": "2026-10-12",
                    "date_end": "2026-10-27",
                    "trainees": [
                        {
                            "id": "T-SSIAP-1",
                            "last_name": "VAILLANT",
                            "first_name": "Clement",
                            "created_at": "2026-06-08",
                        }
                    ],
                }
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get(
                "/admin/sessions/S-SSIAP/stagiaires/T-SSIAP-1/summary"
            )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(
            'class="training-badge training-badge--red">SSIAP 1</div>', html
        )
        self.assertNotIn(
            'class="training-badge training-badge--gray">FORMATION</div>', html
        )


if __name__ == "__main__":
    unittest.main()
