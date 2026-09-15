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
            response = self.client.get("/admin/sessions/conventions?status=")

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
            response = self.client.get("/admin/sessions/conventions?status=")

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
            response = self.client.get("/admin/sessions/conventions?status=")

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
            response = self.client.get("/admin/sessions/conventions?status=")

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
            response = self.client.get("/admin/sessions/conventions?status=")

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
            response = self.client.get("/admin/sessions/conventions?status=")

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
            response = self.client.get("/admin/sessions/conventions?status=")

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
                            "convention_signature": {
                                "status": "done",
                                "created_at": "2026-07-16T09:00:00Z",
                                "signed_at": "2026-07-16T10:00:00Z",
                            },
                        }
                    ],
                }
            ]
        }
        saved_payloads = []

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data", side_effect=lambda data: saved_payloads.append(data)):
            api_response = self.client.get("/api/conventions_signed_unseen")
            page_response = self.client.get("/admin/sessions/conventions?status=")
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
                            "convention_signature": {
                                "status": "done",
                                "created_at": "2026-07-16T09:00:00Z",
                                "signed_at": "2026-07-16T10:00:00Z",
                            },
                        }
                    ],
                }
            ]
        }
        saved_payloads = []

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data", side_effect=lambda data: saved_payloads.append(data)):
            api_response = self.client.get("/api/conventions_signed_unseen")
            page_response = self.client.get("/admin/sessions/conventions?status=")
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

    def test_signed_conventions_badge_counts_recent_conventions_in_older_sessions(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-LONG-RUNNING",
                    "name": "Formation annuelle",
                    "training_type": "DESP",
                    "date_start": "2026-01-01",
                    "date_end": "2026-12-31",
                    "trainees": [
                        {
                            "id": "T-RECENT-1",
                            "convention_signature": {
                                "status": "done",
                                "created_at": "2026-07-27T13:27:00Z",
                                "signed_at": "2026-07-27T13:38:00Z",
                            },
                        },
                        {
                            "id": "T-RECENT-2",
                            "convention_signature": {
                                "status": "done",
                                "created_at": "2026-07-27T14:43:00Z",
                                "signed_at": "2026-07-27T14:54:00Z",
                            },
                        },
                    ],
                }
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/api/conventions_signed_unseen")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["count"], 2)
        self.assertEqual(
            {item["trainee_id"] for item in response.get_json()["items"]},
            {"T-RECENT-1", "T-RECENT-2"},
        )


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
            response = self.client.get("/admin/sessions/conventions?status=")

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
        self.assertLess(html.index("À imprimer"), html.index("Total"))
        self.assertNotIn("<span>Documents</span>", html)

    def test_conventions_default_to_the_print_queue(self):
        fake_data = {
            "sessions": [{
                "id": "S-APS",
                "training_type": "APS",
                "trainees": [
                    {"id": "T-TO-PRINT", "last_name": "A-IMPRIMER", "convention_signature": {"status": "done", "created_at": "2026-07-16T10:00:00Z"}},
                    {"id": "T-UNSIGNED", "last_name": "A-SIGNER", "convention_status": "signing"},
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
        self.assertEqual(captured["selected_status_effective"], "to_print")
        self.assertEqual([row["trainee_id"] for row in captured["rows"]], ["T-TO-PRINT"])

    def test_explicit_empty_status_still_displays_all_conventions(self):
        fake_data = {
            "sessions": [{
                "id": "S-APS",
                "training_type": "APS",
                "trainees": [{"id": "T-UNSIGNED", "last_name": "A-SIGNER", "convention_status": "signing"}],
            }],
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions?status=")

        self.assertEqual(response.status_code, 200)
        self.assertIn("A-SIGNER", response.get_data(as_text=True))

    def test_empty_print_kpi_is_disabled_and_has_no_filter_link(self):
        fake_data = {
            "sessions": [{
                "id": "S-APS",
                "training_type": "APS",
                "trainees": [{
                    "id": "T-PRINTED",
                    "last_name": "DEJA-IMPRIMEE",
                    "printed": True,
                    "convention_signature": {"status": "done", "created_at": "2026-07-16T10:00:00Z"},
                }],
            }],
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data):
            response = self.client.get("/admin/sessions/conventions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('class="conv-kpi is-disabled" aria-disabled="true"', html)
        self.assertIn("aucune convention à imprimer", html)
        self.assertNotIn('href="/admin/sessions/conventions?status=to_print"', html)

    def test_cancelled_legacy_convention_remains_searchable_without_creation_date(self):
        trainee = {
            "id": "T-CANCELLED-LEGACY",
            "last_name": "ANNULEE",
            "convention_status": "signed",
            "convention_legacy_signed": True,
            "convention_legacy_signed_at": "2026-07-21T08:24:00Z",
            "registration_cancelled": True,
            "registration_cancelled_at": "2026-09-07T03:29:00Z",
            "printed": True,
        }
        fake_data = {"sessions": [{"id": "S-APS", "training_type": "APS", "trainees": [trainee]}]}
        for query in ("q=ANNULEE", "q=T-CANCELLED-LEGACY", "status=", "status=registration_cancelled"):
            with self.subTest(query=query), \
                 patch.object(gestion_app, "load_data", return_value=fake_data), \
                 patch.object(gestion_app, "save_data") as save, \
                 patch.object(gestion_app, "_refresh_yousign_convention_status_if_pending") as refresh:
                response = self.client.get(f"/admin/sessions/conventions?{query}")

            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn("ANNULEE", html)
            self.assertIn("Inscription annulée", html)
            self.assertIn("07/09/2026", html)
            self.assertIn("PDF signé non rattaché", html)
            self.assertIn("Signée via ancien logiciel", html)
            self.assertIn("/T-CANCELLED-LEGACY/convention/signed-pdf?download=1", html)
            self.assertNotIn('method="post"', html)
            self.assertNotIn('data-trainee-id="T-CANCELLED-LEGACY"', html)
            self.assertNotIn("PDF final disponible", html)
            refresh.assert_not_called()
            save.assert_not_called()
            self.assertTrue(trainee["registration_cancelled"])

    def test_cancelled_conventions_are_kept_out_of_operational_queues(self):
        fake_data = {"sessions": [{"id": "S-APS", "training_type": "APS", "trainees": [
            {"id": "T-ACTIVE", "convention_signature": {"status": "done", "created_at": "2026-07-16T10:00:00Z"}},
            {"id": "T-CANCELLED-SIGNED", "registration_cancelled": True,
             "convention_signature": {"status": "done", "created_at": "2026-07-16T10:00:00Z"}},
            {"id": "T-CANCELLED-NO-PDF", "inscription_annulee": "oui"},
        ]}]}
        captured = {}

        def fake_render_template(template_name, **context):
            captured.update(context)
            return "OK"

        for query, expected in (("", ["T-ACTIVE"]), ("?status=action_required", []),
                                ("?status=registration_cancelled", ["T-CANCELLED-SIGNED", "T-CANCELLED-NO-PDF"])):
            with self.subTest(query=query), \
                 patch.object(gestion_app, "load_data", return_value=fake_data), \
                 patch.object(gestion_app, "render_template", side_effect=fake_render_template), \
                 patch.object(gestion_app, "_refresh_yousign_convention_status_if_pending", return_value=False):
                response = self.client.get(f"/admin/sessions/conventions{query}")

            self.assertEqual(response.status_code, 200)
            self.assertEqual({row["trainee_id"] for row in captured["rows"]}, set(expected))
            self.assertEqual(captured["stats"]["total"], 3)
            self.assertEqual(captured["stats"]["to_print"], 1)
            self.assertEqual(captured["stats"]["action_required"], 0)
            for row in captured["rows"]:
                if row["registration_cancelled"]:
                    self.assertFalse(row["can_send"])
                    self.assertFalse(row["can_remind"])
                    self.assertFalse(row["needs_printing"])

    def test_cancelled_pending_and_early_vae_conventions_remain_read_only(self):
        fake_data = {"sessions": [{"id": "S-VAE", "training_type": "DIRIGEANT VAE", "trainees": [{
            "id": "T-CANCELLED-PENDING",
            "last_name": "ANNULEE-EN-ATTENTE",
            "registration_canceled": "true",
            "vae_status": "livret_1_validated",
            "convention_signature": {"status": "ongoing", "signature_request_id": "request-1",
                                     "signature_link": "https://example.test/sign"},
        }]}]}
        with patch.object(gestion_app, "load_data", return_value=fake_data), \
             patch.object(gestion_app, "_refresh_yousign_convention_status_if_pending") as refresh:
            response = self.client.get("/admin/sessions/conventions?status=registration_cancelled")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("ANNULEE-EN-ATTENTE", html)
        self.assertNotIn('method="post"', html)
        self.assertNotIn('data-copy-signature-link="https://example.test/sign"', html)
        refresh.assert_not_called()

    def test_search_can_find_a_printed_historical_convention_with_explicit_status_preserved(self):
        fake_data = {"sessions": [{"id": "S-APS", "training_type": "APS", "trainees": [{
            "id": "T-HISTORY", "last_name": "HISTORIQUE", "printed": True,
            "convention_signature": {"status": "done", "created_at": "2026-06-01T10:00:00Z"},
        }]}]}
        with patch.object(gestion_app, "load_data", return_value=fake_data):
            search_response = self.client.get("/admin/sessions/conventions?q=HISTORIQUE")
            queue_response = self.client.get("/admin/sessions/conventions?q=HISTORIQUE&status=to_print")

        self.assertEqual(search_response.status_code, 200)
        self.assertIn("/T-HISTORY", search_response.get_data(as_text=True))
        self.assertEqual(queue_response.status_code, 200)
        self.assertNotIn("/T-HISTORY", queue_response.get_data(as_text=True))

    def test_search_counts_only_matching_records_without_reopening_historical_print_queue(self):
        fake_data = {"sessions": [{"id": "S-APS", "training_type": "APS", "trainees": [
            {"id": "T-CANCELLED", "last_name": "ANNULEE", "registration_cancelled": True,
             "convention_signature": {"status": "done"}},
            {"id": "T-HISTORY", "last_name": "HISTORIQUE",
             "convention_signature": {"status": "done", "created_at": "2026-06-01T10:00:00Z"}},
            {"id": "T-UNRELATED", "last_name": "AUTRE",
             "convention_signature": {"status": "ongoing", "signature_request_id": "request-other"}},
        ]}]}
        captured = {}

        def fake_render_template(template_name, **context):
            captured.update(context)
            return "OK"

        for query, expected in (("q=ANNULEE", ["T-CANCELLED"]),
                                ("q=HISTORIQUE", ["T-HISTORY"]),
                                ("q=HISTORIQUE&status=to_print", [])):
            with self.subTest(query=query), \
                 patch.object(gestion_app, "load_data", return_value=fake_data), \
                 patch.object(gestion_app, "render_template", side_effect=fake_render_template), \
                 patch.object(gestion_app, "_refresh_yousign_convention_status_if_pending", return_value=False) as refresh:
                response = self.client.get(f"/admin/sessions/conventions?{query}")

            self.assertEqual(response.status_code, 200)
            self.assertEqual([row["trainee_id"] for row in captured["rows"]], expected)
            self.assertEqual(captured["stats"]["total"], 1)
            self.assertEqual(captured["stats"]["signed"], 1)
            self.assertEqual(captured["stats"]["to_print"], 0)
            self.assertEqual(captured["stats"]["waiting_signature"], 0)
            self.assertEqual(captured["stats"]["action_required"], 0)
            self.assertTrue(all(call.args[3]["id"] != "T-UNRELATED" for call in refresh.call_args_list))


if __name__ == "__main__":
    unittest.main()
