"""Editorial regression guards; these do not substitute for semantic review."""
import json
import re
import unittest
import unicodedata
from collections import Counter
from copy import deepcopy
from pathlib import Path

from scripts.aps62_v10.assessment import _rows, apply_course, apply_exam

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "20261007-aps62-v9"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalized(text):
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def exercises(course):
    return {a["id"] + ":" + e["id"]: e for s in course["sections"] for a in s["activities"]
            for e in a.get("practice", {}).get("exercises", [])}


class AssessmentV10Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.courses = [read(p) for p in sorted((ROOT / "elearning_native/aps62/courses").glob(f"*/{SOURCE}.json"))]
        cls.bank = [read(p) for p in sorted((ROOT / f"elearning_native/aps62/exams/{SOURCE}").glob("module-*.json"))]
        cls.old_final = read(ROOT / f"elearning_native/aps62/exams/{SOURCE}/final.json")
        cls.final = apply_exam(cls.old_final)

    def test_all_184_targeted_choices_are_changed_without_changing_grading_or_training(self):
        declared = {"aps62-" + row[0] for row in _rows("practice_choices.txt", 4)}
        expected = {key for c in self.courses for key, e in exercises(c).items()
                    if e.get("kind") == "single" and any(marker in key for marker in ("-transfert:", "-etude:", "-journal:"))}
        self.assertEqual(len(expected), 184)
        self.assertEqual(declared, expected)
        changed = set()
        for source in self.courses:
            frozen = deepcopy(source)
            result = apply_course(source)
            self.assertEqual(source, frozen)
            self.assertEqual(source["settings"], result["settings"])
            before, after = exercises(source), exercises(result)
            self.assertEqual(before.keys(), after.keys())
            for key, original in before.items():
                revised = after[key]
                if key in expected:
                    self.assertNotEqual(original["options"], revised["options"], key)
                    changed.add(key)
                    stripped_before, stripped_after = deepcopy(original), deepcopy(revised)
                    for item in (stripped_before, stripped_after):
                        for option in item["options"]:
                            del option["text"]
                    self.assertEqual(stripped_before, stripped_after, key)
                else:
                    self.assertEqual(original, revised, key)
        self.assertEqual(changed, expected)

    def test_83_binary_cues_removed_with_bank_keys_and_explanations_preserved(self):
        expected = {q["id"] for e in self.bank for q in e["questions"]
                    if all(o["text"].startswith(("Oui", "Non")) for o in q["options"])}
        self.assertEqual(len(expected), 83)
        self.assertEqual(expected, {row[0] for row in _rows("bank_cases.txt", 5)})
        self.assertEqual(sum(len(e["questions"]) for e in self.bank), 450)
        for source in self.bank:
            result = apply_exam(source)
            self.assertEqual(source["pass_percent"], result["pass_percent"])
            for old, new in zip(source["questions"], result["questions"]):
                if old["id"] not in expected:
                    self.assertEqual(old, new)
                    continue
                self.assertEqual(old["answer"], new["answer"])
                self.assertEqual(old["explanation"], new["explanation"])
                self.assertEqual(old["sources"], new["sources"])
                self.assertFalse(any(re.match(r"^(oui|non)\b", o["text"], re.I) for o in new["options"]))

    def test_final_is_independent_of_bank_and_covers_all_modules(self):
        questions = self.final["questions"]
        bank = [q for e in self.bank for q in apply_exam(e)["questions"]]
        self.assertEqual(len(questions), 100)
        self.assertEqual(len({q["id"] for q in questions}), 100)
        self.assertFalse({q["id"] for q in questions} & {q["id"] for q in bank})
        self.assertFalse({normalized(q["prompt"]) for q in questions} & {normalized(q["prompt"]) for q in bank})
        self.assertEqual(len({normalized(q["prompt"]) for q in questions}), 100)
        bank_options = {normalized(o["text"]) for q in bank for o in q["options"]}
        self.assertFalse(bank_options & {normalized(o["text"]) for q in questions for o in q["options"]})
        self.assertEqual(Counter(q["module"][:2] for q in questions),
                         {f"{i:02d}": 7 if i <= 10 else 6 for i in range(1, 16)})
        self.assertEqual(self.final["pass_percent"], self.old_final["pass_percent"])
        self.assertEqual(self.final["pass_percent"], 75)

    def test_final_has_valid_keys_sources_specific_feedback_and_balanced_positions(self):
        counts = Counter(q["answer"] for q in self.final["questions"])
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
        answers = [q["answer"] for q in self.final["questions"]]
        for period in (1, 2, 3):
            self.assertFalse(all(answers[i] == answers[i % period] for i in range(len(answers))))
        explanations = set()
        for q in self.final["questions"]:
            with self.subTest(question=q["id"]):
                self.assertEqual(len(q["options"]), 3)
                self.assertEqual(sum(o["id"] == q["answer"] for o in q["options"]), 1)
                self.assertEqual(len({normalized(o["text"]) for o in q["options"]}), 3)
                self.assertTrue(q["sources"])
                self.assertIn("?", q["prompt"])
                correct = next(o["text"] for o in q["options"] if o["id"] == q["answer"])
                self.assertNotEqual(normalized(q["explanation"]), normalized(correct))
                self.assertNotRegex(q["explanation"], r"(?i)(première|deuxième|troisième) (réponse|conduite|option)")
                explanations.add(q["explanation"])
        self.assertEqual(len(explanations), 100)

    def test_longest_or_shortest_option_cannot_be_a_majority_solver(self):
        for filename, width, offset in (("practice_choices.txt", 4, 1), ("bank_cases.txt", 5, 2), ("final_cases.txt", 7, 3)):
            rows = _rows(filename, width)
            longest = shortest = 0
            for row in rows:
                options = row[offset:offset + 3]
                counts = [len(re.findall(r"\w+", text)) for text in options]
                self.assertLessEqual(max(counts) / min(counts), 1.8, (filename, row[0]))
                longest += counts[0] > max(counts[1:])
                shortest += counts[0] < min(counts[1:])
            self.assertLess(longest / len(rows), .5, filename)
            self.assertLess(shortest / len(rows), .5, filename)

    def test_server_grades_new_final_ids_and_preserves_75_percent_threshold(self):
        from elearning_native.exams import grade_exam, public_exam
        questions = self.final["questions"]
        for correct_count, passed in ((75, True), (74, False), (100, True)):
            answers = {q["id"]: q["answer"] if i < correct_count else next(o["id"] for o in q["options"] if o["id"] != q["answer"])
                       for i, q in enumerate(questions)}
            result = grade_exam(self.final, answers)
            self.assertEqual(result["score"], correct_count)
            self.assertEqual(result["passed"], passed)
        for question in public_exam(self.final)["questions"]:
            self.assertEqual(set(question), {"id", "prompt", "options"})

    def test_transforms_do_not_mutate_input_or_change_on_reapplication(self):
        for original, transform in [(c, apply_course) for c in self.courses] + [(e, apply_exam) for e in self.bank + [self.old_final]]:
            frozen = deepcopy(original)
            result = transform(original)
            self.assertEqual(original, frozen)
            self.assertEqual(transform(result), result)


if __name__ == "__main__":
    unittest.main()
