import datetime as dt
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask, jsonify, session
import pytest

import cpf_provider as providers
import edof_directory
from edof_gmail import Vault
import edof_readonly_test as observer
import edof_server_test as server
import integrale_edof_dashboard as dashboard
from wedof_service import WedofApiError, WedofClient


def test_selection_survives_restart_and_fences_concurrent_work(tmp_path):
    a, b = providers.ProviderStore(tmp_path), providers.ProviderStore(tmp_path)
    assert a.state()["provider"] == "wedof"
    lock = a.acquire("wedof")
    with pytest.raises(providers.ProviderUnavailable):
        b.switch("integrale", 0, "admin")
    os.close(lock)
    assert b.switch("integrale", 0, "admin")["revision"] == 1
    with pytest.raises(providers.ProviderUnavailable):
        a.acquire("wedof")
    with pytest.raises(providers.ProviderUnavailable):
        a.switch("wedof", 0, "stale")
    native = a.acquire("integrale")
    with pytest.raises(providers.ProviderUnavailable):
        b.switch("wedof", 1, "admin")
    os.close(native)
    assert b.switch("wedof", 1, "admin")["revision"] == 2


def test_disabled_wedof_stops_transport_webhooks_cron_and_crm_and_resumes(tmp_path, monkeypatch):
    store = providers.ProviderStore(tmp_path)
    monkeypatch.setattr(providers, "current_store", lambda: store)
    calls = []
    app = Flask(__name__)
    for ep in ["wedof_webhook", "internal_cron_wedof_automation", "internal_cron_wedof_reconciliation",
               "send_wedof_to_crm", "internal_wedof_governor_reserve"]:
        def run(name=ep):
            calls.append(name)
            return jsonify(ok=True)
        app.add_url_rule("/"+ep, endpoint=ep, view_func=run, methods=["POST"])
    providers.register_wedof_guards(app)
    store.switch("integrale", 0, "admin")
    client = app.test_client()
    for ep in app.view_functions:
        if ep != "static":
            assert client.post("/"+ep).status_code in {200,409}
    assert not calls
    transport = object.__new__(WedofClient)
    transport._session = Mock()
    for method in (lambda: transport._get_json_response("/x"),lambda: transport._post_json_response("/x", {})):
        with pytest.raises(WedofApiError, match="désactivé"):
            method()
    assert not transport._session.mock_calls
    store.switch("wedof", 1, "admin")
    assert client.post("/internal_cron_wedof_automation").json["ok"]
    assert calls == ["internal_cron_wedof_automation"]


@pytest.fixture
def site(tmp_path, monkeypatch):
    store = server.ServerTestStore(tmp_path)
    gate = providers.ProviderStore(tmp_path)
    monkeypatch.setattr(providers, "current_store", lambda: gate)
    monkeypatch.setattr(server, "start_job", lambda *a: pytest.fail("Viewing or switching must not start a browser"))
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root/"templates"))
    # Stand in only for navigation routes outside this isolated EDOF app.
    app.url_build_error_handlers.append(lambda error, endpoint, values:
        None if endpoint.startswith(("integrale_edof.","edof_server_test.","edof_test.")) else "/navigation/"+endpoint)
    app.context_processor(lambda: dict(is_admin_logged_in=True, is_super_admin=True, partner_has_module=lambda _:True,
                                       sales_today_notification_count=0, admin_unresolved_total=0, admin_notifications=[]))
    app.add_url_rule("/session/<session_id>/stagiaire/<trainee_id>", "admin_trainee_page", lambda **kwargs: "stagiaire")
    app.secret_key = "synthetic-only-key-for-isolated-dashboard-tests"
    datafile = tmp_path / "data.json"
    data = {"sessions": [{"id":"s1", "name":"Formation test", "date_start":"2026-02-02", "date_end":"2026-02-06",
           "trainees":[{"id":"t1","first_name":"Anne","last_name":"Exemple","email":"anne@example.invalid"}]}]}
    datafile.write_text(json.dumps(data))
    def mutate(fn):
        current = json.loads(datafile.read_text())
        fn(current)
        datafile.write_text(json.dumps(current))
    legacy = SimpleNamespace(DATA_FILE=datafile, _atomic_update_data=mutate)
    access = lambda: session.get("admin_logged_in") and not session.get("assist_partner_id")
    observer.register_routes(app, observer.ObservationStore(tmp_path), admin_required=lambda f:f,
                             can_access=access, data_file=datafile, dashboard=True)
    server.register_routes(app, store, legacy=legacy, admin_required=lambda f:f, can_access=access)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update(admin_logged_in=True, admin_username="admin")
    assert client.get("/admin/edof-test").status_code == 200
    with client.session_transaction() as sess:
        owner, csrf = sess["edof_history_account"], sess["edof_server_csrf"]
    records = [{"folder_id":str(100000+i),"first_name":"Anne","last_name":"Exemple","title":"Formation test",
               "state":state,"session_start_date":"2026-02-02","session_end_date":"2026-02-06"}
               for i,state in enumerate(("Accepté", "Entrée déclarée", "A traiter", "Annulé par le titulaire"))]
    vault = Vault(tmp_path, store.connector_key)
    vault.put(edof_directory.record_key(owner), {"checked":10000,"rows":{r["folder_id"]:r for r in records}})
    return SimpleNamespace(client=client, gate=gate, csrf=csrf, store=store, local=datafile, vault=vault, owner=owner)


