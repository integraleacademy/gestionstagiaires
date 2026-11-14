"""Deterministic interleavings for the lost Qonto invoice regression."""

from copy import deepcopy
import json

import pytest

from billing_persistence import (
    BillingPersistenceConflict, merge_billing_state, mark_saved, track_payload,
)


def line(**values):
    return {"id": "bill-personal", "amount": 2486, "invoiceStatus": "not_invoiced",
            "qontoInvoiceId": None, "paymentMode": "cash", "paymentPlan": {},
            "directDebitInstallments": [], "generationInProgress": True, **values}


def document(row=None):
    return {"sessions": [{"id": "session", "comment": "before"}],
            "billing_lines": [row or line()]}


def completed_invoice():
    return line(
        qontoInvoiceId="invoice-486", qontoDraftId="invoice-486",
        qontoInvoiceNumber="FL-2026-486", invoiceStatus="finalized",
        invoiceGeneratedAt="2026-11-12T15:41:21Z", generationInProgress=False,
        paymentMode="sepa_direct_debit", paymentPlan={"installments": 3},
        directDebitInstallments=[{"date": "2026-11-20", "amount": 828.66,
                                  "qonto_direct_debit_subscription_id": "subscription-1"}],
        logs=[{"at": "2026-11-12T15:41:27Z", "action": "Facture finalisée"}],
    )


def test_unrelated_stale_save_preserves_completed_invoice_and_plan():
    stale = track_payload(document())
    stale["sessions"][0]["comment"] = "edited administrator comment"
    canonical = document(completed_invoice())
    merge_billing_state(stale, canonical)
    assert stale["billing_lines"] == canonical["billing_lines"]
    assert stale["sessions"][0]["comment"] == "edited administrator comment"


def test_two_concurrent_collection_returns_survive_a_mandate_replacement():
    stale = track_payload(document(line(qonto_direct_debit_mandate_id="old")))
    stale["billing_lines"][0]["qontoReturnedCollections"] = {"a": {"id": "a", "status": "returned"}}
    current = document(line(qonto_direct_debit_mandate_id="new",
                            qontoReturnedCollections={"b": {"id": "b", "status": "returned"}}))
    merge_billing_state(stale, current)
    assert stale["billing_lines"][0]["qonto_direct_debit_mandate_id"] == "new"
    assert set(stale["billing_lines"][0]["qontoReturnedCollections"]) == {"a", "b"}


def test_stale_mandate_attachment_keeps_invoice_and_all_bank_ids():
    stale = track_payload(document())
    stale["billing_lines"][0].update(
        qonto_direct_debit_mandate_id="mandate-1", qonto_mandate_status="active",
        mandateStatus="active", qonto_mandate_rum="RUM-TEST",
        updatedAt="2026-11-12T15:43:43Z",
        logs=[{"at": "2026-11-12T15:43:42Z", "action": "Mandat retrouvé"}],
    )
    canonical = document(completed_invoice())
    merge_billing_state(stale, canonical)
    saved = stale["billing_lines"][0]
    assert saved["qontoInvoiceNumber"] == "FL-2026-486"
    assert saved["invoiceStatus"] == "finalized"
    assert saved["generationInProgress"] is False
    assert saved["directDebitInstallments"] == canonical["billing_lines"][0]["directDebitInstallments"]
    assert saved["paymentMode"] == "sepa_direct_debit"
    assert saved["qonto_direct_debit_mandate_id"] == "mandate-1"
    assert saved["mandateStatus"] == "active"
    assert [event["action"] for event in saved["logs"]] == ["Facture finalisée", "Mandat retrouvé"]


def test_generated_empty_defaults_do_not_overwrite_a_concurrent_new_line():
    stale = track_payload({"billing_lines": []})
    stale["billing_lines"] = [line(generationInProgress=False, paymentStatus="not_applicable",
        qonto_direct_debit_mandate_id="mandate-1", mandateStatus="active")]
    merge_billing_state(stale, document(completed_invoice()))
    saved = stale["billing_lines"][0]
    assert saved["qontoInvoiceId"] == "invoice-486"
    assert saved["mandateStatus"] == "active"
    assert saved["paymentMode"] == "sepa_direct_debit"


def test_explicit_reset_is_applied_when_invoice_identity_has_not_changed():
    base = document(completed_invoice())
    reset = track_payload(deepcopy(base))
    reset["billing_lines"][0].update(qontoInvoiceId="", qontoDraftId="",
        qontoInvoiceNumber="", invoiceStatus="not_invoiced", paymentMode="cash",
        paymentPlan={}, directDebitInstallments=[])
    merge_billing_state(reset, base)
    saved = reset["billing_lines"][0]
    assert saved["qontoInvoiceId"] == ""
    assert saved["invoiceStatus"] == "not_invoiced"
    assert saved["directDebitInstallments"] == []


def test_old_invoice_refresh_cannot_resurrect_reset_or_payments():
    stale = track_payload(document(completed_invoice()))
    stale["billing_lines"][0].update(invoiceStatus="paid", qonto_amount_paid_cents=248600,
                                     qonto_total_amount_cents=248600, paymentStatus="paid")
    canonical = document(line(generationInProgress=False, qontoDraftId="",
        qontoInvoiceNumber="", qonto_amount_paid_cents=0, paymentStatus="not_applicable"))
    merge_billing_state(stale, canonical)
    saved = stale["billing_lines"][0]
    assert not saved["qontoInvoiceId"]
    assert saved["invoiceStatus"] == "not_invoiced"
    assert saved["qonto_amount_paid_cents"] == 0
    assert saved["paymentStatus"] == "not_applicable"
    assert saved["directDebitInstallments"] == []


