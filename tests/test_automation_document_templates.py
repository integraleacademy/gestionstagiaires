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


if __name__ == "__main__":
    unittest.main()