def test_tabs_render_native_data_and_read_only_efp(site):
    for section in dashboard.SECTIONS:
        reply = site.client.get("/admin/edof-test", query_string={"section":section})
        assert reply.status_code == 200 and "Pilotage des dossiers CPF" in reply.text
        assert "wedof-hero" in reply.text and "app-shell" in reply.text
        if section == "technical":
            assert "Activer Intégrale EDOF" in reply.text
    assert "100002" in site.client.get("/admin/edof-test?section=requests").text
    assert "100003" in site.client.get("/admin/edof-test?section=cancellations").text
    assert "100001" in site.client.get("/admin/edof-test?tab=training").text
    assert "100001" not in site.client.get("/admin/edof-test?tab=accepted").text
    assert "100000" in site.client.get("/admin/edof-test?q=exemple+anne").text
    assert site.client.get("/admin/edof-test/lecture-chrome").status_code == 200
    assert site.client.get("/admin/edof-test?folder=100000").status_code == 200
    bad = site.client.post("/admin/edof-test/provider", data={"provider":"integrale","revision":0})
    assert bad.status_code == 403


def test_full_switch_block_associate_prepare_resume(site):
    client = site.client
    post = lambda path,**kw: client.post("/admin/edof-test/"+path, data={"csrf":site.csrf,**kw}, follow_redirects=True)
    assert "désactivé" in post("dossiers/100000/block",action="entry_training",reason="no_show").text
    assert "Désactiver Intégrale EDOF" in post("provider",provider="integrale",revision=0).text
    assert "a changé" in post("provider",provider="wedof",revision=0).text
    assert site.gate.state()["provider"] == "integrale"
    assert "Automatisation bloquée" in post("dossiers/100000/block",action="entry_training",reason="no_show").text
    draft={"action":"entry_training","actual_date":"2026-02-02","evidence":"Présence signée","attested":"yes"}
    assert "dossier est bloqué" in post("dossiers/100000/prepare",**draft).text
    assert "Blocage levé" in post("dossiers/100000/block",action="entry_training",release="yes").text
    assert "Déclaration préparée" in post("dossiers/100000/prepare",**draft).text
    assert "Association locale enregistrée" in post("dossiers/100000/associate",session_id="s1",trainee_id="t1",verified="yes").text
    assert "Suivi local" in post("dossiers/100002/follow-up",change="handled").text
    assert "Désactiver WeDoF" in post("provider",provider="wedof",revision=1).text
    assert len(json.loads(site.local.read_text())["wedof_links"]) == 1
    assert dashboard.local_operations(site.gate)["100000"]["draft"]["actual_date"] == "2026-02-02"


