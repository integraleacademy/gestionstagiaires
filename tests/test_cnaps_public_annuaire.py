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
        class TimeoutSession:
            def get(self, *args, **kwargs):
                return HttpDummyResponse(200, {"Content-Type": "text/html"}, "<html></html>")
            def post(self, *args, **kwargs):
                raise TimeoutError("CNAPS timeout")
        try:
            with mock.patch.object(gestion_app.requests, "Session", return_value=TimeoutSession()):
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

        class CaptureSession:
            def get(self, *args, **kwargs):
                return HttpDummyResponse(200, {"Content-Type": "text/html"}, "<html></html>")
            def post(self, url, json, headers, timeout, allow_redirects=True):
                captured.update({"url": url, "json": json, "headers": headers, "timeout": timeout})
                return HttpDummyResponse(200, {"Content-Type": "application/json"}, "", {"resultats": [row(activite=AP_SH), row(activite=CP_SH)]})

        gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT = "https://cnaps.example/annuaire"
        try:
            with mock.patch.object(gestion_app.requests, "Session", return_value=CaptureSession()):
                result = gestion_app.fetch_cnaps_public_annuaire("lardjane", "1000731")
        finally:
            gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT = original_endpoint

        self.assertEqual(captured["json"]["nom"], "LARDJANE")
        self.assertEqual(captured["json"]["nub"], "1000731")
        self.assertEqual(captured["json"]["size"], 100)
        self.assertEqual(captured["json"]["limit"], 100)
        self.assertEqual(result["cnaps_active_titles"], ["AP SH ACTIF", "CP SH ACTIF"])


class CnapsPublicAnnuaireHttpTests(unittest.TestCase):
    def setUp(self):
        self.original_endpoint = gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT
        gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT = "https://cnaps.example/annuaire/api/annuaire-public/recherche"

    def tearDown(self):
        gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT = self.original_endpoint

    def fake_session(self, response=None, post_exc=None):
        class DummySession:
            def get(self, *args, **kwargs):
                return HttpDummyResponse(200, {"Content-Type": "text/html"}, "<html></html>")
            def post(self, *args, **kwargs):
                if post_exc:
                    raise post_exc
                return response
        return DummySession()

    def run_with_response(self, response=None, post_exc=None, previous_success=None):
        with mock.patch.object(gestion_app.requests, "Session", return_value=self.fake_session(response, post_exc)):
            return gestion_app.fetch_cnaps_public_annuaire("LARDJANE", "1000731", previous_success=previous_success)

    def test_http_404_is_error_and_keeps_last_successful_snapshot(self):
        previous = {"checked_at": "2026-07-15T10:00:00+00:00", "active_titles": [{"label": "AP SH ACTIF"}]}
        result = self.run_with_response(HttpDummyResponse(404, {"Content-Type": "application/json"}, '{"error":"not found"}'), previous_success=previous)
        self.assertEqual(result["check_status"], "error")
        self.assertEqual(result["active_titles"], [])
        self.assertNotEqual(result.get("message"), "Aucun titre actif trouvé")
        self.assertEqual(result["last_successful_check"], previous)

    def test_http_200_empty_list_is_success_and_clears_old_titles(self):
        result = self.run_with_response(HttpDummyResponse(200, {"Content-Type": "application/json"}, '{"resultats":[]}'))
        self.assertEqual(result["check_status"], "success")
        self.assertEqual(result["active_titles"], [])
        self.assertEqual(result["message"], "Aucun titre actif trouvé")

    def test_http_200_ap_sh_and_cp_sh_returns_two_badges(self):
        result = self.run_with_response(HttpDummyResponse(200, {"Content-Type": "application/json"}, "", {"resultats": [row(activite=AP_SH), row(activite=CP_SH)]}))
        self.assertEqual(result["check_status"], "success")
        self.assertEqual(result["cnaps_active_titles"], ["AP SH ACTIF", "CP SH ACTIF"])

    def test_http_200_html_is_error(self):
        result = self.run_with_response(HttpDummyResponse(200, {"Content-Type": "text/html"}, "<html>Erreur</html>"))
        self.assertEqual(result["check_status"], "error")
        self.assertIn("HTML", result["error"])

    def test_http_429_is_error(self):
        result = self.run_with_response(HttpDummyResponse(429, {"Content-Type": "application/json"}, '{"error":"rate limited"}'))
        self.assertEqual(result["check_status"], "error")
        self.assertEqual(result["active_titles"], [])

    def test_timeout_is_error(self):
        result = self.run_with_response(post_exc=TimeoutError("CNAPS timeout"))
        self.assertEqual(result["check_status"], "error")
        self.assertEqual(result["active_titles"], [])

    def test_same_name_other_nub_retains_no_title(self):
        result = self.run_with_response(HttpDummyResponse(200, {"Content-Type": "application/json"}, "", {"resultats": [row(nub="9999999", activite=AP_SH)]}))
        self.assertEqual(result["check_status"], "success")
        self.assertEqual(result["active_titles"], [])


class HttpDummyResponse:
    def __init__(self, status_code=200, headers=None, text="", payload=None, url="https://cnaps.example/final"):
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}
        self.text = text
        self._payload = payload
        self.url = url
    def json(self):
        if self._payload is not None:
            return self._payload
        import json
        return json.loads(self.text or "{}")


if __name__ == "__main__":
    unittest.main()
