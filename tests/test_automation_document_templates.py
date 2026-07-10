import html
import os
import unittest

import app as gestion_app


class AutomationDocumentTemplateConfigTests(unittest.TestCase):
    def test_all_configured_automation_templates_exist_for_supported_formations(self):
        sessions = [
            {"training_type": "APS", "name": "Formation APS"},
            {"training_type": "A3P", "name": "Formation A3P"},
            {"training_type": "DIRIGEANT", "name": "Formation DESP Puget"},
            {"training_type": "DIRIGEANT", "name": "Formation DESP Paris"},
            {"training_type": "SSIAP", "name": "Formation SSIAP"},
            {"training_type": "VTC", "name": "Formation VTC"},
            {"training_type": "DIRIGEANT VAE", "name": "VAE DESP"},
        ]

        missing = []
        for session in sessions:
            config = gestion_app._automation_document_config(session)
            for key, template_name in config.items():
                if not key.endswith("_template") or not template_name:
                    continue
                template_path = os.path.join(gestion_app.app.root_path, "templates_word", template_name)
                if not os.path.exists(template_path):
                    missing.append((config.get("label"), key, template_name))

        self.assertEqual(missing, [])

    def test_desp_paris_entry_attestation_uses_existing_word_template(self):
        session = {"training_type": "DIRIGEANT", "name": "DESP Paris"}

        self.assertEqual(
            gestion_app._automation_document_config(session)["entry_template"],
            "attestationentreedesparis.docx",
        )
        self.assertTrue(os.path.exists(gestion_app._aps_entry_attestation_template_path(session)))


class AttestationEmailTrainingLabelTests(unittest.TestCase):
    def test_entry_and_end_attestation_emails_use_supported_training_labels(self):
        cases = [
            (
                {"training_type": "SSIAP", "name": "Formation SSIAP 1"},
                "SSIAP",
                "Agent de sécurité incendie SSIAP 1",
            ),
            (
                {"training_type": "A3P", "name": "Formation A3P"},
                "A3P",
                "Agent de Protection Physique des Personnes A3P",
            ),
            (
                {"training_type": "DIRIGEANT", "name": "Formation DESP"},
                "DESP",
                "Dirigeant d'une entreprise de sécurité privée (DESP)",
            ),
        ]

        for session, short_label, long_label in cases:
            with self.subTest(short_label=short_label):
                entry_subject, entry_html = gestion_app._build_aps_entry_attestation_email(
                    "Jean", "2026-09-01", session
                )
                end_subject, end_html = gestion_app._build_aps_end_attestation_email(
                    "Jean", "2026-09-30", session
                )

                self.assertIn(f"formation {short_label}", entry_subject)
                self.assertIn(f"formation {short_label}", end_subject)
                escaped_long_label = html.escape(long_label)
                self.assertIn(escaped_long_label, entry_html)
                self.assertIn(escaped_long_label, end_html)
                self.assertNotIn("formation APS", entry_subject)
                self.assertNotIn("formation APS", end_subject)
                self.assertNotIn("formation APS", entry_html)
                self.assertNotIn("formation APS", end_html)


if __name__ == "__main__":
    unittest.main()
