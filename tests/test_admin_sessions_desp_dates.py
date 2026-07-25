import unittest
from pathlib import Path


class AdminSessionsDespDatesTests(unittest.TestCase):
    def setUp(self):
        self.template = Path("templates/admin_sessions.html").read_text()

    def test_desp_dates_are_available_in_create_edit_and_session_cards(self):
        self.assertIn('{% set is_desp = "DIRIGEANT" in training_upper or "DESP" in training_upper %}', self.template)
        self.assertIn('{{ s.dirigeant_remote_start|frdate }} → {{ s.dirigeant_remote_end|frdate }}', self.template)
        self.assertIn('{{ s.dirigeant_in_person_start|frdate }} → {{ s.dirigeant_in_person_end|frdate }}', self.template)
        self.assertIn('Début distanciel DESP', self.template)
        self.assertIn('Fin présentiel DESP', self.template)
        self.assertIn('return type.startsWith("DIRIGEANT") || type.includes("DESP");', self.template)

    def test_desp_exam_date_is_visible_and_saved(self):
        self.assertEqual(
            self.template.count('examDateField.style.display = isVtc ? "none" : "";'),
            2,
        )
        self.assertIn(
            'const exam_date = (document.getElementById("examDate").value || "").trim();',
            self.template,
        )
        self.assertIn(
            'exam_date: (document.getElementById("editExamDate").value || "").trim(),',
            self.template,
        )
        self.assertNotIn('const exam_date = isDirigeant ? ""', self.template)


if __name__ == "__main__":
    unittest.main()