def test_exit_requires_real_data_and_partial_reason():
    row={"state":"inTraining", "session_start_date":"2026-02-02", "session_end_date":"2026-02-06"}
    fields={"action":"service_done","actual_date":"2026-02-06","evidence":"Attestation signée","attested":"yes"}
    for values in ({}, {"rate":"65"}, {"rate":"101"}, {"rate":"100","actual_date":"2100-02-02"}):
        with pytest.raises(ValueError):
            dashboard.declaration_draft(row,{**fields,**values})
    assert dashboard.declaration_draft(row,{**fields,"rate":"65","reason":"Interruption documentée"})["rate"] == 65


def test_partner_and_viewer_cannot_switch(site):
    for changes in [{"assist_partner_id":"other"},{"assist_partner_id":"","admin_role":"viewer"}]:
        with site.client.session_transaction() as s:
            s.update(changes)
        result=site.client.post("/admin/edof-test/provider",data={"provider":"integrale","revision":0,"csrf":site.csrf})
        assert result.status_code == 403 and site.gate.state()["revision"] == 0


def test_sync_preserves_history_and_ignores_old_exercise_dates(site):
    from integrale_edof_sync import process_directory
    snap = {"checked":100,"rows":{"100000":{"folder_id":"100000","state":"accepted"}}}
    from integrale_edof_dashboard import record_work
    record_work(site.gate, "100000", "LMS", draft=json.dumps({
        "action":"entry_training","source":"lms","actual_date":"2026-02-03","evidence":"Premier exercice"}))
    process_directory(site.store,snap)
    process_directory(site.store,{"checked":101,"rows":{"100000":{"folder_id":"100000","state":"inTraining"}}})
    process_directory(site.store,snap)
    with site.gate.connect() as db:
        assert list(map(tuple,db.execute("SELECT previous,state FROM directory_events"))) == [("accepted","entry")]
    assert not dashboard.local_operations(site.gate)["100000"]["draft"]
    site.gate.switch("integrale",0,"admin")
    html = site.client.get("/admin/edof-test?folder=100000").text
    assert 'name="actual_date" value="2026-02-02"' in html and "Premier exercice" not in html


def test_activation_after_weeks_schedules_one_refresh_and_stops_after_auth_error(tmp_path):
    store = server.ServerTestStore(tmp_path)
    store.request_directory("admin")
    assert store.due_directories() == ["admin"]
    job = store.reserve("admin","directory")
    store.finish(job, {"code":"credentials_rejected"})
    assert store.due_directories() == []


def test_selected_folder_scope_and_unconfirmed_billing():
    assert dashboard.category({"state":"canceledByAttendeeNotRealized"}) == "canceled"
    assert dashboard.category({"state":"waitingAcceptation"}) == "waiting"
    assert dashboard.category({"state":"serviceDoneValidated","billing_state":"billed"}) == "invoiced"
    assert dashboard.category({"state":"serviceDoneValidated"}) == "billable"


def test_simulate_at_actual_paris_cutoff_without_sending(site):
    before = dt.datetime(2026,2,2,7,59,tzinfo=dashboard.PARIS)
    after = before + dt.timedelta(minutes=1)
    assert dashboard.simulate("accepted", "2026-02-02", None, None, before) == "planned"
    assert dashboard.simulate("accepted", "2026-02-02", None, None, after) == "unconfirmed"
    assert dashboard.simulate("accepted", "2026-02-02", {"active":True}, None, after) == "blocked"
    assert dashboard.simulate("accepted", "2026-02-02", None, {"action":"entry_training","evidence":"LMS","actual_date":"2026-02-02"}, after) == "ready"
    reply = site.client.get("/admin/edof-test?section=state&simulation=1")
    assert reply.status_code == 200 and "Résultat du test des automatisations" in reply.text
    assert site.gate.state()["provider"] == "wedof"


