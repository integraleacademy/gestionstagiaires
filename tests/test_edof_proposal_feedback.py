"""Immediate dispatch and visible, truthful proposal outcomes; synthetic data only."""
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from werkzeug.datastructures import MultiDict

import edof_dispatch as dispatch
import edof_proposal_jobs as jobs
from edof_server_test import JobCooldown
from test_edof_proposals import FOLDER, OPTIONS, official, offer, terms
from test_integrale_edof_dashboard import site

BASE = f'/admin/edof-test/dossiers/{FOLDER}/proposal/'
DETAIL = f'/admin/edof-test?section=requests&tab=request&folder={FOLDER}'
HEADERS = {'Accept':'application/json'}


def ready(site):
    site.gate.switch('integrale',0,'fixture')
    source = offer.project(official())
    site.vault.put(jobs.source_key(site.owner,FOLDER),source)
    site.vault.put(jobs.option_key(site.owner),OPTIONS)
    values = {**terms(official()), 'priceTotal':'1500'}
    site.vault.put('proposal-draft:'+site.owner+':'+FOLDER,{'signature':source['signature'],'values':values})
    payload = MultiDict({k:v for k,v in values.items() if k not in {'blocks','trainingPaces'}})
    payload.update({'blocks':'BC01','trainingPaces':'p','csrf':site.csrf,'signature':source['signature'],'confirm':'yes'})
    return payload


def test_submission_wakes_other_process_keeps_single_ticket_and_reports_real_refusal(site):
    payload = ready(site)
    with dispatch.listen(site.store.directory) as inbox:
        dispatch.wait(inbox,0)
        response = site.client.post(BASE+'submit',data=payload,headers=HEADERS)
        assert response.status_code == 202 and response.json['status']=='queued', response.json
        marker = inbox['path'].stat().st_mtime_ns
        assert marker != inbox['seen']
        dispatch.wait(inbox,0)
        assert inbox['seen']==marker
    url = response.json['poll_url']
    assert site.client.post(BASE+'submit',data=payload,headers=HEADERS).json['poll_url']==url
    work = jobs.record(site.store.directory,FOLDER,site.owner)
    jobs.complete(site.store.directory,work,{'code':'proposal_refused'},'Début de session : 11 jours ouvrés minimum.')
    result = site.client.get(url)
    assert result.json['status']=='error' and '11 jours' in result.json['message']
    assert result.headers['Cache-Control']=='no-store'
    assert not {'terms','signature','receipt','owner'} & result.json.keys()
    assert site.client.get(url+'bad').status_code==404
    with site.client.session_transaction() as session:
        session['admin_username']='another-admin'
    assert site.client.get(url).status_code==404


def test_json_validation_and_permissions_never_enqueue(site):
    payload = ready(site)
    payload['weeklyDuration']='0'
    result = site.client.post(BASE+'submit',data=payload,headers=HEADERS)
    assert result.status_code==409 and result.json['message']
    assert not jobs.record(site.store.directory,FOLDER,site.owner)
    payload['csrf']='wrong'
    assert site.client.post(BASE+'submit',data=payload,headers=HEADERS).status_code==403
    payload['csrf']=site.csrf
    with site.client.session_transaction() as session:
        session['admin_role']='viewer'
    assert site.client.post(BASE+'submit',data=payload,headers=HEADERS).status_code==403


def test_shared_session_avoids_artificial_job_delay_but_keeps_single_browser(site):
    ready(site)
    first = site.store.reserve(site.owner,'proposal_read')
    site.store.finish(first,{'code':'proposal_loaded'})
    with pytest.raises(JobCooldown):
        site.store.reserve(site.owner,'proposal_send')
    second = site.store.reserve(site.owner,'proposal_send',shared_session=True)
    with pytest.raises(ValueError,match='déjà en cours'):
        site.store.reserve(site.owner,'proposal_send',shared_session=True)
    site.store.finish(second,{'code':'proposal_confirmed'})
    with pytest.raises(JobCooldown):
        site.store.reserve(site.owner,'read',shared_session=True)


@pytest.fixture
def screen(site):
    pw = pytest.importorskip('playwright.sync_api')
    ready(site)
    root = Path(__file__).resolve().parents[1]
    site.client.application.static_folder = str(root/'static')
    with pw.sync_playwright() as runner:
        executable = os.environ.get('EDOF_TEST_CHROMIUM')
        if not executable and not Path(runner.chromium.executable_path).exists():
            pytest.skip('Chromium is not installed')
        browser = runner.chromium.launch(executable_path=executable,args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1440,'height':1000},locale='fr-FR')
        fixture = SimpleNamespace(site=site,page=page,posts=[],errors=[],reject=None,drop=False)
        page.on('pageerror',lambda error:fixture.errors.append(str(error)))
        def local(route):
            req = route.request
            url = urlsplit(req.url)
            if url.hostname != 'fixture.local': return route.abort()
            if req.method=='POST':
                fixture.posts.append(url.path)
                if fixture.drop: return route.abort()
                if fixture.reject: return route.fulfill(status=409,json={'message':fixture.reject})
            if url.path=='/templates/cpf.jpg':
                return route.fulfill(path='/tmp/edof-cpf-logo.jpg',content_type='image/jpeg') if Path('/tmp/edof-cpf-logo.jpg').exists() else route.fulfill(status=404)
            response = site.client.open(url.path,query_string=url.query,method=req.method,
                data=req.post_data_buffer,content_type=req.headers.get('content-type'),headers={'Accept':req.headers.get('accept','')})
            route.fulfill(status=response.status_code,headers=dict(response.headers),body=response.data)
        page.route('**/*',local)
        page.goto('http://fixture.local'+DETAIL)
        yield fixture
        assert not fixture.errors
        browser.close()


