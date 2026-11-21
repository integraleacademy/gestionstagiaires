"""Additional SEPA installments on an already-programmed Qonto invoice.

The existing installment is not moved, canceled, nor re-created. Qonto calls
are mocked: these regression tests never contact a real bank account.
"""

import copy
import datetime

import pytest

import app as gestion
from test_billing_direct_debit_scheduling import scheduling, stored_line


AVAILABILITY = "/api/billing/direct-debit/additional/availability"
PREVIEW = "/api/billing/direct-debit/additional/preview"
SCHEDULE = "/api/billing/direct-debit/additional/schedule"


@pytest.fixture
def additional(scheduling, monkeypatch):
    """A 950 € invoice with a first 475 € installment already in Qonto."""
    monkeypatch.setattr(
        gestion, "list_qonto_direct_debit_collections", lambda **_kwargs: {"items": []}
    )
    monkeypatch.setattr(
        gestion, "_read_debit_statement_dates", lambda *_args, **_kwargs: None
    )
    original = scheduling.client.post(
        "/api/billing/direct-debit/preview",
        json={
            "lineId": scheduling.line_id,
            "debitAmount": "475.00",
            "schedule": [
                {"date": scheduling.schedule[0]["date"], "amount": "475.00"},
            ],
        },
    )
    assert original.status_code == 200, original.json
    programmed = scheduling.client.post(
        "/api/billing/direct-debit/schedule",
        json={"selectionToken": original.json["selectionToken"]},
    )
    assert programmed.status_code == 200, programmed.json
    assert len(scheduling.subscriptions) == 1
    return scheduling


def availability(case):
    return case.client.get(AVAILABILITY, query_string={"lineId": case.line_id})


def preview(case, *, amount="475.00", due=None):
    return case.client.post(
        PREVIEW,
        json={
            "lineId": case.line_id,
            "amount": amount,
            "date": due or case.schedule[1]["date"],
        },
    )


def confirm(case, selection):
    return case.client.post(
        SCHEDULE, json={"selectionToken": selection["selectionToken"]}
    )


def test_availability_subtracts_existing_qonto_installments(additional):
    result = availability(additional)
    assert result.status_code == 200, result.json
    assert result.json["remainingCents"] == 95000
    assert result.json["scheduledCents"] == 47500
    assert result.json["availableCents"] == 47500
    assert additional.schedule[0]["date"] in result.json["occupiedDates"]
    assert len(additional.subscriptions) == 1
    assert additional.create.call_count == 1


def test_confirm_appends_one_installment_and_preserves_original_subscription(additional):
    initial_line = copy.deepcopy(stored_line(additional))
    original_id = additional.subscriptions[0]["id"]

    checked = preview(additional)
    assert checked.status_code == 200, checked.json
    assert checked.json["summary"]["availableCents"] == 47500
    assert len(additional.subscriptions) == 1

    response = confirm(additional, checked.json)
    assert response.status_code == 200, response.json
    assert response.json["ok"] is True
    assert additional.create.call_count == 2
    assert len(additional.subscriptions) == 2
    assert additional.subscriptions[0]["id"] == original_id
    assert additional.subscriptions[1]["amount"]["value"] == "475.00"
    assert additional.subscriptions[1]["initial_collection_date"] == additional.schedule[1]["date"]
    assert additional.subscriptions[1]["direct_debit_mandate_id"] == additional.mandate["id"]
    assert additional.subscriptions[1]["notify_client"] is True

    after = stored_line(additional)
    before_rows = initial_line["directDebitInstallments"]
    after_rows = after["directDebitInstallments"]
    assert len(before_rows) == 1
    assert len(after_rows) == 2
    assert after_rows[0]["qonto_direct_debit_subscription_id"] == original_id
    assert after_rows[0]["date"] == before_rows[0]["date"]
    assert after_rows[0]["amount"] == before_rows[0]["amount"]
    assert after_rows[1]["qonto_direct_debit_subscription_id"] == additional.subscriptions[1]["id"]
    assert after_rows[1]["additional_manual_debit"] is True
    assert len(after["initialDebitSchedule"]) == 1  # Contractual original stays as-is.
    assert len(after["paymentPlan"]["schedule"]) == 2
    assert after["paymentPlan"]["qontoAdditionalDebitOperation"]["state"] == "completed"

    replay = confirm(additional, checked.json)
    assert replay.status_code == 409, replay.json
    assert additional.create.call_count == 2


def test_rejects_excess_amount_duplicate_date_and_repeated_coverage(additional):
    before = additional.create.call_count
    assert preview(additional, amount="475.01").status_code == 409
    assert preview(additional, amount="0").status_code == 409
    assert preview(additional, due=additional.schedule[0]["date"]).status_code == 409
    assert additional.create.call_count == before

    checked = preview(additional)
    assert checked.status_code == 200, checked.json
    assert confirm(additional, checked.json).status_code == 200
    filled = availability(additional)
    assert filled.status_code == 409
    assert additional.create.call_count == before + 1