@pytest.mark.parametrize("target", ["crm","salesforce"])
def test_native_transfer_is_complete_and_idempotent_across_switches(site, target, monkeypatch):
    from integrale_edof_transfers import transfer, respect_native_receipt
    monkeypatch.setenv("CRM_WEDOF_WEBHOOK_SECRET","fixture-only")
    sent = []
    def external(entry):
        envelope = entry["payload"]
        assert envelope["externalId"] == "100002" and envelope["attendee"]["email"].endswith(".invalid")
        sent.append(entry["delivery_id"])
        entry.update({target+"_sent":True, "crm_processed":True})
        return {"success":True}, 200
    legacy=SimpleNamespace(_send_wedof_entry_to_crm=external, _send_wedof_entry_to_salesforce=external, _load_wedof_webhooks=lambda:[])
    source={"folder_id":"100002","first_name":"Anne","last_name":"Exemple","email":"anne@example.invalid"}
    site.gate.switch("integrale",0,"admin")
    assert "accusé réception" in transfer(site.gate,legacy,source,target,"https://official.invalid/folder")
    assert "déjà" in transfer(site.gate,legacy,source,target,"https://official.invalid/folder")
    site.gate.switch("wedof",1,"admin")
    wrapped = respect_native_receipt(target)(lambda entry: pytest.fail("duplicate sent on reactivation"))
    assert wrapped({"folder_id":"100002","payload":{}})[0]["skipped"]
    assert len(sent)==1


def test_uncertain_or_historical_native_delivery_is_not_replayed(site):
    from integrale_edof_transfers import transfer
    row={"folder_id":"100002","first_name":"Anne","last_name":"Exemple","email":"anne@example.invalid"}
    fn=Mock(side_effect=TimeoutError())
    legacy=SimpleNamespace(_send_wedof_entry_to_salesforce=fn, _load_wedof_webhooks=lambda:[])
    with pytest.raises(ValueError,match="à vérifier"):
        transfer(site.gate,legacy,row,"salesforce","")
    with pytest.raises(ValueError,match="à vérifier"):
        transfer(site.gate,legacy,row,"salesforce","")
    assert fn.call_count==1
    legacy._load_wedof_webhooks=lambda:[{"folder_id":"100003","salesforce_sent":True}]
    assert "déjà" in transfer(site.gate,legacy,{**row,"folder_id":"100003"},"salesforce","")


def test_bulk_preview_and_sync_use_verified_remote_contacts(site):
    folder={"folder_id":"100000","first_name":"Anne","last_name":"Exemple","email":"anne@example.invalid","state":"accepted"}
    job=site.store.reserve(site.owner,"read")
    site.store.finish(job,{"code":"read_success","fields":folder})
    result=site.client.get("/admin/edof-test?section=state&matching=1")
    assert result.status_code==200 and "Prévisualisation des correspondances" in result.text
    assert site.gate.state()["provider"]=="wedof"


def test_legacy_french_dates_work_in_live_simulation_and_declarations_without_remote_refresh(site):
    key=edof_directory.record_key(site.owner)
    snapshot=site.vault.get(key)
    snapshot["rows"]["100000"].update(session_start_date="02/02/2026",session_end_date="06/02/2026")
    site.vault.put(key,snapshot)
    response=site.client.get("/admin/edof-test?simulation=1")
    assert response.status_code == 200
    row = response.text.split('<tr data-edof-folder="100000">',1)[1].split("</tr>",1)[0]
    assert "02/02/2026" in row and "Déclaration à compléter" in row
    assert "Date à vérifier" not in row
    site.gate.switch("integrale",0,"admin")
    result=site.client.post("/admin/edof-test/dossiers/100000/prepare", data={
        "action":"entry_training","actual_date":"2026-02-03","attested":"yes","evidence":"Présence signée","csrf":site.csrf}, follow_redirects=True)
    assert "Déclaration préparée" in result.text
    assert edof_directory.session_date("31/02/2026") == ""


def test_new_requests_counts_official_state_independently_of_local_notes(site):
    page = site.client.get("/admin/edof-test?section=state&tab=request")
    assert page.status_code == 200
    assert page.text.index("<span>Nouvelle demande</span>") < page.text.index("<span>Acceptés</span>")
    assert "<strong>1</strong><span>Nouvelle demande</span>" in page.text
    assert "100002" in page.text and "100001" not in page.text
    dashboard.record_work(site.gate, "100002", "admin", handled=1)
    assert "100002" in site.client.get("/admin/edof-test?section=state&tab=request").text
    assert "100002" in site.client.get("/admin/edof-test?section=requests").text
    dashboard.record_work(site.gate, "100002", "admin", handled=0, archived=1)
    page = site.client.get("/admin/edof-test?section=state&tab=request")
    assert "<strong>1</strong><span>Nouvelle demande</span>" in page.text and "Archivée localement" in page.text
    assert dashboard.category({"state":"Non traité"}) == "request"
    assert dashboard.category({"state":"Accepté"}) == "accepted"


