import datetime as dt
from contextlib import closing
from types import SimpleNamespace as NS

import pytest

import cpf_provider as providers
import edof_declarations as ledger
import edof_declaration_form as form
from edof_server_browser import EDOF_HOST, API_PREFIX, DETAIL_PREFIX
from test_integrale_edof_dashboard import site

FOLDER = "123456789"
ROW = {"folder_id": FOLDER, "first_name": "Marie", "last_name": "Essai",
       "session_start_date": "2026-01-01", "session_end_date": "2026-01-30"}
ENTRY = {"action": "entry_training", "actual_date": "2026-01-03", "evidence": "Justificatif local contrôlé"}
EXIT = {"action": "service_done", "actual_date": "2026-01-29",
        "evidence": "Attestation de fin et bilan", "rate": 65, "motif": "trainee_absent"}
PREFIX = "https://"+EDOF_HOST+API_PREFIX+FOLDER


def prepare(path, draft):
    provider = providers.ProviderStore(path)
    provider.switch("integrale", 0, "admin")
    assert ledger.enqueue(path, "account", 1, ROW, draft, "admin") == "queued"
    return ledger.next_job(NS(directory=path), 1)


def request(path, payload):
    return NS(method="PUT", resource_type="xhr", url=path, frame=NS(url=DETAIL_PREFIX+FOLDER), post_data_json=payload)


def test_real_request_fence_requires_provider_target_action_date_and_single_send(tmp_path):
    spec = prepare(tmp_path, ENTRY)
    gate = form.SingleWrite(spec, EDOF_HOST, API_PREFIX, tmp_path)
    valid = request(PREFIX+"/in-training", {"date": ENTRY["actual_date"]})
    assert not gate.allows(valid)
    gate.armed = True
    for refused in (request(PREFIX+"1/in-training", valid.post_data_json), request(PREFIX+"/cancel", valid.post_data_json),
                    request(PREFIX+"/in-training", {"date": "2026-01-02"}
                            ), request(PREFIX+"?token=x", valid.post_data_json),
                    request(PREFIX, {"date": ENTRY["actual_date"], "currentState": "canceled"})):
        assert not gate.allows(refused)
    assert gate.allows(valid) and not gate.allows(valid)
    assert ledger.records(tmp_path)[0]["status"] == "sending"
    ledger.complete(tmp_path, spec, "timeout")
    assert ledger.enqueue(tmp_path, "account", 1, ROW, ENTRY, "admin") == "uncertain"
    assert ledger.request_recheck(tmp_path, FOLDER, "entry_training")
    verify = ledger.next_job(NS(directory=tmp_path), 1)
    assert verify["mode"] == "reconcile"
    verify_gate = form.SingleWrite(verify, EDOF_HOST, API_PREFIX, tmp_path)
    verify_gate.armed = True
    assert not verify_gate.allows(valid)
    assert form.transmit(None, verify, {**ROW, "state": "accepted"},
                         verify_gate, None)["code"] == "declaration_unverified"
    result = form.transmit(None, verify, {**ROW, "state": "inTraining",
                           "start_date": ENTRY["actual_date"]}, verify_gate, None)
    assert result["confirmed_state"] == "inTraining"
    assert "fields" not in result
    ledger.complete(tmp_path, verify, result["code"], result["confirmed_state"])
    receipt = ledger.records(tmp_path)[0]
    assert receipt["status"] == "confirmed"
    assert receipt["intent"]["confirmed_state"] == "inTraining"


def test_queued_work_expires_on_provider_change_and_resume(tmp_path):
    spec = prepare(tmp_path, ENTRY)
    selection = providers.ProviderStore(tmp_path)
    selection.switch("wedof", 1, "admin")
    assert not ledger.begin_send(tmp_path, spec)
    selection.switch("integrale", 2, "admin")
    assert ledger.next_job(NS(directory=tmp_path), 3) is None
    assert ledger.records(tmp_path)[0]["status"] == "paused"
    assert ledger.enqueue(tmp_path, "account", 3, ROW, ENTRY, "admin") == "queued"


