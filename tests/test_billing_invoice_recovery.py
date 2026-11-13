"""An existing invoice can be attached only to one verified financing."""

from copy import deepcopy

import pytest

from billing_invoice_recovery import InvoiceRecoveryError, validate_invoice_attachment


@pytest.fixture
def line():
    return {
        "id": "billing-1", "traineeId": "trainee-1", "sessionId": "session-1",
        "financingType": "PERSONNEL", "amount": 1275.55, "amountTTC": 1275.55,
        "currency": "EUR", "qontoClientId": "client-1", "qontoCustomerId": "client-1",
        "qonto_mandate_client_id": "client-1", "clientName": "Camille Martin",
        "dateStart": "2027-03-01", "dateEnd": "2027-04-08", "examDate": "2027-04-09",
        "paymentMode": "cash", "paymentPlan": {}, "directDebitInstallments": [],
        "generationInProgress": True,
    }


@pytest.fixture
def invoice():
    return {
        "id": "invoice-1", "number": "INV-TEST-700", "status": "unpaid",
        "client_id": "client-1", "client": {"id": "client-1", "name": "Camille Martin"},
        "total_amount": {"value": "1275.55", "currency": "EUR"},
        "performance_start_date": "2027-03-01", "performance_end_date": "2027-04-08",
        "issue_date": "2027-01-20", "due_date": "2027-02-19",
        "items": [{"title": "Formation — Session du 01/03/2027 au 08/04/2027"}],
    }


def verify(invoice, line, known=None, number="INV-TEST-700"):
    return validate_invoice_attachment(invoice, line, known if known is not None else [line], requested_number=number)


def assert_rejected(code, invoice, line, known=None, number="INV-TEST-700"):
    with pytest.raises(InvoiceRecoveryError) as error:
        verify(invoice, line, known, number)
    assert error.value.code == code


def test_attaches_exact_final_invoice_without_touching_financial_plan(invoice, line):
    before = deepcopy((invoice, line))
    invoice.update(email="private@example.test", iban="private-bank-data", public_url="https://example.test/private")
    remote_before = deepcopy(invoice)
    result = verify(invoice, line)
    assert result["updates"] == {
        "qontoInvoiceId": "invoice-1", "qontoDraftId": "invoice-1", "qontoInvoiceNumber": "INV-TEST-700",
        "qontoClientId": "client-1", "qontoCustomerId": "client-1", "generationInProgress": False,
    }
    assert result["summary"] == {
        "id": "invoice-1", "number": "INV-TEST-700", "client_name": "Camille Martin",
        "total_amount_cents": 127555, "status": "unpaid", "issue_date": "2027-01-20",
        "due_date": "2027-02-19", "performance_start_date": "2027-03-01", "performance_end_date": "2027-04-08",
    }
    assert invoice == remote_before
    assert line == before[1]


@pytest.mark.parametrize("status", ["finalized", "sent", "paid", "unpaid", "partially_paid", "overdue"])
def test_valid_final_statuses(invoice, line, status):
    invoice["status"] = status
    assert verify(invoice, line)["summary"]["status"] == status


@pytest.mark.parametrize("status", ["draft", "cancelled", "canceled", "deleted", "unknown", ""])
def test_nonfinal_or_cancelled_invoices_are_rejected(invoice, line, status):
    invoice["status"] = status
    assert_rejected("invoice_not_final", invoice, line)


def test_invoice_number_is_exact_and_proforma_is_not_accepted(invoice, line):
    assert_rejected("invoice_number_mismatch", invoice, line, number="inv-test-700")
    invoice["number"] = "INV-TEST-700-PROFORMA"
    assert_rejected("invoice_not_final", invoice, line, number=invoice["number"])


def test_conflicting_invoice_number_aliases_are_rejected(invoice, line):
    invoice["invoice_number"] = "INV-TEST-701"
    assert_rejected("invoice_number_ambiguous", invoice, line)


def test_missing_remote_id_is_rejected(invoice, line):
    invoice.pop("id")
    assert_rejected("missing_invoice_id", invoice, line)


@pytest.mark.parametrize("key", ["qontoClientId", "qontoCustomerId", "qonto_mandate_client_id"])
def test_each_verified_local_client_reference_can_identify_the_customer(invoice, line, key):
    for field in ("qontoClientId", "qontoCustomerId", "qonto_mandate_client_id"):
        line.pop(field)
    line[key] = "client-1"
    assert verify(invoice, line)["updates"]["qontoClientId"] == "client-1"


def test_missing_or_conflicting_client_identity_is_not_guessed_from_name(invoice, line):
    line["qonto_mandate_client_id"] = "client-2"
    assert_rejected("local_client_ambiguous", invoice, line)
    for key in ("qontoClientId", "qontoCustomerId", "qonto_mandate_client_id"):
        line.pop(key)
    assert_rejected("local_client_ambiguous", invoice, line)


def test_wrong_remote_client_and_remote_alias_conflict_are_rejected(invoice, line):
    invoice["client_id"] = "client-2"
    assert_rejected("remote_client_ambiguous", invoice, line)
    invoice["client"]["id"] = "client-2"
    assert_rejected("client_mismatch", invoice, line)


