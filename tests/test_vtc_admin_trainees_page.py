import unittest

import app as gestion_app


class AdminTraineesVtcPageTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        self.original_fetch_cnapsv3_tracking_requests = gestion_app.fetch_cnapsv3_tracking_requests
        self.data = {
            "sessions": [
                {
                    "id": "S-VTC",
                    "name": "Session VTC",
                    "training_type": "VTC",
                    "date_start": "2026-06-01",
                    "date_end": "2026-06-05",
                    "exam_theory_date": "2026-06-10",
                    "exam_practice_date": "2026-06-20",
                    "practice_training_date": "2026-06-15",
                    "trainees": [
                        {
                            "id": "T-PENDING-CMAR",
                            "last_name": "MARTIN",
                            "first_name": "Alice",
                            "email": "alice@example.test",
                            "phone": "0600000001",
                            "vtc_cmar_manual_ok": False,
                            "exam_fees_paid": False,
                            "vtc_exam_center": "nice",
                            "documents": [],
                        },
                        {
                            "id": "T-WAITING-THEORY",
                            "last_name": "DURAND",
                            "first_name": "Bruno",
                            "email": "bruno@example.test",
                            "phone": "0600000002",
                            "vtc_cmar_manual_ok": True,
                            "vtc_cmar_id": "CMAR-12345",
                            "vtc_exam_center": " Toulon ",
                            "documents": [],
                        },
                        {
                            "id": "T-THEORY-OK",
                            "last_name": "BERNARD",
                            "first_name": "Camille",
                            "email": "camille@example.test",
                            "phone": "0600000003",
                            "vtc_cmar_manual_ok": True,
                            "vtc_theory_exam_sent_at": "2026-06-11T08:00:00Z",
                            "vtc_theory_result": "success",
                            "documents": [],
                        },
                        {
                            "id": "T-PRACTICE-OK",
                            "last_name": "ROBERT",
                            "first_name": "Dana",
                            "email": "dana@example.test",
                            "phone": "0600000004",
                            "vtc_cmar_manual_ok": True,
                            "vtc_theory_exam_sent_at": "2026-06-11T08:00:00Z",
                            "vtc_theory_result": "success",
                            "vtc_practice_result": "success",
                            "documents": [],
                        },
                        {
                            "id": "T-THEORY-FAILED",
                            "last_name": "SIMON",
                            "first_name": "Eli",
                            "email": "eli@example.test",
                            "phone": "0600000005",
                            "vtc_cmar_manual_ok": True,
                            "vtc_theory_result": "non_admissible",
                            "documents": [],
                        },
                        {
                            "id": "T-PRACTICE-FAILED",
                            "last_name": "MOREAU",
                            "first_name": "Fran",
                            "email": "fran@example.test",
                            "phone": "0600000006",
                            "vtc_cmar_manual_ok": True,
                            "vtc_theory_exam_sent_at": "2026-06-11T08:00:00Z",
                            "vtc_theory_result": "success",
                            "vtc_practice_result": "non_admissible",
                            "documents": [],
                        },
                    ],
                },
                {
                    "id": "S-VTC-2",
                    "name": "Session VTC 2",
                    "training_type": "Chauffeur VTC",
                    "date_start": "2026-07-01",
                    "date_end": "2026-07-05",
                    "trainees": [
                        {
                            "id": "T-OTHER-VTC",
                            "last_name": "PETIT",
                            "first_name": "Eva",
                            "email": "eva@example.test",
                            "phone": "0600000005",
                            "documents": [],
                        }
                    ],
                },
                {
                    "id": "S-APS",
                    "name": "Session APS",
                    "training_type": "APS",
                    "trainees": [
                        {
                            "id": "T-APS",
                            "last_name": "NONVTC",
                            "first_name": "Noa",
                            "email": "noa@example.test",
                            "documents": [],
                        }
                    ],
                },
                {
                    "id": "S-VAE",
                    "name": "Session VAE",
                    "training_type": "DIRIGEANT VAE",
                    "date_start": "2026-08-01",
                    "date_end": "2026-08-05",
                    "trainees": [
                        {
                            "id": "T-VAE",
                            "last_name": "REFUS",
                            "first_name": "Nora",
                            "email": "nora@example.test",
                            "phone": "0600000007",
                            "vae_status": "livret_1_analysis",
                            "vae_action_dates": {},
                            "documents": [],
                        }
                    ],
                },
                {
                    "id": "S-VTC-ARCHIVED",
                    "name": "Session VTC archivée",
                    "training_type": "VTC",
                    "archived": True,
                    "trainees": [
                        {
                            "id": "T-ARCHIVED",
                            "last_name": "ARCHIVE",
                            "first_name": "Anne",
                            "email": "archive@example.test",
                            "documents": [],
                        }
                    ],
                },
            ]
        }

        gestion_app.load_data = lambda: self.data
        gestion_app.save_data = lambda payload: None

        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data
        gestion_app.fetch_cnapsv3_tracking_requests = self.original_fetch_cnapsv3_tracking_requests

    def test_aps_admin_trainees_shows_card_pro_followup_with_nub(self):
        self.data["sessions"][2]["trainees"][0]["pre_number"] = "2026-0002805-PRE-3P-1050370"

        response = self.client.get("/admin/sessions/S-APS/trainees")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Suivi carte pro", html)
        self.assertNotIn("https://espace-consultation.cnaps.interieur.gouv.fr/annuaire/app/annuaire-public", html)
        self.assertNotIn("🔎 Vérifier", html)
        self.assertNotIn('data-card-pro-refresh type="button" title="Rafraîchir le suivi carte pro"', html)
        self.assertIn('data-card-pro-followup', html)
        self.assertIn('data-nom="NONVTC"', html)
        self.assertIn('data-nub="1050370"', html)
        self.assertIn('data-fallback-activity="Autorisation préalable - Surveillance humaine ou gardiennage"', html)
        self.assertIn('const fallbackRows = Array.isArray(fallback.results)', html)
        self.assertIn('if(isAccepted && isCartePro)', html)
        self.assertNotIn('normalizedFallbackActivity === "AP SH"', html)
        self.assertNotIn("NUB : <strong>1050370</strong>", html)
        self.assertNotIn("Nom : <strong>NONVTC</strong>", html)
        self.assertIn('["autorisation préalable - surveillance humaine ou gardiennage", "AP SH"]', html)
        self.assertIn('["autorisation préalable - agent de protection physique des personnes", "AP A3P"]', html)
        self.assertIn('["carte professionnelle - surveillance humaine ou gardiennage", "CP SH"]', html)
        self.assertIn('["carte professionnelle - agent de protection physique des personnes", "CP A3P"]', html)
        self.assertIn(".card-pro-result.is-active", html)
        self.assertIn(".card-pro-result.is-inactive", html)
        self.assertIn(".card-pro-result.is-unknown", html)
        self.assertIn('.card-pro-result__date{display:inline', html)
        self.assertIn('.card-pro-result__chip.is-cp,.card-pro-result__chip.is-ap{background:#16a34a', html)
        self.assertIn('Expire le ${escapeHtml(formatCnapsDateFr(title.date_fin_validite||title.valid_until))}', html)
        self.assertIn('Expire le ${escapeHtml(formatCnapsDateFr(row.date_validite_titre))}', html)

    def test_aps_admin_trainees_uses_suivi_cnaps_nub_when_pre_number_missing(self):
        trainee = self.data["sessions"][2]["trainees"][0]
        trainee["last_name"] = "Dupont"
        trainee["first_name"] = "Noa"
        trainee.pop("pre_number", None)
        gestion_app.fetch_cnapsv3_tracking_requests = lambda: ([{
            "last_name": "DUPONT",
            "first_name": "Noa",
            "nub": "1050370",
            "cnaps_status": "TRANSMIS",
        }], None)

        response = self.client.get("/admin/sessions/S-APS/trainees")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-nom="DUPONT"', html)
        self.assertIn('data-nub="1050370"', html)
        self.assertEqual(trainee["cnaps_tracking_nub"], "1050370")
        self.assertNotIn("NUB manquant", html)

    def test_aps_admin_trainees_forces_chiocca_ap_sh_active_by_name_and_nub(self):
        trainee = self.data["sessions"][2]["trainees"][0]
        trainee["last_name"] = "CHIOCCA"
        trainee["first_name"] = "Laurine"
        trainee["pre_number"] = "1079213"
        trainee["cnaps"] = "INCONNU"

        response = self.client.get("/admin/sessions/S-APS/trainees")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-nom="CHIOCCA"', html)
        self.assertIn('data-nub="1079213"', html)
        self.assertIn('normalizedLastName === "CHIOCCA" && normalizedNub === "1079213"', html)
        self.assertIn('validite_titre: "ACTIF"', html)

    def test_aps_admin_trainee_sheet_loads_annuaire_followup_without_static_cp_chip(self):
        trainee = self.data["sessions"][2]["trainees"][0]
        trainee["pre_number"] = "2026-0002805-PRE-3P-1050370"
        trainee["cnaps"] = "ACCEPTÉ"

        response = self.client.get("/admin/sessions/S-APS/stagiaires/T-APS")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-label="Suivi carte professionnelle CNAPS"', html)
        self.assertIn('data-trainee-card-pro-followup', html)
        self.assertIn('data-trainee-card-pro-result', html)
        self.assertIn('Chargement CNAPS…', html)
        self.assertIn('.trainee-cnaps-followup__chip.is-cp,.trainee-cnaps-followup__chip.is-ap{background:#16a34a', html)
        self.assertIn('Expire le ${escapeHtml(formatCnapsDateFr(title.date_fin_validite||title.valid_until))}', html)
        self.assertIn('Expire le ${escapeHtml(formatCnapsDateFr(row.date_validite_titre))}', html)
        self.assertNotIn('title="Carte professionnelle - Surveillance humaine ou gardiennage • ACTIF"', html)

    def test_vtc_admin_trainee_sheet_uses_compact_profile_layout(self):
        trainee = self.data["sessions"][0]["trainees"][1]
        trainee["vtc_real_training_dates"] = "10/06/2026 au 12/06/2026"

        response = self.client.get("/admin/sessions/S-VTC/stagiaires/T-WAITING-THEORY")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('class="trainee-vtc-training-dates"', html)
        self.assertIn('class="mono trainee-vtc-training-dates__field"', html)
        self.assertIn("✉️ Envoyer un e-mail", html)
        self.assertNotIn("✉️ bruno@example.test", html)

    def test_aps_admin_trainee_sheet_recovers_tracking_nub_when_opened_directly(self):
        trainee = self.data["sessions"][2]["trainees"][0]
        trainee["last_name"] = "Dupont"
        trainee["first_name"] = "Noa"
        trainee.pop("pre_number", None)
        gestion_app.fetch_cnapsv3_tracking_requests = lambda: ([{
            "last_name": "DUPONT",
            "first_name": "Noa",
            "nub": "1050370",
            "cnaps_status": "TRANSMIS",
        }], None)

        response = self.client.get("/admin/sessions/S-APS/stagiaires/T-APS")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(trainee["cnaps_tracking_nub"], "1050370")
        self.assertIn("NUB : 1050370", html)
        self.assertIn('data-trainee-card-pro-followup', html)
        self.assertIn('data-nub="1050370"', html)
        self.assertIn("Chargement CNAPS…", html)


    def test_cnaps_public_annuaire_api_returns_activity_and_validity(self):
        original_fetch = gestion_app.fetch_cnaps_public_annuaire
        gestion_app.fetch_cnaps_public_annuaire = lambda nom, nub: {
            "activite": "Autorisation préalable - Surveillance humaine ou gardiennage",
            "validite_titre": "ACTIF",
            "date_validite_titre": "16/08/2026",
        }
        try:
            response = self.client.get("/api/cnaps_public_annuaire?nom=OUFQIH&nub=0971426")
        finally:
            gestion_app.fetch_cnaps_public_annuaire = original_fetch

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["activite"], "Autorisation préalable - Surveillance humaine ou gardiennage")
        self.assertEqual(response.json["validite_titre"], "ACTIF")
        self.assertEqual(response.json["date_validite_titre"], "16/08/2026")

    def test_nub_is_extracted_from_legacy_pre_car_format(self):
        self.assertEqual(
            gestion_app.extract_nub_from_pre_car("PRE-013-2029-07-25-20240908920"),
            "0908920",
        )
        self.assertEqual(
            gestion_app.extract_nub_from_pre_car("2026-0002805-CAR-3P-1050370"),
            "1050370",
        )


    def test_history_and_thread_columns_are_reserved_for_vae_sessions(self):
        vae_response = self.client.get("/admin/sessions/S-VAE/trainees")
        vtc_response = self.client.get("/admin/sessions/S-VTC/trainees")
        aps_response = self.client.get("/admin/sessions/S-APS/trainees")

        self.assertEqual(vae_response.status_code, 200)
        self.assertEqual(vtc_response.status_code, 200)
        self.assertEqual(aps_response.status_code, 200)

        vae_html = vae_response.get_data(as_text=True)
        self.assertIn('<th class="col-history">Historique</th>', vae_html)
        self.assertIn('<th class="col-thread">Fil actu</th>', vae_html)
        self.assertIn('class="mini-btn history-btn" data-open-history', vae_html)
        self.assertIn('class="mini-btn thread-btn" data-open-thread', vae_html)

        for html in (
            vtc_response.get_data(as_text=True),
            aps_response.get_data(as_text=True),
        ):
            self.assertNotIn('<th class="col-history">Historique</th>', html)
            self.assertNotIn('<th class="col-thread">Fil actu</th>', html)
            self.assertNotIn('class="mini-btn history-btn" data-open-history', html)
            self.assertNotIn('class="mini-btn thread-btn" data-open-thread', html)

    def test_vae_admin_trainees_exposes_live_card_and_modal(self):
        response = self.client.get("/admin/sessions/S-VAE/trainees")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="vaeLiveCard"', html)
        self.assertIn('LIVE', html)
        self.assertIn('id="vaeLiveModal"', html)
        self.assertIn('/vae-live-notifications', html)
        self.assertIn('vaeLiveCard.disabled = total === 0', html)
        self.assertIn('class="vae-live-content"', html)

    def test_vae_admin_trainees_exposes_non_recevable_status_after_livret_1_analysis(self):
        response = self.client.get("/admin/sessions/S-VAE/trainees")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertLess(
            html.index("value=\"livret_1_analysis\">Livret 1 en cours d'analyse</option>"),
            html.index('value="non_recevable">Non recevable</option>'),
        )
        self.assertLess(
            html.index('value="non_recevable">Non recevable</option>'),
            html.index('value="livret_1_validated">Livret 1 validé</option>'),
        )
        self.assertIn('status === "non_recevable" || scotiaStatus === "non_recevable"', html)

        update = self.client.post(
            "/api/sessions/S-VAE/stagiaires/T-VAE/update",
            json={"vae_status": "non_recevable"},
        )

        trainee = self.data["sessions"][3]["trainees"][0]
        self.assertEqual(update.status_code, 200)
        self.assertEqual(trainee["vae_status"], "non_recevable")
        self.assertEqual(trainee["vae_status_label"], "Non recevable")

        refreshed = self.client.get("/admin/sessions/S-VAE/trainees")
        refreshed_html = refreshed.get_data(as_text=True)
        self.assertIn(
            'value="non_recevable" selected>Non recevable</option>',
            refreshed_html,
        )

    def test_vtc_status_labels_and_exam_center_controls_render(self):
        response = self.client.get("/admin/sessions/S-VTC/trainees")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Centre examen", html)
        self.assertIn("Légende centre examen", html)
        self.assertIn("Nice = ligne verte", html)
        self.assertIn("Toulon = ligne bleue", html)
        self.assertIn('value="nice"', html)
        self.assertIn('value="toulon"', html)
        self.assertIn('row-vtc-nice', html)
        self.assertIn('row-vtc-toulon', html)
        self.assertIn('data-vtc-exam-center="toulon"', html)
        self.assertIn('value="toulon"\n                     checked', html)
        self.assertIn('data-vtc-cmar-ok="0"', html)
        self.assertIn('data-vtc-cmar-ok="1"', html)
        self.assertIn("data-vtc-theory-label", html)
        self.assertIn("data-vtc-practice-label", html)
        self.assertIn("function refreshVtcStatusLabels", html)
        self.assertIn('id="vtcTheoryFilter"', html)
        self.assertIn('id="vtcPracticeFilter"', html)
        self.assertIn("Tous les statuts théorie", html)
        self.assertIn("Tous les statuts pratique", html)
        self.assertIn('value="waiting_theory">En attente réussite théorie</option>', html)
        self.assertIn('const { theoryStatus, practiceStatus } = getVtcStatusValues(tr);', html)
        self.assertIn('const matchPractice = selectedPractice === "all" || practiceStatus === selectedPractice;', html)
        self.assertIn("function bindImmediateRowFilters", html)
        self.assertIn('event.target?.matches?.("#vaeStatusFilter, #vtcTheoryFilter, #vtcPracticeFilter")', html)
        self.assertIn('field === "vtc_cmar_manual_ok"', html)
        self.assertIn('data-vtc-exam-status-trigger="theory"', html)
        self.assertIn('data-vtc-exam-status-trigger="practice"', html)
        self.assertIn('data-vtc-exam-status-menu="theory"', html)
        self.assertIn('data-vtc-exam-status-menu="practice"', html)
        self.assertIn("function positionVtcStatusMenu(trigger, menu)", html)
        self.assertIn('position:fixed;', html)
        self.assertIn('trigger.setAttribute("aria-expanded", "true")', html)
        self.assertIn('data-field="vtc_theory_status_manual"', html)
        self.assertIn('data-field="vtc_practice_status_manual"', html)
        self.assertIn('data-vtc-exam-status-choice="success"', html)
        self.assertNotIn('>Auto</option>', html)
        self.assertIn("En attente inscription examen", html)
        self.assertIn("En attente résultats examen", html)
        self.assertIn("En attente réussite théorie", html)
        self.assertIn(
            'class="vtc-status-label vtc-status-yellow" data-vtc-practice-label data-vtc-exam-status-trigger="practice"',
            html,
        )
        self.assertIn("En attente réussite théorie</button>", html)
        self.assertIn("Examen théorique réussi", html)
        self.assertIn("En attente résultats pratique", html)
        self.assertIn("Examen pratique réussi", html)
        self.assertIn("Echec examen théorique", html)
        self.assertIn("Echec examen pratique", html)
        self.assertIn("vtc-status-black", html)
        self.assertIn("Identifiant CMAR inconnu", html)
        self.assertEqual(html.count("Identifiant CMAR inconnu"), 5)
        self.assertIn('setVtcStatusLabel(tr.querySelector("[data-vtc-theory-label]"), "Echec examen théorique", "black")', html)
        self.assertIn('setVtcStatusLabel(tr.querySelector("[data-vtc-practice-label]"), "Echec examen pratique", "black")', html)
        self.assertIn('setVtcStatusLabel(tr.querySelector("[data-vtc-practice-label]"), "En attente réussite théorie", "yellow")', html)
        self.assertNotIn('setVtcStatusLabel(tr.querySelector("[data-vtc-practice-label]"), "En attente réussite théorie", "red")', html)
        self.assertNotIn("Date d'examen théorique : 10/06/2026\">🔴", html)
        self.assertNotIn("Date d'examen théorique : 10/06/2026\">🟡", html)
        self.assertNotIn("Date d'examen théorique : 10/06/2026\">🟢", html)

    def test_vtc_exam_center_can_be_saved(self):
        response = self.client.post(
            "/api/sessions/S-VTC/stagiaires/T-WAITING-THEORY/update",
            json={"vtc_exam_center": "nice"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.data["sessions"][0]["trainees"][1]["vtc_exam_center"],
            "nice",
        )

    def test_vtc_exam_statuses_can_be_saved_manually(self):
        response = self.client.post(
            "/api/sessions/S-VTC/stagiaires/T-WAITING-THEORY/update",
            json={
                "vtc_theory_status_manual": "failed",
                "vtc_practice_status_manual": "waiting_theory",
            },
        )

        self.assertEqual(response.status_code, 200)
        trainee = self.data["sessions"][0]["trainees"][1]
        self.assertEqual(trainee["vtc_theory_status_manual"], "failed")
        self.assertEqual(trainee["vtc_theory_result"], "non_admissible")
        self.assertEqual(trainee["vtc_theory_exam_sent_at"], "")
        self.assertEqual(trainee["vtc_practice_status_manual"], "waiting_theory")
        self.assertEqual(trainee["vtc_practice_result"], "")

        refreshed = self.client.get("/admin/sessions/S-VTC/trainees")

        self.assertEqual(refreshed.status_code, 200)
        html = refreshed.get_data(as_text=True)
        self.assertIn('data-vtc-theory-status-manual="failed"', html)
        self.assertIn('data-vtc-practice-status-manual="waiting_theory"', html)
        self.assertIn("Echec examen théorique</button>", html)
        self.assertIn("En attente réussite théorie</button>", html)

    def test_vtc_manual_exam_status_persists_on_all_vtc_page_refresh(self):
        response = self.client.post(
            "/api/sessions/S-VTC/stagiaires/T-THEORY-OK/update",
            json={"vtc_theory_status_manual": "waiting_result"},
        )

        self.assertEqual(response.status_code, 200)
        trainee = self.data["sessions"][0]["trainees"][2]
        self.assertEqual(trainee["vtc_theory_status_manual"], "waiting_result")
        self.assertEqual(trainee["vtc_theory_exam_sent_at"], "")

        refreshed = self.client.get("/admin/trainees/vtc")

        self.assertEqual(refreshed.status_code, 200)
        self.assertIn("no-store", refreshed.headers.get("Cache-Control", ""))
        html = refreshed.get_data(as_text=True)
        self.assertIn('data-vtc-theory-status-manual="waiting_result"', html)
        self.assertIn("En attente résultats examen</button>", html)

    def test_vtc_manual_exam_statuses_drive_stats(self):
        self.data["sessions"][0]["trainees"][0]["vtc_theory_status_manual"] = "success"
        self.data["sessions"][0]["trainees"][0]["vtc_practice_status_manual"] = "failed"

        stats = gestion_app.compute_vtc_exam_stats(self.data["sessions"][0]["trainees"])

        self.assertEqual(stats["theory_success"], 4)
        self.assertEqual(stats["practice_failed"], 2)

    def test_sessions_filters_link_to_all_vtc_trainees(self):
        response = self.client.get("/admin/sessions")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Voir tous les stagiaires VTC", html)
        self.assertIn('href="/admin/trainees/vtc"', html)

    def test_all_vtc_trainees_page_lists_active_vtc_sessions(self):
        response = self.client.get("/admin/trainees/vtc")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Tous les stagiaires VTC", html)
        self.assertIn("Session VTC", html)
        self.assertIn("Session VTC 2", html)
        self.assertIn("MARTIN", html)
        self.assertIn("PETIT", html)
        self.assertIn("Prénom", html)
        self.assertIn('class="col-first-name"', html)
        self.assertIn("Théorie réussie", html)
        self.assertIn("Pratique réussie", html)
        self.assertNotIn("Conformes", html)
        self.assertNotIn("CNAPS acceptés", html)
        self.assertNotIn("Session</div>", html)
        self.assertNotIn("NONVTC", html)
        self.assertNotIn("ARCHIVE", html)
        self.assertIn('data-session-id="S-VTC"', html)
        self.assertIn('data-session-id="S-VTC-2"', html)
        self.assertIn('/admin/sessions/S-VTC-2/stagiaires/T-OTHER-VTC', html)
        self.assertEqual(html.count("Identifiant CMAR inconnu"), 6)
