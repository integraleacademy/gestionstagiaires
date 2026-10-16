"""Assessment wording for APS v9, applied only while building the new edition.

The reviewed tables keep the assessed competence and the existing correct option
ID. Display positions change without changing answer keys or historical files.
The final exam reuses the module-bank wording by question ID.
"""

from copy import deepcopy
import hashlib
from pathlib import Path
import random


REVISION = "20261007-aps62-v9"
DATA_DIR = Path(__file__).resolve().parent


def _balanced_positions(count, identity):
    # Stable at edition build time: neither a repeating A/B/C pattern nor a
    # request-time shuffle that would move choices while a learner answers.
    positions = [index % 3 for index in range(count)]
    seed = hashlib.sha256(f"{REVISION}:{identity}".encode("utf-8")).digest()
    random.Random(int.from_bytes(seed, "big")).shuffle(positions)
    return positions


def _load_rows(pattern, width):
    rows = {}
    for path in sorted(DATA_DIR.glob(pattern)):
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            fields = [field.strip() for field in raw.split("|")]
            if len(fields) != width or any(not field for field in fields):
                raise ValueError(f"Invalid editorial row: {path.name}:{number}")
            question_id, *content = fields
            if question_id in rows:
                raise ValueError(f"Duplicate editorial question: {question_id}")
            if len(set(content[:3])) != 3:
                raise ValueError(f"Duplicate answer wording: {question_id}")
            rows[question_id] = tuple(content)
    if not rows:
        raise ValueError(f"No assessment data matching {pattern}")
    return rows


def _rewrite_options(question, wording, correct_id, position):
    options = question["options"]
    if len(options) != 3 or len({option["id"] for option in options}) != 3:
        raise ValueError(f"Expected three distinct options: {question['id']}")
    correct = [option for option in options if option["id"] == correct_id]
    if len(correct) != 1:
        raise ValueError(f"Missing correct option: {question['id']}")
    correct = correct[0]
    wrong = sorted(
        (option for option in options if option["id"] != correct_id),
        key=lambda option: option["id"],
    )
    correct["text"] = wording[0]
    for option, text in zip(wrong, wording[1:3]):
        option["text"] = text
    wrong.insert(position, correct)
    question["options"] = wrong


def apply_questions(course):
    """Return a copy of an APS course with reviewed scenario questions.

    All question/option identifiers, scoring flags, media, timings and guided
    activities remain intact. Correct answers are balanced over all 62 dossiers.
    """
    result = deepcopy(course)
    rows = _load_rows("course_questions.tsv", 5)
    positions = dict(zip(sorted(rows), _balanced_positions(len(rows), "courses")))
    for section in result["sections"]:
        for activity in section["activities"]:
            if activity.get("question_type") != "single_choice":
                continue
            question_id = activity["id"]
            if question_id not in rows:
                raise ValueError(f"Unreviewed course question: {question_id}")
            wording = rows[question_id]
            correct = [option for option in activity["options"] if option.get("is_correct")]
            if len(correct) != 1:
                raise ValueError(f"Expected one correct answer: {question_id}")
            _rewrite_options(activity, wording, correct[0]["id"], positions[question_id])
            question_sentence = "Quelle conduite retenir dans cette situation ?"
            if not activity["prompt"].rstrip().endswith(question_sentence):
                activity["prompt"] = activity["prompt"].rstrip() + "\n\n" + question_sentence
            original_explanation = activity.get("explanation", "").strip()
            if not original_explanation.startswith(wording[3]):
                activity["explanation"] = wording[3] + (
                    "\n\n" + original_explanation if original_explanation else ""
                )
    result["assessment_revision"] = REVISION
    return result


def apply_exam(exam):
    """Return a reviewed copy, preserving IDs, answer keys, sources and scoring.

    The correct option occupies each display position equally in a 30-question
    module, and 34/33/33 positions in the 100-question final. The same item keeps
    the same wording when reused in another exam; only display order can differ.
    """
    result = deepcopy(exam)
    rows = _load_rows("exam_questions*.tsv", 4)
    positions = _balanced_positions(len(result["questions"]), result["id"])
    for index, question in enumerate(result["questions"]):
        question_id = question["id"]
        if question_id not in rows:
            raise ValueError(f"Unreviewed exam question: {question_id}")
        _rewrite_options(question, rows[question_id], question["answer"], positions[index])
    result["assessment_revision"] = REVISION
    return result
