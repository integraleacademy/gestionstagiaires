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
                            "vtc_exam_center": "toulon",
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
                    ],
                }
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
        self.assertIn('data-vtc-cmar-ok="0"', html)
        self.assertIn('data-vtc-cmar-ok="1"', html)
        self.assertIn("data-vtc-theory-label", html)
        self.assertIn("data-vtc-practice-label", html)
        self.assertIn("function refreshVtcStatusLabels", html)
        self.assertIn('field === "vtc_cmar_manual_ok"', html)
        self.assertIn("En attente inscription examen", html)
        self.assertIn("En attente résultats examen", html)
        self.assertIn("En attente réussite théorie", html)
        self.assertIn("Examen théorique réussi", html)
        self.assertIn("En attente résultats pratique", html)
        self.assertIn("Examen pratique réussi", html)
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
