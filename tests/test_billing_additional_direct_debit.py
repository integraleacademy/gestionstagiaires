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
    assert filled.status_code == 200, filled.json
    assert filled.json["ok"] is True
    assert filled.json["covered"] is True
    assert filled.json["canSchedule"] is False
    assert filled.json["scheduledCents"] == 95000
    assert filled.json["availableCents"] == 0
    assert len(filled.json["commitments"]) == 2
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



def test_recurring_qonto_debit_is_not_just_the_next_month_in_the_table(additional):
    """One Qonto subscription may have two 475 € occurrences remaining.

    The table shows one upcoming date, but the financial cover totals 950 €,
    not 475 €. Never create a third debit for the same invoice.
    """
    sub = additional.subscriptions[0]
    sub["schedule_type"] = "monthly"
    sub["schedule_total_collection_count"] = 2
    sub["schedule_next_collection_date"] = sub["initial_collection_date"]
    sub["schedule_end_date"] = gestion._add_months(
        datetime.date.fromisoformat(additional.schedule[0]["date"]), 1
    ).isoformat()
    old_calls = additional.create.call_count
    overview = additional.client.get(
        f"/api/billing/trainee/T-SCHEDULING/session/S-SCHEDULING/bank-schedule"
    )
    assert overview.status_code == 200, overview.json
    assert len(overview.json["upcoming"]) == 1
    assert overview.json["upcoming"][0]["amount_cents"] == 47500
    assert overview.json["upcoming"][0]["remaining_count"] == 2
    assert overview.json["upcoming"][0]["remaining_cents"] == 95000

    availability_result = availability(additional)
    assert availability_result.status_code == 200, availability_result.json
    assert availability_result.json["ok"]
    assert availability_result.json["covered"] is True
    assert availability_result.json["canSchedule"] is False
    assert availability_result.json["remainingCents"] == 95000
    assert availability_result.json["scheduledCents"] == 95000
    assert availability_result.json["availableCents"] == 0
    commitments = availability_result.json["commitments"]
    assert len(commitments) == 1
    assert commitments[0]["frequency"] == "monthly"
    assert commitments[0]["remainingCount"] == 2
    assert commitments[0]["amountCents"] == 47500
    assert commitments[0]["remainingCents"] == 95000
    assert "no-store" in availability_result.headers["Cache-Control"]

    # Even if a user calls the preview endpoint directly (bypassing the UI),
    # server-side bank checks refuse a third subscription.
    refused = preview(additional)
    assert refused.status_code == 409
    assert "entièrement couvert" in refused.json["error"]
    assert additional.create.call_count == old_calls


def test_full_coverage_overview_does_not_mutate_local_financing(additional):
    before = stored_line(additional)
    extra = additional.record_subscription({
        **copy.deepcopy(additional.subscriptions[0]),
        "reference": f"{additional.line_id} - complément externe - échéance 1/1",
        "initial_collection_date": additional.schedule[1]["date"],
        "amount": {"value": "475.00", "currency": "EUR"},
    })
    assert extra["direct_debit_subscription"]["id"] != additional.subscriptions[0]["id"]
    outcome = availability(additional)
    assert outcome.status_code == 200, outcome.json
    assert outcome.json["covered"] is True
    assert len(outcome.json["commitments"]) == 2
    after = stored_line(additional)
    # Routine data loading can normalize unrelated billing metadata. What
    # matters is that this read-only endpoint never changes SEPA commitments.
    assert after["directDebitInstallments"] == before["directDebitInstallments"]
    assert after["paymentPlan"] == before["paymentPlan"]
    assert after["initialDebitSchedule"] == before["initialDebitSchedule"]
    assert after["qonto_direct_debit_subscription_id"] == before["qonto_direct_debit_subscription_id"]


@pytest.fixture
def returned_plan(scheduling, monkeypatch):
    """1,079 EUR, an archived SEPA return and one remaining monthly debit."""
    case = scheduling
    today = datetime.date.today()
    past = (today - datetime.timedelta(days=20)).isoformat()
    due = case.schedule[0]["date"]
    amount = {"value": "539.50", "currency": "EUR"}
    case.invoice.update(total_amount=dict(amount, value="1079.00"), amount_paid=amount, remaining_amount=amount)
    sub = case.record_subscription({
        "direct_debit_mandate_id": case.mandate["id"], "reference": case.invoice["number"],
        "initial_collection_date": past, "schedule_next_collection_date": due,
        "schedule_end_date": due, "schedule_type": "monthly", "amount": amount,
    })["direct_debit_subscription"]
    archived = {"qonto_direct_debit_subscription_id": "old-series", "qonto_direct_debit_collection_id": "old-debit",
                "status": "returned", "date": past, "amount": 539.5}
    data = gestion.load_data()
    data["sessions"][0]["trainees"][0]["personal_amount"] = 1079
    line = gestion._find_billing_line(data, case.line_id)
    line.update(amount=1079, amountTTC=1079, qontoRemoteAmountPaidCents=53950,
                qonto_total_amount_cents=107900, qonto_amount_paid_cents=0,
                paymentMode="sepa_direct_debit", qonto_direct_debit_subscription_id=sub["id"],
                directDebitInstallments=[{"qonto_direct_debit_subscription_id": sub["id"],
                                          "date": due, "amount": 539.5, "status": "scheduled"}],
                financial_tracking_override={"enabled": True, "source": "inline_schedule",
                                             "edit_history": [{"before": [archived], "after": [archived]}]})
    gestion._save_billing_line(data, line)
    gestion.save_data(data)
    case.collections = [{"id": "old-debit", "direct_debit_subscription_id": "old-series",
                         "collection_date": past, "status": "returned", "amount": amount}]

    def collections(subscription_id="", **_):
        return {"items": [row for row in case.collections
                          if not subscription_id or row["direct_debit_subscription_id"] == subscription_id]}

    monkeypatch.setattr(gestion, "list_qonto_direct_debit_collections", collections)
    monkeypatch.setattr(gestion, "_read_debit_statement_dates", lambda _: None)
    return case


