"""Versioned CMA-format VTC papers, server clocks and isolated attempts.

This module does not change curriculum completion, time tracking or final exams.
Mutable attempts live in SQLite; neither deadlines nor marks come from clients.
"""
from __future__ import annotations

import copy
import json
import math
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path


CURRENT_VERSION = "20261012-cma-v1"
BANK_ROOT = Path(__file__).parent / "vtc" / "cma"
LETTERS = tuple("ABCDEFG")
RETRYABLE_CORRECTION_MESSAGE = "La correction doit être vérifiée à nouveau. Votre copie est conservée ; vous pouvez relancer cette matière."
_SPECS = ((45, 3, 6, 10, 5, 1, 2), (45, 2, 6, 16, 2, 1, 2),
          (30, 3, 6, 20, 0, 1, 0), (30, 2, 6, 7, 3, 2, 2),
          (30, 1, 4, 20, 0, 1, 0), (30, 3, 6, 12, 4, 1, 2),
          (20, 3, 6, 6, 2, 2, 4))


class CmaError(ValueError):
    def __init__(self, message, *, code="invalid", status=400):
        super().__init__(message)
        self.code, self.status = code, status


@lru_cache(maxsize=8)
def _load_bank(version):
    if not re.fullmatch(r"[a-zA-Z0-9-]{8,80}", version):
        raise CmaError("Édition du sujet inconnue.", status=404)
    try:
        bank = json.loads((BANK_ROOT / f"{version}.json").read_text())
    except FileNotFoundError as exc:
        raise CmaError("Cette édition du sujet n’est plus disponible.", status=404) from exc
    validate_bank(bank)
    return bank


def load_bank(version=CURRENT_VERSION):
    return copy.deepcopy(_load_bank(version))


def validate_bank(bank):
    """Fail closed on an accidentally malformed scoring edition."""
    assert tuple(s["id"] for s in bank["subjects"]) == LETTERS
    assert bank["minutes"] == 230 and bank["coefficient_total"] == 17
    seen = set()
    for subject, spec in zip(bank["subjects"], _SPECS):
        assert tuple(subject[k] for k in ("minutes", "coefficient", "minimum", "qcm_count",
                                         "qrc_count", "qcm_points", "qrc_points")) == spec
        questions = subject["questions"]
        assert sum(q["max_points"] for q in questions) == 20
        assert sum(q["kind"] == "qcm" for q in questions) == subject["qcm_count"]
        assert sum(q["kind"] == "qrc" for q in questions) == subject["qrc_count"]
        for q in questions:
            assert q["id"] not in seen
            seen.add(q["id"])
            assert q["prompt"] and q["lesson_refs"]
            if q["kind"] == "qcm":
                ids = [o["id"] for o in q["options"]]
                assert len(ids) == len(set(ids)) and set(q["answers"]) <= set(ids)
                assert q["answers"] and (q.get("multiple") or len(q["answers"]) == 1)
            else:
                assert q["model_response"] and q["rubric"]
                assert sum(c["max_points"] for c in q["rubric"]) == q["max_points"]
                assert all(c["field_ids"] == [q["id"]] for c in q["rubric"])
        if subject["id"] == "D":
            assert 15 <= len(subject["passage_lines"]) <= 20
    assert len(seen) == 107


def subject_for(bank, letter):
    found = next((s for s in bank["subjects"] if s["id"] == letter), None)
    if found is None:
        raise CmaError("Matière inconnue.", status=404)
    return found


def public_subject(subject):
    """Explicit allowlist: answer keys, rubrics and model responses stay private."""
    public = {k: copy.deepcopy(subject[k]) for k in (
        "id", "title", "minutes", "coefficient", "minimum", "qcm_count", "qrc_count",
        "qcm_points", "qrc_points", "passage_title", "passage_lines") if k in subject}
    public["questions"] = [{k: copy.deepcopy(q[k]) for k in
                            ("id", "kind", "prompt", "options", "multiple", "max_points", "max_chars")
                            if k in q} for q in subject["questions"]]
    return public


