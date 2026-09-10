"""CI-only checks with disposable SQLite files and fictitious test fixtures."""
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def production_entrypoint_check():
    import crm_app
    import app as legacy
    with tempfile.TemporaryDirectory() as directory:
        client = crm_app.app.test_client()
        with client.session_transaction() as state:
            state['admin_logged_in'] = True
            state['admin_role'] = 'admin'
        with patch.object(legacy, 'AKTO_BTS_DB_FILE', str(Path(directory) / 'akto.sqlite3')), \
             patch.object(legacy, 'AKTO_BTS_SYNC_LOCK_FILE', str(Path(directory) / 'akto.lock')), \
             patch.object(legacy, 'load_data', side_effect=AssertionError('BTS must not read data.json')):
            for path in ('/admin/BTS', '/admin/BTS/nouveau', '/admin/BTS/connexion'):
                response = client.get(path)
                assert response.status_code == 200, (path, response.status_code, response.get_data(as_text=True)[:1000])
            assert client.post('/admin/BTS/nouveau', data={}).status_code == 400
    print('Production crm_app entrypoint: BTS routes, isolation and CSRF OK')


def browser_check():
    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server
    from flask import redirect, session
    from tests.test_bts_workspace import make_legacy, seed_remote
    from bts_workspace import register_bts_workspace
    from bts_workspace_store import WorkspaceStore
    from tests.test_wedof_bts import contract, folder
    from wedof_bts import folder_fields, normalize_summary
    output = ROOT / 'test-artifacts' / 'bts'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        legacy = make_legacy(directory)
        # This route exists only on a disposable test Flask app, never production.
        @legacy.app.get('/__test_login')
        def test_login():
            session.update(admin_logged_in=True, admin_role='admin')
            return redirect('/admin/BTS')
        register_bts_workspace(legacy)
        store = WorkspaceStore(legacy.AKTO_BTS_DB_FILE)
        record_id, _ = seed_remote(store)
        api = Mock()
        api.contracts_page.return_value = ([normalize_summary(contract())], False, 1)
        api.folder.return_value = folder_fields(folder(), 'OPCO-1')
        server = make_server('127.0.0.1', 0, legacy.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        try:
            with patch.dict(os.environ, {'WEDOF_API_KEY': 'test-key'}), \
                 patch('bts_workspace.WedofBtsClient', return_value=api) as factory, \
                 sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={'width': 1440, 'height': 1100})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url + '/__test_login')
                factory.assert_not_called()
                page.get_by_role('button', name='Synchroniser AKTO via WEDOF').click()
                page.get_by_role('link', name='Ouvrir le dossier Camille Exemple', exact=True).wait_for()
                assert store.wedof_state()['status'] == 'complete'
                api.contracts_page.assert_called_once()
                api.folder.assert_called_once()
                page.screenshot(path=str(output / 'dossiers-desktop.png'), full_page=True)
                page.goto(url + f'/admin/BTS/dossiers/{record_id}?tab=comptabilite')
                page.get_by_role('heading', name='Échéancier de facturation').wait_for()
                page.screenshot(path=str(output / 'comptabilite-desktop.png'), full_page=True)
                page.get_by_role('button', name='Ajouter des frais annexes').click()
                page.locator('#fee-dialog input[name="amount"]').fill('60,55')
                page.locator('#fee-dialog input[name="description"]').fill('Frais de test')
                page.get_by_role('button', name='Enregistrer le frais').click()
                page.wait_for_load_state()
                assert store.record(record_id)['fees'][0]['amount_cents'] == 6055
                page.get_by_role('button', name='Préparer', exact=True).click()
                page.wait_for_load_state()
                assert len(store.record(record_id)['drafts']) == 1
                page.goto(url + '/admin/BTS/nouveau')
                page.locator('[name="apprentice_first_name"]').fill('Camille')
                page.locator('[name="apprentice_last_name"]').fill('Exemple')
                page.get_by_role('button', name='Créer le dossier').click()
                page.wait_for_load_state()
                assert 'Camille Exemple' in page.title()
                page.screenshot(path=str(output / 'etudiant-desktop.png'), full_page=True)
                for width in (1024, 768, 390):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    page.goto(url + '/admin/BTS')
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'), f'Dossier list overflow at {width}px'
                    page.screenshot(path=str(output / f'dossiers-{width}.png'), full_page=True)
                    page.goto(url + f'/admin/BTS/dossiers/{record_id}?tab=comptabilite')
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'), f'Page overflow at {width}px'
                    page.screenshot(path=str(output / f'comptabilite-{width}.png'), full_page=True)
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
    print('Browser flows: WEDOF import, dossier creation, fee dialog, invoice draft, responsive layouts and JavaScript OK')


if __name__ == '__main__':
    production_entrypoint_check()
    if '--browser' in sys.argv:
        browser_check()
