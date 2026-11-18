from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import multiprocessing
import sqlite3
import threading

import pytest

import uv_questionnaire_store as storage
from uv_questionnaire_store import UVQuestionnaireStore


KEY = ("partner-a", "session-a", "trainee-a")
ATTEMPTS = "uv_questionnaire_attempts"
RESULTS = "uv_questionnaires"
RESETS = "uv_questionnaire_resets"


@pytest.fixture
def store(tmp_path):
    return UVQuestionnaireStore(tmp_path / "persist" / "uv.sqlite3")


def test_first_mutation_imports_legacy_state_once_and_returns_detached_data(store):
    seed = {ATTEMPTS: {"aps": {"2": {"answers": {"q1": "é"}, "index": 1}}}}
    original = deepcopy(seed)
    assert store.read(KEY) is None
    returned = store.mutate(KEY, seed, lambda state: state)
    assert returned == original
    returned[ATTEMPTS]["aps"]["2"]["answers"]["q1"] = "changed"
    seed[ATTEMPTS]["aps"]["2"]["answers"]["q1"] = "also changed"
    snapshot = store.read(KEY)
    assert snapshot == original
    snapshot.clear()
    assert store.read(KEY) == original

    # Existing rows do not consult the seed, including a stale/invalid seed.
    assert store.mutate(KEY, {"unrelated": "must not migrate"}, lambda state: state) == original


def test_storage_is_isolated_by_partner_session_and_trainee(store):
    keys = [KEY, ("partner-b", *KEY[1:]), (KEY[0], "session-b", KEY[2]), (*KEY[:2], "trainee-b")]
    for index, key in enumerate(keys):
        store.mutate(key, {RESULTS: {"aps": {"2": {"score": index}}}}, lambda state: None)
    for index, key in enumerate(keys):
        assert store.read(key)[RESULTS]["aps"]["2"]["score"] == index


def test_reset_keeps_authoritative_empty_row_and_never_resurrects_legacy_result(store):
    seed = {RESULTS: {"aps": {"2": {"score": 18}}}}
    store.mutate(KEY, seed, lambda state: None)
    store.mutate(KEY, seed, lambda state: state.clear())
    assert store.read(KEY) == {}
    assert store.mutate(KEY, seed, lambda state: state) == {}
    assert store.read(KEY) == {}
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM uv_questionnaire_state").fetchone()[0] == 1


def test_reset_generation_survives_stale_seed(store):
    seed = {ATTEMPTS: {"aps": {"2": {"index": 7}}}, RESULTS: {"aps": {"3": {"score": 19}}}}
    store.mutate(KEY, seed, lambda state: None)

    def reset(state):
        state[ATTEMPTS]["aps"].pop("2")
        state[RESETS] = {"aps": {"2": "new-generation"}}

    store.mutate(KEY, seed, reset)
    actual = store.mutate(KEY, seed, lambda state: state)
    assert "2" not in actual[ATTEMPTS]["aps"]
    assert actual[RESETS] == {"aps": {"2": "new-generation"}}
    assert actual[RESULTS]["aps"]["3"]["score"] == 19


def test_independent_instances_use_current_state_after_answer_and_reset(store):
    other_store = UVQuestionnaireStore(store.database_path)
    seed = {ATTEMPTS: {"aps": {"2": {"answers": {}, "index": 0}}}}
    store.mutate(KEY, seed, lambda state: None)
    stale_seed = other_store.read(KEY)
    store.mutate(KEY, seed, lambda state: state[ATTEMPTS]["aps"]["2"]["answers"].update({"q1": "a"}))
    other_store.mutate(KEY, stale_seed, lambda state: state[ATTEMPTS]["aps"]["2"]["answers"].update({"q2": "b"}))
    assert store.read(KEY)[ATTEMPTS]["aps"]["2"]["answers"] == {"q1": "a", "q2": "b"}

    def reset(state):
        state.clear()
        state[RESETS] = {"aps": {"2": "generation-after-reset"}}

    store.mutate(KEY, seed, reset)
    assert other_store.mutate(KEY, stale_seed, lambda state: state) == {
        RESETS: {"aps": {"2": "generation-after-reset"}}
    }
    assert other_store.read(KEY) == store.read(KEY)


