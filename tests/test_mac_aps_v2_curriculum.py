"""Release invariants for the scoped MAC APS edition and its frozen history."""
from __future__ import annotations

import hashlib
import json
import unittest
from collections import Counter

from elearning_native import mac_aps


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


class MacAPSV2CurriculumTests(unittest.TestCase):
    def test_historical_graphs_are_exactly_preserved(self):
        version = mac_aps.LEGACY_VERSION
        manifest = mac_aps.curriculum_manifest(version)
        courses = {cid: mac_aps.load_bundled_course(cid, version)
                   for cid in mac_aps.curriculum_ids(version)}
        exams = {eid: mac_aps.load_exam(eid, version)
                 for eid in [*("macaps-module-" + n for n in ("01", "02", "03", "04", "05")), "macaps-final"]}
        self.assertEqual(canonical_sha256(manifest),
                         "d63f4e231abaa18e43b7dac9894f06a71e543488f1383a56cdc466ca95c870a2")
        self.assertEqual(canonical_sha256(courses),
                         "16b9274099d6fb4014546948ed757f38d26cd988fd7f84fcc6215c8356f672e1")
        self.assertEqual(canonical_sha256(exams),
                         "82c9614520babc51511a1757fb27d5bff13e766a842eecd764ef2f0eb610aba3")
        # Public loaders return detached data, including nested answer keys.
        courses["academy-macaps-02"]["sections"].clear()
        exams["macaps-final"]["questions"][0]["answer"] = "changed"
        self.assertTrue(mac_aps.load_bundled_course("academy-macaps-02", version)["sections"])
        self.assertNotEqual(mac_aps.load_exam("macaps-final", version)["questions"][0]["answer"], "changed")

    def test_ten_historical_objectives_have_exact_budgets(self):
        manifest = mac_aps.curriculum_manifest()
        self.assertEqual(manifest["version"], "20261012-macaps-v2")
        self.assertEqual([m["number"] for m in manifest["modules"]], ["02", "03", "05"])
        self.assertEqual([m["planned_minutes"] for m in manifest["modules"]], [180, 240, 420])
        self.assertEqual(manifest["planned_minutes"], 840)
        objectives = mac_aps.legal_objectives()
        self.assertEqual([o["minimum_minutes"] for o in objectives],
                         [180, 240, 90, 60, 60, 60, 60, 30, 30, 30])
        self.assertEqual(sum(o["required_seconds"] for o in objectives), 14 * 60 * 60)
        for course_id in mac_aps.curriculum_ids():
            course = mac_aps.load_bundled_course(course_id)
            self.assertEqual(course["version"], mac_aps.VERSION)
            self.assertEqual(course["pedagogical_scope"], "principal")
            self.assertEqual(course["planned_minutes"], mac_aps.minimum_minutes(course_id))
            self.assertEqual(course["required_minutes"], course["planned_minutes"])
            self.assertEqual(sum(a["planned_minutes"] for s in course["sections"] for a in s["activities"]),
                             course["planned_minutes"])
            self.assertEqual(mac_aps.required_section_ids(course_id), [s["id"] for s in course["sections"]])
            self.assertNotRegex(course["title"], r"MAC APS · 0[235] ·")

    def test_timed_objectives_partition_all_activities_and_end_with_quiz(self):
        for course_id in mac_aps.curriculum_ids():
            course = mac_aps.load_bundled_course(course_id)
            activities = {a["id"]: a for s in course["sections"] for a in s["activities"]}
            assigned = []
            for objective in course["timed_objectives"]:
                grouped = [activities[aid] for aid in objective["activity_ids"]]
                assigned.extend(objective["activity_ids"])
                self.assertEqual(sum(a["planned_minutes"] * 60 for a in grouped), objective["required_seconds"])
                self.assertTrue(all(a["objective_id"] == objective["id"] for a in grouped))
                closing = grouped[-1]
                self.assertEqual(closing["id"], objective["assessment_activity_id"])
                self.assertEqual(closing["type"], "question")
                self.assertTrue(closing["is_objective_assessment"])
                self.assertGreaterEqual(len(closing["answer_groups"]), 6)
                self.assertEqual(closing["macaps"]["kind"], "quiz")
                # Only answer labels are projected into the public question payload.
                for question in closing["macaps"]["questions"]:
                    self.assertEqual(set(question), {"id", "prompt", "options"})
                    self.assertFalse(any("is_correct" in option for option in question["options"]))
            self.assertEqual(assigned, course["activity_order"])
            self.assertEqual(len(assigned), len(set(assigned)))
            self.assertEqual(sum(o["required_seconds"] for o in course["timed_objectives"]),
                             course["required_minutes"] * 60)
            for section in course["sections"]:
                self.assertEqual(section["required_seconds"], sum(a["planned_minutes"] for a in section["activities"]) * 60)

    def test_course_work_is_developed_and_all_lessons_are_mapped_once(self):
        lessons = mac_aps._lessons()
        self.assertEqual(Counter(l["module"] for l in lessons), {"02": 6, "03": 8, "05": 14})
        mapped = [ref for objective in mac_aps.legal_objectives() for ref in objective["lesson_refs"]]
        self.assertEqual(mapped, [lesson["id"] for lesson in lessons])
        self.assertEqual(len(set(mapped)), 28)
        quiz_prompts = []
        prose_words = 0
        for lesson in lessons:
            prose = " ".join(p for section in lesson["sections"] for p in section["paragraphs"])
            prose += " " + " ".join(lesson["example"]["paragraphs"])
            prose_words += len(prose.split())
            self.assertGreaterEqual(len(prose.split()), 800, lesson["id"])
            self.assertGreaterEqual(len(lesson["sections"]), 4)
            self.assertTrue(lesson.get("table") or lesson.get("flow"))
            self.assertGreaterEqual(len(lesson["takeaways"]), 3)
            self.assertEqual(lesson["mode"], "revision_theorique")
            self.assertEqual(lesson["pedagogical_scope"], "principal")
            self.assertEqual(len(lesson["quiz"]), 6)
            self.assertEqual(len(lesson["scenario"]["steps"]), 3)
            self.assertTrue(lesson["source_urls"])
            self.assertTrue(all(url.startswith("https://") for url in lesson["source_urls"]))
            for question in [*lesson["quiz"], *lesson["scenario"]["steps"]]:
                self.assertEqual(len({o["text"] for o in question["options"]}), len(question["options"]))
                self.assertIn(question["answer"], {o["id"] for o in question["options"]})
                self.assertTrue(question["explanation"])
            quiz_prompts.extend(q["prompt"].strip().casefold() for q in lesson["quiz"])
        self.assertGreater(prose_words, 26000)
        self.assertEqual(len(quiz_prompts), len(set(quiz_prompts)))
        manifest = mac_aps.curriculum_manifest()
        self.assertEqual((manifest["lesson_count"], manifest["inline_question_count"], manifest["decision_count"]), (28, 168, 84))
        self.assertEqual((manifest["activity_count"], manifest["objective_question_count"]), (124, 74))

    def test_complements_and_mixed_terrorism_video_are_outside_14_hours(self):
        principal_ids = set(mac_aps.curriculum_ids())
        manifest = mac_aps.complement_manifest()
        self.assertEqual(manifest["principal_minutes"], 0)
        self.assertEqual(len(manifest["modules"]), 3)
        for module in manifest["modules"]:
            self.assertNotIn(module["id"], principal_ids)
            course = mac_aps.load_bundled_course(module["id"], mac_aps.VERSION)
            self.assertEqual(course["pedagogical_scope"], "complement")
            self.assertEqual(course["required_minutes"], 0)
            self.assertEqual(course["principal_minutes"], 0)
            self.assertEqual(course["timed_objectives"], [])
            self.assertNotIn("mock_exam_id", course)
            self.assertEqual(mac_aps.required_section_ids(module["id"]), [])
            self.assertEqual(mac_aps.minimum_minutes(module["id"]), 0)
        terrorism = mac_aps.load_bundled_course("academy-macaps-05")
        self.assertFalse(any(s["id"] in {"macaps-05-07", "macaps-05-08", "macaps-05-synthese"}
                             for s in terrorism["sections"]))
        self.assertFalse(any(s["id"].startswith(("macaps-01-", "macaps-04-")) for s in terrorism["sections"]))
        self.assertEqual(terrorism["counts"]["required_videos"], 0)
        alert = next(l for l in mac_aps._lessons() if l["id"] == "macaps-05-10")
        self.assertEqual(alert["objective_id"], "macaps-terrorisme-secours")
        self.assertNotEqual(alert["title"], next(l for l in mac_aps._lessons(mac_aps.LEGACY_VERSION)
                                               if l["id"] == "macaps-05-10")["title"])

    def test_exam_scope_and_feedback_only_reference_the_principal_objectives(self):
        ids, prompts = set(), set()
        lessons = {row["id"]: row for row in mac_aps._lessons()}
        objective_ids = {row["id"] for row in mac_aps.legal_objectives()}
        for exam_id in ["macaps-module-02", "macaps-module-03", "macaps-module-05", "macaps-final"]:
            exam = mac_aps.load_exam(exam_id, mac_aps.VERSION)
            self.assertEqual(len(exam["questions"]), 100 if exam_id == "macaps-final" else 30)
            for question in exam["questions"]:
                self.assertNotIn(question["id"], ids)
                self.assertNotIn(question["prompt"].strip().casefold(), prompts)
                ids.add(question["id"])
                prompts.add(question["prompt"].strip().casefold())
                self.assertIn(question["objective_id"], objective_ids)
                self.assertTrue(question["lesson_refs"])
                self.assertTrue(all(ref in lessons for ref in question["lesson_refs"]))
                self.assertTrue(all(lessons[ref]["objective_id"] == question["objective_id"] for ref in question["lesson_refs"]))
                self.assertTrue(question["sources"])
                self.assertTrue(question["explanation"])
                self.assertIn(question["answer"], {o["id"] for o in question["options"]})
        final = mac_aps.load_exam("macaps-final", mac_aps.VERSION)
        self.assertEqual({q["objective_id"] for q in final["questions"]}, objective_ids)
        self.assertIsNone(mac_aps.load_exam("macaps-module-01", mac_aps.VERSION))
        self.assertIsNone(mac_aps.load_exam("macaps-module-04", mac_aps.VERSION))

    def test_reference_does_not_claim_extension_or_issue_certificates(self):
        manifest = mac_aps.curriculum_manifest()
        review = manifest["regulatory_review"]
        self.assertFalse(review["current_distance_authorization_claimed"])
        self.assertEqual(review["reference_period_end"], "2025-12-31")
        self.assertEqual((review["stage_minutes"], review["stage_minutes_with_documented_first_aid_exemption"]), (2040, 1620))
        self.assertEqual(len(review["initial_assessment"]), 10)
        self.assertIn("31 décembre 2025", manifest["notice"])
        for course_id in [*mac_aps.curriculum_ids(), *(m["id"] for m in mac_aps.complement_manifest()["modules"])]:
            regulation = mac_aps.load_bundled_course(course_id)["regulation"]
            self.assertEqual(regulation["scope"], "pedagogical_support")
            self.assertFalse(regulation["automatic_stage_credit"])
            self.assertFalse(regulation["automatic_certificate"])
            self.assertFalse(regulation["current_distance_authorization_claimed"])

    def test_assets_versions_and_pacing_remain_scoped(self):
        from elearning_native.videos import mac_aps_pacing_enabled
        self.assertTrue(set(mac_aps.curriculum_ids(mac_aps.LEGACY_VERSION)) <= set(mac_aps.bundled_course_ids()))
        for version in mac_aps.SUPPORTED_VERSIONS:
            for course_id in mac_aps.curriculum_ids(version):
                self.assertTrue(mac_aps_pacing_enabled(course_id, version))
        self.assertFalse(mac_aps_pacing_enabled("academy-macaps-complement-05", mac_aps.VERSION))
        self.assertIsNone(mac_aps.load_bundled_course("academy-macaps-02", "unknown"))
        self.assertIsNone(mac_aps.curriculum_manifest("unknown"))
        self.assertIsNone(mac_aps.load_bundled_course("academy-macaps-01", mac_aps.VERSION))
        for number in ("02", "03"):
            course_id = "academy-macaps-" + number
            course = mac_aps.load_bundled_course(course_id)
            self.assertEqual(course["counts"]["required_videos"], 1)
            for name in course["assets"]:
                self.assertTrue(mac_aps.bundled_asset(course_id, mac_aps.VERSION, name).is_file())
            self.assertIsNone(mac_aps.bundled_asset(course_id, mac_aps.VERSION, "../../lessons.json"))


if __name__ == "__main__":
    unittest.main()
