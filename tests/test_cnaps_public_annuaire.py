import json
import unittest
from unittest import mock

import app as gestion_app


ENDPOINT = "https://espace-consultation.cnaps.interieur.gouv.fr/annuaire/api/back/public/annuaire/search/personne-physique"
AP_SH = "Autorisation préalable - Surveillance humaine ou gardiennage"
CP_SH = "Carte professionnelle - Surveillance humaine ou gardiennage"
REAL_RESPONSE = {
    "results": [
        {"id": 1134465, "siret": None, "raisonSociale": None, "nom": "LARDJANE", "prenom": "Zinedine", "nub": "1000731", "typeActivite": AP_SH, "agrementStatutEs": "ACTIF", "dateFinValidite": "2026-10-07", "recepisse": False},
        {"id": 1451678, "siret": None, "raisonSociale": None, "nom": "LARDJANE", "prenom": "Zinedine", "nub": "1000731", "typeActivite": CP_SH, "agrementStatutEs": "ACTIF", "dateFinValidite": "2031-06-30", "recepisse": False},
    ],
    "totalElements": 2,
    "nbElements": 2,
    "pageNumber": 0,
    "pageSize": 10,
    "totalPages": 1,
}


def api_row(nub="1000731", nom="LARDJANE", activity=AP_SH, status="ACTIF", date="2026-10-07"):
    return {"nom": nom, "prenom": "Zinedine", "nub": nub, "typeActivite": activity, "agrementStatutEs": status, "dateFinValidite": date, "recepisse": False}


def response(payload, status=200, content_type="application/json"):
    return HttpDummyResponse(status, {"Content-Type": content_type}, json.dumps(payload), payload)


class CnapsPublicAnnuaireTests(unittest.TestCase):
    def setUp(self):
        self.original_endpoint = gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT
        gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT = ENDPOINT

    def tearDown(self):
        gestion_app.CNAPS_PUBLIC_ANNUAIRE_ENDPOINT = self.original_endpoint

    def run_fetch(self, responses=None, post_exc=None):
        calls = []
        responses = list(responses or [])

        class DummySession:
            def post(self, url, **kwargs):
                calls.append({"url": url, **kwargs})
                if post_exc:
                    raise post_exc
                return responses.pop(0)

        with mock.patch.object(gestion_app.requests, "Session", return_value=DummySession()):
            result = gestion_app.fetch_cnaps_public_annuaire("LARDJANE", "1000731")
        return result, calls

    def test_real_response_endpoint_post_body_json_and_two_titles(self):
        result, calls = self.run_fetch([response(REAL_RESPONSE)])
        expected_body = {"nom": "LARDJANE", "nub": "1000731", "page": 0, "size": 10, "sorts": [{"field": "nom", "asc": True}, {"field": "dateFinValidite", "asc": True}]}
        self.assertEqual(calls[0]["url"], ENDPOINT)
        self.assertIn("json", calls[0])
        self.assertEqual(calls[0]["json"], expected_body)
        self.assertNotIn("data", calls[0])
        self.assertEqual(result["total_elements"], 2)
        self.assertEqual(len(result["titles"]), 2)
        self.assertEqual(result["cnaps_active_titles"], ["AP SH ACTIF", "CP SH ACTIF"])
        by_code = {t["code"]: t for t in result["titles"]}
        self.assertEqual(by_code["AP SH"]["date_fin_validite"], "2026-10-07")
        self.assertEqual(by_code["CP SH"]["date_fin_validite"], "2031-06-30")
        self.assertEqual({t["label"] for t in result["titles"]}, {AP_SH, CP_SH})

    def test_results_empty_is_success(self):
        result, _ = self.run_fetch([response({"results": [], "totalElements": 0, "totalPages": 1})])
        self.assertEqual(result["check_status"], "success")
        self.assertEqual(result["message"], "Aucun titre CNAPS trouvé")

    def test_nub_different_rejected(self):
        result, _ = self.run_fetch([response({"results": [api_row(nub="999")], "totalPages": 1})])
        self.assertEqual(result["titles"], [])

    def test_nom_different_same_nub_rejected(self):
        result, _ = self.run_fetch([response({"results": [api_row(nom="DUPONT")], "totalPages": 1})])
        self.assertEqual(result["titles"], [])

    def test_non_active_status_is_kept_but_not_active(self):
        result, _ = self.run_fetch([response({"results": [api_row(status="INACTIF")], "totalPages": 1})])
        self.assertEqual(result["titles"][0]["display_status"], "AP SH INACTIF")
        self.assertEqual(result["cnaps_active_titles"], [])

    def test_unknown_type_keeps_original_information(self):
        unknown = "Autorisation spéciale - Activité future"
        result, _ = self.run_fetch([response({"results": [api_row(activity=unknown)], "totalPages": 1})])
        self.assertEqual(result["titles"][0]["code"], unknown)
        self.assertEqual(result["titles"][0]["label"], unknown)

    def test_missing_results_is_error(self):
        result, _ = self.run_fetch([response({"resultats": []})])
        self.assertEqual(result["check_status"], "error")
        self.assertEqual(result["message"], "Vérification CNAPS impossible")

    def test_non_json_is_error(self):
        result, _ = self.run_fetch([HttpDummyResponse(200, {"Content-Type": "text/html"}, "<html>")])
        self.assertEqual(result["check_status"], "error")

    def test_http_404_and_500_are_errors(self):
        for status in (404, 500):
            result, _ = self.run_fetch([response({"results": []}, status=status)])
            self.assertEqual(result["check_status"], "error")
            self.assertEqual(result["http_status"], status)

    def test_timeout_is_error(self):
        result, _ = self.run_fetch(post_exc=TimeoutError("CNAPS timeout"))
        self.assertEqual(result["check_status"], "error")

    def test_multiple_pages_are_concatenated(self):
        p0 = {"results": [api_row(activity=AP_SH)], "totalPages": 2, "totalElements": 2}
        p1 = {"results": [api_row(activity=CP_SH, date="2031-06-30")], "totalPages": 2, "totalElements": 2}
        result, calls = self.run_fetch([response(p0), response(p1)])
        self.assertEqual([c["json"]["page"] for c in calls], [0, 1])
        self.assertEqual(result["cnaps_active_titles"], ["AP SH ACTIF", "CP SH ACTIF"])

    def test_exact_duplicate_across_pages_is_deduplicated_not_by_nub(self):
        p0 = {"results": [api_row(activity=AP_SH), api_row(activity=CP_SH, date="2031-06-30")], "totalPages": 2}
        p1 = {"results": [api_row(activity=AP_SH), api_row(activity=CP_SH, date="2031-06-30")], "totalPages": 2}
        result, _ = self.run_fetch([response(p0), response(p1)])
        self.assertEqual(len(result["titles"]), 2)
        self.assertEqual(result["cnaps_active_titles"], ["AP SH ACTIF", "CP SH ACTIF"])


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
        return json.loads(self.text or "{}")


if __name__ == "__main__":
    unittest.main()
