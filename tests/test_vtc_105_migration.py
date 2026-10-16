import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from elearning_native import vtc_105_migration as migration
from elearning_native.paths import assigned_modules, project_progress
from elearning_native.store import NativeElearningStore


class Vtc105MigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "tracking.sqlite3"
        self.store = NativeElearningStore(self.path)
        self.trainee = {"id": "learner-1"}
        self.session = {"id": "session-vtc", "training_type": "Chauffeur VTC", "aps_native_path_title": "Mon parcours",
                        "aps_native_modules": [{"course_id": "academy-vtc-" + letter, "course_version": migration.BASE_VERSION,
                                                 "title": "Module " + letter.upper(), "required_minutes": 10,
                                                 "section_ids": [f"vtc-{letter}-01", f"vtc-{letter}-02"]}
                                                for letter in "abcdefgh"]}
        self.loader = patch("elearning_native.vtc.load_bundled_course", side_effect=self.course)
        self.loader.start()
        self.addCleanup(self.loader.stop)

    @staticmethod
    def course(course_id, version):
        letter = course_id[-1]
        course = {
            "id": course_id, "version": version, "title": "Cours " + letter.upper(),
            "training_label": "VTC", "settings": {"mastery_score": 80},
            "sections": [
                {"id": f"vtc-{letter}-01", "title": "Leçon", "activities": [
                    {"id": letter + "-lesson", "type": "content", "blocks": [
                        {"type": "video", "video": {"id": "video-" + letter, "required": True, "duration_seconds": 10}}]}]},
                {"id": f"vtc-{letter}-02", "title": "Vérification", "activities": [
                    {"id": letter + "-quiz", "type": "single_choice", "scored": True, "answer": "correct", "blocks": []}]},
            ],
        }
        if version == migration.VERSION:
            for number in range(1, 5):
                course["sections"][(number - 1) % 2]["activities"].append({
                    "id": f"vtc-{letter}-production-{number:02}", "type": "content", "scored": False, "optional": True,
                    "production": {"id": f"vtc-{letter}-production-{number:02}"}, "blocks": [],
                })
        course["activity_order"] = [activity["id"] for section in course["sections"] for activity in section["activities"]]
        return course

    def access(self, letter="a", version=migration.BASE_VERSION, trainee_id="learner-1"):
        return {"session_id": self.session["id"], "trainee_id": trainee_id,
                "course_id": "academy-vtc-" + letter, "course_version": version}

    def seed(self, letter="a", *, seconds=125.125, complete=False, video_complete=True, version=migration.BASE_VERSION,
             trainee_id="learner-1"):
        access = self.access(letter, version, trainee_id)
        timestamp = "2026-10-10T08:05:42.123456Z"
        with self.store._transaction() as connection:
            self.store._ensure_progress_row(connection, access, now_iso=timestamp, current_activity_id=letter + "-quiz")
            completed = [letter + "-lesson", letter + "-quiz"] if complete else [letter + "-lesson"]
            answers = {letter + "-quiz": {"selected": "correct", "correct": True, "first_correct": False,
                                         "history": [{"selected": "wrong", "correct": False}]}}
            videos = {letter + "-lesson": {"video-" + letter: {
                "duration_seconds": 10, "watched_seconds": 10 if video_complete else 3,
                "completed": video_complete, "completed_at": timestamp if video_complete else None}}}
            connection.execute("""UPDATE learner_course_progress SET completed_json=?,answers_json=?,video_progress_json=?,
                active_seconds=?,status=?,score_percent=100,completed_at=?
                WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?""",
                (json.dumps(completed), json.dumps(answers, ensure_ascii=False), json.dumps(videos), seconds,
                 "passed" if complete else "in_progress", timestamp if complete else None, *self.store._key_values(access)))
        return access

    def rows(self, table="learner_course_progress"):
        with self.store._connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM " + table)]

    def resolve(self, session=None, trainee=None):
        return migration.resolve_session(session or self.session, trainee or self.trainee, self.store)

    def test_unstarted_full_path_becomes_105_hours_without_fabricating_activity(self):
        before = copy.deepcopy(self.session)
        view = self.resolve()
        self.assertEqual(sum(module["required_minutes"] for module in assigned_modules(view)), 6300)
        self.assertEqual({module["course_version"] for module in assigned_modules(view)}, {migration.VERSION})
        self.assertEqual(self.session, before)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.rows("tracking_sessions"), [])
        self.assertEqual(self.rows("tracking_events"), [])
        self.assertEqual(view[migration.META_KEY]["status"], "migrated")
        self.assertEqual(len(self.rows(migration.TABLE)), 1)

    def test_copy_preserves_exact_seconds_timestamps_answers_and_videos_without_new_completions(self):
        self.seed(complete=True)
        before = self.rows()[0]
        view = self.resolve()
        original = next(row for row in self.rows() if row["course_version"] == migration.BASE_VERSION)
        target = next(row for row in self.rows() if row["course_version"] == migration.VERSION)
        for key in ("completed_json", "answers_json", "video_progress_json", "active_seconds", "started_at", "updated_at"):
            self.assertEqual(target[key], before[key], key)
            self.assertEqual(original[key], before[key], key)
        self.assertEqual(target["active_seconds"], 125.125)
        self.assertIsNone(target["completed_at"])
        self.assertEqual(original["completed_at"], before["completed_at"])
        self.assertEqual(target["status"], "awaiting_time")
        self.assertEqual(target["current_activity_id"], "a-quiz")
        self.assertFalse(any("production" in activity_id for activity_id in json.loads(target["completed_json"])))
        effective_course = self.course("academy-vtc-a", migration.VERSION)
        effective_course["required_minutes"] = assigned_modules(view)[0]["required_minutes"]
        progress = project_progress(self.store._serialize_progress(target), effective_course)
        self.assertFalse(progress["module_complete"])

    def test_original_tracking_ledger_is_not_copied_and_a_delayed_old_heartbeat_cannot_credit(self):
        access = self.seed()
        tracking_id = self.store.start_tracking(access, tab_id="old-tab", activity_id="a-quiz", now_epoch=1000)["tracking_session_id"]
        heartbeat = dict(activity_id="a-quiz", visible=True, focused=True, recent_activity=True, media_playing=False)
        self.store.heartbeat(access, tracking_id, now_epoch=1000, **heartbeat)
        self.store.heartbeat(access, tracking_id, now_epoch=1010, **heartbeat)
        original_time = self.rows()[0]["active_seconds"]
        old_connections = self.rows("tracking_sessions")
        old_events = self.rows("tracking_events")
        view = self.resolve()
        connections = self.rows("tracking_sessions")
        self.assertEqual(len(connections), len(old_connections))
        for key in ("id", "created_at", "last_seen_at", "last_seen_epoch", "credited_seconds", "course_version"):
            self.assertEqual(connections[0][key], old_connections[0][key])
        self.assertEqual(connections[0]["status"], "ended")
        self.assertEqual(connections[0]["ended_at"], old_connections[0]["last_seen_at"])
        self.assertEqual(self.rows("tracking_events"), old_events)
        late = self.store.heartbeat(access, tracking_id, now_epoch=1020, **heartbeat)
        self.assertTrue(late["ended"])
        self.assertEqual(late["credited_seconds"], 0)
        self.assertEqual({row["active_seconds"] for row in self.rows()}, {original_time})
        self.assertEqual(migration.lineage_versions(view, "academy-vtc-a"), [migration.VERSION, migration.BASE_VERSION])

    def test_fully_completed_path_stays_pinned_and_evidence_is_untouched(self):
        for letter in "abcdefgh":
            self.seed(letter, seconds=600, complete=True)
        before = self.rows()
        view = self.resolve()
        self.assertEqual(assigned_modules(view), assigned_modules(self.session))
        self.assertEqual(view[migration.META_KEY]["status"], "completed_preserved")
        self.assertEqual(self.rows(), before)
        self.assertEqual(migration.lineage_versions(view, "academy-vtc-a"), [migration.BASE_VERSION])
        self.assertEqual(migration.read_transition_session(self.session, self.trainee, self.path), view)

    def test_recorded_passed_status_alone_does_not_hide_missing_time_or_video_work(self):
        for variant in ("time", "video"):
            with self.subTest(variant=variant):
                person = {"id": "person-" + variant}
                for letter in "abcdefgh":
                    self.seed(letter, seconds=599 if variant == "time" else 600, complete=True,
                              video_complete=variant != "video", trainee_id=person["id"])
                view = self.resolve(trainee=person)
                self.assertEqual(view[migration.META_KEY]["status"], "migrated")

    def test_partial_mixed_older_or_revoked_paths_are_never_expanded(self):
        variants = []
        value = copy.deepcopy(self.session); value["aps_native_modules"][0]["section_ids"] = ["vtc-a-01"]; variants.append(value)
        value = copy.deepcopy(self.session); value["aps_native_modules"][0]["course_version"] = "20261010-vtc-v6-pedagogie"; variants.append(value)
        value = copy.deepcopy(self.session); value["aps_native_modules"].pop(); variants.append(value)
        value = copy.deepcopy(self.session); value["aps_native_modules"] = []; variants.append(value)
        value = copy.deepcopy(self.session); value["training_type"] = "APS"; variants.append(value)
        value = copy.deepcopy(self.session); value["aps_native_modules"][0]["course_id"] = "academy-aps62-01"; variants.append(value)
        for value in variants:
            with self.subTest(value=value):
                self.assertIs(migration.resolve_session(value, self.trainee, self.store), value)
        with self.store._connect() as connection:
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name=?", (migration.TABLE,)).fetchone())
        self.assertEqual(self.rows(), [])

    def test_changed_video_or_question_content_is_not_assumed_equivalent(self):
        for variant in ("video", "question"):
            def loader(course_id, version):
                result = self.course(course_id, version)
                if version == migration.VERSION:
                    if variant == "video":
                        result["sections"][0]["activities"][0]["blocks"][0]["video"]["duration_seconds"] = 20
                    else:
                        result["sections"][1]["activities"][0]["answer"] = "changed"
                return result
            with self.subTest(variant=variant), patch("elearning_native.vtc.load_bundled_course", side_effect=loader):
                self.assertIs(self.resolve(), self.session)
        self.assertEqual(self.rows(), [])

    def test_only_the_authored_v12_supplement_notice_can_change(self):
        for variant in ("expected_notice", "unknown_notice", "changed_content"):
            def loader(course_id, version):
                result = self.course(course_id, version)
                lesson = result["sections"][0]["activities"][0]
                lesson["vtc"] = {"kind": "supplements", "notice": "Les entraînements en ligne se font sans rédaction."}
                if version == migration.VERSION:
                    lesson["vtc"]["notice"] = migration.NOTICE
                    if variant == "unknown_notice":
                        lesson["vtc"]["notice"] = "Une autre édition pédagogique."
                    elif variant == "changed_content":
                        lesson["blocks"].append({"type": "text", "text": "Un nouvel apprentissage obligatoire."})
                return result
            with self.subTest(variant=variant), patch("elearning_native.vtc.load_bundled_course", side_effect=loader):
                view = self.resolve(trainee={"id": variant})
                if variant == "expected_notice":
                    self.assertEqual(view[migration.META_KEY]["status"], "migrated")
                else:
                    self.assertIs(view, self.session)
        self.assertEqual(len(self.rows(migration.TABLE)), 1)
        self.assertEqual(self.rows(), [])

    def test_restart_is_idempotent_and_never_recopies_old_time_over_new_work(self):
        self.seed()
        first = self.resolve()
        target_access = self.access(version=migration.VERSION)
        with self.store._transaction() as connection:
            connection.execute("""UPDATE learner_course_progress SET active_seconds=888.125, completed_json=?
                WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?""",
                (json.dumps(["a-lesson", "vtc-a-production-01"]), *self.store._key_values(target_access)))
        restarted = NativeElearningStore(self.path)
        second = migration.resolve_session(self.session, self.trainee, restarted)
        self.assertEqual(first, second)
        self.assertEqual(len(self.rows(migration.TABLE)), 1)
        self.assertEqual(len(self.rows()), 2)
        target = next(row for row in self.rows() if row["course_version"] == migration.VERSION)
        self.assertEqual(target["active_seconds"], 888.125)
        self.assertIn("vtc-a-production-01", json.loads(target["completed_json"]))

    def test_unproved_nonempty_target_is_not_merged_or_overwritten(self):
        self.seed(seconds=100)
        self.seed(seconds=50, version=migration.VERSION)
        before = self.rows()
        view = self.resolve()
        self.assertEqual(view[migration.META_KEY]["status"], "manual_review")
        self.assertEqual(assigned_modules(view), assigned_modules(self.session))
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.rows(migration.TABLE), [])

    def test_transition_lookup_is_bound_to_current_scope_order_and_required_minutes(self):
        self.seed()
        self.resolve()
        for variant in ("section", "module", "time", "order"):
            changed = copy.deepcopy(self.session)
            if variant == "section":
                changed["aps_native_modules"][0]["section_ids"] = ["vtc-a-01"]
            elif variant == "module":
                changed["aps_native_modules"].pop()
            elif variant == "time":
                changed["aps_native_modules"][0]["required_minutes"] = 20
            else:
                changed["aps_native_modules"].reverse()
            with self.subTest(variant=variant):
                self.assertIs(migration.read_transition_session(changed, self.trainee, self.path), changed)
        revoked = {**self.session, "aps_native_modules": []}
        self.assertIs(migration.resolve_session(revoked, self.trainee, self.store), revoked)

    def test_read_only_lookup_creates_neither_database_nor_transition_schema(self):
        absent = Path(self.directory.name) / "never-created" / "tracking.sqlite3"
        self.assertIs(migration.read_transition_session(self.session, self.trainee, absent), self.session)
        self.assertFalse(absent.parent.exists())
        before = self.path.read_bytes()
        self.assertIs(migration.resolve_session(self.session, self.trainee, self.path, migrate=False), self.session)
        self.assertEqual(self.path.read_bytes(), before)
        with sqlite3.connect(self.path) as connection:
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name=?", (migration.TABLE,)).fetchone())

    def test_failure_during_copy_rolls_back_the_whole_transition(self):
        self.seed("a"); self.seed("b")
        before = self.rows()
        original_copy = migration._copy_progress
        calls = []
        def fail_second(connection, source, target):
            calls.append(source["course_id"])
            if len(calls) == 2:
                raise RuntimeError("simulated database failure")
            return original_copy(connection, source, target)
        with patch.object(migration, "_copy_progress", side_effect=fail_second), self.assertRaises(RuntimeError):
            self.resolve()
        self.assertEqual(self.rows(), before)
        self.assertIs(migration.read_transition_session(self.session, self.trainee, self.path), self.session)

    def test_lineage_and_dominance_never_cross_learners_or_unassigned_modules(self):
        self.seed()
        self.seed(trainee_id="another-person")
        view = self.resolve()
        rows = self.store.learner_progress(self.session["id"], self.trainee["id"])
        other = self.store.learner_progress(self.session["id"], "another-person")
        filtered = migration.current_progress_rows(view, rows + other)
        self.assertEqual(len(filtered), 2)
        self.assertEqual({row["course_version"] for row in filtered if row["trainee_id"] == "learner-1"}, {migration.VERSION})
        self.assertEqual({row["course_version"] for row in filtered if row["trainee_id"] == "another-person"}, {migration.BASE_VERSION})
        self.assertEqual(migration.lineage_versions(view, "academy-aps62-01"), [])
        self.assertIs(migration.read_transition_session(self.session, {"id": "another-person"}, self.path), self.session)
        removed = {**view, "aps_native_modules": assigned_modules(view)[1:]}
        self.assertEqual(migration.lineage_versions(removed, "academy-vtc-a"), [])

    def test_full_selection_order_and_custom_module_titles_are_preserved(self):
        changed = copy.deepcopy(self.session)
        changed["aps_native_modules"].reverse()
        changed["aps_native_modules"][0]["section_ids"].reverse()
        changed["aps_native_modules"][0]["title"] = "Mon premier module choisi"
        view = self.resolve(session=changed)
        self.assertEqual([module["course_id"] for module in assigned_modules(view)], [module["course_id"] for module in assigned_modules(changed)])
        self.assertEqual(assigned_modules(view)[0]["title"], "Mon premier module choisi")
        self.assertEqual(assigned_modules(view)[0]["section_ids"], assigned_modules(changed)[0]["section_ids"])

    def test_implicit_all_sections_has_the_same_meaning_as_path_projection(self):
        changed = copy.deepcopy(self.session)
        changed["aps_native_modules"][0]["section_ids"] = None
        changed["aps_native_modules"][1].pop("section_ids")
        view = self.resolve(session=changed)
        self.assertEqual(view[migration.META_KEY]["status"], "migrated")
        self.assertEqual(assigned_modules(view)[0]["section_ids"], ["vtc-a-01", "vtc-a-02"])

    def test_an_unexpected_old_key_cannot_validate_a_new_production(self):
        access = self.seed()
        with self.store._transaction() as connection:
            connection.execute("""UPDATE learner_course_progress SET completed_json=?,answers_json=?
                WHERE session_id=? AND trainee_id=? AND course_id=? AND course_version=?""",
                (json.dumps(["a-lesson", "vtc-a-production-01"]),
                 json.dumps({"vtc-a-production-01": {"production_ai_feedback": {"score": 20}}}),
                 *self.store._key_values(access)))
        self.resolve()
        rows = {row["course_version"]: row for row in self.rows()}
        self.assertIn("vtc-a-production-01", json.loads(rows[migration.BASE_VERSION]["completed_json"]))
        self.assertNotIn("vtc-a-production-01", json.loads(rows[migration.VERSION]["completed_json"]))
        self.assertNotIn("vtc-a-production-01", json.loads(rows[migration.VERSION]["answers_json"]))


if __name__ == "__main__":
    unittest.main()
