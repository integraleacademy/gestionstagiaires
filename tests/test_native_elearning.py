from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from elearning_native.importer import CourseCatalog, CourseImportError, import_easygenerator_course
from elearning_native.store import NativeElearningStore


def _write_synthetic_course(
    path: Path,
    *,
    dangerous_member: str = "",
    fill_blank_input: bool = False,
    course_id: str = "course-test",
    extra_section: bool = False,
) -> None:
    fill_blank_answers = [
        {
            "id": "blank-a",
            "text": {"fr": "l'agent"},
            "isCorrect": True,
            "matchCase": False,
        }
    ]
    if not fill_blank_input:
        fill_blank_answers.append(
            {"id": "blank-b", "text": {"fr": "la police"}, "isCorrect": False}
        )
    course = {
        "id": course_id,
        "version": "version-1",
        "title": {"fr": "Cours de test"},
        "authorFullName": "Intégrale Academy",
        "introductions": [],
        "sections": [
            {
                "id": "section-1",
                "title": {"fr": "Séquence 1"},
                "learningObjective": {"fr": "Comprendre"},
                "questions": [
                    {
                        "id": "content-1",
                        "type": "informationContent",
                        "title": {"fr": "Leçon"},
                        "learningContents": [{"id": "block-1", "children": []}],
                    },
                    {
                        "id": "question-1",
                        "type": "singleSelectText",
                        "title": {"fr": "Choisissez"},
                        "answers": [
                            {"id": "answer-a", "text": {"fr": "Oui"}, "isCorrect": True},
                            {"id": "answer-b", "text": {"fr": "Non"}, "isCorrect": False},
                        ],
                    },
                    {
                        "id": "question-2",
                        "type": "fillInTheBlank",
                        "title": {"fr": "Complétez"},
                        "answerGroups": [
                            {
                                "id": "group-1",
                                "answers": fill_blank_answers,
                            }
                        ],
                    },
                ],
            }
        ],
    }
    if extra_section:
        course["sections"].append({
            "id": "section-2", "title": {"fr": "Séquence complémentaire"},
            "questions": [{"id": "content-2", "type": "informationContent", "title": {"fr": "Leçon complémentaire"},
                           "learningContents": [{"id": "block-1", "children": []}]}],
        })
    settings = {
        "masteryScore": {"score": 80, "isOverall": True},
        "forceNavigation": {"enabled": True},
        "numberOfAttempts": {"isLimited": False, "attemptsLimit": 0},
        "timer": {"enabled": False},
        "branding": {
            "colors": [
                {"key": "main-color", "value": "red; background:url(javascript:alert(1))"},
                {"key": "cta-button-color", "value": "#F97316"},
            ]
        },
    }
    block_html = """<div class="eg-content-editor" data-type="oneImage">
      <p onclick="alert(1)">Texte <strong>utile</strong></p>
      <script>alert('bad')</script>
      <img src="media/image.png" onerror="alert(2)">
      <img src="https://tracker.invalid/pixel.png">
      <a href="javascript:alert(3)">lien dangereux</a>
    </div>"""
    if fill_blank_input:
        blank_html = """<div data-type="fillInTheBlank"><p>Le rôle de <input contenteditable="false" class="blankInput" data-group-id="group-1" data-match-case="False" value="" size="15"><span class="removed-flag" data-blank-id="group-1" style="display:none"></span> est encadré.</p></div>"""
    else:
        blank_html = """<div data-type="fillInTheBlank"><p>Le rôle de <select data-group-id="group-1"><option>cassé par l'apostrophe</option></select> est encadré.</p></div>"""

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("content/data.js", json.dumps(course, ensure_ascii=False))
        archive.writestr("settings.js", json.dumps(settings))
        archive.writestr("languageSettings.json", json.dumps([{"language": "fr", "isDefault": True}]))
        archive.writestr("content/fr/block-1.html", block_html)
        archive.writestr("content/fr/question-2_content.html", blank_html)
        archive.writestr("media/image.png", b"not-a-real-image")
        if dangerous_member:
            archive.writestr(dangerous_member, b"danger")


