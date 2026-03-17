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
            self.assertIn("FORMATION DESP VAE", vae_html)

    def test_print_page_uses_desp_label_for_dirigeant_initial_and_expected_highlight(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S3",
                    "name": "Formation dirigeant",
                    "training_type": "DIRIGEANT initial",
                    "date_start": "2026-03-09",
                    "date_end": "2026-04-24",
                    "trainees": [{"id": "T3", "last_name": "Koita", "first_name": "Manoury"}],
                },
            ]
        }

        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data"):
            resp = client.get("/admin/sessions/S3/stagiaires/T3/etiquette")
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn("FORMATION DESP", html)
            self.assertNotIn("FORMATION DIRIGEANT INITIAL", html)
            self.assertIn("color:#fff", html)
            self.assertIn("background:#8b5e3c", html)



    def test_print_page_applies_training_specific_colors(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S4",
                    "name": "Formation aps",
                    "training_type": "APS",
                    "date_start": "2026-04-01",
                    "date_end": "2026-06-26",
                    "trainees": [{"id": "T4", "last_name": "Oufqih", "first_name": "Yannis"}],
                },
                {
                    "id": "S5",
                    "name": "Formation a3p",
                    "training_type": "A3P",
                    "date_start": "2026-09-01",
                    "date_end": "2026-10-27",
                    "trainees": [{"id": "T5", "last_name": "Urbanik", "first_name": "Anthony"}],
                },
            ]
        }

        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data"):
            aps_resp = client.get("/admin/sessions/S4/stagiaires/T4/etiquette")
            self.assertEqual(aps_resp.status_code, 200)
            aps_html = aps_resp.get_data(as_text=True)
            self.assertIn("FORMATION TFP APS", aps_html)
            self.assertIn("background:#7dd3fc", aps_html)

            a3p_resp = client.get("/admin/sessions/S5/stagiaires/T5/etiquette")
            self.assertEqual(a3p_resp.status_code, 200)
            a3p_html = a3p_resp.get_data(as_text=True)
            self.assertIn("FORMATION A3P", a3p_html)
            self.assertIn("background:#fde047", a3p_html)
            self.assertIn("checklist-compact", a3p_html)

if __name__ == "__main__":
    unittest.main()
