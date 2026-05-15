import unittest

import app as gestion_app


class AdminTraineesVtcPageTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.data = {
            "sessions": [
                {
                    "id": "S-VTC",
                    "name": "Session VTC",
                    "training_type": "VTC",
                    "date_start": "2026-06-01",
                    "date_end": "2026-06-05",
                    "exam_theory_date": "2026-06-10",
                    "exam_practice_date": "2026-06-20",
                    "practice_training_date": "2026-06-15",
                    "trainees": [
                        {
                            "id": "T-PENDING-CMAR",
                            "last_name": "MARTIN",
                            "first_name": "Alice",
                            "email": "alice@example.test",
                            "phone": "0600000001",
                            "vtc_cmar_manual_ok": False,
                            "exam_fees_paid": False,
                            "vtc_exam_center": "nice",
                            "documents": [],
                        },
                        {
                            "id": "T-WAITING-THEORY",
                            "last_name": "DURAND",
                            "first_name": "Bruno",
                            "email": "bruno@example.test",
                            "phone": "0600000002",
                            "vtc_cmar_manual_ok": True,
                            "vtc_cmar_id": "CMAR-12345",
                            "vtc_exam_center": " Toulon ",
                            "documents": [],
                        },
                        {
                            "id": "T-THEORY-OK",
                            "last_name": "BERNARD",
                            "first_name": "Camille",
                            "email": "camille@example.test",
                            "phone": "0600000003",
                            "vtc_cmar_manual_ok": True,
                            "vtc_theory_exam_sent_at": "2026-06-11T08:00:00Z",
                            "vtc_theory_result": "success",
                            "documents": [],
                        },
                        {
                            "id": "T-PRACTICE-OK",
                            "last_name": "ROBERT",
                            "first_name": "Dana",
                            "email": "dana@example.test",
                            "phone": "0600000004",
                            "vtc_cmar_manual_ok": True,
                            "vtc_theory_exam_sent_at": "2026-06-11T08:00:00Z",
                            "vtc_theory_result": "success",
                            "vtc_practice_result": "success",
                            "documents": [],
                        },
                        {
                            "id": "T-THEORY-FAILED",
                            "last_name": "SIMON",
                            "first_name": "Eli",
                            "email": "eli@example.test",
                            "phone": "0600000005",
                            "vtc_cmar_manual_ok": True,
                            "vtc_theory_result": "non_admissible",
                            "documents": [],
                        },
                        {
                            "id": "T-PRACTICE-FAILED",
                            "last_name": "MOREAU",
                            "first_name": "Fran",
                            "email": "fran@example.test",
                            "phone": "0600000006",
                            "vtc_cmar_manual_ok": True,
                            "vtc_theory_exam_sent_at": "2026-06-11T08:00:00Z",
                            "vtc_theory_result": "success",
                            "vtc_practice_result": "non_admissible",
                            "documents": [],
                        },
                    ],
                },
                {
                    "id": "S-VTC-2",
                    "name": "Session VTC 2",
                    "training_type": "Chauffeur VTC",
                    "date_start": "2026-07-01",
                    "date_end": "2026-07-05",
                    "trainees": [
                        {
                            "id": "T-OTHER-VTC",
                            "last_name": "PETIT",
                            "first_name": "Eva",
                            "email": "eva@example.test",
                            "phone": "0600000005",
                            "documents": [],
                        }
                    ],
                },
                {
                    "id": "S-APS",
                    "name": "Session APS",
                    "training_type": "APS",
                    "trainees": [
                        {
                            "id": "T-APS",
                            "last_name": "NONVTC",
                            "first_name": "Noa",
                            "email": "noa@example.test",
                            "documents": [],
                        }
                    ],
                },
                {
                    "id": "S-VTC-ARCHIVED",
                    "name": "Session VTC archivée",
                    "training_type": "VTC",
                    "archived": True,
                    "trainees": [
                        {
                            "id": "T-ARCHIVED",
                            "last_name": "ARCHIVE",
                            "first_name": "Anne",
                            "email": "archive@example.test",
                            "documents": [],
                        }
                    ],
                },
            ]
        }

        gestion_app.load_data = lambda: self.data
        gestion_app.save_data = lambda payload: None

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data

    def test_vtc_status_labels_and_exam_center_controls_render(self):
        response = self.client.get("/admin/sessions/S-VTC/trainees")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Centre examen", html)
        self.assertIn("Légende centre examen", html)
        self.assertIn("Nice = ligne verte", html)
        self.assertIn("Toulon = ligne bleue", html)
        self.assertIn('value="nice"', html)
        self.assertIn('value="toulon"', html)
        self.assertIn('row-vtc-nice', html)
        self.assertIn('row-vtc-toulon', html)
        self.assertIn('data-vtc-exam-center="toulon"', html)
        self.assertIn('value="toulon"\n                     checked', html)
        self.assertIn('data-vtc-cmar-ok="0"', html)
        self.assertIn('data-vtc-cmar-ok="1"', html)
        self.assertIn("data-vtc-theory-label", html)
        self.assertIn("data-vtc-practice-label", html)
        self.assertIn("function refreshVtcStatusLabels", html)
        self.assertIn('id="vtcTheoryFilter"', html)
        self.assertIn('id="vtcPracticeFilter"', html)
        self.assertIn("Tous les statuts théorie", html)
        self.assertIn("Tous les statuts pratique", html)
        self.assertIn('value="waiting_theory">En attente réussite théorie</option>', html)
        self.assertIn('const { theoryStatus, practiceStatus } = getVtcStatusValues(tr);', html)
        self.assertIn('const matchPractice = selectedPractice === "all" || practiceStatus === selectedPractice;', html)
        self.assertIn("function bindImmediateRowFilters", html)
        self.assertIn('event.target?.matches?.("#vaeStatusFilter, #vtcTheoryFilter, #vtcPracticeFilter")', html)
        self.assertIn('field === "vtc_cmar_manual_ok"', html)
        self.assertIn('data-vtc-exam-status-trigger="theory"', html)
        self.assertIn('data-vtc-exam-status-trigger="practice"', html)
        self.assertIn('data-vtc-exam-status-menu="theory"', html)
        self.assertIn('data-vtc-exam-status-menu="practice"', html)
        self.assertIn('data-field="vtc_theory_status_manual"', html)
        self.assertIn('data-field="vtc_practice_status_manual"', html)
        self.assertIn('data-vtc-exam-status-choice="success"', html)
        self.assertNotIn('>Auto</option>', html)
        self.assertIn("En attente inscription examen", html)
        self.assertIn("En attente résultats examen", html)
        self.assertIn("En attente réussite théorie", html)
        self.assertIn(
            'class="vtc-status-label vtc-status-yellow" data-vtc-practice-label data-vtc-exam-status-trigger="practice"',
            html,
        )
        self.assertIn("En attente réussite théorie</button>", html)
        self.assertIn("Examen théorique réussi", html)
        self.assertIn("En attente résultats pratique", html)
        self.assertIn("Examen pratique réussi", html)
        self.assertIn("Echec examen théorique", html)
        self.assertIn("Echec examen pratique", html)
        self.assertIn("vtc-status-black", html)
        self.assertIn("Identifiant CMAR inconnu", html)
        self.assertEqual(html.count("Identifiant CMAR inconnu"), 5)
        self.assertIn('setVtcStatusLabel(tr.querySelector("[data-vtc-theory-label]"), "Echec examen théorique", "black")', html)
        self.assertIn('setVtcStatusLabel(tr.querySelector("[data-vtc-practice-label]"), "Echec examen pratique", "black")', html)
        self.assertIn('setVtcStatusLabel(tr.querySelector("[data-vtc-practice-label]"), "En attente réussite théorie", "yellow")', html)
        self.assertNotIn('setVtcStatusLabel(tr.querySelector("[data-vtc-practice-label]"), "En attente réussite théorie", "red")', html)
        self.assertNotIn("Date d'examen théorique : 10/06/2026\">🔴", html)
        self.assertNotIn("Date d'examen théorique : 10/06/2026\">🟡", html)
        self.assertNotIn("Date d'examen théorique : 10/06/2026\">🟢", html)

    def test_vtc_exam_center_can_be_saved(self):
        response = self.client.post(
            "/api/sessions/S-VTC/stagiaires/T-WAITING-THEORY/update",
            json={"vtc_exam_center": "nice"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.data["sessions"][0]["trainees"][1]["vtc_exam_center"],
            "nice",
        )

    def test_vtc_exam_statuses_can_be_saved_manually(self):
        response = self.client.post(
            "/api/sessions/S-VTC/stagiaires/T-WAITING-THEORY/update",
            json={
                "vtc_theory_status_manual": "failed",
                "vtc_practice_status_manual": "waiting_theory",
            },
        )

        self.assertEqual(response.status_code, 200)
        trainee = self.data["sessions"][0]["trainees"][1]
        self.assertEqual(trainee["vtc_theory_status_manual"], "failed")
        self.assertEqual(trainee["vtc_theory_result"], "non_admissible")
        self.assertEqual(trainee["vtc_theory_exam_sent_at"], "")
        self.assertEqual(trainee["vtc_practice_status_manual"], "waiting_theory")
        self.assertEqual(trainee["vtc_practice_result"], "")

        refreshed = self.client.get("/admin/sessions/S-VTC/trainees")

        self.assertEqual(refreshed.status_code, 200)
        html = refreshed.get_data(as_text=True)
        self.assertIn('data-vtc-theory-status-manual="failed"', html)
        self.assertIn('data-vtc-practice-status-manual="waiting_theory"', html)
        self.assertIn("Echec examen théorique</button>", html)
        self.assertIn("En attente réussite théorie</button>", html)

    def test_vtc_manual_exam_status_persists_on_all_vtc_page_refresh(self):
        response = self.client.post(
            "/api/sessions/S-VTC/stagiaires/T-THEORY-OK/update",
            json={"vtc_theory_status_manual": "waiting_result"},
        )

        self.assertEqual(response.status_code, 200)
        trainee = self.data["sessions"][0]["trainees"][2]
        self.assertEqual(trainee["vtc_theory_status_manual"], "waiting_result")
        self.assertEqual(trainee["vtc_theory_exam_sent_at"], "")

        refreshed = self.client.get("/admin/trainees/vtc")

        self.assertEqual(refreshed.status_code, 200)
        self.assertIn("no-store", refreshed.headers.get("Cache-Control", ""))
        html = refreshed.get_data(as_text=True)
        self.assertIn('data-vtc-theory-status-manual="waiting_result"', html)
        self.assertIn("En attente résultats examen</button>", html)

    def test_vtc_manual_exam_statuses_drive_stats(self):
        self.data["sessions"][0]["trainees"][0]["vtc_theory_status_manual"] = "success"
        self.data["sessions"][0]["trainees"][0]["vtc_practice_status_manual"] = "failed"

        stats = gestion_app.compute_vtc_exam_stats(self.data["sessions"][0]["trainees"])

        self.assertEqual(stats["theory_success"], 4)
        self.assertEqual(stats["practice_failed"], 2)

    def test_sessions_filters_link_to_all_vtc_trainees(self):
        response = self.client.get("/admin/sessions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Voir tous les stagiaires VTC", html)
        self.assertIn('href="/admin/trainees/vtc"', html)

    def test_all_vtc_trainees_page_lists_active_vtc_sessions(self):
        response = self.client.get("/admin/trainees/vtc")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Tous les stagiaires VTC", html)
        self.assertIn("Session VTC", html)
        self.assertIn("Session VTC 2", html)
        self.assertIn("MARTIN", html)
        self.assertIn("PETIT", html)
        self.assertIn("Prénom", html)
        self.assertIn('class="col-first-name"', html)
        self.assertIn("Théorie réussie", html)
        self.assertIn("Pratique réussie", html)
        self.assertNotIn("Conformes", html)
        self.assertNotIn("CNAPS acceptés", html)
        self.assertNotIn("Session</div>", html)
        self.assertNotIn("NONVTC", html)
        self.assertNotIn("ARCHIVE", html)
        self.assertIn('data-session-id="S-VTC"', html)
        self.assertIn('data-session-id="S-VTC-2"', html)
        self.assertIn('/admin/sessions/S-VTC-2/stagiaires/T-OTHER-VTC', html)
        self.assertEqual(html.count("Identifiant CMAR inconnu"), 6)
