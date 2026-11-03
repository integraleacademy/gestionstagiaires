import datetime as dt
import json
import os
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


def test_native_sync_prepares_entries_from_real_activity_and_never_replays_history(site, tmp_path):
    import sqlite3
    from integrale_edof_sync import process_directory
    record = {"folder_id":"100000", "state":"accepted","session_start_date":"2026-02-02","session_end_date":"2026-02-06"}
    data = json.loads(site.local.read_text())
    data["wedof_links"] = [{"external_id":"100000","session_id":"s1","trainee_id":"t1","active":True}]
    site.local.write_text(json.dumps(data))
    (tmp_path/"native_elearning").mkdir()
    with sqlite3.connect(tmp_path/"native_elearning"/"tracking.sqlite3") as db:
        db.execute("CREATE TABLE tracking_events(id INTEGER, session_id TEXT, trainee_id TEXT,event_type TEXT,activity_id TEXT,event_at TEXT)")
        db.executemany("INSERT INTO tracking_events VALUES(?, 's1', 't1',?, 'unit',?)",
                       [(1,"session_opened","2026-02-02T10:00:00Z"),(2,"content_completed","2026-02-03T10:00:00Z")])
    snap = {"checked":100, "rows":{"100000":record}}
    process_directory(site.store,snap,site.local)
    draft=dashboard.local_operations(site.gate)["100000"]["draft"]
    assert draft["actual_date"] == "2026-02-03" and draft["source"] == "lms"
    process_directory(site.store,{"checked":101,"rows":{"100000":{**record,"state":"inTraining"}}},site.local)
    process_directory(site.store,snap,site.local)
    with site.gate.connect() as db:
        assert list(map(tuple,db.execute("SELECT previous,state FROM directory_events"))) == [("accepted","training")]
    assert dashboard.local_operations(site.gate)["100000"]["draft"] == draft


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
    assert dashboard.category({"state":"serviceDoneValidated"}) == "service"


def test_simulate_at_actual_paris_cutoff_without_sending(site):
    before = dt.datetime(2026,2,2,17,59,tzinfo=dashboard.PARIS)
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
    row = next(part.split("</tr>", 1)[0] for part in response.text.split("<tr>") if ">100000</a>" in part)
    assert "02/02/2026" in row and "Justificatif à renseigner" in row
    assert "Date à vérifier" not in row
    site.gate.switch("integrale",0,"admin")
    result=site.client.post("/admin/edof-test/dossiers/100000/prepare", data={
        "action":"entry_training","actual_date":"2026-02-03","attested":"yes","evidence":"Présence signée","csrf":site.csrf}, follow_redirects=True)
    assert "Déclaration préparée" in result.text
    assert edof_directory.session_date("31/02/2026") == ""


def test_new_requests_tab_counts_current_unarchived_requests(site):
    page = site.client.get("/admin/edof-test?section=state&tab=request")
    assert page.status_code == 200
    assert page.text.index("<span>Nouvelle demande</span>") < page.text.index("<span>Acceptés</span>")
    assert "<strong>1</strong><span>Nouvelle demande</span>" in page.text
    assert "100002" in page.text and "100001" not in page.text
    dashboard.record_work(site.gate, "100002", "admin", archived=1)
    page = site.client.get("/admin/edof-test?section=state&tab=request")
    assert "<strong>0</strong><span>Nouvelle demande</span>" in page.text and "100002" not in page.text
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
