"""No live EDOF traffic: pacing, resumable scans and queue ownership."""
import json
import os
import time
from unittest.mock import Mock

import pytest

import edof_directory as directory
import edof_server_browser as runner
import edof_throttle as throttle
from edof_directory_batches import Cursor, BatchPending, MAX_AGE
from edof_gmail import Vault, connector_key
from edof_traffic import Traffic, PacedContext, operation
from test_edof_recovery import recovery_site, claim, recovery
from test_edof_proposals import conn, prepare
from test_integrale_edof_dashboard import site

URL = 'https://' + runner.EDOF_HOST + runner.API_PREFIX + 'pad'


@pytest.fixture
def vault(tmp_path):
    return Vault(tmp_path,connector_key('synthetic-traffic-only'*3))


def test_cadence_shared_between_jobs_restarts_and_methods(vault):
    now = [time.time()]
    def sleep(delay):
        now[0] += delay
    first = Traffic(vault,clock=lambda:now[0],sleep=sleep)
    first.before(URL,'GET',{'state':'all'})
    beginning = now[0]
    second = Traffic(vault,clock=lambda:now[0],sleep=sleep)
    second.before(URL.replace('pad','123456'), 'PUT')
    assert now[0]-beginning == pytest.approx(1.5)
    second.before(URL,'GET',{'state':'notProcessed'})
    assert now[0]-beginning == pytest.approx(3)
    assert second.report()['requests'] == {'PUT:folder_update':1,'GET:pending':1}
    second.before('https://'+runner.EDOF_HOST+'/asset.js','GET')
    assert now[0]-beginning == pytest.approx(3)


def test_429_blocks_following_write_and_preserves_deadline(vault):
    context = Mock()
    response = Mock(status=429,url=URL,headers={'retry-after':'23'})
    context.request.get.return_value=response
    traffic = Traffic(vault)
    paced = PacedContext(context,traffic)
    with pytest.raises(throttle.PortalThrottled):
        paced.request.get(URL,params={'state':'all'})
    until = throttle.status(vault)['until']
    for _ in range(3):
        with pytest.raises(throttle.PortalThrottled):
            paced.request.put(URL.replace('pad','123456'),data={'private':'never logged'})
    context.request.put.assert_not_called()
    response.dispose.assert_called_once()
    assert throttle.status(vault)['until']==until
    assert traffic.report()['limit']=={'operation':'full','method':'GET','source':'portal','until':until,'retry_seconds':23}
    with traffic.connect() as db:
        assert db.execute('SELECT gap FROM cadence').fetchone()[0]==3
    assert '123456' not in json.dumps(traffic.report()) and 'private' not in json.dumps(traffic.report())


def test_operation_labels_do_not_leak_account_paths_or_query_values():
    assert operation(URL+'?state=notProcessed&name=PRIVATE','GET')=='pending'
    assert operation(URL.replace('pad','391783025701/status')+'?token=SECRET','PUT')=='proposal_validate'
    assert operation('https://efpconnect.emploi.gouv.fr/auth/realms/efp/login-actions/authenticate?code=SECRET','POST')=='efp_auth'
    assert operation('https://other.invalid/'+runner.API_PREFIX,'GET') is None


def portal(count=5):
    witness = Mock(method='GET',url=URL)
    witness.all_headers.return_value={}
    context=Mock()
    seen=[]
    def get(url,params,**kwargs):
        seen.append(params['page'])
        index=params['page']
        items=[{'id':str(100000+index),'currentState':'accepted', 'beginDate':'2026-11-01'}] if index<count else []
        response=Mock(status=200,url=url)
        response.body.return_value=json.dumps({'numberOfItems':count,'items':items}).encode()
        return response
    context.request.get.side_effect=get
    return context,witness,seen