def _public_notice(bank):
    return bank["notice"].replace(
        "Les QRC sont évaluées selon un barème explicite ; un doute de correction appelle une vérification par l’équipe pédagogique.",
        "Les réponses courtes sont évaluées selon un barème explicite. Une analyse complémentaire est lancée si nécessaire.")


def public_bank(bank, *, questions=False):
    public = {k: copy.deepcopy(bank[k]) for k in (
        "id", "version", "title", "reviewed_at", "minutes", "question_count", "qcm_count",
        "qrc_count", "coefficient_total", "sources", "notice", "qcm_scoring_notice",
        "timing_notice", "extra_training")}
    public["subjects"] = [public_subject(s) for s in bank["subjects"]]
    public["notice"] = _public_notice(bank)
    public["timing_notice"] = ("Chaque matière dispose de son propre chronomètre. Utilisez « Mettre en pause » "
                               "avant de quitter la page pour conserver le temps restant et revenir plus tard. "
                               "À l’échéance, la dernière sauvegarde constitue votre copie. "
                               "Les 3 h 50 correspondent au temps maximal d’épreuve, hors pauses.")
    if not questions:
        for subject in public["subjects"]:
            for key in ("questions", "passage_title", "passage_lines"):
                subject.pop(key, None)
    return public


def normalize_answers(subject, answers):
    if not isinstance(answers, dict):
        raise CmaError("La copie doit contenir un objet de réponses.")
    questions = {q["id"]: q for q in subject["questions"]}
    if set(answers) - set(questions):
        raise CmaError("La copie contient une question étrangère à cette matière.")
    clean = {}
    for qid, value in answers.items():
        q = questions[qid]
        if q["kind"] == "qrc":
            if not isinstance(value, str) or len(value) > q["max_chars"] or "\x00" in value:
                raise CmaError("Une réponse rédigée est invalide ou trop longue.")
            clean[qid] = value.strip()
        else:
            if (not isinstance(value, list) or any(not isinstance(v, str) for v in value)
                    or len(value) != len(set(value))
                    or set(value) - {o["id"] for o in q["options"]}
                    or (not q.get("multiple") and len(value) > 1)):
                raise CmaError("Sélection de QCM invalide.")
            clean[qid] = value
    return clean


def qrc_assignment(bank, subject):
    questions = [q for q in subject["questions"] if q["kind"] == "qrc"]
    brief = "Réponses courtes de la simulation VTC. Noter uniquement les éléments du barème ; accepter les formulations équivalentes. Une réponse vide vaut zéro."
    if subject.get("passage_lines"):
        brief += "\nTexte support :\n" + "\n".join(subject["passage_lines"])
    sources = {source["url"]: source for q in questions for source in q.get("sources", [])}
    return {
        "id": f"{bank['version']}-{subject['id']}-qrc", "title": subject["title"], "brief": brief,
        "grading_context": "cma_simulation",
        "response_fields": [{"id": q["id"], "label": f"Question {q['id']} · {q['max_points']} points", "instructions": q["prompt"],
                             "min_chars": 0, "max_chars": q["max_chars"], "required": False} for q in questions],
        "rubric": [copy.deepcopy(c) for q in questions for c in q["rubric"]],
        "model_response": {q["id"]: q["model_response"] for q in questions},
        "sources": list(sources.values()), "spelling_review": subject["id"] == "D",
        "revision_targets": [{"id": ref, "title": f"Leçon {ref}", "course_id": "academy-vtc-" + ref[0].lower(),
                              "section_id": "vtc-" + ref.lower().replace(".", "-")} for ref in
                             sorted({ref for q in questions for ref in q["lesson_refs"]})],
    }


def needs_ai(subject, answers):
    return any(q["kind"] == "qrc" and str(answers.get(q["id"]) or "").strip() for q in subject["questions"])


