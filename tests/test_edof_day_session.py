import datetime as dt
import os

import pytest

from edof_day_session import PARIS, allow_login, working_hours
from edof_gmail import Vault, connector_key
from edof_server_test import ServerTestStore


@pytest.mark.parametrize("instant, expected", [
    ("2026-11-02T05:59:59+00:00", False), ("2026-11-02T06:00:00+00:00", True),
    ("2026-11-06T17:59:59+00:00", True), ("2026-11-06T18:00:00+00:00", False),
    ("2026-11-07T12:00:00+00:00", True), ("2026-11-08T12:00:00+00:00", True),
    ("2027-07-05T04:59:59+00:00", False), ("2027-07-05T05:00:00+00:00", True),
])
def test_paris_hours(instant, expected):
    assert working_hours(dt.datetime.fromisoformat(instant)) is expected


def test_single_automatic_sign_in_survives_restart_and_manual_login(tmp_path):
    key = connector_key("test" * 12)
    now = dt.datetime(2026, 11, 6, 8, tzinfo=PARIS)
    for hour in (8,11,14,17):
        assert allow_login(Vault(tmp_path, key), now=now.replace(hour=hour))
    assert not allow_login(Vault(tmp_path, key), now=now.replace(hour=18))
    assert allow_login(Vault(tmp_path, key), now=now + dt.timedelta(days=1))
    monday = now + dt.timedelta(days=3)
    assert allow_login(Vault(tmp_path, key), now=monday)
    assert not allow_login(Vault(tmp_path, key), now=monday)
    assert allow_login(Vault(tmp_path, key), now=monday + dt.timedelta(days=1))


