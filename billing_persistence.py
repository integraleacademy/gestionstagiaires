"""Three-way protection for billing rows saved with a whole-document snapshot.

Only payloads returned by ``track_payload`` participate.  The baseline is a
Python attribute, never a JSON key.  Call ``merge_billing_state`` while holding
the storage lock, and ``mark_saved`` only after the write succeeds.  Callers
which already read and mutate canonical data under that lock can keep using
plain dictionaries.
"""

from copy import deepcopy
import json


class BillingPersistenceConflict(ValueError):
    """Two concurrent operations selected different banking resources."""

    def __init__(self, line_id, resource):
        self.line_id = line_id
        self.resource = resource
        super().__init__(
            f"Le suivi financier {line_id} a changé ({resource}). "
            "Rechargez la fiche avant de poursuivre."
        )


class BillingPayload(dict):
    """A normal JSON-serializable dictionary with a private billing baseline."""

    def __init__(self, value):
        super().__init__(value)
        self._billing_baseline = deepcopy(value.get("billing_lines", []))


def track_payload(data):
    return data if isinstance(data, BillingPayload) else BillingPayload(data)


def mark_saved(payload):
    """Rebase the same live object after a successful write, not before it."""
    if isinstance(payload, BillingPayload):
        payload._billing_baseline = deepcopy(payload.get("billing_lines", []))


# Keep coupled provider fields together: a stale refresh must not combine a
# current invoice ID with the old invoice's amount, status, or payment plan.
_GROUPS = {
    "invoice": frozenset("""
        qontoInvoiceId qontoDraftId qontoInvoiceNumber invoiceStatus
        invoiceGeneratedAt finalizedAt sentAt cancelledAt invoiceDownloadedAt
        invoicePdfUrl qontoPdfUrl creditNoteStatus qontoCreditNoteId
        externalInvoiceMarkedAt externalInvoiceNote generationInProgress
        syncWarning qonto_status qontoStatus qontoSyncError
        dueDate due_date issueDate issue_date invoiceDate invoice_date
    """.split()),
    "client": frozenset("qontoClientId qontoCustomerId".split()),
    "mandate": frozenset("""
        qonto_direct_debit_mandate_id qonto_mandate_rum qonto_mandate_client_id
        sign_url mandateStatus qonto_mandate_status qonto_mandate_sign_url
        qonto_mandate_signed_at
    """.split()),
    "schedule": frozenset("""
        paymentPlan paymentMode directDebitInstallments initialDebitSchedule
        initialDebitScheduleVersion qonto_direct_debit_subscription_id
        sepa_payment_plan financial_tracking_override qontoPaymentGlobalStatus
        qonto_rejected_collection_ids qontoDirectDebitSyncWarning
        qontoDirectDebitLastSyncedAt reviewedDebitRejections
    """.split()),
    "payments": frozenset("""
        paymentStatus qonto_amount_paid_cents qonto_total_amount_cents
        qonto_remaining_amount_cents qontoInvoiceAmountPaid qontoPaidAt paidAt
        qontoLastSyncedAt qontoRemoteAmountPaidCents qontoBankTransfers
        qontoBankTransferSyncedAt qontoBankTransferSyncWarning amountPaid
        amount_paid manualPaymentInvoiceId payment_status qonto_payment_status
        total_amount_cents paid_amount_cents remaining_amount_cents
        payment_percentage qontoCollectedAmountCents
    """.split()),
}
_HISTORIES = frozenset(("logs", "billingHistory"))
_METADATA = frozenset(("createdAt", "updatedAt", "qontoAutoSyncAttemptedAt"))
_MANAGED = frozenset().union(*_GROUPS.values(), _HISTORIES, _METADATA, {"qontoReturnedCollections"})
_MISSING = object()
_DEFAULTS = {
    "invoiceStatus": "not_invoiced",
    "paymentStatus": "not_applicable",
    "paymentMode": "cash",  # "Comptant", independent of cash-payment flags.
    "qontoPaymentGlobalStatus": "Comptant",
}


def _rows(values):
    return {
        str(row["id"]): row
        for row in values if isinstance(row, dict) and row.get("id")
    } if isinstance(values, list) else {}


def _state(row, fields):
    # Generated billing views materialize empty/default fields.  That must not
    # look like an intentional edit to an invoice absent from the baseline.
    return {
        key: row[key] for key in fields
        if key in row and row[key] and row[key] != _DEFAULTS.get(key, _MISSING)
    }


def _identity(row, resource):
    if resource == "invoice":
        return str(row.get("qontoInvoiceId") or row.get("qontoDraftId") or "")
    if resource == "client":
        return str(row.get("qontoClientId") or row.get("qontoCustomerId") or "")
    if resource == "mandate":
        return str(row.get("qonto_direct_debit_mandate_id") or "")
    ids = {str(row.get("qonto_direct_debit_subscription_id") or "")}
    plan = row.get("sepa_payment_plan")
    installments = list(row.get("directDebitInstallments") or [])
    if isinstance(plan, dict):
        installments.extend(plan.get("installments") or [])
    ids.update(str(item.get("qonto_direct_debit_subscription_id") or "")
               for item in installments if isinstance(item, dict))
    return frozenset(ids - {""})


