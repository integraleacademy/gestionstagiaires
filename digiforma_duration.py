"""Digiforma journal attendance and overall APS e-learning progress."""

import re
import unicodedata
from decimal import Decimal

REQUIRED_CONNECTION_SECONDS = 62 * 60 * 60
REQUIRED_APS_PATHS = 8
REQUIRED_APS_EVALUATIONS = 8


def duration_seconds(value):
    """Parse a complete Digiforma total without rounding across the 62 h boundary."""
    text = unicodedata.normalize("NFKD", str(value or "")).lower().strip()
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s+", " ", text)
    if not text or text.startswith(("<", ">", "-")):
        return None
    clock = re.fullmatch(r"(\d+):(\d{2})(?::(\d{2}))?", text)
    if clock:
        hours, minutes, seconds = (int(v or 0) for v in clock.groups())
        return hours * 3600 + minutes * 60 + seconds if minutes < 60 and seconds < 60 else None
    compact = re.fullmatch(r"(\d+)h(\d{1,2})(?:m(\d{1,2})s?)?", text)
    if compact:
        hours, minutes, seconds = (int(v or 0) for v in compact.groups())
        return hours * 3600 + minutes * 60 + seconds if minutes < 60 and seconds < 60 else None
    units = r"(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>heures?|h|minutes?|min|m|secondes?|sec|s)"
    matches = list(re.finditer(units, text))
    remainder = re.sub(units, "", text)
    if not matches or re.sub(r"\bet\b|[,\s.]", "", remainder):
        return None
    total = Decimal(0)
    seen = set()
    for match in matches:
        unit = match["unit"][0]
        if unit in seen:
            return None
        seen.add(unit)
        total += Decimal(match["number"].replace(",", ".")) * {"h": 3600, "m": 60, "s": 1}[unit]
    return int(total)


def journal_attendance(value):
    seconds = duration_seconds(value)
    met = seconds is not None and seconds > REQUIRED_CONNECTION_SECONDS
    rate = 100.0 if met else min(99.9, round((seconds or 0) * 100 / REQUIRED_CONNECTION_SECONDS, 1))
    label = "Non renseignée"
    short_label = "Non renseignée"
    if seconds is not None:
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds_part = divmod(remainder, 60)
        label = f"{hours} h {minutes:02} min {seconds_part:02} s"
        short_label = f"{hours} h {minutes:02}"
    return {
        "connection_seconds": seconds,
        "connection_duration_label": label,
        "connection_duration_short_label": short_label,
        "connection_requirement_met": met,
        "attendance_rate": rate,
        "attendance_rate_label": f"{rate:g}".replace(".", ",") + " %",
    }


def aps_elearning_completion(tracking):
    """Give each of the three required objectives equal weight, without early 100%."""
    attendance = journal_attendance(tracking.get("connection_log_total"))

    def completed_count(prefix, required):
        try:
            total = int(tracking.get(prefix + "_total"))
            completed = int(tracking.get(prefix + "_completed"))
        except (TypeError, ValueError, OverflowError):
            return None
        if total <= 0 or completed < 0 or completed > total:
            return None
        return min(completed, required)

    paths = completed_count("paths", REQUIRED_APS_PATHS)
    evaluations = completed_count("evaluations", REQUIRED_APS_EVALUATIONS)
    paths_met = paths == REQUIRED_APS_PATHS
    evaluations_met = evaluations == REQUIRED_APS_EVALUATIONS
    complete = paths_met and evaluations_met and attendance["connection_requirement_met"]
    rate = None
    if paths is not None and evaluations is not None and attendance["connection_seconds"] is not None:
        average = (paths * 100 / REQUIRED_APS_PATHS
                   + evaluations * 100 / REQUIRED_APS_EVALUATIONS
                   + attendance["attendance_rate"]) / 3
        rate = 100.0 if complete else min(99.9, round(average, 1))
    return {
        **attendance,
        "paths_completed": paths,
        "paths_required": REQUIRED_APS_PATHS,
        "paths_requirement_met": paths_met,
        "evaluations_completed": evaluations,
        "evaluations_required": REQUIRED_APS_EVALUATIONS,
        "evaluations_requirement_met": evaluations_met,
        "overall_rate": rate,
        "overall_rate_label": f"{rate:g}".replace(".", ",") + " %" if rate is not None else "À vérifier",
        "is_complete": complete,
    }
