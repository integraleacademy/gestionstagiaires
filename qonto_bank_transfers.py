"""Conservative, read-only matching of bank credits to external invoices.

No fuzzy names, partial payments or allocation between several registrations are
inferred here. The caller supplies all billing lines, including already paid and
linked ones, so an eligible external invoice cannot steal another line's credit.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re
import unicodedata


def _words(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[A-Z0-9]+", value.upper()))


def _day(value):
    try:
        return date.fromisoformat(str(value or "")[:10])
    except (TypeError, ValueError):
        return None


def _cents(value, *, already_cents=False):
    if isinstance(value, bool) or isinstance(value, (dict, list)):
        return 0
    try:
        amount = Decimal(str(value))
        scaled = amount if already_cents else amount * 100
        if not scaled.is_finite() or scaled != scaled.to_integral_value():
            return 0
        return max(int(scaled), 0)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return 0


def _transaction_id(transaction):
    return str(transaction.get("id") or transaction.get("transaction_id") or "").strip()


def _record(transaction):
    """Keep the proof needed for a payment, never account/IBAN details."""
    amount = _cents(transaction.get("amount_cents"), already_cents=True)
    if transaction.get("amount_cents") is None:
        amount = _cents(transaction.get("amount"))
    operation = str(transaction.get("operation_type") or "").lower()
    # Qonto documents income/Income as an incoming transfer (Transfer is
    # outgoing). operation_type is sufficient when subject_type is omitted;
    # reject an explicitly contradictory subject such as a collection/refund.
    # https://docs.qonto.com/api-reference/business-api/transactions-statements/transactions/list-transactions
    subject = str(transaction.get("subject_type") or "").strip().lower()
    if operation in {"income", "swift_income"} and subject in {"", "income", "swiftincome"}:
        operation = "transfer"
    return {
        "id": _transaction_id(transaction),
        "amount_cents": amount,
        "currency": str(transaction.get("currency") or "").upper(),
        "status": str(transaction.get("status") or "").lower(),
        "side": str(transaction.get("side") or "").lower(),
        "operation_type": operation,
        "paid_at": str(transaction.get("settled_at") or transaction.get("paid_at") or ""),
        "label": str(transaction.get("label") or transaction.get("clean_counterparty_name") or "")[:300],
        "reference": str(transaction.get("reference") or "")[:500],
        "payer_name": str(transaction.get("payer_name") or transaction.get("clean_counterparty_name") or transaction.get("label") or "")[:300],
    }


def _is_completed_credit(record, today):
    settled = _day(record.get("paid_at"))
    return bool(
        record.get("id") and record.get("status") == "completed"
        and record.get("side") == "credit" and record.get("currency") == "EUR"
        and record.get("operation_type") == "transfer"
        and _cents(record.get("amount_cents"), already_cents=True) > 0
        and settled and settled <= today
    )


def bank_transfer_paid_cents(line, *, today=None):
    """Count verified transfers once; a conflicting/reversed duplicate wins."""
    current_day = today or date.today()
    records = defaultdict(list)
    for raw in line.get("qontoBankTransfers") or []:
        if isinstance(raw, dict) and _transaction_id(raw):
            records[_transaction_id(raw)].append(_record(raw))
    total = 0
    for group in records.values():
        if all(item == group[0] for item in group) and _is_completed_credit(group[0], current_day):
            total += group[0]["amount_cents"]
    return total


def _names(line):
    first = _words(line.get("traineeFirstName"))
    last = _words(line.get("traineeLastName"))
    return {f"{first} {last}", f"{last} {first}"} if first and last else set()


def _strip_bank_prefix(value):
    value = _words(value)
    value = re.sub(r"^(?:VIREMENT|VIR)(?: DE| DE LA PART DE)? ", "", value)
    return re.sub(r"^(?:M|MR|MME|MLLE|MONSIEUR|MADAME|MADEMOISELLE) ", "", value)


def _identity_matches(line, transaction):
    names = _names(line)
    if not names:
        return False
    if any(_strip_bank_prefix(transaction.get(key)) in names for key in ("label", "clean_counterparty_name")):
        return True
    reference = f" {_words(transaction.get('reference'))} "
    return any(f" {name} " in reference for name in names)


def _date_matches(line, record):
    start = _day(line.get("dateStart"))
    end = _day(line.get("dateEnd")) or start
    paid = _day(record.get("paid_at"))
    return bool(start and end and paid and start - timedelta(days=180) <= paid <= end + timedelta(days=90))


def _eligible(line):
    plan = line.get("sepa_payment_plan")
    plan = plan if isinstance(plan, dict) else {}
    return bool(
        str(line.get("financingType") or "").upper() == "PERSONNEL"
        and str(line.get("invoiceStatus") or "").lower() in {"external_generated", "external", "generated_externally"}
        and not line.get("registrationCancelled")
        and not (line.get("qontoInvoiceId") or line.get("qontoDraftId"))
        and line.get("paymentMode") != "sepa_direct_debit"
        and not line.get("directDebitInstallments")
        and not plan.get("installments")
        and not (line.get("cash_payment_enabled") or line.get("cashPaymentEnabled"))
        and not line.get("manualPaymentInvoiceId")
        and not _cents(line.get("amountPaid") or line.get("amount_paid") or 0)
        and not _cents(line.get("qonto_amount_paid_cents") or line.get("paid_amount_cents") or 0, already_cents=True)
    )


def match_bank_transfers(lines, transactions, *, today=None):
    """Return changed ``line_id: [proofs]`` records without mutating inputs.

    Existing proofs are preserved when absent from the remote page and refreshed
    when present (including reversals). New matches require one exact total and
    one full identity, unambiguous across *all* supplied lines and transactions.
    """
    current_day = today or date.today()
    all_lines = {str(item.get("id")): item for item in lines if isinstance(item, dict) and item.get("id")}
    remote = defaultdict(list)
    for transaction in transactions:
        if isinstance(transaction, dict) and _transaction_id(transaction):
            remote[_transaction_id(transaction)].append(transaction)
    indexed = {}
    for identifier, group in remote.items():
        records = [_record(item) for item in group]
        if all(record == records[0] for record in records):
            indexed[identifier] = (group[0], records[0])
        else:
            record = dict(records[0], status="ambiguous")
            indexed[identifier] = (group[0], record)

    owners = defaultdict(set)
    saved = {}
    for line_id, line in all_lines.items():
        saved[line_id] = [dict(item) for item in line.get("qontoBankTransfers") or [] if isinstance(item, dict)]
        for record in saved[line_id]:
            if _transaction_id(record):
                owners[_transaction_id(record)].add(line_id)

    changed = {}
    for line_id, records in saved.items():
        refreshed = []
        for record in records:
            identifier = _transaction_id(record)
            replacement = dict(indexed[identifier][1]) if identifier in indexed else dict(record)
            for key in ("allocation_method", "allocated_at", "allocated_by"):
                if key in record:
                    replacement[key] = record[key]
            # Reversals may clear settled_at. Retain the original settlement
            # date as history, while the reversed status makes the amount zero.
            if replacement.get("status") == "reversed" and not replacement.get("paid_at"):
                replacement["paid_at"] = record.get("paid_at") or ""
            if len(owners.get(identifier, ())) > 1:
                replacement["status"] = "ambiguous"
            refreshed.append(replacement)
        if refreshed != records:
            changed[line_id] = refreshed

    proposals = defaultdict(list)
    for identifier, (transaction, record) in indexed.items():
        if identifier in owners or not _is_completed_credit(record, current_day):
            continue
        identity_lines = [line for line in all_lines.values() if _identity_matches(line, transaction)]
        # An identical name belonging to different people is never resolved by
        # comparing amounts alone. Names cannot establish a unique identity.
        identities = {str(line.get("traineeId") or line["id"]) for line in identity_lines}
        if len(identities) != 1:
            continue
        candidates = [line for line in identity_lines if
                      _cents(line.get("amountTTC") if line.get("amountTTC") is not None else line.get("amount")) == record["amount_cents"]
                      and _date_matches(line, record)]
        if len(candidates) != 1:
            continue
        line = candidates[0]
        line_id = str(line["id"])
        if not _eligible(line) or saved[line_id]:
            continue
        proposals[line_id].append(record)

    for line_id, records in proposals.items():
        # Several equal credits are an ambiguity, not permission to select the
        # first one or to overstate the amount received for this registration.
        if len(records) == 1:
            changed[line_id] = [dict(records[0])]
    return changed


def bank_transfer_candidates(lines, transactions, query, *, today=None):
    """Search actual incoming transfers; manual allocation never infers a payer."""
    words = _words(query).split()
    if not words:
        return []
    owners = defaultdict(set)
    for line in lines:
        for record in line.get("qontoBankTransfers") or []:
            if isinstance(record, dict) and _transaction_id(record):
                owners[_transaction_id(record)].add(str(line.get("id")))
    grouped = defaultdict(list)
    for transaction in transactions:
        if isinstance(transaction, dict) and _transaction_id(transaction):
            grouped[_transaction_id(transaction)].append(_record(transaction))
    results = []
    for identifier, group in grouped.items():
        record = group[0]
        if not all(item == record for item in group) or not _is_completed_credit(record, today or date.today()):
            continue
        haystack = _words(" ".join(record[key] for key in ("payer_name", "label", "reference")))
        if not all(word in haystack for word in words):
            continue
        results.append(dict(record, assigned=bool(owners.get(identifier))))
    return sorted(results, key=lambda record: (record["paid_at"], record["id"]), reverse=True)


def verified_bank_transfer(transaction, *, today=None):
    """Allowlisted bank evidence, or an error for an unsettled/non-transfer row."""
    record = _record(transaction)
    if not _is_completed_credit(record, today or date.today()):
        raise ValueError("Ce virement n’est plus un encaissement confirmé en euros.")
    return record
