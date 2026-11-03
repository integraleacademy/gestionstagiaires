import datetime as dt
import os

import pytest

from edof_day_session import PARIS, allow_login, working_hours
from edof_gmail import Vault, connector_key
from edof_server_test import ServerTestStore


@pytest.mark.parametrize("instant, expected", [
    ("2026-11-02T06:59:59+00:00", False), ("2026-11-02T07:00:00+00:00", True),
    ("2026-11-06T17:59:59+00:00", True), ("2026-11-06T18:00:00+00:00", False),
    ("2026-11-07T12:00:00+00:00", False), ("2026-11-08T12:00:00+00:00", False),
    ("2027-07-05T06:00:00+00:00", True),
])
def test_paris_hours(instant, expected):
    assert working_hours(dt.datetime.fromisoformat(instant)) is expected


def test_single_automatic_sign_in_survives_restart_and_manual_login(tmp_path):
    key = connector_key("test" * 12)
    now = dt.datetime(2026, 11, 6, 8, tzinfo=PARIS)
    assert allow_login(Vault(tmp_path, key), automatic=True, now=now)
    assert not allow_login(Vault(tmp_path, key), automatic=True, now=now.replace(hour=17))
    assert not allow_login(Vault(tmp_path, key), automatic=True, now=now + dt.timedelta(days=1))
    monday = now + dt.timedelta(days=3)
    assert allow_login(Vault(tmp_path, key), automatic=False, now=monday)
    assert not allow_login(Vault(tmp_path, key), automatic=True, now=monday)
    assert allow_login(Vault(tmp_path, key), automatic=True, now=monday + dt.timedelta(days=1))


def test_failed_watch_resumes_next_weekday_and_respects_pause(tmp_path, monkeypatch):
    store = ServerTestStore(tmp_path)
    now = dt.datetime.now(PARIS)
    monday = (now-dt.timedelta(days=now.weekday())).replace(hour=8, minute=0, second=0, microsecond=0)
    monkeypatch.setattr("edof_server_test.time.time", lambda: monday.timestamp()+7200)
    store.use_directory("owner", enable=True)
    assert store.day_owners(monday) == ["owner"]
    with store.connect() as db:
        db.execute("INSERT INTO jobs VALUES ('one','owner',?,?,'directory',?)",
                   (monday.timestamp(), monday.timestamp()+2, '{"code":"day_login_used","day_session":true}'))
    assert not store.day_owners(monday+dt.timedelta(hours=2))
    assert store.day_owners(monday+dt.timedelta(days=1)) == ["owner"]
    store.pause_directory("owner")
    assert not store.day_owners(monday+dt.timedelta(days=1))


def test_same_chromium_tab_for_two_directory_reads_only(monkeypatch, tmp_path):
    from playwright.sync_api import sync_playwright
    import edof_server_browser as runner
    seen = []
    def stop_on_open(page, context, saved, signals, checkpoint):
        seen.append((context, page))
        raise runner.StopRun("directory_unavailable")
    monkeypatch.setenv("RENDER_SERVICE_ID", runner.TEST_SERVICE_ID)
    monkeypatch.setattr(runner, "open_workspace_or_login", stop_on_open)
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("EDOF_TEST_CHROMIUM"), headless=True)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Chromium absent")
            raise
        live = {"pw": pw, "browser": browser}
        for _ in range(2):
            assert runner.run_browser({"mode":"directory","owner":"fixture","day_session":True}, live=live)["code"] == "directory_unavailable"
        assert len(seen) == 2 and seen[0] == seen[1] and len(browser.contexts) == 1
        with pytest.raises(ValueError):
            runner.run_browser({"mode":"declare"}, live=live)
        browser.close()


def test_working_tab_sees_next_request_without_another_code(monkeypatch, tmp_path):
    """Two authenticated directory reads through Chromium, with all HTTP fulfilled locally."""
    import json
    from playwright.sync_api import Route, sync_playwright
    import edof_directory as directory
    import edof_server_browser as runner

    key = connector_key("local fixtures only, nothing from a connected account")
    vault = Vault(tmp_path, key)
    monkeypatch.setenv("EDOF_CONNECTOR_KEY", key)
    monkeypatch.setenv("EDOF_CONNECTOR_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("EDOF_EFP_USERNAME", "fixture@example.invalid")
    monkeypatch.setenv("EDOF_EFP_PASSWORD", "fixture-only")
    monkeypatch.setenv("RENDER_SERVICE_ID", runner.TEST_SERVICE_ID)
    vault.put("browser", {"cookies":[], "origins":[]}, ttl=86400)
    folders = []
    def local_reply(route, **kwargs):
        assert route.request.method == "GET" and route.request.url.startswith("https://"+runner.EDOF_HOST+"/")
        if runner.API_PREFIX+"pad" in route.request.url:
            route.fulfill(json={"items":folders, "numberOfItems":len(folders)})
        elif "/espace-prive/html/" in route.request.url:
            route.fulfill(content_type="text/html", body='<a href="#/dossiers/en-cours">Dossiers</a><script>fetch('+json.dumps(runner.API_PREFIX+"pad")+')</script>')
        else:
            route.fulfill(status=404, body="")
    monkeypatch.setattr(Route, "continue_", local_reply)
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("EDOF_TEST_CHROMIUM"), headless=True)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Chromium absent")
            raise
        live = {"pw":pw, "browser":browser}
        for size in (0,1):
            result = runner.run_browser({"mode":"directory", "day_session":True, "owner":"fixture"}, live=live)
            assert result["code"] == "directory_ready", result
            assert result["gmail_code_used"] is False and result["fresh_session"] is False
            assert result["candidate_count"] == size
            folders.append({"id":"100088","attendee":{"firstName":"Test","lastName":"Exemple"},"currentState":"notProcessed"})
        assert vault.get(directory.record_key("fixture"))["rows"]["100088"]["state"] == "notProcessed"
        assert len(browser.contexts) == len(browser.contexts[0].pages) == 1
        browser.close()