def _history(current, incoming):
    events, seen = [], set()
    for event in [*(current or []), *(incoming or [])]:
        key = json.dumps(event, sort_keys=True, ensure_ascii=False, default=str)
        if key not in seen:
            seen.add(key)
            events.append(deepcopy(event))
    # Existing billing logs retain the newest 200 entries.  Sorting avoids
    # old events from a stale request displacing newer canonical receipts.
    events.sort(key=lambda event: str(
        event.get("at") or event.get("date") or ""
    ) if isinstance(event, dict) else "")
    return events[-200:]


def _merge_row(line_id, base, incoming, current):
    identities = {
        name: tuple(_identity(row, name) for row in (base, incoming, current))
        for name in ("invoice", "client", "mandate", "schedule")
    }
    # An old in-flight refresh can finish after an explicit reset/deletion.
    # Its old invoice's receipts and schedule must not restore that identity.
    force_current = set()
    for resource, dependent in (
        ("invoice", {"invoice", "payments", "schedule"}),
        ("mandate", {"mandate", "schedule"}),
    ):
        before, proposed, saved = identities[resource]
        if before and saved != before and proposed == before:
            force_current.update(dependent)

    for resource, (before, proposed, saved) in identities.items():
        if resource not in force_current and proposed != before and saved != before and proposed != saved:
            raise BillingPersistenceConflict(line_id, resource)

    result = deepcopy(current)
    for group, fields in _GROUPS.items():
        before, proposed, saved = (_state(row, fields) for row in (base, incoming, current))
        identity = identities.get(group)
        explicit_transition = bool(identity and identity[1] != identity[0] and identity[2] == identity[0])
        use_incoming = (
            group not in force_current and proposed != before
            and (saved == before or saved == proposed or explicit_transition)
        )
        if use_incoming:
            for key in fields:
                result.pop(key, None)
                if key in incoming:
                    result[key] = deepcopy(incoming[key])

    # Ordinary unrelated edits never block a save.  If both requests changed
    # the same non-banking field differently, retain the canonical value.
    for key in (base.keys() | incoming.keys() | current.keys()) - _MANAGED:
        before, proposed, saved = (row.get(key, _MISSING) for row in (base, incoming, current))
        if proposed != before and (saved == before or saved == proposed):
            if proposed is _MISSING:
                result.pop(key, None)
            else:
                result[key] = deepcopy(proposed)
    for key in _HISTORIES:
        if key in current or key in incoming:
            result[key] = _history(current.get(key), incoming.get(key))
    if current.get("qontoReturnedCollections") or incoming.get("qontoReturnedCollections"):
        # Returns belong to the billing line across mandate replacements.
        # Concurrent observations of different collection IDs both survive.
        result["qontoReturnedCollections"] = deepcopy({
            **(incoming.get("qontoReturnedCollections") or {}),
            **(current.get("qontoReturnedCollections") or {}),
        })
    if result != current and incoming.get("updatedAt"):
        result["updatedAt"] = incoming["updatedAt"]
    if not result.get("createdAt") and incoming.get("createdAt"):
        result["createdAt"] = incoming["createdAt"]
    # Poll throttling is observational and must not replace financial groups.
    if str(incoming.get("qontoAutoSyncAttemptedAt") or "") > str(current.get("qontoAutoSyncAttemptedAt") or ""):
        result["qontoAutoSyncAttemptedAt"] = incoming["qontoAutoSyncAttemptedAt"]
    return result


def merge_billing_state(payload, canonical):
    """Merge only billing_lines; the caller owns the canonical storage lock.

    Plain dicts deliberately retain their existing behavior for initialization
    and already-atomic code paths.  Do not use a plain dict for stale snapshots.
    A missing collection means no edit; an explicit empty list means deletion.
    """
    if not isinstance(payload, BillingPayload) or not isinstance(canonical, dict):
        return payload
    base = _rows(payload._billing_baseline)
    incoming = _rows(payload.get("billing_lines", payload._billing_baseline))
    current = _rows(canonical.get("billing_lines", []))
    result = []
    for line_id in dict.fromkeys([*current, *incoming, *base]):
        old, proposed, saved = base.get(line_id), incoming.get(line_id), current.get(line_id)
        if saved is None:
            # A canonical deletion wins over an old request. New independent
            # rows are accepted; a stale edit cannot resurrect a deleted row.
            if old is None and proposed is not None:
                result.append(deepcopy(proposed))
        elif proposed is None:
            # Delete only a row that has not changed since it was read.
            if old is None or saved != old:
                result.append(deepcopy(saved))
        else:
            result.append(_merge_row(line_id, old or {}, proposed, saved))
    if "billing_lines" in payload or "billing_lines" in canonical or base:
        payload["billing_lines"] = result
    return payload