def test_exit_receipt_checks_actual_date_rate_identity_and_state(tmp_path):
    spec = prepare(tmp_path, EXIT)
    fields = {**ROW, "state": "serviceDoneDeclared",
              "end_date": EXIT["actual_date"], "completion_rate": "65.00"}
    assert form.transmit(None, spec, fields, None, None)["code"] == "declaration_confirmed"
    for diff in ({"first_name": "Autre"}, {"session_end_date": "2026-02-01"}, {"state": "accepted"},
                 {"end_date": "2026-01-25"}, {"completion_rate": "100"}):
        assert form.transmit(None, {**spec, "mode": "reconcile"}, {**fields, **diff},
                             None, None)["code"] != "declaration_confirmed"
    with pytest.raises(ValueError):
        ledger.enqueue(tmp_path, "account", 1, ROW, {**EXIT, "motif": "libre"}, "admin")
    assert form.transmit(None, spec, {**ROW, "state": "inTraining",
                         "start_date": "2026-01-30"}, None, None)["code"] == "declaration_changed"


def test_operator_routes_require_admin_csrf_active_provider_and_actual_evidence(site):
    client = site.client
    form_data = {"csrf": site.csrf, "action": "service_done", "actual_date": "2026-02-05", "rate": "65",
                 "evidence": "Feuille vérifiée", "attested": "yes", "motif": "trainee_absent"}
    url = "/admin/edof-test/dossiers/100001/submit"
    assert "désactivé" in client.post(url, data=form_data, follow_redirects=True).text
    client.post("/admin/edof-test/provider", data={"csrf": site.csrf, "provider": "integrale", "revision": 0})
    assert client.post(url, data={**form_data, "csrf": ""}).status_code == 403
    assert "En attente de transmission" in client.post(url, data=form_data, follow_redirects=True).text
    assert "En attente de transmission" in client.post(url, data=form_data, follow_redirects=True).text
    assert len(ledger.records(site.store.directory)) == 1
    assert "En attente de transmission" in client.get("/admin/edof-test?folder=100001").text
    assert "Vérifier les commandes en lecture seule" in client.get("/admin/edof-test?section=technical").text


def test_discovery_requires_production_evidence_link_and_no_block(tmp_path, monkeypatch):
    import cpf_provider
    monkeypatch.setattr(cpf_provider, "on_test_service", lambda: True)
    row = {**ROW, "state": "accepted"}
    store = NS(directory=tmp_path)
    providers.ProviderStore(tmp_path).switch("integrale", 0, "admin")
    proof = {**ROW, "blocks": ["both"], "entry_training": {**ENTRY, "source": "production"}}
    monkeypatch.setattr(ledger, "authoritative_proofs", lambda ids: {FOLDER: proof})
    for override in ({"blocks": ["both"]}, {"last_name": "Homonyme", "blocks": []}):
        proof.update(override)
        ledger.discover(store, "account", {"rows": {FOLDER: row}})
        assert not ledger.records(tmp_path)
    proof.update(last_name=ROW["last_name"])
    ledger.discover(store, "account", {"rows": {FOLDER: row}})
    assert ledger.records(tmp_path)[0]["actor"] == "Gestion Stagiaires"