def test_only_a_verified_tab_can_automatically_renew_once(tmp_path):
    vault = Vault(tmp_path, connector_key("test" * 12))
    day = dt.datetime(2026, 11, 3, 8, tzinfo=PARIS)
    assert allow_login(vault, automatic=True, owner="A", now=day)
    assert not allow_login(vault, automatic=True, owner="A", now=day.replace(hour=9))
    assert allow_login(vault, automatic=True, owner="A", verified_tab=True, now=day.replace(hour=11))
    assert not allow_login(vault, automatic=True, owner="A", verified_tab=True, now=day.replace(hour=16))
    vault.put("day-login-override:A", day.date().isoformat(), ttl=600)
    assert not allow_login(vault, automatic=True, owner="B", now=day.replace(hour=17))
    assert allow_login(vault, automatic=True, owner="A", now=day.replace(hour=17))
    assert not allow_login(vault, automatic=True, owner="A", now=day.replace(hour=18))


def test_manual_window_on_weekend_expires_without_enabling_weekday_schedule(tmp_path, monkeypatch):
    from edof_day_session import session_deadline
    saturday = dt.datetime(2026, 11, 7, 10, tzinfo=PARIS)
    monkeypatch.setattr("edof_server_test.time.time", lambda: saturday.timestamp())
    store = ServerTestStore(tmp_path)
    assert store.activate_manual("owner")
    assert not store.activate_manual("owner")
    until = store.manual_until("owner")
    assert not store.directory_enabled("owner")
    assert session_deadline(saturday, until) == (saturday+dt.timedelta(hours=1)).timestamp()
    assert store.day_owners(saturday) == ["owner"]
    assert store.day_owners(saturday+dt.timedelta(hours=1)) == []
    vault = Vault(tmp_path, connector_key("test" * 12))
    assert allow_login(vault, automatic=True, manual_until=until, now=saturday)
    assert not allow_login(vault, automatic=True, manual_until=until, now=saturday+dt.timedelta(hours=1))
    store.pause_directory("owner")
    assert not store.manual_until("owner")


def test_delayed_official_return_recovers_only_during_manual_hour(tmp_path):
    from edof_day_session import awaiting_edof_return
    from edof_server_browser import returning_shell, EDOF_HOST
    result = {"code":"timeout","stage":"authentication","gmail_code_used":True,
              "diagnostics":{"callback_status":200,"location":"edof_initialisation"}}
    assert awaiting_edof_return(result)
    assert not awaiting_edof_return({**result,"gmail_code_used":False})
    assert not awaiting_edof_return({**result,"diagnostics":{"callback_status":401,"location":"edof_initialisation"}})
    assert returning_shell(f"https://{EDOF_HOST}/espace-prive/html/", result["diagnostics"])
    assert not returning_shell("https://example.invalid/espace-prive/html/", result["diagnostics"])
    vault = Vault(tmp_path, connector_key("test" * 12))
    instant = dt.datetime(2026,11,3,6,30,tzinfo=PARIS)
    until = instant.timestamp()+3600
    assert allow_login(vault, automatic=True, manual_until=until, now=instant)
    assert not allow_login(vault, automatic=True, manual_until=until, now=instant)
    assert allow_login(vault, automatic=True, manual_until=until, now=instant, recover_return=True)
    assert not allow_login(vault, automatic=True, manual_until=until, now=instant, recover_return=True)


def test_navigation_between_efp_and_edof_keeps_waiting_without_restarting():
    from unittest.mock import Mock
    import edof_server_browser as portal
    page = Mock()
    page.url = "https://"+portal.EFP_HOST+"/auth/"
    page.locator.return_value.count.return_value = 1
    check = Mock(side_effect=[RuntimeError("Execution context was destroyed, most likely because of a navigation"),None])
    assert not portal.open_workspace_or_login(page, Mock(), False, {}, check)
    assert check.call_count == 2 and page.goto.call_count == 1
    with pytest.raises(RuntimeError, match="not a navigation"):
        portal.open_workspace_or_login(page, Mock(), False, {}, Mock(side_effect=RuntimeError("not a navigation")))