def test_archived_return_reopens_exactly_one_installment_through_confirmation(returned_plan):
    case = returned_plan
    original = copy.deepcopy(case.subscriptions[0])
    overview = case.client.get("/api/billing/trainee/T-SCHEDULING/session/S-SCHEDULING?local=1")
    assert overview.json["financial_summary"]["remaining_total_cents"] == 107900
    result = availability(case)
    assert result.status_code == 200, result.json
    assert result.json["remainingCents"] == 107900
    assert result.json["scheduledCents"] == result.json["availableCents"] == 53950
    assert result.json["canSchedule"] and result.json["returnAdjustmentCents"] == 53950
    assert preview(case, amount="539.51").status_code == 409
    assert preview(case, amount="539.50", due=case.schedule[0]["date"]).status_code == 409
    checked = preview(case, amount="539.50")
    assert checked.status_code == 200, checked.json
    assert checked.json["summary"]["reviewReturnCents"] == 53950
    assert confirm(case, checked.json).status_code == 409
    case.create.assert_not_called()
    payload = {"selectionToken": checked.json["selectionToken"], "confirmedReturnCents": 53950}
    saved = case.client.post(SCHEDULE, json=payload)
    assert saved.status_code == 200, saved.json
    assert case.subscriptions[0] == original
    assert case.subscriptions[1]["amount"] == {"value": "539.50", "currency": "EUR"}
    assert case.subscriptions[1]["initial_collection_date"] == case.schedule[1]["date"]
    operation = stored_line(case)["paymentPlan"]["qontoAdditionalDebitOperation"]
    assert operation["confirmedReturnCents"] == 53950
    assert availability(case).json["availableCents"] == 0
    assert case.client.post(SCHEDULE, json=payload).status_code == 409
    case.create.assert_called_once()


@pytest.mark.parametrize("bank_status", [None, "declined", "failed", "completed"])
def test_unconfirmed_return_never_releases_invoice_credit(returned_plan, bank_status):
    case = returned_plan
    if bank_status is None:
        case.collections.clear()
    else:
        case.collections[0]["status"] = bank_status
    # An unrelated return under the old shared subscription does not belong here.
    case.collections.append({"id": "unrelated", "direct_debit_subscription_id": "old-series",
                             "collection_date": "2020-01-10", "status": "returned",
                             "amount": {"value": "539.50", "currency": "EUR"}})
    result = availability(case)
    assert result.status_code == 200, result.json
    assert result.json["availableCents"] == result.json["returnAdjustmentCents"] == 0
    assert preview(case, amount="539.50").status_code == 409
    case.create.assert_not_called()


def test_verified_transfer_is_retained_despite_a_return_for_the_same_amount(returned_plan):
    case = returned_plan
    data = gestion.load_data()
    line = gestion._find_billing_line(data, case.line_id)
    line["qontoBankTransfers"] = [{"id": "wire", "status": "completed", "amount_cents": 53950,
                                  "paid_at": "2020-01-10", "operation_type": "transfer",
                                  "currency": "EUR", "side": "credit"}]
    gestion._save_billing_line(data, line)
    gestion.save_data(data)
    result = availability(case)
    assert result.status_code == 200, result.json
    assert result.json["availableCents"] == result.json["returnAdjustmentCents"] == 0
    case.create.assert_not_called()


def test_other_invoice_credit_survives_duplicate_returns_and_final_bank_check(returned_plan, monkeypatch):
    case = returned_plan
    case.invoice.update(amount_paid={"value": "639.50", "currency": "EUR"},
                        remaining_amount={"value": "439.50", "currency": "EUR"})
    case.collections.append(dict(case.collections[0]))
    result = availability(case)
    assert result.status_code == 200, result.json
    assert result.json["remainingCents"] == 97900
    assert result.json["availableCents"] == 43950
    checked = preview(case, amount="439.50")
    assert checked.status_code == 200, checked.json
    ensure = gestion.ensure_sepa_subscription
    original_collections = list(case.collections)

    def bank_changes_before_create(*args):
        case.collections.clear()
        return ensure(*args)

    monkeypatch.setattr(gestion, "ensure_sepa_subscription", bank_changes_before_create)
    response = case.client.post(SCHEDULE, json={"selectionToken": checked.json["selectionToken"],
                                                "confirmedReturnCents": 53950})
    assert response.status_code == 409, response.json
    assert response.json["requiresVerification"] is False
    case.create.assert_not_called()
    monkeypatch.setattr(gestion, "ensure_sepa_subscription", ensure)
    case.collections.extend(original_collections)
    new_preview = preview(case, amount="439.50")
    assert new_preview.status_code == 200, new_preview.json
    retry = case.client.post(SCHEDULE, json={"selectionToken": new_preview.json["selectionToken"],
                                             "confirmedReturnCents": 53950})
    assert retry.status_code == 200, retry.json
    case.create.assert_called_once()


@pytest.mark.parametrize("status", ["returned", "refunded"])
def test_multiple_returns_cannot_release_more_than_gross_invoice_credit(returned_plan, status):
    case = returned_plan
    extra = dict(case.collections[0], id="another-return", status=status,
                 direct_debit_subscription_id=case.subscriptions[0]["id"])
    case.collections.append(extra)
    result = availability(case)
    assert result.status_code == 200, result.json
    assert result.json["remainingCents"] == 107900
    assert result.json["availableCents"] == 53950
    assert result.json["returnAdjustmentCents"] == 53950
    case.create.assert_not_called()
