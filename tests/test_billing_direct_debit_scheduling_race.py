"""A local business change during Qonto preflight must stop the actual POST."""

import pytest

import app as gestion
from test_billing_direct_debit_scheduling import (
    scheduling,
    confirmed_preview,
    confirm,
    stored_line,
)


@pytest.mark.parametrize("field,value", [
    ("personal_amount", 960),
    ("registration_cancelled", True),
])
def test_business_change_in_last_remote_listing_prevents_subscription_creation(
    scheduling, field, value,
):
    selection = confirmed_preview(scheduling)
    original_listing = scheduling.list_subscriptions.side_effect
    changed = False

    def list_then_change_business_state(*args, **kwargs):
        nonlocal changed
        result = original_listing(*args, **kwargs)
        operation = (stored_line(scheduling).get("paymentPlan") or {}).get("qontoSchedulingOperation")
        if operation and not changed:
            # The reservation and the per-slot local check already passed.
            # Simulate another admin saving while the final bank GET is in flight.
            changed = True

            def update(current):
                current["sessions"][0]["trainees"][0][field] = value
                return {"ok": True}

            gestion._atomic_update_data(update)
        return result

    scheduling.list_subscriptions.side_effect = list_then_change_business_state
    response = confirm(scheduling, selection)

    assert changed, "The business change must occur after the operation is reserved"
    assert response.status_code == 409, response.json
    assert response.json["ok"] is False
    scheduling.create.assert_not_called()
    assert not scheduling.subscriptions
    line = stored_line(scheduling)
    assert line["paymentPlan"]["qontoSchedulingOperation"]["state"] == "failed"
    assert all(not row.get("qonto_direct_debit_subscription_id")
               for row in line["directDebitInstallments"])
