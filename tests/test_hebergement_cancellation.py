"""A cancelled hosting reservation must reopen booking without erasing on errors."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from lxml import html

import app as gestion_app


@pytest.fixture
def hosting_case(monkeypatch):
    trainee = {
        "id": "T-HOSTING",
        "public_token": "PUBLIC-HOSTING",
        "public_has_logged_in": True,
        "last_name": "DUPONT",
        "first_name": "Camille",
        "email": "camille@example.test",
        "hosting_status": "reserved",
        "cnaps": "ACCEPTÉ",
        "documents": [],
    }
    session = {
        "id": "S-HOSTING",
        "name": "A3P NOVEMBRE 2026",
        "training_type": "A3P",
        "date_start": "2026-11-10",
        "date_end": "2027-01-14",
        "trainees": [trainee],
    }
    data = {"sessions": [session]}
    saved = []
    monkeypatch.setattr(gestion_app, "load_data", lambda: data)
    monkeypatch.setattr(gestion_app, "save_data", lambda value: saved.append(deepcopy(value)))
    monkeypatch.setattr(gestion_app, "fetch_cnaps_status_by_name", lambda *_: "ACCEPTÉ")
    monkeypatch.setattr(gestion_app, "_hydrate_missing_trainee_nubs_from_cnaps_tracking", lambda *_: None)
    monkeypatch.setattr(gestion_app, "HEBERGEMENT_STATUS_ENDPOINT", "https://assistance.example/lookup_hebergement.json")
    monkeypatch.setattr(gestion_app.time, "sleep", lambda *_: None)
    client = gestion_app.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["admin_logged_in"] = True
        browser_session["admin_role"] = "admin"
        browser_session["public_auth_PUBLIC-HOSTING"] = True
    return client, session, trainee, saved


def mock_lookup(monkeypatch, payload, *, status_code=200):
    response = Mock(status_code=status_code, text="hosting response")
    response.json.return_value = payload
    lookup = Mock(return_value=response)
    monkeypatch.setattr(gestion_app.requests, "get", lookup)
    return lookup


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"ok": True, "reserved": False, "status": "inconnu"}, "unknown"),
        ({"ok": True, "reserved": True, "status": "réservé"}, "reserved"),
        ({"ok": False, "reserved": False}, None),
        ({"ok": False, "reserved": True}, None),
        ({"reserved": False}, None),
        ({"ok": True}, None),
        ({"status": "inconnu"}, None),
        ({}, None),
        ([], None),
        (None, None),
    ],
)
def test_lookup_distinguishes_confirmed_absence_from_inconclusive_response(hosting_case, monkeypatch, payload, expected):
    mock_lookup(monkeypatch, payload)
    assert gestion_app.fetch_hebergement_status("camille@example.test") == expected


def hosting_step(response):
    page = html.fromstring(response.data)
    return page.xpath('//div[contains(@class, "step-item")][.//div[@class="step-title" and text()="Hébergement"]]')[0]


def test_cancelled_reservation_reopens_booking_and_new_booking_is_recognized(hosting_case, monkeypatch):
    client, _, trainee, saved = hosting_case
    lookup = mock_lookup(monkeypatch, {"ok": True, "reserved": False, "status": "inconnu"})

    response = client.get("/espace/PUBLIC-HOSTING")

    assert response.status_code == 200
    step = hosting_step(response)
    assert "Aucun hébergement réservé" in step.text_content()
    assert step.xpath('.//a[normalize-space()="Réserver"]/@href') == ["https://assistance-alw9.onrender.com/hebergement"]
    assert not step.xpath('.//span[normalize-space()="Réservé" or normalize-space()="RÉSERVÉ"]')
    assert trainee["hosting_status"] == "unknown"
    assert saved[-1]["sessions"][0]["trainees"][0]["hosting_status"] == "unknown"
    lookup.assert_called_once()

    lookup.return_value.json.return_value = {"ok": True, "reserved": True, "status": "réservé"}
    response = client.get("/espace/PUBLIC-HOSTING")

    assert response.status_code == 200
    step = hosting_step(response)
    assert not step.xpath('.//a[normalize-space()="Réserver"]')
    assert trainee["hosting_status"] == "reserved"
    assert saved[-1]["sessions"][0]["trainees"][0]["hosting_status"] == "reserved"


@pytest.mark.parametrize("failure", ["http", "timeout", "invalid_json", "incomplete", "rejected"])
def test_lookup_failure_preserves_existing_booking(hosting_case, monkeypatch, failure):
    client, _, trainee, saved = hosting_case
    lookup = mock_lookup(monkeypatch, {"ok": True}, status_code=503 if failure == "http" else 200)
    if failure == "timeout":
        lookup.side_effect = gestion_app.requests.Timeout("temporary unavailability")
    elif failure == "invalid_json":
        lookup.return_value.json.side_effect = ValueError("invalid response")
    elif failure == "rejected":
        lookup.return_value.json.return_value = {"ok": False, "reserved": False}

    response = client.get("/espace/PUBLIC-HOSTING")

    assert response.status_code == 200
    assert trainee["hosting_status"] == "reserved"
    assert saved[-1]["sessions"][0]["trainees"][0]["hosting_status"] == "reserved"
    assert not hosting_step(response).xpath('.//a[normalize-space()="Réserver"]')


@pytest.mark.parametrize("path", [
    "/admin/sessions/S-HOSTING/trainees",
    "/admin/sessions/S-HOSTING/stagiaires/T-HOSTING",
])
def test_admin_pages_also_persist_confirmed_cancellation(hosting_case, monkeypatch, path):
    client, _, trainee, saved = hosting_case
    mock_lookup(monkeypatch, {"ok": True, "reserved": False})
    monkeypatch.setattr(gestion_app, "render_template", lambda *args, **kwargs: "ok")

    response = client.get(path)

    assert response.status_code == 200
    assert trainee["hosting_status"] == "unknown"
    assert saved[-1]["sessions"][0]["trainees"][0]["hosting_status"] == "unknown"


def test_external_refresh_api_persists_cancellation_and_does_not_repeat_save(hosting_case, monkeypatch):
    client, _, trainee, saved = hosting_case
    mock_lookup(monkeypatch, {"ok": True, "reserved": False})

    response = client.post("/api/sessions/S-HOSTING/stagiaires/T-HOSTING/refresh-external")

    assert response.status_code == 200
    assert response.get_json()["hosting_status"] == "unknown"
    assert trainee["hosting_status"] == "unknown"
    assert len(saved) == 1
    assert saved[-1]["sessions"][0]["trainees"][0]["hosting_status"] == "unknown"

    response = client.post("/api/sessions/S-HOSTING/stagiaires/T-HOSTING/refresh-external")
    assert response.status_code == 200
    assert len(saved) == 1


def test_non_a3p_trainee_does_not_call_hosting_service(hosting_case, monkeypatch):
    _, session, trainee, _ = hosting_case
    session["training_type"] = "APS"
    lookup = mock_lookup(monkeypatch, {"ok": True, "reserved": False})

    assert gestion_app._refresh_trainee_hebergement_status(session, trainee) is False
    lookup.assert_not_called()
