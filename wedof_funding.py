"""Read CPF co-funding without changing local billing or payment amounts.

WEDOF documents trainingActionInfo.solicitations and funding type POLE_EMPLOI
(9). Its actual folder payloads use status validated / inProgress / refused,
with amount in euros. A solicitation is not an awarded grant until validated.
"""

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional


FRANCE_TRAVAIL_FIELDS = (
    "france_travail_amount", "france_travail_status",
    "france_travail_requested_amount",
)


def funding_amount(value: Any) -> Optional[str]:
    """Return a finite, nonnegative euro amount; missing is never zero."""
    if value is None or isinstance(value, (bool, dict, list)):
        return None
    try:
        amount = Decimal("".join(str(value).split()).replace(",", "."))
        if not amount.is_finite() or amount < 0:
            return None
        return str(amount.quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return None


def _submission_date(item: Dict[str, Any]) -> float:
    try:
        value = dt.datetime.fromisoformat(str(item.get("submissionDate") or "").replace("Z", "+00:00"))
        return value.replace(tzinfo=value.tzinfo or dt.timezone.utc).timestamp()
    except (ValueError, OverflowError):
        return float("-inf")


def extract_france_travail_funding(folder: Dict[str, Any], legacy_amount: Any = None) -> Dict[str, Any]:
    """Keep the latest France Travail request, never add request history up."""
    info = folder.get("trainingActionInfo")
    solicitations = info.get("solicitations") if isinstance(info, dict) else None
    if str(folder.get("type") or "").strip().casefold() == "cpf" and isinstance(solicitations, list):
        requests = [item for item in solicitations if isinstance(item, dict)
                    and str(item.get("fundingType") or "").upper() in {"9", "POLE_EMPLOI"}]
        if not requests:
            return dict.fromkeys(FRANCE_TRAVAIL_FIELDS)
        _, latest = max(enumerate(requests), key=lambda pair: (_submission_date(pair[1]), pair[0]))
        status = latest.get("status")
        status = status if status in ("validated", "inProgress", "refused") else "unknown"
        amount = funding_amount(latest.get("amount"))
        return {
            "france_travail_status": status,
            "france_travail_amount": amount if status == "validated" else None,
            "france_travail_requested_amount": amount,
        }
    # Compatibility with older snapshots / integrations exposing a direct amount.
    amount = funding_amount(legacy_amount)
    return {
        "france_travail_status": "validated" if amount is not None and Decimal(amount) > 0 else None,
        "france_travail_amount": amount,
        "france_travail_requested_amount": None,
    }
