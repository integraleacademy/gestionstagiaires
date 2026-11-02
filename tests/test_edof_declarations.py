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
    ledger.complete(tmp_path, verify, result["code"])
    assert ledger.records(tmp_path)[0]["status"] == "confirmed"


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
