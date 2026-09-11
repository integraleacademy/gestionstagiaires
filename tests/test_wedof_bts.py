import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from bts_workspace import register_bts_workspace
from bts_workspace_store import WorkspaceStore, billing_view, opco_costs_view
from tests.test_bts_workspace import make_legacy
from wedof_bts import FINANCERS, WedofBtsClient, folder_fields, is_apprenticeship_event, normalize_summary, raw_fields
from wedof_bts_lookup import add_selection, matches, reference, search_step
from wedof_service import WedofApiError


def contract(key=1, **changes):
    return {"id": key, "financer": "opcoCfaAkto", "state": "accepted", "amount": 6000,
            "externalIdTrainingOrganism": f"AK-{key}", "externalIdDeca": f"DECA-{key}",
            "startDate": "2026-09-01T00:00:00Z", "endDate": "2028-08-31T00:00:00Z",
            "updatedOn": "2026-09-10T12:00:00Z", "_links": {
                "registrationFolder": {"externalId": f"OPCO-{key}", "href": "https://untrusted.invalid"},
                "employer": {"name": "Entreprise exemple", "siret": "12345678901234"}}, **changes}


def folder(key=1, **changes):
    return {"externalId": f"OPCO-{key}", "type": "opcoCfa", "iban": "PRIVATE-BANK",
            "attendee": {"firstName": "Camille", "lastName": "Exemple", "email": "camille@example.test", "nir": "PRIVATE-NIR"},
            "trainingActionInfo": {"title": "BTS MOS", "sessionStartDate": "2026-09-01", "sessionEndDate": "2028-08-31", "hoursInCenter": 1350},
            "_links": {"certification": {"externalId": "RNCP38362"}}, **changes}


def detailed_dossier(key=1):
    """Synthetic CFA Dock v1 response (official schema, 2026-02-11)."""
    return {"cerfa": {"numeroInterne": f"AK-{key}",
                     "contrat": {"noContrat": f"DECA-{key}", "dateDebutContrat": "2026-08-20T00:00:00+0000",
                                 "dateConclusion": "2026-08-03", "dateFinContrat": "2028-08-31", "salaireEmbauche": 1081.23},
                     "formation": {"dureeFormation": 1350, "nombreHeuresEnDistanciel": 0},
                     "apprenti": {"nir": "PRIVATE-NIR", "adresse": {"adresse1": "1 rue Exemple", "codePostal": "75001", "commune": "Paris"}},
                     "maitre1": {"prenom": "Alex", "nom": "Exemple", "courriel": "alex@example.test", "nir": "PRIVATE-TUTOR"}},
            "echeances": [{"numero": 2, "codification": "E2", "montantTotal": 2648.40, "montantRegle": 0,
                           "montantEnCoursInstruction": 0, "dateOuverture": "2027-03-01T00:00:00+0000",
                           "dateDebut": None, "dateFin": None, "iban": "PRIVATE-BANK"}],
            "engagementsFraisAnnexe": [{"natureFrais": "Restauration", "quantite": 100, "prixUnitaire": 3, "montantTotal": 300},
                                       {"natureFrais": "Premierequipement", "quantite": 1, "prixUnitaire": 500, "montantTotal": 500}],
            "detailsFacturation": {"plafondFraisPremierEquipement": 500, "fraisPremierEquipementRegles": False,
                                   "periodesFraisAnnexes": [{"numeroEcheance": 1, "nature": "RESTAURATION", "iban": "PRIVATE"}],
                                   "iban": "PRIVATE"}}


