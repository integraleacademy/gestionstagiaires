"""Action acknowledgements and local browser checks; no EDOF calls or real codes."""
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from test_integrale_edof_dashboard import site


def test_sync_acknowledgement_identifies_current_run_and_partial_result(site, monkeypatch):
    import edof_server_test as server
    monkeypatch.setattr(server, 'configuration', lambda: {'credentials_configured':True})
    site.vault.put('gmail', {'fixture':True})
    response = site.client.post('/admin/edof-test/synchroniser', data={'csrf':site.csrf,'scope':'all'}, headers={'Accept':'application/json'})
    assert response.status_code == 202 and response.json['requested']
    status = site.store.manual_sync_status(site.owner, 'all')
    assert status['busy'] and status['requested'] == response.json['requested']
    job = site.store.reserve(site.owner, 'directory', day_session=True, sync_scope='all')
    site.store.finish(job, {'code':'requests_ready'})
    status = site.store.manual_sync_status(site.owner, 'all')
    assert status['updated'] and not status['complete'] and not status['busy']
    assert status['requested'] == response.json['requested']


def test_json_connection_and_catchup_keep_csrf_role_and_provider_guards(site, monkeypatch):
    import edof_server_test as server
    headers = {'Accept':'application/json'}
    path = '/admin/edof-test/server/directory/manual'
    assert site.client.post(path, data={'csrf':site.csrf}, headers=headers).status_code == 409
    monkeypatch.setattr(server, 'configuration', lambda: {'credentials_configured':True})
    site.vault.put('gmail', {'fixture':True})
    assert site.client.post(path, data={'csrf':'invalid'}, headers=headers).status_code == 403
    reply = site.client.post(path, data={'csrf':site.csrf}, headers=headers)
    assert reply.status_code == 202 and reply.json['requested'] and not reply.json['active']
    job = site.store.reserve(site.owner, 'directory', day_session=True)
    site.store.finish(job, {'code':'day_login_used'})
    last = site.store.live_connection(site.owner, False)['last_read']
    assert last['finished'] >= reply.json['requested'] and last['code'] == 'day_login_used'
    resume = site.client.post('/admin/edof-test/server/directory/resume', data={'csrf':site.csrf}, headers=headers)
    assert resume.status_code == 202 and resume.json['requested']
    assert site.vault.get('day-login-override:'+site.owner)
    catchup = '/admin/edof-test/automatisations/rattraper'
    assert site.client.post(catchup, data={'csrf':site.csrf,'revision':0}, headers=headers).status_code == 409
    site.gate.switch('integrale',0,'fixture')
    assert site.client.post(catchup, data={'csrf':site.csrf,'revision':1}, headers=headers).status_code == 202
    with site.client.session_transaction() as session:
        session['admin_role'] = 'viewer'
    assert site.client.post(path, data={'csrf':site.csrf}, headers=headers).status_code == 403


@pytest.fixture
def screen(site):
    playwright = pytest.importorskip('playwright.sync_api')
    site.gate.switch('integrale',0,'fixture')
    site.vault.put('gmail', {'fixture':True})
    html = site.client.get('/admin/edof-test?section=automations').text
    state = site.client.get('/admin/edof-test/connection-status?catchup=1').json
    fixture = SimpleNamespace(state=state, posts=[], result={'requested':100,'message':'Demande reçue'}, status=202, errors=[])
    root = Path(__file__).resolve().parents[1]
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(executable_path=os.environ.get('EDOF_TEST_CHROMIUM'), headless=True, args=['--no-sandbox'])
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip('Chromium not installed')
            raise
        page = browser.new_page(viewport={'width':1440,'height':1000})
        fixture.page = page
        page.on('pageerror', lambda error: fixture.errors.append(str(error)))
        def route(request):
            path = urlsplit(request.request.url).path
            if request.request.method == 'POST':
                fixture.posts.append(path)
                request.fulfill(status=fixture.status, json=fixture.result)
            elif path.endswith('/connection-status'):
                request.fulfill(json=fixture.state)
            elif path.startswith('/static/') and (root/path.lstrip('/')).is_file():
                file = root/path.lstrip('/')
                request.fulfill(body=file.read_bytes(), content_type='text/javascript' if file.suffix=='.js' else 'text/css')
            elif path == '/admin/edof-test':
                request.fulfill(body=html, content_type='text/html')
            else:
                request.fulfill(status=404)
        page.route('**/*', route)
        page.goto('https://dashboard.invalid/admin/edof-test?section=automations')
        page.clock.install()
        yield fixture
        assert not fixture.errors
        browser.close()