def test_failed_watch_resumes_next_day_and_respects_pause(tmp_path, monkeypatch):
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
        assert url in {"https://"+runner.EDOF_HOST+runner.API_PREFIX+"pad",
                       "https://"+runner.EDOF_HOST+runner.WORKSPACE_API_PREFIX+"organisms/current/factures"}
        items = folders if url.endswith("/pad") and params.get("state") == "all" else []
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
            result = runner.run_browser({"mode":"directory", "day_session":True, "full_sync":True, "owner":"fixture"}, live=live)
            assert result["code"] == "directory_ready", result
            assert result["gmail_code_used"] is False and result["fresh_session"] is False
            assert result["candidate_count"] == size
            folders.append({"id":"100088","attendee":{"firstName":"Test","lastName":"Exemple"},"beginDate":"01/01/2026","currentState":"notProcessed"})
        assert vault.get(directory.record_key("fixture"))["rows"]["100088"]["state"] == "notProcessed"
        # Age of the last general list never causes a background full scan.
        import time
        full = vault.get(directory.record_key("fixture"))
        full["checked"] = time.time()-1800
        vault.put(directory.record_key("fixture"), full)
        snapshot = {"checked":time.time(),"rows":full["rows"]}
        vault.put(directory.pending_key("fixture"), snapshot)
        read_pending = Mock(return_value=snapshot)
        monkeypatch.setattr(runner, "read_pending_with_private_session", read_pending)
        scan = Mock(side_effect=AssertionError("A new-only read attempted the general list"))
        monkeypatch.setattr(runner, "read_recent_directory", scan)
        checked = runner.run_browser({"mode":"directory","day_session":True,"owner":"fixture"}, live=live)
        scan.assert_not_called()
        assert checked["code"] == "requests_ready" and not checked["gmail_code_used"]
        assert vault.get(directory.record_key("fixture")) == full
        with monkeypatch.context() as scoped:
            scoped.setattr(runner, "open_workspace_or_login", lambda *a: pytest.fail("Warm poll reopened the portal"))
            assert runner.run_browser({"mode":"directory","day_session":True,"owner":"fixture"},live=live)["code"] == "requests_ready"
        with monkeypatch.context() as scoped:
            scoped.setattr(runner, "read_pending_with_private_session", lambda *a: None)
            scoped.setattr(runner, "read_official_pending", lambda *a: None)
            failed = runner.run_browser({"mode":"directory","day_session":True,"owner":"fixture"},live=live)
            assert failed["code"] == "pending_unavailable"
        scan.assert_not_called()
        assert vault.get(directory.record_key("fixture")) == full
        assert vault.get(directory.pending_key("fixture")) == snapshot
        # A dossier job uses the very same tab and EFP session, with only its own
        # write fence. All HTTP in this test stays on synthetic local routes.
        active_page = live["page"][1]
        def inspect_dossier(page, url, arrived, timeout):
            assert page is active_page
            page.evaluate("url => fetch(url)", "https://"+runner.EDOF_HOST+runner.API_PREFIX+"100088")
        def dossier_http(route, **kwargs):
            if route.request.url.endswith(runner.API_PREFIX+"100088"):
                return route.fulfill(json=folders[0])
            return local_reply(route, **kwargs)
        monkeypatch.setattr(Route,"continue_",dossier_http)
        monkeypatch.setattr(runner,"open_folder_view",inspect_dossier)
        monkeypatch.setattr(runner,"project_folder",lambda raw, **kw:{"folder_id":raw["id"]})
        from edof_declaration_form import SingleWrite
        def receipt(page,spec,fields,gate,reload_fields):
            assert page is active_page and isinstance(gate,SingleWrite) and not gate.armed and not gate.sent
            return {"code":"declaration_confirmed"}
        monkeypatch.setattr("edof_declaration_form.transmit",receipt)
        for mode in ("declare","reconcile"):
            result = runner.run_browser({"mode":mode,"owner":"fixture","shared_job":True,"folder_id":"100088",
                                         "intent":{"action":"service_done"}},live=live)
            assert result["code"] == "declaration_confirmed",result
            assert result["session_saved"] and not result["gmail_code_used"] and not result["fresh_session"]

        def entry_request(context, witness, spec, storage, origin, prefix):
            assert context is active_page.context or context.raw is active_page.context
            assert witness.method == "GET" and witness.url.startswith("https://" + runner.EDOF_HOST + runner.WORKSPACE_API_PREFIX)
            assert spec["folder_id"] == "100088"
            return {"code": "declaration_confirmed"}
        monkeypatch.setattr("edof_entry_request.run_entry", entry_request)
        for mode in ("declare", "reconcile"):
            result = runner.run_browser({"mode": mode, "owner": "fixture", "shared_job": True,
                                         "folder_id": "100088", "intent": {"action": "entry_training"}}, live=live)
            assert result["code"] == "declaration_confirmed" and not result["gmail_code_used"]
        monkeypatch.setattr("edof_entry_request.run_full_completion", entry_request)
        with monkeypatch.context() as scoped:
            scoped.setattr("edof_declaration_form.transmit", lambda *args: pytest.fail("Full exit reopened the form"))
            for mode in ("declare", "reconcile"):
                result = runner.run_browser({"mode": mode, "owner": "fixture", "shared_job": True,
                                             "folder_id": "100088", "intent": {"action": "service_done", "rate": 100}}, live=live)
                assert result["code"] == "declaration_confirmed" and not result["gmail_code_used"]
        # A real login form in this same previously verified tab ends the timer
        # before any mail lookup. This entire exchange is routed locally.
        timing = runner.session_clock.read_clock(vault, "fixture")
        assert timing["current"]["last"] >= timing["current"]["start"]
        login = f"https://{runner.EFP_HOST}/auth/realms/efp/login-actions/authenticate"
        def expired_portal(route, **kwargs):
            if route.request.url == login:
                return route.fulfill(content_type="text/html", body=f'<form method="post" action="{login}"><input name="username"><input type="password" name="password"></form>')
            return dossier_http(route, **kwargs)
        def require_login(page, context, saved, signals, checkpoint):
            page.goto(login)
            checkpoint()
            return False
        monkeypatch.setattr(Route, "continue_", expired_portal)
        monkeypatch.setattr(runner, "open_workspace_or_login", require_login)
        monkeypatch.setattr(runner, "read_pending_with_private_session", lambda *a: None)
        vault.put("efp-login-day", {"date":dt.datetime.now(PARIS).date().isoformat(),"count":4})
        result = runner.run_browser({"mode":"directory","day_session":True,"owner":"fixture",
                                    "manual_until":dt.datetime.now(PARIS).timestamp()+120},live=live)
        assert result["code"] == "day_login_used" and not result["gmail_code_used"]
        measured = runner.session_clock.read_clock(vault, "fixture")
        assert "current" not in measured and measured["previous"]["last"] == timing["current"]["last"]
        assert measured["previous"]["detected"] >= timing["current"]["last"]
        assert len(browser.contexts) == len(browser.contexts[0].pages) == 1
        browser.close()


