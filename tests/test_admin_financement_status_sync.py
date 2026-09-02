import json
import shutil
import subprocess
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
        self.assertIn("computed.personalFundingPlanned", template)
        self.assertIn("computed.personalFundingInvoiced", template)
        self.assertIn("value:`${fmtMoney(c.personalFundingInvoiced)} / ${fmtMoney(c.personalFundingPlanned)}`", template)
        self.assertIn("badge(personalFundingFact[0],personalFundingFact[1])", template)
        self.assertIn("computed.otherFundingPlanned", template)
        self.assertIn("computed.otherFundingInvoiced", template)
        self.assertIn("value:`${fmtMoney(c.otherFundingInvoiced)} / ${fmtMoney(c.otherFundingPlanned)}`", template)
        self.assertIn("badge(otherFundingFact[0],otherFundingFact[1])", template)

    def test_finance_kpis_distinguish_funding_sources_and_payment_statuses(self):
        template = gestion_app.app.jinja_loader.get_source(
            gestion_app.app.jinja_env,
            "admin_trainee.html",
        )[0]

        self.assertIn('id="financeSummaryCards" class="finance-kpi-groups"', template)
        self.assertIn("finance-kpi-group--funding", template)
        self.assertIn("finance-kpi-group--payment", template)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", template)
        self.assertIn("grid-template-columns:repeat(var(--finance-kpi-count,3),minmax(0,1fr))", template)
        self.assertIn("const fundingCards=[", template)
        self.assertIn("{label:'Financement personnel'", template)
        self.assertIn("{label:'Autres financements'", template)
        self.assertNotIn("{label:'AUTRES FINANCEMENTS'", template)

        payment_start = template.index("    const paymentCards=[")
        payment_end = template.index("\n    ];", payment_start)
        payment_cards = template[payment_start:payment_end]
        self.assertIn("...(showDirectDebitKpi?[{label:'Prélèvements'", payment_cards)
        self.assertLess(payment_cards.index("{label:'Prélèvements'"), payment_cards.index("{label:'Payé'"))

    def test_direct_debit_kpi_is_hidden_when_cash_covers_personal_funding(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to execute the cash financing KPI rule")

        template = gestion_app.app.jinja_loader.get_source(
            gestion_app.app.jinja_env,
            "admin_trainee.html",
        )[0]
        start = template.index("  function cashCoversEntirePersonalFunding(c){")
        end = template.index("\n  function renderSummary(c){", start)
        helper = template[start:end]
        script = f"""
{helper}
const states = {{
  fullCash: cashCoversEntirePersonalFunding({{cashPaymentEnabled:true,cashPlanned:1470,personalFundingPlanned:1470}}),
  overCash: cashCoversEntirePersonalFunding({{cashPaymentEnabled:true,cashPlanned:1500,personalFundingPlanned:1470}}),
  partialCash: cashCoversEntirePersonalFunding({{cashPaymentEnabled:true,cashPlanned:1000,personalFundingPlanned:1470}}),
  cashDisabled: cashCoversEntirePersonalFunding({{cashPaymentEnabled:false,cashPlanned:1470,personalFundingPlanned:1470}}),
  noPersonalFunding: cashCoversEntirePersonalFunding({{cashPaymentEnabled:true,cashPlanned:1470,personalFundingPlanned:0}})
}};
process.stdout.write(JSON.stringify(states));
"""

        completed = subprocess.run(
            [node, "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        states = json.loads(completed.stdout)

        self.assertTrue(states["fullCash"])
        self.assertTrue(states["overCash"])
        self.assertFalse(states["partialCash"])
        self.assertFalse(states["cashDisabled"])
        self.assertFalse(states["noPersonalFunding"])

    def test_fully_paid_other_funding_is_automatically_validated(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to execute the financing validation rule")

        template = gestion_app.app.jinja_loader.get_source(
            gestion_app.app.jinja_env,
            "admin_trainee.html",
        )[0]
        start = template.index("  function financingValidationFrom(c, lines){")
        end = template.index("\n  function syncFinancementStatusIfValidated", start)
        validation_function = template[start:end]
        base_case = {
            "prixFormation": 4300,
            "montantCpf": 0,
            "montantPersonnel": 0,
            "montantAutre": 4300,
            "totalFinancement": 4300,
            "objectifFacturation": 4300,
        }
        script = f"""
const financeValidationManualMode = false;
const financeValidationManualStatus = '';
{validation_function}
const paid = financingValidationFrom({json.dumps({**base_case, "totalPaye": 4300})}, []);
const unpaid = financingValidationFrom({json.dumps({**base_case, "totalPaye": 0})}, []);
process.stdout.write(JSON.stringify({{paid, unpaid}}));
"""

        completed = subprocess.run(
            [node, "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        states = json.loads(completed.stdout)

        self.assertEqual(states["paid"]["label"], "Financement validé")
        self.assertEqual(states["paid"]["tone"], "green")
        self.assertEqual(states["unpaid"]["label"], "Financement à valider")
        self.assertEqual(states["unpaid"]["tone"], "gray")

    def test_invoiced_card_identifies_qonto_and_external_invoice_origins(self):
        template = gestion_app.app.jinja_loader.get_source(
            gestion_app.app.jinja_env,
            "admin_trainee.html",
        )[0]

        self.assertIn("function invoiceOriginBadges(lines)", template)
        self.assertIn("badge('QONTO','black')", template)
        self.assertIn("badge('Générée ailleurs','purple')", template)
        self.assertIn("finance-badge--black", template)
        self.assertIn("finance-badge--purple", template)
        self.assertIn("invoiceOriginBadges(personalFundingLines)", template)
        self.assertIn("invoiceOriginBadges(otherFundingLines)", template)

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
