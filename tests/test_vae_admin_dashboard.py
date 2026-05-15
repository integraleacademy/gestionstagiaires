import unittest

import app as gestion_app


class VaeAdminDashboardTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.data = {
            "sessions": [
                {
                    "id": "S-VAE-DASH",
                    "name": "Session VAE dashboard",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "id": "T-L1",
                            "last_name": "ALPHA",
                            "first_name": "Alice",
                            "vae_status": "livret_1_todo",
                            "public_has_logged_in": False,
                            "documents": [],
                        },
                        {
                            "id": "T-L1-ANALYSIS",
                            "last_name": "BRAVO",
                            "first_name": "Bob",
                            "vae_status": "livret_1_analysis",
                            "public_has_logged_in": True,
                            "documents": [],
                        },
                    ],
                }
            ],
            "notifications_admin": [],
        }
        gestion_app.load_data = lambda: self.data
        gestion_app.save_data = lambda _payload: None
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data

    def test_vae_dashboard_filters_have_runtime_dependencies(self):
        response = self.client.get("/admin/sessions/S-VAE-DASH/trainees")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('class="vae-admin-dashboard"', html)
        self.assertIn('data-vae-dashboard-filter="status:livret_1_todo"', html)
        self.assertIn('data-vae-dashboard-filter="no_login"', html)
        self.assertIn('data-public-has-logged-in="0"', html)
        self.assertIn('data-public-has-logged-in="1"', html)
        self.assertIn("function getVtcStatusValues(tr)", html)
        self.assertIn('const { theoryStatus, practiceStatus } = getVtcStatusValues(tr);', html)
        self.assertIn('activeVaeDashboardFilter = filter === activeVaeDashboardFilter ? "" : filter;', html)
        self.assertIn('activeVaeDashboardFilter === "no_login" && !hasLoggedIn', html)


if __name__ == "__main__":
    unittest.main()