def test_only_an_explicit_single_use_permit_can_exceed_four_codes(tmp_path):
    vault = Vault(tmp_path, connector_key("test" * 12))
    day = dt.datetime(2026, 11, 3, 8, tzinfo=PARIS)
    assert allow_login(vault, owner="A", now=day)
    assert allow_login(vault, owner="A", now=day.replace(hour=9))
    assert allow_login(vault, owner="A", now=day.replace(hour=11))
    assert allow_login(vault, owner="A", now=day.replace(hour=16))
    vault.put("day-login-override:A", day.date().isoformat(), ttl=600)
    assert not allow_login(vault, owner="B", now=day.replace(hour=17))
    assert allow_login(vault, owner="A", now=day.replace(hour=17))
    assert not allow_login(vault, owner="A", now=day.replace(hour=18))


def test_manual_window_expires_without_enabling_the_watch(tmp_path, monkeypatch):
    from edof_day_session import session_deadline
    saturday = dt.datetime(2026, 11, 7, 10, tzinfo=PARIS)
    monkeypatch.setattr("edof_server_test.time.time", lambda: saturday.timestamp())
    store = ServerTestStore(tmp_path)
    assert store.activate_manual("owner")
    assert not store.activate_manual("owner")
    until = store.manual_until("owner")
    assert not store.directory_enabled("owner")
    assert session_deadline(saturday, until) == saturday.replace(hour=19).timestamp()
    assert store.day_owners(saturday) == ["owner"]
    assert store.day_owners(saturday+dt.timedelta(hours=1)) == []
    vault = Vault(tmp_path, connector_key("test" * 12))
    assert allow_login(vault, manual_until=until, now=saturday)
    assert not allow_login(vault, manual_until=until, now=saturday+dt.timedelta(minutes=1))
    store.pause_directory("owner")
    assert not store.manual_until("owner")


def test_delayed_official_return_never_grants_a_second_code(tmp_path):
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
    assert allow_login(vault, manual_until=until, now=instant)
    assert not allow_login(vault, manual_until=until, now=instant)


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
    vault.put("efp-login-day", {"date":now.date().isoformat(), "count":4})
    launch=Mock(side_effect=AssertionError("unexpected browser"))
    monkeypatch.setattr("edof_day_session.subprocess.Popen",launch)
    outcome=DayWorker().read({"mode":"directory","owner":"example", "manual_until":now.timestamp()+3600},
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


def test_old_counters_keep_consumed_budget_when_four_codes_are_enabled(tmp_path, monkeypatch):
    now = dt.datetime.now(PARIS).replace(hour=12,minute=15,second=0,microsecond=0)
    monkeypatch.setattr("edof_server_test.time.time",lambda:now.timestamp())
    store = ServerTestStore(tmp_path)
    key = store.connector_key = connector_key("test"*12)
    vault = Vault(tmp_path,key)
    store.use_directory("A",enable=True)
    with store.connect() as db:
        for idx,code in enumerate(("directory_ready","day_login_used")):
            stamp = now.timestamp()-600+idx*60
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?)",
                       (str(idx),"A",stamp,stamp+2,"directory",'{"code":"'+code+'"}'))
    for legacy,allowed in ((now.date().isoformat(),True), ({"date":now.date().isoformat(),"count":3},True),
                           ({"date":now.date().isoformat(),"count":4},False)):
        vault.put("efp-login-day",legacy)
        vault.put("efp-paused-day",now.date().isoformat())
        assert bool(store.day_owners(now)) is allowed
        assert allow_login(Vault(tmp_path,key),owner="A",now=now) is allowed
        assert store.day_owners(now+dt.timedelta(days=1)) == ["A"]


def test_enabled_weekend_watch_stops_at_19_and_respects_pause(tmp_path, monkeypatch):
    store = ServerTestStore(tmp_path)
    saturday = dt.datetime(2026,11,7,7,tzinfo=PARIS)
    monkeypatch.setattr("edof_server_test.time.time", lambda:saturday.timestamp())
    store.use_directory("A",enable=True)
    assert not store.day_owners(saturday-dt.timedelta(seconds=1), daily=True)
    assert store.day_owners(saturday, daily=True) == ["A"]
    assert not store.day_owners(saturday.replace(hour=19), daily=True)
    store.pause_directory("A")
    assert not store.day_owners(saturday, daily=True)