def test_old_remote_schedule_discovered_after_reset_stays_discarded():
    stale = track_payload(document(completed_invoice()))
    stale["billing_lines"][0]["directDebitInstallments"].append({
        "qonto_direct_debit_subscription_id": "historical-subscription-2",
        "amount": 828.66, "date": "2026-12-20",
    })
    canonical = document(line(generationInProgress=False))
    merge_billing_state(stale, canonical)
    assert not stale["billing_lines"][0]["qontoInvoiceId"]
    assert stale["billing_lines"][0]["directDebitInstallments"] == []


@pytest.mark.parametrize("field,resource", [
    ("qontoInvoiceId", "invoice"), ("qonto_direct_debit_mandate_id", "mandate"),
    ("qonto_direct_debit_subscription_id", "schedule"),
])
def test_divergent_new_provider_id_is_an_explicit_conflict(field, resource):
    stale = track_payload(document())
    stale["billing_lines"][0][field] = "created-in-request-A"
    canonical = document(line(**{field: "created-in-request-B"}))
    before = deepcopy(stale)
    with pytest.raises(BillingPersistenceConflict) as error:
        merge_billing_state(stale, canonical)
    assert error.value.resource == resource
    assert stale == before  # No partial merge is exposed on failure.


def test_canonical_new_rows_survive_and_new_incoming_rows_are_added():
    stale = track_payload(document())
    stale["billing_lines"].append({"id": "incoming-new", "amount": 10})
    canonical = document()
    canonical["billing_lines"].append({"id": "canonical-new", "qontoInvoiceId": "invoice-new"})
    merge_billing_state(stale, canonical)
    assert {row["id"] for row in stale["billing_lines"]} == {
        "bill-personal", "incoming-new", "canonical-new",
    }


def test_explicit_deletion_works_but_old_snapshot_cannot_resurrect_it():
    base = document()
    deletion = track_payload(deepcopy(base))
    deletion["billing_lines"] = []
    merge_billing_state(deletion, base)
    assert deletion["billing_lines"] == []
    stale = track_payload(deepcopy(base))
    stale["billing_lines"][0]["invoiceNotes"] = "an old in-flight edit"
    merge_billing_state(stale, deletion)
    assert stale["billing_lines"] == []


def test_deletion_from_old_snapshot_does_not_remove_a_new_invoice():
    stale = track_payload(document())
    stale["billing_lines"] = []
    canonical = document(completed_invoice())
    merge_billing_state(stale, canonical)
    assert stale["billing_lines"] == canonical["billing_lines"]


def test_missing_collection_is_not_an_explicit_deletion():
    stale = track_payload(document())
    del stale["billing_lines"]
    canonical = document(completed_invoice())
    merge_billing_state(stale, canonical)
    assert stale["billing_lines"] == canonical["billing_lines"]


def test_non_identity_conflicts_do_not_block_an_unrelated_admin_save():
    stale = track_payload(document(completed_invoice()))
    stale["sessions"][0]["comment"] = "keep this edit"
    stale["billing_lines"][0].update(invoiceStatus="sent", invoiceNotes="request A")
    canonical = document(completed_invoice())
    canonical["billing_lines"][0].update(invoiceStatus="paid", invoiceNotes="request B")
    merge_billing_state(stale, canonical)
    assert stale["sessions"][0]["comment"] == "keep this edit"
    assert stale["billing_lines"][0]["invoiceStatus"] == "paid"
    assert stale["billing_lines"][0]["invoiceNotes"] == "request B"


def test_successful_save_rebases_same_object_for_later_reset():
    payload = track_payload(document())
    canonical = document(completed_invoice())
    merge_billing_state(payload, canonical)
    mark_saved(payload)
    payload["billing_lines"][0].update(qontoInvoiceId="", qontoDraftId="",
                                      qontoInvoiceNumber="", invoiceStatus="not_invoiced")
    merge_billing_state(payload, canonical)
    assert payload["billing_lines"][0]["qontoInvoiceId"] == ""


def test_deepcopy_preserves_independent_baseline_and_json_has_no_metadata():
    tracked = track_payload(document())
    copied = deepcopy(tracked)
    assert track_payload(copied) is copied  # Tracking must not silently rebase.
    tracked["billing_lines"][0]["qontoInvoiceId"] = "local-mutation"
    mark_saved(tracked)
    merge_billing_state(copied, document(completed_invoice()))
    assert copied["billing_lines"][0]["qontoInvoiceId"] == "invoice-486"
    serialized = json.loads(json.dumps(copied))
    assert set(serialized) == {"sessions", "billing_lines"}
    assert "_billing_baseline" not in json.dumps(copied)


def test_plain_atomic_or_initialization_payload_is_not_changed():
    plain = document(line(qontoInvoiceId="intentional-atomic-reset"))
    before = deepcopy(plain)
    assert merge_billing_state(plain, document(completed_invoice())) is plain
    mark_saved(plain)
    assert plain == before


def test_nullable_old_poll_timestamp_is_safe():
    tracked = track_payload(document(line(qontoAutoSyncAttemptedAt=None)))
    canonical = document(line(qontoAutoSyncAttemptedAt=None))
    tracked["billing_lines"][0]["qontoAutoSyncAttemptedAt"] = "2026-11-13T08:00:00Z"
    merge_billing_state(tracked, canonical)
    assert tracked["billing_lines"][0]["qontoAutoSyncAttemptedAt"] == "2026-11-13T08:00:00Z"
