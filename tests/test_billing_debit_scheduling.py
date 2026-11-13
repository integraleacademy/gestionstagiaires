"""Exact calendar validation and process-safe explicit scheduling guards."""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import multiprocessing

import pytest

from billing_debit_scheduling import exclusive_operation, snapshot, validate_schedule


TODAY = date(2026, 11, 13)
CUTOFF = date(2027, 2, 16)


def validate(rows, total=248600, *, today=TODAY, cutoff=CUTOFF):
    return validate_schedule(rows, total, today=today, cutoff=cutoff)


def test_valid_calendar_preserves_exact_cent_allocations_and_input():
    rows = [{"date": "2026-11-20", "amount": "828.66"},
            {"date": "2026-12-20", "amount": Decimal("828.67")},
            {"date": "2027-01-20", "amount": 828.67}]
    before = deepcopy(rows)
    assert validate(rows) == [{"date": "2026-11-20", "amount": 828.66},
                              {"date": "2026-12-20", "amount": 828.67},
                              {"date": "2027-01-20", "amount": 828.67}]
    assert rows == before


@pytest.mark.parametrize("total", [248599, 248601])
def test_one_cent_difference_is_rejected_without_rebalancing(total):
    with pytest.raises(ValueError, match="exactement"):
        validate([{"date": "2026-11-20", "amount": "2486.00"}], total)


@pytest.mark.parametrize("amount", [
    "1.001", "2486.000000000000000000000000000001", "NaN", "Infinity", "-1", 0,
    True, None, {}, [], "10000.01", "1,50", "not-a-number",
])
def test_invalid_or_fractional_cent_amounts_are_rejected(amount):
    with pytest.raises(ValueError):
        validate([{"date": "2026-11-20", "amount": amount}])


def test_per_installment_limit_is_inclusive_and_not_a_total_limit():
    rows = [{"date": "2026-11-14", "amount": "10000.00"},
            {"date": "2026-11-15", "amount": "10000.00"}]
    assert validate(rows, 2000000)[1]["amount"] == 10000


@pytest.mark.parametrize("value", ["2026-11-13", "2026-11-12", "2026-11-31", "20261120",
                                    "2026-W48-1", "2026-11-20T00:00:00", " 2026-11-20", None])
def test_invalid_non_iso_or_nonfuture_dates_are_rejected(value):
    with pytest.raises(ValueError):
        validate([{"date": value, "amount": 2486}])


def test_tomorrow_and_cutoff_are_allowed_but_day_after_cutoff_is_not():
    assert validate([{"date": "2026-11-14", "amount": 2486}])
    assert validate([{"date": "2027-02-16", "amount": 2486}])
    with pytest.raises(ValueError, match="16/02/2027"):
        validate([{"date": "2027-02-17", "amount": 2486}])
    assert validate([{"date": "2027-02-17", "amount": 2486}], cutoff=None)


@pytest.mark.parametrize("second", ["2026-11-20", "2026-11-19"])
def test_duplicate_and_unsorted_dates_are_rejected(second):
    with pytest.raises(ValueError, match="croissantes"):
        validate([{"date": "2026-11-20", "amount": 1243},
                  {"date": second, "amount": 1243}])


def test_row_count_limits_and_no_empty_schedules():
    rows = [{"date": (TODAY + timedelta(days=i + 1)).isoformat(), "amount": 1} for i in range(60)]
    assert len(validate(rows, 6000)) == 60
    for invalid in ([], {}, None, [None], rows + [{"date": "2027-01-14", "amount": 1}]):
        with pytest.raises(ValueError):
            validate(invalid)


@pytest.mark.parametrize("remaining", [0, -1, True, 248600.0, "248600", None])
def test_remaining_amount_must_be_verified_positive_integer_cents(remaining):
    with pytest.raises(ValueError):
        validate([{"date": "2026-11-20", "amount": 2486}], remaining)


def _hold_operation(directory, line_id, connection):
    try:
        with exclusive_operation(directory, line_id):
            connection.send("locked")
            connection.recv()
    finally:
        connection.close()


def test_lock_blocks_other_process_for_same_line_without_blocking_other_lines(tmp_path):
    context = multiprocessing.get_context("fork")
    parent, child = context.Pipe()
    process = context.Process(target=_hold_operation, args=(str(tmp_path), "bill-1", child))
    process.start()
    child.close()
    try:
        assert parent.poll(5), "The child failed to acquire its test lock"
        assert parent.recv() == "locked"
        with pytest.raises(ValueError, match="déjà en cours"):
            with exclusive_operation(tmp_path, "bill-1"):
                pytest.fail("Concurrent same-line execution must not enter")
        with exclusive_operation(tmp_path, "bill-2"):
            pass
        parent.send("release")
        process.join(5)
        assert not process.is_alive()
        assert process.exitcode == 0
        with exclusive_operation(tmp_path, "bill-1"):
            pass
    finally:
        parent.close()
        if process.is_alive():
            process.terminate()
            process.join(5)


