"""Concurrent real SQLite/UV-route regression coverage, isolated from the CRM."""

from concurrent.futures import ThreadPoolExecutor
import json
import threading

from scripts.benchmark_uv_questionnaires import (
    create_harness, synthetic_data, validate_persisted_states,
)


def test_24_learners_complete_while_general_json_lock_is_held(tmp_path):
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps(synthetic_data(24, .125)), encoding="utf-8")
    app, services, uv = create_harness({
        "data_file": str(data_file), "db_path": str(tmp_path / "uv-questionnaires.sqlite3"),
        "clients": 24, "secret": "synthetic-concurrency-test-only",
    })
    app.config["TESTING"] = True
    questions = uv.unit("aps", 2)["questions"]
    barrier = threading.Barrier(24)

    def forbidden_general_save(_mutate):
        raise AssertionError("UV replies must not acquire or rewrite the general JSON store")

    services._atomic_update_data = forbidden_general_save

    def learner(index):
        client = app.test_client()
        csrf = client.post(f"/benchmark/login/{index}").json["csrf"]
        path = f"/espace/bench-token-{index:03}/questionnaires-uv/2"

        def submit(action, **payload):
            response = client.post(path, json={"csrf": csrf, "generation": "", "action": action, **payload})
            assert response.status_code == 200, response.text
            assert not response.json.get("answer_expired")
            return response.json

        try:
            barrier.wait(timeout=20)
            state = submit("start", in_class="yes")
            for ordinal, question in enumerate(questions):
                assert state["question"]["id"] == question["id"]
                barrier.wait(timeout=20)
                state = submit("answer", question_id=question["id"], answer=question["answer"])
                if ordinal in {0, 9, 19}:
                    repeated = submit("answer", question_id=question["id"], answer=question["answer"])
                    assert repeated.get("index") == state.get("index")
                    assert repeated.get("completed") == state.get("completed")
                    state = repeated
            assert state == {"completed": True, "score": 20}
        except Exception:
            barrier.abort()
            raise

    # Keep the actual global JSON writer lock unavailable throughout all 480
    # answers. The dedicated store must still complete; data reads are atomic.
    with services.locked_general_data():
        with ThreadPoolExecutor(max_workers=24) as pool:
            list(pool.map(learner, range(24)))

    result = app.test_client().get("/benchmark/results").json
    # This case holds the lock instead of running the background-save thread;
    # the standalone HTTP benchmark exercises that writer and its real fsyncs.
    assert validate_persisted_states(result, questions, 24, require_background_saves=False) == []
    assert result["dedicated_database"] is True
    assert result["general_saves"] == 0
    assert result["json_contains_uv_states"] is False
