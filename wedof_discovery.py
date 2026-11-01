"""Persist verified WEDOF listings before the declaration worker selects work."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Dict, Iterable
from zoneinfo import ZoneInfo

from wedof_automation import sync_folder_automation_status
from wedof_matching import extract_folder, normalize_date


PARIS = ZoneInfo("Europe/Paris")


def parse_timestamp(value: Any):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=PARIS) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def merge_verified_folders(data: Dict[str, Any], folders: Iterable[Dict[str, Any]],
                           *, observed_at: dt.datetime) -> Dict[str, int]:
    """Merge under the application's file lock; never delete unrelated records.

    A listing that began before a webhook or live declaration cannot overwrite
    its newer state. Newly discovered, already-ended enrolments require review
    instead of unexpectedly declaring historic attendance.
    """
    counts = {"updated": 0, "historical_blocked": 0, "newer_preserved": 0}
    statuses = {str(row.get("external_id") or ""): row
                for row in data.get("wedof_automation_status", []) if isinstance(row, dict)}
    cache = {str(row.get("external_id") or ""): row
             for row in data.get("wedof_folder_cache", []) if isinstance(row, dict)}
    journal_ids = {str(row.get("external_id") or "")
                   for row in data.get("wedof_automation_actions", []) if isinstance(row, dict)}
    for folder in folders:
        remote = extract_folder(folder)
        external_id = str(remote.get("external_id") or "")
        if not external_id or str(remote.get("type") or "").strip().casefold() != "cpf":
            continue
        previous = statuses.get(external_id, {})
        checked = parse_timestamp(previous.get("last_checked_at"))
        if checked and checked > observed_at:
            counts["newer_preserved"] += 1
            continue
        end_date = normalize_date(remote.get("end_date"))
        if (not previous and external_id not in journal_ids
                and remote.get("state") == "accepted" and end_date
                and dt.date.fromisoformat(end_date) < observed_at.astimezone(PARIS).date()):
            blocks = data.setdefault("wedof_automation_blocks", [])
            if not any(row.get("external_id") == external_id
                       and row.get("action") in {"entry_training", "both"}
                       and row.get("active") is True for row in blocks if isinstance(row, dict)):
                blocks.append({
                    "id": "WDISC-" + uuid.uuid4().hex[:8].upper(),
                    "external_id": external_id, "action": "entry_training", "active": True,
                    "reason_code": "administrative_issue", "source": "historical_discovery",
                    "comment": "Dossier découvert après sa date de fin : vérifier l’entrée réelle avant de réactiver l’automatisation.",
                    "created_at": observed_at.isoformat(), "updated_at": observed_at.isoformat(),
                })
                counts["historical_blocked"] += 1
        status = sync_folder_automation_status(data, folder, now=observed_at)
        if status is not None:
            statuses[external_id] = status
            cache[external_id] = {**remote, "synced_at": observed_at.isoformat()}
            counts["updated"] += 1
    data["wedof_folder_cache"] = list(cache.values())
    return counts