def test_nested_remote_client_identity_is_supported(invoice, line):
    invoice.pop("client_id")
    assert verify(invoice, line)["updates"]["qontoCustomerId"] == "client-1"


@pytest.mark.parametrize("value", ["1275.54", "1275.56"])
def test_one_cent_difference_is_rejected(invoice, line, value):
    invoice["total_amount"]["value"] = value
    assert_rejected("amount_mismatch", invoice, line)


@pytest.mark.parametrize("value", ["1275.551", "1275.550000000000000000000000000001", "NaN", "Infinity", "-1275.55", "0", True, None])
def test_invalid_amounts_are_not_rounded_or_coerced(invoice, line, value):
    invoice["total_amount"]["value"] = value
    assert_rejected("invalid_amount", invoice, line)


def test_cent_totals_and_currency_are_explicit(invoice, line):
    invoice.pop("total_amount")
    invoice["total_amount_cents"] = 127555
    invoice["currency"] = "EUR"
    assert verify(invoice, line)["summary"]["total_amount_cents"] == 127555
    invoice["total_amount_cents"] = "127555.1"
    assert_rejected("invalid_amount", invoice, line)


def test_missing_or_conflicting_remote_totals_are_rejected(invoice, line):
    invoice["total_amount_cents"] = 127556
    assert_rejected("remote_amount_ambiguous", invoice, line)
    invoice.pop("total_amount_cents")
    invoice.pop("total_amount")
    invoice["currency"] = "EUR"
    assert_rejected("remote_amount_ambiguous", invoice, line)


def test_conflicting_local_totals_are_rejected(invoice, line):
    line["amount"] = 1500
    assert_rejected("local_amount_ambiguous", invoice, line)


def test_currency_must_be_verified_as_eur(invoice, line):
    invoice["total_amount"]["currency"] = "USD"
    assert_rejected("currency_mismatch", invoice, line)
    invoice["currency"] = "EUR"
    assert_rejected("currency_unverified", invoice, line)
    invoice.pop("currency")
    invoice["total_amount"].pop("currency")
    assert_rejected("currency_unverified", invoice, line)


def test_dates_if_exposed_must_match_training_not_exam(invoice, line):
    invoice["performance_end_date"] = line["examDate"]
    assert_rejected("performance_dates_mismatch", invoice, line)


def test_missing_remote_performance_dates_do_not_invent_dates(invoice, line):
    invoice.pop("performance_start_date")
    invoice.pop("performance_end_date")
    result = verify(invoice, line)
    assert result["summary"]["performance_start_date"] == ""
    assert result["summary"]["performance_end_date"] == ""


def test_item_session_dates_are_checked_even_without_top_level_dates(invoice, line):
    invoice.pop("performance_start_date")
    invoice.pop("performance_end_date")
    invoice["items"][0]["title"] = "Formation — Session du 02/03/2027 au 08/04/2027"
    assert_rejected("performance_dates_mismatch", invoice, line)


def test_invalid_remote_calendar_date_is_rejected(invoice, line):
    invoice["performance_start_date"] = "2027-02-30"
    assert_rejected("invalid_date", invoice, line)


def test_same_invoice_attachment_is_idempotent(invoice, line):
    line.update(qontoInvoiceId="invoice-1", qontoDraftId="invoice-1", qontoInvoiceNumber="INV-TEST-700")
    assert verify(invoice, line)["updates"]["qontoInvoiceId"] == "invoice-1"


def test_existing_different_invoice_on_target_is_not_replaced(invoice, line):
    line["qontoInvoiceId"] = "invoice-2"
    assert_rejected("target_already_linked", invoice, line)


@pytest.mark.parametrize("reference", [
    {"qontoInvoiceId": "invoice-1"}, {"qontoDraftId": "invoice-1"},
    {"qontoInvoiceNumber": "INV-TEST-700"}, {"qontoInvoiceNumber": "INV-TEST-700-PROFORMA"},
    {"qonto_invoice": {"qonto_invoice_id": "invoice-1"}},
])
def test_invoice_attached_to_another_line_is_rejected_including_legacy(invoice, line, reference):
    other = {**line, "id": "billing-2", **reference}
    assert_rejected("invoice_already_linked", invoice, line, [line, other])


def test_changed_target_or_ambiguous_line_identity_is_rejected(invoice, line):
    changed = {**line, "qontoInvoiceId": "invoice-2"}
    assert_rejected("target_changed", invoice, line, [changed])
    changed = {**line, "traineeId": "trainee-2"}
    assert_rejected("target_changed", invoice, line, [changed])


@pytest.mark.parametrize("known", [None, {}, [None], "not-a-list"])
def test_unverifiable_known_links_fail_closed(invoice, line, known):
    with pytest.raises(InvoiceRecoveryError) as error:
        validate_invoice_attachment(invoice, line, known, requested_number="INV-TEST-700")
    assert error.value.code == "invalid_known_lines"
