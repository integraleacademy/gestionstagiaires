"""Validation and local concurrency guards for an explicitly approved schedule.

This module never contacts Qonto, creates a banking resource, or sends a message.
"""

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import errno
import fcntl
import hashlib
import json
from pathlib import Path


def _day(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("Indiquez chaque date au format AAAA-MM-JJ.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Une date de prélèvement est invalide.") from exc
    if parsed.isoformat() != value:
        raise ValueError("Indiquez chaque date au format AAAA-MM-JJ.")
    return parsed


def _amount_cents(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Chaque échéance doit avoir un montant positif avec deux décimales maximum.")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0:
            raise ValueError("Chaque montant de prélèvement doit être strictement positif.")
        if amount > Decimal("10000"):
            raise ValueError("Une échéance ne peut pas dépasser 10 000 €.")
        # Compare against the unrounded original Decimal. Multiplying a very
        # long decimal by 100 first could round away a fractional cent under
        # the default Decimal precision.
        exact_cents = amount.quantize(Decimal("0.01"))
        if amount != exact_cents:
            raise ValueError("Les montants doivent avoir deux décimales maximum, sans fraction de centime.")
        return int(exact_cents * 100)
    except (InvalidOperation, TypeError, OverflowError) as exc:
        raise ValueError("Un montant de prélèvement est invalide.") from exc


def validate_schedule(rows, remaining_cents, *, today: date, cutoff: date | None):
    """Validate the exact proposed rows, preserving their order and amounts."""
    if type(remaining_cents) is not int or remaining_cents <= 0:
        raise ValueError("Le solde restant à prélever doit être positif et vérifié en centimes.")
    if not isinstance(today, date) or isinstance(today, datetime):
        raise ValueError("La date de référence du calendrier est invalide.")
    if cutoff is not None and (not isinstance(cutoff, date) or isinstance(cutoff, datetime)):
        raise ValueError("La date limite des prélèvements est invalide.")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 60:
        raise ValueError("Prévoyez entre 1 et 60 échéances de prélèvement.")
    earliest = today + timedelta(days=1)
    result, total, previous = [], 0, None
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Chaque échéance doit préciser sa date et son montant.")
        due = _day(row.get("date"))
        if due < earliest:
            raise ValueError("Les prélèvements doivent être prévus au plus tôt demain.")
        if cutoff is not None and due > cutoff:
            raise ValueError(f"Les prélèvements doivent être terminés au plus tard le {cutoff:%d/%m/%Y}.")
        if previous is not None and due <= previous:
            raise ValueError("Les dates doivent être croissantes et sans doublon.")
        cents = _amount_cents(row.get("amount"))
        result.append({"date": due.isoformat(), "amount": cents / 100})
        total += cents
        previous = due
    if total != remaining_cents:
        expected = f"{remaining_cents // 100},{remaining_cents % 100:02d} €"
        raise ValueError(f"Le total des échéances doit correspondre exactement au solde restant de {expected}.")
    return result


@contextmanager
def exclusive_operation(directory, line_id):
    """Hold a nonblocking interprocess lock for one billing line's operation."""
    if not isinstance(line_id, str) or not line_id.strip():
        raise ValueError("La ligne de financement à programmer est introuvable.")
    root = Path(directory) / "qonto_existing_mandate_scheduling"
    root.mkdir(parents=True, exist_ok=True)
    filename = hashlib.sha256(line_id.strip().encode("utf-8")).hexdigest() + ".lock"
    with (root / filename).open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EACCES):
                raise ValueError("Une programmation est déjà en cours pour ce financement. Attendez son résultat avant de réessayer.") from exc
            raise
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    # Keep the lock inode: removing it could let another process lock a new
    # inode while an existing waiter still holds the old one.


_BUSINESS_FIELDS = (
    "id", "sessionId", "traineeId", "financingType", "typeFinanceur", "financingRef",
    "qontoInvoiceId", "qontoDraftId", "qontoInvoiceNumber", "invoiceStatus", "qonto_status",
    "qontoClientId", "qontoCustomerId", "qonto_mandate_client_id",
    "qonto_direct_debit_mandate_id", "qonto_mandate_rum", "mandateStatus", "qonto_mandate_status",
    "amount", "amountTTC", "amountHT", "currency",
    "qonto_total_amount_cents", "qonto_amount_paid_cents", "qonto_remaining_amount_cents",
    "qontoRemoteAmountPaidCents", "qontoBankTransferPaidCents", "qontoInvoiceAmountPaid",
    "amountPaid", "amount_paid", "manualPaymentInvoiceId", "paymentStatus",
    "qonto_payment_status", "payment_status", "paid_amount_cents", "remaining_amount_cents",
    "cashPaymentEnabled", "cash_payment_enabled", "cash_payment_amount", "cash_payment_settled",
    "registrationCancelled", "dateStart", "dateEnd", "examDate", "dueDate", "due_date",
)
_TRANSFER_FIELDS = (
    "id", "transaction_id", "amount_cents", "amount", "currency", "status", "side",
    "operation_type", "paid_at", "settled_at",
)


def snapshot(line):
    """Fingerprint business context independently of reservation/schedule state.

    The caller must separately validate its operation ID and reserved calendar.
    Provider subscription IDs, schedule/mode, logs and synchronization timestamps
    are intentionally absent so the approved context survives its reservation.
    """
    if not isinstance(line, dict):
        raise ValueError("Le contexte du financement est invalide.")
    values = {key: line.get(key) for key in _BUSINESS_FIELDS}
    transfers = line.get("qontoBankTransfers")
    if transfers is None:
        transfers = []
    if not isinstance(transfers, list) or any(not isinstance(row, dict) for row in transfers):
        raise ValueError("Les justificatifs de paiement doivent être vérifiés avant la programmation.")
    proofs = [{key: row.get(key) for key in _TRANSFER_FIELDS} for row in transfers]
    serialize = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    values["qontoBankTransfers"] = sorted(proofs, key=serialize)
    return hashlib.sha256(serialize(values).encode("utf-8")).hexdigest()
