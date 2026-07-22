import unittest
from unittest.mock import patch

import app as gestion_app


class AdminSessionsConventionsTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def test_conventions_include_vae_from_financement_validated_status(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "training_type": "APS",
                    "date_start": "2026-09-01",
                    "date_end": "2026-09-15",
                    "trainees": [
                        {
                            "last_name": "CLASSIQUE",
                            "first_name": "Claire",
                            "convention_status": "soon",
                        }
                    ],
                },
                {
                    "id": "S-VAE",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "last_name": "AVANT",
                            "first_name": "Alice",
                            "convention_status": "soon",
                            "vae_status": "livret_1_validated",
                        },
                        {
                            "last_name": "SEUIL",
                            "first_name": "Bruno",
                            "convention_status": "soon",
                            "vae_status": "financement_validated",
                        },
                        {
                            "last_name": "APRES",
                            "first_name": "Chloé",
                            "convention_status": "signing",
                            "vae_status": "jury",
                        },
                        {
                            "last_name": "SIGNEE",
                            "first_name": "Diane",
                            "convention_status": "signed",
                            "vae_status": "certified",
                        },
                    ],
                },
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("CLASSIQUE", html)
        self.assertIn("SEUIL", html)
        self.assertIn("APRES", html)
        self.assertNotIn("AVANT", html)
        self.assertNotIn("SIGNEE", html)
        self.assertIn("Les VAE sont incluses à partir du statut", html)

    def test_convention_signed_in_public_journey_is_excluded_without_signature_evidence(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "training_type": "APS",
                    "date_start": "2026-09-01",
                    "date_end": "2026-09-15",
                    "trainees": [
                        {
                            "id": "T-DIRTY",
                            "last_name": "DIRTY",
                            "first_name": "Data",
                            "convention_status": "signed",
                            "convention_aps_status": "signed",
                        }
                    ],
                }
            ]
        }

        captured = {}

        def fake_render_template(template_name, **context):
            captured.update(context)
            return "OK"

        with patch.object(gestion_app, "load_data", return_value=fake_data), \
             patch.object(gestion_app, "render_template", side_effect=fake_render_template):
            response = self.client.get("/admin/sessions/conventions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["rows"], [])

    def test_fiche_button_links_to_trainee_summary(self):
        fake_data = {
            "sessions": [{
                "id": "S-APS",
                "training_type": "APS",
                "date_start": "2026-09-01",
                "trainees": [{
                    "id": "T-SUMMARY",
                    "last_name": "RECAP",
                    "first_name": "Rania",
                }],
            }]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('href="/admin/sessions/S-APS/stagiaires/T-SUMMARY/summary">Fiche</a>', html)

    def test_legacy_signed_convention_is_excluded_when_public_journey_shows_signed(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "training_type": "APS",
                    "date_start": "2026-09-01",
                    "date_end": "2026-09-15",
                    "trainees": [
                        {
                            "id": "T-LEGACY",
                            "last_name": "LEGACY",
                            "first_name": "Lina",
                            "convention_status": "signed",
                            "convention_legacy_signed": True,
                            "convention_legacy_signed_at": "2026-07-16T10:00:00Z",
                        }
                    ],
                }
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn("LEGACY", html)

    def test_signed_conventions_created_since_july_15_are_included_in_tracking(self):
        fake_data = {
            "sessions": [{
                "id": "S-APS",
                "training_type": "APS",
                "trainees": [
                    {
                        "id": "T-SIGNED-BEFORE",
                        "last_name": "SIGNATURE-AVANT",
                        "first_name": "Samira",
                        "convention_signature": {
                            "status": "signed",
                            "created_at": "2026-07-14T23:59:59Z",
                        },
                    },
                    {
                        "id": "T-SIGNED-FROM",
                        "last_name": "SIGNATURE-DEPUIS",
                        "first_name": "Sonia",
                        "convention_signature": {
                            "status": "signed",
                            "created_at": "2026-07-15T00:00:00Z",
                        },
                    },
                    {
                        "id": "T-APS-SIGNED-FROM",
                        "last_name": "APS-DEPUIS",
                        "first_name": "Sofia",
                        "convention_status": "signed",
                        "convention_aps_generated_at": "2026-07-15T12:00:00Z",
                        "convention_aps_pdf_path": "convention.pdf",
                    },
                    {
                        "id": "T-PENDING",
                        "last_name": "PENDING",
                        "first_name": "Paul",
                        "convention_signature": {"status": "ongoing"},
                    },
                ],
            }]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn("SIGNATURE-AVANT", html)
        self.assertIn("SIGNATURE-DEPUIS", html)
        self.assertIn("APS-DEPUIS", html)
        self.assertIn("PENDING", html)

    def test_conventions_use_vae_label_and_action_dates_to_apply_threshold(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-VAE",
                    "training_type": "DIRIGEANT VAE",
                    "trainees": [
                        {
                            "last_name": "LIBELLE",
                            "first_name": "Emma",
                            "convention_status": "soon",
                            "vae_status_label": "Financement validé",
                        },
                        {
                            "last_name": "ACTION",
                            "first_name": "Farah",
                            "convention_status": "soon",
                            "vae_status": "livret_1_validated",
                            "vae_action_dates": {
                                "financement_validated": "12/06/2026"
                            },
                        },
                    ],
                }
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("LIBELLE", html)
        self.assertIn("ACTION", html)


    def test_convention_history_dates_are_displayed_in_french_timezone(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "training_type": "APS",
                    "date_start": "2026-09-01",
                    "date_end": "2026-09-15",
                    "trainees": [
                        {
                            "id": "T1",
                            "last_name": "DATES",
                            "first_name": "Delphine",
                            "email": "delphine@example.test",
                            "convention_status": "signing",
                            "convention_signature": {
                                "signature_request_id": "sig-1",
                                "signature_link": "https://sign.example.test/sig-1",
                                "status": "ongoing",
                                "created_at": "2026-07-03T09:50:32.129789Z",
                                "signature_email_sent_at": "2026-07-03T09:51:00Z",
                                "next_reminder_at": "2026-07-05T09:50:32Z",
                                "reminder_count": 0,
                            },
                        }
                    ],
                }
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Créée :</strong> 03/07/2026 à 11h50", html)
        self.assertIn("Envoyée :</strong> 03/07/2026 à 11h51", html)
        self.assertIn("prochaine 05/07/2026 à 11h50", html)
        self.assertNotIn("2026-07-03T09:50:32", html)
        self.assertNotIn("2026-07-05T09:50:32", html)

    def test_conventions_can_filter_by_formation_and_status(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "training_type": "APS",
                    "trainees": [
                        {"last_name": "APS-SOON", "first_name": "Alice", "convention_status": "soon"},
                        {"last_name": "APS-SIGNING", "first_name": "Bruno", "convention_status": "signing"},
                    ],
                },
                {
                    "id": "S-A3P",
                    "training_type": "A3P",
                    "trainees": [
                        {"last_name": "A3P-SOON", "first_name": "Chloé", "convention_status": "soon"},
                    ],
                },
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions?formation=APS&status=signing")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("APS-SIGNING", html)
        self.assertNotIn("APS-SOON", html)
        self.assertNotIn("A3P-SOON", html)
        self.assertIn('option value="APS" selected', html)
        self.assertIn('option value="signing" selected', html)
        self.assertIn("Réinitialiser", html)
        self.assertIn('id="sidebarConventionsSignedBadge"', html)
        self.assertIn('id="sidebarToolsConventionsSignedBadge"', html)

    def test_non_signed_conventions_from_past_sessions_are_displayed(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-PAST",
                    "training_type": "APS",
                    "date_start": "2026-06-01",
                    "date_end": "2026-06-15",
                    "trainees": [
                        {
                            "id": "T-PAST-UNSIGNED",
                            "last_name": "NON-SIGNEE",
                            "first_name": "Nora",
                            "convention_status": "signing",
                        },
                    ],
                },
            ],
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions?status=signing")

        self.assertEqual(response.status_code, 200)
        self.assertIn("NON-SIGNEE", response.get_data(as_text=True))

    def test_signed_conventions_unseen_api_and_page_acknowledgement(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "name": "Session APS",
                    "training_type": "APS",
                    "date_start": "2026-09-01",
                    "date_end": "2026-09-15",
                    "trainees": [
                        {
                            "id": "T1",
                            "last_name": "SIGNEE",
                            "first_name": "Sarah",
                            "convention_status": "signed",
                            "convention_aps_status": "signed",
                            "convention_aps_pdf_path": "unsigned.pdf",
                            "convention_signature": {"status": "done", "signed_at": "2026-07-16T10:00:00Z"},
                        }
                    ],
                }
            ]
        }
        saved_payloads = []

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data", side_effect=lambda data: saved_payloads.append(data)):
            api_response = self.client.get("/api/conventions_signed_unseen")
            page_response = self.client.get("/admin/sessions/conventions")
            api_after_response = self.client.get("/api/conventions_signed_unseen")

        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.get_json()["count"], 1)
        self.assertEqual(page_response.status_code, 200)
        self.assertFalse(saved_payloads)
        self.assertNotIn("convention_signed_seen_at", fake_data["sessions"][0]["trainees"][0])
        self.assertEqual(api_after_response.get_json()["count"], 1)

    def test_signed_conventions_badge_stays_until_convention_is_printed(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "name": "Session APS",
                    "training_type": "APS",
                    "date_start": "2026-09-01",
                    "date_end": "2026-09-15",
                    "trainees": [
                        {
                            "id": "T1",
                            "last_name": "SIGNEE",
                            "first_name": "Sarah",
                            "convention_status": "signed",
                            "convention_aps_status": "signed",
                            "convention_aps_pdf_path": "unsigned.pdf",
                            "convention_signature": {"status": "done", "signed_at": "2026-07-16T10:00:00Z"},
                        }
                    ],
                }
            ]
        }
        saved_payloads = []

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data", side_effect=lambda data: saved_payloads.append(data)):
            api_response = self.client.get("/api/conventions_signed_unseen")
            page_response = self.client.get("/admin/sessions/conventions")
            api_after_page_response = self.client.get("/api/conventions_signed_unseen")
            print_response = self.client.post("/api/stagiaires/T1/mark-printed", json={"printed": True})
            api_after_print_response = self.client.get("/api/conventions_signed_unseen")

        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.get_json()["count"], 1)
        self.assertEqual(page_response.status_code, 200)
        self.assertEqual(api_after_page_response.get_json()["count"], 1)
        self.assertEqual(print_response.status_code, 200)
        self.assertTrue(saved_payloads)
        self.assertTrue(fake_data["sessions"][0]["trainees"][0]["printed"])
        self.assertNotIn("convention_signed_seen_at", fake_data["sessions"][0]["trainees"][0])
        self.assertEqual(api_after_print_response.get_json()["count"], 0)


    def test_print_button_is_highlighted_only_for_unprinted_signed_conventions(self):
        fake_data = {
            "sessions": [{
                "id": "S-APS",
                "training_type": "APS",
                "trainees": [
                    {
                        "id": "T-SIGNED-UNPRINTED",
                        "last_name": "SIGNED-UNPRINTED",
                        "convention_signature": {"status": "done", "created_at": "2026-07-16T10:00:00Z"},
                    },
                    {
                        "id": "T-SIGNED-PRINTED",
                        "last_name": "SIGNED-PRINTED",
                        "printed": True,
                        "convention_signature": {"status": "done", "created_at": "2026-07-16T10:00:00Z"},
                    },
                    {"id": "T-UNSIGNED", "last_name": "UNSIGNED", "convention_status": "signing"},
                ],
            }],
        }
        captured = {}

        def fake_render_template(template_name, **context):
            captured.update(context)
            return "OK"

        with patch.object(gestion_app, "load_data", return_value=fake_data), \
             patch.object(gestion_app, "render_template", side_effect=fake_render_template):
            response = self.client.get("/admin/sessions/conventions")

        self.assertEqual(response.status_code, 200)
        rows_by_id = {row["trainee_id"]: row for row in captured["rows"]}
        self.assertTrue(rows_by_id["T-SIGNED-UNPRINTED"]["needs_printing"])
        self.assertFalse(rows_by_id["T-SIGNED-PRINTED"]["needs_printing"])
        self.assertFalse(rows_by_id["T-UNSIGNED"]["needs_printing"])
        self.assertEqual(captured["stats"]["to_print"], 1)

    def test_conventions_can_filter_signed_conventions_to_print(self):
        fake_data = {
            "sessions": [{
                "id": "S-APS",
                "training_type": "APS",
                "trainees": [
                    {"id": "T-TO-PRINT", "last_name": "A-IMPRIMER", "convention_signature": {"status": "done", "created_at": "2026-07-16T10:00:00Z"}},
                    {"id": "T-PRINTED", "last_name": "DEJA-IMPRIMEE", "printed": True, "convention_signature": {"status": "done", "created_at": "2026-07-16T10:00:00Z"}},
                ],
            }],
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions?status=to_print")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("A-IMPRIMER", html)
        self.assertNotIn("DEJA-IMPRIMEE", html)
        self.assertIn("À imprimer", html)
        self.assertIn("has-print-pending", html)
        self.assertIn("convPrintKpiPulse", html)
        self.assertNotIn('content:"Filtre actif"', html)


if __name__ == "__main__":
    unittest.main()
