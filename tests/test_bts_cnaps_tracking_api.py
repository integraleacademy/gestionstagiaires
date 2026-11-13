import copy
import hashlib
import hmac
import json

import pytest
import requests
from flask import Flask

import bts_cnaps_tracking_api as tracking


KEY = "test-key-for-bts-integration-" + "x" * 40
CID = "candidate-security"
CANDIDATE = {"id": CID, "bts": "PARCOURS-SECURITE", "nom": "De la Côte", "prenom": "Élodie",
             "email": "elodie@example.test", "date_naissance": "2001-02-03"}
ROW = {"id": 22, "nom": "DE LA COTE", "prenom": "ELODIE", "email": "elodie@example.test",
       "date_naissance": "03/02/2001", "nub": "1234567", "statut_cnaps": "TRANSMIS",
       "formation": "APS", "session_date": "2027-01", "created_at": "2026-11-13T09:00:00Z"}
PATH = f"/api/integrations/bts/candidats/{CID}/cnaps-tracking"
HEADERS = {"Authorization": "Bearer " + hmac.new(KEY.encode(), tracking.TOKEN_CONTEXT, hashlib.sha256).hexdigest()}


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("BTS_IMPORT_API_KEY", KEY)
    app = Flask(__name__)
    app.config["TESTING"] = True
    candidate = copy.deepcopy(CANDIDATE)
    state = {"rows": [copy.deepcopy(ROW)], "lookups": [], "candidate_calls": [], "annuaire_calls": []}

    def read_candidate(cid):
        state["candidate_calls"].append(cid)
        return copy.deepcopy(candidate)

    def read_tracking(person):
        state["lookups"].append(copy.deepcopy(person))
        if state.get("error"):
            raise state["error"]
        return copy.deepcopy(state["rows"])

    def annuaire(nom, nub):
        state["annuaire_calls"].append((nom, nub))
        if state.get("annuaire_error"):
            raise RuntimeError("Unavailable")
        return {"checked_at": "2026-11-13T10:00:00Z", "check_status": "success",
                "titles": [{"code": "AP SH", "status": "ACTIF", "expires_at": "2027-06-01"}],
                "token": "MUST-NOT-LEAK"}

    tracking.register_bts_cnaps_tracking_api(app, candidate_fetcher=read_candidate,
                                            tracking_fetcher=read_tracking, annuaire_fetcher=annuaire)
    return app.test_client(), candidate, state


def test_authentication_uses_only_the_derived_bts_key(service, monkeypatch):
    client, _, state = service
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Bearer " + KEY},
                    {"Authorization": "Bearer café"}):
        assert client.get(PATH, headers=headers).status_code == 401
    assert state["candidate_calls"] == state["lookups"] == []
    monkeypatch.setenv("BTS_IMPORT_API_KEY", "too-short")
    assert client.get(PATH, headers=HEADERS).status_code == 503
    assert state["candidate_calls"] == []


def test_trusted_candidate_identity_and_minimal_tracking_response(service):
    client, candidate, state = service
    candidate["private_token"] = "MUST-NOT-LEAK"
    state["rows"][0].update(password="MUST-NOT-LEAK", source_url="https://malicious.example/")
    response = client.get(PATH + "?nom=Other&prenom=Person", headers=HEADERS)
    assert response.status_code == 200
    result = response.json
    assert state["lookups"][0]["nom"] == CANDIDATE["nom"]
    assert result["found"] is True
    assert result["source_url"] == tracking.SOURCE_URL
    assert result["cnaps"]["cnaps_status"] == "TRANSMIS"
    assert result["cnaps"]["titles"] == [{"type": "AP SH", "state": "ACTIF", "expires_at": "2027-06-01"}]
    assert result["inscription"] == "APS · 2027-01"
    body = response.get_data(as_text=True)
    assert "MUST-NOT-LEAK" not in body and "elodie@example.test" not in body and "2001-02-03" not in body


def test_eligibility_and_identity_checked_before_remote_lookup(service):
    client, candidate, state = service
    candidate["bts"] = "MOS"
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 403 and response.json["reason"] == "ineligible_candidate"
    candidate.update(bts="PARCOURS-SECURITE", nom="")
    assert client.get(PATH, headers=HEADERS).status_code == 422
    candidate.update(nom="Martin", id="someone-else")
    assert client.get(PATH, headers=HEADERS).status_code == 502
    assert state["lookups"] == []


def test_no_match_is_a_clear_state_and_never_checks_public_annuaire(service):
    client, _, state = service
    state["rows"] = [{**ROW, "nom": "Another"}]
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 200
    assert response.json["found"] is False and response.json["reason"] == "cnaps_not_found"
    assert state["annuaire_calls"] == []


def test_email_and_birth_date_disambiguate_namesakes(service):
    client, _, state = service
    state["rows"].append({**ROW, "id": 55, "email": "other@example.test", "date_naissance": "04/02/2001", "nub": "7654321"})
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 200
    assert response.json["cnaps"]["nub"] == "1234567"
    assert response.json["match_count"] == 1


@pytest.mark.parametrize("changes,reason", [
    ({"email": "other@example.test", "date_naissance": ""}, "identity_mismatch"),
    ({"date_naissance": "04/02/2001"}, "identity_mismatch"),
])
def test_contradictory_identity_is_never_returned(service, changes, reason):
    client, _, state = service
    state["rows"][0].update(changes)
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 409 and response.json["reason"] == reason
    assert state["annuaire_calls"] == []


