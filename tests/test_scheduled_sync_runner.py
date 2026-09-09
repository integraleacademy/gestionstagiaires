import threading
from unittest.mock import Mock

import pytest

from scripts import run_wedof_automation as runner


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
