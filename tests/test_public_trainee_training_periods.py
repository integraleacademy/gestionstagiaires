import unittest
from unittest.mock import patch

import app as gestion_app
from lxml import html


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

    def test_vtc_displays_three_separate_dates_with_change_notice(self):
        response = self._render_session({
            "training_type": "CHAUFFEUR VTC", "exam_theory_date": "2026-10-27",
            "practice_training_date": "2026-11-09", "exam_practice_date": "2026-11-23",
        })
        page = html.fromstring(response.data)
        for key, label, date in (
            ("theory_exam", "Examen théorique", "27/10/2026"),
            ("practice_training", "Formation pratique", "09/11/2026"),
            ("practice_exam", "Examen pratique", "23/11/2026"),
        ):
            card = page.xpath(f'//*[@data-vtc-date="{key}"]')[0]
            self.assertIn(label, card.text_content())
            self.assertIn(date, card.text_content())
            self.assertIn("Sous réserve de modifications", card.text_content())
        self.assertNotIn("Fiche expérience professionnelle", page.text_content())
        chamber = page.xpath('//section[@aria-labelledby="vtcChamberTitle"]')[0]
        assistance = page.xpath('//section[@aria-labelledby="vtcAssistanceTitle"]')[0]
        self.assertIs(chamber.getparent(), assistance.getparent())
        self.assertEqual(page.xpath('//a[@href="tel:0492125338"]')[0].get("class"),
                         page.xpath('//a[@href="tel:0494619925"]')[0].get("class"))

    def test_vtc_missing_practical_dates_do_not_reuse_the_theory_date(self):
        response = self._render_session({"training_type": "VTC"})
        page = html.fromstring(response.data)
        self.assertIn("13/10/2026", page.xpath('//*[@data-vtc-date="theory_exam"]')[0].text_content())
        for key in ("practice_training", "practice_exam"):
            self.assertIn("Date à venir", page.xpath(f'//*[@data-vtc-date="{key}"]')[0].text_content())

    def test_vtc_supports_legacy_exam_dates(self):
        response = self._render_session({"training_type": "VTC", "exam_date": "",
            "date_examen_theorique": "2026-10-27", "date_examen_pratique": "2026-11-23"})
        page = html.fromstring(response.data)
        self.assertIn("27/10/2026", page.xpath('//*[@data-vtc-date="theory_exam"]')[0].text_content())
        self.assertIn("23/11/2026", page.xpath('//*[@data-vtc-date="practice_exam"]')[0].text_content())


if __name__ == "__main__":
    unittest.main()
