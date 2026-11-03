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
    from playwright.sync_api import APIRequestContext
    from unittest.mock import Mock
    def private_read(_context, url, *, params, **_kw):
        reply = Mock(status=200, url=url)
        items = folders if params["state"] == "all" else []
        reply.body.return_value = json.dumps({"items":items, "numberOfItems":len(items)}).encode()
        return reply
    monkeypatch.setattr(APIRequestContext, "get", private_read)
    monkeypatch.setattr(runner, "read_pending_with_private_session", lambda *_: None)
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
            folders.append({"id":"100088","attendee":{"firstName":"Test","lastName":"Exemple"},"beginDate":"01/01/2026","currentState":"notProcessed"})
        assert vault.get(directory.record_key("fixture"))["rows"]["100088"]["state"] == "notProcessed"
        # A slow full scan must not erase the live tab or mask freshly read pending rows.
        import time
        full = vault.get(directory.record_key("fixture"))
        full["checked"] = time.time()-1800
        vault.put(directory.record_key("fixture"), full)
        vault.put("edof-full-attempt:fixture", time.time()-1800)
        snapshot = {"checked":time.time(),"rows":full["rows"]}
        vault.put(directory.pending_key("fixture"), snapshot)
        read_pending = Mock(return_value=snapshot)
        monkeypatch.setattr(runner, "read_pending_with_private_session", read_pending)
        scan = Mock(side_effect=runner.StopRun("bulk_deferred"))
        monkeypatch.setattr(runner, "read_recent_directory", scan)
        checked = runner.run_browser({"mode":"directory","day_session":True,"owner":"fixture"}, live=live)
        scan.assert_called_once()
        assert checked["code"] == "requests_ready" and not checked["gmail_code_used"]
        assert vault.get(directory.record_key("fixture")) == full
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


def test_pending_filter_reads_four_private_rows_and_preserves_other_dossiers(monkeypatch):
    import json
    import edof_directory as directory
    import edof_server_browser as reader
    from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
    raw = [{"id":str(100000+i),"attendee":{"firstName":"Test","lastName":"Exemple"},"beginDate":"01/01/2026","currentState":"notProcessed"} for i in range(4)]
    full = {"checked":1,"rows":{"999999":{"folder_id":"999999","session_start_date":"2026-01-01","session_end_date":"","state":"accepted"}}}
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("EDOF_TEST_CHROMIUM"), headless=True)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Chromium absent")
            raise
        page=browser.new_page()
        def local(route):
            assert route.request.method=="GET"
            if reader.API_PREFIX+"pad" in route.request.url:
                route.fulfill(json={"items":raw,"numberOfItems":4})
            else:
                route.fulfill(content_type="text/html",body="<meta charset=utf-8><button>À traiter <span>4</span></button><script>document.querySelector('button').onclick=()=>fetch("+json.dumps(reader.API_PREFIX+"pad?state=notProcessed")+")</script>")
        page.route("**/*",local)
        pending=reader.read_official_pending(page, lambda: None, BrowserTimeout)
        assert set(pending["rows"]) == {r["id"] for r in raw}
        merged=directory.with_pending(full,pending)
        assert len(merged["rows"])==5 and merged["pending_ids"]==set(pending["rows"])
        assert merged["checked"]==1 and merged["pending_checked"]==pending["checked"]
        assert directory.with_pending({**full,"checked":pending["checked"]+1},pending)["rows"]==full["rows"]
        browser.close()


def test_private_list_fallback_requires_complete_matching_rows():
    import json
    from unittest.mock import Mock
    from edof_server_browser import EDOF_HOST, API_PREFIX, read_pending_with_private_session
    base = "https://"+EDOF_HOST+API_PREFIX
    source = Mock(method="GET", url=base+"pad")
    source.all_headers.return_value={"accept":"application/json", "irrelevant":"discard"}
    context = Mock()
    raw=[{"id":str(200000+i),"attendee":{"firstName":"Test","lastName":"Exemple"},"beginDate":"01/01/2026","currentState":"notProcessed"} for i in range(4)]
    response=Mock(status=200,url=base+"pad?page=0&size=100&state=notProcessed")
    response.body.return_value=json.dumps({"items":raw,"numberOfItems":4}).encode()
    context.request.get.return_value=response
    assert len(read_pending_with_private_session(context,source)["rows"])==4
    assert context.request.get.call_args.kwargs["headers"]=={"accept":"application/json"}
    assert context.request.get.call_args.kwargs["max_redirects"]==0
    raw[1]["currentState"]="accepted"
    response.body.return_value=json.dumps({"items":raw,"numberOfItems":4}).encode()
    assert read_pending_with_private_session(context,source) is None
    context.reset_mock()
    source.url="https://unrelated.invalid"+API_PREFIX+"pad"
    assert read_pending_with_private_session(context,source) is None
    context.request.get.assert_not_called()