def test_session_sort_disorder_does_not_hide_a_recent_dossier_on_a_later_page():
    import json
    from unittest.mock import Mock
    import edof_server_browser as reader
    witness = Mock(method="GET", url="https://"+reader.EDOF_HOST+reader.API_PREFIX+"pad")
    witness.all_headers.return_value = {}
    batches = [
        [("100001","2026-01-01"),("100002","2026-08-01")],
        [("100003","2025-01-01")],
        [("100004","2026-04-01")]
    ]
    def reply(url, *,params,**kwargs):
        assert params["filter"] == "tous"
        items = [{"id":key,"currentState":"accepted","beginDate":date} for key,date in batches[params["page"]]]
        result = Mock(status=200, url=url)
        result.body.return_value = json.dumps({"numberOfItems":4,"items":items}).encode()
        return result
    context = Mock()
    context.request.get.side_effect = reply
    snap = reader.read_recent_directory(context,witness,"all",lambda:None,{})
    assert set(snap["rows"]) == {"100001","100002","100004"}


def test_recent_accepted_tab_reconciles_without_certifying_a_complete_list():
    import edof_directory as directory
    def row(key,state):
        return {"folder_id":key, "session_start_date":"2026-11-16","state":state}
    full = {"checked":1,"rows":{"100001":row("100001","validated"),"100002":row("100002","accepted")}}
    accepted = {"checked":3,"rows":{"100001":row("100001","accepted")}}
    result = directory.with_accepted(full, accepted)
    assert set(result["rows"]) == {"100001"} and result["rows"]["100001"]["state"] == "accepted"
    assert result["checked"] == 1 and result["accepted_checked"] == 3
    pending = {"checked":4,"rows":{"100001":row("100001","notProcessed")}}
    assert directory.with_accepted(directory.with_pending(full,pending),accepted)["rows"]["100001"]["state"] == "notProcessed"
    assert directory.with_accepted({**full,"checked":5},accepted)["rows"] == full["rows"]


def test_dossier_login_is_limited_by_the_watch_even_in_a_fresh_browser(tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright, Route
    import edof_server_browser as runner

    key = connector_key("local-fixture-only" * 3)
    vault = Vault(tmp_path,key)
    today = dt.datetime.now(PARIS).date().isoformat()
    monkeypatch.setenv("RENDER_SERVICE_ID", runner.TEST_SERVICE_ID)
    monkeypatch.setenv("EDOF_CONNECTOR_KEY",key)
    monkeypatch.setenv("EDOF_CONNECTOR_DIRECTORY",str(tmp_path))
    monkeypatch.setenv("EDOF_EFP_USERNAME","fixture@example.invalid")
    monkeypatch.setenv("EDOF_EFP_PASSWORD","local-browser-fixture")
    vault.put("efp-login-day", {"date":today,"count":4})
    login = f"https://{runner.EFP_HOST}/auth/realms/efp/login-actions/authenticate"
    def local_only(route, **_):
        assert route.request.method == "GET"
        route.fulfill(content_type="text/html",body=f'<form method="post" action="{login}"><input name="username"><input type="password" name="password"><button id="kc-login">Entrer</button></form>')
    def login_form(page, *args):
        page.goto(login)
        return False
    monkeypatch.setattr(Route,"continue_",local_only)
    monkeypatch.setattr(runner,"open_workspace_or_login",login_form)
    monkeypatch.setattr(runner,"GmailCodes",lambda *args: pytest.fail("mailbox should not be opened"))
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("EDOF_TEST_CHROMIUM"),headless=True)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Chromium absent")
            raise
        for mode in ("directory","declare","reconcile","proposal_read","proposal_send","proposal_check"):
            spec = {"owner":"fixture","mode":mode,"day_session":mode=="directory","shared_job":True,
                    "manual_until":dt.datetime.now(PARIS).timestamp()+120,"intent":{"action":"entry_training"}}
            outcome = runner.run_browser(spec,live={"pw":pw,"browser":browser})
            assert outcome["code"]=="day_login_used" and not outcome["gmail_code_used"]
        assert vault.get("efp-login-day")["count"]==4
        browser.close()