class EasygeneratorImporterTests(unittest.TestCase):
    def test_converts_course_and_sanitizes_imported_html(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "course.zip"
            _write_synthetic_course(archive)

            imported = import_easygenerator_course(archive, root / "catalog", archive_source=False)

            self.assertEqual(imported["id"], "eg-course-test")
            self.assertEqual(imported["counts"]["sections"], 1)
            self.assertEqual(imported["counts"]["activities"], 3)
            self.assertEqual(imported["counts"]["scored_activities"], 2)
            self.assertEqual(imported["settings"]["mastery_score"], 80)
            self.assertTrue(imported["settings"]["force_navigation"])
            self.assertEqual(imported["theme"]["main_color"], "#4f46e5")
            self.assertEqual(imported["theme"]["button_color"], "#f97316")

            html = imported["sections"][0]["activities"][0]["blocks"][0]["html"]
            self.assertIn("Texte <strong>utile</strong>", html)
            self.assertIn('src="media/image.png"', html)
            self.assertNotIn("onclick", html)
            self.assertNotIn("onerror", html)
            self.assertNotIn("<script", html)
            self.assertNotIn("tracker.invalid", html)
            self.assertNotIn("javascript:", html)

            fill = imported["sections"][0]["activities"][2]["prompt_html"]
            self.assertIn("l'agent", fill)
            self.assertIn('value="blank-a"', fill)
            self.assertIn('data-group-id="group-1"', fill)

            catalog = CourseCatalog(root / "catalog")
            loaded = catalog.load_course(imported["id"])
            self.assertEqual(loaded["source"]["sha256"], imported["source"]["sha256"])
            self.assertTrue(catalog.asset_path(imported["id"], imported["version"], "media/image.png").is_file())

    def test_same_archive_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "course.zip"
            _write_synthetic_course(archive)
            first = import_easygenerator_course(archive, root / "catalog", archive_source=False)
            second = import_easygenerator_course(archive, root / "catalog", archive_source=False)
            self.assertEqual(first["version"], second["version"])
            versions = [path for path in (root / "catalog" / "courses" / first["id"]).iterdir() if path.is_dir()]
            self.assertEqual(len(versions), 1)

    def test_converts_easygenerator_free_text_fill_blank(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "course.zip"
            _write_synthetic_course(archive, fill_blank_input=True)

            imported = import_easygenerator_course(archive, root / "catalog", archive_source=False)

            activity = imported["sections"][0]["activities"][2]
            prompt = activity["prompt_html"]
            self.assertIn('type="text"', prompt)
            self.assertIn('class="native-elearning-blank native-elearning-blank--text"', prompt)
            self.assertIn('data-group-id="group-1"', prompt)
            self.assertNotIn("contenteditable", prompt)
            self.assertNotIn("l'agent", prompt)
            self.assertEqual(activity["answer_groups"][0]["mode"], "text")
            self.assertFalse(activity["answer_groups"][0]["answers"][0]["match_case"])

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "dangerous.zip"
            _write_synthetic_course(archive, dangerous_member="../outside.txt")
            with self.assertRaisesRegex(CourseImportError, "dangereux"):
                import_easygenerator_course(archive, root / "catalog")
            self.assertFalse((root / "outside.txt").exists())

    def test_rejects_dynamic_wrapper_without_course_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "dynamic.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("index.html", '<iframe src="https://easygenerator.com/course"></iframe>')
            with self.assertRaisesRegex(CourseImportError, "content/data.js"):
                import_easygenerator_course(archive, root / "catalog")


class NativeTrackingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store = NativeElearningStore(Path(self.temporary.name) / "tracking.sqlite3")
        self.access = {
            "session_id": "session-1",
            "trainee_id": "trainee-1",
            "course_id": "course-1",
            "course_version": "v1",
        }
        self.order = ["lesson-1", "lesson-2", "quiz-1"]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_counts_only_server_validated_active_time_and_blocks_second_tab(self) -> None:
        first = self.store.start_tracking(
            self.access, tab_id="tab-1", activity_id="lesson-1", now_epoch=1_000
        )["tracking_session_id"]
        initial = self.store.heartbeat(
            self.access,
            first,
            activity_id="lesson-1",
            visible=True,
            focused=True,
            recent_activity=True,
            media_playing=False,
            now_epoch=1_000,
        )
        self.assertTrue(initial["active"])
        self.assertEqual(initial["credited_seconds"], 0)

        credited = self.store.heartbeat(
            self.access,
            first,
            activity_id="lesson-1",
            visible=True,
            focused=True,
            recent_activity=True,
            media_playing=False,
            now_epoch=1_015,
        )
        self.assertEqual(credited["credited_seconds"], 15)

        second = self.store.start_tracking(
            self.access, tab_id="tab-2", activity_id="lesson-1", now_epoch=1_016
        )["tracking_session_id"]
        duplicate = self.store.heartbeat(
            self.access,
            second,
            activity_id="lesson-1",
            visible=True,
            focused=True,
            recent_activity=True,
            media_playing=False,
            now_epoch=1_016,
        )
        self.assertTrue(duplicate["duplicate"])
        self.assertFalse(duplicate["active"])

        paused = self.store.heartbeat(
            self.access,
            first,
            activity_id="lesson-1",
            visible=False,
            focused=False,
            recent_activity=False,
            media_playing=False,
            now_epoch=1_030,
        )
        self.assertFalse(paused["active"])
        self.assertEqual(paused["credited_seconds"], 15)

        self.store.heartbeat(
            self.access,
            second,
            activity_id="lesson-1",
            visible=True,
            focused=True,
            recent_activity=True,
            media_playing=False,
            now_epoch=1_031,
        )
        progress = self.store.get_progress(
            self.access, activity_order=self.order, scored_activity_ids=["quiz-1"]
        )
        self.assertEqual(progress["active_seconds"], 30)
        events = self.store.events_for_learner(self.access)
        self.assertIn("duplicate_tab_blocked", [event["event_type"] for event in events])

    def test_heartbeat_credit_is_capped(self) -> None:
        tracking_id = self.store.start_tracking(
            self.access, tab_id="tab-1", activity_id="lesson-1", now_epoch=2_000
        )["tracking_session_id"]
        self.store.heartbeat(
            self.access,
            tracking_id,
            activity_id="lesson-1",
            visible=True,
            focused=True,
            recent_activity=True,
            media_playing=False,
            now_epoch=2_000,
        )
        delayed = self.store.heartbeat(
            self.access,
            tracking_id,
            activity_id="lesson-1",
            visible=True,
            focused=True,
            recent_activity=True,
            media_playing=False,
            now_epoch=2_120,
        )
        self.assertEqual(delayed["credited_seconds"], 20)

    def test_other_module_cannot_double_count_time_but_other_learner_can(self):
        signals = dict(activity_id="lesson-1", visible=True, focused=True, recent_activity=True, media_playing=False)
        first = self.store.start_tracking(self.access, tab_id="first", activity_id="lesson-1", now_epoch=1000)["tracking_session_id"]
        self.store.heartbeat(self.access, first, now_epoch=1000, **signals)
        other_module = {**self.access, "course_id": "second-course"}
        second = self.store.start_tracking(other_module, tab_id="second", activity_id="lesson-1", now_epoch=1001)["tracking_session_id"]
        blocked = self.store.heartbeat(other_module, second, now_epoch=1001, **signals)
        self.assertTrue(blocked["duplicate"])
        self.assertEqual(blocked["credited_seconds"], 0)
        other_learner = {**self.access, "trainee_id": "another-learner"}
        third = self.store.start_tracking(other_learner, tab_id="third", activity_id="lesson-1", now_epoch=1001)["tracking_session_id"]
        self.assertTrue(self.store.heartbeat(other_learner, third, now_epoch=1001, **signals)["active"])
        self.store.finish_tracking(self.access, first, activity_id="lesson-1", now_epoch=1015)
        self.assertTrue(self.store.heartbeat(other_module, second, now_epoch=1016, **signals)["active"])
        credited = self.store.heartbeat(other_module, second, now_epoch=1031, **signals)
        self.assertEqual(credited["credited_seconds"], 15)
        rows = self.store.learner_progress(self.access["session_id"], self.access["trainee_id"])
        self.assertEqual(sum(row["active_seconds"] for row in rows), 30)

    def test_stale_module_cannot_credit_overlapping_time_after_handover(self):
        signals = dict(activity_id="lesson-1", visible=True, focused=True, recent_activity=True, media_playing=False)
        first = self.store.start_tracking(self.access, tab_id="first", activity_id="lesson-1", now_epoch=1000)["tracking_session_id"]
        self.store.heartbeat(self.access, first, now_epoch=1000, **signals)
        other = {**self.access, "course_id": "second-course"}
        second = self.store.start_tracking(other, tab_id="second", activity_id="lesson-1", now_epoch=1060)["tracking_session_id"]
        self.assertTrue(self.store.heartbeat(other, second, now_epoch=1060, **signals)["active"])
        self.assertEqual(self.store.heartbeat(other, second, now_epoch=1075, **signals)["credited_seconds"], 15)
        delayed = self.store.heartbeat(self.access, first, now_epoch=1076, **signals)
        self.assertTrue(delayed["duplicate"])
        self.assertEqual(delayed["credited_seconds"], 0)

    def test_completion_and_score_are_calculated_server_side(self) -> None:
        first = self.store.complete_activity(
            self.access,
            "lesson-1",
            activity_order=self.order,
            scored_activity_ids=["quiz-1"],
            mastery_score=80,
        )
        self.assertEqual(first["status"], "in_progress")
        self.store.complete_activity(
            self.access,
            "lesson-2",
            activity_order=self.order,
            scored_activity_ids=["quiz-1"],
            mastery_score=80,
        )
        final = self.store.complete_activity(
            self.access,
            "quiz-1",
            activity_order=self.order,
            scored_activity_ids=["quiz-1"],
            mastery_score=80,
            answer={"selected": ["answer-a"], "correct": True},
        )
        self.assertEqual(final["status"], "passed")
        self.assertEqual(final["progress_percent"], 100)
        self.assertEqual(final["score_percent"], 100)
        self.assertIsNotNone(final["completed_at"])


if __name__ == "__main__":
    unittest.main()
