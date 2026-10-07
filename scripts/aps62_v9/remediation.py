"""Apply the explicitly authored APS v9 practice bank to a fresh course dict.

The function mutates and returns that dict. It never opens or rewrites a course
file. Missing/extra exercises and incomplete banks fail before any mutation.
Cases and distractors are editorial source, not variants assembled from a type.
"""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REVISION = "20261007-aps62-v9"
MAIN_IDS = ("constat", "decision", "evolution")
TRANSFER_IDS = ("variante", "application")
EXTRA_COUNTS = {
    "01-04-etude": 4, "02-03-etude": 4, "03-02-etude": 4,
    "04-01-etude": 4, "05-03-etude": 4, "06-04-etude": 4,
    "07-05-etude": 4, "08-01-etude": 4, "08-03-journal": 5,
    "08-05-journal": 5, "09-03-etude": 4, "10-07-etude": 4,
    "11-02-etude": 4, "12-07-etude": 4, "13-01-journal": 4,
    "13-02-journal": 4, "14-07-etude": 4, "15-07-etude": 4,
}
SECTION_COUNTS = (4, 3, 2, 1, 3, 4, 5, 5, 3, 7, 2, 7, 2, 7, 7)
SECTIONS = tuple(f"{module:02d}-{section:02d}"
                 for module, count in enumerate(SECTION_COUNTS, 1)
                 for section in range(1, count + 1))

# Hints are methods, not the answer or the explanation to the new case.
METHODS = {
    1: "Repérez la mission confiée, le document présenté et ce que ce document permet réellement.",
    2: "Distinguez les faits, leur moment et la question de responsabilité ou de protection à examiner.",
    3: "Distinguez une observation, un indice et une conclusion ; vérifiez le cadre du relais.",
    4: "Examinez séparément le besoin, les droits d'accès et le canal de transmission.",
    5: "Comparez les faits et les critères appliqués aux personnes, puis le champ de la règle.",
    6: "Repérez ce qui change dans la demande et ses effets sur l'intégrité ou la traçabilité.",
    7: "Relevez le déclencheur, la prochaine étape vérifiable et les conditions de sécurité de l'échange.",
    8: "Lisez les sources, les heures, le statut des démarches et l'action précise à transmettre.",
    9: "Replacez chaque information au moment où elle est connue avant de justifier une décision.",
    10: "Identifiez le danger, les personnes exposées et les conditions réelles de la protection proposée.",
    11: "Repérez ce qui établit la sécurité de l'environnement et ce qui relève de la mission du poste.",
    12: "Comparez faits observés, informations rapportées et consignes dont l'origine est connue.",
    13: "Vérifiez la référence, l'auteur, les heures, la source et le statut de chaque document.",
    14: "Séparez ce qui est observé, ce qui est rapporté et ce qui reste à vérifier pour le relais.",
    15: "Reliez chaque demande à sa zone, son créneau, son rôle et au circuit de coordination prévu.",
}