def test_throttled_directory_does_not_retry_the_portal(tmp_path,monkeypatch):
    from unittest.mock import Mock
    import edof_server_browser as runner
    from edof_day_session import DayWorker
    witness = Mock(method="GET",url=f"https://{runner.EDOF_HOST}{runner.API_PREFIX}pad")
    witness.all_headers.return_value={}
    reply = Mock(status=429, headers={"retry-after":"7200"})
    ctx = Mock()
    ctx.request.get.return_value = reply
    with pytest.raises(runner.directory.PortalThrottled) as stopped:
        runner.read_recent_directory(ctx,witness,"all",lambda:None,{})
    assert stopped.value.delay == 7200 and ctx.request.get.call_count == 1
    assert runner.directory.PortalThrottled(None).delay == 60
    key = connector_key("test"*12)
    vault = Vault(tmp_path,key)
    vault.put("edof-throttled",True,ttl=7200)
    monkeypatch.setattr("edof_day_session.subprocess.Popen",Mock(side_effect=AssertionError("unexpected browser")))
    outcome = DayWorker().read({"mode":"directory","owner":"fixture","manual_until":dt.datetime.now(PARIS).timestamp()+60},
                               {"EDOF_CONNECTOR_DIRECTORY":str(tmp_path),"EDOF_CONNECTOR_KEY":key},30)
    assert outcome["code"]=="portal_throttled"


def test_efp_form_posts_are_single_use_and_allow_the_normal_otp_step(tmp_path,monkeypatch):
    from playwright.sync_api import Route,sync_playwright
    import edof_server_browser as runner
    key = connector_key("local-otp-fixture"*4)
    for name,value in {"RENDER_SERVICE_ID":runner.TEST_SERVICE_ID, "EDOF_CONNECTOR_KEY":key,
                       "EDOF_CONNECTOR_DIRECTORY":str(tmp_path),"EDOF_EFP_USERNAME":"fixture@example.invalid",
                       "EDOF_EFP_PASSWORD":"fixture-only"}.items():
        monkeypatch.setenv(name,value)
    root = f"https://{runner.EFP_HOST}/auth/realms/efp/login-actions/authenticate"
    calls = []
    def offline(route,**_):
        request=route.request
        if request.method=="GET":
            html=f'<form method="post" action="{root}?step=password"><input name="username"><input type="password" name="password"><button id="kc-login">Entrer</button></form>'
        else:
            calls.append(request.url)
            if request.url.endswith("step=password"):
                html=f'<form method="post" action="{root}?step=otp"><input name="otp" autocomplete="one-time-code"></form><script>fetch("{root}?step=resend",{{method:"POST"}}).catch(()=>{{}})</script>'
            else:
                html="Account is disabled"
        route.fulfill(content_type="text/html; charset=utf-8",body=html)
    def open_login(page,*args):
        page.goto(root)
        return False
    class Mailbox:
        def __init__(self,*args): pass
        def wait_for_code(self,requested_at,tick): return "123456"  # entirely local fixture
    monkeypatch.setattr(Route,"continue_",offline)
    monkeypatch.setattr(runner,"GmailCodes",Mailbox)
    monkeypatch.setattr(runner,"open_workspace_or_login",open_login)
    with sync_playwright() as pw:
        try:
            browser=pw.chromium.launch(executable_path=os.environ.get("EDOF_TEST_CHROMIUM"),headless=True)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc): pytest.skip("Chromium absent")
            raise
        outcome=runner.run_browser({"mode":"directory","owner":"fixture","day_session":True,
                  "manual_until":dt.datetime.now(PARIS).timestamp()+60},live={"pw":pw,"browser":browser})
        assert outcome["code"]=="account_unavailable" and outcome["gmail_code_used"], outcome
        assert calls==[root+"?step=password",root+"?step=otp"]
        assert Vault(tmp_path,key).get("efp-login-day")["count"]==1
        browser.close()

def test_watch_is_due_at_two_minutes(tmp_path,monkeypatch):
    start = dt.datetime(2026,11,7,7,tzinfo=PARIS)
    monkeypatch.setattr("edof_server_test.time.time", lambda: start.timestamp())
    store = ServerTestStore(tmp_path)
    store.use_directory("owner",enable=True)
    job = store.reserve("owner","directory",day_session=True)
    store.finish(job,{"code":"requests_ready","day_session":True})
    assert store.day_owners(start + dt.timedelta(seconds=119)) == []
    assert store.day_owners(start + dt.timedelta(seconds=120)) == ["owner"]
