"""Paris deadlines shared by the EDOF scheduler and the dossier dashboard."""
import datetime as dt
from zoneinfo import ZoneInfo


PARIS = ZoneInfo("Europe/Paris")
# Earlier entries keep the rules in force on their start date.
PAPER_ENTRY_FROM = "2026-11-05"


def paper_entry(action, date):
    return action == "entry_training" and isinstance(date, str) and date >= PAPER_ENTRY_FROM


def scheduled_at(action, date):
    if action not in {"entry_training", "service_done"}:
        return None
    try:
        day = dt.date.fromisoformat(date)
    except (TypeError, ValueError):
        return None
    hour = 8 if action == "entry_training" and not paper_entry(action, date) else 18
    return dt.datetime.combine(day, dt.time(hour), PARIS)
