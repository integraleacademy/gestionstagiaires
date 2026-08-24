import datetime as dt
import inspect
from unittest.mock import Mock

import app as application
from cpf_tracking import (CPF_STEPS, automation_view, build_cpf_view, build_steps,
                          format_euro, format_paris_date, format_paris_datetime, has_cpf_financing,
                          map_wedof_status, waiting_reason)


def test_block_is_absent_without_cpf_and_present_with_cpf_or_mixed_funding():
    data = {"wedof_links": []}
    session = {"id": "S1"}
    assert build_cpf_view({"id": "T1", "personal_amount": 100}, session, data) is None
    assert build_cpf_view({"id": "T1", "cpf_amount": "1"}, session, data) is not None
    mixed = {"id": "T1", "financings": [{"type": "CPF + France Travail"}]}
    assert has_cpf_financing(mixed)
    assert build_cpf_view(mixed, session, data) is not None


def test_the_six_wedof_steps_are_mapped_centrally():
    states = ["pending", "accepted", "inTraining", "serviceDoneDeclared", "serviceDoneValidated", "invoiced"]
    assert len(CPF_STEPS) == 6
    assert [map_wedof_status(state) for state in states] == list(range(6))
    for index, state in enumerate(states):
        view = build_steps({"state": state})
        assert len(view["steps"]) == 6
        assert view["steps"][index]["state"] == "current"


def test_wedof_invoice_advances_a_validated_service_to_invoiced():
    for invoice_data in (
        {"invoice_status": "unpaid"},
        {"qonto_invoice_number": "FL-2026-367"},
        {"billing_state": "billed"},
        {"billingState": "billed"},
        {"invoice_status": "paid", "invoice_paid_at": "2026-08-13T16:00:00Z"},
    ):
        view = build_steps({"state": "serviceDoneValidated", **invoice_data})
        assert view["current_index"] == 5
        assert view["steps"][4]["state"] == "done"
        assert view["steps"][5]["state"] == "current"


def test_draft_or_cancelled_invoice_does_not_mark_the_cpf_folder_as_invoiced():
    for invoice_status in ("draft", "cancelled", "error"):
        view = build_steps({
            "state": "serviceDoneValidated",
            "invoice_status": invoice_status,
            "qonto_invoice_id": "inv-draft",
        })
        assert view["current_index"] == 4
        assert view["steps"][4]["state"] == "current"
        assert view["steps"][5]["state"] == "future"


def test_persisted_cpf_invoice_also_advances_the_tracking_step():
    trainee = {"id": "T1", "cpf_amount": 980}
    session = {"id": "S1"}
    data = {
        "wedof_links": [{
            "active": True,
            "session_id": "S1",
            "trainee_id": "T1",
            "external_id": "401604887065",
            "wedof_state": "serviceDoneValidated",
            "cpf_snapshot": {"state": "serviceDoneValidated"},
        }],
        "billing_lines": [{
            "traineeId": "T1",
            "sessionId": "S1",
            "financingType": "CPF",
            "invoiceStatus": "sent",
            "qontoInvoiceNumber": "FL-2026-367",
        }],
    }

    view = build_cpf_view(trainee, session, data)

    assert view["snapshot"]["state"] == "serviceDoneValidated"
    assert view["current_index"] == 5
    assert view["steps"][5]["state"] == "current"


def test_cpf_billing_placeholder_without_invoice_reference_is_not_invoiced():
    trainee = {"id": "T1", "cpf_amount": 980}
    session = {"id": "S1"}
    data = {
        "wedof_links": [{
            "active": True,
            "session_id": "S1",
            "trainee_id": "T1",
            "external_id": "401604887065",
            "cpf_snapshot": {"state": "serviceDoneValidated"},
        }],
        "billing_lines": [{
            "traineeId": "T1",
            "sessionId": "S1",
            "financingType": "CPF",
            "paymentStatus": "unpaid",
        }],
    }

    view = build_cpf_view(trainee, session, data)

    assert view["current_index"] == 4
    assert view["steps"][5]["state"] == "future"


