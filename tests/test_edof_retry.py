"""Synthetic portal limits and corrections during a manual customer call."""
import datetime as dt
from email.utils import format_datetime
import io
import json
import os
from unittest.mock import Mock

import pytest

import edof_throttle as throttle
from edof_day_session import DayWorker, PARIS
from edof_gmail import Vault, connector_key
from test_edof_proposals import conn, prepare, run, jobs, offer, directory, FOLDER, URL, DAY
from test_edof_proposal_feedback import site, ready, BASE, HEADERS, screen


@pytest.fixture
def clock(monkeypatch):
    now = [dt.datetime(2026,11,4,16,30,tzinfo=dt.timezone.utc).timestamp()]
    monkeypatch.setattr(throttle.time,'time',lambda:now[0])
    return now


@pytest.mark.parametrize('header,delay,explicit', [('30',30,True),('7200',7200,True),('0',1,True),
    (None,60,False),('',60,False),('invalid',60,False),('-1',60,False)])
def test_retry_after_does_not_add_one_hour(header,delay,explicit):
    pause = throttle.PortalThrottled(header)
    assert (pause.delay,pause.explicit)==(delay,explicit)


def test_retry_dates_backoff_restart_and_no_deadline_extension(tmp_path,clock):
    key=connector_key('synthetic-retry'*4)
    vault=Vault(tmp_path,key)
    date=format_datetime(dt.datetime.fromtimestamp(clock[0]+45,dt.timezone.utc),usegmt=True)
    pause=throttle.PortalThrottled(date)
    pause.remember(vault)
    assert throttle.status(vault)['remaining']==45
    assert '17h30:45' in throttle.message(vault) and 'Délai demandé' in throttle.message(vault)
    clock[0]+=15
    pause.remember(vault)
    assert throttle.status(Vault(tmp_path,key))['remaining']==30
    clock[0]+=30
    assert throttle.status(vault) is None
    for expected in (120,240,480,900,900):
        pause=throttle.PortalThrottled(None)
        pause.remember(vault)
        assert throttle.status(vault)['remaining']==expected
        clock[0]+=expected
    clock[0]+=3601
    throttle.PortalThrottled(None).remember(vault)
    assert throttle.status(vault)['remaining']==60


def test_explicit_long_deadline_and_unknown_old_pause_are_never_shortened(tmp_path,clock):
    vault=Vault(tmp_path,connector_key('synthetic-retry'*4))
    throttle.PortalThrottled('7200').remember(vault)
    clock[0]+=10
    throttle.PortalThrottled('10').remember(vault)
    assert throttle.status(vault)['remaining']==7190
    vault.put(throttle.KEY,True,ttl=3600)
    throttle.PortalThrottled('5').remember(vault)
    assert throttle.status(vault)['source']=='legacy'
    clock[0]+=3599
    assert throttle.status(vault)
    clock[0]+=1
    assert not throttle.status(vault)


def test_refused_validation_preserves_new_baseline_and_operator_draft(conn):
    spec=prepare(conn)
    before=conn.vault.get(jobs.source_key('owner',FOLDER))
    desired=jobs.record(conn.path,FOLDER,'owner')['terms']
    conn.vault.put('proposal-draft:owner:'+FOLDER,{'signature':before['signature'],'values':desired})
    conn.portal.refused=True
    refused=run(conn,spec)
    assert refused['code']=='proposal_refused'
    jobs.complete(conn.path,spec,refused,refused['proposal_message'])
    current=conn.vault.get(jobs.source_key('owner',FOLDER))
    assert current['signature']!=before['signature']
    assert conn.vault.get('proposal-draft:owner:'+FOLDER)=={'signature':current['signature'],'values':desired}
    revised={**desired,'sessionStartDate':(dt.date.fromisoformat(DAY)+dt.timedelta(days=1)).isoformat()}
    jobs.enqueue(conn.path,'owner',1,directory.project(conn.portal.raw),current,revised)
    conn.portal.refused=False
    result=run(conn,jobs.next_job(conn.path,conn.gate.state()))
    assert result['code']=='proposal_confirmed'
    assert conn.portal.writes==[URL,URL+'/status',URL,URL+'/status']


def test_external_change_after_our_refused_edit_is_still_blocked(conn):
    spec=prepare(conn)
    conn.portal.refused=True
    refused=run(conn,spec)
    jobs.complete(conn.path,spec,refused,'Refus')
    current=conn.vault.get(jobs.source_key('owner',FOLDER))
    revised={**current['values'],'sessionStartDate':(dt.date.fromisoformat(DAY)+dt.timedelta(days=1)).isoformat()}
    jobs.enqueue(conn.path,'owner',1,directory.project(conn.portal.raw),current,revised)
    conn.portal.raw['trainingActionInfo']['trainingGoal']='Modification externe'
    count=len(conn.portal.writes)
    result=run(conn,jobs.next_job(conn.path,conn.gate.state()))
    assert result['code']=='proposal_changed' and len(conn.portal.writes)==count


