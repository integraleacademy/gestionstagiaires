"""Checks against the published v9 fixtures for the v10 audit corrections."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from elearning_native.practice import grade_practice, public_practice
from scripts.aps62_v10.content_fixes import (
    ARTICLE73_DOCUMENT, BADGE_FACT, INITIAL_REPORT, SOURCE_URLS,
    TRANSMISSION_FACT, UNIFORM_DIAGRAM, VIDEO_CHANGED_IDS,
    VIGIPIRATE_CURRENT, VIGIPIRATE_OLD, apply_course, apply_video_scripts,
)

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "elearning_native" / "aps62"
PREVIOUS = "20261007-aps62-v9"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def section(course, sid):
    return next(item for item in course["sections"] if item["id"] == sid)


def activity(course, aid):
    return next(item for part in course["sections"] for item in part["activities"] if item["id"] == aid)


def exercise(course, aid, eid):
    return next(item for item in activity(course, aid)["practice"]["exercises"] if item["id"] == eid)


def correct_text(ex):
    return next(item["text"] for item in ex["options"] if item["id"] == ex["answer"])


def serialized(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class APS62V10ContentFixesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {number: read(BASE / f"courses/academy-aps62-{number:02}/{PREVIOUS}.json") for number in range(1, 16)}
        cls.original_bytes = {path: path.read_bytes() for path in BASE.glob(f"courses/*/{PREVIOUS}.json")}
        cls.updated = {number: apply_course(course) for number, course in cls.previous.items()}
        cls.scripts = read(BASE / "video_scripts_v7.json")
        cls.updated_scripts = apply_video_scripts(cls.scripts)

    def test_historical_input_files_ids_answers_and_durations_are_preserved(self):
        total = 0
        for number, original in self.previous.items():
            snapshot = deepcopy(original)
            updated = apply_course(original)
            self.assertEqual(original, snapshot)
            self.assertEqual(apply_course(updated), updated)
            self.assertEqual(updated["version"], PREVIOUS)
            self.assertEqual(updated["activity_order"], original["activity_order"])
            total += updated["planned_minutes"]
            for old_section, new_section in zip(original["sections"], updated["sections"]):
                self.assertEqual(old_section["id"], new_section["id"])
                for old, new in zip(old_section["activities"], new_section["activities"]):
                    self.assertEqual(old["id"], new["id"])
                    self.assertEqual(old["planned_minutes"], new["planned_minutes"])
                    if old.get("practice"):
                        for old_ex, new_ex in zip(old["practice"]["exercises"], new["practice"]["exercises"]):
                            self.assertEqual(old_ex["id"], new_ex["id"])
                            self.assertEqual(old_ex.get("answer"), new_ex.get("answer"))
                            self.assertEqual([o["id"] for o in old_ex["options"]], [o["id"] for o in new_ex["options"]])
        self.assertEqual(total, 3720)
        for path, before in self.original_bytes.items():
            self.assertEqual(path.read_bytes(), before)

    def test_unaffected_modules_and_video_rows_are_unchanged(self):
        for number in (2, 4, 8, 9, 10, 11, 13, 15):
            self.assertEqual(self.previous[number], self.updated[number])
        self.assertEqual(apply_video_scripts(self.updated_scripts), self.updated_scripts)
        actual_changes = {sid for sid in self.scripts if self.scripts[sid] != self.updated_scripts[sid]}
        self.assertEqual(actual_changes, VIDEO_CHANGED_IDS)
        self.assertEqual(self.scripts, read(BASE / "video_scripts_v7.json"))

    def test_vigipirate_current_teaching_changes_but_historical_exercise_survives(self):
        current = serialized(section(self.updated[12], "aps62-12-01"))
        self.assertIn(VIGIPIRATE_CURRENT, current)
        self.assertNotIn(VIGIPIRATE_OLD, current)
        self.assertIn(VIGIPIRATE_CURRENT, self.updated_scripts["aps62-12-01"]["transcript"])
        self.assertEqual(section(self.previous[12], "aps62-12-03"), section(self.updated[12], "aps62-12-03"))
        self.assertIn("urgence attentat", serialized(section(self.updated[12], "aps62-12-03")).lower())

    def test_ordinal_correction_remains_valid_if_choices_are_reordered(self):
        ex = deepcopy(exercise(self.updated[7], "aps62-07-04-transfert", "application"))
        self.assertNotIn("première phrase", ex["explanation"])
        self.assertIn("La réponse adaptée", ex["explanation"])
        ex["options"].reverse()
        self.assertIn("cesser les insultes", correct_text(ex))

    def test_initial_report_only_refers_to_already_observed_insults(self):
        row = self.updated_scripts["aps62-07-04"]
        case = row["field_case"]
        self.assertIn("insulte", case["situation"])
        self.assertEqual(case["unverified_document"], INITIAL_REPORT)
        docs = next(s for s in row["scenes"] if s["kind"] == "field_documents")
        self.assertIn("insultes entendues", docs["text"])
        self.assertNotIn("menace explicite", docs["text"])
        self.assertIn("menace maintenant", case["evolution"])
        self.assertNotIn("sans mention de la menace explicite", serialized(section(self.updated[7], "aps62-07-04")))

    def test_badge_roles_are_explicit_in_case_choices_and_recorded_script(self):
        ex = exercise(self.updated[6], "aps62-06-04-atelier", "constat")
        self.assertIn("Lina", ex["context"])
        self.assertIn("Maxime", ex["context"])
        self.assertIn("Maxime entrerait-il", ex["prompt"])
        self.assertEqual(correct_text(ex), "Sous l'identité de Lina, titulaire du badge demandé.")
        action = exercise(self.updated[6], "aps62-06-04-atelier", "decision")
        self.assertIn("Refuser le prêt", correct_text(action))
        self.assertEqual(self.updated_scripts["aps62-06-04"]["field_case"]["fact"], BADGE_FACT)
        self.assertNotIn("Refuser d’utiliser l’identité d’un collègue", self.updated_scripts["aps62-06-04"]["transcript"])

    def test_observation_does_not_invent_commercial_motive(self):
        ex = exercise(self.updated[3], "aps62-03-02-atelier", "constat")
        self.assertIn("retour du directeur", correct_text(ex))
        self.assertNotIn("raison commerciale", ex["explanation"])
        self.assertNotIn("raison commerciale", self.updated_scripts["aps62-03-02"]["field_case"]["fact"])
        # The separate remediation explicitly says "afin de préserver les ventes".
        old = exercise(self.previous[3], "aps62-03-02-atelier", "constat")
        self.assertEqual(ex["remediation"], old["remediation"])

    def test_transmission_observation_keeps_the_document_and_adds_no_supposition(self):
        ex = exercise(self.updated[14], "aps62-14-06-atelier", "constat")
        self.assertEqual(correct_text(ex), TRANSMISSION_FACT)
        self.assertIn("ticket", ex["explanation"])
        self.assertNotIn("suppositions", ex["explanation"])
        # The later rumour really is introduced by the evolution and remains.
        evolution = exercise(self.updated[14], "aps62-14-06-atelier", "evolution")
        self.assertIn("rumeur", evolution["context"])

    def test_reference_document_now_tests_a_relevant_legal_condition(self):
        row = self.updated_scripts["aps62-05-03"]
        self.assertEqual(row["field_case"]["verified_document"], ARTICLE73_DOCUMENT)
        self.assertIn("crime flagrant", row["field_case"]["verified_document"])
        self.assertNotIn("Repère civique : devise", serialized(section(self.updated[5], "aps62-05-03")))
        recap = activity(self.updated[5], "aps62-05-03-synthese")["academy"]
        self.assertIn(SOURCE_URLS["article73"], [s[1] for s in recap["sources"]])

    def test_modified_choices_still_grade_and_public_data_has_no_answer_key(self):
        for number, aid in ((3, "aps62-03-02-atelier"), (6, "aps62-06-04-atelier"),
                            (7, "aps62-07-04-transfert"), (14, "aps62-14-06-atelier")):
            practice = activity(self.updated[number], aid)["practice"]
            for ex in practice["exercises"]:
                if ex["kind"] != "single":
                    continue
                for option in ex["options"]:
                    result = grade_practice(practice, {ex["id"]: option["id"]}, step=ex["id"])
                    self.assertEqual(result["correct"], option["id"] == ex["answer"])
                    self.assertEqual(result["feedback"][0]["explanation"], ex["explanation"])
            for public in public_practice(practice)["exercises"]:
                self.assertNotIn("answer", public)
                self.assertNotIn("explanation", public)

    def test_scripts_and_embedded_draft_transcriptions_agree_without_fake_timing(self):
        for sid in VIDEO_CHANGED_IDS:
            row = self.updated_scripts[sid]
            self.assertEqual(row["transcript"], "\n\n".join(scene["text"] for scene in row["scenes"]))
            course = self.updated[int(sid[6:8])]
            memory = activity(course, sid + "-memoriser")
            self.assertEqual(memory["academy"]["transcript"], row["transcript"])
            self.assertEqual(memory["blocks"][0]["video"]["transcript"], row["transcript"])
        with self.assertRaisesRegex(ValueError, "timed media manifest"):
            apply_video_scripts(read(BASE / "video_manifest_v7.json"))

    def test_uniform_diagram_is_available_with_accessible_text_and_real_specs(self):
        lesson = activity(self.updated[1], "aps62-01-04-comprendre")["academy"]
        diagram = lesson["uniform_diagram"]
        self.assertEqual(diagram["src"], UNIFORM_DIAGRAM["src"])
        self.assertIn(diagram["src"], self.updated[1]["assets"])
        svg_path = BASE / "assets" / diagram["src"]
        svg = ET.parse(svg_path).getroot()
        self.assertEqual(svg.attrib["role"], "img")
        self.assertIn("title", svg.attrib["aria-labelledby"])
        self.assertIsNotNone(svg.find("{http://www.w3.org/2000/svg}desc"))
        text = serialized(lesson["deepening"])
        for expected in ("54 × 15 mm", "50 mm", "Arial 76", "sept derniers chiffres", "gauche au porté", "article 4"):
            self.assertIn(expected, text)
        self.assertIn("fictif", diagram["caption"])


if __name__ == "__main__":
    unittest.main()
