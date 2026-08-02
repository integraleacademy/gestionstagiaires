import unittest

import app as gestion_app


class AdminDespExamTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.data = {"sessions": [{
            "id": "DESP-1", "name": "DESP initial septembre", "training_type": "DIRIGEANT INITIAL",
            "date_start": "2026-09-01", "date_end": "2026-09-20", "exam_date": "2026-09-22",
            "trainees": [{"id": "T1", "last_name": "MARTIN", "first_name": "Alice", "email": "alice@example.test"}],
        }, {"id": "VAE-1", "name": "VAE DESP", "training_type": "DIRIGEANT VAE", "trainees": []}]}
        gestion_app.load_data = lambda: self.data
        gestion_app.save_data = lambda payload: None
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data

    def test_exam_list_only_contains_desp_initial(self):
        response = self.client.get("/admin/exams")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("DESP initial septembre", html)
        self.assertNotIn("VAE DESP", html)

    def test_training_qcu_is_created_completed_and_limited_to_four(self):
        response = self.client.post("/admin/exams/DESP-1/training-qcu")
        self.assertEqual(response.status_code, 302)
        attempts = self.data["sessions"][0]["desp_training_qcu_attempts"]
        self.assertEqual(len(attempts), 1)
        attempt_id = attempts[0]["id"]
        player = self.client.get(f"/admin/exams/DESP-1/training-qcu/{attempt_id}")
        self.assertIn("Quelle autorit", player.get_data(as_text=True))
        self.assertIn('id="timer">45', player.get_data(as_text=True))
        complete = self.client.post(f"/admin/exams/DESP-1/training-qcu/{attempt_id}/complete")
        self.assertTrue(complete.get_json()["ok"])
        self.assertEqual(attempts[0]["status"], "completed")
        for _ in range(4):
            self.client.post("/admin/exams/DESP-1/training-qcu")
        self.assertEqual(len(attempts), 4)

    def test_non_initial_desp_exam_is_not_accessible(self):
        self.assertEqual(self.client.get("/admin/exams/VAE-1").status_code, 404)


if __name__ == "__main__":
    unittest.main()