def test_small_batches_resume_after_restart_without_publishing_partial_list(vault):
    context,witness,seen=portal()
    spec={'owner':'a','revision':1,'provider':'integrale','sync_until':time.time()+3600}
    old={'checked':1,'rows':{'999999':{'state':'old'}}}
    vault.put(directory.record_key('a'),old)
    for expected in (2,4):
        cursor=Cursor(Vault(vault.path.parent,connector_key('synthetic-traffic-only'*3)),spec)
        with pytest.raises(BatchPending):
            runner.read_recent_directory(context,witness,'all',lambda:None,{},cursor=cursor)
        assert len(seen)==expected
        assert vault.get(directory.record_key('a'))==old
    result=runner.read_recent_directory(context,witness,'all',lambda:None,{},cursor=Cursor(vault,spec))
    assert seen==[0,1,2,3,4] and len(result['rows'])==5
    assert not Cursor(vault,spec).value
    assert '100000' not in vault.path.read_bytes().decode(errors='ignore')


def test_cursor_rejects_other_provider_revision_request_or_stale_snapshot(vault):
    spec={'owner':'a','provider':'integrale','revision':1,'sync_until':10}
    for change in ({'revision':2},{'provider':'wedof'},{'sync_until':11}):
        Cursor(vault,spec).save({'index':2})
        assert Cursor(vault,{**spec,**change}).value is None
    cursor=Cursor(vault,spec)
    cursor.save({'started':time.time()-MAX_AGE-1})
    saved=vault.get(cursor.key)
    saved['started']=time.time()-MAX_AGE-1
    vault.put(cursor.key,saved)
    assert Cursor(vault,spec).value is None
    Cursor(vault,spec).save({'index':2})
    vault.put('directory-generation',123)
    assert Cursor(vault,spec).value is None


def test_pause_arriving_while_waiting_prevents_the_next_request(vault):
    now=[time.time()]
    def sleep(delay):
        now[0]+=delay
        throttle.PortalThrottled('60').remember(vault)
    traffic=Traffic(vault,clock=lambda:now[0],sleep=sleep)
    traffic.before(URL,'GET')
    context=Mock()
    with pytest.raises(throttle.PortalThrottled):
        PacedContext(context,traffic).request.put(URL.replace('pad','123456'),data={})
    context.request.put.assert_not_called()


@pytest.mark.parametrize('fault',['count','page_overlap'])
def test_changed_list_is_not_certified_complete(vault,fault):
    context,witness,_=portal()
    spec={'owner':'a'}
    with pytest.raises(BatchPending):
        runner.read_recent_directory(context,witness,'all',lambda:None,{},cursor=Cursor(vault,spec))
    reply=Mock(status=200,url=URL)
    reply.body.return_value=json.dumps({'numberOfItems':6 if fault=='count' else 5,
        'items':[{'id':'100000','currentState':'accepted','beginDate':'2026-11-01'}]}).encode()
    context.request.get.side_effect=None
    context.request.get.return_value=reply
    with pytest.raises(directory.IncompleteDirectory,match=fault):
        runner.read_recent_directory(context,witness,'all',lambda:None,{},cursor=Cursor(vault,spec))
    assert vault.get(directory.record_key('a')) is None


def test_recovery_continues_immediately_but_does_not_complete_on_a_batch(recovery_site):
    site=recovery_site
    site.read('portal_throttled')
    site.read('requests_ready')
    job=claim(site)
    site.store.finish(job,{'code':'directory_progress','session_saved':True})
    assert recovery.pending(site.store,site.owner)
    assert recovery.next_job(site.store,site.gate.state(),site.now())
    with site.store.connect() as db:
        assert not db.execute("SELECT 1 FROM edof_automation_events WHERE detail='directory_progress'").fetchone()
    assert 'petits lots' in recovery.status(site.store,site.owner)['message']


