import threading
from unittest.mock import Mock

import pytest

from scripts import run_wedof_automation as runner
from scripts import run_document_reminders as documents


@pytest.fixture(autouse=True)
def isolated_runner_environment(monkeypatch):
    monkeypatch.delenv("WEDOF_AUTOMATION_URL", raising=False)
    monkeypatch.delenv("DOCUMENT_REMINDERS_URL", raising=False)


def test_qonto_starts_while_wedof_is_still_waiting(monkeypatch):
    monkeypatch.setenv('QONTO_SYNC_URL', 'https://app.example/internal/cron/qonto-sync')
    qonto_started = threading.Event()

    def wedof():
        assert qonto_started.wait(timeout=2), 'Qonto must start without waiting for WEDOF'

    monkeypatch.setattr(runner, 'run_wedof', wedof)
    monkeypatch.setattr(runner, 'run_qonto', qonto_started.set)
    runner.main()
    assert qonto_started.is_set()


@pytest.mark.parametrize('failing', ['run_wedof', 'run_qonto'])
def test_one_service_failure_does_not_skip_the_other(monkeypatch, failing):
    monkeypatch.setenv('QONTO_SYNC_URL', 'https://app.example/internal/cron/qonto-sync')
    calls = {name: Mock(side_effect=SystemExit('unavailable') if name == failing else None)
             for name in ('run_wedof', 'run_qonto')}
    for name, call in calls.items():
        monkeypatch.setattr(runner, name, call)
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 1
    for call in calls.values():
        call.assert_called_once_with()


def test_existing_wedof_only_configuration_still_works(monkeypatch):
    monkeypatch.delenv('QONTO_SYNC_URL', raising=False)
    wedof, qonto = Mock(), Mock()
    monkeypatch.setattr(runner, 'run_wedof', wedof)
    monkeypatch.setattr(runner, 'run_qonto', qonto)
    runner.main()
    wedof.assert_called_once_with()
    qonto.assert_not_called()


def test_document_job_runs_independently_of_failing_wedof(monkeypatch):
    monkeypatch.setenv("WEDOF_AUTOMATION_URL", "https://app.example/internal/cron/wedof-automation")
    monkeypatch.setenv("QONTO_SYNC_URL", "https://app.example/internal/cron/qonto-sync")
    jobs = {name: Mock(side_effect=SystemExit("unavailable") if name == "run_wedof" else None)
            for name in ("run_wedof", "run_qonto", "run_documents")}
    for name, job in jobs.items(): monkeypatch.setattr(runner, name, job)
    with pytest.raises(SystemExit): runner.main()
    for job in jobs.values(): job.assert_called_once_with()


def test_document_job_uses_existing_live_origin_and_secret_without_new_env(monkeypatch):
    monkeypatch.setenv("WEDOF_AUTOMATION_URL", "https://app.example/internal/cron/wedof-automation")
    monkeypatch.setenv("CRON_SECRET", "test-cron-secret")
    post = Mock(return_value=Mock(ok=True, json=lambda: {"ok": True, "processed": 0}))
    monkeypatch.setattr(documents.requests, "post", post)
    documents.main()
    assert post.call_args.args == ("https://app.example/internal/cron/document-reminders",)
    assert post.call_args.kwargs["headers"]["X-Cron-Secret"] == "test-cron-secret"


def test_document_job_failure_makes_scheduler_failure_visible(monkeypatch):
    monkeypatch.setenv("DOCUMENT_REMINDERS_URL", "https://app.example/internal/cron/document-reminders")
    monkeypatch.setenv("CRON_SECRET", "test-cron-secret")
    monkeypatch.setattr(documents.requests, "post", Mock(return_value=Mock(ok=False, status_code=502)))
    with pytest.raises(SystemExit, match="HTTP 502"):
        documents.main()
