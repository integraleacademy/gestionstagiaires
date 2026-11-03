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
