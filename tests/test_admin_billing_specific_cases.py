import datetime
import unittest

import app


class AdminBillingSpecificCasesTests(unittest.TestCase):
    def _session(self, *, cash=False):
        return {
            "id": "session-specific",
            "name": "Session APS",
            "training_type": "APS",
            "date_start": max(app.BILLING_START_DATE, datetime.date.today()).isoformat(),
            "date_end": max(app.BILLING_START_DATE, datetime.date.today()).isoformat(),
            "trainees": [{
                "id": "trainee-specific",
                "first_name": "Jean",
                "last_name": "Test",
                "personal_amount": 500,
                "cash_payment_enabled": cash,
            }],
        }

    def test_cash_payment_automatically_marks_billing_line_specific(self):
        line = app.buildBillingLinesFromSessions([self._session(cash=True)])[0]
        self.assertTrue(line["specificCase"])
        self.assertTrue(line["specificCaseAutomatic"])
        self.assertIn("espèces", line["specificCaseReason"])

    def test_cash_payment_does_not_block_other_financing_invoice(self):
        session = self._session(cash=True)
        trainee = session["trainees"][0]
        trainee["other_amount"] = 900

        lines = app.buildBillingLinesFromSessions([session])
        other_line = next(line for line in lines if line["financingType"] == "AUTRE")

        self.assertFalse(other_line["specificCase"])
        self.assertFalse(other_line["specificCaseAutomatic"])
        self.assertEqual(other_line["specificCaseReason"], "")

    def test_old_automatic_cash_flag_no_longer_blocks_other_financing(self):
        session = self._session(cash=True)
        trainee = session["trainees"][0]
        trainee["other_amount"] = 900
        initial_lines = app.buildBillingLinesFromSessions([session])
        other_line = next(line for line in initial_lines if line["financingType"] == "AUTRE")

        rebuilt = app.buildBillingLinesFromSessions([session], {
            other_line["id"]: {
                "id": other_line["id"],
                "specificCase": True,
                "specificCaseAutomatic": True,
                "specificCaseReason": "Paiement en espèces indiqué dans la fiche stagiaire.",
            }
        })
        rebuilt_other = next(line for line in rebuilt if line["financingType"] == "AUTRE")

        self.assertFalse(rebuilt_other["specificCase"])
        self.assertFalse(rebuilt_other["specificCaseAutomatic"])

    def test_manual_specific_case_is_restored_from_persisted_line(self):
        base = app.buildBillingLinesFromSessions([self._session()])[0]
        lines = app.buildBillingLinesFromSessions([self._session()], {
            base["id"]: {"id": base["id"], "specificCase": True, "specificCaseReason": "Dossier à vérifier"}
        })
        self.assertTrue(lines[0]["specificCase"])
        self.assertEqual(lines[0]["specificCaseReason"], "Dossier à vérifier")
        self.assertFalse(lines[0]["specificCaseAutomatic"])

    def test_cash_specific_case_can_be_explicitly_dismissed(self):
        base = app.buildBillingLinesFromSessions([self._session(cash=True)])[0]
        lines = app.buildBillingLinesFromSessions([self._session(cash=True)], {
            base["id"]: {
                "id": base["id"],
                "specificCase": False,
                "specificCaseCashDismissed": True,
            }
        })
        self.assertFalse(lines[0]["specificCase"])
        self.assertFalse(lines[0]["specificCaseAutomatic"])
        self.assertTrue(lines[0]["specificCaseCashDismissed"])

    def test_billing_page_contains_specific_case_controls(self):
        template = open("templates/admin_sessions_billing.html", encoding="utf-8").read()
        self.assertIn("Cas spécifique", template)
        self.assertIn("Pourquoi est-ce un cas spécifique ?", template)
        self.assertIn("specific-case-row", template)
        self.assertIn("Génération désactivée", template)
        self.assertIn('data-external="${id}">Générée ailleurs</button>', template)
        self.assertIn("['specific_case','Cas spécifique',specificCases.length", template)
        self.assertNotIn("['draft','Factures en brouillon'", template)
        self.assertIn('l.specificCase&&has&&!isExternalInvoice(l)', template)
        self.assertIn('data-reset-external="${id}">Générée ailleurs</button>', template)
        self.assertNotIn('disabled title="Activé automatiquement par le paiement en espèces"', template)
