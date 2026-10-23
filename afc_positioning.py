"""Explainable RAN allocation using only matched positioning-test results."""
import math
import re
from fractions import Fraction

from afc_enrolments import normalized


def name(value):
    return re.sub(r"[^\w]+", " ", normalized(value)).strip()


def identity(contact):
    return name(contact.get("last_name")), name(contact.get("first_name"))


def phone(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("0033"):
        digits = "0" + digits[4:]
    elif digits.startswith("33") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits


def same_contact(left, right):
    email = normalized(left.get("email"))
    number = phone(left.get("phone"))
    return bool((email and email == normalized(right.get("email")))
                or (number and number == phone(right.get("phone"))))


def matched_result(trainee, cohort, tests):
    pair = identity(trainee)
    if not all(pair):
        return None
    matches = [entry for entry in tests if isinstance(entry, dict)
               and isinstance(entry.get("contact"), dict)
               and identity(entry["contact"]) in (pair, pair[::-1])]
    strong = [entry for entry in matches if same_contact(trainee, entry["contact"])]
    if strong:
        matches = strong
    elif any(other is not trainee and identity(other) in (pair, pair[::-1]) for other in cohort):
        return None
    elif len({(normalized(entry["contact"].get("email")), phone(entry["contact"].get("phone")))
              for entry in matches}) > 1:
        return None
    if not matches:
        return None
    latest = max(matches, key=lambda entry: (str(entry.get("created_at") or ""), str(entry.get("id") or "")))
    try:
        score, total = float(latest["score"]), float(latest["total"])
        if not math.isfinite(score) or not math.isfinite(total) or total <= 0 or not 0 <= score <= total:
            return None
    except (KeyError, ValueError, TypeError):
        return None
    return {"id": str(latest.get("id") or ""), "score": score, "total": total,
            "over_20": round(score / total * 20, 2), "created_at": str(latest.get("created_at") or "")}


def allocation(cohort, tests, target):
    scores = {str(trainee["id"]): matched_result(trainee, cohort, tests) for trainee in cohort}
    result = {"scores": scores, "profiles": None, "issue": ""}
    if not target:
        result["issue"] = "La répartition automatique 8 / 2 / 2 est prévue pour la session AFC de novembre 2026."
        return result
    if len(cohort) != sum(target.values()):
        result["issue"] = "La répartition 8 / 2 / 2 nécessite exactement 12 candidats inscrits."
        return result
    if any(score is None for score in scores.values()):
        result["issue"] = "Un résultat manque ou son identité est ambiguë. Vérifiez les tests avant de répartir."
        return result
    if len({score["id"] for score in scores.values()}) != len(scores):
        result["issue"] = "Un même test correspond à plusieurs candidats. Vérifiez leurs identités."
        return result
    def ratio(trainee_id):
        score = scores[trainee_id]
        return Fraction(str(score["score"])) / Fraction(str(score["total"]))
    ranking = sorted(scores, key=lambda trainee_id: (ratio(trainee_id), trainee_id))
    for boundary in (target["54"], target["54"] + target["40"]):
        if 0 < boundary < len(ranking) and ratio(ranking[boundary - 1]) == ratio(ranking[boundary]):
            result["issue"] = "Des notes ex æquo se trouvent entre deux groupes RAN. Choisissez les profils concernés."
            return result
    result["profiles"] = {trainee_id: 54 if index < target["54"] else 40 if index < target["54"] + target["40"] else 0
                          for index, trainee_id in enumerate(ranking)}
    return result