def _verified_correction(correction, letter):
    """Only a checked result is reusable; legacy review flags are not a grade."""
    if (not isinstance(correction, dict) or correction.get("status") != "corrected"
            or correction.get("subject") != letter):
        return False
    score = correction.get("score")
    if (not isinstance(score, (int, float)) or isinstance(score, bool)
            or not math.isfinite(score) or not 0 <= score <= 20
            or type(correction.get("minimum_met")) is not bool):
        return False
    written = [q for q in correction.get("corrections", []) if q.get("kind") == "qrc"]
    ai = correction.get("ai_feedback")
    if any(str(q.get("selected") or "").strip() for q in written) and not isinstance(ai, dict):
        return False
    if ai is not None and (not isinstance(ai, dict) or ai.get("status") != "corrected"
                           or ai.get("needs_human_review") or ai.get("human_review_reasons")):
        return False
    if ai and any(item.get("status") == "uncertain" for item in ai.get("criteria", [])):
        return False
    for question in written:
        for item in [question, *question.get("criteria", [])]:
            points, maximum = item.get("points"), item.get("max_points")
            if (item.get("status") == "uncertain" or not isinstance(points, (int, float))
                    or isinstance(points, bool) or not math.isfinite(points)
                    or not isinstance(maximum, (int, float)) or isinstance(maximum, bool)
                    or not math.isfinite(maximum) or not 0 <= points <= maximum):
                return False
    if correction.get("subject") == "D" and ai:
        count, errors = ai.get("spelling_error_count"), ai.get("spelling_errors")
        if (ai.get("spelling_review_complete") is not True or type(count) is not int
                or count < 0 or not isinstance(errors, list) or count != len(errors)):
            return False
    return True


def grade_subject(bank, letter, answers, *, qrc_grader=None, allow_pending=False):
    subject = subject_for(bank, letter)
    answers = normalize_answers(subject, answers)
    qcm_score, corrections = 0, []
    for q in subject["questions"]:
        if q["kind"] != "qcm":
            continue
        selected = answers.get(q["id"], [])
        correct = set(selected) == set(q["answers"])
        points = q["max_points"] if correct else 0
        qcm_score += points
        corrections.append({**copy.deepcopy(q), "selected": selected, "correct": correct, "points": points})
    written = [q for q in subject["questions"] if q["kind"] == "qrc"]
    ai_result = None
    if needs_ai(subject, answers):
        if qrc_grader is None:
            if not allow_pending:
                from .vtc_ai import grade_written_work
                qrc_grader = grade_written_work
        if qrc_grader:
            assignment = qrc_assignment(bank, subject)
            ai_result = qrc_grader(assignment, {q["id"]: answers.get(q["id"], "") for q in written})
    pending = needs_ai(subject, answers) and ai_result is None
    review = bool(ai_result and (ai_result.get("needs_human_review") or ai_result.get("status") != "corrected"))
    criteria = {c["id"]: c for c in (ai_result or {}).get("criteria", [])}
    qrc_score = 0
    for q in written:
        marks = []
        for rubric in q["rubric"]:
            item = copy.deepcopy(criteria.get(rubric["id"], {}))
            raw = item.get("points")
            empty = not answers.get(q["id"], "").strip()
            if empty:
                points = 0
                item.update(feedback="Aucune réponse remise pour cette question.", improvement=rubric["expected"])
            elif isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw) and 0 <= raw <= rubric["max_points"]:
                points = float(raw)
            else:
                points = None
                if not pending:
                    review = True
            item.update(id=rubric["id"], label=rubric["label"], max_points=rubric["max_points"],
                        points=points, expected=rubric["expected"], partial_guidance=rubric["partial_guidance"])
            marks.append(item)
        points = None if any(c["points"] is None for c in marks) else round(sum(c["points"] for c in marks), 2)
        if points is not None:
            qrc_score += points
        corrections.append({"id": q["id"], "kind": "qrc", "prompt": q["prompt"], "max_points": q["max_points"],
                            "points": points, "selected": answers.get(q["id"], ""), "criteria": marks,
                            "model_response": q["model_response"], "lesson_refs": q["lesson_refs"],
                            "sources": q.get("sources", []), "origin": q["origin"]})
    spelling_count, penalty = 0, 0
    if letter == "D" and ai_result:
        spelling_count = ai_result.get("spelling_error_count")
        spelling_errors = ai_result.get("spelling_errors", [])
        if (ai_result.get("spelling_review_complete") is not True
                or not isinstance(spelling_count, int) or isinstance(spelling_count, bool) or spelling_count < 0
                or not isinstance(spelling_errors, list) or spelling_count != len(spelling_errors)):
            review, spelling_count = True, None
        elif not review:
            penalty = int(spelling_count > 5)
    if any(q["kind"] == "qrc" and q["points"] is None for q in corrections):
        score = None
    else:
        score = round(max(0, min(20, qcm_score + qrc_score - penalty)), 2)
    result = {"subject": letter, "title": subject["title"], "coefficient": subject["coefficient"],
            "minimum": subject["minimum"], "qcm_score": qcm_score, "qrc_score": None if pending else round(qrc_score, 2),
            "score": score, "max_score": 20, "minimum_met": score >= subject["minimum"] if score is not None and not review else None,
            "status": "pending_correction" if pending else "needs_human_review" if review else "corrected",
            "spelling_error_count": spelling_count if letter == "D" else None, "spelling_penalty": penalty,
            "spelling_errors": copy.deepcopy((ai_result or {}).get("spelling_errors", [])),
            "corrections": corrections, "ai_feedback": copy.deepcopy(ai_result),
            "lesson_refs": sorted({ref for q in corrections if q["points"] is None or q["points"] < q["max_points"] for ref in q["lesson_refs"]})}
    if (pending and not allow_pending) or (not pending and not _verified_correction(result, letter)):
        # The correction engine performs its bounded second analysis. An
        # incomplete response must still remain retryable at this boundary.
        from .vtc_ai import VtcAIError
        raise VtcAIError("invalid_response")
    return result


