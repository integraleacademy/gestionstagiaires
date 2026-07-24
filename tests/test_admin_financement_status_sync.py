import unittest
from unittest.mock import patch

import app as gestion_app


class AdminFinancementStatusSyncTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def test_admin_trainees_marks_financement_green_from_manual_validation(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "name": "APS TEST",
                    "training_type": "APS",
                    "date_start": "2026-09-01",
                    "date_end": "2026-10-01",
                    "trainees": [
                        {
                            "id": "T1",
                            "last_name": "VAILLANT",
                            "first_name": "Clément",
                            "financement_status": "soon",
                            "financing_validation_manual_mode": "manual",
                            "financing_validation_manual_status": "validated",
                            "documents": [],
                        }
                    ],
                }
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data"):
            response = self.client.get("/admin/sessions/S-APS/trainees")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('<option value="validated" selected>🟢</option>', html)
        self.assertEqual(fake_data["sessions"][0]["trainees"][0]["financement_status"], "validated")


    def test_manual_validation_update_persists_for_cpf_plus_personal_financing(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "name": "APS TEST",
                    "training_type": "APS",
                    "trainees": [
                        {
                            "id": "T1",
                            "last_name": "VAILLANT",
                            "first_name": "Clément",
                            "financement_status": "soon",
                            "cpf_amount": "1000",
                            "personal_amount": "650",
                            "training_price": "1650",
                            "documents": [],
                        }
                    ],
                }
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data") as save_data:
            response = self.client.post(
                "/api/sessions/S-APS/stagiaires/T1/update",
                json={
                    "financing_validation_manual_mode": "manual",
                    "financing_validation_manual_status": "validated",
                    "financement_status": "validated",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        trainee = fake_data["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["financing_validation_manual_mode"], "manual")
        self.assertEqual(trainee["financing_validation_manual_status"], "validated")
        self.assertEqual(trainee["financement_status"], "validated")
        save_data.assert_called_once()


    def test_cpf_validated_update_persists(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "name": "APS TEST",
                    "training_type": "APS",
                    "trainees": [
                        {
                            "id": "T1",
                            "last_name": "VAILLANT",
                            "first_name": "Clément",
                            "cpf_amount": "1000",
                            "documents": [],
                        }
                    ],
                }
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data), patch.object(gestion_app, "save_data") as save_data:
            response = self.client.post(
                "/api/sessions/S-APS/stagiaires/T1/update",
                json={"cpf_validated": True},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertTrue(fake_data["sessions"][0]["trainees"][0]["cpf_validated"])
        save_data.assert_called_once()


    def test_force_financement_validated_route_works_without_javascript_for_cpf_plus_personal(self):
        fake_data = {
            "sessions": [
                {
                    "id": "S-APS",
                    "name": "APS TEST",
                    "training_type": "APS",
                    "trainees": [
                        {
                            "id": "T1",
                            "last_name": "VAILLANT",
                            "first_name": "Clément",
                            "financement_status": "soon",
                            "cpf_amount": "1000",
                            "personal_amount": "650",
                            "training_price": "1650",
                            "documents": [],
                        }
                    ],
                }
            ]
        }

        with patch.object(gestion_app, "load_data", return_value=fake_data), \
             patch.object(gestion_app, "save_data") as save_data, \
             patch.object(gestion_app, "_auto_send_convention_signature_if_needed") as auto_send:
            response = self.client.post(
                "/admin/sessions/S-APS/trainees/T1/finance/force-validated",
                headers={"Accept": "application/json"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        trainee = fake_data["sessions"][0]["trainees"][0]
        self.assertEqual(trainee["financing_validation_manual_mode"], "manual")
        self.assertEqual(trainee["financing_validation_manual_status"], "validated")
        self.assertEqual(trainee["financement_status"], "validated")
        save_data.assert_called_once()
        auto_send.assert_called_once()

    def test_admin_trainee_finance_widget_syncs_validated_status(self):
        template = gestion_app.app.jinja_loader.get_source(
            gestion_app.app.jinja_env,
            "admin_trainee.html",
        )[0]

        self.assertIn("function syncFinancementStatusIfValidated(state)", template)
        self.assertIn("updateTrainee({financement_status:'validated'})", template)
        self.assertIn("financing_validation_manual_status:'validated', financement_status:'validated'", template)
        self.assertIn("function saveFinanceValidationOverride(payload)", template)
        self.assertIn("function applyFinancingValidationState(state)", template)
        self.assertIn('id="financeForceValidatedForm"', template)
        self.assertIn("admin_force_financement_validated", template)
        self.assertIn("fetch(financeValidationForceForm.action", template)
        self.assertIn("financeValidationWrap.dataset.manualMode = 'manual'", template)
        self.assertIn("applyFinancingValidationState({label:'Financement validé', tone:'green', icon:'✓', manual:true})", template)
        self.assertIn("/api/sessions/${encodeURIComponent(sessionId)}/stagiaires/${encodeURIComponent(traineeId)}/update", template)
        self.assertNotIn("/admin/sessions/${encodeURIComponent(sessionId)}/trainees/${encodeURIComponent(traineeId)}/update", template)
        self.assertIn("setFinanceSaveIndicator('Financement validé','saved')", template)
        self.assertIn("computed.otherFundingPlanned", template)
        self.assertIn("computed.otherFundingInvoiced", template)
        self.assertIn("value:`${fmtMoney(c.otherFundingInvoiced)} / ${fmtMoney(c.otherFundingPlanned)}`", template)
        self.assertIn("badge(otherFundingFact[0],otherFundingFact[1])", template)

    def test_completed_invoice_generation_is_not_a_notification(self):
        template = gestion_app.app.jinja_loader.get_source(
            gestion_app.app.jinja_env,
            "admin_trainee.html",
        )[0]

        self.assertIn("function renderAlerts(lines,c)", template)
        self.assertNotIn("Toutes les factures à gérer ici sont générées.", template)

    def test_quick_invoice_action_does_not_report_completion_with_an_amount_remaining(self):
        template = gestion_app.app.jinja_loader.get_source(
            gestion_app.app.jinja_env,
            "admin_trainee.html",
        )[0]

        self.assertIn("const remainingToInvoice=Number(computeFinance(currentLines).resteAFacturer||0);", template)
        self.assertIn("const hasUnrepresentedInvoice=remainingToInvoice>0.01;", template)
        self.assertIn("⚠ Facture à générer : actualiser les financements", template)


if __name__ == "__main__":
    unittest.main()
