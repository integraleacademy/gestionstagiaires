import copy
import datetime
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gestion_app


class RegistrationCancellationTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    @staticmethod
    def _session():
        today = datetime.date.today().isoformat()
        return {
            "id": "S-CANCEL",
            "name": "Session APS",
            "training_type": "APS",
            "date_start": today,
            "date_end": today,
            "trainees": [
                {
                    "id": "T-ACTIVE",
                    "first_name": "Alice",
                    "last_name": "Active",
                    "created_at": today,
                    "training_price": 1000,
                    "sales_tracking_amount": 1000,
                    "personal_amount": 1000,
                    "documents": [],
                },
                {
                    "id": "T-CANCELLED",
                    "first_name": "Camille",
                    "last_name": "Annulee",
                    "created_at": today,
                    "training_price": 9000,
                    "sales_tracking_amount": 9000,
                    "personal_amount": 9000,
                    "registration_cancelled": True,
                    "documents": [],
                },
            ],
        }

    def test_cancelled_registration_is_excluded_from_counts_sales_and_finance(self):
        session = self._session()

        stats = gestion_app.compute_stats(session)
        finance = gestion_app._admin_trainees_finance_summary(session, session["trainees"])
        cancelled_finance = gestion_app.calculate_trainee_financial_summary(
            session["trainees"][1],
            [{"traineeId": "T-CANCELLED", "amount": 9000}],
        )
        with gestion_app.app.test_request_context():
            sales = gestion_app._build_sales_tracking_metrics(
                {"sessions": [session]}, datetime.date.today().year
            )

        self.assertEqual(stats["total"], 1)
        self.assertEqual(finance["trainees_count"], 1)
        self.assertEqual(finance["revenue"], 1000)
        self.assertEqual(sales["annual_inscriptions"], 1)
        self.assertEqual(sales["annual_revenue"], 1000)
        self.assertEqual(sales["sales_count"], 1)
        self.assertTrue(cancelled_finance["registration_cancelled"])
        self.assertEqual(cancelled_finance["planned_total_cents"], 0)
        self.assertEqual(cancelled_finance["paid_total_cents"], 0)
        self.assertEqual(cancelled_finance["remaining_total_cents"], 0)

    def test_update_endpoint_keeps_record_and_closes_open_notifications(self):
        session = self._session()
        session["trainees"][1]["registration_cancelled"] = False
        data = {
            "sessions": [session],
            "notifications_admin": [
                {
                    "id": "N1",
                    "label": "Action stagiaire",
                    "done": False,
                    "meta": {"session_id": "S-CANCEL", "trainee_id": "T-CANCELLED"},
                }
            ],
        }
        saved = None

        def capture(payload):
            nonlocal saved
            saved = copy.deepcopy(payload)

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data", side_effect=capture
        ):
            response = self.client.post(
                "/api/sessions/S-CANCEL/stagiaires/T-CANCELLED/update",
                json={"registration_cancelled": True},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["registration_cancelled"])
        self.assertTrue(payload["registration_cancelled_at"])
        self.assertEqual(len(saved["sessions"][0]["trainees"]), 2)
        cancelled = saved["sessions"][0]["trainees"][1]
        self.assertTrue(cancelled["registration_cancelled"])
        self.assertTrue(cancelled["registration_cancelled_at"])
        self.assertTrue(saved["notifications_admin"][0]["done"])
        self.assertEqual(saved["notifications_admin"][0]["resolution"], "Inscription annulée")

    def test_cancelled_billing_line_is_retained_but_cannot_generate_invoice(self):
        session = self._session()
        session["trainees"] = [session["trainees"][1]]
        line = gestion_app.buildBillingLinesFromSessions([session])[0]
        data = {"sessions": [session], "billing_lines": [line]}

        self.assertTrue(line["registrationCancelled"])
        with patch.object(gestion_app, "save_data"):
            ok, result = gestion_app._create_invoice_for_billing_line(data, line)

        self.assertFalse(ok)
        self.assertTrue(result["ignored"])
        self.assertIn("inscription est annulée", result["message"])

    def test_cancelled_registration_blocks_new_sepa_actions(self):
        session = self._session()
        session["trainees"] = [session["trainees"][1]]
        line = gestion_app.buildBillingLinesFromSessions([session])[0]
        line.update({
            "paymentMode": "sepa_direct_debit",
            "sign_url": "https://example.test/sign",
        })
        data = {"sessions": [session], "billing_lines": [line]}

        skipped = gestion_app.ensure_qonto_sepa_installments_for_line(line)
        self.assertTrue(skipped["registration_cancelled"])
        self.assertEqual(skipped["created"], 0)

        future_date = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            resend = self.client.post(
                "/api/billing/resend-mandate", json={"lineId": line["id"]}
            )
            create = self.client.post(
                "/api/billing/create-mandate", json={"lineId": line["id"]}
            )
            reschedule = self.client.post(
                "/api/billing/reschedule-rejected-debit",
                json={"lineId": line["id"], "collectionDate": future_date},
            )

        self.assertEqual(resend.status_code, 409)
        self.assertEqual(create.status_code, 409)
        self.assertEqual(reschedule.status_code, 409)

    def test_cancelled_registration_can_be_reactivated(self):
        data = {"sessions": [self._session()]}
        trainee = data["sessions"][0]["trainees"][1]
        trainee["registration_cancelled_at"] = "2026-08-31T12:00:00Z"

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/api/sessions/S-CANCEL/stagiaires/T-CANCELLED/update",
                json={"registration_cancelled": False},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["registration_cancelled"])
        self.assertEqual(trainee["registration_cancelled_at"], "")
        self.assertEqual(gestion_app.compute_stats(data["sessions"][0])["total"], 2)

    @staticmethod
    def _indemnity_case():
        trainee = {
            "id": "T-INDEMNITY",
            "first_name": "Alex",
            "last_name": "Test",
            "email": "alex@example.com",
            "registration_cancelled": True,
            "registration_cancelled_at": "2026-09-30T10:00:00Z",
            "training_price": 4200,
            "cpf_amount": 2940,
            "personal_amount": 1260,
        }
        session = {
            "id": "S-INDEMNITY",
            "name": "APS + SSIAP",
            "training_type": "AFC APS + SSIAP",
            "date_start": "2026-11-01",
            "date_end": "2026-12-31",
            "trainees": [trainee],
        }
        lines = [{
            "id": gestion_app._billing_line_id(
                session["id"], trainee["id"], "PERSONNEL", "legacy"
            ),
            "traineeId": trainee["id"],
            "sessionId": session["id"],
            "financingType": "PERSONNEL",
            "amount": 1260,
            "directDebitInstallments": [
                {"amount": 420, "status": "completed", "schedule_index": 1}
            ],
        }]
        return session, trainee, lines

    def test_indemnity_calculator_matches_contract_and_financing_example(self):
        session, trainee, lines = self._indemnity_case()

        result = gestion_app.calculate_registration_cancellation_indemnity(
            session,
            trainee,
            lines,
            cancellation_date="2026-09-30",
        )

        self.assertEqual(result["rule_key"], "more_than_one_month")
        self.assertEqual(result["penalty_rate"], 10.0)
        self.assertEqual(result["training_price_cents"], 420000)
        self.assertEqual(result["cpf_amount_cents"], 294000)
        self.assertEqual(result["personal_paid_cents"], 42000)
        self.assertEqual(result["deductible_paid_cents"], 42000)
        self.assertEqual(result["penalty_cents"], 42000)
        self.assertEqual(result["balance_due_cents"], 0)
        self.assertEqual(result["balance_status"], "settled")

    def test_indemnity_calculator_applies_every_date_band(self):
        session, trainee, lines = self._indemnity_case()
        cases = (
            ("2026-10-01", "between_one_month_and_two_weeks", 20.0, 84000),
            ("2026-10-18", "between_one_month_and_two_weeks", 20.0, 84000),
            ("2026-10-19", "less_than_two_weeks", 30.0, 126000),
        )

        for cancellation_date, rule_key, rate, penalty_cents in cases:
            with self.subTest(cancellation_date=cancellation_date):
                result = gestion_app.calculate_registration_cancellation_indemnity(
                    session,
                    trainee,
                    lines,
                    cancellation_date=cancellation_date,
                )
                self.assertEqual(result["rule_key"], rule_key)
                self.assertEqual(result["penalty_rate"], rate)
                self.assertEqual(result["penalty_cents"], penalty_cents)

    def test_indemnity_calculator_adds_training_prorata_during_course(self):
        session, trainee, lines = self._indemnity_case()

        result = gestion_app.calculate_registration_cancellation_indemnity(
            session,
            trainee,
            lines,
            cancellation_date="2026-11-10",
            total_training_hours="100",
            delivered_hours="25",
        )

        self.assertEqual(result["rule_key"], "during_training")
        self.assertTrue(result["calculation_complete"])
        self.assertEqual(result["penalty_cents"], 126000)
        self.assertEqual(result["prorata_cents"], 105000)
        self.assertEqual(result["total_due_cents"], 231000)
        self.assertEqual(result["balance_due_cents"], 189000)

    def test_indemnity_calculator_requires_actual_hours_during_course(self):
        session, trainee, lines = self._indemnity_case()

        result = gestion_app.calculate_registration_cancellation_indemnity(
            session,
            trainee,
            lines,
            cancellation_date="2026-11-10",
        )

        self.assertFalse(result["calculation_complete"])
        self.assertEqual(result["total_training_hours"], 393.0)
        self.assertIsNone(result["delivered_hours"])

    def test_indemnity_api_is_available_only_after_cancellation(self):
        session, trainee, lines = self._indemnity_case()
        data = {"sessions": [session], "billing_lines": lines}
        url = (
            "/api/sessions/S-INDEMNITY/stagiaires/T-INDEMNITY/"
            "cancellation-indemnity?cancellation_date=2026-09-30"
        )

        with patch.object(gestion_app, "load_data", return_value=data):
            response = self.client.get(url)
            trainee["registration_cancelled"] = False
            blocked = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(response.get_json()["calculation"]["balance_due_cents"], 0)
        self.assertEqual(blocked.status_code, 409)

    def test_cancellation_email_builder_matches_the_calculation_and_contract(self):
        session, trainee, lines = self._indemnity_case()
        calculation = gestion_app.calculate_registration_cancellation_indemnity(
            session,
            trainee,
            lines,
            cancellation_date="2026-09-30",
        )

        subject, html_body, text_body = gestion_app.build_registration_cancellation_email(
            session, trainee, calculation
        )

        self.assertIn("Suite à votre demande d’annulation", subject)
        self.assertIn("Article 9", html_body)
        self.assertIn("Règle appliquée à votre dossier", html_body)
        self.assertIn("10 % du coût total initial", html_body)
        self.assertIn("20 % du coût total initial", html_body)
        self.assertIn("30 % du coût total initial", html_body)
        self.assertIn("4 200 €", html_body)
        self.assertIn("2 940 €", html_body)
        self.assertIn("Somme déjà versée et déduite", html_body)
        self.assertIn("Solde de votre dossier", html_body)
        self.assertIn("reporter votre inscription", html_body)
        self.assertIn("Vous confirmez l’annulation de votre inscription ?", html_body)
        self.assertIn("Les pénalités financières seront donc appliquées.", html_body)
        self.assertIn("Merci de répondre à cet email pour confirmer votre choix", html_body)
        self.assertIn(
            "par quel mode de paiement vous souhaitez régler la pénalité financière "
            "(chèque, virement, prélèvement)",
            html_body,
        )
        self.assertIn("Clément VAILLANT", html_body)
        self.assertIn("Pouvez-vous nous confirmer", text_body)
        self.assertIn("Merci de répondre à cet email pour confirmer votre choix", text_body)
        self.assertIn("Les pénalités financières seront donc appliquées.", text_body)
        self.assertIn("(chèque, virement, prélèvement)", text_body)

    def test_cancellation_email_is_previewed_then_sent_and_recorded(self):
        session, trainee, lines = self._indemnity_case()
        data = {"sessions": [session], "billing_lines": lines}
        saved = None

        def capture(payload):
            nonlocal saved
            saved = copy.deepcopy(payload)

        def fake_send(to_email, subject, html_body, **kwargs):
            target = kwargs["trainee"]
            target.setdefault("sent_email_history", []).insert(0, {
                "to_email": to_email,
                "subject": subject,
                "html": html_body,
                "sent_at": "2026-09-30T12:00:00Z",
            })
            return {"ok": True, "message_id": "brevo-test", "error": ""}

        request_payload = {
            "cancellation_date": "2026-09-30",
            "training_price_amount": "4200",
            "deductible_paid_amount": "420",
        }
        base_url = "/api/sessions/S-INDEMNITY/stagiaires/T-INDEMNITY/cancellation-email"
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data", side_effect=capture
        ), patch.object(gestion_app, "brevo_send_email", side_effect=fake_send) as send_mock:
            preview = self.client.post(f"{base_url}/preview", json=request_payload)
            sent = self.client.post(f"{base_url}/send", json=request_payload)

        self.assertEqual(preview.status_code, 200)
        preview_payload = preview.get_json()
        self.assertEqual(preview_payload["recipient"], "alex@example.com")
        self.assertIn("Article 9", preview_payload["html"])
        self.assertIn("Suite à votre demande d’annulation", preview_payload["subject"])
        self.assertTrue(preview_payload["warnings"])

        self.assertEqual(sent.status_code, 200)
        self.assertTrue(sent.get_json()["mail_sent"])
        send_mock.assert_called_once()
        self.assertEqual(send_mock.call_args.args[0], "alex@example.com")
        self.assertEqual(send_mock.call_args.kwargs["metadata"]["purpose"], "registration_cancellation_summary")
        saved_trainee = saved["sessions"][0]["trainees"][0]
        self.assertTrue(saved_trainee["cancellation_email_sent_at"])
        self.assertEqual(saved_trainee["cancellation_email_sent_count"], 1)
        self.assertEqual(saved_trainee["sent_email_history"][0]["to_email"], "alex@example.com")
        self.assertEqual(saved_trainee["activity_history"][0]["label"], "Mail d’annulation envoyé")
        self.assertEqual(saved["activity_logs"][0]["action"], "registration_cancellation_email_sent")

    def test_cancellation_email_refuses_an_incomplete_during_training_calculation(self):
        session, trainee, lines = self._indemnity_case()
        data = {"sessions": [session], "billing_lines": lines}

        with patch.object(gestion_app, "load_data", return_value=data):
            response = self.client.post(
                "/api/sessions/S-INDEMNITY/stagiaires/T-INDEMNITY/cancellation-email/preview",
                json={"cancellation_date": "2026-11-10"},
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("heures dispensées", response.get_json()["error"])

    def test_templates_expose_cancelled_state_and_exclude_it_from_billing_kpis(self):
        detail = Path("templates/admin_trainee.html").read_text(encoding="utf-8")
        listing = Path("templates/admin_trainees.html").read_text(encoding="utf-8")
        billing = Path("templates/admin_sessions_billing.html").read_text(encoding="utf-8")
        direct_debits = Path("templates/admin_direct_debits.html").read_text(encoding="utf-8")

        self.assertIn('id="registrationCancelledCheckbox"', detail)
        self.assertIn('id="registrationCancelledBanner"', detail)
        self.assertIn('id="btnCancellationCalculator"', detail)
        self.assertIn('id="cancellationIndemnityModal"', detail)
        self.assertIn('id="btnPrepareCancellationEmail"', detail)
        self.assertIn('id="cancellationEmailModal"', detail)
        self.assertIn('id="btnSendCancellationEmail"', detail)
        self.assertIn(".cancellation-calculator-loading[hidden]", detail)
        self.assertIn("api_registration_cancellation_indemnity", detail)
        self.assertIn("api_registration_cancellation_email_preview", detail)
        self.assertIn("api_registration_cancellation_email_send", detail)
        self.assertIn("row-registration-cancelled", listing)
        self.assertIn("Inscription annulée", listing)
        self.assertIn("!l.registrationCancelled&&lineMatchesCurrentFilters", billing)
        self.assertIn("billing-registration-cancelled", billing)
        self.assertIn("allDebits.filter(d=>!d.line.registrationCancelled)", direct_debits)
        self.assertIn("is-registration-cancelled", direct_debits)
        self.assertIn("historique non comptabilisé", direct_debits)

    def test_admin_pages_render_cancelled_record_without_removing_it(self):
        data = {"sessions": [self._session()]}
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            listing = self.client.get("/admin/sessions/S-CANCEL/trainees")
            detail = self.client.get(
                "/admin/sessions/S-CANCEL/stagiaires/T-CANCELLED"
            )
            active_detail = self.client.get(
                "/admin/sessions/S-CANCEL/stagiaires/T-ACTIVE"
            )

        self.assertEqual(listing.status_code, 200)
        self.assertIn("row-registration-cancelled", listing.get_data(as_text=True))
        self.assertIn("Inscription annulée", listing.get_data(as_text=True))
        self.assertEqual(detail.status_code, 200)
        detail_html = detail.get_data(as_text=True)
        self.assertIn('id="registrationCancelledCheckbox" checked', detail_html)
        self.assertIn('id="registrationCancelledBanner"', detail_html)
        self.assertIn('id="btnCancellationCalculator"', detail_html)
        self.assertNotIn('id="btnCancellationCalculator" hidden', detail_html)
        self.assertEqual(active_detail.status_code, 200)
        self.assertRegex(
            active_detail.get_data(as_text=True),
            r'id="btnCancellationCalculator"\s+hidden',
        )


if __name__ == "__main__":
    unittest.main()
