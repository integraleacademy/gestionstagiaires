import datetime as dt
from contextlib import closing
import json
import time

import pytest
from werkzeug.datastructures import MultiDict

import edof_automation_audit as audit
import edof_declarations as ledger
import edof_directory as directory
import integrale_edof_dashboard as dashboard
import integrale_edof_history as history
from integrale_edof_sync import process_directory
from test_edof_declarations import prepare, ENTRY, EXIT, ROW, FOLDER
from test_integrale_edof_dashboard import site


def entries(path):
    with closing(ledger.database(path)) as db:
        return [dict(r) for r in db.execute("SELECT * FROM edof_automation_events ORDER BY id")]


@pytest.mark.parametrize("status", ["refused", "rejected", "REFUSED"])
def test_refused_topup_is_a_dedicated_request_not_a_refused_dossier(status, site):
    raw = {"id": "100002", "currentState": "validated", "attendee": {"firstName": "Anne", "lastName": "Exemple"},
           "trainingActionInfo": {"sessionStartDate": "2026-02-02", "sessionEndDate": "2026-02-06",
                                  "solicitations": [{"fundingType": 9, "status": status}]}}
    row = directory.project(raw)
    assert row["ft_refused"] and not row["ft_pending"]
    assert dashboard.category(row) == "ft_refused"
    assert dashboard.category({**row, "state": "accepted"}) == "accepted"
    assert dashboard.category({**row, "state": "refused"}) == "refused"
    assert dashboard.category({**row, "state": "billed", "service_done_validated": True}) == "invoiced"
    snap = site.vault.get(directory.record_key(site.owner))
    snap["rows"]["100002"] = row
    site.vault.put(directory.record_key(site.owner), snap)
    response = site.client.get("/admin/edof-test?group=requests&tab=ft_refused")
    assert response.status_code == 200 and 'data-edof-folder="100002"' in response.text
    assert "Financement FT en cours" in response.text and "Financement FT refusé" in response.text
    raw["trainingActionInfo"]["solicitations"].append({"fundingType": "9", "status": "inProgress"})
    assert dashboard.category(directory.project(raw)) == "ft"
    raw["trainingActionInfo"]["solicitations"][-1]["status"] = "accepted"
    assert dashboard.category(directory.project(raw)) == "waiting"
    raw["trainingActionInfo"]["solicitations"] = [{"fundingType": 3, "status": "refused"}, {"fundingType": 9, "status": "unknown"}]
    assert not directory.project(raw)["ft_refused"]


def test_exit_and_service_receipts_are_distinct_durable_and_not_replayed(tmp_path):
    spec = prepare(tmp_path, EXIT)
    assert ledger.begin_send(tmp_path, spec)
    ledger.complete(tmp_path, spec, "declaration_exit_confirmed")
    ledger.complete(tmp_path, spec, "declaration_exit_confirmed")  # Same receipt cannot create two exits.
    follow = ledger.next_job(type("Store", (), {"directory": tmp_path})(), 1)
    assert ledger.begin_send(tmp_path, follow)
    ledger.complete(tmp_path, follow, "declaration_confirmed", "serviceDoneDeclared")
    ledger.complete(tmp_path, follow, "declaration_confirmed", "serviceDoneDeclared")
    events = entries(tmp_path)
    assert [(e["kind"], e["status"]) for e in events] == [
        ("declared", "queued"), ("declared", "sending"), ("out", "confirmed"),
        ("declared", "sending"), ("declared", "confirmed")]
    assert all(e["occurred"] > 0 for e in events)
    assert entries(tmp_path) == events  # Reopening never rewrites audit timestamps.


def test_retry_deadline_is_not_an_event_time_and_failures_survive_success(tmp_path):
    spec = prepare(tmp_path, ENTRY)
    before = time.time()
    ledger.complete(tmp_path, spec, "timeout")
    after = time.time()
    assert ledger.records(tmp_path)[0]["changed"] > after + 800
    assert before - .01 <= entries(tmp_path)[-1]["occurred"] <= after + .01
    assert ledger.begin_send(tmp_path, spec)
    ledger.complete(tmp_path, spec, "declaration_unverified")
    ledger.request_recheck(tmp_path, FOLDER, "entry_training")
    assert ledger.records(tmp_path)[0]["changed"] == 0
    ledger.complete(tmp_path, {**spec, "mode": "reconcile"}, "declaration_confirmed")
    events = entries(tmp_path)
    assert "timeout" in {e["detail"] for e in events}
    assert "declaration_unverified" in {e["detail"] for e in events}
    assert events[-1]["status"] == "confirmed"
    assert all(e["occurred"] > 0 for e in events)


