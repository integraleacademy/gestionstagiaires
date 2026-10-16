"""Authored VTC productions and a 105-hour edition built on the reviewed V10 course.

The bank contains private marking guides. Only ``public_production`` is suitable
for an unsubmitted learner response. Composing the edition changes no historical
course, media, enrolment, or learner record.
"""
from __future__ import annotations

import copy
from functools import lru_cache
import json
from pathlib import Path
import re

VERSION = "20261012-vtc-v12-cma-105h"
BASE_VERSION = "20261010-vtc-v10-lecons-video"
ROOT = Path(__file__).parent / "vtc"
BANK_PATH = ROOT / "productions" / "20261012-vtc-v12.json"
MODULE_MINUTES = dict(zip("ABCDEFGH", (840, 840, 780, 720, 840, 780, 720, 780)))
BASE_MINUTES = dict(zip("ABCDEFGH", (755, 693, 706, 618, 718, 678, 612, 642)))
INDEPENDENT_STUDY_MINUTES = {letter: MODULE_MINUTES[letter] - BASE_MINUTES[letter] for letter in MODULE_MINUTES}
# The authored optional subjects offer one way to use the study allocation.
# Their estimates never impose submissions or grant tracked study time.
PRODUCTION_MINUTES = dict(INDEPENDENT_STUDY_MINUTES)
TOTAL_MINUTES = 6300
NOTICE = (
    "Parcours pédagogique VTC de 105 heures minimum : cours et activités, avec "
    "approfondissements au choix parmi les exercices, missions et révisions. "
    "Les productions personnelles sont facultatives. "
    "L’examen en conditions réelles de 3 h 50 est proposé en complément ; les examens de module "
    "restent des bilans pédagogiques. La préparation écrite ne remplace pas "
    "l'entraînement à la conduite ni l'épreuve pratique en circulation."
)
INDEPENDENT_STUDY_LABEL = "Approfondissement au choix : cours, exercices, missions, révisions ou productions facultatives"
OPTIONAL_NOTE = "Cette production est facultative. Vous pouvez poursuivre le module sans la remettre."
PUBLIC_KEYS = (
    "id", "version", "module", "course_id", "title", "brief", "documents",
    "response_fields", "estimated_minutes", "work_phases", "instructions",
    "sources", "revision_targets", "pass_points", "max_points",
)


def _validate_bank(value):
    if not isinstance(value, dict) or value.get("version") != VERSION:
        raise ValueError("Édition des productions VTC invalide.")
    rows = value.get("productions")
    expected = {f"vtc-{letter.lower()}-production-{n:02}" for letter in "ABCDEFGH" for n in range(1, 5)}
    if (not isinstance(rows, list) or len(rows) != 32
            or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in rows)
            or {row["id"] for row in rows} != expected):
        raise ValueError("Le programme VTC doit contenir 32 productions distinctes.")
    minutes = {letter: 0 for letter in "ABCDEFGH"}
    for row in rows:
        letter = row.get("module")
        if (not isinstance(letter, str) or letter not in minutes
                or not row["id"].startswith(f"vtc-{letter.lower()}-production-")
                or row.get("course_id") != f"academy-vtc-{letter.lower()}"
                or row.get("version") != VERSION or row.get("grading_mode") != "chatgpt"
                or row.get("max_points") != 20 or row.get("pass_points") != 12):
            raise ValueError("Identification ou barème de production VTC invalide.")
        duration = row.get("estimated_minutes")
        phases = row.get("work_phases")
        if (type(duration) is not int or not 10 <= duration <= 90
                or not isinstance(phases, list) or len(phases) < 3
                or any(not isinstance(p, dict) or type(p.get("minutes")) is not int
                       or p["minutes"] <= 0 or not p.get("title") or not p.get("deliverable") for p in phases)
                or sum(p["minutes"] for p in phases) != duration):
            raise ValueError("La durée doit correspondre aux étapes de travail décrites.")
        if row.get("after_section_id") != f"vtc-{letter.lower()}-{int(row['id'][-2:]) * 3:02}":
            raise ValueError("Position de production VTC invalide.")
        fields = row.get("response_fields")
        if (not isinstance(fields, list) or not 2 <= len(fields) <= 6
                or any(not isinstance(f, dict) or not f.get("label") or not f.get("help")
                       or not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", str(f.get("id", "")))
                       or type(f.get("min_chars")) is not int or type(f.get("max_chars")) is not int
                       or not 20 <= f["min_chars"] < f["max_chars"] <= 6000 for f in fields)):
            raise ValueError("Champs de réponse VTC invalides.")
        field_ids = {f["id"] for f in fields}
        if len(field_ids) != len(fields):
            raise ValueError("Champ de production dupliqué.")
        model = row.get("model_response")
        if not isinstance(model, dict) or set(model) != field_ids:
            raise ValueError("Le modèle de correction doit couvrir tous les champs.")
        for field in fields:
            text = model[field["id"]]
            if not isinstance(text, str) or not field["min_chars"] <= len(text) <= field["max_chars"]:
                raise ValueError("Réponse modèle hors du format de réponse attendu.")
        rubric = row.get("rubric")
        if (not isinstance(rubric, list) or not 3 <= len(rubric) <= 8
                or any(not isinstance(c, dict) or not isinstance(c.get("id"), str) for c in rubric)
                or len({c["id"] for c in rubric}) != len(rubric)
                or any(not isinstance(c, dict) or not c.get("label") or not c.get("expected")
                       or not c.get("partial_guidance") or type(c.get("max_points")) is not int
                       or not 1 <= c["max_points"] <= 10
                       or type(c.get("critical", False)) is not bool
                       or not isinstance(c.get("field_ids"), list) or not c["field_ids"]
                       or any(not isinstance(fid, str) for fid in c["field_ids"])
                       or not set(c["field_ids"]).issubset(field_ids) for c in rubric)
                or sum(c["max_points"] for c in rubric) != 20
                or set().union(*(set(c["field_ids"]) for c in rubric)) != field_ids):
            raise ValueError("Le barème VTC doit totaliser 20 points et couvrir les réponses.")
        minutes[letter] += duration
    if minutes != PRODUCTION_MINUTES or sum(minutes.values()) != 878:
        raise ValueError("Les estimations des productions facultatives doivent correspondre aux étapes de travail prévues.")
    return value


