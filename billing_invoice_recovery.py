"""Validate an existing Qonto invoice before attaching it to one billing line.

This module has no I/O and never creates invoices, payments or mandates. Call it
with the full remote invoice, then again against fresh local data inside the
attachment transaction. Render the summary as text, never as trusted HTML.
"""

from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any


class InvoiceRecoveryError(ValueError):
    """A business validation failure with a stable, non-sensitive error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code, message):
    raise InvoiceRecoveryError(code, message)


def _text(value, *, code="invalid_reference", required=False, limit=160):
    if value in (None, ""):
        if required:
            _fail(code, "Une référence nécessaire à la vérification est absente.")
        return ""
    if not isinstance(value, str):
        _fail(code, "Une référence reçue ne peut pas être vérifiée.")
    text = value.strip()
    if len(text) > limit or any(ord(char) < 32 or ord(char) == 127 for char in text):
        _fail(code, "Une référence reçue ne peut pas être vérifiée.")
    if required and not text:
        _fail(code, "Une référence nécessaire à la vérification est absente.")
    return text


def _single(values, *, code, required=True):
    found = {_text(value, code=code) for value in values if value not in (None, "")}
    found.discard("")
    if len(found) > 1 or required and not found:
        _fail(code, "Les références nécessaires sont absentes ou contradictoires.")
    return next(iter(found), "")


def _cents(value, *, already_cents=False):
    if isinstance(value, Mapping):
        value = value.get("value")
    if isinstance(value, bool) or value is None or not isinstance(value, (str, int, float, Decimal)):
        _fail("invalid_amount", "Le montant de la facture ne peut pas être vérifié.")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount > Decimal(2**53 - 1):
            raise ValueError
        # Inspect the exact coefficient before multiplying: Decimal's default
        # precision could otherwise round away a very small fractional cent.
        digits, exponent = amount.as_tuple().digits, amount.as_tuple().exponent
        fractional_digits = -(exponent + (0 if already_cents else 2))
        if fractional_digits > 0 and any(digits[-fractional_digits:]):
            raise ValueError
        cents = amount if already_cents else amount * 100
        if cents != cents.to_integral_value() or cents > Decimal(2**53 - 1):
            raise ValueError
        return int(cents)
    except (InvalidOperation, ValueError, OverflowError):
        _fail("invalid_amount", "Le montant doit être positif et exact au centime.")


def _amount(values, *, code):
    amounts = {_cents(value, already_cents=is_cents) for value, is_cents in values
               if value not in (None, "")}
    if len(amounts) != 1:
        _fail(code, "Les montants nécessaires sont absents ou contradictoires.")
    return next(iter(amounts))


def _date(value):
    raw = _text(value, code="invalid_date")
    if not raw:
        return ""
    try:
        # Qonto's performance and invoice dates are calendar dates, not times.
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            raise ValueError
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        _fail("invalid_date", "Une date de la facture ne peut pas être vérifiée.")


def _check_dates(invoice, line):
    expected_start = _date(line.get("dateStart"))
    expected_end = _date(line.get("dateEnd") or line.get("dateStart"))
    if expected_start and expected_end and expected_end < expected_start:
        _fail("invalid_date", "Les dates de la formation sont incohérentes.")
    starts, ends = [], []
    starts.extend(_date(invoice.get(key)) for key in ("performance_start_date", "performance_date") if invoice.get(key))
    if invoice.get("performance_end_date"):
        ends.append(_date(invoice["performance_end_date"]))
    # Our generated item labels also expose session dates. Check these when
    # present even if the remote response omits top-level performance fields.
    range_pattern = re.compile(
        r"session\s+du\s+(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})\s+au\s+"
        r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", re.IGNORECASE,
    )
    for key in ("items", "line_items", "invoice_items"):
        rows = invoice.get(key)
        if rows is None:
            continue
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            _fail("invalid_invoice", "Les prestations de la facture ne peuvent pas être vérifiées.")
        for row in rows:
            if row.get("performance_start_date"):
                starts.append(_date(row["performance_start_date"]))
            if row.get("performance_end_date"):
                ends.append(_date(row["performance_end_date"]))
            for field in ("title", "description"):
                content = row.get(field)
                if not isinstance(content, str):
                    continue
                for start, end in range_pattern.findall(content):
                    def parse(value):
                        if "/" in value:
                            day, month, year = value.split("/")
                            value = f"{year}-{month}-{day}"
                        return _date(value)
                    starts.append(parse(start))
                    ends.append(parse(end))
    if any(not expected_start or value != expected_start for value in starts):
        _fail("performance_dates_mismatch", "Le début de prestation ne correspond pas à cette formation.")
    if any(not expected_end or value != expected_end for value in ends):
        _fail("performance_dates_mismatch", "La fin de prestation ne correspond pas à cette formation.")


def _invoice_refs(line):
    sources = [line]
    legacy = line.get("qonto_invoice")
    if legacy not in (None, {}):
        if not isinstance(legacy, Mapping):
            _fail("invalid_known_lines", "Les rattachements existants ne peuvent pas être vérifiés.")
        sources.append(legacy)
    ids, numbers = set(), set()
    for source in sources:
        for key in ("qontoInvoiceId", "qontoDraftId", "qonto_invoice_id"):
            value = _text(source.get(key))
            if value:
                ids.add(value)
        for key in ("qontoInvoiceNumber", "qonto_invoice_number"):
            value = _text(source.get(key))
            if value:
                numbers.add(value)
    return ids, numbers


def _number_family(number):
    return re.sub(r"-PROFORMA$", "", number, flags=re.IGNORECASE).casefold()


def validate_invoice_attachment(
    invoice: Mapping[str, Any], line: Mapping[str, Any],
    known_lines: Iterable[Mapping[str, Any]], *, requested_number: str,
) -> dict[str, Any]:
    """Return verified link updates and a small UI summary; reject ambiguity.

    ``known_lines`` must include stored/legacy links, including historical
    registrations, so a disappeared row cannot make its invoice appear free.
    The caller performs lookup and persistence, and must revalidate in its
    atomic transaction. Financial state and SEPA plans are deliberately absent
    from ``updates``; existing invoice reconciliation handles those separately.
    """
    if not isinstance(invoice, Mapping) or not isinstance(line, Mapping):
        _fail("invalid_invoice", "La facture ou le financement ne peut pas être vérifié.")
    number = _text(requested_number, required=True)
    remote_number = _single((invoice.get("number"), invoice.get("invoice_number")), code="invoice_number_ambiguous")
    if remote_number != number:
        _fail("invoice_number_mismatch", "Le numéro retourné par Qonto ne correspond pas à la recherche.")
    if re.search(r"(?:^|[-\s])PROFORMA(?:$|[-\s])", number, re.IGNORECASE):
        _fail("invoice_not_final", "Seule une facture définitive peut être rattachée.")
    invoice_id = _text(invoice.get("id"), code="missing_invoice_id", required=True)
    status = _text(invoice.get("status"), code="invoice_not_final", required=True).lower()
    if status not in {"finalized", "sent", "paid", "unpaid", "partially_paid", "overdue"}:
        _fail("invoice_not_final", "Cette facture n’est pas définitive ou a été annulée.")
    target = tuple(_text(line.get(key), code="missing_line_identity", required=True)
                   for key in ("id", "traineeId", "sessionId"))
    expected_client = _single((line.get(key) for key in (
        "qontoClientId", "qontoCustomerId", "qonto_mandate_client_id",
    )), code="local_client_ambiguous")
    remote_clients = [invoice.get("client_id"), invoice.get("clientId"), invoice.get("customer_id")]
    client_names = []
    for key in ("client", "customer"):
        client = invoice.get(key)
        if client is not None:
            if not isinstance(client, Mapping):
                _fail("remote_client_ambiguous", "Le client Qonto ne peut pas être vérifié.")
            remote_clients.extend((client.get("id"), client.get("client_id"), client.get("customer_id")))
            client_names.extend((client.get("name"), client.get("company_name")))
    if _single(remote_clients, code="remote_client_ambiguous") != expected_client:
        _fail("client_mismatch", "La facture appartient à un autre client Qonto.")
    amount_keys = ("total_amount", "total_including_taxes", "amount_including_taxes")
    currencies = [invoice.get("currency")]
    currencies.extend(invoice[key].get("currency") for key in amount_keys if isinstance(invoice.get(key), Mapping))
    currency = _single(currencies, code="currency_unverified")
    if currency != "EUR" or _text(line.get("currency") or "EUR") != "EUR":
        _fail("currency_mismatch", "Le financement et la facture doivent être en euros.")
    total_cents = _amount(
        [(invoice.get(key), False) for key in amount_keys]
        + [(invoice.get(key), True) for key in ("total_amount_cents", "totalAmountCents")],
        code="remote_amount_ambiguous",
    )
    expected_cents = _amount([(line.get(key), False) for key in ("amountTTC", "amount")], code="local_amount_ambiguous")
    if total_cents != expected_cents:
        _fail("amount_mismatch", "Le montant de la facture diffère du montant de ce financement.")
    _check_dates(invoice, line)
    current_ids, current_numbers = _invoice_refs(line)
    if current_ids - {invoice_id} or any(_number_family(value) != _number_family(number) for value in current_numbers):
        _fail("target_already_linked", "Ce financement est déjà lié à une autre facture.")
    if isinstance(known_lines, (str, bytes, Mapping)) or not isinstance(known_lines, Iterable):
        _fail("invalid_known_lines", "Les rattachements existants ne peuvent pas être vérifiés.")
    for other in known_lines:
        if not isinstance(other, Mapping):
            _fail("invalid_known_lines", "Les rattachements existants ne peuvent pas être vérifiés.")
        other_ids, other_numbers = _invoice_refs(other)
        identity = tuple(_text(other.get(key)) for key in ("id", "traineeId", "sessionId"))
        if identity[0] == target[0]:
            if identity != target or other_ids - {invoice_id} or any(
                _number_family(value) != _number_family(number) for value in other_numbers
            ):
                _fail("target_changed", "Ce financement a changé. Relancez la vérification.")
            continue
        if invoice_id in other_ids or any(_number_family(value) == _number_family(number) for value in other_numbers):
            _fail("invoice_already_linked", "Cette facture est déjà rattachée à un autre financement.")
    client_name = next((value for value in (*client_names, invoice.get("client_name"), line.get("clientName"))
                        if isinstance(value, str) and value.strip()), "")
    client_name = "".join(char for char in client_name if ord(char) >= 32 and ord(char) != 127).strip()[:240]
    return {
        "updates": {
            "qontoInvoiceId": invoice_id, "qontoDraftId": invoice_id,
            "qontoInvoiceNumber": number, "qontoClientId": expected_client,
            "qontoCustomerId": expected_client, "generationInProgress": False,
        },
        "summary": {
            "id": invoice_id, "number": number, "client_name": client_name,
            "total_amount_cents": total_cents, "status": status,
            "issue_date": _date(invoice.get("issue_date")),
            "due_date": _date(invoice.get("due_date")),
            "performance_start_date": _date(invoice.get("performance_start_date") or invoice.get("performance_date")),
            "performance_end_date": _date(invoice.get("performance_end_date")),
        },
    }