def test_distinct_nubs_are_ambiguous_even_when_names_match(service):
    client, _, state = service
    state["rows"].append({**ROW, "id": 55, "nub": "7654321"})
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 409 and response.json["reason"] == "ambiguous_match"
    assert state["annuaire_calls"] == []


def test_duplicate_requests_for_same_identity_have_a_deterministic_result(service):
    client, _, state = service
    state["rows"].append({**ROW, "id": 55, "statut_cnaps": "ACCEPTÉ", "updated_at": "2026-11-13T12:00:00Z"})
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 200 and response.json["match_count"] == 2
    assert response.json["cnaps"]["cnaps_status"] == "ACCEPTÉ"


def test_exact_name_normalization_matches_source_without_prefix_guessing(service):
    client, candidate, state = service
    candidate.update(nom="D’Angelo", prenom="Jean-Pierre")
    state["rows"] = [{**ROW, "nom": "D Angelo", "prenom": "Jean Pierre"}]
    assert client.get(PATH, headers=HEADERS).json["found"] is True
    candidate["prenom"] = "Jean"
    assert client.get(PATH, headers=HEADERS).json["found"] is False


def test_cache_refresh_and_identity_changes(service):
    client, candidate, state = service
    assert client.get(PATH, headers=HEADERS).json["cached"] is False
    assert client.get(PATH, headers=HEADERS).json["cached"] is True
    assert len(state["lookups"]) == 1
    assert len(state["candidate_calls"]) == 2
    assert client.get(PATH + "?refresh=1", headers=HEADERS).json["cached"] is False
    assert len(state["lookups"]) == 2
    candidate["email"] = "updated@example.test"
    assert client.get(PATH, headers=HEADERS).json["cached"] is False
    assert len(state["lookups"]) == 3
    candidate["bts"] = "MOS"
    assert client.get(PATH, headers=HEADERS).status_code == 403
    assert len(state["lookups"]) == 3


def test_remote_failure_preserves_previous_result_but_not_ambiguity(service):
    client, _, state = service
    assert client.get(PATH, headers=HEADERS).status_code == 200
    state["error"] = tracking.TrackingError("Indisponible")
    response = client.get(PATH + "?refresh=1", headers=HEADERS)
    assert response.status_code == 200 and response.json["stale"] is True
    assert response.json["refresh_failed"] is True
    assert response.json["cnaps"]["cnaps_status"] == "TRANSMIS"
    state["error"] = tracking.TrackingError("Ambigu", 409, "ambiguous_match")
    response = client.get(PATH + "?refresh=1", headers=HEADERS)
    assert response.status_code == 409


def test_annuaire_failure_keeps_previous_titles_with_unavailable_notice(service):
    client, _, state = service
    first = client.get(PATH, headers=HEADERS).json
    state["annuaire_error"] = True
    response = client.get(PATH + "?refresh=1", headers=HEADERS)
    assert response.status_code == 200
    assert response.json["cnaps"]["cnaps_unavailable"] is True
    assert response.json["cnaps"]["titles_stale"] is True
    assert response.json["cnaps"]["titles"] == first["cnaps"]["titles"]
    assert response.json["cnaps"]["last_checked_at"] == first["cnaps"]["last_checked_at"]


class RemoteResponse:
    def __init__(self, payload=None, status=200, content_type="application/json"):
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.content = json.dumps(payload if payload is not None else {"success": True, "requests": [ROW]}).encode()
        self.closed = False

    def iter_content(self, size):
        yield self.content

    def close(self):
        self.closed = True


def test_remote_client_uses_only_readonly_endpoint_and_does_not_follow_redirects(monkeypatch):
    monkeypatch.setenv("CNAPSV3_API_TOKEN", "server-only-cnaps-key")
    monkeypatch.setenv("CNAPSV3_BASE_URL", "https://cnapsv3.onrender.com/")
    calls = []
    response = RemoteResponse()
    assert tracking.fetch_tracking_requests(CANDIDATE, http_get=lambda *a, **kw: calls.append((a, kw)) or response) == [ROW]
    args, kwargs = calls[0]
    assert args[0] == "https://cnapsv3.onrender.com/api/cnaps-tracking"
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"]["Authorization"] == "Bearer server-only-cnaps-key"
    assert kwargs["params"] == {"nom": CANDIDATE["nom"], "prenom": CANDIDATE["prenom"]}
    assert response.closed is True


@pytest.mark.parametrize("response", [RemoteResponse(status=302), RemoteResponse(status=401),
    RemoteResponse(content_type="text/html"), RemoteResponse(payload={"success": True, "requests": "wrong"})])
def test_remote_client_fails_safely_without_fallback(monkeypatch, response):
    monkeypatch.setenv("CNAPSV3_API_TOKEN", "server-only-cnaps-key")
    calls = []
    with pytest.raises(tracking.TrackingError):
        tracking.fetch_tracking_requests(CANDIDATE, http_get=lambda *a, **kw: calls.append(a[0]) or response)
    assert len(calls) == 1 and calls[0].endswith("/api/cnaps-tracking")
    assert response.closed is True


def test_remote_network_exception_does_not_expose_tokens(monkeypatch):
    monkeypatch.setenv("CNAPSV3_API_TOKEN", "server-only-cnaps-key")
    def fail(*a, **kw):
        raise requests.ConnectionError("server-only-cnaps-key")
    with pytest.raises(tracking.TrackingError) as exc:
        tracking.fetch_tracking_requests(CANDIDATE, http_get=fail)
    assert "server-only-cnaps-key" not in str(exc.value)