def test_manual_sync_stays_busy_and_retains_original_request_between_batches(recovery_site):
    site=recovery_site
    site.store.queue_sync(site.owner,'all')
    before=dict(site.store.next_manual_sync())
    job=site.read('directory_progress',sync_scope='all')
    site.store.queue_sync(site.owner,'all')
    assert dict(site.store.next_manual_sync())==before
    assert site.store.manual_sync_status(site.owner,'all')['busy']
    site.read('directory_ready',sync_scope='all')
    assert site.store.next_manual_sync() is None
    assert site.store.manual_sync_status(site.owner,'all')['complete']


def test_warm_batches_yield_to_manual_proposal_and_keep_two_minute_poll(conn,monkeypatch):
    from playwright.sync_api import sync_playwright,Page,APIRequestContext
    spec=prepare(conn)
    key=connector_key('synthetic-private-connector'*2)
    monkeypatch.setenv('EDOF_CONNECTOR_KEY',key)
    monkeypatch.setenv('EDOF_CONNECTOR_DIRECTORY',str(conn.path))
    monkeypatch.setenv('RENDER_SERVICE_ID',runner.TEST_SERVICE_ID)
    # Cadence itself is tested above with a controlled clock; keep this integration fast.
    monkeypatch.setattr('edof_traffic.MIN_GAP',0)
    executable=os.environ.get('EDOF_TEST_CHROMIUM')
    if not executable:
        pytest.skip('Explicit test Chromium not configured')
    vault=Vault(conn.path,key)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=executable,headless=True)
        context=browser.new_context()
        context.route('**/*',lambda route:route.fulfill(content_type='text/html',body='Dossiers EDOF'))
        page=context.new_page()
        page.goto(runner.LIST_URL)
        witness=Mock(method='GET',url=URL)
        witness.all_headers.return_value={}
        live={'pw':pw,'browser':browser,'page':(context,page),'pending_witness':witness,
              'proposal_witness':('owner',spec['folder_id'],conn.witness)}
        monkeypatch.setattr(Page,'reload',Mock(side_effect=AssertionError('No full reload between batches')))
        monkeypatch.setattr(runner,'open_workspace_or_login',Mock(side_effect=AssertionError('No new login')))
        calls=[]
        def get(_context,url,**kw):
            if url!=URL:
                calls.append('manual')
                return conn.portal.get(url,**kw)
            params=kw['params'];state=params['state'];index=params['page']
            calls.append((state,index))
            items=[] if state=='notProcessed' else [{'id':str(200000+index),'currentState':'accepted','beginDate':'2026-11-01'}]
            reply=Mock(status=200,url=url)
            reply.body.return_value=json.dumps({'items':items,'numberOfItems':0 if state=='notProcessed' else 5}).encode()
            return reply
        monkeypatch.setattr(APIRequestContext,'get',get)
        full={'mode':'directory','day_session':True,'full_sync':True,'owner':'owner','revision':1,'provider':'integrale','sync_until':100}
        assert runner.run_browser(full,live=live)['code']=='directory_progress'
        assert calls==[('notProcessed',0),('all',0),('all',1)]
        # A queued manual read gets the same session before the next full-list batch.
        manual=runner.run_browser({**spec,'mode':'proposal_read','shared_job':True},live=live)
        assert manual['code']=='proposal_loaded',manual
        assert conn.portal.writes==[]
        assert runner.run_browser(full,live=live)['code']=='directory_progress'
        assert calls[-3:]==['manual',('all',2),('all',3)]
        assert vault.get(directory.record_key('owner')) is None
        vault.put(directory.pending_key('owner'),{'checked':time.time()-121,'rows':{}})
        vault.put('pending-attempt:owner',time.time()-121)
        assert runner.run_browser(full,live=live)['code']=='directory_ready'
        assert calls[-2:]==[('notProcessed',0),('all',4)]
        assert len(vault.get(directory.record_key('owner'))['rows'])==5
        assert not any(isinstance(c,tuple) and c[0]=='accepted' for c in calls)
        assert 'efp_auth' not in json.dumps(calls)
        browser.close()