def result_for(bank, state):
    if state["status"] != "submitted":
        return None
    rows = []
    for letter in LETTERS:
        part = state["parts"][letter]
        row = copy.deepcopy(part.get("correction")) or grade_subject(bank, letter, part["answers"], allow_pending=True)
        if part.get("correction") and not _verified_correction(row, letter):
            # Keep the historical analysis as provisional evidence, even when
            # only its top-level review flag was changed in an older record.
            row.update(status="needs_human_review", minimum_met=None)
        row["delivery"] = part["status"]
        row["submitted_at"] = part.get("submitted_at")
        row["grading_status"] = part.get("grading_status", "pending") if row["status"] in {
            "pending_correction", "needs_human_review"} else row["status"]
        row["grading_error"] = part.get("grading_error")
        rows.append(row)
    pending = [row["subject"] for row in rows if row["status"] == "pending_correction"]
    review = [row["subject"] for row in rows if row["status"] == "needs_human_review"]
    # Compare the unrounded weighted sum: 9.995 must not become admissible.
    weighted_sum = sum(row["score"] * row["coefficient"] for row in rows) if all(row["score"] is not None for row in rows) else None
    average = round(weighted_sum / 17, 2) if weighted_sum is not None else None
    passed = weighted_sum >= 170 and all(row["minimum_met"] for row in rows) if not pending and not review else None
    return {"subjects": rows, "weighted_average": average if not pending and not review else None,
            "provisional_average": average, "passed": passed,
            "status": "pending_correction" if pending else "needs_human_review" if review else "admissible" if passed else "not_admissible",
            "pending_subjects": pending, "review_subjects": review,
            "failed_minima": [r["subject"] for r in rows if r["minimum_met"] is False],
            "notice": _public_notice(bank)}