def advance(screen):
    screen.page.clock.fast_forward(3500)
    screen.page.wait_for_timeout(80)


def test_sync_modal_waits_for_its_result_and_can_be_minimised(screen):
    page, state = screen.page, screen.state
    page.get_by_role('button', name='Synchro manuelle tous les dossiers', exact=True).click()
    page.get_by_role('heading',name='Synchronisation manuelle en cours',exact=True).wait_for()
    page.get_by_text('Demande de synchronisation reçue',exact=True).wait_for()
    # An old success must not complete the new action.
    state['manual_sync'] = {'requested':99,'busy':False,'updated':True,'complete':True,'message':'Ancien succès'}
    advance(screen)
    assert page.locator('#edof-action-dialog').get_attribute('data-state') == 'running'
    page.get_by_role('button',name='Continuer en arrière-plan',exact=True).click()
    assert not page.locator('#edof-action-dialog').is_visible()
    state['manual_sync'] = {'requested':100,'busy':False,'updated':True,'complete':True,'message':'Tous les dossiers sont synchronisés.'}
    advance(screen)
    assert page.locator('#edof-action-resume').is_visible()
    page.locator('#edof-action-resume').click()
    page.get_by_role('heading',name='Synchronisation terminée',exact=True).wait_for()
    assert len(screen.posts) == 1
    assert page.get_by_role('button',name='Actualiser les dossiers',exact=True).is_visible()


@pytest.mark.parametrize('action', ['connect','reconnect'])
def test_connection_modal_requires_fresh_verification(screen, action):
    page, state = screen.page, screen.state
    if action == 'reconnect':
        state['paused'] = True
        advance(screen)
    page.locator('#edof-activate button' if action=='connect' else '#edof-resume button').click()
    expected = 'Connexion EDOF en cours' if action=='connect' else 'Reconnexion EDOF en cours'
    page.get_by_role('heading',name=expected,exact=True).wait_for()
    page.get_by_text('Demande de connexion reçue',exact=True).wait_for()
    state.update(active=True,last_read={'finished':99,'code':'requests_ready'})
    advance(screen)
    assert page.get_by_role('heading',name=expected,exact=True).is_visible()
    state['last_read']['finished'] = 101
    advance(screen)
    assert page.locator('#edof-action-dialog').get_attribute('data-state') == 'success'
    assert len(screen.posts) == 1


def test_rejected_action_and_incomplete_catchup_never_show_success(screen):
    page, state = screen.page, screen.state
    screen.status, screen.result = 409, {'message':'Une lecture est déjà en cours.'}
    page.get_by_role('button',name='Synchro manuelle nouveaux dossiers',exact=True).click()
    page.get_by_role('heading',name='Traitement non terminé',exact=True).wait_for()
    assert 'Une lecture est déjà en cours.' in page.locator('#edof-action-message').inner_text()
    page.get_by_role('button',name='Fermer',exact=True).click()
    screen.status, screen.result = 202, {'requested':100,'message':'Rattrapage demandé'}
    page.get_by_role('button',name='Rattraper les automatisations',exact=True).click()
    page.get_by_text('Demande de rattrapage reçue',exact=True).wait_for()
    state['catchup'] = {'requested':100,'busy':False,'phase':'done','result':'warning','message':'Deux déclarations nécessitent une vérification.'}
    advance(screen)
    page.get_by_role('heading',name='Traitement à vérifier',exact=True).wait_for()
    assert len(screen.posts) == 2


def test_background_polling_never_opens_a_modal_and_mobile_fits(screen):
    page, state = screen.page, screen.state
    state.update(pending=True,phase='Lecture des dossiers À traiter')
    advance(screen)
    assert not page.locator('#edof-action-dialog').is_visible()
    page.set_viewport_size({'width':390,'height':844})
    page.get_by_role('button',name='Synchro manuelle tous les dossiers',exact=True).click()
    dialog = page.locator('#edof-action-dialog')
    dialog.wait_for(state='visible')
    assert dialog.evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    page.keyboard.press('Escape')
    assert not dialog.is_visible() and page.locator('#edof-action-resume').is_visible()
