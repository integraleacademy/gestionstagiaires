from pathlib import Path
import unittest


class AdminTraineeTransferSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = Path("templates/admin_trainee.html").read_text(encoding="utf-8")

    def test_matching_sessions_are_rendered_as_direct_suggestions(self):
        self.assertIn('id="transferSessionResults" role="listbox"', self.template)
        self.assertIn('button.className = "transfer-session-result"', self.template)
        self.assertIn('results.classList.toggle("show", matches.length > 0)', self.template)
        self.assertIn('button.addEventListener("click", ()=>selectSession(option, button))', self.template)

    def test_destination_select_is_kept_only_as_hidden_form_value(self):
        self.assertIn(
            'id="transferSessionSelect" required hidden aria-hidden="true"',
            self.template,
        )
        self.assertNotIn('<div class="label">Session de destination</div>', self.template)
        self.assertIn("select.value = option.value", self.template)


if __name__ == "__main__":
    unittest.main()
