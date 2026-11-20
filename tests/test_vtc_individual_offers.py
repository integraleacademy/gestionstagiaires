"""Regression tests for individual VTC practical training / vehicle-only offers."""
from unittest import mock

from docx import Document
import fitz

import convention_design
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
    ("practice", "Contrat de formation professionnelle", "600,00 € TTC"),
    ("vehicle", "Convention de mise à disposition d’un véhicule", "150,00 € TTC"),
])
def test_generated_offer_uses_academy_model_and_signable_pdf(vtc, tmp_path, kind, title, price):
    training, trainee = vtc
    offers.update(trainee, kind, "1500")
    training.update(practice_training_date="2026-12-01", practice_training_time="09:00")
    trainee.update(vtc_exam_center="nice", personal_amount="1500")
    word, pdf = app._generate_aps_convention_files(training, trainee, output_dir=tmp_path)
    document = Document(word)
    body = " ".join(document.element.body.xpath(".//w:t/text()"))
    assert document.styles["Normal"].font.name == convention_design.FONT
    assert title in body and price in body and "Camille EXEMPLE" in body
    assert "Saint-Laurent-du-Var (06)" in body and "05/12/2026" in body
    assert "105 heures" not in body and "1 500" not in body and "1500" not in body
    assert body.count("{{s1|signature|") == 1 and body.count("{{") == 1
    assert "Article 10" in body and "franchise" in body
    assert bool(document.sections[0].header._element.xpath(".//w:drawing"))
    if kind == "practice":
        assert "Annexe 1 – Programme" in body and "RÈGLEMENT INTÉRIEUR" in body
        assert "Article 13.4" in body and "09h00 à 12h30 (3 h 30)" in body
        assert "Établir le prix d’une course" in body and "formation théorique" in body
    else:
        assert "RÈGLEMENT INTÉRIEUR" not in body and "Aucun acompte" not in body
        assert "aucune formation" in body and "Utilisation et restitution" in body
    clean, anchors = app._prepare_yousign_pdf_and_fields(pdf)
    assert len(anchors) == 1
    a = anchors[0]
    with fitz.open(clean) as pages:
        assert len(pages) >= (6 if kind == "practice" else 3)
        page = pages[a["page"] - 1]
        field = fitz.Rect(a["x"], a["y"], a["x"] + a["width"], a["y"] + a["height"])
        assert page.rect.contains(field)
        assert "Signature" in page.get_text() and not any("{{" in p.get_text() for p in pages)
        assert all("INTÉGRALE" in p.get_text().upper() and "Page " in p.get_text() for p in pages)


def test_offer_does_not_use_theory_exam_date_and_only_shows_matching_funding(vtc, tmp_path, monkeypatch):
    training, trainee = vtc
    training.pop("exam_practice_date")
    training["exam_date"] = "2026-11-25"
    trainee.update(vtc_offer="practice", cpf_amount="450", personal_amount="150")
    monkeypatch.setattr(offers, "write_pdf", lambda host, doc, *args: doc)
    doc = offers.convention(app, training, trainee, output_dir=tmp_path)
    body = " ".join(doc.element.body.xpath(".//w:t/text()"))
    assert "25/11/2026" not in body and "selon convocation officielle" in body
    assert "450,00 €" in body and "150,00 €" in body and "Mon Compte Formation" in body


def test_vehicle_examiner_pdf_is_only_vehicle_attestation(vtc):
    training, trainee = vtc
    offers.update(trainee, "vehicle", "1500")
    document = offers._examiner_document(training, trainee)
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


@pytest.fixture
def signature_case(vtc, monkeypatch):
    training, trainee = vtc
    trainee.update(
        convention_signature={},
        convocation_signature={"signature_request_id": "request-a", "status": "ongoing",
                              "signature_link": "https://example.test/old", "next_reminder_at": "2026-12-01"},
        convention_status="signing", convocation_aps_sent_at="2026-11-10",
    )
    data = {"sessions": [training]}
    monkeypatch.setattr(app, "load_data", lambda **kwargs: data)
    monkeypatch.setattr(app, "_atomic_update_data", lambda update: update(data))
    monkeypatch.setattr(app.admin_trainee_wedof_refresh, "schedule_refresh", mock.Mock())
    client = app.app.test_client()
    with client.session_transaction() as user:
        user.update(admin_logged_in=True, admin_role="admin")
    return training, trainee, client


TRAINEE_API = "/api/sessions/S-VTC-OFFERS/stagiaires/TRN-OFFERS"
CANCEL_URL = TRAINEE_API + "/convention/signature/cancel"
TRAINEE_PAGE = "/admin/sessions/S-VTC-OFFERS/stagiaires/TRN-OFFERS"


def test_cancel_only_then_change_offer_without_sending(signature_case, monkeypatch):
    training, trainee, client = signature_case
    remote = mock.Mock(side_effect=[{"status": "ongoing"}, {"status": "canceled"}])
    monkeypatch.setattr(app, "_yousign_json", remote)
    send = mock.Mock()
    monkeypatch.setattr(app, "send_yousign_signature_link_email", send)
    monkeypatch.setattr(app, "create_yousign_convention_signature", send)
    first = client.post(CANCEL_URL, json={"request_id": "request-a"})
    assert first.json == {"ok": True, "status": "canceled"}
    assert client.post(CANCEL_URL, json={"request_id": "request-a"}).json == first.json
    assert [call.args for call in remote.call_args_list] == [
        ("GET", "/signature_requests/request-a"), ("POST", "/signature_requests/request-a/cancel"),
    ]
    state = trainee["convention_signature"]
    assert state is trainee["convocation_signature"]
    assert not any(key in state for key in ("signature_link", "next_reminder_at", "signature_request_id"))
    assert len(trainee["convention_signature_history"]) == 1
    assert trainee["convention_signature_history"][0]["signature_request_id"] == "request-a"
    assert trainee["convocation_aps_sent_at"] == "2026-11-10"
    assert trainee["training_price"] == "1500"
    assert not trainee.get("registration_cancelled")
    assert client.post(TRAINEE_API + "/vtc-offer", json={"offer": "practice"}).json["training_price"] == "600"
    assert not app._auto_send_convention_signature_if_needed(training, [trainee], trainee, training["id"],
                                                              trainee["id"], trigger="financement_validated")
    send.assert_not_called()