def test_program_day_without_immediate_login_or_provider_switch(site, monkeypatch):
    monkeypatch.setattr(server, "configuration", lambda: {"credentials_configured":True})
    site.vault.put("gmail", {"fixture":True})
    target = "/admin/edof-test/server/directory/schedule"
    assert site.client.post(target, data={"csrf":""}).status_code == 403
    assert site.client.post(target, data={"csrf":site.csrf}).status_code == 303
    assert site.store.directory_enabled(site.owner)
    assert site.gate.state()["provider"] == "wedof" and not site.store.latest(site.owner)


def test_admin_resume_requires_a_paused_open_watch(site, monkeypatch):
    monkeypatch.setattr(server, "working_hours", lambda **kwargs:True)
    site.store.use_directory(site.owner, enable=True)
    url = "/admin/edof-test/server/directory/resume"
    assert site.client.post(url, data={"csrf":site.csrf}).status_code == 409
    jid = site.store.reserve(site.owner, "directory", day_session=True)
    site.store.finish(jid, {"code":"day_login_used","day_session":True})
    assert site.client.post(url, data={"csrf":""}).status_code == 403
    assert site.client.post(url, data={"csrf":site.csrf}).status_code == 303
    assert site.vault.get("day-login-override:"+site.owner) == dt.datetime.now(dashboard.PARIS).date().isoformat()
    assert site.gate.state()["provider"] == "wedof"


def test_manual_activation_updates_lamp_only_after_private_read(site, monkeypatch):
    monkeypatch.setattr(server, "configuration", lambda: {"credentials_configured": True})
    site.vault.put("gmail", {"fixture":True})
    path = "/admin/edof-test/server/directory/manual"
    assert site.client.post(path, data={"csrf":""}).status_code == 403
    assert site.client.post(path, data={"csrf":site.csrf}).status_code == 303
    expires = site.store.manual_until(site.owner)
    assert expires and site.gate.state()["provider"] == "wedof"
    assert site.client.post(path, data={"csrf":site.csrf}).status_code == 303
    assert expires == site.store.manual_until(site.owner)
    badge = "/admin/edof-test/connection-status"
    assert site.client.get(badge).json["active"] is False
    jid = site.store.reserve(site.owner, "directory", day_session=True)
    assert site.client.get(badge).json["pending"] is True
    site.vault.put("browser", {"cookies":[{"name":"fixture"}]})
    site.store.finish(jid, {"code":"directory_ready", "day_session":True})
    assert site.client.get(badge).json["active"] is True
    assert "Connexion EDOF active" in site.client.get("/admin/edof-test").text
    jid = site.store.reserve(site.owner, "directory", day_session=True)
    site.store.finish(jid, {"code":"day_login_used", "day_session":True})
    assert not site.client.get(badge).json["active"]


def test_processing_pages_classify_official_states_and_exclude_legacy_folders(site):
    snapshot = site.vault.get(edof_directory.record_key(site.owner))
    template = snapshot["rows"]["100000"]
    cases = {"waiting":{"state":"validated"}, "ft":{"state":"validated","ft_pending":True},
             "out":{"state":"terminated"}, "declared":{"state":"serviceDoneDeclared"},
             "billable":{"state":"serviceDoneValidated"}, "invoiced":{"state":"serviceDoneValidated","billing_state":"billed"},
             "paid":{"state":"serviceDoneValidated","billing_state":"billed","payment_state":"Issued"}}
    for i, fields in enumerate(cases.values()):
        folder = str(200000+i)
        snapshot["rows"][folder] = {**template, "folder_id":folder, **fields}
    old = {**template,"folder_id":"900000","session_start_date":"31/12/2025"}
    snapshot["rows"][old["folder_id"]] = old
    site.vault.put(edof_directory.record_key(site.owner), snapshot)
    site.vault.put(edof_directory.pending_key(site.owner), {"checked":snapshot["checked"]+1,"rows":{old["folder_id"]:old}})
    for i, tab in enumerate(cases):
        section = "requests" if tab in dashboard.REQUEST_TABS else "automations"
        page = site.client.get("/admin/edof-test", query_string={"section":section, "tab":tab})
        assert page.status_code == 200 and dashboard.SECTIONS[section] in page.text
        assert "900000" not in page.text and str(200000+i) in page.text
        assert all(str(200000+j) not in page.text for j in range(len(cases)) if i != j)
    assert site.client.get("/admin/edof-test?folder=900000").status_code == 404


