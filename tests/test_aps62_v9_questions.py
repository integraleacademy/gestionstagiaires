"""Editorial and historical-integrity checks for the APS v9 assessments."""

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts.aps62_v9.questions import (
    REVISION,
    _load_rows,
    apply_exam,
    apply_questions,
)


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "elearning_native" / "aps62"
PREVIOUS = "20261007-aps62-v8"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def course_questions(course):
    return [
        activity
        for section in course["sections"]
        for activity in section["activities"]
        if activity.get("question_type") == "single_choice"
    ]


def option_structure(options):
    return sorted(
        ({key: value for key, value in option.items() if key != "text"} for option in options),
        key=lambda option: option["id"],
    )


class APS62V9QuestionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.courses = [read(path) for path in sorted(BASE.glob(f"courses/*/{PREVIOUS}.json"))]
        cls.exams = [read(BASE / "exams" / PREVIOUS / f"module-{number:02d}.json") for number in range(1, 16)]
        cls.final = read(BASE / "exams" / PREVIOUS / "final.json")
        cls.course_rows = _load_rows("course_questions.tsv", 5)
        cls.exam_rows = _load_rows("exam_questions*.tsv", 4)

    def test_editorial_coverage_is_exact(self):
        self.assertEqual(len(self.courses), 15)
        course_ids = {question["id"] for course in self.courses for question in course_questions(course)}
        exam_ids = {question["id"] for exam in self.exams for question in exam["questions"]}
        final_ids = {question["id"] for question in self.final["questions"]}
        self.assertEqual(len(course_ids), 62)
        self.assertEqual(len(exam_ids), 450)
        self.assertEqual(len(final_ids), 100)
        self.assertEqual(set(self.course_rows), course_ids)
        self.assertEqual(set(self.exam_rows), exam_ids)
        self.assertLessEqual(final_ids, exam_ids)

    def test_course_history_and_non_question_content_are_untouched(self):
        total_minutes = 0
        for original in self.courses:
            with self.subTest(course=original["id"]):
                snapshot = deepcopy(original)
                updated = apply_questions(original)
                self.assertEqual(original, snapshot)
                self.assertEqual(updated["assessment_revision"], REVISION)
                self.assertEqual(apply_questions(updated), updated)
                total_minutes += updated["planned_minutes"]
                restored = deepcopy(updated)
                restored.pop("assessment_revision")
                old_questions = {question["id"]: question for question in course_questions(original)}
                for question in course_questions(restored):
                    old = old_questions[question["id"]]
                    self.assertEqual(option_structure(question["options"]), option_structure(old["options"]))
                    self.assertTrue(question["prompt"].startswith(old["prompt"].rstrip()))
                    self.assertTrue(question["prompt"].endswith("Quelle conduite retenir dans cette situation ?"))
                    self.assertTrue(question["explanation"].endswith(old["explanation"].strip()))
                    self.assertIn(self.course_rows[question["id"]][3], question["explanation"])
                    for key in ("prompt", "explanation", "options"):
                        question[key] = deepcopy(old[key])
                self.assertEqual(restored, original)
        self.assertEqual(total_minutes, 3720)

    def test_exam_answer_keys_sources_and_competencies_are_preserved(self):
        for original in [*self.exams, self.final]:
            with self.subTest(exam=original["id"]):
                snapshot = deepcopy(original)
                updated = apply_exam(original)
                self.assertEqual(original, snapshot)
                self.assertEqual(apply_exam(updated), updated)
                restored = deepcopy(updated)
                self.assertEqual(restored.pop("assessment_revision"), REVISION)
                for old, question in zip(original["questions"], restored["questions"]):
                    self.assertEqual(option_structure(question["options"]), option_structure(old["options"]))
                    self.assertEqual(question["answer"], old["answer"])
                    by_id = {option["id"]: option["text"] for option in question["options"]}
                    self.assertEqual(by_id[question["answer"]], self.exam_rows[question["id"]][0])
                    question["options"] = deepcopy(old["options"])
                self.assertEqual(restored, original)

    def test_balanced_positions_are_stable_without_an_abc_cycle(self):
        course_positions = [
            next(index for index, option in enumerate(question["options"]) if option["is_correct"])
            for course in self.courses
            for question in course_questions(apply_questions(course))
        ]
        self.assertEqual(Counter(course_positions), Counter({0: 21, 1: 21, 2: 20}))
        self.assertNotEqual(course_positions, [index % 3 for index in range(62)])
        for original in [*self.exams, self.final]:
            positions = [
                next(index for index, option in enumerate(question["options"]) if option["id"] == question["answer"])
                for question in apply_exam(original)["questions"]
            ]
            expected = Counter({0: 34, 1: 33, 2: 33}) if len(positions) == 100 else Counter({0: 10, 1: 10, 2: 10})
            self.assertEqual(Counter(positions), expected)
            self.assertNotEqual(positions, [index % 3 for index in range(len(positions))])

    def test_final_reuses_exactly_the_reviewed_module_wording(self):
        module_wording = {
            question["id"]: {option["id"]: option["text"] for option in question["options"]}
            for exam in self.exams
            for question in apply_exam(exam)["questions"]
        }
        for question in apply_exam(self.final)["questions"]:
            self.assertEqual(
                {option["id"]: option["text"] for option in question["options"]},
                module_wording[question["id"]],
            )

    def test_comparable_choice_lengths_remove_the_dominant_length_hint(self):
        # This is a regression guard against the former 58/62 longest-answer
        # shortcut, not a substitute for reviewing the meaning of each choice.
        for kind, rows in (("course", self.course_rows), ("exam", self.exam_rows)):
            longest = shortest = 0
            for question_id, wording in rows.items():
                with self.subTest(kind=kind, question=question_id):
                    lengths = [len(text) for text in wording[:3]]
                    self.assertLessEqual(max(lengths) / min(lengths), 1.8)
                    longest += lengths[0] > max(lengths[1:])
                    shortest += lengths[0] < min(lengths[1:])
                    self.assertEqual(len(set(wording[:3])), 3)
            self.assertLessEqual(longest / len(rows), 0.50)
            self.assertLessEqual(shortest / len(rows), 0.50)

    def test_unknown_questions_fail_instead_of_silently_using_unreviewed_text(self):
        exam = deepcopy(self.exams[0])
        exam["questions"][0]["id"] = "aps62-q-unknown"
        with self.assertRaisesRegex(ValueError, "Unreviewed exam question"):
            apply_exam(exam)
        course = deepcopy(self.courses[0])
        course_questions(course)[0]["id"] = "aps62-unknown-q1"
        with self.assertRaisesRegex(ValueError, "Unreviewed course question"):
            apply_questions(course)


if __name__ == "__main__":
    unittest.main()
