"""Publication gates for authored v12 content and immutable v11 learner editions.

These checks validate complete banks through the application's actual loaders and
markers, plus rendered lesson coverage. Editorial review remains a human task.
"""
import hashlib
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

from jinja2 import Environment, FileSystemLoader, select_autoescape

from elearning_native.academy import ROOT, bundled_asset, curriculum_manifest, load_bundled_course
from elearning_native.exams import grade_exam, load_exam
from elearning_native.practice import grade_practice

VERSION = "20261012-aps62-v12"
PREVIOUS = "20261010-aps62-v11"
V11_SHA256 = "d79c85a5422bb1a8ceccfd97c8562e4a9324b4c9d041ade0bd38bf6e25072a21"
REPOSITORY = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def activities(course):
    return [activity for section in course["sections"] for activity in section["activities"]]


def normalized(text):
    return re.sub(r"\W+", " ", text.casefold()).strip()


class APSV12ContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = curriculum_manifest()
        # Authored snapshots stay immutable; delivery rules are checked separately
        # by test_aps62_without_productions, including older assigned editions.
        cls.courses = [read(ROOT / "courses" / f"academy-aps62-{number:02}" / (VERSION + ".json")) for number in range(1, 16)]
        cls.exams = [load_exam(f"module-{number:02}", VERSION) for number in range(1, 16)] + [load_exam("final", VERSION)]

    def assert_distinct_options(self, options):
        self.assertEqual(len(options), len({option["id"] for option in options}))
        self.assertEqual(len(options), len({normalized(option["text"]) for option in options}))
        self.assertTrue(all(option["text"].strip() for option in options))

    def test_previous_edition_is_immutable_and_still_loadable(self):
        paths = sorted((ROOT / "courses").glob("*/" + PREVIOUS + ".json")) + sorted((ROOT / "exams" / PREVIOUS).glob("*.json"))
        self.assertEqual(len(paths), 31)
        digest = hashlib.sha256()
        for path in paths:
            digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
        self.assertEqual(digest.hexdigest(), V11_SHA256)
        for current in self.courses:
            old = load_bundled_course(current["id"], PREVIOUS)
            original = read(ROOT / "courses" / current["id"] / (PREVIOUS + ".json"))
            self.assertEqual(old["version"], original["version"])
            self.assertEqual(old["required_minutes"], original["required_minutes"])
            self.assertEqual(old["activity_order"], [a["id"] for a in activities(original) if not a.get("production")])
        self.assertEqual(load_exam("module-01", PREVIOUS)["questions"][2]["prompt"], "Que vérifie-t-on avant de prendre un poste ?")

    def test_new_edition_preserves_ids_order_and_time_budgets(self):
        self.assertEqual(self.manifest["version"], VERSION)
        self.assertIn(PREVIOUS, self.manifest["exam_versions"])
        self.assertIn(VERSION, self.manifest["exam_versions"])
        sections = total_activities = minutes = 0
        for course in self.courses:
            old = read(ROOT / "courses" / course["id"] / (PREVIOUS + ".json"))
            self.assertEqual(course["version"], VERSION)
            self.assertEqual(course["activity_order"], old["activity_order"])
            self.assertEqual([s["id"] for s in course["sections"]], [s["id"] for s in old["sections"]])
            self.assertEqual([a["id"] for a in activities(course)], [a["id"] for a in activities(old)])
            self.assertEqual(course["planned_minutes"], old["planned_minutes"])
            self.assertEqual(course["required_minutes"], old["required_minutes"])
            self.assertTrue(course["settings"]["require_correct_answers"])
            for section, previous_section in zip(course["sections"], old["sections"]):
                durations = [a["planned_minutes"] for a in section["activities"]]
                self.assertEqual(durations, [a["planned_minutes"] for a in previous_section["activities"]])
                self.assertEqual(sum(durations), section["planned_minutes"])
                sections += 1
                total_activities += len(durations)
                minutes += sum(durations)
        self.assertEqual((sections, total_activities, minutes), (62, 452, 3720))
        self.assertEqual(self.courses[11]["planned_minutes"], 420)

    def test_every_course_question_has_one_unambiguous_structural_key(self):
        questions = [a for c in self.courses for a in activities(c) if a.get("type") == "question"]
        self.assertEqual(len(questions), 124)
        for q in questions:
            with self.subTest(question=q["id"]):
                self.assertTrue(q["prompt"].strip())
                self.assertTrue(q["explanation"].strip())
                if q["question_type"] == "single_choice":
                    self.assert_distinct_options(q["options"])
                    self.assertEqual(sum(bool(o.get("is_correct")) for o in q["options"]), 1)
                else:
                    self.assertEqual(q["question_type"], "matching")
                    self.assertEqual(len(q["pairs"]), 3)
                    for side in ("id", "left", "right"):
                        self.assertEqual(len({pair[side] for pair in q["pairs"]}), 3)

    def test_all_550_exam_items_load_and_grade_with_preserved_answer_ids(self):
        self.assertEqual([len(e["questions"]) for e in self.exams], [30] * 15 + [100])
        module_prompts = set()
        for exam in self.exams:
            previous = load_exam(exam["id"], PREVIOUS)
            self.assertEqual([(q["id"], q["answer"]) for q in exam["questions"]], [(q["id"], q["answer"]) for q in previous["questions"]])
            prompts = set()
            for question in exam["questions"]:
                with self.subTest(exam=exam["id"], question=question["id"]):
                    self.assert_distinct_options(question["options"])
                    self.assertIn(question["answer"], {o["id"] for o in question["options"]})
                    self.assertTrue(question["explanation"].strip())
                    self.assertTrue(question["sources"])
                    self.assertNotIn(normalized(question["prompt"]), prompts)
                    prompts.add(normalized(question["prompt"]))
            answers = {q["id"]: q["answer"] for q in exam["questions"]}
            self.assertEqual(grade_exam(exam, answers)["percent"], 100.0)
            question = exam["questions"][0]
            answers[question["id"]] = next(o["id"] for o in question["options"] if o["id"] != question["answer"])
            marked = grade_exam(exam, answers)
            self.assertEqual(marked["score"], len(exam["questions"]) - 1)
            self.assertFalse(marked["corrections"][0]["correct"])
            if exam["id"] != "final":
                module_prompts |= prompts
            else:
                self.assertFalse(prompts & module_prompts, "The final exam must not repeat exact module prompts")

    def test_workshops_and_remediations_survive_loading_and_use_valid_keys(self):
        workshops = exercise_count = remediation_count = 0
        for course in self.courses:
            original_json = read(ROOT / "courses" / course["id"] / (VERSION + ".json"))
            delivered = load_bundled_course(course["id"], VERSION)
            self.assertEqual([a["practice"] for a in activities(delivered) if a.get("practice")],
                             [a["practice"] for a in activities(original_json) if a.get("practice")],
                             "Delivery changes must not replace v12 authored workshops")
            for activity in activities(course):
                practice = activity.get("practice")
                if not practice:
                    continue
                workshops += 1
                self.assertEqual(practice["revision"], VERSION)
                answers = {}
                reviews = {}
                for exercise in practice["exercises"]:
                    exercise_count += 1
                    self.assert_distinct_options(exercise["options"])
                    keys = {o["id"] for o in exercise["options"]}
                    self.assertTrue(exercise["context"].strip())
                    if exercise["kind"] == "single":
                        self.assertIn(exercise["answer"], keys)
                        answers[exercise["id"]] = exercise["answer"]
                    else:
                        answers[exercise["id"]] = {row["id"]: row["answer"] for row in exercise["rows"]}
                        self.assertTrue(set(answers[exercise["id"]].values()) <= keys)
                    drill = exercise["remediation"]
                    remediation_count += 1
                    self.assert_distinct_options(drill["options"])
                    self.assertIn(drill["answer"], {o["id"] for o in drill["options"]})
                    reviews[exercise["id"]] = drill["answer"]
                result = grade_practice(practice, answers, reviews)
                self.assertTrue(result["correct"], activity["id"])
                self.assertTrue(all(item["correct"] for item in result["review"]), activity["id"])
        self.assertEqual((workshops, exercise_count, remediation_count), (132, 364, 364))
        self.assertEqual(self.manifest["visual_learning"]["guided_workshops"], workshops)

    def test_original_video_metadata_and_transcripts_are_not_rewritten(self):
        videos = 0
        for current in self.courses:
            previous = read(ROOT / "courses" / current["id"] / (PREVIOUS + ".json"))
            for activity, old_activity in zip(activities(current), activities(previous)):
                current_videos = [b["video"] for b in activity.get("blocks", []) if b.get("video")]
                old_videos = [b["video"] for b in old_activity.get("blocks", []) if b.get("video")]
                self.assertEqual(current_videos, old_videos)
                videos += len(current_videos)
                self.assertEqual(activity.get("academy", {}).get("transcript"), old_activity.get("academy", {}).get("transcript"))
        self.assertEqual(videos, 62)

    def test_added_topics_are_visible_in_real_lesson_template(self):
        env = Environment(loader=FileSystemLoader(REPOSITORY / "templates"), autoescape=select_autoescape())
        template = env.get_template("_aps62_activity.html")
        course = self.courses[11]
        html_by_section = {}
        for section in course["sections"]:
            lesson = next(a for a in section["activities"] if a.get("academy", {}).get("kind") == "lesson")
            html_by_section[section["id"]] = template.render(activity=lesson, course=course)
        expectations = {
            "aps62-12-01": ["prise d’otages", "véhicule", "motivation"],
            "aps62-12-02": ["pistolet", "revolver", "fusil d’assaut", "fusil de chasse", "fusil à pompe", "lance-roquettes", "factice"],
            "aps62-12-06": ["radiologique", "biologique", "chimique", "hameçonnage", "indépendant"],
            "aps62-12-07": ["pneumothorax", "hémorragie", "blast", "projectiles", "difficulté à respirer"]
        }
        for section, terms in expectations.items():
            for term in terms:
                self.assertIn(term.casefold(), html_by_section[section].casefold(), (section, term))
        review = self.manifest["regulatory_review"]
        terror = next(m for m in review["modules"] if m["id"] == course["id"])
        self.assertEqual(terror["trainer_validation"]["status"], "pending")

    def test_new_diagrams_are_accessible_version_scoped_assets(self):
        current = self.courses[11]
        diagrams = [a["academy"]["uniform_diagram"] for a in activities(current) if a.get("academy", {}).get("uniform_diagram")]
        self.assertEqual(len(diagrams), 3)
        self.assertEqual(current["counts"]["assets"], len(current["assets"]))
        for diagram in diagrams:
            path = bundled_asset(current["id"], VERSION, diagram["src"])
            self.assertIsNotNone(path)
            self.assertIsNone(bundled_asset(current["id"], PREVIOUS, diagram["src"]))
            root = ET.parse(path).getroot()
            self.assertEqual(root.attrib["role"], "img")
            self.assertTrue(root.find("{http://www.w3.org/2000/svg}title").text)
            self.assertTrue(root.find("{http://www.w3.org/2000/svg}desc").text)
            self.assertTrue(diagram["alt"] and diagram["points"])
            self.assertFalse(root.findall(".//{http://www.w3.org/2000/svg}script"))

    def test_documented_repairs_refer_to_real_items_and_contexts(self):
        report = read(ROOT / "content_review_v12.json")
        self.assertEqual(report["previous_edition_sha256"], V11_SHA256)
        questions = {q["id"]: q for exam in self.exams for q in exam["questions"]}
        self.assertEqual(len(report["wording_repairs"]), 31)
        self.assertEqual(len(report["coverage_exam_questions"]), 17)
        for repair in report["wording_repairs"]:
            self.assertIn(repair["id"], questions)
            self.assertEqual(repair["prompt"], questions[repair["id"]]["prompt"])
        self.assertEqual(len(report["independent_workshop_contexts"]), 52)
        self.assertEqual(len(report["workshop_wording_repairs"]), 18)
        indexed = {a["id"]: a for course in self.courses for a in activities(course)}
        q = next(e for e in indexed["aps62-05-03-transfert"]["practice"]["exercises"] if e["id"] == "application")
        self.assertIn("sans menace", q["prompt"])
        self.assertNotIn("menace maintenant", q["context"])
        self.assertIn("indépendante", q["context"])


if __name__ == "__main__":
    unittest.main()