def test_waiting_reasons_only_use_explicit_remote_value():
    assert waiting_reason({"waiting_reason": "attendee"}) == "En attente de validation de la part du candidat"
    assert waiting_reason({"waiting_reason": "france_travail"}) == "Demande en cours d’instruction par France Travail"
    assert waiting_reason({}) == "Type d’attente non communiqué"


def test_unknown_refused_cancelled_or_abandoned_are_never_classified():
    for state in ("brandNewState", "refused", "cancelled", "abandoned"):
        assert map_wedof_status(state) is None
        view = build_steps({"state": state})
        assert view["unknown"] is True
        assert all(step["state"] == "future" for step in view["steps"])


def test_real_automation_states_are_not_inferred_from_theoretical_dates():
    statuses = [{"external_id": "D1", "entry_training": {"status": "planned", "planned_at": "2026-09-08T08:00:00+02:00"},
                 "service_done": {"status": "failed", "last_error_code": "remote_error", "next_attempt_at": "2026-08-11T15:00:00Z"}}]
    view = automation_view("D1", statuses, [])
    assert [a["status"] for a in view["actions"]] == ["Programmée", "Échec"]
    assert view["actions"][1]["error"] == "remote_error"
    empty = automation_view("D1", [], [], {"state": "accepted"})
    assert [a["status"] for a in empty["actions"]] == ["À calculer", "À venir"]
    assert "prochain contrôle WEDOF" in empty["actions"][0]["detail"]
    assert "passera « En formation »" in empty["actions"][1]["detail"]
    executed = automation_view("D1", [{"external_id": "D1", "entry_training": {"status": "executed", "executed_at": "2026-10-10T18:05:00+02:00"}}], [])
    assert executed["actions"][0]["status"] == "Exécutée"


def test_waiting_service_done_has_an_explicit_target_without_false_alert():
    statuses = [{
        "external_id": "D1", "wedof_state": "accepted",
        "entry_training": {"status": "planned", "planned_at": "2026-09-07T18:00:00+02:00"},
        "service_done": {"status": "waiting_for_in_training", "planned_at": "2026-10-09T23:00:00+02:00"},
    }]
    view = automation_view("D1", statuses, [])
    assert [action["status"] for action in view["actions"]] == ["Programmée", "À venir"]
    assert "07/09/2026 à 18h00" in view["actions"][0]["detail"]
    assert "09/10/2026 à 23h00" in view["actions"][1]["detail"]


def test_french_money_and_paris_datetime_formats():
    assert format_euro("4200") == "4\u202f200,00 €"
    assert format_paris_datetime("2026-08-11T12:45:00Z") == "11/08/2026 à 14h45"
    assert format_paris_date("2026-08-11T22:45:00Z") == "12/08/2026"


def test_reached_cpf_steps_show_wedof_dates_without_time():
    view = build_steps({
        "state": "inTraining",
        "created_at": "2026-08-03T08:12:00Z",
        "start_date": "2026-09-08",
        "step_dates": {
            "accepted": {"changedAt": "2026-08-13T14:42:32+02:00"},
        },
    })
    assert [step["date"] for step in view["steps"]] == [
        "03/08/2026", "13/08/2026", "08/09/2026", "", "", "",
    ]


def test_pending_step_uses_folder_creation_date_and_current_step_is_dated():
    view = build_steps({
        "state": "pending",
        "created_at": "2026-08-13T12:42:32Z",
    })
    assert view["steps"][0] == {
        "label": "En attente d’acceptation",
        "state": "current",
        "date": "13/08/2026",
    }


def test_accepted_folder_uses_remote_creation_and_update_dates_without_history():
    view = build_steps({
        "state": "accepted",
        "created_at": "2026-08-10T09:00:00Z",
        "updated_at": "2026-08-13T14:42:32+02:00",
    })
    assert [step["date"] for step in view["steps"][:2]] == ["10/08/2026", "13/08/2026"]


def test_status_history_list_dates_are_supported():
    view = build_steps({
        "state": "accepted",
        "step_dates": [
            {"status": "pending", "date": "2026-08-01T09:00:00Z"},
            {"state": "accepted", "at": "2026-08-04T17:30:00Z"},
        ],
    })
    assert [step["date"] for step in view["steps"][:2]] == ["01/08/2026", "04/08/2026"]


