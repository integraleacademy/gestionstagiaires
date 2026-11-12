"""Declarations reuse the live EDOF session without relaxing cold-login guards."""
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import cpf_provider as providers
import edof_server_test as server


@pytest.mark.parametrize("mode", ["declare", "reconcile"])
def test_shared_declarations_follow_completed_jobs_without_five_minute_wait(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(server.time, "time", lambda: 1000000.0)
    store = server.ServerTestStore(tmp_path)
    previous = store.reserve("owner", "declare")
    store.finish(previous, {"code": "declaration_confirmed"})

    current = store.reserve("owner", mode, shared_session=True)
    assert current != previous
    with pytest.raises(ValueError, match="en cours"):
        store.reserve("owner", mode, shared_session=True)
    store.finish(current, {"code": "declaration_confirmed"})
    assert store.reserve("owner", mode, shared_session=True) != current


@pytest.mark.parametrize("mode", ["declare", "reconcile"])
def test_cold_declarations_still_wait_between_authentication_jobs(tmp_path, monkeypatch, mode):
    now = [1000000.0]
    monkeypatch.setattr(server.time, "time", lambda: now[0])
    store = server.ServerTestStore(tmp_path)
    store.finish(store.reserve("owner", "declare"), {"code": "declaration_confirmed"})

    with pytest.raises(server.JobCooldown) as error:
        store.reserve("owner", mode)
    assert error.value.remaining == 300
    now[0] += 300
    assert store.reserve("owner", mode)


@pytest.mark.parametrize("mode", ["read", "inspect_forms"])
def test_other_authentication_jobs_keep_their_cooldown(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(server.time, "time", lambda: 1000000.0)
    store = server.ServerTestStore(tmp_path)
    store.finish(store.reserve("owner", "declare"), {"code": "declaration_confirmed"})
    with pytest.raises(server.JobCooldown):
        store.reserve("owner", mode, shared_session=True)


@pytest.mark.parametrize("mode", ["declare", "reconcile"])
@pytest.mark.parametrize("session_state", ["live", "missing", "stopped", "other_owner", "other_provider"])
def test_scheduler_only_skips_wait_for_the_same_live_session(tmp_path, monkeypatch, mode, session_state):
    monkeypatch.setattr(server.time, "time", lambda: 1000000.0)
    monkeypatch.setattr(server, "working_hours", lambda: True)
    gate = providers.ProviderStore(tmp_path)
    gate.switch("integrale", 0, "test")
    monkeypatch.setattr(providers, "current_store", lambda: gate)
    store = server.ServerTestStore(tmp_path)
    store.finish(store.reserve("owner", "declare"), {"code": "declaration_confirmed"})
    check = Mock(return_value=True)
    monkeypatch.setattr(server.declarations, "check_before_job", check)
    thread = Mock()
    start_thread = Mock(return_value=thread)
    monkeypatch.setattr(server.threading, "Thread", start_thread)
    worker = SimpleNamespace(
        owner="other" if session_state == "other_owner" else "owner",
        provider="wedof" if session_state == "other_provider" else "integrale",
        process=Mock(poll=Mock(return_value=1 if session_state == "stopped" else None)),
    )
    if session_state == "missing":
        worker = None
    spec = {"mode": mode, "provider": "integrale", "revision": 1, "intent": {}}

    if session_state == "live":
        job = server.start_job(store, "owner", spec, day_worker=worker)
        args = start_thread.call_args.kwargs["args"]
        try:
            assert args[1] == job and args[-1] is worker
            assert args[2]["mode"] == mode
            thread.start.assert_called_once()
        finally:
            os.close(args[3])
            os.close(args[4])
    else:
        with pytest.raises(server.JobCooldown):
            server.start_job(store, "owner", spec, day_worker=worker)
        start_thread.assert_not_called()
    check.assert_called_once()
