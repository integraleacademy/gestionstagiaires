"""One journal-based attendance rule, shared by the admin view and PDF layouts."""

import re
import unicodedata
from decimal import Decimal

REQUIRED_CONNECTION_SECONDS = 62 * 60 * 60


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
    if seconds is not None:
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds_part = divmod(remainder, 60)
        label = f"{hours} h {minutes:02} min {seconds_part:02} s"
    return {
        "connection_seconds": seconds,
        "connection_duration_label": label,
        "connection_requirement_met": met,
        "attendance_rate": rate,
        "attendance_rate_label": f"{rate:g}".replace(".", ",") + " %",
    }