def test_individual_entry_uses_persisted_production_hold_and_official_status_payload(tmp_path, monkeypatch):
    import cpf_provider
    monkeypatch.setattr(cpf_provider, "on_test_service", lambda: True)
    ticket = "a" * 32
    store = NS(directory=tmp_path, data_file=None)
    row = {**ROW, "state": "accepted"}
    good = {**ENTRY, "source": "production"}
    proof = {**ROW, "entry_training": good}
    states = {FOLDER: {"available": True, "start": ROW["session_start_date"], "end": ROW["session_end_date"],
                       "reserved": True, "ticket": ticket, "proof": proof}}
    def remote(folder, mode="inspect", **args):
        state = states[folder]
        return {**state, "operation": args.get("operation") if mode == "claim" and state["reserved"] else ""}
    monkeypatch.setattr(ledger, "pilot_state", remote)
    ledger.enqueue(tmp_path, "admin", 0, row, {**good, "pilot_ticket": ticket}, "admin")
    ledger.enqueue(tmp_path, "admin", 0, {**row, "folder_id": "111111111"}, ENTRY, "admin")
    spec = ledger.next_job(store, 0, provider="wedof")
    assert spec["folder_id"] == FOLDER and ledger.check_before_job(store, spec)
    gate = form.SingleWrite(spec, EDOF_HOST, API_PREFIX, tmp_path)
    gate.armed = True
    payload = {"state":"IN_TRAINING", "date":"03/01/2026"}
    for url, invalid in [(PREFIX+"/status", {**payload,"state":"CANCELED"}),
                         (PREFIX+"/status", {**payload,"date":"01/01/2026"}),
                         (PREFIX+"/status", {**payload,"anotherAction": True}),
                         (PREFIX+"/in-training", payload), (PREFIX+"1/status",payload)]:
        assert not gate.allows(request(url, invalid))
    assert gate.allows(request(PREFIX+"/status",payload))
    assert not gate.allows(request(PREFIX+"/status",payload))
    ledger.complete(tmp_path,spec,"declaration_unverified")
    assert ledger.enqueue(tmp_path,"admin",0,row,{**good,"pilot_ticket":ticket},"admin") == "uncertain"
    assert ledger.next_job(store,0,provider="wedof") is None
    states[FOLDER]["reserved"] = False
    assert not ledger.check_before_job(store,{**spec, "intent":{**spec["intent"], "pilot_ticket":"b"*32}})


def test_reservation_ui_cannot_submit_an_exit_or_another_folder_while_wedof_is_active(site, monkeypatch):
    import integrale_edof_dashboard as dashboard
    monkeypatch.setattr(dashboard, "on_test_service", lambda: True)
    monkeypatch.setattr(dashboard, "production_request", lambda: {"provider":"wedof"})
    state = {"available":True, "reserved":False, "ticket":"", "start":"2026-02-02", "end":"2026-02-06"}
    def remote(folder, mode="inspect", **kwargs):
        assert folder == "100000"
        if mode == "reserve":
            state.update(reserved=True,ticket="f"*32)
        return state
    monkeypatch.setattr(ledger,"pilot_state",remote)
    url = "/admin/edof-test/dossiers/100000/entry-pilot"
    client = site.client
    def post(**kwargs):
        return client.post(url, data={"csrf":site.csrf,**kwargs}, follow_redirects=True)
    assert client.post(url,data={"mode":"reserve"}).status_code == 403
    assert "Réserver uniquement" in client.get("/admin/edof-test?folder=100000").text
    assert "Entrée exclue de WeDoF en production" in post(mode="reserve").text
    params = {"mode":"submit","actual_date":"2026-02-02","evidence":"Émargement du stagiaire","attested":"yes"}
    post(**params,action="service_done")
    assert not ledger.records(site.store.directory)
    post(**params,action="entry_training")
    assert ledger.records(site.store.directory)[0]["intent"]["pilot_ticket"] == "f"*32
    assert site.gate.state()["provider"] == "wedof"


