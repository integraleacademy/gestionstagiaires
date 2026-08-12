import datetime as dt

from cpf_tracking import (CPF_STEPS, automation_view, build_cpf_view, build_steps,
                          format_euro, format_paris_datetime, has_cpf_financing,
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
    empty = automation_view("D1", [], [])
    assert all(a["status"] == "Non programmée" for a in empty["actions"])
    executed = automation_view("D1", [{"external_id": "D1", "entry_training": {"status": "executed", "executed_at": "2026-10-10T18:05:00+02:00"}}], [])
    assert executed["actions"][0]["status"] == "Exécutée"


def test_french_money_and_paris_datetime_formats():
    assert format_euro("4200") == "4\u202f200,00 €"
    assert format_paris_datetime("2026-08-11T12:45:00Z") == "11/08/2026 à 14h45"


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