@pytest.mark.parametrize("source,status", [("convention_signature", {"status": "completed"}),
                                         ("convention_signature", {"signed_pdf_path": "/test/signed.pdf"}),
                                         ("convention_status", "signed"), ("convention_aps_signed_at", "2026-11-01"),
                                         ("convention_legacy_signed", True)])
def test_existing_signed_evidence_protects_both_actions(signature_case, monkeypatch, source, status):
    _, trainee, client = signature_case
    trainee[source] = status
    remote = mock.Mock()
    monkeypatch.setattr(app, "_yousign_json", remote)
    assert client.post(CANCEL_URL, json={"request_id": "request-a"}).status_code == 409
    assert client.post(TRAINEE_API + "/vtc-offer", json={"offer": "vehicle"}).status_code == 409
    remote.assert_not_called()
    assert trainee["training_price"] == "1500"


@pytest.mark.parametrize("remote_responses,expected", [
    ([{"status": "done"}], 409),
    ([{"status": "ongoing"}, app.YousignAPIError(409, "changed"), {"status": "done"}], 409),
    ([RuntimeError("unavailable")], 502),
    ([{"status": "ongoing"}, RuntimeError("timeout")], 502),
    ([{"status": "canceled"}], 200),
    ([{"status": "expired"}], 200),
    ([{"status": "approval"}, {"status": "canceled"}], 200),
])
def test_reconcile_remote_status_before_unlocking(signature_case, monkeypatch, remote_responses, expected):
    _, trainee, client = signature_case
    remote = mock.Mock(side_effect=remote_responses)
    monkeypatch.setattr(app, "_yousign_json", remote)
    result = client.post(CANCEL_URL, json={"request_id": "request-a"})
    assert result.status_code == expected
    if expected != 200:
        assert trainee["convention_signature"]["signature_request_id"] == "request-a"
        assert not trainee.get("convention_signature_history")
        assert client.post(TRAINEE_API + "/vtc-offer", json={"offer": "practice"}).status_code == 409
    else:
        assert client.post(TRAINEE_API + "/vtc-offer", json={"offer": "vehicle"}).json["training_price"] == "150"


def test_stale_page_and_concurrent_replacement_cannot_cancel_new_request(signature_case, monkeypatch):
    _, trainee, client = signature_case
    remote = mock.Mock()
    monkeypatch.setattr(app, "_yousign_json", remote)
    assert client.post(CANCEL_URL, json={"request_id": "old"}).status_code == 409
    remote.assert_not_called()

    def replace_during_cancel(method, path, **kwargs):
        if method == "POST":
            app._yousign_state(trainee).update(signature_request_id="request-b", signature_link="new")
            return {"status": "canceled"}
        return {"status": "ongoing"}
    remote.side_effect = replace_during_cancel
    assert client.post(CANCEL_URL, json={"request_id": "request-a"}).status_code == 409
    assert trainee["convention_signature"]["signature_link"] == "new"
    assert not trainee.get("convention_signature_history")
    assert all("/request-a" in call.args[1] for call in remote.call_args_list)


@pytest.mark.parametrize("blocked", ["viewer", "locked", "canceled", "company"])
def test_cancel_requires_writable_individual_convention(signature_case, monkeypatch, blocked):
    _, trainee, client = signature_case
    remote = mock.Mock()
    monkeypatch.setattr(app, "_yousign_json", remote)
    if blocked == "viewer":
        with client.session_transaction() as user:
            user["admin_role"] = "viewer"
    elif blocked == "locked":
        monkeypatch.setattr(app, "_automation_partner_module_enabled", lambda: False)
    elif blocked == "canceled":
        trainee["registration_cancelled"] = True
    else:
        trainee["company_convention"] = {"name": "Test"}
    assert client.post(CANCEL_URL, json={"request_id": "request-a"}).status_code in {403, 409}
    remote.assert_not_called()


def test_offer_panel_and_signature_action_on_trainee_sheet(signature_case, monkeypatch):
    from lxml import html
    training, trainee, client = signature_case
    def sheet():
        res = client.get(TRAINEE_PAGE)
        assert res.status_code == 200
        return html.fromstring(res.data)
    page = sheet()
    panel, = page.xpath('//*[@id="vtcIndividualOffer"]')
    assert not panel.xpath('ancestor::*[contains(@class, "trainee-profile-card__identity")]')
    assert panel.xpath('.//fieldset[@disabled]')
    assert panel.xpath('.//*[@data-cancel-convention and @data-request-id="request-a"]')
    assert page.xpath('//*[@id="automationHub"]//*[@data-cancel-convention]')
    training["training_type"] = "APS"
    page = sheet()
    assert not page.xpath('//*[@id="vtcIndividualOffer"]')
    assert page.xpath('//*[@id="automationHub"]//*[@data-cancel-convention]')
    trainee["convention_aps_signed_at"] = "2026-11-20"
    assert not sheet().xpath('//*[@data-cancel-convention]')