def _utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _expire(state, now):
    for part in state["parts"].values():
        if part["status"] == "running" and now >= part["deadline"]:
            part.update(status="expired", submitted_at=_utc(part["deadline"]), revision=part["revision"] + 1)
    if all(p["status"] in {"submitted", "expired"} for p in state["parts"].values()):
        state["status"] = "submitted"


def _next_letter(state):
    return next((letter for letter in LETTERS if state["parts"][letter]["status"] in {"running", "paused", "not_started"}), None)


def public_attempt(bank, state, *, now=None):
    now = time.time() if now is None else now
    current = _next_letter(state)
    parts = [{"subject": letter, **{k: copy.deepcopy(part[k]) for k in
              ("status", "started_at", "deadline", "submitted_at", "revision", "remaining_seconds") if k in part}}
             for letter, part in state["parts"].items()]
    public = {"id": state["id"], "version": state["version"], "created_at": state["created_at"],
              "status": state["status"], "server_now": now, "current_subject": current, "parts": parts}
    if current and state["parts"][current]["status"] in {"running", "paused"}:
        public["paper"] = public_subject(subject_for(bank, current))
        public["answers"] = copy.deepcopy(state["parts"][current]["answers"])
    if state["status"] == "submitted":
        public["result"] = result_for(bank, state)
    return public