def test_callback_exception_rolls_back_and_leaves_seed_untouched(store):
    seed = {ATTEMPTS: {"aps": {"2": {"index": 0}}}}
    original = deepcopy(seed)

    def fail(state):
        state[ATTEMPTS]["aps"]["2"]["index"] = 5
        raise RuntimeError("simulation")

    with pytest.raises(RuntimeError, match="simulation"):
        store.mutate(KEY, seed, fail)
    assert store.read(KEY) is None
    assert seed == original
    store.mutate(KEY, seed, lambda state: None)
    with pytest.raises(RuntimeError, match="simulation"):
        store.mutate(KEY, seed, fail)
    assert store.read(KEY) == original


def test_repeated_answer_does_not_write_an_update(store):
    store.mutate(KEY, {}, lambda state: state.setdefault(ATTEMPTS, {}).update({"q1": "a"}))
    with sqlite3.connect(store.database_path) as connection:
        connection.executescript("""
            CREATE TABLE observed_updates (marker INTEGER);
            CREATE TRIGGER observe_uv_update AFTER UPDATE ON uv_questionnaire_state
            BEGIN INSERT INTO observed_updates VALUES (1); END;
        """)
    for _ in range(4):
        assert store.mutate(KEY, {}, lambda state: state[ATTEMPTS].setdefault("q1", "a")) == "a"
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM observed_updates").fetchone()[0] == 0
    store.mutate(KEY, {}, lambda state: state[ATTEMPTS].update({"q2": "b"}))
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM observed_updates").fetchone()[0] == 1


@pytest.mark.parametrize("key", [(), ("a", "b"), ("a", "b", "c", "d"),
                                  ("", "b", "c"), ("a", "  ", "c"),
                                  ("a", "b", None), ["a", "b", "c"]])
def test_invalid_identity_is_rejected(store, key):
    with pytest.raises(ValueError, match="identifiers"):
        store.read(key)
    with pytest.raises(ValueError, match="identifiers"):
        store.mutate(key, {}, lambda state: None)


def test_non_uv_fields_and_non_json_values_cannot_be_persisted(store):
    with pytest.raises(ValueError, match="Only UV"):
        store.mutate(KEY, {"first_name": "not questionnaire state"}, lambda state: None)
    assert store.read(KEY) is None
    store.mutate(KEY, {}, lambda state: None)
    with pytest.raises(ValueError, match="Only UV"):
        store.mutate(KEY, {}, lambda state: state.update({"first_name": "invalid"}))
    with pytest.raises(TypeError):
        store.mutate(KEY, {}, lambda state: state.update({ATTEMPTS: object()}))
    with pytest.raises(ValueError):
        store.mutate(KEY, {}, lambda state: state.update({ATTEMPTS: float("nan")}))
    assert store.read(KEY) == {}


def test_corrupt_database_state_is_not_replaced_with_legacy_data(store):
    store.mutate(KEY, {}, lambda state: None)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("UPDATE uv_questionnaire_state SET state_json = ?", ("not json",))
    with pytest.raises(ValueError):
        store.read(KEY)
    with pytest.raises(ValueError):
        store.mutate(KEY, {RESULTS: {"old": True}}, lambda state: None)


def test_database_error_propagates_without_fallback(store):
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TABLE uv_questionnaire_state")
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        store.read(KEY)
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        store.mutate(KEY, {}, lambda state: None)


def test_durable_wal_configuration_on_each_connection(store):
    connection = store._connect()
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
    finally:
        connection.close()


def test_24_concurrent_learners_save_all_20_answers_in_real_sqlite(tmp_path):
    path = tmp_path / "simultaneous-first-start" / "uv.sqlite3"
    ready = threading.Barrier(24)

    def learner(index):
        ready.wait(timeout=15)
        local_store = UVQuestionnaireStore(path)
        key = ("partner", "session", f"trainee-{index}")
        for question in range(20):
            def answer(state):
                state.setdefault(ATTEMPTS, {}).setdefault("aps", {}).setdefault("2", {})[str(question)] = index
            local_store.mutate(key, {}, answer)
        return key

    with ThreadPoolExecutor(max_workers=24) as pool:
        keys = list(pool.map(learner, range(24)))
    final_store = UVQuestionnaireStore(path)
    for index, key in enumerate(keys):
        assert final_store.read(key)[ATTEMPTS]["aps"]["2"] == {str(question): index for question in range(20)}


