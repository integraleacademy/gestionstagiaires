"""Behavioural coverage of the real CMA format, immutable copies and clocks."""
import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from elearning_native import vtc_cma as cma
from elearning_native.vtc_ai import _private_assignment


def full_answers(subject, *, written=True):
    return {q["id"]: copy.deepcopy(q["answers"]) if q["kind"] == "qcm" else q["model_response"] if written else ""
            for q in subject["questions"]}


def fake_grade(assignment, answers, *, ratio=1, review=False, spelling=0):
    criteria = [{"id": c["id"], "label": c["label"], "max_points": c["max_points"],
                 "points": c["max_points"] * ratio if any(answers.get(f, "").strip() for f in c["field_ids"]) else 0,
                 "feedback": "Éléments du barème contrôlés.", "improvement": "Reprendre les éléments manquants."}
                for c in assignment["rubric"]]
    return {"status": "needs_human_review" if review else "corrected", "needs_human_review": review,
            "score": sum(c["points"] for c in criteria), "max_score": sum(c["max_points"] for c in criteria),
            "criteria": criteria, "spelling_error_count": spelling,
            "spelling_errors": [{"field_id": assignment["response_fields"][0]["id"], "excerpt": "mot", "correction": "mots", "occurrence": i + 1} for i in range(spelling)],
            "spelling_review_complete": True, "model_response": assignment["model_response"], "next_steps": []}


@pytest.fixture
def timed_store(tmp_path):
    clock = [1_790_000_000.0]
    return cma.CmaStore(tmp_path / "tracking.sqlite3", clock=lambda: clock[0]), clock


def finish_papers(store, *, owner=("session", "trainee"), written=True):
    bank = cma.load_bank()
    state = store.create(*owner)
    for subject in bank["subjects"]:
        letter = subject["id"]
        if letter != "A":
            state = store.start_part(*owner, state["id"], letter)
        state = store.save(*owner, state["id"], letter, full_answers(subject, written=written), 0, submit=True)
    return state


def test_paper_matches_all_seven_official_compositions_and_real_written_rubrics():
    bank = cma.load_bank()
    cma.validate_bank(bank)
    assert sum(s["minutes"] for s in bank["subjects"]) == 230
    assert sum(s["coefficient"] for s in bank["subjects"]) == 17
    assert sum(s["qcm_count"] for s in bank["subjects"]) == 91
    assert sum(s["qrc_count"] for s in bank["subjects"]) == 16
    assert len(cma.subject_for(bank, "D")["passage_lines"]) == 18
    for subject in bank["subjects"]:
        if subject["qrc_count"]:
            private = _private_assignment(cma.qrc_assignment(bank, subject))
            assert len(private["response_fields"]) == subject["qrc_count"]
            assert all(not f["required"] and f["min_chars"] == 0 for f in private["response_fields"])
            assert all(not c["critical"] for c in private["rubric"])
            assert all(f["instructions"] for f in private["response_fields"])
    public = cma.public_bank(bank, questions=True)
    forbidden = {"answers", "answer", "rubric", "explanation", "model_response", "lesson_refs"}
    assert all(not forbidden.intersection(q) for s in public["subjects"] for q in s["questions"])
    assert all("questions" not in s for s in cma.public_bank(bank)["subjects"])


def test_all_correct_qcm_and_real_qrc_are_scored_to_twenty():
    bank = cma.load_bank()
    calls = []
    def grader(assignment, answers):
        calls.append(assignment["id"])
        return fake_grade(assignment, answers)
    for subject in bank["subjects"]:
        grade = cma.grade_subject(bank, subject["id"], full_answers(subject), qrc_grader=grader)
        assert grade["score"] == 20
        assert grade["status"] == "corrected" and grade["minimum_met"]
    assert len(calls) == 5  # grouped by subject, not sixteen provider calls


def test_partial_qrc_blank_fields_and_no_ai_for_empty_copies():
    bank = cma.load_bank()
    subject = cma.subject_for(bank, "G")
    answers = full_answers(subject)
    answers["G-qrc-02"] = ""
    result = cma.grade_subject(bank, "G", answers,
        qrc_grader=lambda a, b: fake_grade(a, b, ratio=.5))
    assert result["score"] == 14  # 12 QCM + 2/4 on QRC1 + blank QRC2
    assert result["corrections"][-1]["points"] == 0
    def never(*_):
        raise AssertionError("A blank copy must not call an AI")
    for letter in cma.LETTERS:
        assert cma.grade_subject(bank, letter, {}, qrc_grader=never)["score"] == 0


@pytest.mark.parametrize("count,penalty", [(5, 0), (6, 1), (15, 1)])
def test_french_spelling_penalty_is_one_point_only_after_five_errors(count, penalty):
    bank = cma.load_bank()
    result = cma.grade_subject(bank, "D", full_answers(cma.subject_for(bank, "D")),
        qrc_grader=lambda a, b: fake_grade(a, b, spelling=count))
    assert result["score"] == 20 - penalty
    assert result["spelling_penalty"] == penalty