def test_new_receipt_updates_old_directory_view_only_for_same_enrolment(site):
    from integrale_edof_dashboard import apply_confirmed_entries
    from edof_directory import dated_snapshot, record_key
    current = dated_snapshot(site.vault.get(record_key(site.owner)))
    folder = "100000"
    row = current["rows"][folder]
    draft = {**ENTRY, "actual_date": row["session_start_date"], "pilot_ticket": "a"*32}
    ledger.enqueue(site.store.directory, site.owner, 0, row, draft, "admin")
    spec = ledger.next_job(site.store, 0, provider="wedof")
    def present(snap, owner=site.owner):
        return apply_confirmed_entries(snap, site.store.directory, owner)["rows"][folder]

    assert present(current)["state"] == "Accepté"
    ledger.complete(site.store.directory, spec, "declaration_confirmed")
    assert present(current)["state"] == "Entrée déclarée"
    state_view = site.client.get("/admin/edof-test?section=state&q="+folder).text
    assert "Entrée confirmée le " in state_view
    assert present({**current,"checked":1e11})["state"] == "Accepté"
    assert present(current, "autre compte")["state"] == "Accepté"
    stale = {**current,"rows":{folder:{**row,"last_name":"Homonyme"}}}
    assert "entry_confirmed_on" not in present(stale)
    advanced = {**current,"rows":{folder:{**row,"state":"Annulé par le titulaire"}}}
    assert present(advanced)["state"] == "Annulé par le titulaire"


def test_provider_off_and_paris_cutoffs_for_weekend_and_dst(tmp_path, monkeypatch):
    import cpf_provider
    from integrale_edof_dashboard import simulate, PARIS
    from edof_day_session import working_hours
    from unittest.mock import Mock
    monkeypatch.setattr(cpf_provider,"on_test_service",lambda:True)
    proofs = Mock(side_effect=AssertionError("provider is inactive"))
    monkeypatch.setattr(ledger,"authoritative_proofs",proofs)
    ledger.discover(NS(directory=tmp_path),"owner",{"rows":{FOLDER:{**ROW,"state":"accepted"}}})
    proofs.assert_not_called()
    for day in (dt.date(2026,3,29),dt.date(2026,10,25)):
        for kind,hour in (("accepted",8),("entry",18)):
            at = dt.datetime.combine(day,dt.time(hour),PARIS)
            assert working_hours(at,daily=True)
            assert simulate(kind,day.isoformat(),None,None,at-dt.timedelta(seconds=1)) == "planned"
            assert simulate(kind,day.isoformat(),None,None,at) == "unconfirmed"


def test_official_exit_status_payload_must_match_date_and_actual_rate(tmp_path):
    draft = {**EXIT,"rate":100}
    spec = prepare(tmp_path,draft)
    gate = form.SingleWrite(spec,EDOF_HOST, API_PREFIX,tmp_path)
    gate.armed = True
    body = {"state":"TERMINATED","terminatedDate":"29/01/2026","achievementRate":100,
            "completed":True,"terminatedReason":"8","forceMajeureAbsence":False}
    for change in ({"state":"CANCELED"},{"terminatedDate":"30/01/2026"},{"achievementRate":99},{"terminatedReason":"31"}):
        assert not gate.allows(request(PREFIX+"/status",{**body,**change}))
    assert gate.allows(request(PREFIX+"/status",body))


def test_verified_exit_only_requeues_once_for_remaining_service(tmp_path):
    spec = prepare(tmp_path, EXIT)
    assert ledger.begin_send(tmp_path,spec)
    fields = {**ROW,"state":"terminated","end_date":EXIT["actual_date"]}
    result = form.transmit(None,{**spec,"mode":"reconcile"},fields,None,None)
    assert result["code"] == "declaration_exit_confirmed"
    ledger.complete(tmp_path,spec,result["code"])
    follow = ledger.next_job(NS(directory=tmp_path),1)
    assert follow["operation"] != spec["operation"] and follow["intent"]["exit_confirmed"] is True
    assert ledger.begin_send(tmp_path,follow)
    result = form.transmit(None,{**follow,"mode":"reconcile"},fields,None,None)
    assert result["code"] == "declaration_unverified"
    ledger.complete(tmp_path,follow,result["code"])
    assert ledger.records(tmp_path)[0]["status"] == "uncertain"


