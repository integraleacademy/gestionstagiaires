"""Authored APS v10 assessment changes; never edits historical course files.

The text tables contain correct answer first, then two plausible distractors.
Runtime display order is independently shuffled. Existing exercise and option IDs
are deliberately retained so content fixes, progress and grading remain compatible.
"""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import random

REVISION = "20261010-aps62-v10"
DATA_DIR = Path(__file__).resolve().parent


def _rows(name, width):
    rows = []
    for line_no, line in enumerate((DATA_DIR / name).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        row = [value.strip() for value in line.split("|")]
        if len(row) != width or any(not value for value in row):
            raise ValueError(f"{name}:{line_no}: expected {width} nonempty fields")
        rows.append(row)
    return rows


def _indexed(name, width):
    rows = _rows(name, width)
    result = {row[0]: row[1:] for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"Duplicate editorial key in {name}")
    return result


def _replace_options(question, texts):
    options = question["options"]
    correct = [option for option in options if str(option["id"]) == str(question["answer"])]
    if len(options) != 3 or len(correct) != 1 or len(set(texts)) != 3:
        raise ValueError(f"Invalid option structure: {question['id']}")
    correct[0]["text"] = texts[0]
    for option, text in zip((o for o in options if o is not correct[0]), texts[1:]):
        option["text"] = text


def apply_course(course):
    """Return a copy with 184 transfer/document/journal choices rewritten in all modules."""
    result = deepcopy(course)
    edits = _indexed("practice_choices.txt", 4)
    prefix = result["id"].removeprefix("academy-aps62-") + "-"
    expected = {key for key in edits if key.startswith(prefix)}
    applied = set()
    for section in result.get("sections", []):
        for activity in section.get("activities", []):
            for exercise in activity.get("practice", {}).get("exercises", []):
                key = activity["id"].removeprefix("aps62-") + ":" + exercise["id"]
                if key in edits:
                    if exercise.get("kind") != "single":
                        raise ValueError(f"Expected a single-choice exercise: {key}")
                    _replace_options(exercise, edits[key])
                    applied.add(key)
    if applied != expected:
        raise ValueError(f"Practice edits not applied: {sorted(expected - applied)}")
    result["assessment_revision"] = REVISION
    return result


def apply_exam(exam):
    """Return a copy: preserve the 450-item training bank, author an independent final."""
    result = deepcopy(exam)
    if result["id"] == "final":
        rows = _rows("final_cases.txt", 7)
        counts = Counter(row[0] for row in rows)
        expected = {f"{i:02d}": 7 if i <= 10 else 6 for i in range(1, 16)}
        if counts != expected or len({(r[0], r[1]) for r in rows}) != 100:
            raise ValueError("The final must contain 100 unique competencies/cases across 15 modules")
        exemplars = {q["module"][:2]: q for q in result["questions"]}
        if set(exemplars) != set(expected):
            raise ValueError("Missing module sources for final assessment")
        questions = []
        answer_positions = [i % 3 for i in range(len(rows))]
        random.Random(REVISION + ":" + result["id"]).shuffle(answer_positions)
        for index, (module, competency, prompt, correct, wrong1, wrong2, explanation) in enumerate(rows):
            answer_index = answer_positions[index]
            texts = [wrong1, wrong2]
            texts.insert(answer_index, correct)
            exemplar = exemplars[module]
            questions.append({
                "id": f"aps62-final-v10-{module}-{competency}",
                "prompt": prompt,
                "options": [{"id": str(i + 1), "text": text} for i, text in enumerate(texts)],
                "answer": str(answer_index + 1),
                "explanation": explanation,
                "module": exemplar["module"],
                "sources": deepcopy(exemplar.get("sources", [])),
                "competency": competency,
                "assessment_origin": "independent-final-v10",
            })
        result["questions"] = questions
    else:
        edits = _indexed("bank_cases.txt", 5)
        for question in result["questions"]:
            if question["id"] in edits:
                prompt, *texts = edits[question["id"]]
                question["prompt"] = prompt
                _replace_options(question, texts)
    result["assessment_revision"] = REVISION
    result["reviewed_on"] = "2026-10-10"
    return result
