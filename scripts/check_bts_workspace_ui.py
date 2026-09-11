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
            for path in ('/admin/BTS', '/admin/BTS/nouveau', '/admin/BTS/connexion', '/admin/BTS/ajouter-opco'):
                response = client.get(path)
                assert response.status_code == 200, (path, response.status_code, response.get_data(as_text=True)[:1000])
            assert client.post('/admin/BTS/nouveau', data={}).status_code == 400
            assert client.get('/admin/BTS/ajouter-akto').location == '/admin/BTS/ajouter-opco'
            with client.session_transaction() as state:
                csrf = state['bts_csrf_token']
            for path in ('/admin/BTS/wedof/synchroniser', '/admin/BTS/synchroniser', '/admin/BTS/akto/sync'):
                assert client.post(path, data={'bts_csrf_token': csrf}).status_code == 410
    print('Production crm_app entrypoint: BTS routes, isolation and CSRF OK')


def browser_check():
    from pypdf import PdfReader
    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server
    from flask import redirect, session
    from tests.test_bts_workspace import make_legacy, seed_remote
    from bts_workspace import register_bts_workspace
    from bts_workspace_store import WorkspaceStore
    from tests.test_wedof_bts import contract, folder, detailed_dossier
    from wedof_bts import folder_fields, normalize_summary, raw_fields
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
        available = [normalize_summary(contract(key, financer=financer)) for key, financer in enumerate(
            ['opcoCfaEp', 'opcoCfaAkto', 'opcoCfaOpcommerce', 'opcoCfaMobilites'], 1)]
        api.contracts_page.return_value = (available, False, 4)
        api.contract.return_value = available[0]
        api.folder.return_value = folder_fields(folder(), 'OPCO-1')
        details = detailed_dossier()
        details['echeances'] = [{**details['echeances'][0], 'numero': n, 'codification': f'E{n}', 'dateOuverture': opening}
                               for n, opening in enumerate(('2026-09-01', '2027-03-01', '2027-06-01'), 1)]
        api.raw.return_value = raw_fields(details, available[0])
        store.add_fee(record_id, 'RESTAURATION', '60.55', 'Ancienne saisie conservée', 'Test')
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
                assert page.get_by_label('OPCO à rechercher').input_value() == ''
                assert page.get_by_label('OPCO à rechercher').locator('option').count() == 5
                page.get_by_label('Numéro de contrat OPCO ou numéro DECA').fill('DECA-1')
                page.get_by_role('button', name='Rechercher le contrat', exact=True).click()
                page.get_by_role('button', name='Ajouter ce dossier', exact=True).wait_for()
                assert store.record('w-1') is None
                assert store.record('w-2') is None
                api.contracts_page.assert_called_once_with(1, financer='')
                assert 'OPCO EP · Engagé' in page.inner_text('body')
                api.folder.assert_called_once()
                page.screenshot(path=str(output / 'recherche-contrat-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 1000})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
                page.screenshot(path=str(output / 'recherche-contrat-mobile.png'), full_page=True)
                page.get_by_role('button', name='Ajouter ce dossier', exact=True).click()
                page.get_by_role('heading', name='Camille Exemple', exact=True).wait_for()
                assert store.record('w-1') is not None
                assert all(store.record('w-' + str(key)) is None for key in (2, 3, 4))
                assert store.record('w-1')['financer'] == 'opcoCfaEp'
                assert 'OPCO EP' in page.inner_text('body')
                api.raw.assert_called_once()
                page.goto(url + '/admin/BTS/dossiers/w-1?tab=contrat')
                page.get_by_role('heading', name='Générer le contrat d’apprentissage').wait_for()
                assert page.locator('[name="contract_start"]').input_value() == '2026-08-20'
                assert page.locator('[name="training_hours"]').input_value() == '1350'
                assert page.locator('[name="exam_end"]').input_value() == ''
                assert 'OPCO EP' in page.inner_text('body')
                page.locator('[data-cerfa-section="agreement"] summary').click()
                page.locator('[name="weekly_hours"]').fill('35')
                page.locator('[name="weekly_minutes"]').fill('0')
                assert page.get_by_role('link', name='Télécharger le CERFA').get_attribute('aria-disabled') == 'true'
                assert page.locator('[data-cerfa-unsaved]').is_visible()
                page.get_by_role('button', name='Enregistrer les informations').click()
                page.wait_for_load_state()
                assert store.cerfa_complements('w-1')['values']['weekly_hours'] == '35'
                assert store.record('w-1')['contract_start'] == '2026-08-20'
                assert page.get_by_role('link', name='Télécharger le CERFA').get_attribute('aria-disabled') is None
                api.raw.assert_called_once()
                with page.expect_download() as download_info:
                    page.get_by_role('link', name='Télécharger le CERFA').click()
                downloaded = Path(directory) / 'cerfa-test.pdf'
                download_info.value.save_as(str(downloaded))
                filled_pdf = PdfReader(downloaded)
                assert len(filled_pdf.pages) == 2
                assert filled_pdf.get_fields()['Zone de texte 8_68']['/V'] == '35'
                assert filled_pdf.get_fields()['Zone de texte 21_19']['/V'] == '20'
                assert filled_pdf.get_fields()['Zone de texte 8_17']['/V'] == 'Camille'
                page.screenshot(path=str(output / 'cerfa-mobile.png'), full_page=True)
                page.set_viewport_size({'width': 1440, 'height': 1100})
                page.screenshot(path=str(output / 'cerfa-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 1000})
                page.goto(url + '/admin/BTS/dossiers/w-1?tab=comptabilite')
                assert 'Ouverture à la facturation' in page.inner_text('body')
                assert '01/03/2027' in page.inner_text('body')
                assert 'Du 01/09/2026 au 01/03/2027' in page.inner_text('body')
                assert 'Du 01/03/2027 au 01/06/2027' in page.inner_text('body')
                assert 'Dernière échéance : aucune ouverture suivante.' in page.inner_text('body')
                assert 'Frais annexes accordés par l’OPCO' in page.inner_text('body')
                assert '300,00 €' in page.inner_text('body')
                assert 'Non soldé' in page.inner_text('body')
                assert 'Règlement non communiqué' in page.inner_text('body')
                assert page.get_by_role('button', name='Ajouter des frais annexes').count() == 0
                assert 'Frais annexes saisis localement' not in page.inner_text('body')
                assert 'plafond' not in page.inner_text('body').lower()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
                page.screenshot(path=str(output / 'opco-details-mobile.png'), full_page=True)
                page.set_viewport_size({'width': 1440, 'height': 1100})
                page.screenshot(path=str(output / 'opco-details-desktop.png'), full_page=True)
                page.goto(url + '/admin/BTS')
                page.screenshot(path=str(output / 'dossiers-desktop.png'), full_page=True)
                page.goto(url + f'/admin/BTS/dossiers/{record_id}?tab=comptabilite')
                page.get_by_role('heading', name='Échéancier de facturation').wait_for()
                page.screenshot(path=str(output / 'comptabilite-desktop.png'), full_page=True)
                assert page.get_by_role('button', name='Ajouter des frais annexes').count() == 0
                assert '60,55 €' not in page.inner_text('body')
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
                    page.goto(url + '/admin/BTS/dossiers/w-1?tab=comptabilite')
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'), f'OPCO fee grid overflow at {width}px'
                    page.screenshot(path=str(output / f'frais-opco-{width}.png'), full_page=True)
                    for tab in ('contrat', 'etudiant', 'entreprise'):
                        page.goto(url + f'/admin/BTS/dossiers/w-1?tab={tab}')
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'), f'CERFA {tab} overflow at {width}px'
                    page.screenshot(path=str(output / f'cerfa-entreprise-{width}.png'), full_page=True)
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
    print('Browser flows: manual OPCO import, CERFA prefill/save/download, granted fees and payment availability, opening-to-opening periods, invoice draft, responsive layouts and JavaScript OK')


if __name__ == '__main__':
    production_entrypoint_check()
    if '--browser' in sys.argv:
        browser_check()