def send(screen):
    screen.page.locator('[name="confirm"]').check()
    screen.page.get_by_role('button',name='Valider et envoyer la proposition à EDOF').click()
    screen.page.locator('#edof-action-dialog[open]').wait_for()
    screen.page.wait_for_function("document.querySelector('#proposition-edof').dataset.transmissionState === 'queued'")


def test_modal_follows_actual_success_and_never_double_sends(screen):
    page = screen.page
    send(screen)
    assert 'Dossier en cours de transmission' in page.locator('#edof-action-title').inner_text()
    assert page.get_by_alt_text('Mon Compte Formation').is_visible()
    page.get_by_role('button',name='Continuer en arrière-plan',exact=True).click()
    assert page.locator('#edof-action-resume').is_visible()
    assert not page.get_by_role('button',name='Valider et envoyer la proposition à EDOF').is_enabled()
    work = jobs.record(screen.site.store.directory,FOLDER,screen.site.owner)
    row = official(); row['currentState']='validated'
    import edof_directory
    jobs.complete(screen.site.store.directory,work,{'code':'proposal_confirmed','proposal_receipt':edof_directory.project(row)},'Réception confirmée par EDOF.')
    page.locator('#edof-action-resume[data-state="waiting"]').wait_for()
    page.locator('#edof-action-resume').click()
    assert page.locator('#edof-action-title').inner_text()=='En attente d’acceptation du titulaire'
    assert 'Dossier transmis à EDOF, en attente d’acceptation par le titulaire.' in page.locator('#edof-action-message').inner_text()
    assert not page.get_by_role('button',name='Inscrire sur une session',exact=True).is_visible()
    # The dossier evolves independently from the delivery receipt.
    import time
    row['currentState']='accepted'
    screen.site.vault.put(edof_directory.record_key(screen.site.owner), {
        'checked':time.time()+1,'rows':{FOLDER:edof_directory.project(row)}})
    page.locator('#edof-action-dialog[data-journey="accepted"]').wait_for()
    assert page.get_by_role('button',name='Inscrire sur une session',exact=True).is_visible()
    assert screen.posts.count(BASE+'submit')==1
    assert all(path in {BASE+'submit', f'/admin/edof-test/dossiers/{FOLDER}/journey/watch'} for path in screen.posts)


@pytest.mark.parametrize('width',[1440,390])
def test_server_refusal_is_visible_and_form_is_restored(screen,width):
    page=screen.page
    page.set_viewport_size({'width':width,'height':950})
    send(screen)
    work=jobs.record(screen.site.store.directory,FOLDER,screen.site.owner)
    jobs.complete(screen.site.store.directory,work,{'code':'proposal_refused'},'La date de début doit respecter 11 jours ouvrés minimum.')
    page.locator('#edof-action-dialog[data-state="error"]').wait_for()
    assert '11 jours ouvrés' in page.locator('#edof-action-message').inner_text()
    page.locator('[name="confirm"]').wait_for(state='attached')
    page.screenshot(path=f'/tmp/edof-proposal-refusal-{width}.png')
    bounds=page.locator('#edof-action-dialog').bounding_box()
    assert bounds['x'] >= 0 and bounds['width'] <= width
    page.get_by_role('button',name='Revoir les informations').click()
    assert not page.locator('#edof-action-dialog').is_visible()
    assert page.locator('[name="sessionStartDate"]').is_visible()
    assert screen.posts==[BASE+'submit']


def test_missing_fields_open_modal_without_post_and_return_to_invalid_field(screen):
    page=screen.page
    page.locator('[name="priceTotal"]').fill('')
    page.get_by_role('button',name='Valider et envoyer la proposition à EDOF').click()
    page.locator('#edof-action-dialog[data-state="error"]').wait_for()
    assert page.locator('#edof-action-title').inner_text()=='Informations à compléter'
    assert 'Prix total' in page.locator('[data-action-issues]').inner_text()
    assert not screen.posts
    page.get_by_role('button',name='Revoir les informations').click()
    assert page.locator('[name="priceTotal"]').evaluate('(el) => el === document.activeElement')