def test_global_hold_survives_state_changes_and_release(site):
    import edof_declarations as ledger
    site.gate.switch("integrale", 0, "admin")
    url = "/admin/edof-test/dossiers/100000/hold"
    assert site.client.post(url, data={"csrf":site.csrf, "hold":"yes"}).status_code == 303
    row = site.vault.get(edof_directory.record_key(site.owner))["rows"]["100000"]
    for action in ("entry_training","service_done"):
        draft = {"action":action,"actual_date":"2026-02-02","evidence":"Feuille signée","rate":100}
        assert ledger.enqueue(site.store.directory,site.owner,1,row,draft,"test",automatic=True) == "paused"
    assert site.client.post(url,data={"csrf":site.csrf}).status_code == 303
    assert not ledger.folder_holds(site.store.directory)


def test_trainee_import_requires_verified_detail_and_is_idempotent(site, monkeypatch):
    import integrale_edof_registration as registrations
    started = []
    monkeypatch.setattr(server, "start_job", lambda *args: started.append(args[-1]))
    post = lambda folder: site.client.post(f"/admin/edof-test/dossiers/{folder}/create-trainee",
                                            data={"csrf":site.csrf,"session_id":"s1"}, follow_redirects=True)
    assert "Choisissez une session" in post("100002").text and not started
    assert "Lecture de la fiche complète" in post("100000").text
    assert started[0]["folder_id"] == "100000" and started[0]["import_session"] == "s1"
    data = json.loads(site.local.read_text())
    fields = {**site.vault.get(edof_directory.record_key(site.owner))["rows"]["100000"], "birth_date":"1986-03-12",
              "email":"edof@example.invalid","phone":"0600000000", "total_incl":"1250.00"}
    def mutate(fn):
        saved = json.loads(site.local.read_text())
        fn(saved)
        site.local.write_text(json.dumps(saved))
    legacy = SimpleNamespace(INTEGRALE_PARTNER_ID="academy", _atomic_update_data=mutate,
                             _session_trainees_list=lambda s:s["trainees"],
                             _new_session_trainee=lambda s,r: {"id":"test-id", **{k:r[k] for k in ("first_name","last_name","email","birth_date","phone")}},
                             _apply_pending_cnaps_imports_for_trainee=Mock(), increment_partner_trainee_usage=Mock())
    with pytest.raises(ValueError,match="existe déjà"):
        registrations.create_registration(legacy,"100000","s1",fields)
    data["sessions"][0]["trainees"].clear()
    site.local.write_text(json.dumps(data))
    for _ in range(2):
        registrations.create_registration(legacy,"100000","s1",fields)
    saved = json.loads(site.local.read_text())
    assert len(saved["sessions"][0]["trainees"]) == len(saved["wedof_links"]) == 1
    trainee = saved["sessions"][0]["trainees"][0]
    from cpf_tracking import has_cpf_financing
    assert has_cpf_financing(trainee) and not trainee.get("cpf_amount")
    assert trainee["birth_date"] == fields["birth_date"] and trainee["phone"] == fields["phone"]
    assert trainee["edof_registration"]["folder_id"] == "100000" and trainee["training_price"] == "1250.00"