def test_manual_catchup_runs_only_when_active_and_reuses_the_durable_ledger(site, monkeypatch):
    import cpf_provider
    import edof_directory
    import time

    url = "/admin/edof-test/automatisations/rattraper"
    form = {"csrf":site.csrf,"revision":"1","section":"automations"}
    site.vault.put("gmail",{"fixture":True})
    assert site.client.post(url,data=form,follow_redirects=True).status_code == 200
    assert not site.store.catchup_status(site.owner)
    site.gate.switch("integrale",0,"fixture")
    assert site.client.post(url,data={**form,"csrf":""}).status_code == 403
    assert site.client.post(url,data={**form,"revision":"0"},follow_redirects=True).status_code == 200
    assert not site.store.catchup_status(site.owner)
    with site.client.session_transaction() as sess:
        sess["admin_role"]="viewer"
    assert site.client.post(url,data=form).status_code == 403
    with site.client.session_transaction() as sess:
        sess["admin_role"]="admin"
    assert site.client.post(url,data=form).status_code == 303
    first = site.store.next_manual_sync()
    assert first["catchup"] and site.store.catchup_status(site.owner)["busy"]
    assert site.client.post(url,data=form).status_code == 303
    assert first["requested"] == site.store.next_manual_sync()["requested"]
    assert "Relancez" not in site.store.catchup_status(site.owner)["message"]
    monkeypatch.setattr(cpf_provider,"on_test_service",lambda:True)
    monkeypatch.setattr("cpf_provider_bridge.production_request", lambda:{"provider":"integrale"})

    def row(folder,state,**updates):
        return {**ROW,"folder_id":folder,"state":state,**updates}
    rows = {r["folder_id"]:r for r in [
        row("100001","accepted"),row("100002","inTraining"),row("100003","accepted"),row("100004","accepted"),
        row("100005","accepted"),row("100006","inTraining"),row("100007","accepted",session_start_date="2099-10-01"),
        row("100008","serviceDoneValidated"),row("100009","accepted",session_start_date="2025-12-31")]}
    proofs = {f:{**r,"blocks":[],"entry_training":{**ENTRY,"source":"production"},
                 "service_done":{**EXIT,"source":"production"}} for f,r in rows.items()}
    del proofs["100004"]["entry_training"]
    proofs["100006"]["blocks"]=["both"]
    monkeypatch.setattr(ledger,"authoritative_proofs",lambda ids:{f:proofs[f] for f in ids})
    ledger.hold_folder(site.store.directory,"100003",True)
    ledger.enqueue(site.store.directory,site.owner,1,rows["100005"],ENTRY,"admin")
    old = next(r for r in ledger.records(site.store.directory) if r["folder"]=="100005")
    job = site.store.reserve(site.owner,"directory",day_session=True,sync_scope="all")
    site.store.process_catchups(site.gate.state())
    assert site.store.catchup_status(site.owner)["busy"]
    site.vault.put(edof_directory.record_key(site.owner),{"scope":"all","rows":rows,"checked":time.time()})
    site.store.finish(job,{"code":"directory_ready"})
    site.store.process_catchups(site.gate.state())
    state = site.store.catchup_status(site.owner)
    assert state["busy"] and state["phase"] == "send"
    assert "en attente : 3" in state["message"]
    assert "outcomes" not in state
    page = site.client.get("/admin/edof-test?section=automations&tab=due").text
    def table_row(folder):
        return page.split(f'<tr data-edof-folder="{folder}">',1)[1].split("</tr>",1)[0]
    assert "En attente de transmission" in table_row("100005")
    assert "Déclarer la date d’entrée" not in table_row("100005")
    assert "Déclarer la date d’entrée" in table_row("100004")
    assert "#declaration-edof" in table_row("100004")
    assert "entrées en formation · 1, sorties avec service fait · 1" in state["message"]
    assert "Bloquées : 2" in state["message"] and "à préciser : 1" in state["message"]
    assert "en cours : 1" in state["message"]
    jobs = ledger.records(site.store.directory)
    assert {(r["folder"],r["action"]) for r in jobs} == {
        ("100001","entry_training"),("100002","service_done"),("100005","entry_training")}
    assert old["token"] == next(r["token"] for r in jobs if r["folder"]=="100005")
    site.store.process_catchups(site.gate.state())
    assert jobs == ledger.records(site.store.directory)

    # For a finished session, the next scheduler pass can catch up the exit
    # once EDOF has acknowledged the entry, without a second operator click.
    from integrale_edof_dashboard import apply_confirmed_entries
    entry = next(r for r in jobs if r["folder"] == "100001")
    spec = {"mode":"declare","operation":entry["token"],"folder_id":entry["folder"],
            "intent":entry["intent"],"revision":entry["revision"]}
    assert ledger.begin_send(site.store.directory, spec)
    ledger.complete(site.store.directory, spec, "declaration_confirmed", "inTraining")
    projected = apply_confirmed_entries(site.vault.get(edof_directory.record_key(site.owner)), site.store.directory, site.owner)
    assert projected["rows"][entry["folder"]]["state"] == "inTraining"
    ledger.discover(site.store, site.owner, projected)
    stages = {(r["action"], r["status"]) for r in ledger.records(site.store.directory, entry["folder"])}
    assert stages == {("entry_training","confirmed"), ("service_done","queued")}
    for pending in (r for r in jobs if r["folder"] != entry["folder"]):
        ledger.complete(site.store.directory, {"operation":pending["token"],"mode":"declare"}, "declaration_blocked")
    state = site.store.catchup_status(site.owner)
    assert state["phase"] == "done" and not state["busy"]
    assert state["result"] == "warning"
    assert "confirmés par EDOF : 1" in state["message"] and "à vérifier : 2" in state["message"]
    # The next-stage exit is its own declaration, outside this run's original batch.