class ClientTests(unittest.TestCase):
    def response(self, payload, headers=None, status=200):
        return Mock(status_code=status, headers=headers or {}, json=Mock(return_value=payload))

    def test_financer_pagination_and_quota_counting(self):
        http = Mock()
        http.get.return_value = self.response([contract()], {"X-Total-Count": "3", "X-Current-Page": "1", "X-Item-Per-Page": "1"})
        with patch('wedof_service.reserve_request') as reserve:
            client = WedofBtsClient(api_key='test-key', session=http)
            items, more, total = client.contracts_page(limit=1)
        self.assertTrue(more)
        self.assertEqual(total, 3)
        self.assertEqual(items[0]['employer_name'], 'Entreprise exemple')
        self.assertEqual(http.get.call_args.kwargs['params'], {'financer': ','.join(FINANCERS), 'state': 'all', 'page': 1, 'limit': 1})
        self.assertEqual(reserve.call_args.kwargs['origin'], 'gestionstagiaires-bts')
        self.assertNotIn('allow_over_limit', reserve.call_args.kwargs)
        self.assertEqual(http.get.call_args.args[0], 'https://www.wedof.fr/api/workingContracts')

    def test_invalid_financer_or_identity_fails_closed(self):
        for item in (contract(financer='cpf'), contract(financer='opcoCfaAtlas'), contract(financer=[]),
                     contract(id='../organisms'), {'type': 'cpf'}, contract(id=True)):
            with self.assertRaises(WedofApiError):
                normalize_summary(item)
        http = Mock()
        http.get.return_value = self.response(contract(2))
        with patch('wedof_service.reserve_request'):
            with self.assertRaises(WedofApiError):
                WedofBtsClient(api_key='x', session=http).contract('1')

    def test_four_financers_and_explicit_filter_are_checked_against_the_response(self):
        http = Mock()
        payload = [contract(key, financer=financer) for key, financer in enumerate(FINANCERS, 1)]
        with patch('wedof_service.reserve_request'):
            client = WedofBtsClient(api_key='x', session=http)
            http.get.return_value = self.response(payload)
            items, _, _ = client.contracts_page()
            self.assertEqual({item['financer'] for item in items}, set(FINANCERS))
            for financer in FINANCERS:
                with self.subTest(financer=financer):
                    http.get.return_value = self.response([contract(financer=financer)])
                    self.assertEqual(client.contracts_page(financer=financer)[0][0]['financer'], financer)
                    self.assertEqual(http.get.call_args.kwargs['params']['financer'], financer)
            http.reset_mock()
            with self.assertRaises(WedofApiError):
                client.contracts_page(financer='cpf')
            http.get.assert_not_called()
            http.get.return_value = self.response([contract()])
            with self.assertRaises(WedofApiError):
                client.contracts_page(financer='opcoCfaEp')

    def test_rate_limit_has_no_retry_and_governor_redacts_contract_ids(self):
        http = Mock()
        http.get.return_value = self.response({}, {'Retry-After': '60'}, 429)
        with patch('wedof_service.reserve_request') as reserve, patch('wedof_service.time.sleep') as sleep:
            with self.assertRaises(WedofApiError):
                WedofBtsClient(api_key='x', session=http).contract('456')
        self.assertEqual(http.get.call_count, 1)
        sleep.assert_not_called()
        self.assertEqual(reserve.call_args.kwargs['path'], '/workingContracts/:id')

    def test_pagination_rejects_duplicates_and_inconsistent_headers(self):
        for payload, headers in (([contract(), contract()], {}), ([contract()], {'x-total-count': '8', 'x-current-page': '2'}),
                                 ([], {'x-total-count': '20'}), ({'error': 'unexpected'}, {})):
            http = Mock(get=Mock(return_value=self.response(payload, headers)))
            with patch('wedof_service.reserve_request'), self.assertRaises(WedofApiError):
                WedofBtsClient(api_key='x', session=http).contracts_page(limit=2)

    def test_matching_folder_is_required_and_private_fields_not_stored(self):
        fields = folder_fields(folder(), 'OPCO-1')
        self.assertEqual(fields['rncp'], 'RNCP38362')
        self.assertEqual(fields['training_start'], '2026-09-01')
        self.assertNotIn('PRIVATE', json.dumps(fields))
        for payload in (folder(type='cpf'), folder(externalId='OTHER')):
            with self.assertRaises(WedofApiError):
                folder_fields(payload, 'OPCO-1')

    def test_raw_identity_and_unknown_financial_amounts(self):
        summary = normalize_summary(contract())
        raw = {'cerfa': {'numeroInterne': 'AK-1'}, 'echeances': [{'numero': 1, 'montantTotal': 6000}], 'iban': 'PRIVATE'}
        fields = raw_fields(raw, summary)
        self.assertIsNone(billing_view(fields)['cards'][0]['paid'])
        self.assertFalse(billing_view(fields)['cards'][0]['can_draft'])
        for raw in ({}, {'cerfa': {'numeroInterne': 'OTHER'}}):
            with self.assertRaises(WedofApiError):
                raw_fields(raw, summary)
        self.assertIsNone(normalize_summary(contract(amount=None))['engagement'])
        self.assertIsNone(normalize_summary(contract(amount=float('nan')))['engagement'])

    def test_complete_cerfa_and_granted_costs_for_all_supported_opcos(self):
        for financer in FINANCERS:
            with self.subTest(financer=financer):
                fields = raw_fields(detailed_dossier(), normalize_summary(contract(financer=financer)))
                self.assertEqual(fields['contract_start'], '2026-08-20')
                self.assertEqual(fields['contract_conclusion'], '2026-08-03')
                self.assertEqual(fields['training_hours'], 1350)
                self.assertEqual(fields['remote_hours'], 0)
                self.assertEqual(fields['gross_salary'], 1081.23)
                self.assertEqual(fields['apprentice_address'], '1 rue Exemple')
                self.assertEqual(fields['tutor_name'], 'Alex Exemple')
                self.assertNotIn('PRIVATE', json.dumps(fields))
                self.assertEqual(opco_costs_view(fields)['items'][1]['label'], 'Premier équipement')
                self.assertEqual(opco_costs_view(fields)['items'][0]['label'], 'Restauration')
                self.assertEqual(opco_costs_view(fields)['items'][0]['amount'], 30000)
                self.assertFalse(opco_costs_view(fields)['ceilings'][0]['paid'])
                card = billing_view(fields)['cards'][0]
                self.assertEqual(card['opening_date'], '2027-03-01')
                self.assertFalse(card['raw']['dateDebut'])
                self.assertFalse(card['can_draft'])
                self.assertEqual(billing_view(fields)['total'], 264840)  # Fees must not inflate tuition schedules.

    def test_absent_numbers_stay_unknown_and_real_periods_are_kept(self):
        raw = detailed_dossier()
        raw['cerfa']['formation'] = {'dureeFormation': None, 'nombreHeuresEnDistanciel': float('nan')}
        raw['cerfa']['contrat']['salaireEmbauche'] = -1
        raw['echeances'][0].update(dateDebut='2026-09-01', dateFin='2027-02-28')
        raw['engagementsFraisAnnexe'][0]['montantTotal'] = None
        fields = raw_fields(raw, normalize_summary(contract()))
        self.assertNotIn('training_hours', fields)
        self.assertNotIn('remote_hours', fields)
        self.assertNotIn('gross_salary', fields)
        self.assertIsNone(opco_costs_view(fields)['items'][0]['amount'])
        self.assertEqual(fields['schedules'][0]['dateFin'], '2027-02-28')
        self.assertEqual(fields['schedules'][0]['dateOuverture'], '2027-03-01')


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.legacy = make_legacy(self.temp.name)
        self.store = WorkspaceStore(self.legacy.AKTO_BTS_DB_FILE)
        self.api = Mock()
        self.api.contracts_page.return_value = ([normalize_summary(contract()), normalize_summary(contract(2))], False, 2)
        self.api.folder.side_effect = lambda key: folder_fields(folder(int(key.split('-')[-1])), key)
        self.api.contract.side_effect = lambda key: normalize_summary(contract(int(key)))
        self.api.raw.side_effect = lambda key, summary: raw_fields(detailed_dossier(int(key)), summary)

    def step(self, **kwargs):
        return search_step(self.store, self.api, 'browser-one', config_id='config', **kwargs)

    def finish(self, state):
        while state['status'] == 'running':
            state = self.step(action='continue', run_id=state['id'], revision=state['revision'])
        return state

    def search(self, number='DECA-1'):
        return self.finish(self.step(number=number))

    def add(self, key='1', run_id=None):
        state = self.store.wedof_lookup('browser-one')
        return add_selection(self.store, self.api, state, key, 'Test', config_id='config', run_id=run_id or state['id'])

    def test_lookup_only_previews_exact_matches_and_never_creates_dossiers(self):
        result = self.search(' dEcA- 1 ')
        self.assertEqual(result['status'], 'ready')
        self.assertEqual([c['working_contract_id'] for c in result['candidates']], ['1'])
        self.assertNotIn('config_id', result)
        self.assertNotIn('summary_hash', result['candidates'][0])
        self.assertEqual(self.store.listing()['total'], 0)
        self.api.raw.assert_not_called()
        self.api.folder.assert_called_once_with('OPCO-1')
        self.assertNotIn('AK-2', json.dumps(self.store.wedof_lookup('browser-one')))
        self.assertNotIn('bts_wedof_lookups', self.store.export_workspace())
        self.assertNotIn('PRIVATE', json.dumps(self.store.wedof_lookup('browser-one')))

    def test_manual_add_only_selected_contract_and_retries_preserve_local_work(self):
        local = self.store.create_local({'apprentice_first_name': 'Local', 'apprentice_last_name': 'Exemple'})
        self.search('AK-1')
        record_id, added = self.add()
        self.assertEqual((record_id, added), ('w-1', True))
        self.assertEqual(self.store.record('w-1')['name'], 'Camille Exemple')
        self.assertIsNone(self.store.record('w-2'))
        self.api.raw.assert_called_once()
        self.assertEqual(self.api.raw.call_args.args[0], '1')
        self.assertEqual(self.store.record('w-1')['contract_start'], '2026-08-20')
        self.assertEqual(len(self.store.record('w-1')['extra_costs']), 2)
        self.store.annotate('w-1', 'Suivi à conserver', ['cerfa_prepared'], 0, 'Test')
        self.store.add_fee('w-1', 'PREMIER_EQUIPEMENT', '150', 'Frais', 'Test')
        self.api.reset_mock()
        self.assertEqual(self.add(), ('w-1', False))
        self.api.contract.assert_not_called()
        self.api.folder.assert_not_called()
        self.api.raw.assert_not_called()
        self.assertEqual(self.store.listing()['total'], 2)
        self.assertIsNotNone(self.store.record(local))
        self.assertEqual(self.store.record('w-1')['annotation']['notes'], 'Suivi à conserver')
        self.assertEqual(self.store.record('w-1')['fees'][0]['amount_cents'], 15000)

    def test_optional_raw_failure_keeps_selected_dossier_and_explains_partial_import(self):
        self.search()
        self.api.raw.side_effect = WedofApiError('Données temporairement indisponibles.', 'raw_unavailable')
        self.assertEqual(self.add(), ('w-1', True))
        record = self.store.record('w-1')
        self.assertEqual(record['name'], 'Camille Exemple')
        self.assertTrue(record['raw_stale'])
        self.assertIn('indisponibles', record['raw_error'])
        self.assertIsNone(self.store.record('w-2'))

    def test_refresh_and_ui_show_opening_and_grants_preserve_local_fees(self):
        self.search()
        self.add()
        self.store.add_fee('w-1', 'RESTAURATION', '12', 'Local', 'Test')
        register_bts_workspace(self.legacy)
        client = self.legacy.app.test_client()
        with client.session_transaction() as state:
            state.update(admin_logged_in=True, admin_role='admin')
        page = client.get('/admin/BTS/dossiers/w-1?tab=comptabilite')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Ouverture à la facturation', page.text)
        self.assertIn('01/03/2027', page.text)
        self.assertIn('Période de prestation non transmise', page.text)
        self.assertIn('300,00 €', page.text)
        self.assertIn('12,00 €', page.text)
        with client.session_transaction() as state:
            token = state['bts_csrf_token']
        self.api.folder.side_effect = WedofApiError('Fiche temporairement indisponible.', 'folder_unavailable')
        self.api.raw.reset_mock()
        with patch.dict(os.environ, {'WEDOF_API_KEY': 'test-key'}), patch('bts_workspace.WedofBtsClient', return_value=self.api):
            client.post('/admin/BTS/dossiers/w-1/actualiser', data={'bts_csrf_token': token})
        self.api.raw.assert_called_once()
        self.assertEqual(self.store.record('w-1')['contract_start'], '2026-08-20')
        self.assertEqual(self.store.record('w-1')['fees'][0]['amount_cents'], 1200)
        self.store.upsert_wedof_summary(normalize_summary(contract(startDate=None)), 'Test')
        self.assertEqual(self.store.record('w-1')['contract_start'], '2026-08-20')
        self.assertTrue(opco_costs_view(self.store.record('w-1'))['stale'])
        empty = detailed_dossier()
        empty.update(echeances=[], engagementsFraisAnnexe=[], detailsFacturation={})
        self.store.update_wedof_details('1', raw_fields(empty, normalize_summary(contract())))
        page = client.get('/admin/BTS/dossiers/w-1?tab=comptabilite')
        self.assertIn('WEDOF a renvoyé un échéancier vide', page.text)
        self.assertNotIn('0,00 €', page.text.split('<dl class="ws-legend">')[1].split('</dl>')[0])

    def test_same_deca_requires_selection_and_only_adds_one(self):
        self.api.contracts_page.return_value = ([normalize_summary(contract()), normalize_summary(contract(2, externalIdDeca='DECA-1'))], False, 2)
        result = self.search()
        self.assertEqual(len(result['candidates']), 2)
        self.assertEqual(self.store.listing()['total'], 0)
        self.api.contract.side_effect = lambda key: normalize_summary(contract(2, externalIdDeca='DECA-1'))
        self.assertEqual(self.add('2'), ('w-2', True))
        self.assertIsNone(self.store.record('w-1'))

    def test_same_deca_across_four_opcos_keeps_each_contract_and_financer_distinct(self):
        summaries = [normalize_summary(contract(key, financer=financer, externalIdDeca='DECA-1'))
                     for key, financer in enumerate(FINANCERS, 1)]
        self.api.contracts_page.return_value = (summaries, False, 4)
        self.api.contract.side_effect = lambda key: summaries[int(key) - 1]
        result = self.search()
        self.assertEqual({c['financer'] for c in result['candidates']}, set(FINANCERS))
        self.assertEqual(self.store.listing()['total'], 0)
        for key, financer in enumerate(FINANCERS, 1):
            with self.subTest(financer=financer):
                self.assertEqual(self.add(str(key)), ('w-' + str(key), True))
                self.assertEqual(self.store.listing()['total'], key)
                record = self.store.record('w-' + str(key))
                self.assertEqual(record['financer'], financer)
                self.assertIn(FINANCERS[financer], record['events'][0]['label'])
                self.assertEqual(self.add(str(key)), ('w-' + str(key), False))
        self.assertEqual({row['financer'] for row in self.store.listing()['records']}, set(FINANCERS))

    def test_selected_opco_is_retained_on_resume_and_cannot_change_during_add(self):
        summary = normalize_summary(contract(financer='opcoCfaEp'))
        self.api.contracts_page.return_value = ([summary], False, 1)
        first = self.step(number='DECA-1', financer='opcoCfaEp')
        done = self.step(action='continue', run_id=first['id'], revision=first['revision'], financer='opcoCfaAkto')
        self.assertEqual(done['status'], 'ready')
        self.assertEqual(done['financer'], 'opcoCfaEp')
        self.api.contracts_page.assert_called_once_with(1, financer='opcoCfaEp')
        # The same WEDOF ID and DECA from another supported OPCO cannot replace the preview.
        self.api.contract.return_value = normalize_summary(contract(financer='opcoCfaMobilites'))
        self.api.contract.side_effect = None
        with self.assertRaises(ValueError):
            self.add()
        self.assertEqual(self.store.listing()['total'], 0)
        self.api.reset_mock()
        with self.assertRaises(WedofApiError):
            self.step(number='DECA-1', financer='opcoCfaAtlas')
        self.api.contracts_page.assert_not_called()

    def test_partial_reference_does_not_match_and_invalid_input_is_rejected(self):
        self.assertFalse(matches(normalize_summary(contract(123)), reference('DECA-12')))
        self.assertEqual(self.search('AK-123')['candidates'], [])
        for number in ('', 'x', 'DECA', '<script>123', '1' * 121):
            with self.assertRaises(ValueError):
                self.step(number=number)
        self.assertEqual(self.store.listing()['total'], 0)

    def test_forged_or_replaced_search_cannot_add_a_contract(self):
        first = self.search()
        with self.assertRaises(ValueError):
            self.add('2')
        with self.assertRaises(ValueError):
            self.add('../organisms')
        self.search('DECA-2')
        with self.assertRaises(ValueError):
            self.add('1', run_id=first['id'])
        self.api.contract.assert_not_called()
        self.assertEqual(self.store.listing()['total'], 0)

    def test_changed_contract_or_failed_detail_read_does_not_create_a_dossier(self):
        self.search()
        self.api.contract.side_effect = None
        self.api.contract.return_value = normalize_summary(contract(amount=5000))
        with self.assertRaises(ValueError):
            self.add()
        self.api.contract.return_value = normalize_summary(contract())
        self.api.folder.side_effect = WedofApiError('Indisponible', 'wedof_server_error', True, 503)
        with self.assertRaises(WedofApiError):
            self.add()
        self.assertEqual(self.store.listing()['total'], 0)

    def test_quota_pause_retains_search_cursor_without_importing_catalogue(self):
        self.api.contracts_page.side_effect = [
            ([normalize_summary(contract())], True, 2),
            WedofApiError('Plafond atteint', 'wedof_quota_exceeded', False, 429),
            ([normalize_summary(contract(2))], False, 2)]
        first = self.step(number='DECA-2')
        paused = self.step(action='continue', run_id=first['id'], revision=first['revision'])
        self.assertEqual(paused['status'], 'paused')
        self.assertEqual(self.store.wedof_lookup('browser-one')['page'], 2)
        resumed = self.step(action='resume', run_id=paused['id'], revision=paused['revision'])
        result = self.finish(resumed)
        self.assertEqual(result['candidates'][0]['working_contract_id'], '2')
        self.assertEqual([c.args[0] for c in self.api.contracts_page.call_args_list], [1, 2, 2])
        self.assertEqual(self.store.listing()['total'], 0)

    def test_stale_request_repeated_pages_and_budget_cannot_trigger_extra_imports(self):
        first = self.step(number='DECA-1')
        done = self.finish(first)
        self.assertEqual(self.step(action='continue', run_id=first['id'], revision=first['revision']), done)
        self.api.folder.assert_called_once()
        state = self.store.wedof_lookup('browser-one')
        state.update(status='running', phase='list', requests=20, page=2)
        self.store.save_wedof_lookup('browser-one', state)
        self.api.reset_mock()
        paused = self.step(action='continue', run_id=state['id'], revision=state['revision'])
        self.assertEqual(paused['status'], 'paused')
        self.api.contracts_page.assert_not_called()
        self.api.contracts_page.return_value = ([normalize_summary(contract())], True, 2)
        paused = self.step(action='resume', run_id=paused['id'], revision=paused['revision'])
        self.assertEqual(paused['status'], 'paused')
        self.assertEqual(self.store.wedof_lookup('browser-one')['page'], 1)
        self.assertEqual(self.store.listing()['total'], 0)

    def test_previews_expire_and_are_bound_to_the_browser(self):
        result = self.search()
        self.assertEqual(self.store.wedof_lookup('browser-two'), {})
        with patch('bts_workspace_store.time.time', return_value=9999999999):
            self.assertEqual(self.store.wedof_lookup('browser-one'), {})
            with self.assertRaises(ValueError):
                add_selection(self.store, self.api, {}, '1', 'Test', config_id='config', run_id=result['id'])
        self.api.contract.assert_not_called()

    def test_old_schedules_cannot_be_billed_after_a_change_or_incomplete_refresh(self):
        summary = normalize_summary(contract())
        self.store.upsert_wedof_summary(summary, 'Test')
        raw = {'cerfa': {'numeroInterne': 'AK-1'}, 'echeances': [{
            'numero': 1, 'montantTotal': 6000, 'montantRegle': 0,
            'montantEnCoursInstruction': 0, 'dateOuverture': '2026-09-01'}]}
        self.store.update_wedof_details('1', raw_fields(raw, summary))
        self.assertTrue(billing_view(self.store.record('w-1'))['cards'][0]['can_draft'])
        self.store.upsert_wedof_summary(normalize_summary(contract(amount=5000)), 'Test')
        self.assertFalse(billing_view(self.store.record('w-1'))['cards'][0]['can_draft'])
        self.store.update_wedof_details('1', raw_fields({'cerfa': {'numeroInterne': 'AK-1'}}, summary))
        self.assertFalse(billing_view(self.store.record('w-1'))['cards'][0]['can_draft'])
        self.assertEqual(len(self.store.record('w-1')['schedules']), 1)

    def test_record_refresh_cannot_replace_the_financer_and_the_ui_keeps_its_name(self):
        summary = normalize_summary(contract(financer='opcoCfaEp'))
        self.store.upsert_wedof_summary(summary, 'Test', details=folder_fields(folder(), 'OPCO-1'))
        register_bts_workspace(self.legacy)
        client = self.legacy.app.test_client()
        with client.session_transaction() as state:
            state.update(admin_logged_in=True, admin_role='admin')
        with patch.dict(os.environ, {'WEDOF_API_KEY': 'test-key'}), patch('bts_workspace.WedofBtsClient', return_value=self.api):
            page = client.get('/admin/BTS/dossiers/w-1')
            self.assertIn('<strong>OPCO EP</strong>', page.text)
            self.assertIn('OPCO EP via WEDOF', page.text)
            self.assertNotIn('<strong>AKTO</strong>', page.text)
            self.assertIn('OPCO EP via WEDOF', client.get('/admin/BTS').text)
            with client.session_transaction() as state:
                token = state['bts_csrf_token']
            response = client.post('/admin/BTS/dossiers/w-1/actualiser', data={'bts_csrf_token': token})
            self.assertEqual(response.status_code, 302)
            self.api.folder.assert_not_called()
            self.api.raw.assert_not_called()
            self.assertEqual(self.store.record('w-1')['financer'], 'opcoCfaEp')

    def test_routes_are_manual_protected_and_old_bulk_routes_are_disabled(self):
        legacy_bulk = Mock(return_value='Unexpected bulk import')
        self.legacy.app.add_url_rule('/admin/BTS/akto/sync', 'admin_bts_akto_sync', lambda: legacy_bulk(), methods=['POST'])
        register_bts_workspace(self.legacy)
        client = self.legacy.app.test_client()
        with patch.dict(os.environ, {'WEDOF_API_KEY': 'test-key'}), patch('bts_workspace.WedofBtsClient', return_value=self.api) as factory:
            self.assertEqual(client.post('/admin/BTS/wedof/rechercher').status_code, 302)
            with client.session_transaction() as session:
                session.update(admin_logged_in=True, admin_role='admin')
            for path in ('/admin/BTS', '/admin/BTS/connexion', '/admin/BTS/ajouter-opco', '/admin/BTS/nouveau'):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('Synchroniser AKTO via WEDOF', response.text)
            self.assertEqual(client.get('/admin/BTS/ajouter-akto').location, '/admin/BTS/ajouter-opco')
            factory.assert_not_called()
            self.assertEqual(client.post('/admin/BTS/wedof/rechercher').status_code, 400)
            with client.session_transaction() as session:
                token = session['bts_csrf_token']
            data = {'bts_csrf_token': token, 'action': 'start', 'number': 'DECA-1'}
            for path in ('/admin/BTS/wedof/synchroniser', '/admin/BTS/synchroniser', '/admin/BTS/akto/sync'):
                self.assertEqual(client.post(path, data=data).status_code, 410)
            legacy_bulk.assert_not_called()
            factory.assert_not_called()
            response = client.post('/admin/BTS/wedof/rechercher', data=data, headers={'Accept': 'application/json'})
            result = response.json
            self.assertEqual(response.status_code, 200)
            client.post('/admin/BTS/wedof/rechercher', data={**data, 'action': 'continue', 'run_id': result['id'], 'revision': result['revision']})
            preview = client.get('/admin/BTS/ajouter-opco')
            self.assertIn('Ajouter ce dossier', preview.text)
            self.assertEqual(self.store.listing()['total'], 0)
            calls = self.api.contracts_page.call_count
            client.get('/admin/BTS/ajouter-opco')
            client.get('/admin/BTS')
            self.assertEqual(self.api.contracts_page.call_count, calls)
            self.assertEqual(self.store.listing()['total'], 0)
            for role in ('viewer', 'partner_admin'):
                with client.session_transaction() as session:
                    session['admin_role'] = role
                for path in ('/admin/BTS/wedof/rechercher', '/admin/BTS/wedof/ajouter'):
                    self.assertEqual(client.post(path, data=data).status_code, 403)


class RelayTests(unittest.TestCase):
    def test_known_opco_events_are_recognised_without_affecting_cpf(self):
        for payload in (folder(), {'financer': 'opcoCfaAkto'}, {'event': 'workingContract.updated'},
                        {'payload': {'type': 'opco', 'accessModality': 'apprentissage'}}):
            self.assertTrue(is_apprenticeship_event(payload))
        self.assertFalse(is_apprenticeship_event({'type': 'cpf'}))

    def test_apprenticeship_events_never_reach_commercial_relays(self):
        import app as legacy
        entry = {'payload': folder(), 'event': 'registrationFolder.created'}
        with patch.object(legacy.requests, 'post') as post:
            for send in (legacy._send_wedof_entry_to_crm, legacy._send_wedof_entry_to_salesforce):
                result, code = send(entry)
                self.assertEqual(code, 200)
                self.assertTrue(result['skipped'])
            post.assert_not_called()
        with patch.object(legacy, '_load_wedof_webhooks') as load, patch.object(legacy, '_fetch_wedof_folder_details') as fetch:
            response = legacy.app.test_client().post('/api/webhooks/wedof', json=folder())
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['reason'], 'apprenticeship_bts_only')
            load.assert_not_called()
            fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