def test_unperformed_actions_are_kept_without_repeating_the_same_alert(tmp_path):
    for _ in range(3):
        audit.decision(tmp_path, "account", ROW, "entry_training", "missing")
    assert len(entries(tmp_path)) == 1
    audit.decision(tmp_path, "account", ROW, "entry_training", "blocked")
    assert len(entries(tmp_path)) == 2
    assert entries(tmp_path)[-1]["detail"] == "discovery_blocked"


def test_job_history_survives_operational_retention_and_scopes_accounts(site):
    job = site.store.reserve(site.owner, "directory", day_session=True)
    site.store.finish(job, {"code": "directory_incomplete", "private": "must never be archived"})
    with closing(site.store.connect()) as db, db:
        db.execute("UPDATE jobs SET created=? WHERE id=?", (time.time()-90000, job))
    with closing(site.store.connect()) as db:
        assert not db.execute("SELECT 1 FROM jobs WHERE id=?", (job,)).fetchone()
        event = dict(db.execute("SELECT * FROM edof_automation_events WHERE event_key LIKE ?", ("job:"+job+":%",)).fetchone())
        assert "private" not in str(event) and event["status"] == "error"
    snapshot = site.vault.get(directory.record_key(site.owner))
    visible = history.page(site.store, site.owner, snapshot, MultiDict())
    assert visible["counts"]["issues"] == 1
    assert visible["entries"][0]["kind"] == "sync"
    assert history.page(site.store, "different-account", snapshot, MultiDict())["total"] == 0


def test_long_interruption_is_archived_before_cache_cleanup(site):
    job = site.store.reserve(site.owner, "directory", day_session=True)
    with closing(site.store.connect()) as db, db:
        db.execute("UPDATE jobs SET created=? WHERE id=?", (time.time()-90000, job))
    with closing(site.store.connect()) as db:
        event = db.execute("SELECT * FROM edof_automation_events WHERE event_key LIKE ?", ("job:"+job+":%",)).fetchone()
        assert event["detail"] == "interrupted" and event["status"] == "error"
        assert not db.execute("SELECT 1 FROM jobs WHERE id=?", (job,)).fetchone()


