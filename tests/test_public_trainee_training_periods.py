import unittest
from unittest.mock import patch

import app as gestion_app


class PublicTraineeTrainingPeriodsTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["admin_logged_in"] = True

    def _render_session(self, session_data):
        session = {
            "id": "S1",
            "name": "Session septembre",
            "date_start": "2026-09-08",
            "date_end": "2026-10-12",
            "exam_date": "2026-10-13",
            "trainees": [
                {
                    "id": "T1",
                    "last_name": "DUPONT",
                    "first_name": "Alice",
                    "birth_date": "1990-01-01",
                    "public_token": "PUBLIC-PERIODS",
                }
            ],
            **session_data,
        }
        with patch.object(gestion_app, "load_data", return_value={"sessions": [session]}), patch.object(
            gestion_app, "save_data"
        ):
            return self.client.get("/espace/PUBLIC-PERIODS")

    def test_aps_page_displays_training_remote_and_in_person_periods(self):
        response = self._render_session(
            {
                "training_type": "APS",
                "aps_remote_start": "2026-09-08",
                "aps_remote_end": "2026-09-18",
                "aps_in_person_start": "2026-09-21",
                "aps_in_person_end": "2026-10-12",
            }
        )

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="info-label">Dates de formation</div>', body)
        self.assertIn('class="info-label">Distanciel</div>', body)
        self.assertIn('class="info-label">Présentiel</div>', body)
        self.assertIn("Du 08/09/2026 au 12/10/2026", body)
        self.assertIn("Du 08/09/2026 au 18/09/2026", body)
        self.assertIn("Du 21/09/2026 au 12/10/2026", body)

    def test_desp_initial_page_displays_its_own_split_periods(self):
        response = self._render_session(
            {
                "training_type": "DIRIGEANT INITIAL",
                "dirigeant_remote_start": "2026-09-08",
                "dirigeant_remote_end": "2026-10-02",
                "dirigeant_in_person_start": "2026-10-05",
                "dirigeant_in_person_end": "2026-10-12",
            }
        )

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="info-label">Dates de formation</div>', body)
        self.assertIn('class="info-label">Distanciel</div>', body)
        self.assertIn('class="info-label">Présentiel</div>', body)
        self.assertIn("Du 08/09/2026 au 02/10/2026", body)
        self.assertIn("Du 05/10/2026 au 12/10/2026", body)

    def test_other_training_keeps_existing_start_and_end_display(self):
        response = self._render_session({"training_type": "VTC"})

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('class="info-label">Distanciel</div>', body)
        self.assertNotIn('class="info-label">Présentiel</div>', body)
        self.assertIn('class="info-label">Début</div>', body)
        self.assertIn('class="info-label">Fin</div>', body)

    def test_desp_vae_does_not_display_initial_training_periods(self):
        response = self._render_session(
            {
                "training_type": "DIRIGEANT VAE",
                "dirigeant_remote_start": "2026-09-08",
                "dirigeant_remote_end": "2026-10-02",
                "dirigeant_in_person_start": "2026-10-05",
                "dirigeant_in_person_end": "2026-10-12",
            }
        )

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('class="info-label">Dates de formation</div>', body)
        self.assertNotIn('class="info-label">Distanciel</div>', body)
        self.assertNotIn('class="info-label">Présentiel</div>', body)


if __name__ == "__main__":
    unittest.main()