def test_lock_is_released_after_exception_and_uses_safe_filename(tmp_path):
    with pytest.raises(RuntimeError):
        with exclusive_operation(tmp_path, "../../bill-with-path"):
            raise RuntimeError("simulated error")
    with exclusive_operation(tmp_path, "../../bill-with-path"):
        pass
    files = list((tmp_path / "qonto_existing_mandate_scheduling").iterdir())
    assert len(files) == 1
    assert len(files[0].stem) == 64


@pytest.fixture
def business_line():
    return {
        "id": "bill-1", "sessionId": "session-1", "traineeId": "trainee-1",
        "financingType": "PERSONNEL", "qontoInvoiceId": "invoice-1",
        "qontoDraftId": "invoice-1", "qontoInvoiceNumber": "F-TEST-123", "invoiceStatus": "finalized",
        "qontoClientId": "client-1", "qonto_direct_debit_mandate_id": "mandate-1",
        "qonto_mandate_rum": "RUM-1", "qonto_mandate_status": "active",
        "amount": 2486.0, "amountTTC": 2486.0, "currency": "EUR",
        "qonto_amount_paid_cents": 0, "qonto_remaining_amount_cents": 248600,
        "registrationCancelled": False, "dateStart": "2027-01-04",
        "dateEnd": "2027-02-18", "examDate": "2027-02-19",
    }


def test_snapshot_survives_reservation_and_metadata_updates(business_line):
    initial = snapshot(business_line)
    reserved = {**business_line,
                "paymentMode": "sepa_direct_debit", "paymentPlan": {"operation": "reservation-1"},
                "sepa_payment_plan": {"status": "programming", "installments": [{"amount": 2486}]},
                "directDebitInstallments": [{"qonto_direct_debit_subscription_id": "sub-confirmed"}],
                "qonto_direct_debit_subscription_id": "sub-confirmed",
                "initialDebitSchedule": [{"date": "2026-11-20", "amount": 2486}],
                "updatedAt": "2026-11-13T12:00:00Z", "qontoLastSyncedAt": "2026-11-13T12:00:00Z",
                "logs": [{"action": "reservation"}], "operation": {"status": "running"}}
    assert snapshot(reserved) == initial
    assert len(initial) == 64
    assert snapshot(dict(reversed(list(business_line.items())))) == initial


@pytest.mark.parametrize("key,value", [
    ("qontoInvoiceId", "different-invoice"), ("qontoInvoiceNumber", "F-TEST-124"),
    ("invoiceStatus", "cancelled"), ("qontoClientId", "different-client"),
    ("qonto_direct_debit_mandate_id", "different-mandate"), ("qonto_mandate_rum", "RUM-2"),
    ("qonto_mandate_status", "revoked"), ("amountTTC", 2487), ("currency", "USD"),
    ("qonto_amount_paid_cents", 100), ("qonto_remaining_amount_cents", 248500),
    ("cashPaymentEnabled", True), ("registrationCancelled", True), ("examDate", "2027-02-20"),
])
def test_snapshot_detects_changed_business_context(business_line, key, value):
    assert snapshot({**business_line, key: value}) != snapshot(business_line)


def test_payment_proof_order_and_metadata_do_not_change_context_but_payment_status_does(business_line):
    proofs = [{"id": "tx-1", "amount_cents": 5000, "status": "completed"},
              {"id": "tx-2", "amount_cents": 6000, "status": "completed"}]
    baseline = snapshot({**business_line, "qontoBankTransfers": proofs})
    changed_metadata = [{**proof, "allocated_at": "later", "label": "new label"} for proof in reversed(proofs)]
    assert snapshot({**business_line, "qontoBankTransfers": changed_metadata}) == baseline
    changed_metadata[0]["status"] = "reversed"
    assert snapshot({**business_line, "qontoBankTransfers": changed_metadata}) != baseline


def test_malformed_payment_proofs_fail_closed(business_line):
    for bad in ({}, [None], "proof"):
        with pytest.raises(ValueError):
            snapshot({**business_line, "qontoBankTransfers": bad})