def _read_groups(filename: str, columns: int) -> dict[str, list[list[str]]]:
    result: dict[str, list[list[str]]] = {}
    key = None
    for line_number, raw in enumerate((ROOT / filename).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            key = line[1:]
            if not key or key in result:
                raise ValueError(f"{filename}:{line_number}: duplicate/empty group {key!r}")
            result[key] = []
            continue
        fields = [part.strip() for part in line.split("|")]
        if key is None or len(fields) != columns or not all(fields):
            raise ValueError(f"{filename}:{line_number}: expected {columns} nonempty fields")
        result[key].append(fields)
    return result


def _exercise_ids(group: str) -> tuple[str, ...]:
    if group in SECTIONS:
        return MAIN_IDS + TRANSFER_IDS
    count = EXTRA_COUNTS[group]
    return tuple(f"choix-{i}" for i in range(1, count + 1)) if group.endswith("journal") else (
        "choix-1", "choix-2", "choix-3", "classement"
    )


def _bank_key(group: str, index: int) -> str:
    if group in SECTIONS:
        activity = group + ("-atelier" if index < 3 else "-transfert")
    else:
        activity = group
    return f"aps62-{activity}/{_exercise_ids(group)[index]}"


def _balanced_positions(keys: list[str], salt: str) -> dict[str, int]:
    # Hash-ranked assignment gives exactly balanced totals without an ABC cycle
    # in teaching order. The same key is stable across rebuilds and course calls.
    order = sorted(keys, key=lambda key: sha256(f"{salt}:{key}".encode()).digest())
    return {key: index % 3 for index, key in enumerate(order)}


@lru_cache(maxsize=1)
def _banks():
    bank = _read_groups("remediation_bank.txt", 5)
    distractors = _read_groups("workshop_distractors.txt", 2)
    answers = _read_groups("workshop_answers.txt", 1)
    expected = set(SECTIONS) | set(EXTRA_COUNTS)
    if set(bank) != expected or set(distractors) != set(SECTIONS) or set(answers) != set(SECTIONS):
        raise ValueError("Incomplete or unexpected APS v9 editorial groups")
    seen_prompts = set()
    rows_by_key = {}
    for group, rows in bank.items():
        if len(rows) != (5 if group in SECTIONS else EXTRA_COUNTS[group]):
            raise ValueError(f"Wrong number of remediation cases in {group}")
        for index, fields in enumerate(rows):
            prompt, correct, wrong1, wrong2, explanation = fields
            if prompt in seen_prompts or len({correct, wrong1, wrong2}) != 3:
                raise ValueError(f"Repeated case or duplicate choices in {group}/{index}")
            seen_prompts.add(prompt)
            rows_by_key[_bank_key(group, index)] = fields
    for section in SECTIONS:
        if len(distractors[section]) != 3 or len(answers[section]) != 2:
            raise ValueError(f"Incomplete main workshop choices: {section}")
    if len(rows_by_key) != 384:
        raise ValueError("APS v9 requires exactly 384 individually authored remediation cases")
    main_keys = [f"aps62-{section}-atelier/{exercise}" for section in SECTIONS for exercise in MAIN_IDS]
    return bank, distractors, answers, rows_by_key, _balanced_positions(list(rows_by_key), "remediation-v9"), _balanced_positions(main_keys, "workshop-v9")


def apply_remediation(course: dict) -> dict:
    """Mutate and return one v8/v9 APS course; reject uncovered practice first."""
    _, distractors, answers, rows, drill_positions, main_positions = _banks()
    course_id = course.get("id", "")
    if not course_id.startswith("academy-aps62-"):
        raise ValueError(f"Not an APS62 course: {course_id!r}")
    module = int(course_id.rsplit("-", 1)[1])
    if not 1 <= module <= len(SECTION_COUNTS):
        raise ValueError(f"Unknown APS62 module: {module}")
    prefix = f"aps62-{module:02d}-"
    expected_keys = {key for key in rows if key.startswith(prefix)}
    actual_keys = set()
    planned = []
    for section in course.get("sections", []):
        for activity in section.get("activities", []):
            practice = activity.get("practice")
            if not practice:
                continue
            activity_id = activity.get("id", "")
            section_key = section["id"].removeprefix("aps62-")
            exercises = practice.get("exercises", [])
            if activity_id.endswith("-atelier"):
                expected_ids = MAIN_IDS
            elif activity_id.endswith("-transfert"):
                expected_ids = TRANSFER_IDS
            else:
                extra = activity_id.removeprefix("aps62-")
                if extra not in EXTRA_COUNTS:
                    raise ValueError(f"Uncovered practice activity {activity_id}")
                expected_ids = _exercise_ids(extra)
            if tuple(e.get("id") for e in exercises) != expected_ids:
                raise ValueError(f"Exercise IDs/order differ from authored bank: {activity_id}")
            for index, exercise in enumerate(exercises):
                key = f"{activity_id}/{exercise['id']}"
                if key not in rows or key in actual_keys:
                    raise ValueError(f"Uncovered or duplicated practice exercise {key}")
                actual_keys.add(key)
                main = activity_id.endswith("-atelier")
                if main:
                    options = exercise.get("options", [])
                    if len(options) not in (2, 3) or len({o["id"] for o in options}) != len(options):
                        raise ValueError(f"Unexpected main choices {key}")
                    if len([o for o in options if o["id"] == exercise.get("answer")]) != 1:
                        raise ValueError(f"Invalid answer in {key}")
                planned.append((practice, exercise, key, section_key, index, main))
    if actual_keys != expected_keys:
        raise ValueError(f"Incomplete module practices: missing={sorted(expected_keys - actual_keys)}, extra={sorted(actual_keys - expected_keys)}")

    # All coverage checks above are transactional: a rejected course is unchanged.
    for practice, exercise, key, section_key, index, main in planned:
        prompt, correct, wrong1, wrong2, explanation = rows[key]
        choices = [wrong1, wrong2]
        if sha256((key + ":wrong-order").encode()).digest()[0] % 2:
            choices.reverse()
        position = drill_positions[key]
        choices.insert(position, correct)
        exercise["remediation"] = {
            "prompt": prompt,
            "options": [{"id": str(i + 1), "text": value} for i, value in enumerate(choices)],
            "answer": str(position + 1),
            "explanation": explanation,
            "lesson": METHODS[module],
        }
        if main:
            existing = exercise["options"]
            answer_id = exercise["answer"]
            answer_option = next(o.copy() for o in existing if o["id"] == answer_id)
            if index > 0:
                answer_option["text"] = answers[section_key][index - 1][0]
            old_wrong_ids = [o["id"] for o in existing if o["id"] != answer_id]
            if len(old_wrong_ids) == 1:
                old_wrong_ids.append("v9-alternative")
            wrong_texts = distractors[section_key][index]
            other_options = [{"id": oid, "text": value} for oid, value in zip(old_wrong_ids, wrong_texts)]
            other_options.insert(main_positions[key], answer_option)
            exercise["options"] = other_options
        practice["revision"] = REVISION
        # Preserve all stage/context/documents/journal fields and all exercise IDs.
    course["remediation_revision"] = REVISION
    return course
