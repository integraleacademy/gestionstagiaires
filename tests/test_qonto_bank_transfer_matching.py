from copy import deepcopy
from datetime import date

import pytest

from qonto_bank_transfers import bank_transfer_paid_cents, match_bank_transfers


TODAY = date(2026, 11, 1)


def line(**changes):
    return dict({"id": "L1", "traineeId": "T1", "sessionId": "S1",
                 "traineeFirstName": "Alex", "traineeLastName": "MARTIN",
                 "amount": 1250, "financingType": "PERSONNEL",
                 "invoiceStatus": "external_generated", "dateStart": "2026-09-01",
                 "dateEnd": "2026-10-27"}, **changes)


def transfer(**changes):
    return dict({"id": "TX1", "amount_cents": 125000, "currency": "EUR",
                 "side": "credit", "operation_type": "transfer", "status": "completed",
                 "label": "M ALEX MARTIN", "reference": "Virement de M Alex Martin",
                 "settled_at": "2026-09-03T12:32:00Z"}, **changes)


def test_alex_exact_credit_is_matched_without_exposing_bank_details():
    raw = transfer(transfer={"counterparty_account_number": "SECRET-IBAN"})
    rows = [line()]
    original = deepcopy(rows)
    result = match_bank_transfers(rows, [raw], today=TODAY)
    assert bank_transfer_paid_cents({"qontoBankTransfers": result["L1"]}, today=TODAY) == 125000
    assert rows == original
    assert "SECRET-IBAN" not in repr(result)
    assert result["L1"][0]["paid_at"] == "2026-09-03T12:32:00Z"


def test_accented_names_and_reference_only_match_are_normalized():
    student = line(traineeFirstName="Élise", traineeLastName="D'ANGELO")
    credit = transfer(label="Parent", reference="Formation Elise D Angelo septembre")
    assert "L1" in match_bank_transfers([student], [credit], today=TODAY)


@pytest.mark.parametrize("changes", [
    {"side": "debit"}, {"status": "reversed"}, {"status": "pending"},
    {"currency": "USD"}, {"amount_cents": 124999}, {"amount_cents": -125000},
    {"operation_type": "card"}, {"operation_type": "income", "subject_type": "Refund"},
    {"settled_at": "2027-01-01"}, {"settled_at": "2025-01-01"}, {"settled_at": ""},
    {"label": "Alex AUTRENOM", "reference": "Virement MARTIN"},
    {"label": "Alex MARTINEZ", "reference": ""},
])
def test_ineligible_or_unverified_transaction_is_not_assigned(changes):
    assert match_bank_transfers([line()], [transfer(**changes)], today=TODAY) == {}


def test_income_identified_as_transfer_is_accepted():
    result = match_bank_transfers([line()], [transfer(operation_type="income", subject_type="Transfer")], today=TODAY)
    assert bank_transfer_paid_cents({"qontoBankTransfers": result["L1"]}, today=TODAY) == 125000


@pytest.mark.parametrize("changes", [
    {"financingType": "CPF"}, {"invoiceStatus": "not_invoiced"},
    {"qontoInvoiceId": "INV1"}, {"qontoDraftId": "INV1"},
    {"paymentMode": "sepa_direct_debit"}, {"directDebitInstallments": [{"amount": 1250}]},
    {"cash_payment_enabled": True}, {"cashPaymentEnabled": True}, {"amountPaid": 1250}, {"paid_amount_cents": 125000},
    {"registrationCancelled": True},
])
def test_ineligible_billing_line_is_not_assigned(changes):
    assert match_bank_transfers([line(**changes)], [transfer()], today=TODAY) == {}


def test_homonym_is_not_resolved_by_amount_or_invoice_status():
    other = line(id="L2", traineeId="T2", amount=1000, qontoInvoiceId="INV2", invoiceStatus="paid")
    assert match_bank_transfers([line(), other], [transfer()], today=TODAY) == {}


def test_second_registration_with_same_amount_prevents_assignment():
    other = line(id="L2", sessionId="S2", qontoInvoiceId="INV2", invoiceStatus="paid")
    assert match_bank_transfers([line(), other], [transfer()], today=TODAY) == {}


def test_multiple_equal_credits_are_not_arbitrarily_selected():
    assert match_bank_transfers([line()], [transfer(), transfer(id="TX2")], today=TODAY) == {}


def test_repeated_remote_transaction_is_deduplicated():
    result = match_bank_transfers([line()], [transfer(), transfer()], today=TODAY)
    assert len(result["L1"]) == 1
    assert bank_transfer_paid_cents({"qontoBankTransfers": result["L1"] * 2}, today=TODAY) == 125000


def test_previously_assigned_transaction_cannot_be_reused():
    proof = match_bank_transfers([line()], [transfer()], today=TODAY)["L1"]
    other = line(id="L2", traineeId="T2", traineeLastName="OTHER", qontoBankTransfers=proof)
    assert match_bank_transfers([line(), other], [transfer()], today=TODAY) == {}


def test_existing_credit_is_idempotent_and_reversal_removes_paid_amount():
    proof = match_bank_transfers([line()], [transfer()], today=TODAY)["L1"]
    saved = line(qontoBankTransfers=proof)
    assert match_bank_transfers([saved], [transfer()], today=TODAY) == {}
    assert match_bank_transfers([saved], [], today=TODAY) == {}
    updates = match_bank_transfers([saved], [transfer(status="reversed")], today=TODAY)
    assert bank_transfer_paid_cents(line(qontoBankTransfers=updates["L1"]), today=TODAY) == 0


def test_conflicting_duplicates_do_not_count():
    proof = match_bank_transfers([line()], [transfer()], today=TODAY)["L1"]
    conflicting = [*proof, dict(proof[0], status="reversed")]
    assert bank_transfer_paid_cents(line(qontoBankTransfers=conflicting), today=TODAY) == 0


def test_same_transaction_stored_on_two_lines_is_flagged_ambiguous():
    proof = match_bank_transfers([line()], [transfer()], today=TODAY)["L1"]
    updates = match_bank_transfers([line(qontoBankTransfers=proof), line(id="L2", qontoBankTransfers=proof)], [], today=TODAY)
    assert set(updates) == {"L1", "L2"}
    assert all(bank_transfer_paid_cents({"qontoBankTransfers": records}, today=TODAY) == 0 for records in updates.values())
