import unittest

from digiforma_duration import aps_elearning_completion, duration_seconds, journal_attendance


class JournalAttendanceTests(unittest.TestCase):
    def test_supported_journal_totals_keep_seconds(self):
        for value, expected in [
            ("50 heures, 13 minutes et 31 secondes", 180811),
            ("62 heures", 223200), ("62h", 223200), ("62h00", 223200),
            ("62h00m01s", 223201), ("62 h 00 min 01 s", 223201),
            ("62:00:01", 223201), ("62:00", 223200),
            ("61 heures, 59 minutes et 59 secondes", 223199),
            ("62,5 heures", 225000), ("0 seconde", 0),
        ]:
            with self.subTest(value=value):
                self.assertEqual(duration_seconds(value), expected)

    def test_100_percent_requires_strictly_more_than_62_hours(self):
        for value, expected in [
            ("61h59m59s", False), ("62h00m00s", False),
            ("62h00m01s", True), ("80 heures", True),
        ]:
            with self.subTest(value=value):
                metrics = journal_attendance(value)
                self.assertEqual(metrics["connection_requirement_met"], expected)
                self.assertEqual(metrics["attendance_rate"] == 100, expected)
        self.assertEqual(journal_attendance("50 heures, 13 minutes et 31 secondes")["attendance_rate"], 81)

    def test_unreadable_or_approximate_totals_never_pass(self):
        for value in (None, "", "Non renseignée", "< 30 secondes", "62h incomplet", "-63 heures", "NaN", "62:99:00"):
            with self.subTest(value=value):
                metrics = journal_attendance(value)
                self.assertIsNone(metrics["connection_seconds"])
                self.assertFalse(metrics["connection_requirement_met"])
                self.assertEqual(metrics["attendance_rate"], 0)


class ApsElearningCompletionTests(unittest.TestCase):
    @staticmethod
    def tracking(**overrides):
        return dict(paths_total=8, paths_completed=8, evaluations_total=8,
                    evaluations_completed=8, connection_log_total="63 heures", **overrides)

    def test_equal_weight_with_no_compensation_or_early_completion(self):
        for paths, evaluations, duration, expected_rate in [
            (0, 0, "0 seconde", 0),
            (4, 4, "31 heures", 50),
            (8, 8, "44h54m51s", 90.8),
            (7, 8, "80 heures", 95.8),
            (8, 7, "80 heures", 95.8),
            (0, 8, "500 heures", 66.7),
            (8, 0, "500 heures", 66.7),
            (8, 8, "61h59m59s", 99.9),
            (8, 8, "62 heures", 99.9),
            (8, 8, "62h00m01s", 100),
        ]:
            with self.subTest(paths=paths, evaluations=evaluations, duration=duration):
                tracking = self.tracking()
                tracking.update(paths_completed=paths, evaluations_completed=evaluations,
                                connection_log_total=duration)
                progress = aps_elearning_completion(tracking)
                self.assertEqual(progress["overall_rate"], expected_rate)
                self.assertEqual(progress["is_complete"], expected_rate == 100)

    def test_missing_or_inconsistent_data_cannot_claim_a_percentage(self):
        for overrides in [
            {"paths_total": 0}, {"evaluations_total": 0},
            {"paths_completed": None}, {"evaluations_completed": "inconnu"},
            {"paths_completed": 9}, {"evaluations_completed": -1},
            {"connection_log_total": ""}, {"connection_log_total": "< 63 heures"},
        ]:
            with self.subTest(overrides=overrides):
                tracking = self.tracking()
                tracking.update(overrides)
                progress = aps_elearning_completion(tracking)
                self.assertIsNone(progress["overall_rate"])
                self.assertEqual(progress["overall_rate_label"], "À vérifier")
                self.assertFalse(progress["is_complete"])

    def test_smaller_report_totals_do_not_lower_the_eight_required(self):
        tracking = self.tracking()
        tracking.update(paths_total=4, paths_completed=4,
                        evaluations_total=4, evaluations_completed=4)
        progress = aps_elearning_completion(tracking)
        self.assertEqual(progress["paths_required"], 8)
        self.assertEqual(progress["evaluations_required"], 8)
        self.assertEqual(progress["overall_rate"], 66.7)
        self.assertFalse(progress["is_complete"])
