import unittest
from unittest import mock

import app as gestion_app


AP_SH = "Autorisation préalable - Surveillance humaine ou gardiennage"
AP_A3P = "Autorisation préalable - Agent de protection physique des personnes"
CP_SH = "Carte professionnelle - Surveillance humaine ou gardiennage"
CP_A3P = "Carte professionnelle - Agent de protection physique des personnes"


def row(nub="1000731", activite=AP_SH, validite="ACTIF", date="07/10/2026"):
    return {"nom": "LARDJANE", "prenom": "Zinedine", "nub": nub, "activite": activite, "dateValiditeTitre": date, "validiteTitre": validite}


class CnapsPublicAnnuaireTests(unittest.TestCase):
    def labels(self, snapshot):
        return snapshot["cnaps_active_titles"]

    def test_two_active_titles_same_nub(self):
        rows = gestion_app._extract_cnaps_public_annuaire_results({"resultats": [row(activite=AP_SH), row(activite=CP_SH, date="30/06/2031")]})
        snapshot = gestion_app.build_cnaps_public_annuaire_snapshot(rows, "1000731")
        self.assertEqual(self.labels(snapshot), ["AP SH ACTIF", "CP SH ACTIF"])

    def test_empty_result_replaces_old_status(self):
        old = ["AP SH ACTIF"]
        snapshot = gestion_app.build_cnaps_public_annuaire_snapshot([], "1000731")
        self.assertEqual(old, ["AP SH ACTIF"])
        self.assertEqual(self.labels(snapshot), [])
        self.assertEqual(snapshot["check_status"], "success")

    def test_same_name_other_nub_is_rejected(self):
        rows = gestion_app._extract_cnaps_public_annuaire_results({"resultats": [row(nub="9999999", activite=AP_SH)]})
        snapshot = gestion_app.build_cnaps_public_annuaire_snapshot(rows, "1000731")
        self.assertEqual(self.labels(snapshot), [])

    def test_inactive_activity_is_ignored(self):
        rows = gestion_app._extract_cnaps_public_annuaire_results({"resultats": [row(activite=AP_SH, validite="INACTIF"), row(activite=CP_SH, validite="ACTIF")]})
        snapshot = gestion_app.build_cnaps_public_annuaire_snapshot(rows, "1000731")
        self.assertEqual(self.labels(snapshot), ["CP SH ACTIF"])

    def test_four_active_activities_stable_order(self):
        rows = gestion_app._extract_cnaps_public_annuaire_results({"resultats": [row(activite=CP_A3P), row(activite=CP_SH), row(activite=AP_A3P), row(activite=AP_SH)]})
        snapshot = gestion_app.build_cnaps_public_annuaire_snapshot(rows, "1000731")
        self.assertEqual(self.labels(snapshot), ["AP SH ACTIF", "AP A3P ACTIF", "CP SH ACTIF", "CP A3P ACTIF"])

    def test_duplicate_rows_are_deduplicated(self):
        rows = gestion_app._extract_cnaps_public_annuaire_results({"resultats": [row(activite=CP_SH), row(activite=CP_SH)]})
        snapshot = gestion_app.build_cnaps_public_annuaire_snapshot(rows, "1000731")
        self.assertEqual(self.labels(snapshot), ["CP SH ACTIF"])

    def test_case_and_accent_variation(self):
        rows = gestion_app._extract_cnaps_public_annuaire_results({"resultats": [row(activite="CARTE PROFESSIONNELLE - AGENT DE PROTECTION PHYSIQUE DES PERSONNES")]})
        snapshot = gestion_app.build_cnaps_public_annuaire_snapshot(rows, "1000731")
        self.assertEqual(self.labels(snapshot), ["CP A3P ACTIF"])

    def test_network_or_parsing_error_returns_error_snapshot(self):
        original_endpoint = gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT
        gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT = "https://cnaps.example/annuaire"
        try:
            with mock.patch.object(gestion_app.requests, "post", side_effect=TimeoutError("CNAPS timeout")):
                with mock.patch.object(gestion_app.requests, "get", side_effect=TimeoutError("CNAPS timeout")):
                    snapshot = gestion_app.fetch_cnaps_public_annuaire("LARDJANE", "1000731")
        finally:
            gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT = original_endpoint
        self.assertEqual(snapshot["check_status"], "error")
        self.assertEqual(snapshot["cnaps_active_titles"], [])
        self.assertIn("CNAPS timeout", snapshot["error"])

    def test_refresh_replaces_previous_snapshot(self):
        old = gestion_app.build_cnaps_public_annuaire_snapshot(gestion_app._extract_cnaps_public_annuaire_results({"resultats": [row(activite=AP_SH)]}), "1000731")
        new = gestion_app.build_cnaps_public_annuaire_snapshot(gestion_app._extract_cnaps_public_annuaire_results({"resultats": [row(activite=CP_SH)]}), "1000731")
        self.assertEqual(self.labels(old), ["AP SH ACTIF"])
        self.assertEqual(self.labels(new), ["CP SH ACTIF"])

    def test_html_contains_two_distinct_badges(self):
        with open("templates/admin_cnaps_tracking.html", encoding="utf-8") as f:
            html = f.read()
        self.assertIn('activeTitles.map', html)
        self.assertIn('title.label', html)
        snapshot = gestion_app.build_cnaps_public_annuaire_snapshot(gestion_app._extract_cnaps_public_annuaire_results({"resultats": [row(activite=AP_SH), row(activite=CP_SH)]}), "1000731")
        rendered = "".join(f'<span class="card-pro-result__chip is-active"><span class="card-pro-result__activity">{title["label"]}</span></span>' for title in snapshot["active_titles"])
        self.assertIn("AP SH ACTIF", rendered)
        self.assertIn("CP SH ACTIF", rendered)
        self.assertEqual(rendered.count('card-pro-result__chip is-active'), 2)

    def test_fetch_requests_enough_rows_to_include_all_titles(self):
        original_endpoint = gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT
        captured = {}

        class DummyResponse:
            status_code = 200
            def json(self):
                return {"resultats": [row(activite=AP_SH), row(activite=CP_SH)]}

        def fake_post(url, json, headers, timeout):
            captured.update({"url": url, "json": json, "headers": headers, "timeout": timeout})
            return DummyResponse()

        gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT = "https://cnaps.example/annuaire"
        try:
            with mock.patch.object(gestion_app.requests, "post", side_effect=fake_post):
                result = gestion_app.fetch_cnaps_public_annuaire("lardjane", "1000731")
        finally:
            gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT = original_endpoint

        self.assertEqual(captured["json"]["nom"], "LARDJANE")
        self.assertEqual(captured["json"]["nub"], "1000731")
        self.assertEqual(captured["json"]["size"], 100)
        self.assertEqual(captured["json"]["limit"], 100)
        self.assertEqual(result["cnaps_active_titles"], ["AP SH ACTIF", "CP SH ACTIF"])


if __name__ == "__main__":
    unittest.main()
