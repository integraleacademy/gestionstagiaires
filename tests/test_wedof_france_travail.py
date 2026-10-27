"""Real WEDOF solicitation shapes, with synthetic IDs and amounts only."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from cpf_tracking import build_cpf_view, france_travail_view
from wedof_matching import extract_folder


def folder(solicitations, **changes):
    return {
        "externalId": "CPF-TEST", "type": "cpf", "state": "accepted",
        "trainingActionInfo": {"totalIncl": 4200, "solicitations": solicitations},
        **changes,
    }


def solicitation(status="validated", amount=1200, funding_type=9, **changes):
    return {"fundingType": funding_type, "amount": amount, "status": status,
            "submissionDate": "2026-10-10T12:00:00Z", **changes}


@pytest.mark.parametrize("funding_type", [9, "9", "POLE_EMPLOI"])
def test_validated_grant_is_identified_and_normalization_is_idempotent(funding_type):
    result = extract_folder(folder([solicitation(funding_type=funding_type)]))
    assert result["france_travail_amount"] == "1200.00"
    assert result["france_travail_status"] == "validated"
    assert result["total_amount"] == 4200
    assert extract_folder(result) == result
    assert france_travail_view(result)["label"] == "Financement France Travail"


@pytest.mark.parametrize("status,label", [
    ("inProgress", "France Travail · en cours"),
    ("refused", "France Travail · refusé"),
    ("futureStatus", "France Travail · à vérifier"),
])
def test_unconfirmed_requests_are_never_presented_as_awarded(status, label):
    result = extract_folder(folder([solicitation(status=status)], franceTravailAmount=1200))
    assert result["france_travail_amount"] is None
    view = france_travail_view(result)
    assert view["label"] == label
    assert view["amount"] == ("1200.00" if status == "inProgress" else None)


@pytest.mark.parametrize("items", [[], [solicitation(funding_type=29)], ["9", None, {}]])
def test_cpf_only_and_candidate_payment_have_no_france_travail_badge(items):
    assert france_travail_view(extract_folder(folder(items))) is None


@pytest.mark.parametrize("amount", [None, "", "invalid", -1, True, float("nan"), float("inf")])
def test_missing_or_invalid_amount_keeps_confirmed_funder_without_inventing_a_sum(amount):
    view = france_travail_view(extract_folder(folder([solicitation(amount=amount)])))
    assert view["label"] == "Financement France Travail"
    assert view["amount"] is None
    assert view["amount_label"] == "Non communiqué"


def test_zero_amount_is_not_a_financial_contribution():
    assert france_travail_view(extract_folder(folder([solicitation(amount=0)]))) is None


def test_latest_request_wins_regardless_of_payload_order_without_double_counting():
    old = solicitation(amount=1200, submissionDate="2026-10-01T12:00:00Z")
    latest = solicitation(status="inProgress", amount=1400, submissionDate="2026-10-12T12:00:00Z")
    for items in ([old, latest], [latest, old]):
        result = extract_folder(folder(items))
        assert result["france_travail_amount"] is None
        assert result["france_travail_requested_amount"] == "1400.00"
        assert result["france_travail_status"] == "inProgress"


def test_french_amount_and_legacy_snapshot_are_supported():
    view = france_travail_view({"france_travail_amount": "1\u202f234,56"})
    assert view["amount"] == "1234.56"
    assert view["amount_label"] == "1\u202f234,56 €"


def test_cancelled_folder_does_not_present_the_grant_as_current():
    view = france_travail_view(extract_folder(folder(
        [solicitation()], state="canceledByAttendeeNotRealized",
    )))
    assert "dossier annulé" in view["label"]
    assert "Abondement initial" in view["detail"]


def test_link_refresh_persists_funding_and_removes_a_stale_awarded_grant(monkeypatch):
    import app

    client = Mock()
    client.get_registration_folder_interactive.return_value = folder([solicitation()])
    monkeypatch.setattr(app, "WedofClient", lambda: client)
    monkeypatch.setattr(app, "sync_folder_automation_status", Mock())
    data = {"wedof_automation_status": []}
    link = {"external_id": "CPF-TEST"}
    app._refresh_cpf_link_from_wedof(data, link)
    assert link["cpf_snapshot"]["france_travail_amount"] == "1200.00"
    assert link["cpf_snapshot"]["france_travail_status"] == "validated"
    assert data["wedof_folder_cache"][0]["france_travail_amount"] == "1200.00"
    client.get_registration_folder_interactive.return_value = folder([solicitation(status="refused")])
    app._refresh_cpf_link_from_wedof(data, link)
    assert link["cpf_snapshot"].get("france_travail_amount") is None
    assert france_travail_view(link["cpf_snapshot"])["label"] == "France Travail · refusé"


def test_cofunding_is_informational_and_does_not_change_billing_totals():
    import app

    trainee = {"id": "T1", "training_price": 4200, "cpf_amount": 4200,
               "personal_amount": 0, "other_amount": 0}
    session = {"id": "S1"}
    data = {"wedof_links": [{"active": True, "trainee_id": "T1", "session_id": "S1",
                            "cpf_snapshot": extract_folder(folder([solicitation()]))}]}
    before = deepcopy((trainee, data))
    financial = app.calculate_trainee_financial_summary(trainee, [])
    view = build_cpf_view(trainee, session, data)
    assert view["france_travail"]["amount"] == "1200.00"
    assert (trainee, data) == before
    assert app.calculate_trainee_financial_summary(trainee, []) == financial
    assert financial["planned_total_cents"] == 0
    # Only the associated registration's funding may be displayed.
    assert build_cpf_view(trainee, {"id": "S2"}, data)["france_travail"] is None


def test_rendered_funding_card_distinguishes_missing_amount_and_stale_data():
    env = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape())
    card = env.get_template("_cpf_france_travail.html").module.funding_card
    view = france_travail_view(extract_folder(folder([solicitation(amount=None)])))
    html = card(view, "27/10/2026 à 08h00", "Synchronisation momentanément indisponible")
    assert "Financement France Travail" in html
    assert "Montant non communiqué" in html
    assert "Dernières données connues" in html
    assert "inclus dans le financement CPF" in html
    assert "0,00" not in html
    assert not card(None).strip()


@pytest.mark.parametrize("status", ["validated", "inProgress", "refused", None])
def test_trainee_page_renders_the_corresponding_badge_and_valid_javascript(monkeypatch, tmp_path, status):
    import app
    import re
    import subprocess

    trainee = {"id": "T-TEST", "first_name": "Camille", "last_name": "TEST",
               "cpf_amount": 4200, "training_price": 4200, "documents": []}
    local_session = {"id": "S-TEST", "name": "A3P test", "training_type": "A3P",
                     "date_start": "2027-01-19", "date_end": "2027-03-16", "trainees": [trainee]}
    snapshot = extract_folder(folder([solicitation(status=status)] if status else []))
    data = {"sessions": [local_session], "wedof_links": [{
        "active": True, "session_id": "S-TEST", "trainee_id": "T-TEST",
        "external_id": "CPF-TEST", "cpf_snapshot": snapshot,
    }]}
    monkeypatch.setattr(app, "load_data", Mock(return_value=data))
    monkeypatch.setattr(app, "save_data", Mock())
    monkeypatch.setattr(app, "_load_wedof_webhooks", Mock(return_value=[]))
    monkeypatch.setattr(app, "_build_trainee_automation_status", Mock(return_value=None))
    client = app.app.test_client()
    with client.session_transaction() as session:
        session["admin_logged_in"] = True
    response = client.get("/admin/sessions/S-TEST/stagiaires/T-TEST")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    if status:
        assert france_travail_view(snapshot)["label"] in html
        assert f'data-france-travail-status="{status}"' in html
    else:
        assert 'data-france-travail-status="' not in html
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.S)
    # Parse all inline JavaScript after Jinja rendering (no network, no execution).
    import json
    check = tmp_path / "parse.cjs"
    check.write_text("const scripts = " + json.dumps(scripts) + "; scripts.forEach(s => new Function(s));")
    subprocess.run(["node", str(check)], check=True, capture_output=True, text=True)