def test_pause_rejects_manual_requests_without_worker_and_preserves_draft(clock,site):
    payload=ready(site)
    throttle.PortalThrottled('30').remember(site.vault)
    site.store.use_directory(site.owner,enable=True)
    jid=site.store.reserve(site.owner,'directory',day_session=True)
    site.store.finish(jid,{'code':'requests_ready','session_saved':True})
    live=site.store.live_connection(site.owner,True)
    assert not live['active'] and not live['paused'] and '17h30:30' in live['error']
    result=site.client.post(BASE+'submit',data=payload,headers=HEADERS)
    assert result.status_code==409 and '17h30:30' in result.json['message']
    assert jobs.record(site.store.directory,FOLDER,site.owner) is None
    assert site.vault.get('proposal-draft:'+site.owner+':'+FOLDER)['values']['priceTotal']=='1500'
    result=site.client.post(BASE+'read',data={'csrf':site.csrf},headers=HEADERS)
    assert result.status_code==409
    with jobs.database(site.store.directory) as db:
        assert db.execute('SELECT count(*) FROM proposal_reads').fetchone()[0]==0
    clock[0]+=30
    assert site.client.post(BASE+'submit',data=payload,headers=HEADERS).status_code==202


def test_pause_does_not_close_live_worker_or_consume_a_code(monkeypatch):
    worker=DayWorker()
    worker.owner,worker.provider='fixture','integrale'
    process=Mock(stdout=io.StringIO(json.dumps({'code':'portal_throttled'})+'\n'))
    process.poll.return_value=None
    worker.process=process
    monkeypatch.setattr('edof_day_session.socket.send_fds',Mock())
    monkeypatch.setattr('edof_day_session.select.select',lambda *a:([process.stdout],[],[]))
    result=worker.read({'owner':'fixture','provider':'integrale','mode':'directory',
                       'manual_until':dt.datetime.now(PARIS).timestamp()+60},{},30)
    assert result['code']=='portal_throttled' and worker.process is process
    process.wait.assert_not_called()


def test_warm_proposal_checks_fresh_data_without_reloading_the_portal(conn,monkeypatch):
    from playwright.sync_api import sync_playwright, Page, APIRequestContext
    import edof_server_browser as runner
    spec=prepare(conn)
    key=connector_key('synthetic-private-connector'*2)
    monkeypatch.setenv('EDOF_CONNECTOR_KEY',key)
    monkeypatch.setenv('EDOF_CONNECTOR_DIRECTORY',str(conn.path))
    monkeypatch.setenv('RENDER_SERVICE_ID',runner.TEST_SERVICE_ID)
    with sync_playwright() as pw:
        executable=os.environ.get('EDOF_TEST_CHROMIUM')
        if not executable:
            pytest.skip('Explicit test Chromium not configured')
        browser=pw.chromium.launch(executable_path=executable,headless=True)
        context=browser.new_context()
        context.route('**/*',lambda route:route.fulfill(content_type='text/html',body='Dossier EDOF'))
        page=context.new_page()
        page.goto(runner.DETAIL_PREFIX+FOLDER)
        live={'pw':pw,'browser':browser,'page':(context,page),'proposal_witness':('owner',FOLDER,conn.witness)}
        monkeypatch.setattr(Page,'reload',Mock(side_effect=AssertionError('Unexpected full page reload')))
        monkeypatch.setattr(runner,'open_workspace_or_login',Mock(side_effect=AssertionError('Unexpected login')))
        reads=[]
        def get(_context,url,**kw):
            reads.append(url)
            return conn.portal.get(url,**kw)
        monkeypatch.setattr(APIRequestContext,'get',get)
        monkeypatch.setattr(APIRequestContext,'put',lambda _context,url,**kw:conn.portal.put(url,**kw))
        result=runner.run_browser({**spec,'shared_job':True},live=live)
        assert result['code']=='proposal_confirmed' and not result['gmail_code_used']
        assert reads==[URL,URL,URL] and conn.portal.writes==[URL,URL+'/status']
        assert 'proposal_witness' in live
        browser.close()


def test_modal_shows_actual_pause_and_keeps_dates(screen):
    throttle.PortalThrottled('30').remember(screen.site.vault)
    page=screen.page
    page.locator('[name="confirm"]').check()
    page.get_by_role('button',name='Valider et envoyer la proposition à EDOF').click()
    page.locator('#edof-action-dialog[data-state="error"]').wait_for()
    assert 'Délai demandé par EDOF/EFP' in page.locator('#edof-action-message').inner_text()
    assert 'heure' not in page.locator('#edof-action-message').inner_text()
    assert jobs.record(screen.site.store.directory,FOLDER,screen.site.owner) is None
    page.screenshot(path='/tmp/edof-retry-modal.png')
    page.get_by_role('button',name='Revoir les informations').click()
    assert page.locator('[name="sessionStartDate"]').input_value()==DAY
