"""Read-only presentation of practice-exam scores and recorded exam time."""
from __future__ import annotations

import math


def recorded_seconds(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def activity_exam_seconds(progress, activity_id):
    """Never substitute a module's total learning time for its exam time."""
    ledger = progress.get("activity_seconds") or {}
    return recorded_seconds(ledger.get(activity_id)) if activity_id and isinstance(ledger, dict) else None


def number_label(value):
    number = recorded_seconds(value)
    return f"{number:g}".replace(".", ",") if number is not None else "—"


def exam_groups(report):
    """Group newest-first attempts by pinned exam/version, without inventing time.

    Active seconds cover all recorded work on that exam, including corrections;
    they are deliberately never copied into individual attempt durations.
    """
    groups = {}
    for entry in report.get("exam_catalogue") or []:
        key = (entry["id"], entry.get("version") or "")
        groups[key] = {**entry, "active_seconds": recorded_seconds(entry.get("active_seconds")), "attempts": []}
    for attempt in report.get("exams") or []:
        key = (attempt.get("id") or attempt.get("module") or attempt.get("title") or "Examen blanc",
               attempt.get("version") or "")
        group = groups.setdefault(key, {"id": key[0], "version": key[1],
            "title": attempt.get("title") or attempt.get("module") or "Examen blanc",
            "active_seconds": None, "attempts": []})
        score, total = recorded_seconds(attempt.get("score")), recorded_seconds(attempt.get("total"))
        percent = recorded_seconds(attempt.get("percent"))
        # The public specimen stores a percentage under 'score', with no raw
        # correct-answer count. Keep it as a percentage rather than guessing one.
        if percent is None and total is None and attempt.get("questions"):
            percent = score
        note = f"{number_label(score)} / {number_label(total)}" if score is not None and total else ""
        if percent is not None:
            note += ("\n" if note else "") + number_label(percent) + " %"
        passed = attempt.get("passed")
        result = "Réussi" if passed is True else "À retravailler" if passed is False else attempt.get("status") or "Non disponible"
        group["attempts"].append({"date_label": attempt.get("date_label") or attempt.get("date") or "Non renseignée",
            "score_label": note or "Non disponible", "result_label": result,
            "pass_label": number_label(attempt.get("pass_percent")) + " %" if recorded_seconds(attempt.get("pass_percent")) is not None else "—"})
    result = []
    for group in groups.values():
        if not group["attempts"] and not group["active_seconds"]:
            continue
        group["attempts"].reverse()
        for index, attempt in enumerate(group["attempts"], 1):
            attempt["number"] = index
        group["latest"] = group["attempts"][-1] if group["attempts"] else {
            "date_label": "Aucune tentative soumise", "score_label": "—", "result_label": "En cours"}
        result.append(group)
    return result
