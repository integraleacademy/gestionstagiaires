import unittest
from unittest.mock import patch

import app as gestion_app


class EtiquetteLabelsTests(unittest.TestCase):
    def test_template_mapping_matches_requested_training_types(self):
        self.assertEqual(gestion_app._etiquette_template_name("APS"), "etiquette_aps.docx")
        self.assertEqual(gestion_app._etiquette_template_name("A3P"), "etiquette_a3p.docx")
        self.assertEqual(gestion_app._etiquette_template_name("DIRIGEANT"), "etiquette_dirigeant_initial.docx")
        self.assertEqual(gestion_app._etiquette_template_name("DIRIGEANT VAE"), "etiquette_dirigeant.docx")

    def test_print_page_displays_expected_checklist_for_a3p_and_vae(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S1",
                    "name": "Formation test",
                    "training_type": "A3P",
                    "date_start": "2026-01-05",
                    "date_end": "2026-02-06",
                    "trainees": [{"id": "T1", "last_name": "Doe", "first_name": "Jane"}],
                },
                {
                    "id": "S2",
                    "name": "Formation test VAE",
                    "training_type": "DIRIGEANT VAE",
                    "date_start": "2026-01-05",
                    "date_end": "2026-02-06",
                    "trainees": [{"id": "T2", "last_name": "Doe", "first_name": "John"}],
                },
            ]
        }

        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data"):
            a3p_resp = client.get("/admin/sessions/S1/stagiaires/T1/etiquette")
            self.assertEqual(a3p_resp.status_code, 200)
            a3p_html = a3p_resp.get_data(as_text=True)
            self.assertIn("Permis de conduire valide", a3p_html)
            self.assertIn("Certificat médical de moins de 3 mois", a3p_html)

            vae_resp = client.get("/admin/sessions/S2/stagiaires/T2/etiquette")
            self.assertEqual(vae_resp.status_code, 200)
            vae_html = vae_resp.get_data(as_text=True)
            self.assertIn("Convention de VAE signée", vae_html)
            self.assertIn("Attestation de recevabilité", vae_html)
            self.assertIn("FORMATION DESP", vae_html)
            self.assertIn("EN VAE", vae_html)


if __name__ == "__main__":
    unittest.main()
