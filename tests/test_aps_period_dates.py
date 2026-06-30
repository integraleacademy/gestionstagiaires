import unittest

import app


class ApsPeriodDatesTests(unittest.TestCase):
    def test_compute_aps_period_dates_skips_weekends_and_holidays(self):
        self.assertEqual(
            app._compute_aps_period_dates("2026-05-01"),
            {
                "aps_remote_start": "2026-05-04",
                "aps_remote_end": "2026-05-18",
                "aps_in_person_start": "2026-05-19",
                "aps_in_person_end": "2026-06-10",
                "aps_in_person_hours": 113,
                "aps_in_person_days": 16,
                "aps_computed_exam_date": "2026-06-11",
            },
        )

    def test_calculate_aps_periods_matches_expected_september_example(self):
        self.assertEqual(
            app.calculateApsPeriods("2026-09-07"),
            {
                "distancielStart": "2026-09-07",
                "distancielEnd": "2026-09-17",
                "presentielStart": "2026-09-18",
                "presentielEnd": "2026-10-09",
                "presentielHours": 113,
                "presentielDays": 16,
                "distancielHours": 62,
                "distancielDays": 9,
                "examDate": "2026-10-12",
            },
        )

    def test_sync_aps_period_dates_updates_global_session_dates(self):
        session = {"training_type": "APS", "date_start": "2026-07-08", "date_end": ""}

        app._sync_aps_period_dates(session)

        self.assertEqual(session["aps_remote_start"], "2026-07-08")
        self.assertEqual(session["aps_remote_end"], "2026-07-21")
        self.assertEqual(session["aps_in_person_start"], "2026-07-22")
        self.assertEqual(session["aps_in_person_end"], "2026-08-12")
        self.assertEqual(session["aps_in_person_hours"], 113)
        self.assertEqual(session["aps_in_person_days"], 16)
        self.assertEqual(session["date_start"], "2026-07-08")
        self.assertEqual(session["date_end"], "2026-08-12")
        self.assertEqual(session["exam_date"], "2026-08-13")

    def test_sync_aps_period_dates_removes_periods_for_other_training_types(self):
        session = {
            "training_type": "VTC",
            "date_start": "2026-07-08",
            "aps_remote_start": "2026-07-08",
            "aps_remote_end": "2026-07-21",
            "aps_in_person_start": "2026-07-22",
            "aps_in_person_end": "2026-08-13",
            "aps_in_person_hours": 113,
            "aps_in_person_days": 17,
            "aps_computed_exam_date": "2026-08-14",
        }

        app._sync_aps_period_dates(session)

        self.assertNotIn("aps_remote_start", session)
        self.assertNotIn("aps_remote_end", session)
        self.assertNotIn("aps_in_person_start", session)
        self.assertNotIn("aps_in_person_end", session)
        self.assertNotIn("aps_in_person_hours", session)
        self.assertNotIn("aps_in_person_days", session)

    def test_aps_manual_presentiel_start_keeps_exam_after_training_end(self):
        session = {
            "training_type": "APS",
            "date_start": "2026-07-08",
            "aps_in_person_start": "2026-07-22",
            "exam_date": "2026-08-13",
        }

        app._sync_aps_period_dates(session)

        self.assertEqual(session["date_start"], "2026-07-08")
        self.assertEqual(session["date_end"], "2026-08-12")
        self.assertEqual(session["aps_remote_start"], "2026-07-08")
        self.assertEqual(session["aps_remote_end"], "2026-07-21")
        self.assertEqual(session["aps_in_person_start"], "2026-07-22")
        self.assertEqual(session["aps_in_person_end"], "2026-08-12")
        self.assertEqual(session["aps_in_person_hours"], 113)
        self.assertEqual(session["aps_in_person_days"], 16)
        self.assertEqual(session["exam_date"], "2026-08-13")


if __name__ == "__main__":
    unittest.main()