def test_deadlines_use_the_action_date_and_hour_and_sort_by_distance():
    now = dt.datetime(2026, 11, 3, 14, tzinfo=dashboard.PARIS)
    def row(folder, state, start, end):
        return {"folder_id":folder,"state":state,"session_start_date":start,"session_end_date":end}
    records = [
        row("100001","accepted","2026-11-04","2026-11-28"),
        row("100002","inTraining","2026-01-01","2026-11-03"),
        row("100003","accepted","2026-11-03","2026-11-26"),
        row("100004","accepted","2026-11-03","2026-12-14"),
        row("100005","inTraining","2026-02-02",""),
        row("100006","accepted","2026-11-03","2026-11-20"),
    ]
    blocks = {"wedof_automation_blocks":[{"external_id":"100006","active":True,"action":"both"}]}
    rows, _ = dashboard.dashboard_rows({"rows":{r["folder_id"]:r for r in records}}, blocks, {}, now)
    dashboard.prioritize_rows(rows, now)
    assert [r["folder_id"] for r in rows[:4]] == ["100002","100003","100004","100001"]
    assert rows[0]["scheduled"].hour == 18 and rows[1]["scheduled"].hour == 8
    assert rows[1]["due"] and rows[0]["evaluation"] == "planned"
    assert {r["evaluation"] for r in rows[4:]} == {"missing","blocked"}


@pytest.mark.parametrize("section", ["state","automations"])
def test_due_pages_filter_and_sort_before_paginating(site, section):
    today = dt.datetime.now(dashboard.PARIS).date()
    base = site.vault.get(edof_directory.record_key(site.owner))["rows"]["100000"]
    records = {}
    for i in reversed(range(29)):
        number = str(910000+i)
        records[number] = {**base, "folder_id":number, "session_start_date":(today+dt.timedelta(days=8+i)).isoformat()}
    records["900000"] = {**base,"folder_id":"900000","state":"inTraining","session_end_date":today.isoformat()}
    site.vault.put(edof_directory.record_key(site.owner), {"checked":10000,"rows":records})
    def ids(page):
        response = site.client.get("/admin/edof-test",query_string={"section":section,"tab":"due","page":page,"q":"Exemple"})
        assert response.status_code == 200
        return re.findall(r'<tr data-edof-folder="(\d+)">', response.text)
    assert ids(1) == ["900000", *[str(910000+i) for i in range(24)]]
    assert ids(2) == [str(910000+i) for i in range(24,29)]


def test_sync_badge_distinguishes_general_list_requests_and_later_login(site):
    from contextlib import closing
    import time
    stamp = time.time() - 1200
    full_time = stamp - 86400
    snapshot = site.vault.get(edof_directory.record_key(site.owner))
    site.vault.put(edof_directory.record_key(site.owner), {**snapshot, "checked":full_time})
    site.vault.put(edof_directory.pending_key(site.owner), {"rows":{}, "checked":stamp})
    label = edof_directory.stamp({"checked":stamp})
    general = edof_directory.stamp({"checked":full_time})
    html = site.client.get("/admin/edof-test").text
    assert f"Dernière synchronisation · {label} · Demandes à traiter" in html
    assert f"Liste générale · {general}" in html
    with closing(site.store.connect()) as db, db:
        for jid, owner, mode, offset, code in (
            ("full",site.owner,"directory",-86400,"directory_ready"),
            ("requests",site.owner,"directory",0,"requests_ready"),
            ("later-login",site.owner,"directory",180,"day_login_used"),
            ("other-mode",site.owner,"read",240,"read_success"),
            ("another-owner","other","directory",360,"directory_ready")
        ):
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?)",
                       (jid,owner,stamp,stamp+offset,mode,json.dumps({"code":code})))
    badge = site.client.get("/admin/edof-test/connection-status").json
    assert badge["stamp"] == stamp+180 and badge["active"] is False
    assert badge["sync"] == {"stamp":stamp,"label":label,"scope":"Demandes à traiter",
                             "full_stamp":full_time,"full_label":general}
    with closing(site.store.connect()) as db, db:
        db.execute("UPDATE jobs SET finished=? WHERE id='full'", (stamp+400,))
    assert site.client.get("/admin/edof-test/connection-status").json["sync"]["scope"] == "Liste générale"