def test_no_cold_browser_without_existing_session_or_login_budget(tmp_path, monkeypatch):
    from edof_day_session import DayWorker
    from unittest.mock import Mock
    now=dt.datetime.now(PARIS)
    key=connector_key("test"*12)
    vault=Vault(tmp_path,key)
    vault.put("efp-login-day", {"date":now.date().isoformat(), "count":3})
    launch=Mock(side_effect=AssertionError("unexpected browser"))
    monkeypatch.setattr("edof_day_session.subprocess.Popen",launch)
    outcome=DayWorker().read({"owner":"example", "manual_until":now.timestamp()+3600},
                              {"EDOF_CONNECTOR_DIRECTORY":str(tmp_path), "EDOF_CONNECTOR_KEY":key},30)
    assert outcome["code"]=="day_login_used" and not outcome["gmail_code_used"]
    launch.assert_not_called()


def test_sorted_portal_query_stops_at_cutoff_and_keeps_january_first():
    import json
    from unittest.mock import Mock
    import edof_server_browser as reader
    url = f"https://{reader.EDOF_HOST}{reader.API_PREFIX}pad"
    source = Mock(method="GET", url=url)
    source.all_headers.return_value = {}
    ctx = Mock()
    def reply(_url, *, params, **kwargs):
        assert params["sort"] == "DATE_DEBUT_SESSION" and params["order"] == "DESC"
        days = (["2027-03-01","2026-01-01"], ["2025-12-31","2025-12-30"])[params["page"]]
        res = Mock(status=200,url=url)
        res.body.return_value = json.dumps({"numberOfItems":7000, "items":[
            {"id":str(100000+params["page"]*2+i),"currentState":"validated","beginDate":d,"trainingActionInfo":{
             "solicitations":[{"fundingType":9,"status":"inProgress"}]}} for i,d in enumerate(days)]}).encode()
        return res
    ctx.request.get.side_effect = reply
    result = reader.read_recent_directory(ctx,source,"all",lambda:None,{})
    assert set(result["rows"]) == {"100000","100001"} and ctx.request.get.call_count == 2
    assert result["rows"]["100001"]["ft_pending"]


def test_expired_verified_session_renews_after_restart_without_reusing_proof(tmp_path, monkeypatch):
    now = dt.datetime.now(PARIS).replace(hour=12, minute=15, second=0, microsecond=0)
    monkeypatch.setattr("edof_server_test.time.time", lambda: now.timestamp())
    store = ServerTestStore(tmp_path)
    key = store.connector_key = connector_key("test" * 12)
    vault = Vault(tmp_path, key)
    store.use_directory("A", enable=True)
    store.use_directory("B", enable=True)
    # Older deployments stored the count but no timestamp. Both owners are paused.
    vault.put("efp-login-day", {"date":now.date().isoformat(), "count":3})
    start = now.replace(hour=9, minute=21)
    with store.connect() as db:
        for index, (owner, moment, code) in enumerate((
            ("A",start,"requests_ready"), ("A",start+dt.timedelta(minutes=3),"day_login_used"),
            ("B",start+dt.timedelta(minutes=3),"day_login_used")
        )):
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?)", (str(index),owner,moment.timestamp()-10,
                       moment.timestamp(),"directory",'{"code":"'+code+'"}'))
    assert store.day_owners(now, daily=True) == ["A"]
    proof = store.verified_watch_at("A", now)
    assert allow_login(vault, automatic=True, owner="A", now=now, daily=True, verified_at=proof)
    assert not allow_login(Vault(tmp_path,key), automatic=True, owner="A", now=now+dt.timedelta(hours=1),
                           daily=True, verified_at=proof)
    assert store.day_owners(now+dt.timedelta(minutes=15), daily=True) == []
    # A fresh successful read allows a later expiry to recover, subject to the cooldown.
    fresh = now + dt.timedelta(minutes=2)
    with store.connect() as db:
        db.execute("INSERT INTO jobs VALUES('new','A',?,?,'directory',?)",
                   (fresh.timestamp()-5,fresh.timestamp(),'{"code":"directory_ready"}'))
        db.execute("INSERT INTO jobs VALUES('blocked','A',?,?,'directory',?)",
                   (fresh.timestamp()+60,fresh.timestamp()+61,'{"code":"day_login_used"}'))
    assert not store.day_owners(now+dt.timedelta(minutes=5), daily=True)
    assert store.day_owners(now+dt.timedelta(minutes=10), daily=True) == ["A"]
    assert store.day_owners(now.replace(hour=19), daily=True) == []
    with store.connect() as db:
        db.execute("INSERT INTO jobs VALUES('denied','A',?,?,'directory',?)",
                   (fresh.timestamp()+120,fresh.timestamp()+121,'{"code":"credentials_rejected"}'))
    assert store.next_renewal("A", now+dt.timedelta(minutes=20)) is None
    assert not store.day_owners(now+dt.timedelta(minutes=20), daily=True)


def test_enabled_weekend_watch_stops_at_19_and_respects_pause(tmp_path, monkeypatch):
    store = ServerTestStore(tmp_path)
    saturday = dt.datetime(2026,11,7,8,tzinfo=PARIS)
    monkeypatch.setattr("edof_server_test.time.time", lambda:saturday.timestamp())
    store.use_directory("A",enable=True)
    assert not store.day_owners(saturday-dt.timedelta(seconds=1), daily=True)
    assert store.day_owners(saturday, daily=True) == ["A"]
    assert not store.day_owners(saturday.replace(hour=19), daily=True)
    store.pause_directory("A")
    assert not store.day_owners(saturday, daily=True)