def test_manual_catchup_rejects_partial_reads_and_provider_switches(site):
    store = site.store
    site.gate.switch("integrale",0,"admin")
    store.queue_sync(site.owner,"all",catchup_revision=1)
    store.finish(store.reserve(site.owner,"directory",day_session=True,sync_scope="all"), {"code":"requests_ready"})
    store.process_catchups(site.gate.state())
    assert "liste générale EDOF n’a pas été actualisée" in store.catchup_status(site.owner)["message"]
    assert store.catchup_status(site.owner)["result"] == "error"
    store.queue_sync(site.owner,"all",catchup_revision=1)
    site.gate.switch("wedof",1,"admin")
    store.process_catchups(site.gate.state())
    assert "système de traitement CPF a changé" in store.catchup_status(site.owner)["message"]
    assert not ledger.records(store.directory)

def test_date_based_entries_only_queue_the_selected_effective_starts(site):
    import edof_directory
    import integrale_edof_dashboard as dashboard

    site.gate.switch("integrale",0,"admin")
    key = edof_directory.record_key(site.owner)
    snap = site.vault.get(key)
    rows = snap["rows"]
    base = rows["100000"]
    choices = []
    for folder, updates in (("100000",{}), ("200001",{}), ("200002",{}), ("200003",{"session_start_date":"2099-11-03","session_end_date":"2099-11-30"})):
        rows[folder] = {**base, "folder_id":folder, **updates}
        choices.append(dashboard.entry_choice(rows[folder]))
    rows["200002"]["first_name"] = "Autre titulaire"
    site.vault.put(key,snap)
    ledger.hold_folder(site.store.directory,"200001",True)
    url = "/admin/edof-test/automatisations/entrees-effectives"
    data = {"entry":choices,"revision":"1","csrf":site.csrf,"attested":"yes"}
    assert site.client.post(url,data={**data,"csrf":""}).status_code == 403
    site.client.post(url,data={**data,"attested":""})
    site.client.post(url,data={**data,"revision":"0"})
    assert not ledger.records(site.store.directory)
    site.client.post(url,data=data)
    site.client.post(url,data=data)
    jobs = ledger.records(site.store.directory)
    assert len(jobs) == 1 and jobs[0]["folder"] == "100000"
    assert jobs[0]["intent"]["operator_confirmed"] and jobs[0]["intent"]["evidence"] == ""
    assert jobs[0]["intent"]["actual_date"] == base["session_start_date"]