def test_incomplete_spelling_review_or_missing_criterion_does_not_issue_verified_grade():
    bank = cma.load_bank()
    answers = full_answers(cma.subject_for(bank, "D"))
    def incomplete(a, b):
        result = fake_grade(a, b)
        result["spelling_review_complete"] = False
        return result
    result = cma.grade_subject(bank, "D", answers, qrc_grader=incomplete)
    assert result["status"] == "needs_human_review"
    assert result["minimum_met"] is None
    def missing(a, b):
        result = fake_grade(a, b); result["criteria"].pop(); return result
    result = cma.grade_subject(bank, "D", answers, qrc_grader=missing)
    assert result["score"] is None and result["status"] == "needs_human_review"


def test_deadline_is_fixed_on_resume_and_late_answers_never_replace_saved_copy(timed_store):
    store, clock = timed_store
    state = store.create("session", "trainee")
    aid, deadline = state["id"], state["parts"]["A"]["deadline"]
    assert deadline == clock[0] + 45 * 60
    saved = {"A-qrc-01": "La copie sauvegardée avant expiration."}
    state = store.save("session", "trainee", aid, "A", saved, 0)
    clock[0] += 120
    resumed = store.create("session", "trainee")
    assert resumed["id"] == aid and resumed["parts"]["A"]["deadline"] == deadline
    assert resumed["parts"]["A"]["answers"] == saved
    clock[0] = deadline
    expired = store.save("session", "trainee", aid, "A", {"A-qrc-01": "Copie arrivée trop tard"}, 1, submit=True)
    assert expired["parts"]["A"]["status"] == "expired"
    assert expired["parts"]["A"]["answers"] == saved
    assert cma.public_attempt(cma.load_bank(), expired, now=clock[0])["current_subject"] == "B"
    assert "paper" not in cma.public_attempt(cma.load_bank(), expired, now=clock[0])
    next_state = store.start_part("session", "trainee", aid, "B")
    assert next_state["parts"]["B"]["deadline"] == clock[0] + 45 * 60


def test_server_copy_cannot_be_reopened_or_skip_a_subject(timed_store):
    store, _ = timed_store
    state = store.create("s", "t"); aid = state["id"]
    with pytest.raises(cma.CmaError, match="Terminez"):
        store.start_part("s", "t", aid, "G")
    state = store.save("s", "t", aid, "A", {"A-qrc-01": "Copie remise"}, 0, submit=True)
    again = store.save("s", "t", aid, "A", {"A-qrc-01": "Tentative de modification"}, 1, submit=True)
    assert again["parts"]["A"] == state["parts"]["A"]
    with pytest.raises(cma.CmaError):
        store.start_part("s", "t", aid, "A")
    with pytest.raises(cma.CmaError, match="sept"):
        store.claim_grading("s", "t", aid, "A")


def test_one_active_attempt_and_concurrent_saves_have_no_silent_overwrite(timed_store):
    store, _ = timed_store
    with ThreadPoolExecutor(max_workers=4) as pool:
        attempts = list(pool.map(lambda _: store.create("session", "trainee"), range(4)))
    assert len({a["id"] for a in attempts}) == 1
    aid = attempts[0]["id"]
    def save(value):
        try:
            return store.save("session", "trainee", aid, "A", {"A-qrc-01": value}, 0)
        except cma.CmaError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(save, ["première page", "seconde page"]))
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert "revision_conflict" in outcomes


def test_attempt_ownership_and_immutable_bank_version(timed_store):
    store, _ = timed_store
    state = store.create("session", "trainee")
    with pytest.raises(cma.CmaError) as error:
        store.read("other-session", "trainee", state["id"])
    assert error.value.status == 404
    with pytest.raises(cma.CmaError):
        store.save("session", "other-trainee", state["id"], "A", {}, 0)
    assert store.history("other-session", "trainee") == []
    edited = cma.load_bank(); edited["subjects"][0]["questions"][0]["answers"] = ["tampered"]
    assert cma.load_bank()["subjects"][0]["questions"][0]["answers"] != ["tampered"]


def test_ai_claim_is_single_use_and_failure_preserves_unscored_copy_for_retry(timed_store):
    store, clock = timed_store
    state = finish_papers(store); aid = state["id"]
    state, claim = store.claim_grading("session", "trainee", aid, "A")
    with pytest.raises(cma.CmaError) as error:
        store.claim_grading("session", "trainee", aid, "A")
    assert error.value.code == "grading_busy"
    failed = store.finish_grading("session", "trainee", aid, "A", claim, error="Indisponible")
    result = cma.result_for(cma.load_bank(), failed)
    assert result["weighted_average"] is None and result["passed"] is None
    assert result["subjects"][0]["score"] is None
    assert failed["parts"]["A"]["answers"] == state["parts"]["A"]["answers"]
    state, second_claim = store.claim_grading("session", "trainee", aid, "A")
    assert second_claim != claim
    correction = cma.grade_subject(cma.load_bank(), "A", state["parts"]["A"]["answers"], qrc_grader=fake_grade)
    store.finish_grading("session", "trainee", aid, "A", second_claim, correction=correction)
    _, third_claim = store.claim_grading("session", "trainee", aid, "A")
    assert third_claim is None