def test_24_concurrent_updates_of_same_learner_do_not_lose_writes(store):
    ready = threading.Barrier(24)

    def append(index):
        ready.wait(timeout=15)
        store.mutate(KEY, {}, lambda state: state.setdefault(ATTEMPTS, {}).update({str(index): index}))

    with ThreadPoolExecutor(max_workers=24) as pool:
        list(pool.map(append, range(24)))
    assert store.read(KEY) == {ATTEMPTS: {str(index): index for index in range(24)}}


def _process_writer(path, ready, index):
    ready.wait(timeout=15)
    local_store = UVQuestionnaireStore(path)
    for question in range(6):
        key = f"{index}-{question}"
        local_store.mutate(KEY, {}, lambda state: state.setdefault(ATTEMPTS, {}).update({key: True}))


def test_processes_can_initialize_and_update_the_same_database(tmp_path):
    path = str(tmp_path / "process-first-start" / "uv.sqlite3")
    context = multiprocessing.get_context("spawn")
    ready = context.Barrier(4)
    processes = [context.Process(target=_process_writer, args=(path, ready, index)) for index in range(4)]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
            assert process.exitcode == 0
        assert UVQuestionnaireStore(path).read(KEY) == {
            ATTEMPTS: {f"{index}-{question}": True for index in range(4) for question in range(6)}
        }
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)


def test_transfer_imports_once_and_keeps_one_canonical_state_through_return(store):
    destination = (KEY[0], 'session-destination', KEY[2])
    final_destination = (KEY[0], 'session-third', KEY[2])
    seed = {ATTEMPTS: {'q1': 'a'}}
    store.transfer(KEY, destination, seed)
    assert store.read(KEY) == store.read(destination) == seed
    store.mutate(destination, {}, lambda state: state[ATTEMPTS].update({'q2': 'b'}))
    # Going back does not create an alias cycle or restore the old seed.
    store.transfer(destination, KEY, seed)
    store.transfer(KEY, destination, seed)
    store.transfer(destination, final_destination, seed)
    store.mutate(KEY, seed, lambda state: state[ATTEMPTS].update({'q3': 'c'}))
    expected = {ATTEMPTS: {'q1': 'a', 'q2': 'b', 'q3': 'c'}}
    assert store.read(KEY) == store.read(destination) == store.read(final_destination) == expected
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute('SELECT count(*) FROM uv_questionnaire_state').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM uv_questionnaire_alias').fetchone()[0] == 2


def test_authorized_transfer_can_cross_partners_without_copying_state(store):
    destination = ('partner-b', 'session-b', KEY[2])
    unrelated = ('partner-c', 'session-b', KEY[2])
    store.mutate(KEY, {RESULTS: {'aps': {'2': {'score': 18}}}}, lambda state: None)
    store.transfer(KEY, destination, {})
    assert store.read(destination) == store.read(KEY)
    assert store.read(unrelated) is None
    store.mutate(destination, {}, lambda state: state.update({RESETS: {'aps': {'2': 'reset'}}}))
    assert store.read(KEY)[RESETS]['aps']['2'] == 'reset'


@pytest.mark.parametrize('destination_is_alias', [False, True])
def test_transfer_refuses_existing_destination_without_changing_either_state(store, destination_is_alias):
    destination = (KEY[0], 'occupied-session', KEY[2])
    owner = ('other-partner', 'other-session', 'other-trainee')
    if destination_is_alias:
        store.transfer(owner, destination, {RESULTS: {'existing': True}})
    else:
        store.mutate(destination, {}, lambda state: None)  # even an empty row is authoritative
    before = store.read(destination)
    with pytest.raises(ValueError, match='destination already owns'):
        store.transfer(KEY, destination, {RESULTS: {'incoming': True}})
    assert store.read(KEY) is None
    assert store.read(destination) == before


