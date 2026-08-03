from pathlib import Path
import unittest


class AdminSessionsTraineeSessionSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = Path("templates/admin_sessions.html").read_text(encoding="utf-8")

    def test_create_modal_has_direct_session_search(self):
        self.assertIn('id="traineeSessionSearch" type="search"', self.template)
        self.assertIn('id="traineeSessionSearchResults" role="listbox"', self.template)
        self.assertIn('button.className = "trainee-session-result"', self.template)
        self.assertIn("sessionSearchText(s).includes(query)", self.template)

    def test_only_not_started_sessions_are_offered_for_required_trainings(self):
        self.assertIn(
            'new Set(["APS", "A3P", "SSIAP", "DIRIGEANT initial"])',
            self.template,
        )
        self.assertIn(
            's.status_key === "upcoming" && !!s.date_start',
            self.template,
        )

    def test_vtc_offers_sessions_from_the_whole_year(self):
        future_only_declaration = next(
            line for line in self.template.splitlines() if "const futureOnlyTrainings" in line
        )
        self.assertNotIn('"VTC"', future_only_declaration)


if __name__ == "__main__":
    unittest.main()