def test_template_keeps_automation_and_places_cpf_before_elearning():
    source = open("templates/admin_trainee.html", encoding="utf-8").read()
    assert "id=\"automationHub\"" in source
    assert source.index("id=\"cpfTracking\"") > source.index("id=\"automationHub\"")
    assert source.index("id=\"cpfTracking\"") < source.index("Identifiants e-learning APS")
    assert "{% if cpf_tracking %}" in source
    assert '<details class="cpf-panel" id="cpfTracking">' in source
    assert '<summary class="cpf-panel__summary"' in source
    assert "cpf-panel__current-label" in source
    assert '<details class="cpf-panel" id="cpfTracking" open' not in source
    assert "data-cpf-auto-match" in source
    assert "admin_trainee_cpf_auto_match" in source
    assert "admin_trainee_cpf_associate_match" in source
    assert "js/cpf-auto-match.js" in source
    assert "L’ouverture de la fiche ne contacte pas WEDOF." in source
    assert "Rechercher dans le cache" in source
    assert "{{ action.detail }}" in source
    assert "Automatisation attendue mais non programmée" not in source


def test_successful_cpf_association_reloads_the_current_trainee_page():
    source = open("static/js/cpf-auto-match.js", encoding="utf-8").read()
    assert "function refreshAfterAssociation" in source
    assert "window.history.replaceState(null, '', target.href)" in source
    assert "window.location.reload()" in source
    assert source.count("refreshAfterAssociation(payload.redirect_url)") == 2
    assert "window.location.assign(payload.redirect_url)" not in source


def test_cpf_matching_waits_for_an_explicit_click_when_the_page_opens():
    source = open("static/js/cpf-auto-match.js", encoding="utf-8").read()
    assert "function initCpfAutoMatch()" in source
    assert "document.addEventListener('DOMContentLoaded', initCpfAutoMatch, {once: true})" in source
    assert "root.dataset.cpfAutoMatchInitialized = 'true'" in source
    assert "\n  search();\n" not in source
    assert "retry.addEventListener('click', search)" in source


def test_opening_a_trainee_page_never_refreshes_wedof_implicitly():
    source = inspect.getsource(application.admin_trainee_page)
    assert "_refresh_cpf_link_from_wedof" not in source
    assert "strictement locale" in source


def test_refresh_cpf_link_updates_status_snapshot_and_automation(monkeypatch):
    remote_folder = {
        "externalId": "CPF-42",
        "type": "CPF",
        "state": "serviceDoneDeclared",
        "billingState": "billed",
        "invoiceNumber": "FL-2026-374",
        "trainingActionInfo": {"sessionStartDate": "2026-07-13", "sessionEndDate": "2026-08-12"},
    }
    client = Mock()
    client.get_registration_folder_interactive.return_value = remote_folder
    automation_sync = Mock()
    monkeypatch.setattr(application, "WedofClient", lambda: client)
    monkeypatch.setattr(application, "sync_folder_automation_status", automation_sync)
    monkeypatch.setattr(application, "_now_iso", lambda: "2026-08-13T10:00:00+00:00")
    data = {"wedof_automation_status": []}
    link = {
        "external_id": "CPF-42",
        "wedof_state": "inTraining",
        "cpf_snapshot": {"state": "inTraining"},
        "cpf_sync_error": "ancienne erreur",
    }

    application._refresh_cpf_link_from_wedof(data, link)

    client.get_registration_folder_interactive.assert_called_once_with("CPF-42")
    assert link["wedof_state"] == "serviceDoneDeclared"
    assert link["cpf_snapshot"]["state"] == "serviceDoneDeclared"
    assert link["cpf_snapshot"]["billing_state"] == "billed"
    assert link["cpf_snapshot"]["invoice_number"] == "FL-2026-374"
    assert link["cpf_snapshot"]["qonto_invoice_number"] == "FL-2026-374"
    assert link["cpf_snapshot"]["synced_at"] == "2026-08-13T10:00:00+00:00"
    assert link["last_seen_at"] == "2026-08-13T10:00:00+00:00"
    assert "cpf_sync_error" not in link
    automation_sync.assert_called_once_with(data, remote_folder)