def test_validation_rejection_and_network_loss_never_report_success(screen):
    page=screen.page
    screen.reject='Le début de session doit être au plus tôt le 19/11/2026.'
    page.locator('[name="confirm"]').check()
    page.get_by_role('button',name='Valider et envoyer la proposition à EDOF').click()
    page.locator('#edof-action-dialog[data-state="error"]').wait_for()
    assert '19/11/2026' in page.locator('#edof-action-message').inner_text()
    page.get_by_role('button',name='Revoir les informations').click()
    screen.reject=None; screen.drop=True
    page.get_by_role('button',name='Valider et envoyer la proposition à EDOF').click()
    page.locator('#edof-action-dialog[data-state="warning"]').wait_for()
    assert 'peut avoir été pris en charge' in page.locator('#edof-action-message').inner_text()
    assert not jobs.record(screen.site.store.directory,FOLDER,screen.site.owner)


def test_scheduler_is_woken_from_another_process_without_twenty_second_wait(tmp_path):
    import subprocess
    import sys
    import time
    with dispatch.listen(tmp_path) as inbox:
        dispatch.wait(inbox,0)
        started=time.monotonic()
        child=subprocess.Popen([sys.executable,'-c','from edof_dispatch import wake; import sys; wake(sys.argv[1])',str(tmp_path)])
        try:
            dispatch.wait(inbox,2)
            assert time.monotonic()-started < 1.5
            assert inbox['seen'] > 0
        finally:
            child.wait(timeout=2)


def test_failed_initial_read_shows_that_nothing_was_sent(screen):
    send(screen)
    work = jobs.record(screen.site.store.directory, FOLDER, screen.site.owner)
    jobs.complete(screen.site.store.directory, work, {"code":"read_unconfirmed"}, jobs.LEGACY_READ_MESSAGE)
    page = screen.page
    page.locator('#edof-action-dialog[data-state="error"]').wait_for()
    assert page.locator('#edof-action-title').inner_text() == 'Proposition non envoyée'
    assert 'Aucune proposition envoyée' in page.locator('#edof-action-message').inner_text()
    assert 'lecture autonome' not in page.locator('#edof-action-dialog').inner_text()
    assert not page.get_by_role('button', name='Revoir les informations').is_visible()
    assert screen.posts == [BASE+'submit']


@pytest.mark.parametrize('width',[1440,390])
def test_accepted_dossier_prefills_filters_and_registers_in_the_same_dialog(screen,width):
    import json
    import time
    import edof_directory as directory
    import edof_enrolment_watch as watch
    from unittest.mock import Mock
    from test_edof_enrolment import catalogue
    site, page = screen.site, screen.page
    site.local.write_text(json.dumps(catalogue()))
    row = {'folder_id':FOLDER,'first_name':'Anne','last_name':'Exemple','state':'accepted',
           'title':'Formation VTC tout inclus','session_start_date':'2027-01-04','session_end_date':'2027-02-04'}
    site.vault.put(directory.record_key(site.owner), {'checked':time.time()-1,'rows':{FOLDER:row}})
    watch.watch(site.vault,site.owner,row)
    site.vault.put(watch.key(site.owner,FOLDER), {'checked':time.time(),'row':row,'fields':{
        **row,'birth_date':'1988-02-12','email':'anne@example.invalid','phone':'0600000000','total_incl':'1500.00'}})
    site.legacy.INTEGRALE_PARTNER_ID='integrale'
    site.legacy._session_trainees_list=lambda group:group['trainees']
    site.legacy._new_session_trainee=lambda group,fields:{**fields,'id':'new-trainee'}
    site.legacy._apply_pending_cnaps_imports_for_trainee=Mock()
    site.legacy.increment_partner_trainee_usage=Mock()
    page.set_viewport_size({'width':width,'height':950})
    page.goto('http://fixture.local'+DETAIL)
    page.get_by_role('button',name='Inscrire sur une session',exact=True).click()
    dialog=page.locator('#edof-action-dialog')
    page.locator('#edof-action-dialog[data-journey="choosing"]').wait_for()
    assert dialog.get_by_text('anne@example.invalid',exact=True).is_visible()
    assert dialog.locator('[data-session-option]').count()==2
    assert 'APS janvier' not in dialog.inner_text()
    submit=dialog.get_by_role('button',name='Confirmer l’inscription dans cette session',exact=True)
    assert not submit.is_enabled()
    dialog.locator('[data-session-search]').fill('février')
    assert dialog.locator('[data-session-option]:visible').count()==1
    dialog.locator('[data-session-search]').fill('')
    dialog.locator('[name="session_id"][value="v1"]').check()
    assert submit.is_enabled()
    page.screenshot(path=f'/tmp/edof-enrolment-{width}.png')
    assert dialog.evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    page.keyboard.press('Escape')
    assert not dialog.is_visible()
    page.locator('#edof-action-resume').click()
    assert dialog.locator('[name="session_id"][value="v1"]').is_checked()
    submit.click()
    page.locator('#edof-action-dialog[data-journey="registered"]').wait_for()
    assert dialog.get_by_role('button',name='Ouvrir la fiche stagiaire',exact=True).is_visible()
    saved=json.loads(site.local.read_text())
    assert len(saved['sessions'][0]['trainees'])==len(saved['wedof_links'])==1
    assert screen.posts==[f'/admin/edof-test/dossiers/{FOLDER}/create-trainee']
