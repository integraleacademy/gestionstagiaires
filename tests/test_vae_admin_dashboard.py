import datetime
import unittest

import app as gestion_app


class VaeAdminDashboardTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        recent_created_at = (now - datetime.timedelta(hours=12)).isoformat()
        extended_recent_created_at = (now - datetime.timedelta(hours=60)).isoformat()
        old_created_at = (now - datetime.timedelta(hours=80)).isoformat()
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
                            "created_at": old_created_at,
                            "documents": [],
                            "scotia_thread_comments": [
                                {
                                    "id": "C-SCOTIA-1",
                                    "content": "Merci de compléter ce point",
                                    "author_label": "Scotia",
                                    "author_party": "scotia",
                                    "created_at": "2026-06-01T07:25:00Z",
                                }
                            ],
                        },
                        {
                            "id": "T-L1-ANALYSIS",
                            "last_name": "BRAVO",
                            "first_name": "Bob",
                            "vae_status": "livret_1_analysis",
                            "public_has_logged_in": True,
                            "created_at": recent_created_at,
                            "documents": [],
                        },
                        {
                            "id": "T-RECENT-72H",
                            "last_name": "CHARLIE",
                            "first_name": "Chloé",
                            "vae_status": "livret_1_todo",
                            "public_has_logged_in": True,
                            "created_at": extended_recent_created_at,
                            "documents": [],
                        },
                        {
                            "id": "T-L2-FINANCING",
                            "last_name": "DELTA",
                            "first_name": "Diane",
                            "vae_status": "financement_l2_validated",
                            "public_has_logged_in": True,
                            "created_at": old_created_at,
                            "documents": [],
                        },
                        {
                            "id": "T-SCOTIA-TODO",
                            "last_name": "ECHO",
                            "first_name": "Emma",
                            "vae_status": "livret_1_analysis",
                            "public_has_logged_in": True,
                            "created_at": old_created_at,
                            "vae_action_dates": {"livret_1_transmitted_scotia": "01/06/2026"},
                            "scotia_status": "",
                            "documents": [],
                        },
                        {
                            "id": "T-SCOTIA-CONTROL",
                            "last_name": "FOXTROT",
                            "first_name": "Farah",
                            "vae_status": "livret_1_analysis",
                            "public_has_logged_in": True,
                            "created_at": old_created_at,
                            "vae_action_dates": {"livret_1_transmitted_scotia": "01/06/2026"},
                            "scotia_status": "complement_requested",
                            "scotia_added_documents": [{"date": "01/06/2026", "files": ["token-added"]}],
                            "documents": [],
                        },
                        {
                            "id": "T-SCOTIA-WAITING",
                            "last_name": "GOLF",
                            "first_name": "Gaëlle",
                            "vae_status": "livret_1_analysis",
                            "public_has_logged_in": True,
                            "created_at": old_created_at,
                            "vae_action_dates": {"livret_1_transmitted_scotia": "01/06/2026"},
                            "scotia_status": "complement_requested",
                            "scotia_complementary_documents_review_status": "complement_documents_new_expected",
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
        self.assertIn('data-vae-dashboard-filter="new_vae_request_72h"', html)
        self.assertIn('data-vae-dashboard-count="new_vae_request_72h"', html)
        self.assertIn('data-vae-dashboard-filter="status:livret_2_validated"', html)
        self.assertIn('data-vae-dashboard-count="status:livret_2_validated">1</strong>', html)
        self.assertNotIn('data-vae-dashboard-count="l2_validated"', html)
        self.assertIn("72 dernières heures", html)
        self.assertNotIn("48 dernières heures", html)
        self.assertIn('data-public-has-logged-in="0"', html)
        self.assertIn('data-public-has-logged-in="1"', html)
        self.assertIn('data-vae-new-request-72h="0"', html)
        self.assertIn('data-vae-new-request-72h="1"', html)
        self.assertIn('data-scotia-unread-count="1"', html)
        self.assertIn('class="thread-badge" aria-label="1 commentaire non lu">1</span>', html)
        self.assertIn('@keyframes threadBadgePulse', html)
        self.assertIn("function getVtcStatusValues(tr)", html)
        self.assertIn('const { theoryStatus, practiceStatus } = getVtcStatusValues(tr);', html)
        self.assertIn('activeVaeDashboardFilter = filter === activeVaeDashboardFilter ? "" : filter;', html)
        self.assertIn('activeVaeDashboardFilter === "no_login" && !hasLoggedIn', html)
        self.assertIn('activeVaeDashboardFilter === "new_vae_request_72h" && isNewVaeRequest72h', html)
        self.assertIn('function normalizeVaeDashboardStatus(status)', html)
        self.assertIn('return "livret_2_validated";', html)
        self.assertIn('selectedVae === "livret_2_validated" && isLivret2ValidatedDashboardStatus(rowVaeStatus)', html)
        self.assertIn("grid-template-columns:repeat(auto-fit, minmax(180px, 1fr));", html)
        self.assertIn("overflow:visible;", html)
        self.assertIn("STATUT SCOTIA", html)
        self.assertIn("A TRAITER (Scotia)", html)
        self.assertIn("COMPLEMENT DE DOSSIER A CONSULTER (Scotia)", html)
        self.assertIn("EN ATTENTE DOCUMENTS COMPLEMENTAIRES", html)
        self.assertIn("scotia-admin-status--danger", html)
        self.assertIn("scotia-admin-status--warning", html)


if __name__ == "__main__":
    unittest.main()