def test_prefilled_date_is_editable_and_never_sets_a_completion_rate(site):
    import re
    site.gate.switch("integrale",0,"admin")
    for folder,date in (("100000","2026-02-02"),("100001","2026-02-06")):
        html = site.client.get("/admin/edof-test?folder="+folder).text
        form = html.split('<form class="draft"',1)[1].split("</form>",1)[0]
        assert f'name="actual_date" value="{date}"' in form
        assert 'name="evidence"' not in form
        assert re.search(r'<button[^>]*name="attested" value="yes"',form)
        if folder == "100001":
            assert 'name="rate" value=""' in form
    site.client.post("/admin/edof-test/dossiers/100001/submit", data={"csrf":site.csrf,"attested":"yes",
                     "action":"service_done","actual_date":"2026-02-05","rate":"65","motif":"trainee_absent"})
    receipt = ledger.records(site.store.directory)[0]["intent"]
    assert receipt["actual_date"] == "2026-02-05" and receipt["rate"] == 65 and receipt["operator_confirmed"]

def test_native_catchup_uses_linked_local_effective_date_if_production_only_knows_the_session(site, monkeypatch):
    import json

    site.gate.switch("integrale",0,"admin")
    monkeypatch.setattr(providers,"on_test_service",lambda:True)
    row = {**ROW,"state":"accepted"}
    remote = {FOLDER:{**row,"blocks":[]}}
    monkeypatch.setattr(ledger,"authoritative_proofs",lambda ids:remote)
    data = {"sessions":[{"id":"s","date_start":row["session_start_date"],"date_end":row["session_end_date"],
              "trainees":[{"id":"t","first_name":row["first_name"],"last_name":row["last_name"],"actual_training_start_date":"2026-01-03"}]}],
            "wedof_links":[{"active":True,"external_id":FOLDER,"session_id":"s","trainee_id":"t"}]}
    site.local.write_text(json.dumps(data))
    site.store.data_file = site.local
    report = ledger.discover(site.store,site.owner,{"rows":{FOLDER:row}})
    assert report["entry_training"] == 1
    spec = ledger.next_job(site.store,1)
    assert spec["intent"]["actual_date"] == "2026-01-03" and spec["intent"]["source"] == "local"
    assert ledger.check_before_job(site.store,spec)
    remote[FOLDER]["first_name"] = "Autre"
    assert not ledger.check_before_job(site.store,spec)

def test_exercise_on_a_later_day_does_not_move_an_entry_and_a_partial_draft_has_priority(site,monkeypatch):
    import json
    import integrale_edof_dashboard as dashboard
    site.gate.switch("integrale",0,"admin")
    monkeypatch.setattr(providers,"on_test_service",lambda:True)
    remote = {**ROW,"entry_training":{**ENTRY,"source":"production","evidence":"Activité pédagogique enregistrée en production, événement 936"}}
    monkeypatch.setattr(ledger,"authoritative_proofs",lambda ids:{FOLDER:remote})
    def scan(state):
        return ledger.discover(site.store,site.owner,{"rows":{FOLDER:{**ROW,"state":state}}})
    assert scan("accepted")["missing"] == 1
    assert not ledger.records(site.store.directory)
    remote["service_done"] = {**EXIT,"rate":100,"source":"production","actual_date":ROW["session_end_date"]}
    saved = {**ROW, **EXIT, "source":"admin","operator_confirmed":True}
    dashboard.record_work(site.gate,FOLDER,"admin",draft=json.dumps(saved))
    assert scan("inTraining")["service_done"] == 1
    job = ledger.next_job(site.store,1)
    assert job["intent"]["rate"] == 65 and job["intent"]["actual_date"] == EXIT["actual_date"]
    assert ledger.check_before_job(site.store,job)
