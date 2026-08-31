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

    def test_templates_expose_cancelled_state_and_exclude_it_from_billing_kpis(self):
        detail = Path("templates/admin_trainee.html").read_text(encoding="utf-8")
        listing = Path("templates/admin_trainees.html").read_text(encoding="utf-8")
        billing = Path("templates/admin_sessions_billing.html").read_text(encoding="utf-8")
        direct_debits = Path("templates/admin_direct_debits.html").read_text(encoding="utf-8")

        self.assertIn('id="registrationCancelledCheckbox"', detail)
        self.assertIn('id="registrationCancelledBanner"', detail)
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

        self.assertEqual(listing.status_code, 200)
        self.assertIn("row-registration-cancelled", listing.get_data(as_text=True))
        self.assertIn("Inscription annulée", listing.get_data(as_text=True))
        self.assertEqual(detail.status_code, 200)
        detail_html = detail.get_data(as_text=True)
        self.assertIn('id="registrationCancelledCheckbox" checked', detail_html)
        self.assertIn('id="registrationCancelledBanner"', detail_html)


if __name__ == "__main__":
    unittest.main()