def test_transfer_preserves_answer_already_in_flight_and_later_old_identity_write(store):
    destination = (KEY[0], 'session-destination', KEY[2])
    entered = threading.Event()
    release = threading.Event()
    transfer_started = threading.Event()

    def answer(state):
        state.setdefault(ATTEMPTS, {})['q1'] = 'a'
        entered.set()
        assert release.wait(timeout=10)

    def transfer():
        transfer_started.set()
        store.transfer(KEY, destination, {})

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending_answer = pool.submit(store.mutate, KEY, {}, answer)
        assert entered.wait(timeout=10)
        pending_transfer = pool.submit(transfer)
        assert transfer_started.wait(timeout=10)
        release.set()
        pending_answer.result(timeout=15)
        pending_transfer.result(timeout=15)
    assert store.read(destination) == {ATTEMPTS: {'q1': 'a'}}
    # An HTTP request can have resolved its source session before the move.
    store.mutate(KEY, {}, lambda state: state[ATTEMPTS].update({'q2': 'b'}))
    assert store.read(destination) == {ATTEMPTS: {'q1': 'a', 'q2': 'b'}}


def test_reset_and_stale_seed_remain_authoritative_through_alias(store):
    destination = (KEY[0], 'session-destination', KEY[2])
    legacy = {RESULTS: {'aps': {'2': {'score': 20}}}}
    store.transfer(KEY, destination, legacy)
    store.mutate(destination, legacy, lambda state: state.clear())
    store.transfer(destination, KEY, legacy)
    assert store.mutate(KEY, legacy, lambda state: state) == {}
    assert store.read(destination) == {}


def test_corrupt_alias_cycle_fails_instead_of_looping_or_reimporting_seed(store):
    destination = (KEY[0], 'session-destination', KEY[2])
    with sqlite3.connect(store.database_path) as connection:
        # Raw corruption bypasses the store's enabled foreign key checks.
        connection.execute('INSERT INTO uv_questionnaire_alias VALUES (?, ?, ?, ?, ?, ?)', (*KEY, *destination))
        connection.execute('INSERT INTO uv_questionnaire_alias VALUES (?, ?, ?, ?, ?, ?)', (*destination, *KEY))
    with pytest.raises(ValueError, match='cycle'):
        store.read(KEY)
    with pytest.raises(ValueError, match='cycle'):
        store.mutate(KEY, {}, lambda state: None)
    with pytest.raises(ValueError, match='cycle'):
        store.transfer(KEY, ('p', 'new', 't'), {})


def test_backup_includes_recent_wal_commits_and_transfer_aliases(store, tmp_path):
    destination = (KEY[0], 'session-destination', KEY[2])
    backup = tmp_path / 'backups' / 'uv-snapshot.sqlite3'
    keeper = store._connect()
    try:
        store.transfer(KEY, destination, {ATTEMPTS: {'q1': 'a'}})
        store.mutate(destination, {}, lambda state: state[ATTEMPTS].update({'q2': 'b'}))
        # Keep the source open so committed pages are still in its live WAL.
        assert store.database_path.with_name(store.database_path.name + '-wal').is_file()
        assert store.backup_to(backup) == backup
        with sqlite3.connect(backup) as connection:
            assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
            assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        restored = UVQuestionnaireStore(backup)
        assert restored.read(KEY) == restored.read(destination) == {ATTEMPTS: {'q1': 'a', 'q2': 'b'}}
        store.mutate(KEY, {}, lambda state: state[ATTEMPTS].update({'q3': 'c'}))
        assert restored.read(destination) == {ATTEMPTS: {'q1': 'a', 'q2': 'b'}}
    finally:
        keeper.close()
    assert not list(backup.parent.glob('*.tmp*'))


def test_failed_backup_publication_preserves_previous_snapshot(store, tmp_path, monkeypatch):
    backup = tmp_path / 'backups' / 'uv-snapshot.sqlite3'
    store.mutate(KEY, {ATTEMPTS: {'q1': 'a'}}, lambda state: None)
    store.backup_to(backup)
    before = backup.read_bytes()
    store.mutate(KEY, {}, lambda state: state[ATTEMPTS].update({'q2': 'b'}))

    def fail_replace(*args, **kwargs):
        raise OSError('publication failed')

    monkeypatch.setattr(storage.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='publication failed'):
        store.backup_to(backup)
    assert backup.read_bytes() == before
    assert not list(backup.parent.glob('*.tmp*'))
    assert store.read(KEY) == {ATTEMPTS: {'q1': 'a', 'q2': 'b'}}


def test_backup_refuses_live_database_destination(store):
    store.mutate(KEY, {}, lambda state: None)
    with pytest.raises(ValueError, match='must differ'):
        store.backup_to(store.database_path)
    assert store.read(KEY) == {}
