import unittest

from digiforma_duration import duration_seconds, journal_attendance


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
