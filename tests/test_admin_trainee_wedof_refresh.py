import datetime
from unittest.mock import Mock

import pytest
import admin_trainee_wedof_refresh as refresh


def test_only_stale_links_are_queued_once(monkeypatch):
    host = Mock()
    host._parse_iso_datetime.side_effect = lambda value: datetime.datetime.fromisoformat(value) if value else None
    pool = Mock()
    monkeypatch.setattr(refresh, '_pool', pool)
    monkeypatch.setattr(refresh, '_pending', set())
    monkeypatch.setattr(refresh, '_recent_attempts', refresh.OrderedDict())
    refresh.schedule_refresh(host, 'S', 'T', None)
    refresh.schedule_refresh(host, 'S', 'T', {'external_id':'123', 'last_seen_at':datetime.datetime.utcnow().isoformat()})
    pool.submit.assert_not_called()
    stale = {'external_id':'123', 'last_seen_at':'2026-01-01'}
    refresh.schedule_refresh(host, 'S', 'T', stale)
    refresh.schedule_refresh(host, 'S', 'T', stale)
    pool.submit.assert_called_once()
    host.WedofClient.assert_not_called()


@pytest.mark.parametrize("concurrent_change", [False, True])
def test_refresh_merges_only_the_same_unchanged_cpf_link(monkeypatch, concurrent_change):
    from contextlib import nullcontext
    monkeypatch.setattr(refresh, 'provider_operation', lambda name: nullcontext())
    host = Mock()
    host.INTEGRALE_PARTNER_ID = "integrale"
    host.find_session.return_value = {"id": "S"}
    folder = {'external_id':'123', 'type':'CPF', 'state':'accepted'}
    host.WedofClient.return_value.get_registration_folder_interactive.return_value = folder
    host.extract_folder.return_value = host._cpf_public_snapshot.return_value = folder
    link = {'external_id':'123', 'wedof_state':'old'}
    latest = dict(link, wedof_state='new' if concurrent_change else 'old')
    host._cpf_active_link.return_value = latest
    host._atomic_update_data.side_effect = lambda apply: apply({})
    assert refresh.refresh_link(host, 'S', 'T', link) is not concurrent_change
    if concurrent_change:
        assert latest == {'external_id':'123', 'wedof_state':'new'}
        host.sync_folder_automation_status.assert_not_called()
    else:
        assert latest['cpf_snapshot'] == folder
        host.sync_folder_automation_status.assert_called_once()


def test_provider_switch_prevents_background_reads_and_writes(monkeypatch):
    host = Mock()
    monkeypatch.setattr(refresh, "provider_operation", Mock(side_effect=refresh.ProviderUnavailable("off")))
    with pytest.raises(refresh.ProviderUnavailable):
        refresh.refresh_link(host, "S", "T", {"external_id":"123"})
    host.WedofClient.assert_not_called()
    host._atomic_update_data.assert_not_called()


def test_remote_failure_preserves_cached_snapshot_and_records_staleness(monkeypatch):
    from contextlib import nullcontext
    monkeypatch.setattr(refresh, "provider_operation", lambda _: nullcontext())
    host = Mock()
    host.INTEGRALE_PARTNER_ID = "integrale"
    host.find_session.return_value = {"id":"S"}
    host.WedofApiError = ValueError
    host.WedofConfigurationError = RuntimeError
    host.WedofClient.return_value.get_registration_folder_interactive.side_effect = ValueError("unavailable")
    snapshot = {"state":"accepted"}
    link = {"external_id":"123","cpf_snapshot":snapshot,"last_seen_at":"2026-09-02"}
    host._cpf_active_link.return_value = link
    host._atomic_update_data.side_effect = lambda apply: apply({})
    with pytest.raises(ValueError):
        refresh.refresh_link(host, "S", "T", link)
    assert link["cpf_snapshot"] is snapshot
    assert link["last_seen_at"] == "2026-09-02" and link["cpf_sync_error"]
    host.sync_folder_automation_status.assert_not_called()
