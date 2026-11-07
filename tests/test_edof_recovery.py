"""Recovery is exercised with local stores, verified snapshots and synthetic proofs."""
import datetime as dt
import io
import json
from types import SimpleNamespace

import pytest

import cpf_provider
import edof_declarations as ledger
import edof_directory
import edof_recovery as recovery
from edof_day_session import PARIS, DayWorker, allow_login
from edof_server_test import ServerTestStore
from test_integrale_edof_dashboard import site


@pytest.fixture
def recovery_site(site, monkeypatch):
    clock = [dt.datetime(2026,11,4,10,tzinfo=PARIS).timestamp()]
    monkeypatch.setattr('time.time', lambda:clock[0])
    monkeypatch.setattr(cpf_provider, 'on_test_service', lambda:True)
    monkeypatch.setattr('cpf_provider_bridge.production_request', lambda:{'provider':'integrale'})
    site.gate.switch('integrale',0,'fixture')
    site.vault.put('gmail', {'fixture':True})
    site.store.use_directory(site.owner,enable=True)
    site.clock = clock
    site.now = lambda:dt.datetime.fromtimestamp(clock[0],PARIS)
    def read(code, **kwargs):
        clock[0] += 1
        job = site.store.reserve(site.owner,'directory',day_session=True,**kwargs)
        clock[0] += 1
        site.store.finish(job,{'code':code})
        return job
    site.read = read
    return site


def claim(site):
    spec = recovery.next_job(site.store,site.gate.state(),site.now())
    assert spec and 'sync_scope' not in spec and 'manual_until' not in spec
    job = site.store.reserve(site.owner,'directory',day_session=True,
                             recovery_since=spec['recovery_since'],revision=spec['revision'])
    site.clock[0] += 1
    return job


def test_outage_survives_restart_partial_read_then_full_catchup_without_duplicates(recovery_site, monkeypatch):
    s = recovery_site
    s.read('directory_unavailable')
    assert recovery.pending(s.store,s.owner)
    # Creating another store cannot erase the outstanding recovery.
    restarted = ServerTestStore(s.store.directory)
    restarted.connector_key = s.store.connector_key
    assert recovery.status(restarted,s.owner)['pending']
    assert recovery.next_job(s.store,s.gate.state(),s.now()) is None
    s.read('requests_ready')
    job = claim(s)
    s.store.finish(job,{'code':'requests_ready'})
    assert recovery.next_job(s.store,s.gate.state(),s.now()) is None
    s.clock[0] += recovery.RETRY_SECONDS
    s.read('requests_ready')
    job = claim(s)
    rows = {str(n):{'folder_id':str(n),'first_name':'Anne','last_name':'Exemple','state':'accepted',
                   'session_start_date':'2026-11-03','session_end_date':'2026-12-01'} for n in (100001,100002)}
    proofs = {'100001':{**rows['100001'],'blocks':[],'entry_training':{
        'action':'entry_training','actual_date':'2026-11-03','evidence':'Présence effective vérifiée','source':'production'}}, '100002':{}}
    monkeypatch.setattr(ledger,'authoritative_proofs',lambda ids:proofs)
    s.vault.put(edof_directory.record_key(s.owner),{'scope':'all','checked':s.clock[0],'rows':rows})
    s.store.finish(job,{'code':'directory_ready'})
    recovery.prepare(s.store,s.gate.state(),s.now())
    state = recovery.status(s.store,s.owner)
    assert not state['pending'] and 'Automatisations préparées : 2' in state['message'] and 'À vérifier : 0' in state['message']
    original = ledger.records(s.store.directory)
    assert len(original) == 2 and all(row['status'] == 'queued' for row in original)
    recovery.prepare(s.store,s.gate.state(),s.now())
    s.read('requests_ready')
    assert recovery.next_job(s.store,s.gate.state(),s.now()) is None
    assert ledger.records(s.store.directory) == original