def test_stale_bank_schedule_is_rejected_without_creating_a_subscription(additional):
    checked = preview(additional)
    assert checked.status_code == 200, checked.json
    before_count = additional.create.call_count
    # A second bank-side commitment appears after preview but before confirmation.
    additional.subscriptions.append({
        **copy.deepcopy(additional.subscriptions[0]),
        "id": "other-qonto-subscription",
        "initial_collection_date": additional.schedule[1]["date"],
        "reference": f"{additional.line_id} - échéance extérieure",
    })
    rejected = confirm(additional, checked.json)
    assert rejected.status_code == 409, rejected.json
    assert rejected.json["ok"] is False
    assert additional.create.call_count == before_count


@pytest.mark.parametrize("role", ["viewer", "partner"])
def test_restricted_roles_cannot_program_an_additional_installment(additional, monkeypatch, role):
    if role == "partner":
        monkeypatch.setattr(gestion, "_is_partner_data_scope_session", lambda: True)
    else:
        with additional.client.session_transaction() as auth:
            auth["admin_role"] = role
    assert availability(additional).status_code == 403
    assert preview(additional).status_code == 403
    assert additional.client.post(SCHEDULE, json={"selectionToken": "anything"}).status_code == 403
    assert additional.create.call_count == 1



def _mark_financial_tracking_manually_reviewed(case, source="admin_reviewed_schedule"):
    data = gestion.load_data()
    line = gestion._find_billing_line(data, case.line_id)
    line["financial_tracking_override"] = {
        "enabled": True,
        "source": source,
        "updated_at": "2026-11-21T16:00:00Z",
        "fingerprint": "manually-reviewed-schedule",
    }
    gestion._save_billing_line(data, line)
    gestion.save_data(data)


@pytest.mark.parametrize("source", [
    "admin_reviewed_schedule",
    "inline_schedule",
    "qonto_attachment",
])
def test_manually_reviewed_tracking_can_explicitly_append_verified_qonto_debit(additional, source):
    """Previously the availability call failed before consulting Qonto.

    Keep manually-reviewed tracking enabled so the background job never
    recreates any bank subscriptions from local installments.
    """
    _mark_financial_tracking_manually_reviewed(additional, source)
    previous = stored_line(additional)["directDebitInstallments"][0]
    original_sid = previous["qonto_direct_debit_subscription_id"]
    assert additional.create.call_count == 1

    bank_checked = availability(additional)
    assert bank_checked.status_code == 200, bank_checked.json
    assert bank_checked.json["availableCents"] == 47500
    assert bank_checked.json["scheduledCents"] == 47500

    selection = preview(additional)
    assert selection.status_code == 200, selection.json
    result = confirm(additional, selection.json)
    assert result.status_code == 200, result.json
    assert additional.create.call_count == 2

    after = stored_line(additional)
    assert after["financial_tracking_override"]["enabled"] is True
    assert after["financial_tracking_override"]["source"] == source
    assert len(after["directDebitInstallments"]) == 2
    assert after["directDebitInstallments"][0]["qonto_direct_debit_subscription_id"] == original_sid
    assert after["directDebitInstallments"][0]["date"] == previous["date"]
    assert after["directDebitInstallments"][0]["amount"] == previous["amount"]
    assert after["directDebitInstallments"][1]["qonto_direct_debit_subscription_id"] != original_sid

    # A manually corrected schedule must not trigger an unrequested
    # automatic bank POST when the periodic synchronization runs.
    auto = gestion.ensure_qonto_sepa_installments_for_line(after)
    assert auto["skipped"] is True
    assert auto["manual_tracking"] is True
    assert additional.create.call_count == 2


def test_unknown_manual_override_origin_remains_blocked(additional):
    _mark_financial_tracking_manually_reviewed(additional, "unrecognized_admin_override")
    result = availability(additional)
    assert result.status_code == 409, result.json
    assert "rapproché" in result.json["error"]
    assert additional.create.call_count == 1


def test_manual_tracking_requires_existing_bank_confirmed_debit(additional):
    _mark_financial_tracking_manually_reviewed(additional)
    additional.subscriptions.clear()
    result = availability(additional)
    assert result.status_code == 409, result.json
    assert "aucun prélèvement actif" in result.json["error"]
    assert additional.create.call_count == 1


def test_manually_reviewed_schedule_edit_invalidates_prior_confirmation(additional):
    _mark_financial_tracking_manually_reviewed(additional)
    selected = preview(additional)
    assert selected.status_code == 200, selected.json

    data = gestion.load_data()
    line = gestion._find_billing_line(data, additional.line_id)
    line["financial_tracking_override"]["updated_at"] = "2026-11-21T16:01:00Z"
    gestion._save_billing_line(data, line)
    gestion.save_data(data)

    result = confirm(additional, selected.json)
    assert result.status_code == 409, result.json
    assert result.json["ok"] is False
    assert additional.create.call_count == 1