def test_full_sync_button_queues_once_survives_restart_and_preserves_provider(site, monkeypatch):
    monkeypatch.setattr(server,"configuration",lambda:{"credentials_configured":True})
    site.vault.put("gmail", {"fixture":True})
    path = "/admin/edof-test/synchroniser"
    headers = {"Accept":"application/json"}
    assert site.client.post(path, headers=headers).status_code == 403
    for _ in range(2):
        assert site.client.post(path, data={"csrf":site.csrf}, headers=headers).status_code == 202
    store = server.ServerTestStore(site.store.directory)
    assert store.next_manual_sync()["owner"] == site.owner
    job = store.reserve(site.owner,"directory",day_session=True,sync_scope="all")
    assert store.next_manual_sync() is None and store.manual_sync_status(site.owner,"all")["busy"]
    with open(store.directory / "edof_server_test.lock", "a") as active:
        server.fcntl.flock(active, server.fcntl.LOCK_EX)
        store.recover_directory_reads()
        assert store.next_manual_sync() is None
    store.recover_directory_reads()
    assert store.next_manual_sync()["owner"] == site.owner
    retry = store.reserve(site.owner,"directory",day_session=True,sync_scope="all")
    store.finish(retry, {"code":"requests_ready"})
    assert "liste générale n’a pas pu" in store.manual_sync_status(site.owner,"all")["message"]
    assert store.next_manual_sync() is None
    assert site.gate.state()["provider"] == "wedof" and not store.directory_enabled(site.owner)
    assert store.manual_sync_status("someone-else","all") is None
    with site.client.session_transaction() as session:
        session["admin_role"] = "viewer"
    assert site.client.post(path,data={"csrf":site.csrf},headers=headers).status_code == 403


def test_course_header_and_folded_sections_show_session_first(site):
    html = site.client.get("/admin/edof-test?section=requests&tab=request&folder=100002").text
    assert "<h1>Formation test</h1>" in html and "<strong>Anne Exemple</strong>" in html
    assert "Synchro manuelle nouveaux dossiers" in html and "Synchro manuelle tous les dossiers" in html
    assert 'data-manual-sync="new"' in html and 'data-manual-sync="all"' in html
    assert re.findall(r'data-fold="(\w+)" open',html) == ["session"]
    session_fields = html.split('data-fold="session"',1)[1].split("</details>",1)[0]
    assert 'name="sessionStartDate" value="2026-02-02"' in session_fields
    assert 'name="priceTotal"' in session_fields and 'name="trainingGoal"' in html

def test_new_and_full_manual_requests_are_independent_and_coalesced(site,monkeypatch):
    monkeypatch.setattr(server,"configuration",lambda:{"credentials_configured":True})
    site.vault.put("gmail", {"fixture":True})
    def post(scope):
        return site.client.post("/admin/edof-test/synchroniser", data={"scope":scope,"csrf":site.csrf},
                                headers={"Accept":"application/json"})
    assert post("unknown").status_code == 400
    for scope in ["new","all","new","all"]:
        assert post(scope).status_code == 202
    store = server.ServerTestStore(site.store.directory)
    assert store.next_manual_sync()["scope"] == "new"
    job = store.reserve(site.owner,"directory",day_session=True,sync_scope="new")
    assert store.next_manual_sync()["scope"] == "all"
    store.finish(job,{"code":"requests_ready"})
    badge = site.client.get("/admin/edof-test/connection-status").json
    assert not badge["new_sync"]["busy"] and "Nouveaux dossiers" in badge["new_sync"]["message"]
    assert badge["manual_sync"]["busy"]
    assert not store.directory_enabled(site.owner)

def test_legacy_full_request_survives_queue_upgrade(site):
    from contextlib import closing
    import time
    with closing(site.store.connect()) as db, db:
        db.execute("CREATE TABLE manual_directory (owner TEXT PRIMARY KEY, requested REAL, job_id TEXT)")
        db.execute("INSERT INTO manual_directory VALUES(?,?,NULL)",(site.owner,time.time()))
    assert site.store.next_manual_sync()["scope"] == "all"
    assert site.store.manual_sync_status(site.owner,"all")["busy"]