def test_crashed_grading_can_be_reclaimed_after_lease_and_old_worker_cannot_overwrite(timed_store):
    store, clock = timed_store
    state = finish_papers(store)
    _, old = store.claim_grading("session", "trainee", state["id"], "G")
    clock[0] += 121
    _, new = store.claim_grading("session", "trainee", state["id"], "G")
    assert old != new
    with pytest.raises(cma.CmaError):
        store.finish_grading("session", "trainee", state["id"], "G", old, error="stale")


def test_weighted_mean_each_minimum_and_human_review_gate_admissibility(timed_store):
    store, _ = timed_store
    bank = cma.load_bank(); state = finish_papers(store)
    for letter in cma.LETTERS:
        state["parts"][letter]["correction"] = cma.grade_subject(bank, letter, state["parts"][letter]["answers"], qrc_grader=fake_grade)
    assert cma.result_for(bank, state)["passed"] is True
    assert cma.result_for(bank, state)["weighted_average"] == 20
    for letter in cma.LETTERS:
        state["parts"][letter]["correction"].update(score=10, minimum_met=True)
    assert cma.result_for(bank, state)["passed"] is True
    state["parts"]["E"]["correction"].update(score=3.99, minimum_met=False)
    result = cma.result_for(bank, state)
    assert result["passed"] is False and result["failed_minima"] == ["E"]
    state["parts"]["E"]["correction"].update(score=9.99, minimum_met=True)
    result = cma.result_for(bank, state)
    assert result["weighted_average"] == 10 and result["passed"] is False
    state["parts"]["E"]["correction"].update(score=10, status="needs_human_review", minimum_met=None)
    result = cma.result_for(bank, state)
    assert result["status"] == "needs_human_review" and result["passed"] is None and result["weighted_average"] is None


@pytest.mark.parametrize("bad", [None, "a", ["a", "a"], ["not-a-choice"], [True], {"a": True}])
def test_qcm_rejects_invalid_values(bad):
    with pytest.raises(cma.CmaError):
        cma.normalize_answers(cma.subject_for(cma.load_bank(), "A"), {"A-qcm-01": bad})


def test_multiple_choice_exact_set_support_and_writing_limits():
    bank = cma.load_bank()
    question = bank["subjects"][0]["questions"][0]
    question["multiple"] = True
    question["answers"] = [o["id"] for o in question["options"][:2]]
    qid = question["id"]
    assert cma.grade_subject(bank, "A", {qid: question["answers"]})["qcm_score"] == 1
    assert cma.grade_subject(bank, "A", {qid: question["answers"][:1]})["qcm_score"] == 0
    with pytest.raises(cma.CmaError):
        cma.normalize_answers(bank["subjects"][0], {"A-qrc-01": "x" * 4001})
    with pytest.raises(cma.CmaError):
        cma.normalize_answers(bank["subjects"][0], {"G-qrc-01": "Autre matière"})


def test_reporting_reader_is_read_only_scoped_and_contains_no_written_copy(timed_store):
    store, _ = timed_store
    state = finish_papers(store)
    before = store.path.read_bytes()
    rows = cma.learner_attempt_summaries(store.path, "session", "trainee")
    assert store.path.read_bytes() == before
    assert rows[0]["attempt_id"] == state["id"]
    assert rows[0]["submitted_subjects"] == 7
    assert rows[0]["pending_subjects"] == ["A", "B", "D", "F", "G"]
    assert rows[0]["passed"] is None and len(rows[0]["subjects"]) == 7
    assert rows[0]["subjects"][2]["score"] == 20
    assert "answers" not in str(rows) and "corrections" not in str(rows)
    assert state["parts"]["A"]["answers"]["A-qrc-01"] not in str(rows)
    assert cma.learner_attempt_summaries(store.path, "another-session", "trainee") == []
    assert cma.learner_attempt_summaries(store.path, "session", "another-trainee") == []


def test_reporting_missing_database_or_table_creates_nothing(tmp_path):
    path = tmp_path / "does-not-exist.sqlite3"
    assert cma.learner_attempt_summaries(path, "s", "t") == []
    assert not path.exists()
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE unrelated (value TEXT)")
    before = path.read_bytes()
    assert cma.learner_attempt_summaries(path, "s", "t") == []
    assert path.read_bytes() == before


def test_qcm_answer_positions_are_varied_and_english_distractors_are_not_placeholders():
    bank = cma.load_bank()
    for subject in bank["subjects"]:
        positions = [next(i for i, o in enumerate(q["options"]) if o["id"] in q["answers"])
                     for q in subject["questions"] if q["kind"] == "qcm"]
        assert len(set(positions)) >= 3
    english = cma.subject_for(bank, "E")
    assert all(len({o["text"] for o in q["options"]}) == len(q["options"]) for q in english["questions"])