def learner_attempt_summaries(db_path, session_id, trainee_id, *, limit=30):
    """Read-only, owner-scoped report; no answers, keys, DDL or provider calls.

    Each item contains attempt_id/version/created_at/status/current_subject,
    submitted_subjects/exam_seconds, result_status/weighted_average/
    provisional_average/passed/failed_minima/pending_subjects/review_subjects,
    and subjects[{id,title,status,submitted_at,score,max_score,coefficient,
    minimum,minimum_met,grading_status}]. Missing database/table returns [].
    exam_seconds describes supplementary exam time, never curriculum time.
    """
    path = Path(db_path).resolve()
    if not path.is_file() or not session_id or not trainee_id:
        return []
    limit = min(100, max(1, limit if isinstance(limit, int) and not isinstance(limit, bool) else 30))
    db = None
    try:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='vtc_cma_attempts'").fetchone()
        if not exists:
            return []
        rows = db.execute("SELECT attempt_id, version, created_at, state_json FROM vtc_cma_attempts WHERE session_id=? AND trainee_id=? ORDER BY created_at DESC LIMIT ?",
                          (str(session_id), str(trainee_id), limit)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        if db is not None:
            db.close()
    summaries, now = [], time.time()
    for row in rows:
        try:
            state = json.loads(row["state_json"])
            bank = load_bank(row["version"])
            _expire(state, now)  # derive clock state in memory; never persist in reports
            result = result_for(bank, state)
            results = {part["subject"]: part for part in (result or {}).get("subjects", [])}
            subjects, seconds = [], 0
            for spec in bank["subjects"]:
                letter = spec["id"]
                part, grade = state["parts"][letter], results.get(letter, {})
                if part.get("started_at") is not None:
                    end = (part["paused_at"] if part["status"] == "paused" else
                           datetime.fromisoformat(part["submitted_at"]).timestamp() if part.get("submitted_at") else now)
                    seconds += max(0, min(spec["minutes"] * 60, int(end - part["started_at"] - part.get("paused_seconds", 0))))
                subjects.append({"id": letter, "title": spec["title"], "status": part["status"],
                                 "submitted_at": part.get("submitted_at"), "score": grade.get("score"),
                                 "max_score": 20, "coefficient": spec["coefficient"], "minimum": spec["minimum"],
                                 "minimum_met": grade.get("minimum_met"), "grading_status": grade.get("grading_status", "not_started")})
            summaries.append({"attempt_id": row["attempt_id"], "version": row["version"],
                              "created_at": _utc(row["created_at"]), "status": state["status"],
                              "current_subject": _next_letter(state), "subjects": subjects,
                              "submitted_subjects": sum(p["status"] in {"submitted", "expired"} for p in subjects),
                              "exam_seconds": seconds, "result_status": (result or {}).get("status", "in_progress"),
                              "weighted_average": (result or {}).get("weighted_average"),
                              "provisional_average": (result or {}).get("provisional_average"),
                              "passed": (result or {}).get("passed"), "failed_minima": (result or {}).get("failed_minima", []),
                              "pending_subjects": (result or {}).get("pending_subjects", []),
                              "review_subjects": (result or {}).get("review_subjects", [])})
        except (ValueError, KeyError, TypeError, AssertionError, OverflowError):
            # A damaged/retired edition remains visible, without inventing results.
            summaries.append({"attempt_id": row["attempt_id"], "version": row["version"],
                              "created_at": _utc(row["created_at"]), "status": "unavailable", "result_status": "unavailable",
                              "current_subject": None, "submitted_subjects": 0, "exam_seconds": 0, "subjects": [],
                              "weighted_average": None, "provisional_average": None, "passed": None,
                              "failed_minima": [], "pending_subjects": [], "review_subjects": []})
    return summaries


class CmaStore:
    """SQLite transactions serialize saves, deadlines, duplicate starts and grading."""
    def __init__(self, path, *, clock=None):
        self.path = Path(path)
        self.clock = clock or time.time
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS vtc_cma_attempts (
                attempt_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, trainee_id TEXT NOT NULL,
                version TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
                updated_at REAL NOT NULL, state_json TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS vtc_cma_owner ON vtc_cma_attempts(session_id, trainee_id, created_at)")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _owned(self, db, session_id, trainee_id, attempt_id):
        if not isinstance(attempt_id, str) or not re.fullmatch(r"[a-f0-9]{32}", attempt_id):
            raise CmaError("Tentative introuvable.", status=404)
        row = db.execute("SELECT state_json FROM vtc_cma_attempts WHERE attempt_id=? AND session_id=? AND trainee_id=?",
                         (attempt_id, str(session_id), str(trainee_id))).fetchone()
        if not row:
            raise CmaError("Tentative introuvable.", status=404)
        return json.loads(row["state_json"])

    def _write(self, db, state, now):
        db.execute("UPDATE vtc_cma_attempts SET status=?, updated_at=?, state_json=? WHERE attempt_id=?",
                   (state["status"], now, json.dumps(state, ensure_ascii=False), state["id"]))

    @staticmethod
    def _begin(state, letter, now, bank):
        if _next_letter(state) != letter:
            raise CmaError("Terminez la matière en cours avant de commencer la suivante.", status=409)
        part = state["parts"][letter]
        if part["status"] == "not_started":
            part.update(status="running", started_at=now, deadline=now + subject_for(bank, letter)["minutes"] * 60)

    def create(self, session_id, trainee_id, *, version=CURRENT_VERSION):
        bank, now = load_bank(version), self.clock()
        with self._db() as db:
            row = db.execute("SELECT state_json FROM vtc_cma_attempts WHERE session_id=? AND trainee_id=? AND status='active' ORDER BY created_at DESC LIMIT 1",
                             (str(session_id), str(trainee_id))).fetchone()
            if row:
                state = json.loads(row["state_json"])
                _expire(state, now)
                self._write(db, state, now)
                return state
            state = {"id": secrets.token_hex(16), "version": version, "status": "active", "created_at": _utc(now),
                     "parts": {letter: {"status": "not_started", "revision": 0, "answers": {}, "correction": None,
                                        "grading_status": "pending"} for letter in LETTERS}}
            self._begin(state, "A", now, bank)
            db.execute("INSERT INTO vtc_cma_attempts VALUES (?,?,?,?,?,?,?,?)",
                       (state["id"], str(session_id), str(trainee_id), version, state["status"], now, now,
                        json.dumps(state, ensure_ascii=False)))
            return state

    def read(self, session_id, trainee_id, attempt_id):
        now = self.clock()
        with self._db() as db:
            state = self._owned(db, session_id, trainee_id, attempt_id)
            _expire(state, now)
            self._write(db, state, now)
            return state

    def start_part(self, session_id, trainee_id, attempt_id, letter):
        now = self.clock()
        with self._db() as db:
            state = self._owned(db, session_id, trainee_id, attempt_id)
            _expire(state, now)
            self._begin(state, letter, now, load_bank(state["version"]))
            self._write(db, state, now)
            return state

    def save(self, session_id, trainee_id, attempt_id, letter, answers, revision, *, submit=False):
        now = self.clock()
        with self._db() as db:
            state = self._owned(db, session_id, trainee_id, attempt_id)
            bank = load_bank(state["version"])
            subject = subject_for(bank, letter)
            part = state["parts"][letter]
            _expire(state, now)
            # A late arrival never replaces the last saved copy, even on submit.
            if part["status"] in {"expired", "submitted"}:
                self._write(db, state, now)
                return state
            if part["status"] != "running" or _next_letter(state) != letter:
                raise CmaError("Reprenez cette matière avant de modifier ou valider vos réponses.", status=409)
            if not isinstance(revision, int) or isinstance(revision, bool) or revision != part["revision"]:
                raise CmaError("La copie a changé dans une autre page. Rechargez pour reprendre la dernière sauvegarde.", code="revision_conflict", status=409)
            part["answers"] = normalize_answers(subject, answers)
            part["revision"] += 1
            if submit:
                part.update(status="submitted", submitted_at=_utc(now))
            _expire(state, now)
            self._write(db, state, now)
            return state

    def control(self, session_id, trainee_id, attempt_id, letter, action, revision, *, answers=None):
        """Persist clock controls atomically with ownership and revision checks.

        Pausing saves the current draft in the same transaction as its remaining
        time. Reset is restricted to the current, unfinished paper and leaves it
        paused until the learner explicitly resumes. Old clients cannot replay
        answers or clock controls over a resumed/reset paper.
        """
        if action not in {"pause", "resume", "reset"}:
            raise CmaError("Action inconnue.")
        now = self.clock()
        with self._db() as db:
            state = self._owned(db, session_id, trainee_id, attempt_id)
            subject = subject_for(load_bank(state["version"]), letter)
            part = state["parts"][letter]
            _expire(state, now)
            if part["status"] in {"submitted", "expired"}:
                self._write(db, state, now)
                return state
            if _next_letter(state) != letter or part["status"] not in {"running", "paused"}:
                raise CmaError("Cette matière n’a pas commencé.", status=409)
            if not isinstance(revision, int) or isinstance(revision, bool) or revision != part["revision"]:
                raise CmaError("La copie a changé dans une autre page. Rechargez pour reprendre la dernière sauvegarde.", code="revision_conflict", status=409)
            if action == "pause":
                if part["status"] != "running":
                    raise CmaError("Cette matière est déjà en pause.", status=409)
                part["answers"] = normalize_answers(subject, answers)
                part.update(status="paused", paused_at=now, remaining_seconds=part.pop("deadline") - now)
            elif action == "resume":
                if part["status"] != "paused":
                    raise CmaError("Cette matière est déjà en cours.", status=409)
                part["paused_seconds"] = part.get("paused_seconds", 0) + max(0, now - part.pop("paused_at"))
                part.update(status="running", deadline=now + part.pop("remaining_seconds"))
            else:
                part = {"status": "paused", "started_at": now, "paused_at": now,
                        "remaining_seconds": subject["minutes"] * 60, "paused_seconds": 0,
                        "answers": {}, "correction": None, "grading_status": "pending", "revision": revision}
                state["parts"][letter] = part
            part["revision"] += 1
            self._write(db, state, now)
            return state

    @staticmethod
    def _grading_journal(part):
        history = part.setdefault("grading_history", [])
        if not isinstance(history, list) or any(not isinstance(entry, dict) for entry in history):
            raise CmaError("L’historique de correction doit être vérifié. Votre copie est conservée.", status=409)
        return history

    def claim_grading(self, session_id, trainee_id, attempt_id, letter):
        now = self.clock()
        with self._db() as db:
            state = self._owned(db, session_id, trainee_id, attempt_id)
            _expire(state, now)
            if state["status"] != "submitted":
                raise CmaError("Les corrigés s’ouvrent après remise des sept matières.", status=409)
            subject_for(load_bank(state["version"]), letter)
            part = state["parts"][letter]
            if _verified_correction(part.get("correction"), letter):
                return state, None
            if part.get("grading_status") == "working" and part.get("lease_until", 0) > now:
                raise CmaError("Cette correction est déjà en cours. Vous pouvez reprendre son résultat dans quelques instants.", code="grading_busy", status=409)
            history = self._grading_journal(part)
            previous = part.get("correction")
            if previous and not any(entry.get("correction") == previous for entry in history):
                # Legacy analyses have no reliable completion timestamp. Record
                # when they were preserved, without inventing a grading date.
                history.append({"status": "previous_correction", "recorded_at": _utc(now),
                                "correction": copy.deepcopy(previous)})
            old_claim = part.get("lease")
            if old_claim:
                old_entry = next((entry for entry in history if entry.get("claim") == old_claim), None)
                if old_entry is None:
                    old_entry = {"claim": old_claim}
                    history.append(old_entry)
                old_entry.update(status="expired", finished_at=_utc(now))
            claim = secrets.token_hex(16)
            history.append({"claim": claim, "status": "working", "started_at": _utc(now)})
            part.update(grading_status="working", lease=claim, lease_until=now + 120, grading_error=None)
            self._write(db, state, now)
            return state, claim

    def finish_grading(self, session_id, trainee_id, attempt_id, letter, claim, *, correction=None, error=None):
        now = self.clock()
        with self._db() as db:
            state = self._owned(db, session_id, trainee_id, attempt_id)
            subject_for(load_bank(state["version"]), letter)
            part = state["parts"][letter]
            if not isinstance(claim, str) or not re.fullmatch(r"[a-f0-9]{32}", claim):
                raise CmaError("Correction introuvable. Rechargez le bilan.", status=409)
            if part.get("lease") != claim:
                if not part.get("lease") and part.get("last_grading_claim") == claim:
                    # A transport retry cannot append history or replace the
                    # result of an already finished worker, even after restart.
                    return state
                raise CmaError("Une autre correction a repris cette matière. Rechargez le bilan.", status=409)
            history = self._grading_journal(part)
            entry = next((item for item in history if item.get("claim") == claim), None)
            if entry is None:
                # A worker started just before deployment may finish afterwards.
                entry = {"claim": claim}
                history.append(entry)
            entry["finished_at"] = _utc(now)
            if correction is not None:
                entry["correction"] = copy.deepcopy(correction)
            if _verified_correction(correction, letter):
                part.update(correction=copy.deepcopy(correction), grading_status="corrected", grading_error=None)
                entry.update(status="corrected")
            else:
                message = error or RETRYABLE_CORRECTION_MESSAGE
                part.update(grading_status="unavailable", grading_error=message)
                entry.update(status="unavailable", error=message)
            part["last_grading_claim"] = claim
            part.pop("lease", None)
            part.pop("lease_until", None)
            self._write(db, state, now)
            return state

    def history(self, session_id, trainee_id):
        with self._db() as db:
            rows = db.execute("SELECT attempt_id, version, status, created_at FROM vtc_cma_attempts WHERE session_id=? AND trainee_id=? ORDER BY created_at DESC LIMIT 30",
                              (str(session_id), str(trainee_id))).fetchall()
            return [{"id": row["attempt_id"], "version": row["version"], "status": row["status"], "created_at": _utc(row["created_at"])} for row in rows]
