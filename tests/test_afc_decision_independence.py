"""CNAPS priority must never override the AFC recruitment decision."""

import copy
import re
from unittest.mock import Mock

import pytest

import app as gestion_app


@pytest.fixture
def afc_record(monkeypatch):
    candidate = {
        "id": "AFC-DECISION-TEST",
        "nom": "EXEMPLE",
        "prenom": "Camille",
        "email": "candidate@example.com",
        "decision": "NON RETENU",
        "motif_refus": "Projet à préciser",
        "complement_refus": "Autre",
        "complement_refus_autre": "Nouvel entretien nécessaire",
        "cnaps_priority": True,
        "cnaps_status": "INCONNU",
        "presence_afc_status": "PRESENT",
        "notification_status": "ENVOYEE",
        "notification_sent_at": "2026-08-01T09:00:00Z",
    }
    stored = {"afc": {"candidates": [candidate]}, "sessions": [], "positioning_tests": []}

    def save(updated):
        stored.clear()
        stored.update(copy.deepcopy(updated))

    monkeypatch.setattr(gestion_app, "load_data", lambda: copy.deepcopy(stored))
    monkeypatch.setattr(gestion_app, "save_data", save)
    email = Mock()
    sms = Mock()
    monkeypatch.setattr(gestion_app, "brevo_send_email", email)
    monkeypatch.setattr(gestion_app, "brevo_send_sms", sms)
    client = gestion_app.app.test_client()
    with client.session_transaction() as session:
        session["admin_logged_in"] = True
        session["admin_role"] = "admin"
    yield client, stored
    email.assert_not_called()
    sms.assert_not_called()


def current(stored):
    return stored["afc"]["candidates"][0]


def assert_decision_survives_navigation(client, stored, expected):
    for path in (
        "/admin/afc/candidates/AFC-DECISION-TEST",
        "/admin/afc",
        "/admin/afc/export",
        "/admin/afc/candidates/AFC-DECISION-TEST",
    ):
        response = client.get(path)
        assert response.status_code == 200
        if "/candidates/" in path:
            options = re.search(
                r'<select id="decision">(.*?)</select>', response.get_data(as_text=True), re.S
            ).group(1)
            selected = re.findall(r'<option value="([^"]*)" selected', options)
            assert selected == ([expected["decision"]] if expected["decision"] else [])
        for key, value in expected.items():
            assert current(stored).get(key) == value, (path, key)


@pytest.mark.parametrize("decision", ["", "NON RETENU", "RETENU"])
def test_opening_cnaps_priority_candidate_preserves_existing_decision(afc_record, decision):
    client, stored = afc_record
    current(stored)["decision"] = decision
    expected = {key: current(stored)[key] for key in (
        "decision", "motif_refus", "complement_refus", "complement_refus_autre",
        "notification_status", "notification_sent_at",
    )}
    assert_decision_survives_navigation(client, stored, expected)


@pytest.mark.parametrize("decision", ["", "NON RETENU", "RETENU"])
@pytest.mark.parametrize("priority", [False, True])
def test_toggling_cnaps_does_not_make_a_recruitment_decision(afc_record, decision, priority):
    client, stored = afc_record
    current(stored).update(decision=decision, cnaps_priority=not priority)
    expected = {key: current(stored)[key] for key in (
        "decision", "motif_refus", "complement_refus", "complement_refus_autre",
        "notification_status", "notification_sent_at",
    )}
    response = client.patch(
        "/api/admin/afc/candidates/AFC-DECISION-TEST", json={"cnaps_priority": priority}
    )
    assert response.status_code == 200
    assert current(stored)["cnaps_priority"] is priority
    if priority:
        assert current(stored)["cnaps_status"] == "ACCEPTE"
    assert_decision_survives_navigation(client, stored, expected)


@pytest.mark.parametrize("decision", ["", "NON RETENU", "RETENU"])
def test_explicit_decision_is_saved_with_cnaps_checked(afc_record, decision):
    client, stored = afc_record
    expected = {
        "decision": decision,
        "motif_refus": "Projet à préciser" if decision == "NON RETENU" else "",
        "complement_refus": "Autre" if decision == "NON RETENU" else "",
        "complement_refus_autre": "Nouvel entretien nécessaire" if decision == "NON RETENU" else "",
    }
    response = client.patch(
        "/api/admin/afc/candidates/AFC-DECISION-TEST",
        json={**expected, "cnaps_priority": True, "presence_afc_status": "PRESENT"},
    )
    assert response.status_code == 200
    assert_decision_survives_navigation(client, stored, expected)


def test_absent_candidate_stays_rejected_despite_cnaps_priority(afc_record):
    client, stored = afc_record
    current(stored)["decision"] = "RETENU"
    response = client.patch(
        "/api/admin/afc/candidates/AFC-DECISION-TEST",
        json={"presence_afc_status": "ABSENT", "cnaps_priority": True},
    )
    assert response.status_code == 200
    assert_decision_survives_navigation(client, stored, {
        "decision": "NON RETENU",
        "motif_refus": gestion_app.AFC_ABSENCE_REFUSAL_REASON,
        "complement_refus": "",
        "complement_refus_autre": "",
    })
