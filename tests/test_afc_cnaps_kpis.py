from pathlib import Path
import unittest


TEMPLATE = Path("templates/admin_afc.html").read_text(encoding="utf-8")


class AfcCnapsKpiTemplateTests(unittest.TestCase):
    def test_afc_page_exposes_clickable_cnaps_status_kpis(self):
        expected = {
            "all": "Total candidats",
            "inconnu": "CNAPS à transmettre / inconnu",
            "en_cours": "CNAPS transmis / en cours",
            "accepte": "CNAPS acceptés",
            "refuse": "CNAPS refusés",
        }
        for key, label in expected.items():
            self.assertIn(f'data-afc-cnaps-kpi="{key}"', TEMPLATE)
            self.assertIn(label, TEMPLATE)

        self.assertIn("function updateAfcCnapsKpis()", TEMPLATE)
        self.assertIn("activeAfcCnapsFilter = button.dataset.afcCnapsKpi || 'all';", TEMPLATE)
        self.assertIn("button.setAttribute('aria-pressed', String(isActive));", TEMPLATE)
        self.assertNotIn('id="afcCnapsFilter"', TEMPLATE)

    def test_afc_cnaps_unknown_group_includes_not_transmitted_statuses(self):
        for status in ("AUCUN DOSSIER", "PAS DE DOSSIER", "NON TRANSMIS", "A TRANSMETTRE"):
            self.assertIn(status, TEMPLATE)

        self.assertIn("return 'inconnu';", TEMPLATE)


if __name__ == "__main__":
    unittest.main()