def test_existing_receipt_migration_preserves_its_timestamp_and_is_idempotent(tmp_path):
    from cpf_provider import ProviderStore
    tmp_path.mkdir(exist_ok=True)
    with closing(ProviderStore(tmp_path).connect()) as db, db:
        db.execute("""CREATE TABLE cpf_declarations (
            folder TEXT, action TEXT, token TEXT UNIQUE, owner TEXT, revision INTEGER, actor TEXT, intent TEXT,
            status TEXT, created REAL, changed REAL, detail TEXT DEFAULT '', checks INTEGER DEFAULT 0,
            PRIMARY KEY(folder,action))""")
        db.execute("INSERT INTO cpf_declarations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (FOLDER,'entry_training','old-token','account',1,'admin',json.dumps(ROW),'confirmed',100,200,'declaration_confirmed',0))
    result = entries(tmp_path)
    assert len(result) == 1 and result[0]["occurred"] == 200 and result[0]["source"] == "legacy"
    assert entries(tmp_path) == result


def seed(site, count=33):
    snapshot = site.vault.get(directory.record_key(site.owner))
    row = snapshot["rows"]["100000"]
    with closing(ledger.database(site.store.directory)) as db, db:
        for i in range(count):
            audit.add(db, owner=site.owner, folder=row["folder_id"], kind="entry", status="confirmed",
                      occurred=dt.datetime(2026,11,4,16,30,tzinfo=dt.timezone.utc).timestamp()-i,
                      row={**row,"first_name":"Élodie <script>bad</script>"}, source="declaration")
        audit.add(db, owner="another-account", folder=row["folder_id"], kind="entry", status="error",
                  occurred=time.time(), row=row, source="declaration")
    return snapshot


def test_history_filters_pagination_and_escaped_markup(site):
    snap = seed(site)
    params = MultiDict({"type":"entry", "result":"confirmed", "q":"elodie", "from":"2026-11-04", "until":"2026-11-04"})
    first = history.page(site.store, site.owner, snap, params)
    assert first["total"] == 33 and first["pages"] == 2 and len(first["entries"]) == 25
    assert first["entries"][0]["date"] == "04/11/2026" and first["entries"][0]["time"] == "17h30"
    params["page"] = "2"
    second = history.page(site.store, site.owner, snap, params)
    assert len(second["entries"]) == 8
    assert not {e["uid"] for e in first["entries"]} & {e["uid"] for e in second["entries"]}
    response = site.client.get("/admin/edof-test", query_string={**params, "section":"consumption"})
    assert response.status_code == 200 and "Historique des automatisations" in response.text
    assert "Consommation Intégrale EDOF" not in response.text
    assert "&lt;script&gt;bad&lt;/script&gt;" in response.text and "<script>bad</script>" not in response.text
    assert 'aria-label="Pages de l’historique"' in response.text
    assert all("type-"+key in response.text for key in ("entry","out","declared","billable","invoiced","paid"))
    params["until"] = "2026-11-03"
    assert history.page(site.store, site.owner, snap, params)["total"] == 0
    # Old bookmarks use the new single history page.
    assert "Journal d’activité" in site.client.get("/admin/edof-test?section=automations&tab=history").text


@pytest.mark.parametrize("instant,expected", [("2026-07-01T15:30:00+00:00","17h30"),
    ("2026-11-04T16:30:00+00:00","17h30"), ("2026-03-29T01:30:00+00:00","03h30")])
def test_french_timezone_including_dst(instant, expected):
    assert history.timestamp(dt.datetime.fromisoformat(instant).timestamp())["time"] == expected


def test_observed_milestones_are_not_fabricated_automations_or_duplicate_receipts(site):
    snap = site.vault.get(directory.record_key(site.owner))
    row = snap["rows"]["100000"]
    stamp = time.time()
    with closing(ledger.database(site.store.directory)) as db, db:
        audit.add(db, owner=site.owner, folder=row["folder_id"], kind="entry", status="confirmed",
                  occurred=stamp-10, row=row, source="declaration")
    for i,state in enumerate(["accepted", "inTraining", "serviceDoneValidated", "billed", "paid"]):
        process_directory(site.store, {"checked":stamp+i,"rows":{"100000":{**row,"state":state}}}, owner=site.owner)
    result = history.page(site.store, site.owner, snap, MultiDict())
    assert result["total"] == 4
    assert result["counts"]["confirmed"] == 1 and result["counts"]["observed"] == 3
    assert {e["kind"] for e in result["entries"]} == {"entry", "billable", "invoiced", "paid"}
    assert all("détection" in e["note"] for e in result["entries"] if e["status"] == "observed")


def test_missing_attendance_is_never_labelled_as_declared(site):
    snap = site.vault.get(directory.record_key(site.owner))
    row = snap["rows"]["100000"]
    audit.decision(site.store.directory, site.owner, row, "entry_training", "missing")
    page = site.client.get("/admin/edof-test?section=consumption&q=100000")
    assert "Entrée non transmise" in page.text
    assert "Entrée en formation" in page.text and "Entrée déclarée" not in page.text
    with closing(ledger.database(site.store.directory)) as db, db:
        audit.add(db, owner=site.owner, folder=row["folder_id"], kind="entry", status="confirmed",
                  occurred=time.time(), detail="declaration_confirmed", row=row, source="declaration")
    events = history.page(site.store, site.owner, snap, MultiDict({"q":"100000"}))["entries"]
    assert [(e["kind_label"], e["label"]) for e in events] == [
        ("Entrée déclarée", "Réception confirmée par EDOF"), ("Entrée en formation", "Entrée non transmise")]