@lru_cache(maxsize=1)
def _bank():
    return _validate_bank(json.loads(BANK_PATH.read_text(encoding="utf-8")))


def production_bank():
    """Return the private authored bank to server-side callers only."""
    return copy.deepcopy(_bank())


def get_production(production_id, version=VERSION):
    if version != VERSION:
        return None
    return next((copy.deepcopy(row) for row in _bank()["productions"] if row["id"] == production_id), None)


load_production = get_production


def productions_for_module(course_id, version=VERSION):
    if version != VERSION or not re.fullmatch(r"academy-vtc-[a-h]", str(course_id)):
        return []
    return [copy.deepcopy(row) for row in _bank()["productions"] if row["course_id"] == course_id]


def public_production(production, *, reveal=False):
    """Expose the task and point allocation, withholding all marking answers."""
    result = {key: copy.deepcopy(production[key]) for key in PUBLIC_KEYS if key in production}
    result["optional"] = True
    result["optional_note"] = OPTIONAL_NOTE
    result["rubric_preview"] = [{key: copy.deepcopy(criterion[key]) for key in ("id", "label", "max_points")}
                                for criterion in production["rubric"]]
    if reveal:
        result["feedback"] = {"rubric": copy.deepcopy(production["rubric"]),
                              "model_response": copy.deepcopy(production["model_response"])}
    return result


def compose_course(base):
    """Add four optional assignments after lessons 3/6/9/12 to a repaired V10 copy."""
    if (not isinstance(base, dict) or base.get("version") != BASE_VERSION
            or not re.fullmatch(r"academy-vtc-[a-h]", str(base.get("id", "")))):
        raise ValueError("La nouvelle édition VTC doit dériver du cours V10 vérifié.")
    course = copy.deepcopy(base)
    letter = course["id"][-1].upper()
    if course.get("planned_minutes") != BASE_MINUTES[letter]:
        raise ValueError("La durée du cours VTC source a changé ; réviser le programme avant publication.")
    by_section = {section["id"]: section for section in course["sections"]}
    productions = productions_for_module(course["id"])
    for production in productions:
        target = by_section.get(production["after_section_id"])
        if target is None:
            raise ValueError("Séquence source manquante pour la production VTC.")
        target["activities"].append({
            "id": production["id"], "title": production["title"], "type": "content", "scored": False,
            "optional": True,
            "planned_minutes": production["estimated_minutes"], "blocks": [],
            "vtc": {"kind": "production", "module": letter, "ref": production["id"],
                    "objective": production["brief"]},
            "production": production,
        })
    course["version"] = VERSION
    course["source"] = {**course.get("source", {}), "edition": "cma-productions-105h-v12",
                        "base_course_version": BASE_VERSION, "production_edition_on": "2026-10-12"}
    course["planned_minutes"] = MODULE_MINUTES[letter]
    course["required_minutes"] = MODULE_MINUTES[letter]
    course["programme_minutes"] = TOTAL_MINUTES
    course["independent_study_minutes"] = INDEPENDENT_STUDY_MINUTES[letter]
    course["productions_optional"] = True
    course["duration_note"] = _bank()["duration_note"]
    for section in course["sections"]:
        for activity in section["activities"]:
            if activity.get("vtc", {}).get("kind") == "supplements":
                activity["vtc"]["notice"] = NOTICE
    course["activity_order"] = [activity["id"] for section in course["sections"] for activity in section["activities"]]
    course["counts"] = {**course["counts"], "activities": len(course["activity_order"]),
                        "productions": len(productions), "optional_productions": len(productions),
                        "production_minutes": PRODUCTION_MINUTES[letter]}
    course["duration_breakdown"] = [*course["duration_breakdown"],
                                     {"label": INDEPENDENT_STUDY_LABEL,
                                      "minutes": INDEPENDENT_STUDY_MINUTES[letter]}]
    actual = sum(activity.get("planned_minutes", 0) for section in course["sections"] for activity in section["activities"])
    if actual != course["planned_minutes"] or len(set(course["activity_order"])) != len(course["activity_order"]):
        raise ValueError("Le programme VTC composé est incohérent.")
    return course
