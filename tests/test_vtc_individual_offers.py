"""Regression tests for individual VTC practical training / vehicle-only offers."""
from unittest import mock

from docx import Document
import pytest

import app
import vtc_elearning_activation as activation
import vtc_individual_offers as offers
from elearning_native.vtc_enrolments import effective_learner_session


@pytest.fixture
def vtc():
    session = {
        "id": "S-VTC-OFFERS", "name": "CHAUFFEUR VTC", "training_type": "VTC",
        "date_start": "2026-12-01", "date_end": "2026-12-02",
        "exam_practice_date": "2026-12-05",
    }
    trainee = {
        "id": "TRN-OFFERS", "first_name": "Camille", "last_name": "Exemple",
        "phone": "0600000000", "email": "camille@example.test",
        "address": "1 rue du Test", "zip_code": "83480", "city": "Puget-sur-Argens",
        "training_price": "1500",
    }
    session["trainees"] = [trainee]
    return session, trainee


def test_prices_and_mutually_exclusive_value_with_restoration(vtc):
    _, trainee = vtc
    assert offers.offer(trainee) == "full"
    assert offers.update(trainee, "practice", "1500")
    assert offers.reduced(trainee)
    assert trainee["training_price"] == "600"
    assert offers.update(trainee, "vehicle", "1500")
    assert trainee["training_price"] == "150"
    assert not offers.update(trainee, "vehicle", "1500")
    assert offers.update(trainee, "full", "1500")
    assert trainee["training_price"] == "1500"
    assert not offers.reduced(trainee)


@pytest.mark.parametrize("kind, price", [("practice", "600"), ("vehicle", "150")])
def test_no_elearning_even_for_previously_activated_account(vtc, kind, price):
    training, trainee = vtc
    offers.update(trainee, kind, "1500")
    assert trainee["training_price"] == price
    assert not activation.eligible(app, training, trainee)
    activation.schedule_new_enrolment(app, training, trainee)
    assert activation.STATE_KEY not in trainee
    trainee[activation.STATE_KEY] = {
        "activated_at": "2026-11-19T08:00:00+00:00",
        "modules": [{"course_id": "academy-vtc-a"}],
    }
    for resolver in (activation.learner_session, effective_learner_session):
        visible = resolver(training, trainee)
        assert visible["aps_elearning_enabled"] is False
        assert not visible["aps_native_modules"]
        assert not visible["vtc_auto_access_available"]


@pytest.mark.parametrize("kind, title, price", [
    ("practice", "CONTRAT DE FORMATION PRATIQUE VTC", "600 €"),
    ("vehicle", "CONVENTION DE MISE À DISPOSITION D’UN VÉHICULE", "150 €"),
])
def test_distinct_conventions_have_exact_prices_and_no_theory(vtc, kind, title, price):
    training, trainee = vtc
    offers.update(trainee, kind, "1500")
    document = offers._make_document(training, trainee, practice_slot={"date": "2026-12-01", "start": "09:00", "end": "12:00"})
    body = "\n".join(p.text for p in document.paragraphs)
    assert title in body
    assert price in body
    assert "{{s1|signature|160|80}}" in body
    assert "Aptos" == document.styles["Normal"].font.name
    assert "Aucune formation, aucun cours théorique" in body if kind == "vehicle" else "Objectifs : prise en charge" in body


def test_vehicle_examiner_pdf_is_only_vehicle_attestation(vtc):
    training, trainee = vtc
    offers.update(trainee, "vehicle", "1500")
    document = offers._make_document(training, trainee, examiner=True)
    body = "\n".join(p.text for p in document.paragraphs)
    assert "DOCUMENT À PRÉSENTER AUX EXAMINATEURS" in body
    assert "Attestation de mise à disposition" in body
    assert "Formation pratique" not in body
    assert "600 €" not in body
    assert "CMA" in body
    assert "05/12/2026" in body


def test_non_vtc_records_cannot_choose_these_offers(vtc, monkeypatch):
    training, trainee = vtc
    training["training_type"] = "APS"
    monkeypatch.setattr(app, "_atomic_update_data", lambda fn: fn({"sessions": [training]}))
    client = app.app.test_client()
    with client.session_transaction() as user:
        user["admin_logged_in"] = True
        user["admin_role"] = "admin"
    response = client.post(
        "/api/sessions/S-VTC-OFFERS/stagiaires/TRN-OFFERS/vtc-offer",
        json={"offer": "practice"},
    )
    assert response.status_code == 409
    assert trainee.get("training_price") == "1500"
    assert offers.offer(trainee) == "full"


def test_offer_api_updates_price_together_with_selection(vtc, monkeypatch):
    training, trainee = vtc
    monkeypatch.setattr(app, "_atomic_update_data", lambda fn: fn({"sessions": [training]}))
    client = app.app.test_client()
    with client.session_transaction() as user:
        user["admin_logged_in"] = True
        user["admin_role"] = "admin"
    response = client.post(
        "/api/sessions/S-VTC-OFFERS/stagiaires/TRN-OFFERS/vtc-offer",
        json={"offer": "vehicle"},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json == {"ok": True, "offer": "vehicle", "training_price": "150"}
    assert trainee["training_price"] == "150"
    assert trainee["elearning_link"] == ""
    assert trainee["vtc_elearning_manual_ok"] is False


def test_existing_yousign_request_blocks_uncontrolled_contract_switch(vtc, monkeypatch):
    training, trainee = vtc
    trainee["convention_signature"] = {"signature_request_id": "sig-already-sent", "status": "ongoing"}
    monkeypatch.setattr(app, "_atomic_update_data", lambda fn: fn({"sessions": [training]}))
    client = app.app.test_client()
    with client.session_transaction() as user:
        user["admin_logged_in"] = True
        user["admin_role"] = "admin"
    response = client.post(
        "/api/sessions/S-VTC-OFFERS/stagiaires/TRN-OFFERS/vtc-offer",
        json={"offer": "practice"},
    )
    assert response.status_code == 409
    assert "Yousign" in response.json["error"]
    assert offers.offer(trainee) == "full"