def test_authentication_pause_hours_provider_and_throttling_remain_enforced(recovery_site):
    s = recovery_site
    assert allow_login(s.vault,owner=s.owner,now=s.now())
    s.read('day_login_used')
    assert recovery.next_job(s.store,s.gate.state(),s.now()) is None
    assert not allow_login(s.vault,owner=s.owner,now=s.now())
    assert not s.vault.get('day-login-override:'+s.owner)
    s.read('requests_ready')
    assert recovery.next_job(s.store,s.gate.state(),s.now())
    assert recovery.next_job(s.store,{**s.gate.state(),'pending':True},s.now()) is None
    assert recovery.next_job(s.store,{**s.gate.state(),'provider':'wedof'},s.now()) is None
    assert recovery.next_job(s.store,s.gate.state(),s.now().replace(hour=20)) is None
    s.vault.put('edof-throttled',{'fixture':True})
    assert recovery.next_job(s.store,s.gate.state(),s.now()) is None
    s.vault.delete('edof-throttled')
    s.store.pause_directory(s.owner)
    assert recovery.next_job(s.store,s.gate.state(),s.now()) is None


def test_restart_during_full_read_and_stale_snapshot_do_not_complete_recovery(recovery_site):
    s = recovery_site
    s.store.recover_directory_reads()
    s.read('requests_ready')
    first = claim(s)
    s.store.recover_directory_reads()
    recovery.prepare(s.store,s.gate.state(),s.now())
    assert recovery.pending(s.store,s.owner)
    s.clock[0] += recovery.RETRY_SECONDS
    s.read('requests_ready')
    second = claim(s)
    assert second != first
    s.store.finish(second,{'code':'directory_ready'})
    # Fixture's pre-outage cached list is not a fresh complete read.
    recovery.prepare(s.store,s.gate.state(),s.now())
    assert recovery.pending(s.store,s.owner) and not ledger.records(s.store.directory)
    assert recovery.next_job(s.store,s.gate.state(),s.now()) is None


def test_missed_poll_is_remembered_and_unconfirmed_auth_retries_with_cooldown(recovery_site):
    s = recovery_site
    s.read('requests_ready')
    s.clock[0] += 361
    recovery.prepare(s.store,s.gate.state(),s.now())
    assert recovery.pending(s.store,s.owner)
    s.read('authentication_unconfirmed')
    assert not s.store.day_owners(s.now())
    s.clock[0] += 900
    assert s.owner in s.store.day_owners(s.now())
    s.vault.put('efp-login-day',{'date':s.now().date().isoformat(),'count':4})
    s.read('day_login_used')
    s.clock[0] += 900
    assert not s.store.day_owners(s.now())


def test_provider_revision_change_requires_a_new_full_read(recovery_site):
    s = recovery_site
    s.read('timeout')
    s.read('requests_ready')
    job = claim(s)
    s.store.finish(job,{'code':'directory_ready'})
    s.gate.switch('wedof',1,'fixture')
    s.gate.switch('integrale',2,'fixture')
    recovery.prepare(s.store,s.gate.state(),s.now())
    assert recovery.pending(s.store,s.owner) and not ledger.records(s.store.directory)
    spec = recovery.next_job(s.store,s.gate.state(),s.now())
    assert spec and spec['revision'] == 3


def test_recovery_command_reads_all_folders_in_the_existing_session(monkeypatch):
    worker = DayWorker()
    worker.owner,worker.provider = 'fixture','integrale'
    worker.process = SimpleNamespace(poll=lambda:None,stdout=io.StringIO('{"code":"directory_ready"}\n'))
    worker.channel = object()
    commands = []
    monkeypatch.setattr('edof_day_session.socket.send_fds',lambda channel,data,fds:commands.append(json.loads(data[0])))
    monkeypatch.setattr('edof_day_session.select.select',lambda *args:([worker.process.stdout],[],[]))
    result = worker.read({'mode':'directory','owner':'fixture','provider':'integrale','recovery_since':10,
                         'manual_until':dt.datetime.now(PARIS).timestamp()+3600},{},30)
    assert result['code'] == 'directory_ready' and commands[0]['full_sync']


def test_new_outage_before_analysis_keeps_recovery_pending(recovery_site):
    s = recovery_site
    s.read('timeout')
    s.read('requests_ready')
    job = claim(s)
    s.store.finish(job,{'code':'directory_ready'})
    s.read('day_login_used')
    recovery.prepare(s.store,s.gate.state(),s.now())
    assert recovery.pending(s.store,s.owner) and recovery.next_job(s.store,s.gate.state(),s.now()) is None
    assert not ledger.records(s.store.directory)
