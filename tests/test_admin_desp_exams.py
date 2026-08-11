import datetime
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
            "trainees": [{"id": "T1", "last_name": "MARTIN", "first_name": "Alice", "email": "alice@example.test", "public_token": "TOKEN-1"},
                         {"id": "T2", "last_name": "DURAND", "first_name": "Lina", "email": "lina@example.test", "public_token": "TOKEN-2"}],
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
        self.assertIn("localStorage.getItem(stateKey)", player.get_data(as_text=True))
        self.assertIn("deadline-Date.now()", player.get_data(as_text=True))
        self.assertIn("Math.ceil(left/1000)", player.get_data(as_text=True))
        complete = self.client.post(f"/admin/exams/DESP-1/training-qcu/{attempt_id}/complete")
        self.assertTrue(complete.get_json()["ok"])
        self.assertEqual(attempts[0]["status"], "completed")
        for _ in range(4):
            self.client.post("/admin/exams/DESP-1/training-qcu")
        self.assertEqual(len(attempts), 4)

    def test_non_initial_desp_exam_is_not_accessible(self):
        self.assertEqual(self.client.get("/admin/exams/VAE-1").status_code, 404)

    def test_training_is_nominative_public_and_uses_distinct_question_orders(self):
        self.client.post("/admin/exams/DESP-1/training-qcu")
        attempt = self.data["sessions"][0]["desp_training_qcu_attempts"][0]
        self.assertEqual([c["candidate_id"] for c in attempt["candidates"]], ["T1", "T2"])
        self.assertNotEqual(attempt["candidates"][0]["question_order"], attempt["candidates"][1]["question_order"])
        with self.client.session_transaction() as session:
            session.pop("admin_logged_in", None)
            session["public_auth_TOKEN-1"] = True
        player = self.client.get(f"/espace/TOKEN-1/qcu/training/{attempt['id']}")
        self.assertEqual(player.status_code, 200)
        self.assertIn("Alice MARTIN", player.get_data(as_text=True))
        question = self.client.get(f"/espace/TOKEN-1/qcu/training/{attempt['id']}/question/0")
        self.assertEqual(question.status_code, 200)
        first_deadline = question.get_json()["deadline_at"]
        self.assertIn("server_time", question.get_json())
        refreshed = self.client.get(f"/espace/TOKEN-1/qcu/training/{attempt['id']}/question/0")
        self.assertEqual(refreshed.get_json()["deadline_at"], first_deadline)
        self.assertEqual(attempt["candidates"][0]["question_deadlines"], [first_deadline])
        answer = self.client.post(f"/espace/TOKEN-1/qcu/training/{attempt['id']}/answer",
                                  json={"position": 0, "answer": 0})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(len(attempt["candidates"][0]["answers"]), 1)

    def test_public_qcu_timeout_records_zero_and_advances_to_next_question(self):
        self.client.post("/admin/exams/DESP-1/training-qcu")
        attempt = self.data["sessions"][0]["desp_training_qcu_attempts"][0]
        candidate = attempt["candidates"][0]
        with self.client.session_transaction() as session:
            session.pop("admin_logged_in", None)
            session["public_auth_TOKEN-1"] = True

        player_url = f"/espace/TOKEN-1/qcu/training/{attempt['id']}"
        player = self.client.get(player_url)
        self.assertIn("answer(null)", player.get_data(as_text=True))
        self.client.get(f"{player_url}/question/0")
        candidate["question_deadlines"][0] = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
        ).isoformat().replace("+00:00", "Z")

        timed_out = self.client.post(f"{player_url}/answer", json={"position": 0, "answer": None})
        self.assertEqual(timed_out.status_code, 200)
        self.assertTrue(timed_out.get_json()["timed_out"])
        self.assertEqual(candidate["answers"][0]["selected_answer"], None)
        self.assertFalse(candidate["answers"][0]["correct"])
        self.assertTrue(candidate["answers"][0]["unanswered"])
        self.assertEqual(self.client.get(f"{player_url}/question/1").status_code, 200)

    def test_exam_batch_and_designed_results_pdf(self):
        self.client.post("/admin/exams/DESP-1/exam-qcu")
        attempt = self.data["sessions"][0]["desp_exam_qcu_attempts"][0]
        response = self.client.get(f"/admin/exams/DESP-1/qcu/exam/{attempt['id']}/results.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF"))

    def test_official_qcu_records_server_deadlines_answers_and_candidate_audit(self):
        started = self.client.post("/admin/exams/DESP-1/official-qcu/T1")
        self.assertEqual(started.status_code, 201)
        attempt_id = started.get_json()["attempt_id"]
        play = self.client.get(started.get_json()["play_url"])
        self.assertEqual(play.status_code, 200)
        self.assertIn("coupure réseau", play.get_data(as_text=True))

        opened = self.client.post(f"/admin/exams/DESP-1/official-qcu/{attempt_id}/questions/0/open")
        self.assertEqual(opened.status_code, 201)
        self.assertIn("opened_at", opened.get_json())
        self.assertIn("deadline_at", opened.get_json())
        answered = self.client.post(
            f"/admin/exams/DESP-1/official-qcu/{attempt_id}/questions/0/answer", json={"answer": 0}
        )
        self.assertEqual(answered.status_code, 200)
        attempt = self.data["sessions"][0]["desp_official_qcu_attempts"][0]
        self.assertEqual(attempt["candidate_id"], "T1")
        self.assertIn("received_at", attempt["answers"][0])
        self.assertIn("question_opened", [event["event"] for event in attempt["audit_log"]])
        self.assertIn("answer_recorded", [event["event"] for event in attempt["audit_log"]])

        duplicate = self.client.post("/admin/exams/DESP-1/official-qcu/T1")
        self.assertEqual(duplicate.status_code, 409)

    def test_official_qcu_rejects_late_answer(self):
        started = self.client.post("/admin/exams/DESP-1/official-qcu/T1").get_json()
        attempt_id = started["attempt_id"]
        self.client.get(started["play_url"])
        self.client.post(f"/admin/exams/DESP-1/official-qcu/{attempt_id}/questions/0/open")
        attempt = self.data["sessions"][0]["desp_official_qcu_attempts"][0]
        attempt["questions"][0]["deadline_at"] = "2000-01-01T00:00:00Z"
        late = self.client.post(
            f"/admin/exams/DESP-1/official-qcu/{attempt_id}/questions/0/answer", json={"answer": 0}
        )
        self.assertEqual(late.status_code, 409)
        self.assertEqual(attempt["answers"], [])
        self.assertEqual(attempt["audit_log"][-1]["event"], "late_answer_rejected")


if __name__ == "__main__":
    unittest.main()
