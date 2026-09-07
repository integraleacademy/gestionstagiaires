import copy
import datetime
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as gestion_app


class AdminCancellationTrackingTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"
            session["admin_username"] = "clement@integraleacademy.com"

    @staticmethod
    def _data():
        today = datetime.datetime.now(ZoneInfo("Europe/Paris")).date()
        start = today + datetime.timedelta(days=65)
        end = start + datetime.timedelta(days=30)
        cancelled = {
            "id": "T-CANCEL-TRACK",
            "first_name": "Camille",
            "last_name": "Annulee",
            "email": "camille@example.com",
            "phone": "0612345678",
            "registration_cancelled": True,
            "registration_cancelled_at": f"{today.isoformat()}T08:30:00Z",
            "training_price": 1000,
            "personal_amount": 1000,
            "documents": [],
        }
        active = {
            "id": "T-ACTIVE-TRACK",
            "first_name": "Alex",
            "last_name": "Actif",
            "registration_cancelled": False,
            "training_price": 1000,
            "documents": [],
        }
        session = {
            "id": "S-CANCEL-TRACK",
            "name": "Session APS suivi annulations",
            "training_type": "APS",
            "date_start": start.isoformat(),
            "date_end": end.isoformat(),
            "trainees": [cancelled, active],
        }
        return {
            "sessions": [session],
            "billing_lines": [],
            "notifications_admin": [],
            "activity_logs": [],
        }

    def test_dashboard_contains_only_cancelled_registrations_and_financial_kpis(self):
        data = self._data()
        with gestion_app.app.test_request_context("/admin/cancellations"):
            dashboard = gestion_app._cancellation_tracking_dashboard(data)

        self.assertEqual(len(dashboard["items"]), 1)
        item = dashboard["items"][0]
        self.assertEqual(item["trainee_id"], "T-CANCEL-TRACK")
        self.assertEqual(item["penalty_rate"], 10.0)
        self.assertEqual(item["effective_total_due_cents"], 10000)
        self.assertEqual(item["remaining_cents"], 10000)
        self.assertEqual(dashboard["kpis"]["total"], 1)
        self.assertEqual(dashboard["kpis"]["remaining_cents"], 10000)

    def test_dashboard_page_and_navigation_expose_suivi_annulations(self):
        data = self._data()
        with patch.object(gestion_app, "load_data", return_value=data):
            response = self.client.get("/admin/cancellations?session_id=S-CANCEL-TRACK")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Suivi des annulations", html)
        self.assertIn("Camille ANNULEE", html)
        self.assertIn('value="S-CANCEL-TRACK" selected', html)

        sidebar = Path("templates/admin_sidebar.html").read_text(encoding="utf-8")
        sessions = Path("templates/admin_sessions.html").read_text(encoding="utf-8")
        commands = Path("templates/_global_command_search.html").read_text(encoding="utf-8")
        self.assertIn("Suivi annulations", sidebar)
        self.assertIn("Suivi annulations", sessions)
        self.assertIn("Suivi annulations", commands)

    def test_session_tools_link_opens_tracking_preselected_on_current_session(self):
        data = self._data()
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.get("/admin/sessions/S-CANCEL-TRACK/trainees")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'href="/admin/cancellations?session_id=S-CANCEL-TRACK"',
            response.get_data(as_text=True),
        )

    def test_marking_registration_cancelled_opens_tracking_case_automatically(self):
        data = self._data()
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/api/sessions/S-CANCEL-TRACK/stagiaires/T-ACTIVE-TRACK/update",
                json={"registration_cancelled": True},
            )

        self.assertEqual(response.status_code, 200)
        trainee = data["sessions"][0]["trainees"][1]
        tracking = trainee["cancellation_tracking"]
        self.assertEqual(tracking["case_status"], "to_process")
        self.assertEqual(tracking["events"][0]["label"], "Dossier d’annulation ouvert")

    def test_viewer_can_open_tracking_but_cannot_change_financial_data(self):
        data = self._data()
        with self.client.session_transaction() as session:
            session["admin_role"] = "viewer"
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ) as save_data:
            page_response = self.client.get("/admin/cancellations")
            write_response = self.client.post(
                "/api/admin/cancellations/S-CANCEL-TRACK/T-CANCEL-TRACK/payments",
                json={"amount": "50", "method": "bank_transfer"},
            )

        self.assertEqual(page_response.status_code, 200)
        self.assertEqual(write_response.status_code, 403)
        self.assertIn(write_response.get_json()["error"], {"read_only", "Droits insuffisants pour modifier ces données."})
        save_data.assert_not_called()

    def test_case_update_persists_assignment_dates_calculation_and_adjustment(self):
        data = self._data()
        captured = None

        def capture(payload, **_kwargs):
            nonlocal captured
            captured = copy.deepcopy(payload)

        payload = {
            "case_status": "awaiting_payment",
            "origin": "trainee",
            "reason": "professional",
            "reason_details": "Nouvel emploi incompatible avec la session.",
            "assigned_to": "Cassandre MENARD",
            "next_action_date": (datetime.date.today() + datetime.timedelta(days=5)).isoformat(),
            "payment_due_date": (datetime.date.today() + datetime.timedelta(days=15)).isoformat(),
            "decision": "custom",
            "manual_total_due_amount": "75",
            "adjustment_reason": "Geste commercial validé par la direction.",
            "payment_terms": "single",
            "calculation_inputs": {
                "cancellation_date": data["sessions"][0]["trainees"][0]["registration_cancelled_at"][:10],
                "training_price_amount": "1000",
                "deductible_paid_amount": "0",
                "total_training_hours": "175",
                "delivered_hours": "",
            },
        }
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data", side_effect=capture
        ):
            response = self.client.post(
                "/api/admin/cancellations/S-CANCEL-TRACK/T-CANCEL-TRACK",
                json=payload,
            )

        self.assertEqual(response.status_code, 200)
        item = response.get_json()["item"]
        self.assertEqual(item["case_status"], "awaiting_payment")
        self.assertEqual(item["effective_total_due_cents"], 7500)
        self.assertEqual(item["remaining_cents"], 7500)
        state = captured["sessions"][0]["trainees"][0]["cancellation_tracking"]
        self.assertEqual(state["assigned_to"], "Cassandre MENARD")
        self.assertEqual(state["manual_total_due_cents"], 7500)
        self.assertTrue(state["calculation_snapshot"])
        self.assertEqual(state["events"][0]["label"], "Suivi d’annulation mis à jour")
        self.assertEqual(captured["activity_logs"][-1]["action"], "registration_cancellation_tracking_updated")

    def test_adjustment_requires_a_reason(self):
        data = self._data()
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/api/admin/cancellations/S-CANCEL-TRACK/T-CANCEL-TRACK",
                json={
                    "decision": "custom",
                    "manual_total_due_amount": "75",
                    "adjustment_reason": "",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Expliquez", response.get_json()["error"])

    def test_non_finite_payment_amount_is_rejected_without_persisting(self):
        data = self._data()
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ) as save_data:
            response = self.client.post(
                "/api/admin/cancellations/S-CANCEL-TRACK/T-CANCEL-TRACK/payments",
                json={"amount": "Infinity", "method": "bank_transfer"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("montant", response.get_json()["error"].lower())
        save_data.assert_not_called()

    def test_payments_are_accumulated_and_can_be_voided_without_being_deleted(self):
        data = self._data()
        trainee = data["sessions"][0]["trainees"][0]
        trainee["cancellation_tracking"] = {
            "decision": "custom",
            "manual_total_due_cents": 10000,
            "adjustment_reason": "Montant validé.",
            "case_status": "awaiting_payment",
            "payments": [],
            "contacts": [],
            "events": [],
        }

        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            recorded = self.client.post(
                "/api/admin/cancellations/S-CANCEL-TRACK/T-CANCEL-TRACK/payments",
                json={
                    "amount": "40",
                    "method": "bank_transfer",
                    "paid_at": datetime.date.today().isoformat(),
                    "reference": "VIR-001",
                    "note": "Premier versement",
                },
            )
            self.assertEqual(recorded.status_code, 200)
            recorded_item = recorded.get_json()["item"]
            payment_id = recorded_item["payments"][0]["id"]
            self.assertEqual(recorded_item["payments_received_cents"], 4000)
            self.assertEqual(recorded_item["remaining_cents"], 6000)
            self.assertEqual(recorded_item["collection_status"], "partial")

            voided = self.client.post(
                f"/api/admin/cancellations/S-CANCEL-TRACK/T-CANCEL-TRACK/payments/{payment_id}/void",
                json={"reason": "Virement saisi sur le mauvais dossier"},
            )

        self.assertEqual(voided.status_code, 200)
        voided_item = voided.get_json()["item"]
        self.assertEqual(voided_item["payments_received_cents"], 0)
        self.assertEqual(voided_item["remaining_cents"], 10000)
        self.assertTrue(voided_item["payments"][0]["voided_at"])
        self.assertEqual(len(trainee["cancellation_tracking"]["payments"]), 1)

    def test_contact_log_updates_workflow_and_next_action(self):
        data = self._data()
        next_action = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.post(
                "/api/admin/cancellations/S-CANCEL-TRACK/T-CANCEL-TRACK/contacts",
                json={
                    "channel": "phone",
                    "outcome": "payment_plan_agreed",
                    "contacted_at": datetime.date.today().isoformat(),
                    "next_action_date": next_action,
                    "note": "Deux règlements convenus avec le stagiaire.",
                },
            )

        self.assertEqual(response.status_code, 200)
        item = response.get_json()["item"]
        self.assertEqual(item["case_status"], "payment_plan")
        self.assertEqual(item["state"]["payment_terms"], "installments")
        self.assertEqual(item["next_action_date"], next_action)
        self.assertEqual(len(item["contacts"]), 1)
        self.assertTrue(any(event["kind"] == "contact" for event in item["timeline"]))

    def test_active_registration_is_rejected_by_tracking_api(self):
        data = self._data()
        with patch.object(gestion_app, "load_data", return_value=data):
            response = self.client.get(
                "/api/admin/cancellations/S-CANCEL-TRACK/T-ACTIVE-TRACK"
            )
        self.assertEqual(response.status_code, 409)
        self.assertIn("plus annulée", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
