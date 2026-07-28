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
            'new Set(["APS", "A3P", "SSIAP", "DIRIGEANT initial", "VTC"])',
            self.template,
        )
        self.assertIn(
            's.status_key === "upcoming" && !!s.date_start',
            self.template,
        )


if __name__ == "__main__":
    unittest.main()
